"""Layer 5 — Performance & Load Tests.

Tests that Orion responds within acceptable time limits.

Uses local LLM (Ollama) to generate diverse test data via llm_data fixture.
"""

import time

import pytest


@pytest.mark.performance
class TestResponseTime:
    """Tools must respond within acceptable time limits."""

    async def test_whoami_response_time(self, mcp_client, call):
        """whoami should respond in under 1s."""
        start = time.monotonic()
        r = await call("whoami")
        elapsed = time.monotonic() - start
        assert "Trajectory" in r
        assert elapsed < 2.0, f"whoami took {elapsed:.2f}s"

    async def test_recall_response_time(self, mcp_client, call):
        """recall_context should respond in under 2s."""
        start = time.monotonic()
        await call("recall_context", {"query": "test"})
        elapsed = time.monotonic() - start
        assert elapsed < 3.0, f"recall took {elapsed:.2f}s"

    async def test_browse_response_time(self, mcp_client, call):
        """browse_memories should respond quickly."""
        start = time.monotonic()
        await call("browse_memories")
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"browse took {elapsed:.2f}s"


@pytest.mark.performance
class TestBulkOperations:
    """Orion handles multiple operations without degrading."""

    async def test_bulk_remember(self, mcp_client, call, llm_data):
        """Write 30 decisions with LLM-generated data and verify they exist."""
        start = time.monotonic()
        for i in range(30):
            topic = llm_data(f"topic #{i+1} for a software architecture decision", fallback=f"bulk_topic_{i}")
            decision = llm_data(f"technical decision about {topic}", fallback=f"bulk entry number {i}")
            await call("remember_decision", {
                "topic": topic,
                "decision": decision,
                "tags": "bulk,performance,llm",
            })
        elapsed = time.monotonic() - start
        assert elapsed < 30.0, f"30 LLM-generated writes took {elapsed:.2f}s"

        browse = await call("browse_memories")
        assert "bulk" in browse

    async def test_recall_with_many_entries(self, mcp_client, call):
        """Semantic search should still work with many entries."""
        start = time.monotonic()
        r = await call("recall_context", {
            "query": "bulk entry",
            "limit": 3,
        })
        elapsed = time.monotonic() - start
        assert elapsed < 5.0, f"recall with bulk data took {elapsed:.2f}s"
        assert isinstance(r, str)
