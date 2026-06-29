"""bytewright command-line interface — drive the backend and harness from a shell."""
from __future__ import annotations

import argparse
import json
import sys

from . import harness


def _load_ir(path: str) -> dict:
    with open(path) as fh:
        return json.load(fh)


def _print(obj):
    print(json.dumps(obj, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="bytewright", description="intent -> verifiable IR -> .exe")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="compile IR JSON to a .exe")
    b.add_argument("ir"); b.add_argument("-o", "--out")

    r = sub.add_parser("run", help="run a .exe in the emulator")
    r.add_argument("exe"); r.add_argument("--stdin", default="")

    t = sub.add_parser("trace", help="trace execution step by step")
    t.add_argument("exe"); t.add_argument("--stdin", default=""); t.add_argument("--max-steps", type=int, default=2000)

    v = sub.add_parser("validate", help="structural PE validation")
    v.add_argument("exe")

    d = sub.add_parser("disasm", help="disassemble .text")
    d.add_argument("exe"); d.add_argument("--count", type=int, default=64)

    i = sub.add_parser("imports", help="list imported APIs")
    i.add_argument("exe")

    c = sub.add_parser("crash", help="analyze a crash")
    c.add_argument("exe"); c.add_argument("--stdin", default="")

    args = p.parse_args(argv)

    if args.cmd == "build":
        rep = harness.build_binary(_load_ir(args.ir), args.out)
        _print(rep)
        return 0 if rep["ok"] else 1
    if args.cmd == "run":
        _print(harness.run(args.exe, stdin=args.stdin)); return 0
    if args.cmd == "trace":
        _print(harness.trace(args.exe, stdin=args.stdin, max_steps=args.max_steps)); return 0
    if args.cmd == "validate":
        rep = harness.validate_pe(args.exe); _print(rep); return 0 if rep["ok"] else 1
    if args.cmd == "disasm":
        _print(harness.disassemble(args.exe, {"count": args.count})); return 0
    if args.cmd == "imports":
        _print(harness.list_imports(args.exe)); return 0
    if args.cmd == "crash":
        _print(harness.crash_analysis(args.exe, stdin=args.stdin)); return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
