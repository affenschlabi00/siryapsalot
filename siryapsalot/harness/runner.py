"""run / trace / inspect / crash_analysis: thin wrappers over the one emulator engine."""
from __future__ import annotations

import time

from .emulator import Emulator


def _decode(b: bytes) -> str:
    return bytes(b).decode("utf-8", errors="replace")


def run(path: str, stdin: str | bytes = b"", args: list | None = None,
        timeout_ms: int = 5000, max_steps: int = 1_000_000) -> dict:
    """Execute in the sandboxed emulator; capture stdout/stderr/exit code."""
    emu = Emulator(path, stdin=stdin if isinstance(stdin, (bytes, bytearray))
                   else str(stdin or "").encode())
    t0 = time.perf_counter()
    res = emu.execute(max_steps=max_steps)
    dt = (time.perf_counter() - t0) * 1000.0
    return {
        "exit_code": res["exit_code"],
        "stdout": _decode(res["stdout"]),
        "stderr": _decode(res["stderr"]),
        "time_ms": round(dt, 2),
        "crashed": res["crashed"],
        "truncated": res["truncated"],
        "instructions_executed": res["instr_count"],
        "files": {k: _decode(v) for k, v in res["vfs"].items()},
        "dialogs": res["dialogs"],
        "windows": res["windows"],
        "controls": res["controls"],
        "sounds": res["sounds"],
        "events": res["events"],
        "screen": res["screen"],
    }


def trace(path: str, stdin: str | bytes = b"", args: list | None = None,
          max_steps: int = 100_000) -> dict:
    """Run recording every step — the deterministic execution movie (Plan §6)."""
    emu = Emulator(path, stdin=stdin if isinstance(stdin, (bytes, bytearray))
                   else str(stdin or "").encode())
    res = emu.execute(max_steps=max_steps, record=True)
    return {
        "steps": res["steps"],
        "summary": {
            "instructions_executed": res["instr_count"],
            "api_calls": len(res["api_calls"]),
            "ended": res["ended"] or ("crash" if res["crashed"] else "max_steps"),
            "exit_code": res["exit_code"],
            "stdout": _decode(res["stdout"]),
            "truncated": res["truncated"],
        },
    }


def inspect(path: str, at: dict, stdin: str | bytes = b"") -> dict:
    """State snapshot at a step index or breakpoint RVA."""
    emu = Emulator(path, stdin=stdin if isinstance(stdin, (bytes, bytearray))
                   else str(stdin or "").encode())
    kwargs = {}
    if "step" in at:
        kwargs["stop_step"] = int(at["step"])
    elif "breakpoint_rva" in at:
        kwargs["stop_bp"] = emu.image_base + int(str(at["breakpoint_rva"]), 0)
    res = emu.execute(max_steps=1_000_000, **kwargs)
    snap = res["snapshot"] or emu._snapshot()

    # best-effort call stack: stack slots that point back into an executable section
    call_stack = []
    text_secs = [(emu.image_base + s.virtual_address,
                  emu.image_base + s.virtual_address + s.virtual_size)
                 for s in emu.bin.sections if int(s.characteristics) & 0x20000000]
    for slot in snap.get("stack", []):
        v = int(slot["value"], 16)
        if any(lo <= v < hi for lo, hi in text_secs):
            call_stack.append(slot["value"])

    return {
        "registers": snap["registers"],
        "stack": snap["stack"],
        "memory_regions": [{"name": s.name, "base": f"{emu.image_base + s.virtual_address:#x}",
                            "size": s.virtual_size} for s in emu.bin.sections],
        "call_stack": call_stack,
        "reached": res["snapshot"] is not None,
    }


def crash_analysis(path: str, stdin: str | bytes = b"") -> dict:
    """On fault, decode why it died with a likely-cause heuristic (Plan §6)."""
    emu = Emulator(path, stdin=stdin if isinstance(stdin, (bytes, bytearray))
                   else str(stdin or "").encode())
    res = emu.execute(max_steps=1_000_000)
    if not res["crashed"]:
        return {"crashed": False, "exit_code": res["exit_code"],
                "note": "program ran to completion without faulting"}

    f = res["fault"]
    regs = f["registers"]
    ins = f["fault_instruction"]
    likely = _likely_cause(ins, regs, f.get("target_addr"))
    return {
        "crashed": True,
        "fault_addr": f["fault_addr"],
        "fault_instruction": ins,
        "reason": f["access"],
        "target_addr": f.get("target_addr"),
        "registers_at_fault": {k: v for k, v in regs.items()
                               if k in ins["operands"] or k in ("rip", "rsp")},
        "likely_cause": likely,
    }


def _likely_cause(ins: dict, regs: dict, target_addr: str | None) -> str:
    ops = ins["operands"]
    zero_regs = [r for r in regs if r in ops and int(regs[r], 16) == 0]
    if target_addr is not None and int(target_addr, 16) < 0x1000:
        culprit = f": {zero_regs[0]} is 0" if zero_regs else ""
        return f"null pointer dereference{culprit}"
    if zero_regs:
        return f"dereference through zero register {zero_regs[0]}"
    if "div" in ins["mnemonic"]:
        return "division error (divide by zero or overflow)"
    return f"access to unmapped memory at {target_addr or ins['operands']}"
