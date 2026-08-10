import logging
import tomllib
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

TESTS_DIR = Path(__file__).resolve().parent.parent / "tests"

REPO_FLAVOR = {
    "br2-external": "br2",
    "u-boot": "uboot",
    "lnxdsp-adi-meta": "yocto",
}


def find_one(items, pattern, kind):
    """Return the single fnmatch match, else assert."""
    from fnmatch import fnmatch

    matches = [i for i in items if fnmatch(_name(i), pattern)]
    assert matches, f"no {kind} matches {pattern!r}"
    assert len(matches) == 1, f"multiple {kind} match {pattern!r}: {matches}"
    return matches[0]


def _name(item):
    return item.name if isinstance(item, Path) else str(item)


class Images:
    def __init__(self, context, github):
        self.context = context
        self.github = github
        self._descriptor = None
        self._cache = {}

    @property
    def flavor(self):
        override = self.context.get("flavor")
        if override:
            return override
        repo = self.github.owner_repository
        basename = repo.rsplit("/", 1)[-1] if repo else None
        flavor = REPO_FLAVOR.get(basename)
        if flavor is None:
            pytest.skip(f"unknown flavor for repo {repo!r}")
        return flavor

    def _descriptor_path(self):
        """Resolve the descriptor from the test's category."""
        name = self.context.get("name", "")
        category = name.split("/", 1)[0]
        assert category, f"cannot resolve test category from name {name!r}"
        return TESTS_DIR / category / "artifacts.toml"

    def _load(self):
        if self._descriptor is None:
            path = self._descriptor_path()
            assert path.is_file(), f"missing artifacts descriptor: {path}"
            with path.open("rb") as f:
                self._descriptor = tomllib.load(f)
        return self._descriptor

    def _needs(self):
        needs = self.context.get("needs") or []
        if isinstance(needs, str):
            needs = [needs]
        return [n.lower() for n in needs]

    def _select_artifact(self, artifact_glob):
        artifacts = self.github.list_artifacts()
        if not artifacts:
            # No listing available (offline / no GITHUB_TOKEN). The caller falls
            # back to GitHub.download's local '_artifacts/' path instead.
            return None
        needs = self._needs()
        candidates = [
            a["name"] for a in artifacts
            if all(tok in a["name"].lower() for tok in needs)
            and not a["name"].lower().endswith(_SIDECAR_SUFFIXES)
        ]
        assert candidates, f"no artifact matches needs {needs}"
        matches = [n for n in candidates if fnmatch(n, artifact_glob)]
        assert matches, f"no artifact matches {artifact_glob!r} in {candidates}"
        assert len(matches) == 1, f"multiple artifacts match {artifact_glob!r}: {matches}"
        return matches[0]

    def get(self, role):
        flavor = self.flavor
        roles = self._load().get(flavor, {})
        if role not in roles:
            pytest.skip(f"role {role!r} not available for flavor {flavor!r}")
        spec = roles[role]

        name = self._select_artifact(spec["artifact"])
        # Offline: no resolved name; key the download by the artifact glob so
        # roles sharing an artifact still share one local fallback directory.
        key = name if name is not None else spec["artifact"]
        if key not in self._cache:
            self._cache[key] = self.github.download(name or spec["artifact"])
        directory = self._cache[key]

        # Top-level only: artifacts may carry nested duplicates (e.g. yocto's
        # programming-images/) that would make a basename match ambiguous.
        files = sorted(p for p in Path(directory).glob("*") if p.is_file())
        return find_one(files, spec["file"], "file")
