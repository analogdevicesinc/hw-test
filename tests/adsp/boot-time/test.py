import logging
from pathlib import Path
from time import monotonic, sleep

import pytest

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
    client = LabgridClient(context)
    with client.acquire() as target:
        spi_boot = target.get_driver("DigitalOutputProtocol", name="spi_boot")
        power = target.get_driver("PowerProtocol")
        ssh = target.get_driver("SSHDriver")
        openocd = target.get_driver("OpenOCDDriver", activate=False)
        shell = target.get_driver("ShellDriver", activate=False)
        power_sense = target.get_driver(
            "DigitalOutputProtocol", name="power_sense", activate=False
        )
        boot_done = target.get_driver(
            "DigitalOutputProtocol", name="boot_done", activate=False
        )

        spi_boot.set(True)

        # Boot the board and program the systemd service
        power.cycle()
        target.activate(shell)
        shell.run_check("udhcpc -i end0 -n -q")
        files = {
            "gpio-boot-trace": FILES / "gpio-boot-trace",
            "gpio-boot-trace.service": FILES / "gpio-boot-trace.service",
        }
        with exporter_http_server(ssh, files) as port:
            base = f"http://{openocd.interface.host}:{port}"
            shell.run_check(f"wget -O /tmp/gpio-boot-trace {base}/gpio-boot-trace")
            shell.run_check(
                f"wget -O /tmp/gpio-boot-trace.service {base}/gpio-boot-trace.service"
            )
        shell.run_check(
            "install -m0755 /tmp/gpio-boot-trace /usr/libexec/gpio-boot-trace && "
            "install -m0644 /tmp/gpio-boot-trace.service "
            "/lib/systemd/system/gpio-boot-trace.service && "
            "systemctl unmask gpio-boot-trace.service; systemctl daemon-reload && "
            "systemctl enable gpio-boot-trace.service && sync"
        )
        logger.info("gpio-boot-trace service installed into SPI rootfs")
        target.deactivate(shell)

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
