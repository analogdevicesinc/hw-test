"""JSON boundary for the MCP tools.

Tool arguments and results cross a stdio/JSON boundary, so dataclasses and
``Subsystem`` enums must round-trip through plain dicts. ``to_jsonable``
recursively converts any model into JSON-safe primitives; ``changeset_from_dict``
rebuilds a ``ChangeSet`` from a dict the driving agent passes back in (e.g. the
output of ``inspect_pr`` handed to ``get_classification_evidence``).
"""

from __future__ import annotations

import dataclasses
from enum import Enum

from mcp_server.models import ChangeSet, FileChange, SourceRef


def to_jsonable(obj):
    """Recursively convert dataclasses/enums/containers to JSON-safe values."""
    if isinstance(obj, Enum):
        return obj.value
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name))
                for f in dataclasses.fields(obj)}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    return obj


_REQUIRED_CHANGESET_KEYS = ("source", "repo", "head_sha", "base_ref",
                            "merge_base_sha")


def changeset_from_dict(data) -> ChangeSet:
    """Rebuild a ChangeSet from a dict (or pass through an existing ChangeSet).

    The dict must be an ``inspect_pr``/``inspect_local`` result passed back
    unchanged. A partial dict (e.g. just ``repo`` + ``pr_number``) is rejected
    with a message that names the missing fields and says what to pass, rather
    than a bare ``KeyError`` that led the caller to re-paste the whole payload.
    """
    if isinstance(data, ChangeSet):
        return data
    missing = [k for k in _REQUIRED_CHANGESET_KEYS if k not in data]
    if missing:
        raise ValueError(
            f"changeset is missing required field(s) {missing}; pass the "
            f"inspect_pr / inspect_local result back unchanged (do not drop "
            f"fields or send a partial object)."
        )
    src = data["source"]
    source = (src if isinstance(src, SourceRef)
              else SourceRef(repo=src["repo"], ref_or_sha=src["ref_or_sha"],
                             kind=src["kind"]))
    files = [
        f if isinstance(f, FileChange)
        else FileChange(path=f["path"], status=f["status"],
                        hunk_snippets=list(f.get("hunk_snippets", [])))
        for f in data.get("files", [])
    ]
    return ChangeSet(
        source=source,
        repo=data["repo"],
        head_sha=data["head_sha"],
        base_ref=data["base_ref"],
        merge_base_sha=data["merge_base_sha"],
        files=files,
        commits=list(data.get("commits", [])),
        human_summary=data.get("human_summary", ""),
        pr_number=data.get("pr_number"),
    )
