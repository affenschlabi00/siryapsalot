"""The Phase 3 agentic scaffolding: drive a generator through the harness to build and
repair working binaries (Plan §3)."""
from __future__ import annotations

from .generators import (LibraryGenerator, LLMGenerator, ScriptedGenerator,
                         break_factorial_digit, make_buggy)
from .loop import solve

__all__ = ["solve", "LibraryGenerator", "ScriptedGenerator", "LLMGenerator",
           "make_buggy", "break_factorial_digit"]
