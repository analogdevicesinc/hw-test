from contextlib import contextmanager

from labgrid import Environment

from hw_tests.labgrid.hosts import install_host_aliases


@contextmanager
def labgrid_environment(config_file, coordinator=None, ssh_hosts=None):
    install_host_aliases(ssh_hosts)
    env = Environment(config_file)
    if coordinator:
        env.config.set_option("coordinator_address", coordinator)

    try:
        yield env
    finally:
        env.cleanup()

