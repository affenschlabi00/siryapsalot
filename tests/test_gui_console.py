"""Phase 6: GUI binaries (MessageBoxA) and the virtual console (positioned drawing)."""
import os

from siryapsalot import harness
from siryapsalot.chatbot import Chatbot
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
    assert r["dialogs"][0]["caption"] == "siryapsalot"


def test_virtual_console_draw_box(build_dir):
    out = os.path.join(build_dir, "draw_box.exe")
    rep = harness.build_binary(load_example("draw_box.ir.json"), out)
    assert rep["ok"], rep["errors"]
    r = harness.run(out)
    assert not r["crashed"]
    assert "HELLO" in r["screen"]
    assert "############" in r["screen"]          # the box border, drawn by fill
    assert r["screen"].count("#") > 20            # borders all present


def test_real_window_is_created(build_dir):
    out = os.path.join(build_dir, "hello_window.exe")
    rep = harness.build_binary(load_example("hello_window.ir.json"), out)
    assert rep["ok"], rep["errors"]
    assert harness.validate_pe(out)["headers"]["subsystem"] == "gui"
    r = harness.run(out)
    assert not r["crashed"] and r["exit_code"] == 0      # message loop exits cleanly
    assert r["windows"] and "Sir Yaps-a-Lot window" in r["windows"][0]["title"]
    assert r["windows"][0]["width"] == 640


def test_chatbot_verifies_window(build_dir):
    gen = lambda m, fb, it, h: {"program_name": "hello_window", "explanation": "opens a window",
                                "ir": load_example("hello_window.ir.json"),
                                "self_tests": [{"stdin": "", "expect_window_contains": "Sir Yaps-a-Lot"}]}
    assert Chatbot(gen, out_dir=build_dir).send("open a window")["success"]


def test_resolve_api_messagebox():
    ra = harness.resolve_api("MessageBoxA")
    assert ra["known"] and ra["dll"] == "user32.dll"


def test_code_reference_function_pointer(build_dir):
    """`code:LABEL` takes a function pointer (used to register a window proc)."""
    from siryapsalot import harness as H
    out = os.path.join(build_dir, "hello_window2.exe")
    H.build_binary(load_example("hello_window.ir.json"), out)
    # the window proc address must be a real code address inside .text
    d = H.disassemble(out, {"count": 6})["instructions"]
    assert any("lea" in i["mnemonic"] for i in d)


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
