import logging
import time

import pytest

from hw_tests.github import GitHub
from hw_tests.images import Images
from hw_tests.labgrid import LabgridClient

logger = logging.getLogger(__name__)


@pytest.mark.uboot
def test_uboot_version(context):
    github = GitHub(context)
    images = Images(context, github)
    spl = images.get("spl")
    uboot_image = images.get("uboot")

    assert spl.is_file(), f"missing SPL image: {spl}"
    assert uboot_image.is_file(), f"missing U-Boot image: {uboot_image}"

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
        ssh.put(str(uboot_image), "u-boot")

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
        logger.info("U-Boot prompt verified")
