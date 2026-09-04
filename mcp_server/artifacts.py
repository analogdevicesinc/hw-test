"""Resolve the CI workflow run that published images for a commit.

The hw-test test self-downloads its images from a GitHub Actions run: it reads
``context['workflow_run_url']`` (the run's REST API URL) and lists that run's
artifacts with ``GITHUB_TOKEN`` (see ``hw_tests/github.py`` /
``hw_tests/images.py``). So "resolve an image for a SHA" means "find the newest
completed run for that SHA that still has non-expired artifacts" and hand its
API URL to the test.

``gh(endpoint) -> dict`` is injected (production = ``gh api <endpoint>``), so
this is unit-testable with no network.
"""

from __future__ import annotations

_API = "https://api.github.com"


def _live_artifacts(gh, repo, run_id) -> bool:
    data = gh(f"repos/{repo}/actions/runs/{run_id}/artifacts")
    return any(not a.get("expired") for a in data.get("artifacts", []))


def resolve_workflow_run(repo, sha, *, gh) -> str | None:
    """Return the API URL of the newest run for ``sha`` with live artifacts.

    ``repo`` is ``owner/name``. Returns ``None`` when no completed run for the
    commit has usable (non-expired) artifacts — the caller then reports an
    honest ``build-artifact-unavailable`` rather than faking a run.
    """
    listing = gh(f"repos/{repo}/actions/runs?head_sha={sha}&per_page=100")
    runs = listing.get("workflow_runs", [])
    completed = [r for r in runs if r.get("status") == "completed"]
    # Newest first by creation time (ISO-8601 strings sort chronologically).
    completed.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    for run in completed:
        if _live_artifacts(gh, repo, run["id"]):
            return f"{_API}/repos/{repo}/actions/runs/{run['id']}"
    return None
