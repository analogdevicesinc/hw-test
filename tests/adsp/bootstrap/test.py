import re
import logging

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


def main(context):
    target = context.get('labgrid_target')
    assert target, "missing labgrid_target in context"
    coordinator = context.get('labgrid_coordinator')
    assert coordinator, "missing labgrid_coordinator in context"
    config_file = f"envs/{target}.yaml"

    github = GitHub(context)
    images = github.download("images-bootstrap-adi_sc598_ezkit_defconfig")

    spl = images / "u-boot-spl"
    uboot = images / "u-boot"
    kernel = images / "Image"
    devicetree = find_one(images, "*.dtb")

    OPKSSH()

    client = LabgridClient(coordinator=coordinator, config=config_file, place=target)
    with acquired_places(client, [target]):
        with labgrid_environment(config_file, coordinator=coordinator) as env:
            target_ = env.get_target(target)
            get_boot_mode_output(target_, required=True)

            console = boot_to_uboot(target_, spl, uboot)
            output = run_uboot_command(console, "version", require_output=True)
            assert "U-Boot" in output, "version output did not contain U-Boot"

            with remote_http_server(target_, kernel, devicetree) as server:
                boot_linux_from_uboot(console, server)
                console.expect(re.escape("Continue? [y/N]:"), timeout=240)
                logger.info("Linux booted")
                console.sendline("y")
                console.expect(re.escape("SPI install complete"), timeout=600)
                logger.info("SPI install complete")
                console.expect(re.escape("Waiting for switch"), timeout=120)

                set_spi_boot_mode(target_, required=True)
                wait_for_prompt(console, timeout=240)

            output = run_uboot_command(console, "version", require_output=True)
            assert "U-Boot" in output, "version output did not contain U-Boot"
            logger.info("SPI U-Boot verified")
