"""Shared fixtures for Lupus — MCP client, clean data, server helpers."""

import json
import time
import urllib.request
from pathlib import Path

import pytest
import yaml
from fastmcp import Client

CONFIG_PATH = Path(__file__).parent / "config.yaml"
_run_start_time: float = 0.0
_test_results: list[dict] = []


def pytest_addoption(parser):
    """Register custom CLI options for Lupus."""
    parser.addoption("--server", default="orion", help="Server name from config.yaml")


def load_config() -> dict:
    """Load the server registry from config.yaml."""
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


@pytest.fixture
def config() -> dict:
    """Server registry fixture."""
    return load_config()


@pytest.fixture
def server_config(request, config) -> dict:
    """Configuration for a specific server, defaulting to 'orion'."""
    name = request.config.getoption("--server", default="orion")
    return config["servers"][name]


@pytest.fixture
async def mcp_client(server_config) -> Client:
    """Async MCP client connected to the target server.

    Handles Streamable HTTP session negotiation automatically.
    """
    async with Client(server_config["url"]) as client:
        yield client


@pytest.fixture
def call(mcp_client):
    """Helper that calls a tool and extracts the text content.

    FastMCP wraps tool return values in CallToolResult objects.
    This fixture unwraps them so tests can assert on plain strings.
    """

    class Call:
        def __init__(self, client):
            self._client = client

        async def __call__(self, name: str, args: dict | None = None) -> str:
            result = await self._client.call_tool(name, args or {})
            content = getattr(result, "content", [])
            if content and hasattr(content[0], "text"):
                return content[0].text
            return str(result)

    return Call(mcp_client)


# ---------------------------------------------------------------------------
# Raw HTTP helper — for protocol-level tests that need no session
# ---------------------------------------------------------------------------

def _raw_mcp_request(url: str, method: str, params: dict | None = None) -> dict:
    """Send a raw JSON-RPC request without session negotiation.

    Used to verify protocol errors (missing session, unknown methods).
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or {},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8"))


@pytest.fixture
def raw(server_config):
    """Raw HTTP request helper — no session negotiation."""
    def _call(method: str, params: dict | None = None) -> dict:
        return _raw_mcp_request(server_config["url"], method, params)
    return _call


# ---------------------------------------------------------------------------
# Ollama client — local LLM for adversarial test generation
# ---------------------------------------------------------------------------

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2"


@pytest.fixture
def ollama():
    """Client for the local Ollama LLM used to generate test inputs."""

    def ask(prompt: str, timeout: int = 120) -> str:
        """Send a prompt to Ollama and return the response text."""
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

    return ask


@pytest.fixture
def llm_data(ollama):
    """Generate realistic test data via local LLM.

    Returns a callable that generates data from a prompt.
    Falls back to a default value if Ollama is unavailable or slow.
    """

    def generate(prompt: str, fallback: str = "test_data", timeout: int = 10) -> str:
        """Generate data via LLM with automatic fallback.

        Args:
            prompt: Instruction for the LLM.
            fallback: Value to use if LLM fails.
            timeout: Max seconds to wait for LLM response.

        Returns:
            LLM-generated string or fallback value.
        """
        try:
            resp = ollama(
                f"Respond ONLY with the requested data, nothing else. No quotes, no explanation: {prompt}",
                timeout=timeout,
            )
            if resp and "OLLAMA_ERROR" not in resp:
                cleaned = resp.strip().strip('"').strip("'")
                return cleaned[:200] if cleaned else fallback
            return fallback
        except Exception:
            return fallback

    return generate


# ---------------------------------------------------------------------------
# Report generation — pytest hooks
# ---------------------------------------------------------------------------

def pytest_sessionstart(session):
    """Record the start time of the test session."""
    global _run_start_time
    _run_start_time = time.monotonic()


def pytest_runtest_logreport(report):
    """Collect test results as they complete."""
    if report.when == "call" or report.when == "setup" and report.outcome == "error":
        layer = "unknown"
        for mark in report.keywords:
            if mark in ("protocol", "functional", "contracts", "persistence", "performance"):
                layer = mark
                break

        # Detect LLM usage from fixtures
        llm_used = False
        if hasattr(report, "funcargs") and "llm_data" in report.funcargs:
            llm_used = True
        if hasattr(report, "funcargs") and "ollama" in report.funcargs:
            llm_used = True

        duration = report.duration
        outcome = report.outcome  # passed, failed, skipped
        error = ""
        if report.longreprtext:
            error = report.longreprtext[:500]

        _test_results.append({
            "name": report.nodeid,
            "outcome": outcome,
            "duration": duration,
            "layer": layer,
            "error": error,
            "llm_used": llm_used,
        })


def pytest_sessionfinish(session, exitstatus):
    """Generate the test dossier at the end of the session."""
    from report import generate_report

    global _test_results
    total_time = time.monotonic() - _run_start_time
    any_llm = any(r.get("llm_used") for r in _test_results)

    if _test_results:
        report_path = generate_report(_test_results, total_time, llm_used=any_llm)
        print(f"\n  Test dossier: {report_path}")

    _test_results = []
