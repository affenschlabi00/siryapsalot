"""A chatbot that builds Windows binaries. You talk, it ships .exe files.

No flags, no specs, no oracle from the user. The model turns a plain-English message into a
self-contained spec (IR + its own self-tests + an explanation); the harness builds it, runs the
model's self-tests, and on any failure feeds the crash/diff back so the model repairs — looping
until it works. The user only ever sends messages and gets back a binary and a friendly reply.
"""
from __future__ import annotations

import os
import re

from . import harness
from .agent import feedback as fb


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:28] or "program"


def _check(test: dict, run: dict) -> tuple[bool, str]:
    """Did this self-test pass? Returns (ok, reason-if-not)."""
    if run["crashed"]:
        return False, "the program crashed"
    if run["truncated"]:
        return False, "the program ran too long (likely an infinite loop)"
    out = run["stdout"]
    if "expect_equals" in test and test["expect_equals"] is not None:
        if out != test["expect_equals"]:
            return False, f"expected output {test['expect_equals']!r} but got {out!r}"
    if test.get("expect_contains"):
        if test["expect_contains"] not in out:
            return False, f"output {out!r} does not contain {test['expect_contains']!r}"
    return True, ""


class Chatbot:
    """Conversational binary builder. Call .send(message) and get a reply + a built .exe."""

    def __init__(self, generator, max_iters: int = 6, out_dir: str = "build"):
        # generator: callable(message, feedback, iteration, history) -> spec dict
        #            spec = {program_name, explanation, ir, self_tests:[{stdin, expect_*}]}
        self.generator = generator
        self.max_iters = max_iters
        self.out_dir = out_dir
        self.history: list[dict] = []

    def send(self, message: str, verbose: bool = False) -> dict:
        os.makedirs(self.out_dir, exist_ok=True)
        feedback = None
        spec = {}
        for it in range(self.max_iters):
            spec = self.generator(message, feedback, it, self.history)
            ir = spec.get("ir", spec)  # tolerate a bare IR
            name = spec.get("program_name") or _slug(message)
            tests = spec.get("self_tests") or [{"stdin": ""}]
            out = os.path.join(self.out_dir, f"{name}.exe")

            rep = harness.build_binary(ir, out)
            if not rep["ok"]:
                feedback = fb.from_build(rep)
                if verbose:
                    print(f"  iter {it}: build failed")
                continue
            vp = harness.validate_pe(out)
            if not vp["ok"]:
                feedback = fb.from_validate(vp)
                continue

            runs, failing = [], None
            for t in tests:
                r = harness.run(out, stdin=t.get("stdin", ""))
                runs.append((t, r))
                ok, why = _check(t, r)
                if not ok and failing is None:
                    failing = (t, r, why)

            if failing is None:
                outputs = [r["stdout"] for _, r in runs]
                reply = self._success_reply(spec, runs)
                self.history.append({"message": message, "program_name": name,
                                     "explanation": spec.get("explanation", ""), "ir": ir})
                return {"success": True, "reply": reply, "path": out, "ir": ir,
                        "explanation": spec.get("explanation", ""), "outputs": outputs,
                        "iterations": it + 1}

            t, r, why = failing
            feedback = self._test_feedback(t, r, why, out)
            if verbose:
                print(f"  iter {it}: self-test failed — {why}")

        return {"success": False,
                "reply": ("I couldn't get this one working within a few attempts. Could you "
                          "rephrase or simplify the request a little?"),
                "path": None, "ir": spec.get("ir"), "iterations": self.max_iters}

    # --- feedback & replies ------------------------------------------------
    def _test_feedback(self, test, run, why, path) -> str:
        if run["crashed"]:
            ca = harness.crash_analysis(path, stdin=test.get("stdin", ""))
            return (f"Your program failed self-test (stdin={test.get('stdin','')!r}): it CRASHED "
                    f"— {ca['reason']} at {ca['fault_addr']} ({ca['fault_instruction']['mnemonic']} "
                    f"{ca['fault_instruction']['operands']}). Likely cause: {ca['likely_cause']}. "
                    f"Return a corrected IR (same JSON shape).")
        return (f"Your program failed its own self-test (stdin={test.get('stdin','')!r}): {why}. "
                f"Fix the IR and return the same JSON shape.")

    def _success_reply(self, spec, runs) -> str:
        expl = spec.get("explanation") or "your program"
        name = spec.get("program_name", "program")
        sample = runs[0][1]["stdout"]
        shown = sample if len(sample) < 400 else sample[:400] + "…"
        lines = [f"Done — I built **{name}.exe**. {expl}"]
        if shown.strip():
            lines.append("\nSample run:\n" + "\n".join("    " + ln for ln in shown.splitlines()))
        lines.append(f"\nIt passed {len(runs)} self-test(s). The binary is at build/{name}.exe.")
        return "\n".join(lines)


class ChatbotGenerator:
    """The live model behind the chatbot (needs the anthropic SDK + ANTHROPIC_API_KEY)."""

    def __init__(self, model: str | None = None, max_tokens: int = 8192):
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError("the chatbot needs the anthropic SDK: pip install anthropic") from e
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set — needed for the live chatbot.")
        from .agent import generators, prompt
        self._gen = generators
        self._prompt = prompt
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("BYTEWRIGHT_MODEL", "claude-sonnet-4-6")
        self.max_tokens = max_tokens

    def __call__(self, message, feedback, iteration, history):
        msgs = []
        for turn in history:
            msgs.append({"role": "user", "content": turn["message"]})
            msgs.append({"role": "assistant",
                         "content": f"(built {turn['program_name']}: {turn['explanation']})"})
        user = message if not feedback else f"{message}\n\n[automatic feedback]\n{feedback}"
        msgs.append({"role": "user", "content": user})
        resp = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, temperature=0.0,
            system=self._prompt.chatbot_system_prompt(), messages=msgs)
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        return self._gen.extract_json(text)


def chatbot(generator=None, **kw) -> Chatbot:
    """Convenience: a Chatbot backed by the live model unless a generator is given."""
    return Chatbot(generator or ChatbotGenerator(), **kw)
