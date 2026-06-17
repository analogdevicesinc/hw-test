import logging
from os import environ
from urllib.parse import quote

logger = logging.getLogger(__name__)


def in_actions():
    return environ.get("GITHUB_ACTIONS") == "true"


def mask(value):
    if in_actions() and value:
        print(f"::add-mask::{value}", flush=True)


def require_id_token_permission():
    if not environ.get("ACTIONS_ID_TOKEN_REQUEST_URL"):
        raise RuntimeError(
            "GitHub OIDC token requests require 'id-token: write' permission "
            "in the workflow job"
        )
    if not environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN"):
        raise RuntimeError("ACTIONS_ID_TOKEN_REQUEST_TOKEN is not set")


def repository_owner():
    return environ.get("GITHUB_REPOSITORY_OWNER", "")


def audience_for_owner(owner=None):
    owner = owner or repository_owner()
    if not owner:
        raise RuntimeError("GITHUB_REPOSITORY_OWNER is not set")
    return f"https://github.com/{owner}"


def get_id_token(audience):
    import requests

    require_id_token_permission()
    logger.debug("Requesting GitHub OIDC token...")

    base_url = environ["ACTIONS_ID_TOKEN_REQUEST_URL"]
    auth_token = environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]
    url = f"{base_url}&audience={quote(audience, safe='')}"
    headers = {"Authorization": f"Bearer {auth_token}"}

    response = requests.get(url, headers=headers)
    response.raise_for_status()
    token = response.json()["value"]
    mask(token)
    return token
