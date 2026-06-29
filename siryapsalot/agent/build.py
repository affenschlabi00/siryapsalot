"""build_from_intent — plain-English request in, working .exe out (Plan §3).

This is the user-facing loop: a generator (a model) turns intent into IR; the harness builds,
validates, runs, and on failure feeds a diagnosis back for repair. With no oracle there is no
ground truth, so "success" means: the IR validates, the PE is loadable, and every case runs
without crashing or looping forever — and the produced output is returned for the user to see.
If the caller supplies an oracle or expected outputs, correctness is checked too.
"""
from __future__ import annotations

import os
import re

from .. import harness
from . import feedback as fb


def _slug(intent: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", intent.lower()).strip("_")
    return (s[:24] or "program")


def build_from_intent(intent: str, generator, *, cases=None, oracle=None, expected=None,
                      max_iters: int = 6, out_path: str | None = None, name: str | None = None,
                      verbose: bool = True) -> dict:
    """Drive `generator` through the harness until the request is satisfied.

    Returns {success, iterations, ir, path, outputs, trajectory}. `outputs` holds the stdout
    for each case from the final attempt so the caller can judge correctness.
    """
    name = name or _slug(intent)
    cases = cases or [{"stdin": ""}]
    out = out_path or os.path.join("build", f"{name}.exe")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    task = {"name": name, "intent": intent, "cases": cases}
    if oracle:
        task["oracle"] = oracle

    trajectory: list[dict] = []
    fbk: str | None = None

    for it in range(max_iters):
        if verbose:
            print(f"[{name}] iteration {it}: asking the model for IR...")
        ir = generator(task, fbk, iteration=it)
        step = {"iteration": it, "feedback_in": fbk, "tool_calls": []}

        rep = harness.build_binary(ir, out)
        step["tool_calls"].append({"tool": "build_binary", "ok": rep["ok"]})
        if not rep["ok"]:
            fbk = fb.from_build(rep)
            step["feedback_out"] = fbk
            trajectory.append(step)
            _say(verbose, "  build failed", fbk)
            continue

        vp = harness.validate_pe(out)
        step["tool_calls"].append({"tool": "validate_pe", "ok": vp["ok"]})
        if not vp["ok"]:
            fbk = fb.from_validate(vp)
            step["feedback_out"] = fbk
            trajectory.append(step)
            _say(verbose, "  PE invalid", fbk)
            continue

        # verification
        if oracle or expected is not None:
            ref = {"oracle": oracle} if oracle else {"expected": expected}
            diff = harness.diff_behavior(out, ref, cases)
            step["tool_calls"].append({"tool": "diff_behavior",
                                       "pass_count": diff["pass_count"], "total": diff["total"]})
            outputs = [c["got"] for c in diff["per_case"]]
            if diff["pass_count"] == diff["total"]:
                trajectory.append(step)
                _say(verbose, f"  SOLVED ({diff['pass_count']}/{diff['total']} cases)", None)
                return _ok(it, ir, out, outputs, trajectory)
            fbk = fb.from_diff(out, diff, task)
        else:
            runs = [harness.run(out, stdin=c.get("stdin", "")) for c in cases]
            outputs = [r["stdout"] for r in runs]
            bad = [r for r in runs if r["crashed"] or r["truncated"]]
            step["tool_calls"].append({"tool": "run", "ok": not bad})
            if not bad:
                trajectory.append(step)
                _say(verbose, "  runs cleanly", None)
                if verbose:
                    for c, o in zip(cases, outputs):
                        print(f"     input={c.get('stdin','')!r} -> output={o!r}")
                return _ok(it, ir, out, outputs, trajectory)
            fbk = _crash_feedback(out, cases, runs)

        step["feedback_out"] = fbk
        trajectory.append(step)
        _say(verbose, "  not yet correct", fbk)

    return {"success": False, "iterations": max_iters, "ir": ir, "path": out,
            "outputs": outputs if "outputs" in dir() else [], "trajectory": trajectory}


def _crash_feedback(path, cases, runs) -> str:
    for c, r in zip(cases, runs):
        if r["crashed"]:
            ca = harness.crash_analysis(path, stdin=c.get("stdin", ""))
            return (f"On input {c.get('stdin','')!r} the program CRASHED: {ca['reason']} at "
                    f"{ca['fault_addr']} ({ca['fault_instruction']['mnemonic']} "
                    f"{ca['fault_instruction']['operands']}). Likely cause: {ca['likely_cause']}.")
        if r["truncated"]:
            return (f"On input {c.get('stdin','')!r} the program hit the instruction limit — "
                    "likely an infinite loop. Make sure every loop has an exit condition.")
    return "The program did not run cleanly."


def _ok(it, ir, out, outputs, trajectory):
    return {"success": True, "iterations": it + 1, "ir": ir, "path": out,
            "outputs": outputs, "trajectory": trajectory}


def _say(verbose, status, detail):
    if verbose:
        print(status)
        if detail:
            for line in str(detail).splitlines():
                print(f"     {line}")
