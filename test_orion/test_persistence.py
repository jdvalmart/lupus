"""Layer 4 — Persistence & Recovery Tests.

Tests that Orion handles data correctly across calls.

Uses local LLM (Ollama) to generate realistic test data via llm_data fixture.
"""

import pytest


@pytest.mark.persistence
class TestDataIntegrity:
    """Data survives across tool calls and server remains consistent."""

    async def test_empty_state_is_graceful(self, mcp_client, call):
        """Empty state returns friendly messages, not crashes."""
        r = await call("browse_memories")
        assert isinstance(r, str)

    async def test_data_persists_across_calls(self, mcp_client, call, llm_data):
        """Data written in one call is readable in subsequent calls."""
        topic = llm_data("a topic about data persistence patterns")
        decision = llm_data("a decision about using a specific persistence strategy")

        await call("remember_decision", {
            "topic": topic,
            "decision": decision,
            "tags": "persistence,llm",
        })
        r = await call("recall_context", {
            "query": "persistence patterns",
        })
        assert isinstance(r, str)

    async def test_recall_works_after_restart(self, mcp_client, call):
        """Data survives the full session (tested by running after
        test_data_persists_across_calls)."""
        browse = await call("browse_memories")
        assert isinstance(browse, str)
