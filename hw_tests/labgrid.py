from contextlib import contextmanager
from argparse import Namespace
from os import environ
from pathlib import Path
import logging
import shlex

from labgrid import Environment
from labgrid.remote.client import start_session
from labgrid.util.ssh import sshmanager

from hw_tests.github import GitHub
from hw_tests.opkssh import OPKSSH
from hw_tests.ssh_config import SSHConfig

logger = logging.getLogger(__name__)


class LabgridClient:
    def __init__(self, context):
        self.context = context
        self.coordinator = self._resolve_coordinator()
        self.place = self._resolve_place()
        self.config = Path("envs") / f"{self.place}.yaml"
        assert self.config.is_file(), f"missing labgrid config: {self.config}"

        self.hosts = set()
        self.ssh_config = SSHConfig()
        self._opkssh = None

        logger.info("Labgrid place: %s", self.place)

    def _resolve_coordinator(self):
        coordinator = self.context.get("labgrid_coordinator") or environ.get(
            "LG_COORDINATOR"
        )
        assert coordinator, (
            "missing labgrid_coordinator in context or LG_COORDINATOR in environment"
        )
        return coordinator

    def _resolve_place(self):
        needs = self.context.get("needs")
        assert needs, "missing needs in test config"

        session = start_session(self.coordinator)
        try:
            owner = f"{session.gethostname()}/{session.getuser()}"
            candidates = []
            for place in session.places.values():
                tags = set(place.tags)
                tags.update(str(value) for value in place.tags.values())
                if (
                    all(need in tags for need in needs)
                    and place.acquired in (None, owner)
                    and (Path("envs") / f"{place.name}.yaml").is_file()
                ):
                    candidates.append(place)

            assert candidates, f"no available place found for needs: {needs}"
            return sorted(candidates, key=lambda place: place.name)[0].name
        finally:
            try:
                session.loop.run_until_complete(session.stop())
            finally:
                session.loop.run_until_complete(session.close())

    def _configure_ssh(self, session, place):
        resources = session.get_target_resources(place)
        for resource in resources.values():
            host = resource.params.get("host")
            if host is None:
                continue

            host = str(host).split("%", maxsplit=1)[0]
            if "://" not in host:
                self.hosts.add(host)

        for host in self.hosts:
            GitHub.mask(host)
            self.ssh_config.configure_host(host)

        self._opkssh = OPKSSH(self)

    @contextmanager
    def acquire(self):
        """Acquire the selected labgrid place and yield its target."""
        env = Environment(str(self.config))
        env.config.set_option("coordinator_address", self.coordinator)

        session = start_session(
            self.coordinator,
            extra={
                "args": Namespace(
                    allow_unmatched=False,
                    initial_state=None,
                    kick=False,
                    place=self.place,
                    state=None,
                ),
                "env": env,
                "role": self.place,
            },
        )
        acquired = False

        try:
            place = session.get_place(self.place)
            owner = f"{session.gethostname()}/{session.getuser()}"
            if place.acquired == owner:
                session.check_matches(place)
            else:
                session.loop.run_until_complete(session.acquire())
                acquired = True

            place = session.get_acquired_place(self.place)
            self._configure_ssh(session, place)

            target = session._get_target(place)
            yield target
        finally:
            try:
                env.cleanup()
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
def exporter_http_server(ssh, *files):
    """Serve files temporarily from a remote host over HTTP."""
    directory = ssh.run_check("mktemp -d /tmp/hw-test-http.XXXXXX")[0].strip()
    assert directory.startswith("/tmp/hw-test-http."), f"unexpected dir: {directory}"

    directory_q = shlex.quote(directory)
    pid_file = shlex.quote(f"{directory}/http.pid")
    log_file = shlex.quote(f"{directory}/http.log")

    try:
        for path in files:
            ssh.put(str(path), f"{directory}/{path.name}")

        ssh.run_check(
            "nohup python3 -m http.server --bind 0.0.0.0 "
            f"--directory {directory_q} >{log_file} 2>&1 </dev/null & "
            f"echo $! > {pid_file} && sleep 1 && kill -0 $(cat {pid_file})"
        )
        yield
    finally:
        ssh.run(f"kill $(cat {pid_file}) 2>/dev/null; rm -rf {directory_q}")
