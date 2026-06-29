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


def fizzbuzz(stdin) -> str:
    out = []
    for i in range(1, 16):
        if i % 15 == 0:
            out.append("FizzBuzz")
        elif i % 3 == 0:
            out.append("Fizz")
        elif i % 5 == 0:
            out.append("Buzz")
        else:
            out.append(str(i))
    return "".join(s + "\n" for s in out)


def sum1to100(stdin) -> str:
    return f"{sum(range(1, 101))}\n"


def fibonacci(stdin) -> str:
    out, a, b = [], 0, 1
    while a < 100:
        out.append(f"{a}\n")
        a, b = b, a + b
    return "".join(out)


def strlen(stdin) -> str:
    n = 0
    for ch in _as_str(stdin):
        if ch in "\r\n":
            break
        n += 1
    return f"{n}\n"


ORACLES = {
    "hello": hello,
    "count": count,
    "echo": echo,
    "factorial": factorial,
    "fizzbuzz": fizzbuzz,
    "sum1to100": sum1to100,
    "fibonacci": fibonacci,
    "strlen": strlen,
}
