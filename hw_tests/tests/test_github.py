from unittest.mock import MagicMock, patch

from hw_tests.github import GitHub


def _gh(monkeypatch_env):
    ctx = {
        "name": "adsp/u-boot",
        "workflow_run_url": "https://api.github.com/repos/analogdevicesinc/u-boot/actions/runs/31278064245",
    }
    return GitHub(ctx)


def test_owner_repository_from_context(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    gh = _gh(monkeypatch)
    assert gh.owner_repository == "analogdevicesinc/u-boot"


def test_list_artifacts_filters_expired(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    gh = _gh(monkeypatch)
    payload = {"artifacts": [
        {"name": "keep", "expired": False, "archive_download_url": "u1"},
        {"name": "gone", "expired": True, "archive_download_url": "u2"},
    ]}
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    with patch("hw_tests.github.requests.get", return_value=resp):
        names = [a["name"] for a in gh.list_artifacts()]
    assert names == ["keep"]


def test_list_artifacts_no_token_returns_empty(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    gh = _gh(monkeypatch)
    assert gh.list_artifacts() == []
