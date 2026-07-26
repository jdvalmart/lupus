"""Layer 3 — Contract & Edge Case Tests.

Tests that Orion handles invalid, unexpected, or malicious inputs
without crashing or leaking information.
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

    async def test_special_characters(self, mcp_client, call):
        """Special characters in topic and decision are handled."""
        r = await call("remember_decision", {
            "topic": "emoji 🔥 test",
            "decision": "unicode ñ á é í ó ú — em dash – bullet •",
            "tags": "🔥,unicode,test",
        })
        assert "Stored decision" in r

        recall = await call("recall_context", {
            "query": "unicode ñ",
        })
        assert "unicode ñ á é í ó ú" in recall

    async def test_very_long_input(self, mcp_client, call):
        """Very long decision text should not break storage."""
        long_text = "x" * 5000
        r = await call("remember_decision", {
            "topic": "long",
            "decision": long_text,
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
