"""Tests for pr.inspect_local against real temporary git repositories.

No network, no mocks: each test builds a real repo with `git init` + commits so
merge-base and diff exercise real git plumbing.
"""

import subprocess

import pytest

from mcp_server import pr


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True,
                   capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    (r / "a.txt").write_text("base\n")
    (r / "drivers").mkdir()
    (r / "drivers" / "spi.c").write_text("orig\n")
    _git(r, "add", ".")
    _git(r, "commit", "-q", "-m", "base commit")
    return r


def test_inspect_local_diffs_branch_against_merge_base(repo):
    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "drivers" / "spi.c").write_text("orig\nnew line\n")
    (repo / "new.c").write_text("added\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "feature work")

    cs = pr.inspect_local(path=str(repo), base="main")

    assert cs.source.kind == "local"
    assert cs.base_ref == "main"
    assert cs.pr_number is None
    paths = set(cs.file_paths())
    assert paths == {"drivers/spi.c", "new.c"}
    statuses = {f.path: f.status for f in cs.files}
    assert statuses["drivers/spi.c"] == "modified"
    assert statuses["new.c"] == "added"
    # merge-base is the base commit; head is the feature commit; they differ.
    assert cs.merge_base_sha != cs.head_sha
    assert len(cs.commits) == 1
    assert "1 commit" in cs.human_summary or "commit" in cs.human_summary


def test_inspect_local_carries_hunk_snippets(repo):
    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "drivers" / "spi.c").write_text("orig\nAAA\n")
    _git(repo, "commit", "-aq", "-m", "edit")

    cs = pr.inspect_local(path=str(repo), base="main")
    spi = next(f for f in cs.files if f.path == "drivers/spi.c")
    assert any("AAA" in s for s in spi.hunk_snippets)


def test_inspect_local_auto_base_uses_default_branch(repo):
    # No explicit base: fall back to the repo's default branch (main).
    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "new.c").write_text("x\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "add")

    cs = pr.inspect_local(path=str(repo))
    assert "new.c" in cs.file_paths()


def test_inspect_local_unresolvable_base_raises(repo):
    with pytest.raises(ValueError, match="merge-base"):
        pr.inspect_local(path=str(repo), base="does-not-exist")
