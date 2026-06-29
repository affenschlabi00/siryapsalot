"""The harness: emulated execution + introspection (Plan §6).

The same engine is correctness checker, debugger, and (later) RL reward signal. These are
the MCP tool surface, importable directly as Python functions.
"""
from __future__ import annotations

from ..backend import build_binary
from .apidb import resolve_api
from .differ import diff_behavior
from .disasm import disassemble
from .runner import crash_analysis, inspect, run, trace
from .validate_pe import list_imports, validate_pe

__all__ = [
    "build_binary", "validate_pe", "disassemble", "run", "trace",
    "inspect", "crash_analysis", "diff_behavior", "list_imports", "resolve_api",
]
