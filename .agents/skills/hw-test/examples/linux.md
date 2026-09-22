# Example: Linux PR coverage

Prompt: "Check `analogdevicesinc/linux` PR `<N>` and add hardware
coverage." (Also covers: "Check this Linux PR and determine whether
existing hw-test coverage is sufficient.")

1. **Inspect the PR.** `gh pr diff analogdevicesinc/linux <N>` and note
   the driver/subsystem and board(s) affected (e.g.
   `drivers/iio/dac/ad3530r.c` + `adi/sc598*` device tree, matching
   `tests/demo/linux-iio-dac` and `tests/adsp/*`'s `[[repository]]`
   `path` globs).
2. **Decide the right layer before writing code** — don't default to "add
   a boot test":
   - Change can only regress **boot** (DT, clock/driver init order,
     probe-time crash) → boot-level is enough. Extend/reuse
     `tests/adsp/initramfs-boot` style: boot to a shell and confirm it's
     reached.
   - Change affects **kernel functionality** visible after boot (a
     specific driver's behavior, an ioctl, a sysfs attribute, a value a
     userspace tool would read) → boot alone doesn't prove anything; add
     an `ssh.run_check(...)` step against the booted system asserting the
     specific behavior, following the `SSHDriver` pattern in
     `tests/adsp/smoke`.
   - Change requires **userspace validation** (a library, IIO tool,
     specific rootfs content) → confirm the tool/library is actually
     present in the target rootfs/build before writing a step that
     invokes it; if it isn't, that's a prerequisite to flag, not something
     to fake.
   - If none of the above can observe the changed code path on real
     hardware (pure refactor, comment/Kconfig text, build-only change),
     say explicitly that hardware coverage doesn't apply and why —
     don't manufacture a test.
3. **Check existing coverage first.** Grep `tests/**/config.toml` for
   `[[repository]] name = "linux"` blocks whose `path` glob already
   matches the PR's changed files (`tests/demo/linux-iio-dac`,
   `tests/adsp/smoke`, `tests/adsp/bootstrap` all declare theirs). If one
   matches, that test is the existing coverage — evaluate whether its
   assertions are strong enough for this PR's specific behavior, and
   extend it if not, rather than adding a parallel test for the same path.
4. **If a new test is warranted**, pick the board via `needs` from the
   closest existing `adsp/*` test, resolve the kernel/dtb via `Images`
   (role `kernel`/`dtb`, flavor `linux` — see
   [../artifact-selection.md](../artifact-selection.md)), and boot using
   the `initramfs-boot`/`bootstrap` pattern (SPL/U-Boot via
   `exporter_http_server`, then `wget` kernel/dtb/rootfs, then `booti`).
5. **Base vs. patched**: same approach as
   [uboot.md](uboot.md) step 6 — run the identical test against a CI run
   built from the PR's base commit and against the PR's own run if a
   regression is being demonstrated; state plainly if base testing was
   skipped and why.
6. **Report**: which layer was chosen and why, board/place, revision(s)
   tested, exact test name(s), result, and — if you concluded "existing
   coverage is sufficient" or "no hardware test applies" — say that
   explicitly instead of adding a token test to look thorough.
