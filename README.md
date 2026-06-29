# Sir Yaps-a-Lot (`bytewright`)

> **A chatbot that builds Windows binaries.** Tell it what you want — *"make me a tic-tac-toe
> game"* — and it ships a working `.exe`. No C, no Rust, no source code, and nothing technical
> from you. Works with the Anthropic API **or a local Ollama model** (no API key needed).

```bash
pip install -e .
bytewright            # start chatting (terminal)
bytewright serve      # …or a browser chat UI
```

Under the hood the model emits a verifiable machine-level representation that a trusted,
deterministic backend links into a real Portable Executable, and an emulated harness runs and
self-tests it — **but you never see any of that; you just chat.** This repository implements the
[execution plan](docs/this-plan.md). The internals:

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
| 3 | Agentic scaffolding (intent → build → run → repair) | ✅ chatbot (terminal + **browser GUI**), self-test + repair loop, 9-task eval; **Anthropic or local Ollama** |
| 4 | Training-data factory | 🟡 harvester emits verified (intent→IR), (intent→raw bytes), and repair-trajectory samples; SFT formatter |
| 5 | Train: distill, then RLVR | 🟡 dense reward ladder (scores IR *and* raw bytes) + an `RLEnv` (harness-as-reward); training run gated on compute |
| 6 | Harden & expand | 🟡 GUI (message boxes + **real windows**), positioned/colored console, a real playable game (Tic-Tac-Toe), and the **raw-bytes path** (model emits literal machine code → binary); angr verification still planned |

> Phases 4–5 are *scaffolded and tested* (harvester, SFT formatter, reward ladder, RL
> environment), but the actual training run — and the full data factory (compiling a source
> corpus at multiple optimization levels) — are gated on a compute decision (`decisions.md` §11).
> In this repo Claude stands in as the model (hand-emitting IR/bytes); the loops are unchanged.

## Just talk to it

You say what you want — no flags, no formats, no test cases — and it ships a `.exe`. Internally
the model writes the program *and its own self-tests*; the harness builds, runs, and checks them,
feeding any crash or mismatch back for repair until it works. You only ever see the result.

**Pick a model backend (no API key required):**

```bash
# Option A — local & free with Ollama (https://ollama.com):
ollama pull qwen2.5-coder            # any capable model works
export OLLAMA_MODEL=qwen2.5-coder    # a running Ollama server is also auto-detected

# Option B — Anthropic API:
pip install -e ".[ai]" && export ANTHROPIC_API_KEY=sk-...
```

**Then just chat:**

```bash
bytewright            # terminal chat (no subcommand needed)
bytewright serve      # browser chat UI at http://127.0.0.1:8765 with download buttons
```

```text
you> make me a christmas tree
bot> Done — I built christmas_tree.exe.   *  / *** / ***** / ...
you> now something that tells me if a number is prime
bot> Done — I built prime.exe.  (self-tested: 7 -> prime, 8 -> not prime)
```

**Scope, honestly.** Bytewright builds:
- console (text) programs — arithmetic, loops, file + console I/O;
- **turn-based games** — e.g. *"make me a tic-tac-toe game"* produces a real playable game
  (move parsing, board rendering each turn, win/draw detection) and *"make me a guessing game"*
  works too (line-buffered stdin);
- **positioned / colored** console output (cursor + fill APIs — boxes, boards, frames);
- **GUI** programs — message boxes *and* real windows (`RegisterClassEx` + `CreateWindowEx` +
  a message loop), e.g. *"open a window titled hello"* builds a genuine windowed `.exe`.

It can't *yet* do window controls/buttons that react to clicks, real-time keyboard, graphics,
or sound — so a live-key graphical *"tetris"* is still out of reach. It won't refuse, though: it
builds the closest version and tells you what it couldn't do. Those are the remaining Phase 6 items.

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
- **Raw-bytes path** (`bytewright/raw.py`): the end goal — `build_from_obj` links model-emitted
  machine-code bytes + relocations into a PE; `build_raw_pe` accepts an entire `.exe` as bytes.
  Shares the trusted linker (`backend/layout.link`) with the IR path.
- **MCP server** (`bytewright/mcp_server.py`): exposes all the tools (incl. `build_from_obj`,
  `build_raw_pe`) to an agent/model.
- **Agent / chatbot** (`bytewright/agent/`, `bytewright/chatbot.py`): the build → validate →
  run → self-test → repair loop; works with an IR or a raw-bytes builder.
- **Training** (`bytewright/reward.py`, `bytewright/dataset.py`, `bytewright/training/`): the
  dense reward ladder (the RLVR signal, scores IR and raw bytes), the data harvester, an
  `RLEnv`, and an SFT formatter — the Phase 4/5 scaffolding.

Key design decisions and how the plan's open questions were resolved live in
[`decisions.md`](decisions.md).

## Layout

```
schema/ir.schema.json     frozen IR contract           bytewright/harness/   emulator + §6 tools
examples/*.ir.json        IR programs (hello, game, …)  bytewright/mcp_server.py  MCP surface (13 tools)
examples/raw_hi.obj.json  raw machine-code object       bytewright/chatbot.py  conversational builder
bytewright/backend/       IR -> .exe (trusted)          bytewright/agent/     generators + repair loop
bytewright/raw.py         raw bytes -> .exe             bytewright/training/  RL env + SFT formatter
bytewright/eval/          task suite + oracles          bytewright/reward.py  dense reward ladder
bytewright/dataset.py     training-data harvester       tests/                75 unit/differential tests
docs/                     plan + design notes           decisions.md          decision log
```
