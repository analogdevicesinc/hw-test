import shutil
import subprocess
import hashlib
import logging
import urllib.request
import re

from os import environ
from pathlib import Path

logger = logging.getLogger(__name__)

script_url = "https://raw.githubusercontent.com/openpubkey/opkssh/v0.14.0/scripts/install-linux.sh"
script_sha = "493cc42f55b2da31491c3947fd75dc2589d691d1a79fa284fc8e9fef3815ca54"

class OPKSSH():
    _strict = None
    _authorized = False

    def __init__(self, host='localhost'):
        self.host = host

        OPKSSH.ensure()
        self.authenticate()

    def authenticate(self):
        if environ.get('GITHUB_ACTIONS') == 'true':
            if not environ.get('ACTIONS_ID_TOKEN_REQUEST_URL'):
                raise RuntimeError(
                    "opkssh login github requires 'id-token: write' permission in the workflow job"
                )
            # hide: 2026/06/05 19:05:32 created client config file at /home/runner/.opk/config.yml
            subprocess.run(["opkssh", "login", "--create-config"],
                           stdout=subprocess.DEVNULL,
                           check=True)
            # hide: repo:owner/repo:ref:refs/heads/main https://token.actions.githubusercontent.com <id_token>
            result = subprocess.run(["opkssh", "login", "github"],
                                    capture_output=True,
                                    text=True,
                                    check=True)
            output_string = result.stdout.strip()
            if output_string:
                token = output_string.split()[-1]
                print(f"::add-mask::{token}", flush=True)

            self.strict_host_key(self.host, 'accept-new')
            self._authorized = result.returncode == 0
            return

        logger.info("No environment matched, assuming already authorized.")
        self._authorized = True
        return

    def strict_host_key(self, host, value):
        """
        Don't prompt to accept keys with 'False'.
        """
        path = Path.home() / ".ssh" / "config"
        path.parent.mkdir(parents=True, exist_ok=True)
        config = path.read_text() if path.exists() else ""

        if f"Host {host}" not in config:
            config += f"\nHost {host}\n  StrictHostKeyChecking {value}\n"
        elif re.search(rf'Host {host}\s+StrictHostKeyChecking', config):
            config = re.sub(rf'(Host {host}\s+StrictHostKeyChecking)\s+\w+', rf'\1 {value}', config)
        else:
            config = config.replace(f"Host {host}", f"Host {host}\n  StrictHostKeyChecking {value}")

        path.write_text(config.lstrip())
        self._strict = value

    @staticmethod
    def ensure():
        if shutil.which("opkssh"):
            return

        logger.info("Package 'opkssh' not installed.")
        if not shutil.which("sudo"):
            raise ValueError("Package 'sudo' is required.") # Also needed by install-linux.sh

        pkg = next((p for p in ["zypper", "dnf", "apt-get", "yum"] if shutil.which(p)), None)

        if not pkg:
            raise ValueError("No package manager mached.") # Also needed by install-linux.sh

        logger.info(f"Trying to install from package manager '{pkg}'...")
        result = subprocess.run(["sudo", pkg, "install", "-y", "opkssh"])
        if result.returncode == 0 and shutil.which("opkssh"):
            return

        logger.info("Trying to install from 'opkssh/install-linux.sh'...")
        with urllib.request.urlopen(script_url) as response:
            script = response.read()

        sha = hashlib.sha256(script).hexdigest()
        if sha != script_sha:
            raise ValueError(f"Expected '{script_sha}', got '{sha}'")

        result = subprocess.run(['sudo', 'bash'], input=script, check=True)
        if result.returncode == 0 and shutil.which("opkssh"):
            return

        raise ValueError("Could not ensure 'opkssh' is installed")
