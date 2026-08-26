import tomllib
from unittest.mock import MagicMock

import pytest

from hw_tests.images import TESTS_DIR, Images

ADSP_DESCRIPTOR = TESTS_DIR / "adsp" / "artifacts.toml"


def test_descriptor_parses_and_has_expected_roles():
    with ADSP_DESCRIPTOR.open("rb") as f:
        data = tomllib.load(f)
    assert set(data) == {"br2", "uboot", "yocto"}
    assert set(data["br2"]) >= {"spl", "uboot", "kernel", "dtb", "emmc"}
    assert set(data["uboot"]) == {"spl", "uboot"}
    assert set(data["yocto"]) == {"spl", "uboot"}
    for flavor in data.values():
        for role in flavor.values():
            assert set(role) == {"artifact", "file"}


def _gh(repo):
    gh = MagicMock()
    gh.owner_repository = repo
    return gh


def test_descriptor_resolved_from_test_category():
    # The descriptor is looked up at tests/<category>/artifacts.toml, where
    # category is the first segment of the test name — so non-adsp categories
    # get their own descriptor, not a hardcoded adsp one.
    imgs = Images({"name": "adsp/u-boot"}, _gh("analogdevicesinc/u-boot"))
    assert imgs._descriptor_path() == TESTS_DIR / "adsp" / "artifacts.toml"
    imgs = Images({"name": "linux/boot"}, _gh("analogdevicesinc/linux"))
    assert imgs._descriptor_path() == TESTS_DIR / "linux" / "artifacts.toml"


def test_flavor_from_repo():
    cases = {
        "analogdevicesinc/br2-external": "br2",
        "analogdevicesinc/u-boot": "uboot",
        "analogdevicesinc/lnxdsp-adi-meta": "yocto",
    }
    for repo, flavor in cases.items():
        assert Images({}, _gh(repo)).flavor == flavor


def test_flavor_context_override_wins():
    imgs = Images({"flavor": "yocto"}, _gh("analogdevicesinc/br2-external"))
    assert imgs.flavor == "yocto"


def test_flavor_unknown_repo_skips():
    imgs = Images({}, _gh("analogdevicesinc/some-other-repo"))
    with pytest.raises(pytest.skip.Exception):
        _ = imgs.flavor


BR2_RUN = ["adi_sc598_ezkit_defconfig", "adi_sc598_ezkit_defconfig-bootstrap",
           "adi_sc598_ezkit_defconfig-debug", "adi_sc589_ezkit_defconfig"]


def _gh_run(repo, artifact_names, download_dir):
    gh = MagicMock()
    gh.owner_repository = repo
    gh.list_artifacts.return_value = [{"name": n} for n in artifact_names]
    gh.download.return_value = download_dir
    return gh


def _make_files(tmp_path, names):
    for n in names:
        (tmp_path / n).write_text("x")
    return tmp_path


def test_get_br2_selects_bootstrap_and_file(tmp_path):
    bootstrap = tmp_path / "bootstrap"
    bootstrap.mkdir()
    _make_files(bootstrap, ["u-boot-spl", "u-boot", "Image", "sc598-som-ezkit.dtb"])
    d = tmp_path
    gh = _gh_run("analogdevicesinc/br2-external", BR2_RUN, d)
    imgs = Images({"name": "adsp/test", "needs": ["sc598", "ezkit"]}, gh)
    assert imgs.get("spl").name == "u-boot-spl"
    assert imgs.get("uboot").name == "u-boot"
    assert imgs.get("kernel").name == "Image"
    assert imgs.get("dtb").name == "sc598-som-ezkit.dtb"
    assert imgs.artifact_path("spl") == "bootstrap/u-boot-spl"
    assert imgs.artifact_path("uboot") == "bootstrap/u-boot"
    assert imgs.artifact_path("kernel") == "bootstrap/Image"
    assert imgs.artifact_path("dtb") == "bootstrap/sc598-som-ezkit.dtb"
    # Pick the complete board bundle, not its standalone flavor artifacts.
    gh.download.assert_called_with("adi_sc598_ezkit_defconfig")
    assert gh.download.call_count == 1


def test_get_br2_dtb_narrowed_by_needs(tmp_path):
    bootstrap = tmp_path / "bootstrap"
    bootstrap.mkdir()
    _make_files(bootstrap, [
        "sc598-htol.dtb",
        "sc598-som-ezkit.dtb",
        "sc598-som-ezkit-sd.dtb",
        "sc598-som-ezlite.dtb",
    ])
    d = tmp_path
    gh = _gh_run("analogdevicesinc/br2-external", BR2_RUN, d)
    imgs = Images({"name": "adsp/test", "needs": ["sc598", "ezkit"]}, gh)
    assert imgs.get("dtb").name == "sc598-som-ezkit.dtb"


def test_get_br2_emmc_selects_debug_file_from_bundle(tmp_path):
    debug = tmp_path / "debug"
    debug.mkdir()
    _make_files(debug, ["emmc.img.gz"])
    d = tmp_path
    gh = _gh_run("analogdevicesinc/br2-external", BR2_RUN, d)
    imgs = Images({"name": "adsp/test", "needs": ["sc598", "ezkit"]}, gh)
    assert imgs.get("emmc").name == "emmc.img.gz"
    assert imgs.get("emmc").parent == debug
    assert imgs.artifact_path("emmc") == "debug/emmc.img.gz"
    gh.download.assert_called_with("adi_sc598_ezkit_defconfig")


def test_needs_reject_ezlite_and_wrong_soc(tmp_path):
    d = _make_files(tmp_path, ["u-boot-spl", "u-boot"])
    names = ["sc598-som-ezlite-spl_defconfig", "sc589-ezkit_defconfig",
             "sc598-som-ezkit-spl_defconfig", "sc598-htol-spl_defconfig"]
    gh = _gh_run("analogdevicesinc/u-boot", names, d)
    imgs = Images({"name": "adsp/test", "needs": ["sc598", "ezkit"]}, gh)
    imgs.get("spl")
    gh.download.assert_called_with("sc598-som-ezkit-spl_defconfig")


def test_yocto_elf_glob(tmp_path):
    d = _make_files(tmp_path, ["u-boot-spl-sc598-som-ezkit.elf",
                               "u-boot-proper-sc598-som-ezkit.elf", "u-boot.ldr"])
    gh = _gh_run("analogdevicesinc/lnxdsp-adi-meta",
                 ["adsp-sc598-som-ezkit-adsp-sc5xx-minimal"], d)
    imgs = Images({"name": "adsp/test", "needs": ["sc598", "ezkit"]}, gh)
    assert imgs.get("uboot").name == "u-boot-proper-sc598-som-ezkit.elf"


def test_sidecar_sbom_artifact_ignored(tmp_path):
    # Real yocto runs publish a '<image>.sbom' metadata artifact next to the
    # image; both match needs + '*', so it must be dropped to stay unambiguous.
    d = _make_files(tmp_path, ["u-boot-proper-sc598-som-ezkit.elf"])
    names = ["adsp-sc598-som-ezkit-adsp-sc5xx-minimal.sbom",
             "adsp-sc598-som-ezkit-adsp-sc5xx-minimal"]
    gh = _gh_run("analogdevicesinc/lnxdsp-adi-meta", names, d)
    imgs = Images({"name": "adsp/test", "needs": ["sc598", "ezkit"]}, gh)
    assert imgs.get("uboot").name == "u-boot-proper-sc598-som-ezkit.elf"
    gh.download.assert_called_with("adsp-sc598-som-ezkit-adsp-sc5xx-minimal")


def test_offline_no_listing_uses_download_fallback(tmp_path):
    # Offline / no GITHUB_TOKEN: list_artifacts() is empty. Images must still
    # resolve by handing off to GitHub.download (its local '_artifacts/'
    # fallback) and globbing the role's file there — not assert.
    d = _make_files(tmp_path, ["u-boot-spl", "u-boot"])
    gh = MagicMock()
    gh.owner_repository = "analogdevicesinc/u-boot"
    gh.list_artifacts.return_value = []
    gh.download.return_value = d
    imgs = Images({"name": "adsp/test", "needs": ["sc598", "ezkit"]}, gh)
    assert imgs.get("spl").name == "u-boot-spl"
    assert imgs.get("uboot").name == "u-boot"
    # both roles share the '*' artifact glob → one download
    assert gh.download.call_count == 1


def test_nested_duplicate_file_ignored(tmp_path):
    # Real yocto artifacts carry nested duplicates (programming-images/); file
    # resolution is top-level only, so a nested same-name file must not make
    # the match ambiguous.
    (tmp_path / "u-boot-proper-sc598-som-ezkit.elf").write_text("x")
    nested = tmp_path / "programming-images" / "adsp-sc5xx-minimal"
    nested.mkdir(parents=True)
    (nested / "u-boot-proper-sc598-som-ezkit.elf").write_text("x")
    gh = _gh_run("analogdevicesinc/lnxdsp-adi-meta",
                 ["adsp-sc598-som-ezkit-adsp-sc5xx-minimal"], tmp_path)
    imgs = Images({"name": "adsp/test", "needs": ["sc598", "ezkit"]}, gh)
    resolved = imgs.get("uboot")
    assert resolved.name == "u-boot-proper-sc598-som-ezkit.elf"
    assert resolved.parent == tmp_path  # top-level, not the nested copy


def test_role_not_available_skips(tmp_path):
    gh = _gh_run("analogdevicesinc/u-boot", ["sc598-som-ezkit-spl_defconfig"], tmp_path)
    imgs = Images({"name": "adsp/test", "needs": ["sc598", "ezkit"]}, gh)
    with pytest.raises(pytest.skip.Exception):
        imgs.get("kernel")


def test_shared_artifact_downloads_once(tmp_path):
    d = _make_files(tmp_path, ["u-boot-spl", "u-boot"])
    gh = _gh_run("analogdevicesinc/u-boot", ["sc598-som-ezkit-spl_defconfig"], d)
    imgs = Images({"name": "adsp/test", "needs": ["sc598", "ezkit"]}, gh)
    imgs.get("spl")
    imgs.get("uboot")
    assert gh.download.call_count == 1
