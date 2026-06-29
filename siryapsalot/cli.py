"""siryapsalot command-line interface — drive the backend and harness from a shell."""
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
    p = argparse.ArgumentParser(
        prog="siryapsalot",
        description="A chatbot that builds Windows binaries. Just run `siryapsalot` and chat.")
    sub = p.add_subparsers(dest="cmd")   # no subcommand -> chat

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

    e = sub.add_parser("eval", help="run the eval task suite (reference solutions)")
    e.add_argument("--task", help="run only this task")

    s = sub.add_parser("solve", help="run the agent repair loop on a task")
    s.add_argument("task"); s.add_argument("--max-iters", type=int, default=5)

    cr = sub.add_parser("create", help="describe a program; the AI builds the .exe (no specs needed)")
    cr.add_argument("intent", help='e.g. "make me a game" or "print the first 10 primes"')
    cr.add_argument("--max-iters", type=int, default=6)

    sub.add_parser("chat", help="conversational: just tell it what to build (default)")

    sv = sub.add_parser("serve", help="open a browser chat UI to build binaries")
    sv.add_argument("--port", type=int, default=8765)

    rw = sub.add_parser("reward", help="score a task's reference IR on the dense reward ladder")
    rw.add_argument("task")

    ds = sub.add_parser("dataset", help="harvest a training dataset (Phase 4)")
    ds.add_argument("-o", "--out", default="datasets/siryapsalot.jsonl")

    rb = sub.add_parser("rawbuild", help="build from raw machine-code bytes + relocations (an object)")
    rb.add_argument("obj"); rb.add_argument("-o", "--out"); rb.add_argument("--stdin", default="")

    args = p.parse_args(argv)

    if args.cmd is None or args.cmd == "chat":
        return _chat()
    if args.cmd == "serve":
        from .web import serve
        try:
            serve(port=args.port)
        except Exception as e:
            from .llm import LLMUnavailable
            if isinstance(e, LLMUnavailable):
                print(e)
                return 1
            raise
        return 0
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
    if args.cmd == "eval":
        from .eval import TASKS, run_suite, library_get_ir
        tasks = [t for t in TASKS if t["name"] == args.task] if args.task else TASKS
        summary = run_suite(library_get_ir, tasks)
        for r in summary["results"]:
            tag = "PASS" if r["passed"] else f"FAIL@{r['stage']}"
            print(f"  {r['task']:12} {tag}  {r.get('pass_count','')}/{r.get('total','')}")
        print(f"SUITE: {summary['passed']}/{summary['total']} tasks pass")
        return 0 if summary["passed"] == summary["total"] else 1
    if args.cmd == "solve":
        from .agent import solve, LibraryGenerator
        from .eval import TASKS_BY_NAME
        task = TASKS_BY_NAME.get(args.task)
        if not task:
            print(f"unknown task '{args.task}'; known: {list(TASKS_BY_NAME)}"); return 1
        res = solve(task, LibraryGenerator(), max_iters=args.max_iters, verbose=True)
        print(f"success={res['success']} iterations={res['iterations']}")
        return 0 if res["success"] else 1
    if args.cmd == "create":
        from .chatbot import Chatbot, ChatbotGenerator
        try:
            bot = Chatbot(ChatbotGenerator(), max_iters=args.max_iters)
        except RuntimeError as e:
            print(f"the chatbot needs a model: {e}"); return 1
        res = bot.send(args.intent, verbose=True)
        print("\n" + res["reply"])
        return 0 if res["success"] else 1
    if args.cmd == "reward":
        from .reward import reward
        from .eval import TASKS_BY_NAME, library_get_ir
        task = TASKS_BY_NAME.get(args.task)
        if not task:
            print(f"unknown task '{args.task}'; known: {list(TASKS_BY_NAME)}"); return 1
        _print(reward(library_get_ir(task), task)); return 0
    if args.cmd == "dataset":
        from .dataset import build_dataset
        _print(build_dataset(args.out)); return 0
    if args.cmd == "rawbuild":
        from .raw import build_from_obj
        rep = build_from_obj(_load_ir(args.obj), args.out)
        _print(rep)
        if rep["ok"]:
            print("stdout:", repr(harness.run(rep["path"], stdin=args.stdin)["stdout"]))
        return 0 if rep["ok"] else 1
    return 1


def _chat() -> int:
    from .chatbot import Chatbot, ChatbotGenerator
    try:
        gen = ChatbotGenerator()
    except Exception as e:
        print(e)                      # LLMUnavailable carries a friendly how-to message
        return 1
    bot = Chatbot(gen)
    b = gen.backend
    print(f"Sir Yaps-a-Lot — using {b.name} ({getattr(b, 'model', '?')}).")
    print("Tell me what to build and I'll make you a .exe. (Ctrl-D to quit)")
    while True:
        try:
            msg = input("\nyou> ").strip()
        except EOFError:
            print("\nbye!"); return 0
        if not msg:
            continue
        res = bot.send(msg)
        print("\nbot> " + res["reply"])


if __name__ == "__main__":
    sys.exit(main())
