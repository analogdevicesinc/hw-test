"""Tests for serde: dataclass <-> JSON-able dict at the MCP tool boundary."""

from mcp_server import serde
from mcp_server.models import (
    ChangeSet,
    DocRef,
    FileChange,
    SourceRef,
)


def _changeset():
    return ChangeSet(
        source=SourceRef(repo="u-boot", ref_or_sha="h", kind="pr"),
        repo="u-boot", head_sha="h", base_ref="b", merge_base_sha="mb",
        files=[FileChange(path="a.c", status="modified", hunk_snippets=["+x"])],
        commits=["c1"], human_summary="s", pr_number=7,
    )


def test_to_jsonable_dataclass_becomes_dict():
    d = serde.to_jsonable(_changeset())
    assert d["repo"] == "u-boot"
    assert d["files"][0]["path"] == "a.c"
    assert d["source"]["kind"] == "pr"
    assert d["pr_number"] == 7


def test_to_jsonable_enum_becomes_value():
    d = serde.to_jsonable(DocRef(repo="documentation", query="q"))
    assert d == {"repo": "documentation", "query": "q", "board": None,
                 "doc_id": None, "version_hint": None}


def test_to_jsonable_list_of_dataclasses():
    out = serde.to_jsonable([FileChange(path="a.c", status="added")])
    assert out == [{"path": "a.c", "status": "added", "hunk_snippets": []}]


def test_changeset_round_trips_through_dict():
    original = _changeset()
    d = serde.to_jsonable(original)
    rebuilt = serde.changeset_from_dict(d)
    assert isinstance(rebuilt, ChangeSet)
    assert rebuilt.repo == original.repo
    assert rebuilt.file_paths() == original.file_paths()
    assert rebuilt.source.kind == "pr"
    assert rebuilt.pr_number == 7


def test_changeset_from_dict_accepts_changeset_passthrough():
    original = _changeset()
    assert serde.changeset_from_dict(original) is original


def test_changeset_from_dict_missing_key_gives_clear_error():
    # The agent passed a partial dict (only repo + pr_number). A bare KeyError
    # 'source' is opaque and made the agent re-paste the whole changeset. The
    # error must name the missing field and say to pass the inspect_* output
    # unchanged.
    import pytest

    partial = {"repo": "u-boot", "pr_number": 7}
    with pytest.raises(ValueError) as exc:
        serde.changeset_from_dict(partial)
    msg = str(exc.value)
    assert "source" in msg
    assert "inspect_pr" in msg or "inspect_local" in msg
