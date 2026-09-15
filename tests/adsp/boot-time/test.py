import logging
import time
from pathlib import Path
from time import monotonic, sleep

import pytest

from hw_tests.github import GitHub
from hw_tests.images import Images
from hw_tests.labgrid import LabgridClient, exporter_http_server

logger = logging.getLogger(__name__)

FILES = Path(__file__).parent / "files"

POLL_INTERVAL = 0.01


# The service toggles the line at boot-complete, debounce the signal to
# ensure the level is stable before accepting an edge.
def debounce(driver, level):
    edge_start = None
    deadline = monotonic() + 0.5
    while monotonic() < deadline:
        sleep(POLL_INTERVAL)
        if bool(driver.get()) == level:
            edge_start = edge_start or monotonic()
            # Debounce signals for 50 ms
            if monotonic() - edge_start >= 0.05:
                return edge_start
        else:
            edge_start = None
    return None


@pytest.mark.linux
def test_boot_time(context, record_property):
    github = GitHub(context)
    images = Images(context, github)

    spl = images.get("spl")
    uboot = images.get("uboot")
    spl_ldr = images.get("spl-boot")
    uboot_ldr = images.get("uboot-boot")
    fit_image = images.get("fitImage")
    spi_rootfs = images.get("rootfs-spi")

    client = LabgridClient(context)
    with client.acquire() as target:
        spi_boot = target.get_driver("DigitalOutputProtocol", name="spi_boot")
        power = target.get_driver("PowerProtocol")
        ssh = target.get_driver("SSHDriver")
        openocd = target.get_driver("OpenOCDDriver", activate=False)
        uboot_driver = target.get_driver("UBootDriver", name="uboot", activate=False)
        shell = target.get_driver("ShellDriver", activate=False)
        console = uboot_driver.console
        power_sense = target.get_driver(
            "DigitalOutputProtocol", name="power_sense", activate=False
        )
        boot_done = target.get_driver(
            "DigitalOutputProtocol", name="boot_done", activate=False
        )

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
            images.artifact_path("fitImage"): fit_image,
        }
        with exporter_http_server(ssh, files) as port:
            console.sendline("dhcp")
            console.expect(uboot_driver.prompt, timeout=120)

            console.sendline(f"setenv httpdstp {port}")
            console.expect(uboot_driver.prompt, timeout=30)

            console.sendline(
                f"wget ${{loadaddr}} {openocd.interface.host}:/"
                f"{images.artifact_path('fitImage')}"
            )
            console.expect(uboot_driver.prompt, timeout=180)

            console.sendline("run ramargs")
            console.expect(uboot_driver.prompt, timeout=30)

            console.sendline("bootm ${loadaddr}")
            uboot_driver.await_boot()
            target.deactivate(uboot_driver)
            logger.info("Linux booted from RAM disk")

        target.activate(shell)
        shell.run_check("udhcpc -i eth0 -q")

        transfers = {
            "u-boot-spl.ldr": spl_ldr,
            "u-boot.ldr": uboot_ldr,
            "fitImage": fit_image,
            "rootfs.ubi": spi_rootfs,
            "gpio-boot-trace": FILES / "gpio-boot-trace",
            "gpio-boot-trace.service": FILES / "gpio-boot-trace.service",
        }
        with exporter_http_server(ssh, transfers) as port:
            base = f"http://{openocd.interface.host}:{port}"
            shell.run_check("mkdir -p /tmp")
            for name in transfers:
                shell.run_check(f"wget -O /tmp/{name} {base}/{name}")

        spl_mtd = mtd_index(shell, "u-boot-spl")
        uboot_mtd = mtd_index(shell, "u-boot")
        kernel_mtd = mtd_index(shell, "kernel")
        rootfs_mtd = mtd_index(shell, "rootfs")
        flash_timeout = 900
        shell.run_check(f"flashcp -v /tmp/u-boot-spl.ldr /dev/mtd0", timeout=flash_timeout)
        shell.run_check(f"flashcp -v /tmp/u-boot.ldr /dev/mtd1", timeout=flash_timeout)
        shell.run_check(f"flashcp -v /tmp/fitImage /dev/mtd2", timeout=flash_timeout)
        shell.run_check(f"ubiformat /dev/mtd3 -f /tmp/rootfs.ubi -y", timeout=flash_timeout)
        logger.info("Programmed SPI NOR partitions")

        # Install the boot-trace service into the freshly-flashed rootfs
        shell.run_check(f"ubiattach -m 3 -d 0")
        shell.run_check(
            "mkdir -p /mnt/rootfs && mount -t ubifs ubi0:rootfs /mnt/rootfs"
        )
        try:
            shell.run_check(
                "install -m0755 /tmp/gpio-boot-trace "
                "/mnt/rootfs/usr/libexec/gpio-boot-trace && "
                "install -m0644 /tmp/gpio-boot-trace.service "
                "/mnt/rootfs/lib/systemd/system/gpio-boot-trace.service && "
                "mkdir -p /mnt/rootfs/etc/systemd/system/multi-user.target.wants && "
                "ln -sf /lib/systemd/system/gpio-boot-trace.service "
                "/mnt/rootfs/etc/systemd/system/multi-user.target.wants/"
                "gpio-boot-trace.service"
            )
        finally:
            shell.run_check("sync && umount /mnt/rootfs && ubidetach -m 3")
        logger.info("gpio-boot-trace service installed into SPI rootfs")
        target.deactivate(shell)

        spi_boot.set(True)
        target.activate(power_sense)
        target.activate(boot_done)
        power_sense.get()
        boot_done.get()
        power.cycle()

        power_time = None
        deadline = monotonic() + 180
        while monotonic() < deadline:
            if bool(power_sense.get()):
                power_time = monotonic()
                logger.info("Power detected on power_sense")
                break
            sleep(POLL_INTERVAL)
        assert power_time is not None, "power-on was never detected"

        # Wait for low->high edge toggled by GPIO in Linux
        low_time = None
        while monotonic() < deadline:
            if not boot_done.get():
                low_time = debounce(boot_done, False)
                if low_time is not None:
                    break
            sleep(POLL_INTERVAL)
        assert low_time is not None, "boot-trace marker never seen low"

        high_time = None
        while monotonic() < deadline:
            if boot_done.get():
                high_time = debounce(boot_done, True)
                if high_time is not None:
                    break
            sleep(POLL_INTERVAL)
        assert high_time is not None, "boot-trace marker never seen high"

        # The boot-trace service toggles the line low->high after 500ms to create
        # a clean edge for timing, so subtract 500ms from measured time to get true time
        boot_time = (high_time - power_time) - 0.5
        record_property("boot_time_s", round(boot_time, 3))
        logger.info("Boot time: %.3f s", boot_time)
