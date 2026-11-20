# Example: Linux PR coverage

Prompt: "Check `analogdevicesinc/linux` PR `<N>` and add hardware
coverage." (Also covers: "Check this Linux PR and determine whether
existing hw-test coverage is sufficient.")

Follow [regression-testing.md](../regression-testing.md) end to end; this
page only adds the Linux-specific detail.

1. **Inspect the PR.** `gh pr diff analogdevicesinc/linux <N>` and note
   the driver/subsystem and board(s) affected (e.g.
   `drivers/iio/dac/ad3530r.c` + `adi/sc598*` device tree, matching
   `tests/demo/linux-iio-dac` and `tests/adsp/*`'s `[[repository]]`
   `path` globs). If the PR lives on a GitHub host/org `gh` isn't
   authenticated to (e.g. an internal mirror), `gh` can't reach it — fall
   back to `curl` against that host's API with the same `GITHUB_TOKEN`
   (see [../local-environment.md](../local-environment.md)):
   ```bash
   curl -L \
     -H "Accept: application/vnd.github.patch" \
     -H "Authorization: Bearer $GITHUB_TOKEN" \
     -H "X-GitHub-Api-Version: 2026-03-10" \
     https://api.github.com/repos/<org>/linux/pulls/<N>
   ```
2. **Pick the layer and check existing coverage** per
   regression-testing.md §§1-2 — boot-level
   (`tests/adsp/initramfs-boot` style) if the change can only regress
   boot; an `ssh.run_check(...)` assertion (the `SSHDriver` pattern in
   `tests/adsp/smoke`) if it changes kernel-visible behavior; confirm the
   tool/library is actually in the rootfs first if it needs userspace
   validation. Grep `tests/**/config.toml` for `[[repository]] name =
   "linux"` blocks whose `path` glob already matches the PR's changed
   files (`tests/demo/linux-iio-dac`, `tests/adsp/smoke`,
   `tests/adsp/bootstrap` all declare theirs) before adding a parallel
   test for the same path.
3. **If a new test is warranted**, pick the board via `needs` from the
   closest existing `adsp/*` test, resolve the kernel/dtb via `Images`
   (role `kernel`/`dtb`, flavor `linux` — see
   [../artifact-selection.md](../artifact-selection.md)), and boot using
   the `initramfs-boot`/`bootstrap` pattern (SPL/U-Boot via
   `exporter_http_server`, then `wget` kernel/dtb/rootfs, then `booti`).
4. **Base vs. patched** per regression-testing.md §3: run the identical
   test against a CI run built from the PR's base commit and against the
   PR's own run if a regression is being demonstrated; state plainly if
   base testing was skipped and why.
5. **Report**: which layer was chosen and why, board/place, revision(s)
   tested, exact test name(s), result, and — if you concluded "existing
   coverage is sufficient" or "no hardware test applies" — say that
   explicitly instead of adding a token test to look thorough.
