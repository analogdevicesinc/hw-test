import logging
from os import environ
from pathlib import Path
from urllib.parse import quote
from zipfile import ZipFile

logger = logging.getLogger(__name__)


class GitHub:
    @staticmethod
    def in_actions():
        return environ.get("GITHUB_ACTIONS") == "true"

    @staticmethod
    def mask(value):
        if GitHub.in_actions() and value:
            print(f"::add-mask::{value}", flush=True)

    @staticmethod
    def require_id_token_permission():
        if not environ.get("ACTIONS_ID_TOKEN_REQUEST_URL"):
            raise RuntimeError(
                "GitHub OIDC token requests require 'id-token: write' permission "
                "in the workflow job"
            )
        if not environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN"):
            raise RuntimeError("ACTIONS_ID_TOKEN_REQUEST_TOKEN is not set")

    @staticmethod
    def repository_owner():
        return environ.get("GITHUB_REPOSITORY_OWNER", "")

    @staticmethod
    def audience_for_owner(owner=None):
        owner = owner or GitHub.repository_owner()
        if not owner:
            raise RuntimeError("GITHUB_REPOSITORY_OWNER is not set")
        return f"https://github.com/{owner}"

    @staticmethod
    def get_id_token(audience):
        import requests

        GitHub.require_id_token_permission()
        logger.debug("Requesting GitHub OIDC token...")

        base_url = environ["ACTIONS_ID_TOKEN_REQUEST_URL"]
        auth_token = environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]
        url = f"{base_url}&audience={quote(audience, safe='')}"
        headers = {"Authorization": f"Bearer {auth_token}"}

        response = requests.get(url, headers=headers)
        response.raise_for_status()
        token = response.json()["value"]
        GitHub.mask(token)
        return token

    @staticmethod
    def _repository(repository):
        if "/" in repository:
            return repository

        owner = (
            environ.get("HW_TEST_GITHUB_OWNER")
            or environ.get("GITHUB_REPOSITORY_OWNER")
            or "analogdevicesinc"
        )
        return f"{owner}/{repository}"

    @staticmethod
    def _headers():
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        token = environ.get("GITHUB_TOKEN", "").strip()
        if token:
            GitHub.mask(token)
            headers["Authorization"] = f"Bearer {token}"
        return headers

    @staticmethod
    def _matches_ref(artifact, ref):
        if not ref:
            return True

        workflow_run = artifact.get("workflow_run") or {}
        sha = workflow_run.get("head_sha", "")
        branch = workflow_run.get("head_branch", "")

        if ref.startswith("refs/heads/"):
            return branch == ref.removeprefix("refs/heads/")
        if ref.startswith("refs/tags/"):
            return branch == ref.removeprefix("refs/tags/")
        return sha == ref or sha.startswith(ref)

    @staticmethod
    def find_artifact(repository, name, ref=None):
        import requests

        repository = GitHub._repository(repository)
        url = f"https://api.github.com/repos/{repository}/actions/artifacts"
        response = requests.get(
            url,
            headers=GitHub._headers(),
            params={"name": name, "per_page": 100},
            timeout=60,
        )
        response.raise_for_status()

        for artifact in response.json().get("artifacts", []):
            if artifact.get("expired"):
                continue
            if GitHub._matches_ref(artifact, ref):
                return artifact

        raise LookupError(f"GitHub artifact {repository}/{name!r} not found for {ref!r}")

    @staticmethod
    def download_artifact(repository, name, ref=None, dest=None):
        import requests

        artifact = GitHub.find_artifact(repository, name, ref=ref)
        dest_dir = Path(dest or ".")
        dest_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "Downloading GitHub artifact %s/%s",
            GitHub._repository(repository),
            name,
        )
        response = requests.get(
            artifact["archive_download_url"],
            headers=GitHub._headers(),
            stream=True,
            timeout=60,
        )
        response.raise_for_status()

        archive = dest_dir / f"{name}.zip"
        with open(archive, "wb") as f:
            for chunk in response.iter_content(chunk_size=1 << 20):
                f.write(chunk)

        with ZipFile(archive) as zip_file:
            zip_file.extractall(dest_dir)

        path = dest_dir / name
        if path.exists():
            return path

        files = [path for path in dest_dir.rglob("*") if path.is_file() and path != archive]
        if len(files) == 1:
            return files[0]

        if files:
            return dest_dir

        raise LookupError(f"GitHub artifact {name!r} did not contain any files")

    @staticmethod
    def download_context_artifact(context, key="artifacts", dest=None):
        artifact = context.get("with", {}).get(key, {})
        repository = artifact["repository"]
        name = artifact["name"]
        ref = artifact.get("ref")

        return GitHub.download_artifact(repository, name, ref=ref, dest=dest)
