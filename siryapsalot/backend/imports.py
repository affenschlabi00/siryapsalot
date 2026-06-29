"""Import directory / IAT construction (hand-rolled — decision D2).

Lays the whole import blob inside .rdata:
    [ Import Directory | Import Lookup Tables | Import Address Table | Hint/Name | DLL names ]
and reports the RVA of every function's IAT slot, which the code's `call [rip+disp32]`
instructions relocate against. The loader (real or our emulator) overwrites the IAT with
resolved addresses at load time.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field


@dataclass
class ImportBlob:
    blob: bytes
    import_dir_rva: int
    import_dir_size: int
    iat_rva: int
    iat_size: int
    slot_rva: dict[str, int] = field(default_factory=dict)   # "dll!func" -> IAT slot RVA


def _align2(n: int) -> int:
    return n + (n & 1)


def build_imports(imports: list[dict], rdata_rva: int) -> ImportBlob:
    """imports: [{dll, function}, ...] in declaration order."""
    # group by DLL, preserving first-seen order
    order: list[str] = []
    by_dll: dict[str, list[str]] = {}
    for im in imports:
        dll = im["dll"]
        by_dll.setdefault(dll, [])
        if dll not in order:
            order.append(dll)
        if im["function"] not in by_dll[dll]:
            by_dll[dll].append(im["function"])

    if not order:
        return ImportBlob(b"", 0, 0, 0, 0, {})

    # ---- pass 1: compute offsets within the blob ----
    off = 0
    idt_off = off
    off += (len(order) + 1) * 20            # descriptors + null terminator

    ilt_off: dict[str, int] = {}
    for dll in order:
        ilt_off[dll] = off
        off += (len(by_dll[dll]) + 1) * 8

    iat_start = off
    iat_off: dict[str, int] = {}
    slot_off: dict[str, int] = {}
    for dll in order:
        iat_off[dll] = off
        for i, fn in enumerate(by_dll[dll]):
            slot_off[f"{dll.lower()}!{fn}"] = off + i * 8
        off += (len(by_dll[dll]) + 1) * 8
    iat_size = off - iat_start

    hn_off: dict[str, int] = {}             # keyed by "dll!func"
    for dll in order:
        for fn in by_dll[dll]:
            hn_off[f"{dll}!{fn}"] = off
            off += _align2(2 + len(fn) + 1)

    name_off: dict[str, int] = {}
    for dll in order:
        name_off[dll] = off
        off += len(dll) + 1

    blob = bytearray(off)

    def rva(x: int) -> int:
        return rdata_rva + x

    # ---- pass 2: emit ----
    # Import Directory Table
    p = idt_off
    for dll in order:
        struct.pack_into("<IIIII", blob, p,
                         rva(ilt_off[dll]),     # OriginalFirstThunk (ILT)
                         0, 0,                  # TimeDateStamp, ForwarderChain
                         rva(name_off[dll]),    # Name
                         rva(iat_off[dll]))     # FirstThunk (IAT)
        p += 20
    # (null descriptor already zero)

    # ILTs and IATs (identical at build time: each thunk -> RVA of hint/name)
    for dll in order:
        p_ilt = ilt_off[dll]
        p_iat = iat_off[dll]
        for fn in by_dll[dll]:
            thunk = rva(hn_off[f"{dll}!{fn}"]) & 0x7FFFFFFFFFFFFFFF   # import by name
            struct.pack_into("<Q", blob, p_ilt, thunk)
            struct.pack_into("<Q", blob, p_iat, thunk)
            p_ilt += 8
            p_iat += 8
        # null thunks already zero

    # Hint/Name table
    for dll in order:
        for fn in by_dll[dll]:
            q = hn_off[f"{dll}!{fn}"]
            struct.pack_into("<H", blob, q, 0)            # hint
            blob[q + 2:q + 2 + len(fn)] = fn.encode("ascii")
            blob[q + 2 + len(fn)] = 0

    # DLL name strings
    for dll in order:
        q = name_off[dll]
        blob[q:q + len(dll)] = dll.encode("ascii")
        blob[q + len(dll)] = 0

    return ImportBlob(
        blob=bytes(blob),
        import_dir_rva=rva(idt_off),
        import_dir_size=(len(order) + 1) * 20,
        iat_rva=rva(iat_start),
        iat_size=iat_size,
        slot_rva={k: rva(v) for k, v in slot_off.items()},
    )
