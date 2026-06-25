import logging
import pytest

from hw_tests.github import GitHub
from hw_tests.labgrid.environment import labgrid_environment
from hw_tests.labgrid.labgrid_client import LabgridClient, acquired_places
from hw_tests.labgrid.uboot import boot_to_uboot, run_uboot_command
from hw_tests.opkssh import OPKSSH

logger = logging.getLogger(__name__)


@pytest.mark.uboot
def test_uboot_version(context):
    github = GitHub(context)
    images = github.download("images-bootstrap-adi_sc598_ezkit_defconfig")

    spl = images / "u-boot-spl"
    uboot = images / "u-boot"

    client = LabgridClient(context, require_place=True)
    OPKSSH()

    place = client.place
    with acquired_places(client, [place]):
        with labgrid_environment(client.config, coordinator=client.coordinator) as env:
            place_ = env.get_target(place)
            console = boot_to_uboot(place_, spl, uboot)
            output = run_uboot_command(console, "version", require_output=True)
            assert "U-Boot" in output, "version output did not contain U-Boot"
            logger.info(output)
