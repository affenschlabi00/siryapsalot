"""Turn harness tool output into actionable feedback for the generator (Plan §3).

This is what makes the loop a *repair* loop rather than blind resampling: the structured
errors, crash diagnosis, and behavioral diffs are fed back so the next IR is informed.
"""
from __future__ import annotations

from .. import harness


def from_build(rep: dict) -> str:
    lines = ["The backend rejected the IR:"]
    for e in rep["errors"]:
        ref = f" [{e['instruction_ref']}]" if e.get("instruction_ref") else ""
        lines.append(f"  - ({e['stage']}){ref} {e['message']}")
    return "\n".join(lines)


def from_validate(vp: dict) -> str:
    return "The PE failed structural validation:\n" + "\n".join(f"  - {i}" for i in vp["issues"])


def from_diff(path: str, diff: dict, task: dict) -> str:
    """Explain the first failing case; enrich with a crash diagnosis or a trace if useful."""
    fail = next((c for c in diff["per_case"] if not c["match"]), None)
    if fail is None:
        return "Some cases failed but none could be isolated."

    lines = [f"{diff['pass_count']}/{diff['total']} cases passed. First failure:",
             f"  input:    {fail['input']!r}",
             f"  expected: {fail['expected']!r}",
             f"  got:      {fail['got']!r}"]

    # was it a crash?
    ca = harness.crash_analysis(path, stdin=fail["input"])
    if ca.get("crashed"):
        lines.append(f"  The program CRASHED: {ca['reason']} at {ca['fault_addr']} "
                     f"({ca['fault_instruction']['mnemonic']} {ca['fault_instruction']['operands']}).")
        lines.append(f"  Likely cause: {ca['likely_cause']}.")
    else:
        if "first_divergence_output_byte" in fail and fail["first_divergence_output_byte"] is not None:
            lines.append(f"  Output first diverges at byte {fail['first_divergence_output_byte']}.")
        run = harness.run(path, stdin=fail["input"])
        if run["truncated"]:
            lines.append("  Execution hit the instruction limit — likely an infinite loop.")
    return "\n".join(lines)
