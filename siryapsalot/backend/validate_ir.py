"""IR validation: JSON-schema structure plus semantic checks.

Errors are structured ({stage, message, instruction_ref}) and point at the offending
instruction, so the agent/model gets actionable feedback (Plan §4, §5 step 1).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from .isa import FORBIDDEN_OPS, BRANCH_OPS, is_register

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "schema", "ir.schema.json")

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DATA_REF = re.compile(r"data:([A-Za-z_]\w*)")
_CODE_REF = re.compile(r"code:([A-Za-z_]\w*)")
_IMPORT_REF = re.compile(r"^import:([\w.\-]+\.dll)!([A-Za-z_]\w*)$", re.IGNORECASE)


def _load_schema() -> dict:
    with open(os.path.normpath(_SCHEMA_PATH)) as fh:
        return json.load(fh)


def err(stage: str, message: str, ref: str | None = None) -> dict:
    e = {"stage": stage, "message": message}
    if ref:
        e["instruction_ref"] = ref
    return e


def _iter_instructions(ir: dict):
    """Yield (proc_label, index, instruction_dict) for real instructions (skip pure labels)."""
    for proc in ir.get("code", []):
        for i, ins in enumerate(proc.get("instructions", [])):
            if "op" in ins:
                yield proc.get("label", "?"), i, ins


def validate_ir(ir: Any) -> list[dict]:
    """Return a list of structured errors. Empty list == valid."""
    errors: list[dict] = []

    # 1) Structural validation against the frozen JSON schema.
    try:
        import jsonschema  # type: ignore

        schema = _load_schema()
        validator = jsonschema.Draft202012Validator(schema)
        for e in sorted(validator.iter_errors(ir), key=lambda x: list(x.path)):
            loc = "/".join(str(p) for p in e.path) or "<root>"
            errors.append(err("schema", f"{e.message}", loc))
        if errors:
            return errors  # structure is broken; semantic checks would be noise
    except ImportError:
        if not isinstance(ir, dict):
            return [err("schema", "IR must be a JSON object")]

    # 2) Semantic checks.
    code_labels: set[str] = set()
    for proc in ir.get("code", []):
        code_labels.add(proc["label"])
        for ins in proc["instructions"]:
            if "op" not in ins and "label" in ins:
                code_labels.add(ins["label"])

    data_labels = {d["label"] for d in ir.get("data", [])}
    imports = {f"{im['dll'].lower()}!{im['function']}" for im in ir.get("imports", [])}

    entry = ir.get("metadata", {}).get("entry")
    if entry and entry not in {p["label"] for p in ir.get("code", [])}:
        errors.append(err("semantic", f"entry label '{entry}' is not a procedure", "metadata.entry"))

    for proc_label, idx, ins in _iter_instructions(ir):
        op = ins["op"].strip().lower()
        args = [str(a) for a in ins.get("args", [])]
        ref = f"proc '{proc_label}' instr {idx} (op={op})"

        if op in FORBIDDEN_OPS:
            errors.append(err("semantic",
                              f"'{op}' is backend-owned; the model must not manage the stack "
                              f"frame (no push/pop/sub rsp/leave). See decision D3.", ref))
            continue

        for a in args:
            # data: references must point at a declared data label
            for m in _DATA_REF.finditer(a):
                if m.group(1) not in data_labels:
                    errors.append(err("semantic", f"unknown data label '{m.group(1)}'", ref))
            # code: references (function pointers) must point at a known code label
            for m in _CODE_REF.finditer(a):
                if m.group(1) not in code_labels:
                    errors.append(err("semantic", f"unknown code label '{m.group(1)}'", ref))
            # import: references must be declared and only used by call/jmp
            if a.lower().startswith("import:"):
                m = _IMPORT_REF.match(a)
                if not m:
                    errors.append(err("semantic", f"malformed import operand '{a}' "
                                                  f"(expected import:dll.dll!Func)", ref))
                elif f"{m.group(1).lower()}!{m.group(2)}" not in imports:
                    errors.append(err("semantic",
                                      f"import '{m.group(1)}!{m.group(2)}' not declared in imports[]", ref))
                elif op not in ("call", "jmp"):
                    errors.append(err("semantic", f"import operand only valid for call/jmp, not '{op}'", ref))

        # branch target (bare identifier) must resolve to a code label
        if op in BRANCH_OPS and args:
            tgt = args[0]
            if (not tgt.lower().startswith("import:") and not is_register(tgt)
                    and "[" not in tgt and _IDENT.match(tgt)):
                if tgt not in code_labels:
                    errors.append(err("semantic", f"branch target '{tgt}' is not a known label", ref))

        # storing an immediate into a data: memory operand isn't supported (disp not last bytes)
        if op == "mov" and len(args) == 2 and "data:" in args[0] and "[" in args[0]:
            if not is_register(args[1]) and not args[1].lower().startswith(("rip", "data:")):
                try:
                    int(args[1], 0)
                    errors.append(err("semantic",
                                      "storing an immediate to a data label is unsupported; "
                                      "load its address with `lea` first.", ref))
                except ValueError:
                    pass

    return errors
