import subprocess
from unittest.mock import patch

from hw_tests.github import GitHub
from hw_tests.labgrid.labgrid_client import LabgridClient
from hw_tests.ssh_config import SSHConfig

SHOW_OUTPUT = """\
Place 'MUN-01-SC598_EZKIT-01':
  matches:
    adi-lf-test/MUN-01-SC598_EZKIT-01/*
    adi-lf-test/MUN-01-SC598_EZKIT-01/NetworkPowerPort/power
    adi-lf-test/MUN-01-SC598_EZKIT-01/NetworkSerialPort/console
    adi-lf-test/MUN-01-SC598_EZKIT-01/NetworkUSBDebugger/onboard-debug-agent
  acquired: None
  acquired resources:
  created: 2026-05-12 10:31:43.961482
  changed: 2026-06-23 16:07:28.001844
Matching resource 'boot-mode' (adi-lf-test/MUN-01-SC598_EZKIT-01/NetworkSerialPort/boot-mode):
  {'acquired': None,
   'avail': True,
   'cls': 'NetworkSerialPort',
   'params': {'extra': {'path': '/dev/ttyUSB5',
                        'proxy': 'localhost.localdomain',
                        'proxy_required': False},
              'host': '10.44.3.61',
              'port': None,
              'speed': 115200}}
Matching resource 'console' (adi-lf-test/MUN-01-SC598_EZKIT-01/NetworkSerialPort/console):
  {'acquired': None,
   'avail': True,
   'cls': 'NetworkSerialPort',
   'params': {'extra': {'path': '/dev/ttyUSB1',
                        'proxy': 'localhost.localdomain',
                        'proxy_required': False},
              'host': '10.44.3.61',
              'port': None,
              'speed': 115200}}
Matching resource 'onboard-debug-agent' (adi-lf-test/MUN-01-SC598_EZKIT-01/NetworkUSBDebugger/onboard-debug-agent):
  {'acquired': None,
   'avail': True,
   'cls': 'NetworkUSBDebugger',
   'params': {'busnum': 1,
              'devnum': 11,
              'extra': {'proxy': 'localhost.localdomain',
                        'proxy_required': False},
              'host': '10.44.3.61',
              'model_id': 9476,
              'path': '1-12.2.1',
              'vendor_id': 1611}}
Matching resource 'power' (adi-lf-test/MUN-01-SC598_EZKIT-01/NetworkPowerPort/power):
  {'acquired': None,
   'avail': True,
   'cls': 'NetworkPowerPort',
   'params': {'extra': {'proxy': 'localhost.localdomain',
                        'proxy_required': False},
              'host': 'http://admin:admin@10.44.3.200',
              'index': 7,
              'model': 'tinycontrol_tcpdu'}}
"""

SHOW_OUTPUT_ACQUIRED = """\
Place 'MUN-01-SC598_EZKIT-02':
  matches:
    adi-lf-test/MUN-01-SC598_EZKIT-02/*
  acquired: runner/HYB-bZmliY2RpDf
  acquired resources:
    adi-lf-test/MUN-01-SC598_EZKIT-02/NetworkSerialPort/console
    adi-lf-test/MUN-01-SC598_EZKIT-02/NetworkUSBDebugger/onboard-debug-agent
  created: 2026-05-12 10:31:43.961482
  changed: 2026-06-23 13:15:38.509595
Acquired resource 'console' (adi-lf-test/MUN-01-SC598_EZKIT-02/NetworkSerialPort/console):
  {'acquired': 'MUN-01-SC598_EZKIT-02',
   'avail': True,
   'cls': 'NetworkSerialPort',
   'params': {'extra': {'path': '/dev/ttyUSB0',
                        'proxy': 'localhost.localdomain',
                        'proxy_required': False},
              'host': '10.44.3.61',
              'port': 47175,
              'speed': 115200}}
Acquired resource 'onboard-debug-agent' (adi-lf-test/MUN-01-SC598_EZKIT-02/NetworkUSBDebugger/onboard-debug-agent):
  {'acquired': 'MUN-01-SC598_EZKIT-02',
   'avail': True,
   'cls': 'NetworkUSBDebugger',
   'params': {'busnum': 1,
              'devnum': 16,
              'extra': {'proxy': 'localhost.localdomain',
                        'proxy_required': False},
              'host': '10.44.3.61',
              'model_id': 9476,
              'path': '1-12.1.4',
              'vendor_id': 1611}}
Acquired resource 'power' (adi-lf-test/MUN-01-SC598_EZKIT-02/NetworkPowerPort/power):
  {'acquired': 'MUN-01-SC598_EZKIT-02',
   'avail': True,
   'cls': 'NetworkPowerPort',
   'params': {'extra': {'proxy': 'localhost.localdomain',
                        'proxy_required': False},
              'host': 'http://admin:admin@10.44.3.200',
              'index': 6,
              'model': 'tinycontrol_tcpdu'}}
"""


def _fake_run(show_output):
    """Return a mock for subprocess.run that returns *show_output* for 'show'."""

    def fake_run(cmd, **kwargs):
        assert "show" in cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=show_output, stderr="")

    return fake_run


def _make_client(show_output, tmp_path):
    """Create a LabgridClient with mocked subprocess and SSH config."""
    ssh_config_path = tmp_path / "ssh_config"

    with (
        patch("hw_tests.labgrid.labgrid_client.subprocess.run", _fake_run(show_output)),
        patch("hw_tests.labgrid.labgrid_client.SSHConfig", lambda: SSHConfig(path=ssh_config_path)),
    ):
        client = LabgridClient({
            "labgrid_place": "MUN-01-SC598_EZKIT-01"
        })

    return client, ssh_config_path


def test_resolve_place_hosts_configures_ssh(tmp_path):
    _, ssh_config_path = _make_client(SHOW_OUTPUT, tmp_path)

    text = ssh_config_path.read_text()
    assert "Host 10.44.3.61" in text
    assert "User ci" in text
    assert "StrictHostKeyChecking accept-new" in text
    if GitHub.in_actions():
        assert "IdentityFile ~/.ssh/id_ecdsa" in text
        assert "CertificateFile ~/.ssh/id_ecdsa-cert.pub" in text
        assert "IdentitiesOnly yes" in text
    else:
        assert "IdentityFile" not in text
        assert "CertificateFile" not in text


def test_resolve_place_hosts_skips_url_hosts(tmp_path):
    _, ssh_config_path = _make_client(SHOW_OUTPUT, tmp_path)

    text = ssh_config_path.read_text()
    assert "10.44.3.200" not in text


def test_resolve_place_hosts_acquired(tmp_path):
    """'Acquired resource' lines are parsed the same as 'Matching resource'."""
    _, ssh_config_path = _make_client(SHOW_OUTPUT_ACQUIRED, tmp_path)

    text = ssh_config_path.read_text()
    assert "Host 10.44.3.61" in text


def test_resolve_place_hosts_show_failure(tmp_path):
    """A failed 'show' command must not raise and must not write SSH config."""
    ssh_config_path = tmp_path / "ssh_config"

    def fail_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="some error")

    with (
        patch("hw_tests.labgrid.labgrid_client.subprocess.run", fail_run),
        patch("hw_tests.labgrid.labgrid_client.SSHConfig", lambda: SSHConfig(path=ssh_config_path)),
    ):
        LabgridClient({
            "labgrid_place": "MUN-01-SC598_EZKIT-01"
        })

    assert not ssh_config_path.exists()


def test_no_place_skips_resolve(tmp_path):
    """Without a place, no coordinator query is made."""
    with patch("hw_tests.labgrid.labgrid_client.subprocess.run") as mock_run:
        LabgridClient({})

    mock_run.assert_not_called()
