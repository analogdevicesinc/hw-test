# Turning a PR or bug report into a hardware test

## 1. Understand the change before writing anything

For a PR/patch in `linux`, `u-boot`, `hdl`, or a related repo:

- Read the diff (`gh pr diff <owner>/<repo>#<N>` or `gh pr view ... --json
  files,body`). Identify the subsystem and the file paths touched.
- State the **externally observable behavior** that should change — a
  console message, a boot succeeding/failing, a device node appearing, a
  sysfs value, a timing bound. Not "the diff touches driver X" — what a
  user or another test could observe.
- Identify which board family can exercise it. If the PR patches
  `arch/arm64/boot/dts/adi/sc598*` or `board/adi/sc598*`, the affected
  hardware is the sc598/ezkit family already used by
  `tests/adsp/*` — match `needs` accordingly rather than guessing a board.
- Search `tests/**` for existing coverage of that path/behavior
  (`grep -r <driver-or-symbol> tests/`, check each category's
  `config.toml` `[[repository]] path` globs — they already declare which
  file globs each test cares about). If an existing test already exercises
  the behavior, extend or rerun it — don't fork a near-duplicate.
- Do not create a test merely because files changed. If the change is not
  observable from outside the running system (a comment, a Kconfig help
  text, a refactor with no behavior delta), say so and skip writing a test.

## 2. Pick the smallest meaningful test

Prefer, in order:
1. Extending an existing test's assertions if it already boots/exercises
   the right path.
2. A new, narrowly-scoped test next to the closest existing pattern
   (`tests/adsp/u-boot` for a U-Boot-only regression, `tests/adsp/
   initramfs-boot` for a kernel boot check, `tests/adsp/smoke` as the
   template for anything SSH-only).
3. Only add a new `tests/<category>/artifacts.toml` role/flavor entry if
   the existing roles genuinely can't express what you need to fetch.

For a Linux PR specifically, decide the right layer before writing code:

- **Boot-level** is enough if the change can only regress boot (a DT
  change, a clock/driver init order issue) — reuse
  `tests/adsp/initramfs-boot` style: boot and reach a shell.
- **Kernel functionality** (a specific driver, IOCTL, sysfs attribute)
  needs an SSH command against the booted system, not just a boot check —
  add an `ssh.run_check(...)`/assertion step after boot, following the
  `SSHDriver` pattern from `tests/adsp/smoke`.
- **Userspace validation** (a library, a tool, an IIO channel value) needs
  the userspace piece present on the rootfs and invoked over SSH; check
  whether the existing rootfs/build already includes it before assuming
  you need a new artifact role.
- If none of the above actually exercises the changed code path on real
  hardware, say that explicitly rather than writing a boot-only test and
  calling it coverage.

## 3. Base vs. patched

For a bug-fix PR, prefer demonstrating the regression itself:

```
base revision    -> observable failure (matches the bug report)
patched revision -> the same test passes
```

over only running the patched revision. Use the same test, same `needs`,
same board — vary only the artifact source (see
[artifact-selection.md](artifact-selection.md), "Selecting a PR build vs a
base build"). Report both results.

If testing the base revision is impractical (no CI ever built it, the
board doesn't exist yet, the bug requires hours to reproduce), run the
patched revision and **explicitly say the base was not tested and why** —
never claim the regression is "proven" from the patched run alone.

## 4. Registering a new test

- Path: `tests/<category>/<test-name>/{config.toml, test.py,
  requirements.txt?}`. The directory path *is* the test name used in
  `set='{"name": "..."}'`.
- `config.toml`: `needs = [...]` (capability tags) plus optional
  `[[repository]]` entries describing which repo/ref/path triggers this
  test in CI (used by `hw_tests.collect` for `run-tests.yml`, not required
  for a manually-run regression test).
- If the test uses a new `@pytest.mark.<name>`, add `<name>` to
  `pyproject.toml`'s `[tool.pytest.ini_options] markers` list —
  `--strict-markers` will otherwise fail collection.
- Try it locally first (`set='{"name": "..."}' pytest -vvv`), on one
  board, before wiring it into any workflow.
