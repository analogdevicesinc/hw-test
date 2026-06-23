import platform
import subprocess
import logging
import urllib.request
from shutil import which
from os import environ
from pathlib import Path

from hw_tests.github import GitHub

logger = logging.getLogger(__name__)

OPKSSH_VERSION = "v0.14.0"
OPKSSH_BASE_URL = f"https://github.com/openpubkey/opkssh/releases/download/{OPKSSH_VERSION}"
OPKSSH_BIN = Path.home() / ".local" / "bin" / "opkssh"

class OPKSSH():
    _strict = None
    _authorized = False

    def __init__(self):
        OPKSSH.ensure()
        self.authenticate()

    def authenticate(self):
        if not GitHub.in_actions():
            logger.info("No environment matched, assuming already authorized.")
            self._authorized = True
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

        self._authorized = True

    @staticmethod
    def ensure():
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
