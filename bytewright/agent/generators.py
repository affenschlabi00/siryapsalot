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

    This is the generator that turns a user's plain-English request into IR. It needs the
    `anthropic` SDK and an API key (ANTHROPIC_API_KEY); the model id comes from BYTEWRIGHT_MODEL
    (default: claude-sonnet-4-6). The system prompt is assembled from the live schema, API
    surface, and worked examples (see prompt.py) so it can't drift from the backend.
    """

    def __init__(self, model: str | None = None, max_tokens: int = 8192,
                 temperature: float = 0.0):
        import os
        try:
            import anthropic  # raised lazily so the package imports without the SDK
        except ImportError as e:
            raise RuntimeError(
                "the model-driven generator needs the anthropic SDK: pip install anthropic"
            ) from e
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Set it to let the model generate IR, or pass a "
                "different generator (e.g. one where Claude-in-the-loop supplies the IR).")
        from . import prompt
        self._prompt = prompt
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("BYTEWRIGHT_MODEL", "claude-sonnet-4-6")
        self.max_tokens = max_tokens
        self.temperature = temperature

    def __call__(self, task, feedback=None, iteration=0):
        msg = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, temperature=self.temperature,
            system=self._prompt.system_prompt(),
            messages=[{"role": "user", "content": self._prompt.user_prompt(
                task["intent"], feedback, task.get("cases"))}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
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
