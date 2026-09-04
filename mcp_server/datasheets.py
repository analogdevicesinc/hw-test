"""Pick doctools docling-branch datasheet markdown for test authoring.

The doctools ``docling`` branch carries thousands of markdown files converted
from analog.com PDF datasheets and hardware reference manuals, all under
``media/en/technical-documentation/data-sheets/``. They hold register maps,
offsets, and peripheral descriptions directly useful when authoring a hw-test.

This module NEVER fetches document content. It only turns the branch's file
tree into ``{path, raw_url}`` pointers the driving agent can hand to WebFetch.
The git-tree fetch (``tree_fetcher``) is injected so the module is pure
and unit-testable with no network, mirroring :mod:`mcp_server.review`, which
likewise produces pointers and never retrieves docs.
"""

from __future__ import annotations

_DOC_PREFIX = "media/en/technical-documentation/data-sheets/"
_RAW_BASE = "https://raw.githubusercontent.com/analogdevicesinc/doctools/docling/"


def raw_url(path: str) -> str:
    """Return the docling-branch raw URL for a data-sheets markdown ``path``.

    ``path`` must live under the data-sheets prefix; anything else is a
    programming error, not a graceful miss, so it raises.
    """
    if not path.startswith(_DOC_PREFIX):
        raise ValueError(f"path not under {_DOC_PREFIX!r}: {path!r}")
    return _RAW_BASE + path


def list_docs(query: str, *, tree_fetcher, limit: int = 40) -> list[dict]:
    """Return ``[{path, raw_url}]`` for datasheet md files matching ``query``.

    ``tree_fetcher()`` returns a GitHub git-tree API dict (blobs for the whole
    branch). A file matches when ANY whitespace-separated term of ``query``
    appears (case-insensitive) in its path. Only ``.md`` blobs under the
    data-sheets prefix are considered. Results are sorted by path and capped at
    ``limit``. An empty/whitespace query returns ``[]`` (no term to match).
    """
    terms = query.lower().split()
    if not terms:
        return []

    tree = tree_fetcher() or {}
    matches = []
    for entry in tree.get("tree", []):
        if entry.get("type") != "blob":
            continue
        path = entry.get("path", "")
        if not path.startswith(_DOC_PREFIX) or not path.endswith(".md"):
            continue
        lowered = path.lower()
        if any(term in lowered for term in terms):
            matches.append(path)

    matches.sort()
    return [{"path": p, "raw_url": raw_url(p)} for p in matches[:limit]]
