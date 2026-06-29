"""The web chat GUI: ChatService core + a live server round-trip (no model needed)."""
import json
import threading
import urllib.request
from http.server import HTTPServer

from siryapsalot.chatbot import Chatbot
from siryapsalot.web import ChatService, INDEX_HTML, make_handler
from conftest import load_example


def _fake_bot(build_dir):
    def gen(msg, fb, it, hist):
        return {"program_name": "christmas_tree", "explanation": "a tree",
                "ir": load_example("christmas_tree.ir.json"),
                "self_tests": [{"stdin": "", "expect_contains": "*"}]}
    return Chatbot(gen, out_dir=build_dir)


def test_chatservice_builds_and_offers_download(build_dir):
    svc = ChatService(bot=_fake_bot(build_dir), build_dir=build_dir)
    out = svc.message("make me a christmas tree")
    assert out["success"]
    assert out["download"] == "christmas_tree.exe"
    assert "built" in out["reply"].lower()


def test_index_html_is_a_chat_page():
    assert "<form" in INDEX_HTML and "/api/build" in INDEX_HTML


def test_web_server_roundtrip(build_dir):
    svc = ChatService(bot=_fake_bot(build_dir), build_dir=build_dir)
    httpd = HTTPServer(("127.0.0.1", 0), make_handler(svc))
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        assert b"<form" in urllib.request.urlopen(base + "/", timeout=5).read()

        req = urllib.request.Request(base + "/api/build",
                                     data=json.dumps({"message": "tree"}).encode(),
                                     headers={"Content-Type": "application/json"})
        res = json.loads(urllib.request.urlopen(req, timeout=10).read())
        assert res["success"] and res["download"] == "christmas_tree.exe"

        exe = urllib.request.urlopen(base + "/download/christmas_tree.exe", timeout=5).read()
        assert exe[:2] == b"MZ"            # a real PE was served
    finally:
        httpd.shutdown()
