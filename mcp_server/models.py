"""Typed shared models for the change-driven validation MCP server.

Every value crossing a module or MCP-tool boundary is one of these dataclasses
or the ``Subsystem`` enum. No unstructured dict is passed between modules. The
dataclasses are plain (``dataclasses.asdict`` serializes them for tool output)
and validate their own constrained string fields in ``__post_init__`` so an
invalid ``confidence``/``kind``/label is rejected at construction, not deep in
planning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Subsystem(str, Enum):
    """Affected-area taxonomy. str-valued so it serializes as a plain string.

    Mirrors the conservative subsystem list in the product brief.
    """

    BOOT_CHAIN = "boot_chain"
    BOARD_DT = "board_dt"
    CLOCK_RESET_POWER = "clock_reset_power"
    SPI_QSPI_XSPI = "spi_qspi_xspi"
    STORAGE_MMC_SD = "storage_mmc_sd"
    NET_PHY = "net_phy"
    UART_CONSOLE = "uart_console"
    CAN = "can"
    USB = "usb"
    DDR = "ddr"
    KCONFIG_BUILD = "kconfig_build"
    OTHER = "other"


_KINDS = frozenset({"pr", "local"})
_CONFIDENCE = frozenset({"high", "medium", "low", "none"})
_SOURCES = frozenset({"llm", "cache"})
_COVERAGE_GAP = frozenset({"reuse", "parameterize", "new"})
_RESULT_LABELS = frozenset({
    "validation-only", "coverage-improvement", "inconclusive",
    "hardware-unavailable", "build-artifact-unavailable",
    "test-design-requires-user-input",
})


def _require(value, allowed, field_name):
    if value not in allowed:
        raise ValueError(
            f"{field_name} must be one of {sorted(allowed)}, got {value!r}"
        )


@dataclass
class SourceRef:
    """Where a ChangeSet came from."""

    repo: str
    ref_or_sha: str
    kind: str  # "pr" | "local"

    def __post_init__(self):
        _require(self.kind, _KINDS, "kind")


@dataclass
class FileChange:
    """One changed file and short snippets of its diff hunks."""

    path: str
    status: str  # git/gh status: modified|added|removed|renamed|...
    hunk_snippets: list[str] = field(default_factory=list)


@dataclass
class ChangeSet:
    """Normalized result of inspecting a PR or a local branch."""

    source: SourceRef
    repo: str
    head_sha: str
    base_ref: str
    merge_base_sha: str
    files: list[FileChange] = field(default_factory=list)
    commits: list[str] = field(default_factory=list)
    human_summary: str = ""
    pr_number: int | None = None

    def file_paths(self) -> list[str]:
        return [f.path for f in self.files]


@dataclass
class DocRef:
    """A doctools-ready documentation pointer.

    Shaped so the driving agent can hand ``repo``/``query`` straight to the
    doctools MCP server's ``search`` tool. This server never fetches docs.
    """

    repo: str
    query: str
    board: str | None = None
    doc_id: str | None = None
    version_hint: str | None = None


@dataclass
class Classification:
    """A subsystem attribution for part of a ChangeSet.

    Produced by the driving LLM (or a reviewed cache) and validated by the
    server: the subsystem must be a ``Subsystem`` enum member and confidence a
    known level. Evidence-file existence is checked against the ChangeSet by
    ``planning``, not here (this type does not see the ChangeSet).
    """

    subsystem: Subsystem
    confidence: str  # high|medium|low|none
    evidence_files: list[str]
    source: str  # llm|cache
    rationale: str = ""

    def __post_init__(self):
        if not isinstance(self.subsystem, Subsystem):
            raise ValueError(
                f"subsystem must be a Subsystem enum member, got "
                f"{self.subsystem!r}"
            )
        _require(self.confidence, _CONFIDENCE, "confidence")
        _require(self.source, _SOURCES, "source")


@dataclass
class ClassificationEvidence:
    """Deterministic facts handed to the classifier role, no judgment applied."""

    repo: str
    files: list[FileChange]
    matched_metas: list[str]  # test _uid's whose repo path-globs match
    subsystem_choices: list[str]  # Subsystem enum values, for the LLM to pick
    seed_doc_refs: list[DocRef] = field(default_factory=list)


@dataclass
class TestPlan:
    """The honest, structured plan output of this slice. No pass/fail verdict."""

    changeset_ref: str
    classifications: list[Classification]
    scope: str
    candidate_capabilities: list[str]
    existing_test_matches: list[str]
    coverage_gap: str  # reuse|parameterize|new
    doc_refs: list[DocRef]
    expected_base_vs_pr: str
    board_requirements: list[str]
    result_label_if_no_hw: str
    human_summary: str

    def __post_init__(self):
        _require(self.coverage_gap, _COVERAGE_GAP, "coverage_gap")
        _require(self.result_label_if_no_hw, _RESULT_LABELS,
                 "result_label_if_no_hw")


_IMAGE_SOURCES = frozenset({"artifact", "build"})
_RUN_REFS = frozenset({"base", "pr"})
_RUN_STATES = frozenset({"passed", "failed", "inconclusive"})


@dataclass
class ImageRef:
    """A resolved image for one ref: either a fetched artifact or a local build."""

    repo: str
    sha: str
    role: str  # e.g. "u-boot"
    source: str  # artifact|build
    location: str  # path or artifact id the executor consumes
    build_log_tail: str = ""  # populated when source == "build"

    def __post_init__(self):
        _require(self.source, _IMAGE_SOURCES, "source")


@dataclass
class RunOutcome:
    """The result of one hardware run (base or PR)."""

    ref: str  # base|pr
    sha: str
    image: "ImageRef"
    state: str  # passed|failed|inconclusive
    returncode: int | None
    log_tail: str
    collected_artifacts: list[str] = field(default_factory=list)

    def __post_init__(self):
        _require(self.ref, _RUN_REFS, "ref")
        _require(self.state, _RUN_STATES, "state")


class Transition(str, Enum):
    """How the test state changed from base to PR."""

    STABLE_PASS = "pass->pass"
    REGRESSION = "pass->fail"
    FIX = "fail->pass"
    STILL_BROKEN = "fail->fail"
    INCONCLUSIVE = "inconclusive"


@dataclass
class CompareReport:
    """Honest base-vs-PR outcome. No claim beyond the observed state delta."""

    changeset_ref: str
    test_name: str
    board: str | None
    base: "RunOutcome | None"
    pr: "RunOutcome | None"
    transition: "Transition | None"
    regressed: bool
    result_label: str  # from _RESULT_LABELS
    evidence: list[str]
    human_summary: str
    # What the test checks, from its docstring — so a bare "passed" is not
    # opaque. Empty when no describer was supplied.
    test_description: str = ""

    def __post_init__(self):
        _require(self.result_label, _RESULT_LABELS, "result_label")


@dataclass
class ValidationResult:
    """Outcome of the server-side gate on a proposed test."""

    ok: bool
    parsed: bool
    collected: bool
    collect_log: str
    tag_match: bool | None  # None = no coordinator reachable (graceful)
    tag_places: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


@dataclass
class StagedTest:
    """A validated test written to the staging dir, awaiting human promotion."""

    name: str
    staged_dir: str
    files: list[str]
    diff: str
    validation: "ValidationResult"
    runnable_now: bool
    result_label: str  # from _RESULT_LABELS

    def __post_init__(self):
        _require(self.result_label, _RESULT_LABELS, "result_label")
