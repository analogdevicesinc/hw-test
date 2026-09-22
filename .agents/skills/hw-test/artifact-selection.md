# Getting the right build onto the board

Full background: `docs/write-a-test.rst` ("Use build artifacts when
needed"), `docs/run-a-test.rst` ("Run against local build files").

## Two ways to get a file

**A single known artifact** — `hw_tests.github.GitHub.download(name)`
downloads one named artifact from the triggering workflow run (or, with
`source=`, one release asset). Use this only when a test genuinely wants
one specific, named build output.

**A role, resolved for whatever was built** — `hw_tests.images.Images`.
Prefer this for anything platform/build-system shaped (`spl`, `uboot`,
`kernel`, `dtb`, `rootfs`, `emmc`, ...):

```python
from hw_tests.github import GitHub
from hw_tests.images import Images

images = Images(context, GitHub(context))
spl = images.get("spl")
uboot = images.get("uboot")
```

`Images.get(role)`:
1. Detects the *flavor* from the repository under test
   (`GitHub.owner_repository`'s last path segment, e.g. `linux`,
   `u-boot`, `br2-external`, `lnxdsp-adi-meta`) — or `context["flavor"]`
   if explicitly overridden.
2. Reads `tests/<category>/artifacts.toml` (`category` = first path
   segment of the test name, so `adsp/u-boot` reads
   `tests/adsp/artifacts.toml`).
3. Picks the artifact whose name matches the role's `artifact` glob, and
   the file inside it matching the role's `file` glob. When more than one
   candidate remains, it narrows by `needs` as a **case-insensitive
   substring** of the artifact name (`needs = ["sc598", "ezkit"]` matches
   an artifact containing `sc598_ezkit`, and rejects one containing
   `ezlite`).
4. If the role isn't defined for the detected flavor, the test is
   **skipped**, not failed — that image source just doesn't support it.

## `artifacts.toml` shape

```toml
["br2-external".spl]
artifact = "*_defconfig"
file = "bootstrap/u-boot-spl"

[linux.kernel]
artifact = "*_defconfig-gcc-arm64"
file = "boot/Image"

[linux.spl]
artifact = "*_defconfig*"
file = "debug/u-boot-spl"
source = "br2-external"          # pull this role from a release instead

[sources.br2-external]
backend = "release"               # only supported backend today
repository = "analogdevicesinc/br2-external"
tag = "2026.02-1.1.1"
```

`source` lets a Linux kernel test mix the kernel/dtb from the PR's own
workflow run with SPL/U-Boot/rootfs pinned to a known-good release — read
the existing `tests/adsp/artifacts.toml` before adding a new role or
flavor; extend it rather than duplicating role logic in `test.py`.

## Local development without CI

Without `workflow_run_url`/`GITHUB_TOKEN`, `Images`/`GitHub` fall back to
files placed at `_artifacts/<test-name>/<index>/` (workflow-sourced roles,
index increasing per `download()` call) or
`_artifacts/<test-name>/release/<source-name>/` (release-sourced roles).
Running the test once prints the exact expected path in a `WARNING` — copy
your locally built files there rather than guessing the layout.

## Default to release artifacts unless told otherwise

When the user hasn't given a PR link, `workflow_run_url`, branch, or other
explicit source preference, don't default to fetching the triggering
workflow run's own build — default to whatever `tests/<category>/artifacts.toml`
already pins as `source =` (the release backend under `[sources.<name>]`).
That's the known-good, always-available build; a workflow-run artifact only
exists for one specific CI run and requires `GITHUB_TOKEN` plus knowing
which run to point at. If it's not clear from the task whether the user
wants the release-pinned build or a specific PR/branch build, ask — don't
guess a `workflow_run_url` on their behalf.

## Selecting a PR build vs. a base build (for regression tests)

To exercise a specific PR/commit, pass `workflow_run_url` (and
`GITHUB_TOKEN`) pointing at the workflow run that built *that* commit, and
override `context["repository"][<repo>]["ref"]` if the test's default ref
differs:

```bash
export GITHUB_TOKEN=<token>
set='{"name": "adsp/u-boot", "workflow_run_url": "https://api.github.com/repos/analogdevicesinc/u-boot/actions/runs/<run_id>"}' \
    pytest -vvs
```

For a genuine base-vs-patched comparison, run the identical test twice,
changing only which build the artifacts resolve to:

1. **Patched**: `workflow_run_url` of the PR branch's CI run (or a locally
   built PR artifact under `_artifacts/...`).
2. **Base**: `workflow_run_url` of a CI run built from the PR's base
   commit/branch (the most recent green run on the target branch before
   the PR), or a locally built base artifact placed the same way.

If no base build exists anywhere (never built, or the base commit predates
CI for this platform), say so explicitly in the report instead of building
one artificially — see [regression-testing.md](regression-testing.md).
Do not claim the base was tested unless a base build was actually acquired
and run.
