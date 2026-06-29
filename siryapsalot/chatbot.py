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
    if test.get("expect_screen_contains"):
        if test["expect_screen_contains"] not in run.get("screen", ""):
            return False, (f"the rendered screen does not contain "
                           f"{test['expect_screen_contains']!r}")
    if test.get("expect_dialog_contains"):
        shown = " | ".join(f"{d['caption']}: {d['text']}" for d in run.get("dialogs", []))
        if test["expect_dialog_contains"] not in shown:
            return False, f"no message box containing {test['expect_dialog_contains']!r} (saw: {shown!r})"
    if test.get("expect_window_contains"):
        titles = " | ".join(str(w.get("title", "")) for w in run.get("windows", []))
        if test["expect_window_contains"] not in titles:
            return False, f"no window titled like {test['expect_window_contains']!r} (saw: {titles!r})"
    if test.get("expect_control_contains"):
        labels = " | ".join(f"{c.get('class')}:{c.get('text')}" for c in run.get("controls", []))
        if test["expect_control_contains"] not in labels:
            return False, f"no control labelled {test['expect_control_contains']!r} (saw: {labels!r})"
    if test.get("expect_sound"):
        if not run.get("sounds"):
            return False, "the program did not play any sound (expected a Beep/MessageBeep/PlaySound)"
    return True, ""


class Chatbot:
    """Conversational binary builder. Call .send(message) and get a reply + a built .exe."""

    def __init__(self, generator, max_iters: int = 6, out_dir: str = "build", builder=None):
        # generator: callable(message, feedback, iteration, history) -> spec dict
        #            spec = {program_name, explanation, ir, self_tests:[{stdin, expect_*}]}
        # builder:   callable(program, out_path) -> build report. Default builds IR; pass
        #            siryapsalot.raw.build_from_obj to build from raw machine-code bytes instead
        #            (same self-test + repair loop, the model just emits bytes).
        self.generator = generator
        self.max_iters = max_iters
        self.out_dir = out_dir
        self.builder = builder or harness.build_binary
        self.history: list[dict] = []

    @property
    def mode(self):
        """The persona currently chatting (a modes.Mode), if the generator has one."""
        return getattr(self.generator, "mode", None)

    def switch(self, mode_id):
        """Switch which persona you're chatting with (e.g. 'yapzilla'). Returns the new Mode."""
        from . import modes
        m = modes.get_mode(mode_id)
        if m is not None and hasattr(self.generator, "mode"):
            self.generator.mode = m
        return m

    # --- LLM model / backend switching (orthogonal to the persona) ---------
    @property
    def backend(self):
        return getattr(self.generator, "backend", None)

    def models(self) -> list[str]:
        b = self.backend
        return b.list_models() if b else []

    def set_model(self, model: str) -> str | None:
        b = self.backend
        if b and model:
            b.set_model(model)
            return model
        return None

    def set_backend(self, name: str):
        """Switch the LLM provider (e.g. 'openai'); keeps the same persona."""
        from .llm import make_backend
        b = make_backend(prefer=name)
        if hasattr(self.generator, "backend"):
            self.generator.backend = b
        return b

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

            rep = self.builder(ir, out)
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
        run = runs[0][1]
        lines = [f"Done — I built **{name}.exe**. {expl}"]

        stdout = run["stdout"]
        screen = run.get("screen", "")
        # positioned-drawing programs put the real picture on the screen; prefer the richer view
        nonblank = lambda s: len([ln for ln in s.splitlines() if ln.strip()])
        view = screen if nonblank(screen) > nonblank(stdout) else stdout

        if view.strip():
            shown = view if len(view) < 800 else view[:800] + "…"
            lines.append("\nOutput:\n" + "\n".join("    " + ln for ln in shown.splitlines()))
        elif run.get("windows"):
            w = run["windows"][0]
            lines.append(f"\nIt opens a window titled “{w['title']}” ({w.get('width')}×{w.get('height')}).")
        elif run.get("dialogs"):
            d = run["dialogs"][0]
            lines.append(f"\nIt pops up a message box — [{d['caption']}] {d['text']!r}")

        extras = []
        if run.get("controls"):
            labels = ", ".join(f"[{c.get('text') or c.get('class')}]" for c in run["controls"][:6])
            extras.append(f"controls: {labels}")
        if run.get("sounds"):
            extras.append(f"plays {len(run['sounds'])} sound(s) 🔊")
        if extras:
            lines.append("    (" + "; ".join(extras) + ")")

        lines.append(f"\nIt passed {len(runs)} self-test(s). The binary is at build/{name}.exe.")
        return "\n".join(lines)


class ChatbotGenerator:
    """The live model behind the chatbot — Anthropic API or a local Ollama model.

    Picks a backend automatically (see siryapsalot.llm.make_backend): Anthropic if
    ANTHROPIC_API_KEY is set, otherwise a running/ configured Ollama model. No key required.
    """

    def __init__(self, backend=None, model: str | None = None, mode=None,
                 backend_name: str | None = None):
        from . import modes
        from .agent import generators, prompt
        from .llm import make_backend
        self._gen = generators
        self._prompt = prompt
        self.backend = backend or make_backend(prefer=backend_name)
        if model:
            self.backend.set_model(model)
        self.mode = (modes.get_mode(mode) or modes.MODES[modes.DEFAULT])

    def __call__(self, message, feedback, iteration, history):
        msgs = []
        for turn in history:
            msgs.append({"role": "user", "content": turn["message"]})
            msgs.append({"role": "assistant",
                         "content": f"(built {turn['program_name']}: {turn['explanation']})"})
        user = message if not feedback else f"{message}\n\n[automatic feedback]\n{feedback}"
        msgs.append({"role": "user", "content": user})
        text = self.backend.chat(self._prompt.chatbot_system_prompt(self.mode), msgs)
        return self._gen.extract_json(text)


def chatbot(generator=None, **kw) -> Chatbot:
    """Convenience: a Chatbot backed by the live model unless a generator is given."""
    return Chatbot(generator or ChatbotGenerator(), **kw)
