"""Universal MCP compliance tests — apply to ANY server in config.yaml."""

import pytest


@pytest.mark.protocol
class TestMCPCompliance:
    """Tests that any MCP server — not just Orion — must pass."""

    async def test_tools_list_has_names(self, mcp_client, call):
        """Every tool returned by tools/list must have a name."""
        tools = await mcp_client.list_tools()
        assert len(tools) > 0, "Server must expose at least one tool"
        for tool in tools:
            assert hasattr(tool, "name"), f"Tool missing name: {tool}"
            assert tool.name, f"Tool name is empty"

    async def test_registered_tools_exist(self, mcp_client, server_config):
        """All tools listed in config.yaml must be available on the server."""
        server_tool_names = {t.name for t in await mcp_client.list_tools()}
        expected = set(server_config.get("tools", []))
        missing = expected - server_tool_names
        assert not missing, (
            f"Missing tools on {server_config['url']}: {', '.join(sorted(missing))}"
        )

    async def test_can_list_tools(self, mcp_client, call):
        """Server must respond to tools/list."""
        tools = await mcp_client.list_tools()
        assert isinstance(tools, list)
