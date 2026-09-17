"""Tests for planning.validate_classifications (the determinism gate)."""

import pytest

from mcp_server import planning
from mcp_server.models import ChangeSet, Classification, FileChange, SourceRef, Subsystem


def _changeset(paths):
    return ChangeSet(
        source=SourceRef(repo="u-boot", ref_or_sha="h", kind="pr"),
        repo="u-boot", head_sha="h", base_ref="b", merge_base_sha="mb",
        files=[FileChange(path=p, status="modified") for p in paths],
        commits=["c1"], human_summary="", pr_number=1,
    )


def test_valid_classification_dicts_become_typed_objects():
    cs = _changeset(["drivers/spi/adi_spi3.c"])
    raw = [{
        "subsystem": "spi_qspi_xspi", "confidence": "high",
        "evidence_files": ["drivers/spi/adi_spi3.c"], "source": "llm",
        "rationale": "spi driver touched",
    }]
    out = planning.validate_classifications(cs, raw)
    assert len(out) == 1
    assert isinstance(out[0], Classification)
    assert out[0].subsystem is Subsystem.SPI_QSPI_XSPI


def test_rejects_unknown_subsystem():
    cs = _changeset(["a.c"])
    raw = [{"subsystem": "quantum_flux", "confidence": "high",
            "evidence_files": ["a.c"], "source": "llm"}]
    with pytest.raises(ValueError, match="subsystem"):
        planning.validate_classifications(cs, raw)


def test_rejects_evidence_file_not_in_changeset():
    cs = _changeset(["a.c"])
    raw = [{"subsystem": "spi_qspi_xspi", "confidence": "high",
            "evidence_files": ["not/in/changeset.c"], "source": "llm"}]
    with pytest.raises(ValueError, match="evidence"):
        planning.validate_classifications(cs, raw)


def test_rejects_empty_evidence():
    cs = _changeset(["a.c"])
    raw = [{"subsystem": "other", "confidence": "low",
            "evidence_files": [], "source": "llm"}]
    with pytest.raises(ValueError, match="evidence"):
        planning.validate_classifications(cs, raw)


def test_rejects_bad_source():
    cs = _changeset(["a.c"])
    raw = [{"subsystem": "other", "confidence": "low",
            "evidence_files": ["a.c"], "source": "guess"}]
    with pytest.raises(ValueError, match="source"):
        planning.validate_classifications(cs, raw)


def test_accepts_already_typed_classification():
    cs = _changeset(["a.c"])
    typed = Classification(subsystem=Subsystem.OTHER, confidence="low",
                           evidence_files=["a.c"], source="llm")
    out = planning.validate_classifications(cs, [typed])
    assert out[0] is typed


def test_error_names_the_offending_index():
    cs = _changeset(["a.c"])
    raw = [
        {"subsystem": "other", "confidence": "low", "evidence_files": ["a.c"],
         "source": "llm"},
        {"subsystem": "other", "confidence": "low", "evidence_files": ["x.c"],
         "source": "llm"},
    ]
    with pytest.raises(ValueError, match="index 1"):
        planning.validate_classifications(cs, raw)


def test_reports_all_errors_in_one_entry_at_once():
    # The classifier sent one entry with several problems at once. The gate
    # must name every problem in a single error, not fail on the first field
    # and force a resubmit per field.
    cs = _changeset(["a.c"])
    raw = [{"subsystem": "other", "evidence_files": []}]  # no confidence,
    #                                       no source, empty evidence
    with pytest.raises(ValueError) as exc:
        planning.validate_classifications(cs, raw)
    msg = str(exc.value)
    assert "confidence" in msg
    assert "source" in msg
    assert "evidence" in msg


def test_reports_errors_across_all_entries_at_once():
    # Two bad entries -> one error naming both indices, so the classifier fixes
    # everything in a single resubmit instead of ping-ponging per entry.
    cs = _changeset(["a.c"])
    raw = [
        {"subsystem": "other", "confidence": "low", "evidence_files": ["x.c"],
         "source": "llm"},
        {"subsystem": "quantum_flux", "confidence": "high",
         "evidence_files": ["a.c"], "source": "llm"},
    ]
    with pytest.raises(ValueError) as exc:
        planning.validate_classifications(cs, raw)
    msg = str(exc.value)
    assert "index 0" in msg
    assert "index 1" in msg
