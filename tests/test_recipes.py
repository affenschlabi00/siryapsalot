"""Verified recipes: common requests build correctly every time — even with no model at all."""
import os

from siryapsalot import harness, recipes
from siryapsalot.chatbot import Chatbot
from conftest import load_example


def test_find_matches_common_requests():
    cases = {
        "make me a calculator": "calculator",
        "fizzbuzz please": "fizzbuzz",
        "is 13 a prime number": "prime",
        "tic-tac-toe game": "tictactoe",
        "a window with a button that beeps": "click_beeps",
        "draw a box": "draw_box",
        "christmas tree": "christmas_tree",
        "factorial of a number": "factorial",
        "factorial calculator": "factorial",          # named algorithm wins over generic calc
        "fibonacci sequence": "fibonacci",
        "a guessing game": "guess",
        "hello world": "hello",
        "just a window": "hello_window",
        "pop up a message box": "hello_gui",
        "count to five": "count",
        "sum 1 to 100": "sum1to100",
    }
    for msg, name in cases.items():
        r = recipes.find(msg)
        assert r and r["name"] == name, (msg, r and r["name"])


def test_find_returns_none_for_unknown():
    assert recipes.find("make me a snake game with graphics") is None
    assert recipes.find("") is None


def test_calculator_example_computes(build_dir):
    out = os.path.join(build_dir, "calculator.exe")
    rep = harness.build_binary(load_example("calculator.ir.json"), out)
    assert rep["ok"], rep["errors"]
    for stdin, expect in [("3 + 4\n", "7\n"), ("10 - 3\n", "7\n"), ("6 * 7\n", "42\n"),
                          ("20 / 4\n", "5\n"), ("3 - 10\n", "-7\n"), ("8*9\n", "72\n")]:
        assert harness.run(out, stdin=stdin)["stdout"] == expect


def test_chatbot_recipe_first_with_no_model(build_dir):
    bot = Chatbot(None, out_dir=build_dir)                 # no generator at all
    res = bot.send("make me a calculator")
    assert res["success"] and res.get("recipe")
    assert res["path"].endswith("calculator.exe")


def test_chatbot_no_model_non_recipe_gives_help(build_dir):
    bot = Chatbot(None, out_dir=build_dir)
    res = bot.send("make me a snake game with graphics")
    assert not res["success"] and "connect an AI model" in res["reply"]


def test_recipe_beats_a_failing_model(build_dir):
    """For a recognized request the verified recipe is used; a broken model is never consulted."""
    def bad_model(*a, **k):
        return {"kind": "build", "program_name": "x",
                "ir": {"metadata": {"name": "x", "entry": "main"}, "imports": [], "data": [],
                       "code": [{"label": "main", "instructions": [{"op": "ret", "args": []}]}]},
                "self_tests": [{"stdin": "", "expect_contains": "NOPE"}]}

    calls = {"n": 0}

    def counting(*a, **k):
        calls["n"] += 1
        return bad_model()

    bot = Chatbot(counting, out_dir=build_dir)
    res = bot.send("make me a calculator")
    assert res["success"] and res.get("recipe") and calls["n"] == 0


def test_catalog_lists_programs():
    cat = recipes.catalog()
    assert any("calculator" in c for c in cat) and len(cat) >= 10


def test_gui_fallback_matches_gui_words():
    assert recipes.gui_fallback("make me a graphical app")["name"] == "click_beeps"
    assert recipes.gui_fallback("an app with a menu and a form")["name"] == "click_beeps"
    assert recipes.gui_fallback("a message box that says hi")["name"] == "hello_gui"
    assert recipes.gui_fallback("primes under 50") is None        # not a GUI request


def test_no_model_gui_request_builds_a_window(build_dir):
    bot = Chatbot(None, out_dir=build_dir)
    res = bot.send("make me a graphical app")                     # GUI words, no specific recipe
    assert res["success"] and res.get("recipe")
    assert "No AI model is connected" in res["reply"]


def test_failing_model_gui_request_falls_back_to_a_window(build_dir):
    """The reported bug: a GUI request the model can't build must NOT dead-end on 'couldn't get it
    working' — it ships a real, working window instead."""
    def failing(m, fb, it, h):
        return {"kind": "build", "program_name": "clockapp", "explanation": "a clock window",
                "ir": {"metadata": {"name": "x", "entry": "main", "subsystem": "gui"},
                       "imports": [], "data": [],
                       "code": [{"label": "main", "instructions": [
                           {"op": "xor", "args": ["eax", "eax"]},
                           {"op": "mov", "args": ["rax", "qword ptr [rax]"]}]}]},
                "self_tests": [{"stdin": "", "expect_window_contains": "Clock"}]}

    bot = Chatbot(failing, out_dir=build_dir, max_iters=2)
    res = bot.send("make me a graphical app with a menu")         # GUI words, no recipe match
    assert res["success"] and res.get("recipe")                   # didn't dead-end
    assert "couldn't generate that exact GUI" in res["reply"]
