"""MCP server — exposes the harness + backend tools to an agent/model (Plan §6).

These are the model's senses: construct a binary, statically validate it, read it back,
execute it, record an execution movie, snapshot state, decode crashes, diff against an
oracle, and learn how to call a Win32 API. Run with:  python -m bytewright.mcp_server
(stdio transport, as MCP clients expect).
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import harness
from .agent import LibraryGenerator, solve as _solve
from .eval import TASKS_BY_NAME

mcp = FastMCP("bytewright")


@mcp.tool()
def build_binary(ir: dict, out_path: str | None = None) -> dict:
    """Compile a Bytewright IR program (see schema/ir.schema.json) into a Windows .exe."""
    return harness.build_binary(ir, out_path)


@mcp.tool()
def validate_pe(path: str) -> dict:
    """Statically validate a PE: will the Windows loader accept it? (structure, entry, imports)."""
    return harness.validate_pe(path)


@mcp.tool()
def disassemble(path: str, start_rva: str | None = None, count: int = 64) -> dict:
    """Disassemble a region of a PE (default: 64 instructions from the entry point)."""
    rng = {"count": count}
    if start_rva is not None:
        rng["start_rva"] = start_rva
    return harness.disassemble(path, rng)


@mcp.tool()
def run(path: str, stdin: str = "", timeout_ms: int = 5000) -> dict:
    """Execute a .exe in the sandboxed emulator; returns stdout/stderr/exit_code/files."""
    return harness.run(path, stdin=stdin, timeout_ms=timeout_ms)


@mcp.tool()
def trace(path: str, stdin: str = "", max_steps: int = 100000) -> dict:
    """Run recording every instruction — the deterministic execution movie (registers, memory, APIs)."""
    return harness.trace(path, stdin=stdin, max_steps=max_steps)


@mcp.tool()
def inspect(path: str, step: int | None = None, breakpoint_rva: str | None = None,
            stdin: str = "") -> dict:
    """Snapshot registers/stack/call-stack at a step index or a breakpoint RVA."""
    at = {"step": step} if step is not None else {"breakpoint_rva": breakpoint_rva}
    return harness.inspect(path, at, stdin=stdin)


@mcp.tool()
def crash_analysis(path: str, stdin: str = "") -> dict:
    """If the program faults, decode why: fault address, instruction, reason, likely cause."""
    return harness.crash_analysis(path, stdin=stdin)


@mcp.tool()
def diff_behavior(path: str, reference: dict, cases: list[dict]) -> dict:
    """Compare a candidate .exe against a reference exe / oracle / expected outputs across cases."""
    return harness.diff_behavior(path, reference, cases)


@mcp.tool()
def list_imports(path: str) -> dict:
    """List the Win32 APIs a PE imports, with their IAT slot RVAs."""
    return harness.list_imports(path)


@mcp.tool()
def resolve_api(name: str) -> dict:
    """How to call a Win32 function correctly: signature, calling convention, arg registers."""
    return harness.resolve_api(name)


@mcp.tool()
def solve_task(task_name: str, max_iters: int = 5) -> dict:
    """Run the scaffolded agent loop on a named eval task using the reference generator."""
    task = TASKS_BY_NAME.get(task_name)
    if not task:
        return {"error": f"unknown task '{task_name}'", "known": list(TASKS_BY_NAME)}
    res = _solve(task, LibraryGenerator(), max_iters=max_iters)
    return {"success": res["success"], "iterations": res["iterations"], "path": res.get("path")}


def main():
    mcp.run()


if __name__ == "__main__":
    main()
