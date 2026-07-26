"""Lupus — CLI for the universo test suite.

Commands:
  run      Execute pytest layers against registered servers.
  attack   Run AI-powered adversarial tests via local LLM.
  report   Display the latest QA report.
"""

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent


def cmd_run(args) -> None:
    """Execute the test suite."""
    cmd = [sys.executable, "-m", "pytest"]

    if args.server:
        cmd.extend(["--server", args.server])

    if args.layer:
        layers = args.layer.split(",")
        marks = " or ".join(l.strip() for l in layers)
        cmd.extend(["-m", marks])

    if args.verbose:
        cmd.append("-v")

    if args.fail_fast:
        cmd.append("-x")

    if args.quiet:
        cmd.append("-q")

    cmd.append(str(PROJECT_DIR))

    result = subprocess.run(cmd, cwd=str(PROJECT_DIR))
    sys.exit(result.returncode)


def cmd_attack(args) -> None:
    """Run AI-powered adversarial testing."""
    import asyncio
    from attacker import run_adversarial

    asyncio.run(run_adversarial(
        count=args.count,
        tools=args.tools.split(",") if args.tools else None,
        server_url=args.server,
    ))


def cmd_report(args) -> None:
    """Display the latest QA report."""
    report_path = PROJECT_DIR / "QA_REPORT.md"
    if not report_path.exists():
        print("No QA report found. Run `lupus attack` first.")
        sys.exit(1)

    content = report_path.read_text(encoding="utf-8")
    print(content)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="lupus",
        description="Test suite for the universo MCP ecosystem.",
    )
    sub = parser.add_subparsers(dest="command")

    # run
    run_parser = sub.add_parser("run", help="Execute test layers (protocol, functional, contracts, etc.)")
    run_parser.add_argument("--server", default="orion", help="Server name from config.yaml")
    run_parser.add_argument("--layer", help="Layer(s) to run: protocol,functional,contracts,persistence,performance")
    run_parser.add_argument("-v", "--verbose", action="store_true")
    run_parser.add_argument("-x", "--fail-fast", action="store_true")
    run_parser.add_argument("-q", "--quiet", action="store_true")

    # attack
    attack_parser = sub.add_parser("attack", help="Run AI adversarial tests via local LLM")
    attack_parser.add_argument("--count", type=int, default=4, help="Inputs generated per tool (default: 4)")
    attack_parser.add_argument("--tools", help="Comma-separated tool names (default: all)")
    attack_parser.add_argument("--server", default="orion", help="Server name from config.yaml")

    # report
    sub.add_parser("report", help="Show the latest QA_REPORT.md")

    args = parser.parse_args()

    if args.command == "run":
        cmd_run(args)
    elif args.command == "attack":
        cmd_attack(args)
    elif args.command == "report":
        cmd_report(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
