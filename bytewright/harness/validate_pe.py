"""validate_pe + list_imports: static structural validation via LIEF (Plan §6).

Answers "will the loader accept this?" before we ever execute it. Uses LIEF as an
independent parser of the hand-built PE (decision D2).
"""
from __future__ import annotations

import lief

_SUBSYS = {2: "gui", 3: "console"}


def validate_pe(path: str) -> dict:
    b = lief.parse(path)
    if b is None:
        return {"ok": False, "format_ok": False, "issues": [f"not a parseable PE: {path}"]}

    oh = b.optional_header
    magic = "PE32+" if oh.magic == lief.PE.PE_TYPE.PE32_PLUS else "PE32"
    subsystem = _SUBSYS.get(int(oh.subsystem), str(oh.subsystem))
    entry = oh.addressof_entrypoint

    sections = []
    for s in b.sections:
        flags = ""
        c = int(s.characteristics)
        flags += "R" if c & 0x40000000 else ""
        flags += "W" if c & 0x80000000 else ""
        flags += "X" if c & 0x20000000 else ""
        sections.append({"name": s.name, "rva": f"{s.virtual_address:#x}",
                         "size": s.virtual_size, "flags": flags})

    imports = []
    for imp in b.imports:
        for e in imp.entries:
            imports.append({"dll": imp.name, "function": e.name or f"ord{e.ordinal}",
                            "iat_rva": f"{e.iat_address:#x}"})

    # structural checks
    issues = []
    exec_secs = [s for s in b.sections if int(s.characteristics) & 0x20000000]
    in_exec = any(s.virtual_address <= entry < s.virtual_address + s.virtual_size for s in exec_secs)
    if not in_exec:
        issues.append("entry point is not inside an executable section")
    if b.header.machine != lief.PE.Header.MACHINE_TYPES.AMD64:
        issues.append(f"machine is not AMD64 ({b.header.machine})")
    if not imports:
        issues.append("no imports (program cannot call any Win32 API)")

    return {
        "ok": not issues,
        "format_ok": True,
        "headers": {"magic": magic, "subsystem": subsystem,
                    "image_base": f"{oh.imagebase:#x}"},
        "entry_point": f"{entry:#x}",
        "sections": sections,
        "imports": imports,
        "issues": issues,
    }


def list_imports(path: str) -> dict:
    b = lief.parse(path)
    if b is None:
        return {"imports": [], "error": f"could not parse {path}"}
    out = []
    for imp in b.imports:
        for e in imp.entries:
            out.append({"dll": imp.name, "function": e.name or f"ord{e.ordinal}",
                        "iat_rva": f"{e.iat_address:#x}"})
    return {"imports": out}
