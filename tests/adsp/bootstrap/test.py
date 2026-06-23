import re
import logging

import pytest

from hw_tests.github import GitHub
from hw_tests.labgrid import LabgridClient, exporter_http_server

logger = logging.getLogger(__name__)


def find_one(path, pattern):
    matches = sorted(path.glob(pattern))
    assert matches, f"missing {path / pattern}"
    assert len(matches) == 1, f"multiple files match {path / pattern}"
    return matches[0]


@pytest.mark.bootstrap
def test_bootstrap(context):
    github = GitHub(context)
    images = github.download("images-bootstrap-adi_sc598_ezkit_defconfig")

    spl = images / "u-boot-spl"
    uboot = images / "u-boot"
    kernel = images / "Image"
    devicetree = find_one(images, "*.dtb")

    client = LabgridClient(context)
    with client.acquire() as target:
        spi_boot = target.get_driver("SerialPortDigitalOutputDriver", name="spi_boot")
        power = target.get_driver("PowerProtocol")
        ssh = target.get_driver("SSHDriver")
        openocd = target.get_driver("OpenOCDDriver", activate=False)
        uboot_driver = target.get_driver("UBootDriver", name="uboot", activate=False)
        console = uboot_driver.console

        spi_boot.set(True)
        power.cycle()

        ssh.put(str(spl), "u-boot-spl")
        ssh.put(str(uboot), "u-boot")

        target.activate(openocd)
        try:
            openocd.execute(openocd.load_commands)
        finally:
            target.deactivate(openocd)

        target.activate(uboot_driver)
        console.sendline("version")
        console.expect("U-Boot", timeout=30)
        console.expect(uboot_driver.prompt, timeout=30)

        with exporter_http_server(ssh, kernel, devicetree):
            console.sendline("dhcp")
            console.expect(uboot_driver.prompt, timeout=120)

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

            console.expect(re.escape("Waiting for switch"), timeout=120)

            spi_boot.set(False)
            target.deactivate(spi_boot)

            target.activate(uboot_driver)
            console.sendline("version")
            console.expect("U-Boot", timeout=30)
            console.expect(uboot_driver.prompt, timeout=30)
            logger.info("SPI U-Boot verified")
