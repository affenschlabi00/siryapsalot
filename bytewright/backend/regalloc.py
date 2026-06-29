"""Virtual-register allocation (decision D4).

v1 is intentionally simple: bind each distinct %vN in a procedure to a callee-saved
register. Callee-saved means the value survives across API calls by construction, and
never collides with the caller-saved registers the model uses for args/scratch.
Spilling (>7 live virtual regs) is a documented v1 limitation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .isa import CALLEE_SAVED_POOL

_VREG = re.compile(r"%v(\d+)")


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


def allocate(proc: dict) -> ProcAlloc:
    vregs = find_vregs(proc)
    if len(vregs) > len(CALLEE_SAVED_POOL):
        raise NotImplementedError(
            f"procedure '{proc.get('label')}' uses {len(vregs)} virtual registers; "
            f"v1 supports at most {len(CALLEE_SAVED_POOL)} (register spilling not implemented). "
            f"See decision D4.")
    alloc = ProcAlloc()
    for v, phys in zip(vregs, CALLEE_SAVED_POOL):
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
