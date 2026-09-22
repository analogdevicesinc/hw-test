---
name: hw-test
description: Use when creating, running, debugging, or reviewing hardware tests in the analogdevicesinc/hw-test repository - writing a new test for a board, adding regression coverage for a Linux/U-Boot/HDL PR, reproducing a bug on real hardware, acquiring/releasing labgrid boards, or triaging a failed hardware test run.
---

# hw-test: working with real hardware safely

`hw-test` runs pytest tests against real boards borrowed from a shared
Labgrid pool (`LG_COORDINATOR`). It already provides board selection,
acquisition/release, artifact fetching, and SSH. Your job is to use that
machinery correctly, not to reinvent it.

Read the matching supporting doc before doing the matching task:

| Doc | Read it for |
|---|---|
| [local-environment.md](local-environment.md) | Running as a local agent: `gh auth`, `LG_COORDINATOR`, preflight, what to report |
| [labgrid.md](labgrid.md) | `LabgridClient`, `needs`, drivers, acquire/release, timeouts |
| [artifact-selection.md](artifact-selection.md) | `GitHub`, `Images`, `artifacts.toml`, base-vs-patch artifacts |
| [regression-testing.md](regression-testing.md) | Turning a PR/bug into the smallest regression test |
| [failure-triage.md](failure-triage.md) | Classifying a failed run, hung DUTs, evidence to keep |
| [examples/](examples/) | Worked SC846 watchdog, U-Boot PR, Linux PR walkthroughs |

For chip/board register or feature detail (e.g. confirming a real watchdog
interface before writing a test step), check the ADI datasheets/reference
manuals indexed at
https://github.com/analogdevicesinc/doctools/tree/docling/media/en/technical-documentation/data-sheets
rather than guessing from the part name.

The repository's own guides (`docs/*.rst`, built at
`docs/_build/html` or readable directly) are the primary source of truth;
this skill teaches how to *use* them for agent-driven tasks, it does not
replace them.

## Golden path

0. **If running locally** (not inside GitHub Actions), check only what the
   task needs before doing it: `gh auth status` if it touches GitHub,
   `test -n "$LG_COORDINATOR"` and `labgrid-client places` if it touches
   hardware. Never print a token or the coordinator address. See
   [local-environment.md](local-environment.md) for the exact checks and
   warnings to give the user when one is missing.
1. **Understand the change first.** For a PR/bug: read the diff, name the
   externally observable behavior that should change, and check whether a
   test under `tests/**` already covers it (`grep -r` for the subsystem,
   the driver name, the board family). Don't write a test just because
   files changed — see [regression-testing.md](regression-testing.md).
2. **Reuse, don't reinvent.** Find a similar existing test
   (`tests/adsp/u-boot`, `tests/adsp/smoke`, `tests/adsp/initramfs-boot`,
   `tests/adsp/bootstrap` are the reference patterns) and adapt it. Reuse
   `LabgridClient`, `Images`/`GitHub`, `exporter_http_server`, and the
   driver protocol names already in use. See [labgrid.md](labgrid.md).
3. **Express hardware need as tags, not a board.** `needs = [...]` in
   `config.toml` selects capability tags; never hardcode a place name
   (`labgrid_target`) unless the user explicitly asked for one specific
   board.
4. **Validate cheaply before touching hardware:**
   - `ruff check` / `python -m py_compile` on the new `test.py`.
   - `pytest hw_tests` (library unit tests, no hardware).
   - If the test declares a new pytest marker, add it to `pyproject.toml`
     `[tool.pytest.ini_options] markers` — `--strict-markers` is on, an
     unregistered marker fails collection.
   - `labgrid-client places` / `who` to see whether a matching board is
     free *before* running pytest — `LabgridClient` will otherwise poll
     for up to an hour before giving up.
5. **Run the one test you're working on**, never `pytest tests` (reserves
   every matching board across the whole repo):
   ```bash
   export LG_COORDINATOR=<coordinator>
   set='{"name": "adsp/my-test"}' pytest -vvs
   ```
6. **Acquisition is always `with client.acquire() as target:`.** This
   guarantees release on success, assertion failure, exception, or DUT
   hang. Never call the underlying labgrid session `acquire()`/`release()`
   directly, and never leave a place acquired at the end of a task.
7. **On failure, classify before acting** (see
   [failure-triage.md](failure-triage.md)):
   - `PRODUCT_FAILURE` — the DUT/software shows the bug the test targets.
   - `TEST_FAILURE` — the test's assumptions, parsing, sequencing, or
     timeouts are wrong.
   - `INFRASTRUCTURE_FAILURE` — coordinator, exporter, SSH, power, or
     artifact retrieval is broken, or no board is actually available.
   - `INCONCLUSIVE` — evidence doesn't distinguish the above.
   Fix `TEST_FAILURE`s and rerun the *same* targeted test. Never weaken an
   assertion to force green, and never touch the product/coordinator/
   exporter config just to make a generated test pass.
8. **Report with evidence**: place/board used, revision or artifact
   tested, exact `pytest` invocation, result, whether base-vs-patched was
   actually run, and any limitation. State `IMPLEMENTED` /
   `STATICALLY_VALIDATED` / `HARDWARE_VALIDATED` explicitly (see
   [local-environment.md](local-environment.md)) rather than a blanket
   "implemented and validated" — never claim hardware validation
   succeeded, or that a base regression is proven, unless it was actually
   executed.

## Hard rules

- Never invent a `hw_tests` API, driver name, or `needs` tag — grep the
  repo (`hw_tests/`, `docs/reference/`, similar `tests/**`) first.
- Never hardcode a specific board/place unless the user explicitly asked
  for one; let `needs` + `LabgridClient` pick a free match.
- Never bypass `LabgridClient.acquire()` with hand-rolled labgrid session
  calls when the existing abstraction already does the job.
- Never leave a board acquired — use the `with` block; don't `break`/early
  `return` out around it.
- Never run `pytest tests` (whole hardware farm) or target an unrelated
  board to "just check something."
- Never modify coordinator/exporter/place config to make a test pass
  unless the task is explicitly about infrastructure (see
  [integrate-hardware](../../../docs/integrate-hardware.rst)).
- Never print or store `LG_COORDINATOR`, `GITHUB_TOKEN`/`GH_TOKEN`, SSH
  keys, PDU/exporter credentials, or any other token — checking that one is
  *set* is fine (`test -n "$VAR"`, `gh auth status`); printing its value is
  not. `hw_tests.logging` and `GitHub.mask` already redact registered
  secrets and IPs; register anything new the same way instead of leaking it.
- Never claim a base-vs-patched regression was proven without actually
  running the base revision; state clearly when that step was skipped and
  why.
