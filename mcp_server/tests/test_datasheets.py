"""Tests for datasheets: pick doctools docling-branch datasheet md pointers.

The module never touches the network: ``list_docs`` takes an injected
``tree_fetcher`` returning a git-tree API dict, and ``raw_url`` is pure.
"""

import pytest

from mcp_server import datasheets

_PREFIX = "media/en/technical-documentation/data-sheets/"


def _tree(*paths, truncated=False):
    """Fake git-tree API response with blob entries at the given paths."""
    return {
        "sha": "docling",
        "truncated": truncated,
        "tree": [{"path": p, "type": "blob", "mode": "100644"} for p in paths],
    }


def test_list_docs_matches_any_query_term():
    fetch = lambda: _tree(
        _PREFIX + "adsp-sc596-adsp-sc598.md",
        _PREFIX + "some-unrelated-part.md",
        _PREFIX + "uart-transceiver.md",
    )
    out = datasheets.list_docs("sc598 uart", tree_fetcher=fetch)
    paths = [d["path"] for d in out]
    assert _PREFIX + "adsp-sc596-adsp-sc598.md" in paths
    assert _PREFIX + "uart-transceiver.md" in paths
    assert _PREFIX + "some-unrelated-part.md" not in paths


def test_list_docs_filters_non_datasheet_and_non_md():
    fetch = lambda: _tree(
        _PREFIX + "adsp-sc598.md",         # keep
        _PREFIX + "adsp-sc598.pdf",        # not .md
        "media/en/other/adsp-sc598.md",    # not under data-sheets/
    )
    out = datasheets.list_docs("sc598", tree_fetcher=fetch)
    paths = [d["path"] for d in out]
    assert paths == [_PREFIX + "adsp-sc598.md"]


def test_list_docs_ignores_tree_entries_only_blobs():
    fetch = lambda: {
        "truncated": False,
        "tree": [
            {"path": _PREFIX + "sc598", "type": "tree"},
            {"path": _PREFIX + "sc598.md", "type": "blob"},
        ],
    }
    out = datasheets.list_docs("sc598", tree_fetcher=fetch)
    assert [d["path"] for d in out] == [_PREFIX + "sc598.md"]


def test_list_docs_empty_query_returns_empty():
    fetch = lambda: _tree(_PREFIX + "sc598.md")
    assert datasheets.list_docs("", tree_fetcher=fetch) == []
    assert datasheets.list_docs("   ", tree_fetcher=fetch) == []


def test_list_docs_no_match_returns_empty():
    fetch = lambda: _tree(_PREFIX + "sc598.md")
    assert datasheets.list_docs("nothingmatches", tree_fetcher=fetch) == []


def test_list_docs_respects_limit_and_is_sorted():
    fetch = lambda: _tree(
        _PREFIX + "sc598-c.md",
        _PREFIX + "sc598-a.md",
        _PREFIX + "sc598-b.md",
    )
    out = datasheets.list_docs("sc598", tree_fetcher=fetch, limit=2)
    assert [d["path"] for d in out] == [
        _PREFIX + "sc598-a.md", _PREFIX + "sc598-b.md"]


def test_list_docs_result_carries_raw_url():
    fetch = lambda: _tree(_PREFIX + "sc598.md")
    out = datasheets.list_docs("sc598", tree_fetcher=fetch)
    assert out[0]["raw_url"] == datasheets.raw_url(_PREFIX + "sc598.md")
    assert out[0]["raw_url"].startswith(
        "https://raw.githubusercontent.com/analogdevicesinc/doctools/docling/")


def test_raw_url_builds_docling_raw():
    url = datasheets.raw_url(_PREFIX + "adsp-sc598.md")
    assert url == ("https://raw.githubusercontent.com/analogdevicesinc/"
                   "doctools/docling/" + _PREFIX + "adsp-sc598.md")


def test_raw_url_rejects_outside_data_sheets():
    with pytest.raises(ValueError):
        datasheets.raw_url("media/en/other/x.md")
