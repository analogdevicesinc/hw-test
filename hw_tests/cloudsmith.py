import logging
import requests
from os import environ
from urllib.parse import quote

logger = logging.getLogger(__name__)

class Cloudsmith():
    _token = None

    def __init__(self):
        self.authenticate()

    def authenticate(self):
        self._token = environ.get('CLOUDSMITH_API_KEY', '').strip()

        if self._token != '':
            if environ.get('GITHUB_ACTIONS') == 'true':
                print(f"::add-mask::{self._token}", flush=True)
        elif environ.get('GITHUB_ACTIONS') == 'true':
            self.github_oidc()

        if self._token != '':
            Cloudsmith.validate(self._token)
        else:
            logger.warning("No 'CLOUDSMITH_API_KEY' obtained, only public artifacts will be available.")

    def github_oidc(self):
        cs_namespace = environ.get("CLOUDSMITH_NAMESPACE", '').strip()
        cs_service_slug = environ.get("CLOUDSMITH_SERVICE_SLUG", '').strip()
        if cs_service_slug == '':
            return

        github_owner = environ.get("GITHUB_REPOSITORY_OWNER")
        github_audience = f"https://github.com/{github_owner}"

        id_token = Cloudsmith.get_github_id_token(github_audience)
        self._token = Cloudsmith.get_api_token(cs_namespace, cs_service_slug, id_token)

        environ.set("CLOUDSMITH_API_KEY", self._token)
        with open(environ['GITHUB_ENV'], 'a') as f:
            f.write(f'CLOUDSMITH_API_KEY={self._token}')

        return

    @staticmethod
    def get_github_id_token(audience: str) -> str:
        logger.debug("Requesting GitHub OIDC token...")
        base_url = environ["ACTIONS_ID_TOKEN_REQUEST_URL"]
        auth_token = environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]

        url = f"{base_url}&audience={quote(audience, safe='')}"
        headers = {
            "Authorization": f"Bearer {auth_token}",
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        id_token = response.json()["value"]
        print(f"::add-mask::{id_token}", flush=True)
        return id_token

    @staticmethod
    def get_api_token(org_name: str, cs_service_slug: str, id_token: str, api_host: str = "api.cloudsmith.io") -> str:
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
        print(f"::add-mask::{token}", flush=True)
        return token

    @staticmethod
    def validate(token: str, api_host: str = "api.cloudsmith.io") -> None:
        url = f"https://{api_host}/v1/user/self/"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        name = response.json().get("name", "<unknown>")
        logger.info(f"Authenticated as {name}")
