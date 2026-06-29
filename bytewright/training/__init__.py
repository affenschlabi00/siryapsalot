"""Phase 5 — the training interface (Plan §5).

The model isn't trained here (that's gated on compute), but the two things training needs are
real and runnable now:

  - RLEnv: the harness packaged as a verifiable-reward environment. `env.step(program)` returns
    the dense reward (the RLVR signal). Works for IR programs and raw byte emissions alike.
  - to_sft: turns harvested (intent -> IR/bytes) samples and repair trajectories into chat-format
    supervised fine-tuning pairs.

Together with bytewright.reward (the ladder) and bytewright.dataset (the harvester), this is the
scaffolding to distill then RL a model that emits binaries.
"""
from __future__ import annotations

from .rl_env import RLEnv, make_envs
from .sft_data import to_sft

__all__ = ["RLEnv", "make_envs", "to_sft"]
