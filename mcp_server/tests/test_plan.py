"""Tests for planning.create_test_plan (honest, verdict-free plan synthesis)."""

from mcp_server import knowledge, planning
from mcp_server.models import (
    ChangeSet,
    Classification,
    ClassificationEvidence,
    DocRef,
    FileChange,
    SourceRef,
    Subsystem,
    TestPlan as _TestPlan,
)

METAS = [
    {
        "_uid": "adsp/u-boot",
        "needs": ["sc598", "ezkit"],
        "repository": [{"name": "u-boot",
                        "path": "board/adi/sc598*\nconfigs/sc598*\n"}],
        "capabilities": {"provides": ["uboot", "openocd", "spi_boot"]},
    },
]


def _changeset(repo, paths, pr=1):
    return ChangeSet(
        source=SourceRef(repo=repo, ref_or_sha="head123", kind="pr"),
        repo=repo, head_sha="head123", base_ref="mainline", merge_base_sha="mb",
        files=[FileChange(path=p, status="modified") for p in paths],
        commits=["c1"], human_summary="", pr_number=pr,
    )


def _evidence(repo, paths, matched, seed_refs=None):
    return ClassificationEvidence(
        repo=repo,
        files=[FileChange(path=p, status="modified") for p in paths],
        matched_metas=matched,
        subsystem_choices=[s.value for s in Subsystem],
        seed_doc_refs=seed_refs or [],
    )


def test_plan_reuses_matched_test_and_capabilities():
    cs = _changeset("analogdevicesinc/u-boot", ["board/adi/sc598/x.c"])
    ev = _evidence("analogdevicesinc/u-boot", ["board/adi/sc598/x.c"],
                   ["adsp/u-boot"])
    classifications = [Classification(
        subsystem=Subsystem.BOARD_DT, confidence="high",
        evidence_files=["board/adi/sc598/x.c"], source="llm")]

    plan = planning.create_test_plan(cs, classifications, ev, metas=METAS,
                                     board="sc598")

    assert isinstance(plan, _TestPlan)
    assert plan.existing_test_matches == ["adsp/u-boot"]
    assert "uboot" in plan.candidate_capabilities
    assert plan.coverage_gap == "reuse"
    assert "sc598" in plan.board_requirements
    assert plan.result_label_if_no_hw == "hardware-unavailable"
    assert plan.classifications == classifications
    assert "head123" in plan.changeset_ref
    assert plan.human_summary


def test_plan_no_match_is_new_coverage_gap():
    cs = _changeset("u-boot", ["drivers/usb/host/xhci.c"])
    ev = _evidence("u-boot", ["drivers/usb/host/xhci.c"], [])
    classifications = [Classification(
        subsystem=Subsystem.USB, confidence="medium",
        evidence_files=["drivers/usb/host/xhci.c"], source="llm")]

    plan = planning.create_test_plan(cs, classifications, ev, metas=METAS)

    assert plan.coverage_gap == "new"
    assert plan.candidate_capabilities == []
    assert plan.existing_test_matches == []
    assert plan.result_label_if_no_hw == "test-design-requires-user-input"


def test_plan_doc_refs_populated_from_seed():
    seed = DocRef(repo="documentation", query="sc598 ospi boot")
    cs = _changeset("u-boot", ["drivers/spi/adi_spi3.c"])
    ev = _evidence("u-boot", ["drivers/spi/adi_spi3.c"], ["adsp/u-boot"],
                   seed_refs=[seed])
    classifications = [Classification(
        subsystem=Subsystem.SPI_QSPI_XSPI, confidence="high",
        evidence_files=["drivers/spi/adi_spi3.c"], source="cache")]

    plan = planning.create_test_plan(cs, classifications, ev, metas=METAS,
                                     board="sc598")

    assert any(d.query == "sc598 ospi boot" for d in plan.doc_refs)


def test_plan_scope_lists_subsystems():
    cs = _changeset("u-boot", ["a.c", "b.c"])
    ev = _evidence("u-boot", ["a.c", "b.c"], [])
    classifications = [
        Classification(subsystem=Subsystem.BOARD_DT, confidence="high",
                       evidence_files=["a.c"], source="llm"),
        Classification(subsystem=Subsystem.NET_PHY, confidence="medium",
                       evidence_files=["b.c"], source="llm"),
    ]

    plan = planning.create_test_plan(cs, classifications, ev, metas=METAS)

    assert "board_dt" in plan.scope
    assert "net_phy" in plan.scope
