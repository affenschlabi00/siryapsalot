"""Live build feedback: send() emits progress steps, and the web service runs builds in a
background thread so the UI can poll for what's happening instead of freezing."""
import threading
import time

from siryapsalot import llm
from siryapsalot.chatbot import Chatbot
from siryapsalot.web import ChatService
from conftest import load_example


def _hello_spec(*a):
    return {"kind": "build", "program_name": "hello", "explanation": "prints hello",
            "ir": load_example("hello.ir.json"),
            "self_tests": [{"stdin": "", "expect_contains": "Hello"}]}


def _wait_build(svc, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = svc.build_status()
        if not s["running"] and s["result"]:
            return s
        time.sleep(0.02)
    raise AssertionError("build did not finish")


def test_send_emits_progress_stages(build_dir):
    events = []
    bot = Chatbot(_hello_spec, out_dir=build_dir)
    res = bot.send("make me a hello program", progress=events.append)
    assert res["success"]
    stages = [e["stage"] for e in events]
    for expected in ("thinking", "compiling", "testing", "done"):
        assert expected in stages, (expected, stages)
    assert all(e.get("message") is not None for e in events)


def test_send_emits_repairing_on_self_test_failure(build_dir):
    good = load_example("hello.ir.json")
    specs = [
        {"kind": "build", "program_name": "hello", "explanation": "x", "ir": good,
         "self_tests": [{"stdin": "", "expect_equals": "WRONG"}]},   # fails -> triggers repair
        {"kind": "build", "program_name": "hello", "explanation": "x", "ir": good,
         "self_tests": [{"stdin": "", "expect_contains": "Hello"}]},  # passes
    ]
    events = []
    bot = Chatbot(lambda m, fb, it, h: specs[min(it, 1)], out_dir=build_dir)
    res = bot.send("a hello program", progress=events.append)
    assert res["success"] and res["iterations"] == 2
    assert "repairing" in [e["stage"] for e in events]


def test_start_build_runs_in_background_and_reports_result(build_dir):
    svc = ChatService(bot=Chatbot(_hello_spec, out_dir=build_dir), build_dir=build_dir)
    out = svc.start_build("make me a hello program")
    assert out["started"]
    s = _wait_build(svc)
    assert s["result"]["success"] and s["result"]["download"] == "hello.exe"
    assert any(st["stage"] == "compiling" for st in s["steps"])      # live steps were recorded


def test_start_build_busy_guard(build_dir):
    gate = threading.Event()

    def slow_gen(m, fb, it, h):
        gate.wait(5)
        return _hello_spec()

    svc = ChatService(bot=Chatbot(slow_gen, out_dir=build_dir), build_dir=build_dir)
    assert svc.start_build("make a hello program")["started"]
    second = svc.start_build("make another program")
    assert second["started"] is False and second.get("busy")
    gate.set()
    _wait_build(svc)


def test_start_build_small_talk_returns_chat_quickly(build_dir):
    def boom(*a, **k):
        raise AssertionError("small talk must not call the model")

    svc = ChatService(bot=Chatbot(boom, out_dir=build_dir), build_dir=build_dir)
    svc.start_build("hello")
    s = _wait_build(svc)
    assert s["result"]["success"] and s["result"]["download"] is None   # chat, no binary
    assert s["result"].get("chat") is True


def test_all_backends_and_needs_key():
    assert llm.all_backends() == ["openai", "anthropic", "ollama"]
    assert llm.needs_key("openai") and llm.needs_key("anthropic")
    assert not llm.needs_key("ollama")


def test_make_backend_uses_supplied_key(monkeypatch):
    """A runtime api_key reaches OpenAIBackend without any env var (so the UI key box works)."""
    for k in ("OPENAI_API_KEY", "SIRYAPSALOT_BACKEND"):
        monkeypatch.delenv(k, raising=False)
    b = llm.make_backend("openai", api_key="sk-runtime")
    assert b.name == "openai" and b.api_key == "sk-runtime"
