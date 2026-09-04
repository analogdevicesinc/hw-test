"""Shape documentation-evidence pointers for the driving agent.

This module NEVER fetches documentation. Doc retrieval belongs to the separate
doctools MCP server (`adoc`: search/search_wiki). Here we only produce
doctools-ready ``DocRef`` pointers so the agent can hand ``repo``/``query``
straight to that server's ``search`` tool.

Preference order per classification: a reviewed cache seed DocRef (already
carries a curated query), else a fallback query built from the board plus
subsystem keywords.
"""

from __future__ import annotations

from mcp_server.models import Classification, ClassificationEvidence, DocRef, Subsystem

# Keyword hints per subsystem for the fallback doctools query. Kept small and
# board-agnostic; the board token is prepended at call time.
_SUBSYSTEM_QUERY_TERMS = {
    Subsystem.BOOT_CHAIN: "boot chain spl u-boot",
    Subsystem.BOARD_DT: "board device tree",
    Subsystem.CLOCK_RESET_POWER: "clock reset power cgu",
    Subsystem.SPI_QSPI_XSPI: "spi qspi ospi boot",
    Subsystem.STORAGE_MMC_SD: "emmc sd mmc storage",
    Subsystem.NET_PHY: "ethernet phy emac network",
    Subsystem.UART_CONSOLE: "uart console serial",
    Subsystem.CAN: "can canfd",
    Subsystem.USB: "usb",
    Subsystem.DDR: "ddr dmc memory controller",
    Subsystem.KCONFIG_BUILD: "kconfig defconfig build",
    Subsystem.OTHER: "overview",
}

# Default doctools repo for system-level ADI docs.
_DEFAULT_DOC_REPO = "documentation"


def _fallback_ref(subsystem: Subsystem, board: str | None) -> DocRef:
    terms = _SUBSYSTEM_QUERY_TERMS.get(subsystem, subsystem.value)
    query = f"{board} {terms}".strip() if board else terms
    return DocRef(repo=_DEFAULT_DOC_REPO, query=query, board=board)


def doc_refs_for(classifications: list[Classification],
                 evidence: ClassificationEvidence,
                 board: str | None = None) -> list[DocRef]:
    """Return deduped doctools-ready DocRefs: curated cache seeds first, then a
    fallback query for any classified subsystem no seed already covers.
    """
    refs: list[DocRef] = []
    seen: set[tuple[str, str]] = set()

    def _add(ref: DocRef) -> None:
        key = (ref.repo, ref.query)
        if key not in seen:
            seen.add(key)
            refs.append(ref)

    # Curated cache seeds are authoritative — include first.
    for ref in evidence.seed_doc_refs:
        _add(ref)

    seed_queries = [r.query for r in evidence.seed_doc_refs]
    for c in classifications:
        terms = _SUBSYSTEM_QUERY_TERMS.get(c.subsystem, c.subsystem.value)
        if not any(terms.split()[0] in q for q in seed_queries):
            _add(_fallback_ref(c.subsystem, board))

    return refs
