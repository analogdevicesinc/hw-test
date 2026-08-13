import tomllib
from unittest.mock import MagicMock

import pytest

from hw_tests.images import TESTS_DIR, Images

ADSP_DESCRIPTOR = TESTS_DIR / "adsp" / "artifacts.toml"


def test_descriptor_parses_and_has_expected_roles():
    with ADSP_DESCRIPTOR.open("rb") as f:
        data = tomllib.load(f)
    flavors = {k: v for k, v in data.items() if k != "sources"}
    assert set(flavors) == {"br2", "uboot", "yocto", "linux"}
    assert set(flavors["br2"]) >= {"spl", "uboot", "kernel", "dtb", "emmc"}
    assert set(flavors["uboot"]) == {"spl", "uboot"}
    assert set(flavors["yocto"]) == {"spl", "uboot"}
    assert set(flavors["linux"]) >= {"kernel", "dtb", "spl", "uboot", "rootfs"}
    for flavor in flavors.values():
        for role in flavor.values():
            # 'source' is optional: it pins a role to another repo's artifact.
            assert {"artifact", "file"} <= set(role) <= {"artifact", "file", "source"}

    # Release-backed sources live at the top level, shared across the category.
    assert set(data["sources"]) == {"br2"}
    for src in data["sources"].values():
        assert src["backend"] == "release"
        assert src["repository"]
        assert src["tag"]


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


def test_linux_kernel_resolves_nested_boot_file(tmp_path):
    # The linux run ships the kernel and dtbs under boot/; the file glob is a
    # path (boot/Image), so nested layouts resolve where a bare pattern would
    # only see the top level.
    (tmp_path / "boot").mkdir()
    (tmp_path / "boot" / "Image").write_text("x")
    gh = _gh_run("analogdevicesinc/linux",
                 ["sc598-som-ezkit_defconfig-gcc-arm64",
                  "sc598-som-ezkit_defconfig-gcc-arm64-headers"], tmp_path)
    imgs = Images({"name": "adsp/test", "needs": ["sc598", "ezkit"]}, gh)
    resolved = imgs.get("kernel")
    assert resolved.name == "Image"
    assert resolved.parent == tmp_path / "boot"
    # '-headers' sibling is anchored out by the '*_defconfig-gcc-arm64' glob
    gh.download.assert_called_with("sc598-som-ezkit_defconfig-gcc-arm64")


def test_linux_dtb_from_dtb_gcc_narrowed_by_needs(tmp_path):
    # The dtb comes from the same-run 'dtb-gcc' artifact (compile-devicetrees),
    # whose layout preserves the full source path. The descriptor glob is
    # board-agnostic 'dtb/arch/*/boot/dts/adi/*.dtb', narrowed to sc598-som-ezkit
    # by needs tokens.
    dtb = tmp_path / "dtb" / "arch" / "arm64" / "boot" / "dts" / "adi"
    dtb.mkdir(parents=True)
    for n in ["sc598-som-ezkit.dtb", "sc598-som-ezlite.dtb",
              "sc846-som-ezkit.dtb"]:
        (dtb / n).write_text("x")
    gh = _gh_run("analogdevicesinc/linux",
                 ["dtb-gcc", "sc598-som-ezkit_defconfig-gcc-arm64"], tmp_path)
    imgs = Images({"name": "adsp/test", "needs": ["sc598", "ezkit"]}, gh)
    resolved = imgs.get("dtb")
    assert resolved.name == "sc598-som-ezkit.dtb"
    gh.download.assert_called_with("dtb-gcc")


def test_linux_dtb_prefers_base_board_over_variant(tmp_path):
    # A base board and its variant both carry the needs tokens: dtb-gcc ships
    # sc598-som-ezkit.dtb AND sc598-som-ezkit-sd.dtb. needs=["sc598","ezkit"]
    # matches both, so file narrowing must prefer the base (shortest stem that
    # prefixes the rest) — the plain RAM-boot dtb, not the SD variant.
    dtb = tmp_path / "dtb" / "arch" / "arm64" / "boot" / "dts" / "adi"
    dtb.mkdir(parents=True)
    for n in ["sc598-som-ezkit.dtb", "sc598-som-ezkit-sd.dtb",
              "sc598-som-ezlite.dtb"]:
        (dtb / n).write_text("x")
    gh = _gh_run("analogdevicesinc/linux", ["dtb-gcc"], tmp_path)
    imgs = Images({"name": "adsp/test", "needs": ["sc598", "ezkit"]}, gh)
    assert imgs.get("dtb").name == "sc598-som-ezkit.dtb"


def test_linux_dtb_variant_selected_by_extra_need(tmp_path):
    # Adding the distinguishing token ('sd') to needs selects the variant
    # instead of the base — the base no longer carries every token.
    dtb = tmp_path / "dtb" / "arch" / "arm64" / "boot" / "dts" / "adi"
    dtb.mkdir(parents=True)
    for n in ["sc598-som-ezkit.dtb", "sc598-som-ezkit-sd.dtb"]:
        (dtb / n).write_text("x")
    gh = _gh_run("analogdevicesinc/linux", ["dtb-gcc"], tmp_path)
    imgs = Images({"name": "adsp/test", "needs": ["sc598", "ezkit", "sd"]}, gh)
    assert imgs.get("dtb").name == "sc598-som-ezkit-sd.dtb"


def test_release_role_downloads_asset_and_finds_nested_file(tmp_path):
    # br2 rootfs: pick the *-initramfs-* asset, extract, rglob the nested file.
    extracted = tmp_path / "buildroot" / "output" / "images"
    extracted.mkdir(parents=True)
    (extracted / "rootfs.cpio.uboot").write_bytes(b"uramdisk")
    (extracted / "rootfs.cpio").write_bytes(b"bare")

    gh = _gh("analogdevicesinc/linux")
    gh.list_release_assets.return_value = [
        {"name": "images-bootstrap-adi_sc598_ezkit_defconfig-2026.02-0.2.0.tar.xz"},
        {"name": "images-initramfs-adi_sc598_ezkit_defconfig-2026.02-0.2.0.tar.xz"},
        {"name": "images-debug-adi_sc598_ezkit_defconfig-2026.02-0.2.0.tar.xz"},
    ]
    gh.download_release_asset.return_value = tmp_path

    imgs = Images({"name": "adsp/initramfs-boot", "flavor": "linux",
                   "needs": ["sc598", "ezkit"]}, gh)

    got = imgs.get("rootfs")
    assert got.name == "rootfs.cpio.uboot"
    gh.list_release_assets.assert_called_with("2026.02-0.2.0", "analogdevicesinc/br2-external")
    gh.download_release_asset.assert_called_with(
        "images-initramfs-adi_sc598_ezkit_defconfig-2026.02-0.2.0.tar.xz",
        "2026.02-0.2.0",
        "analogdevicesinc/br2-external",
    )


def test_release_spl_uboot_come_from_bootstrap_asset(tmp_path):
    # spl/uboot use artifact='*-bootstrap-*', so among the release's tarballs
    # they select the bootstrap image (not initramfs/debug) and rglob the flat
    # u-boot-spl / u-boot out of buildroot/output/images/ — without matching the
    # u-boot.ldr / u-boot.gdb / u-boot-spl.ldr siblings.
    extracted = tmp_path / "buildroot" / "output" / "images"
    extracted.mkdir(parents=True)
    for n in ["u-boot-spl", "u-boot-spl.ldr", "u-boot", "u-boot.ldr",
              "u-boot.gdb", "Image", "rootfs.cpio"]:
        (extracted / n).write_bytes(b"x")

    gh = _gh("analogdevicesinc/linux")
    gh.list_release_assets.return_value = [
        {"name": "images-bootstrap-adi_sc598_ezkit_defconfig-2026.02-0.2.0.tar.xz"},
        {"name": "images-initramfs-adi_sc598_ezkit_defconfig-2026.02-0.2.0.tar.xz"},
        {"name": "images-debug-adi_sc598_ezkit_defconfig-2026.02-0.2.0.tar.xz"},
    ]
    gh.download_release_asset.return_value = tmp_path

    imgs = Images({"name": "adsp/initramfs-boot", "flavor": "linux",
                   "needs": ["sc598", "ezkit"]}, gh)

    assert imgs.get("spl").name == "u-boot-spl"
    assert imgs.get("uboot").name == "u-boot"
    gh.download_release_asset.assert_called_with(
        "images-bootstrap-adi_sc598_ezkit_defconfig-2026.02-0.2.0.tar.xz",
        "2026.02-0.2.0",
        "analogdevicesinc/br2-external",
    )


def test_release_role_missing_asset_asserts(tmp_path):
    gh = _gh("analogdevicesinc/linux")
    gh.list_release_assets.return_value = [
        {"name": "images-bootstrap-x.tar.xz"},
        {"name": "images-debug-x.tar.xz"},
    ]
    imgs = Images({"name": "adsp/initramfs-boot", "flavor": "linux",
                   "needs": ["sc598", "ezkit"]}, gh)
    with pytest.raises(AssertionError):
        imgs.get("rootfs")


def test_nonrelease_role_still_uses_github_run(tmp_path):
    # kernel has no 'source' -> must not touch the release methods.
    d = tmp_path / "boot"
    d.mkdir()
    (d / "Image").write_bytes(b"kernel")
    gh = _gh("analogdevicesinc/linux")
    gh.list_artifacts.return_value = [{"name": "adi_sc598_ezkit_defconfig-gcc-arm64"}]
    gh.download.return_value = tmp_path

    imgs = Images({"name": "adsp/initramfs-boot", "flavor": "linux",
                   "needs": ["sc598", "ezkit"]}, gh)

    got = imgs.get("kernel")
    assert got.name == "Image"
    gh.list_release_assets.assert_not_called()
    gh.download_release_asset.assert_not_called()


def test_multi_glob_match_narrowed_to_board_by_needs():
    # A board-agnostic glob (*-bootstrap) matches one artifact PER BOARD in the
    # run. Needs tokens must narrow to the board under test — the wrong-board
    # artifact must NOT win.
    imgs = Images({"name": "adsp/test", "needs": ["sc598", "ezkit"]},
                  _gh("analogdevicesinc/br2-external"))
    name, reason = imgs._match_artifact(
        [{"name": "adi_sc598_ezkit_defconfig-bootstrap"},
         {"name": "adi_sc589_ezkit_defconfig-bootstrap"}],
        "*-bootstrap")
    assert name == "adi_sc598_ezkit_defconfig-bootstrap", reason


def test_glob_specific_match_ignores_coexisting_tokened_artifact():
    # dtb-gcc must resolve even though a token-bearing artifact
    # (sc598-som-ezkit_defconfig-gcc-arm64) shares the run. Glob-first means the
    # specific 'dtb-gcc' glob picks it directly.
    imgs = Images({"name": "adsp/test", "needs": ["sc598", "ezkit"]},
                  _gh("analogdevicesinc/linux"))
    name, reason = imgs._match_artifact(
        [{"name": "dtb-gcc"},
         {"name": "sc598-som-ezkit_defconfig-gcc-arm64"}],
        "dtb-gcc")
    assert name == "dtb-gcc", reason
