#!/usr/bin/env bash
# Lupus — convenience wrapper around lupus_cli.py
# Usage:
#   ./run_tests.sh                      # all layers (isolated Orion instance)
#   ./run_tests.sh --layer functional   # one layer
#   ./run_tests.sh --attack             # adversarial run (Ollama optional)
#   ./run_tests.sh --report             # latest TEST_REPORT.md
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
PYTHON=".venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    echo "ERROR: .venv missing. Run: uv venv && uv pip install -e ." >&2
    exit 1
fi

case "${1:-}" in
    --attack|-a) shift; exec "$PYTHON" lupus_cli.py attack "$@" ;;
    --report|-r) shift; exec "$PYTHON" lupus_cli.py report "$@" ;;
    *)           exec "$PYTHON" lupus_cli.py run "$@" ;;
esac
