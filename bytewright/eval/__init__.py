"""Evaluation: task suite, oracles, and runner (Plan §7)."""
from __future__ import annotations

from . import oracles  # noqa: F401  (registers ORACLES, imported by harness.differ)
from .runner import evaluate_ir, library_get_ir, run_suite
from .tasks import TASKS, TASKS_BY_NAME

__all__ = ["TASKS", "TASKS_BY_NAME", "evaluate_ir", "run_suite", "library_get_ir", "oracles"]
