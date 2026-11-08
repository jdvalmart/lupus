"""Lupus — CLI for the universo test suite.

Commands:
  run      Execute the pytest layers against an isolated server instance.
  attack   Run adversarial testing (built-in corpus + optional local LLM).
  report   Show the latest TEST_REPORT.md or QA_REPORT.md.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
LAYERS = ("protocol", "functional", "contracts", "persistence", "performance")


def cmd_run(args: argparse.Namespace) -> int:
    """Execute the test suite."""
    cmd = [sys.executable, "-m", "pytest", "--server", args.server]
    if args.layer:
        layers = [layer.strip() for layer in args.layer.split(",")]
        unknown = set(layers) - set(LAYERS)
        if unknown:
            sys.exit(f"Unknown layer(s): {', '.join(sorted(unknown))}. Valid: {', '.join(LAYERS)}")
        cmd.extend(["-m", " or ".join(layers)])
    if args.verbose:
        cmd.append("-v")
    if args.fail_fast:
        cmd.append("-x")
    if args.quiet:
        cmd.append("-q")
    return subprocess.run(cmd, cwd=PROJECT_DIR).returncode


def cmd_attack(args: argparse.Namespace) -> int:
    """Run adversarial testing; exit code 1 when vulnerabilities are found."""
    from attacker import run_adversarial

    tools = [t.strip() for t in args.tools.split(",")] if args.tools else None
    score = asyncio.run(run_adversarial(count=args.count, tools=tools, server_name=args.server))
    return 0 if score == 100 else 1


def cmd_report(args: argparse.Namespace) -> int:
    """Print the latest report."""
    path = PROJECT_DIR / ("QA_REPORT.md" if args.qa else "TEST_REPORT.md")
    if not path.exists():
        print(f"No {path.name} yet. Run `lupus {'attack' if args.qa else 'run'}` first.")
        return 1
    print(path.read_text(encoding="utf-8"))
    return 0


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        prog="lupus", description="Test suite for the universo MCP ecosystem."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Execute test layers")
    run.add_argument("--server", default="orion", help="Server name from config.yaml")
    run.add_argument("--layer", help=f"Comma-separated layers: {', '.join(LAYERS)}")
    run.add_argument("-v", "--verbose", action="store_true")
    run.add_argument("-x", "--fail-fast", action="store_true")
    run.add_argument("-q", "--quiet", action="store_true")
    run.set_defaults(func=cmd_run)

    attack = sub.add_parser("attack", help="Adversarial testing on an isolated instance")
    attack.add_argument("--count", type=int, default=4, help="LLM cases per tool (default: 4)")
    attack.add_argument("--tools", help="Comma-separated tool names (default: all)")
    attack.add_argument("--server", default="orion", help="Server name from config.yaml")
    attack.set_defaults(func=cmd_attack)

    report = sub.add_parser("report", help="Show the latest report")
    report.add_argument("--qa", action="store_true", help="Show QA_REPORT.md (attack run)")
    report.set_defaults(func=cmd_report)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
