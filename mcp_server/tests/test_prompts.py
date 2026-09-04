"""Tests for prompts: the subagent-driving prompt text builders."""

from mcp_server import prompts


def test_classify_changes_names_tools_and_rules():
    text = prompts.classify_changes()
    # Must steer the classifier through the server's determinism gate.
    assert "get_classification_evidence" in text
    assert "submit_classification" in text
    # Must forbid free-form subsystems and unbacked evidence.
    assert "evidence_files" in text
    assert "Subsystem" in text or "subsystem" in text


def test_inspect_and_plan_orders_the_five_tools():
    text = prompts.inspect_and_plan()
    for tool in ("inspect_pr", "inspect_local", "get_classification_evidence",
                 "submit_classification", "create_test_plan"):
        assert tool in text
    # inspection precedes classification precedes planning
    assert text.index("inspect_pr") < text.index("submit_classification")
    assert text.index("submit_classification") < text.index("create_test_plan")


def test_role_guide_known_roles():
    for role in ("inspector", "classifier", "planner"):
        text = prompts.role_guide(role)
        assert role in text.lower()
        assert text.strip()


def test_role_guide_unknown_role_lists_valid_roles():
    text = prompts.role_guide("wizard")
    assert "inspector" in text
    assert "classifier" in text
    assert "planner" in text


def test_prompts_do_not_overstate_confidence():
    # Honesty rule: prompts must not tell the agent to assert pass/fail.
    for text in (prompts.classify_changes(), prompts.inspect_and_plan()):
        lowered = text.lower()
        assert "verdict" not in lowered
        assert "guarantee" not in lowered


def test_base_vs_pr_run_prompt_orders_guard_before_run():
    text = prompts.base_vs_pr_run()
    assert "run_base_vs_pr" in text
    assert "reuse" in text
    # guard mentioned before the tool call
    assert text.lower().index("reuse") < text.index("run_base_vs_pr")


def test_base_vs_pr_run_prompt_is_honest():
    text = prompts.base_vs_pr_run().lower()
    assert "verdict" not in text
    assert "guarantee" not in text


def test_role_guide_hw_runner_known():
    text = prompts.role_guide("hw-runner")
    assert "hw-runner" in text.lower() or "run_base_vs_pr" in text
    assert text.strip()


def test_test_writer_prompt_mentions_submit_and_review():
    text = prompts.test_writer()
    assert "submit_test" in text
    # authored test is unrun, awaits human review/promotion
    low = text.lower()
    assert "review" in low or "promote" in low or "staged" in low


def test_test_writer_prompt_is_honest():
    low = prompts.test_writer().lower()
    assert "verdict" not in low
    assert "guarantee" not in low
    # never claim the authored (unrun) test passes
    assert "passes" not in low


def test_role_guide_test_writer_known():
    text = prompts.role_guide("test-writer")
    assert "test-writer" in text.lower() or "submit_test" in text
    assert text.strip()
    assert "test-writer" in prompts._VALID_ROLES


def test_test_pr_prompt_gates_author_and_run_on_user_approval():
    text = prompts.test_pr()
    low = text.lower()
    # Drives the whole check-first flow.
    assert "inspect_pr" in text
    assert "create_test_plan" in text
    # Gate A: no reusable test -> ASK before authoring, never auto-write.
    assert "submit_test" in text
    assert "ask" in low
    # Gate B: ASK before running, never auto-run.
    assert "run_base_vs_pr" in text
    # Both gates require explicit approval.
    assert "approv" in low or "permission" in low
    # Ordering: check/plan -> author gate -> run gate.
    assert text.index("create_test_plan") < text.index("submit_test")
    assert text.index("submit_test") < text.index("run_base_vs_pr")


def test_test_pr_prompt_is_honest():
    low = prompts.test_pr().lower()
    assert "verdict" not in low
    assert "guarantee" not in low


def test_test_pr_in_valid_roles_and_role_guide():
    assert "test-pr" in prompts._VALID_ROLES
    text = prompts.role_guide("test-pr")
    assert text.strip()
    assert "test-pr" in text.lower() or "run_base_vs_pr" in text


def test_test_pr_prompt_uses_datasheets_as_optional_authoring_context():
    text = prompts.test_pr()
    low = text.lower()
    # The author phase consults datasheet docs to ground the test.
    assert "list_datasheets" in text
    # It sits inside authoring: after the write-approval, before submit_test.
    assert text.index("list_datasheets") < text.index("submit_test")
    # It is auxiliary context, never a gate: authoring proceeds without a doc.
    assert "optional" in low or "without" in low


def test_test_pr_prompt_narrates_progress_and_renders_summary():
    text = prompts.test_pr()
    low = text.lower()
    # Tells the agent to narrate a short status line after phases.
    assert "one line" in low or "one-line" in low or "short status" in low
    # Ends with a single PR-ready summary via render_pr_summary.
    assert "render_pr_summary" in text
    # The summary comes after the run, so it reflects the outcome.
    assert text.index("run_base_vs_pr") < text.index("render_pr_summary")
    # No emoji in the guidance the agent is handed.
    assert text.isascii()
