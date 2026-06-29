"""Verified recipes: common requests → known-good IR that is guaranteed to build and pass.

The bespoke machine-level IR is genuinely hard for an LLM to emit correctly, so for the most
common asks we don't gamble on the model — we ship a verified solution (one of the worked
`examples/*.ir.json`, each already exercised by the test suite). The chatbot tries a recipe first;
anything that doesn't match falls through to the model. This is what makes the product feel like it
"just works": "make me a calculator / fizzbuzz / tic-tac-toe / a beeping button" are instant and
correct every time, model or no model.
"""
from __future__ import annotations

import json
import os
import re

_EX = os.path.join(os.path.dirname(__file__), "..", "examples")
_cache: dict[str, dict] = {}


def _ir(name: str) -> dict:
    if name not in _cache:
        with open(os.path.join(_EX, name)) as fh:
            _cache[name] = json.load(fh)
    return _cache[name]


def _r(pattern, name, ex, explanation, tests):
    return {"re": re.compile(pattern, re.I), "name": name, "ex": ex,
            "explanation": explanation, "tests": tests}


# Order matters: specific named programs first, then the generic ones (so "factorial calculator"
# is a factorial, not the calculator; button before window; christmas before a bare "tree").
RECIPES = [
    _r(r"\bfizz\s*buzz\b", "fizzbuzz", "fizzbuzz.ir.json",
       "FizzBuzz from 1 to 15", [{"stdin": "", "expect_contains": "FizzBuzz"}]),
    _r(r"\bfib(onacci)?\b", "fibonacci", "fibonacci.ir.json",
       "the Fibonacci numbers below 100", [{"stdin": "", "expect_contains": "89"}]),
    _r(r"\bfactorial\b", "factorial", "factorial.ir.json",
       "a factorial calculator — type a number n and it prints n!",
       [{"stdin": "5\n", "expect_equals": "120\n"}, {"stdin": "0\n", "expect_equals": "1\n"}]),
    _r(r"\b(calculator|calc|arithmetic|add (two|2) numbers|sum of two|a\s*\+\s*b)\b",
       "calculator", "calculator.ir.json",
       "a calculator — type `a + b` (also - * /) and it prints the result",
       [{"stdin": "7 + 8", "expect_equals": "15\n"}, {"stdin": "9 - 4", "expect_equals": "5\n"},
        {"stdin": "6 * 7", "expect_equals": "42\n"}]),
    _r(r"\bprime\b", "prime", "prime.ir.json",
       "a prime checker — type a number and it says whether it's prime",
       [{"stdin": "7", "expect_equals": "prime\n"}, {"stdin": "8", "expect_equals": "not prime\n"}]),
    _r(r"\b(tic.?tac.?toe|noughts and crosses)\b", "tictactoe", "tictactoe.ir.json",
       "a 2-player Tic-Tac-Toe game — type cell numbers 1-9",
       [{"stdin": "1\n4\n2\n5\n3\n", "expect_contains": "X wins!"}]),
    _r(r"\bguess(ing)?\b", "guess", "guess.ir.json",
       "a number-guessing game (target 42) — type guesses and get hints",
       [{"stdin": "50\n40\n42\n", "expect_contains": "correct!"}]),
    _r(r"\b(christmas|xmas)\b", "christmas_tree", "christmas_tree.ir.json",
       "a centered ASCII Christmas tree", [{"stdin": "", "expect_contains": "*********"}]),
    _r(r"\b(echo|repeat (my|what))\b", "echo", "echo.ir.json",
       "an echo program — it prints back whatever you type",
       [{"stdin": "round trip", "expect_contains": "round trip"}]),
    _r(r"\b(string length|length of|how many characters|number of characters|strlen)\b",
       "strlen", "strlen.ir.json",
       "counts the characters in a line you type", [{"stdin": "hello", "expect_contains": "5"}]),
    _r(r"\bsum\b.*(1.*100|hundred)|1 to 100", "sum1to100", "sum1to100.ir.json",
       "sums the integers from 1 to 100", [{"stdin": "", "expect_contains": "5050"}]),
    _r(r"\bcount(ing)?\b", "count", "count.ir.json",
       "counts from 1 to 5", [{"stdin": "", "expect_equals": "1\n2\n3\n4\n5\n"}]),
    _r(r"\b(button|beep|clickable|click)\b", "click_beeps", "click_beeps.ir.json",
       "a window with a button that beeps when clicked",
       [{"stdin": "", "expect_control_contains": "Beep", "expect_sound": True,
         "expect_event": "WM_COMMAND"}]),
    _r(r"\b(message ?box|popup|pop ?up|dialog|alert)\b", "hello_gui", "hello_gui.ir.json",
       "a Windows message box", [{"stdin": "", "expect_dialog_contains": "GUI"}]),
    _r(r"\b(draw|drawing)\b.*\bbox\b|\bbox\b|\bsquare\b|\bframe\b", "draw_box", "draw_box.ir.json",
       "a drawn box with a label", [{"stdin": "", "expect_screen_contains": "HELLO"}]),
    _r(r"\bwindow\b", "hello_window", "hello_window.ir.json",
       "a real Win32 window", [{"stdin": "", "expect_window_contains": "Sir Yaps-a-Lot"}]),
    _r(r"\bhello,?\s*world\b", "hello", "hello.ir.json",
       "the classic “Hello, world!”", [{"stdin": "", "expect_contains": "Hello, world!"}]),
]


def find(message: str):
    """Return a ready-to-build recipe dict for a recognized request, else None."""
    msg = str(message or "")
    for r in RECIPES:
        if r["re"].search(msg):
            return {"name": r["name"], "explanation": r["explanation"],
                    "ir": _ir(r["ex"]), "self_tests": r["tests"]}
    return None


_GUI_WORDS = re.compile(
    r"\b(gui|graphical|window|button|click|dialog|pop ?up|popup|menu|check ?box|text ?box|"
    r"message ?box|form|interface|paint|canvas|sketch|desktop app|widget|app window)\b", re.I)


def gui_fallback(message: str):
    """A working GUI to fall back to when a GUI request can't be generated. The model is bad at
    GUI IR, so rather than dead-end on failure we always ship a real window the user can build on."""
    m = str(message or "")
    if not _GUI_WORDS.search(m):
        return None
    if re.search(r"\b(message ?box|alert|popup|pop ?up|dialog)\b", m, re.I):
        return {"name": "hello_gui", "ir": _ir("hello_gui.ir.json"),
                "explanation": "a Windows message box",
                "self_tests": [{"stdin": "", "expect_dialog_contains": "GUI"}]}
    return {"name": "click_beeps", "ir": _ir("click_beeps.ir.json"),
            "explanation": "a window with a clickable button that beeps when clicked",
            "self_tests": [{"stdin": "", "expect_control_contains": "Beep", "expect_sound": True,
                            "expect_event": "WM_COMMAND"}]}


def catalog() -> list[str]:
    """Human-readable list of what the recipes can build (for a 'what can you do' answer)."""
    seen, out = set(), []
    for r in RECIPES:
        if r["name"] not in seen:
            seen.add(r["name"])
            out.append(r["explanation"])
    return out
