from contextlib import contextmanager

from labgrid import Environment


@contextmanager
def labgrid_environment(config_file, coordinator=None):
    env = Environment(config_file)
    if coordinator:
        env.config.set_option("coordinator_address", coordinator)

    try:
        yield env
    finally:
        env.cleanup()

