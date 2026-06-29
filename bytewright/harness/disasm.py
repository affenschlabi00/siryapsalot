"""disassemble: bytes -> instructions (Capstone). Round-trip verification (Plan §6)."""
from __future__ import annotations

import lief
from capstone import Cs, CS_ARCH_X86, CS_MODE_64


def disassemble(path: str, range: dict | None = None) -> dict:
    b = lief.parse(path)
    if b is None:
        return {"instructions": [], "error": f"could not parse {path}"}
    base = b.optional_header.imagebase

    if range and "start_rva" in range:
        start_rva = int(str(range["start_rva"]), 0)
    else:
        start_rva = b.optional_header.addressof_entrypoint
    count = int(range["count"]) if range and "count" in range else 64

    sec = None
    for s in b.sections:
        if s.virtual_address <= start_rva < s.virtual_address + s.virtual_size:
            sec = s
            break
    if sec is None:
        return {"instructions": [], "error": f"rva {start_rva:#x} not in any section"}

    off = start_rva - sec.virtual_address
    code = bytes(sec.content)[off:]
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    out = []
    for ins in md.disasm(code, base + start_rva):
        out.append({"addr": f"{ins.address:#x}", "mnemonic": ins.mnemonic,
                    "operands": ins.op_str, "bytes": code[ins.address - (base + start_rva):
                                                           ins.address - (base + start_rva) + ins.size].hex()})
        if len(out) >= count:
            break
    return {"instructions": out}
