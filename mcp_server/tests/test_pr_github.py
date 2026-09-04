"""Tests for pr.inspect_pr with an injected gh runner (no network)."""

import json

import pytest

from mcp_server import pr


def make_runner(pr_json, compare_json):
    """Return a runner that answers the two gh api calls inspect_pr makes."""
    calls = []

    def runner(argv, cwd):
        calls.append(argv)
        joined = " ".join(argv)
        assert argv[0] == "gh"
        if "/pulls/" in joined:
            return json.dumps(pr_json)
        if "/compare/" in joined:
            return json.dumps(compare_json)
        raise AssertionError(f"unexpected gh call: {joined}")

    runner.calls = calls
    return runner


PR_JSON = {
    "number": 107,
    "base": {"ref": "adi-u-boot-2025.10.y"},
    "head": {"sha": "headsha", "ref": "feature",
             "repo": {"full_name": "analogdevicesinc/u-boot"}},
}

COMPARE_JSON = {
    "merge_base_commit": {"sha": "mergebasesha"},
    "status": "ahead",
    "files": [
        {"filename": "drivers/spi/adi_spi3.c", "status": "modified",
         "patch": "@@ -1,2 +1,3 @@\n ctx\n+new spi line\n"},
        {"filename": "board/adi/sc598/x.c", "status": "added",
         "patch": "@@ -0,0 +1 @@\n+added\n"},
    ],
    "commits": [{"sha": "c1"}, {"sha": "c2"}],
}


def test_inspect_pr_builds_changeset_from_compare():
    runner = make_runner(PR_JSON, COMPARE_JSON)
    cs = pr.inspect_pr(pr=107, repo="analogdevicesinc/u-boot", runner=runner)

    assert cs.source.kind == "pr"
    assert cs.pr_number == 107
    assert cs.repo == "analogdevicesinc/u-boot"
    assert cs.base_ref == "adi-u-boot-2025.10.y"
    assert cs.head_sha == "headsha"
    assert cs.merge_base_sha == "mergebasesha"
    assert set(cs.file_paths()) == {"drivers/spi/adi_spi3.c",
                                    "board/adi/sc598/x.c"}
    assert cs.commits == ["c1", "c2"]


def test_inspect_pr_extracts_hunk_snippets_from_patch():
    runner = make_runner(PR_JSON, COMPARE_JSON)
    cs = pr.inspect_pr(pr=107, repo="analogdevicesinc/u-boot", runner=runner)
    spi = next(f for f in cs.files if f.path == "drivers/spi/adi_spi3.c")
    assert any("new spi line" in s for s in spi.hunk_snippets)


def test_inspect_pr_requires_repo():
    runner = make_runner(PR_JSON, COMPARE_JSON)
    with pytest.raises(ValueError, match="repo"):
        pr.inspect_pr(pr=107, repo=None, runner=runner)


def test_inspect_pr_diverged_base_still_resolves_merge_base():
    diverged = {**COMPARE_JSON, "status": "diverged"}
    runner = make_runner(PR_JSON, diverged)
    cs = pr.inspect_pr(pr=107, repo="analogdevicesinc/u-boot", runner=runner)
    assert cs.merge_base_sha == "mergebasesha"


def test_inspect_pr_missing_merge_base_raises():
    broken = {**COMPARE_JSON}
    broken = {k: v for k, v in broken.items() if k != "merge_base_commit"}
    runner = make_runner(PR_JSON, broken)
    with pytest.raises(ValueError, match="merge.base"):
        pr.inspect_pr(pr=107, repo="analogdevicesinc/u-boot", runner=runner)
