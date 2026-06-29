"""The Phase 3 agentic scaffolding: drive a generator through the harness to build and
repair working binaries from intent (Plan §3)."""
from __future__ import annotations

from .build import build_from_intent
from .generators import (AnthropicGenerator, CallableGenerator, LibraryGenerator,
                         LLMGenerator, ScriptedGenerator, break_factorial_digit,
                         extract_json, make_buggy)
from .loop import solve

__all__ = [
    "solve", "build_from_intent",
    "LibraryGenerator", "ScriptedGenerator", "LLMGenerator", "AnthropicGenerator",
    "CallableGenerator", "make_buggy", "break_factorial_digit", "extract_json",
]
