"""The persona switcher: Lil Yapper (classic) vs Yapzilla (deluxe GUI+sound)."""
import os

from siryapsalot import modes
from siryapsalot.agent.prompt import available_apis, chatbot_system_prompt
from siryapsalot.chatbot import Chatbot
from siryapsalot.web import ChatService
from conftest import load_example


def test_modes_resolve_by_id_name_and_alias():
    assert modes.get_mode("classic").name == "Lil Yapper"
    assert modes.get_mode("yapzilla").id == "deluxe"
    assert modes.get_mode("lil").id == "classic"
    assert modes.get_mode("Yapzilla").id == "deluxe"
    assert modes.get_mode("nope") is None


def test_deluxe_advertises_sound_classic_does_not():
    assert "Beep" in available_apis(include_deluxe=True)
    assert "Beep" not in available_apis(include_deluxe=False)
    assert "YAPZILLA" in chatbot_system_prompt("deluxe")
    assert "Lil Yapper" in chatbot_system_prompt("classic")


class _FakeGen:
    """A generator with a mutable mode, like ChatbotGenerator."""

    def __init__(self, spec):
        self.mode = modes.MODES["classic"]
        self.spec = spec

    def __call__(self, message, feedback, iteration, history):
        return self.spec


def test_chatbot_switch_changes_persona():
    bot = Chatbot(_FakeGen({}))
    assert bot.mode.name == "Lil Yapper"
    assert bot.switch("yapzilla").name == "Yapzilla"
    assert bot.mode.id == "deluxe"
    assert bot.switch("nope") is None and bot.mode.id == "deluxe"   # unknown -> unchanged


def test_deluxe_example_records_window_control_and_sound(build_dir):
    from siryapsalot import harness
    out = os.path.join(build_dir, "gui_deluxe.exe")
    rep = harness.build_binary(load_example("gui_deluxe.ir.json"), out)
    assert rep["ok"], rep["errors"]
    r = harness.run(out)
    assert not r["crashed"]
    assert r["windows"] and r["windows"][0]["title"] == "Yapzilla Deluxe!"
    assert r["controls"] and r["controls"][0]["class"] == "BUTTON"
    assert r["sounds"] and r["sounds"][0]["type"] == "beep"


def test_chatbot_verifies_control_and_sound(build_dir):
    spec = {"program_name": "gui_deluxe", "explanation": "window + button + beep",
            "ir": load_example("gui_deluxe.ir.json"),
            "self_tests": [{"stdin": "", "expect_control_contains": "Click me!", "expect_sound": True}]}
    bot = Chatbot(lambda m, fb, it, h: spec, out_dir=build_dir)
    assert bot.send("make a deluxe window")["success"]


def test_web_service_passes_mode_through(build_dir):
    gen = _FakeGen({"program_name": "hello", "explanation": "x",
                    "ir": load_example("hello.ir.json"), "self_tests": [{"stdin": "", "expect_contains": "Hello"}]})
    svc = ChatService(bot=Chatbot(gen, out_dir=build_dir), build_dir=build_dir)
    out = svc.message("hi", mode="yapzilla")
    assert gen.mode.id == "deluxe"            # the switch took effect
    assert out["persona"] == "Yapzilla"
