"""Interactive event layer: the harness dispatches WM_* messages into the guest window-proc,
so click (WM_COMMAND) and paint (WM_PAINT) handlers actually run. This is what turns a static
window into a genuinely interactive GUI app (decision D11)."""
import os

from siryapsalot import harness
from siryapsalot.chatbot import Chatbot, _check
from conftest import load_example


def _run(build_dir, example="click_beeps.ir.json", name="click_beeps"):
    out = os.path.join(build_dir, name + ".exe")
    rep = harness.build_binary(load_example(example), out)
    assert rep["ok"], rep["errors"]
    return harness.run(out)


def test_events_are_dispatched_into_window_proc(build_dir):
    r = _run(build_dir)
    assert not r["crashed"] and not r["truncated"]
    names = [e["message"] for e in r["events"]]
    assert "WM_CREATE" in names
    assert "WM_PAINT" in names
    assert any(n.startswith("WM_COMMAND") for n in names)
    assert "WM_DESTROY" in names
    assert all(e["ok"] for e in r["events"])           # every handler ran without faulting


def test_click_and_paint_handlers_actually_run(build_dir):
    """The proof: `main` makes NO sound; the sounds exist ONLY because the harness dispatched
    WM_PAINT (-> MessageBeep) and WM_COMMAND (-> Beep 880) into the window proc."""
    r = _run(build_dir)
    kinds = {s["type"] for s in r["sounds"]}
    assert "beep" in kinds and "messagebeep" in kinds
    assert any(s.get("freq") == 880 for s in r["sounds"])    # the click handler's distinctive beep


def test_command_carries_the_control_id(build_dir):
    r = _run(build_dir)
    cmd = [e for e in r["events"] if e["message"].startswith("WM_COMMAND")]
    assert cmd and "id=1" in cmd[0]["message"]      # the button's control id reached the handler


def test_expect_event_self_test_passes(build_dir):
    spec = {"program_name": "click_beeps", "explanation": "a clickable, beeping window",
            "ir": load_example("click_beeps.ir.json"),
            "self_tests": [{"stdin": "", "expect_event": "WM_COMMAND", "expect_sound": True}]}
    res = Chatbot(lambda m, fb, it, h: spec, out_dir=build_dir).send("a window with a button that beeps")
    assert res["success"]
    assert "live event" in res["reply"]             # the reply advertises the interactivity


def test_expect_event_fails_for_an_event_with_no_handler(build_dir):
    r = _run(build_dir)
    ok, why = _check({"expect_event": "WM_KEYDOWN"}, r)
    assert not ok and "WM_KEYDOWN" in why


def test_a_faulting_handler_stays_local(build_dir):
    """A buggy click handler must not bring down the whole program: the fault is contained to
    that event (ok=False) while `main` and the other events are unaffected."""
    ir = load_example("click_beeps.ir.json")
    for proc in ir["code"]:
        if proc["label"] == "WndProc":
            proc["instructions"].insert(0, {"op": "xor", "args": ["eax", "eax"]})
            proc["instructions"].insert(1, {"op": "mov", "args": ["rax", "qword ptr [rax]"]})
            break
    out = os.path.join(build_dir, "click_crash.exe")
    rep = harness.build_binary(ir, out)
    assert rep["ok"], rep["errors"]
    r = harness.run(out)
    assert not r["crashed"]                          # main completed; handler faults are contained
    assert r["events"] and any(not e["ok"] for e in r["events"])
    assert any("fault" in e for e in r["events"])    # the fault detail is recorded per-event


def test_window_without_controls_still_dispatches_paint_and_destroy(build_dir):
    """Regression: a plain window (no buttons) gets WM_CREATE/WM_PAINT/WM_DESTROY but no
    WM_COMMAND, and still runs cleanly."""
    r = _run(build_dir, example="hello_window.ir.json", name="hello_window")
    assert not r["crashed"]
    names = [e["message"] for e in r["events"]]
    assert "WM_PAINT" in names and "WM_DESTROY" in names
    assert not any(n.startswith("WM_COMMAND") for n in names)   # no controls -> no click events
