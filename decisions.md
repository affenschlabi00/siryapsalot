# Decision log — Sir Yaps-a-Lot (`siryapsalot`)

This file records the locked decisions from project kickoff and how the deferred /
open questions (Plan §11, §4) were resolved during the Phase 0 build. Flip any of
these by editing this file and the affected module.

## Locked at kickoff (Plan §0)

| Decision | Choice | Status |
|---|---|---|
| How "pure" is binary-writing? | IR + trusted deterministic backend (main line). Raw-hex emission is a Phase 6 stretch. | Locked |
| Train or scaffold v1? | Scaffold a frontier model through the harness first; training is a later, separate track. | Locked |
| First target? | Windows `.exe` (x86-64 PE), from day one. | Locked |

## Resolved during Phase 0

### D1 — Emulator: build directly on **Unicorn**, not Qiling (for v1)
The plan names Qiling for the Windows-API layer. In practice the `qiling` pip package
ships **no Windows rootfs** (no `kernel32.dll`/`ntdll.dll` stubs), and a real rootfs
means copying licensed Windows DLLs. Since *we* control the backend and therefore the
exact, small set of Win32 APIs our programs import, we instead built a purpose-built
**Unicorn-based emulator** (`siryapsalot/harness/emulator.py`) that intercepts each
imported API with a Python implementation (`siryapsalot/harness/apidb.py`).

Why this is better here, not just easier:
- No rootfs, no Windows-DLL licensing, fully reproducible from `pip install`.
- Total deterministic observability (single-step, full memory, every API call) — which
  is the entire point of emulating instead of running on hardware (Plan §1).
- The API surface grows deliberately and is auditable in one file.

Qiling/Wine remain a **documented future fidelity path** (Plan §6 "fidelity sampling"):
run a sampled subset on a real loader to confirm the emulator matches. Tracked, not built.

### D2 — PE construction: **hand-rolled writer** is primary; **LIEF** is the independent checker
The plan offers LIEF (build) with a hand-rolled writer as an optional purity path. We
inverted it: `siryapsalot/backend/pe_builder.py` writes the PE container by hand (full
control over RVA/IAT layout, which our RIP-relative relocations depend on), and the
harness uses **LIEF** to *independently parse and validate* the result
(`siryapsalot/harness/validate_pe.py`). Build-by-hand + check-with-an-independent-library
is a stronger correctness story than build-and-check with the same tool.

### D3 — Calling convention & stack frames: **backend-owned** (resolves Plan §4/§11 open question)
The model writes machine-level instructions but does **not** manage the stack frame.
The backend inserts a standard prologue/epilogue per procedure: it reserves shadow space
(32 bytes), sizes the frame to cover outgoing stack arguments and saved registers, and
keeps RSP 16-byte aligned at every `call`. This kills the single biggest class of
calling-convention bugs (Plan §1, §4).

Concretely, the model **must not** emit `push`, `pop`, `sub rsp`, `add rsp`, `ret`,
`leave`, or `enter` — the IR validator rejects them with a clear message. Outgoing stack
arguments (the 5th+ integer arg) are written to `[rsp+32]`, `[rsp+40]`, … directly; the
backend reserves enough frame for the deepest such access. The entry procedure must end
by calling `ExitProcess` (the backend appends one if missing).

### D4 — Registers: **virtual registers (`%vN`) allocated to callee-saved**, real regs allowed
Per Plan §4/§11 "v1 default = backend-allocated virtual registers." Each distinct `%vN`
in a procedure is bound to a callee-saved register (`rbx, rsi, rdi, r12–r15`), pushed in
the prologue and popped in the epilogue. Because they are callee-saved, their values
survive across API calls *by construction*. The model may also name real registers
directly (`rax, rcx, …`); the allocator never assigns a `%vN` to a caller-saved register,
so model-used scratch registers (`rax/rcx/rdx/r8/r9/r10/r11`) never collide with `%vN`.
Spilling (>7 live virtual registers) raises a clear "not yet implemented" error in v1.
Model-driven real-register-only mode is a Plan §6 toggle.

### D5 — Position-independent addressing → **no base relocations**
All symbolic references use RIP-relative addressing: data via `lea reg, data:LABEL`
(→ `lea reg, [rip+disp32]`), imports via `call import:dll!func` (→ `call [rip+disp32]`),
and code labels via near `rel32` branches. Every such instruction places its 32-bit
field as the **last 4 bytes**, patched uniformly as `target_VA − (field_VA + 4)`. The
image therefore needs **no `.reloc` section** and is marked non-relocatable.

### D6 — Instruction subset (Plan §0/§11 — initial frozen set)
v1 supports: data movement (`mov`, `lea`, `movzx`, `movsx`), arithmetic/logic
(`add, sub, imul, idiv, inc, dec, and, or, xor, neg, not, shl, shr, sar`), compare/test
(`cmp, test`), control flow (`jmp`, `je/jne/jl/jle/jg/jge/jb/jbe/ja/jae/js/jns/jz/jnz`,
`call`, conditional `setcc`), and `nop`. `cdq/cqo` for division sign-extension. Anything
keystone can encode that has **no symbolic operand** also passes through. Expanded later.

## D7 — Product: a chatbot, with pluggable model backends (Anthropic **or** Ollama)
The product is a chatbot that builds binaries: `siryapsalot` (terminal) or `siryapsalot serve`
(browser GUI). The IR is an internal implementation detail — users never see it; they chat and
get a `.exe`. The model backend is pluggable (`siryapsalot/llm.py`, `make_backend`): it uses the
Anthropic API if `ANTHROPIC_API_KEY` is set, otherwise a local **Ollama** model (auto-detected,
or `OLLAMA_MODEL`) — so no API key is required. Ollama runs are constrained to JSON output
(`format=json`) for reliability. The web UI is pure stdlib (`http.server`), no new dependency.

## D8 — GUI: message boxes and real windows (Plan §6)
The harness implements `user32` GUI APIs (`MessageBoxA`, `RegisterClassExA`, `CreateWindowExA`,
`ShowWindow`, the `GetMessageA` message loop, etc.) and *records* dialogs and windows
(title/size). `GetMessageA` returns 0 so a standard message loop exits cleanly under emulation;
the emitted `.exe` is a genuine Win32 GUI program that shows a window on real Windows. A new
`code:LABEL` operand takes a function pointer to a procedure (e.g. the window proc). The chatbot
self-tests GUI programs with `expect_dialog_contains` / `expect_window_contains`. (Interactive
control/click handling was added later — see **D11**; real-time input and graphics remain out.)

## D9 — Switchable personas (Lil Yapper / Yapzilla) + sound & controls
The chatbot has two switchable personas (`siryapsalot/modes.py`) — like a model switcher, but for
the builder's vibe and capability surface, not the LLM:
- **Lil Yapper** (classic): humble, console apps + basic windows/dialogs; sound APIs are *not*
  advertised in its prompt.
- **Yapzilla** (deluxe): goes big — advertises child **controls** (buttons via `CreateWindowExA`
  with class `BUTTON` + a parent HWND) and **sound** (`Beep`, `MessageBeep`, `PlaySoundA`).
Both run the same harness; the mode only changes the persona text and which APIs the prompt
offers. Switch via `-m/--mode`, the terminal `/switch`, or the web UI dropdown. The harness records
controls and sounds (they execute in `main`, so they really run under emulation; on Windows they
show/play). Self-tests gain `expect_control_contains` and `expect_sound`. (Controls reacting to
*live* clicks was originally out of scope; **D11** adds it.)

## D10 — Model providers (OpenAI/Anthropic/Ollama) + self-update
- **Backends** (`siryapsalot/llm.py`): OpenAI/ChatGPT, Anthropic, and Ollama all implement
  `chat()` + `list_models()`. OpenAI uses `response_format={"type":"json_object"}` (Ollama uses
  `format=json`) so structured IR output is reliable. Switch provider/model at runtime
  (`/backend`, `/model`, `--backend/--model`, or the web dropdowns); `make_backend` auto-detects
  from env (OpenAI key → Anthropic key → running Ollama). OpenAI is called over stdlib `urllib`
  (no SDK dependency).
- **Per-provider model picker in the web UI**: the top bar has a **provider** dropdown next to a
  **model** dropdown. `llm.available_backends()` lists only the providers that can be constructed
  right now (key present / Ollama reachable). `POST /api/backend` switches the provider and returns
  *its* model list, so choosing a provider refreshes the model dropdown to that provider's models
  (Ollama → local models, OpenAI → `gpt-*`/`o*`, Anthropic → Claude). `ChatService.set_backend`
  fails soft — an unavailable provider returns `{ok:false, error}` and the working one is kept.
- **Self-update** (`siryapsalot/updater.py`): the repo is public, so the app can `git fetch` +
  fast-forward `pull` and switch branches (`ls-remote` lists remote branches read-only). Exposed
  as the web **Update** button (+ branch dropdown) and `siryapsalot update [--branch]` / `/update`.
  Requires an editable install (`pip install -e .`) so the code lives in the checkout; restart to
  load new code.

## D11 — Interactive event layer: dispatch WM_* into the guest window proc (Plan §6)
GUI programs were static under emulation: `main` ran (registering the window class, creating
windows/controls) and the message loop exited because `GetMessageA` returns 0, so a button's
click handler never executed. D11 closes that gap **without** real-time input: after `main`
finishes, the harness **pumps a synthetic message sequence into the registered window proc** —
`WM_CREATE` → `WM_PAINT` → one `WM_COMMAND` per child control (with `wParam` = that control's id)
→ `WM_DESTROY` — so the program's own click/paint handlers actually run and their effects
(sounds, dialogs, drawing, `SetWindowTextA`) are recorded.

How (re-entrancy is the hard part): you cannot call the guest window proc from *inside* an API
hook (that hook is mid-instruction). So dispatch is a **separate phase 2** after the main
`emu_start` returns. `_call_guest` sets up a fresh 16-aligned frame, pushes a sentinel return
address `EVENT_RET` (a `ret` byte in the hook page), loads the four args per the MS x64
convention, and runs `emu_start(proc, until=EVENT_RET)` — a clean top-level call that stops when
the proc returns. The window proc is captured at `RegisterClassExA` time (read from
`WNDCLASSEXA.lpfnWndProc`, offset 8); each control's id/HWND is captured at `CreateWindowExA`.

Fault isolation: a buggy handler must not fail the whole program. A `phase` flag tells the
unmapped-memory hook to record a fault **locally** (per event, `ok:false` + fault detail) instead
of marking the run crashed, and each `_call_guest` is wrapped so a `UcError` only ends that one
event. The chatbot gains an `expect_event` self-test ("this message's handler must run cleanly"),
and the success reply notes when an app "reacts to N live event(s) 🖱️". Demonstrated by
`examples/click_beeps.ir.json`: `main` makes **no** sound, yet the window proc beeps on `WM_PAINT`
(MessageBeep) and `WM_COMMAND` (Beep 880) — so any recorded sound proves the events were
dispatched. Still out of scope: real-time continuous input (held keys, mouse-move, animation) and
graphics/sprites — so a live-action graphical "tetris" remains future work.

## D12 — In-GUI model eval: benchmark a chosen provider/model on the oracle suite (Plan §7)
The product can now answer "how good is *this* model at building binaries?" from the web UI. A
**🧪 Eval** button (next to the model picker) runs the **agent repair loop** (`agent.solve`) for
the selected provider/model over the Phase-3 task suite (`eval/tasks.py`) and scores each task
against its **oracle** (`diff_behavior`) — an objective pass/fail, not a self-reported one.

- **Background + live progress.** `ChatService.start_eval` spawns a daemon thread and returns at
  once; the single-threaded `HTTPServer` stays responsive because the work is off the request
  thread. The browser polls `GET /api/eval/status` (~1.5s) and renders a live scoreboard
  (per-task ✅/❌, repair iterations, cases passed) ending in a `passed/total (score%)`. One eval
  at a time — a second `start_eval` while running returns `{started:false, busy:true}`.
- **Which model.** The eval uses an `LLMGenerator` bound to the requested provider/model
  (`make_backend(prefer=...)` + `set_model`), so it tests exactly what the dropdowns select,
  independent of later chat actions.
- **Testable offline.** `start_eval(generator=...)` accepts an injected generator;
  `agent.LibraryGenerator` (reference IR) drives the whole pipeline deterministically with no API
  key, which is how the feature is unit-tested. Endpoints: `POST /api/eval`,
  `GET /api/eval/status`, `GET /api/eval/tasks`.
- **CLI parity.** `siryapsalot eval --live [--backend …] [--model …] [--task …] [--max-iters N]`
  benchmarks a model from the terminal; plain `siryapsalot eval` still scores the reference
  solutions as a harness self-check.

## D13 — Chat-vs-build routing: small talk gets a reply, not a build
Every message used to go straight into the build → run → self-test → repair loop, so a plain
"hello" made the model invent some program and grind through up to `max_iters` model calls +
builds — which looks like a hang (especially on a slow local Ollama). `Chatbot.send` now routes:

- **Instant heuristic** (`chatbot._quick_chat`): obvious small talk — greetings, thanks, "what
  can you do?", "who are you" — gets a friendly canned reply with **zero** model calls and no
  build. A build-keyword guard means anything like "make/build/draw/window/tetris/…" is never
  swallowed as chat. This is what makes "hello" feel instant.
- **Model-side `kind`**: the chatbot prompt now asks the model to return either
  `{"kind":"chat","reply":…}` or `{"kind":"build", program_name, explanation, ir, self_tests}`.
  `send` honors `kind=="chat"` (reply, no build). `_is_chat_spec` treats a legacy spec with an
  `ir` and no `kind` as a build, so older generators/tests are unaffected.

Chat turns are recorded in history (`{"message","reply","chat":True}`) and replayed to the model
as real assistant turns, so the conversation stays coherent across chat and build. A chat result
is `{"success":True,"reply":…,"path":None,"chat":True}`; the web/CLI already handle a missing
binary (no download). When unsure, the model is told to prefer chat and ask a clarifying question
rather than build something random.

## D14 — Switch provider with a pasted key + live build progress
Two UX gaps reported by a user running local Ollama: you couldn't switch to ChatGPT/Anthropic, and
a build looked frozen for minutes.

- **Provider switching without env vars.** `make_backend` / the backends now accept a runtime
  `api_key` (and `model`/`host`/`base_url`), so credentials no longer have to come from the
  environment. The web provider dropdown lists **all** providers (`llm.all_backends()`), not just
  the configured ones (`llm.available_backends()`), marking unconfigured cloud ones with a key icon.
  Picking one that needs a key reveals an API-key box; `POST /api/backend {backend, api_key}`
  switches and returns `{ok:false, needs_key:true}` when a key is what's missing so the UI knows to
  prompt. Keys live only in the in-memory backend object — never written to disk. CLI parity:
  `/key <provider> <api-key>` (and `/backend` hints to use it). `AnthropicBackend` now raises a
  clear `LLMUnavailable` if the SDK is missing or no key is set (instead of an opaque error).
- **Live build feedback.** `Chatbot.send(message, progress=cb)` emits step events
  (thinking, compiling, testing, repairing, done/failed). The terminal prints each step; the web
  layer runs the build in a **background thread** (`ChatService.start_build`) and the browser polls
  `GET /api/build/status` for the latest step + final result, so the page streams progress instead
  of blocking. `/api/build` is now start-and-poll (one build at a time; a second returns
  `{started:false, busy:true}`). `ChatService.message` stays synchronous as the testable core.

## Raw-bytes path (Plan §6 stretch — now implemented)
The end goal: a model that emits raw bytes which become a great binary. Two levels are built,
both sharing the trusted linker (`backend/layout.link`) and the harness repair loop:

- **Object level** (`raw.build_from_obj`) — the sweet spot. The model emits the literal `.text`
  machine-code bytes (it does the instruction *encoding* — the real machine-level work) plus a
  relocation list and the data/imports; the backend only links (RVA layout, IAT, PE container).
  This is an object file: bytes from the model, clerical layout from the trusted floor.
- **Full-PE level** (`raw.build_raw_pe`) — the purest flex. The model emits the entire `.exe` as
  bytes; the harness just writes and validates/runs it.

`validate_obj` gives structured errors (bad reloc offset, undeclared import, bad hex), and
`disassemble`/`run`/`crash_analysis` all work on raw-built binaries, so the same chatbot loop
drives byte-level self-repair (`Chatbot(..., builder=raw.build_from_obj)`). Demonstrated by
hand-emitting raw bytes that build and run (`examples/raw_hi.obj.json`). Per the plan this path
"may never beat the IR path," but the infrastructure and the repair loop for it now exist.

## Phase 4/5 starters (built ahead, compute-free)
- **Reward ladder** (`siryapsalot/reward.py`) — the Plan §5 RLVR reward, computed by the harness:
  IR validates → builds → loadable → runs → k/n tests → all tests → efficiency bonus, with
  partial credit (fraction of cases that ran, output similarity) so there is always a gradient.
  Reusable today as a richer eval metric.
- **Data harvester** (`siryapsalot/dataset.py`) — emits verified (intent → IR) supervised pairs
  and (intent → buggy IR → feedback → fixed IR) repair trajectories as JSONL. The full factory
  (compiling a real source corpus at multiple optimization levels for scale) builds on this
  same schema and is what remains gated on compute.

## Still deferred (revisit before the relevant phase) — Plan §11
- **Training compute** — gates the *training runs* and the full data factory. Needs a real number.
- **ISA** — x86-64 only (forced by Windows desktop target). ARM64 only if a 2nd target lands.
- **Register spilling** — implement when a program needs >7 simultaneous virtual registers.
- **Fidelity testing cadence** — how often to cross-check the emulator against real Windows/Wine.
- **Project name** — `siryapsalot` (codename); repo is `siryapsalot`.
