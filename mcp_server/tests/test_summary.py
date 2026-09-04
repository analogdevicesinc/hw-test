"""Tests for summary.render: CompareReport dict -> PR-ready markdown.

Reports are built as real CompareReport objects then run through
``serde.to_jsonable`` so the fixtures match the exact wire format the
run_base_vs_pr tool emits. The renderer is pure: dict in, markdown str out,
no network and no I/O.
"""

from mcp_server import serde, summary
from mcp_server.models import (
    CompareReport,
    ImageRef,
    RunOutcome,
    Transition,
)


def _outcome(ref, state, log="line-a\nline-b"):
    img = ImageRef(repo="u-boot", sha=ref, role="u-boot", source="artifact",
                   location="/a")
    return RunOutcome(ref=ref, sha=f"{ref}sha", image=img, state=state,
                      returncode=0 if state == "passed" else 1, log_tail=log)


def _report(**kw):
    base = dict(
        changeset_ref="analogdevicesinc/u-boot@a1b2c3d",
        test_name="adsp/u-boot", board="sc598+ezkit",
        base=_outcome("base", "passed"), pr=_outcome("pr", "passed"),
        transition=Transition.STABLE_PASS, regressed=False,
        result_label="validation-only", evidence=["- old", "+ new"],
        human_summary="adsp/u-boot on sc598+ezkit: base passed, PR passed.",
        test_description="Verifies the SC598 UART console returns a prompt.",
    )
    base.update(kw)
    return serde.to_jsonable(CompareReport(**base))


def test_stable_pass_renders_pass_verdict():
    md = summary.render(_report())
    assert md.startswith("### hw-test:")
    assert "adsp/u-boot" in md
    assert "sc598+ezkit" in md
    # plain-text verdict token, no emoji
    assert "PASS" in md
    assert "pass -> pass" in md
    # PR ref shown
    assert "analogdevicesinc/u-boot@a1b2c3d" in md
    # what the test checks folded in
    assert "UART console" in md
    # honest disclaimer present
    assert "no claim" in md.lower() or "makes no claim" in md.lower()
    # no emoji anywhere
    assert md.isascii()


def test_regression_renders_regression_verdict():
    md = summary.render(_report(
        base=_outcome("base", "passed"), pr=_outcome("pr", "failed"),
        transition=Transition.REGRESSION, regressed=True))
    assert "REGRESSION" in md
    assert "pass -> fail" in md


def test_fix_renders_fix_verdict():
    md = summary.render(_report(
        base=_outcome("base", "failed"), pr=_outcome("pr", "passed"),
        transition=Transition.FIX, regressed=False,
        result_label="coverage-improvement"))
    assert "FIX" in md
    assert "fail -> pass" in md


def test_still_broken_renders_still_broken_verdict():
    md = summary.render(_report(
        base=_outcome("base", "failed"), pr=_outcome("pr", "failed"),
        transition=Transition.STILL_BROKEN, regressed=False))
    assert "STILL-BROKEN" in md


def test_inconclusive_renders_inconclusive_verdict():
    md = summary.render(_report(
        transition=Transition.INCONCLUSIVE, result_label="inconclusive"))
    assert "INCONCLUSIVE" in md


def test_evidence_block_is_fenced_and_present():
    md = summary.render(_report())
    assert "```" in md
    assert "+ new" in md


def test_head_only_run_says_no_base_comparison():
    # base None, pr present, transition None -> single-run report.
    md = summary.render(_report(
        base=None, pr=_outcome("pr", "passed"), transition=None,
        human_summary="adsp/u-boot on sc598+ezkit: PR head passed "
                      "(head-only run; no base comparison)."))
    assert "PASS" in md
    assert "no base comparison" in md.lower()


def test_head_only_fail_renders_fail():
    md = summary.render(_report(
        base=None, pr=_outcome("pr", "failed"), transition=None))
    assert "FAIL" in md
    assert "no base comparison" in md.lower()


def test_no_hardware_label_renders_no_run():
    md = summary.render(_report(
        base=None, pr=None, transition=None,
        result_label="hardware-unavailable", evidence=[],
        human_summary="No board available to run adsp/u-boot."))
    assert "NO-RUN" in md
    # names why nothing ran
    assert "No board available" in md
    # no bogus verdict
    assert "PASS" not in md
    assert "REGRESSION" not in md


def test_build_artifact_unavailable_renders_no_run():
    md = summary.render(_report(
        base=None, pr=None, transition=None,
        result_label="build-artifact-unavailable", evidence=["cc1: error"],
        human_summary="Could not obtain an image for adsp/u-boot."))
    assert "NO-RUN" in md
    assert "Could not obtain an image" in md


def test_test_design_required_renders_no_run():
    md = summary.render(_report(
        base=None, pr=None, transition=None,
        result_label="test-design-requires-user-input", evidence=[],
        human_summary="No reusable test; authoring is a separate step."))
    assert "NO-RUN" in md
