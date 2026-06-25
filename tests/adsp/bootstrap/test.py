import re
import logging

import pytest

from hw_tests.github import GitHub
from hw_tests.labgrid.environment import labgrid_environment
from hw_tests.labgrid.labgrid_client import LabgridClient, acquired_places
from hw_tests.opkssh import OPKSSH
from hw_tests.labgrid.linux import (
    boot_linux_from_uboot,
    remote_http_server,
)
from hw_tests.labgrid.uboot import (
    boot_to_uboot,
    get_boot_mode_output,
    run_uboot_command,
    set_spi_boot_mode,
    wait_for_prompt,
)

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

    client = LabgridClient(context, require_place=True)
    OPKSSH()

    place = client.place
    with acquired_places(client, [place]):
        with labgrid_environment(client.config, coordinator=client.coordinator) as env:
            place_ = env.get_target(place)
            get_boot_mode_output(place_, required=True)

            console = boot_to_uboot(place_, spl, uboot)
            output = run_uboot_command(console, "version", require_output=True)
            assert "U-Boot" in output, "version output did not contain U-Boot"

            with remote_http_server(place_, kernel, devicetree) as server:
                boot_linux_from_uboot(console, server)
                console.expect(re.escape("Continue? [y/N]:"), timeout=240)
                logger.info("Linux booted")
                console.sendline("y")
                console.expect(re.escape("SPI install complete"), timeout=600)
                logger.info("SPI install complete")
                console.expect(re.escape("Waiting for switch"), timeout=120)

                set_spi_boot_mode(place_, required=True)
                wait_for_prompt(console, timeout=240)

            output = run_uboot_command(console, "version", require_output=True)
            assert "U-Boot" in output, "version output did not contain U-Boot"
            logger.info("SPI U-Boot verified")
