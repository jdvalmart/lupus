#!/usr/bin/env bash
# Lupus — Test runner script
# Usage:
#   ./run_tests.sh              # Run all tests
#   ./run_tests.sh --layer functional  # Run specific layer
#   ./run_tests.sh --attack     # Run adversarial attack (needs Ollama)
#   ./run_tests.sh --report     # Show latest report

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate venv
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "ERROR: .venv not found. Run: python -m venv .venv && pip install -r requirements.txt"
    exit 1
fi

# Ensure we're using the venv python
PYTHON="$(pwd)/.venv/bin/python"

# Parse args
LAYER=""
ATTACK=false
REPORT_ONLY=false
VERBOSE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --layer|-l)
            LAYER="$2"
            shift 2
            ;;
        --attack|-a)
            ATTACK=true
            shift
            ;;
        --report|-r)
            REPORT_ONLY=true
            shift
            ;;
        --verbose|-v)
            VERBOSE="-v"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: ./run_tests.sh [--layer <name>] [--attack] [--report] [--verbose]"
            exit 1
            ;;
    esac
done

# Report only
if [ "$REPORT_ONLY" = true ]; then
    if [ -f "TEST_REPORT.md" ]; then
        cat TEST_REPORT.md
    else
        echo "No report found. Run tests first: ./run_tests.sh"
    fi
    exit 0
fi

# Adversarial attack
if [ "$ATTACK" = true ]; then
    echo "Running adversarial attack..."
    $PYTHON lupus_cli.py attack
    exit $?
fi

# Check Orion is running
if ! curl -s http://localhost:9099/mcp -o /dev/null 2>/dev/null; then
    echo "WARNING: Orion not responding on port 9099"
    echo "Start it: systemctl --user start orion"
    echo ""
fi

# Run tests
echo "Running Lupus test suite..."
echo "==========================="

if [ -n "$LAYER" ]; then
    $PYTHON -m pytest test_orion/ -m "$LAYER" $VERBOSE
else
    $PYTHON -m pytest test_orion/ $VERBOSE
fi
