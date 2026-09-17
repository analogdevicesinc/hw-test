"""Test-writer slice: author a test for a coverage gap, validate, stage it.

Fires when a change's ``coverage_gap`` is ``new`` or ``parameterize`` (the case
Slice 1 stops on). An LLM authors ``test.py``; this module is the server-side
gate — parse + collect + graceful tag-resolve — and the stager. It never writes
live ``tests/``, never runs the test, never flashes hardware. A human promotes
the staged artifact.

The collector (pytest --collect-only), tag_resolver (labgrid place tags), and
staging_root are injected so every path is unit-testable with no hardware and no
network. Board/needs come from the PR/plan and live labgrid tags, not from a
hand-maintained table; tag-resolve is a convenience annotation, never a gate.
"""

from __future__ import annotations

import ast
import difflib
import json
import tempfile
import tomllib
from pathlib import Path

from mcp_server import serde
from mcp_server.models import StagedTest, ValidationResult


def _parse_needs(config_toml: str) -> list[str]:
    """Best-effort read of the needs list; never raises on bad config."""
    try:
        data = tomllib.loads(config_toml)
    except tomllib.TOMLDecodeError:
        return []
    needs = data.get("needs", [])
    return [str(n) for n in needs] if isinstance(needs, list) else []


def validate_test(name, test_py, config_toml, *, existing_names,
                  collector, tag_resolver, collect_root=None) -> ValidationResult:
    """Gate a proposed test: parse + collect + graceful tag-resolve.

    ``collect_root`` places the throwaway collection dir inside the repo
    ``tests/`` tree so the root ``conftest.py``, pyproject markers, and the
    ``context`` fixture apply — otherwise an honest hw-test test (importing
    ``hw_tests`` and using ``@pytest.mark`` + ``context``) never collects.
    """
    reasons: list[str] = []

    if name in existing_names:
        reasons.append(f"name collides with existing tests/{name}")

    parsed = True
    try:
        ast.parse(test_py)
    except SyntaxError as exc:
        parsed = False
        reasons.append(f"test.py failed to parse (syntax error): {exc}")

    collected = False
    collect_log = ""
    if parsed:
        with tempfile.TemporaryDirectory(dir=collect_root) as tmp:
            d = Path(tmp)
            (d / "test.py").write_text(test_py)
            (d / "config.toml").write_text(config_toml)
            collected, _items, collect_log = collector(str(d))
        if not collected:
            reasons.append(f"pytest could not collect the test: {collect_log}")

    # Tag-resolve is graceful: it annotates runnability, never blocks staging.
    tag = tag_resolver(_parse_needs(config_toml)) or {}
    tag_match = tag.get("match")
    tag_places = list(tag.get("places", []))

    ok = parsed and collected and name not in existing_names
    return ValidationResult(
        ok=ok, parsed=parsed, collected=collected, collect_log=collect_log,
        tag_match=tag_match, tag_places=tag_places, reasons=reasons,
    )


def _reject(name, validation) -> StagedTest:
    return StagedTest(
        name=name, staged_dir="", files=[], diff="", validation=validation,
        runnable_now=False, result_label="test-design-requires-user-input",
    )


def stage_test(name, test_py, config_toml, meta, *, staging_root,
               validation) -> StagedTest:
    """Write the validated test to the staging dir and build a diff."""
    staged_dir = Path(staging_root) / name
    staged_dir.mkdir(parents=True, exist_ok=True)

    contents = {
        "test.py": test_py,
        "config.toml": config_toml,
        "meta.json": json.dumps(meta, indent=2) + "\n",
    }
    files: list[str] = []
    diff_parts: list[str] = []
    for fname, text in contents.items():
        path = staged_dir / fname
        path.write_text(text)
        files.append(str(path))
        diff_parts.extend(difflib.unified_diff(
            [], text.splitlines(), fromfile=f"/dev/null",
            tofile=f"{name}/{fname}", lineterm=""))

    return StagedTest(
        name=name, staged_dir=str(staged_dir), files=sorted(files),
        diff="\n".join(diff_parts), validation=validation,
        runnable_now=(validation.tag_match is True),
        result_label="coverage-improvement",
    )


def submit_test(changeset, name, test_py, config_toml, plan, *,
                existing_names, collector, tag_resolver, staging_root,
                collect_root=None) -> StagedTest:
    """Validate a proposed test and stage it, or reject it with reasons."""
    cs = serde.changeset_from_dict(changeset)
    validation = validate_test(
        name, test_py, config_toml, existing_names=existing_names,
        collector=collector, tag_resolver=tag_resolver,
        collect_root=collect_root)
    if not validation.ok:
        return _reject(name, validation)

    plan = plan or {}
    meta = {
        "changeset_ref": plan.get("changeset_ref")
        or f"{cs.repo}@{cs.head_sha}",
        "subsystem": plan.get("scope", ""),
        "coverage_gap": plan.get("coverage_gap", "new"),
        "evidence_files": cs.file_paths(),
    }
    return stage_test(name, test_py, config_toml, meta,
                      staging_root=staging_root, validation=validation)
