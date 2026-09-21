"""Reproduce analogdevicesinc/linux#3400 with an uncompressed network write."""

import logging
import shlex
import time
from contextlib import contextmanager

import pytest

from hw_tests.github import GitHub
from hw_tests.images import Images
from hw_tests.labgrid import LabgridClient, exporter_http_server

logger = logging.getLogger(__name__)


@contextmanager
def sparse_http_server(ssh):
    directory = ssh.run_check("mktemp -d /dev/shm/hw-test-emmc.XXXXXX")[0].strip()
    assert directory.startswith("/dev/shm/hw-test-emmc."), f"unexpected dir: {directory}"
    directory_q = shlex.quote(directory)
    pid_file = shlex.quote(f"{directory}/http.pid")
    log_file = shlex.quote(f"{directory}/http.log")

    try:
        ssh.run_check(f"truncate -s 4294967296 {directory_q}/emmc.img")
        port = ssh.run_check(
            "python3 -c 'import socket; s = socket.socket(); "
            "s.bind((\"\", 0)); print(s.getsockname()[1])'"
        )[0].strip()
        assert port.isdigit(), f"unexpected HTTP port: {port}"
        ssh.run_check(
            "nohup python3 -m http.server --bind 0.0.0.0 "
            f"--directory {directory_q} {port} >{log_file} 2>&1 </dev/null & "
            f"echo $! > {pid_file} && sleep 1 && kill -0 $(cat {pid_file})"
        )
        yield port
    finally:
        ssh.run(f"kill $(cat {pid_file}) 2>/dev/null; rm -rf {directory_q}")


@pytest.mark.linux
def test_emmc_sustained_write(context):
    images = Images(context, GitHub(context))
    spl = images.get("spl")
    uboot = images.get("uboot")
    kernel = images.get("kernel")
    devicetree = images.get("dtb")
    ramdisk = images.get("rootfs")

    with LabgridClient(context).acquire() as target:
        spi_boot = target.get_driver("DigitalOutputProtocol", name="spi_boot")
        power = target.get_driver("PowerProtocol")
        ssh = target.get_driver("SSHDriver")
        openocd = target.get_driver("OpenOCDDriver", activate=False)
        uboot_driver = target.get_driver("UBootDriver", name="uboot", activate=False)
        console = uboot_driver.console

        spi_boot.set(False)
        power.cycle()
        ssh.put(str(spl), "u-boot-spl")
        ssh.put(str(uboot), "u-boot")

        target.activate(console)
        target.activate(openocd)
        try:
            openocd.execute(openocd.load_commands)
        finally:
            target.deactivate(openocd)

        console.sendline("")
        time.sleep(0.2)
        target.activate(uboot_driver)
        console.sendline("version")
        console.expect("U-Boot", timeout=30)
        console.expect(uboot_driver.prompt, timeout=30)

        files = {
            images.artifact_path("kernel"): kernel,
            images.artifact_path("dtb"): devicetree,
            images.artifact_path("rootfs"): ramdisk,
        }
        with exporter_http_server(ssh, files) as port:
            console.sendline("dhcp")
            console.expect(uboot_driver.prompt, timeout=120)
            console.sendline(f"setenv httpdstp {port}")
            console.expect(uboot_driver.prompt, timeout=30)

            for role, address in (
                ("kernel", "kernel_addr_r"),
                ("dtb", "fdt_addr_r"),
                ("rootfs", "ramdisk_addr_r"),
            ):
                console.sendline(
                    f"wget ${{{address}}} {openocd.interface.host}:/"
                    f"{images.artifact_path(role)}"
                )
                console.expect(uboot_driver.prompt, timeout=180)

            console.sendline("run ramargs")
            console.expect(uboot_driver.prompt, timeout=30)
            console.sendline("booti ${kernel_addr_r} ${ramdisk_addr_r} ${fdt_addr_r}")
            uboot_driver.await_boot()
            target.deactivate(uboot_driver)

            if console.expect(["login:", r"~ #", r"# "], timeout=240)[0] == 0:
                console.sendline("root")
                console.expect(r"# ", timeout=30)

            console.sendline("printf 'KERNEL_RELEASE=%s\\n' \"$(uname -r)\"")
            console.expect(r"KERNEL_RELEASE=6\.18\.[^\s]+", timeout=30)
            console.expect(r"# ", timeout=30)

            console.sendline(
                "for net in $(ip -o link show | awk -F ': ' '!/lo/ && !/LOOPBACK/ {print $2}'); "
                "do ip link set \"$net\" up; udhcpc -i \"$net\" -n -q -T 3 && break; done"
            )
            console.expect(r"# ", timeout=120)
            console.sendline("set -o pipefail")
            console.expect(r"# ", timeout=30)

            # Sparse zeros reproduce the raw HTTP write without copying a 4 GiB image.
            with sparse_http_server(ssh) as emmc_port:
                logger.info("Writing 4 GiB uncompressed HTTP stream to eMMC")
                console.sendline(
                    f"wget -O - http://{openocd.interface.host}:{emmc_port}/emmc.img "
                    "| dd of=/dev/mmcblk0 bs=1M conv=fsync; "
                    "printf 'EMMC_STRESS_RESULT=%s\\n' \"$?\""
                )
                _, _, match, _ = console.expect(r"EMMC_STRESS_RESULT=([0-9]+)", timeout=1800)
            assert match.group(1) == b"0", "raw eMMC write failed"
            console.expect(r"# ", timeout=30)

            console.sendline(
                "dmesg | grep -E 'mmc_complete|set_work_data|mmc_blk_mq_req_done'; "
                "printf 'EMMC_KERNEL_RESULT=%s\\n' \"$?\""
            )
            _, _, match, _ = console.expect(r"EMMC_KERNEL_RESULT=([0-9]+)", timeout=30)
            assert match.group(1) == b"1", "MMC/workqueue error in kernel log"
            logger.info("Sustained eMMC write completed without the reported kernel error")
