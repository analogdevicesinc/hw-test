"""
Match workflow-run-to-context output against tests/**/config.toml metafiles.

Input: JSON by workflow-run-to-context@action, e.g.:
  {
    "repository": "linux",
    "head_sha": "010c31d...",
    "changed_files": "drivers/iio/dac/Kconfig\ndrivers/iio/dac/ad3530r.c",
    ...
  }

Output: JSON list written to <output_path> (or stdout), one entry per matched test:
  [
    {
      "name": "demo/linux-iio-dac",
      "with": {
        "linux": {"ref": "010c31d..."},   <- merge_commit_sha || head_sha: this repo triggered
      }
    }
  ]
"""

import fnmatch
import glob
import json
import logging
import tomllib

from os import environ

from .logging import set_logging

logger = logging.getLogger(__name__)


def load_test_metas():
    metas = []
    for path in sorted(glob.glob('tests/**/config.toml', recursive=True)):
        uid = path[len('tests/'):-len('/config.toml')]
        with open(path, 'rb') as f:
            meta = tomllib.load(f)
        meta['_uid'] = uid
        metas.append(meta)
    return metas


def paths_match(changed_files, path_block):
    """Return True if any changed file matches any glob pattern in path_block."""
    if not path_block:
        return False
    patterns = [p.strip() for p in path_block.splitlines() if p.strip()]
    for filepath in changed_files:
        for pat in patterns:
            if fnmatch.fnmatch(filepath, pat):
                return True
    return False


def match_tests(context, metas):
    """
    For each test metafile, check whether any repo rule fires for the triggering
    repository.  Emit at most one result entry per test.
    """
    triggering_repo = context.get('repository', '')
    sha = context.get('merge_commit_sha', '')
    if sha == '':
      sha = context.get('head_sha', '')
    branch = context.get('branch', '')
    ref = f"refs/heads/{branch}"
    raw_files = context.get('changed_files', '')
    changed_files = [f for f in raw_files.replace(' ', '\n').splitlines() if f.strip()]

    results = []

    for meta in metas:
        name = meta['_uid']
        meta_repos = meta.get('repo', [])

        triggered = False
        for repo in meta_repos:
            name_ = repo.get('name', '')
            on = repo.get('on', {})
            on_ref = on.get('ref', None)
            if (name_ == triggering_repo and
                paths_match(changed_files, on.get('path', '')) and
                (on_ref is not None and ref == on_ref)):
                triggered = True
                break

        if not triggered:
            continue

        with_repos = {}
        for repo in meta_repos:
            name_ = repo.get('name', '')
            if name_ == triggering_repo and sha:
                with_repos[name_] = {'ref': sha}

        logger.info(f"Matched test '{name}'")
        results.append({
            'name': name,
            'with': with_repos,
        })

    return results


def main():
    set_logging()

    context = json.loads(environ['context'])
    metas = load_test_metas()
    matched = match_tests(context, metas)

    names = json.dumps([t['name'] for t in matched])
    tests = json.dumps(matched, indent=2)

    logger.info(f"names: {names}")
    logger.info(f"tests: {tests}")

    if environ.get('GITHUB_ACTIONS') == 'true':
        with open(environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f'names={names}\n')
            f.write(f'tests<<EOF\n{tests}\nEOF\n')

if __name__ == '__main__':
    main()
