"""hw-test change-driven planning MCP server (inspect + classify + plan).

Thin tool layer over the modular helpers. No hardware is touched here — this
slice inspects a PR or local branch, gathers deterministic classification
evidence, validates LLM/cache classifications, and synthesizes an honest,
verdict-free test plan. Hardware execution is a separate slice.

Each tool has a plain ``_*_impl`` function (unit-testable, no MCP types) that
``build_server`` wraps with ``@mcp.tool()``. Tools cross a JSON boundary, so
inputs/outputs go through :mod:`mcp_server.serde`.

Roles are subagent-driven: the ``inspect-and-plan`` prompt orchestrates the
whole pass, while ``classify-changes`` and ``role-guide`` drive focused
sub-roles. The server never classifies; it validates what the classifier
submits.
"""

from __future__ import annotations

import logging

from mcp_server import authoring, compare, datasheets, planning, prompts, serde, summary
from mcp_server import pr as pr_mod

# Logs go to stderr only: stdout carries the JSON-RPC stream for the stdio
# transport, so anything printed there would corrupt the protocol. The client
# (e.g. Claude Code) surfaces stderr in its MCP debug output.
logger = logging.getLogger("hw_test_mcp")


def _configure_logging():
    """Send INFO+ to stderr. Level overridable via HW_TEST_MCP_LOG (e.g. DEBUG)."""
    import sys
    from os import environ

    level = getattr(logging, environ.get("HW_TEST_MCP_LOG", "INFO").upper(),
                    logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s hw-test-mcp %(levelname)s %(message)s", "%H:%M:%S"))
    root = logging.getLogger("hw_test_mcp")
    root.handlers[:] = [handler]
    root.setLevel(level)
    root.propagate = False

# Small in-repo fixture so tests exercise wiring without importing hw_tests.
_TEST_METAS_FIXTURE = [
    {
        "_uid": "adsp/u-boot",
        "needs": ["sc598", "ezkit"],
        "repository": [{"name": "u-boot",
                        "path": "board/adi/sc598*\nconfigs/sc598*\n"}],
        "capabilities": {"provides": ["uboot", "openocd", "spi_boot"]},
    },
]


# ---- tool implementations (pure, JSON in / JSON out) ----------------------

def _inspect_pr_impl(pr: int, repo: str, runner=pr_mod._default_runner) -> dict:
    changeset = pr_mod.inspect_pr(pr, repo=repo, runner=runner)
    return serde.to_jsonable(changeset)


def _inspect_local_impl(path: str | None = None, base: str | None = None,
                        runner=pr_mod._default_runner) -> dict:
    changeset = pr_mod.inspect_local(path=path, base=base, runner=runner)
    return serde.to_jsonable(changeset)


def _get_evidence_impl(changeset: dict, metas=None) -> dict:
    cs = serde.changeset_from_dict(changeset)
    ev = planning.get_classification_evidence(cs, metas=metas)
    return serde.to_jsonable(ev)


def _submit_classification_impl(changeset: dict, classifications: list) -> list:
    cs = serde.changeset_from_dict(changeset)
    validated = planning.validate_classifications(cs, classifications)
    return serde.to_jsonable(validated)


def _create_plan_impl(changeset: dict, classifications: list,
                      board: str | None = None, metas=None) -> dict:
    cs = serde.changeset_from_dict(changeset)
    validated = planning.validate_classifications(cs, classifications)
    evidence = planning.get_classification_evidence(cs, metas=metas)
    plan = planning.create_test_plan(cs, validated, evidence, metas=metas,
                                     board=board)
    return serde.to_jsonable(plan)


def _test_docstring(test_name: str) -> str:
    """Read the test function's docstring from tests/<name>/test.py via AST —
    no import or exec, so reading it is side-effect-free and safe.
    """
    import ast
    from pathlib import Path

    path = Path("tests") / test_name / "test.py"
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError):
        return ""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node)
            if doc and node.name.startswith("test"):
                return doc
    return ast.get_docstring(tree) or ""


def _run_base_vs_pr_impl(changeset: dict, test_name: str, needs: list,
                         primitives, coverage_gap: str = "reuse",
                         mode: str = "base-vs-pr") -> dict:
    logger.info("run_base_vs_pr test=%s needs=%s mode=%s gap=%s",
                test_name, needs, mode, coverage_gap)
    report = compare.run_base_vs_pr(
        changeset, test_name, needs, primitives=primitives,
        coverage_gap=coverage_gap, mode=mode, test_describer=_test_docstring)
    logger.info("run_base_vs_pr result=%s summary=%s",
                report.result_label, report.human_summary)
    return serde.to_jsonable(report)


def _submit_test_impl(changeset: dict, name: str, test_py: str,
                      config_toml: str, plan: dict | None,
                      authoring_deps: dict) -> dict:
    staged = authoring.submit_test(
        changeset, name, test_py, config_toml, plan,
        existing_names=authoring_deps["existing_names"],
        collector=authoring_deps["collector"],
        tag_resolver=authoring_deps["tag_resolver"],
        staging_root=authoring_deps["staging_root"],
        collect_root=authoring_deps.get("collect_root"))
    return serde.to_jsonable(staged)


def _default_tree_fetcher():
    """Fetch the doctools docling branch git-tree via ``gh api`` (recursive).

    Returns the parsed git-tree dict. Runs the GitHub CLI so it reuses the
    operator's auth; any failure raises and the caller degrades gracefully.
    """
    import json
    import subprocess

    proc = subprocess.run(
        ["gh", "api",
         "repos/analogdevicesinc/doctools/git/trees/docling?recursive=1"],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"gh api git/trees failed: {proc.stderr.strip()}")
    tree = json.loads(proc.stdout)
    if tree.get("truncated"):
        logger.warning("doctools docling git-tree was truncated; "
                       "datasheet list may be incomplete")
    return tree


def _list_datasheets_impl(query: str, tree_fetcher=None) -> dict:
    """List doctools datasheet md pointers matching ``query``.

    Doc lookup is auxiliary context for test authoring, never a gate: every
    failure (no gh, API error, no match) degrades to an empty list plus a
    human ``note`` so the caller proceeds without a datasheet.
    """
    fetch = tree_fetcher or _default_tree_fetcher
    try:
        docs = datasheets.list_docs(query, tree_fetcher=fetch)
    except Exception as exc:
        logger.info("list_datasheets unavailable: %s", exc)
        return {"docs": [], "note": "datasheet index unavailable; "
                                    "author without it"}
    if not docs:
        return {"docs": [], "note": "no datasheet matched; author without it"}
    return {"docs": docs, "note": ""}


def _render_pr_summary_impl(report: dict) -> dict:
    """Render a CompareReport dict into PR-ready markdown (pure, no I/O)."""
    return {"markdown": summary.render(report)}


# ---- server assembly ------------------------------------------------------

def build_server(metas=None, primitives=None, authoring_deps=None):
    """Build and return the configured MCPServer (tools + prompts registered).

    ``metas`` overrides test-meta loading for tests; production passes None so
    the real ``hw_tests.collect.load_test_metas`` is used. ``primitives``
    injects a fake for the base-vs-PR tool in tests; production wiring is built
    lazily inside the tool call so a server that never runs hardware never
    imports the hardware modules. ``authoring_deps`` injects the test-writer
    collector/tag_resolver/staging_root for tests; production is built lazily.
    """
    from mcp.server.mcpserver import MCPServer

    mcp = MCPServer("hw-test-plan")

    @mcp.tool(name="inspect_pr")
    def inspect_pr(pr: int, repo: str) -> dict:
        """Inspect a GitHub PR into a ChangeSet (merge-base, files, hunks)."""
        return _inspect_pr_impl(pr, repo)

    @mcp.tool(name="inspect_local")
    def inspect_local(path: str | None = None, base: str | None = None) -> dict:
        """Inspect a local branch/worktree into a ChangeSet against its base."""
        return _inspect_local_impl(path=path, base=base)

    @mcp.tool(name="get_classification_evidence")
    def get_classification_evidence(changeset: dict) -> dict:
        """Gather deterministic evidence (files, matched metas, enum, docs)."""
        return _get_evidence_impl(changeset, metas=metas)

    @mcp.tool(name="submit_classification")
    def submit_classification(changeset: dict, classifications: list) -> list:
        """Validate classifications against the Subsystem enum and ChangeSet.

        Pass `changeset` = the inspect_pr / inspect_local result unchanged (do
        not drop fields or rebuild a partial object). Each classification is an
        object with ALL of these keys, or the whole call is rejected:
          - subsystem: one value from get_classification_evidence's
            subsystem_choices
          - confidence: "high" | "medium" | "low" | "none"
          - source: "llm" | "cache"
          - evidence_files: >=1 path, each one exactly as it appears in the
            changeset's files
          - rationale: short, grounded in the hunks
        The server reports every problem across every entry in one error, so
        fix them all in a single resubmit rather than one field at a time.
        """
        return _submit_classification_impl(changeset, classifications)

    @mcp.tool(name="create_test_plan")
    def create_test_plan(changeset: dict, classifications: list,
                         board: str | None = None) -> dict:
        """Synthesize an honest, verdict-free test plan from classifications."""
        return _create_plan_impl(changeset, classifications, board=board,
                                 metas=metas)

    @mcp.tool(name="run_base_vs_pr")
    def run_base_vs_pr(changeset: dict, test_name: str,
                       needs: list[str],
                       coverage_gap: str = "reuse",
                       mode: str = "base-vs-pr") -> dict:
        """Run the matched test on hardware and report the honest outcome.

        needs is the list of labgrid tags the board must carry, e.g.
        ["sc598", "ezkit"] — every tag must match. Pass them as separate list
        items, never one combined string.

        mode="base-vs-pr" runs at merge-base and PR head and reports the state
        delta; mode="head-only" runs just the PR head (use when the base commit
        has no usable CI artifacts).
        """
        prims = primitives if primitives is not None else build_primitives()
        return _run_base_vs_pr_impl(changeset, test_name, needs, prims,
                                    coverage_gap=coverage_gap, mode=mode)

    @mcp.tool(name="submit_test")
    def submit_test(changeset: dict, name: str, test_py: str,
                    config_toml: str, plan: dict | None = None) -> dict:
        """Validate an authored test and stage it for human review."""
        deps = (authoring_deps if authoring_deps is not None
                else build_authoring_deps())
        return _submit_test_impl(changeset, name, test_py, config_toml, plan,
                                 authoring_deps=deps)

    @mcp.tool(name="list_datasheets")
    def list_datasheets(query: str) -> dict:
        """List ADI datasheet/HRM markdown docs matching a query.

        query is whitespace-separated terms (e.g. "sc598 uart"); a doc matches
        when ANY term appears in its path. Returns {"docs": [{"path",
        "raw_url"}], "note"}. The docs come from the doctools docling branch
        (PDF datasheets + hardware reference manuals converted to markdown).

        This tool returns POINTERS only — it never fetches content. Pick the
        most relevant doc, then WebFetch its raw_url with a targeted question
        (e.g. register offset, reset value) to ground a test in hardware truth.
        Doc lookup is optional context: an empty list with a note means author
        the test without it, not that anything failed.
        """
        return _list_datasheets_impl(query)

    @mcp.tool(name="render_pr_summary")
    def render_pr_summary(report: dict) -> dict:
        """Render a base-vs-PR run report into PR-ready markdown.

        Pass the dict returned by run_base_vs_pr unchanged. Returns
        {"markdown": ...} — a self-contained summary (verdict, board,
        transition, what ran, evidence, disclaimer) to paste into a PR
        comment. This tool only formats; it posts nothing and makes no claim
        beyond the report's observed state delta.
        """
        return _render_pr_summary_impl(report)

    @mcp.prompt(name="classify-changes")
    def classify_changes() -> str:
        """Drive the classifier role: evidence in, validated subsystems out."""
        return prompts.classify_changes()

    @mcp.prompt(name="inspect-and-plan")
    def inspect_and_plan() -> str:
        """Drive the full inspect -> classify -> plan pass."""
        return prompts.inspect_and_plan()

    @mcp.prompt(name="role-guide")
    def role_guide(role: str) -> str:
        """One-paragraph guide for a named sub-role (inspector/classifier/planner)."""
        return prompts.role_guide(role)

    @mcp.prompt(name="base-vs-pr-run")
    def base_vs_pr_run() -> str:
        """Drive the hw-runner role: run the matched test base-vs-PR."""
        return prompts.base_vs_pr_run()

    @mcp.prompt(name="test-writer")
    def test_writer() -> str:
        """Drive the test-writer role: author a test for a coverage gap."""
        return prompts.test_writer()

    @mcp.prompt(name="test-pr")
    def test_pr() -> str:
        """Drive 'test this PR' with approval gates before authoring + running."""
        return prompts.test_pr()

    return mcp


def build_authoring_deps():
    """Bind the test-writer collector/tag_resolver/staging to real backends.

    Imported lazily so tests that inject fakes never import hardware or spawn
    subprocesses. The collector runs ``pytest --collect-only`` (never runs the
    test). The tag_resolver scans live labgrid place tags with the same logic
    as the reservation primitive and is graceful when no coordinator is set:
    it returns ``match=None`` rather than raising, so authoring still stages.
    """
    import subprocess
    import sys
    from os import environ

    from hw_tests.collect import load_test_metas

    def collector(test_dir):
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", test_dir],
            capture_output=True, text=True)
        log = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, 0, log[-4000:]

    def tag_resolver(needs):
        coordinator = environ.get("LG_COORDINATOR")
        if not coordinator:
            return {"match": None, "places": []}
        try:
            from labgrid.remote.client import start_session

            from mcp_server.orchestration.reservation import matching_places
            # matching_places always stops+closes the discovery session; a
            # leaked pump task would poison labgrid's stashed loop and make the
            # next reserve fail with "Could not connect to coordinator".
            places = matching_places(
                needs, session_factory=lambda: start_session(coordinator))
            return {"match": bool(places), "places": places}
        except Exception:
            # labgrid is a convenience here, never a gate.
            return {"match": None, "places": []}

    existing_names = {m.get("_uid") for m in load_test_metas()}
    return {
        "collector": collector,
        "tag_resolver": tag_resolver,
        "existing_names": existing_names,
        "staging_root": "tests/_staged",
        # Collect inside the repo tests tree so the root conftest, pyproject
        # markers, and the ``context`` fixture apply during --collect-only.
        "collect_root": "tests",
    }


def build_primitives():
    """Bind the compare Primitives interface to the real orchestration backends.

    Imported lazily so tests that inject a fake never import hardware modules.
    """
    import json
    import subprocess
    import time
    from os import environ
    from time import monotonic

    from labgrid.remote.client import start_session

    from mcp_server.orchestration import execution, imaging, reservation
    from mcp_server import artifacts
    from mcp_server.models import ImageRef, RunOutcome

    def _gh(endpoint):
        proc = subprocess.run(["gh", "api", endpoint],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            raise imaging.BuildError(
                f"gh api {endpoint} failed", log_tail=proc.stderr.strip())
        return json.loads(proc.stdout)

    def _github_token():
        # The test lists/downloads artifacts with GITHUB_TOKEN. Prefer an
        # explicit env token (set in the mcpServers env), else borrow the gh
        # CLI's token so the operator need not paste one.
        token = environ.get("GITHUB_TOKEN")
        if token:
            return token
        proc = subprocess.run(["gh", "auth", "token"],
                              capture_output=True, text=True)
        return proc.stdout.strip() if proc.returncode == 0 else ""

    class _Primitives:
        def reserve(self, needs):
            coordinator = environ["LG_COORDINATOR"]
            logger.info("reserve: matching needs=%s on %s", needs, coordinator)
            res = reservation.reserve(
                needs, session_factory=lambda: start_session(coordinator),
                clock=monotonic)
            logger.info("reserve: acquired place=%s token=%s",
                        res.place, res.token[:8])
            return res.token

        def resolve_image(self, repo, sha, role):
            def resolver(repo, sha, role):
                # The image lives in the CI run's artifacts; the test fetches
                # them from this run URL. A miss -> imaging raises BuildError.
                return artifacts.resolve_workflow_run(repo, sha, gh=_gh)

            def builder(repo, sha, role):
                raise imaging.BuildError(
                    f"no CI run with artifacts for {repo}@{sha}",
                    log_tail="no completed workflow run published artifacts "
                             "for this commit")

            return imaging.resolve_image_for_ref(
                repo, sha, role, resolver=resolver, builder=builder)

        def run(self, test_name, token, image):
            entry = reservation.get(token, clock=monotonic)
            gh_token = _github_token()
            logger.info("run: test=%s place=%s image=%s",
                        test_name, entry.place, image.location)
            return execution.run(
                test_name, entry.place, image.location,
                overrides={"workflow_run_url": image.location},
                env={"GITHUB_TOKEN": gh_token} if gh_token else None)

        def wait(self, run_id, ref):
            while execution.status(run_id)["state"] == "running":
                time.sleep(2)
            res = execution.result(run_id)
            logger.info("wait: ref=%s state=%s rc=%s",
                        ref, res["state"], res.get("returncode"))
            return RunOutcome(
                ref=ref, sha=ref,
                image=ImageRef(repo="", sha=ref, role="", source="artifact",
                               location=""),
                state=res["state"], returncode=res.get("returncode"),
                log_tail=execution.logs(run_id, tail=200))

        def release(self, token):
            logger.info("release: token=%s", token[:8])
            reservation.release(token)

    return _Primitives()


def main() -> None:
    _configure_logging()
    logger.info("hw-test MCP server starting (stdio)")
    build_server().run("stdio")


if __name__ == "__main__":
    main()
