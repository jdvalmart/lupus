"""Layer 1 — MCP Protocol Compliance.

Tests that verify the server speaks MCP correctly at the wire level,
including Streamable HTTP session negotiation requirements.
"""

import pytest


@pytest.mark.protocol
class TestProtocol:
    """Raw protocol tests — verify JSON-RPC and session behavior."""

    def test_jsonrpc_version_on_sessionless_request(self, raw):
        """Without a session, the server still responds with valid JSON-RPC."""
        resp = raw("tools/list")
        assert resp.get("jsonrpc") == "2.0", f"Expected jsonrpc 2.0, got: {resp}"

    def test_missing_session_is_rejected_with_error(self, raw):
        """Streamable HTTP requires a session ID. Without it, we get an error."""
        resp = raw("tools/list")
        assert "error" in resp, (
            f"Sessionless request should return an error, got: {resp}"
        )

    def test_invalid_method_returns_error_code(self, raw):
        """Unknown methods must return an error code.

        Streamable HTTP may reject the request with a session error (-32600)
        before checking the method, which is also valid behavior.
        """
        resp = raw("tools/eat_pizza")
        assert "error" in resp, f"Expected error response: {resp}"
        code = resp["error"]["code"]
        assert code == -32601 or code == -32600, (
            f"Expected -32601 (method not found) or -32600 (session required), got {code}"
        )

    def test_error_response_has_code_and_message(self, raw):
        """All error responses must include code and message fields."""
        resp = raw("tools/call", {
            "name": "nonexistent_tool_xyz",
            "arguments": {},
        })
        if "error" in resp:
            assert "code" in resp["error"], f"Error missing code: {resp}"
            assert "message" in resp["error"], f"Error missing message: {resp}"
