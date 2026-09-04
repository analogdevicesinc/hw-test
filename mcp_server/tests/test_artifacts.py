"""Tests for CI workflow-run resolution for a commit (no network)."""

from mcp_server import artifacts


def _gh(runs, artifacts_by_run):
    """Fake gh(endpoint)->dict: canned runs list + per-run artifacts."""
    def gh(endpoint):
        if "/actions/runs?" in endpoint or endpoint.endswith("/actions/runs"):
            return {"workflow_runs": runs}
        if endpoint.endswith("/artifacts"):
            run_id = int(endpoint.rsplit("/", 2)[-2])
            arts = artifacts_by_run.get(run_id, [])
            return {"total_count": len(arts), "artifacts": arts}
        raise AssertionError(f"unexpected endpoint {endpoint}")
    return gh


def test_resolves_newest_run_with_artifacts():
    runs = [
        {"id": 100, "head_sha": "abc", "status": "completed",
         "conclusion": "success", "created_at": "2026-09-01T00:00:00Z"},
        {"id": 200, "head_sha": "abc", "status": "completed",
         "conclusion": "success", "created_at": "2026-09-02T00:00:00Z"},
    ]
    arts = {
        100: [{"name": "sc598_defconfig", "expired": False}],
        200: [{"name": "sc598_defconfig", "expired": False}],
    }
    url = artifacts.resolve_workflow_run("analogdevicesinc/u-boot", "abc",
                                         gh=_gh(runs, arts))
    # newest run (200) wins
    assert url == ("https://api.github.com/repos/analogdevicesinc/u-boot/"
                   "actions/runs/200")


def test_skips_runs_without_live_artifacts():
    runs = [
        {"id": 300, "head_sha": "def", "status": "completed",
         "conclusion": "success", "created_at": "2026-09-02T00:00:00Z"},
        {"id": 400, "head_sha": "def", "status": "completed",
         "conclusion": "success", "created_at": "2026-09-01T00:00:00Z"},
    ]
    arts = {
        300: [{"name": "x", "expired": True}],   # expired -> not usable
        400: [{"name": "sc598_defconfig", "expired": False}],
    }
    url = artifacts.resolve_workflow_run("analogdevicesinc/u-boot", "def",
                                         gh=_gh(runs, arts))
    assert url.endswith("/actions/runs/400")


def test_returns_none_when_no_run_has_artifacts():
    runs = [{"id": 500, "head_sha": "ghi", "status": "completed",
             "conclusion": "success", "created_at": "2026-09-01T00:00:00Z"}]
    arts = {500: []}
    url = artifacts.resolve_workflow_run("analogdevicesinc/u-boot", "ghi",
                                         gh=_gh(runs, arts))
    assert url is None
