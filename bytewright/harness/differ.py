"""diff_behavior: compare a candidate .exe against a reference/oracle across cases (Plan §6)."""
from __future__ import annotations

from .runner import run


def _expected_for(reference: dict, case: dict, index: int) -> str:
    if "path" in reference:
        return run(reference["path"], stdin=case.get("stdin", ""),
                   args=case.get("args"))["stdout"]
    if "expected" in reference:           # inline expected outputs, aligned to cases
        return reference["expected"][index]
    if "oracle" in reference:             # python oracle: stdin -> expected stdout
        from ..eval import oracles
        fn = oracles.ORACLES[reference["oracle"]]
        return fn(case.get("stdin", ""))
    raise ValueError("reference must have one of: path, expected, oracle")


def _first_divergence(a: str, b: str) -> int | None:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return None if a == b else min(len(a), len(b))


def diff_behavior(path: str, reference: dict, cases: list[dict]) -> dict:
    per_case = []
    passed = 0
    for i, case in enumerate(cases):
        got = run(path, stdin=case.get("stdin", ""), args=case.get("args"))["stdout"]
        expected = _expected_for(reference, case, i)
        match = got == expected
        passed += match
        entry = {"input": case.get("stdin", ""), "got": got, "expected": expected, "match": match}
        if not match:
            entry["first_divergence_output_byte"] = _first_divergence(got, expected)
        per_case.append(entry)
    return {"per_case": per_case, "pass_count": passed, "total": len(cases)}
