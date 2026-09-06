"""Layer 3 — Contract & Edge Case Tests.

Tests that Orion handles invalid, unexpected, or malicious inputs
without crashing or leaking information.

Uses local LLM (Ollama) to generate edge cases via ollama fixture.
"""

import pytest


@pytest.mark.contracts
class TestNonExistentIDs:
    """Operations on IDs that don't exist should fail gracefully."""

    async def test_revise_nonexistent(self, mcp_client, call):
        r = await call("revise_decision", {
            "id": 99999,
            "topic": "ghost",
        })
        assert "not found" in r.lower()

    async def test_forget_nonexistent(self, mcp_client, call):
        r = await call("forget_decision", {"id": 99999})
        assert "not found" in r.lower()

    async def test_find_related_nonexistent(self, mcp_client, call):
        r = await call("find_related", {"id": 99999})
        assert "no relationships" in r.lower() or "not found" in r.lower()


@pytest.mark.contracts
class TestEmptyAndSpecialInputs:
    """Empty strings, weird characters, and edge values."""

    async def test_empty_topic(self, mcp_client, call):
        """Empty topic should still store."""
        r = await call("remember_decision", {
            "topic": "",
            "decision": "empty topic test",
        })
        assert "Stored decision" in r

    async def test_empty_query(self, mcp_client, call):
        """Empty query should not crash."""
        r = await call("recall_context", {"query": ""})
        assert isinstance(r, str)

    async def test_special_characters(self, mcp_client, call, ollama):
        """Special characters in topic and decision are handled.

        Uses LLM to generate realistic Unicode/emoji test strings.
        """
        unicode_str = ollama(
            "Generate a string with emojis and special Unicode characters for testing. "
            "Include at least 3 emojis and accented letters. Only the string, nothing else.",
            timeout=10,
        )
        if not unicode_str or "OLLAMA_ERROR" in unicode_str:
            unicode_str = "emoji 🔥 test unicode ñ á é í ó ú — em dash – bullet •"

        r = await call("remember_decision", {
            "topic": unicode_str[:50],
            "decision": unicode_str,
            "tags": "unicode,llm,test",
        })
        assert "Stored decision" in r

        recall = await call("recall_context", {
            "query": unicode_str[:30],
        })
        assert isinstance(recall, str)

    async def test_very_long_input(self, mcp_client, call, ollama):
        """Very long decision text should not break storage.

        Uses LLM to generate a long technical text.
        """
        long_text = ollama(
            "Write a detailed 500-word technical explanation of how distributed databases work. "
            "Only the text, no headings or formatting.",
            timeout=15,
        )
        if not long_text or "OLLAMA_ERROR" in long_text or len(long_text) < 100:
            long_text = "x" * 5000

        r = await call("remember_decision", {
            "topic": "long_input_llm",
            "decision": long_text[:5000],
        })
        assert "Stored decision" in r


@pytest.mark.contracts
class TestZeroAndNegativeValues:
    """Numeric edge cases."""

    async def test_zero_id(self, mcp_client, call):
        """ID 0 should not exist."""
        r = await call("forget_decision", {"id": 0})
        assert "not found" in r.lower()

    async def test_negative_id(self, mcp_client, call):
        """Negative IDs should not exist."""
        r = await call("forget_decision", {"id": -1})
        assert "not found" in r.lower()

    async def test_recall_zero_limit(self, mcp_client, call):
        """Limit 0 should not crash."""
        r = await call("recall_context", {
            "query": "test",
            "limit": 0,
        })
        assert isinstance(r, str)
