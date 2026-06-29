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
    if "fib" in m:
        return _spec("fibonacci", "prints the Fibonacci numbers below 100",
                     [{"stdin": "", "expect_contains": "89"}])
    raise ValueError(f"(demo stand-in has no canned IR for {message!r})")


def main():
    bot = Chatbot(claude_model)
    conversation = [
        "make me a christmas tree",
        "pop up a message box that says hello",
        "open a window titled hello",
        "draw me a box with a label",
        "make me a tic-tac-toe game",
        "make me a tetris game",
        "now write something that tells me whether a number is prime",
        "make me a guessing game",
    ]
    for msg in conversation:
        print("\n" + "=" * 72)
        print(f"you> {msg}\n")
        res = bot.send(msg)
        print("bot> " + res["reply"])


if __name__ == "__main__":
    main()
