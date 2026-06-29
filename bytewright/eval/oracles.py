"""Reference implementations (oracles) — known-correct expected outputs (Plan §1, §6).

Each oracle maps stdin -> expected stdout. `diff_behavior` compares a candidate .exe
against these to decide correctness.
"""
from __future__ import annotations

import math


def _as_str(stdin) -> str:
    return stdin if isinstance(stdin, str) else bytes(stdin).decode("utf-8", "replace")


def hello(stdin) -> str:
    return "Hello, world!\n"


def count(stdin) -> str:
    return "".join(f"{i}\n" for i in range(1, 6))


def echo(stdin) -> str:
    return _as_str(stdin)


def factorial(stdin) -> str:
    n = int(_as_str(stdin).strip() or "0")
    return f"{math.factorial(n)}\n"


ORACLES = {
    "hello": hello,
    "count": count,
    "echo": echo,
    "factorial": factorial,
}
