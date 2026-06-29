"""Phase 4/5 starters: the dense reward ladder and the dataset harvester."""
import os

from bytewright import dataset
from bytewright.agent import break_factorial_digit, make_buggy
from bytewright.eval import TASKS_BY_NAME, library_get_ir
from bytewright.reward import reward


def test_reward_is_monotone_in_correctness():
    task = TASKS_BY_NAME["factorial"]
    good = reward(library_get_ir(task), task)
    buggy = reward(make_buggy(task["solution"], break_factorial_digit), task)
    invalid = reward({"metadata": {"name": "x", "entry": "main"},
                      "code": [{"label": "main", "instructions": [{"op": "push", "args": ["rbx"]}]}]},
                     task)
    assert good["score"] > buggy["score"] > invalid["score"]
    assert invalid["score"] == 0.0
    assert good["rungs"]["tests_passed"] == "5/5"


def test_reward_gives_partial_gradient_on_wrong_output():
    """A program that builds and runs but produces wrong output still scores > 0 (a gradient)."""
    task = TASKS_BY_NAME["factorial"]
    buggy = reward(make_buggy(task["solution"], break_factorial_digit), task)
    assert 0.0 < buggy["score"] < 1.0
    assert buggy["rungs"]["runs"] is True            # it ran...
    assert buggy["rungs"]["tests_passed"] == "0/5"   # ...but produced wrong output
    assert 0.0 < buggy["signals"]["output_similarity"] < 1.0


def test_all_reference_solutions_score_full():
    from bytewright.eval import TASKS
    for task in TASKS:
        r = reward(library_get_ir(task), task)
        assert r["score"] >= 1.0, (task["name"], r)


def test_dataset_harvest(tmp_path):
    out = str(tmp_path / "ds.jsonl")
    stats = dataset.build_dataset(out)
    assert stats["reference"] >= 8 and stats["trajectories"] == 1
    samples = dataset.load_dataset(out)
    assert all("intent" in s for s in samples)
    traj = [s for s in samples if s["source"] == "repair_trajectory"][0]
    assert traj["success"] and len(traj["attempts"]) == 2
