"""
Run a test from tests/**/.

Input: Test to run:
  {
    "name": "demo/linux-iio-dac",
    "with": {
      "linux": {"ref": "010c31d..."}
    }
  }
"""

import json
import tomllib
import importlib.util

from sys import stderr, stdin, modules, exit
from pathlib import Path


def run_test(context):
    name = context.get('name')
    if name is None:
        print("No '.name' provided", file=stderr)
        exit(1)

    path = Path(f"tests/{name}")
    if not Path.is_dir(path):
        print(f"Test path '{path}' does not exist", file=stderr)
        exit(1)

    with path.joinpath('config.toml').open('rb') as meta_:
        meta = tomllib.load(meta_)

    # enrich with defaults
    if 'with' not in context:
        context['with'] = {}
    meta_repos = meta.get('repo', [])
    for repo in meta_repos:
        name_ = repo.get('name', '')
        if name_ not in context['with']:
            default_ref = repo.get('on', {}).get('ref', '')
            context['with'][name_] = {'ref': default_ref}

    print(f"invoking '{path}' with context:\n{context}")

    test_script = path / "test.py"
    spec = importlib.util.spec_from_file_location("dynamic_test_mod", test_script)
    module = importlib.util.module_from_spec(spec)
    modules["dynamic_test_mod"] = module
    spec.loader.exec_module(module)
    module.main(context)

    return


def main():
    context = json.load(stdin)
    run_test(context)

if __name__ == '__main__':
    main()
