import tomllib
from pathlib import Path

DESCRIPTOR = Path("images/artifacts.toml")


def test_descriptor_parses_and_has_expected_roles():
    with DESCRIPTOR.open("rb") as f:
        data = tomllib.load(f)
    assert set(data) == {"br2", "uboot", "yocto"}
    assert set(data["br2"]) >= {"spl", "uboot", "kernel", "dtb"}
    assert set(data["uboot"]) == {"spl", "uboot"}
    assert set(data["yocto"]) == {"spl", "uboot"}
    for flavor in data.values():
        for role in flavor.values():
            assert set(role) == {"artifact", "file"}
