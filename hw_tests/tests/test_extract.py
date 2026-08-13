import lzma
import tarfile
from pathlib import Path

from hw_tests.github import _extract_if_archive


def _make_tar_xz(dir_path: Path, arcname: str, payload: bytes) -> Path:
    inner = dir_path / "payload.bin"
    inner.write_bytes(payload)
    archive = dir_path / "bundle.tar.xz"
    with lzma.open(archive, "wb") as xz, tarfile.open(fileobj=xz, mode="w") as tar:
        tar.add(inner, arcname=arcname)
    inner.unlink()
    return archive


def test_extract_tar_xz_expands_and_removes_archive(tmp_path):
    archive = _make_tar_xz(tmp_path, "buildroot/output/images/rootfs.cpio.uboot", b"data")
    _extract_if_archive(archive)
    assert not archive.exists()
    extracted = tmp_path / "buildroot" / "output" / "images" / "rootfs.cpio.uboot"
    assert extracted.is_file()
    assert extracted.read_bytes() == b"data"


def test_extract_leaves_plain_file_untouched(tmp_path):
    plain = tmp_path / "u-boot-spl"
    plain.write_bytes(b"ELF...")
    _extract_if_archive(plain)
    assert plain.is_file()
    assert plain.read_bytes() == b"ELF..."
