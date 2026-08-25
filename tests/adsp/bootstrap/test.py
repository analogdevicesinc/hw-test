import logging
import re
import time

import pytest

from hw_tests.github import GitHub
from hw_tests.images import Images
from hw_tests.labgrid import LabgridClient, exporter_http_server

logger = logging.getLogger(__name__)


@pytest.mark.bootstrap
def test_bootstrap(context):
    github = GitHub(context)
    images = Images(context, github)

    spl = images.get("spl")
    uboot = images.get("uboot")
    kernel = images.get("kernel")
    devicetree = images.get("dtb")
    emmc_image = images.get("emmc")

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

        with exporter_http_server(ssh, kernel, devicetree, emmc_image) as port:
            console.sendline("dhcp")
            console.expect(uboot_driver.prompt, timeout=120)

            # This is not part of the manual bootstrap flow in documentation,
            # but it is needed to avoid collisions on exporter.
            console.sendline(f"setenv httpdstp {port}")
            console.expect(uboot_driver.prompt, timeout=30)

            console.sendline(
                f"wget ${{kernel_addr_r}} {openocd.interface.host}:/{kernel.name}"
            )
            console.expect(uboot_driver.prompt, timeout=180)

            console.sendline(
                f"wget ${{fdt_addr_r}} {openocd.interface.host}:/{devicetree.name}"
            )
            console.expect(uboot_driver.prompt, timeout=180)

            console.sendline("booti ${kernel_addr_r} - ${fdt_addr_r}")
            uboot_driver.await_boot()
            target.deactivate(uboot_driver)
            logger.info("Linux booted")

            console.expect(re.escape("Continue? [y/N]:"), timeout=240)
            console.sendline("y")
            console.expect(re.escape("SPI install complete"), timeout=600)
            logger.info("SPI install complete")

            # This test only serves the Buildroot eMMC image.
            console.expect(re.escape("Choice [0/1/2]:"), timeout=240)
            console.sendline("1")
            console.expect(re.escape("PC IP address:"), timeout=240)
            console.sendline(f"{openocd.interface.host}:{port}")
            console.expect(re.escape("eMMC install complete."), timeout=1800)
            logger.info("eMMC install complete")

            console.expect(re.escape("Waiting for switch"), timeout=120)

            spi_boot.set(True)
            target.deactivate(spi_boot)
            console.expect(re.escape("SPI boot mode detected."), timeout=30)
            console.expect(re.escape("Rebooting..."), timeout=30)

            target.activate(uboot_driver)
            console.sendline("version")
            console.expect("U-Boot", timeout=30)
            console.expect(uboot_driver.prompt, timeout=30)
            logger.info("SPI U-Boot verified")

            console.sendline("run emmcboot")
            uboot_driver.await_boot()
            console.expect("login:", timeout=240)
            logger.info("eMMC Linux boot verified")
