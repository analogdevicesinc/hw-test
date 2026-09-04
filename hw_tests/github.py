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
import tarfile
import tempfile
from os import environ
from pathlib import Path
from urllib.parse import quote
from zipfile import ZipFile

import requests

from hw_tests.logging import gha_escape, register_sensitive

logger = logging.getLogger(__name__)

_ZIP_MAGIC = b"PK\x03\x04"


def _extract_if_archive(archive: Path) -> None:
    with open(archive, "rb") as f:
        header = f.read(4)
    if header == _ZIP_MAGIC:
        logger.debug("Extracting zip %s", archive)
        with ZipFile(archive) as zf:
            zf.extractall(archive.parent)
        archive.unlink()
        return
    if tarfile.is_tarfile(archive):
        logger.debug("Extracting tar %s", archive)
        with tarfile.open(archive) as tf:
            tf.extractall(archive.parent, filter="data")
        archive.unlink()
        return


def _download_to(url, name, headers, path=None, prefix="hw-test-") -> Path:
    """Stream ``url`` to ``<dir>/name``, extract if it is an archive, return the dir."""
    dest_dir = (
        Path(path) if path is not None else Path(tempfile.mkdtemp(prefix=prefix))
    )
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / name

    response = requests.get(url, headers=headers, stream=True)
    response.raise_for_status()
    with open(dest_file, "wb") as f:
        f.writelines(response.iter_content(chunk_size=1 << 20))

    _extract_if_archive(dest_file)
    return dest_dir


class GitHub:
    _token = None
    _owner_repository = None
    _test_name = None
    _run_id = None
    __down_counter = 0

    def __init__(self, context):

        self._token = environ.get("GITHUB_TOKEN")
        self._get_workflow_run_vars(context)
        self._test_name = context.get("name") # for fallback

        if self._token is None:
            logger.info("No 'GITHUB_TOKEN' set, only auth-less API calls will work")

    @staticmethod
    def in_actions():
        return environ.get("GITHUB_ACTIONS") == "true"

    def _get_workflow_run_vars(self, context):
        """Get common variables from the context/environment."""

        # Test running as a shared job at top-level.yml
        self._owner_repository = environ.get("GITHUB_REPOSITORY")
        self._run_id = environ.get("GITHUB_RUN_ID")

        if 'workflow_run_url' in context:
            # Test was triggered from a WebHook, workflow_run_url
            #   https://api.github.com/repos/<owner>/<repository>/actions/runs/<run_id>
            # is in the context
            url = context['workflow_run_url']
            parts = url.rstrip('/').split('/')

            self._owner_repository = f"{parts[4]}/{parts[5]}"
            self._run_id = parts[-1]
            return

    @staticmethod
    def mask(value):
        register_sensitive(value)
        if GitHub.in_actions():
            print(f"::add-mask::{gha_escape(str(value))}", flush=True)

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

    @property
    def owner_repository(self):
        return self._owner_repository

    def list_artifacts(self, owner_repository=None, run_id=None):
        """Return non-expired artifact dicts for a run, or [] when unavailable."""
        if owner_repository is None:
            owner_repository = self._owner_repository
        if run_id is None:
            run_id = self._run_id
        if owner_repository is None or run_id is None or self._token is None:
            return []

        all_artifacts = []
        page = 1
        total_count = None
        while total_count is None or len(all_artifacts) < total_count:
            response = requests.get(
                f"https://api.github.com/repos/{owner_repository}/actions/runs/{run_id}/artifacts",
                headers=self._headers(),
                params={"per_page": 100, "page": page},
            )
            response.raise_for_status()
            data = response.json()
            total_count = data.get("total_count", 0)
            artifacts = data.get("artifacts", [])
            if not artifacts:
                break
            all_artifacts.extend(artifacts)
            page += 1

        return [
            item
            for item in all_artifacts
            if not item.get("expired")
        ]

    def successful_run_ids(self, owner_repository=None, branch=None, limit=20):
        """Return ids of recent successful workflow runs, newest first.

        Used to resolve the latest green run of a source repository when a test
        pins a source by repository/branch rather than an exact run_id. Returns
        [] when unavailable (no token / no repository)."""
        if owner_repository is None:
            owner_repository = self._owner_repository
        if owner_repository is None or self._token is None:
            return []

        params = {"status": "success", "per_page": min(limit, 100), "page": 1}
        if branch:
            params["branch"] = branch
        response = requests.get(
            f"https://api.github.com/repos/{owner_repository}/actions/runs",
            headers=self._headers(),
            params=params,
        )
        response.raise_for_status()
        runs = response.json().get("workflow_runs", [])
        return [run["id"] for run in runs[:limit]]

    def download(
        self,
        name: str,
        owner_repository: str | None = None,
        run_id: str | None = None,
        path: Path | str | None = None
    ) -> Path:
        """Download artifact a single artifact from GitHub.
        Behaves like actions/download-artifact"""
        local_ = Path.cwd() / '_artifacts' / self._test_name / str(self.__down_counter) # fallback
        self.__down_counter += 1

        msg__ = f"cannot download artifacts; assuming you have them at '{local_}'"
        msg_ = "Neither 'workflow_run_url' in context or '{}' in environment, " + msg__

        if owner_repository is None:
            owner_repository = self._owner_repository
        if run_id is None:
            run_id = self._run_id
        if owner_repository is None:
            logger.warning(msg_.format('GITHUB_REPOSITORY'))
            return local_
        if run_id is None:
            logger.warning(msg_.format('GITHUB_RUN_ID'))
            return local_
        if self._token is None:
            # API always requires a token
            logger.warning(f"No 'GITHUB_TOKEN' in environment, {msg__}")
            return local_

        artifact = next(
            (
                item for item in self.list_artifacts(owner_repository, run_id)
                if item.get("name") == name
            ),
            None,
        )
        if artifact is None:
            raise LookupError(
                f"GitHub artifact '{name}' at '{owner_repository}/{run_id}' not found"
            )

        logger.info(f"Downloading GitHub artifact '{name}'")
        return _download_to(
            artifact["archive_download_url"], name, self._headers(), path, "hw-test-gh-"
        )

    def list_release_assets(self, tag: str, owner_repository: str | None = None) -> list[dict]:
        """Return the assets of a release addressed by tag.

        Unlike Actions-run artifacts, release assets do not expire, so this is
        the durable source for companion images (SPL/U-Boot/rootfs) that are not
        built by the run under test."""
        if owner_repository is None:
            owner_repository = self._owner_repository
        url = f"https://api.github.com/repos/{owner_repository}/releases/tags/{tag}"
        response = requests.get(url, headers=self._headers())
        response.raise_for_status()
        return response.json().get("assets", [])

    def download_release_asset(
        self,
        asset_name: str,
        tag: str,
        owner_repository: str | None = None,
        path: Path | str | None = None,
    ) -> Path:
        """Download and extract a single release asset by exact name."""
        if owner_repository is None:
            owner_repository = self._owner_repository
        assets = self.list_release_assets(tag, owner_repository)
        asset = next((a for a in assets if a.get("name") == asset_name), None)
        if asset is None:
            raise LookupError(
                f"release asset {asset_name!r} not found in {owner_repository}@{tag} "
                f"(assets: {[a.get('name') for a in assets]})"
            )

        logger.info(f"Downloading release asset '{asset_name}' from {owner_repository}@{tag}")
        headers = self._headers()
        headers["Accept"] = "application/octet-stream"
        return _download_to(asset["url"], asset_name, headers, path, "hw-test-rel-")
