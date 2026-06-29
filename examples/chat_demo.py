#!/usr/bin/env python3
"""A scripted chatbot conversation — no API key needed.

Shows the product experience: you send plain-English messages, the bot builds .exe files,
self-tests them, and replies. The `claude_model` function stands in for the live model
(`siryapsalot.chatbot.ChatbotGenerator`), returning the IR + self-tests a model would emit.

Run:  python examples/chat_demo.py
"""
import json
import os

from siryapsalot.chatbot import Chatbot

HERE = os.path.dirname(__file__)


def _spec(name, explanation, tests):
    return {"program_name": name, "explanation": explanation,
            "ir": json.load(open(os.path.join(HERE, f"{name}.ir.json"))), "self_tests": tests}


def claude_model(message, feedback, iteration, history):
    """Stand-in for the live model: message -> {program_name, explanation, ir, self_tests}."""
    m = message.lower()
    if "click" in m or "interactive" in m or "react" in m:
        return _spec("click_beeps",
                     "an interactive window: its button beeps when clicked (the WM_COMMAND handler "
                     "really runs) and it chimes on repaint",
                     [{"stdin": "", "expect_event": "WM_COMMAND", "expect_sound": True}])
    if "deluxe" in m or "button" in m or "sound" in m or "beep" in m:
        return _spec("gui_deluxe", "a real window with a button — and it beeps!",
                     [{"stdin": "", "expect_control_contains": "Click me!", "expect_sound": True}])
    if "christmas" in m or "tree" in m:
        return _spec("christmas_tree", "prints a centered ASCII christmas tree",
                     [{"stdin": "", "expect_contains": "***********"}])
    if "prime" in m:
        return _spec("prime", "reads a number and reports whether it is prime",
                     [{"stdin": "7", "expect_equals": "prime\n"},
                      {"stdin": "8", "expect_contains": "not prime"}])
    if "tic" in m or "tac" in m or "toe" in m:
        return _spec("tictactoe", "a playable 2-player Tic-Tac-Toe (type cell numbers 1-9)",
                     [{"stdin": "1\n4\n2\n5\n3\n", "expect_contains": "X wins!"}])
    if "tetris" in m or "game" in m:
        return _spec("tetris_board",
                     "Real-time graphical Tetris is beyond the backend right now (no graphics or "
                     "live-keyboard APIs), so I built an ASCII Tetris board — the closest console "
                     "version. A playable build is on the roadmap once GUI support lands.",
                     [{"stdin": "", "expect_contains": "+----------+"}])
    if "window" in m:
        return _spec("hello_window", "opens a real Win32 window (640x480)",
                     [{"stdin": "", "expect_window_contains": "Sir Yaps-a-Lot"}])
    if "message box" in m or "popup" in m or "pop up" in m or "gui" in m:
        return _spec("hello_gui", "pops up a Windows message box (a GUI binary)",
                     [{"stdin": "", "expect_dialog_contains": "GUI binary"}])
    if "box" in m or "draw" in m:
        return _spec("draw_box", "draws a bordered box with a label using console cursor APIs",
                     [{"stdin": "", "expect_screen_contains": "HELLO"}])
    if "guess" in m:
        return _spec("guess", "a number-guessing game (target 42) — type guesses, get hints",
                     [{"stdin": "50\n40\n42\n", "expect_contains": "correct!"}])
    if "deluxe" in m or "button" in m or "sound" in m:
        return _spec("gui_deluxe", "a real window with a button — and it beeps!",
                     [{"stdin": "", "expect_control_contains": "Click me!", "expect_sound": True}])
    if "fib" in m:
        return _spec("fibonacci", "prints the Fibonacci numbers below 100",
                     [{"stdin": "", "expect_contains": "89"}])
    raise ValueError(f"(demo stand-in has no canned IR for {message!r})")


class StandIn:
    """Stand-in generator with a switchable .mode (like the real ChatbotGenerator)."""
    def __init__(self):
        from siryapsalot import modes
        self.mode = modes.MODES["classic"]

    def __call__(self, message, feedback, iteration, history):
        return claude_model(message, feedback, iteration, history)


def main():
    bot = Chatbot(StandIn())
    print(f"💬 chatting with {bot.mode.name}\n")
    for msg in ["hello", "make me a christmas tree", "make me a tic-tac-toe game",
                "now tell me whether a number is prime"]:
        print("=" * 72 + f"\nyou> {msg}\n")
        print(f"{bot.mode.name}> " + bot.send(msg)["reply"])

    print("\n" + "#" * 72)
    print(f"#  /switch yapzilla   →  now chatting with the deluxe persona")
    print("#" * 72)
    bot.switch("yapzilla")
    print(f"\n💬 chatting with {bot.mode.name} — {bot.mode.tagline}\n")
    for msg in ["build me a deluxe window with a button and sound",
                "now make a window with a button that beeps when I click it"]:
        print("=" * 72 + f"\nyou> {msg}\n")
        print(f"{bot.mode.name}> " + bot.send(msg)["reply"])


if __name__ == "__main__":
    main()
