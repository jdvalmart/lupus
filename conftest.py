"""Shared fixtures for Lupus — isolated server, MCP client, call helpers, report hooks."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import pytest
from fastmcp import Client
from mcp.types import CallToolResult

from lupus_server import Server, server_from_config

LAYERS = ("protocol", "functional", "contracts", "persistence", "performance")

_run_start_time = 0.0
_test_results: list[dict[str, Any]] = []


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register Lupus CLI options."""
    parser.addoption("--server", default="orion", help="Server name from config.yaml")


# ---------------------------------------------------------------------------
# Server and client
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def server(request: pytest.FixtureRequest) -> Iterator[Server]:
    """The server under test, launched once per run with throwaway data."""
    target = server_from_config(request.config.getoption("--server"))
    target.start()
    try:
        yield target
    finally:
        target.cleanup()


@pytest.fixture
def requires_managed(server: Server) -> Server:
    """Skip tests that write data or restart the server when it is external."""
    if not server.managed:
        pytest.skip("needs a managed (isolated) server")
    return server


@pytest.fixture
async def mcp_client(server: Server) -> AsyncIterator[Client]:
    """MCP client connected to the server under test."""
    async with Client(server.url, auth=server.token) as client:
        yield client


@pytest.fixture
def project() -> str:
    """A project name unique to this test, so tests never see each other's data."""
    return f"lupus-{uuid.uuid4().hex[:10]}"


class Caller:
    """Tool-call helpers that work on structured output instead of prose."""

    def __init__(self, client: Client) -> None:
        self._client = client

    async def raw(self, name: str, args: dict[str, Any] | None = None) -> CallToolResult:
        """Call a tool and return the full result, errors included."""
        return await self._client.call_tool(name, args or {}, raise_on_error=False)

    async def ok(self, name: str, args: dict[str, Any] | None = None) -> Any:
        """Call a tool that must succeed; return its structured content."""
        result = await self.raw(name, args)
        assert not result.is_error, f"{name} failed: {text_of(result)}"
        if result.structured_content is None:
            return text_of(result)
        content = result.structured_content
        # FastMCP wraps non-object return values (lists, scalars) in {"result": ...}.
        if set(content) == {"result"}:
            return content["result"]
        return content

    async def error(self, name: str, args: dict[str, Any] | None = None) -> str:
        """Call a tool that must fail; return the error message (lowercased)."""
        result = await self.raw(name, args)
        assert result.is_error, f"{name} should have failed, got: {result.structured_content}"
        return text_of(result).lower()


def text_of(result: CallToolResult) -> str:
    """Concatenated text content of a tool result."""
    return "\n".join(getattr(block, "text", "") for block in result.content)


@pytest.fixture
def call(mcp_client: Client) -> Caller:
    """Tool-call helpers bound to the current client."""
    return Caller(mcp_client)


# ---------------------------------------------------------------------------
# Raw HTTP — protocol-level checks without session negotiation
# ---------------------------------------------------------------------------


def raw_request(
    url: str, method: str, params: dict[str, Any] | None, headers: dict[str, str]
) -> tuple[int, dict[str, Any]]:
    """POST one JSON-RPC message; return (HTTP status, decoded body or {})."""
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **headers,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status, body = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, body = exc.code, exc.read()
    try:
        return status, json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return status, {}


@pytest.fixture
def raw(server: Server) -> Callable[..., tuple[int, dict[str, Any]]]:
    """Authenticated sessionless JSON-RPC request helper."""

    def _call(
        method: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> tuple[int, dict[str, Any]]:
        return raw_request(
            server.url, method, params, server.headers if headers is None else headers
        )

    return _call


# ---------------------------------------------------------------------------
# Report generation — pytest hooks
# ---------------------------------------------------------------------------


def pytest_sessionstart(session: pytest.Session) -> None:
    """Record the start time of the run."""
    global _run_start_time
    _run_start_time = time.monotonic()


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Collect one result per test, including setup and teardown failures.

    pytest reports a failing fixture as outcome "failed" with when="setup";
    those are recorded as "error" so a dead server cannot look like a pass.
    """
    if report.when == "call":
        outcome = report.outcome
    elif report.when == "setup" and report.outcome != "passed":
        outcome = "error" if report.outcome == "failed" else report.outcome
    elif report.when == "teardown" and report.outcome == "failed":
        outcome = "error"
    else:
        return

    layer = next((mark for mark in LAYERS if mark in report.keywords), "unknown")
    _test_results.append(
        {
            "name": report.nodeid,
            "outcome": outcome,
            "duration": report.duration,
            "layer": layer,
            "error": report.longreprtext[:500] if report.longreprtext else "",
        }
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Write TEST_REPORT.md at the end of the run."""
    from report import generate_report

    global _test_results
    if _test_results:
        path = generate_report(_test_results, time.monotonic() - _run_start_time)
        print(f"\n  Test dossier: {path}")
    _test_results = []
