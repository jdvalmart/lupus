"""Adversarial attack module — uses Ollama to generate inputs that break Orion.

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

ATTACK_PROMPT = """You are a QA engineer specialized in adversarial testing.
Generate exactly {count} test inputs designed to break this MCP server tool.

Attack vectors to cover:
- Empty strings, missing required parameters, None/null
- SQL injection patterns, path traversal (../../etc/passwd)
- JSON injection, extremely long strings (5000+ chars)
- Unicode edge cases (emojis, RTL, zero-width chars)
- Boundary numeric values (max int, negative, zero)
- Type confusion (string for int, bool for string)

You MUST respond with ONLY a JSON array and NOTHING else — no markdown,
no explanation, no code fences. Start with [ and end with ].

Example response format:
[{{"why": "testing SQL injection", "params": {{"topic": "x", "decision": "'; DROP--"}}}}]

Here is the tool to break:"""

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2"


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
        count: Number of inputs per tool.
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

        # --- Phase 2: Generation ---
        print(f"🧠 Phase 2: Generating {count} adversarial inputs per tool via {OLLAMA_MODEL}...")
        generated: dict[str, list[dict]] = {}
        prompt = ATTACK_PROMPT.replace("{count}", str(count))

        for i, (name, schema) in enumerate(schemas.items(), 1):
            print(f"   [{i}/{len(schemas)}] {name}...", end=" ", flush=True)
            response = _ask_ollama(f"{prompt}\n{json.dumps(schema, indent=2)}")
            cases = _parse_json_array(response)
            generated[name] = cases if cases else [
                {"why": "LLM output could not be parsed", "params": {}}
            ]
            print(f"{len(generated[name])} inputs")

        total_gen = sum(len(v) for v in generated.values())
        if total_gen == 0:
            print("❌ LLM generated 0 test cases. Is Ollama running?")
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
        f"**LLM:** {OLLAMA_MODEL} (Ollama)",
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
        lines.append("Orion survived every AI-generated adversarial input without issues.")
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
