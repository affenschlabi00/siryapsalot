"""The raw-bytes path (Plan §6): a model emits literal machine code -> a working binary."""
import json
import os

import pytest

from bytewright import harness
from bytewright.chatbot import Chatbot
from bytewright.raw import build_from_obj, build_raw_pe, validate_obj
from conftest import load_example


def _raw_hi():
    return load_example("raw_hi.obj.json")


def test_build_from_obj_runs(build_dir):
    out = os.path.join(build_dir, "raw_hi.exe")
    rep = build_from_obj(_raw_hi(), out)
    assert rep["ok"], rep["errors"]
    assert rep["stats"]["num_relocs"] == 5
    r = harness.run(out)
    assert r["stdout"] == "Hi\n" and not r["crashed"]


def test_raw_bytes_disassemble_as_intended(build_dir):
    out = os.path.join(build_dir, "raw_hi2.exe")
    build_from_obj(_raw_hi(), out)
    d = harness.disassemble(out, {"count": 2})["instructions"]
    assert d[0]["mnemonic"] == "sub" and d[0]["operands"] == "rsp, 0x28"


def test_full_raw_pe_roundtrip(build_dir):
    src = os.path.join(build_dir, "rawhi_src.exe")
    build_from_obj(_raw_hi(), src)
    pe_hex = open(src, "rb").read().hex()
    out = os.path.join(build_dir, "from_hex.exe")
    rep = build_raw_pe(pe_hex, out)
    assert rep["ok"] and rep["validation"]["ok"]
    assert harness.run(out)["stdout"] == "Hi\n"


def test_build_raw_pe_rejects_garbage(build_dir):
    rep = build_raw_pe("00010203deadbeef", os.path.join(build_dir, "junk.exe"))
    assert not rep["ok"] and rep["errors"]


def test_validate_obj_catches_bad_offset():
    obj = _raw_hi()
    obj["relocs"][0]["offset"] = 999
    assert any("offset" in e["message"] for e in validate_obj(obj))


def test_validate_obj_catches_undeclared_import():
    obj = _raw_hi()
    obj["relocs"][0]["target"] = "kernel32.dll!Nonexistent"
    assert any("undeclared import" in e["message"] for e in validate_obj(obj))


def test_validate_obj_catches_bad_hex():
    assert any("hex" in e["message"] for e in validate_obj({"code": "zzz", "relocs": []}))


def test_crash_analysis_on_raw_binary(build_dir):
    """A hand-emitted null deref is diagnosed — the repair signal works on raw bytes."""
    obj = {"metadata": {"name": "rawcrash", "entry_offset": 0},
           "code": "488b00", "imports": [], "data": [], "relocs": []}   # mov rax,[rax], rax=0
    out = os.path.join(build_dir, "rawcrash.exe")
    assert build_from_obj(obj, out)["ok"]
    ca = harness.crash_analysis(out)
    assert ca["crashed"] and "null pointer" in ca["likely_cause"]


def test_raw_chatbot_repairs(build_dir):
    """The chatbot, in raw mode, emits bytes, self-tests, and repairs on a wrong output."""
    bad = _raw_hi()
    for d in bad["data"]:
        if d["label"] == "msg":
            d["value"] = "No\n"                      # builds & runs, but prints the wrong thing
    good = _raw_hi()
    attempts = [
        {"program_name": "raw_hi", "explanation": "x", "ir": bad,
         "self_tests": [{"stdin": "", "expect_contains": "Hi"}]},
        {"program_name": "raw_hi", "explanation": "x", "ir": good,
         "self_tests": [{"stdin": "", "expect_contains": "Hi"}]},
    ]
    bot = Chatbot(lambda m, fb, it, h: attempts[min(it, 1)],
                  out_dir=build_dir, builder=build_from_obj)
    res = bot.send("emit raw bytes that print Hi")
    assert res["success"] and res["iterations"] == 2
