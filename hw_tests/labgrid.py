"""
To ensure the tests scope is to test a feature, the ``LabgridClient`` class
handles reservation, acquisition, authentication and lifespan. It reserves a
place that matches the ``needs`` of the test, acquires it, configures SSH, and
releases.
"""


import logging
import shlex
from argparse import Namespace
from contextlib import contextmanager
from os import environ
from pathlib import PurePosixPath
from time import monotonic, sleep
from urllib.parse import urlsplit

from labgrid.exceptions import NoResourceFoundError
from labgrid.remote.client import start_session
from labgrid.remote.common import Reservation, ReservationState
from labgrid.remote.generated import labgrid_coordinator_pb2
from labgrid.util.ssh import sshmanager

from hw_tests.github import GitHub
from hw_tests.opkssh import OPKSSH
from hw_tests.ssh_config import SSHConfig

logger = logging.getLogger(__name__)


class LabgridClient:
    """Reserve a labgrid place for a test and acquire it.

    The coordinator is ``labgrid_coordinator`` from the context or
    ``LG_COORDINATOR``. :meth:`acquire` reserves a place with the ``needs``
    tags (``key=value``) on the coordinator, which allocates a free match or
    queues the request until one is released. ``labgrid_target`` limits the
    match to one place. Waits up to one hour.

    In GitHub Actions, the labgrid user is ``labgrid-client-<run id>-<attempt>``,
    so places left acquired by a previous attempt of the run are released first.

    :param context: Test context.
    """

    def __init__(self, context):
        self.context = context
        self._configure_identity()
        self.coordinator = self._resolve_coordinator()
        self.filters = self._resolve_filters()
        self.place = None
        self.reservation = None

        self.hosts = set()
        self.ssh_config = SSHConfig()
        self._opkssh = None

    def _configure_identity(self):
        self._workflow_owner = None
        if "LG_USERNAME" in environ or "GITHUB_RUN_ID" not in environ:
            return

        self._workflow_owner = (
            f"labgrid-client-{environ['GITHUB_RUN_ID']}-"
            f"{environ.get('GITHUB_RUN_ATTEMPT', '1')}"
        )
        environ["LG_USERNAME"] = self._workflow_owner

    def _is_previous_workflow_owner(self, acquired):
        if self._workflow_owner is None or not acquired:
            return False

        acquired_user = acquired.rsplit("/", maxsplit=1)[-1]
        prefix = self._workflow_owner.rsplit("-", maxsplit=1)[0]
        return acquired_user == prefix or (
            acquired_user.startswith(f"{prefix}-")
            and acquired_user != self._workflow_owner
        )

    def _resolve_coordinator(self):
        coordinator = self.context.get("labgrid_coordinator") or environ.get(
            "LG_COORDINATOR"
        )
        assert coordinator, (
            "missing labgrid_coordinator in context or LG_COORDINATOR in environment"
        )
        GitHub.mask(coordinator)
        coordinator_host = urlsplit(f"//{coordinator}").hostname
        if coordinator_host:
            GitHub.mask(coordinator_host)
        return coordinator

    def _resolve_filters(self):
        needs = self.context.get("needs")
        assert needs, "missing needs in test config"
        assert all("=" in need for need in needs), f"needs must be place tags as key=value: {needs}"
        filters = dict(need.split("=", 1) for need in needs)
        if self.context.get("labgrid_target"):
            filters["name"] = self.context["labgrid_target"]
        return filters

    def _matches(self, place):
        tags = {**place.tags, "name": place.name}
        return all(tags.get(key) == value for key, value in self.filters.items())

    def _reserve(self, session):
        """Reserve a place and return its name once allocated."""
        run = session.loop.run_until_complete
        request = labgrid_coordinator_pb2.CreateReservationRequest(
            filters={"main": labgrid_coordinator_pb2.Reservation.Filter(filter=self.filters)}
        )
        reservation = Reservation.from_pb2(run(session.stub.CreateReservation(request)).reservation)
        self.reservation = reservation.id
        logger.info("Labgrid reservation %s: %s", reservation.id, self.filters)

        if reservation.state is ReservationState.waiting:
            logger.info("Waiting for a free labgrid place")
        # Reservations expire 60 s after the last poll
        deadline = monotonic() + 60 * 60
        while reservation.state is ReservationState.waiting:
            assert monotonic() < deadline, f"no place allocated after 1 hour for {self.filters}"
            sleep(5)
            request = labgrid_coordinator_pb2.PollReservationRequest(token=reservation.id)
            reservation = Reservation.from_pb2(run(session.stub.PollReservation(request)).reservation)

        assert reservation.state is ReservationState.allocated, (
            f"reservation {reservation.id} is {reservation.state.name}"
        )
        return reservation.allocations["main"][0]

    def _configure_ssh(self, session, place, target):
        resources = session.get_target_resources(place)
        for resource in resources.values():
            host = resource.params.get("host")
            if host is None:
                continue

            host = str(host).split("%", maxsplit=1)[0]
            if "://" not in host:
                self.hosts.add(host)

        # NetworkService is normally supplied by the coordinator-side place
        # config. Include it explicitly because it may be the only resource
        # that carries the SSH address.
        try:
            networkservice = target.get_resource("NetworkService", wait_avail=False)
        except NoResourceFoundError as error:
            if error.found:
                raise RuntimeError(
                    f"multiple NetworkService resources found for place {place.name}; "
                    "the SSH driver must identify the resource to use"
                ) from error
            networkservice = None
        if networkservice is not None:
            address = str(networkservice.address)
            if "://" in address:
                raise ValueError(
                    f"NetworkService address must be an SSH host, not a URI: {address}"
                )
            self.hosts.add(address)

        for host in self.hosts:
            GitHub.mask(host)
            self.ssh_config.configure_host(host)

        self._opkssh = OPKSSH(self)

    @contextmanager
    def acquire(self):
        """Reserve and acquire a place and yield its labgrid target.

        Writes the SSH config for the hosts and checks SSH access. On exit,
        cleans up the target, releases the place and cancels the reservation.
        """
        session = start_session(
            self.coordinator,
            extra={
                "args": Namespace(
                    allow_unmatched=False,
                    initial_state=None,
                    kick=True,
                    place=None,
                    state=None,
                ),
                "env": None,
                "role": None,
            },
        )
        run = session.loop.run_until_complete
        acquired = False
        target = None

        try:
            matches = [place for place in session.places.values() if self._matches(place)]
            assert matches, f"no place found for {self.filters}"
            for place in matches:
                if self._is_previous_workflow_owner(place.acquired):
                    logger.info("Releasing place %s left by %s", place.name, place.acquired)
                    session.args.place = place.name
                    run(session.release())

            self.place = session.args.place = self._reserve(session)
            run(session.acquire())
            acquired = True
            logger.info("Labgrid place: %s", self.place)

            place = session.get_acquired_place(self.place)
            target = session._get_target(place)
            self._configure_ssh(session, place, target)
            yield target
        finally:
            try:
                if target is not None:
                    target.cleanup()
            finally:
                try:
                    if acquired:
                        run(session.release())
                finally:
                    try:
                        if self.reservation:
                            request = labgrid_coordinator_pb2.CancelReservationRequest(token=self.reservation)
                            run(session.stub.CancelReservation(request))
                    finally:
                        try:
                            run(session.stop())
                        finally:
                            run(session.close())
                            sshmanager.close_all()


@contextmanager
def exporter_http_server(ssh, files):
    """Serve files over HTTP from a remote host.

    Copies ``files`` to a temporary directory on the host, starts
    ``python3 -m http.server`` on a free port, and removes everything on exit.

    :param ssh: Labgrid ``SSHDriver`` of the host.
    :param files: Maps paths relative to the HTTP root to local files.
    :returns: Context manager yielding ``(directory, port)``, the remote
        directory and the HTTP port.
    """
    directory = ssh.run_check("mktemp -d /var/tmp/hw-test-http.XXXXXX")[0].strip()
    assert directory.startswith("/var/tmp/hw-test-http."), f"unexpected dir: {directory}"

    directory_q = shlex.quote(directory)
    pid_file = shlex.quote(f"{directory}/http.pid")
    log_file = shlex.quote(f"{directory}/http.log")

    try:
        remote_paths = set()
        for remote_path, source in files.items():
            remote_path = PurePosixPath(remote_path)
            if (
                remote_path.is_absolute()
                or not remote_path.parts
                or ".." in remote_path.parts
            ):
                raise ValueError(
                    f"HTTP path must be relative and stay below the server root: "
                    f"{remote_path}"
                )
            if remote_path in remote_paths:
                raise ValueError(f"duplicate HTTP path: {remote_path}")
            remote_paths.add(remote_path)

            remote_file = PurePosixPath(directory) / remote_path
            if remote_file.parent != PurePosixPath(directory):
                remote_parent = str(remote_file.parent)
                ssh.run_check(f"mkdir -p {shlex.quote(remote_parent)}")
            ssh.put(str(source), str(remote_file))

        port = ssh.run_check(
            "python3 -c "
            "'import socket; "
            "sock = socket.socket(); "
            "sock.bind((\"\", 0)); "
            "print(sock.getsockname()[1])'"
        )[0].strip()
        assert port.isdigit(), f"unexpected HTTP port: {port}"

        ssh.run_check(
            "nohup python3 -m http.server --bind 0.0.0.0 "
            f"--directory {directory_q} {port} >{log_file} 2>&1 </dev/null & "
            f"echo $! > {pid_file} && sleep 1 && kill -0 $(cat {pid_file}) || (cat {log_file}; exit 1)"
        )
        yield directory, port
    finally:
        ssh.run(f"kill $(cat {pid_file}) 2>/dev/null; rm -rf {directory_q}")
