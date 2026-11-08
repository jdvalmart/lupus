"""Server lifecycle for Lupus — launch an isolated instance of the server under test.

A managed server gets a fresh temporary data directory, a random bearer token
and a free port, so tests and attacks can never touch real data. External
servers (``url`` in config.yaml, no ``command``) are supported for read-only
checks against something already running.
"""

from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PROJECT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_DIR / "config.yaml"


def load_config() -> dict[str, Any]:
    """Load the server registry."""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class Server:
    """A server under test: either launched by Lupus or already running."""

    name: str
    tools: list[str]
    url: str = ""
    token: str | None = None
    command: list[str] | None = None
    env: dict[str, str] = field(default_factory=dict)
    data_env: str | None = None
    token_env: str | None = None
    port_arg: str = "--port"
    data_dir: Path | None = None
    _process: subprocess.Popen[bytes] | None = None
    _port: int | None = None
    _log: Path | None = None

    @property
    def managed(self) -> bool:
        return self.command is not None

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def start(self) -> None:
        """Launch the server (no-op for external servers) and wait until it answers."""
        if not self.managed:
            return
        assert self.command is not None
        if self.data_dir is None:
            self.data_dir = Path(tempfile.mkdtemp(prefix=f"lupus-{self.name}-"))
        if self._port is None:
            self._port = _free_port()
        if self.token_env and self.token is None:
            self.token = secrets.token_urlsafe(24)

        env = {k: v for k, v in os.environ.items() if not k.startswith("ORION_")}
        env.update(self.env)
        if self.data_env:
            env[self.data_env] = str(self.data_dir)
        if self.token_env and self.token:
            env[self.token_env] = self.token

        executable = (PROJECT_DIR / self.command[0]).resolve()
        if not executable.exists():
            raise RuntimeError(
                f"{self.name}: command not found: {executable}. "
                "Install the server first (see README)."
            )
        self._log = self.data_dir / "server.log"
        with open(self._log, "ab") as log:
            self._process = subprocess.Popen(
                [str(executable), *self.command[1:], self.port_arg, str(self._port)],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=self.data_dir,
            )
        self.url = f"http://127.0.0.1:{self._port}/mcp"
        self._wait_ready()

    def _wait_ready(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._process is not None and self._process.poll() is not None:
                raise RuntimeError(f"{self.name} exited early:\n{self.log_tail()}")
            try:
                urllib.request.urlopen(self.url, timeout=1)
                return
            except urllib.error.HTTPError:
                return  # any HTTP answer (401, 405, 406…) means it is listening
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                time.sleep(0.2)
        raise RuntimeError(f"{self.name} did not start within {timeout}s:\n{self.log_tail()}")

    def stop(self) -> None:
        """Terminate the managed process, keeping its data directory."""
        if self._process is None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
        self._process = None

    def restart(self) -> None:
        """Stop and start again on the same port and data directory."""
        if not self.managed:
            raise RuntimeError("Cannot restart an external server.")
        self.stop()
        self.start()

    def cleanup(self) -> None:
        """Stop the server and delete its temporary data."""
        self.stop()
        if self.managed and self.data_dir is not None:
            shutil.rmtree(self.data_dir, ignore_errors=True)

    def log_tail(self, lines: int = 30) -> str:
        if self._log is None or not self._log.exists():
            return ""
        return "\n".join(self._log.read_text(errors="replace").splitlines()[-lines:])

    def alive(self) -> bool:
        """Whether a managed process is still running (external: assume yes)."""
        return self._process is None or self._process.poll() is None


def server_from_config(name: str) -> Server:
    """Build a Server from its config.yaml entry."""
    servers = load_config()["servers"]
    if name not in servers:
        raise KeyError(f"Unknown server '{name}'. Known: {', '.join(servers)}")
    entry = servers[name]
    return Server(
        name=name,
        tools=entry.get("tools", []),
        url=entry.get("url", ""),
        token=os.environ.get(entry["token_from"]) if entry.get("token_from") else None,
        command=entry.get("command"),
        env={k: str(v) for k, v in (entry.get("env") or {}).items()},
        data_env=entry.get("data_env"),
        token_env=entry.get("token_env"),
        port_arg=entry.get("port_arg", "--port"),
    )
