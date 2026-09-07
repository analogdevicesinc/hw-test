import logging
import tomllib
from fnmatch import fnmatch
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

TESTS_DIR = Path(__file__).resolve().parent.parent / "tests"

# Metadata artifacts published alongside images (never an image source).
_SIDECAR_SUFFIXES = (".sbom",)


def find_one(items, what, needs=()):
    """Return the single item, narrowed by needs then base-stem when several match."""
    matches = list(items)
    if len(matches) > 1:
        narrowed = [p for p in matches if all(token in _name(p).lower() for token in needs)]
        if narrowed:
            matches = narrowed
    if len(matches) > 1:
        stems = sorted(matches, key=lambda p: len(Path(_name(p)).stem))
        base = stems[0]
        if all(Path(_name(p)).stem.startswith(Path(_name(base)).stem) for p in stems):
            matches = [base]
    assert matches, f"no {what} matches"
    assert len(matches) == 1, f"multiple {what} match: {matches}"
    return matches[0]


def _name(item):
    return item.name if isinstance(item, Path) else str(item)


class Images:
    def __init__(self, context, github):
        self.context = context
        self.github = github
        self._descriptor = None
        self._cache = {}
        self._paths = {}

    @property
    def flavor(self):
        override = self.context.get("flavor")
        if override:
            return override
        repo = self.github.owner_repository
        if repo is None:
            pytest.skip(f"unknown flavor for repo {repo!r}")
        return repo.rsplit("/", 1)[-1]

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

    def _source(self, spec):
        """Return the descriptor-defined release source for a role, if any."""
        source = spec.get("source")
        if not source:
            return None
        sources = self._load().get("sources") or {}
        source = sources.get(source)
        assert source, f"role source {spec['source']!r} not configured in descriptor [sources]"
        assert source.get("backend") == "release", (
            f"unsupported source backend for {spec['source']!r}: {source.get('backend')!r}"
        )
        assert source.get("repository"), f"source {spec['source']!r} missing 'repository'"
        assert source.get("tag"), f"release source {spec['source']!r} missing 'tag'"
        return source

    def _select_artifact(self, artifacts, artifact_glob):
        names = [
            artifact["name"]
            for artifact in artifacts
            if not artifact["name"].lower().endswith(_SIDECAR_SUFFIXES)
            and fnmatch(artifact["name"], artifact_glob)
        ]
        return find_one(names, f"artifact matching {artifact_glob!r}", self._needs())

    def _role_spec(self, role):
        flavor = self.flavor
        roles = self._load().get(flavor)
        if roles is None:
            pytest.skip(f"unknown flavor for repo {self.github.owner_repository!r}")
        if role not in roles:
            pytest.skip(f"role {role!r} not available for flavor {flavor!r}")
        return roles[role]

    def _resolve_file(self, directory, file_glob, role, recursive=False):
        globber = Path(directory).rglob if recursive else Path(directory).glob
        files = sorted(p for p in globber(file_glob) if p.is_file())
        image = find_one(files, file_glob, self._needs())
        self._paths[role] = image.relative_to(directory).as_posix()
        return image

    def get(self, role):
        spec = self._role_spec(role)
        source = self._source(spec)
        if source:
            local = Path.cwd() / "_artifacts" / self.context["name"] / "release" / spec["source"]
            if local.is_dir():
                return self._resolve_file(local, spec["file"], role, recursive=True)
            owner_repository = source["repository"]
            tag = source["tag"]
            assets = self.github.list_artifacts(source=source)
            name = self._select_artifact(assets, spec["artifact"])
            key = ("release", owner_repository, tag, name)
            if key not in self._cache:
                self._cache[key] = self.github.download(name, source=source)
            return self._resolve_file(self._cache[key], spec["file"], role, recursive=True)

        artifacts = self.github.list_artifacts()
        name = self._select_artifact(artifacts, spec["artifact"]) if artifacts else None
        key = name if name is not None else spec["artifact"]
        if key not in self._cache:
            self._cache[key] = self.github.download(name or spec["artifact"])
        return self._resolve_file(self._cache[key], spec["file"], role)

    def artifact_path(self, role):
        """Return the descriptor-relative path resolved for ``role``."""
        if role not in self._paths:
            self.get(role)
        return self._paths[role]
