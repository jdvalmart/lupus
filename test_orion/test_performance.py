"""Layer 5 — performance: latency stays low with a realistic amount of data.

Budgets are deliberately generous; they catch order-of-magnitude
regressions, not milliseconds.
"""

from __future__ import annotations

import statistics
import time

import pytest

pytestmark = [pytest.mark.performance, pytest.mark.usefixtures("requires_managed")]

SEED = 200


@pytest.fixture
async def seeded(call, project) -> str:
    for index in range(SEED):
        await call.ok(
            "remember_decision",
            {
                "topic": f"topic-{index}",
                "decision": f"Decision {index} about service {index % 17} and cache layer",
                "tags": [f"group-{index % 5}"],
                "project": project,
            },
        )
    return project


async def _p95(call, name: str, args: dict, runs: int = 20) -> float:
    timings = []
    for _ in range(runs):
        start = time.perf_counter()
        await call.ok(name, args)
        timings.append(time.perf_counter() - start)
    return statistics.quantiles(timings, n=20)[18]


async def test_bulk_writes_throughput(call, project):
    start = time.perf_counter()
    for index in range(100):
        await call.ok(
            "remember_decision", {"topic": f"bulk-{index}", "decision": "x", "project": project}
        )
    elapsed = time.perf_counter() - start
    assert elapsed < 20.0, f"100 writes took {elapsed:.1f}s"


@pytest.mark.parametrize(
    ("tool", "args", "budget"),
    [
        ("recall_context", {"query": "service cache"}, 0.5),
        ("browse_memories", {"limit": 50}, 0.5),
        ("recall_session", {}, 0.5),
        ("whoami", {}, 0.5),
    ],
)
async def test_p95_latency(call, seeded, tool, args, budget):
    if tool != "whoami":
        args = {**args, "project": seeded}
    p95 = await _p95(call, tool, args)
    assert p95 < budget, f"{tool} p95 {p95 * 1000:.0f}ms over {budget * 1000:.0f}ms"
