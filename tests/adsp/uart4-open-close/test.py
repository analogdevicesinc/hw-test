"""Stress adi_uart4 startup/shutdown by repeatedly opening and closing a port.

adi_uart4_serial_shutdown() used to free the RX DMA buffer before stopping
the RX flush timer, so the timer could read freed memory on the last close
of a port (oops in adi_uart4_serial_rx_dma_timeout()).

ttySC0 is the console and is held open by init, so it never sees a last
close. Instead, uart2 is enabled in the devicetree from U-Boot; nothing else
opens it, so every close in the loop runs the shutdown path.

The RX flush timer is armed in startup() and fires every 50 ms while the
port is open. The bug needs it to fire during shutdown(), so each
iteration holds the port open for about one timer period (hold_ms, with
hold_jitter_ms of random spread) to vary where the close lands relative to
the timer. hold_ms = 0 opens and closes back to back instead.
"""

import logging
import re
import time

import pexpect
import pytest

from hw_tests.github import GitHub
from hw_tests.images import Images
from hw_tests.labgrid import LabgridClient, exporter_http_server

logger = logging.getLogger(__name__)

# uart2 on SC59x, aliased to serial2 (ttySC2)
UART_ALIAS = "serial2"
UART_DEVICE = "31003800.serial"

SHELL_PROMPT = r"# $"
CRASH_PATTERNS = [
    r"Unable to handle kernel",
    r"Internal error: Oops",
    r"Kernel panic",
    r"BUG: ",
    r"WARNING: CPU",
    r"rcu: INFO: rcu_.* detected stalls",
]


def shell(console, cmd, timeout=30):
    console.sendline(cmd)
    _, before, _, _ = console.expect(SHELL_PROMPT, timeout=timeout)
    return before.decode(errors="replace")


@pytest.mark.linux
def test_uart4_open_close(context):
    duration = int(context.get("duration", 600))
    hold_ms = int(context.get("hold_ms", 50))
    hold_jitter_ms = int(context.get("hold_jitter_ms", 20))

    github = GitHub(context)
    images = Images(context, github)

    spl = images.get("spl")
    uboot = images.get("uboot")
    kernel = images.get("kernel")
    devicetree = images.get("dtb")
    ramdisk = images.get("rootfs")

    client = LabgridClient(context)
    with client.acquire() as target:
        spi_boot = target.get_driver("DigitalOutputProtocol", name="spi_boot")
        power = target.get_driver("PowerProtocol")
        ssh = target.get_driver("SSHDriver")
        openocd = target.get_driver("OpenOCDDriver", activate=False)
        uboot_driver = target.get_driver("UBootDriver", name="uboot", activate=False)
        console = uboot_driver.console

        spi_boot.set(False)
        power.cycle()

        files = {
            "u-boot-spl": spl,
            "u-boot": uboot,
            images.artifact_path("kernel"): kernel,
            images.artifact_path("dtb"): devicetree,
            images.artifact_path("rootfs"): ramdisk,
        }
        with exporter_http_server(ssh, files) as (directory, port):
            target.activate(console)
            target.activate(openocd)
            try:
                openocd.execute([f"cd {directory}", *openocd.load_commands])
            finally:
                target.deactivate(openocd)

            console.sendline("")
            time.sleep(0.2)
            target.activate(uboot_driver)
            console.sendline("version")
            console.expect("U-Boot", timeout=30)
            console.expect(uboot_driver.prompt, timeout=30)

            console.sendline("dhcp")
            console.expect(uboot_driver.prompt, timeout=120)

            console.sendline(f"setenv httpdstp {port}")
            console.expect(uboot_driver.prompt, timeout=30)

            for addr, role in (
                ("kernel_addr_r", "kernel"),
                ("fdt_addr_r", "dtb"),
                ("ramdisk_addr_r", "rootfs"),
            ):
                console.sendline(
                    f"wget ${{{addr}}} {openocd.interface.host}:/"
                    f"{images.artifact_path(role)}"
                )
                console.expect(uboot_driver.prompt, timeout=180)

            # Enable a UART that nobody holds open.
            for cmd in (
                "fdt addr ${fdt_addr_r}",
                f"fdt set {UART_ALIAS} status okay",
                f"fdt print {UART_ALIAS} status",
            ):
                console.sendline(cmd)
                _, before, _, _ = console.expect(uboot_driver.prompt, timeout=30)
            assert b"okay" in before, (
                f"failed to enable {UART_ALIAS} in the devicetree"
            )

            console.sendline("run ramargs")
            console.expect(uboot_driver.prompt, timeout=30)

            console.sendline("booti ${kernel_addr_r} ${ramdisk_addr_r} ${fdt_addr_r}")
            uboot_driver.await_boot()
            target.deactivate(uboot_driver)
            logger.info("Linux booted")

            console.expect("login:", timeout=240)
            console.sendline("root")
            index, _, _, _ = console.expect([SHELL_PROMPT, "Password:"], timeout=30)
            assert index == 0, "root login asks for a password"
            logger.info("Logged in")

            # The tty sits below the serial-base port device, so resolve it
            # through /sys/class/tty instead of the platform device.
            out = shell(
                console,
                "for t in /sys/class/tty/ttySC*; do readlink -f $t; done"
                f" | grep '/{UART_DEVICE}/'",
            )
            ttys = sorted(set(re.findall(r"/tty/(ttySC\d+)\s", out)))
            assert len(ttys) == 1, f"no tty for {UART_DEVICE}: {out!r}"
            tty = f"/dev/{ttys[0]}"
            logger.info(
                "Stressing %s for %d s (hold %d ms, jitter %d ms)",
                tty,
                duration,
                hold_ms,
                hold_jitter_ms,
            )

            shell(console, "echo 8 > /proc/sys/kernel/printk")
            # No modem lines on this port: do not block open() on carrier.
            shell(console, f"stty -F {tty} clocal")
            out = shell(console, f"dmesg | grep -i '{UART_DEVICE}'")
            logger.info("dmesg: %s", out.strip())

            # Each iteration is a full open + last close, i.e. startup() and
            # shutdown() of the port.
            if hold_ms > 0:
                low_us = max(hold_ms * 1000 - hold_jitter_ms * 500, 0)
                span_us = max(hold_jitter_ms * 1000, 1)
                hold = f"usleep $(( {low_us} + (RANDOM * 32768 + RANDOM) % {span_us} )); "
                batch = 1
            else:
                hold = ""
                batch = 100
            # The 'done' marker is split so the command echo does not match.
            console.sendline(
                f"end=$(( $(date +%s) + {duration} )); n=0; "
                f"while [ $(date +%s) -lt $end ]; do "
                f"for i in $(seq {batch}); do exec 3<{tty}; {hold}exec 3<&-; done; "
                f"n=$((n + {batch})); done; "
                f"echo uart4-open-close: 'DO''NE' $n"
            )
            try:
                index, _, match, _ = console.expect(
                    [r"uart4-open-close: DONE (\d+)", *CRASH_PATTERNS],
                    timeout=duration + 120,
                )
            except pexpect.TIMEOUT:
                pytest.fail(f"board hung while stressing {tty} (no output)")
            if index != 0:
                # Collect the rest of the oops/panic for the log.
                try:
                    console.expect(r"end Kernel panic|---\[ end trace", timeout=30)
                except pexpect.TIMEOUT:
                    logger.warning("no end marker after the crash")
                pytest.fail(f"kernel crashed while stressing {tty}: {match.group(0)!r}")

            cycles = int(match.group(1).decode())
            console.expect(SHELL_PROMPT, timeout=30)
            logger.info("%d open/close cycles on %s without a crash", cycles, tty)

            # Log any driver messages from the stress (e.g. RX DMA errors).
            out = shell(console, f"dmesg | grep -iE 'adi-uart4|{UART_DEVICE}' | tail -5")
            logger.info("dmesg: %s", out.strip())
