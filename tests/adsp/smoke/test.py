import pytest

from hw_tests.labgrid import LabgridClient


@pytest.mark.smoke
def test_smoke(context):
    client = LabgridClient(context)
    with client.acquire() as target:
        ssh = target.get_driver("SSHDriver")
        ssh.run_check("true")
