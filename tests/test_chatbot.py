"""The chatbot: bare message in, a working .exe out — with self-testing and self-repair."""
import json
import os

import pytest

from bytewright.chatbot import Chatbot, ChatbotGenerator
from conftest import load_example


def _spec(example, tests, name=None, explanation="a program"):
    ir = load_example(example)
    return {"program_name": name or example.replace(".ir.json", ""),
            "explanation": explanation, "ir": ir, "self_tests": tests}


def test_chatbot_builds_from_bare_message(build_dir):
    gen = lambda msg, fb, it, hist: _spec("christmas_tree.ir.json",
                                          [{"stdin": "", "expect_contains": "***********"}])
    bot = Chatbot(gen, out_dir=build_dir)
    res = bot.send("make me a christmas tree")
    assert res["success"]
    assert os.path.exists(res["path"])
    assert "*" in res["outputs"][0]
    assert "christmas_tree.exe" in res["reply"]


def test_chatbot_self_test_gate_rejects_wrong_output(build_dir):
    """If the produced output doesn't match the model's own self-test, it's not accepted."""
    gen = lambda msg, fb, it, hist: _spec("prime.ir.json",
                                          [{"stdin": "7", "expect_equals": "PRIME\n"}])  # wrong case
    bot = Chatbot(gen, out_dir=build_dir, max_iters=2)
    res = bot.send("prime checker")
    assert not res["success"]   # builds & runs, but fails its own (mis-stated) self-test


def test_chatbot_repairs_after_crash(build_dir):
    """iter 0 crashes (null deref); harness diagnoses; iter 1 is correct -> success."""
    good = load_example("christmas_tree.ir.json")
    bad = json.loads(json.dumps(good))
    bad["code"][0]["instructions"].insert(0, {"op": "xor", "args": ["rbx", "rbx"]})
    bad["code"][0]["instructions"].insert(1, {"op": "mov", "args": ["r9", "qword ptr [rbx]"]})
    specs = [
        {"program_name": "tree", "explanation": "x", "ir": bad,
         "self_tests": [{"stdin": "", "expect_contains": "*"}]},
        {"program_name": "tree", "explanation": "x", "ir": good,
         "self_tests": [{"stdin": "", "expect_contains": "*"}]},
    ]
    seen = {}

    def gen(msg, fb, it, hist):
        seen["fb"] = fb
        return specs[min(it, 1)]

    bot = Chatbot(gen, out_dir=build_dir, max_iters=3)
    res = bot.send("draw a tree")
    assert res["success"] and res["iterations"] == 2
    assert "CRASHED" in seen["fb"]      # the repair was driven by a crash diagnosis


@pytest.mark.parametrize("example,stdin,must_contain", [
    ("christmas_tree.ir.json", "", "***********"),
    ("prime.ir.json", "13", "prime"),
    ("tetris_board.ir.json", "", "+----------+"),
])
def test_new_examples_run(build_dir, example, stdin, must_contain):
    from bytewright import harness
    out = os.path.join(build_dir, example.replace(".ir.json", ".exe"))
    rep = harness.build_binary(load_example(example), out)
    assert rep["ok"], rep["errors"]
    r = harness.run(out, stdin=stdin)
    assert not r["crashed"] and must_contain in r["stdout"]


def test_interactive_guessing_game(build_dir):
    """A turn-based game: multiple line-buffered reads in one run, stops at the win."""
    from bytewright import harness
    out = os.path.join(build_dir, "guess.exe")
    harness.build_binary(load_example("guess.ir.json"), out)
    r = harness.run(out, stdin="50\n40\n42\n99\n")
    assert r["stdout"] == "too high\ntoo low\ncorrect!\n"   # 99 never processed -> it stopped
    assert not r["crashed"]


def test_prime_says_not_prime(build_dir):
    from bytewright import harness
    out = os.path.join(build_dir, "prime.exe")
    harness.build_binary(load_example("prime.ir.json"), out)
    assert harness.run(out, stdin="12")["stdout"] == "not prime\n"
    assert harness.run(out, stdin="2")["stdout"] == "prime\n"


def test_chatbot_generator_requires_setup(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY|anthropic SDK"):
        ChatbotGenerator()
