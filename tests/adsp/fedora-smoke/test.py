import logging
import re
import time

import pytest

from hw_tests.github import GitHub
from hw_tests.images import Images
from hw_tests.labgrid import LabgridClient, exporter_http_server

logger = logging.getLogger(__name__)

TEST_USER = "tester"
TEST_PASSWORD = "TestPass123!"


@pytest.mark.fedora
def test_fedora_smoke(context):
    github = GitHub(context)
    images = Images(context, github)

    spl = images.get("spl")
    uboot = images.get("uboot")
    kernel = images.get("kernel")
    devicetree = images.get("dtb")
    emmc_image = images.get("emmc")
    fedora_image = images.get("fedora")

    client = LabgridClient(context)
    with client.acquire() as target:
        spi_boot = target.get_driver("DigitalOutputProtocol", name="spi_boot")
        power = target.get_driver("PowerProtocol")
        ssh = target.get_driver("SSHDriver")
        openocd = target.get_driver("OpenOCDDriver", activate=False)
        uboot_driver = target.get_driver("UBootDriver", name="uboot", activate=False)
        console = uboot_driver.console

        spi_boot.set(False)
        power.cycle()

        files = {
            "u-boot-spl": spl,
            "u-boot": uboot,
            images.artifact_path("kernel"): kernel,
            images.artifact_path("dtb"): devicetree,
            images.artifact_path("emmc"): emmc_image,
            images.artifact_path("fedora"): fedora_image,
        }
        with exporter_http_server(ssh, files) as (directory, port):
            target.activate(console)
            target.activate(openocd)
            try:
                openocd.execute([f"cd {directory}", *openocd.load_commands])
            finally:
                target.deactivate(openocd)

            console.sendline("")
            time.sleep(0.2)
            target.activate(uboot_driver)
            console.sendline("version")
            console.expect("U-Boot", timeout=30)
            console.expect(uboot_driver.prompt, timeout=30)

            console.sendline("dhcp")
            console.expect(uboot_driver.prompt, timeout=120)

            # This is not part of the manual bootstrap flow in documentation,
            # but it is needed to avoid collisions on exporter.
            console.sendline(f"setenv httpdstp {port}")
            console.expect(uboot_driver.prompt, timeout=30)

            console.sendline(
                f"wget ${{kernel_addr_r}} {openocd.interface.host}:/"
                f"{images.artifact_path('kernel')}"
            )
            console.expect(uboot_driver.prompt, timeout=180)

            console.sendline(
                f"wget ${{fdt_addr_r}} {openocd.interface.host}:/"
                f"{images.artifact_path('dtb')}"
            )
            console.expect(uboot_driver.prompt, timeout=180)

            # Pass the ADI console arguments to Linux for the RAM boot.
            console.sendline("setenv bootargs ${adi_bootargs}")
            console.expect(uboot_driver.prompt, timeout=30)

            console.sendline("booti ${kernel_addr_r} - ${fdt_addr_r}")
            uboot_driver.await_boot()
            target.deactivate(uboot_driver)
            logger.info("Linux booted")

            console.expect(re.escape("Continue? [y/N]:"), timeout=240)
            console.sendline("y")
            console.expect(re.escape("SPI install complete"), timeout=600)
            logger.info("SPI install complete")

            # Install the Fedora rootfs onto the board's normal eMMC image.
            console.expect(re.escape("Choice [0/1/2]:"), timeout=240)
            console.sendline("2")
            console.expect(re.escape("PC IP address:"), timeout=240)
            console.sendline(f"{openocd.interface.host}:{port}")
            console.expect(re.escape("eMMC install complete."), timeout=1800)
            console.expect(re.escape("Rootfs install complete."), timeout=600)
            logger.info("Fedora rootfs install complete")

            console.expect(re.escape("Waiting for switch"), timeout=120)

            spi_boot.set(True)
            target.deactivate(spi_boot)
            console.expect(re.escape("SPI boot mode detected."), timeout=30)
            console.expect(re.escape("Rebooting..."), timeout=30)

            target.activate(uboot_driver)
            console.sendline("version")
            console.expect("U-Boot", timeout=30)
            console.expect(uboot_driver.prompt, timeout=30)
            logger.info("SPI U-Boot verified")

            # Default bootcommand is still "run spiboot"; Fedora lives on
            # eMMC, so boot it explicitly.
            console.sendline("run mmcboot")
            uboot_driver.await_boot()
            target.deactivate(uboot_driver)
            logger.info("Fedora Linux booted")

            # firstboot-user.service holds /dev/ttySC0 exclusively here
            # (Conflicts=serial-getty@ttySC0.service), so there is no getty
            # racing this interactive setup.
            console.expect(re.escape("======== First Boot Setup ========"), timeout=120)
            console.expect(re.escape("Username:"), timeout=30)
            console.sendline(TEST_USER)
            console.expect(re.escape(f"Set password for {TEST_USER}:"), timeout=30)
            console.expect("New password:", timeout=30)
            console.sendline(TEST_PASSWORD)
            console.expect("Retype new password:", timeout=30)
            console.sendline(TEST_PASSWORD)
            console.expect(re.escape(f"User '{TEST_USER}' created."), timeout=30)
            console.expect(re.escape("SSH:"), timeout=30)
            logger.info("Fedora first-boot user setup complete")

            # The actual regression check for issue #53: before the
            # Conflicts=/ConditionPathExists= fix, systemd-getty-generator was
            # masked globally and serial-getty@ttySC0 never came back here,
            # leaving no way to log in over the serial console again.
            console.expect("login:", timeout=60)
            console.sendline(TEST_USER)
            console.expect("Password:", timeout=30)
            console.sendline(TEST_PASSWORD)
            console.sendline("whoami")
            console.expect(TEST_USER, timeout=30)
            logger.info("Serial console login verified")

        target.activate(ssh)

        os_release = ssh.run_check("cat /etc/os-release")
        assert any("fedora" in line.lower() for line in os_release), os_release

        systemd_state = ssh.run_check("systemctl is-system-running --wait || true")
        assert systemd_state and systemd_state[0] in ("running", "degraded"), systemd_state

        ssh.run_check("systemctl is-active NetworkManager")
        ssh.run_check("systemctl is-active sshd")

        ip_addr = ssh.run_check("ip -4 -o addr show eth0")
        assert ip_addr, "eth0 has no IPv4 address"
        logger.info("Network up: %s", ip_addr)
