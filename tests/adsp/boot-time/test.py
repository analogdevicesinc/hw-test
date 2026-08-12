import logging
import re
import shlex
import threading
from pathlib import Path
from time import monotonic, sleep

import pytest

from hw_tests.labgrid import LabgridClient

logger = logging.getLogger(__name__)

FILES = Path(__file__).parent / "files"

POWER_ON_LEVEL = True
MARKER_DEBOUNCE = 0.05

class BootTimer(threading.Thread):
    def __init__(self, power_sense, boot_done, poll_interval=0.01):
        super().__init__(daemon=True)
        self._power_sense = power_sense
        self._boot_done = boot_done
        self._poll_interval = poll_interval
        self._stop_event = threading.Event()
        self.power_time = None
        self.done_time = None

    def stop(self):
        self._stop_event.set()

    def run(self):
        # Start timing the instant power is detected.
        while not self._stop_event.is_set():
            if bool(self._power_sense.get()) == POWER_ON_LEVEL:
                self.power_time = monotonic()
                logger.info("Power detected on power_sense")
                break
            sleep(self._poll_interval)

        if self.power_time is None:
            return

        # The service toggles the line at boot-complete; arm on a stable low then
        # time the low->high edge, which is independent of the pin's idle level.
        def await_stable(level):
            since = None
            while not self._stop_event.is_set():
                if bool(self._boot_done.get()) == level:
                    since = since or monotonic()
                    if monotonic() - since >= MARKER_DEBOUNCE:
                        return since
                else:
                    since = None
                sleep(self._poll_interval)
            return None

        if await_stable(False) is None:
            return
        rise_time = await_stable(True)
        if rise_time is None:
            return
        self.done_time = rise_time
        logger.info("Boot-trace marker rising edge detected on boot_done")

    @property
    def elapsed(self):
        if self.power_time is None or self.done_time is None:
            return None
        return self.done_time - self.power_time


def _login(console, prompt, user, password):
    for _ in range(5):
        console.expect("login:", timeout=240)
        sleep(1)
        console.sendline(user)
        if console.expect(["[Pp]assword:", "login:"], timeout=30)[0] != 0:
            continue
        console.sendline(password)
        if console.expect([re.escape(prompt), "login:"], timeout=30)[0] == 0:
            return
    raise AssertionError("failed to log in over the console")


def _board_ip(console, prompt):
    console.sendline("udhcpc -i end0 -n -q 2>/dev/null; ip -4 -o addr show end0")
    match = console.expect(r"inet (\d+\.\d+\.\d+\.\d+)", timeout=60)[2]
    ip = match.group(1).decode()
    console.expect(re.escape(prompt), timeout=15)
    console.sendline("faillock --user root --reset 2>/dev/null; true")
    console.expect(re.escape(prompt), timeout=15)
    logger.info("Board DHCP address: %s", ip)
    return ip


def _install_service(ssh, board_ip, password):
    """Copy the gpio-boot-trace service to the board and enable it.

    The board's rootfs is only reachable from the exporter, so the files are
    staged there and pushed to the board with scp (root password auth).
    """
    opts = (
        "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
        "-o NumberOfPasswordPrompts=1 -o ConnectTimeout=10"
    )
    staging = "/tmp/hw-test-boottrace"
    askpass = f"{staging}/askpass"

    ssh.run_check(f"rm -rf {staging} && mkdir -p {staging}")
    ssh.put(str(FILES / "gpio-boot-trace"), f"{staging}/gpio-boot-trace")
    ssh.put(str(FILES / "gpio-boot-trace.service"), f"{staging}/gpio-boot-trace.service")
    ssh.run_check(
        f"printf '#!/bin/sh\\necho {password}\\n' > {askpass} && chmod +x {askpass}"
    )
    prefix = f"SSH_ASKPASS={askpass} SSH_ASKPASS_REQUIRE=force setsid -w"

    def _run_command(command):
        for attempt in range(4):
            try:
                return ssh.run_check(command)
            except Exception:
                if attempt == 3:
                    raise
                sleep(5)

    _run_command(
        f"{prefix} scp {opts} {staging}/gpio-boot-trace "
        f"{staging}/gpio-boot-trace.service root@{board_ip}:/tmp/"
    )
    remote = (
        "install -m0755 /tmp/gpio-boot-trace /usr/libexec/gpio-boot-trace && "
        "install -m0644 /tmp/gpio-boot-trace.service "
        "/lib/systemd/system/gpio-boot-trace.service && "
        "systemctl unmask gpio-boot-trace.service; systemctl daemon-reload && "
        "systemctl enable gpio-boot-trace.service && sync"
    )
    _run_command(f"{prefix} ssh {opts} root@{board_ip} {shlex.quote(remote)}")
    logger.info("gpio-boot-trace service installed into SPI rootfs")


@pytest.mark.linux
def test_boot_time(context, record_property):
    login_user = context.get("login_user", "root")
    login_password = context.get("login_password", "adi")
    linux_prompt = context.get("linux_prompt", "# ")

    client = LabgridClient(context)
    with client.acquire() as target:
        spi_boot = target.get_driver("DigitalOutputProtocol", name="spi_boot")
        power = target.get_driver("PowerProtocol")
        console = target.get_driver("ConsoleProtocol")
        ssh = target.get_driver("SSHDriver")
        power_sense = target.get_driver(
            "DigitalOutputProtocol", name="power_sense", activate=False
        )
        boot_done = target.get_driver(
            "DigitalOutputProtocol", name="boot_done", activate=False
        )

        # Assuming the board is already programmed until init script updated
        spi_boot.set(True)
        target.activate(console)

        # Boot and install the service 
        power.cycle()
        _login(console, linux_prompt, login_user, login_password)
        board_ip = _board_ip(console, linux_prompt)
        _install_service(ssh, board_ip, login_password)

        # Do a full power cycle, the timer will start when power comes back up enough for the FT to read it
        target.activate(power_sense)
        target.activate(boot_done)
        power_sense.get()
        boot_done.get()
        power.off()
        sleep(3)
        timer = BootTimer(power_sense, boot_done)
        power.on()
        timer.start()
        try:
            timer.join(timeout=180)
        finally:
            timer.stop()
            timer.join(timeout=5)

        assert timer.power_time is not None, "power-on was never detected"
        assert timer.done_time is not None, "boot-trace marker was never set"

        boot_time = timer.elapsed
        record_property("boot_time_s", round(boot_time, 3))
        logger.info("Boot time (power-on to boot-trace marker): %.3f s", boot_time)
