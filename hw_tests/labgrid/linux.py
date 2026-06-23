import shlex
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from labgrid.driver.exception import ExecutionError
from labgrid.util.ssh import sshmanager

from hw_tests.labgrid.uboot import run_uboot_command

_SCRIPTS_DIR = Path(__file__).parent
_START_SCRIPT = (_SCRIPTS_DIR / "http_server_start.py").read_text(encoding="utf-8")
_CLEANUP_SCRIPT = (_SCRIPTS_DIR / "http_server_cleanup.py").read_text(encoding="utf-8")


def linux_artifact_path(value, name):
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise AssertionError(f"missing {name}: {path}")
    return path


@dataclass(frozen=True)
class RemoteHTTPServer:
    host: str
    url_host: str
    remote_dir: str
    kernel_name: str
    devicetree_name: str


def _remote_python(script, *args):
    command = ["python3", "-c", script, *map(str, args)]
    return " ".join(shlex.quote(part) for part in command)


def _fresh_ssh(host):
    try:
        sshmanager.close(host)
    except Exception:
        try:
            sshmanager.remove_by_name(host)
        except Exception:
            pass
    return sshmanager.open(host)


def _remote_file_size(ssh, remote_path):
    output = ssh.run_check(f"stat -c %s {shlex.quote(remote_path)}")
    return int(output[0].strip())


def _put_file_checked(host, ssh, local_path, remote_path):
    expected_size = local_path.stat().st_size

    for attempt in range(1, 3):
        try:
            ssh.put_file(str(local_path), remote_path)
            return ssh
        except (subprocess.CalledProcessError, ExecutionError):
            try:
                ssh = _fresh_ssh(host)
                actual_size = _remote_file_size(ssh, remote_path)
            except Exception:
                if attempt == 2:
                    raise AssertionError(
                        f"failed to copy {local_path.name} to lab host"
                    ) from None
                ssh = _fresh_ssh(host)
                continue

            if actual_size == expected_size:
                return ssh

            if attempt == 2:
                raise AssertionError(
                    f"incomplete copy for {local_path.name}: "
                    f"{actual_size} of {expected_size} bytes"
                ) from None

            ssh = _fresh_ssh(host)

    return ssh


@contextmanager
def remote_http_server(target, kernel_path, devicetree_path):
    openocd = target.get_driver("OpenOCDDriver", activate=False)
    host = openocd.interface.host
    ssh = sshmanager.open(host)
    url_host = host

    kernel_name = kernel_path.name
    devicetree_name = devicetree_path.name

    remote_dir = ssh.run_check(
        _remote_python(
            """
import tempfile

print(tempfile.mkdtemp(prefix="hw-test-http.", dir="/tmp"))
"""
        )
    )[0]

    try:
        ssh = _put_file_checked(host, ssh, kernel_path, f"{remote_dir}/{kernel_name}")
        ssh = _put_file_checked(
            host, ssh, devicetree_path, f"{remote_dir}/{devicetree_name}"
        )
        ssh.run_check(_remote_python(_START_SCRIPT, remote_dir))
        yield RemoteHTTPServer(
            host=host,
            url_host=url_host,
            remote_dir=remote_dir,
            kernel_name=kernel_name,
            devicetree_name=devicetree_name,
        )
    finally:
        try:
            if not ssh.isconnected():
                ssh = _fresh_ssh(host)
            ssh.run_check(_remote_python(_CLEANUP_SCRIPT, remote_dir))
        except Exception:
            pass


def boot_linux_from_uboot(console, server):
    run_uboot_command(console, "dhcp", timeout=120)
    run_uboot_command(
        console,
        f"wget ${{kernel_addr_r}} {server.url_host}:/{server.kernel_name}",
        timeout=180,
    )
    run_uboot_command(
        console,
        f"wget ${{fdt_addr_r}} {server.url_host}:/{server.devicetree_name}",
        timeout=180,
    )
    console.sendline("booti ${kernel_addr_r} - ${fdt_addr_r}")
