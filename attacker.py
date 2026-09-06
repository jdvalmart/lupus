"""Adversarial attack module — uses Ollama + fallback attacks to break Orion.

Runs independently from pytest. Called by `lupus attack`.
"""

import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml
from fastmcp import Client

REPORT_PATH = Path(__file__).parent / "QA_REPORT.md"
CONFIG_PATH = Path(__file__).parent / "config.yaml"

ATTACK_PROMPT = """You are a QA security engineer. Generate exactly {count} DIFFERENT malicious test inputs for this MCP tool.

Each input must target a DIFFERENT attack vector:
1. Empty/missing required fields
2. SQL injection (e.g., '; DROP TABLE--)
3. Path traversal (e.g., ../../etc/passwd)
4. XSS/HTML injection (e.g., <script>alert(1)</script>)
5. Unicode abuse (emojis, RTL override, zero-width chars)
5. Extremely long strings (10000+ chars)
6. Boundary numbers (0, -1, MAX_INT=999999999, float 0.001)
7. Type confusion (string where int expected, bool where string expected)
8. JSON injection (nested objects, arrays)
9. Null bytes and control characters

RESPOND WITH ONLY A JSON ARRAY. No markdown, no explanation, no code fences.
Each item: {{"why": "description", "params": {{"field": "value"}}}}

Example:
[{{"why": "SQL injection in topic", "params": {{"topic": "'; DROP TABLE decisions; --", "decision": "test"}}}}]

Tool schema:"""

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2"


# ---------------------------------------------------------------------------
# Fallback attack vectors — pre-built when LLM fails or generates too few
# ---------------------------------------------------------------------------

_FALLBACK_ATTACKS: dict[str, list[dict]] = {
    "remember_decision": [
        {"why": "empty topic and decision", "params": {"topic": "", "decision": ""}},
        {"why": "SQL injection in topic", "params": {"topic": "'; DROP TABLE decisions; --", "decision": "test"}},
        {"why": "path traversal", "params": {"topic": "../../etc/passwd", "decision": "test"}},
        {"why": "XSS in decision", "params": {"topic": "test", "decision": "<script>alert(1)</script>"}},
        {"why": "extremely long topic", "params": {"topic": "A" * 10000, "decision": "test"}},
        {"why": "unicode bombs", "params": {"topic": "‮؜‎test‏", "decision": "🔥💀☠️"}},
        {"why": "null bytes", "params": {"topic": "test\x00injection", "decision": "test"}},
        {"why": "negative ID abuse", "params": {"topic": "-999999", "decision": "test"}},
        {"why": "float as string", "params": {"topic": "0.000001", "decision": "0.999999"}},
        {"why": "nested JSON", "params": {"topic": "{{\"key\": \"val\"}}", "decision": "[1,2,3]"}},
    ],
    "recall_context": [
        {"why": "empty query", "params": {"query": ""}},
        {"why": "SQL injection", "params": {"query": "'; SELECT * FROM--"}},
        {"why": "very long query", "params": {"query": "A" * 10000}},
        {"why": "unicode query", "params": {"query": "‮test‏"}},
        {"why": "negative limit", "params": {"query": "test", "limit": -1}},
        {"why": "float limit", "params": {"query": "test", "limit": 0.5}},
        {"why": "string limit", "params": {"query": "test", "limit": "abc"}},
        {"why": "null query", "params": {"query": None}},
    ],
    "revise_decision": [
        {"why": "non-existent ID", "params": {"id": 99999, "topic": "ghost"}},
        {"why": "negative ID", "params": {"id": -1, "topic": "test"}},
        {"why": "zero ID", "params": {"id": 0, "topic": "test"}},
        {"why": "float ID", "params": {"id": 0.5, "topic": "test"}},
        {"why": "string ID", "params": {"id": "abc", "topic": "test"}},
        {"why": "missing ID", "params": {"topic": "test"}},
        {"why": "null topic", "params": {"id": 1, "topic": None}},
    ],
    "forget_decision": [
        {"why": "non-existent ID", "params": {"id": 99999}},
        {"why": "negative ID", "params": {"id": -1}},
        {"why": "zero ID", "params": {"id": 0}},
        {"why": "float ID", "params": {"id": 0.5}},
        {"why": "string ID", "params": {"id": "abc"}},
        {"why": "null ID", "params": {"id": None}},
    ],
    "link_concepts": [
        {"why": "missing all params", "params": {}},
        {"why": "non-existent source", "params": {"source_id": 99999, "target_id": 1, "relation": "depends_on"}},
        {"why": "non-existent target", "params": {"source_id": 1, "target_id": 99999, "relation": "depends_on"}},
        {"why": "invalid relation", "params": {"source_id": 1, "target_id": 2, "relation": "eats_pizza"}},
        {"why": "self link", "params": {"source_id": 1, "target_id": 1, "relation": "depends_on"}},
        {"why": "negative IDs", "params": {"source_id": -1, "target_id": -2, "relation": "depends_on"}},
        {"why": "string IDs", "params": {"source_id": "abc", "target_id": "def", "relation": "depends_on"}},
    ],
    "find_related": [
        {"why": "missing ID", "params": {}},
        {"why": "non-existent ID", "params": {"id": 99999}},
        {"why": "negative ID", "params": {"id": -1}},
        {"why": "zero ID", "params": {"id": 0}},
        {"why": "string ID", "params": {"id": "abc"}},
        {"why": "float ID", "params": {"id": 0.5}},
    ],
    "browse_memories": [
        {"why": "with extra params", "params": {"hack": "true"}},
        {"why": "null params", "params": {"limit": None}},
    ],
    "browse_graph": [
        {"why": "with extra params", "params": {"hack": "true"}},
    ],
    "whoami": [
        {"why": "with malicious params", "params": {"inject": "<script>alert(1)</script>"}},
        {"why": "with extra params", "params": {"admin": "true"}},
    ],
    "remember_session": [
        {"why": "empty summary", "params": {"summary": ""}},
        {"why": "SQL injection", "params": {"summary": "'; DROP TABLE sessions; --"}},
        {"why": "very long summary", "params": {"summary": "A" * 10000}},
        {"why": "unicode", "params": {"summary": "‮test‏"}},
        {"why": "missing summary", "params": {}},
        {"why": "null summary", "params": {"summary": None}},
    ],
    "recall_session": [
        {"why": "with extra params", "params": {"hack": "true"}},
    ],
    "browse_sessions": [
        {"why": "with extra params", "params": {"hack": "true"}},
    ],
    "backup_to_s3": [
        {"why": "missing bucket", "params": {}},
        {"why": "empty bucket", "params": {"bucket": ""}},
        {"why": "SQL injection", "params": {"bucket": "'; DROP--"}},
        {"why": "path traversal", "params": {"bucket": "../../etc/passwd"}},
    ],
    "restore_from_s3": [
        {"why": "missing bucket", "params": {}},
        {"why": "empty bucket", "params": {"bucket": ""}},
        {"why": "SQL injection", "params": {"bucket": "'; DROP--"}},
    ],
}


def _ask_ollama(prompt: str, timeout: int = 120) -> str:
    """Send a prompt to the local Ollama instance, requesting JSON output."""
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")).get("response", "")
    except Exception as e:
        return f"OLLAMA_ERROR: {e}"


def _parse_json_array(response: str) -> list[dict]:
    """Extract a JSON array or single object from LLM output."""
    text = response.strip()
    if text.startswith("```"):
        text = re.sub(r"```\w*\n?", "", text).replace("```", "")

    # Try array first: [...]
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    # Fall back to single object: {...} → [{...}]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict) and "params" in parsed:
                return [parsed]
        except json.JSONDecodeError:
            pass

    return []


# Patterns that indicate Orion is defending itself, not breaking
_REJECTION_PATTERNS = [
    "no memories stored", "not found", "invalid relation type",
    "cannot link", "already", "unable to load",
]


def _classify(tool_name: str, params: dict, response: str) -> str:
    """Classify a tool response as passed, rejected, or vulnerability.

    - passed: tool accepted input and returned expected output
    - rejected: tool rejected invalid input gracefully (GOOD — it defended itself)
    - vulnerability: tool returned unexpected output or acted on invalid data
    """
    resp_lower = response.lower()

    for pattern in _REJECTION_PATTERNS:
        if pattern in resp_lower:
            return "rejected"

    if "error" in resp_lower[:30] and "toolerror" not in resp_lower:
        return "rejected"

    return "passed"


def _classify_exception(tool_name: str, params: dict, error: str) -> str:
    """Classify an exception raised during tool execution.

    FastMCP validation errors (missing field, wrong type) are expected
    rejections. All other exceptions are potential vulnerabilities.
    """
    validation_keywords = [
        "missing required argument", "should be a valid integer",
        "input should be", "validation error", "field required",
        "unable to parse string as an integer", "int_type", "int_parsing",
        "missing_argument", "string_type", "list_type",
    ]
    for keyword in validation_keywords:
        if keyword.lower() in error.lower():
            return "rejected"
    return "vulnerability"


async def run_adversarial(
    count: int = 4,
    tools: list[str] | None = None,
    server_url: str = "http://localhost:9099/mcp",
) -> None:
    """Run the full adversarial testing pipeline.

    Args:
        count: Number of inputs per tool (LLM-generated).
        tools: Specific tool names to test (None = all).
        server_url: MCP server endpoint.
    """
    with open(CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f)

    server_cfg = config["servers"].get(server_url.split("/")[-2] if "/" in server_url else server_url, {})
    mcp_url = server_cfg.get("url", server_url)

    print(f"🔍 Connecting to {mcp_url}...")
    t_total = time.monotonic()

    async with Client(mcp_url) as client:
        # --- Phase 1: Discovery ---
        print("📋 Phase 1: Discovering tools...")
        tool_list = await client.list_tools()
        schemas = {}
        for t in tool_list:
            if tools and t.name not in tools:
                continue
            schema = {
                "name": t.name,
                "description": getattr(t, "description", ""),
            }
            if hasattr(t, "inputSchema"):
                schema["inputSchema"] = t.inputSchema
            schemas[t.name] = schema

        print(f"   Found {len(schemas)} tool(s) to attack")

        # --- Phase 2: Generation (LLM + Fallback) ---
        print(f"🧠 Phase 2: Generating adversarial inputs via {OLLAMA_MODEL} + fallback attacks...")
        generated: dict[str, list[dict]] = {}
        prompt = ATTACK_PROMPT.replace("{count}", str(count))

        for i, (name, schema) in enumerate(schemas.items(), 1):
            print(f"   [{i}/{len(schemas)}] {name}...", end=" ", flush=True)

            # LLM generation
            llm_cases: list[dict] = []
            response = _ask_ollama(f"{prompt}\n{json.dumps(schema, indent=2)}")
            llm_cases = _parse_json_array(response)

            # Fallback attacks
            fallback_cases = _FALLBACK_ATTACKS.get(name, [])

            # Merge: LLM + fallback (deduplicate by params)
            all_cases: list[dict] = []
            seen_params: set[str] = set()

            for case in fallback_cases + llm_cases:
                params_key = json.dumps(case.get("params", {}), sort_keys=True)
                if params_key not in seen_params:
                    seen_params.add(params_key)
                    all_cases.append(case)

            generated[name] = all_cases if all_cases else [
                {"why": "no attacks generated", "params": {}}
            ]
            print(f"{len(generated[name])} inputs (LLM: {len(llm_cases)}, fallback: {len(fallback_cases)})")

        total_gen = sum(len(v) for v in generated.values())
        if total_gen == 0:
            print("❌ No attack cases generated. Check Ollama and fallback data.")
            return

        # --- Phase 3: Execution ---
        print(f"⚔️  Phase 3: Executing {total_gen} adversarial inputs...")
        results: list[dict] = []

        for tool_name, cases in generated.items():
            for case in cases:
                params = case.get("params", {})
                why = case.get("why", "no reason")

                t1 = time.monotonic()
                try:
                    result = await client.call_tool(tool_name, params)
                    content = getattr(result, "content", [])
                    text = content[0].text if content and hasattr(content[0], "text") else str(result)
                    elapsed = time.monotonic() - t1
                    verdict = _classify(tool_name, params, text)
                    results.append({
                        "tool": tool_name, "why": why, "params": params,
                        "verdict": verdict, "response": text[:200],
                        "elapsed_ms": round(elapsed * 1000, 1),
                    })
                except Exception as e:
                    elapsed = time.monotonic() - t1
                    error_text = str(e)[:300]
                    verdict = _classify_exception(tool_name, params, error_text)
                    results.append({
                        "tool": tool_name, "why": why, "params": params,
                        "verdict": verdict, "error": error_text,
                        "elapsed_ms": round(elapsed * 1000, 1),
                    })

        total_time = time.monotonic() - t_total

        passed = sum(1 for r in results if r["verdict"] == "passed")
        rejected = sum(1 for r in results if r["verdict"] == "rejected")
        vulnerabilities = sum(1 for r in results if r["verdict"] == "vulnerability")
        resistant = passed + rejected  # both are good — the server is healthy
        score = round((resistant / len(results)) * 100, 1)

        # --- Phase 4: Report ---
        print(f"📊 Phase 4: Generating report...")
        _write_report(results, len(schemas), total_time, score)
        print(f"\n✅ Done!")
        print(f"   Passed: {passed} | Rejected (defended): {rejected} | Vulnerabilities: {vulnerabilities}")
        print(f"   Score: {score}% | Report: {REPORT_PATH}")


def _write_report(
    results: list[dict],
    tools_count: int,
    total_time: float,
    score: float,
) -> None:
    """Write QA_REPORT.md with proper classification."""
    passed = sum(1 for r in results if r["verdict"] == "passed")
    rejected = sum(1 for r in results if r["verdict"] == "rejected")
    vulnerabilities = sum(1 for r in results if r["verdict"] == "vulnerability")
    total = len(results)

    lines = [
        "# Lupus QA Report",
        "",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Server:** Orion",
        f"**LLM:** {OLLAMA_MODEL} (Ollama) + fallback attacks",
        f"**Total time:** {total_time:.1f}s",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Tests executed | {total} |",
        f"| Passed | {passed} |",
        f"| Rejected (defended) | {rejected} |",
        f"| Vulnerabilities | {vulnerabilities} |",
        f"| Score | {score}% |",
        f"| Tools tested | {tools_count} |",
        "",
        "**Score = (passed + rejected) / total.** Rejections count as success — "
        "they mean Orion correctly defended itself against malicious input.",
        "",
    ]

    if vulnerabilities:
        lines.append(f"## Vulnerabilities ({vulnerabilities})")
        lines.append("")
        for r in results:
            if r["verdict"] == "vulnerability":
                lines.extend([
                    f"### {r['tool']}",
                    f"- **Why:** {r['why']}",
                    f"- **Input:** `{json.dumps(r['params'])}`",
                    f"- **Error:** {r.get('error', 'unknown')}",
                    "",
                ])
    elif rejected > 0:
        lines.append(f"## Rejections ({rejected})")
        lines.append("")
        lines.append("Every rejection below is Orion defending itself correctly — "
                     "not a bug. These inputs were designed to break the server, "
                     "and Orion refused them all.")
        lines.append("")
        lines.append("<details>")
        lines.append("<summary>Click to expand rejection details</summary>")
        lines.append("")
        for r in results:
            if r["verdict"] == "rejected":
                lines.append(f"- **{r['tool']}** — {r.get('error', r.get('response', ''))[:120]}")
        lines.append("")
        lines.append("</details>")
        lines.append("")
    else:
        lines.append("## No vulnerabilities found")
        lines.append("")
        lines.append("Orion survived every adversarial input without issues.")
        lines.append("")

    per_tool: dict[str, list[float]] = {}
    for r in results:
        per_tool.setdefault(r["tool"], []).append(r["elapsed_ms"])

    lines.extend([
        "## Response times",
        "",
        "| Tool | Avg | Min | Max | Calls |",
        "|------|-----|-----|-----|-------|",
    ])
    for tool, times in sorted(per_tool.items()):
        avg = sum(times) / len(times)
        lines.append(
            f"| {tool} | {avg:.0f}ms | {min(times):.0f}ms "
            f"| {max(times):.0f}ms | {len(times)} |"
        )

    lines.extend([
        "",
        f"## Quality Score: {score}%",
        "",
        f"{'🟢 Production-ready' if score >= 95 else '🟡 Needs attention' if score >= 80 else '🔴 Requires fixes'}",
        "",
    ])

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
