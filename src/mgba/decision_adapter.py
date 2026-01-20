# src/mgba/decision_adapter.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from .input_injector import MGBAPress

# conservative defaults (frames @ 60fps)
DEFAULT_TAP_FRAMES = 2
DPAD_TAP_FRAMES = 3
START_SELECT_FRAMES = 2

VALID_KEYS = {
    "A","B","START","SELECT","UP","DOWN","LEFT","RIGHT","L","R",
    # optional aliases if your model ever emits them
    "U","D","LFT","RGT","LEFT_ARROW","RIGHT_ARROW",
}

ALIASES = {
    "U": "UP",
    "D": "DOWN",
    "LFT": "LEFT",
    "RGT": "RIGHT",
    "LEFT_ARROW": "LEFT",
    "RIGHT_ARROW": "RIGHT",
}

def decision_to_press(decision: Dict[str, Any]) -> MGBAPress:
    raw = decision.get("key", "NONE")
    key = ALIASES.get(raw, raw)

    if key == "NONE" or key is None:
        return MGBAPress(keys=[], frames=0)

    if key not in VALID_KEYS:
        # fail safe: do nothing rather than mash a random key
        return MGBAPress(keys=[], frames=0)

    # frame duration heuristics
    if key in {"UP", "DOWN", "LEFT", "RIGHT"}:
        frames = DPAD_TAP_FRAMES
    elif key in {"START", "SELECT"}:
        frames = START_SELECT_FRAMES
    else:
        frames = DEFAULT_TAP_FRAMES

    return MGBAPress(keys=[key], frames=frames)