"""Layout & link: IR procedures + data -> laid-out sections with all symbols resolved.

This is where the trusted floor does its clerical work: assemble .text (with backend
prologue/epilogue and virtual-register saves), build data sections, assign RVAs honoring
section alignment, construct the import blob, then patch every relocation. Decisions D3-D6.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

from . import encode, imports, regalloc

IMAGE_BASE = 0x140000000
SECTION_ALIGN = 0x1000
FILE_ALIGN = 0x200
TEXT_RVA = 0x1000

_INT_FMT = {"u8": "<B", "u16": "<H", "u32": "<I", "u64": "<Q",
            "i8": "<b", "i16": "<h", "i32": "<i", "i64": "<q"}
_RSP_OFF = re.compile(r"\[\s*rsp\s*\+\s*(0x[0-9a-fA-F]+|\d+)\s*\]")


class LayoutError(Exception):
    pass


@dataclass
class Section:
    name: str
    rva: int
    characteristics: int
    data: bytes
    file_off: int = 0       # filled in by pe_builder

    @property
    def vsize(self) -> int:
        return len(self.data)


@dataclass
class LayoutResult:
    sections: list[Section]
    entry_rva: int
    image_base: int = IMAGE_BASE
    import_dir_rva: int = 0
    import_dir_size: int = 0
    iat_rva: int = 0
    iat_size: int = 0
    symbols: dict[str, int] = field(default_factory=dict)   # name -> VA (for reports/debug)
    code_size: int = 0


def _align(n: int, a: int) -> int:
    return (n + a - 1) & ~(a - 1)


def _encode_data_item(d: dict) -> tuple[bytes, bool]:
    """Return (bytes, is_writable)."""
    t = d["type"]
    if t in ("bytes", "utf8"):
        v = d.get("value", "")
        if isinstance(v, list):
            return bytes(int(x) & 0xFF for x in v), False
        return str(v).encode("utf-8"), False
    if t == "zeros":
        return b"\x00" * int(d["size"]), True
    return struct.pack(_INT_FMT[t], int(d.get("value", 0))), True


def _max_stack_off(proc: dict) -> int | None:
    hi = None
    for ins in proc.get("instructions", []):
        for a in ins.get("args", []) or []:
            for m in _RSP_OFF.finditer(str(a)):
                off = int(m.group(1), 0)
                hi = off if hi is None else max(hi, off)
    return hi


def _assemble_text(ir: dict):
    """Build .text. Returns (text bytearray, symbols{name->text_off}, relocs[list])."""
    text = bytearray()
    symbols: dict[str, int] = {}
    relocs: list[encode.Reloc] = []

    # local label sets per proc (for scoping branch targets)
    local_labels: dict[str, set] = {}
    for proc in ir["code"]:
        ls = set()
        for ins in proc["instructions"]:
            if "op" not in ins and "label" in ins:
                ls.add(ins["label"])
        local_labels[proc["label"]] = ls

    for proc in ir["code"]:
        pl = proc["label"]
        alloc = regalloc.allocate(proc)
        frame = encode.compute_frame(len(alloc.saved), _max_stack_off(proc))

        symbols[pl] = len(text)                       # proc entry = start of prologue
        text += encode.emit_prologue(alloc.saved, frame)

        for ins in proc["instructions"]:
            if "op" not in ins:                       # local label marker
                symbols[f"{pl}::{ins['label']}"] = len(text)
                continue
            op = ins["op"].strip().lower()
            args = [regalloc.substitute(str(a), alloc) for a in ins.get("args", [])]

            if op == "ret":                           # backend-expanded epilogue
                text += encode.emit_epilogue(alloc.saved, frame)
                continue

            code, reloc = encode.encode_one(op, args)
            base = len(text)
            text += code
            if reloc is not None:
                if reloc.kind == "code" and reloc.target in local_labels[pl]:
                    reloc.target = f"{pl}::{reloc.target}"   # scope to this proc
                reloc.text_off += base
                relocs.append(reloc)

    return text, symbols, relocs


def layout(ir: dict) -> LayoutResult:
    # ---- .text ----
    text, text_syms, relocs = _assemble_text(ir)
    code_size = len(text)

    # ---- data items: split read-only vs writable ----
    ro_chunks: list[tuple[str, bytes]] = []
    w_chunks: list[tuple[str, bytes]] = []
    for d in ir.get("data", []):
        blob, writable = _encode_data_item(d)
        (w_chunks if writable else ro_chunks).append((d["label"], blob))

    # ---- assign section RVAs ----
    rdata_rva = _align(TEXT_RVA + code_size, SECTION_ALIGN)
    imp = imports.build_imports(ir.get("imports", []), rdata_rva)

    # read-only data follows the import blob inside .rdata
    ro_base = len(imp.blob)
    ro_off: dict[str, int] = {}
    rdata = bytearray(imp.blob)
    for label, blob in ro_chunks:
        ro_off[label] = len(rdata)
        rdata += blob

    data_rva = _align(rdata_rva + len(rdata), SECTION_ALIGN) if rdata else rdata_rva
    w_off: dict[str, int] = {}
    data = bytearray()
    for label, blob in w_chunks:
        w_off[label] = len(data)
        data += blob

    # ---- symbol -> VA resolution ----
    def code_va(name: str) -> int:
        return IMAGE_BASE + TEXT_RVA + text_syms[name]

    sym_va: dict[str, int] = {}
    for label, off in ro_off.items():
        sym_va[label] = IMAGE_BASE + rdata_rva + off
    for label, off in w_off.items():
        sym_va[label] = IMAGE_BASE + data_rva + off

    # ---- patch relocations ----
    for r in relocs:
        if r.kind == "code":
            target_va = code_va(r.target)
        elif r.kind == "data":
            if r.target not in sym_va:
                raise LayoutError(f"unresolved data label '{r.target}'")
            target_va = sym_va[r.target]
        elif r.kind == "import":
            if r.target not in imp.slot_rva:
                raise LayoutError(f"unresolved import '{r.target}'")
            target_va = IMAGE_BASE + imp.slot_rva[r.target]
        else:
            raise LayoutError(f"unknown reloc kind {r.kind}")
        field_va = IMAGE_BASE + TEXT_RVA + r.text_off
        disp = target_va - (field_va + 4)
        if not (-0x80000000 <= disp <= 0x7FFFFFFF):
            raise LayoutError(f"relocation out of 32-bit range for {r.target}")
        struct.pack_into("<i", text, r.text_off, disp)

    entry_label = ir["metadata"]["entry"]
    if entry_label not in text_syms:
        raise LayoutError(f"entry '{entry_label}' not found in code")
    entry_rva = TEXT_RVA + text_syms[entry_label]

    # ---- sections ----
    sections = [Section(".text", TEXT_RVA, 0x60000020, bytes(text))]   # CODE|EXEC|READ
    if rdata:
        sections.append(Section(".rdata", rdata_rva, 0x40000040, bytes(rdata)))  # IDATA|READ
    if data:
        sections.append(Section(".data", data_rva, 0xC0000040, bytes(data)))     # IDATA|R|W

    symbols_report = {**{k: code_va(k) for k in text_syms}, **sym_va}
    for k, v in imp.slot_rva.items():
        symbols_report[f"iat:{k}"] = IMAGE_BASE + v

    return LayoutResult(
        sections=sections,
        entry_rva=entry_rva,
        import_dir_rva=imp.import_dir_rva,
        import_dir_size=imp.import_dir_size,
        iat_rva=imp.iat_rva,
        iat_size=imp.iat_size,
        symbols=symbols_report,
        code_size=code_size,
    )
