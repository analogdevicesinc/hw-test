"""Shared pytest fixtures for the mcp_server test suite."""

import pytest


@pytest.fixture
def anyio_backend():
    # The MCP server's async surface is awaited via anyio; pin to asyncio so
    # tests don't require trio installed.
    return "asyncio"
