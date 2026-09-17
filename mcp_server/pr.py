"""Resolve a PR or local branch into a normalized ChangeSet.

Two entry points share the ChangeSet shape:

- ``inspect_local`` — pure local git: current branch vs its merge-base with a
  base ref. No network.
- ``inspect_pr`` — GitHub via the ``gh`` CLI (added in the next task); a single
  ``compare`` call yields merge-base, files, and commits.

Both take an injectable command runner so tests never touch the network. The
runner is ``(argv, cwd) -> stdout``; the default runs the real subprocess.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

from mcp_server.models import ChangeSet, FileChange, SourceRef

Runner = Callable[[list[str], str | None], str]

# Max diff lines kept per file in FileChange.hunk_snippets. Enough for the
# classifier to see what changed without shipping whole files across the wire.
_MAX_HUNK_LINES = 40

_STATUS_MAP = {
    "M": "modified", "A": "added", "D": "removed",
    "R": "renamed", "C": "copied", "T": "typechange",
}


def _default_runner(argv: list[str], cwd: str | None) -> str:
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(argv)}\n"
            f"{result.stderr.strip()}"
        )
    return result.stdout


def _git(runner: Runner, cwd: str, *args: str) -> str:
    return runner(["git", *args], cwd)


def _resolve_base(runner: Runner, cwd: str, base: str | None) -> str:
    """Pick the base ref to diff against: explicit, else the default branch."""
    if base:
        return base
    # origin/HEAD points at the remote default branch when a remote exists.
    for ref in ("refs/remotes/origin/HEAD", "main", "master"):
        try:
            out = _git(runner, cwd, "rev-parse", "--abbrev-ref", ref).strip()
            if out:
                return out.replace("origin/", "")
        except RuntimeError:
            continue
    raise ValueError("cannot resolve a base branch; pass base= explicitly")


def _parse_name_status(text: str) -> list[tuple[str, str]]:
    """Parse `git diff --name-status` into [(status, path), ...]."""
    entries = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        code = parts[0]
        # Rename/copy: "R100\told\tnew" — report the new path.
        path = parts[-1]
        status = _STATUS_MAP.get(code[0], code[0])
        entries.append((status, path))
    return entries


def _hunk_snippets(diff_text: str) -> list[str]:
    """Keep the meaningful diff lines (hunk headers + +/- content), capped."""
    snippets = []
    for line in diff_text.splitlines():
        if line.startswith(("diff --git", "index ", "--- ", "+++ ",
                            "new file", "deleted file", "similarity ",
                            "rename ", "old mode", "new mode")):
            continue
        if line.startswith(("@@", "+", "-")):
            snippets.append(line)
        if len(snippets) >= _MAX_HUNK_LINES:
            snippets.append("... (truncated)")
            break
    return snippets


def _build_file_changes(runner: Runner, cwd: str, base_sha: str, head: str,
                        entries: list[tuple[str, str]]) -> list[FileChange]:
    files = []
    for status, path in entries:
        diff_text = _git(runner, cwd, "diff", f"{base_sha}..{head}", "--", path)
        files.append(FileChange(path=path, status=status,
                                hunk_snippets=_hunk_snippets(diff_text)))
    return files


def _summarize(repo: str, files: list[FileChange], commits: list[str]) -> str:
    nf, nc = len(files), len(commits)
    return (f"{repo}: {nf} file{'s' if nf != 1 else ''} changed across "
            f"{nc} commit{'s' if nc != 1 else ''}")


def inspect_local(path: str | None = None, base: str | None = None,
                  runner: Runner = _default_runner) -> ChangeSet:
    """Inspect the current local branch against its merge-base with ``base``."""
    cwd = str(Path(path).expanduser().resolve()) if path else str(Path.cwd())

    base_ref = _resolve_base(runner, cwd, base)
    head_sha = _git(runner, cwd, "rev-parse", "HEAD").strip()

    try:
        merge_base = _git(runner, cwd, "merge-base", base_ref, "HEAD").strip()
    except RuntimeError as exc:
        raise ValueError(
            f"cannot compute merge-base of {base_ref!r} and HEAD: {exc}"
        ) from exc

    name_status = _git(runner, cwd, "diff", "--name-status",
                       f"{merge_base}..HEAD")
    entries = _parse_name_status(name_status)
    files = _build_file_changes(runner, cwd, merge_base, "HEAD", entries)

    commits = [c for c in _git(runner, cwd, "rev-list",
                               f"{merge_base}..HEAD").splitlines() if c.strip()]

    repo = Path(cwd).name
    return ChangeSet(
        source=SourceRef(repo=repo, ref_or_sha=head_sha, kind="local"),
        repo=repo, head_sha=head_sha, base_ref=base_ref,
        merge_base_sha=merge_base, files=files, commits=commits,
        human_summary=_summarize(repo, files, commits), pr_number=None,
    )


def _gh_json(runner: Runner, endpoint: str) -> dict:
    """Call `gh api <endpoint>` and parse the JSON response."""
    out = runner(["gh", "api", endpoint], None)
    return json.loads(out)


def _files_from_compare(compare: dict) -> list[FileChange]:
    files = []
    for entry in compare.get("files", []):
        # gh's compare `patch` is already merge-base-relative; reuse the same
        # snippet extractor the local path uses.
        patch = entry.get("patch", "") or ""
        files.append(FileChange(
            path=entry["filename"],
            status=entry.get("status", "modified"),
            hunk_snippets=_hunk_snippets(patch),
        ))
    return files


def inspect_pr(pr: int, repo: str | None = None,
               runner: Runner = _default_runner) -> ChangeSet:
    """Inspect a GitHub PR into a ChangeSet via a single `gh api compare` call.

    ``repo`` is ``owner/name`` (e.g. ``analogdevicesinc/u-boot``). The compare
    endpoint returns the merge-base commit, merge-base-relative file patches,
    and the PR commits together, so no worktree is needed.
    """
    if not repo:
        raise ValueError("repo is required (owner/name), e.g. analogdevicesinc/u-boot")

    pr_meta = _gh_json(runner, f"repos/{repo}/pulls/{pr}")
    base_ref = pr_meta["base"]["ref"]
    head_sha = pr_meta["head"]["sha"]

    compare = _gh_json(runner, f"repos/{repo}/compare/{base_ref}...{head_sha}")
    merge_base_commit = compare.get("merge_base_commit")
    if not merge_base_commit or not merge_base_commit.get("sha"):
        raise ValueError(
            f"no merge-base for {repo}#{pr}; base {base_ref!r} and head may "
            f"have diverged unrecoverably or the ref is missing"
        )
    merge_base = merge_base_commit["sha"]

    files = _files_from_compare(compare)
    commits = [c["sha"] for c in compare.get("commits", []) if c.get("sha")]

    return ChangeSet(
        source=SourceRef(repo=repo, ref_or_sha=head_sha, kind="pr"),
        repo=repo, head_sha=head_sha, base_ref=base_ref,
        merge_base_sha=merge_base, files=files, commits=commits,
        human_summary=_summarize(f"{repo}#{pr}", files, commits),
        pr_number=pr,
    )
