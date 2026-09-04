"""Tests for the test-writer authoring module (no hardware, no network)."""

import json
from pathlib import Path

import pytest

from mcp_server import authoring
from mcp_server.models import StagedTest


# ---- fakes ----------------------------------------------------------------

def _collector_ok(items=1, log="collected 1 item"):
    def collector(test_dir):
        return True, items, log
    return collector


def _collector_fail(log="ImportError: no module"):
    def collector(test_dir):
        return False, 0, log
    return collector


def _tag_resolver(match=True, places=None):
    def resolver(needs):
        return {"match": match, "places": places or ["sc598-a"]}
    return resolver


def _tag_resolver_no_coord():
    def resolver(needs):
        return {"match": None, "places": []}
    return resolver


_GOOD_TEST = "import pytest\n\n\ndef test_thing(context):\n    assert True\n"
_BAD_TEST = "def test_thing(context)\n    assert True\n"  # syntax error
_CONFIG = 'needs = ["sc598", "ezkit"]\n'


def _plan():
    return {
        "changeset_ref": "u-boot@h (PR #7)",
        "classifications": [],
        "scope": "board_dt",
        "candidate_capabilities": [],
        "existing_test_matches": [],
        "coverage_gap": "new",
        "doc_refs": [{"repo": "documentation", "query": "sc598 boot"}],
        "expected_base_vs_pr": "",
        "board_requirements": ["sc598", "ezkit"],
        "result_label_if_no_hw": "test-design-requires-user-input",
        "human_summary": "",
    }


def _cs():
    return {
        "source": {"repo": "u-boot", "ref_or_sha": "h", "kind": "pr"},
        "repo": "u-boot", "head_sha": "prsha", "base_ref": "main",
        "merge_base_sha": "basesha",
        "files": [{"path": "board/adi/sc598/x.c", "status": "modified"}],
        "commits": ["c1"], "human_summary": "", "pr_number": 7,
    }


# ---- validate_test --------------------------------------------------------

def test_validate_rejects_syntax_error():
    v = authoring.validate_test("adsp/new", _BAD_TEST, _CONFIG,
                                existing_names=set(),
                                collector=_collector_ok(),
                                tag_resolver=_tag_resolver())
    assert v.ok is False
    assert v.parsed is False
    assert any("syntax" in r.lower() or "parse" in r.lower() for r in v.reasons)


def test_validate_rejects_uncollectable():
    v = authoring.validate_test("adsp/new", _GOOD_TEST, _CONFIG,
                                existing_names=set(),
                                collector=_collector_fail("ImportError: x"),
                                tag_resolver=_tag_resolver())
    assert v.ok is False
    assert v.parsed is True
    assert v.collected is False
    assert any("ImportError" in r for r in v.reasons)


def test_validate_ok_with_tag_match():
    v = authoring.validate_test("adsp/new", _GOOD_TEST, _CONFIG,
                                existing_names=set(),
                                collector=_collector_ok(),
                                tag_resolver=_tag_resolver(match=True))
    assert v.ok is True
    assert v.tag_match is True
    assert v.tag_places == ["sc598-a"]
    assert v.reasons == []


def test_validate_graceful_when_no_coordinator():
    v = authoring.validate_test("adsp/new", _GOOD_TEST, _CONFIG,
                                existing_names=set(),
                                collector=_collector_ok(),
                                tag_resolver=_tag_resolver_no_coord())
    assert v.ok is True          # tag-resolve never blocks
    assert v.tag_match is None


def test_validate_collects_inside_collect_root(tmp_path):
    # The root conftest/markers/context fixture only apply when the temp
    # collection dir lives inside the repo tests tree, so honest tests that
    # import hw_tests and use the context fixture actually collect.
    seen = {}

    def recording_collector(test_dir):
        seen["dir"] = test_dir
        return True, 1, "collected 1 item"

    root = tmp_path / "tests" / "_staged"
    root.mkdir(parents=True)
    authoring.validate_test("adsp/new", _GOOD_TEST, _CONFIG,
                            existing_names=set(),
                            collector=recording_collector,
                            tag_resolver=_tag_resolver_no_coord(),
                            collect_root=str(root))
    assert seen["dir"].startswith(str(root))


# ---- submit_test (orchestration) ------------------------------------------

def test_submit_rejects_name_collision(tmp_path):
    st = authoring.submit_test(
        _cs(), "adsp/u-boot", _GOOD_TEST, _CONFIG, _plan(),
        existing_names={"adsp/u-boot"}, collector=_collector_ok(),
        tag_resolver=_tag_resolver(), staging_root=str(tmp_path))
    assert st.result_label == "test-design-requires-user-input"
    assert any("collide" in r.lower() for r in st.validation.reasons)
    assert st.files == []
    # nothing written
    assert list(tmp_path.iterdir()) == []


def test_submit_rejects_bad_test_without_staging(tmp_path):
    st = authoring.submit_test(
        _cs(), "adsp/new", _BAD_TEST, _CONFIG, _plan(),
        existing_names=set(), collector=_collector_ok(),
        tag_resolver=_tag_resolver(), staging_root=str(tmp_path))
    assert st.result_label == "test-design-requires-user-input"
    assert st.files == []
    assert list(tmp_path.iterdir()) == []


def test_submit_stages_valid_test(tmp_path):
    st = authoring.submit_test(
        _cs(), "adsp/new", _GOOD_TEST, _CONFIG, _plan(),
        existing_names=set(), collector=_collector_ok(),
        tag_resolver=_tag_resolver(match=True), staging_root=str(tmp_path))
    assert st.result_label == "coverage-improvement"
    assert st.runnable_now is True
    staged = Path(st.staged_dir)
    assert (staged / "test.py").read_text() == _GOOD_TEST
    assert (staged / "config.toml").read_text() == _CONFIG
    meta = json.loads((staged / "meta.json").read_text())
    assert meta["changeset_ref"].startswith("u-boot@")
    assert meta["subsystem"] == "board_dt"
    assert "test.py" in st.diff
    assert sorted(Path(p).name for p in st.files) == \
        ["config.toml", "meta.json", "test.py"]


def test_submit_stages_but_not_runnable_without_coordinator(tmp_path):
    st = authoring.submit_test(
        _cs(), "adsp/new", _GOOD_TEST, _CONFIG, _plan(),
        existing_names=set(), collector=_collector_ok(),
        tag_resolver=_tag_resolver_no_coord(), staging_root=str(tmp_path))
    assert st.result_label == "coverage-improvement"
    assert st.runnable_now is False
    assert Path(st.staged_dir, "test.py").is_file()
