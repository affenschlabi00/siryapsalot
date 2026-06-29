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
            self.mode = modes.get_mode()

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
        assert set(info["backends"]) == {"openai", "anthropic", "ollama"}   # all providers offered
        assert any(m["name"] == "Sir Yaps-a-Lot" for m in info["modes"])
    finally:
        httpd.shutdown()


def test_available_backends_reflects_env(monkeypatch):
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OLLAMA_MODEL", "SIRYAPSALOT_BACKEND"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(llm, "_ollama_reachable", lambda host: False)
    assert llm.available_backends() == []
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    assert "openai" in llm.available_backends()


class _OtherBackend(llm.LLMBackend):
    name = "openai"
    model = "gpt-4o-mini"

    def list_models(self):
        return ["gpt-4o-mini", "gpt-4o", "o4-mini"]

    def chat(self, *a, **k):
        return "{}"


def test_web_set_backend_switches_provider_and_refreshes_models(build_dir, monkeypatch):
    """Picking a provider returns that provider's models — the heart of the per-backend picker."""
    svc = ChatService(bot=Chatbot(_fake_gen()), build_dir=build_dir)
    assert svc._backend_info()["backend"] == "fake"
    monkeypatch.setattr(llm, "make_backend", lambda prefer=None, **kw: _OtherBackend())
    out = svc.set_backend("openai")
    assert out["ok"] and out["backend"] == "openai"
    assert "gpt-4o" in out["models"] and "m1" not in out["models"]   # model list followed the switch


def test_web_set_backend_with_api_key(build_dir, monkeypatch):
    """A key pasted in the UI is threaded through to make_backend (so you can switch w/o env vars)."""
    seen = {}

    def fake_make(prefer=None, api_key=None, model=None, **kw):
        seen["prefer"] = prefer
        seen["api_key"] = api_key
        return _OtherBackend()

    monkeypatch.setattr(llm, "make_backend", fake_make)
    svc = ChatService(bot=Chatbot(_fake_gen()), build_dir=build_dir)
    out = svc.set_backend("openai", api_key="sk-pasted")
    assert out["ok"] and seen == {"prefer": "openai", "api_key": "sk-pasted"}


def test_web_set_backend_failure_reports_needs_key(build_dir, monkeypatch):
    svc = ChatService(bot=Chatbot(_fake_gen()), build_dir=build_dir)

    def boom(prefer=None, **kw):
        raise llm.LLMUnavailable("no Anthropic API key")

    monkeypatch.setattr(llm, "make_backend", boom)
    out = svc.set_backend("anthropic")
    assert out["ok"] is False and out["needs_key"] is True           # UI knows to prompt for a key
    assert svc._backend_info()["backend"] == "fake"                  # unchanged on failure


# --- robustness: a failure in one part of /api/info must never empty the dropdowns ----------
def _raise(exc):
    def _f(*a, **k):
        raise exc
    return _f


def test_info_survives_updater_failure(build_dir, monkeypatch):
    """The empty-dropdown bug: git/updater blowing up used to take down the whole response."""
    svc = ChatService(bot=Chatbot(_fake_gen()), build_dir=build_dir)
    monkeypatch.setattr(updater, "status", _raise(FileNotFoundError("git not found")))
    i = svc.info()
    assert [m["name"] for m in i["modes"]]                          # personas still present
    assert "openai" in i["backends"] and "ollama" in i["backends"]  # providers still offered
    assert i["model"] == "m1"
    assert i["available"] is False                                  # degraded, not crashed


def test_info_survives_backend_listing_failure(build_dir):
    class Boom(llm.LLMBackend):
        name = "openai"
        model = "gpt-4o"

        def list_models(self):
            raise RuntimeError("api down")

        def chat(self, *a, **k):
            return "{}"

    g = _fake_gen()
    g.backend = Boom()
    svc = ChatService(bot=Chatbot(g), build_dir=build_dir)
    i = svc.info()
    assert i["modes"] and "openai" in i["backends"]                 # still usable
    assert i["model"] == "gpt-4o" and i["models"] == []             # model known, list just empty


def test_api_info_handler_fallback_serves_static_modes(build_dir, monkeypatch):
    """Even if info() itself explodes, the HTTP layer still hands the UI personas + providers."""
    svc = ChatService(bot=Chatbot(_fake_gen()), build_dir=build_dir)
    monkeypatch.setattr(svc, "info", _raise(RuntimeError("boom")))
    httpd = HTTPServer(("127.0.0.1", 0), make_handler(svc))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        j = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/info", timeout=5).read())
        assert any(m["name"] == "Sir Yaps-a-Lot" for m in j["modes"])     # dropdowns can populate
        assert "ollama" in j["backends"]
    finally:
        httpd.shutdown()


def test_updater_status_degrades_without_git(monkeypatch):
    monkeypatch.setattr(updater, "available", lambda: True)
    monkeypatch.setattr(subprocess, "run", _raise(FileNotFoundError("git")))
    s = updater.status()
    assert s["available"] is False and "git" in s["reason"].lower()  # no exception escapes
