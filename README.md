# Lupus

Test suite for the universo MCP ecosystem. The wolf that hunts bugs.

## Install

```bash
cd universo/lupus
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Run

```bash
pytest -v                          # all tests
pytest -v -k "protocol"            # only protocol
pytest -v -k "functional"          # only functional
pytest -v -k "performance"         # only performance
pytest test_orion/ -v              # only Orion
pytest test_shared/ -v             # universal compliance
```

## Layers

| Layer | Mark | What it tests |
|-------|------|---------------|
| 1 — Protocol | `protocol` | Does the server speak valid MCP? |
| 2 — Functional | `functional` | Does each tool do what it claims? |
| 3 — Contracts | `contracts` | Does it survive invalid/malicious inputs? |
| 4 — Persistence | `persistence` | Does it survive file corruption? |
| 5 — Performance | `performance` | Does it scale without degrading? |
| Universal | `protocol` | Same as Layer 1 but for ANY server |

## Structure

```
lupus/
├── pyproject.toml           # pytest, fastmcp, pyyaml
├── config.yaml              # server registry
├── conftest.py              # MCP client fixtures
├── test_orion/              # Orion-specific tests
│   ├── test_protocol.py
│   ├── test_functional.py
│   ├── test_contracts.py
│   ├── test_persistence.py
│   └── test_performance.py
├── test_shared/             # Universal MCP compliance
│   └── test_mcp_compliance.py
└── README.md
```
