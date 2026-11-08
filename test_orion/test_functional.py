"""Layer 2 — every tool does what it claims, checked on structured output."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.functional, pytest.mark.usefixtures("requires_managed")]


async def remember(call, project: str, topic: str, decision: str, **extra) -> dict:
    return await call.ok(
        "remember_decision", {"topic": topic, "decision": decision, "project": project, **extra}
    )


class TestMemoryCRUD:
    """Create, read, update, delete — full cycle."""

    async def test_remember_returns_stored_entry(self, call, project):
        stored = await remember(call, project, "database", "SQLite in WAL mode", tags=["Storage"])
        assert stored["id"] > 0
        assert stored["project"] == project
        assert stored["topic"] == "database"
        assert stored["tags"] == ["storage"]

    async def test_browse_lists_newest_first(self, call, project):
        first = await remember(call, project, "first", "one")
        second = await remember(call, project, "second", "two")
        page = await call.ok("browse_memories", {"project": project})
        assert page["total"] == 2
        assert [item["id"] for item in page["items"]] == [second["id"], first["id"]]

    async def test_recall_finds_matching_entry(self, call, project):
        target = await remember(call, project, "payments", "Wompi handles card checkout")
        await remember(call, project, "styling", "Tailwind with a warm palette")
        found = await call.ok("recall_context", {"query": "wompi checkout", "project": project})
        assert found["results"][0]["id"] == target["id"]
        assert found["results"][0]["match"] in ("keyword", "both")

    async def test_revise_changes_only_given_fields(self, call, project):
        stored = await remember(call, project, "auth", "Cookies", tags=["security"])
        revised = await call.ok("revise_decision", {"id": stored["id"], "decision": "JWT"})
        assert revised["decision"] == "JWT"
        assert revised["topic"] == "auth"
        assert revised["tags"] == ["security"]

    async def test_forget_removes_from_browse_and_search(self, call, project):
        stored = await remember(call, project, "cache", "Redis for sessions")
        await call.ok("forget_decision", {"id": stored["id"]})
        page = await call.ok("browse_memories", {"project": project})
        assert page["total"] == 0
        found = await call.ok("recall_context", {"query": "redis", "project": project})
        assert found["results"] == []

    async def test_ids_are_not_reused_after_forget(self, call, project):
        first = await remember(call, project, "a", "a")
        await call.ok("forget_decision", {"id": first["id"]})
        second = await remember(call, project, "b", "b")
        assert second["id"] > first["id"]


class TestProjects:
    """Memories are scoped to projects."""

    async def test_search_is_scoped_to_project(self, call, project):
        other = f"{project}-other"
        await remember(call, project, "queue", "Celery workers")
        await remember(call, other, "queue", "RQ workers")
        scoped = await call.ok("recall_context", {"query": "workers", "project": project})
        assert {hit["project"] for hit in scoped["results"]} == {project}
        everywhere = await call.ok("recall_context", {"query": "workers", "scope": "all"})
        assert {project, other} <= {hit["project"] for hit in everywhere["results"]}

    async def test_list_projects_reports_counts(self, call, project):
        await remember(call, project, "t", "d")
        projects = await call.ok("list_projects")
        mine = next(p for p in projects if p["name"] == project)
        assert mine["memories"] == 1


class TestKnowledgeGraph:
    """Graph tools: link, find, browse, cascade."""

    async def test_link_and_find_both_directions(self, call, project):
        a = await remember(call, project, "auth-service", "Issues tokens")
        b = await remember(call, project, "payment-service", "Charges cards")
        edge = await call.ok(
            "link_concepts",
            {"source_id": b["id"], "target_id": a["id"], "relation": "depends_on"},
        )
        assert edge["relation"] == "depends_on"

        outgoing = await call.ok("find_related", {"id": b["id"]})
        assert outgoing["links"] == [
            {
                "id": a["id"],
                "topic": "auth-service",
                "relation": "depends_on",
                "direction": "outgoing",
                "description": None,
            }
        ]
        incoming = await call.ok("find_related", {"id": a["id"]})
        assert incoming["links"][0]["direction"] == "incoming"

    async def test_browse_graph_lists_project_edges(self, call, project):
        a = await remember(call, project, "a", "a")
        b = await remember(call, project, "b", "b")
        await call.ok(
            "link_concepts", {"source_id": a["id"], "target_id": b["id"], "relation": "relates_to"}
        )
        graph = await call.ok("browse_graph", {"project": project})
        assert graph["total"] == 1

    async def test_forget_cascades_to_edges(self, call, project):
        a = await remember(call, project, "a", "a")
        b = await remember(call, project, "b", "b")
        await call.ok(
            "link_concepts", {"source_id": a["id"], "target_id": b["id"], "relation": "relates_to"}
        )
        await call.ok("forget_decision", {"id": b["id"]})
        assert (await call.ok("find_related", {"id": a["id"]}))["links"] == []

    async def test_supersedes_links_new_to_old(self, call, project):
        old = await remember(call, project, "orm", "Raw SQL")
        new = await remember(call, project, "orm", "SQLAlchemy", supersedes=old["id"])
        related = await call.ok("find_related", {"id": new["id"]})
        assert (related["links"][0]["id"], related["links"][0]["relation"]) == (
            old["id"],
            "supersedes",
        )

    async def test_invalid_relation_is_rejected(self, call, project):
        a = await remember(call, project, "a", "a")
        b = await remember(call, project, "b", "b")
        await call.error(
            "link_concepts", {"source_id": a["id"], "target_id": b["id"], "relation": "eats_pizza"}
        )

    async def test_self_link_is_rejected(self, call, project):
        a = await remember(call, project, "a", "a")
        message = await call.error(
            "link_concepts", {"source_id": a["id"], "target_id": a["id"], "relation": "depends_on"}
        )
        assert "itself" in message


class TestSessions:
    """Session history and project state."""

    async def test_session_cycle_restores_context(self, call, project):
        decision = await remember(call, project, "api", "REST")
        await call.ok(
            "remember_session",
            {"summary": "Scaffolded the repo", "phase": "Phase 0", "project": project},
        )
        await call.ok(
            "remember_session",
            {
                "summary": "Built the API",
                "next_steps": "Write the frontend",
                "decisions_made": [decision["id"]],
                "project": project,
            },
        )
        context = await call.ok("recall_session", {"project": project})
        assert context["phase"] == "Phase 0"
        assert context["next_steps"] == "Write the frontend"
        assert context["total_sessions"] == 2
        assert [s["summary"] for s in context["recent_sessions"]] == [
            "Built the API",
            "Scaffolded the repo",
        ]
        assert context["recent_decisions"][0]["id"] == decision["id"]

    async def test_browse_sessions_pages(self, call, project):
        for index in range(3):
            await call.ok("remember_session", {"summary": f"s{index}", "project": project})
        page = await call.ok("browse_sessions", {"project": project, "limit": 2})
        assert page["total"] == 3
        assert [s["summary"] for s in page["items"]] == ["s2", "s1"]


class TestProfileAndHealth:
    """Profile sections and diagnostics."""

    async def test_update_profile_round_trip(self, call):
        await call.ok("update_profile", {"section": "lupus_probe", "value": {"ok": True}})
        profile = await call.ok("whoami")
        assert profile["lupus_probe"] == {"ok": True}
        await call.ok("update_profile", {"section": "lupus_probe", "value": None})
        assert "lupus_probe" not in await call.ok("whoami")

    async def test_health_reports_integrity(self, call):
        health = await call.ok("orion_health")
        assert health["integrity"] == "ok"
        assert health["schema_version"] >= 1
