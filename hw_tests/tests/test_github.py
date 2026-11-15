from unittest.mock import MagicMock, patch

from hw_tests.github import GitHub


def _gh():
    ctx = {
        "name": "adsp/u-boot",
        "workflow_run_url": "https://api.github.com/repos/analogdevicesinc/u-boot/actions/runs/31278064245",
    }
    return GitHub(ctx)


def test_owner_repository_from_context(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    gh = _gh()
    assert gh.owner_repository == "analogdevicesinc/u-boot"


def test_mask_escapes_workflow_command_data(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    GitHub.mask("coordinator%name\r\nnext")

    assert capsys.readouterr().out == "::add-mask::coordinator%25name%0D%0Anext\n"


def test_list_artifacts_filters_expired(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    gh = _gh()
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
    gh = _gh()
    assert gh.list_artifacts() == []


def test_list_artifacts_paginates_all_pages(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    gh = _gh()

    page1_artifacts = [
        {"name": f"artifact-{i}", "expired": False, "archive_download_url": f"u{i}"}
        for i in range(100)
    ]
    page2_artifacts = [
        {"name": f"artifact-{i}", "expired": False, "archive_download_url": f"u{i}"}
        for i in range(100, 150)
    ]

    resp1 = MagicMock()
    resp1.json.return_value = {"total_count": 150, "artifacts": page1_artifacts}
    resp1.raise_for_status.return_value = None

    resp2 = MagicMock()
    resp2.json.return_value = {"total_count": 150, "artifacts": page2_artifacts}
    resp2.raise_for_status.return_value = None

    with patch("hw_tests.github.requests.get", side_effect=[resp1, resp2]) as mock_get:
        names = [a["name"] for a in gh.list_artifacts()]

    assert len(names) == 150
    assert names == [f"artifact-{i}" for i in range(150)]
    assert mock_get.call_count == 2
    assert mock_get.call_args_list[0].kwargs["params"] == {"per_page": 100, "page": 1}
    assert mock_get.call_args_list[1].kwargs["params"] == {"per_page": 100, "page": 2}


def test_list_artifacts_single_page(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    gh = _gh()

    payload = {"total_count": 2, "artifacts": [
        {"name": "keep1", "expired": False, "archive_download_url": "u1"},
        {"name": "keep2", "expired": False, "archive_download_url": "u2"},
    ]}
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None

    with patch("hw_tests.github.requests.get", return_value=resp) as mock_get:
        names = [a["name"] for a in gh.list_artifacts()]

    assert names == ["keep1", "keep2"]
    assert mock_get.call_count == 1


def test_annotate_starts_on_a_new_line(monkeypatch, capsys):
    """Print the annotation on its own line, with escaped properties and message."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    GitHub.annotate("error", "line 1\nline 2", title="a: b, c", file="test.py", line=3)

    assert capsys.readouterr().out == (
        "\n::error file=test.py,line=3,title=a%3A b%2C c::line 1%0Aline 2\n"
    )


def test_annotate_redacts_lab_hosts(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    GitHub.annotate("error", "ssh: connect to host 10.1.2.3 via lab.ad.analog.com", title="in 10.1.2.3")

    out = capsys.readouterr().out
    assert out == "\n::error title=in <IP>::ssh: connect to host <IP> via <INTERNAL_HOST>\n"
