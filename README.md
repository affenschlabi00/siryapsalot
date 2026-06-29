# Sir Yaps-a-Lot

*A chatbot that builds Windows binaries. Python package: `siryapsalot` · commands: `siryapsalot`, `yaps`.*

> **A chatbot that builds Windows binaries.** Tell it what you want — *"make me a tic-tac-toe
> game"* — and it ships a working `.exe`. No C, no Rust, no source code, and nothing technical
> from you. Works with the Anthropic API **or a local Ollama model** (no API key needed).

```bash
pip install -e .
siryapsalot            # start chatting (terminal)
siryapsalot serve      # …or a browser chat UI
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
| 3 | Agentic scaffolding (intent → build → run → repair) | ✅ chatbot (terminal + **browser GUI**), self-test + repair loop, 9-task eval; **OpenAI / Anthropic / local Ollama** + model switcher + self-update |
| 4 | Training-data factory | 🟡 harvester emits verified (intent→IR), (intent→raw bytes), and repair-trajectory samples; SFT formatter |
| 5 | Train: distill, then RLVR | 🟡 dense reward ladder (scores IR *and* raw bytes) + an `RLEnv` (harness-as-reward); training run gated on compute |
| 6 | Harden & expand | 🟡 GUI (message boxes, **real windows, clickable buttons/controls, sound**, **live WM_COMMAND/WM_PAINT dispatch**), **persona switcher** (Lil Yapper / Yapzilla), positioned/colored console, a real game (Tic-Tac-Toe), and the **raw-bytes path**; angr verification still planned |

> Phases 4–5 are *scaffolded and tested* (harvester, SFT formatter, reward ladder, RL
> environment), but the actual training run — and the full data factory (compiling a source
> corpus at multiple optimization levels) — are gated on a compute decision (`decisions.md` §11).
> In this repo Claude stands in as the model (hand-emitting IR/bytes); the loops are unchanged.

## Just talk to it

You say what you want — no flags, no formats, no test cases — and it ships a `.exe`. Internally
the model writes the program *and its own self-tests*; the harness builds, runs, and checks them,
feeding any crash or mismatch back for repair until it works. You only ever see the result.

**Pick a model backend** — OpenAI/ChatGPT, Anthropic, or a local Ollama model (auto-detected):

```bash
# Option A — OpenAI / ChatGPT:
export OPENAI_API_KEY=sk-...          # export OPENAI_MODEL=gpt-4o   (default: gpt-4o-mini)

# Option B — Anthropic:
pip install -e ".[ai]" && export ANTHROPIC_API_KEY=sk-...

# Option C — local & free with Ollama (https://ollama.com):
ollama pull qwen2.5-coder
export OLLAMA_MODEL=qwen2.5-coder     # a running Ollama server is also auto-detected
```

**Switch provider & model any time.** In the **web UI** the top bar has a **provider** dropdown
(OpenAI / Anthropic / Ollama — only the ones you have set up) next to a **model** dropdown; pick a
provider and the model list refreshes to *that* provider's models (Ollama → your local models,
OpenAI → the `gpt-*`/`o*` models on your key, Anthropic → the Claude models). In the terminal:
`/models` (list), `/model gpt-4o` (switch model), `/backend openai|anthropic|ollama` (switch
provider). At launch: `siryapsalot --backend openai --model gpt-4o`.

**Then just chat:**

```bash
siryapsalot            # terminal chat (no subcommand needed)
siryapsalot serve      # browser chat UI at http://127.0.0.1:8765 (provider+model pickers, Update button)
```

```text
you> make me a christmas tree
bot> Done — I built christmas_tree.exe.   *  / *** / ***** / ...
you> now something that tells me if a number is prime
bot> Done — I built prime.exe.  (self-tested: 7 -> prime, 8 -> not prime)
```

## Two builders — pick who you chat with

Sir Yaps-a-Lot has **two switchable personas** (think of it like a model switcher, but for the
builder's vibe + powers):

| Persona | Vibe | Builds |
|---|---|---|
| 🙂 **Lil Yapper** *(classic)* | the humble OG, keeps it simple | console apps, text games, basic windows & message boxes |
| 😈 **Yapzilla** *(deluxe)* | the maxed-out beast | **full GUI** — windows with **clickable buttons & controls** — and **SOUND** 🔊 |

```bash
siryapsalot -m yapzilla        # start as the deluxe builder
# …or switch mid-chat:
you ▶ /who                     # list personas
you ▶ /switch yapzilla         # change who you're talking to
you ▶ build me a window with a button that beeps when clicked
Yapzilla ▶ Done — click_beeps.exe  (controls: [Beep!]; plays 2 sound(s) 🔊; reacts to 2 live event(s) 🖱️)
```

In the browser UI (`siryapsalot serve`) there's a dropdown in the top-right to pick the persona.

## Staying up to date

The repo is public, so Sir Yaps-a-Lot can update itself. In the **web UI** there's an **⟳ Update**
button (top-right) and a **branch dropdown** — pick a branch and click Update to fetch the newest
code and switch to it. From the terminal:

```bash
siryapsalot update                 # pull the newest code on the current branch
siryapsalot update --branch main   # switch to a branch and pull
siryapsalot update --list          # show current branch / commit / available branches
# (or inside a chat:  /update   /update main)
```

After an update, restart `siryapsalot` to load the new code. *Updates require running from a git
clone installed with `pip install -e .` (so the code lives in your checkout).*

**Scope, honestly.** Sir Yaps-a-Lot builds:
- console (text) programs — arithmetic, loops, file + console I/O;
- **turn-based games** — e.g. *"make me a tic-tac-toe game"* produces a real playable game
  (move parsing, board rendering each turn, win/draw detection) and *"make me a guessing game"*
  works too (line-buffered stdin);
- **positioned / colored** console output (cursor + fill APIs — boxes, boards, frames);
- **GUI** programs — message boxes, real windows (`RegisterClassEx` + `CreateWindowEx` + a
  message loop), and in **Yapzilla** mode: **child controls** (buttons, etc.) and **sound**
  (`Beep`/`MessageBeep`/`PlaySound`). e.g. *"a window with a button that beeps"* → a genuine
  GUI+audio `.exe`.
- **interactive windows** — the harness now **dispatches window messages into your window proc**
  (`WM_CREATE` → `WM_PAINT` → a `WM_COMMAND` per button → `WM_DESTROY`), so a button's **click
  handler** and your **paint handler** actually run and their effects are recorded. *"a window
  with a button that beeps when clicked"* builds a window whose `WM_COMMAND` handler beeps — the
  beep happens **because the click was dispatched**, not from `main`.

It can't *yet* do **real-time continuous input** (held keys, mouse-move, animation frames) or
graphics/sprites — so a live-action graphical *"tetris"* is still out of reach, but a **clickable,
button-driven window is now in reach**. It won't refuse, though: it builds the closest version and
tells you what it couldn't do. Those are the remaining Phase 6 items.

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

## Running on Windows

**Do the binaries it makes need anything installed? No.** Every `.exe` Sir Yaps-a-Lot produces is
a real native Windows PE — copy it to any Windows machine and double-click it; nothing to install.

**Does the *tool* need anything? Yes — a one-time setup** (it's a Python program). No compiler,
no Visual Studio, no MinGW — all dependencies are normal pip wheels with prebuilt Windows
binaries.

1. **Install Python 3.10+** from [python.org](https://www.python.org/downloads/windows/) — tick
   *"Add python.exe to PATH"* in the installer.
2. **Install Sir Yaps-a-Lot** (PowerShell or Command Prompt):
   ```powershell
   git clone https://github.com/affenschlabi00/siryapsalot
   cd siryapsalot
   pip install -e .         # -e keeps code in the clone so the Update button works (all wheels)
   ```
3. **Pick a model** (one of):
   - **ChatGPT — OpenAI:** `setx OPENAI_API_KEY sk-...` (optionally `setx OPENAI_MODEL gpt-4o`)
   - **Local & free — Ollama:** install [Ollama for Windows](https://ollama.com/download), then
     ```powershell
     ollama pull qwen2.5-coder
     setx OLLAMA_MODEL qwen2.5-coder      # reopen the terminal after setx
     ```
   - **Anthropic API:** `pip install anthropic` then `setx ANTHROPIC_API_KEY sk-...`
4. **Run it:**
   ```powershell
   siryapsalot           # chat in the terminal  (or:  yaps)
   siryapsalot serve     # browser chat UI at http://127.0.0.1:8765
   ```
5. The binaries land in `build\` — they're native Windows `.exe`s you can run directly.

> The whole build → run → self-test → repair loop runs on Windows: the harness emulates the CPU
> (Unicorn) and the Win32 calls in-process, so it works the same on Windows, macOS, and Linux —
> and the output is always a real Windows `.exe`.

## Raw bytes → binary (the end goal)

The north star: a model that just emits **raw bytes** and gets a great binary. That path is
built. The sweet spot is an *object file* — the model emits the literal `.text` machine-code
bytes (it does the encoding itself) plus a relocation list; the trusted backend only links and
writes the unforgiving PE container:

```bash
python -m siryapsalot.cli rawbuild examples/raw_hi.obj.json   # raw machine code -> .exe -> "Hi"
```

```python
from siryapsalot.raw import build_from_obj, build_raw_pe
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
python -m siryapsalot.cli build examples/hello.ir.json -o build/hello.exe
python -m siryapsalot.cli run   build/hello.exe          # -> "Hello, world!"
python -m siryapsalot.cli validate build/hello.exe       # structural PE check (LIEF)
python -m siryapsalot.cli trace build/hello.exe          # step-by-step execution movie
python -m siryapsalot.cli eval                           # build+verify the whole task suite
```

Or from Python:

```python
import json
from siryapsalot import harness

ir  = json.load(open("examples/hello.ir.json"))
rep = harness.build_binary(ir, "build/hello.exe")        # IR -> .exe
print(harness.run("build/hello.exe")["stdout"])          # -> "Hello, world!\n"
```

## How it works

- **IR** (`schema/ir.schema.json`, examples in `examples/`): real x86-64 instructions with
  *symbolic names* — labels for jumps, `import:dll!func` for Win32 APIs, `data:label`,
  and virtual registers `%vN`. The model never computes byte offsets.
- **Backend** (`siryapsalot/backend/`): validates IR, allocates virtual registers, inserts
  the prologue/epilogue (shadow space + 16-byte alignment), encodes via Keystone with a
  relocation scheme, lays out sections, builds the import directory/IAT, and writes a
  hand-rolled PE32+. Deterministic and trusted — **never learned**.
- **Harness** (`siryapsalot/harness/`): a Unicorn-based Windows emulator that loads the PE,
  intercepts each imported API with a Python implementation (no Windows rootfs needed),
  and exposes the Plan §6 tools — `build_binary`, `validate_pe`, `disassemble`, `run`,
  `trace`, `inspect`, `crash_analysis`, `diff_behavior`, `list_imports`, `resolve_api`.
  After `main` returns it **pumps window messages into the registered window proc**
  (`WM_CREATE`/`WM_PAINT`/`WM_COMMAND`-per-button/`WM_DESTROY`), recording each handler's
  effects — so click/paint behavior is observable and a faulting handler stays contained.
- **Raw-bytes path** (`siryapsalot/raw.py`): the end goal — `build_from_obj` links model-emitted
  machine-code bytes + relocations into a PE; `build_raw_pe` accepts an entire `.exe` as bytes.
  Shares the trusted linker (`backend/layout.link`) with the IR path.
- **MCP server** (`siryapsalot/mcp_server.py`): exposes all the tools (incl. `build_from_obj`,
  `build_raw_pe`) to an agent/model.
- **Agent / chatbot** (`siryapsalot/agent/`, `siryapsalot/chatbot.py`): the build → validate →
  run → self-test → repair loop; works with an IR or a raw-bytes builder.
- **Model backends** (`siryapsalot/llm.py`): OpenAI/ChatGPT, Anthropic, or local Ollama —
  switchable at runtime; **personas** in `siryapsalot/modes.py` (Lil Yapper / Yapzilla).
- **Web UI + self-update** (`siryapsalot/web.py`, `siryapsalot/updater.py`): a browser chat with
  persona, **provider, and per-provider model** pickers (choose a provider → the model list
  refreshes to its models), download buttons, and a git **Update** button (branch switching).
- **Training** (`siryapsalot/reward.py`, `siryapsalot/dataset.py`, `siryapsalot/training/`): the
  dense reward ladder (the RLVR signal, scores IR and raw bytes), the data harvester, an
  `RLEnv`, and an SFT formatter — the Phase 4/5 scaffolding.

Key design decisions and how the plan's open questions were resolved live in
[`decisions.md`](decisions.md).

## Layout

```
schema/ir.schema.json     frozen IR contract           siryapsalot/harness/   emulator + §6 tools
examples/*.ir.json        IR programs (hello, game, …)  siryapsalot/mcp_server.py  MCP surface (13 tools)
examples/raw_hi.obj.json  raw machine-code object       siryapsalot/chatbot.py  conversational builder
siryapsalot/backend/       IR -> .exe (trusted)          siryapsalot/agent/     generators + repair loop
siryapsalot/raw.py         raw bytes -> .exe             siryapsalot/training/  RL env + SFT formatter
siryapsalot/llm.py         OpenAI/Anthropic/Ollama       siryapsalot/modes.py   Lil Yapper / Yapzilla
siryapsalot/web.py         browser chat UI               siryapsalot/updater.py git self-update
siryapsalot/eval/          task suite + oracles          siryapsalot/reward.py  dense reward ladder
siryapsalot/dataset.py     training-data harvester       tests/                94 unit/differential tests
docs/                     plan + design notes           decisions.md          decision log
```
