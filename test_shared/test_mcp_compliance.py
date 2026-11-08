"""Universal MCP compliance tests — apply to ANY server in config.yaml."""

from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.protocol

TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


async def test_tools_have_names_descriptions_and_schemas(mcp_client):
    tools = await mcp_client.list_tools()
    assert tools, "Server must expose at least one tool"
    for tool in tools:
        assert TOOL_NAME.match(tool.name), f"Invalid tool name for most clients: {tool.name!r}"
        assert tool.description and tool.description.strip(), f"{tool.name} has no description"
        assert tool.input_schema.get("type") == "object", f"{tool.name}: bad input schema"


async def test_registered_tools_exist(mcp_client, server):
    available = {t.name for t in await mcp_client.list_tools()}
    missing = set(server.tools) - available
    assert not missing, f"Missing tools on {server.name}: {', '.join(sorted(missing))}"


async def test_unknown_tool_is_an_error(mcp_client):
    result = await mcp_client.call_tool("lupus_nonexistent_tool", {}, raise_on_error=False)
    assert result.is_error
