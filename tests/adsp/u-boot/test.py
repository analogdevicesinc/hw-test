import os
import sys
import tempfile
from pathlib import Path

import pytest

from hw_tests.cloudsmith import Cloudsmith


def main(context):
    uboot_ref = context.get("with", {}).get("u-boot", {}).get("ref") or None

    cloudsmith = Cloudsmith()
    dest = Path(tempfile.mkdtemp(prefix="hw-test-uboot-"))

    cloudsmith.download(repository="u-boot", artifact="u-boot-spl", version=uboot_ref, dest=dest)
    cloudsmith.download(repository="u-boot", artifact="u-boot", version=uboot_ref, dest=dest)

    coordinator = os.environ.get("LABGRID_COORDINATOR", "")
    env = os.environ.get("LABGRID_ENV", "")

    args = [
        str(Path(__file__).parent / "_tests.py"),
        "-v",
        "--timeout=300",
    ]
    if coordinator:
        args += ["--lg-coordinator", coordinator]
    if env:
        args += ["--lg-env", env]

    os.environ.setdefault("UBOOT_SPL", str(dest / "u-boot-spl"))
    os.environ.setdefault("UBOOT", str(dest / "u-boot"))

    sys.exit(pytest.main(args))
