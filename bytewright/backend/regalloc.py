"""Virtual-register allocation (decision D4).

v1 is intentionally simple: bind each distinct %vN in a procedure to a callee-saved
register. Callee-saved means the value survives across API calls by construction, and
never collides with the caller-saved registers the model uses for args/scratch.
Spilling (>7 live virtual regs) is a documented v1 limitation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .isa import ALL_REGS, CALLEE_SAVED_POOL, REG64, reg_index

_VREG = re.compile(r"%v(\d+)")
_TOKEN = re.compile(r"[a-z][a-z0-9]*")


@dataclass
class ProcAlloc:
    mapping: dict[str, str] = field(default_factory=dict)   # "%v0" -> "r12"
    saved: list[str] = field(default_factory=list)          # callee-saved regs to push/pop


def find_vregs(proc: dict) -> list[str]:
    seen: list[str] = []
    for ins in proc.get("instructions", []):
        for a in ins.get("args", []) or []:
            for m in _VREG.finditer(str(a)):
                v = f"%v{m.group(1)}"
                if v not in seen:
                    seen.append(v)
    return seen


def model_used_callee_saved(proc: dict) -> set[str]:
    """Callee-saved registers the model names directly (so the allocator avoids them).

    Maps any sub-register (ebx, bx, bl -> rbx) to its 64-bit form. This prevents %vN from
    colliding with a real register the model already uses (decision D4).
    """
    used: set[str] = set()
    for ins in proc.get("instructions", []):
        for a in ins.get("args", []) or []:
            for tok in _TOKEN.findall(str(a).lower()):
                if tok in ALL_REGS and tok != "rip":
                    r64 = REG64[reg_index(tok)]
                    if r64 in CALLEE_SAVED_POOL:
                        used.add(r64)
    return used


def allocate(proc: dict) -> ProcAlloc:
    vregs = find_vregs(proc)
    pool = [r for r in CALLEE_SAVED_POOL if r not in model_used_callee_saved(proc)]
    if len(vregs) > len(pool):
        raise NotImplementedError(
            f"procedure '{proc.get('label')}' needs {len(vregs)} virtual registers but only "
            f"{len(pool)} callee-saved registers are free (the model uses the others directly, "
            f"or there are too many %vN; register spilling is not implemented). See decision D4.")
    alloc = ProcAlloc()
    for v, phys in zip(vregs, pool):
        alloc.mapping[v] = phys
        alloc.saved.append(phys)
    return alloc


def substitute(arg: str, alloc: ProcAlloc) -> str:
    """Replace %vN tokens in an operand string with their allocated physical register."""
    def repl(m: re.Match) -> str:
        v = f"%v{m.group(1)}"
        if v not in alloc.mapping:
            raise KeyError(f"unallocated virtual register {v}")
        return alloc.mapping[v]
    return _VREG.sub(repl, arg)
