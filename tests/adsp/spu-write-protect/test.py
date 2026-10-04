import logging
import time

import pytest

from hw_tests.github import GitHub
from hw_tests.images import Images
from hw_tests.labgrid import LabgridClient, exporter_http_server

logger = logging.getLogger(__name__)

# SPU0 peripheral 35 is gpc (gpio@31004100 in sc59x-64.dtsi, consumed as
# `access-controllers = <&spu 35>`). uart2 (peripheral 31) is status =
# "disabled" in the DT, so adi_spu_filter_bus()'s for_each_available_child_of_node()
# skips it and never logs a write-protect message; gpc is status = "okay"
# and unused by the rest of this test, so it is safe to detach.
# REG_SPU0_WP_START = 0x3108B400, stride 4.
SPU0_WP_GPC = 0x3108B400 + 35 * 4
BITM_SPU0_WP_CM_A55 = 1


@pytest.mark.linux
def test_spu_write_protect(context):
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

            # Pinned bootstrap u-boot already leaves the SPU permissive;
            # poke the one bit a stricter firmware policy would set, in
            # place of a real sc5xx_soc_init() change we can't flash here.
            console.sendline(f"mw.l {SPU0_WP_GPC:x} {BITM_SPU0_WP_CM_A55:x}")
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

            # adi_spu_filter_bus() runs at SPU probe time, well before the
            # login prompt, and logs this straight to the console - no need
            # to log in and grep dmesg for it.
            console.expect("peripheral 35 is write-protected from the A55", timeout=240)
            logger.info("SPU correctly kept gpc off the A55")

            console.expect("login:", timeout=120)
            console.sendline("root")
            console.expect([r"# ", r"~ #"], timeout=30)

            console.sendline("mount -t debugfs none /sys/kernel/debug")
            console.expect(["# ", "~ #"], timeout=30)

            # The SPU driver never programs policy itself, only reports what
            # is already set; the dmesg line above only proves gpc got
            # detached, not that debugfs is actually surfacing the WP bit
            # correctly. SPU0 base 0x3108B000 -> dev_name "3108b000.bus".
            console.sendline("cat /sys/kernel/debug/3108b000.bus/write-protect")
            console.expect(r"WP\[35\]\s*=\s*0x00000001", timeout=30)
            logger.info("SPU debugfs reports WP[35] correctly")
