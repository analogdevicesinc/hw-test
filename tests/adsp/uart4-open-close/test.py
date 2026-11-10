"""Open and close an adi_uart4 port in DMA mode while RX data is pending.

Each last close runs adi_uart4_serial_shutdown(), which tears down RX DMA
and the RX flush timer. UART3 is unused on the EZ-Kit, so it is enabled in
the device tree from U-Boot and put in internal loopback mode (UART_CTL
LOOP_EN, with MRTS to enable the transmitter), so that every write lands in
the RX DMA buffer without any wiring.
"""

import logging
import re
import time

import pytest

from hw_tests.github import GitHub
from hw_tests.images import Images
from hw_tests.labgrid import LabgridClient, exporter_http_server

logger = logging.getLogger(__name__)

UART_NODE = "/scb/serial@31003c00"
UART_DEV = "/dev/ttySC3"
UART_CTL = 0x31003C04
LOOP_EN = 1 << 1
MRTS = 1 << 25
# adi_uart4 sets fifosize to UART_XMIT_SIZE only when DMA is in use.
DMA_FIFO_SIZE = 4096

SHELL_PROMPT = r"# "
FAILURE_PATTERNS = [
    r"Unable to handle kernel",
    r"Internal error: Oops",
    r"Kernel panic",
    r"BUG: ",
    r"WARNING: CPU",
]

SET_LOOPBACK = (
    f"devmem {UART_CTL:#x} 32 $(( $(devmem {UART_CTL:#x} 32) | {LOOP_EN | MRTS:#x} ))"
)


def shell(console, command, timeout=30):
    """Run a command on the console and return its output."""
    console.sendline(command)
    _, before, _, _ = console.expect(SHELL_PROMPT, timeout=timeout)
    return before.decode(errors="replace")


def expect_or_crash(console, pattern, timeout):
    """Wait for pattern, failing early on a kernel crash."""
    index, _, match, _ = console.expect([pattern, *FAILURE_PATTERNS], timeout=timeout)
    if index:
        _, before, end, _ = console.expect(
            r"end Kernel panic|---\[ end trace", timeout=30
        )
        report = (match.group(0) + before + end.group(0)).decode(errors="replace")
        pytest.fail(f"Kernel crash:\n{report}")
    return match


@pytest.mark.linux
def test_uart4_open_close(context):
    duration = int(context.get("duration_s", 600))

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

            console.sendline(
                f"wget ${{kernel_addr_r}} {openocd.interface.host}:/"
                f"{images.artifact_path('kernel')}"
            )
            console.expect(uboot_driver.prompt, timeout=180)

            console.sendline(
                f"wget ${{fdt_addr_r}} {openocd.interface.host}:/"
                f"{images.artifact_path('dtb')}"
            )
            console.expect(uboot_driver.prompt, timeout=180)

            console.sendline(
                f"wget ${{ramdisk_addr_r}} {openocd.interface.host}:/"
                f"{images.artifact_path('rootfs')}"
            )
            console.expect(uboot_driver.prompt, timeout=180)

            # UART3 is disabled in the EZ-Kit device tree.
            console.sendline("fdt addr ${fdt_addr_r}")
            console.expect(uboot_driver.prompt, timeout=30)
            console.sendline("fdt resize")
            console.expect(uboot_driver.prompt, timeout=30)
            console.sendline(f"fdt set {UART_NODE} status okay")
            console.expect(uboot_driver.prompt, timeout=30)

            console.sendline("run ramargs")
            console.expect(uboot_driver.prompt, timeout=30)

            console.sendline("booti ${kernel_addr_r} ${ramdisk_addr_r} ${fdt_addr_r}")
            uboot_driver.await_boot()
            target.deactivate(uboot_driver)
            logger.info("Linux booted")

            index, _, _, _ = console.expect(["login:", SHELL_PROMPT], timeout=240)
            if index == 0:
                console.sendline("root")
                console.expect(SHELL_PROMPT, timeout=30)
            logger.info("Reached initramfs shell")

            # Check that the port is in DMA mode and that loopback works.
            # Output markers are split in the command so that the echoed
            # command line does not match them.
            shell(console, f"exec 3<>{UART_DEV}")
            shell(console, f"stty -F {UART_DEV} 115200 raw -echo min 0 time 10")
            shell(console, SET_LOOPBACK)
            fifo = shell(
                console,
                f'echo FIFO"="$(cat /sys/class/tty/{UART_DEV[5:]}/xmit_fifo_size)',
            )
            match = re.search(r"FIFO=(\d+)", fifo)
            if not match or int(match.group(1)) != DMA_FIFO_SIZE:
                pytest.fail(f"{UART_DEV} is not using DMA: {fifo!r}")

            echo = shell(console, 'printf L00P >&3; echo LB":"$(head -c 4 <&3)')
            if "LB:L00P" not in echo:
                pytest.fail(f"No loopback data on {UART_DEV}: {echo!r}")
            shell(console, "exec 3>&-")
            logger.info("%s in DMA mode, loopback works", UART_DEV)

            # Randomize the close against the 50 ms RX flush timer.
            console.sendline(
                f"end=$(( $(date +%s) + {duration} )); n=0; "
                f"while [ $(date +%s) -lt $end ]; do "
                f"exec 3<>{UART_DEV}; {SET_LOOPBACK}; "
                f"head -c 256 /dev/zero | tr '\\0' U >&3; "
                f"usleep $(( RANDOM % 50000 )); "
                f"exec 3>&-; n=$((n + 1)); "
                f'done; echo UART4_LOOP" "DONE $n'
            )
            match = expect_or_crash(
                console, r"UART4_LOOP DONE (\d+)", timeout=duration + 120
            )
            cycles = int(match.group(1))
            logger.info("%d open/close cycles in %d s", cycles, duration)

            console.expect(SHELL_PROMPT, timeout=30)
            shell(console, "true")
            assert cycles > 0
