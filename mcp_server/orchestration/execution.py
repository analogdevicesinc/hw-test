"""Run one hw-test test against a reserved place via a pytest subprocess.

The process factory is injected so this is unit-testable without spawning
pytest. Context reaches the test through the ``set`` env var (the existing
executor contract in tests/conftest.py). Destructive tests require confirm.
"""

from __future__ import annotations

import json
import secrets
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class _Run:
    run_id: str
    proc: object
    log_path: Path
    name: str


_RUNS: dict[str, _Run] = {}


def _default_proc_factory(argv, env, log_path):
    import subprocess
    from os import environ
    log_file = open(log_path, "w")
    return subprocess.Popen(argv, env={**environ, **env},
                            stdout=log_file, stderr=subprocess.STDOUT)


def run(name, place, image_location, *, overrides=None, env=None,
        confirm=False, destructive=False, proc_factory=_default_proc_factory):
    if destructive and not confirm:
        raise ValueError(
            f"test '{name}' is destructive; pass confirm=True to run it")
    set_payload = {
        "name": name,
        "labgrid_target": place,
        "image_location": image_location,
        **(overrides or {}),
    }
    run_id = secrets.token_hex(8)
    log_path = Path(tempfile.gettempdir()) / f"hw-test-run-{run_id}.log"
    argv = [sys.executable, "-m", "pytest", "-vvs", f"tests/{name}"]
    child_env = {"set": json.dumps(set_payload), **(env or {})}
    proc = proc_factory(argv, child_env, str(log_path))
    _RUNS[run_id] = _Run(run_id=run_id, proc=proc, log_path=log_path, name=name)
    return run_id


def status(run_id):
    entry = _RUNS[run_id]
    if entry.proc.poll() is None:
        return {"state": "running"}
    return {"state": "passed" if entry.proc.returncode == 0 else "failed"}


def result(run_id):
    entry = _RUNS[run_id]
    if entry.proc.poll() is None:
        raise RuntimeError(f"run '{run_id}' is still running")
    return {
        "state": "passed" if entry.proc.returncode == 0 else "failed",
        "returncode": entry.proc.returncode,
    }


def logs(run_id, tail=200):
    entry = _RUNS[run_id]
    lines = entry.log_path.read_text().splitlines()
    return "\n".join(lines[-tail:])
