"""Tests for the test-writer authoring data models."""

import pytest

from mcp_server.models import StagedTest, ValidationResult


def _vr(ok=True):
    return ValidationResult(ok=ok, parsed=True, collected=ok,
                            collect_log="", tag_match=None, tag_places=[],
                            reasons=[] if ok else ["broke"])


def test_staged_test_rejects_unknown_label():
    with pytest.raises(ValueError, match="result_label"):
        StagedTest(name="adsp/new", staged_dir="/s", files=[], diff="",
                   validation=_vr(), runnable_now=False,
                   result_label="totally-fine")


def test_staged_test_accepts_known_label():
    st = StagedTest(name="adsp/new", staged_dir="/s", files=["/s/test.py"],
                    diff="+x", validation=_vr(), runnable_now=True,
                    result_label="coverage-improvement")
    assert st.result_label == "coverage-improvement"
    assert st.validation.ok is True
