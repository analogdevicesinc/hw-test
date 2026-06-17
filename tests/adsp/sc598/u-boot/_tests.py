import os

import pytest

from hw_tests.labgrid.environment import (
    coordinator_from_pytest,
    env_path_from_pytest,
    get_target,
    labgrid_environment,
)
from hw_tests.labgrid.labgrid_client import LabgridClient, acquired_places, places_from_env
from hw_tests.labgrid.uboot import artifact_path, boot_to_uboot, run_uboot_command


@pytest.mark.uboot
def test_jtag_boot_to_uboot(pytestconfig):
    places = places_from_env()
    if not places:
        pytest.skip("missing LG_TARGETS or LG_PLACE")

    config_file = env_path_from_pytest(pytestconfig)
    assert config_file, "missing environment config (use --lg-env, LABGRID_ENV or LG_ENV)"

    spl = artifact_path(os.environ.get("UBOOT_SPL", "images/u-boot-spl"), "U-Boot SPL")
    uboot_bin = artifact_path(os.environ.get("UBOOT", "images/u-boot"), "U-Boot")

    coordinator = coordinator_from_pytest(pytestconfig)
    client = LabgridClient(coordinator=coordinator, config=config_file)
    with acquired_places(client, places):
        with labgrid_environment(config_file, coordinator=coordinator) as env:
            for place in places:
                target = get_target(env, place, config_file)
                console = boot_to_uboot(target, spl, uboot_bin)
                output = run_uboot_command(console, "version", require_output=True)
                assert "U-Boot" in output, "version output did not contain U-Boot"
                print(output)
