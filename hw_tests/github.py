"""
GitHub wrapper lib

Basic usage:

.. code: python3

   import logging
   logging.basicConfig(level=logging.INFO)

   from hw_tests.github import GitHub

   # Gets defaults from context
   gh = GitHub(context)

   # Get artifact 'example'
   # from run_id '1234' (overwrites from context)
   # and from repository from context
   path = gh.download(
       artifact='example',
       run_id='1234',
   )
"""

import logging
import tempfile
import requests
from os import environ
from pathlib import Path
from urllib.parse import quote
from zipfile import ZipFile


logger = logging.getLogger(__name__)

_ZIP_MAGIC = b"PK\x03\x04"


def _extract_if_archive(archive: Path) -> None:
    with open(archive, "rb") as f:
        header = f.read(4)
    if header != _ZIP_MAGIC:
        return
    logger.debug("Extracting zip %s", archive)
    with ZipFile(archive) as zf:
        zf.extractall(archive.parent)
    archive.unlink()


class GitHub:
    _token = None
    _owner_repository = None
    _run_id = None

    def __init__(self, context):

        self._token = environ.get("GITHUB_TOKEN", None)
        self._owner_repository, self._run_id = self._split_context(context)

    @staticmethod
    def in_actions():
        return environ.get("GITHUB_ACTIONS") == "true"

    @staticmethod
    def _split_context(context):
        """Get common variables from the context/enviroment."""
        if isinstance(context, dict) and 'workflow_run_url' in context:
            # Test was triggered from a WebHook, workflow_run_url
            #   https://api.github.com/repos/<owner>/<repository>/actions/runs/<run_id>
            # is in the context
            url = context['workflow_run_url']
            parts = url.rstrip('/').split('/')

            return (f"{parts[4]}/{parts[5]}", parts[-1])

        elif environ.get("GITHUB_ACTIONS") == "true":
            # Test running as a shared job at top-level.yml
            return (environ.get("GITHUB_REPOSITORY", None), environ.get("GITHUB_RUN_ID", None))

        return (None, None)

    @staticmethod
    def mask(value):
        if environ.get("GITHUB_ACTIONS") == "true":
            print(f"::add-mask::{value}", flush=True)

    @staticmethod
    def get_id_token():
        logger.debug("Requesting GitHub OIDC token...")

        owner = environ.get("GITHUB_REPOSITORY_OWNER")
        audience = f"https://github.com/{owner}"

        base_url = environ["ACTIONS_ID_TOKEN_REQUEST_URL"]
        auth_token = environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]
        url = f"{base_url}&audience={quote(audience, safe='')}"
        headers = {
            "Authorization": f"Bearer {auth_token}",
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        id_token = response.json()["value"]
        GitHub.mask(id_token)

        return id_token

    def _headers(self):
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def download(
        self,
        name: str,
        owner_repository: str | None = None,
        run_id: str | None = None,
        path: Path | str | None = None
    ) -> Path:
        """Download artifact a single artifact from GitHub.
        Behaves like actions/download-artifact"""
        if owner_repository is None:
            owner_repository = self._owner_repository
        if run_id is None:
            run_id = self._run_id

        response = requests.get(
            f"https://api.github.com/repos/{owner_repository}/actions/runs/{run_id}/artifacts",
            headers=self._headers(),
            params={"name": name, "per_page": 100}
        )
        response.raise_for_status()

        artifact = next(
            (
                item for item in response.json().get("artifacts", [])
                if item.get("name") == name and not item.get("expired")
            ),
            None,
        )
        if artifact is None:
            raise LookupError(
                f"GitHub artifact {owner_repository}/{run_id}/{name!r} not found"
            )

        dest_dir = (
            Path(path)
            if path is not None
            else Path(tempfile.mkdtemp(prefix="hw-test-gh-"))
        )
        dest_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Downloading GitHub artifact {name}")
        response = requests.get(
            artifact["archive_download_url"],
            headers=self._headers(),
            stream=True
        )
        response.raise_for_status()

        dest_file = dest_dir / name
        with open(dest_file, "wb") as f:
            for chunk in response.iter_content(chunk_size=1 << 20):
                f.write(chunk)

        _extract_if_archive(dest_file)

        return dest_dir
