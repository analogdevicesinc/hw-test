"""Tests for the base-vs-PR compare data models."""

import pytest

from mcp_server.models import (
    CompareReport,
    ImageRef,
    RunOutcome,
    Transition,
)


def _image(ref_sha="s"):
    return ImageRef(repo="u-boot", sha=ref_sha, role="u-boot",
                    source="artifact", location="/a/uboot.bin")


def test_imageref_rejects_bad_source():
    with pytest.raises(ValueError, match="source"):
        ImageRef(repo="u-boot", sha="s", role="u-boot", source="magic",
                 location="/x")


def test_runoutcome_rejects_bad_ref_and_state():
    with pytest.raises(ValueError, match="ref"):
        RunOutcome(ref="middle", sha="s", image=_image(), state="passed",
                   returncode=0, log_tail="")
    with pytest.raises(ValueError, match="state"):
        RunOutcome(ref="base", sha="s", image=_image(), state="ok",
                   returncode=0, log_tail="")


def test_transition_values():
    assert Transition.REGRESSION.value == "pass->fail"
    assert Transition.FIX.value == "fail->pass"


def test_compare_report_rejects_unknown_label():
    with pytest.raises(ValueError, match="result_label"):
        CompareReport(changeset_ref="u-boot@h", test_name="adsp/u-boot",
                      board="sc598", base=None, pr=None, transition=None,
                      regressed=False, result_label="totally-fine",
                      evidence=[], human_summary="x")


def test_compare_report_accepts_known_label():
    r = CompareReport(changeset_ref="u-boot@h", test_name="adsp/u-boot",
                      board="sc598", base=None, pr=None, transition=None,
                      regressed=False, result_label="hardware-unavailable",
                      evidence=[], human_summary="x")
    assert r.result_label == "hardware-unavailable"
