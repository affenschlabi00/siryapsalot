"""Instruction encoding (Keystone) with relocation generation.

Keystone does not resolve symbolic names, so the backend owns linking. Every symbolic
reference is emitted with a 4-byte zero placeholder positioned as the *last 4 bytes* of
the instruction and recorded as a Reloc; layout.py patches it as `target_VA-(field_VA+4)`
(verified for lea-RIP, call/jmp-[RIP], and rel32 branches). Decisions D5, D6.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from keystone import Ks, KS_ARCH_X86, KS_MODE_64

from .isa import JCC, is_register

_ks = Ks(KS_ARCH_X86, KS_MODE_64)

_DATA_REF = re.compile(r"data:([A-Za-z_]\w*)")
_IMPORT_REF = re.compile(r"^import:([\w.\-]+\.dll)!([A-Za-z_]\w*)$", re.IGNORECASE)
_IDENT = re.compile(r"^[A-Za-z_]\w*$")


class EncodeError(Exception):
    pass


@dataclass
class Reloc:
    text_off: int   # offset within .text of the 4-byte field to patch
    kind: str       # 'code' | 'data' | 'import'
    target: str     # label name, or "dll!func"


def _asm(text: str, addr: int = 0) -> bytes:
    try:
        encoding, _ = _ks.asm(text, addr)
    except Exception as e:  # keystone raises KsError
        raise EncodeError(f"could not encode `{text}`: {e}")
    if not encoding:
        raise EncodeError(f"keystone produced no bytes for `{text}`")
    return bytes(encoding)


def encode_one(op: str, args: list) -> tuple[bytes, Reloc | None]:
    """Encode a single lowered instruction (virtual regs already substituted)."""
    op = op.strip().lower()
    args = [str(a).strip() for a in args]

    # --- indirect call/jmp through the IAT: FF /2 and FF /4, [rip+disp32] ---
    if op in ("call", "jmp") and args and args[0].lower().startswith("import:"):
        m = _IMPORT_REF.match(args[0])
        if not m:
            raise EncodeError(f"malformed import operand: {args[0]}")
        target = f"{m.group(1).lower()}!{m.group(2)}"
        stub = b"\xff\x15" if op == "call" else b"\xff\x25"
        code = stub + b"\x00\x00\x00\x00"
        return code, Reloc(len(code) - 4, "import", target)

    # --- relative branches to code labels: E8/E9/0F8x + rel32 ---
    if (op in JCC or op in ("jmp", "call")) and args and _IDENT.match(args[0]) and not is_register(args[0]):
        target = args[0]
        if op == "jmp":
            code = b"\xe9" + b"\x00" * 4
        elif op == "call":
            code = b"\xe8" + b"\x00" * 4
        else:
            code = b"\x0f" + bytes([0x80 + JCC[op]]) + b"\x00" * 4
        return code, Reloc(len(code) - 4, "code", target)

    # --- data references via RIP-relative addressing ---
    data_target = None
    lowered = []
    for a in args:
        m = _DATA_REF.search(a)
        if m:
            if data_target is not None:
                raise EncodeError(f"at most one data reference per instruction (`{op} {args}`)")
            data_target = m.group(1)
            a = _DATA_REF.sub("rip + 0", a)
            if a.strip() == "rip + 0":      # bare `data:LABEL`, e.g. the source of `lea`
                a = "[rip + 0]"
        lowered.append(a)

    text = f"{op} {', '.join(lowered)}".strip()
    code = _asm(text)
    if data_target is not None:
        return code, Reloc(len(code) - 4, "data", data_target)
    return code, None


def compute_frame(num_saved: int, max_stack_off: int | None) -> int:
    """Frame bytes for `sub rsp, frame` so RSP is 16-aligned at every call (decision D3)."""
    min_frame = 32  # shadow space, always reserved
    if max_stack_off is not None:
        min_frame = max(min_frame, max_stack_off + 8)
    # At entry RSP%16==8; after `num_saved` pushes and `sub rsp,frame` we need RSP%16==0.
    target_mod = 8 if (num_saved % 2 == 0) else 0
    frame = min_frame
    while frame % 16 != target_mod:
        frame += 8
    return frame


def emit_prologue(saved: list[str], frame: int) -> bytes:
    out = b"".join(_asm(f"push {r}") for r in saved)
    if frame:
        out += _asm(f"sub rsp, {frame}")
    return out


def emit_epilogue(saved: list[str], frame: int) -> bytes:
    out = b""
    if frame:
        out += _asm(f"add rsp, {frame}")
    out += b"".join(_asm(f"pop {r}") for r in reversed(saved))
    out += _asm("ret")
    return out
