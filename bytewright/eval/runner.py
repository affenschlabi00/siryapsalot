"""Eval runner: score an IR (or an agent) against the task suite via the harness (Plan §7)."""
from __future__ import annotations

import json

from .. import harness
from .tasks import TASKS


def evaluate_ir(ir: dict, task: dict, out_path: str | None = None) -> dict:
    """Build the IR and check it against the task's oracle across all cases."""
    out = out_path or f"build/{task['name']}.exe"
    rep = harness.build_binary(ir, out)
    if not rep["ok"]:
        return {"task": task["name"], "passed": False, "stage": "build", "errors": rep["errors"]}

    vp = harness.validate_pe(out)
    if not vp["ok"]:
        return {"task": task["name"], "passed": False, "stage": "validate_pe", "issues": vp["issues"]}

    diff = harness.diff_behavior(out, {"oracle": task["oracle"]}, task["cases"])
    return {
        "task": task["name"],
        "passed": diff["pass_count"] == diff["total"],
        "stage": "run",
        "pass_count": diff["pass_count"],
        "total": diff["total"],
        "per_case": diff["per_case"],
        "path": out,
    }


def run_suite(get_ir, tasks=TASKS) -> dict:
    """get_ir(task) -> ir dict (e.g. a generator or `lambda t: json.load(open(t['solution']))`)."""
    results = []
    for task in tasks:
        try:
            ir = get_ir(task)
            results.append(evaluate_ir(ir, task))
        except Exception as e:  # a generator/build blew up
            results.append({"task": task["name"], "passed": False, "stage": "exception", "error": str(e)})
    passed = sum(r["passed"] for r in results)
    return {"results": results, "passed": passed, "total": len(tasks)}


def library_get_ir(task: dict) -> dict:
    """Reference solutions: load the known-good IR for a task."""
    return json.load(open(task["solution"]))
