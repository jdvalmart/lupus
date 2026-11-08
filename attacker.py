"""Adversarial testing — hostile inputs from a local LLM (Ollama) plus a built-in corpus.

Runs outside pytest via ``lupus attack``, always against an isolated server
instance (see lupus_server.py). Each response is classified:

- accepted       the tool succeeded (hostile text stored verbatim is fine)
- rejected       the tool returned a tool error — the server defended itself
- slow           answered, but slower than SLOW_SECONDS (warning)
- vulnerability  server crashed, protocol/transport failure, internal details
                 leaked in the response, or the store failed its integrity check

Score = cases without a vulnerability / total cases.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastmcp import Client

from lupus_server import Server, server_from_config
from report import bar, score_line

REPORT_PATH = Path(__file__).parent / "QA_REPORT.md"
OLLAMA_URL = os.environ.get("LUPUS_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("LUPUS_OLLAMA_MODEL", "llama3.2")
SLOW_SECONDS = 3.0

ATTACK_PROMPT = """You are a QA security engineer. Generate exactly {count} DIFFERENT malicious \
test inputs for this MCP tool, each targeting a different attack vector:
empty or missing fields; SQL injection; path traversal; HTML/script injection; Unicode abuse \
(RTL override, zero-width chars, emojis); extremely long strings; boundary numbers \
(0, -1, 2147483648, 0.001); type confusion; nested JSON; null bytes and control characters.

RESPOND WITH ONLY A JSON ARRAY. No markdown, no explanation.
Each item: {{"why": "description", "params": {{"field": "value"}}}}

Tool schema:
"""

LEAK_PATTERNS = [
    re.compile(p)
    for p in (
        r"Traceback \(most recent call last\)",
        r'File "/',
        r"/home/[\w.-]+/",
        r"site-packages",
        r"sqlite3\.\w+Error",
        r"OperationalError",
    )
]

_LONG = "A" * 10_000
_BIDI = "‮؜‎test‏"

FALLBACK_ATTACKS: dict[str, list[dict[str, Any]]] = {
    "remember_decision": [
        {"why": "empty topic and decision", "params": {"topic": "", "decision": ""}},
        {
            "why": "SQL injection",
            "params": {"topic": "'; DROP TABLE memories; --", "decision": "x"},
        },
        {"why": "path traversal", "params": {"topic": "../../etc/passwd", "decision": "x"}},
        {
            "why": "script injection",
            "params": {"topic": "x", "decision": "<script>alert(1)</script>"},
        },
        {"why": "oversized topic", "params": {"topic": _LONG, "decision": "x"}},
        {"why": "unicode bidi abuse", "params": {"topic": _BIDI, "decision": "🔥💀☠️"}},
        {"why": "null byte", "params": {"topic": "test\x00injection", "decision": "x"}},
        {"why": "tags as object", "params": {"topic": "x", "decision": "x", "tags": {"a": 1}}},
        {
            "why": "hostile project",
            "params": {"topic": "x", "decision": "x", "project": "../../root"},
        },
        {"why": "supersedes unknown", "params": {"topic": "x", "decision": "x", "supersedes": -5}},
    ],
    "recall_context": [
        {"why": "empty query", "params": {"query": ""}},
        {"why": "FTS5 syntax injection", "params": {"query": 'a" OR NEAR(b c) * ^ AND'}},
        {"why": "SQL injection", "params": {"query": "'; SELECT * FROM memories --"}},
        {"why": "oversized query", "params": {"query": _LONG}},
        {"why": "negative limit", "params": {"query": "x", "limit": -1}},
        {"why": "huge limit", "params": {"query": "x", "limit": 2_147_483_648}},
        {"why": "string limit", "params": {"query": "x", "limit": "abc"}},
        {"why": "null query", "params": {"query": None}},
        {"why": "invalid scope", "params": {"query": "x", "scope": "../../"}},
    ],
    "revise_decision": [
        {"why": "unknown id", "params": {"id": 99_999_999, "topic": "ghost"}},
        {"why": "negative id", "params": {"id": -1, "topic": "x"}},
        {"why": "float id", "params": {"id": 0.5, "topic": "x"}},
        {"why": "missing id", "params": {"topic": "x"}},
        {"why": "no fields", "params": {"id": 1}},
    ],
    "forget_decision": [
        {"why": "unknown id", "params": {"id": 99_999_999}},
        {"why": "zero id", "params": {"id": 0}},
        {"why": "string id", "params": {"id": "1 OR 1=1"}},
        {"why": "null id", "params": {"id": None}},
    ],
    "browse_memories": [
        {"why": "negative offset", "params": {"offset": -10}},
        {"why": "huge limit", "params": {"limit": 1_000_000}},
        {"why": "tag injection", "params": {"tag": "' OR '1'='1"}},
        {"why": "unexpected argument", "params": {"admin": True}},
    ],
    "link_concepts": [
        {"why": "missing params", "params": {}},
        {
            "why": "unknown ids",
            "params": {"source_id": 99_999_998, "target_id": 99_999_999, "relation": "depends_on"},
        },
        {"why": "invalid relation", "params": {"source_id": 1, "target_id": 2, "relation": "owns"}},
        {"why": "self link", "params": {"source_id": 1, "target_id": 1, "relation": "depends_on"}},
    ],
    "find_related": [
        {"why": "unknown id", "params": {"id": 99_999_999}},
        {"why": "string id", "params": {"id": "abc"}},
    ],
    "browse_graph": [{"why": "negative offset", "params": {"offset": -1}}],
    "remember_session": [
        {"why": "empty summary", "params": {"summary": ""}},
        {"why": "oversized summary", "params": {"summary": _LONG * 3}},
        {
            "why": "unknown decisions",
            "params": {"summary": "x", "decisions_made": [-1, 99_999_999]},
        },
        {"why": "decisions as string", "params": {"summary": "x", "decisions_made": "1,2,3"}},
    ],
    "recall_session": [{"why": "hostile project", "params": {"project": "/etc/passwd"}}],
    "browse_sessions": [{"why": "zero limit", "params": {"limit": 0}}],
    "list_projects": [{"why": "unexpected argument", "params": {"inject": "<script>"}}],
    "whoami": [{"why": "unexpected argument", "params": {"admin": "true"}}],
    "update_profile": [
        {"why": "empty section", "params": {"section": "", "value": "x"}},
        {"why": "remove unknown section", "params": {"section": "nope", "value": None}},
        {"why": "oversized value", "params": {"section": "big", "value": _LONG * 10}},
        {"why": "deeply nested value", "params": {"section": "deep", "value": [[[[[[[[1]]]]]]]]}},
    ],
    "orion_health": [{"why": "unexpected argument", "params": {"verbose": True}}],
}


# ---------------------------------------------------------------------------
# LLM generation
# ---------------------------------------------------------------------------


def ollama_available() -> bool:
    """Whether the Ollama API answers."""
    try:
        urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=2)
        return True
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return False


def _ask_ollama(prompt: str, timeout: int = 120) -> str:
    payload = json.dumps({"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}).encode()
    request = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8")).get("response", "")
    except (urllib.error.URLError, ConnectionError, TimeoutError, ValueError):
        return ""


def parse_cases(response: str) -> list[dict[str, Any]]:
    """Extract well-formed ``{"why", "params": {...}}`` cases from LLM output."""
    text = re.sub(r"```\w*", "", response.strip())
    candidates: Any = []
    for opener, closer in (("[", "]"), ("{", "}")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                candidates = json.loads(text[start : end + 1])
                break
            except json.JSONDecodeError:
                continue
    if isinstance(candidates, dict):
        candidates = [candidates]
    if not isinstance(candidates, list):
        return []
    return [
        {"why": str(c.get("why", "llm case")), "params": c["params"]}
        for c in candidates
        if isinstance(c, dict) and isinstance(c.get("params"), dict)
    ]


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def find_leak(text: str) -> str | None:
    """The first internal-detail pattern found in a response, if any."""
    for pattern in LEAK_PATTERNS:
        if pattern.search(text):
            return pattern.pattern
    return None


def classify(is_error: bool, text: str, elapsed: float) -> tuple[str, str]:
    """Verdict and reason for a response that came back."""
    leak = find_leak(text)
    if leak:
        return "vulnerability", f"internal details leaked ({leak})"
    if elapsed > SLOW_SECONDS:
        return "slow", f"took {elapsed:.1f}s"
    if is_error:
        return "rejected", text.strip().splitlines()[0][:120] if text.strip() else "tool error"
    return "accepted", ""


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


async def _execute(server: Server, cases: dict[str, list[dict[str, Any]]]) -> list[dict]:
    results: list[dict[str, Any]] = []
    client = Client(server.url, auth=server.token)
    await client.__aenter__()
    try:
        for tool, tool_cases in cases.items():
            for case in tool_cases:
                started = time.monotonic()
                record: dict[str, Any] = {
                    "tool": tool,
                    "why": case["why"],
                    "params": case["params"],
                }
                try:
                    result = await client.call_tool(tool, case["params"], raise_on_error=False)
                    text = "\n".join(getattr(b, "text", "") for b in result.content)
                    elapsed = time.monotonic() - started
                    verdict, reason = classify(result.is_error, text, elapsed)
                    record.update(response=text[:200])
                except Exception as exc:
                    elapsed = time.monotonic() - started
                    verdict, reason = "vulnerability", f"transport/protocol failure: {exc}"[:300]

                if not server.alive():
                    verdict, reason = "vulnerability", "server process crashed"
                    await client.__aexit__(None, None, None)
                    server.start()
                    client = Client(server.url, auth=server.token)
                    await client.__aenter__()

                record.update(verdict=verdict, reason=reason, elapsed_ms=round(elapsed * 1000, 1))
                results.append(record)

        if "orion_health" in {t.name for t in await client.list_tools()}:
            health = await client.call_tool("orion_health", {}, raise_on_error=False)
            integrity = (health.structured_content or {}).get("integrity")
            results.append(
                {
                    "tool": "orion_health",
                    "why": "store integrity after the attack",
                    "params": {},
                    "verdict": "accepted" if integrity == "ok" else "vulnerability",
                    "reason": "" if integrity == "ok" else f"integrity check: {integrity}",
                    "elapsed_ms": 0.0,
                }
            )
    finally:
        await client.__aexit__(None, None, None)
    return results


async def run_adversarial(
    count: int = 4, tools: list[str] | None = None, server_name: str = "orion"
) -> float:
    """Generate, execute and report adversarial cases. Returns the score."""
    server = server_from_config(server_name)
    if not server.managed:
        raise SystemExit(
            f"Refusing to attack '{server_name}': it is an external server with real data. "
            "Configure a `command` so Lupus can launch an isolated instance."
        )
    started = time.monotonic()
    server.start()
    try:
        async with Client(server.url, auth=server.token) as client:
            listed = await client.list_tools()
        schemas = {
            t.name: {"name": t.name, "description": t.description, "inputSchema": t.input_schema}
            for t in listed
            if not tools or t.name in tools
        }
        print(f"🎯 {len(schemas)} tool(s) on isolated {server_name} at {server.url}")

        use_llm = ollama_available()
        print(
            "🧠 Generating cases: built-in corpus"
            + (f" + {OLLAMA_MODEL}" if use_llm else " only (Ollama not reachable)")
        )
        cases: dict[str, list[dict[str, Any]]] = {}
        llm_total = 0
        for name, schema in schemas.items():
            llm_cases = (
                parse_cases(
                    _ask_ollama(ATTACK_PROMPT.format(count=count) + json.dumps(schema, indent=2))
                )
                if use_llm
                else []
            )
            llm_total += len(llm_cases)
            seen: set[str] = set()
            merged = []
            for case in FALLBACK_ATTACKS.get(name, []) + llm_cases:
                key = json.dumps(case["params"], sort_keys=True, default=str)
                if key not in seen:
                    seen.add(key)
                    merged.append(case)
            cases[name] = merged or [{"why": "no arguments", "params": {}}]

        total = sum(len(c) for c in cases.values())
        print(f"⚔️  Executing {total} cases…")
        results = await _execute(server, cases)
    finally:
        server.cleanup()

    vulnerabilities = sum(r["verdict"] == "vulnerability" for r in results)
    score = round((len(results) - vulnerabilities) / len(results) * 100, 1) if results else 0.0
    llm_label = (
        f"{OLLAMA_MODEL} ({llm_total} cases)" if use_llm else "not used (Ollama unreachable)"
    )
    write_report(results, server_name, llm_label, time.monotonic() - started, score)

    counts = {
        v: sum(r["verdict"] == v for r in results)
        for v in ("accepted", "rejected", "slow", "vulnerability")
    }
    print(
        f"✅ Done. Accepted {counts['accepted']} · Rejected {counts['rejected']} · "
        f"Slow {counts['slow']} · Vulnerabilities {counts['vulnerability']}"
    )
    print(f"   Score: {score:g}% · Report: {REPORT_PATH}")
    return score


def write_report(
    results: list[dict[str, Any]], server: str, llm: str, total_time: float, score: float
) -> None:
    """Write QA_REPORT.md."""
    counts = {
        v: sum(r["verdict"] == v for r in results)
        for v in ("accepted", "rejected", "slow", "vulnerability")
    }
    total = len(results)
    lines = [
        "# 🐺 Lupus QA Report — adversarial run",
        "",
        f"🕒 **Generated:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}  ",
        f"🎯 **Server:** {server} (isolated instance)  ",
        f"🧠 **LLM:** {llm}  ",
        f"⏱️ **Total time:** {total_time:.1f}s",
        "",
        "## 📊 Summary",
        "",
        f"### {score_line(score)}",
        "",
        "```",
        bar((total - counts["vulnerability"]) / total if total else 0.0),
        "```",
        "",
        "| Verdict | Cases | Meaning |",
        "|---------|-------|---------|",
        f"| ✅ Accepted | `{counts['accepted']}` | Tool succeeded; hostile text stored verbatim |",
        f"| 🛡️ Rejected | `{counts['rejected']}` | Tool error — invalid input refused |",
        f"| 🐢 Slow | `{counts['slow']}` | Answered after more than {SLOW_SECONDS:g}s |",
        f"| 🚨 Vulnerability | `{counts['vulnerability']}` | Crash, protocol failure, leak or "
        "corruption |",
        "",
        "Score = cases without a vulnerability / total cases.",
        "",
    ]

    findings = [r for r in results if r["verdict"] in ("vulnerability", "slow")]
    if findings:
        lines.extend(
            [
                "## 🚨 Findings",
                "",
                "| Tool | Attack | Verdict | Detail |",
                "|------|--------|---------|--------|",
            ]
        )
        for r in findings:
            lines.append(f"| `{r['tool']}` | {r['why']} | {r['verdict']} | {r['reason'][:150]} |")
        lines.append("")
    else:
        lines.extend(["## ✅ No findings", "", "No crash, leak, corruption or slow response.", ""])

    tools = sorted({r["tool"] for r in results})
    lines.extend(
        [
            "## 🧰 Per tool",
            "",
            "| Tool | Accepted | Rejected | Slow | Vuln | Avg time |",
            "|------|----------|----------|------|------|----------|",
        ]
    )
    for tool in tools:
        rows = [r for r in results if r["tool"] == tool]
        avg = sum(r["elapsed_ms"] for r in rows) / len(rows)
        tally = {v: sum(r["verdict"] == v for r in rows) for v in counts}
        lines.append(
            f"| `{tool}` | {tally['accepted']} | {tally['rejected']} | {tally['slow']} "
            f"| {tally['vulnerability']} | `{avg:.0f}ms` |"
        )

    lines.extend(
        [
            "",
            "<details><summary>All cases</summary>",
            "",
            "| Tool | Attack | Verdict | Detail |",
            "|------|--------|---------|--------|",
            *(
                f"| `{r['tool']}` | {r['why'][:60]} | {r['verdict']} | "
                f"{(r['reason'] or '—')[:80].replace('|', '/')} |"
                for r in results
            ),
            "",
            "</details>",
            "",
            "---",
            "",
            "*Generated by 🐺 Lupus — universo MCP test suite*",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
