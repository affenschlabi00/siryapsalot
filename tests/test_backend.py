"""Backend: IR validation, build, and the relocation/round-trip correctness story."""
import os

import lief
import pytest
from capstone import CS_ARCH_X86, CS_MODE_64, Cs

from bytewright.backend import build_binary, validate_ir
from conftest import load_example


def test_valid_hello_passes_validation():
    assert validate_ir(load_example("hello.ir.json")) == []


def test_forbidden_stack_op_rejected():
    ir = load_example("hello.ir.json")
    ir["code"][0]["instructions"].insert(0, {"op": "push", "args": ["rbx"]})
    errs = validate_ir(ir)
    assert any("backend-owned" in e["message"] for e in errs)


def test_unknown_data_label_rejected():
    ir = load_example("hello.ir.json")
    ir["code"][0]["instructions"][4]["args"] = ["rdx", "data:does_not_exist"]
    errs = validate_ir(ir)
    assert any("unknown data label" in e["message"] for e in errs)


def test_undeclared_import_rejected():
    ir = load_example("hello.ir.json")
    ir["code"][0]["instructions"][1]["args"] = ["import:kernel32.dll!NotImported"]
    errs = validate_ir(ir)
    assert any("not declared" in e["message"] for e in errs)


def test_unknown_branch_target_rejected():
    ir = load_example("count.ir.json")
    for ins in ir["code"][0]["instructions"]:
        if ins.get("op") == "jle":
            ins["args"] = ["nowhere"]
    errs = validate_ir(ir)
    assert any("not a known label" in e["message"] for e in errs)


def test_build_hello_produces_valid_pe(build_dir):
    out = os.path.join(build_dir, "hello.exe")
    rep = build_binary(load_example("hello.ir.json"), out)
    assert rep["ok"], rep["errors"]
    assert os.path.getsize(out) == rep["stats"]["file_size"]
    b = lief.parse(out)
    assert b.optional_header.magic == lief.PE.PE_TYPE.PE32_PLUS
    assert b.header.machine == lief.PE.Header.MACHINE_TYPES.AMD64
    names = {f"{imp.name}!{e.name}" for imp in b.imports for e in imp.entries}
    assert "kernel32.dll!WriteFile" in names


def test_relocations_resolve_to_real_targets(build_dir):
    """Round-trip: disassemble the built code and confirm symbolic refs point at real RVAs."""
    out = os.path.join(build_dir, "hello_rt.exe")
    build_binary(load_example("hello.ir.json"), out)
    b = lief.parse(out)
    base = b.optional_header.imagebase
    text = b.get_section(".text")
    iat_slots = {base + e.iat_address for imp in b.imports for e in imp.entries}
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True
    call_targets = []
    for ins in md.disasm(bytes(text.content), base + text.virtual_address):
        if ins.mnemonic == "call" and "rip" in ins.op_str:
            # RIP-relative target = next instruction address + disp
            disp = ins.operands[0].mem.disp
            call_targets.append(ins.address + ins.size + disp)
    # every indirect call lands on a real IAT slot
    assert call_targets and all(t in iat_slots for t in call_targets)


def test_too_many_virtual_registers_errors(build_dir):
    ir = {
        "metadata": {"name": "many", "entry": "main"},
        "imports": [{"dll": "kernel32.dll", "function": "ExitProcess"}],
        "code": [{"label": "main", "instructions":
                  [{"op": "mov", "args": [f"%v{i}", "0"]} for i in range(8)] +
                  [{"op": "mov", "args": ["ecx", "0"]},
                   {"op": "call", "args": ["import:kernel32.dll!ExitProcess"]}]}],
    }
    rep = build_binary(ir, os.path.join(build_dir, "many.exe"))
    assert not rep["ok"]
    assert any("virtual register" in e["message"] for e in rep["errors"])
