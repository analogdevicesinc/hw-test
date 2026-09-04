"""Reviewed, versioned classification cache.

This is NOT the classifier. The driving LLM decides subsystems; this store is an
optional fast-path of *previously reviewed* attributions, keyed by repo +
path-glob. It is seeded and grown only by a human editing the TOML — never by
the server rewriting itself at runtime from untrusted input. Matches the brief's
"learning = reviewed versioned knowledge" rule.

The seed file lives at ``knowledge/classification_cache.toml`` (may be minimal or
empty). Format::

    version = "2026-09-03"

    [[entry]]
    id = "uboot-spi"
    repo = "u-boot"
    path_glob = "drivers/spi/*"
    subsystem = "spi_qspi_xspi"
    doc = { repo = "documentation", query = "sc598 ospi boot" }
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from mcp_server.models import DocRef, Subsystem

DEFAULT_CACHE_PATH = (
    Path(__file__).resolve().parent / "knowledge" / "classification_cache.toml"
)


@dataclass
class CacheHit:
    """A reviewed cache match for one file path."""

    matched_id: str
    subsystem: Subsystem
    doc_ref: DocRef | None


class Knowledge:
    """Loads the reviewed classification cache."""

    def __init__(self, path: Path | str = DEFAULT_CACHE_PATH):
        self.path = Path(path)

    def _load(self) -> dict:
        if not self.path.is_file():
            return {"entry": []}
        with self.path.open("rb") as f:
            return tomllib.load(f)

    def lookup(self, repo: str, path: str) -> CacheHit | None:
        """Return the first reviewed entry whose repo + glob match, else None."""
        for entry in self._load().get("entry", []):
            if entry.get("repo") != repo:
                continue
            if not fnmatch(path, entry.get("path_glob", "")):
                continue
            doc = entry.get("doc")
            doc_ref = (
                DocRef(repo=doc["repo"], query=doc["query"],
                       board=doc.get("board"), doc_id=doc.get("doc_id"),
                       version_hint=doc.get("version_hint"))
                if doc else None
            )
            return CacheHit(
                matched_id=entry["id"],
                subsystem=Subsystem(entry["subsystem"]),
                doc_ref=doc_ref,
            )
        return None
