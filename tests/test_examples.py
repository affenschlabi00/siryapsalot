"""Every worked example builds to a valid PE and runs with the expected behavior."""
import math
import os

import pytest

from siryapsalot import harness
from conftest import load_example


@pytest.mark.parametrize("name,stdin,expected", [
    ("hello.ir.json", "", "Hello, world!\n"),
    ("count.ir.json", "", "1\n2\n3\n4\n5\n"),
    ("echo.ir.json", "round trip", "round trip"),
])
def test_example_stdout(build_dir, name, stdin, expected):
    out = os.path.join(build_dir, name.replace(".ir.json", ".exe"))
    rep = harness.build_binary(load_example(name), out)
    assert rep["ok"], rep["errors"]
    assert harness.validate_pe(out)["ok"]
    r = harness.run(out, stdin=stdin)
    assert not r["crashed"]
    assert r["exit_code"] == 0
    assert r["stdout"] == expected


@pytest.mark.parametrize("n", [0, 1, 2, 5, 7, 10, 12])
def test_factorial(build_dir, n):
    out = os.path.join(build_dir, "factorial.exe")
    harness.build_binary(load_example("factorial.ir.json"), out)
    r = harness.run(out, stdin=f"{n}\n")
    assert r["stdout"] == f"{math.factorial(n)}\n"
    assert r["exit_code"] == 0


def test_fizzbuzz_multiprocedure(build_dir):
    """FizzBuzz also validates inter-procedure call/ret (the `print` helper)."""
    out = os.path.join(build_dir, "fizzbuzz.exe")
    rep = harness.build_binary(load_example("fizzbuzz.ir.json"), out)
    assert rep["ok"], rep["errors"]
    r = harness.run(out)
    assert not r["crashed"] and r["exit_code"] == 0
    from siryapsalot.eval.oracles import fizzbuzz
    assert r["stdout"] == fizzbuzz("")


def test_filewrite_creates_file(build_dir):
    out = os.path.join(build_dir, "filewrite.exe")
    harness.build_binary(load_example("filewrite.ir.json"), out)
    r = harness.run(out)
    assert not r["crashed"]
    assert r["files"].get("out.txt") == "Hello, file!\n"


def test_trace_records_api_calls(build_dir):
    out = os.path.join(build_dir, "hello_trace.exe")
    harness.build_binary(load_example("hello.ir.json"), out)
    t = harness.trace(out)
    assert t["summary"]["ended"] == "ExitProcess(0)"
    api_names = [s["api_call"]["name"] for s in t["steps"] if s["api_call"]]
    assert api_names == ["GetStdHandle", "WriteFile", "ExitProcess"]
