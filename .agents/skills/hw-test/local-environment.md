# Running from a local developer workstation

This doc is for a coding agent running locally (not inside a GitHub Actions
runner). It covers what to check before touching GitHub or real hardware, and
how to report what was actually validated. It doesn't replace
[labgrid.md](labgrid.md)/[artifact-selection.md](artifact-selection.md)/
[failure-triage.md](failure-triage.md) — it's the preflight layer in front of
them.

## GitHub access

Prefer the developer's existing authenticated `gh` session over asking for a
token:

```bash
gh auth status
```

If authenticated, use `gh` directly (`gh pr view`, `gh pr diff`, `gh issue
view`, `gh api`, `gh run list`, `gh run view`, `gh run download`) — this
covers PR/issue inspection and downloading workflow artifacts without ever
touching `GITHUB_TOKEN` by hand. Don't ask the user for a token if `gh` is
already authenticated.

If `gh` is not authenticated but GitHub access is required, stop and say so:

```
GitHub authentication is required for this operation, but the local
GitHub CLI is not authenticated.

Please run:

    gh auth login
```

Continue with whatever repository-local analysis is still possible (reading
the diff if already fetched, static checks), but don't report a PR/artifact
as inspected if it wasn't actually fetched.

Never print, extract, or log the token value (`GITHUB_TOKEN`/`GH_TOKEN`)
itself — checking that `gh` is authenticated, or that the env var is set, is
fine; printing its contents is not.

## `LG_COORDINATOR`

Hardware tests need `LG_COORDINATOR` in the local shell. Check presence
without printing the value:

```bash
test -n "$LG_COORDINATOR"
```

Never hardcode a coordinator address in the skill, in `AGENTS.md`, or in any
repository file, and never try to pull the plaintext value out of the
GitHub Actions `LG_COORDINATOR` secret — that secret only exists inside a
workflow run; a local agent has no way to read it and shouldn't try.

If it's missing:

```
Hardware execution cannot start because LG_COORDINATOR is not configured
in the local environment.

Please configure it in the current shell, for example:

    export LG_COORDINATOR="<coordinator-address>"

I can continue implementing and statically validating the test, but I
cannot perform hardware validation until coordinator access is available.
```

Don't ask the user to paste the actual address into the chat unless they
volunteer it.

## Coordinator reachability

Once `LG_COORDINATOR` is set, confirm it's actually reachable before
attempting a real test — `labgrid-client places` (or an equivalent read-only
`LabgridClient`/labgrid-client operation already used in this repo) is
harmless and fast:

```bash
labgrid-client places
```

If this hangs/errors while `LG_COORDINATOR` is set:

```
LG_COORDINATOR is configured, but the coordinator is currently
unreachable from this machine.

Check VPN/network connectivity and coordinator availability.
```

Classify this as `INFRASTRUCTURE_FAILURE` (see [failure-triage.md](failure-triage.md)),
not a DUT/product problem.

## Preflight, scoped to the task

Before running on real hardware, check only what the specific task needs —
don't run every check for every request:

| Check | Command |
|---|---|
| In the repo | `git rev-parse --show-toplevel` |
| GitHub access (only if the task touches GitHub) | `gh auth status` |
| `LG_COORDINATOR` set (only if the task touches hardware) | `test -n "$LG_COORDINATOR"` |
| Test collects | `python -m pytest --collect-only <target>` |
| Coordinator reachable | `labgrid-client places` |
| Required board family exists | `labgrid-client places` output, or `show`/`who` for a specific place |

A static-only task (writing/reviewing a test, checking collection) never
needs `LG_COORDINATOR` or `gh` at all.

## Board availability

Still goes through `LabgridClient`/`needs` — this doc changes nothing about
board selection (see [labgrid.md](labgrid.md)). If every board matching
`needs` is occupied: don't steal, don't force-release someone else's place,
don't substitute unrelated hardware. Let `LabgridClient`'s existing wait/
retry behavior run, and tell the user plainly if it can't proceed instead of
working around it.

## Missing local tooling

If `gh`, `labgrid-client`, `pytest`, or a required Python dependency isn't
installed, report exactly what's missing rather than guessing around it.
Don't install system-wide software on your own initiative — follow the
repo's documented setup (`README.md`, `docs/set-up-a-hardware-host.rst`) or
ask, unless the user already told you to install things.

## Reporting what was actually validated

Track and report three independent states, don't collapse them into one
"validated":

```
IMPLEMENTED         — the test file exists and is intended to cover the behavior
STATICALLY_VALIDATED — it was collected/linted successfully, no hardware involved
HARDWARE_VALIDATED  — it was actually acquired a board and run
```

Example — coordinator unavailable:

```
IMPLEMENTED: yes
STATICALLY_VALIDATED: yes
HARDWARE_VALIDATED: no
```
> The test was implemented and collected successfully, but hardware
> validation was not performed because LG_COORDINATOR was unavailable.

Example — hardware run actually happened:

```
IMPLEMENTED: yes
STATICALLY_VALIDATED: yes
HARDWARE_VALIDATED: yes
```
> Ran on <place/board>, <revision/artifact>, result: <pass/fail>.

Never compress this into "implemented and validated" when hardware wasn't
actually run — that's exactly the false claim the rest of this skill already
warns against.

## Privileged/debug access

If an hw-test MCP capability layer is configured for this session, use it
for privileged GitHub and hardware operations instead of doing them
yourself: don't SSH into exporters directly, don't invoke privileged
`labgrid-client` operations directly, and don't ask the user to expose
`LG_COORDINATOR` to the AI process. If it's unavailable or missing a
capability you need, say plainly which live operation can't be performed —
don't fall back to hunting for `LG_COORDINATOR`, `GH_TOKEN`, `GITHUB_TOKEN`,
or SSH credentials in the local environment as a workaround.

If the user explicitly hands you a debug endpoint (e.g. an OpenOCD telnet
interface), treat access to it per whatever security policy is configured,
and still follow the intrusive-vs-non-intrusive diagnostic rules in
[failure-triage.md](failure-triage.md).

## Secrets

Never print or persist the value of: `LG_COORDINATOR`, `GITHUB_TOKEN`,
`GH_TOKEN`, SSH credentials, PDU credentials, exporter credentials, or any
other API token. Checking *whether* one is set (`test -n "$VAR"`, `gh auth
status`) is fine; echoing it is not. This is the same rule
[labgrid.md](labgrid.md) already states for coordinator/exporter hosts —
applies here too, to every credential a local run might touch.
