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
| 4 | Training-data factory | 🟡 starter: harvester emits verified (intent→IR) + repair-trajectory samples |
| 5 | Train: distill, then RLVR | 🟡 starter: the dense reward ladder (the RLVR reward) is built (`bytewright/reward.py`) |
| 6 | Harden & expand | planned (more Win32 surface, GUI, angr, raw-hex stretch) |

> Phases 4–5 are *started* (the data harvester and reward function are real and tested), but
> the full data factory (compiling a source corpus at multiple optimization levels) and the
> training runs themselves are gated on a compute decision — see `decisions.md` §11.

## Just talk to it

It's a chatbot that builds binaries. You say what you want — no flags, no formats, no test
cases — and it ships a `.exe`. The model writes the IR *and its own self-tests*; the harness
builds, runs, and checks those tests, feeding any crash or mismatch back for repair until it
works.

```bash
pip install -e ".[ai]"                 # adds the anthropic SDK
export ANTHROPIC_API_KEY=sk-...        # (optional) export BYTEWRIGHT_MODEL=claude-...

python -m bytewright.cli chat          # then just type:
#   you> make me a christmas tree
#   bot> Done — I built christmas_tree.exe.  *  / *** / ***** ...
#   you> now something that tells me if a number is prime
#   bot> Done — I built prime.exe.  (self-tested: 7 -> prime, 8 -> not prime)
```

One-shot, same thing:

```bash
python -m bytewright.cli create "print the fibonacci numbers below 100"
```

**Scope, honestly.** The backend builds *console* (text) Windows programs. Ask for something
graphical or real-time — *"make me a tetris game"* — and it won't refuse: it builds the closest
console version (an ASCII Tetris board) and tells you what it couldn't do. Real GUI/real-time
games are the Phase 6 expansion (graphics + live-input APIs).

```text
you> make me a tetris game
bot> Real-time graphical Tetris is beyond the backend right now, so I built an ASCII
     Tetris board — the closest console version.
         T E T R I S
     +----------+
     |    ##    |
     |   ###    |
     | ######## |
     +----------+
```

No API key? The exact same loop runs with any `fn(message, feedback, iter, history) -> spec`
generator (see `examples/chat_demo.py`) — that's how the chatbot demo and every
`examples/*.ir.json` were produced and verified here.

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
