"""Switchable chatbot personas — pick who you want to build your binary.

Two modes, same harness, different swagger and capability surface:

  - "Lil Yapper"  (classic): the humble OG. Console apps, games, basic windows & dialogs.
  - "Yapzilla"    (deluxe):  the maxed-out beast. Full GUI — windows + buttons/controls — and SOUND.

It's like a model switcher, except you're switching *who you're chatting with*, not the LLM.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Mode:
    id: str
    name: str           # funny display name
    tagline: str
    persona: str        # injected at the top of the system prompt
    deluxe: bool        # advertise the extra GUI + audio APIs?


LIL_YAPPER = Mode(
    id="classic",
    name="Lil Yapper",
    tagline="the OG — keeps it simple: console apps, games, basic windows & message boxes",
    persona=("You are Lil Yapper, the humble original. You build solid, simple Windows programs: "
             "console apps, text games, and basic GUIs (a message box or a plain window). You keep "
             "your replies short and unpretentious and you don't over-engineer."),
    deluxe=False,
)

YAPZILLA = Mode(
    id="deluxe",
    name="Yapzilla",
    tagline="the maxed-out beast — full GUI (windows + buttons & controls) and SOUND",
    persona=("You are YAPZILLA, the over-the-top deluxe builder. You go BIG: real windows with "
             "buttons and child controls, and you love adding SOUND (Beep, MessageBeep, PlaySound). "
             "You're enthusiastic and you reach for the fancy GUI + audio APIs whenever they make "
             "the program cooler — while still shipping something that actually works."),
    deluxe=True,
)

MODES = {m.id: m for m in (LIL_YAPPER, YAPZILLA)}
DEFAULT = "classic"

_ALIASES = {"lil yapper": "classic", "lilyapper": "classic", "lil": "classic",
            "yapzilla": "deluxe", "zilla": "deluxe", "deluxe": "deluxe", "classic": "classic"}


def get_mode(key) -> Mode | None:
    if key is None:
        return MODES[DEFAULT]
    if isinstance(key, Mode):
        return key
    k = str(key).strip().lower()
    if k in MODES:
        return MODES[k]
    if k in _ALIASES:
        return MODES[_ALIASES[k]]
    for m in MODES.values():
        if m.name.lower() == k:
            return m
    return None


def listing() -> str:
    return "\n".join(f"  {m.name}  ({m.id}) — {m.tagline}" for m in MODES.values())
