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

    Turns a plain-English request into IR using whatever model backend is available — the
    Anthropic API or a local Ollama model (see bytewright.llm.make_backend; no key required for
    Ollama). The system prompt is assembled from the live schema, API surface, and worked
    examples (prompt.py) so it can't drift from the backend.
    """

    def __init__(self, backend=None, model: str | None = None, temperature: float = 0.0):
        from ..llm import make_backend
        from . import prompt
        self._prompt = prompt
        self.backend = backend or make_backend()
        self.temperature = temperature

    def __call__(self, task, feedback=None, iteration=0):
        text = self.backend.chat(
            self._prompt.system_prompt(),
            [{"role": "user", "content": self._prompt.user_prompt(
                task["intent"], feedback, task.get("cases"))}],
            temperature=self.temperature)
        return extract_json(text)


# Alias: the headline generator users reach for.
AnthropicGenerator = LLMGenerator


class CallableGenerator:
    """Wrap any `fn(intent, feedback, iteration) -> ir_dict` as a generator.

    Lets a human (or Claude driving a Claude Code session) be the model: the loop, harness,
    feedback, and verification are identical to the API path.
    """

    def __init__(self, fn):
        self.fn = fn

    def __call__(self, task, feedback=None, iteration=0):
        return self.fn(task["intent"], feedback, iteration)


def extract_json(text: str) -> dict:
    """Pull a JSON IR object out of a model reply (tolerates ```json fences and prose)."""
    text = text.strip()
    if "```" in text:
        seg = text.split("```")[1]
        text = seg[4:] if seg.lower().startswith("json") else seg
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("no JSON object found in model reply")
    return json.loads(text[start:end + 1])
