"""The web chat GUI: ChatService core + a live server round-trip (no model needed)."""
import json
import threading
import time
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


def test_index_html_js_string_literals_are_single_line():
    """Regression: a raw newline inside a ' or " JS string literal (e.g. writing join('\\n') in
    the Python source, where \\n becomes a real newline) breaks the ENTIRE <script>, so no handler
    binds and every dropdown stays empty. Scan the served JS (skipping // and /* */ comments) and
    fail on any such literal."""
    import re
    js = re.search(r"<script>(.*)</script>", INDEX_HTML, re.S).group(1)
    i, n, quote, line = 0, len(js), None, 1
    while i < n:
        ch = js[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            elif ch == "\n" and quote in ("'", '"'):
                raise AssertionError(f"unterminated {quote!r} string literal at <script> line {line}"
                                     " — a raw newline leaked into a JS string (use \\\\n in the "
                                     "Python source).")
            if ch == "\n":
                line += 1
            i += 1
            continue
        if ch == "/" and i + 1 < n and js[i + 1] == "/":            # // line comment
            while i < n and js[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and js[i + 1] == "*":            # /* block comment */
            i += 2
            while i + 1 < n and not (js[i] == "*" and js[i + 1] == "/"):
                if js[i] == "\n":
                    line += 1
                i += 1
            i += 2
            continue
        if ch in ("'", '"', "`"):
            quote = ch
        if ch == "\n":
            line += 1
        i += 1


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
        started = json.loads(urllib.request.urlopen(req, timeout=10).read())
        assert started["started"]                       # build runs in the background

        res = None
        for _ in range(200):                            # poll the live-progress endpoint
            s = json.loads(urllib.request.urlopen(base + "/api/build/status", timeout=5).read())
            if s["result"]:
                res = s["result"]
                break
            time.sleep(0.05)
        assert res and res["success"] and res["download"] == "christmas_tree.exe"

        exe = urllib.request.urlopen(base + "/download/christmas_tree.exe", timeout=5).read()
        assert exe[:2] == b"MZ"            # a real PE was served
    finally:
        httpd.shutdown()
