import pytest

from hw_tests.context import parse_set_env


def pytest_collection_modifyitems(config, items):
    if config.invocation_params.args or parse_set_env():
        return

    raise pytest.UsageError(
        "Please specify which tests to run, for example:\n"
        "  pytest tests/adsp/u-boot   # hardware tests for adsp u-boot\n"
        "  pytest tests               # all hardware tests (danger!)\n"
        "  set='[{...}]' pytest       # hardware tests with context overwrites\n"
        "  pytest hw_tests            # library unit tests\n"
    )
