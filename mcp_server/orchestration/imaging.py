"""Resolve an image for one ref: artifact-first, build fallback.

The resolver (artifact lookup via hw_tests/images.py + github.py) and the
builder (build-from-source at a sha) are injected so this is unit-testable with
no network and no toolchain. On artifact miss we build; if the build fails the
BuildError carries the log tail so the caller can surface it as evidence.
"""

from __future__ import annotations

from mcp_server.models import ImageRef


class BuildError(RuntimeError):
    def __init__(self, message, log_tail=""):
        super().__init__(message)
        self.log_tail = log_tail


def resolve_image_for_ref(repo, sha, role, *, resolver, builder):
    location = resolver(repo, sha, role)
    if location is not None:
        return ImageRef(repo=repo, sha=sha, role=role, source="artifact",
                        location=location)
    built_location, log_tail = builder(repo, sha, role)
    return ImageRef(repo=repo, sha=sha, role=role, source="build",
                    location=built_location, build_log_tail=log_tail)
