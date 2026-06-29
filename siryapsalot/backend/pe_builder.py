"""Hand-rolled PE32+ writer (decision D2).

Takes a laid-out image (sections + entry + import directories) and emits a valid Windows
x86-64 console/GUI executable: DOS header+stub, PE signature, COFF header, Optional Header
(PE32+), section table, and file-aligned section data. No base relocations are emitted
(decision D5 — position-independent via RIP-relative addressing).
"""
from __future__ import annotations

import struct

from .layout import FILE_ALIGN, SECTION_ALIGN, LayoutResult

# Canonical 128-byte MS-DOS header + stub ("This program cannot be run in DOS mode."),
# with e_lfanew (offset 0x3C) = 0x80 pointing at the PE signature.
_DOS = bytes.fromhex(
    "4d5a90000300000004000000ffff0000"
    "b8000000000000004000000000000000"
    "00000000000000000000000000000000"
    "00000000000000000000000080000000"
    "0e1fba0e00b409cd21b8014ccd215468"
    "69732070726f6772616d2063616e6e6f"
    "742062652072756e20696e20444f5320"
    "6d6f64652e0d0d0a2400000000000000"
)

_SUBSYSTEM = {"console": 3, "gui": 2}


def _align(n: int, a: int) -> int:
    return (n + a - 1) & ~(a - 1)


def build_pe(layout: LayoutResult, subsystem: str = "console") -> bytes:
    sections = sorted(layout.sections, key=lambda s: s.rva)
    nsec = len(sections)

    size_of_headers = _align(len(_DOS) + 4 + 20 + 240 + nsec * 40, FILE_ALIGN)

    # assign file offsets and raw sizes
    cursor = size_of_headers
    for s in sections:
        s.file_off = cursor
        cursor += _align(s.vsize, FILE_ALIGN)

    size_of_code = sum(_align(s.vsize, FILE_ALIGN) for s in sections if s.characteristics & 0x20)
    size_of_idata = sum(_align(s.vsize, FILE_ALIGN) for s in sections if s.characteristics & 0x40)
    last = sections[-1]
    size_of_image = _align(last.rva + last.vsize, SECTION_ALIGN)

    # COFF file header
    characteristics = 0x0002 | 0x0020 | 0x0001  # EXECUTABLE_IMAGE | LARGE_ADDRESS_AWARE | RELOCS_STRIPPED
    coff = struct.pack("<HHIIIHH",
                       0x8664,            # Machine = AMD64
                       nsec,
                       0,                 # TimeDateStamp
                       0, 0,              # symbol table (none)
                       240,               # SizeOfOptionalHeader (PE32+)
                       characteristics)

    # Optional header (PE32+)
    opt = struct.pack(
        "<HBBIIIII",
        0x20B,                # Magic = PE32+
        14, 0,                # linker version
        size_of_code,
        size_of_idata,
        0,                    # SizeOfUninitializedData
        layout.entry_rva,     # AddressOfEntryPoint
        SECTION_ALIGN,        # BaseOfCode (== .text rva)
    )
    opt += struct.pack(
        "<QIIHHHHHHIIIIHH",
        layout.image_base,
        SECTION_ALIGN,
        FILE_ALIGN,
        6, 0,                 # OS version
        0, 0,                 # image version
        6, 0,                 # subsystem version
        0,                    # Win32VersionValue
        size_of_image,
        size_of_headers,
        0,                    # CheckSum (0 = unchecked; fine for non-driver)
        _SUBSYSTEM.get(subsystem, 3),
        0x0000,               # DllCharacteristics (no ASLR; relocs stripped)
    )
    opt += struct.pack("<QQQQ", 0x100000, 0x1000, 0x100000, 0x1000)  # stack/heap reserve/commit
    opt += struct.pack("<II", 0, 16)                                  # LoaderFlags, NumberOfRvaAndSizes

    # 16 data directories
    dirs = [(0, 0)] * 16
    dirs[1] = (layout.import_dir_rva, layout.import_dir_size)   # Import
    dirs[12] = (layout.iat_rva, layout.iat_size)               # IAT
    for rva, size in dirs:
        opt += struct.pack("<II", rva, size)
    assert len(opt) == 240, f"optional header is {len(opt)} bytes, expected 240"

    # Section table
    sectab = b""
    for s in sections:
        name = s.name.encode("ascii")[:8].ljust(8, b"\x00")
        sectab += struct.pack("<8sIIIIIIHHI",
                              name,
                              s.vsize,
                              s.rva,
                              _align(s.vsize, FILE_ALIGN),
                              s.file_off,
                              0, 0, 0, 0,
                              s.characteristics)

    out = bytearray()
    out += _DOS
    out += b"PE\x00\x00"
    out += coff
    out += opt
    out += sectab
    out += b"\x00" * (size_of_headers - len(out))

    for s in sections:
        assert len(out) == s.file_off, "section file offset mismatch"
        out += s.data
        out += b"\x00" * (_align(s.vsize, FILE_ALIGN) - s.vsize)

    return bytes(out)
