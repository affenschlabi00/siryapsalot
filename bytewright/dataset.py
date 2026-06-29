"""Phase 4 starter — the training-data factory (Plan §4, §7).

Turns the working system into a data generator. Two sources, both buildable now:
  1. Reference samples: (intent -> verified IR) from the task suite, each scored by the
     harness reward so only correct, runnable pairs are kept.
  2. Repair trajectories: (intent -> buggy IR -> harness feedback -> fixed IR) harvested from
     agent runs — the "how to fix a broken binary" data the plan calls pure gold.

Full Phase 4 (compiling real source at multiple optimization levels for scale) builds on this
same schema; that part is gated on a corpus + compute decision (see decisions.md).
"""
from __future__ import annotations

import json
import os

from . import reward as _reward
from .agent import ScriptedGenerator, break_factorial_digit, make_buggy, solve
from .eval import TASKS, TASKS_BY_NAME, library_get_ir


def reference_sample(task: dict) -> dict:
    """A verified (intent -> IR) supervised pair, scored by the harness reward."""
    ir = library_get_ir(task)
    r = _reward.reward(ir, task)
    return {
        "intent": task["intent"],
        "ir": ir,
        "source": "reference",
        "verified": r["rungs"].get("tests_passed", "").endswith(f"/{len(task['cases'])}")
        and r["score"] >= 1.0,
        "reward": r["score"],
        "cases": task["cases"],
    }


def trajectory_sample(task: dict, result: dict) -> dict:
    """A repair trajectory: every IR attempt with the feedback that drove the next one."""
    attempts = []
    for step in result["trajectory"]:
        attempts.append({"ir": step.get("ir"),
                         "feedback_in": step.get("feedback_in"),
                         "feedback_out": step.get("feedback_out")})
    return {
        "intent": task["intent"],
        "source": "repair_trajectory",
        "success": result["success"],
        "iterations": result["iterations"],
        "attempts": attempts,
        "final_ir": result.get("ir"),
    }


def raw_reference_sample() -> dict:
    """A verified (intent -> raw machine-code bytes) pair — training data for byte emission."""
    import json
    import os

    from . import harness, raw
    path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "examples", "raw_hi.obj.json"))
    obj = json.load(open(path))
    rep = raw.build_from_obj(obj, "build/_ds_raw.exe")
    out = harness.run(rep["path"])["stdout"] if rep["ok"] else ""
    return {
        "intent": "Print 'Hi' to the console, emitted as raw x86-64 machine code (no IR).",
        "obj": obj,
        "source": "raw_reference",
        "verified": rep["ok"] and out == "Hi\n",
        "output": out,
    }


def harvest_repair_demo() -> dict:
    """Generate one repair trajectory (buggy factorial -> fixed) as a worked sample."""
    task = TASKS_BY_NAME["factorial"]
    buggy = make_buggy(task["solution"], break_factorial_digit)
    fixed = library_get_ir(task)
    result = solve(task, ScriptedGenerator([buggy, fixed]), max_iters=4)
    return trajectory_sample(task, result)


def build_dataset(out_path: str = "datasets/bytewright.jsonl", tasks=TASKS,
                  include_trajectories: bool = True) -> dict:
    """Write a JSONL dataset of reference samples (+ a repair trajectory). Returns stats."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    samples = [reference_sample(t) for t in tasks]
    samples.append(raw_reference_sample())          # an (intent -> raw bytes) pair
    if include_trajectories:
        samples.append(harvest_repair_demo())
    with open(out_path, "w") as fh:
        for s in samples:
            fh.write(json.dumps(s) + "\n")
    verified = sum(1 for s in samples if s.get("verified"))
    return {"path": out_path, "count": len(samples),
            "reference": sum(s["source"] == "reference" for s in samples),
            "raw": sum(s["source"] == "raw_reference" for s in samples),
            "trajectories": sum(s["source"] == "repair_trajectory" for s in samples),
            "verified": verified}


def load_dataset(path: str) -> list[dict]:
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]
