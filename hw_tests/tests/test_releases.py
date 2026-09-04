from unittest.mock import MagicMock, patch

import pytest
import requests

from hw_tests.github import GitHub


def _gh(token="t", repo="analogdevicesinc/br2-external"):
    gh = GitHub.__new__(GitHub)  # bypass env-reading __init__
    gh._token = token
    gh._owner_repository = repo
    gh._run_id = None
    gh._test_name = "adsp/initramfs-boot"
    return gh


def test_list_release_assets_hits_tags_endpoint():
    gh = _gh()
    resp = MagicMock()
    resp.json.return_value = {
        "assets": [{"name": "images-initramfs-x.tar.xz", "url": "https://api/assets/1"}]
    }
    resp.raise_for_status.return_value = None
    with patch("hw_tests.github.requests.get", return_value=resp) as get:
        assets = gh.list_release_assets("2025.05-0.3.0")
    assert assets == [{"name": "images-initramfs-x.tar.xz", "url": "https://api/assets/1"}]
    assert get.call_args[0][0] == (
        "https://api.github.com/repos/analogdevicesinc/br2-external/"
        "releases/tags/2025.05-0.3.0"
    )


def test_list_release_assets_missing_tag_raises():
    gh = _gh()
    resp = MagicMock()
    resp.raise_for_status.side_effect = requests.HTTPError("404")
    with patch("hw_tests.github.requests.get", return_value=resp), pytest.raises(
        requests.HTTPError
    ):
        gh.list_release_assets("no-such-tag")


def test_download_release_asset_selects_and_extracts(tmp_path):
    gh = _gh()
    list_resp = MagicMock()
    list_resp.json.return_value = {
        "assets": [
            {"name": "images-bootstrap-x.tar.xz", "url": "https://api/assets/1"},
            {"name": "images-initramfs-x.tar.xz", "url": "https://api/assets/2"},
        ]
    }
    list_resp.raise_for_status.return_value = None

    dl_resp = MagicMock()
    dl_resp.raise_for_status.return_value = None
    dl_resp.iter_content.return_value = [b"payload"]

    def fake_get(url, headers=None, stream=False, params=None):
        if url.endswith("/releases/tags/2025.05-0.3.0"):
            return list_resp
        assert url == "https://api/assets/2"
        assert headers["Accept"] == "application/octet-stream"
        return dl_resp

    with patch("hw_tests.github.requests.get", side_effect=fake_get), patch(
        "hw_tests.github._extract_if_archive"
    ) as extract:
        out = gh.download_release_asset(
            "images-initramfs-x.tar.xz", "2025.05-0.3.0", path=tmp_path
        )
    assert out == tmp_path
    assert (tmp_path / "images-initramfs-x.tar.xz").read_bytes() == b"payload"
    extract.assert_called_once()


def test_download_release_asset_missing_raises(tmp_path):
    gh = _gh()
    list_resp = MagicMock()
    list_resp.json.return_value = {
        "assets": [{"name": "images-bootstrap-x.tar.xz", "url": "https://api/assets/1"}]
    }
    list_resp.raise_for_status.return_value = None
    with patch("hw_tests.github.requests.get", return_value=list_resp), pytest.raises(
        LookupError
    ):
        gh.download_release_asset("images-initramfs-x.tar.xz", "tag", path=tmp_path)
