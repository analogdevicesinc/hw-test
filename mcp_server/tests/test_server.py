"""In-process tests for the MCP server: tool/prompt registration + wiring."""

import pytest

from mcp_server import server as server_mod


@pytest.fixture
def mcp():
    return server_mod.build_server(metas=server_mod._TEST_METAS_FIXTURE)


@pytest.mark.anyio
async def test_registers_nine_tools(mcp):
    names = {t.name for t in await mcp.list_tools()}
    assert names == {
        "inspect_pr", "inspect_local", "get_classification_evidence",
        "submit_classification", "create_test_plan", "run_base_vs_pr",
        "submit_test", "list_datasheets", "render_pr_summary",
    }


@pytest.mark.anyio
async def test_registers_all_prompts(mcp):
    names = {p.name for p in await mcp.list_prompts()}
    assert names == {"classify-changes", "inspect-and-plan", "role-guide",
                     "base-vs-pr-run", "test-writer", "test-pr"}


def test_inspect_pr_tool_returns_jsonable_changeset():
    # The tool callable is directly invokable (decorator returns the function).
    fake = _fake_pr_changeset()
    out = server_mod._inspect_pr_impl(42, "analogdevicesinc/u-boot",
                                      runner=fake)
    assert out["pr_number"] == 42
    assert out["repo"].endswith("u-boot")
    assert out["files"]


def test_get_evidence_then_plan_roundtrip():
    cs = _fake_changeset_dict()
    ev = server_mod._get_evidence_impl(cs, metas=server_mod._TEST_METAS_FIXTURE)
    assert "subsystem_choices" in ev
    assert ev["matched_metas"] == ["adsp/u-boot"]

    classifications = [{
        "subsystem": "board_dt", "confidence": "high",
        "evidence_files": ["board/adi/sc598/x.c"], "source": "llm",
    }]
    validated = server_mod._submit_classification_impl(cs, classifications)
    assert validated[0]["subsystem"] == "board_dt"

    plan = server_mod._create_plan_impl(
        cs, classifications, board="sc598",
        metas=server_mod._TEST_METAS_FIXTURE)
    assert plan["coverage_gap"] == "reuse"
    assert plan["existing_test_matches"] == ["adsp/u-boot"]
    assert "board_dt" in plan["scope"]


def test_submit_classification_rejects_unbacked():
    cs = _fake_changeset_dict()
    with pytest.raises(ValueError, match="evidence"):
        server_mod._submit_classification_impl(cs, [{
            "subsystem": "board_dt", "confidence": "high",
            "evidence_files": ["not/in/changeset.c"], "source": "llm",
        }])


# ---- fixtures -------------------------------------------------------------

def _fake_changeset_dict():
    return {
        "source": {"repo": "analogdevicesinc/u-boot", "ref_or_sha": "head",
                   "kind": "pr"},
        "repo": "analogdevicesinc/u-boot", "head_sha": "head",
        "base_ref": "main", "merge_base_sha": "mb",
        "files": [{"path": "board/adi/sc598/x.c", "status": "modified",
                   "hunk_snippets": ["+x"]}],
        "commits": ["c1"], "human_summary": "", "pr_number": 7,
    }


def _fake_pr_changeset():
    # A runner stub for inspect_pr: maps gh api calls to canned JSON.
    import json

    def runner(argv, cwd=None):
        if argv[:2] == ["gh", "api"] and "pulls" in argv[2]:
            return json.dumps({
                "base": {"ref": "main"}, "head": {"sha": "headsha"},
                "number": 42,
            })
        if argv[:2] == ["gh", "api"] and "compare" in argv[2]:
            return json.dumps({
                "merge_base_commit": {"sha": "mbsha"},
                "files": [{"filename": "board/adi/sc598/x.c", "status": "modified",
                           "patch": "@@ -1 +1 @@\n+x"}],
                "commits": [{"sha": "c1", "commit": {"message": "m"}}],
            })
        raise AssertionError(f"unexpected argv {argv}")

    return runner


@pytest.mark.anyio
async def test_registers_run_base_vs_pr_tool_and_prompt(mcp):
    tool_names = {t.name for t in await mcp.list_tools()}
    assert "run_base_vs_pr" in tool_names
    prompt_names = {p.name for p in await mcp.list_prompts()}
    assert "base-vs-pr-run" in prompt_names


def test_run_base_vs_pr_impl_no_test_guard_is_jsonable():
    class _Prims:
        def reserve(self, needs):
            raise AssertionError("must not reserve on no-test guard")
    cs = _fake_changeset_dict()
    out = server_mod._run_base_vs_pr_impl(cs, "", ["sc598", "ezkit"], primitives=_Prims(),
                                          coverage_gap="new")
    assert out["result_label"] == "test-design-requires-user-input"
    assert out["base"] is None


def test_run_base_vs_pr_impl_regression_roundtrips():
    class _Prims:
        def __init__(self):
            self.released = []

        def reserve(self, needs):
            return "tok"

        def resolve_image(self, repo, sha, role):
            from mcp_server.models import ImageRef
            return ImageRef(repo=repo, sha=sha, role=role, source="artifact",
                            location=f"/a/{sha}")

        def run(self, test_name, token, image):
            return f"run-{image.sha}"

        def wait(self, run_id, ref):
            from mcp_server.models import ImageRef, RunOutcome
            state = "passed" if ref == "base" else "failed"
            img = ImageRef(repo="u-boot", sha=ref, role="u-boot",
                           source="artifact", location="/a")
            return RunOutcome(ref=ref, sha=ref, image=img, state=state,
                              returncode=0 if state == "passed" else 1,
                              log_tail=f"{ref}")

        def release(self, token):
            self.released.append(token)

    cs = _fake_changeset_dict()
    out = server_mod._run_base_vs_pr_impl(cs, "adsp/u-boot", ["sc598", "ezkit"],
                                          primitives=_Prims())
    assert out["transition"] == "pass->fail"
    assert out["regressed"] is True
    assert out["result_label"] == "validation-only"
    assert out["pr"]["state"] == "failed"


@pytest.mark.anyio
async def test_registers_submit_test_tool_and_prompt(mcp):
    tool_names = {t.name for t in await mcp.list_tools()}
    assert "submit_test" in tool_names
    prompt_names = {p.name for p in await mcp.list_prompts()}
    assert "test-writer" in prompt_names


def test_submit_test_impl_stages_and_is_jsonable(tmp_path):
    _GOOD = "import pytest\n\n\ndef test_x(context):\n    assert True\n"
    _CFG = 'needs = ["sc598", "ezkit"]\n'

    deps = {
        "collector": lambda d: (True, 1, "collected 1 item"),
        "tag_resolver": lambda needs: {"match": True, "places": ["sc598-a"]},
        "existing_names": set(),
        "staging_root": str(tmp_path),
    }
    cs = _fake_changeset_dict()
    out = server_mod._submit_test_impl(cs, "adsp/new", _GOOD, _CFG, None,
                                       authoring_deps=deps)
    assert out["result_label"] == "coverage-improvement"
    assert out["runnable_now"] is True
    assert out["validation"]["ok"] is True
    # JSON-able: nested dataclass became a dict
    assert isinstance(out["validation"], dict)


def test_submit_test_impl_rejects_bad_test(tmp_path):
    _BAD = "def test_x(context)\n    assert True\n"  # syntax error
    deps = {
        "collector": lambda d: (True, 1, "ok"),
        "tag_resolver": lambda needs: {"match": None, "places": []},
        "existing_names": set(),
        "staging_root": str(tmp_path),
    }
    out = server_mod._submit_test_impl(_fake_changeset_dict(), "adsp/new",
                                       _BAD, 'needs=["sc598"]\n', None,
                                       authoring_deps=deps)
    assert out["result_label"] == "test-design-requires-user-input"
    assert out["files"] == []


# ---- list_datasheets wiring ----------------------------------------------

def test_list_datasheets_impl_returns_path_and_raw_url():
    _PREFIX = "media/en/technical-documentation/data-sheets/"
    fake_tree = {
        "truncated": False,
        "tree": [{"path": _PREFIX + "adsp-sc598.md", "type": "blob"}],
    }
    out = server_mod._list_datasheets_impl(
        "sc598", tree_fetcher=lambda: fake_tree)
    assert out["docs"][0]["path"] == _PREFIX + "adsp-sc598.md"
    assert out["docs"][0]["raw_url"].startswith(
        "https://raw.githubusercontent.com/analogdevicesinc/doctools/docling/")
    assert "note" not in out or out["note"] == ""


def test_list_datasheets_impl_notes_when_no_match():
    fake_tree = {"truncated": False, "tree": []}
    out = server_mod._list_datasheets_impl(
        "sc598", tree_fetcher=lambda: fake_tree)
    assert out["docs"] == []
    assert out["note"]


def test_list_datasheets_impl_graceful_on_fetch_error():
    def boom():
        raise RuntimeError("gh api exploded")
    out = server_mod._list_datasheets_impl("sc598", tree_fetcher=boom)
    assert out["docs"] == []
    assert "unavailable" in out["note"].lower()


@pytest.mark.anyio
async def test_registers_list_datasheets_tool(mcp):
    names = {t.name for t in await mcp.list_tools()}
    assert "list_datasheets" in names


# ---- render_pr_summary wiring --------------------------------------------

def test_render_pr_summary_impl_returns_markdown():
    report = {
        "changeset_ref": "analogdevicesinc/u-boot@abc",
        "test_name": "adsp/u-boot", "board": "sc598+ezkit",
        "base": {"state": "passed"}, "pr": {"state": "passed"},
        "transition": "pass->pass", "regressed": False,
        "result_label": "validation-only", "evidence": ["+ new"],
        "human_summary": "base passed, PR passed.", "test_description": "",
    }
    out = server_mod._render_pr_summary_impl(report)
    assert "markdown" in out
    assert "PASS" in out["markdown"]
    assert "adsp/u-boot" in out["markdown"]


@pytest.mark.anyio
async def test_registers_render_pr_summary_tool(mcp):
    names = {t.name for t in await mcp.list_tools()}
    assert "render_pr_summary" in names
