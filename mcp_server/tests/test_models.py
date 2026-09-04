"""Tests for the typed shared models crossing MCP module boundaries."""

import dataclasses

import pytest

from mcp_server import models


def test_subsystem_is_str_enum_with_expected_members():
    # str-valued so the enum serializes cleanly to JSON in tool output.
    assert models.Subsystem.SPI_QSPI_XSPI.value == "spi_qspi_xspi"
    assert models.Subsystem("board_dt") is models.Subsystem.BOARD_DT
    names = {s.value for s in models.Subsystem}
    assert names == {
        "boot_chain", "board_dt", "clock_reset_power", "spi_qspi_xspi",
        "storage_mmc_sd", "net_phy", "uart_console", "can", "usb", "ddr",
        "kconfig_build", "other",
    }


def test_source_ref_kind_validated():
    ref = models.SourceRef(repo="u-boot", ref_or_sha="abc123", kind="pr")
    assert ref.kind == "pr"
    with pytest.raises(ValueError):
        models.SourceRef(repo="u-boot", ref_or_sha="abc", kind="bogus")


def test_file_change_roundtrips_to_dict():
    fc = models.FileChange(path="drivers/spi/x.c", status="modified",
                           hunk_snippets=["@@ -1 +1 @@"])
    d = dataclasses.asdict(fc)
    assert d == {"path": "drivers/spi/x.c", "status": "modified",
                 "hunk_snippets": ["@@ -1 +1 @@"]}


def test_changeset_holds_files_and_summary():
    cs = models.ChangeSet(
        source=models.SourceRef(repo="u-boot", ref_or_sha="head", kind="pr"),
        repo="u-boot", pr_number=107, head_sha="head", base_ref="base",
        merge_base_sha="mb",
        files=[models.FileChange(path="a.c", status="modified", hunk_snippets=[])],
        commits=["c1"], human_summary="1 file changed",
    )
    assert cs.repo == "u-boot"
    assert cs.file_paths() == ["a.c"]


def test_classification_requires_enum_subsystem():
    c = models.Classification(
        subsystem=models.Subsystem.SPI_QSPI_XSPI, confidence="high",
        evidence_files=["drivers/spi/x.c"], source="llm",
        rationale="spi driver touched",
    )
    assert c.subsystem is models.Subsystem.SPI_QSPI_XSPI
    with pytest.raises(ValueError):
        models.Classification(
            subsystem="spi_qspi_xspi", confidence="nope",
            evidence_files=[], source="llm", rationale="",
        )


def test_docref_only_requires_repo_and_query():
    d = models.DocRef(repo="documentation", query="sc598 ospi boot")
    assert d.board is None and d.doc_id is None and d.version_hint is None


def test_testplan_result_label_validated():
    plan = models.TestPlan(
        changeset_ref="u-boot@head", classifications=[], scope="uboot boot",
        candidate_capabilities=["uboot"], existing_test_matches=["adsp/u-boot"],
        coverage_gap="reuse", doc_refs=[], expected_base_vs_pr="hypothesis",
        board_requirements=["sc598"], result_label_if_no_hw="validation-only",
        human_summary="reuse adsp/u-boot",
    )
    assert plan.coverage_gap == "reuse"
    with pytest.raises(ValueError):
        dataclasses.replace(plan, result_label_if_no_hw="totally-passes")
    with pytest.raises(ValueError):
        dataclasses.replace(plan, coverage_gap="rewrite-everything")
