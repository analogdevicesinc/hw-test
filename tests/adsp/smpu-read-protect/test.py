import logging
import time

import pytest

from hw_tests.github import GitHub
from hw_tests.images import Images
from hw_tests.labgrid import LabgridClient, exporter_http_server

logger = logging.getLogger(__name__)

# SMPU2 (L2-Core Port 0, the ARM data port) covers 0x20000000-0x200FFFFF
# (HRM Table 12-1) and is region index 0 in drivers/bus/adi-adsp-smpu.c's
# reg list, so its debugfs instance is "smpu0". Region 0 registers, base
# ADI_SMPU_RCTL(0) = 0x31083000 + 0x20.
SMPU2_BASE = 0x31083000
SMPU2_REGION0_RCTL = SMPU2_BASE + 0x20
SMPU2_REGION0_RADDR = SMPU2_BASE + 0x24
SMPU2_REGION0_RIDA = SMPU2_BASE + 0x28
SMPU2_REGION0_RIDMSKA = SMPU2_BASE + 0x2C
SMPU2_REGION0_RIDB = SMPU2_BASE + 0x30
SMPU2_REGION0_RIDMSKB = SMPU2_BASE + 0x34

# Free hole above every reserved-memory region and outside the usable
# memory@ node, so the kernel never allocates from it; 4 KB (SMPU minimum)
# aligned, matching ADI_SMPU_RADDR_MASK = GENMASK(31, 12).
PROTECTED_ADDR = 0x200D0000
CONTROL_ADDR_BELOW = 0x200CF000
CONTROL_ADDR_ABOVE = 0x200D1000

RCTL_RPROTEN_EN = 0x101  # BIT(8) RPROTEN | BIT(0) EN, SIZE field 0 = 4 KB
TID_EXACT_MASK = 0x1FFF  # 13-bit transaction ID, exact match

# A read-protect violation takes the synchronous bus-error path (SIGBUS to
# the reading process), so the console survives and devmem just reports it.
# A write-protect violation is posted and arrives as an uncontainable async
# SError, which arm64 treats as fatal, so only read-protect is testable here.
SMPU_POKE_COMMANDS = [
    f"mw.l {SMPU2_REGION0_RCTL:x} 0",
    f"mw.l {SMPU2_REGION0_RADDR:x} {PROTECTED_ADDR:x}",
    f"mw.l {SMPU2_REGION0_RIDA:x} 0",
    f"mw.l {SMPU2_REGION0_RIDMSKA:x} {TID_EXACT_MASK:x}",
    f"mw.l {SMPU2_REGION0_RIDB:x} 0",
    f"mw.l {SMPU2_REGION0_RIDMSKB:x} {TID_EXACT_MASK:x}",
    f"mw.l {SMPU2_REGION0_RCTL:x} {RCTL_RPROTEN_EN:x}",
]


@pytest.mark.linux
def test_smpu_read_protect(context):
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

            # Pinned bootstrap u-boot leaves the SMPU permissive; poke the
            # region registers a stricter firmware policy would program, in
            # place of a real sc5xx_soc_init() change we can't flash here.
            for command in SMPU_POKE_COMMANDS:
                console.sendline(command)
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

            console.sendline("run ramargs")
            console.expect(uboot_driver.prompt, timeout=30)

            console.sendline("booti ${kernel_addr_r} ${ramdisk_addr_r} ${fdt_addr_r}")
            uboot_driver.await_boot()
            target.deactivate(uboot_driver)
            logger.info("Linux booted")

            console.expect("login:", timeout=240)
            console.sendline("root")
            console.expect([r"# ", r"~ #"], timeout=30)
            logger.info("Reached initramfs shell")

            console.sendline("mount -t debugfs none /sys/kernel/debug")
            console.expect(["# ", "~ #"], timeout=30)

            # Controls: just outside the protected 4 KB window, reads must
            # go through untouched. Proves the base/size math is exact
            # before trusting the protected read below.
            for addr in (CONTROL_ADDR_BELOW, CONTROL_ADDR_ABOVE):
                console.sendline(f"devmem 0x{addr:x} 32")
                index = console.expect(["Bus error", r"0x[0-9a-fA-F]+", r"# ", r"~ #"], timeout=30)
                assert index != 0, f"control address 0x{addr:x} unexpectedly faulted"

            console.sendline(f"devmem 0x{PROTECTED_ADDR:x} 32")
            console.expect("Bus error", timeout=30)
            logger.info("SMPU2 blocked the read as expected")

            console.sendline("cat /sys/kernel/debug/*/smpu0/status")
            console.expect(r"Bus error:\s+yes", timeout=30)
            logger.info("SMPU2 debugfs confirms the bus error")
