"""Layer 1 — MCP protocol compliance and transport security at the wire level."""

from __future__ import annotations

import pytest


@pytest.mark.protocol
class TestProtocol:
    """Raw JSON-RPC over Streamable HTTP, without a negotiated session."""

    def test_sessionless_request_gets_jsonrpc_error(self, raw):
        """Streamable HTTP requires initialize first; the reply is still valid JSON-RPC."""
        _, body = raw("tools/list")
        assert body.get("jsonrpc") == "2.0", body
        assert "error" in body, body
        assert {"code", "message"} <= set(body["error"]), body

    def test_unknown_method_returns_standard_error_code(self, raw):
        """Unknown methods fail with -32601, or -32600 when the session check runs first."""
        _, body = raw("tools/eat_pizza")
        assert body["error"]["code"] in (-32601, -32600), body


@pytest.mark.protocol
class TestAuthentication:
    """A managed server always runs with a bearer token."""

    def test_missing_token_is_rejected(self, raw, requires_managed):
        status, _ = raw("tools/list", headers={})
        assert status == 401

    def test_wrong_token_is_rejected(self, raw, requires_managed):
        status, _ = raw("tools/list", headers={"Authorization": "Bearer not-the-token"})
        assert status == 401

    def test_valid_token_reaches_mcp_layer(self, raw, requires_managed):
        status, body = raw("tools/list")
        assert status != 401
        assert body.get("jsonrpc") == "2.0"
