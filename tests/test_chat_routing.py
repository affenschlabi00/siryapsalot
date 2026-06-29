"""Chat vs. build routing: small talk gets a friendly reply, not a hung .exe build."""
import os

from siryapsalot.chatbot import Chatbot, _is_chat_spec, _quick_chat
from siryapsalot.web import ChatService
from conftest import load_example


def _spec(example="hello.ir.json", tests=None):
    return {"kind": "build", "program_name": example.replace(".ir.json", ""),
            "explanation": "a program", "ir": load_example(example),
            "self_tests": tests or [{"stdin": "", "expect_contains": "Hello"}]}


def test_quick_chat_catches_small_talk():
    for greeting in ["hello", "hi", "Hey!", "HELLO", "  hi  ", "hello there", "yo",
                     "thanks", "thank you", "what can you do?", "help", "who are you"]:
        assert _quick_chat(greeting) is not None, greeting


def test_quick_chat_ignores_build_requests():
    for req in ["make me a calculator", "primes under 50", "draw a box", "tetris",
                "build a window with a button", "fibonacci numbers", "echo my input",
                "write hello world"]:
        assert _quick_chat(req) is None, req


def test_greeting_does_not_invoke_the_model_or_build(build_dir):
    """The reported bug: 'hello' should NOT start the build pipeline (which hangs)."""
    def boom(*a, **k):
        raise AssertionError("the generator/model must not be called for small talk")

    bot = Chatbot(boom, out_dir=build_dir)
    res = bot.send("hello")
    assert res["success"] and res["chat"] and res["path"] is None
    assert res["iterations"] == 0                      # no model round-trips at all
    assert "build" in res["reply"].lower()


def test_build_request_still_builds(build_dir):
    calls = {"n": 0}

    def gen(m, fb, it, hist):
        calls["n"] += 1
        return _spec()

    bot = Chatbot(gen, out_dir=build_dir)
    res = bot.send("make me a hello world program")
    assert res["success"] and not res.get("chat")
    assert res["path"] and os.path.exists(res["path"]) and calls["n"] >= 1


def test_model_can_choose_to_chat(build_dir):
    """A non-heuristic message the model deems conversational returns kind='chat', no build."""
    def gen(m, fb, it, hist):
        return {"kind": "chat", "reply": "I'm Sir Yaps-a-Lot — I build Windows .exes for you!"}

    bot = Chatbot(gen, out_dir=build_dir)
    res = bot.send("are you a real person")            # not caught by the heuristic
    assert res["success"] and res["chat"] and res["path"] is None
    assert "Sir Yaps" in res["reply"]


def test_model_kind_build_routes_to_pipeline(build_dir):
    def gen(m, fb, it, hist):
        return _spec()

    bot = Chatbot(gen, out_dir=build_dir)
    res = bot.send("i would like a greeting program")  # 'program' -> not small talk
    assert res["success"] and not res.get("chat") and res["path"]


def test_is_chat_spec():
    assert _is_chat_spec({"kind": "chat", "reply": "hi"})
    assert _is_chat_spec({"reply": "hi"})                       # reply, no IR
    assert not _is_chat_spec({"kind": "build", "ir": {}})
    assert not _is_chat_spec({"program_name": "x", "ir": {}})   # legacy build spec (no kind)
    assert not _is_chat_spec({"ir": {}, "reply": "x"})          # has IR -> build wins
    assert not _is_chat_spec("nope")


def test_chat_turn_recorded_in_history(build_dir):
    bot = Chatbot(lambda *a: _spec(), out_dir=build_dir)
    bot.send("hello")
    assert bot.history and bot.history[-1]["chat"] and bot.history[-1]["message"] == "hello"


def test_web_small_talk_does_not_build(build_dir):
    calls = {"n": 0}

    def gen(m, fb, it, hist):
        calls["n"] += 1
        return _spec()

    svc = ChatService(bot=Chatbot(gen, out_dir=build_dir), build_dir=build_dir)
    out = svc.message("hello")
    assert out["success"] and out["download"] is None and calls["n"] == 0
    # a real request through the same service still builds
    out2 = svc.message("make me a hello program")
    assert out2["success"] and out2["download"] and calls["n"] >= 1
