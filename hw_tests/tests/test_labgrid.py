from pathlib import Path

import pytest

from hw_tests.labgrid import exporter_http_server


class FakeSSH:
    def __init__(self):
        self.commands = []
        self.uploads = []

    def run_check(self, command):
        self.commands.append(command)
        if command.startswith("mktemp -d"):
            return ["/dev/shm/hw-test-http.test\n"]
        if "sock.getsockname" in command:
            return ["12345\n"]
        return [""]

    def put(self, source, destination):
        self.uploads.append((source, destination))

    def run(self, command):
        self.commands.append(command)


def test_exporter_http_server_uploads_files_at_requested_paths(tmp_path):
    kernel = tmp_path / "Image"
    emmc = tmp_path / "emmc.img.gz"
    ssh = FakeSSH()

    with exporter_http_server(
        ssh,
        {kernel.name: kernel, "debug/emmc.img.gz": emmc},
    ) as port:
        assert port == "12345"

    assert ssh.uploads == [
        (str(kernel), "/dev/shm/hw-test-http.test/Image"),
        (str(emmc), "/dev/shm/hw-test-http.test/debug/emmc.img.gz"),
    ]
    assert "mkdir -p /dev/shm/hw-test-http.test/debug" in ssh.commands
    assert not any("ln -s" in command for command in ssh.commands)


@pytest.mark.parametrize("remote_path", ["", "/outside", "../outside", "a/../../outside"])
def test_exporter_http_server_rejects_paths_outside_root(tmp_path, remote_path):
    ssh = FakeSSH()

    with pytest.raises(
        ValueError, match="below the server root"
    ), exporter_http_server(ssh, {remote_path: Path("emmc.img.gz")}):
        pass


def test_exporter_http_server_rejects_duplicate_normalized_paths(tmp_path):
    ssh = FakeSSH()
    image = tmp_path / "emmc.img.gz"

    with pytest.raises(
        ValueError, match="duplicate HTTP path"
    ), exporter_http_server(
        ssh,
        {"debug/emmc.img.gz": image, "debug/./emmc.img.gz": image},
    ):
        pass
