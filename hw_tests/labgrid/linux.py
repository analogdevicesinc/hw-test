import shlex
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from labgrid.driver.exception import ExecutionError
from labgrid.util.ssh import sshmanager

from hw_tests.labgrid.hosts import parse_host_map
from hw_tests.labgrid.uboot import run_uboot_command


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


def boot_http_host_for(remote_host, ssh_hosts=None):
    host_map = parse_host_map(ssh_hosts)
    return host_map.get(remote_host, remote_host)


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
def remote_http_server(target, kernel_path, devicetree_path, ssh_hosts=None):
    openocd = target.get_driver("OpenOCDDriver", activate=False)
    host = openocd.interface.host
    ssh = sshmanager.open(host)
    url_host = boot_http_host_for(host, ssh_hosts=ssh_hosts)

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

    start_script = """
import os
import subprocess
import sys
import time

remote_dir = sys.argv[1]
log_path = os.path.join(remote_dir, "http.log")
pid_path = os.path.join(remote_dir, "http.pid")

log = open(log_path, "ab", buffering=0)
process = subprocess.Popen(
    ["python3", "-m", "http.server", "--bind", "0.0.0.0"],
    cwd=remote_dir,
    stdin=subprocess.DEVNULL,
    stdout=log,
    stderr=subprocess.STDOUT,
    start_new_session=True,
    close_fds=True,
)
log.close()

with open(pid_path, "w", encoding="ascii") as pid_file:
    pid_file.write(f"{process.pid}\\n")

time.sleep(1)
returncode = process.poll()
if returncode is not None:
    with open(log_path, encoding="utf-8", errors="replace") as log_file:
        sys.stderr.write(log_file.read())
    raise SystemExit(returncode or 1)
"""
    cleanup_script = """
import glob
import os
import shutil
import signal
import sys

remote_dir = sys.argv[1]
pid_path = os.path.join(remote_dir, "http.pid")

try:
    with open(pid_path, encoding="ascii") as pid_file:
        pid = int(pid_file.read().strip())
except (FileNotFoundError, ValueError):
    pid = None

if pid is not None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass

shutil.rmtree(remote_dir, ignore_errors=True)

# Cleanup all orphaned http directories
for old_dir in glob.glob("/tmp/hw-test-http.*"):
    try:
        shutil.rmtree(old_dir, ignore_errors=True)
    except Exception:
        pass
"""

    try:
        ssh = _put_file_checked(host, ssh, kernel_path, f"{remote_dir}/{kernel_name}")
        ssh = _put_file_checked(
            host, ssh, devicetree_path, f"{remote_dir}/{devicetree_name}"
        )
        ssh.run_check(_remote_python(start_script, remote_dir))
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
            ssh.run_check(_remote_python(cleanup_script, remote_dir))
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
