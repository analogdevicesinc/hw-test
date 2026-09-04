"""Tests for the reviewed classification cache (knowledge.py)."""

from mcp_server import knowledge
from mcp_server.models import Subsystem


def test_lookup_matches_path_glob(tmp_path):
    cache = tmp_path / "cache.toml"
    cache.write_text(
        'version = "2026-09-03"\n\n'
        '[[entry]]\n'
        'id = "uboot-spi"\n'
        'repo = "u-boot"\n'
        'path_glob = "drivers/spi/*"\n'
        'subsystem = "spi_qspi_xspi"\n'
        'doc = { repo = "documentation", query = "sc598 ospi boot" }\n'
    )
    store = knowledge.Knowledge(cache)
    hit = store.lookup(repo="u-boot", path="drivers/spi/adi_spi3.c")
    assert hit is not None
    assert hit.subsystem is Subsystem.SPI_QSPI_XSPI
    assert hit.matched_id == "uboot-spi"
    assert hit.doc_ref.query == "sc598 ospi boot"


def test_lookup_repo_must_match(tmp_path):
    cache = tmp_path / "cache.toml"
    cache.write_text(
        'version = "1"\n\n[[entry]]\nid = "x"\nrepo = "linux"\n'
        'path_glob = "drivers/spi/*"\nsubsystem = "spi_qspi_xspi"\n'
    )
    store = knowledge.Knowledge(cache)
    assert store.lookup(repo="u-boot", path="drivers/spi/x.c") is None


def test_lookup_returns_none_when_no_glob_matches(tmp_path):
    cache = tmp_path / "cache.toml"
    cache.write_text(
        'version = "1"\n\n[[entry]]\nid = "x"\nrepo = "u-boot"\n'
        'path_glob = "drivers/net/*"\nsubsystem = "net_phy"\n'
    )
    store = knowledge.Knowledge(cache)
    assert store.lookup(repo="u-boot", path="drivers/spi/x.c") is None


def test_missing_cache_file_is_empty_not_error(tmp_path):
    store = knowledge.Knowledge(tmp_path / "does-not-exist.toml")
    assert store.lookup(repo="u-boot", path="anything") is None
