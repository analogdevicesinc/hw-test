from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest
from labgrid.exceptions import NoResourceFoundError
from labgrid.remote.common import ReservationState
from labgrid.remote.generated import labgrid_coordinator_pb2

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


PLACE = "MUN-01-SC598_EZKIT-02"
OWNER = "test-host/test-user"


def _place(name, acquired=None):
    return SimpleNamespace(name=name, tags={"board": "sc598", "kind": "ezkit"}, acquired=acquired)


class FakeStub:
    """Coordinator stub that allocates ``PLACE`` after ``polls`` polls."""

    def __init__(self, events, polls=0):
        self.events = events
        self.polls = polls
        self.filters = None

    def _reservation(self):
        res = labgrid_coordinator_pb2.Reservation(owner=OWNER, token="RES0000001")
        if self.polls > 0:
            res.state = ReservationState.waiting.value
        else:
            res.state = ReservationState.allocated.value
            res.allocations.update({"main": PLACE})
        return res

    def CreateReservation(self, request):
        self.filters = dict(request.filters["main"].filter)
        self.events.append("reserve")
        return labgrid_coordinator_pb2.CreateReservationResponse(reservation=self._reservation())

    def PollReservation(self, request):
        assert request.token == "RES0000001"
        self.polls -= 1
        self.events.append("poll")
        return labgrid_coordinator_pb2.PollReservationResponse(reservation=self._reservation())

    def CancelReservation(self, request):
        assert request.token == "RES0000001"
        self.events.append("cancel")
        return labgrid_coordinator_pb2.CancelReservationResponse()


def _client(monkeypatch, places, events, polls=0, context=None):
    """LabgridClient on a fake session; the session records events."""
    places = {place.name: place for place in places}
    args = SimpleNamespace(place=None, kick=True)
    target = SimpleNamespace(cleanup=lambda: events.append("cleanup"))
    session = SimpleNamespace(
        places=places,
        args=args,
        stub=FakeStub(events, polls),
        loop=SimpleNamespace(run_until_complete=lambda result: result),
        gethostname=lambda: "test-host",
        getuser=lambda: "test-user",
        acquire=lambda: events.append(f"acquire {args.place}"),
        release=lambda: events.append(f"release {args.place}"),
        get_acquired_place=lambda name: places[name],
        _get_target=lambda place: target,
        stop=lambda: events.append("stop"),
        close=lambda: events.append("close"),
    )
    monkeypatch.setenv("LG_COORDINATOR", "coordinator.example:20408")
    monkeypatch.setattr("hw_tests.labgrid.start_session", lambda *args, **kwargs: session)
    monkeypatch.setattr("hw_tests.labgrid.sleep", lambda seconds: None)
    client = LabgridClient(context or {"needs": ["board=sc598", "kind=ezkit"]})
    monkeypatch.setattr(client, "_configure_ssh", lambda *args: None)
    return client, session


def test_acquire_reserves_then_releases_in_order(monkeypatch):
    events = []
    client, session = _client(monkeypatch, [_place(PLACE, acquired="x/y")], events, polls=2)

    with client.acquire():
        assert client.place == PLACE

    assert session.stub.filters == {"board": "sc598", "kind": "ezkit"}
    assert events == [
        "reserve", "poll", "poll", f"acquire {PLACE}",
        "cleanup", f"release {PLACE}", "cancel", "stop", "close",
    ]


def test_acquire_cleans_up_on_failure(monkeypatch):
    events = []
    client, _ = _client(monkeypatch, [_place(PLACE)], events)

    with pytest.raises(RuntimeError, match="test failure"), client.acquire():
        raise RuntimeError("test failure")

    assert events == ["reserve", f"acquire {PLACE}", "cleanup", f"release {PLACE}", "cancel", "stop", "close"]


def test_acquire_filters_by_target(monkeypatch):
    client, session = _client(
        monkeypatch, [_place(PLACE)], [],
        context={"needs": ["board=sc598"], "labgrid_target": PLACE},
    )
    with client.acquire():
        pass
    assert session.stub.filters == {"board": "sc598", "name": PLACE}


def test_acquire_rejects_unmatched_needs(monkeypatch):
    events = []
    client, _ = _client(monkeypatch, [_place(PLACE)], events, context={"needs": ["board=sc589"]})
    with pytest.raises(AssertionError, match="no place found"), client.acquire():
        pass
    assert "reserve" not in events


def test_acquire_releases_place_of_previous_attempt(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    monkeypatch.delenv("LG_USERNAME", raising=False)
    events = []
    client, _ = _client(monkeypatch, [_place(PLACE, acquired="runner/labgrid-client-123-1")], events)
    with client.acquire():
        pass
    assert events[:3] == [f"release {PLACE}", "reserve", f"acquire {PLACE}"]


def test_acquire_gives_up_after_one_hour(monkeypatch):
    events = []
    client, _ = _client(monkeypatch, [_place(PLACE, acquired="x/y")], events, polls=10)
    clock = iter([0, 0, 10**9])
    monkeypatch.setattr("hw_tests.labgrid.monotonic", lambda: next(clock))

    with pytest.raises(AssertionError, match="no place allocated"), client.acquire():
        pass
    assert events == ["reserve", "poll", "cancel", "stop", "close"]


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
