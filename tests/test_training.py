"""Phase 5 scaffolding: reward on raw bytes, the RL environment, and SFT formatting."""
import json
import os

from bytewright import dataset
from bytewright.eval import TASKS_BY_NAME, library_get_ir
from bytewright.reward import reward
from bytewright.training import RLEnv, to_sft
from conftest import load_example


def test_reward_scores_raw_bytes():
    obj = load_example("raw_hi.obj.json")
    r = reward(obj, {"name": "hi", "cases": [{"stdin": ""}]}, kind="obj")
    assert r["rungs"]["valid"] and r["rungs"]["builds"] and r["rungs"]["runs"]
    assert r["score"] > 0


def test_reward_zero_on_invalid_raw():
    bad = {"code": "zz", "relocs": []}                # not valid hex
    assert reward(bad, {"name": "x", "cases": [{"stdin": ""}]}, kind="obj")["score"] == 0.0


def test_rl_env_grades_ir():
    env = RLEnv(TASKS_BY_NAME["factorial"])
    good = env.step(library_get_ir(TASKS_BY_NAME["factorial"]))
    assert good["reward"] >= 1.0 and good["solved"]
    bad = env.step({"metadata": {"name": "x", "entry": "main"},
                    "code": [{"label": "main", "instructions": [{"op": "push", "args": ["rbx"]}]}]})
    assert bad["reward"] == 0.0 and not bad["solved"]


def test_rl_env_grades_raw():
    env = RLEnv({"name": "hi", "cases": [{"stdin": ""}]})
    step = env.step(load_example("raw_hi.obj.json"), kind="obj")
    assert step["rungs"]["runs"] and step["reward"] > 0


def test_dataset_includes_raw_and_to_sft(tmp_path):
    out = str(tmp_path / "ds.jsonl")
    stats = dataset.build_dataset(out)
    assert stats["raw"] == 1 and stats["reference"] >= 8
    samples = dataset.load_dataset(out)
    sft = to_sft(samples)
    kinds = {p["kind"] for p in sft}
    assert {"ir", "raw", "repair"} <= kinds
    for p in sft:                                    # every pair is a valid chat triple
        roles = [m["role"] for m in p["messages"]]
        assert roles == ["system", "user", "assistant"]
        json.loads(p["messages"][2]["content"])      # assistant target is valid JSON
