"""SSH authentication with `opkssh <https://github.com/openpubkey/opkssh>`_."""

import logging
import platform
import subprocess
import urllib.request
from os import environ
from pathlib import Path
from shutil import which

from hw_tests.github import GitHub

logger = logging.getLogger(__name__)

OPKSSH_VERSION = "v0.16.0"
OPKSSH_BASE_URL = f"https://github.com/openpubkey/opkssh/releases/download/{OPKSSH_VERSION}"
OPKSSH_BIN = Path.home() / ".local" / "bin" / "opkssh"

class OPKSSH:
    """Set up SSH access to the hosts of a labgrid client.

    Installs opkssh if missing and runs :meth:`authenticate`.

    :param client: :class:`~hw_tests.labgrid.LabgridClient` whose hosts to
        check. If ``None``, the SSH check is skipped.
    """

    def __init__(self, client=None):
        OPKSSH.ensure()
        self.authenticate(client)

    def authenticate(self, client=None):
        """Get an SSH certificate and check access to the client hosts.

        In GitHub Actions, runs ``opkssh login github``, which writes
        ``~/.ssh/id_ecdsa`` and its certificate. The job needs the
        ``id-token: write`` permission. Elsewhere, the user's SSH keys are
        used.
        """
        if not GitHub.in_actions():
            self.check_ssh_auth(client)
            return

        if not environ.get('ACTIONS_ID_TOKEN_REQUEST_URL'):
            raise RuntimeError(
                "opkssh login github requires 'id-token: write' permission in the workflow job"
            )

        # create id_ecdsa
        result = subprocess.run(
            ["opkssh", "login", "github"],
            capture_output=True,
            text=True,
            check=True,
        )
        output_string = result.stdout.strip()
        if output_string:
            token = output_string.split()[-1]
            GitHub.mask(token)

        self.check_ssh_auth(client)

    def check_ssh_auth(self, client):
        """Check SSH login to each host of ``client``.

        New host keys are added to ``known_hosts``
        (``StrictHostKeyChecking=accept-new``).

        :raises PermissionError: login to a host failed.
        """
        if client is None:
            return

        logger.debug(f"Test ssh config target '{client}'.")
        for host in client.hosts:
            result = subprocess.run(
                ["ssh",
                 "-F", str(client.ssh_config.path),
                 "-o", "BatchMode=yes",
                 "-o", "ConnectTimeout=10",
                 "-o", "StrictHostKeyChecking=accept-new",
                host, "true"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise PermissionError(
                    f"SSH auth to {host} failed: {result.stderr.strip()}\n"
                    f"Check that your key is accepted by the exporter host."
                )
            logger.debug("SSH auth to %s: OK", host)

    @staticmethod
    def ensure():
        """Download opkssh to ``~/.local/bin`` if it is not in ``PATH``."""
        if which('opkssh') is not None:
            return

        arch = platform.machine()
        if arch == "x86_64":
            arch = "amd64"
        elif arch == "aarch64":
            arch = "arm64"

        url = f"{OPKSSH_BASE_URL}/opkssh-linux-{arch}"
        OPKSSH_BIN.parent.mkdir(parents=True, exist_ok=True)

        logger.info("Downloading opkssh from %s", url)
        urllib.request.urlretrieve(url, OPKSSH_BIN)
        OPKSSH_BIN.chmod(0o755)
