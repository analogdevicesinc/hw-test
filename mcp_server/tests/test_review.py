"""Tests for review.doc_refs_for (evidence/classification -> DocRef pointers)."""

from mcp_server import review
from mcp_server.models import (
    Classification,
    ClassificationEvidence,
    DocRef,
    FileChange,
    Subsystem,
)


def _evidence(seed_refs):
    return ClassificationEvidence(
        repo="u-boot", files=[FileChange(path="a.c", status="modified")],
        matched_metas=[], subsystem_choices=[], seed_doc_refs=seed_refs,
    )


def test_prefers_cache_seed_doc_refs():
    ev = _evidence([DocRef(repo="documentation", query="sc598 ospi boot")])
    classifications = [Classification(
        subsystem=Subsystem.SPI_QSPI_XSPI, confidence="high",
        evidence_files=["a.c"], source="cache")]
    refs = review.doc_refs_for(classifications, ev, board="sc598")
    assert any(r.query == "sc598 ospi boot" for r in refs)


def test_falls_back_to_subsystem_query_when_no_seed():
    ev = _evidence([])
    classifications = [Classification(
        subsystem=Subsystem.STORAGE_MMC_SD, confidence="medium",
        evidence_files=["a.c"], source="llm")]
    refs = review.doc_refs_for(classifications, ev, board="sc598")
    assert len(refs) == 1
    assert refs[0].repo == "documentation"
    assert "sc598" in refs[0].query
    # subsystem keyword present in fallback query
    assert "mmc" in refs[0].query or "storage" in refs[0].query
    assert refs[0].board == "sc598"


def test_dedupes_repeated_refs():
    ev = _evidence([DocRef(repo="documentation", query="sc598 ospi boot")])
    classifications = [
        Classification(subsystem=Subsystem.SPI_QSPI_XSPI, confidence="high",
                       evidence_files=["a.c"], source="cache"),
        Classification(subsystem=Subsystem.SPI_QSPI_XSPI, confidence="high",
                       evidence_files=["a.c"], source="llm"),
    ]
    refs = review.doc_refs_for(classifications, ev, board="sc598")
    keys = [(r.repo, r.query) for r in refs]
    assert len(keys) == len(set(keys))


def test_no_board_still_produces_query():
    ev = _evidence([])
    classifications = [Classification(
        subsystem=Subsystem.NET_PHY, confidence="low",
        evidence_files=["a.c"], source="llm")]
    refs = review.doc_refs_for(classifications, ev, board=None)
    assert refs and refs[0].query
