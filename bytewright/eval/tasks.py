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
]

TASKS_BY_NAME = {t["name"]: t for t in TASKS}
