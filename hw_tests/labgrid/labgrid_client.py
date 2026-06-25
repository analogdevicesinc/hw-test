import logging
import re
import subprocess
from os import environ
from contextlib import contextmanager

from hw_tests.ssh_config import SSHConfig
from hw_tests.github import GitHub
from hw_tests.opkssh import OPKSSH

logger = logging.getLogger(__name__)

_EXPORTER_RE = re.compile(
    r"^(?:Matching|Acquired) resource '.*' \(([^/]+)/",
)
_HOST_RE = re.compile(r"'host':\s*'([^']+)'")


class LabgridClient:
    coordinator: str | None = None
    place: str | None = None
    config: str | None = None
    timeout: int = 30

    def __init__(self, context, require_place=False):
        self.coordinator = context.get('labgrid_coordinator', None)
        if self.coordinator is None:
            self.coordinator = environ.get('LG_COORDINATOR', None)

        self.place = context.get('labgrid_place', None)
        if self.place is None:
            self.place = environ.get('LG_PLACE', None)

        if require_place is True:
            assert self.coordinator, "Neither 'labgrid_coordinator' in context or LG_COORDINATOR in environment"
            assert self.place, "Neither 'labgrid_place' in context or in LG_PLACE environment"

        self.config = f"envs/{self.place}.yaml"

        self.hosts = set()
        self.ssh_config = SSHConfig()
        if self.place:
            self._resolve_place_hosts()

        self._opkssh = OPKSSH(self)

    def command(self, *args, place=None):
        command = ["labgrid-client"]
        if self.coordinator:
            command.extend(["-x", self.coordinator])
        if self.config:
            command.extend(["-c", self.config])
        effective = place or self.place
        if effective:
            command.extend(["-p", effective])
        command.extend(args)
        return command

    def run(self, *args, place=None, check=True, timeout=None):
        return subprocess.run(
            self.command(*args, place=place),
            check=check,
            capture_output=True,
            text=True,
            timeout=self.timeout if timeout is None else timeout,
        )

    def _resolve_place_hosts(self):
        """Query the coordinator for the place's exporter host and configure SSH."""
        result = self.run("show", check=False)
        if result.returncode != 0:
            logger.warning(
                "failed to query place %s: %s",
                self.place, result.stderr.strip(),
            )
            return

        for line in result.stdout.splitlines():
            match = _HOST_RE.search(line)
            if match:
                host = match.group(1)
                GitHub.mask(host)
                if "://" not in host:
                    self.hosts.add(host)

        for host in self.hosts:
            self.ssh_config.configure_host(host)


def split_places(value):
    return (value or "").replace(",", " ").split()


def list_places(client):
    result = client.run("places")
    return [line for line in result.stdout.splitlines() if line.strip()]


def acquire_place(client, place):
    result = client.run("acquire", place=place, check=False)
    if result.returncode == 0:
        return True

    if "already acquired place" in result.stderr:
        logger.warning(result.stderr)
        return False

    result.check_returncode()


def release_place(client, place):
    logger.info("Releasing place: %s", place)
    return client.run("release", place=place, check=False)


@contextmanager
def acquired_places(client, places, acquire=True):
    acquired = set()
    try:
        if acquire:
            for place in places:
                acquire_place(client, place)
                acquired.add(place)
        yield
    finally:
        for place in acquired:
            release_place(client, place)
