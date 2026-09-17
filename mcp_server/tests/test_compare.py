"""Tests for compare diff/report helpers and run_base_vs_pr orchestration."""

import pytest

from mcp_server import compare
from mcp_server.models import ImageRef, RunOutcome, Transition


def _outcome(ref, state, log="ok"):
    img = ImageRef(repo="u-boot", sha=ref, role="u-boot", source="artifact",
                   location="/a")
    return RunOutcome(ref=ref if ref in ("base", "pr") else "base", sha="s",
                      image=img, state=state, returncode=0 if state == "passed"
                      else 1, log_tail=log)


def test_diff_state_regression():
    base = _outcome("base", "passed")
    pr = _outcome("pr", "failed")
    assert compare.diff_state(base, pr) == Transition.REGRESSION


def test_diff_state_fix():
    assert compare.diff_state(_outcome("base", "failed"),
                              _outcome("pr", "passed")) == Transition.FIX


def test_diff_state_stable_and_broken():
    assert compare.diff_state(_outcome("base", "passed"),
                              _outcome("pr", "passed")) == Transition.STABLE_PASS
    assert compare.diff_state(_outcome("base", "failed"),
                              _outcome("pr", "failed")) == Transition.STILL_BROKEN


def test_diff_state_inconclusive():
    assert compare.diff_state(_outcome("base", "inconclusive"),
                              _outcome("pr", "passed")) == Transition.INCONCLUSIVE


def test_label_for_maps_transitions():
    assert compare.label_for(Transition.FIX) == ("coverage-improvement", False)
    assert compare.label_for(Transition.REGRESSION) == ("validation-only", True)
    assert compare.label_for(Transition.STABLE_PASS) == ("validation-only", False)
    assert compare.label_for(Transition.INCONCLUSIVE) == ("inconclusive", False)


def test_log_diff_reports_changed_lines():
    base = _outcome("base", "passed", log="a\nb\nc")
    pr = _outcome("pr", "failed", log="a\nX\nc")
    ev = compare.log_diff(base, pr)
    assert any("X" in line for line in ev)


from mcp_server.models import CompareReport
from mcp_server.orchestration import imaging


class FakePrimitives:
    def __init__(self, *, reserve_fails=False, image_fails_on=None,
                 outcomes=None):
        self.reserve_fails = reserve_fails
        self.image_fails_on = image_fails_on  # sha to fail build on
        self.outcomes = outcomes or {}
        self.calls = []
        self.released = []

    def reserve(self, needs):
        self.calls.append(("reserve", needs))
        if self.reserve_fails:
            raise RuntimeError(
                f"no available place for needs: {needs} (busy by someone)")
        return "tok-1"

    def resolve_image(self, repo, sha, role):
        self.calls.append(("resolve", sha))
        if self.image_fails_on == sha:
            raise imaging.BuildError("build failed", log_tail="cc1: error")
        return ImageRef(repo=repo, sha=sha, role=role, source="artifact",
                        location=f"/a/{sha}")

    def run(self, test_name, token, image):
        self.calls.append(("run", image.sha))
        return f"run-{image.sha}"

    def wait(self, run_id, ref):
        self.calls.append(("wait", ref))
        state = self.outcomes.get(ref, "passed")
        img = ImageRef(repo="u-boot", sha=ref, role="u-boot",
                       source="artifact", location="/a")
        return RunOutcome(ref=ref, sha=ref, image=img, state=state,
                          returncode=0 if state == "passed" else 1,
                          log_tail=f"{ref} log")

    def release(self, token):
        self.released.append(token)


def _cs():
    return {
        "source": {"repo": "u-boot", "ref_or_sha": "h", "kind": "pr"},
        "repo": "u-boot", "head_sha": "prsha", "base_ref": "main",
        "merge_base_sha": "basesha",
        "files": [{"path": "board/adi/sc598/x.c", "status": "modified"}],
        "commits": ["c1"], "human_summary": "", "pr_number": 7,
    }


def test_no_test_guard_skips_hardware():
    prims = FakePrimitives()
    report = compare.run_base_vs_pr(_cs(), "", ["sc598", "ezkit"], primitives=prims,
                                    coverage_gap="new")
    assert report.result_label == "test-design-requires-user-input"
    assert report.base is None and report.pr is None
    assert prims.calls == []  # never reserved


def test_reserve_failure_is_hardware_unavailable():
    prims = FakePrimitives(reserve_fails=True)
    report = compare.run_base_vs_pr(_cs(), "adsp/u-boot", ["sc598", "ezkit"],
                                    primitives=prims)
    assert report.result_label == "hardware-unavailable"
    assert prims.released == []  # nothing to release


def test_image_failure_releases_and_reports():
    prims = FakePrimitives(image_fails_on="prsha")
    report = compare.run_base_vs_pr(_cs(), "adsp/u-boot", ["sc598", "ezkit"],
                                    primitives=prims)
    assert report.result_label == "build-artifact-unavailable"
    assert prims.released == ["tok-1"]  # released despite failure
    assert any("cc1: error" in e for e in report.evidence)


def test_regression_path_runs_both_and_releases():
    prims = FakePrimitives(outcomes={"base": "passed", "pr": "failed"})
    report = compare.run_base_vs_pr(_cs(), "adsp/u-boot", ["sc598", "ezkit"],
                                    primitives=prims)
    assert report.transition == Transition.REGRESSION
    assert report.regressed is True
    assert report.result_label == "validation-only"
    assert report.base.state == "passed" and report.pr.state == "failed"
    assert prims.released == ["tok-1"]
    # base resolved+run before pr
    order = [c for c in prims.calls if c[0] in ("resolve", "run", "wait")]
    assert order.index(("run", "basesha")) < order.index(("run", "prsha"))


def test_fix_path_is_coverage_improvement():
    prims = FakePrimitives(outcomes={"base": "failed", "pr": "passed"})
    report = compare.run_base_vs_pr(_cs(), "adsp/u-boot", ["sc598", "ezkit"],
                                    primitives=prims)
    assert report.transition == Transition.FIX
    assert report.result_label == "coverage-improvement"


def test_head_only_runs_pr_and_skips_base():
    # When the base image is unavailable (e.g. CI artifacts expired), a
    # head-only run validates just the PR head: one run, no base, no transition.
    prims = FakePrimitives(outcomes={"pr": "passed"})
    report = compare.run_base_vs_pr(_cs(), "adsp/u-boot", ["sc598", "ezkit"],
                                    primitives=prims, mode="head-only")
    assert report.base is None
    assert report.pr.state == "passed"
    assert report.transition is None
    assert report.regressed is False
    assert report.result_label == "validation-only"
    assert prims.released == ["tok-1"]
    # base image is never resolved or run
    assert ("resolve", "basesha") not in prims.calls
    assert ("run", "basesha") not in prims.calls
    assert ("run", "prsha") in prims.calls


def test_head_only_image_failure_releases_and_reports():
    prims = FakePrimitives(image_fails_on="prsha")
    report = compare.run_base_vs_pr(_cs(), "adsp/u-boot", ["sc598", "ezkit"],
                                    primitives=prims, mode="head-only")
    assert report.result_label == "build-artifact-unavailable"
    assert prims.released == ["tok-1"]


def test_release_happens_even_if_run_raises():
    prims = FakePrimitives(outcomes={"base": "passed", "pr": "passed"})

    def boom(test_name, token, image):
        raise RuntimeError("run exploded")
    prims.run = boom

    with pytest.raises(RuntimeError, match="exploded"):
        compare.run_base_vs_pr(_cs(), "adsp/u-boot", ["sc598", "ezkit"], primitives=prims)
    assert prims.released == ["tok-1"]  # finally released


def test_needs_list_passed_through_to_reserve():
    # The multi-tag needs list must reach reserve intact — not collapsed into
    # one string. Regression guard for the sc598+ezkit hardware-unavailable bug.
    prims = FakePrimitives(outcomes={"pr": "passed"})
    compare.run_base_vs_pr(_cs(), "adsp/u-boot", ["sc598", "ezkit"],
                           primitives=prims, mode="head-only")
    assert ("reserve", ["sc598", "ezkit"]) in prims.calls


def test_hardware_unavailable_surfaces_reason():
    # When no board matches, the report must say WHY — the reserve error text
    # goes into evidence and the summary, not a blank "no board".
    prims = FakePrimitives(reserve_fails=True)
    report = compare.run_base_vs_pr(_cs(), "adsp/u-boot", ["sc598", "ezkit"],
                                    primitives=prims)
    assert report.result_label == "hardware-unavailable"
    assert any("no available place" in e for e in report.evidence)


def test_report_includes_test_description():
    # The report should say what the test actually checks, pulled from the
    # test's docstring via an injected describer — so "passed" is not opaque.
    prims = FakePrimitives(outcomes={"pr": "passed"})
    report = compare.run_base_vs_pr(
        _cs(), "adsp/u-boot-watchdog", ["sc598", "ezkit"],
        primitives=prims, mode="head-only",
        test_describer=lambda name: "Boots U-Boot and asserts the watchdog "
                                    "device binds and probes. Non-destructive.")
    assert "watchdog device binds and probes" in report.test_description
    # first sentence folded into the human summary
    assert "Boots U-Boot" in report.human_summary


def test_report_test_description_defaults_empty_without_describer():
    prims = FakePrimitives(outcomes={"pr": "passed"})
    report = compare.run_base_vs_pr(_cs(), "adsp/u-boot", ["sc598", "ezkit"],
                                    primitives=prims, mode="head-only")
    assert report.test_description == ""


def test_base_expired_falls_back_to_head_only():
    # base-vs-PR requested, but the base image is unavailable (CI artifacts
    # expired) while the PR head image is live. The run must NOT collapse to
    # build-artifact-unavailable — the head is runnable, so fall back to a
    # head-only run and report it honestly.
    prims = FakePrimitives(image_fails_on="basesha", outcomes={"pr": "passed"})
    report = compare.run_base_vs_pr(_cs(), "adsp/u-boot", ["sc598", "ezkit"],
                                    primitives=prims)
    assert report.result_label == "validation-only"
    assert report.base is None
    assert report.pr.state == "passed"
    assert report.transition is None
    assert prims.released == ["tok-1"]
    # PR head still ran; base was never run.
    assert ("run", "prsha") in prims.calls
    assert ("run", "basesha") not in prims.calls
    # Honest about the missing base comparison.
    assert "base" in report.human_summary.lower()


def test_head_missing_is_still_build_artifact_unavailable():
    # If the PR head image itself is unavailable, there is nothing to run —
    # that is a genuine build-artifact-unavailable, not a head-only fallback.
    prims = FakePrimitives(image_fails_on="prsha")
    report = compare.run_base_vs_pr(_cs(), "adsp/u-boot", ["sc598", "ezkit"],
                                    primitives=prims)
    assert report.result_label == "build-artifact-unavailable"
    assert prims.released == ["tok-1"]
