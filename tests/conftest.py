from pathlib import Path

import pytest

from hw_tests.context import parse_set_env, build_context, test_name
from hw_tests.ssh_config import ssh_config_path


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


@pytest.fixture
def context(request):
    test_dir = Path(request.fspath).parent
    return build_context(test_dir, parse_set_env())


def _addoption_once(group, *args, **kwargs):
    try:
        group.addoption(*args, **kwargs)
    except ValueError as exc:
        if "already added" not in str(exc):
            raise

