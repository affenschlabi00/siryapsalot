"""Phase 6: GUI binaries (MessageBoxA) and the virtual console (positioned drawing)."""
import os

from bytewright import harness
from bytewright.chatbot import Chatbot
from conftest import load_example


def test_gui_messagebox(build_dir):
    out = os.path.join(build_dir, "hello_gui.exe")
    rep = harness.build_binary(load_example("hello_gui.ir.json"), out)
    assert rep["ok"], rep["errors"]
    vp = harness.validate_pe(out)
    assert vp["headers"]["subsystem"] == "gui"
    assert any(i["dll"] == "user32.dll" for i in vp["imports"])
    r = harness.run(out)
    assert not r["crashed"]
    assert r["dialogs"] and "GUI" in r["dialogs"][0]["text"]
    assert r["dialogs"][0]["caption"] == "bytewright"


def test_virtual_console_draw_box(build_dir):
    out = os.path.join(build_dir, "draw_box.exe")
    rep = harness.build_binary(load_example("draw_box.ir.json"), out)
    assert rep["ok"], rep["errors"]
    r = harness.run(out)
    assert not r["crashed"]
    assert "HELLO" in r["screen"]
    assert "############" in r["screen"]          # the box border, drawn by fill
    assert r["screen"].count("#") > 20            # borders all present


def test_resolve_api_messagebox():
    ra = harness.resolve_api("MessageBoxA")
    assert ra["known"] and ra["dll"] == "user32.dll"


def test_chatbot_verifies_dialog(build_dir):
    gen = lambda m, fb, it, h: {"program_name": "hello_gui", "explanation": "pops a message box",
                                "ir": load_example("hello_gui.ir.json"),
                                "self_tests": [{"stdin": "", "expect_dialog_contains": "GUI binary"}]}
    res = Chatbot(gen, out_dir=build_dir).send("pop up a message box")
    assert res["success"]


def test_chatbot_verifies_screen(build_dir):
    gen = lambda m, fb, it, h: {"program_name": "draw_box", "explanation": "draws a box",
                                "ir": load_example("draw_box.ir.json"),
                                "self_tests": [{"stdin": "", "expect_screen_contains": "HELLO"}]}
    res = Chatbot(gen, out_dir=build_dir).send("draw me a box with a label")
    assert res["success"]
