"""One builder identity, always at full power — the Lil Yapper / Yapzilla split is gone."""
import os

from siryapsalot import modes
from siryapsalot.agent.prompt import available_apis, chatbot_system_prompt
from siryapsalot.chatbot import Chatbot
from siryapsalot.web import ChatService
from conftest import load_example


def test_single_identity():
    m = modes.get_mode()
    assert m.name == "Sir Yaps-a-Lot" and m.deluxe is True
    assert modes.get_mode("yapzilla") is m and modes.get_mode("anything") is m  # argument ignored
    assert list(modes.MODES) == ["default"]


def test_full_power_always_advertised():
    sp = chatbot_system_prompt()
    assert "Beep" in available_apis()                       # sound is always available
    assert "Sir Yaps-a-Lot" in sp
    assert "Yapzilla" not in sp and "Lil Yapper" not in sp   # no personas anywhere


def test_switch_is_a_noop():
    bot = Chatbot(None)
    assert bot.mode.name == "Sir Yaps-a-Lot"
    assert bot.switch("yapzilla").name == "Sir Yaps-a-Lot"   # nothing to switch to


def test_full_gui_example_records_window_control_and_sound(build_dir):
    from siryapsalot import harness
    out = os.path.join(build_dir, "gui_deluxe.exe")
    rep = harness.build_binary(load_example("gui_deluxe.ir.json"), out)
    assert rep["ok"], rep["errors"]
    r = harness.run(out)
    assert not r["crashed"]
    assert r["windows"] and r["controls"] and r["sounds"]


def test_chatbot_verifies_control_and_sound(build_dir):
    spec = {"kind": "build", "program_name": "gui_deluxe", "explanation": "window + button + beep",
            "ir": load_example("gui_deluxe.ir.json"),
            "self_tests": [{"stdin": "", "expect_control_contains": "Click me!", "expect_sound": True}]}
    bot = Chatbot(lambda m, fb, it, h: spec, out_dir=build_dir, prefer_recipes=False)
    assert bot.send("a fancy window from my own spec")["success"]


def test_web_service_persona_is_single_identity(build_dir):
    gen = lambda m, fb, it, h: {"kind": "build", "program_name": "hello", "explanation": "x",
                                "ir": load_example("hello.ir.json"),
                                "self_tests": [{"stdin": "", "expect_contains": "Hello"}]}
    svc = ChatService(bot=Chatbot(gen, out_dir=build_dir, prefer_recipes=False), build_dir=build_dir)
    out = svc.message("build me a tiny program")
    assert out["persona"] == "Sir Yaps-a-Lot"
