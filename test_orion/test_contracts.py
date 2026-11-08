"""Layer 3 — contracts: invalid, hostile and edge-case input is rejected or stored safely."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.contracts, pytest.mark.usefixtures("requires_managed")]


class TestNonExistentIDs:
    """Operations on missing ids fail as tool errors, not fake successes."""

    @pytest.mark.parametrize("memory_id", [99_999_999, 0, -1])
    async def test_forget_unknown_id(self, call, memory_id):
        assert "not found" in await call.error("forget_decision", {"id": memory_id})

    async def test_revise_unknown_id(self, call):
        assert "not found" in await call.error(
            "revise_decision", {"id": 99_999_999, "topic": "ghost"}
        )

    async def test_find_related_unknown_id(self, call):
        assert "not found" in await call.error("find_related", {"id": 99_999_999})

    async def test_link_to_unknown_id(self, call, project):
        stored = await call.ok(
            "remember_decision", {"topic": "a", "decision": "a", "project": project}
        )
        assert "not found" in await call.error(
            "link_concepts",
            {"source_id": stored["id"], "target_id": 99_999_999, "relation": "depends_on"},
        )

    async def test_session_with_unknown_decision(self, call, project):
        await call.error(
            "remember_session",
            {"summary": "x", "decisions_made": [99_999_999], "project": project},
        )


class TestInvalidInput:
    """Schema and domain validation."""

    @pytest.mark.parametrize(
        "args",
        [
            {"topic": "", "decision": "empty topic"},
            {"topic": "t", "decision": ""},
            {"topic": "   ", "decision": "blank topic"},
            {"topic": "t" * 201, "decision": "topic over the limit"},
            {"topic": "t", "decision": "d" * 20_001},
            {"decision": "missing topic"},
        ],
        ids=[
            "empty-topic",
            "empty-decision",
            "blank-topic",
            "long-topic",
            "long-decision",
            "missing-topic",
        ],
    )
    async def test_remember_rejects(self, call, project, args):
        await call.error("remember_decision", {**args, "project": project})

    @pytest.mark.parametrize(
        "args",
        [
            {"query": ""},
            {"query": "?!"},
            {"query": "test", "limit": 0},
            {"query": "test", "limit": 51},
            {"query": "test", "limit": "abc"},
            {"query": "test", "scope": "everything"},
        ],
        ids=["empty", "no-words", "limit-0", "limit-51", "limit-string", "bad-scope"],
    )
    async def test_recall_rejects(self, call, project, args):
        await call.error("recall_context", {**args, "project": project})

    async def test_string_id_is_rejected(self, call):
        await call.error("forget_decision", {"id": "abc"})

    async def test_invalid_project_name_is_rejected(self, call):
        await call.error("remember_decision", {"topic": "t", "decision": "d", "project": "///"})

    async def test_empty_summary_is_rejected(self, call, project):
        await call.error("remember_session", {"summary": "  ", "project": project})

    async def test_oversized_profile_section_is_rejected(self, call):
        """whoami returns the whole profile; an unbounded section would flood the context."""
        await call.error("update_profile", {"section": "huge", "value": "x" * 100_000})


class TestHostileContent:
    """Hostile strings are stored verbatim and never alter the store."""

    @pytest.mark.parametrize(
        "text",
        [
            "'; DROP TABLE memories; --",
            "../../etc/passwd",
            "<script>alert(1)</script>",
            "‮؜‎test‏",
            "emoji 🔥 ñ á é — •",
            '{"key": "val"}',
            'unbalanced " quote * NEAR( OR AND',
        ],
        ids=["sql", "path", "xss", "bidi", "unicode", "json", "fts-syntax"],
    )
    async def test_stored_verbatim_and_searchable(self, call, project, text):
        stored = await call.ok(
            "remember_decision", {"topic": "hostile", "decision": text, "project": project}
        )
        assert stored["decision"] == text.strip()
        await call.ok("recall_context", {"query": f"hostile {text}", "project": project})
        health = await call.ok("orion_health")
        assert health["integrity"] == "ok"

    async def test_null_byte_does_not_corrupt_store(self, call, project):
        result = await call.raw(
            "remember_decision", {"topic": "nul", "decision": "a\x00b", "project": project}
        )
        if not result.is_error:
            assert result.structured_content["decision"] == "a\x00b"
        assert (await call.ok("orion_health"))["integrity"] == "ok"

    async def test_hostile_project_name_is_normalised(self, call):
        stored = await call.ok(
            "remember_decision", {"topic": "t", "decision": "d", "project": "../../Etc/Passwd"}
        )
        assert "/" not in stored["project"]
        assert stored["project"] == stored["project"].lower()
