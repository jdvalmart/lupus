"""Layer 4 — persistence: data survives restarts and concurrent clients lose nothing."""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client

from conftest import Caller

pytestmark = [pytest.mark.persistence, pytest.mark.usefixtures("requires_managed")]


async def test_data_survives_restart(server, project):
    async with Client(server.url, auth=server.token) as client:
        call = Caller(client)
        kept = await call.ok(
            "remember_decision", {"topic": "durable", "decision": "survives", "project": project}
        )
        gone = await call.ok(
            "remember_decision", {"topic": "deleted", "decision": "gone", "project": project}
        )
        await call.ok("forget_decision", {"id": gone["id"]})
        await call.ok("remember_session", {"summary": "before restart", "project": project})

    server.restart()

    async with Client(server.url, auth=server.token) as client:
        call = Caller(client)
        page = await call.ok("browse_memories", {"project": project})
        assert [item["id"] for item in page["items"]] == [kept["id"]]
        context = await call.ok("recall_session", {"project": project})
        assert context["recent_sessions"][0]["summary"] == "before restart"
        fresh = await call.ok(
            "remember_decision", {"topic": "after", "decision": "restart", "project": project}
        )
        assert fresh["id"] > gone["id"]
        assert (await call.ok("orion_health"))["integrity"] == "ok"


async def test_concurrent_clients_do_not_lose_writes(server, project):
    clients, writes = 5, 20

    async def writer(index: int) -> list[int]:
        async with Client(server.url, auth=server.token) as client:
            call = Caller(client)
            ids = []
            for n in range(writes):
                stored = await call.ok(
                    "remember_decision",
                    {"topic": f"c{index}-{n}", "decision": "parallel", "project": project},
                )
                ids.append(stored["id"])
            return ids

    results = await asyncio.gather(*(writer(i) for i in range(clients)))
    all_ids = [i for ids in results for i in ids]
    assert len(set(all_ids)) == clients * writes

    async with Client(server.url, auth=server.token) as client:
        page = await Caller(client).ok("browse_memories", {"project": project, "limit": 100})
        assert page["total"] == clients * writes


async def test_empty_project_is_graceful(call, project):
    context = await call.ok("recall_session", {"project": project})
    assert context["total_sessions"] == 0
    assert context["recent_sessions"] == []
    page = await call.ok("browse_memories", {"project": project})
    assert page == {"project": project, "total": 0, "offset": 0, "items": []}
