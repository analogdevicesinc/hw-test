l# Triaging a failed hardware test run

## Classify before acting

| Category | Meaning | Typical signature in this repo |
|---|---|---|
| `PRODUCT_FAILURE` | The DUT/software actually shows the behavior the test targets. | The expected console pattern never appears despite a correct sequence and adequate timeout, and the failure is reproducible on a second run. |
| `TEST_FAILURE` | The test's assumptions, parsing, sequencing, or timeout are wrong. | Wrong `needs`, wrong role/artifact glob, `console.expect` pattern doesn't match actual (but correct) output, timeout too short for a step that's slow but healthy, missing `spi_boot.set()`/`power.cycle()` before boot. |
| `INFRASTRUCTURE_FAILURE` | Lab infra — coordinator, exporter, serial, power, network, artifact retrieval, or an unhealthy board. | `get_driver(...)` raises (driver missing from place config); `PermissionError` from `OPKSSH.check_ssh_auth` (SSH unreachable/unauthorized); `no available place found for needs after 1 hour`; `GitHub`/`Images` fails to download; `labgrid-client places` itself hangs/errors with `LG_COORDINATOR` set (see [local-environment.md](local-environment.md)); the same board fails a totally unrelated test too. |
| `INCONCLUSIVE` | Not enough evidence to pick one of the above. | Failure happened once, logs are ambiguous, or the run was interrupted before reaching the relevant step. |

Determine this **before** touching the product or the test. Never modify
the product merely because a generated test failed — first find out
whether the test itself is at fault.

A `PRODUCT_FAILURE` classification is a strong claim — it says the DUT is
actually broken. Reserve it for when the evidence below actually supports
it. Being unable to immediately explain a symptom is not evidence that the
product is broken; it's evidence you don't have enough data yet. Prefer
`PRODUCT_FAILURE candidate` or `INCONCLUSIVE` until reproducibility,
infrastructure exclusion, and (where practical) a known-good comparison are
all in hand.

## Evidence discipline: observed vs. hypothesis vs. verified

Live hardware debugging (console silent, core apparently stuck, unexpected
register value, etc.) invites jumping straight from a symptom to a root
cause. Don't. Keep three buckets separate, and say which bucket each
statement belongs in:

```
OBSERVED    — what a tool/register/console actually showed, verbatim
HYPOTHESIS  — a plausible explanation that is not yet confirmed
VERIFIED    — a hypothesis with direct supporting evidence, not inference
```

Example:

```
OBSERVED:
- serial console produced no printable output for 4 seconds
- OpenOCD reports target state "running"
- PC sampled four times, all 0xdf08

HYPOTHESIS:
- firmware may be stuck in an early-boot polling loop
- clock/PLL lock alignment may be involved

VERIFIED:
- (nothing yet — no symbolization or register evidence obtained)
```

Avoid `this proves it` / `root cause is` / `definitely caused by` unless the
evidence directly establishes the claim. Prefer `consistent with` /
`suggests` / `one plausible explanation is` / `not yet proven` /
`additional evidence required` while it doesn't.

If new evidence contradicts something you said earlier, say so explicitly
instead of quietly switching explanations:

```
Earlier I suspected OpenOCD was holding the core halted. The subsequent
target-state query shows the core is running, so that explanation is no
longer supported.
```

The debugging loop this skill wants:

```
observation → competing hypotheses → least intrusive discriminating test
→ new evidence → update hypotheses → repeat → verified conclusion
```

not:

```
symptom → plausible explanation → declare root cause
```

## Program counter and symbolization

A raw PC value does not identify a function, loop, or peripheral by itself.
Before writing something like `PC 0xdf08 = CGU polling loop`, get the exact
ELF for the running image and resolve the address (`addr2line`, `objdump
-dS`, `gdb` symbolization, or whatever repository-supported mechanism
applies). A memory map showing the address falls inside ICCM only
establishes "execution is occurring from ICCM" — it does not by itself tell
you which function, source line, loop, or peripheral is involved.

A single PC sample is weak evidence of a core being "stuck" at all. Where
it's safe to do so (see intrusive/non-intrusive below), sample it multiple
times, record the sample count and interval, and state whether it's static
or moving:

```
PC samples: 0xdf08, 0xdf08, 0xdf08, 0xdf08
```

supports "core appears to be repeatedly executing near or parked at
0xdf08" — not, on its own, which source line that is.

## Manual patterns are supporting evidence, not proof

A reference-manual sequence (e.g. "write PLL config, poll PLOCK, poll
CLKSALGN") that matches a symptom is useful supporting evidence, not proof
that the current PC is executing that exact sequence. Before concluding a
clock/PLL issue is the cause, look for direct state, not just a matching
narrative: symbolized PC/disassembly around it, the relevant control/status
register values (e.g. `CGU_STAT`, `CGU_CTL`, `CGU_DIV`/`CGU_DIVEX`, PLOCK/
CLKSALGN bits), a comparison against known-good values, or reproduction
after reverting the suspected change.

Prefer this rough evidence ladder for a suspected clock/hang investigation,
and don't skip from the top straight to a confirmed root cause at the
bottom:

```
console symptoms
  -> target running/halted state
  -> repeated PC samples
  -> exception/register state
  -> symbolized PC / disassembly
  -> relevant control/status register state
  -> compare against known-good configuration
  -> controlled revert/reproduction
```

## Intrusive vs. non-intrusive diagnostics

Classify each debug action before doing it:

```
NON_INTRUSIVE — e.g. reading PC/registers/state without halting, reading
                console output, `labgrid-client places`/`show`
INTRUSIVE     — halting/resuming a core, `init`/reset if it may alter
                target state, power cycle, register or memory writes,
                changing boot mode, modifying clocks
```

Prefer non-intrusive observations first. If an intrusive action is
necessary, say so explicitly in the result, including the limitation it
introduces:

```
INTRUSIVE ACTION:
Core halted briefly to read PC/PSTATE/SP and immediately resumed.

Limitation:
Halting may perturb timing-sensitive failures; subsequent observations
cannot be assumed to represent the untouched failure state.
```

Don't claim "no state changed" merely because the core was resumed
afterward — halting/resuming is itself a state-changing operation.

## OpenOCD/debug-attach causality

If OpenOCD (or another debug attach) was started at or near the time a
failure occurred, don't assume it's a neutral observer. These are different
facts — keep them separate:

```
OpenOCD process exists
target reports "running"
OpenOCD caused a reset
OpenOCD halted the target
OpenOCD otherwise changed target state
```

To rule OpenOCD in or out as a contributor, prefer a controlled comparison
(boot without it attached vs. with it attached) or read the exact
target/reset-config script being used, rather than assuming attach is
side-effect-free.

## A user-reported change is context, not proof

If the user says "I changed the clock configuration" (or any other config
change) right before describing a hang, treat that as highly relevant
context to investigate first — not as an established cause. Don't reason
"config changed + board hung = config change caused the hang" without
looking at the actual change: which fields changed, previous vs. new
values, derived frequencies, legal operating ranges, lock/alignment status,
reproducibility, and behavior on revert. Let the user's report guide where
you look, not what you conclude.

When a datasheet says a limit is "specified elsewhere" and you don't have
that section, don't infer or guess the number — get the correct reference,
or state plainly that exact numeric validation isn't possible yet. Don't
fabricate a plausible-sounding frequency/limit to fill the gap.

## Reading a `pexpect.TIMEOUT`

`console.expect(pattern, timeout=...)` is the only hang detector in use —
there is no separate process-level watchdog. When it fires, distinguish:

- **Command timeout** — one `expect()` call for one command (e.g. `dhcp`,
  a single `wget`) timed out, but the console is otherwise responsive
  (a later, unrelated `sendline`/`expect` still works if you retry within
  the same session). Usually `TEST_FAILURE` (timeout too short, wrong
  pattern) or a narrow, real slowdown (`PRODUCT_FAILURE` candidate if the
  PR is expected to affect that step's timing).
- **DUT hang** — nothing on the console at all past the timeout, including
  a manual `console.sendline("")` producing no echo. Points toward
  `PRODUCT_FAILURE` (real hang) once fixture setup is confirmed correct
  (power was cycled, boot mode GPIO set, SPL/U-Boot actually uploaded).
- **Console/serial disconnect** — the exception isn't `pexpect.TIMEOUT`
  but a serial/transport error, or the exporter's serial resource
  disappears from `labgrid-client -p <place> show`. `INFRASTRUCTURE_FAILURE`
  — the serial adapter or exporter service has a problem, not the DUT.
- **Infra-level timeout** — `LabgridClient` itself raises before any
  console interaction (`no place found for needs`, `no available place
  found... after 1 hour`) or `OPKSSH`/`SSHDriver` raises on connect. This
  is board-availability or connectivity, not a DUT hang —
  `INFRASTRUCTURE_FAILURE` (or `TEST_FAILURE` if `needs` was simply wrong).

If a hang is suspected, re-run the same targeted test once more before
concluding `PRODUCT_FAILURE` — a single occurrence with no obvious
fixture-setup mistake is often still `INCONCLUSIVE`, since there is no
automatic board health-check to rule out a fixture in a bad state (see
"Known gap" below).

## Iterating

1. Inspect the complete relevant log/console output for the failing step,
   not just the last line.
2. Classify using the table above.
3. If `TEST_FAILURE`: fix the test (pattern, timeout, sequencing, `needs`,
   artifact role) and re-run **only** the same targeted test —
   `set='{"name": "<the-same-name>"}' pytest -vvs`, never the whole suite.
4. If `INFRASTRUCTURE_FAILURE`: do not touch the test or the product. Note
   it, and if it blocks further progress, stop and say so — do not route
   around it by hardcoding a different board or bypassing
   `LabgridClient`, and do not modify coordinator/exporter/place config
   unless the task explicitly is infrastructure work.
5. If `PRODUCT_FAILURE`: the test has done its job. Report it with
   evidence; do not "fix" the product yourself unless asked to.
6. If `INCONCLUSIVE` after one retry: say so plainly. Don't round up to a
   more dramatic category to make the report feel decisive.

Never weaken an assertion (broaden a regex, extend a timeout past what the
operation should reasonably take, drop a check) just to turn a red run
green without a technical reason recorded in the test/commit.

For a regression investigation specifically, don't claim a software
regression until you've actually run `known-good/base -> PASS`, `changed
revision -> FAIL` (see [regression-testing.md](regression-testing.md)) — a
plausible-looking diff is not the same as a demonstrated regression.

## Reporting a non-trivial board failure

For anything beyond a one-line pass/fail, report a compact evidence
summary rather than a wall of commands:

```
OBSERVED
- ...

ACTIONS PERFORMED
- ...

CURRENT HYPOTHESIS
- ...

CONFIDENCE
- low / medium / high

NOT YET PROVEN
- ...

NEXT BEST DISCRIMINATING CHECK
- ...
```

Pick "next best discriminating check" for what most clearly separates the
competing hypotheses, not just the next convenient command — e.g. reading
`CGU_STAT`/`CGU_CTL` is more informative than immediately power-cycling the
target if the live question is "is the clock actually locked."

## Evidence to keep

For every hardware run, capture enough to reconstruct what happened:

- Selected place/board name (`labgrid-client places`, or the name
  `LabgridClient` logged: "Labgrid place: ...").
- Platform/board family (the `needs` tags used).
- Revision/artifact tested — commit SHA, `workflow_run_url`, or release
  tag actually resolved by `Images`/`GitHub`.
- The exact `pytest` invocation (`set=...` value) used.
- Console/serial output around the relevant step (redacted logging is
  already applied — don't disable it).
- The `pytest` result (pass/fail) and, on failure, the exception/traceback.
- Any recovery already performed (e.g. a `power.cycle()` the test itself
  issues) and whether it changed the outcome.

Don't dump raw secrets, coordinator addresses, or exporter hostnames —
`hw_tests.logging`/`GitHub.mask` redact registered values automatically;
rely on that rather than manually scrubbing.

## Known gap (useful to flag, not to work around)

There is no coordinator/exporter-side automatic health check that detects
and recovers a board stuck in a bad state between runs — the only
built-in recovery is `LabgridClient` releasing a stale lock left by a
crashed previous CI attempt of the *same* workflow. If a board looks
consistently unhealthy across unrelated tests, that's
`INFRASTRUCTURE_FAILURE` to report to the team that owns the fixture
(`docs/integrate-hardware.rst`), not something to script around inside a
test.
