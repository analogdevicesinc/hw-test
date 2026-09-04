import logging
import shlex
from argparse import Namespace
from contextlib import contextmanager
from os import environ
from pathlib import PurePosixPath
from time import monotonic, sleep
from urllib.parse import urlsplit

import pytest
from labgrid.exceptions import NoResourceFoundError
from labgrid.remote.client import start_session
from labgrid.util.ssh import sshmanager

from hw_tests.github import GitHub
from hw_tests.opkssh import OPKSSH
from hw_tests.ssh_config import SSHConfig

logger = logging.getLogger(__name__)


class LabgridClient:
    def __init__(self, context):
        self.context = context
        self._configure_identity()
        self.coordinator = self._resolve_coordinator()
        self.place = self._resolve_place()

        self.hosts = set()
        self.ssh_config = SSHConfig()
        self._opkssh = None

        logger.info("Labgrid place: %s", self.place)

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

    def _resolve_place(self):
        needs = self.context.get("needs")
        assert needs, "missing needs in test config"
        requested = self.context.get("labgrid_target")

        # Wait for a place that matches the needs and is not acquired by another user for 1 hour
        deadline = monotonic() + 60 * 60
        while True:
            session = start_session(self.coordinator)
            try:
                owner = f"{session.gethostname()}/{session.getuser()}"
                matches = []
                candidates = []
                for place in session.places.values():
                    if requested and place.name != requested:
                        continue
                    if requested:
                        logger.debug("Explicit labgrid target found: %s", requested)
                    tags = set(place.tags)
                    tags.update(str(value) for value in place.tags.values())
                    if not (
                        all(need in tags for need in needs)
                        and place.get_config()
                    ):
                        continue

                    matches.append(place)
                    if place.acquired in (None, owner) or self._is_previous_workflow_owner(
                        place.acquired
                    ):
                        candidates.append(place)

                if not matches:
                    logger.warning("No board matches needs %s; skipping", needs)
                    pytest.skip(f"no board matches needs: {needs}")
                if candidates:
                    return min(candidates, key=lambda place: place.name).name

                if monotonic() >= deadline:
                    acquired_by = ", ".join(
                        f"{place.name} by {place.acquired}" for place in matches
                    )
                    raise AssertionError(
                        f"no available place found for needs after "
                        f"1 hour: {needs} ({acquired_by})"
                    )

                logger.info(
                    "Waiting for labgrid place with needs %s; all matches are acquired",
                    needs,
                )
            finally:
                try:
                    session.loop.run_until_complete(session.stop())
                finally:
                    session.loop.run_until_complete(session.close())
            # Check for available place every 30 seconds
            sleep(30)

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
        """Acquire the selected labgrid place and yield its target."""
        session = start_session(
            self.coordinator,
            extra={
                "args": Namespace(
                    allow_unmatched=False,
                    initial_state=None,
                    kick=True,
                    place=self.place,
                    state=None,
                ),
                "env": None,
                "role": None,
            },
        )
        acquired = False
        target = None

        try:
            place = session.get_place(self.place)
            owner = f"{session.gethostname()}/{session.getuser()}"
            if place.acquired == owner:
                session.check_matches(place)
            else:
                if self._is_previous_workflow_owner(place.acquired):
                    session.loop.run_until_complete(session.release())
                session.loop.run_until_complete(session.acquire())
                acquired = True

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
                        session.loop.run_until_complete(session.release())
                finally:
                    try:
                        session.loop.run_until_complete(session.stop())
                    finally:
                        session.loop.run_until_complete(session.close())
                        sshmanager.close_all()


@contextmanager
def exporter_http_server(ssh, files):
    """Serve files temporarily from a remote host over HTTP.

    ``files`` maps paths relative to the HTTP root to local files.
    """
    directory = ssh.run_check("mktemp -d /dev/shm/hw-test-http.XXXXXX")[0].strip()
    assert directory.startswith("/dev/shm/hw-test-http."), f"unexpected dir: {directory}"

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
        yield port
    finally:
        ssh.run(f"kill $(cat {pid_file}) 2>/dev/null; rm -rf {directory_q}")
