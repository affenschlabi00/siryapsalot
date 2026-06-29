"""Harness tools: validate_pe, disassemble, inspect, crash_analysis, resolve_api, list_imports."""
import os

import pytest

from bytewright import harness
from conftest import load_example


@pytest.fixture(scope="module")
def hello_exe(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("h") / "hello.exe")
    harness.build_binary(load_example("hello.ir.json"), out)
    return out


def test_validate_pe(hello_exe):
    vp = harness.validate_pe(hello_exe)
    assert vp["ok"] and vp["headers"]["magic"] == "PE32+"
    assert vp["headers"]["subsystem"] == "console"
    assert any(s["name"] == ".text" and "X" in s["flags"] for s in vp["sections"])


def test_disassemble_round_trips(hello_exe):
    d = harness.disassemble(hello_exe, {"count": 4})
    assert d["instructions"][0]["mnemonic"] == "push"     # backend prologue


def test_list_imports(hello_exe):
    names = {f"{i['dll']}!{i['function']}" for i in harness.list_imports(hello_exe)["imports"]}
    assert "kernel32.dll!ExitProcess" in names


def test_resolve_api_writefile():
    ra = harness.resolve_api("WriteFile")
    assert ra["known"] and ra["calling_convention"] == "win64"
    assert ra["arg_registers"][:4] == ["rcx", "rdx", "r8", "r9"]


def test_resolve_api_unknown():
    assert harness.resolve_api("TotallyMadeUp")["known"] is False


def test_inspect_at_step(hello_exe):
    ins = harness.inspect(hello_exe, {"step": 6})
    assert ins["reached"]
    assert "rip" in ins["registers"]


def test_crash_analysis_null_deref(tmp_path):
    ir = {
        "metadata": {"name": "crashy", "entry": "main"},
        "imports": [{"dll": "kernel32.dll", "function": "ExitProcess"}],
        "code": [{"label": "main", "instructions": [
            {"op": "xor", "args": ["rax", "rax"]},
            {"op": "mov", "args": ["r10", "qword ptr [rax]"]},
            {"op": "mov", "args": ["ecx", "0"]},
            {"op": "call", "args": ["import:kernel32.dll!ExitProcess"]},
        ]}],
    }
    out = str(tmp_path / "crashy.exe")
    harness.build_binary(ir, out)
    ca = harness.crash_analysis(out)
    assert ca["crashed"]
    assert "null pointer" in ca["likely_cause"]
    assert ca["fault_instruction"]["mnemonic"] == "mov"


def test_clean_program_does_not_crash(hello_exe):
    assert harness.crash_analysis(hello_exe)["crashed"] is False
