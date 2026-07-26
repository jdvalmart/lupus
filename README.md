<p align="center">
  <img src="docs/assets/logo.svg" width="120" alt="Lupus">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-blue.svg?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/pytest-8+-0A9EDC.svg?logo=pytest&logoColor=white" alt="Pytest">
  <img src="https://img.shields.io/badge/tests-36_green-green.svg" alt="Tests">
  <img src="https://img.shields.io/badge/layers-5-purple.svg" alt="Layers">
  <img src="https://img.shields.io/badge/llm-llama3.2-orange.svg?logo=ollama&logoColor=white" alt="Llama">
  <img src="https://img.shields.io/badge/orion_score-100%25-brightgreen.svg" alt="Orion">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey.svg" alt="License">
</p>

---

<br>

Test suite for the **universo** MCP ecosystem. Validates servers at the protocol,
functional, contract, persistence, and performance level — plus AI-powered
adversarial testing via local LLM.

 <br>

|  Protocol |  Functional |  Contracts |  Persistence |  Performance |  AI Attack |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 7 tests | 13 tests | 10 tests | 3 tests | 5 tests | llama3.2 |

<br>

---

```mermaid
graph TD
    subgraph Lupus["Lupus"]
        CLI["  CLI<br/>run · attack · report"]

        subgraph Layers["  5 Test Layers"]
            P["  Protocol"]
            F["  Functional"]
            C["  Contracts"]
            PE["  Persistence"]
            PF["  Performance"]
        end

        AI["  AI Adversarial<br/>llama3.2 via Ollama"]
    end

    subgraph Targets["  Targets"]
        O["  Orion :9099"]
        V["  Vela"]
        D["  Draco"]
    end

    REP["  QA_REPORT.md"]

    CLI --> Layers
    CLI --> AI
    Layers --> O
    Layers -.-> V
    Layers -.-> D
    AI --> O
    Layers --> REP
    AI --> REP
```

##   Quick start

```bash
# Clone & install
git clone https://github.com/jdvalmart/lupus && cd lupus
python -m venv .venv && source .venv/bin/activate
pip install pytest pytest-asyncio fastmcp pyyaml pydantic

# Make sure Orion is running
systemctl --user start orion

# Run the suite
python lupus_cli.py run -v

# AI-powered attack (needs Ollama)
ollama pull llama3.2
python lupus_cli.py attack
```

##   CLI commands

```bash
python lupus_cli.py run                    #   All 5 layers (36 tests)
python lupus_cli.py run --layer contracts  #   Single layer
python lupus_cli.py run -v -x              #   Verbose, stop on first failure

python lupus_cli.py attack                 #   AI adversarial (all 12 tools)
python lupus_cli.py attack --count 10      #   10 inputs per tool
python lupus_cli.py attack --tools recall  #   Specific tools only

python lupus_cli.py report                 #   Latest QA_REPORT.md
```

##   Getting started (step by step)

###  Prerequisites

| Requirement | How to check |
|-------------|--------------|
| Python 3.11+ | `python --version` |
| Orion running | `systemctl --user status orion` |
| Ollama (optional) | `ollama list` |

###  1. Clone and install

```bash
cd ~/Documentos/GitHub/universo
git clone https://github.com/jdvalmart/lupus
cd lupus
python -m venv .venv
source .venv/bin/activate
pip install pytest pytest-asyncio fastmcp pyyaml pydantic
```

###  2. Verify Orion is reachable

```bash
curl -s http://localhost:9099/mcp -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | head -c 100
```

###  3. Run the standard suite

```bash
python lupus_cli.py run -v
# Expected: 36 passed in ~15s
```

###  4. Run an adversarial attack (optional)

```bash
# Terminal 1: ollama serve
# Terminal 2:
python lupus_cli.py attack --tools whoami,recall_context --count 3
```

###  5. View the quality report

```bash
python lupus_cli.py report
# Or: cat QA_REPORT.md
```

###  Common issues

|  Problem |  Solution |
|---------|----------|
| `Connection refused` | Start Orion: `systemctl --user start orion` |
| `Missing session ID` | Orion must run HTTP mode: `python server.py --transport http` |
| `Ollama not running` | `ollama serve` in another terminal |
| `Module not found` | `source .venv/bin/activate` |
| `No QA report found` | Run `python lupus_cli.py attack` first |

##   Test layers

```mermaid
graph BT
    subgraph "  5 — Performance"
        T5[" response time · 30 bulk writes"]
    end
    subgraph "  4 — Persistence"
        T4[" cross-call data · empty state"]
    end
    subgraph "  3 — Contracts"
        T3[" invalid IDs · Unicode · type confusion"]
    end
    subgraph "  2 — Functional"
        T2[" CRUD cycle · graph links · sessions"]
    end
    subgraph "  1 — Protocol"
        T1[" JSON-RPC · tools/list · error codes"]
    end
    T5 --> T4 --> T3 --> T2 --> T1
```

|  # |  Layer |  Mark |  Tests | What it validates |
|---|-------|------|-------|-------------------|
| 1 |  Protocol | `protocol` | 7 | JSON-RPC compliance, error codes, session negotiation |
| 2 |  Functional | `functional` | 13 | Every tool works — CRUD, graph, sessions, whoami |
| 3 |  Contracts | `contracts` | 10 | Non-existent IDs, empty strings, Unicode, boundary values |
| 4 |  Persistence | `persistence` | 3 | Data survives across calls, graceful empty state |
| 5 |  Performance | `performance` | 5 | Response times <1s, bulk writes scale linearly |
| — |  AI Adversarial | — | N | llama3.2 generates malicious inputs, attacker classifies |

##   Adversarial testing

`lupus attack` uses **llama3.2** to generate malicious inputs for every tool,
executes them, and produces `QA_REPORT.md`.

```mermaid
sequenceDiagram
    participant L as  Lupus
    participant O as  Ollama
    participant S as  Orion

    L->>S:  tools/list
    S-->>L:  12 tool schemas

    loop  For each tool
        L->>O:  "Generate adversarial inputs"
        O-->>L:  JSON with malicious params
    end

    loop  For each input
        L->>S:  Execute with adversarial params
        S-->>L:  Response or validation error
        L->>L:  Classify verdict
    end

    L->>L:  Generate QA_REPORT.md
```

###  Verdict classification

|  Verdict |  Meaning |
|---------|---------|
| `passed` |  Input accepted, output correct |
| `rejected` |  Invalid input correctly refused — **defense, not a bug** |
| `vulnerability` |  Crash, data leak, or unexpected behavior |

> **Score = (passed + rejected) / total.** A server that rejects every malicious
> input without crashing scores 100%.

##   Configuration

```yaml
# config.yaml — add any MCP server
servers:
  orion:
    url: "http://localhost:9099/mcp"
    tools:
      - remember_decision
      - recall_context
      # ...
```

##   Structure

```
lupus/
├── lupus_cli.py            #   CLI entrypoint
├── attacker.py             #   adversarial engine
├── conftest.py             #   MCP client + Ollama fixtures
├── config.yaml             #   server registry
├── pyproject.toml          #   pytest configuration
├── test_orion/
│   ├── test_protocol.py    #   layer 1
│   ├── test_functional.py  #   layer 2
│   ├── test_contracts.py   #   layer 3
│   ├── test_persistence.py #   layer 4
│   └── test_performance.py #   layer 5
├── test_shared/
│   └── test_mcp_compliance.py
├── docs/assets/logo.svg    #   wolf logo
├── QA_REPORT.md            #   generated   (gitignored)
└── README.md
```

---

<p align="center">
  <sub>Part of <a href="https://github.com/jdvalmart">universo</a> — constellatio Lupus, venator mendorum</sub>
</p>
