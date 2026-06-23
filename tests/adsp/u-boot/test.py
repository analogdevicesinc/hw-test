
from hw_tests.github import GitHub
from hw_tests.labgrid.environment import labgrid_environment
from hw_tests.labgrid.labgrid_client import LabgridClient, acquired_places
from hw_tests.labgrid.uboot import boot_to_uboot, run_uboot_command
from hw_tests.opkssh import OPKSSH


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

    OPKSSH()

    client = LabgridClient(coordinator=coordinator, config=config_file, place=target)
    with acquired_places(client, [target]):
        with labgrid_environment(config_file, coordinator=coordinator) as env:
            target_ = env.get_target(target)
            console = boot_to_uboot(target_, spl, uboot)
            output = run_uboot_command(console, "version", require_output=True)
            assert "U-Boot" in output, "version output did not contain U-Boot"
            print(output)
