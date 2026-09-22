# Labgrid mechanics in this repo

Full background: `docs/concepts.rst`, `docs/reference/glossary.rst`,
`docs/reference/hardware-model.rst`. This page is the code-level companion.

## The layering

```
pytest test.py (uses `context` fixture)
    -> hw_tests.labgrid.LabgridClient(context)
    -> matches a free labgrid Place by tags ("needs")
    -> client.acquire() -> labgrid session.acquire() + target
    -> target.get_driver(...) -> real board (console, power, SSH, OpenOCD, ...)
```

`context` is built by `tests/conftest.py` (`pytest_generate_tests`) from the
test's `config.toml` plus any `set=` override, and is parametrized once per
entry in `needs` when `needs` is a list-of-lists (multi-target tests).

## `needs`: hardware as tags, not a place name

```toml
# tests/<category>/<test>/config.toml
needs = ["sc598", "ezkit"]
```

`LabgridClient._resolve_place` matches a Place when **every** string in
`needs` is present in that place's tag set (tag keys and tag values are both
matched, e.g. a place tagged `board=sc598` satisfies `needs = ["sc598"]`).
This is an exact-token match, not a substring match — unlike `Images`
artifact narrowing (see [artifact-selection.md](artifact-selection.md)),
which *does* substring-match `needs` against artifact filenames.

**A test that runs on several board capabilities** declares `needs` as a
list of lists instead of a flat list:

```toml
needs = [
    ["sc598", "ezkit"],
    ["sc598", "ezlite"],
    ["sc846", "ezkit"],
]
```

`tests/conftest.py`'s `pytest_generate_tests` detects this (not every
element is a string) and parametrizes one test per entry, each with its own
id and its own `needs` resolution — e.g. `pytest --collect-only` shows
`test_smoke[sc598+ezkit]`, `test_smoke[sc846+ezkit]`, etc. Run just one:

```bash
set='{"name": "adsp/smoke", "needs": ["sc846", "ezkit"]}' pytest -vvs
```

This is the existing mechanism for "this test also covers board X" — don't
hand-roll a second config format or a comment-only capability list for it.

Only pin `labgrid_target` (a specific place name from `labgrid-client
places`) when the user explicitly names a board. Otherwise let the pool
pick a free match — that is the entire point of `needs`.

If no board matches `needs` at all, `LabgridClient` raises immediately
(`no place found for needs: [...]`) — that's a `needs` problem
(`TEST_FAILURE`) or a missing platform (see `docs/integrate-hardware.rst`).
If matches exist but are all held by someone else, it polls every 30s for
up to **one hour** before raising `no available place found for needs
after 1 hour`. Check `labgrid-client places` / `who` first so you don't
burn an hour discovering the board is busy.

## Acquiring a board

Always go through the context manager:

```python
from hw_tests.labgrid import LabgridClient

def test_smoke(context):
    client = LabgridClient(context)
    with client.acquire() as target:
        ssh = target.get_driver("SSHDriver")
        ssh.run_check("true")
```

`client.acquire()` acquires the place, loads its coordinator-side place
config, wires up SSH (including OPKSSH authentication when needed), and
yields the labgrid `target`. Its `finally` block always calls
`target.cleanup()` then releases the place — on a passing test, a failed
assertion, a raised exception, or a `pexpect.TIMEOUT` from a hung DUT. This
is why a hand-rolled `session.acquire()`/`release()` is never needed and
never safer than the existing context manager.

**`SSHDriver` reaches the exporter, not the DUT.** In this repo's place
configs, `SSHDriver` binds to a `NetworkService` resource at the
*exporter's* own address — it exists for staging files onto the exporter
(`ssh.put(...)`, `exporter_http_server(ssh, ...)`) and for the smoke test's
"is the exporter reachable at all" check above. Running `ssh.run_check(...)`
never executes on the SC598/SC846 board itself, even though it looks like
it should. To run a command on the DUT's own Linux userspace, use
`ShellDriver` instead — it binds on top of the DUT's console
(`SerialDriver`) and logs in with the credentials from the place config
(`login_prompt`, `username`, `password`):

```python
shell = target.get_driver("ShellDriver", activate=False)
target.activate(shell)          # runs through boot output and logs in
shell.run_check("cat /proc/uptime")
console = shell.console         # raw pexpect console, e.g. for tight timing
```

If a test needs to detect "the board is gone" with sub-30s precision, poll
`shell.console` directly (`console.sendline(...)`; `console.expect(shell.prompt,
timeout=...)`) rather than `shell.run_check(...)` — `ShellDriver`'s own
command path does a fixed ~30s prompt check on every call, which is too
coarse for timing a fast reset. After a reset, re-login with
`target.deactivate(shell)` then `target.activate(shell)` again — this reruns
`ShellDriver`'s own boot/login handling instead of hand-rolling
`console.expect("login:")`.

In GitHub Actions, if a previous attempt of the *same* workflow run/attempt
crashed while holding the place, `LabgridClient` detects that
(`_is_previous_workflow_owner`) and releases the stale lock before
acquiring — this is the only automatic lock-recovery in the repo; there is
no coordinator-side health check that force-releases a hung place on its
own.

## Drivers: ask by protocol, not by fixture detail

```python
ssh = target.get_driver("SSHDriver")
power = target.get_driver("PowerProtocol")
spi_boot = target.get_driver("DigitalOutputProtocol", name="spi_boot")
openocd = target.get_driver("OpenOCDDriver", activate=False)
uboot = target.get_driver("UBootDriver", name="uboot", activate=False)
console = uboot.console
```

Ask for the *protocol* (`PowerProtocol`, `DigitalOutputProtocol`,
`SSHDriver`) rather than a concrete fixture class where possible, so the
same test runs on any board exposing that capability. `name=` disambiguates
when a place exposes more than one driver of the same kind (e.g. a named
GPIO like `spi_boot`). If `get_driver(...)` raises because the driver is
missing, that is an `INFRASTRUCTURE_FAILURE` — the board's fixture doesn't
expose that control; ask whoever maintains it to extend the coordinator-side
place config (`docs/reference/hardware-model.rst`), do not work around it in
the test.

A GPIO like `spi_boot` is a piece of board state that outlives any one
test's `with client.acquire()` block — the next test to acquire the same
place inherits whatever value the previous test last set it to.
`tests/adsp/u-boot` and `tests/adsp/initramfs-boot` both set
`spi_boot.set(False)` (boot via JTAG) and never restore it;
`tests/adsp/bootstrap` sets it back `True` only at its own end, to leave the
board in its persistent SPI/eMMC-boot state. A test that expects the board
to autoboot its already-flashed image (no JTAG load of its own) must not
assume that state — explicitly `spi_boot.set(True)` before `power.cycle()`,
the same as `bootstrap/test.py` does after flashing. This is a general
pattern, not just this one GPIO: before writing a new test, check how
existing tests under the same `tests/<category>/` handle any shared
board-state driver, don't assume a fresh/default value.

Drivers created with `activate=False` (`OpenOCDDriver`, `UBootDriver`) must
be explicitly `target.activate(driver)` / `target.deactivate(driver)`
around their use — always in a `try/finally` when the driver does
something exclusive on the bus (see `openocd.execute(...)` in
`tests/adsp/u-boot/test.py`), so a raised exception still releases it.

## Console interaction and hang detection

The serial console (`SerialDriver`, wrapped by `UBootDriver.console`, a
pexpect-backed object) is the primary way to observe DUT behavior and
detect a hang:

```python
console.sendline("version")
console.expect("U-Boot", timeout=30)
console.expect(uboot_driver.prompt, timeout=30)
```

`console.expect(pattern, timeout=...)` raises `pexpect.TIMEOUT` if the
pattern doesn't appear within `timeout` seconds — **this is the hang
detector**, there is no separate process-level watchdog wrapping it. Pick a
timeout that matches the operation, following the precedent already in the
repo rather than a single global value:

| Operation | Typical timeout (see existing tests) |
|---|---|
| U-Boot prompt / version | 30s |
| `dhcp` | 120s |
| `wget` of an image over the exporter HTTP server | 180s |
| Linux boot to login/shell (`await_boot()` + `expect(...)`) | 240s |
| SPI/eMMC flashing (`bootstrap` test) | 600-1800s |

`UBootDriver.await_boot()` is the helper for "U-Boot handed off to Linux";
call it, then `target.deactivate(uboot_driver)` before expecting Linux-side
strings on the same `console`.

A `pexpect.TIMEOUT` here is not automatically a product bug — it can mean
the expected string/regex is wrong, the board never got that far due to a
setup mistake, or the DUT genuinely hung. See
[failure-triage.md](failure-triage.md) before drawing a conclusion.

## Serving files to the DUT

`hw_tests.labgrid.exporter_http_server(ssh, files)` starts a short-lived
`http.server` on the exporter (reachable from U-Boot's `wget`) and cleans
it up on exit:

```python
from hw_tests.labgrid import exporter_http_server

files = {images.artifact_path("kernel"): kernel, ...}
with exporter_http_server(ssh, files) as port:
    console.sendline(f"wget ${{kernel_addr_r}} {openocd.interface.host}:/{images.artifact_path('kernel')}")
    console.expect(uboot_driver.prompt, timeout=180)
```

Reuse this instead of writing a new file-serving mechanism.

## SSH, secrets, and redaction

`hw_tests.github.GitHub.mask(value)` and `hw_tests.logging.register_sensitive`
redact coordinator hostnames, exporter hosts, and any explicitly registered
value from subsequent log output (`LabgridClient` already masks the
coordinator and exporter hosts it touches). If a test introduces a new
secret-shaped value (a token, an internal hostname), register it the same
way — don't print it raw "for debugging."
