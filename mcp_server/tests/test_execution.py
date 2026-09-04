"""Tests for the pytest-subprocess execution primitive (fake proc)."""

import json

import pytest

from mcp_server.orchestration import execution


class FakeProc:
    def __init__(self, returncode=0, finished=True):
        self._returncode = returncode
        self._finished = finished
        self.returncode = returncode if finished else None
        self.pid = 4242

    def poll(self):
        return self._returncode if self._finished else None


def _factory(proc, captured):
    def factory(argv, env, log_path):
        captured["argv"] = argv
        captured["env"] = env
        captured["log_path"] = log_path
        # simulate the subprocess writing a log
        with open(log_path, "w") as f:
            f.write("line1\nline2\n")
        return proc
    return factory


def test_run_rejects_destructive_without_confirm():
    with pytest.raises(ValueError, match="destructive"):
        execution.run("adsp/u-boot", "sc598-a", "/img/uboot.bin",
                      destructive=True, confirm=False,
                      proc_factory=lambda *a, **k: None)


def test_run_passes_context_via_set_env():
    execution._RUNS.clear()
    captured = {}
    run_id = execution.run("adsp/u-boot", "sc598-a", "/img/uboot.bin",
                           proc_factory=_factory(FakeProc(), captured))
    payload = json.loads(captured["env"]["set"])
    assert payload["name"] == "adsp/u-boot"
    assert payload["labgrid_target"] == "sc598-a"
    assert payload["image_location"] == "/img/uboot.bin"
    assert "pytest" in " ".join(captured["argv"])
    assert run_id


def test_run_threads_overrides_and_env():
    execution._RUNS.clear()
    captured = {}
    execution.run(
        "adsp/u-boot", "sc598-a", "/img/uboot.bin",
        overrides={"workflow_run_url": "https://api/run/1"},
        env={"GITHUB_TOKEN": "tok"},
        proc_factory=_factory(FakeProc(), captured))
    payload = json.loads(captured["env"]["set"])
    # overrides land in the set JSON the test reads as context
    assert payload["workflow_run_url"] == "https://api/run/1"
    # extra env is passed to the child alongside the set var
    assert captured["env"]["GITHUB_TOKEN"] == "tok"


def test_status_and_result_passed():
    execution._RUNS.clear()
    run_id = execution.run("adsp/u-boot", "sc598-a", "/img/uboot.bin",
                           proc_factory=_factory(FakeProc(returncode=0), {}))
    assert execution.status(run_id) == {"state": "passed"}
    assert execution.result(run_id) == {"state": "passed", "returncode": 0}


def test_status_failed_returncode():
    execution._RUNS.clear()
    run_id = execution.run("adsp/u-boot", "sc598-a", "/img/uboot.bin",
                           proc_factory=_factory(FakeProc(returncode=1), {}))
    assert execution.status(run_id) == {"state": "failed"}
    assert execution.result(run_id)["returncode"] == 1


def test_result_raises_while_running():
    execution._RUNS.clear()
    run_id = execution.run("adsp/u-boot", "sc598-a", "/img/uboot.bin",
                           proc_factory=_factory(FakeProc(finished=False), {}))
    assert execution.status(run_id) == {"state": "running"}
    with pytest.raises(RuntimeError, match="still running"):
        execution.result(run_id)


def test_logs_returns_tail():
    execution._RUNS.clear()
    run_id = execution.run("adsp/u-boot", "sc598-a", "/img/uboot.bin",
                           proc_factory=_factory(FakeProc(), {}))
    assert execution.logs(run_id, tail=1) == "line2"
