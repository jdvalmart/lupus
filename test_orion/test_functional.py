"""Layer 2 — Functional Tests.

Tests that each Orion tool does what it claims via a real MCP session.
Uses fastmcp.Client for proper Streamable HTTP negotiation.
"""

import pytest


@pytest.mark.functional
class TestMemoryCRUD:
    """Create, read, update, delete — full cycle."""

    async def test_remember_and_browse(self, mcp_client, call):
        """Storing a decision shows up in browse."""
        r = await call("remember_decision", {
            "topic": "lupus_test",
            "decision": "functional test entry",
            "tags": "test,lupus",
        })
        assert "Stored decision" in r

        browse = await call("browse_memories")
        assert "lupus_test" in browse

    async def test_recall_finds_entry(self, mcp_client, call):
        """Semantic search finds relevant entries."""
        result = await call("recall_context", {
            "query": "functional test",
            "limit": 3,
        })
        assert "functional test entry" in result

    async def test_revise_updates_entry(self, mcp_client, call):
        """Revising changes the topic."""
        c = await call("remember_decision", {
            "topic": "revise_target",
            "decision": "entry to revise",
        })
        cid = int(c.split("#")[1].split(":")[0])

        r = await call("revise_decision", {
            "id": cid,
            "topic": "lupus_modified",
        })
        assert "Revised decision" in r or "lupus_modified" in r

        browse = await call("browse_memories")
        assert "lupus_modified" in browse

    async def test_forget_removes_entry(self, mcp_client, call):
        """Forgetting removes from browse."""
        c = await call("remember_decision", {
            "topic": "forget_target",
            "decision": "entry to delete",
        })
        cid = int(c.split("#")[1].split(":")[0])

        r = await call("forget_decision", {"id": cid})
        assert "Forgot decision" in r

        browse = await call("browse_memories")
        assert "forget_target" not in browse


@pytest.mark.functional
class TestKnowledgeGraph:
    """Graph tools: link, find, browse."""

    async def test_link_and_find(self, mcp_client, call):
        """Linking two nodes makes find_related work."""
        a = await call("remember_decision", {
            "topic": "graph_node_a", "decision": "first graph node",
        })
        aid = int(a.split("#")[1].split(":")[0])
        b = await call("remember_decision", {
            "topic": "graph_node_b", "decision": "second graph node",
        })
        bid = int(b.split("#")[1].split(":")[0])

        r = await call("link_concepts", {
            "source_id": aid,
            "target_id": bid,
            "relation": "depends_on",
            "description": "test relationship",
        })
        assert "Linked" in r or "already" in r.lower()

        find = await call("find_related", {"id": aid})
        assert "depends_on" in find

    async def test_browse_graph(self, mcp_client, call):
        """Browse shows edges."""
        graph = await call("browse_graph")
        assert "depends_on" in graph or "relationship" in graph.lower()

    async def test_invalid_relation_rejected(self, mcp_client, call):
        """Invalid relation type returns an error message."""
        r = await call("link_concepts", {
            "source_id": 2,
            "target_id": 3,
            "relation": "eats_pizza",
        })
        assert "Invalid relation type" in r

    async def test_self_link_rejected(self, mcp_client, call):
        """Cannot link a node to itself."""
        r = await call("link_concepts", {
            "source_id": 2,
            "target_id": 2,
            "relation": "depends_on",
        })
        assert "Cannot link" in r


@pytest.mark.functional
class TestWhoami:
    """Profile tool."""

    async def test_whoami_returns_profile(self, mcp_client, call):
        """whoami returns Juan's data."""
        result = await call("whoami")
        assert "Juan David" in result or "Trajectory" in result


@pytest.mark.functional
class TestSessions:
    """Session memory tools."""

    async def test_remember_and_recall(self, mcp_client, call):
        """Session cycle: remember → recall contains the summary."""
        r = await call("remember_session", {
            "summary": "Lupus functional test session",
            "tags": "test,lupus",
        })
        assert "Saved session" in r

        recall = await call("recall_session")
        assert "Lupus functional test session" in recall

    async def test_browse_sessions(self, mcp_client, call):
        """Browse shows recorded sessions."""
        browse = await call("browse_sessions")
        assert "session" in browse.lower()
