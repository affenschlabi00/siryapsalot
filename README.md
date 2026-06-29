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
| 6 | Harden & expand | 🟡 in progress: GUI (user32 MessageBox), positioned/colored console, a real playable game (Tic-Tac-Toe), and the **raw-bytes path** (model emits literal machine code → binary); angr verification still planned |

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

**Scope, honestly.** Bytewright builds:
- console (text) programs — arithmetic, loops, file + console I/O;
- **turn-based games** — e.g. *"make me a tic-tac-toe game"* produces a real playable game
  (move parsing, board rendering each turn, win/draw detection) and *"make me a guessing game"*
  works too (line-buffered stdin);
- **positioned / colored** console output (cursor + fill APIs — boxes, boards, frames);
- simple **GUI** dialogs via `user32!MessageBoxA` (a real GUI `.exe`).

It can't *yet* do custom windows, real-time keyboard, graphics, or sound — so a live-key
graphical *"tetris"* is still out of reach. It won't refuse, though: it builds the closest
version (an ASCII Tetris board) and tells you what it couldn't do. Those are the remaining
Phase 6 items.

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

## Raw bytes → binary (the end goal)

The north star: a model that just emits **raw bytes** and gets a great binary. That path is
built. The sweet spot is an *object file* — the model emits the literal `.text` machine-code
bytes (it does the encoding itself) plus a relocation list; the trusted backend only links and
writes the unforgiving PE container:

```bash
python -m bytewright.cli rawbuild examples/raw_hi.obj.json   # raw machine code -> .exe -> "Hi"
```

```python
from bytewright.raw import build_from_obj, build_raw_pe
build_from_obj({                       # object level: bytes + relocations
    "metadata": {"name": "hi", "entry_offset": 0},
    "code": "4883ec28 b9f5ffffff ff15........ ...",   # literal machine code (hex)
    "imports": [{"dll": "kernel32.dll", "function": "WriteFile"}, ...],
    "data": [{"label": "msg", "type": "bytes", "value": "Hi\n"}],
    "relocs": [{"offset": 11, "kind": "import", "target": "kernel32.dll!GetStdHandle"}, ...],
})
build_raw_pe(open("some.exe","rb").read().hex())   # full level: the entire .exe as bytes
```

`disassemble`, `run`, and `crash_analysis` all work on raw-built binaries, so the same chatbot
loop drives **byte-level self-repair** — `Chatbot(generator, builder=build_from_obj)`. (Per the
plan this may never beat the IR path; it's the research flex — and it works.)

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
