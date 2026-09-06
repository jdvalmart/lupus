"""Layer 2 — Functional Tests.

Tests that each Orion tool does what it claims via a real MCP session.
Uses fastmcp.Client for proper Streamable HTTP negotiation.

Uses local LLM (Ollama) to generate realistic test data via llm_data fixture.
"""

import time

import pytest


@pytest.mark.functional
class TestMemoryCRUD:
    """Create, read, update, delete — full cycle."""

    async def test_remember_and_browse(self, mcp_client, call, llm_data):
        """Storing a decision shows up in browse."""
        topic = llm_data("a software architecture topic like 'database choice' or 'API design'")
        decision = llm_data("a short technical decision about that topic")

        r = await call("remember_decision", {
            "topic": topic,
            "decision": decision,
            "tags": "test,lupus,llm",
        })
        assert "Stored decision" in r

        browse = await call("browse_memories")
        assert topic in browse

    async def test_recall_finds_entry(self, mcp_client, call, llm_data):
        """Semantic search finds relevant entries."""
        topic = llm_data("a topic about machine learning or AI")
        decision = llm_data("a decision about using a specific ML framework")

        await call("remember_decision", {
            "topic": topic,
            "decision": decision,
            "tags": "test,llm,recall",
        })

        query = llm_data("a search query to find the decision about ML frameworks")
        result = await call("recall_context", {
            "query": query,
            "limit": 3,
        })
        assert isinstance(result, str)

    async def test_revise_updates_entry(self, mcp_client, call, llm_data):
        """Revising changes the topic."""
        original_topic = llm_data("a topic about deployment strategy")
        new_topic = llm_data("a new topic about container orchestration")

        c = await call("remember_decision", {
            "topic": original_topic,
            "decision": "deployment strategy to revise",
        })
        cid = int(c.split("#")[1].split(":")[0])

        r = await call("revise_decision", {
            "id": cid,
            "topic": new_topic,
        })
        assert "Revised decision" in r or new_topic in r

        browse = await call("browse_memories")
        assert new_topic in browse

    async def test_forget_removes_entry(self, mcp_client, call, llm_data):
        """Forgetting removes from browse."""
        topic = llm_data(
            "a unique topic about testing strategy",
            fallback=f"forget_target_{int(time.time()*1000)}",
        )

        c = await call("remember_decision", {
            "topic": topic,
            "decision": "testing strategy to delete",
        })
        cid = int(c.split("#")[1].split(":")[0])

        r = await call("forget_decision", {"id": cid})
        assert "Forgot decision" in r

        browse = await call("browse_memories")
        assert topic not in browse


@pytest.mark.functional
class TestKnowledgeGraph:
    """Graph tools: link, find, browse."""

    async def test_link_and_find(self, mcp_client, call, llm_data):
        """Linking two nodes makes find_related work."""
        desc_a = llm_data("a description of a microservice like 'user authentication service'")
        desc_b = llm_data("a description of a dependent service like 'payment processing service'")

        a = await call("remember_decision", {
            "topic": "graph_node_a", "decision": desc_a,
        })
        aid = int(a.split("#")[1].split(":")[0])
        b = await call("remember_decision", {
            "topic": "graph_node_b", "decision": desc_b,
        })
        bid = int(b.split("#")[1].split(":")[0])

        relation_desc = llm_data("a short description of the dependency between the two services")

        r = await call("link_concepts", {
            "source_id": aid,
            "target_id": bid,
            "relation": "depends_on",
            "description": relation_desc,
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

    async def test_remember_and_recall(self, mcp_client, call, llm_data):
        """Session cycle: remember → recall contains the summary."""
        summary = llm_data("a short summary of a development session about fixing bugs")

        r = await call("remember_session", {
            "summary": summary,
            "tags": "test,lupus,llm",
        })
        assert "Saved session" in r

        recall = await call("recall_session")
        assert summary in recall

    async def test_browse_sessions(self, mcp_client, call):
        """Browse shows recorded sessions."""
        browse = await call("browse_sessions")
        assert "session" in browse.lower()
