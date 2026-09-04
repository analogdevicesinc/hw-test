"""Render a CompareReport into PR-ready markdown for engineer review.

Pure and deterministic: a JSON-able ``CompareReport`` dict in (exactly what
the ``run_base_vs_pr`` tool returns), a markdown string out. No network, no
I/O, and — by project rule — no emoji anywhere; verdicts are plain-text
tokens. This module makes no judgment beyond what the report already carries;
it never claims a change is correct or broken, only formats the observed
state delta.
"""

from __future__ import annotations

_MAX_EVIDENCE_LINES = 30

# result_label -> what actually happened, for the no-run labels where no
# hardware ran and there is no base/PR state to speak of.
_NO_RUN_LABELS = {
    "hardware-unavailable",
    "build-artifact-unavailable",
    "test-design-requires-user-input",
}

# Human-readable transition text keyed by the enum value on the wire.
_TRANSITION_TEXT = {
    "pass->pass": "pass -> pass",
    "pass->fail": "pass -> fail",
    "fail->pass": "fail -> pass",
    "fail->fail": "fail -> fail",
    "inconclusive": "inconclusive",
}


def _verdict_token(report: dict) -> str:
    """A plain-text verdict for the title, derived from the report.

    Base-vs-PR runs map their transition to PASS/REGRESSION/FIX/STILL-BROKEN/
    INCONCLUSIVE. Head-only runs (no transition) report the PR state as
    PASS/FAIL. No-run labels report NO-RUN.
    """
    if report.get("result_label") in _NO_RUN_LABELS:
        return "NO-RUN"
    transition = report.get("transition")
    if transition:
        return {
            "pass->pass": "PASS",
            "pass->fail": "REGRESSION",
            "fail->pass": "FIX",
            "fail->fail": "STILL-BROKEN",
            "inconclusive": "INCONCLUSIVE",
        }.get(transition, "INCONCLUSIVE")
    # Head-only (single) run: report the PR-head state directly.
    pr = report.get("pr") or {}
    state = pr.get("state")
    if state == "passed":
        return "PASS"
    if state == "failed":
        return "FAIL"
    return "INCONCLUSIVE"


def _evidence_block(evidence) -> str:
    lines = list(evidence or [])[:_MAX_EVIDENCE_LINES]
    if not lines:
        return ""
    body = "\n".join(lines)
    return f"**Evidence:**\n```\n{body}\n```\n\n"


def render(report: dict) -> str:
    """Return PR-ready markdown for a CompareReport dict."""
    test_name = report.get("test_name") or "(unnamed test)"
    board = report.get("board") or "(no board)"
    verdict = _verdict_token(report)

    parts = [f"### hw-test: {test_name} on {board} -- {verdict}\n\n"]

    # Result line: the transition for a base-vs-PR run, else the human summary
    # (head-only / no-run cases already phrase themselves honestly).
    transition = report.get("transition")
    if transition and verdict != "NO-RUN":
        parts.append(f"**Result:** {_TRANSITION_TEXT.get(transition, transition)}\n")
    else:
        parts.append(f"**Result:** {report.get('human_summary', '').strip()}\n")

    parts.append(f"**PR:** {report.get('changeset_ref', '')}\n\n")

    # What ran, so the reader knows the shape of the check.
    what = []
    if report.get("base") and report.get("pr"):
        what.append("- Base (merge-base) and PR head on the same board")
    elif report.get("pr"):
        what.append("- PR head only (no base comparison)")
    if report.get("test_description"):
        what.append(f"- Test: {report['test_description'].strip()}")
    if what:
        parts.append("**What ran:**\n" + "\n".join(what) + "\n\n")

    parts.append(_evidence_block(report.get("evidence")))

    parts.append(
        "_Automated hw-test run. Reports only the state delta between the "
        "runs; makes no claim that the change is correct or broken._\n")

    return "".join(parts)
