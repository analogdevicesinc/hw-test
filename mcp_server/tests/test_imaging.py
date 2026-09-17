"""Tests for artifact-first / build-fallback image resolution."""

import pytest

from mcp_server.orchestration import imaging


def test_uses_artifact_when_resolver_hits():
    def resolver(repo, sha, role):
        return "/artifacts/uboot.bin"

    def builder(repo, sha, role):
        raise AssertionError("builder must not be called on artifact hit")

    img = imaging.resolve_image_for_ref("u-boot", "sha1", "u-boot",
                                        resolver=resolver, builder=builder)
    assert img.source == "artifact"
    assert img.location == "/artifacts/uboot.bin"
    assert img.sha == "sha1"


def test_builds_when_artifact_misses():
    def resolver(repo, sha, role):
        return None

    def builder(repo, sha, role):
        return "/build/uboot.bin", "make: done"

    img = imaging.resolve_image_for_ref("u-boot", "sha2", "u-boot",
                                        resolver=resolver, builder=builder)
    assert img.source == "build"
    assert img.location == "/build/uboot.bin"
    assert img.build_log_tail == "make: done"


def test_build_failure_raises_with_log():
    def resolver(repo, sha, role):
        return None

    def builder(repo, sha, role):
        raise imaging.BuildError("build failed", log_tail="cc1: error")

    with pytest.raises(imaging.BuildError) as exc:
        imaging.resolve_image_for_ref("u-boot", "sha3", "u-boot",
                                      resolver=resolver, builder=builder)
    assert exc.value.log_tail == "cc1: error"
