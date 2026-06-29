"""OpenAI/ChatGPT backend, runtime model switching, and the git self-updater."""
import json
import subprocess
import threading
import urllib.request
from http.server import HTTPServer

import pytest

from siryapsalot import llm, modes, updater
from siryapsalot.chatbot import Chatbot
from siryapsalot.web import ChatService, make_handler
from conftest import load_example


def test_openai_backend_chat_and_models(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    captured = {}

    def fake(url, payload=None, headers=None, timeout=600):
        captured["url"] = url; captured["payload"] = payload; captured["headers"] = headers
        if url.endswith("/models"):
            return {"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}, {"id": "whisper-1"}]}
        return {"choices": [{"message": {"content": '{"ok": 1}'}}]}

    monkeypatch.setattr(llm, "_http_json", fake)
    b = llm.make_backend("openai")
    assert b.name == "openai"
    ms = b.list_models()
    assert "gpt-4o" in ms and "whisper-1" not in ms       # filtered to chat models
    b.set_model("gpt-4o")
    out = b.chat("reply in json please", [{"role": "user", "content": "hi"}])
    assert out == '{"ok": 1}'
    assert captured["payload"]["model"] == "gpt-4o"
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert captured["headers"]["Authorization"] == "Bearer sk-test"


def test_make_backend_unknown_raises():
    with pytest.raises(llm.LLMUnavailable):
        llm.make_backend("gemini")


class _FakeBackend(llm.LLMBackend):
    name = "fake"
    model = "m1"

    def list_models(self):
        return ["m1", "m2"]

    def chat(self, *a, **k):
        return "{}"


def _fake_gen(spec=None):
    class G:
        def __init__(self):
            self.backend = _FakeBackend()
            self.mode = modes.MODES["classic"]

        def __call__(self, *a):
            return spec or {}
    return G()


def test_chatbot_lists_and_switches_model():
    bot = Chatbot(_fake_gen())
    assert bot.models() == ["m1", "m2"]
    assert bot.set_model("m2") == "m2"
    assert bot.backend.model == "m2"


def test_updater_is_available_in_this_repo():
    assert updater.available() is True
    assert updater.current_branch()                      # read-only, no network
    assert updater.current_commit()


def test_updater_update_logic(monkeypatch):
    calls = []

    def fake_git(*args, timeout=120):
        calls.append(args)
        cp = subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[:2] == ("rev-parse", "--abbrev-ref"):
            cp.stdout = "main\n"
        elif args[:2] == ("rev-parse", "--short"):
            cp.stdout = "abc1234\n"
        elif args[0] == "pull":
            cp.stdout = "Already up to date.\n"
        return cp

    monkeypatch.setattr(updater, "available", lambda: True)
    monkeypatch.setattr(updater, "_git", fake_git)
    res = updater.update()
    assert res["ok"] and res["branch"] == "main" and res["commit"] == "abc1234"
    assert ("fetch", "origin") in calls and any(a[0] == "pull" for a in calls)


def test_updater_update_switches_branch(monkeypatch):
    seen = {"checkout": None, "branch": "main"}

    def fake_git(*args, timeout=120):
        cp = subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[:2] == ("rev-parse", "--abbrev-ref"):
            cp.stdout = seen["branch"] + "\n"
        elif args[:2] == ("rev-parse", "--short"):
            cp.stdout = "deadbee\n"
        elif args[0] == "checkout":
            seen["checkout"] = args[1]; seen["branch"] = args[1]
        return cp

    monkeypatch.setattr(updater, "available", lambda: True)
    monkeypatch.setattr(updater, "_git", fake_git)
    res = updater.update(branch="dev")
    assert seen["checkout"] == "dev" and res["branch"] == "dev"


def test_web_info_reports_backend_and_models(build_dir):
    svc = ChatService(bot=Chatbot(_fake_gen({"program_name": "hello", "explanation": "x",
                                             "ir": load_example("hello.ir.json"),
                                             "self_tests": [{"stdin": "", "expect_contains": "Hello"}]}),
                                  out_dir=build_dir), build_dir=build_dir)
    httpd = HTTPServer(("127.0.0.1", 0), make_handler(svc))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        info = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/info", timeout=5).read())
        assert info["backend"] == "fake"
        assert "m1" in info["models"]
        assert any(m["name"] == "Yapzilla" for m in info["modes"])
    finally:
        httpd.shutdown()
