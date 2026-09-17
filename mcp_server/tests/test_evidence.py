"""Tests for planning.get_classification_evidence."""

from mcp_server import knowledge, planning
from mcp_server.models import ChangeSet, FileChange, SourceRef

# Fixture test metas mimicking load_test_metas() output shape.
METAS = [
    {
        "_uid": "adsp/u-boot",
        "needs": ["sc598", "ezkit"],
        "repository": [{"name": "u-boot",
                        "path": "board/adi/sc598*\nconfigs/sc598*\n"}],
        "capabilities": {"provides": ["uboot", "openocd", "spi_boot"]},
    },
    {
        "_uid": "demo/linux-iio-dac",
        "needs": ["sc598"],
        "repository": [{"name": "linux", "path": "drivers/iio/dac/*\n"}],
        "capabilities": {"provides": ["linux"]},
    },
]


def _changeset(repo, paths):
    return ChangeSet(
        source=SourceRef(repo=repo, ref_or_sha="h", kind="pr"),
        repo=repo, head_sha="h", base_ref="b", merge_base_sha="mb",
        files=[FileChange(path=p, status="modified", hunk_snippets=[f"+{p}"])
               for p in paths],
        commits=["c1"], human_summary="", pr_number=1,
    )


def test_evidence_matches_metas_by_repo_and_path(tmp_path):
    cs = _changeset("analogdevicesinc/u-boot", ["board/adi/sc598/x.c"])
    store = knowledge.Knowledge(tmp_path / "empty.toml")
    ev = planning.get_classification_evidence(cs, metas=METAS, knowledge=store)

    assert ev.repo == "analogdevicesinc/u-boot"
    assert ev.matched_metas == ["adsp/u-boot"]
    assert [f.path for f in ev.files] == ["board/adi/sc598/x.c"]


def test_evidence_offers_all_subsystem_choices(tmp_path):
    cs = _changeset("u-boot", ["board/adi/sc598/x.c"])
    store = knowledge.Knowledge(tmp_path / "empty.toml")
    ev = planning.get_classification_evidence(cs, metas=METAS, knowledge=store)
    assert "spi_qspi_xspi" in ev.subsystem_choices
    assert "board_dt" in ev.subsystem_choices
    assert "other" in ev.subsystem_choices


def test_evidence_seeds_doc_refs_from_cache(tmp_path):
    cache = tmp_path / "cache.toml"
    cache.write_text(
        'version = "1"\n\n[[entry]]\nid = "spi"\nrepo = "u-boot"\n'
        'path_glob = "drivers/spi/*"\nsubsystem = "spi_qspi_xspi"\n'
        'doc = { repo = "documentation", query = "sc598 ospi" }\n'
    )
    store = knowledge.Knowledge(cache)
    cs = _changeset("analogdevicesinc/u-boot", ["drivers/spi/adi_spi3.c"])
    ev = planning.get_classification_evidence(cs, metas=METAS, knowledge=store)
    assert any(d.query == "sc598 ospi" for d in ev.seed_doc_refs)


def test_evidence_no_meta_match_is_empty_list(tmp_path):
    cs = _changeset("u-boot", ["drivers/usb/host/xhci.c"])
    store = knowledge.Knowledge(tmp_path / "empty.toml")
    ev = planning.get_classification_evidence(cs, metas=METAS, knowledge=store)
    assert ev.matched_metas == []


def test_evidence_normalizes_owner_repo_to_basename(tmp_path):
    # config.toml repository names are bare ("u-boot"); ChangeSet may carry
    # "owner/u-boot". Matching must normalize.
    cs = _changeset("analogdevicesinc/u-boot", ["configs/sc598_defconfig"])
    store = knowledge.Knowledge(tmp_path / "empty.toml")
    ev = planning.get_classification_evidence(cs, metas=METAS, knowledge=store)
    assert ev.matched_metas == ["adsp/u-boot"]
