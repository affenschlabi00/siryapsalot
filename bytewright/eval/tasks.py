"""The Phase 3 task suite: natural-language intents + test cases + oracles (Plan §7).

Each task is a piece of intent the system must turn into a correct .exe. `solution` points
at a known-good IR used by the LibraryGenerator and as a regression fixture; the agent's job
(with a model generator) is to produce equivalent IR from `intent` alone.
"""
from __future__ import annotations

import os

EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "..", "examples")


def _ex(name: str) -> str:
    return os.path.normpath(os.path.join(EXAMPLES, name))


TASKS = [
    {
        "name": "hello",
        "intent": 'Print "Hello, world!" followed by a newline, then exit with code 0.',
        "cases": [{"stdin": ""}],
        "oracle": "hello",
        "solution": _ex("hello.ir.json"),
    },
    {
        "name": "count",
        "intent": "Print the numbers 1 through 5, each on its own line.",
        "cases": [{"stdin": ""}],
        "oracle": "count",
        "solution": _ex("count.ir.json"),
    },
    {
        "name": "echo",
        "intent": "Read text from stdin and write it back to stdout unchanged.",
        "cases": [{"stdin": "hello"}, {"stdin": "abc 123 xyz"}, {"stdin": "a"}],
        "oracle": "echo",
        "solution": _ex("echo.ir.json"),
    },
    {
        "name": "factorial",
        "intent": "Read a non-negative integer n from stdin and print n! followed by a newline.",
        "cases": [{"stdin": "0\n"}, {"stdin": "1\n"}, {"stdin": "5\n"},
                  {"stdin": "7\n"}, {"stdin": "10\n"}],
        "oracle": "factorial",
        "solution": _ex("factorial.ir.json"),
    },
    {
        "name": "fizzbuzz",
        "intent": ("Print FizzBuzz for 1..15: 'Fizz' for multiples of 3, 'Buzz' for "
                   "multiples of 5, 'FizzBuzz' for multiples of 15, otherwise the number; "
                   "each on its own line."),
        "cases": [{"stdin": ""}],
        "oracle": "fizzbuzz",
        "solution": _ex("fizzbuzz.ir.json"),
    },
    {
        "name": "sum1to100",
        "intent": "Sum the integers from 1 to 100 and print the total.",
        "cases": [{"stdin": ""}],
        "oracle": "sum1to100",
        "solution": _ex("sum1to100.ir.json"),
    },
    {
        "name": "fibonacci",
        "intent": "Print the Fibonacci numbers below 100, one per line.",
        "cases": [{"stdin": ""}],
        "oracle": "fibonacci",
        "solution": _ex("fibonacci.ir.json"),
    },
    {
        "name": "strlen",
        "intent": "Read a line from stdin and print how many characters it has.",
        "cases": [{"stdin": "hello world"}, {"stdin": "a"}, {"stdin": "hi\n"}],
        "oracle": "strlen",
        "solution": _ex("strlen.ir.json"),
    },
    {
        "name": "guess",
        "intent": ("A number-guessing game (target 42): read guesses from stdin line by line "
                   "and reply 'too low', 'too high', or 'correct!' (then stop)."),
        "cases": [{"stdin": "50\n40\n42\n99\n"}, {"stdin": "42\n"}, {"stdin": "10\n20\n30\n"}],
        "oracle": "guess",
        "solution": _ex("guess.ir.json"),
    },
]

TASKS_BY_NAME = {t["name"]: t for t in TASKS}
