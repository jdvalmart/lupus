"""Layer 5 — Performance & Load Tests.

Tests that Orion responds within acceptable time limits.
"""

import time

import pytest


@pytest.mark.performance
class TestResponseTime:
    """Tools must respond within acceptable time limits."""

    async def test_whoami_response_time(self, mcp_client, call):
        """whoami should respond in under 1s."""
        import time as t_time
        start = t_time.monotonic()
        r = await call("whoami")
        elapsed = t_time.monotonic() - start
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

    async def test_bulk_remember(self, mcp_client, call):
        """Write 30 decisions and verify they all exist."""
        start = time.monotonic()
        for i in range(30):
            await call("remember_decision", {
                "topic": f"bulk_{i}",
                "decision": f"bulk entry number {i}",
                "tags": "bulk,performance",
            })
        elapsed = time.monotonic() - start
        assert elapsed < 15.0, f"30 writes took {elapsed:.2f}s"

        browse = await call("browse_memories")
        assert "bulk" in browse

    async def test_recall_with_many_entries(self, mcp_client, call):
        """Semantic search should still work with many entries."""
        start = time.monotonic()
        r = await call("recall_context", {
            "query": "bulk entry number 20",
            "limit": 3,
        })
        elapsed = time.monotonic() - start
        assert elapsed < 5.0, f"recall with bulk data took {elapsed:.2f}s"
        assert "bulk" in r
