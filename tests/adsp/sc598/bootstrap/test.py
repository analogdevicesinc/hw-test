import os
import sys
import tempfile
from pathlib import Path

import pytest

from hw_tests.cloudsmith import Cloudsmith


def main(context):
    refs = context.get("with", {})
    uboot_ref = refs.get("u-boot", {}).get("ref") or None
    linux_ref = refs.get("linux", {}).get("ref") or None

    cloudsmith = Cloudsmith()
    uboot_dest = Path(tempfile.mkdtemp(prefix="hw-test-uboot-"))
    linux_dest = Path(tempfile.mkdtemp(prefix="hw-test-linux-"))

    cloudsmith.download(repository="u-boot", artifact="u-boot-spl", version=uboot_ref, dest=uboot_dest)
    cloudsmith.download(repository="u-boot", artifact="u-boot", version=uboot_ref, dest=uboot_dest)
    cloudsmith.download(repository="linux", artifact="Image", version=linux_ref, dest=linux_dest)
    cloudsmith.download(repository="linux", artifact="sc598-som-ezkit.dtb", version=linux_ref, dest=linux_dest)

    coordinator = os.environ.get("LABGRID_COORDINATOR", "")
    env = os.environ.get("LABGRID_ENV", "")

    args = [
        str(Path(__file__).parent / "_tests.py"),
        "-v",
        "--timeout=600",
    ]
    if coordinator:
        args += ["--lg-coordinator", coordinator]
    if env:
        args += ["--lg-env", env]

    os.environ.setdefault("UBOOT_SPL", str(uboot_dest / "u-boot-spl"))
    os.environ.setdefault("UBOOT", str(uboot_dest / "u-boot"))
    os.environ.setdefault("KERNEL_IMAGE", str(linux_dest / "Image"))
    os.environ.setdefault("DEVICETREE", str(linux_dest / "sc598-som-ezkit.dtb"))

    sys.exit(pytest.main(args))
