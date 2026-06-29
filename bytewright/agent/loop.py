"""The agentic repair loop (Plan §3): task -> IR -> build -> validate -> run/diff ->
read trace/crash on failure -> repair -> repeat.

Every trajectory (task, IR versions, tool calls, feedback, final binary) is logged — this is
both the debugging record and the future training data (Plan §3, §4).
"""
from __future__ import annotations

import json
import os

from .. import harness
from . import feedback as fb


def solve(task: dict, generator, max_iters: int = 5, out_dir: str = "build",
          log_path: str | None = None, verbose: bool = False) -> dict:
    """Drive `generator` through the harness until the task's cases pass or iters run out."""
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{task['name']}.exe")
    trajectory: list[dict] = []
    fbk: str | None = None

    for it in range(max_iters):
        ir = generator(task, fbk, iteration=it)
        step = {"iteration": it, "ir": ir, "tool_calls": [], "feedback_in": fbk}

        rep = harness.build_binary(ir, out)
        step["tool_calls"].append({"tool": "build_binary", "ok": rep["ok"], "errors": rep["errors"]})
        if not rep["ok"]:
            fbk = fb.from_build(rep)
            step["feedback_out"] = fbk
            trajectory.append(step)
            _log(verbose, task, it, "build failed", fbk)
            continue

        vp = harness.validate_pe(out)
        step["tool_calls"].append({"tool": "validate_pe", "ok": vp["ok"], "issues": vp["issues"]})
        if not vp["ok"]:
            fbk = fb.from_validate(vp)
            step["feedback_out"] = fbk
            trajectory.append(step)
            _log(verbose, task, it, "validate failed", fbk)
            continue

        diff = harness.diff_behavior(out, {"oracle": task["oracle"]}, task["cases"])
        step["tool_calls"].append({"tool": "diff_behavior",
                                   "pass_count": diff["pass_count"], "total": diff["total"]})
        if diff["pass_count"] == diff["total"]:
            step["success"] = True
            trajectory.append(step)
            _log(verbose, task, it, "SOLVED", f"{diff['pass_count']}/{diff['total']} cases")
            result = {"success": True, "iterations": it + 1, "ir": ir, "path": out,
                      "trajectory": trajectory}
            _save(log_path, task, result)
            return result

        fbk = fb.from_diff(out, diff, task)
        step["feedback_out"] = fbk
        trajectory.append(step)
        _log(verbose, task, it, f"{diff['pass_count']}/{diff['total']} cases", fbk)

    result = {"success": False, "iterations": max_iters, "trajectory": trajectory, "path": out}
    _save(log_path, task, result)
    return result


def _log(verbose, task, it, status, detail):
    if verbose:
        print(f"[{task['name']}] iter {it}: {status}")
        if detail and status not in ("SOLVED",):
            for line in str(detail).splitlines():
                print(f"        {line}")


def _save(log_path, task, result):
    if not log_path:
        return
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
    with open(log_path, "a") as fh:
        fh.write(json.dumps({"task": task["name"], "success": result["success"],
                             "iterations": result["iterations"],
                             "trajectory": result["trajectory"]}, default=str) + "\n")
