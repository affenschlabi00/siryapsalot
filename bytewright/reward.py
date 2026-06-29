"""The dense reward ladder (Plan §5) — the RLVR reward signal, computed by the harness.

The same harness that debugs and grades is the reward function. The ladder lets a model climb
out of zero reward: each rung (IR validates -> builds -> loadable -> runs -> k/n tests -> all
tests -> efficiency bonus) adds credit, and there is partial credit *within* rungs (fraction of
cases that ran, output similarity) so even a near-miss gets a gradient to follow.

This is reusable today as a richer eval metric; it becomes the RL reward in Phase 5.
"""
from __future__ import annotations

import difflib
import os

from . import harness
from .backend import validate_ir

# Rung weights: a fully correct program scores 1.0; the efficiency bonus adds up to +0.10.
W_IR_VALID = 0.10
W_BUILDS = 0.15
W_LOADABLE = 0.10
W_RUNS = 0.15        # proportional to fraction of cases that run cleanly
W_TESTS = 0.40       # proportional to fraction of cases that match the oracle
W_ALL_TESTS = 0.10   # bonus for passing every case
W_EFFICIENCY = 0.10  # bonus for small/lean binaries (only when fully correct)


def reward(ir: dict, task: dict, out_path: str | None = None) -> dict:
    """Score an IR attempt against a task. Returns {score, rungs, signals}."""
    cases = task.get("cases", [{"stdin": ""}])
    oracle = task.get("oracle")
    out = out_path or os.path.join("build", f"_reward_{task.get('name', 'p')}.exe")
    rungs: dict[str, object] = {}
    signals: dict[str, object] = {}
    score = 0.0

    # rung 1 — IR validates
    errs = validate_ir(ir)
    rungs["ir_valid"] = not errs
    if errs:
        signals["first_error"] = errs[0]["message"]
        return _result(score, rungs, signals)
    score += W_IR_VALID

    # rung 2 — builds
    rep = harness.build_binary(ir, out)
    rungs["builds"] = rep["ok"]
    if not rep["ok"]:
        signals["build_error"] = rep["errors"][0]["message"] if rep["errors"] else "?"
        return _result(score, rungs, signals)
    score += W_BUILDS
    signals["code_size"] = rep["stats"]["code_size"]
    signals["num_imports"] = rep["stats"]["num_imports"]

    # rung 3 — the loader would accept it
    vp = harness.validate_pe(out)
    rungs["loadable"] = vp["ok"]
    if not vp["ok"]:
        signals["pe_issues"] = vp["issues"]
        return _result(score, rungs, signals)
    score += W_LOADABLE

    # rung 4 — runs without crashing (partial credit per case)
    runs = [harness.run(out, stdin=c.get("stdin", "")) for c in cases]
    clean = [not (r["crashed"] or r["truncated"]) for r in runs]
    frac_clean = sum(clean) / len(runs)
    rungs["runs"] = frac_clean == 1.0
    score += W_RUNS * frac_clean
    signals["fraction_ran_clean"] = round(frac_clean, 3)
    signals["instructions_executed"] = [r["instructions_executed"] for r in runs]

    # rung 5/6 — correctness against the oracle (only meaningful with one)
    if oracle:
        from .eval import oracles
        fn = oracles.ORACLES[oracle]
        matches, sims = 0, []
        for c, r in zip(cases, runs):
            expected = fn(c.get("stdin", ""))
            got = r["stdout"]
            matches += got == expected
            sims.append(difflib.SequenceMatcher(None, got, expected).ratio())
        frac_pass = matches / len(cases)
        rungs["tests_passed"] = f"{matches}/{len(cases)}"
        score += W_TESTS * frac_pass
        signals["output_similarity"] = round(sum(sims) / len(sims), 3)
        if frac_pass == 1.0:
            score += W_ALL_TESTS
            # rung 7 — efficiency bonus: lean code, few imports
            eff = _efficiency(rep["stats"])
            score += W_EFFICIENCY * eff
            signals["efficiency"] = round(eff, 3)

    return _result(score, rungs, signals)


def _efficiency(stats: dict) -> float:
    """1.0 for tiny/lean, decaying as code and imports grow. Bounded [0,1]."""
    code = stats.get("code_size", 0)
    imports = stats.get("num_imports", 0)
    code_score = max(0.0, 1.0 - code / 2000.0)      # ~0 by 2 KB of code
    import_score = max(0.0, 1.0 - imports / 16.0)
    return 0.5 * code_score + 0.5 * import_score


def _result(score, rungs, signals):
    depth = sum(1 for v in rungs.values() if v is True)
    return {"score": round(score, 4), "rungs": rungs, "depth": depth, "signals": signals}
