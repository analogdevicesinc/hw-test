from os import environ
from pathlib import Path

import pytest

from hw_tests.context import build_context, parse_set_env, test_name
from hw_tests.logging import gha_escape, install_pytest_log_redaction
from hw_tests.ssh_config import ssh_config_path


def pytest_exception_interact(node, call, report):
    """Surface a test failure as a GitHub Actions error annotation."""
    if environ.get("GITHUB_ACTIONS") != "true" or not report.failed:
        return

    crash = getattr(report.longrepr, "reprcrash", None)
    if crash is not None:
        path, lineno = crash.path, crash.lineno
    else:
        path, lineno, _ = node.location
        lineno = lineno + 1 if lineno is not None else None
    exc = call.excinfo
    title = f"Test failure: {exc.type.__name__}"

    command = f"::error file={gha_escape(path, prop=True)}"
    if lineno is not None:
        command += f",line={lineno}"
    command += f",title={gha_escape(title, prop=True)}"
    command += "::Test failed; see the job log for details."
    print(command, flush=True)


def pytest_configure(config):
    from labgrid.util.ssh import SSHConnection

    _original = SSHConnection._get_ssh_base_args

    @staticmethod
    def _patched():
        args = _original()
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
    overrides = parse_set_env()
    context = build_context(test_dir, overrides)

    needs = context.get("needs")
    # Hardware tests acquire a labgrid board and cannot run without needs to
    # match it. Fail at collection, before any artifacts are downloaded, rather
    # than deep inside the test body once a board is requested. Only guard tests
    # that will actually be selected: when the test call names specific tests,
    # the rest are deselected later in pytest_collection_modifyitems, so their
    # missing needs are irrelevant.
    target_names = {o["name"] for o in overrides if "name" in o}
    selected = not target_names or context["name"] in target_names
    if selected and not needs and hasattr(metafunc.module, "LabgridClient"):
        raise pytest.UsageError(
            f"{context['name']}: no needs to match a board; pass them via the "
            f"test call, e.g. set='{{\"needs\": [\"sc598\", \"ezkit\"]}}'"
        )

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


def _addoption_once(group, *args, **kwargs):
    try:
        group.addoption(*args, **kwargs)
    except ValueError as exc:
        if "already added" not in str(exc):
            raise
