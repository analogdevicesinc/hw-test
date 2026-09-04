import logging
import time

import pytest

from hw_tests.github import GitHub
from hw_tests.images import Images
from hw_tests.labgrid import LabgridClient, exporter_http_server

logger = logging.getLogger(__name__)


@pytest.mark.linux
def test_initramfs_boot(context):
    """Boot the kernel under test to a shell entirely from RAM.

    The kernel and its device tree are the artifacts under test (linux flavor);
    the SPL, U-Boot and initramfs rootfs are pinned to a stable br2-external run
    (source = "br2"). U-Boot is side-loaded over the debugger, then the three
    blobs are fetched over the network and booted with `booti` — nothing is
    written to the board, so a bad kernel cannot brick it.
    """
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

        ssh.put(str(spl), "u-boot-spl")
        ssh.put(str(uboot), "u-boot")

        target.activate(console)
        target.activate(openocd)
        try:
            openocd.execute(openocd.load_commands)
        finally:
            target.deactivate(openocd)

        console.sendline("")
        time.sleep(0.2)
        target.activate(uboot_driver)
        console.sendline("version")
        console.expect("U-Boot", timeout=30)
        console.expect(uboot_driver.prompt, timeout=30)

        files = {
            images.artifact_path("kernel"): kernel,
            images.artifact_path("dtb"): devicetree,
            images.artifact_path("rootfs"): ramdisk,
        }
        with exporter_http_server(ssh, files) as port:
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

            console.sendline("setenv bootargs ${adi_bootargs}")
            console.expect(uboot_driver.prompt, timeout=30)

            console.sendline("booti ${kernel_addr_r} ${ramdisk_addr_r} ${fdt_addr_r}")
            uboot_driver.await_boot()
            target.deactivate(uboot_driver)
            logger.info("Linux booted")

            console.expect(["login:", "buildroot", r"# ", r"~ #"], timeout=240)
            logger.info("Reached initramfs shell")
