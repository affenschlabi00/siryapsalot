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


# --- chat vs. build routing -------------------------------------------------------------------
# So a plain "hello" gets a friendly reply instead of kicking off the build+repair loop (which is
# slow and pointless for small talk). Two layers: an instant no-model heuristic for obvious chat,
# and a model-side "kind" the generator can return to chat instead of build.
_GREETING = {"hi", "hello", "hey", "yo", "sup", "hiya", "howdy", "heya", "hello there",
             "hi there", "hey there", "good morning", "good afternoon", "good evening",
             "greetings", "gm", "g'day", "hola", "wassup", "whats up", "what's up", "yo yo"}
_THANKS = {"thanks", "thank you", "thankyou", "thx", "ty", "cheers", "thank u",
           "much appreciated", "appreciate it", "nice", "cool", "awesome", "great", "ok thanks"}
_BYE = {"bye", "goodbye", "see ya", "see you", "cya", "later", "good night", "gn"}
_HELP = {"help", "what can you do", "what do you do", "who are you", "what are you",
         "what is this", "how does this work", "how do you work", "what can i do",
         "what should i do", "what now", "how do i use this", "how do i use you"}
_BUILD_HINT = re.compile(
    r"\b(make|build|created?|write|generate|gimme|give me|code|compile|program|app|exe|"
    r"binary|game|calculator|print|draw|window|button|beep|sound|tetris|tic.?tac|"
    r"fizzbuzz|prime|fibonacci|factorial|sort|hello world)\b")

_GREET_REPLY = ("Hey! 👋 I'm Sir Yaps-a-Lot — I turn plain English into real Windows .exe files. "
                "Tell me what to build, e.g. “make me a calculator”, “primes under "
                "50”, or “a window with a button that beeps”.")
_HELP_REPLY = ("I build working Windows programs from a plain-English description — no specs "
               "needed. I can make console apps and text games (calculator, FizzBuzz, "
               "tic-tac-toe…), positioned/colored console drawings, and GUI apps with "
               "windows, clickable buttons and sound. Just say things like “make me a "
               "guessing game” or “draw a box that says HELLO” and I’ll build, "
               "test, and hand you the .exe. What should I build?")
_NO_MODEL_REPLY = ("I can build plenty right now with no setup — try: a calculator, FizzBuzz, a "
                   "prime checker, Fibonacci, a factorial calculator, a guessing game, "
                   "tic-tac-toe, a Christmas tree, a drawn box, a window, or a clickable beeping "
                   "button. For anything custom, connect an AI model: set OPENAI_API_KEY or "
                   "ANTHROPIC_API_KEY, run a local Ollama model, or paste an API key in the "
                   "provider box.")


def _quick_chat(message: str) -> str | None:
    """Instant, no-model reply for obvious small talk so a greeting never starts a build."""
    norm = re.sub(r"[\s!?.,'’\"]+", " ", str(message).lower()).strip()
    if not norm or _BUILD_HINT.search(norm):
        return None
    words = norm.split()
    if len(words) > 6:                       # longer messages are probably real requests
        return None
    if norm in _GREETING or (len(words) <= 2 and words[0] in
                             {"hi", "hello", "hey", "yo", "sup", "hiya", "howdy", "heya"}):
        return _GREET_REPLY
    if norm in _THANKS:
        return "You're welcome! 🙂 Want me to build something else?"
    if norm in _BYE:
        return "See you! 👋"
    if norm in _HELP or norm.startswith(("what can you", "what do you", "who are you",
                                         "what are you", "how does this", "how do you")):
        return _HELP_REPLY
    return None


def _is_chat_spec(spec) -> bool:
    """Did the model choose to chat rather than build? (kind=='chat', or a reply with no IR.)"""
    if not isinstance(spec, dict):
        return False
    kind = str(spec.get("kind", "")).lower()
    if kind == "chat":
        return True
    if kind == "build":
        return False
    return ("reply" in spec) and not ("ir" in spec or "code" in spec)


def _emit(progress, stage: str, message: str, **extra):
    """Report a live build step (a greeting/compile/test/repair). Best-effort; never raises."""
    if progress:
        try:
            progress({"stage": stage, "message": message, **extra})
        except Exception:
            pass


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
    if test.get("expect_event"):
        want = test["expect_event"]
        fired = [e for e in run.get("events", [])
                 if want in str(e.get("message", "")) and e.get("ok")]
        if not fired:
            seen = " | ".join(f"{e.get('message')}{'' if e.get('ok') else ' (faulted)'}"
                              for e in run.get("events", [])) or "none"
            return False, (f"the window-proc handler for {want!r} did not fire cleanly "
                           f"(events dispatched: {seen})")
    return True, ""


class Chatbot:
    """Conversational binary builder. Call .send(message) and get a reply + a built .exe."""

    def __init__(self, generator=None, max_iters: int = 8, out_dir: str = "build", builder=None,
                 prefer_recipes: bool = True):
        # generator: callable(message, feedback, iteration, history) -> spec dict, or None to run
        #            recipe-only (common programs still build without any model).
        # builder:   callable(program, out_path) -> build report. Default builds IR; pass
        #            siryapsalot.raw.build_from_obj to build from raw machine-code bytes instead.
        # prefer_recipes: try a verified recipe before the model (reliable fast path).
        self.generator = generator
        self.max_iters = max_iters
        self.out_dir = out_dir
        self.builder = builder or harness.build_binary
        self.prefer_recipes = prefer_recipes
        self.history: list[dict] = []

    @property
    def mode(self):
        """The builder identity — always Sir Yaps-a-Lot (kept as a property for callers)."""
        m = getattr(self.generator, "mode", None)
        if m is not None:
            return m
        from . import modes
        return modes.get_mode()

    def switch(self, mode_id):
        """No-op kept for compatibility: there is one identity now. Returns it."""
        from . import modes
        return modes.get_mode()

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

    def set_backend(self, name: str, api_key: str | None = None, model: str | None = None):
        """Switch the LLM provider. An api_key/model can be supplied at runtime (e.g. pasted in the
        UI) instead of relying on env vars. If there was no model yet, this connects one."""
        from .llm import make_backend
        b = make_backend(prefer=name, api_key=api_key, model=model)
        if self.generator is None:
            self.generator = ChatbotGenerator(backend=b)
        elif hasattr(self.generator, "backend"):
            self.generator.backend = b
        return b

    def _build_recipe(self, rec: dict, message: str, progress=None) -> dict | None:
        """Build a verified recipe (guaranteed-good IR). Returns a result dict, or None if it
        somehow doesn't pass (then send() falls through to the model)."""
        name, ir = rec["name"], rec["ir"]
        out = os.path.join(self.out_dir, f"{name}.exe")
        _emit(progress, "compiling", f"Building {name}.exe (a ready-made, tested version)…")
        rep = self.builder(ir, out)
        if not rep["ok"] or not harness.validate_pe(out)["ok"]:
            return None
        tests = rec.get("self_tests") or [{"stdin": ""}]
        _emit(progress, "testing", f"Running {len(tests)} self-test(s)…")
        runs = []
        for t in tests:
            r = harness.run(out, stdin=t.get("stdin", ""))
            runs.append((t, r))
            ok, _why = _check(t, r)
            if not ok:
                return None
        spec = {"program_name": name, "explanation": rec["explanation"]}
        self.history.append({"message": message, "program_name": name,
                             "explanation": rec["explanation"], "ir": ir})
        _emit(progress, "done", f"Done — built {name}.exe ✅")
        return {"success": True, "reply": self._success_reply(spec, runs), "path": out, "ir": ir,
                "explanation": rec["explanation"], "outputs": [r["stdout"] for _, r in runs],
                "iterations": 1, "recipe": True}

    def send(self, message: str, verbose: bool = False, progress=None) -> dict:
        """Build (or chat) in response to a message. `progress` is an optional callback that
        receives live step dicts ({stage, message, ...}) so a UI can show what's happening."""
        os.makedirs(self.out_dir, exist_ok=True)

        # Small talk: reply instantly without touching the model or the build pipeline.
        quick = _quick_chat(message)
        if quick is not None:
            self.history.append({"message": message, "reply": quick, "chat": True})
            return {"success": True, "reply": quick, "path": None, "ir": None,
                    "chat": True, "iterations": 0}

        # Reliable fast path: a verified recipe for a common request always builds & passes —
        # so common asks "just work" regardless of how much the model struggles (or if there's no
        # model at all).
        if self.prefer_recipes:
            from . import recipes
            rec = recipes.find(message)
            if rec is not None:
                out = self._build_recipe(rec, message, progress)
                if out is not None:
                    return out

        # No model connected: recipes + chat still work; for anything custom, ask for a provider.
        if self.generator is None:
            _emit(progress, "done", "")
            return {"success": False, "reply": _NO_MODEL_REPLY, "path": None, "ir": None,
                    "chat": True, "iterations": 0}

        feedback = None
        spec = {}
        for it in range(self.max_iters):
            _emit(progress, "thinking",
                  "Thinking…" if it == 0 else f"Rethinking (attempt {it + 1}/{self.max_iters})…",
                  iter=it, max=self.max_iters)
            spec = self.generator(message, feedback, it, self.history)

            # The model can also choose to chat instead of build (kind=="chat"); honor it.
            if feedback is None and _is_chat_spec(spec):
                reply = str(spec.get("reply") or "").strip() or _GREET_REPLY
                self.history.append({"message": message, "reply": reply, "chat": True})
                _emit(progress, "done", "")
                return {"success": True, "reply": reply, "path": None, "ir": None,
                        "chat": True, "iterations": it + 1}

            ir = spec.get("ir", spec)  # tolerate a bare IR
            name = spec.get("program_name") or _slug(message)
            tests = spec.get("self_tests") or [{"stdin": ""}]
            out = os.path.join(self.out_dir, f"{name}.exe")

            _emit(progress, "compiling", f"Compiling {name}.exe…", iter=it, name=name)
            rep = self.builder(ir, out)
            if not rep["ok"]:
                feedback = fb.from_build(rep)
                _emit(progress, "repairing", "Build failed — reading the errors and fixing…",
                      iter=it)
                if verbose:
                    print(f"  iter {it}: build failed")
                continue
            vp = harness.validate_pe(out)
            if not vp["ok"]:
                feedback = fb.from_validate(vp)
                _emit(progress, "repairing", "The binary didn't validate — fixing…", iter=it)
                continue

            _emit(progress, "testing", f"Running {len(tests)} self-test(s)…", iter=it)
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
                _emit(progress, "done", f"Done — built {name}.exe ✅", iter=it, name=name)
                return {"success": True, "reply": reply, "path": out, "ir": ir,
                        "explanation": spec.get("explanation", ""), "outputs": outputs,
                        "iterations": it + 1}

            t, r, why = failing
            feedback = self._test_feedback(t, r, why, out)
            _emit(progress, "repairing", f"Self-test failed ({why}) — fixing…", iter=it, why=why)
            if verbose:
                print(f"  iter {it}: self-test failed — {why}")

        _emit(progress, "failed", "Couldn't get it working within a few attempts.")
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
        live = [e for e in run.get("events", [])
                if e.get("ok") and ("WM_COMMAND" in str(e.get("message", ""))
                                    or "WM_PAINT" in str(e.get("message", "")))]
        if live:
            extras.append(f"reacts to {len(live)} live event(s) 🖱️")
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
            if turn.get("chat"):
                msgs.append({"role": "assistant", "content": turn.get("reply", "")})
            else:
                msgs.append({"role": "assistant",
                             "content": f"(built {turn['program_name']}: {turn['explanation']})"})
        user = message if not feedback else f"{message}\n\n[automatic feedback]\n{feedback}"
        msgs.append({"role": "user", "content": user})
        text = self.backend.chat(self._prompt.chatbot_system_prompt(self.mode), msgs)
        return self._gen.extract_json(text)


def chatbot(generator=None, **kw) -> Chatbot:
    """Convenience: a Chatbot backed by the live model unless a generator is given."""
    return Chatbot(generator or ChatbotGenerator(), **kw)
