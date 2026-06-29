# Design notes (as built)

How the implementation realizes the plan, and the engineering choices behind it. Pairs with
[`../decisions.md`](../decisions.md) (the decision log) and [`this-plan.md`](this-plan.md).

## The pipeline, concretely

```
examples/foo.ir.json
   │  siryapsalot.backend.build_binary(ir, out)
   ▼
validate_ir → regalloc → encode(+relocs) → layout(link) → imports(IAT) → pe_builder → foo.exe
   │  siryapsalot.harness.run/trace/inspect/crash_analysis(...)
   ▼
Unicorn emulator: map PE, redirect IAT to Python API hooks, execute with full observability
```

## The relocation scheme (the crux of the backend)

Keystone encodes instructions to bytes but **does not resolve symbolic names** — that is
the backend's job (this is *why* the IR split is buildable: the model never does byte math).
The trick that keeps it simple and correct:

Every symbolic reference is emitted so its 32-bit address field is the **last 4 bytes** of
the instruction, and is position-independent (RIP-relative). Verified forms:

| IR | machine form | bytes (field = last 4) |
|---|---|---|
| `lea reg, data:LABEL` | `lea reg, [rip+disp32]` | `48 8D /r disp32` |
| `call import:dll!fn` | `call [rip+disp32]` | `FF 15 disp32` |
| `jmp/call/jCC label` | near `rel32` | `E9/E8/0F8x disp32` |

After layout assigns every symbol a virtual address, each field is patched uniformly:

```
disp = target_VA − (field_VA + 4)        # field_VA+4 == address of the next instruction == RIP
```

One formula for branches, data refs, and import calls. No `.reloc` section is needed
(decision D5), so the PE is marked relocs-stripped and non-relocatable.

## Backend-owned calling convention (decision D3)

The single biggest source of hand-written-assembly bugs is the Microsoft x64 convention
(arg registers, 32-byte shadow space, 16-byte stack alignment at every `call`). So the model
does **not** manage the stack frame. Per procedure the backend:

1. allocates each `%vN` to a callee-saved register (`rbx, rsi, rdi, r12–r15`) — values then
   survive across API calls by construction (decision D4);
2. emits a prologue: `push` the used callee-saved regs, then `sub rsp, frame`;
3. sizes `frame` to cover shadow space (32B) + the deepest `[rsp+N]` outgoing stack arg, then
   rounds it so RSP is 16-aligned at every call (accounting for the pushes);
4. expands `ret` into the matching epilogue.

The model writes the 5th+ stack arguments directly as `[rsp+32]`, `[rsp+40]`, … — these are
correct regardless of total frame size because outgoing args sit at the bottom of the frame.

## The harness emulator (decision D1)

Built directly on Unicorn rather than Qiling, because the `qiling` package ships no Windows
rootfs and a real one means licensed DLLs. Since the backend controls the imported API set,
we implement those APIs in Python (`harness/apidb.py`) and wire them in like this:

- Map the image at its `ImageBase`; **leave the null page unmapped** so null derefs fault.
- Map a small executable "hook page" filled with `ret` (`0xC3`). Give each imported function
  a unique address on that page and write it into the function's IAT slot.
- When a `call [iat slot]` lands on a hook address, a `UC_HOOK_CODE` callback runs the Python
  API (reads args per the x64 convention, performs side effects, sets RAX); the `0xC3` then
  returns to the caller. `ExitProcess` stops the engine. A sentinel return address on the
  stack turns a top-level `ret` into a clean process exit.

This gives total deterministic observability — single-step, full memory, every API call —
which is the whole reason to emulate instead of run on hardware. The one `execute()` engine
backs `run`, `trace`, `inspect`, and `crash_analysis`.

**Sandboxing:** pure emulation (no host syscalls), a virtual in-memory filesystem, an
instruction-count cap, and a wall-clock timeout. Every candidate binary is treated as
untrusted. Real-Windows/Wine fidelity sampling is a documented future path.

## Verification posture

- **Round-trip:** `disassemble(build(ir))` recovers the intended instructions (Capstone).
- **Independent structural check:** LIEF parses the hand-built PE (`validate_pe`).
- **Differential:** `diff_behavior` compares a candidate against a reference exe or a Python
  oracle across input cases.
- These are *tests passing* + structural validity, not proofs. Bounded symbolic equivalence
  (angr) for small fragments is a Phase 6 item — we don't claim more (Plan §9).
