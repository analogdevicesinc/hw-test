"""Base-vs-PR comparison: two sequential runs on one board, then a state diff.

This module never touches hardware. It depends only on an injected Primitives
interface. It asserts nothing beyond the observed state delta between the two
runs, and maps that delta to an existing honest result label.
"""

from __future__ import annotations

import difflib
from typing import Protocol

from mcp_server.orchestration import imaging
from mcp_server import serde
from mcp_server.models import CompareReport, ImageRef, RunOutcome, Transition

_MAX_DIFF_LINES = 40


def diff_state(base: RunOutcome, pr: RunOutcome) -> Transition:
    if base.state == "inconclusive" or pr.state == "inconclusive":
        return Transition.INCONCLUSIVE
    pair = (base.state, pr.state)
    return {
        ("passed", "passed"): Transition.STABLE_PASS,
        ("passed", "failed"): Transition.REGRESSION,
        ("failed", "passed"): Transition.FIX,
        ("failed", "failed"): Transition.STILL_BROKEN,
    }[pair]


def log_diff(base: RunOutcome, pr: RunOutcome) -> list[str]:
    diff = difflib.unified_diff(
        base.log_tail.splitlines(), pr.log_tail.splitlines(),
        fromfile="base", tofile="pr", lineterm="",
    )
    return list(diff)[:_MAX_DIFF_LINES]


def label_for(transition: Transition) -> tuple[str, bool]:
    if transition == Transition.FIX:
        return "coverage-improvement", False
    if transition == Transition.INCONCLUSIVE:
        return "inconclusive", False
    if transition == Transition.REGRESSION:
        return "validation-only", True
    return "validation-only", False


class Primitives(Protocol):
    def reserve(self, needs) -> str: ...
    def resolve_image(self, repo, sha, role) -> "ImageRef": ...
    def run(self, test_name, token, image) -> str: ...
    def wait(self, run_id, ref) -> RunOutcome: ...
    def release(self, token) -> None: ...


def _no_hw_summary(label, changeset, test_name):
    reasons = {
        "test-design-requires-user-input":
            f"No reusable test for {changeset.repo}@{changeset.head_sha}; "
            f"authoring is a separate step.",
        "hardware-unavailable":
            f"No board available to run {test_name}.",
        "build-artifact-unavailable":
            f"Could not obtain an image for {test_name} (artifact miss and "
            f"build failed).",
    }
    return reasons.get(label, label)


def _first_sentence(text):
    """First sentence of a test docstring, for folding into the summary."""
    text = " ".join(text.split())
    if not text:
        return ""
    head, _, _ = text.partition(". ")
    return head if head.endswith(".") else head + "."


def _with_description(summary, description):
    """Prefix the summary with what the test checks, when we know it."""
    if not description:
        return summary
    return f"{summary} Test: {_first_sentence(description)}"


def _no_hw_report(changeset, test_name, board, label, evidence=None,
                  description=""):
    summary = _no_hw_summary(label, changeset, test_name)
    if evidence:
        # Fold the concrete reason (reserve error, build log tail) into the
        # human summary so the reason is visible without digging into evidence.
        summary = f"{summary} ({evidence[0]})"
    return CompareReport(
        changeset_ref=f"{changeset.repo}@{changeset.head_sha}",
        test_name=test_name, board=board, base=None, pr=None, transition=None,
        regressed=False, result_label=label, evidence=evidence or [],
        human_summary=summary, test_description=description,
    )


def _head_only_report(cs, test_name, board, pr, description="",
                      base_fallback_reason="") -> CompareReport:
    """Report a single PR-head run: honest pass/fail, no base delta.

    ``base_fallback_reason`` is set when a base-vs-PR run degraded to head-only
    because the base image was unavailable; it names why there is no base
    comparison instead of silently dropping it.
    """
    if base_fallback_reason:
        summary = (f"{test_name} on {board}: PR head {pr.state} (head-only "
                   f"run; base image unavailable, no base comparison: "
                   f"{base_fallback_reason}).")
    else:
        summary = (f"{test_name} on {board}: PR head {pr.state} (head-only run; "
                   f"no base comparison).")
    return CompareReport(
        changeset_ref=f"{cs.repo}@{cs.head_sha}", test_name=test_name,
        board=board, base=None, pr=pr, transition=None, regressed=False,
        result_label="validation-only", evidence=pr.log_tail.splitlines()[:_MAX_DIFF_LINES],
        human_summary=_with_description(summary, description),
        test_description=description,
    )


def run_base_vs_pr(changeset, test_name, needs, *, primitives,
                   coverage_gap="reuse", role="u-boot",
                   mode="base-vs-pr", test_describer=None) -> CompareReport:
    cs = serde.changeset_from_dict(changeset)

    # The caller supplies the labgrid tags to match directly (e.g.
    # ["sc598", "ezkit"]); a board label for the report is just those joined.
    if isinstance(needs, str):
        needs = [needs]
    board = "+".join(needs) if needs else None

    # What the test checks, so the report explains the verdict. Optional: an
    # injected describer maps test_name -> docstring; failures are non-fatal.
    description = ""
    if test_describer and test_name:
        try:
            description = test_describer(test_name) or ""
        except Exception:
            description = ""

    # 0. Guard: a reusable test is required.
    if coverage_gap != "reuse" or not test_name:
        return _no_hw_report(cs, test_name, board,
                             "test-design-requires-user-input",
                             description=description)

    # 1. Reserve. Surface the reservation failure text so an unavailable-board
    #    result says WHY (no tag match vs. every match held, and by whom).
    try:
        token = primitives.reserve(needs)
    except RuntimeError as exc:
        return _no_hw_report(cs, test_name, board, "hardware-unavailable",
                             evidence=[str(exc)], description=description)

    head_only = mode == "head-only"
    base_fallback_reason = ""
    try:
        # 2. Resolve the PR-head image first. If the head itself is
        #    unavailable there is nothing to run — a genuine
        #    build-artifact-unavailable.
        try:
            pr_img = primitives.resolve_image(cs.repo, cs.head_sha, role)
        except imaging.BuildError as exc:
            return _no_hw_report(cs, test_name, board,
                                "build-artifact-unavailable",
                                evidence=[exc.log_tail], description=description)

        # 3. Resolve the base image (unless head-only). If ONLY the base is
        #    unavailable (e.g. CI retention expired) the head is still
        #    runnable, so degrade to a head-only run rather than reporting
        #    the whole comparison unavailable — the head image exists.
        base_img = None
        if not head_only:
            try:
                base_img = primitives.resolve_image(cs.repo,
                                                    cs.merge_base_sha, role)
            except imaging.BuildError as exc:
                head_only = True
                base_fallback_reason = exc.log_tail

        # 4. Run base (unless head-only), then 5. run PR — same token.
        base = (None if head_only else
                primitives.wait(primitives.run(test_name, token, base_img),
                                "base"))
        pr = primitives.wait(primitives.run(test_name, token, pr_img), "pr")
    finally:
        # 6. Always release.
        primitives.release(token)

    if head_only:
        return _head_only_report(cs, test_name, board, pr, description,
                                 base_fallback_reason)

    # 6. Diff + report.
    transition = diff_state(base, pr)
    label, regressed = label_for(transition)
    evidence = log_diff(base, pr)
    summary = (f"{test_name} on {board}: base {base.state}, PR {pr.state} "
               f"({transition.value}).")
    return CompareReport(
        changeset_ref=f"{cs.repo}@{cs.head_sha}", test_name=test_name,
        board=board, base=base, pr=pr, transition=transition,
        regressed=regressed, result_label=label, evidence=evidence,
        human_summary=_with_description(summary, description),
        test_description=description,
    )
