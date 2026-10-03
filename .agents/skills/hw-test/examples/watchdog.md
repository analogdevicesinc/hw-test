# Example: watchdog test for SC846

Prompt: "Write a watchdog test for SC846, connect to the coordinator, take
a free board, and test it."

There is currently no `tests/**` watchdog test and no confirmed SC846
place in this checkout — treat both as things to verify, not assume.

1. **Find the closest pattern.** No watchdog test exists yet, so start
   from the smallest structurally-similar test:
   `tests/adsp/smoke/test.py` (SSH-only, minimal `LabgridClient` usage) for
   the acquisition/SSH skeleton, and `tests/adsp/u-boot/test.py` for the
   power/console pattern if the watchdog needs a reset to observe.
2. **Don't invent the watchdog trigger.** Grep the target Linux tree (or
   ask, if you don't have it checked out) for the watchdog driver/userspace
   tool actually in use for this board (`watchdog(8)`, `wdctl`, a sysfs
   node under `/dev/watchdog*`, or a driver-specific ioctl helper) before
   writing any `ssh.run_check(...)` command. Also check the SC846 hardware
   reference manual/data sheet — indexed at
   https://github.com/analogdevicesinc/doctools/tree/docling/media/en/technical-documentation/data-sheets
   — for the watchdog peripheral's real register/timer behavior. If you
   cannot determine the real interface from the software under test or
   these docs, say so and ask rather than guessing a plausible-looking
   command.
3. **Confirm the board exists before writing `needs`.** Run
   `labgrid-client places` (with `LG_COORDINATOR` set) and look for a place
   tagged `sc846` (or whatever tag the team actually uses — don't assume
   the string "sc846" is the tag without checking `show`/`who`). If no
   matching place exists, stop and point at
   `docs/integrate-hardware.rst` instead of fabricating one.
4. **Express the requirement as tags**, e.g. `needs = ["sc846"]` (adjust to
   the real tags once confirmed), not `labgrid_target = "<specific place>"`
   — let the pool pick any free matching board.
5. **Structure the test** on the smoke-test skeleton, add the watchdog
   trigger + expected reboot. Use `ShellDriver`, not `SSHDriver`, for every
   command that must run on the board itself — in this repo's place
   configs `SSHDriver` binds to the *exporter's* `NetworkService`, not the
   DUT, so `ssh.run_check(...)` never touches the SC846 at all. See the
   "SSHDriver reaches the exporter, not the DUT" note in
   [labgrid.md](../labgrid.md):
   ```python
   from hw_tests.labgrid import LabgridClient

   def test_watchdog_reset(context):
       client = LabgridClient(context)
       with client.acquire() as target:
           power = target.get_driver("PowerProtocol")
           shell = target.get_driver("ShellDriver", activate=False)

           power.cycle()
           target.activate(shell)      # boots and logs in

           # Confirm baseline before triggering the watchdog.
           shell.run_check("uptime")

           # Trigger the watchdog reset via the confirmed real interface,
           # e.g.: shell.run("wdctl --settimeout=1 /dev/watchdog0 && sleep 5")
           # The console will go quiet when the board reboots; that is
           # expected, not an error to work around.
           ...

           # Wait for the board to come back: target.deactivate(shell) then
           # target.activate(shell) again re-runs ShellDriver's own
           # boot/login handling, then confirm it actually reset (fresh
           # boot-id, not just "console went quiet" - a hang looks the
           # same as a reset until it comes back).
   ```
   If timing the reset needs sub-30s precision, poll `shell.console`
   directly (`console.sendline(...)`/`console.expect(shell.prompt,
   timeout=...)`) instead of `shell.run_check(...)`, which does a fixed
   ~30s prompt check per call — see `tests/adsp/watchdog/test.py` for a
   worked example of both the timing loop and the reconnect-after-reset
   dance.
6. **Register the marker** (e.g. `watchdog`) in `pyproject.toml`'s
   `markers` list if you add one — `--strict-markers` will fail otherwise.
7. **Run it locally on one board first:**
   ```bash
   export LG_COORDINATOR=<coordinator>
   set='{"name": "adsp/watchdog"}' pytest -vvs
   ```
8. **Evidence to report**: the place acquired, confirmation the watchdog
   actually fired (not just "SSH disconnected" — disconnects also happen
   from network blips), the reboot observed, and result. If the trigger
   command was guessed rather than confirmed against the real driver/tool,
   say that explicitly as a limitation.
