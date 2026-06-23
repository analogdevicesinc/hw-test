def _addoption_once(group, *args, **kwargs):
    try:
        group.addoption(*args, **kwargs)
    except ValueError as exc:
        if "already added" not in str(exc):
            raise


def pytest_addoption(parser):
    labgrid = parser.getgroup("labgrid")
    _addoption_once(
        labgrid,
        "--lg-env",
        action="store",
        default=None,
        help="Path to the Labgrid environment configuration file.",
    )
    _addoption_once(
        labgrid,
        "--lg-coordinator",
        action="store",
        default=None,
        help="Labgrid coordinator address. Falls back to LG_COORDINATOR or LABGRID_COORDINATOR.",
    )
