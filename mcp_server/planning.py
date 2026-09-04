"""Planning: classification evidence, validation, and test-plan synthesis.

The server never classifies. ``get_classification_evidence`` gathers deterministic
facts (changed files, matching test metas, the Subsystem enum choices, seed doc
pointers) for the driving LLM. ``validate_classifications`` is the determinism
gate. ``create_test_plan`` turns validated classifications into an honest,
verdict-free plan.

Test metas are read through ``hw_tests.collect`` (single source of truth); they
are injectable so unit tests use fixtures instead of the repo's real tests/.
"""

from __future__ import annotations

from mcp_server import knowledge as knowledge_mod
from mcp_server import review
from mcp_server.models import (
    _CONFIDENCE,
    _SOURCES,
    ChangeSet,
    Classification,
    ClassificationEvidence,
    DocRef,
    Subsystem,
    TestPlan,
)


def _load_metas():
    # Imported lazily so unit tests that pass metas= never import hw_tests.
    from hw_tests.collect import load_test_metas
    return load_test_metas()


def _basename(repo: str) -> str:
    """Normalize 'owner/u-boot' or 'u-boot' to the bare repo name."""
    return repo.rsplit("/", 1)[-1] if repo else repo


def _meta_matches_repo_paths(meta: dict, repo_basename: str,
                             changed_paths: list[str]) -> bool:
    from hw_tests.collect import paths_match
    for repo_rule in meta.get("repository", []):
        if _basename(repo_rule.get("name", "")) != repo_basename:
            continue
        if paths_match(changed_paths, repo_rule.get("path", "")):
            return True
    return False


def get_classification_evidence(
    changeset: ChangeSet,
    metas: list[dict] | None = None,
    knowledge: knowledge_mod.Knowledge | None = None,
) -> ClassificationEvidence:
    """Gather deterministic classification evidence for the classifier role."""
    metas = metas if metas is not None else _load_metas()
    store = knowledge if knowledge is not None else knowledge_mod.Knowledge()

    repo_basename = _basename(changeset.repo)
    changed_paths = changeset.file_paths()

    matched_metas = [
        meta["_uid"] for meta in metas
        if _meta_matches_repo_paths(meta, repo_basename, changed_paths)
    ]

    # Seed doc refs from any reviewed cache entries that match a changed file.
    seed_doc_refs: list[DocRef] = []
    seen = set()
    for path in changed_paths:
        hit = store.lookup(repo=repo_basename, path=path)
        if hit and hit.doc_ref is not None:
            key = (hit.doc_ref.repo, hit.doc_ref.query)
            if key not in seen:
                seen.add(key)
                seed_doc_refs.append(hit.doc_ref)

    return ClassificationEvidence(
        repo=changeset.repo,
        files=list(changeset.files),
        matched_metas=matched_metas,
        subsystem_choices=[s.value for s in Subsystem],
        seed_doc_refs=seed_doc_refs,
    )


def _coerce_classification(raw, changeset_paths: set[str], index: int):
    """Return ``(classification, issues)`` for one raw entry.

    Collects EVERY problem with the entry into ``issues`` instead of raising on
    the first one, so the caller can report all fields at once and the
    classifier fixes them in a single resubmit. ``classification`` is None when
    ``issues`` is non-empty.
    """
    if isinstance(raw, Classification):
        return raw, []
    if not isinstance(raw, dict):
        return None, [
            f"classification at index {index} must be a dict or "
            f"Classification, got {type(raw).__name__}"
        ]

    issues = []

    subsystem = raw.get("subsystem")
    subsystem_obj = None
    if isinstance(subsystem, Subsystem):
        subsystem_obj = subsystem
    else:
        try:
            subsystem_obj = Subsystem(subsystem)
        except ValueError:
            issues.append(f"unknown subsystem {subsystem!r}")

    confidence = raw.get("confidence", "")
    if confidence not in _CONFIDENCE:
        issues.append(
            f"confidence must be one of {sorted(_CONFIDENCE)}, got "
            f"{confidence!r}")

    source = raw.get("source", "")
    if source not in _SOURCES:
        issues.append(
            f"source must be one of {sorted(_SOURCES)}, got {source!r}")

    evidence_files = list(raw.get("evidence_files", []))
    if not evidence_files:
        issues.append("at least one evidence_file is required")
    else:
        missing = [f for f in evidence_files if f not in changeset_paths]
        if missing:
            issues.append(f"evidence_files not in changeset: {missing}")

    if issues:
        return None, [f"classification at index {index}: {msg}"
                      for msg in issues]

    return Classification(
        subsystem=subsystem_obj,
        confidence=confidence,
        evidence_files=evidence_files,
        source=source,
        rationale=raw.get("rationale", ""),
    ), []


def create_test_plan(
    changeset: ChangeSet,
    classifications: list[Classification],
    evidence: ClassificationEvidence,
    metas: list[dict] | None = None,
    board: str | None = None,
) -> TestPlan:
    """Turn validated classifications into an honest, verdict-free TestPlan.

    Reuses matched test metas (``evidence.matched_metas``) for candidate
    capabilities and board requirements. The coverage gap is derived, not
    guessed: matched metas -> reuse, none -> new. No pass/fail is asserted; the
    ``result_label_if_no_hw`` states plainly what a hardware-less run yields.
    """
    metas = metas if metas is not None else _load_metas()
    by_uid = {m.get("_uid"): m for m in metas}

    matched = list(evidence.matched_metas)

    # Candidate capabilities + board needs come straight from matched metas —
    # single source of truth, never invented here.
    capabilities: list[str] = []
    board_needs: list[str] = []
    for uid in matched:
        meta = by_uid.get(uid, {})
        for cap in meta.get("capabilities", {}).get("provides", []):
            if cap not in capabilities:
                capabilities.append(cap)
        for need in meta.get("needs", []):
            if need not in board_needs:
                board_needs.append(need)

    if board and board not in board_needs:
        board_needs.insert(0, board)

    coverage_gap = "reuse" if matched else "new"
    result_label = ("hardware-unavailable" if matched
                    else "test-design-requires-user-input")

    doc_refs = review.doc_refs_for(classifications, evidence, board=board)

    subsystems = sorted({c.subsystem.value for c in classifications})
    scope = ", ".join(subsystems)

    changeset_ref = f"{changeset.repo}@{changeset.head_sha}"
    if changeset.pr_number is not None:
        changeset_ref += f" (PR #{changeset.pr_number})"

    if matched:
        expected = (
            f"Run {', '.join(matched)} against merge-base "
            f"{changeset.merge_base_sha} and PR head {changeset.head_sha}; "
            f"compare the two runs for regressions in: {scope}."
        )
    else:
        expected = (
            f"No existing hw-test covers {scope}; a new or parameterized test "
            f"is required before a base-vs-PR comparison is meaningful."
        )

    human_summary = (
        f"{scope or 'unclassified'} change in {changeset.repo}; "
        f"{'reuse ' + ', '.join(matched) if matched else 'no existing test match'}."
    )

    return TestPlan(
        changeset_ref=changeset_ref,
        classifications=list(classifications),
        scope=scope,
        candidate_capabilities=capabilities,
        existing_test_matches=matched,
        coverage_gap=coverage_gap,
        doc_refs=doc_refs,
        expected_base_vs_pr=expected,
        board_requirements=board_needs,
        result_label_if_no_hw=result_label,
        human_summary=human_summary,
    )


def validate_classifications(changeset: ChangeSet, raw_classifications
                             ) -> list[Classification]:
    """Validate LLM/cache classifications against schema and the ChangeSet.

    Rejects free-form or unbacked entries: every classification must use a
    ``Subsystem`` enum member, a known confidence and source, and cite at least
    one ``evidence_file`` that actually exists in ``changeset``. Errors name the
    offending index so the classifier can fix exactly that entry.
    """
    changeset_paths = set(changeset.file_paths())
    validated = []
    all_issues = []
    for i, raw in enumerate(raw_classifications):
        classification, issues = _coerce_classification(
            raw, changeset_paths, i)
        if issues:
            all_issues.extend(issues)
        else:
            validated.append(classification)
    if all_issues:
        raise ValueError("; ".join(all_issues))
    return validated
