import os
import re

import pytest
from pexpect import TIMEOUT

from hw_tests.labgrid.environment import (
    coordinator_from_pytest,
    env_path_from_pytest,
    get_target,
    labgrid_environment,
)
from hw_tests.labgrid.labgrid_client import LabgridClient, acquired_places, places_from_env
from hw_tests.labgrid.linux import (
    boot_linux_from_uboot,
    linux_artifact_path,
    remote_http_server,
)
from hw_tests.labgrid.uboot import (
    artifact_path,
    boot_to_uboot,
    get_boot_mode_output,
    run_uboot_command,
    set_spi_boot_mode,
    wait_for_prompt,
)


def expect_text(console, text, timeout):
    index, before, _, _ = console.expect([re.escape(text), TIMEOUT], timeout=timeout)
    if index == 0:
        return before.decode("utf-8", "replace")
    raise AssertionError(f"console text {text!r} not found")


def expect_one_of(console, texts, timeout):
    patterns = [re.escape(text) for text in texts]
    index, before, _, _ = console.expect([*patterns, TIMEOUT], timeout=timeout)
    if index < len(texts):
        return before.decode("utf-8", "replace")
    raise AssertionError(f"none of {texts!r} found")


@pytest.mark.bootstrap
def test_bootstrap_linux_installer_to_spi_uboot(pytestconfig):
    places = places_from_env()
    if not places:
        pytest.skip("missing LG_TARGETS or LG_PLACE")

    config_file = env_path_from_pytest(pytestconfig)
    assert config_file, "missing environment config (use --lg-env, LABGRID_ENV or LG_ENV)"

    spl = artifact_path(os.environ.get("UBOOT_SPL", "images/u-boot-spl"), "U-Boot SPL")
    uboot_bin = artifact_path(os.environ.get("UBOOT", "images/u-boot"), "U-Boot")
    kernel = linux_artifact_path(
        os.environ.get("KERNEL_IMAGE", "images/Image"), "Linux kernel"
    )
    devicetree = linux_artifact_path(
        os.environ.get("DEVICETREE", "images/sc598-som-ezkit.dtb"),
        "Linux device tree",
    )

    coordinator = coordinator_from_pytest(pytestconfig)
    client = LabgridClient(coordinator=coordinator, config=config_file)
    preacquired = os.environ.get("HW_TEST_TARGETS_PREACQUIRED") == "true"

    with acquired_places(client, places, acquire=not preacquired):
        with labgrid_environment(config_file, coordinator=coordinator) as env:
            for place in places:
                target = get_target(env, place, config_file)
                get_boot_mode_output(target, required=True)

                console = boot_to_uboot(target, spl, uboot_bin)
                output = run_uboot_command(console, "version", require_output=True)
                assert "U-Boot" in output, "version output did not contain U-Boot"

                with remote_http_server(target, kernel, devicetree) as server:
                    boot_linux_from_uboot(console, server)
                    expect_text(console, "Continue? [y/N]:", timeout=240)
                    print("Linux booted")
                    console.sendline("y")
                    expect_text(console, "SPI install complete", timeout=600)
                    print("SPI install complete")
                    expect_one_of(
                        console,
                        [
                            "Set the switch S1 to position 1",
                            "Waiting for switch",
                        ],
                        timeout=120,
                    )

                    set_spi_boot_mode(target, required=True)
                    wait_for_prompt(console, timeout=240)

                output = run_uboot_command(console, "version", require_output=True)
                assert "U-Boot" in output, "version output did not contain U-Boot"
                print("SPI U-Boot verified")
