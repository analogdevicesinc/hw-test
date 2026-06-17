import importlib
import subprocess
from shutil import which

import pytest

from hw_tests.labgrid.environment import (
    coordinator_from_pytest,
    env_path_from_pytest,
    get_target,
    labgrid_environment,
)
from hw_tests.labgrid.labgrid_client import LabgridClient, list_places, places_from_env


@pytest.mark.smoke
def test_verify(pytestconfig):
    for module_name in ("labgrid", "pexpect", "pytest"):
        module = importlib.import_module(module_name)
        assert module is not None, f"failed to import {module_name}"

    for executable in ("labgrid-client", "ssh"):
        assert which(executable), f"missing executable: {executable}"

    help_result = subprocess.run(
        ["labgrid-client", "--help"],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert "usage:" in help_result.stdout.lower()

    coordinator = coordinator_from_pytest(pytestconfig)
    assert coordinator, (
        "missing --lg-coordinator, LG_COORDINATOR or LABGRID_COORDINATOR"
    )

    client = LabgridClient(coordinator=coordinator, timeout=20)
    try:
        places = list_places(client)
    except subprocess.CalledProcessError:
        raise AssertionError("failed to list labgrid places") from None

    assert places, "coordinator returned no labgrid places"


@pytest.mark.smoke
def test_labgrid_ssh_connection(pytestconfig):
    places = places_from_env()
    if not places:
        pytest.skip("missing LG_TARGETS or LG_PLACE")

    env_path = env_path_from_pytest(pytestconfig)
    assert env_path, "missing environment config (use --lg-env, LABGRID_ENV or LG_ENV)"
    coordinator = coordinator_from_pytest(pytestconfig)

    with labgrid_environment(env_path, coordinator=coordinator) as env:
        for place in places:
            target = get_target(env, place, env_path)

            from labgrid.driver import SSHDriver
            from labgrid.exceptions import NoDriverFoundError
            from labgrid.resource import NetworkService

            networkservice = target.get_resource(NetworkService)
            assert networkservice.username, (
                f"missing NetworkService.username for target {place}"
            )

            try:
                ssh = target.get_driver("SSHDriver")
            except NoDriverFoundError:
                target.set_binding_map({"networkservice": networkservice.name})
                ssh = SSHDriver(target, name=networkservice.name)
                target.activate(ssh)

            ssh.run_check("true")
