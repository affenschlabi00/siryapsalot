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
| 2 | Deterministic backend (IR → .exe) | ✅ done (loops, branches, arithmetic, div/mul, stdin, file I/O, multi-procedure call/ret) |
| 3 | Agentic scaffolding (intent → build → run → repair) | ✅ `create`/`chat` + repair loop + 8-task eval suite |
| 4–6 | Training-data factory · train · harden | planned (see plan + `decisions.md`) |

## Describe it, get a binary

The headline: say what you want, and the AI builds the `.exe`. A model emits IR, the harness
builds/validates/runs it, and on failure feeds the crash or behavioral diff back for repair —
autonomously, until it works.

```bash
pip install -e ".[ai]"                # adds the anthropic SDK
export ANTHROPIC_API_KEY=sk-...        # (optional) export BYTEWRIGHT_MODEL=claude-...

python -m bytewright.cli create "print the fibonacci numbers below 100, one per line"
python -m bytewright.cli create "read a number n from stdin and print n squared" --stdin "9"
python -m bytewright.cli chat          # interactive: type requests, get binaries
```

Programmatically — the loop is generator-agnostic, so a live model *or* Claude-in-the-loop
can be the generator:

```python
from bytewright.agent import build_from_intent, AnthropicGenerator
res = build_from_intent("sum the integers from 1 to 100 and print the total", AnthropicGenerator())
print(res["path"], res["outputs"])     # build/sum_*.exe  ['5050\n']
```

(No API key in this environment? The exact same loop runs with any
`fn(intent, feedback, iteration) -> ir` via `CallableGenerator` — that's how the examples
under `examples/*.ir.json` were produced and verified.)

## Quick start (compile + inspect)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"           # keystone, capstone, unicorn, lief, jsonschema, pytest

# Compile an IR program to a real PE, then run it in the emulator:
python -m bytewright.cli build examples/hello.ir.json -o build/hello.exe
python -m bytewright.cli run   build/hello.exe          # -> "Hello, world!"
python -m bytewright.cli validate build/hello.exe       # structural PE check (LIEF)
python -m bytewright.cli trace build/hello.exe          # step-by-step execution movie
python -m bytewright.cli eval                           # build+verify the whole task suite
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
