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


def test_regalloc_excludes_model_used_registers():
    from bytewright.backend.regalloc import allocate, model_used_callee_saved
    proc = {"label": "m", "instructions": [
        {"op": "xor", "args": ["ebx", "ebx"]},   # model uses rbx (via ebx) directly
        {"op": "mov", "args": ["%v0", "1"]}]}
    assert "rbx" in model_used_callee_saved(proc)
    assert allocate(proc).mapping["%v0"] != "rbx"   # %v0 must avoid the collision


def test_vreg_does_not_collide_with_model_register(build_dir):
    """End-to-end: a %vN survives even when the model clobbers rbx via ebx."""
    ir = {
        "metadata": {"name": "noclash", "entry": "main"},
        "imports": [{"dll": "kernel32.dll", "function": "GetStdHandle"},
                    {"dll": "kernel32.dll", "function": "WriteFile"},
                    {"dll": "kernel32.dll", "function": "ExitProcess"}],
        "data": [{"label": "hStdout", "type": "u64", "value": 0},
                 {"label": "ch", "type": "zeros", "size": 1},
                 {"label": "written", "type": "u32", "value": 0}],
        "code": [{"label": "main", "instructions": [
            {"op": "mov", "args": ["ecx", "-11"]},
            {"op": "call", "args": ["import:kernel32.dll!GetStdHandle"]},
            {"op": "mov", "args": ["qword ptr [data:hStdout]", "rax"]},
            {"op": "mov", "args": ["%v0", "65"]},          # 'A'
            {"op": "xor", "args": ["ebx", "ebx"]},          # would zero %v0 if it were rbx
            {"op": "lea", "args": ["r10", "data:ch"]},
            {"op": "mov", "args": ["rax", "%v0"]},
            {"op": "mov", "args": ["byte ptr [r10]", "al"]},
            {"op": "mov", "args": ["rcx", "qword ptr [data:hStdout]"]},
            {"op": "lea", "args": ["rdx", "data:ch"]},
            {"op": "mov", "args": ["r8d", "1"]},
            {"op": "lea", "args": ["r9", "data:written"]},
            {"op": "mov", "args": ["qword ptr [rsp+32]", "0"]},
            {"op": "call", "args": ["import:kernel32.dll!WriteFile"]},
            {"op": "mov", "args": ["ecx", "0"]},
            {"op": "call", "args": ["import:kernel32.dll!ExitProcess"]}]}],
    }
    from bytewright import harness
    out = os.path.join(build_dir, "noclash.exe")
    assert harness.build_binary(ir, out)["ok"]
    assert harness.run(out)["stdout"] == "A"


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
