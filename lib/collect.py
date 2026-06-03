"""
Match workflow-run-to-context output against tests/*.yml metafiles.

Input (stdin): JSON produced by workflow-run-to-context@action, e.g.:
  {
    "repository": "linux",
    "head_sha": "010c31d...",
    "changed_files": "drivers/iio/dac/Kconfig\ndrivers/iio/dac/ad3530r.c",
    ...
  }

Output: JSON list written to <output_path> (or stdout), one entry per matched test:
  [
    {
      "name": "linux-iio-dac",
      "with": {
        "linux": {"ref": "010c31d..."},   <- merge_commit_sha || head_sha: this repo triggered
        "hdl":   {"ref": "refs/heads/main"} <- default ref: other repo
      }
    }
  ]
"""

import fnmatch
import glob
import json
import sys
import yaml


def load_test_metas():
    metas = []
    for path in sorted(glob.glob('tests/*.yml')):
        with open(path) as f:
            metas.append(yaml.safe_load(f))
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
    raw_files = context.get('changed_files', '')
    changed_files = [f for f in raw_files.replace(' ', '\n').splitlines() if f.strip()]

    results = []

    for meta in metas:
        name = meta.get('name')
        repo_rules = meta.get('repos', [])

        triggered = False
        for rule in repo_rules:
            name_ = rule.get('name', '')
            if (name_ == triggering_repo and
                paths_match(changed_files, rule.get('path', '')) and
                branch == rule.get('branch', '')):
                triggered = True
                break

        if not triggered:
            continue

        with_repos = {}
        for rule in repo_rules:
            name_ = rule.get('name', '')
            default_ref = rule.get('ref', '')
            if name_ == triggering_repo:
                with_repos[name_] = {'ref': sha if sha else default_ref}
            else:
                with_repos[name_] = {'ref': default_ref}

        print(f"matched test '{name}'", file=sys.stderr)
        results.append({
            'name': name,
            'with': with_repos,
        })

    return results


def main():
    output_path = sys.argv[1] if len(sys.argv) > 1 else None
    context = json.load(sys.stdin)
    metas = load_test_metas()
    matched = match_tests(context, metas)
    serialized = json.dumps(matched, indent=2)
    if output_path:
        with open(output_path, 'w') as f:
            f.write(serialized)
    else:
        print(serialized)

if __name__ == '__main__':
    main()
