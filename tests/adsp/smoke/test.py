from shutil import which

from hw_tests.labgrid.environment import labgrid_environment
from hw_tests.labgrid.labgrid_client import LabgridClient, acquired_places, list_places
from hw_tests.opkssh import OPKSSH


def main(context):
    target = context.get('labgrid_target')
    assert target, "missing labgrid_target in context"
    coordinator = context.get('labgrid_coordinator')
    assert coordinator, "missing labgrid_coordinator in context"
    config_file = f"envs/{target}.yaml"

    for executable in ("labgrid-client", "ssh"):
        assert which(executable), f"missing executable: {executable}"

    client = LabgridClient(coordinator=coordinator, timeout=20)
    list_places(client)  # verify coordinator is reachable

    OPKSSH()

    client = LabgridClient(coordinator=coordinator, config=config_file, place=target)
    with acquired_places(client, [target]):
        with labgrid_environment(config_file, coordinator=coordinator) as env:
            target_ = env.get_target(target)

            from labgrid.driver import SSHDriver
            from labgrid.exceptions import NoDriverFoundError
            from labgrid.resource import NetworkService

            networkservice = target_.get_resource(NetworkService)
            assert networkservice.username, (
                f"missing NetworkService.username for target {target}"
            )

            try:
                ssh = target_.get_driver("SSHDriver")
            except NoDriverFoundError:
                target_.set_binding_map({"networkservice": networkservice.name})
                ssh = SSHDriver(target_, name=networkservice.name)
                target_.activate(ssh)

            ssh.run_check("true")
