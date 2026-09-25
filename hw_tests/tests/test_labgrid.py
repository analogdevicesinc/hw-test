from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest
from labgrid.exceptions import NoResourceFoundError

from hw_tests.labgrid import (
    LabgridClient,
    exporter_http_server,
)


class FakeSSH:
    def __init__(self):
        self.commands = []
        self.uploads = []

    def run_check(self, command):
        self.commands.append(command)
        if command.startswith("mktemp -d"):
            return ["/var/tmp/hw-test-http.test\n"]
        if "sock.getsockname" in command:
            return ["12345\n"]
        return [""]

    def put(self, source, destination):
        self.uploads.append((source, destination))

    def run(self, command):
        self.commands.append(command)


def test_exporter_http_server_uploads_files_at_requested_paths(tmp_path):
    kernel = tmp_path / "Image"
    emmc = tmp_path / "emmc.img.gz"
    ssh = FakeSSH()

    with exporter_http_server(
        ssh,
        {kernel.name: kernel, "debug/emmc.img.gz": emmc},
    ) as (directory, port):
        assert directory == "/var/tmp/hw-test-http.test"
        assert port == "12345"

    assert ssh.uploads == [
        (str(kernel), "/var/tmp/hw-test-http.test/Image"),
        (str(emmc), "/var/tmp/hw-test-http.test/debug/emmc.img.gz"),
    ]
    assert "mkdir -p /var/tmp/hw-test-http.test/debug" in ssh.commands
    assert not any("ln -s" in command for command in ssh.commands)


@pytest.mark.parametrize("remote_path", ["", "/outside", "../outside", "a/../../outside"])
def test_exporter_http_server_rejects_paths_outside_root(tmp_path, remote_path):
    ssh = FakeSSH()

    with pytest.raises(
        ValueError, match="below the server root"
    ), exporter_http_server(ssh, {remote_path: Path("emmc.img.gz")}):
        pass


def test_exporter_http_server_rejects_duplicate_normalized_paths(tmp_path):
    ssh = FakeSSH()
    image = tmp_path / "emmc.img.gz"

    with pytest.raises(
        ValueError, match="duplicate HTTP path"
    ), exporter_http_server(
        ssh,
        {"debug/emmc.img.gz": image, "debug/./emmc.img.gz": image},
    ):
        pass


def test_concurrent_uboot_loads_use_isolated_http_roots(tmp_path):
    class SharedSSH:
        def __init__(self):
            self.lock = Lock()
            self.next_workspace = 0
            self.remote_files = {}

        def run_check(self, command):
            if command == "mktemp -d /var/tmp/hw-test-http.XXXXXX":
                with self.lock:
                    workspace = self.next_workspace
                    self.next_workspace += 1
                return [f"/var/tmp/hw-test-http.{workspace}\n"]
            if "sock.getsockname" in command:
                return ["12345\n"]
            assert command.startswith(
                (
                    "nohup python3 -m http.server",
                    "chmod 0755 /var/tmp/hw-test-http.",
                )
            )
            return [""]

        def put(self, source, destination):
            with self.lock:
                self.remote_files[destination] = Path(source).read_bytes()

        def run(self, command):
            assert "rm -rf /var/tmp/hw-test-http." in command

    class FakeTarget:
        def activate(self, driver):
            driver.active = True

        def deactivate(self, driver):
            driver.active = False

    class FakeOpenOCD:
        def __init__(self, ssh, barrier, expected):
            self.ssh = ssh
            self.barrier = barrier
            self.expected = expected
            self.active = False
            self.load_commands = [
                "source [find /tools/u-boot.tcl]",
                "autoboot_elf",
            ]

        def execute(self, commands):
            assert self.active
            assert commands[0].startswith("cd /var/tmp/hw-test-http.")
            directory = commands[0].removeprefix("cd ")
            assert commands[1:] == self.load_commands

            self.barrier.wait()
            assert self.ssh.remote_files[f"{directory}/u-boot-spl"] == (
                self.expected + b"-spl"
            )
            assert self.ssh.remote_files[f"{directory}/u-boot"] == (
                self.expected + b"-uboot"
            )

    ssh = SharedSSH()
    target = FakeTarget()
    barrier = Barrier(4)

    def load_board(index):
        identity = f"board-{index}".encode()
        spl = tmp_path / f"spl-{index}"
        uboot = tmp_path / f"uboot-{index}"
        spl.write_bytes(identity + b"-spl")
        uboot.write_bytes(identity + b"-uboot")
        openocd = FakeOpenOCD(ssh, barrier, identity)

        files = {"u-boot-spl": spl, "u-boot": uboot}
        with exporter_http_server(ssh, files) as (directory, _):
            target.activate(openocd)
            try:
                openocd.execute([f"cd {directory}", *openocd.load_commands])
            finally:
                target.deactivate(openocd)
        assert not openocd.active

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(load_board, index) for index in range(4)]
        for future in futures:
            future.result()

    assert ssh.next_workspace == 4


def test_labgrid_client_selects_configured_place_without_local_env_file(
    monkeypatch, tmp_path
):
    """Select a tagged place only when its coordinator config is available."""

    class FakeLoop:
        def run_until_complete(self, result):
            return result

    unconfigured_place = SimpleNamespace(
        name="MUN-00-SC598_EZKIT-01",
        tags={"board": "sc598", "kind": "ezkit"},
        acquired=None,
        get_config=dict,
    )
    place = SimpleNamespace(
        name="MUN-01-SC598_EZKIT-02",
        tags={"board": "sc598", "kind": "ezkit"},
        acquired=None,
        get_config=lambda: {"drivers": [{"SSHDriver": {"name": "ssh"}}]},
    )
    session = SimpleNamespace(
        places={unconfigured_place.name: unconfigured_place, place.name: place},
        loop=FakeLoop(),
        gethostname=lambda: "test-host",
        getuser=lambda: "test-user",
        stop=lambda: None,
        close=lambda: None,
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LG_COORDINATOR", "coordinator.example:20408")
    monkeypatch.setattr("hw_tests.labgrid.start_session", lambda coordinator: session)

    client = LabgridClient({"needs": ["sc598", "ezkit"]})

    assert client.place == place.name


def test_labgrid_client_rejects_ambiguous_networkservice(monkeypatch):
    """Do not silently ignore multiple NetworkService resources."""

    client = object.__new__(LabgridClient)
    client.hosts = set()
    client.ssh_config = SimpleNamespace(configure_host=lambda host: None)

    target = SimpleNamespace(
        get_resource=lambda resource, wait_avail: (_ for _ in ()).throw(
            NoResourceFoundError(
                "multiple NetworkService resources", found=["ssh", "dut"]
            )
        )
    )
    session = SimpleNamespace(get_target_resources=lambda place: {})
    place = SimpleNamespace(name="board")

    with pytest.raises(RuntimeError, match="multiple NetworkService"):
        client._configure_ssh(session, place, target)


def test_labgrid_client_cleans_up_target_before_release(monkeypatch):
    """Clean up Labgrid drivers before releasing the coordinator place."""

    events = []
    place = SimpleNamespace(name="board", acquired=None)
    target = SimpleNamespace(cleanup=lambda: events.append("cleanup"))

    class FakeLoop:
        def run_until_complete(self, result):
            return result

    session = SimpleNamespace(
        get_place=lambda name: place,
        gethostname=lambda: "test-host",
        getuser=lambda: "test-user",
        acquire=lambda: events.append("acquire"),
        get_acquired_place=lambda name: place,
        _get_target=lambda selected_place: target,
        release=lambda: events.append("release"),
        stop=lambda: events.append("stop"),
        close=lambda: events.append("close"),
        loop=FakeLoop(),
    )

    client = object.__new__(LabgridClient)
    client.coordinator = "coordinator.example:20408"
    client.place = place.name
    client._workflow_owner = None
    monkeypatch.setattr("hw_tests.labgrid.start_session", lambda *args, **kwargs: session)
    monkeypatch.setattr(client, "_configure_ssh", lambda *args: None)

    with pytest.raises(RuntimeError, match="test failure"), client.acquire():
        raise RuntimeError("test failure")

    assert events == ["acquire", "cleanup", "release", "stop", "close"]
