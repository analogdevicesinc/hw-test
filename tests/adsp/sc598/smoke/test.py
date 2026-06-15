import os
import sys
from pathlib import Path

import pytest


def main(context):
    coordinator = os.environ.get("LABGRID_COORDINATOR", "")
    env = os.environ.get("LABGRID_ENV", "")

    args = [
        str(Path(__file__).parent / "_tests.py"),
        "-v",
        "--timeout=120",
    ]
    if coordinator:
        args += ["--lg-coordinator", coordinator]
    if env:
        args += ["--lg-env", env]

    sys.exit(pytest.main(args))
