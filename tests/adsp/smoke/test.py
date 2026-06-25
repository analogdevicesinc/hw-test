import pytest

from hw_tests.labgrid.environment import labgrid_environment
from hw_tests.labgrid.labgrid_client import LabgridClient, acquired_places, list_places
from hw_tests.opkssh import OPKSSH


@pytest.mark.smoke
def test_smoke(context):
    client = LabgridClient(context, require_place=True)
    list_places(client)
    OPKSSH()

    place = client.place
    with acquired_places(client, [place]):
        with labgrid_environment(client.config, coordinator=client.coordinator) as env:
            target_ = env.get_target(place)

            from labgrid.driver import SSHDriver
            from labgrid.exceptions import NoDriverFoundError
            from labgrid.resource import NetworkService

            networkservice = target_.get_resource(NetworkService)
            assert networkservice.username, (
                f"missing NetworkService.username for place {place}"
            )

            try:
                ssh = target_.get_driver("SSHDriver")
            except NoDriverFoundError:
                target_.set_binding_map({"networkservice": networkservice.name})
                ssh = SSHDriver(target_, name=networkservice.name)
                target_.activate(ssh)

            ssh.run_check("true")
