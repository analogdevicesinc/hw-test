"""
Run a test from tests/**/.

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
import logging
import tomllib
import importlib.util

from os import environ
from sys import modules, exit
from pathlib import Path

from .logging import set_logging

logger = logging.getLogger(__name__)


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


def run_test(context):
    name = context.get('name')
    if name is None:
        logger.error("No '.name' provided")
        exit(1)

    path = Path(f"tests/{name}")
    if not Path.is_dir(path):
        logger.error(f"Test path '{path}' does not exist")
        exit(1)

    if 'repository' not in context:
        context['repository'] = {}

    with path.joinpath('config.toml').open('rb') as meta_:
        meta = tomllib.load(meta_)

    meta = reformat_named_lists(meta)
    context = deep_merge(meta, context)

    logger.info(f"invoking '{path}' with context:\n{context}")

    test_script = path / "test.py"
    spec = importlib.util.spec_from_file_location("dynamic_test_mod", test_script)
    module = importlib.util.module_from_spec(spec)
    modules["dynamic_test_mod"] = module
    spec.loader.exec_module(module)
    module.main(context)

    return


def main():
    set_logging()

    set_val = environ.get('set', '')
    context = json.loads(set_val) if set_val else {}
    logger.info(f"test: {json.dumps(context, indent=2)}")

    run_test(context)

if __name__ == '__main__':
    main()
