"""The user-facing path: plain-English intent -> working .exe via build_from_intent."""
import json
import os

import pytest

from siryapsalot.agent import (AnthropicGenerator, CallableGenerator, build_from_intent)
from conftest import load_example


def _claude_like(mapping):
    """A generator standing in for the model: returns the right IR for a given intent."""
    def fn(intent, feedback, iteration):
        for key, ex in mapping.items():
            if key in intent.lower():
                return load_example(ex)
        raise AssertionError(f"no IR for {intent!r}")
    return CallableGenerator(fn)


def test_intent_sum(build_dir):
    gen = _claude_like({"sum": "sum1to100.ir.json"})
    res = build_from_intent("sum the integers from 1 to 100", gen,
                            expected=["5050\n"], out_path=os.path.join(build_dir, "s.exe"),
                            verbose=False)
    assert res["success"] and res["outputs"][0] == "5050\n"


def test_intent_fibonacci(build_dir):
    gen = _claude_like({"fib": "fibonacci.ir.json"})
    res = build_from_intent("print fib numbers below 100", gen,
                            out_path=os.path.join(build_dir, "f.exe"), verbose=False)
    assert res["success"]
    assert res["outputs"][0] == "".join(f"{x}\n" for x in [0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89])


def test_intent_strlen_with_cases(build_dir):
    gen = _claude_like({"length": "strlen.ir.json"})
    res = build_from_intent("read a line and print its length", gen,
                            cases=[{"stdin": "hello world"}, {"stdin": "a"}],
                            expected=["11\n", "1\n"],
                            out_path=os.path.join(build_dir, "l.exe"), verbose=False)
    assert res["success"]


def test_repair_loop_via_intent(build_dir):
    """A generator that first emits a crashing program, then a good one, converges."""
    good = load_example("sum1to100.ir.json")
    bad = json.loads(json.dumps(good))
    # break it: dereference null at the top of main
    bad["code"][0]["instructions"].insert(0, {"op": "xor", "args": ["rbx", "rbx"]})
    bad["code"][0]["instructions"].insert(1, {"op": "mov", "args": ["r10", "qword ptr [rbx]"]})
    seq = [bad, good]
    gen = CallableGenerator(lambda intent, fb, it: seq[min(it, 1)])
    res = build_from_intent("sum 1..100", gen, expected=["5050\n"],
                            out_path=os.path.join(build_dir, "r.exe"), verbose=False)
    assert res["success"] and res["iterations"] == 2


def test_anthropic_generator_fails_clearly_without_setup(monkeypatch):
    """Without the SDK or a key, the model generator must fail with actionable guidance."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY|anthropic SDK"):
        AnthropicGenerator()
