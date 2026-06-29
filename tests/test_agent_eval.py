"""Phase 3: the eval suite passes via the harness, and the repair loop converges."""
import json

from bytewright.agent import ScriptedGenerator, break_factorial_digit, make_buggy, solve
from bytewright.eval import TASKS_BY_NAME, library_get_ir, run_suite


def test_eval_suite_all_pass():
    summary = run_suite(library_get_ir)
    assert summary["passed"] == summary["total"], [r for r in summary["results"] if not r["passed"]]


def test_repair_loop_converges():
    """Buggy factorial -> harness feedback -> fixed factorial, in <= 2 iterations."""
    task = TASKS_BY_NAME["factorial"]
    buggy = make_buggy(task["solution"], break_factorial_digit)
    fixed = json.load(open(task["solution"]))
    res = solve(task, ScriptedGenerator([buggy, fixed]), max_iters=4)
    assert res["success"]
    assert res["iterations"] == 2
    # first iteration must have failed at diff_behavior (not build/validate)
    first = res["trajectory"][0]
    diff_call = [c for c in first["tool_calls"] if c["tool"] == "diff_behavior"][0]
    assert diff_call["pass_count"] < diff_call["total"]


def test_library_generator_solves_in_one_iteration():
    from bytewright.agent import LibraryGenerator
    task = TASKS_BY_NAME["hello"]
    res = solve(task, LibraryGenerator(), max_iters=3)
    assert res["success"] and res["iterations"] == 1
