"""IR generators for the agent loop (Plan §3).

A generator is `callable(task, feedback, iteration) -> ir_dict`. The loop is generator-
agnostic, so the same harness drives a scaffolded frontier model (LLMGenerator) today and a
trained model later. The Scripted/Library generators make the loop runnable and testable
without external credentials.
"""
from __future__ import annotations

import copy
import json


class LibraryGenerator:
    """Returns the known-good reference IR for the task (happy path / regression)."""

    def __call__(self, task, feedback=None, iteration=0):
        return json.load(open(task["solution"]))


class ScriptedGenerator:
    """Returns a pre-scripted sequence of IRs, advancing each iteration.

    A stand-in for a model: it demonstrates that the loop consumes harness feedback and
    converges. `irs` is typically [buggy, fixed].
    """

    def __init__(self, irs: list[dict]):
        self.irs = irs

    def __call__(self, task, feedback=None, iteration=0):
        return self.irs[min(iteration, len(self.irs) - 1)]


def make_buggy(solution_path: str, mutate) -> dict:
    """Load a known-good IR and apply a mutation that introduces a bug."""
    ir = json.load(open(solution_path))
    mutate(ir)
    return ir


def break_factorial_digit(ir: dict) -> None:
    """Off-by-one in the digit conversion: '0'+d uses 47 instead of 48 -> wrong glyphs."""
    for proc in ir["code"]:
        for ins in proc["instructions"]:
            if ins.get("op") == "add" and ins.get("args") == ["dl", "48"]:
                ins["args"] = ["dl", "47"]


class LLMGenerator:
    """Scaffold a frontier model through the harness (Plan §3, the real v1 path).

    Optional: requires the `anthropic` SDK and an API key. Builds a prompt from the task
    intent, the frozen IR schema, resolve_api hints, and the previous harness feedback, then
    parses an IR JSON object from the reply. Kept dependency-light so the rest of the package
    works without it.
    """

    def __init__(self, model: str = "claude-opus-4-8", max_tokens: int = 4096):
        import anthropic  # raised lazily so the package imports without the SDK
        self.client = anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens
        self._schema = json.load(open(_schema_path()))

    def __call__(self, task, feedback=None, iteration=0):
        sys = (
            "You write programs as Bytewright IR (machine-level x86-64 with symbolic names). "
            "The deterministic backend handles encoding, the stack frame (do NOT emit "
            "push/pop/sub rsp/ret-for-frame), register allocation of %vN (callee-saved), and "
            "linking. Outgoing stack args go at [rsp+32], [rsp+40], ... The entry procedure "
            "must end by calling ExitProcess. Reply with ONLY a JSON IR object.\n\n"
            f"IR JSON schema:\n{json.dumps(self._schema)}"
        )
        user = f"Task: {task['intent']}"
        if feedback:
            user += f"\n\nYour previous attempt failed. Harness feedback:\n{feedback}\n\nFix it."
        msg = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens,
            system=sys, messages=[{"role": "user", "content": user}],
        )
        return _extract_json("".join(b.text for b in msg.content if b.type == "text"))


def _schema_path() -> str:
    import os
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "schema", "ir.schema.json"))


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        text = text[4:] if text.startswith("json") else text
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])
