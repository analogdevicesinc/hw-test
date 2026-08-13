import logging
import tomllib
from fnmatch import fnmatch
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

TESTS_DIR = Path(__file__).resolve().parent.parent / "tests"

REPO_FLAVOR = {
    "br2-external": "br2",
    "u-boot": "uboot",
    "lnxdsp-adi-meta": "yocto",
    "linux": "linux",
}

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
    assert matches, f"no file matches {what!r}"
    assert len(matches) == 1, f"multiple files match {what!r}: {matches}"
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

    def _source(self, spec):
        """Resolve a role's artifact source.

        Roles without ``source`` use the run under test (all None / github).
        A role with ``source`` pulls from another repository; the pin lives in
        the descriptor's top-level ``[sources.<name>]`` table as
        ``{repository, backend?, tag?, branch?, run_id?}``. ``backend =
        "release"`` selects the GitHub Releases backend (addressed by ``tag``);
        otherwise the GitHub Actions-run backend is used (``branch``/``run_id``).

        Returns ``(owner_repository, branch, run_id, backend, tag)``.
        """
        source = spec.get("source")
        if not source:
            return None, None, None, "github", None
        sources = self._load().get("sources") or {}
        pin = sources.get(source)
        assert pin, f"role source {source!r} not configured in descriptor [sources]"
        owner_repository = pin.get("repository")
        assert owner_repository, f"source {source!r} missing 'repository'"
        backend = pin.get("backend", "github")
        tag = pin.get("tag")
        branch = pin.get("branch")
        run_id = pin.get("run_id")
        if backend == "release":
            assert tag, f"release source {source!r} missing 'tag'"
        return owner_repository, branch, (str(run_id) if run_id else None), backend, tag

    def _match_artifact(self, artifacts, artifact_glob):
        """Pure selection: return (name, reason).

        Glob-first, narrowed by needs only when the glob matches several. Returns
        (name, None) or (None, reason) so a strict caller can assert while the
        run-resolution probe skips quietly.
        """
        if not artifacts:
            return None, "no artifacts listed"
        names = [
            a["name"] for a in artifacts
            if not a["name"].lower().endswith(_SIDECAR_SUFFIXES)
        ]
        matches = [n for n in names if fnmatch(n, artifact_glob)]
        if not matches:
            return None, f"no artifact matches {artifact_glob!r} in {names}"
        if len(matches) > 1:
            needs = self._needs()
            narrowed = [n for n in matches if all(tok in n.lower() for tok in needs)]
            if narrowed:
                matches = narrowed
        if len(matches) > 1:
            return None, f"multiple artifacts match {artifact_glob!r}: {matches}"
        return matches[0], None

    def _select_artifact(self, artifact_glob, owner_repository=None, run_id=None):
        artifacts = self.github.list_artifacts(owner_repository, run_id)
        if not artifacts:
            # offline / no token: caller falls back to local _artifacts/
            return None
        name, reason = self._match_artifact(artifacts, artifact_glob)
        assert name, reason
        return name

    def _resolve_run(self, owner_repository, branch, artifact_glob):
        """Newest successful run of ``owner_repository`` that carries the
        artifact. Returns None offline (falls back like the non-pinned path);
        asserts if runs exist but none carries a matching artifact."""
        run_ids = self.github.successful_run_ids(owner_repository, branch)
        for run_id in run_ids:
            artifacts = self.github.list_artifacts(owner_repository, run_id)
            name, _ = self._match_artifact(artifacts, artifact_glob)
            if name:
                return str(run_id)
        assert not run_ids, (
            f"no recent successful run of {owner_repository!r}"
            + (f" on {branch!r}" if branch else "")
            + f" carries an artifact matching {artifact_glob!r} (needs {self._needs()})"
        )
        return None

    def _download(self, name, owner_repository, run_id):
        if owner_repository is None and run_id is None:
            return self.github.download(name)
        return self.github.download(name, owner_repository=owner_repository, run_id=run_id)

    def _role_spec(self, role):
        flavor = self.flavor
        roles = self._load().get(flavor, {})
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
        owner_repository, branch, run_id, backend, tag = self._source(spec)

        if backend == "release":
            assets = self.github.list_release_assets(tag, owner_repository)
            name, reason = self._match_artifact(assets, spec["artifact"])
            assert name, reason
            key = ("release", owner_repository, tag, name)
            if key not in self._cache:
                self._cache[key] = self.github.download_release_asset(
                    name, tag, owner_repository
                )
            return self._resolve_file(self._cache[key], spec["file"], role, recursive=True)

        if spec.get("source") and run_id is None:
            run_id = self._resolve_run(owner_repository, branch, spec["artifact"])
        name = self._select_artifact(spec["artifact"], owner_repository, run_id)
        # offline: key by the artifact glob; include source+run so a resolved
        # run never aliases another
        key = (owner_repository, run_id, name if name is not None else spec["artifact"])
        if key not in self._cache:
            self._cache[key] = self._download(name or spec["artifact"], owner_repository, run_id)
        return self._resolve_file(self._cache[key], spec["file"], role)

    def artifact_path(self, role):
        """Return the descriptor-relative path resolved for ``role``."""
        if role not in self._paths:
            self.get(role)
        return self._paths[role]
