import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

_spec = importlib.util.spec_from_file_location(
    "hw_test_conftest", Path(__file__).parents[2] / "tests" / "conftest.py"
)
conftest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(conftest)


def _annotation(monkeypatch, capsys, error, crash_message):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    node = SimpleNamespace(nodeid="tests/x/test.py::test_x", location=("tests/x/test.py", 4, ""))
    crash = SimpleNamespace(path="tests/x/test.py", lineno=5, message=crash_message)
    report = SimpleNamespace(failed=True, longrepr=SimpleNamespace(reprcrash=crash))
    call = SimpleNamespace(
        excinfo=SimpleNamespace(
            value=error, typename=type(error).__name__, exconly=lambda: crash_message
        )
    )
    conftest.pytest_exception_interact(node, call, report)
    return capsys.readouterr().out


def test_failure_annotation_shows_the_error_lines_of_the_output(monkeypatch, capsys):
    """Show the exit status, up to ten error lines and the last lines of the output."""

    lines = [f"Error: {index}" for index in range(12)] + ["Info : a", "Info : b", "done"]
    error = subprocess.CalledProcessError(1, ["ssh", "openocd"], output="\r".join(lines).encode())

    out = _annotation(monkeypatch, capsys, error, "subprocess.CalledProcessError: Command ...")

    assert out.startswith("\n::error file=tests/x/test.py,line=5,title=Test failure in ")
    assert out.rstrip("\n").split("::")[-1].split("%0A") == [
        "CalledProcessError, exit status 1",
        *[f"Error: {index}" for index in range(10)],
        "Info : a",
        "Info : b",
        "done",
    ]
