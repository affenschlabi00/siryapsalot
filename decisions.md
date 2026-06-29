# Decision log — Sir Yaps-a-Lot (`bytewright`)

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
**Unicorn-based emulator** (`bytewright/harness/emulator.py`) that intercepts each
imported API with a Python implementation (`bytewright/harness/apidb.py`).

Why this is better here, not just easier:
- No rootfs, no Windows-DLL licensing, fully reproducible from `pip install`.
- Total deterministic observability (single-step, full memory, every API call) — which
  is the entire point of emulating instead of running on hardware (Plan §1).
- The API surface grows deliberately and is auditable in one file.

Qiling/Wine remain a **documented future fidelity path** (Plan §6 "fidelity sampling"):
run a sampled subset on a real loader to confirm the emulator matches. Tracked, not built.

### D2 — PE construction: **hand-rolled writer** is primary; **LIEF** is the independent checker
The plan offers LIEF (build) with a hand-rolled writer as an optional purity path. We
inverted it: `bytewright/backend/pe_builder.py` writes the PE container by hand (full
control over RVA/IAT layout, which our RIP-relative relocations depend on), and the
harness uses **LIEF** to *independently parse and validate* the result
(`bytewright/harness/validate_pe.py`). Build-by-hand + check-with-an-independent-library
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
The product is a chatbot that builds binaries: `bytewright` (terminal) or `bytewright serve`
(browser GUI). The IR is an internal implementation detail — users never see it; they chat and
get a `.exe`. The model backend is pluggable (`bytewright/llm.py`, `make_backend`): it uses the
Anthropic API if `ANTHROPIC_API_KEY` is set, otherwise a local **Ollama** model (auto-detected,
or `OLLAMA_MODEL`) — so no API key is required. Ollama runs are constrained to JSON output
(`format=json`) for reliability. The web UI is pure stdlib (`http.server`), no new dependency.

## D8 — GUI: message boxes and real windows (Plan §6)
The harness implements `user32` GUI APIs (`MessageBoxA`, `RegisterClassExA`, `CreateWindowExA`,
`ShowWindow`, the `GetMessageA` message loop, etc.) and *records* dialogs and windows
(title/size). `GetMessageA` returns 0 so a standard message loop exits cleanly under emulation;
the emitted `.exe` is a genuine Win32 GUI program that shows a window on real Windows. A new
`code:LABEL` operand takes a function pointer to a procedure (e.g. the window proc). What's not
emulated yet: interactive control/click handling, real-time input, graphics, sound. The chatbot
self-tests GUI programs with `expect_dialog_contains` / `expect_window_contains`.

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
- **Reward ladder** (`bytewright/reward.py`) — the Plan §5 RLVR reward, computed by the harness:
  IR validates → builds → loadable → runs → k/n tests → all tests → efficiency bonus, with
  partial credit (fraction of cases that ran, output similarity) so there is always a gradient.
  Reusable today as a richer eval metric.
- **Data harvester** (`bytewright/dataset.py`) — emits verified (intent → IR) supervised pairs
  and (intent → buggy IR → feedback → fixed IR) repair trajectories as JSONL. The full factory
  (compiling a real source corpus at multiple optimization levels for scale) builds on this
  same schema and is what remains gated on compute.

## Still deferred (revisit before the relevant phase) — Plan §11
- **Training compute** — gates the *training runs* and the full data factory. Needs a real number.
- **ISA** — x86-64 only (forced by Windows desktop target). ARM64 only if a 2nd target lands.
- **Register spilling** — implement when a program needs >7 simultaneous virtual registers.
- **Fidelity testing cadence** — how often to cross-check the emulator against real Windows/Wine.
- **Project name** — `bytewright` (codename); repo is `siryapsalot`.
