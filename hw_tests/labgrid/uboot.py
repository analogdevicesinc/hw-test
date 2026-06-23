import time

from labgrid.protocol import ConsoleProtocol, DigitalOutputProtocol
from labgrid.util.ssh import sshmanager
from pexpect import TIMEOUT

BOOT_MODE_RESOURCE = "boot-mode"
CONSOLE_RESOURCE = "console"


def get_boot_mode_output(target, required=False):
    for driver in target.drivers:
        if not isinstance(driver, DigitalOutputProtocol):
            continue
        resources = driver.get_bound_resources()
        if any(
            getattr(resource, "name", None) == BOOT_MODE_RESOURCE
            for resource in resources
        ):
            target.activate(driver)
            return driver

    if required:
        raise AssertionError(
            "missing digital output bound to resource, expected name is "
            f"{BOOT_MODE_RESOURCE!r}."
        )
    return None


def get_console(target):
    for driver in target.drivers:
        if not isinstance(driver, ConsoleProtocol):
            continue
        resources = driver.get_bound_resources()
        if any(
            getattr(resource, "name", None) == CONSOLE_RESOURCE
            for resource in resources
        ):
            target.activate(driver)
            return driver

    raise AssertionError(
        f"missing console bound to resource, expected name is {CONSOLE_RESOURCE!r}."
    )


def set_jtag_boot_mode(target):
    output = get_boot_mode_output(target, required=False)
    if output is None:
        return False
    output.set(True)
    return True


def set_spi_boot_mode(target, required=False):
    # Releasing the boot-mode output lets the board fall back to SPI boot.
    output = get_boot_mode_output(target, required=required)
    if output is None:
        return False
    output.set(False)
    target.deactivate(output)
    return True


def stage_openocd_file(target, local_path, remote_name):
    openocd = target.get_driver("OpenOCDDriver", activate=False)
    ssh = sshmanager.open(openocd.interface.host)
    ssh.put_file(str(local_path), remote_name)
    return openocd


def stage_uboot_artifacts(target, spl_path, uboot_path):
    openocd = stage_openocd_file(target, spl_path, "u-boot-spl")
    stage_openocd_file(target, uboot_path, "u-boot")
    return openocd


def execute_openocd_boot(target, openocd):
    target.activate(openocd)
    openocd.execute(openocd.load_commands)


def wait_for_prompt(console, prompt="=> ", timeout=30):
    deadline = time.monotonic() + timeout
    captured = bytearray()

    while time.monotonic() < deadline:
        index, before, _, _ = console.expect([prompt, "U-Boot", TIMEOUT], timeout=2)
        captured.extend(before)
        if index == 0:
            return captured.decode("utf-8", "replace")
        console.sendline("")

    raise AssertionError(
        f"U-Boot prompt {prompt!r} not found. Captured console output:\n"
        + captured.decode("utf-8", "replace")
    )


def drain_console(console, quiet_time=0.2, timeout=2.0):
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        index, _, _, _ = console.expect([r"[\s\S]+", TIMEOUT], timeout=quiet_time)
        if index == 1:
            return


def run_uboot_command(
    console, command, prompt="=> ", timeout=30, require_output=False, drain=True
):
    for _ in range(2 if require_output else 1):
        if drain:
            drain_console(console)
        console.sendline(command)
        _, before, _, _ = console.expect(prompt, timeout=timeout)
        output = before.decode("utf-8", "replace")
        if not require_output or output.strip():
            return output

    raise AssertionError(f"U-Boot command {command!r} produced no output")


def boot_to_uboot(target, spl_path, uboot_path, prompt="=> "):
    set_jtag_boot_mode(target)
    target.get_driver("PowerProtocol").cycle()
    openocd = stage_uboot_artifacts(target, spl_path, uboot_path)
    execute_openocd_boot(target, openocd)

    console = get_console(target)
    wait_for_prompt(console, prompt=prompt)
    return console
