# Sir Yaps-a-Lot — Execution Plan (kickoff brief)

This is the condensed source-of-truth plan the repository implements. The full reusable
artifacts it calls for — the **IR spec** and the **MCP tool schemas** — now live as code:
`schema/ir.schema.json` and the functions in `bytewright/harness/` (mirrored by
`bytewright/mcp_server.py`). See [`design.md`](design.md) for how it was built and
[`../decisions.md`](../decisions.md) for the decision log.

## TL;DR

"AI writes the binary directly" is made buildable by two reframes:

1. **The model emits a verifiable machine-level IR, not raw bytes.** A deterministic backend
   turns IR into real bytes, deleting the entire class of "one wrong offset → loader rejects
   it" errors. The model does the semantic, machine-level work; the backend does the
   error-intolerant clerical work (encode, allocate, lay out, link, build PE).
2. **Build the verifier/debugger BEFORE the generator.** One harness is correctness checker,
   debugger, and (later) RL reward signal.

## Three locked decisions

| Decision | Choice |
|---|---|
| How "pure" is binary-writing? | IR + trusted backend (main line); raw-hex emission a Phase 6 stretch. |
| Train or scaffold v1? | Scaffold a frontier model through the harness first; training is later. |
| First target? | Windows `.exe` (x86-64 PE) from day one. |

## The pipeline

```
intent ─▶ Generator(model) ─▶ IR(JSON) ─▶ Backend(deterministic) ─▶ .exe ─▶ Harness(emulated) ─▶ feedback ─┐
            ▲                                                                                                │
            └────────────────────────── repair loop / RL reward ────────────────────────────────────────────┘
```

## Phased plan & build order

> **Phase 1 (harness) → Phase 2 (backend) → Phase 3 (scaffolded agent)** delivers a real,
> working "AI that writes `.exe` files." Then branch into the **(4 → 5)** training track and
> **(6)** hardening. Build the judge before the player; keep the backend deterministic; let
> the harness be debugger, grader, and reward.

- **Phase 0 — Scope, repo, IR freeze.** Repo scaffold, frozen IR schema + `hello` example,
  decision log. *Acceptance:* schema validates hello; tests run.
- **Phase 1 — Harness / MCP server (FIRST).** All §6 tools over an emulator; validate against
  known-good compiler-built exes. *Acceptance:* run/trace/validate a hello exe; crash_analysis
  diagnoses a deliberately broken binary.
- **Phase 2 — Deterministic backend.** IR → `.exe`, correct-by-construction. *Acceptance:*
  `build_binary(hello)` runs and prints; round-trip and differential tests pass.
- **Phase 3 — Agentic scaffolding.** A loop: task → IR → build → validate → run/diff →
  read trace/crash on failure → repair. *Acceptance:* autonomously solves the task suite,
  logging trajectories (future training data).
- **Phase 4 — Training-data factory.** (intent → IR/binary) pairs *with reasoning* from
  compiled source at multiple opt levels + harvested repair trajectories.
- **Phase 5 — Train: distill, then RLVR.** Harness is the reward; dense reward ladder
  (validates → builds → loadable → runs → k/n tests → all tests → fewer instructions).
- **Phase 6 — Harden & expand.** Larger programs, more Win32 surface (GUI), angr bounded
  equivalence, model-driven real-register mode, the raw-hex stretch, optional 2nd ISA.

## Tech stack

Python harness/backend. **Keystone** (asm→bytes), **Capstone** (bytes→asm), **LIEF** (PE
parse/validate), **Unicorn** (CPU emulation; the harness core), **Qiling/Wine** (optional
fidelity), **angr** (Phase 6 symbolic checks), **MCP SDK** (tool surface).

## IR (summary — full schema in `schema/ir.schema.json`)

Assembly-level: real x86-64 mnemonics; **names not numbers** for jump targets (labels),
Win32 APIs (`import:dll!func`), data (`data:label`), and virtual registers (`%vN`). Machine-
checkable and round-trippable. `metadata` (name/subsystem/entry) · `imports` · `data` · `code`
(procedures of instructions). Worked example: [`../examples/hello.ir.json`](../examples/hello.ir.json).

## Harness tools (summary — see `bytewright/harness/`)

`build_binary` · `validate_pe` · `disassemble` · `run` · `trace` · `inspect` ·
`crash_analysis` · `diff_behavior` · `list_imports` · `resolve_api`. These are the agent's
senses: construct, statically validate, read back, execute, record an execution movie,
snapshot state, decode crashes, diff against an oracle, and learn how to call an API.

## Risks & honest limitations (Plan §9)

Scaling is the real wall — small self-contained algorithmic programs are very doable; large
programs are where compilers' decades of work earn their keep. Correctness means *tests
passing* (+ bounded symbolic checks later), not proofs. The Win32 surface is large — start
tiny, grow deliberately. Emulator ≠ real Windows on edge cases — mitigate with fidelity
sampling. Keep the backend deterministic; the moment the model "helps with layout," the
trusted floor cracks.
