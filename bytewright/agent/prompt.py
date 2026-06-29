"""Prompt construction for the model-driven generator (Plan §3).

Assembles the system prompt from the *live* IR schema, the *live* API surface, and real
worked examples so it can never drift from what the backend/harness actually accept. This is
where most of the "make it reliable" work lives: the clearer the contract and the better the
few-shot examples, the higher the model's first-try success rate.
"""
from __future__ import annotations

import json
import os

from ..harness import apidb

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def _schema() -> dict:
    with open(os.path.join(_ROOT, "schema", "ir.schema.json")) as fh:
        return json.load(fh)


def _example(name: str) -> str:
    with open(os.path.join(_ROOT, "examples", name)) as fh:
        return fh.read().strip()


RULES = """\
You write programs as Bytewright IR: a JSON object of real x86-64 instructions with symbolic
names. A trusted deterministic backend turns your IR into a real Windows .exe, so you never
compute byte offsets, encodings, or addresses.

Contract you MUST follow:
- The backend OWNS the stack frame. Do NOT emit push, pop, sub rsp, add rsp, leave, or enter.
  It inserts the prologue/epilogue, reserves 32 bytes of shadow space, and keeps RSP aligned.
- Registers: name real registers directly (rax, rcx, ...). For values that must survive across
  API calls, use virtual registers %v0, %v1, ... — the backend binds them to callee-saved
  registers and saves/restores them. Up to 7 virtual registers per procedure.
- Microsoft x64 calling convention: integer/pointer args go in rcx, rdx, r8, r9; the 5th and
  later args go on the stack at [rsp+32], [rsp+40], ... (write them there yourself). Return
  value is in rax. Call APIs with `call` and the operand `import:dll!Function`.
- Reference data with `data:LABEL` (e.g. `lea rdx, data:msg`, or `mov r8d, dword ptr [data:n]`).
  Reference code labels by bare name in jmp/jcc/call. A label is its own instruction object:
  {"label": "loop"}. Inside a procedure, `ret` is allowed (the backend expands the epilogue).
- The ENTRY procedure must end by calling ExitProcess. To print, get a handle with
  GetStdHandle(-11) for stdout / -10 for stdin, then use WriteFile / ReadFile.
- Storing an immediate directly into a data label is not supported; load its address with
  `lea` first, then store through the register.
- Reply with ONLY a single JSON IR object — no prose, no markdown fences.

Useful patterns:
- itoa: put the number in rax; repeatedly `xor rdx,rdx; div r9` (r9=10); `add dl,48` gives a
  digit; write digits into a buffer from the end backwards; then WriteFile the slice.
- atoi: loop bytes; for each ASCII digit d: `imul acc,acc,10; add acc,(d-48)`; stop on non-digit.
"""


def available_apis() -> str:
    lines = []
    for name, sig in apidb.SIGNATURES.items():
        lines.append(f"- {name} ({sig['dll']}): {sig['signature']} ; args in {sig['arg_registers']}")
    return "\n".join(lines)


def system_prompt() -> str:
    return (
        RULES
        + "\n\nAPIs the harness implements (you may only import these):\n"
        + available_apis()
        + "\n\nIR JSON schema:\n"
        + json.dumps(_schema())
        + "\n\nExample 1 — print a string:\n" + _example("hello.ir.json")
        + "\n\nExample 2 — a loop that prints 1..5:\n" + _example("count.ir.json")
    )


CHATBOT_ROLE = """\
You are a chatbot that builds working Windows .exe programs from a user's plain-English
request. The user will NOT specify input formats, test cases, or anything technical — infer
everything yourself, make reasonable choices, and just build something that works.

Respond with ONLY a single JSON object (no prose, no markdown fences):
{
  "program_name": "<short snake_case name>",
  "explanation": "<one friendly sentence describing what the program does>",
  "ir": { ... a complete Bytewright IR object, per the rules and schema below ... },
  "self_tests": [
    {"stdin": "<input, or empty string>", "expect_contains": "<substring stdout must contain>"}
  ]
}
Propose 1-3 self_tests that would convince a skeptic the program meets the request — pick
representative inputs yourself. Each self_test may use any of:
  "expect_equals"          the exact stdout,
  "expect_contains"        a substring of stdout,
  "expect_screen_contains" a substring of the rendered console screen (for programs that draw
                           with SetConsoleCursorPosition / FillConsoleOutputCharacterA),
  "expect_dialog_contains" text shown in a MessageBox (for GUI programs).

CAPABILITY & SCOPE — read carefully. You CAN build:
- console (text) programs: console + file I/O, arithmetic, loops, branches;
- turn-based INTERACTIVE programs (stdin is line-buffered — loop reading lines);
- POSITIONED / colored console output (SetConsoleCursorPosition, SetConsoleTextAttribute,
  FillConsoleOutputCharacterA) — boxes, boards, simple frames;
- simple GUI dialogs via user32 MessageBoxA (set metadata.subsystem = "gui").
You CANNOT (yet): custom windows/controls, real-time keyboard, graphics/sprites, or sound — so a
real-time graphical game (live-key "Tetris"/"Snake") is out of reach.
- NEVER refuse. If a request needs something you lack, build the closest version that captures
  the spirit (a turn-based or positioned-text rendering) and SAY SO in "explanation". Ship it.
"""


def chatbot_system_prompt() -> str:
    return CHATBOT_ROLE + "\n\n" + system_prompt()


def user_prompt(intent: str, feedback: str | None = None, cases=None) -> str:
    msg = f"Build this program:\n{intent}"
    if cases:
        shown = [c for c in cases if c.get("stdin")]
        if shown:
            msg += "\n\nIt will be tested with stdin inputs like: " + ", ".join(
                repr(c["stdin"]) for c in shown[:5])
    if feedback:
        msg += (f"\n\nYour previous attempt did not work. Harness feedback:\n{feedback}\n\n"
                "Return a corrected IR JSON object.")
    return msg
