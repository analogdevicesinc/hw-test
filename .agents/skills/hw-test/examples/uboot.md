# Example: U-Boot PR regression

Prompt: "Check `analogdevicesinc/u-boot` PR `<N>`. Write a hw-test
regression test and verify it on compatible hardware."

```
inspect PR -> identify affected functionality -> find suitable board(s)
  -> locate/fetch PR artifact -> implement smallest regression test
  -> test base if practical -> test PR -> compare -> report evidence
```

1. **Inspect the PR.** `gh pr view analogdevicesinc/u-boot <N> --json
   title,body,files` and `gh pr diff analogdevicesinc/u-boot <N>`. Note the
   changed paths (e.g. `board/adi/sc598*`, `configs/sc598*`,
   `drivers/mmc/...`) and what observable U-Boot behavior should change
   (a new `version`/env output, a boot mode now working, a hang now fixed,
   a command now succeeding).
2. **Match against existing tests.** `tests/adsp/u-boot/config.toml`
   already tracks `u-boot` refs under `board/adi/sc598*` /
   `configs/sc598*` — if the PR's paths fall under what
   `tests/adsp/u-boot` (or `tests/adsp/bootstrap`/`initramfs-boot`, which
   also flash U-Boot) already exercises, extend that test's assertions
   rather than writing a new one.
3. **Pick the board.** Match the PR's board paths to `needs` tags already
   used by the closest test (`needs = ["sc598", "ezkit"]`), don't hardcode
   a place.
4. **Get the PR's U-Boot build.** `tests/adsp/artifacts.toml` defines the
   `u-boot` flavor's `spl`/`uboot` roles as coming straight from the
   workflow run of the `u-boot` repo (no `source=`, so it's always the
   run under test). Point the test context at the PR's CI run:
   ```bash
   export GITHUB_TOKEN=<token>
   set='{"name": "adsp/u-boot", "workflow_run_url": "https://api.github.com/repos/analogdevicesinc/u-boot/actions/runs/<pr_run_id>"}' \
       pytest -vvs
   ```
   If the PR's own CI hasn't produced build artifacts, that's a
   precondition to flag, not something to work around by hand-building
   locally unless the user asks for that.
5. **Write the smallest regression test**, following
   `tests/adsp/u-boot/test.py`: boot with the PR's SPL/U-Boot, assert the
   specific behavior the PR changes (e.g. a new env var, a command that
   should now succeed, a boot path that should no longer hang) rather than
   only re-checking `version` succeeds — a version-only assertion doesn't
   demonstrate the regression the PR is meant to fix.
6. **Test the base revision if practical.** Find the most recent CI run
   on `u-boot`'s target branch built from the commit the PR is based on
   (before the PR's changes), and run the identical test against that
   `workflow_run_url`. If the bug can only reproduce with a specific board
   revision/config not otherwise available, or no base build exists, say
   so explicitly instead of skipping the comparison silently.
7. **Compare and report**: board/place used, PR run ID and base run ID (or
   "base not tested, because ..."), the exact test name and `set=` value
   for each run, pass/fail for each, and the failure classification (see
   [../failure-triage.md](../failure-triage.md)) if either run failed
   unexpectedly.
