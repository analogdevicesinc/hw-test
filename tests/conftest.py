from pathlib import Path

from hw_tests.context import build_context, parse_set_env, test_name
from hw_tests.github import GitHub
from hw_tests.labgrid import LabError
from hw_tests.logging import install_pytest_log_redaction
from hw_tests.ssh_config import ssh_config_path


def pytest_exception_interact(node, call, report):
    """Surface a test failure as a GitHub Actions error annotation."""
    if not report.failed:
        return

    crash = getattr(report.longrepr, "reprcrash", None)
    if crash is not None:
        path, lineno = crash.path, crash.lineno
    else:
        path, lineno, _ = node.location
        lineno = lineno + 1 if lineno is not None else None
    error = call.excinfo.value
    title = f"Test failure in {node.nodeid}"
    message = crash.message if crash is not None else call.excinfo.exconly()
    if output := getattr(error, "output", None):
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        lines = output.splitlines()
        picked = [line for line in lines if "Error" in line][:10] + lines[-3:]
        if (returncode := getattr(error, "returncode", None)) is not None:
            message = f"{call.excinfo.typename}, exit status {returncode}"
        message += "\n" + "\n".join(dict.fromkeys(picked))
    GitHub.annotate("error", message, title=title, file=path, line=lineno)


def pytest_runtest_makereport(item, call):
    """Surface a lab problem that skipped a test as a GitHub Actions warning annotation."""
    if call.excinfo is not None and isinstance(call.excinfo.value, LabError):
        GitHub.annotate("warning", str(call.excinfo.value), title=f"Lab problem in {item.nodeid}")


def pytest_configure(config):
    from labgrid.util.ssh import SSHConnection

    _original = SSHConnection._get_ssh_base_args

    def _patched(self):
        args = _original(self)
        if ssh_config_path.exists():
            args += ["-F", str(ssh_config_path)]
        return args

    SSHConnection._get_ssh_base_args = _patched


def pytest_sessionstart(session):
    install_pytest_log_redaction(session.config)


def pytest_collection_modifyitems(config, items):
    """When set env var is provided, keep only tests that match the name."""
    overrides = parse_set_env()
    if not overrides:
        return

    names = {o["name"] for o in overrides if "name" in o}
    if not names:
        return

    selected = []
    deselected = []
    for item in items:
        test_dir = Path(item.fspath).parent
        try:
            name = test_name(test_dir)
        except ValueError:
            deselected.append(item)
            continue

        if name in names:
            selected.append(item)
        else:
            deselected.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
    items[:] = selected


def pytest_generate_tests(metafunc):
    if "context" not in metafunc.fixturenames:
        return

    test_dir = Path(metafunc.definition.fspath).parent
    context = build_context(test_dir, parse_set_env())

    needs = context.get("needs")
    if not needs:
        contexts = [context]
    elif all(isinstance(need, str) for need in needs):
        contexts = [{**context, "needs": needs}]
    else:
        contexts = [{**context, "needs": need} for need in needs]

    ids = [
        "+".join(context["needs"]) if "needs" in context else context["name"]
        for context in contexts
    ]
    metafunc.parametrize("context", contexts, ids=ids)

