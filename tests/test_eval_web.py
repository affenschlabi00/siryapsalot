"""Model eval in the web GUI: benchmark the selected model on the oracle-verified task suite.

The live path drives a model; here we stand in the offline LibraryGenerator (returns the
known-good reference IR) so the whole pipeline — start, background thread, solve loop, oracle
scoring, live status — runs deterministically with no API key."""
import json
import threading
import time
import urllib.request
from http.server import HTTPServer

from siryapsalot import llm
from siryapsalot.agent import LibraryGenerator
from siryapsalot.chatbot import Chatbot
from siryapsalot.web import ChatService, make_handler, INDEX_HTML


class _Backend(llm.LLMBackend):
    name = "fake"
    model = "m1"

    def chat(self, *a, **k):
        return "{}"


def _bot(build_dir):
    class G:
        def __init__(self):
            self.backend = _Backend()

        def __call__(self, *a):
            return {}
    return Chatbot(G(), out_dir=build_dir)


def _wait_done(svc, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = svc.eval_status()
        if not s["running"] and (s["summary"] or s["error"]):
            return s
        time.sleep(0.05)
    raise AssertionError("eval did not finish in time")


def test_eval_status_starts_idle(build_dir):
    svc = ChatService(bot=_bot(build_dir), build_dir=build_dir)
    s = svc.eval_status()
    assert s["running"] is False and s["total"] == 0 and s["results"] == []


def test_eval_tasks_preview(build_dir):
    svc = ChatService(bot=_bot(build_dir), build_dir=build_dir)
    tasks = svc.eval_tasks()
    assert any(t["name"] == "hello" for t in tasks)
    assert all("intent" in t for t in tasks)


def test_eval_reference_generator_scores_all_tasks(build_dir):
    """A correct model (reference IR) should score 1.0 — every task passes its oracle."""
    svc = ChatService(bot=_bot(build_dir), build_dir=build_dir)
    out = svc.start_eval(generator=LibraryGenerator(),
                         task_names=["hello", "count", "factorial"], max_iters=2)
    assert out["started"] and out["total"] == 3
    s = _wait_done(svc)
    assert s["summary"] == {"passed": 3, "total": 3, "score": 1.0}
    assert all(r["passed"] for r in s["results"])
    assert {r["task"] for r in s["results"]} == {"hello", "count", "factorial"}
    # per-task detail the UI renders
    hello = next(r for r in s["results"] if r["task"] == "hello")
    assert hello["cases"][0] == hello["cases"][1] and hello["iterations"] == 1


def test_eval_reports_failures_without_crashing(build_dir):
    """A model that emits broken IR scores 0 but the eval still completes and reports a stage."""
    class BadGen:
        def __call__(self, task, feedback=None, iteration=0):
            return {"metadata": {"name": "x", "entry": "main"}, "imports": [], "data": [],
                    "code": [{"label": "main", "instructions": [{"op": "ret", "args": []}]}]}
    svc = ChatService(bot=_bot(build_dir), build_dir=build_dir)
    out = svc.start_eval(generator=BadGen(), task_names=["hello", "count"], max_iters=1)
    assert out["started"]
    s = _wait_done(svc)
    assert s["summary"]["passed"] == 0 and s["summary"]["total"] == 2
    assert all(not r["passed"] and r["stage"] for r in s["results"])


def test_eval_busy_guard(build_dir):
    """A second eval cannot start while one is running."""
    gate = threading.Event()

    class Slow(LibraryGenerator):
        def __call__(self, task, feedback=None, iteration=0):
            gate.wait(5)
            return super().__call__(task, feedback, iteration)

    svc = ChatService(bot=_bot(build_dir), build_dir=build_dir)
    first = svc.start_eval(generator=Slow(), task_names=["hello"], max_iters=1)
    assert first["started"]
    second = svc.start_eval(generator=LibraryGenerator(), task_names=["count"])
    assert second["started"] is False and second.get("busy")
    gate.set()
    _wait_done(svc)


def test_eval_http_roundtrip(build_dir, monkeypatch):
    """POST /api/eval starts it; GET /api/eval/status streams progress to completion."""
    import siryapsalot.agent as agent

    class RefGen:                                  # what LLMGenerator would be, but offline
        def __init__(self, backend=None, **kw):
            self._lib = LibraryGenerator()

        def __call__(self, task, feedback=None, iteration=0):
            return self._lib(task, feedback, iteration)

    monkeypatch.setattr(agent, "LLMGenerator", RefGen)
    svc = ChatService(bot=_bot(build_dir), build_dir=build_dir)
    httpd = HTTPServer(("127.0.0.1", 0), make_handler(svc))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{port}"
        tasks = json.loads(urllib.request.urlopen(base + "/api/eval/tasks", timeout=5).read())["tasks"]
        assert any(t["name"] == "hello" for t in tasks)

        req = urllib.request.Request(
            base + "/api/eval",
            data=json.dumps({"tasks": ["hello", "count"], "max_iters": 2}).encode(),
            headers={"Content-Type": "application/json"})
        started = json.loads(urllib.request.urlopen(req, timeout=5).read())
        assert started["started"] and started["total"] == 2 and started["model"] == "m1"

        s = {}
        for _ in range(400):
            s = json.loads(urllib.request.urlopen(base + "/api/eval/status", timeout=5).read())
            if not s["running"] and s["summary"]:
                break
            time.sleep(0.05)
        assert s["summary"]["passed"] == 2 and s["summary"]["score"] == 1.0
    finally:
        httpd.shutdown()


def test_index_html_has_eval_button():
    assert 'id="evalbtn"' in INDEX_HTML and "/api/eval" in INDEX_HTML
