"""Format harvested samples into chat-style supervised fine-tuning pairs (Plan §4/§5).

Each pair is {messages:[system, user, assistant]} where the assistant turn is the target the
model should learn to emit — an IR object, raw machine-code object, or a repaired version given
harness feedback. This is the distillation data; the RLEnv reward then refines it.
"""
from __future__ import annotations

import json

from ..agent import prompt as _prompt

_RAW_SYSTEM = (
    "You emit programs as a raw Bytewright object: literal x86-64 machine-code bytes plus a "
    "relocation list. Reply with ONLY a JSON object {metadata:{name,subsystem,entry_offset}, "
    "code:'<hex>', imports:[...], data:[...], relocs:[{offset,kind,target}]}."
)


def _pair(system: str, user: str, assistant: str, kind: str) -> dict:
    return {"kind": kind, "messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "assistant", "content": assistant},
    ]}


def to_sft(samples: list[dict]) -> list[dict]:
    """Convert dataset samples (see bytewright.dataset) into SFT chat pairs."""
    sys_ir = _prompt.system_prompt()
    out: list[dict] = []
    for s in samples:
        intent = s.get("intent", "")
        if s.get("source") == "reference" and "ir" in s:
            out.append(_pair(sys_ir, _prompt.user_prompt(intent), json.dumps(s["ir"]), "ir"))
        elif s.get("source") == "raw_reference" and "obj" in s:
            out.append(_pair(_RAW_SYSTEM, f"Build this program:\n{intent}",
                             json.dumps(s["obj"]), "raw"))
        elif s.get("source") == "repair_trajectory":
            # one pair per attempt: teach both the first try and how to repair given feedback
            for att in s.get("attempts", []):
                if att.get("ir") is None:
                    continue
                user = _prompt.user_prompt(intent, feedback=att.get("feedback_in"))
                out.append(_pair(sys_ir, user, json.dumps(att["ir"]), "repair"))
    return out
