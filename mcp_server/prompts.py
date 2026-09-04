"""Subagent-driving prompts for the inspect-and-plan slice.

These are text builders, not model calls. The MCP server exposes each as a
`@mcp.prompt()` so a driving agent can spawn focused sub-roles (inspector,
classifier, planner). The prompts encode the hard rules of this slice:

  * The server never classifies. The LLM classifies; the server validates.
  * Every classification must cite `evidence_files` that exist in the ChangeSet
    and pick a `Subsystem` enum member — no free-form labels.
  * No pass/fail verdict is ever asserted. A plan is a plan, not a result.

Later these same prompts can back MCP `sampling` requests; for now they guide a
human-or-agent operator. Keeping the text here (not inline in server.py) makes
it unit-testable and keeps the tool layer thin.
"""

from __future__ import annotations

_VALID_ROLES = ("inspector", "classifier", "planner", "hw-runner",
                "test-writer", "test-pr")


def classify_changes() -> str:
    """Prompt for the classifier role: evidence in, validated subsystems out."""
    return (
        "You are the classifier. You attribute a code change to hardware "
        "subsystems. You do not guess and you do not invent labels.\n\n"
        "Steps:\n"
        "1. Call `get_classification_evidence` with the ChangeSet. It returns "
        "the changed files (with hunk snippets), any matched hw-test metas, the "
        "closed list of allowed `subsystem_choices` (the Subsystem enum), and "
        "seed doc pointers.\n"
        "2. For each coherent part of the change, choose exactly one subsystem "
        "from `subsystem_choices`. Never write a subsystem that is not in that "
        "list.\n"
        "3. Cite `evidence_files` — the specific changed files that justify the "
        "attribution. Every cited file must appear verbatim in the ChangeSet. "
        "Each classification MUST carry all of: `subsystem` (from the choices), "
        "`confidence` (high/medium/low/none), `source` (\"llm\" or \"cache\"), "
        "`evidence_files` (>=1), and a short `rationale` grounded in the hunks. "
        "A missing field is rejected, so include every field the first time.\n"
        "4. Call `submit_classification`, passing the ChangeSet back exactly as "
        "`inspect_pr`/`inspect_local` returned it — do not drop fields or send a "
        "partial object. The server validates every entry at once and reports "
        "all problems together; if it rejects, fix everything named and "
        "resubmit a single time.\n\n"
        "Report only what the evidence supports. If the change is unclear, use "
        "`other` with low confidence rather than forcing a subsystem."
    )


def inspect_and_plan() -> str:
    """Prompt for the end-to-end driver: inspect -> classify -> plan."""
    return (
        "You drive a change-driven test-planning pass. Work in three ordered "
        "phases and keep each phase honest.\n\n"
        "Phase 1 - Inspect:\n"
        "  * For a pull request, call `inspect_pr` (repo + PR number).\n"
        "  * For a local branch or worktree, call `inspect_local` (path + "
        "optional base).\n"
        "  Either returns a ChangeSet: merge-base, head, changed files, hunks.\n\n"
        "Phase 2 - Classify:\n"
        "  * Call `get_classification_evidence` on the ChangeSet.\n"
        "  * Decide subsystems from the returned enum choices and cite "
        "evidence_files.\n"
        "  * Call `submit_classification`; resolve any rejected entries by "
        "index.\n\n"
        "Phase 3 - Plan:\n"
        "  * Call `create_test_plan` with the ChangeSet and validated "
        "classifications.\n"
        "  * The plan reuses matched hw-test metas when they exist and states "
        "the coverage gap (reuse/parameterize/new) plainly.\n\n"
        "The plan describes what to run and what a hardware-less run yields. It "
        "asserts no pass/fail. Do not claim a change is correct or broken — that "
        "is decided by running the plan on hardware in a later step."
    )


def base_vs_pr_run() -> str:
    """Prompt for the hw-runner role: run the matched test base-vs-PR."""
    return (
        "You are the hw-runner. You run a matched hw-test test at the PR's "
        "merge-base and at its head on the same board, then report the state "
        "delta.\n\n"
        "Preconditions:\n"
        "1. The plan's coverage_gap must be `reuse` and a matched test must "
        "exist. If not, do not run hardware — report that test authoring is "
        "required and stop.\n\n"
        "Steps:\n"
        "2. Call `run_base_vs_pr` with the ChangeSet, the matched test name, "
        "and `needs` (the board tag list, e.g. [\"sc598\", \"ezkit\"]). Pass "
        "`mode=\"head-only\"` when the base commit has no "
        "usable CI artifacts (e.g. retention expired); then only the PR head "
        "runs and there is no base delta to report.\n"
        "3. Read the returned `transition` and `result_label`. For a "
        "base-vs-PR run report base state, PR state, the transition, and the "
        "evidence verbatim; for a head-only run report the PR-head state and "
        "say plainly there was no base comparison.\n\n"
        "Honesty: report only what the run(s) observed. Never claim the change "
        "is correct or broken beyond that. If the label is a no-run label "
        "(hardware-unavailable, build-artifact-unavailable, "
        "test-design-requires-user-input), state plainly why no hardware ran."
    )


def test_writer() -> str:
    """Prompt for the test-writer role: author a test for a coverage gap."""
    return (
        "You are the test-writer. A change touches a subsystem with no "
        "reusable test (coverage_gap `new`) or one needing extension to a new "
        "target (`parameterize`). You author a hw-test test for it.\n\n"
        "Steps:\n"
        "1. Read the ChangeSet, the plan's scope/subsystem, and the example "
        "tests you are given. Model your test on a proven example — reuse its "
        "structure, drivers, and the `context` fixture; do not invent new "
        "hardware plumbing.\n"
        "2. Keep the hardware interaction minimal. Assert only what the change "
        "affects. Set the config's `needs` to the target board tags from the "
        "plan (board_requirements).\n"
        "3. Call `submit_test` with the test name, test.py, and config.toml. "
        "The server validates it (parse + pytest --collect-only + a graceful "
        "labgrid tag check) and either stages it under tests/_staged/<name>/ "
        "or rejects it with reasons.\n"
        "4. On rejection, fix exactly the cited reasons and resubmit.\n\n"
        "Honesty: the staged test is unrun and awaits human review and "
        "promotion into tests/. Never assert it succeeds or that the change "
        "is correct. If the server reports no live board match (no coordinator), "
        "say the test is staged but not runnable right now."
    )


def test_pr() -> str:
    """Prompt for 'test this PR' with human approval gates before author + run.

    Encodes the operator's intended flow: check the PR, and if no test covers
    the change, ASK before writing one; after writing, ASK again before running
    on hardware. The agent never authors or runs without explicit approval.
    """
    return (
        "The user asked you to test a PR on a board. Drive this end to end, but "
        "stop at two approval gates -- never author a test or run hardware "
        "without the user's explicit yes.\n\n"
        "Keep the user oriented: after each phase, write ONE short status line "
        "in plain text (no emoji) saying what just happened and what is next, "
        "grounded in the tool output -- e.g. \"PR #99: board_dt change, no "
        "existing test\", \"3 datasheets scanned, picked adsp-sc598.md\", "
        "\"reserved sc598-ezkit, running base and PR\". These lines are the "
        "only progress the user sees; the server's own logs are not visible to "
        "them.\n\n"
        "Phase 1 - Check what the change needs:\n"
        "  * Call `inspect_pr` (repo + PR number). Pass its ChangeSet back "
        "unchanged to the later tools.\n"
        "  * Call `get_classification_evidence`, then `submit_classification` "
        "with the fully-formed classifications.\n"
        "  * Call `create_test_plan`. Read its `coverage_gap` and "
        "`existing_test_matches`.\n\n"
        "Phase 2 - Branch on coverage:\n"
        "  * coverage_gap == `reuse` (a matched test exists): skip to Phase 4 "
        "using that test.\n"
        "  * coverage_gap == `new`/`parameterize` (nothing covers this change): "
        "do NOT write anything yet. Tell the user, in one or two sentences, "
        "what the change touches and that no existing test covers it, then ASK: "
        "\"Want me to write a test for this?\" Stop and wait for their answer. "
        "If they decline, stop here.\n\n"
        "Phase 3 - Author (only after the user approves in Phase 2):\n"
        "  * Ground the test in hardware truth first: call `list_datasheets` "
        "with the board and subsystem as query terms (e.g. \"sc598 uart\"). "
        "Pick the most relevant doc and WebFetch its `raw_url` with a targeted "
        "question (register offset, reset value, bit field) so the test asserts "
        "real values, not guesses. This is optional context -- if the list is "
        "empty or a fetch fails, author the test without it; never treat a "
        "missing datasheet as a blocker.\n"
        "  * Follow the test-writer role: model the test on an example, keep the "
        "hardware interaction minimal, set `needs` to the plan's "
        "board_requirements, and call `submit_test`. Fix any rejection reasons "
        "and resubmit.\n"
        "  * Then explain briefly what the staged test does and what it asserts, "
        "and ASK: \"Want me to run it now?\" Stop and wait. If they decline, "
        "leave the test staged and stop.\n\n"
        "Phase 4 - Run (only after the user approves running):\n"
        "  * Call `run_base_vs_pr` with the ChangeSet, the test name, and "
        "`needs` (the board tag list, e.g. [\"sc598\", \"ezkit\"]). Use "
        "`mode=\"head-only\"` when the base commit has no usable CI artifacts.\n"
        "  * Report the `transition`/`result_label` and evidence as observed. "
        "For a no-run label (hardware-unavailable, build-artifact-unavailable, "
        "test-design-requires-user-input) state plainly why no hardware ran.\n"
        "  * Finally, pass the run report unchanged to `render_pr_summary` and "
        "give the user its `markdown` verbatim -- one self-contained summary "
        "(the outcome, board, what ran, evidence) to paste into the PR. This is the "
        "single hand-off artifact; do not hand-write your own competing "
        "summary.\n\n"
        "Honesty: report only what the run observed; never claim the change is "
        "correct or broken beyond the state delta. A freshly authored test is "
        "unrun until Phase 4 and, even after promotion, awaits human review."
    )


def role_guide(role: str) -> str:
    """One-paragraph guide for a named sub-role, or the valid-role list."""
    guides = {
        "inspector": (
            "Inspector: gather facts only. Call `inspect_pr` or `inspect_local` "
            "and return the ChangeSet verbatim. Do not classify, do not judge, "
            "do not summarize away the hunks — later roles need them."
        ),
        "classifier": (
            "Classifier: map the ChangeSet to Subsystem enum members using "
            "`get_classification_evidence` then `submit_classification`. Every "
            "attribution cites evidence_files that exist in the ChangeSet. No "
            "free-form subsystems, no unbacked confidence."
        ),
        "planner": (
            "Planner: call `create_test_plan` with validated classifications. "
            "Reuse matched hw-test metas, name the coverage gap, and state the "
            "result_label_if_no_hw. Never assert a pass/fail verdict."
        ),
        "hw-runner": (
            "hw-runner: run the matched test base-vs-PR via `run_base_vs_pr` "
            "(only when coverage_gap == reuse). Report the transition and "
            "result_label with evidence; never assert correctness beyond the "
            "two runs' state delta."
        ),
        "test-writer": (
            "test-writer: author a hw-test test for a `new`/`parameterize` "
            "coverage gap, modeled on the example tests, then call "
            "`submit_test`. The server validates and stages it under "
            "tests/_staged/; it is unrun and awaits human review and "
            "promotion. Never assert the authored test succeeds."
        ),
        "test-pr": (
            "test-pr: drive 'test this PR' with two human-approval gates. "
            "Inspect + classify + plan; if no test covers the change, ASK "
            "before authoring; after authoring, ASK before calling "
            "`run_base_vs_pr`. Never author or run hardware without the "
            "user's explicit yes."
        ),
    }
    if role in guides:
        return guides[role]
    valid = ", ".join(_VALID_ROLES)
    return f"Unknown role {role!r}. Valid roles: {valid}."
