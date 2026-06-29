"""The raw-bytes path (Plan §6 stretch goal): a model emits literal machine-code bytes,
the trusted backend only handles the unforgiving PE container.

Two levels of "raw":

  build_from_obj(obj)   — the sweet spot. The model emits the .text bytes itself (it does the
                          instruction encoding — the real machine-level work) plus a relocation
                          list and the data/imports. The backend links + builds the PE. This is
                          an object file: the model writes the bytes, the linker does the
                          clerical layout. The harness repair loop (disassemble/run/crash) then
                          drives byte-level fixes.

  build_raw_pe(hex)     — the purest flex. The model emits the ENTIRE .exe as bytes; we just
                          write and validate/run it. Hardest for the model (one wrong offset and
                          the loader rejects it silently), which is exactly why the harness
                          feedback matters.
"""
from __future__ import annotations

import os

from .backend import encode, layout as _layout, pe_builder
from .backend.validate_ir import err
from .harness.validate_pe import validate_pe

_RELOC_KINDS = {"code", "data", "import"}


def _hexbytes(s) -> bytes:
    if isinstance(s, (bytes, bytearray)):
        return bytes(s)
    if isinstance(s, list):
        return bytes(int(x) & 0xFF for x in s)
    return bytes.fromhex("".join(str(s).split()))   # tolerate spaces/newlines in hex


def validate_obj(obj: dict) -> list[dict]:
    """Structural checks on a raw object before linking; structured errors."""
    errors: list[dict] = []
    if "code" not in obj and "code_hex" not in obj:
        errors.append(err("raw", "object needs a 'code' (or 'code_hex') field of machine-code bytes"))
        return errors
    try:
        code = _hexbytes(obj.get("code", obj.get("code_hex", "")))
    except ValueError as e:
        return [err("raw", f"code is not valid hex: {e}")]
    n = len(code)
    data_labels = {d["label"] for d in obj.get("data", [])}
    imports = {f"{im['dll'].lower()}!{im['function']}" for im in obj.get("imports", [])}
    for i, r in enumerate(obj.get("relocs", [])):
        ref = f"relocs[{i}]"
        if r.get("kind") not in _RELOC_KINDS:
            errors.append(err("raw", f"reloc kind must be one of {sorted(_RELOC_KINDS)}", ref))
        off = r.get("offset")
        if not isinstance(off, int) or not (0 <= off <= n - 4):
            errors.append(err("raw", f"reloc offset {off!r} must be an int in [0, {n - 4}]", ref))
        if r.get("kind") == "data" and str(r.get("target")) not in data_labels:
            errors.append(err("raw", f"reloc targets unknown data label {r.get('target')!r}", ref))
        if r.get("kind") == "import":
            t = str(r.get("target", ""))
            key = f"{t.split('!')[0].lower()}!{t.split('!', 1)[1]}" if "!" in t else t
            if key not in imports:
                errors.append(err("raw", f"reloc targets undeclared import {r.get('target')!r}", ref))
    entry = int(obj.get("metadata", {}).get("entry_offset", 0))
    if not (0 <= entry < max(n, 1)):
        errors.append(err("raw", f"entry_offset {entry} is outside the code (0..{n})", "metadata"))
    return errors


def build_from_obj(obj: dict, out_path: str | None = None) -> dict:
    """Build a PE from model-emitted machine-code bytes + relocations."""
    errors = validate_obj(obj)
    if errors:
        return {"ok": False, "path": None, "errors": errors, "warnings": [], "stats": {}}

    code = _hexbytes(obj.get("code", obj.get("code_hex", "")))
    relocs = [encode.Reloc(int(r["offset"]),
                           "import" if r["kind"] == "import" else r["kind"],
                           f"{r['target'].split('!')[0].lower()}!{r['target'].split('!')[1]}"
                           if r["kind"] == "import" else str(r["target"]))
              for r in obj.get("relocs", [])]
    meta = obj.get("metadata", {})
    try:
        lay = _layout.link(bytearray(code), relocs, obj.get("data", []), obj.get("imports", []),
                           entry_offset=int(meta.get("entry_offset", 0)), code_symbols={})
        pe = pe_builder.build_pe(lay, subsystem=meta.get("subsystem", "console"))
    except (_layout.LayoutError, KeyError) as e:
        return {"ok": False, "path": None,
                "errors": [err("raw", f"{type(e).__name__}: {e}")], "warnings": [], "stats": {}}

    out_path = _write(pe, out_path, meta.get("name", "raw"))
    return {"ok": True, "path": out_path, "errors": [], "warnings": [],
            "stats": {"code_size": len(code), "file_size": len(pe),
                      "num_imports": len(obj.get("imports", [])),
                      "num_relocs": len(relocs)}}


def build_raw_pe(pe_hex, out_path: str | None = None, name: str = "rawpe") -> dict:
    """Accept a complete .exe as bytes; write it and report structural validity."""
    try:
        pe = _hexbytes(pe_hex)
    except ValueError as e:
        return {"ok": False, "path": None, "errors": [err("raw", f"not valid hex: {e}")]}
    out_path = _write(pe, out_path, name)
    vp = validate_pe(out_path)
    return {"ok": vp.get("format_ok", False), "path": out_path, "file_size": len(pe),
            "validation": vp, "errors": [] if vp.get("format_ok") else
            [err("raw", "the loader would reject this: " + "; ".join(vp.get("issues", []) or
                 ["unparseable PE"]))]}


def _write(pe: bytes, out_path: str | None, name: str) -> str:
    if out_path is None:
        os.makedirs("build", exist_ok=True)
        out_path = os.path.join("build", f"{name}.exe")
    else:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as fh:
        fh.write(pe)
    return out_path
