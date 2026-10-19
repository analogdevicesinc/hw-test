"""
Download build artifacts from Cloudsmith.

Basic usage:

.. code-block:: python

   import logging
   logging.basicConfig(level=logging.INFO)

   from hw_tests.cloudsmith import Cloudsmith

   cs = Cloudsmith()

   # Get the latest artifact from branch 'refs/heads/...'
   path = cs.download(
       repository='linux',
       name='adi_bcm2709_defconfig-gcc-arm-devel',
       version='refs/heads/rpi-6.12.y',
   )
"""

import logging
import tempfile
from os import environ
from pathlib import Path
from urllib.parse import quote

import requests

from hw_tests.github import GitHub, _extract_if_archive

logger = logging.getLogger(__name__)


class Cloudsmith:
    """Cloudsmith API client.

    Packages are looked up in ``$CLOUDSMITH_NAMESPACE/<repository>``.
    Authentication is done on creation, see :meth:`authenticate`.

    :param context: Test context. Its ``name`` sets the local fallback
        directory of :meth:`download`.
    """

    _token = None
    __down_counter = 0

    def __init__(self, context=None):
        self._test_name = (context or {}).get("name")
        self.authenticate()

    def authenticate(self):
        """Get an API token and validate it.

        Uses ``CLOUDSMITH_API_KEY`` if set. Otherwise, in GitHub Actions, gets
        a token through :meth:`github_oidc`. Without a token, only public
        artifacts can be downloaded.
        """
        self._token = environ.get('CLOUDSMITH_API_KEY', '').strip()

        if self._token != '':
            GitHub.mask(self._token)
        elif GitHub.in_actions():
            self.github_oidc()

        if self._token != '':
            Cloudsmith.validate(self._token)
        else:
            logger.warning("No 'CLOUDSMITH_API_KEY' obtained, only public artifacts will be available.")

    def github_oidc(self):
        """Exchange a GitHub OIDC token for a Cloudsmith API token.

        Requires ``CLOUDSMITH_SERVICE_SLUG`` and ``CLOUDSMITH_NAMESPACE``.
        The token is exported as ``CLOUDSMITH_API_KEY`` to the environment
        and ``GITHUB_ENV``, for the next steps.
        """
        cs_namespace = environ.get("CLOUDSMITH_NAMESPACE", '').strip()
        cs_service_slug = environ.get("CLOUDSMITH_SERVICE_SLUG", '').strip()
        if cs_service_slug == '':
            return

        id_token = GitHub.get_id_token()
        self._token = Cloudsmith.get_api_token(cs_namespace, cs_service_slug, id_token)

        environ["CLOUDSMITH_API_KEY"] = self._token
        with open(environ['GITHUB_ENV'], 'a') as f:
            f.write(f'CLOUDSMITH_API_KEY={self._token}\n')

        return

    @staticmethod
    def get_api_token(org_name: str, cs_service_slug: str, id_token: str, api_host: str = "api.cloudsmith.io") -> str:
        """Return a Cloudsmith API token for an OIDC ``id_token``.

        :raises ValueError: Cloudsmith returned an empty token.
        """
        logger.debug("Exchanging for Cloudsmith token...")
        url = f"https://{api_host}/openid/{org_name}/"
        payload = {
            "oidc_token": id_token,
            "service_slug": cs_service_slug,
        }
        response = requests.post(url, json=payload)
        response.raise_for_status()
        token = response.json().get("token", "")
        if not token or not isinstance(token, str) or not token.strip():
            raise ValueError("Cloudsmith returned an empty or invalid token in the response")
        GitHub.mask(token)
        return token

    @staticmethod
    def validate(token: str, api_host: str = "api.cloudsmith.io") -> None:
        """Check ``token`` against the API and log the authenticated user.

        :raises requests.HTTPError: the token is rejected.
        """
        url = f"https://{api_host}/v1/user/self/"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        name = response.json().get("name", "<unknown>")
        logger.info(f"Authenticated as {name}")

    def _headers(self):
        headers = {"Accept": "application/json"}
        if self._token:
            headers["X-Api-Key"] = self._token
        return headers

    def _org_repo(self, repository: str) -> str:
        namespace = environ.get("CLOUDSMITH_NAMESPACE", "").strip()
        if not namespace:
            raise ValueError("CLOUDSMITH_NAMESPACE is not set")
        return f"{namespace}/{repository}"

    def _find_package(
        self,
        owner_repository: str,
        artifact: str,
        version: str | None,
        tags: tuple | list,
        api_host: str = "api.cloudsmith.io",
    ) -> dict:
        """
        Return the latest package matching artifact name and tag constraints.
        For example, if artifact is not at refs/heads/main, but at refs/heads/main~,
        will return sha from refs/heads/main~
        """
        parts = []

        if version is not None:
            if len(version) == 40 and all(c in "0123456789abcdefABCDEF" for c in version):
                parts.append(f"version:^{version}$")
            elif version.startswith(("refs/heads/", "refs/tags/")):
                parts += ["tag:on/push", f"tag:{version}"]
            elif version.startswith("refs/pull/"):
                parts += ["tag:on/pull_request", f"tag:{version}"]
            else:
                parts += ["tag:on/push", f"version:{version}"]
        elif tags:
            parts += [f"tag:{t}" for t in tags]
        else:
            raise ValueError("Either version or tags must be provided")

        parts.append(f"name:{artifact}")

        query = "+".join(parts)
        url = (
            f"https://{api_host}/v1/packages/{owner_repository}/"
            f"?query={quote(query, safe=':+/^$')}&sort=-date&page_size=1"
        )
        response = requests.get(url, headers=self._headers())
        response.raise_for_status()
        results = response.json()

        if not results:
            raise LookupError(
                f"Artifact {artifact!r} not found in {owner_repository} "
                f"(query: {query!r})"
            )

        return results[0]

    def download(
        self,
        repository: str,
        name: str,
        version: str | None = None,
        tags: tuple | list = (),
        path: Path | str | None = None,
    ) -> Path:
        """Download an artifact and extract it if it is an archive.

        The package is selected by ``version`` if given, else by ``tags``:

        - ``version`` as a full 40-char SHA: exact match.
        - ``version`` as a git ref (``refs/heads/*``, ``refs/tags/*``,
          ``refs/pull/*``): latest package built from that ref.
        - other ``version`` values, such as a short SHA: latest pushed
          package matching the version.
        - ``tags``: latest package that has all the tags, for example
          ``('on/push', 'refs/heads/main')``.

        If ``CLOUDSMITH_NAMESPACE`` is not set, a warning is logged and
        ``_artifacts/<test name>/<n>`` is returned, where ``n`` counts calls.
        Put the files there to run locally. Without a ``context``, a
        ``ValueError`` is raised instead.

        :param repository: Cloudsmith repository in ``CLOUDSMITH_NAMESPACE``.
        :param name: Package name.
        :param version: SHA, git ref, or version.
        :param tags: Tags to match when ``version`` is not given.
        :param path: Output directory. A temporary directory by default.
        :returns: Directory containing the artifact.
        :raises LookupError: no package matches.
        """
        local_ = None
        if self._test_name is not None:
            local_ = Path.cwd() / '_artifacts' / self._test_name / str(self.__down_counter)
            self.__down_counter += 1

        if local_ is not None and not environ.get("CLOUDSMITH_NAMESPACE", "").strip():
            logger.warning(
                f"No 'CLOUDSMITH_NAMESPACE' set, cannot download artifacts; "
                f"assuming you have them at '{local_}'"
            )
            return local_

        owner_repository = self._org_repo(repository)
        package = self._find_package(owner_repository, name, version, tags)

        sha = package.get("version", "<unknown>")
        logger.info(f"Resolved {repository!r}/{name!r} to SHA {sha}")

        cdn_url = package.get("cdn_url")
        if not cdn_url:
            raise ValueError(f"Package {name!r} has no cdn_url")
        dest_dir = (
            Path(path)
            if path is not None
            else Path(tempfile.mkdtemp(prefix="hw-test-cs-"))
        )
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / name

        logger.info(f"Downloading {name} from {cdn_url}")
        response = requests.get(
            cdn_url,
            headers=self._headers(),
            stream=True
        )
        response.raise_for_status()
        with open(dest_file, "wb") as f:
            f.writelines(response.iter_content(chunk_size=1 << 20))

        _extract_if_archive(dest_file)

        return dest_dir
