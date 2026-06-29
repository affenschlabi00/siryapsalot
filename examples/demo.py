#!/usr/bin/env python3
"""End-to-end demonstration of Sir Yaps-a-Lot (bytewright).

Run:  python examples/demo.py
Shows: IR -> deterministic backend -> real PE -> emulated harness, then the agent's
self-repair loop, then the eval suite — the full Phase 0-3 story.
"""
import json
import os

from bytewright import harness
from bytewright.agent import (CallableGenerator, ScriptedGenerator, break_factorial_digit,
                              build_from_intent, make_buggy, solve)
from bytewright.eval import TASKS_BY_NAME, library_get_ir, run_suite

HERE = os.path.dirname(__file__)


def rule(title):
    print(f"\n{'=' * 72}\n  {title}\n{'=' * 72}")


def main():
    rule("1. Compile machine-level IR -> a real Windows PE")
    ir = json.load(open(os.path.join(HERE, "hello.ir.json")))
    rep = harness.build_binary(ir, "build/hello.exe")
    print(f"   built {rep['path']}  ({rep['stats']['file_size']} bytes, "
          f"{rep['stats']['code_size']} bytes of code, {rep['stats']['num_imports']} imports)")

    rule("2. Independently validate the binary (LIEF) — will the loader accept it?")
    vp = harness.validate_pe("build/hello.exe")
    print(f"   ok={vp['ok']}  magic={vp['headers']['magic']}  entry={vp['entry_point']}")
    print(f"   sections: " + ", ".join(f"{s['name']}({s['flags']})" for s in vp["sections"]))

    rule("3. Run it in the emulated, sandboxed Windows harness")
    r = harness.run("build/hello.exe")
    print(f"   stdout: {r['stdout']!r}\n   exit_code={r['exit_code']}  crashed={r['crashed']}")

    rule("4. Trace it — the deterministic execution movie (API calls intercepted)")
    t = harness.trace("build/hello.exe")
    for s in t["steps"]:
        if s["api_call"]:
            print(f"   step {s['idx']:>2}: {s['mnemonic']:5} -> "
                  f"{s['api_call']['name']}(args[0]={s['api_call']['args'][0]}) = {s['api_call']['ret']:#x}")
    print(f"   ended: {t['summary']['ended']}")

    rule("5. THE HEADLINE: describe a program in plain English -> get a working .exe")
    # In production this generator is a live model (bytewright create / chat, with
    # ANTHROPIC_API_KEY). Here a CallableGenerator stands in, mapping the request to IR.
    gen = CallableGenerator(lambda intent, fb, it:
                            json.load(open(os.path.join(HERE, "fibonacci.ir.json"))))
    print("   USER: \"print the fibonacci numbers below 100, one per line\"")
    res = build_from_intent("print the fibonacci numbers below 100, one per line",
                            gen, verbose=False)
    print(f"   -> built {res['path']} (success={res['success']})")
    print("   -> program output:")
    print("      " + res["outputs"][0].replace("\n", " ").strip())

    rule("6. Agent self-repair loop: a buggy factorial is diagnosed and fixed")
    task = TASKS_BY_NAME["factorial"]
    buggy = make_buggy(task["solution"], break_factorial_digit)
    fixed = json.load(open(task["solution"]))
    res = solve(task, ScriptedGenerator([buggy, fixed]), max_iters=4, verbose=True)
    print(f"   -> success={res['success']} after {res['iterations']} iteration(s)")

    rule("7. Eval suite (intent -> correct .exe, verified against oracles)")
    summary = run_suite(library_get_ir)
    for x in summary["results"]:
        print(f"   {x['task']:12} {'PASS' if x['passed'] else 'FAIL'} "
              f"({x.get('pass_count','?')}/{x.get('total','?')} cases)")
    print(f"\n   SUITE: {summary['passed']}/{summary['total']} tasks pass")
    print("\nDone. No C, no Rust, no high-level source anywhere in the pipeline.")


if __name__ == "__main__":
    main()
