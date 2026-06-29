# Sir Yaps-a-Lot (`bytewright`)

> An AI system that takes human intent and produces a working Windows `.exe` directly —
> no C, no Rust, no high-level source. The model reasons in a machine-level Intermediate
> Representation (IR); a trusted, deterministic backend encodes and links that IR into a
> valid Portable Executable; an emulated harness runs and inspects it.

This repository implements the [execution plan](docs/this-plan.md). The core idea:

```
intent ─▶ Generator ─▶ IR (JSON) ─▶ Backend (deterministic) ─▶ .exe ─▶ Harness (emulated) ─▶ feedback ─┐
            ▲ model                    trusted floor, never learned     debugger·grader·reward          │
            └──────────────────────────────── repair loop / RL reward ─────────────────────────────────┘
```

The model does the *interesting* work (machine-level reasoning); the backend does the
*error-intolerant clerical* work (encoding, layout, linking, PE construction). The harness
does triple duty — correctness checker, debugger, and (later) RL reward — built once.

## Status

| Phase | What | State |
|---|---|---|
| 0 | Scope, repo, frozen IR schema | ✅ done |
| 1 | Harness / MCP server (the judge) | ✅ core done (Unicorn emulator + all §6 tools + MCP) |
| 2 | Deterministic backend (IR → .exe) | ✅ done (`hello` + arithmetic/loops/branches/stdin/file I/O) |
| 3 | Agentic scaffolding (build→run→repair loop) | ✅ scaffolding + eval task suite |
| 4–6 | Training-data factory · train · harden | planned (see plan + `decisions.md`) |

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e .                 # installs keystone, capstone, unicorn, lief, jsonschema
pip install -e ".[mcp,dev]"      # + MCP server and pytest

# Compile an IR program to a real PE, then run it in the emulator:
python -m bytewright.cli build examples/hello.ir.json -o build/hello.exe
python -m bytewright.cli run   build/hello.exe          # -> "Hello, world!"
python -m bytewright.cli validate build/hello.exe       # structural PE check (LIEF)
python -m bytewright.cli trace build/hello.exe          # step-by-step execution movie
```

Or from Python:

```python
import json
from bytewright import harness

ir  = json.load(open("examples/hello.ir.json"))
rep = harness.build_binary(ir, "build/hello.exe")        # IR -> .exe
print(harness.run("build/hello.exe")["stdout"])          # -> "Hello, world!\n"
```

## How it works

- **IR** (`schema/ir.schema.json`, examples in `examples/`): real x86-64 instructions with
  *symbolic names* — labels for jumps, `import:dll!func` for Win32 APIs, `data:label`,
  and virtual registers `%vN`. The model never computes byte offsets.
- **Backend** (`bytewright/backend/`): validates IR, allocates virtual registers, inserts
  the prologue/epilogue (shadow space + 16-byte alignment), encodes via Keystone with a
  relocation scheme, lays out sections, builds the import directory/IAT, and writes a
  hand-rolled PE32+. Deterministic and trusted — **never learned**.
- **Harness** (`bytewright/harness/`): a Unicorn-based Windows emulator that loads the PE,
  intercepts each imported API with a Python implementation (no Windows rootfs needed),
  and exposes the Plan §6 tools — `build_binary`, `validate_pe`, `disassemble`, `run`,
  `trace`, `inspect`, `crash_analysis`, `diff_behavior`, `list_imports`, `resolve_api`.
- **MCP server** (`bytewright/mcp_server.py`): exposes those tools to an agent/model.
- **Agent** (`bytewright/agent/`): the Phase 3 build → validate → run → diff → repair loop.

Key design decisions and how the plan's open questions were resolved live in
[`decisions.md`](decisions.md).

## Layout

```
schema/ir.schema.json     frozen IR contract           bytewright/harness/   emulator + §6 tools
examples/*.ir.json        IR programs (hello, …)        bytewright/mcp_server.py  MCP surface
bytewright/backend/       IR -> .exe (trusted)          bytewright/agent/     scaffolded repair loop
bytewright/eval/          task suite + oracles          tests/                unit + differential tests
docs/                     plan + design notes           decisions.md          decision log
```
