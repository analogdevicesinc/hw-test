import os
from contextlib import contextmanager

from labgrid import Environment

from hw_tests.labgrid.hosts import install_host_aliases


def env_path_from_pytest(pytestconfig):
    return (
        pytestconfig.getoption("lg_env", default=None)
        or os.environ.get("LABGRID_ENV")
        or os.environ.get("LG_ENV")
    )


def coordinator_from_pytest(pytestconfig):
    return (
        pytestconfig.getoption("lg_coordinator", default=None)
        or os.environ.get("LG_COORDINATOR")
        or os.environ.get("LABGRID_COORDINATOR")
    )


@contextmanager
def labgrid_environment(config_file, coordinator=None):
    install_host_aliases()
    env = Environment(config_file)
    if coordinator:
        env.config.set_option("coordinator_address", coordinator)

    try:
        yield env
    finally:
        env.cleanup()


def get_target(env, name, config_file):
    target = env.get_target(name)
    if target is None:
        raise AssertionError(f"target {name!r} not found in {config_file}")
    return target
