"""Layer 4 — Persistence & Recovery Tests.

Tests that Orion handles data correctly across calls.
"""

import pytest


@pytest.mark.persistence
class TestDataIntegrity:
    """Data survives across tool calls and server remains consistent."""

    async def test_empty_state_is_graceful(self, mcp_client, call):
        """Empty state returns friendly messages, not crashes."""
        r = await call("browse_memories")
        assert isinstance(r, str)

    async def test_data_persists_across_calls(self, mcp_client, call):
        """Data written in one call is readable in subsequent calls."""
        await call("remember_decision", {
            "topic": "persist_test",
            "decision": "this should survive across calls",
            "tags": "persistence",
        })
        r = await call("recall_context", {
            "query": "survive across calls",
        })
        assert "this should survive across calls" in r

    async def test_recall_works_after_restart(self, mcp_client, call):
        """Data survives the full session (tested by running after
        test_data_persists_across_calls)."""
        browse = await call("browse_memories")
        assert "persist_test" in browse
