"""Deterministic backend: IR -> .exe (Plan §5). The trusted floor — never learned.

Public entry point ``build_binary`` matches the MCP tool contract in Plan §6.
"""
from __future__ import annotations

import os

from . import encode, layout as _layout, regalloc, validate_ir as _validate
from .pe_builder import build_pe

__all__ = ["build_binary", "validate_ir"]

validate_ir = _validate.validate_ir


def build_binary(ir: dict, out_path: str | None = None) -> dict:
    """Compile an IR program to a Windows .exe.

    Returns a structured build report:
        {ok, path, errors[], warnings[], stats{code_size, file_size, num_imports}}
    """
    warnings: list[dict] = []

    errors = validate_ir(ir)
    if errors:
        return {"ok": False, "path": None, "errors": errors, "warnings": warnings, "stats": {}}

    # entry should end by calling ExitProcess (so the process terminates cleanly)
    meta = ir.get("metadata", {})
    entry = meta.get("entry")
    for proc in ir.get("code", []):
        if proc["label"] == entry:
            real = [i for i in proc["instructions"] if "op" in i]
            last = real[-1] if real else None
            ends_exit = bool(last and last["op"].lower() == "call"
                             and any("exitprocess" in str(a).lower() for a in last.get("args", [])))
            if not ends_exit:
                warnings.append(_validate.err(
                    "build", "entry procedure does not end by calling ExitProcess; "
                             "returning from the entry point relies on the harness sentinel."))

    try:
        layout = _layout.layout(ir)
        pe = build_pe(layout, subsystem=meta.get("subsystem", "console"))
    except (encode.EncodeError, _layout.LayoutError, NotImplementedError, KeyError) as e:
        stage = type(e).__name__
        return {"ok": False, "path": None,
                "errors": [_validate.err("backend", f"{stage}: {e}")],
                "warnings": warnings, "stats": {}}

    if out_path is None:
        os.makedirs("build", exist_ok=True)
        out_path = os.path.join("build", f"{meta.get('name', 'program')}.exe")
    else:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as fh:
        fh.write(pe)

    return {
        "ok": True,
        "path": out_path,
        "errors": [],
        "warnings": warnings,
        "stats": {
            "code_size": layout.code_size,
            "file_size": len(pe),
            "num_imports": len(ir.get("imports", [])),
        },
    }
