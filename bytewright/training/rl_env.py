"""RLVR environment: the harness as a verifiable-reward function (Plan §5).

A model proposes a program (IR or raw bytes) for a task; `step` returns the dense reward from
the ladder (validates -> builds -> loadable -> runs -> k/n tests -> all -> efficiency). This is
the reward an RL loop optimizes; it is objective and computed entirely by the trusted harness.
"""
from __future__ import annotations

from ..agent import prompt as _prompt
from ..reward import reward


class RLEnv:
    """One task = one environment. Stateless `step` (each attempt is graded independently)."""

    def __init__(self, task: dict):
        self.task = task

    def prompt(self) -> str:
        """The instruction shown to the policy model."""
        return _prompt.user_prompt(self.task["intent"], cases=self.task.get("cases"))

    def step(self, program: dict, kind: str = "ir") -> dict:
        """Grade a proposed program. Returns {reward, score, rungs, signals, solved}."""
        r = reward(program, self.task, kind=kind)
        n = len(self.task.get("cases", []))
        return {
            "reward": r["score"],
            "score": r["score"],
            "rungs": r["rungs"],
            "signals": r["signals"],
            "depth": r["depth"],
            "solved": r["rungs"].get("tests_passed") == f"{n}/{n}" and n > 0,
        }


def make_envs(tasks) -> list[RLEnv]:
    return [RLEnv(t) for t in tasks]
