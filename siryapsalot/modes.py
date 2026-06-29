"""The builder's identity.

There used to be two switchable personas (Lil Yapper / Yapzilla). That's gone: there is now one
builder, Sir Yaps-a-Lot, and it is ALWAYS at full power — every capability (console, positioned
drawing, real windows, clickable buttons/controls, sound, interactive events) is on, every time.
No modes, no personalities to pick.

The small `Mode`/`get_mode`/`listing` surface is kept (returning the single identity) so existing
callers keep working without change.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Mode:
    id: str
    name: str
    tagline: str
    persona: str
    deluxe: bool        # always True now — the full API surface is always advertised


SIR = Mode(
    id="default",
    name="Sir Yaps-a-Lot",
    tagline="turns plain English into real Windows .exe files — full GUI, sound, the works",
    persona=("You are Sir Yaps-a-Lot, an expert builder of Windows programs. You always use the "
             "full toolbox — console apps and games, positioned/colored console drawing, real "
             "windows with clickable buttons and controls, and sound — picking whatever best fits "
             "the request, and you always ship something that actually works."),
    deluxe=True,
)

MODES = {SIR.id: SIR}
DEFAULT = SIR.id


def get_mode(key=None) -> Mode:
    """Always the one identity (kept for API compatibility; the argument is ignored)."""
    return SIR


def listing() -> str:
    return f"  {SIR.name} — {SIR.tagline}"
