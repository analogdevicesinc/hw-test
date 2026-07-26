"""
Prepare context for a test from tests/**/.

Input: Test to run:
  {
    "name": "demo/linux-iio-dac",
    "repository": {
      "linux": {"ref": "010c31d..."}
    }
  }

From the config.toml files, [[repository]] is parsed as
  {..., 'repository': [{'name': 'linux', 'ref': 'refs/heads/main', 'files': '...'}]}
which is reformated to
  {...,  'repository': {'linux': {'ref': 'refs/heads/main', 'files': '...'}}}
before merging into the context.

That is, any [{'name': '...', ...}], the list is replaced with dict, where name is the key.
(name must exist for each group/list entry)
"""

import json
import re
import tomllib
from os import environ
from pathlib import Path


def reformat_named_lists(d):
    """Reformat any list-of-dicts-with-'name' into a dict keyed by name.

    e.g. [{'name': 'linux', 'ref': '...'}, {'name': 'hdl', 'ref': '...'}]
      -> {'linux': {'ref': '...'}, 'hdl': {'ref': '...'}}
    """
    if isinstance(d, dict):
        return {k: reformat_named_lists(v) for k, v in d.items()}
    if isinstance(d, list) and d and all(isinstance(e, dict) and 'name' in e for e in d):
        return {
            e['name']: reformat_named_lists({k: v for k, v in e.items() if k != 'name'})
            for e in d
        }
    return d


def deep_merge(base, override):
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def parse_set_env():
    """Parse the `set` env var into a list of override dicts."""
    set_val = environ.get("set", "").strip()
    if not set_val:
        return []
    # If json quotes are inverted, quietly fix
    if re.search(r'[{\[]\s*\'', set_val):
        set_val = set_val.replace('"', '\x00').replace("'", '"').replace('\x00', "'")
    parsed = json.loads(set_val)
    if isinstance(parsed, dict):
        return [parsed]
    return parsed


def test_name(test_dir: Path) -> str:
    """Derive the test name from its directory relative to tests/."""
    return str(test_dir.resolve().relative_to(Path(__file__).resolve().parent.parent / "tests"))


def build_context(test_dir: Path, overrides: list[dict]) -> dict:
    name = test_name(test_dir)

    config_path = test_dir / "config.toml"
    if config_path.exists():
        with config_path.open("rb") as f:
            meta = reformat_named_lists(tomllib.load(f))
    else:
        meta = {}

    context = {"name": name}
    context = deep_merge(context, meta)

    override = {}
    for o in overrides:
        if o.get("name", name) == name:
            override = o
            break

    context = deep_merge(context, override)
    if isinstance(context.get("needs"), str):
        context["needs"] = [context["needs"]]
    return context
