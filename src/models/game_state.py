# src/models/game_state.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


def _as_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("", "null", "none"):
            return None
        try:
            return int(s)
        except ValueError:
            return None
    return None


def _as_bool(v: Any) -> Optional[bool]:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v != 0
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "1", "yes", "y", "on"):
            return True
        if s in ("false", "0", "no", "n", "off"):
            return False
    return None


@dataclass(frozen=True, slots=True)
class MainSignals:
    battle_type_flags: Optional[int] = None
    gMainBase: Optional[int] = None
    cb1: Optional[int] = None
    cb2: Optional[int] = None
    script1_active: Optional[int] = None
    script2_active: Optional[int] = None
    palette_fade_active: Optional[int] = None
    player_avatar_flags: Optional[int] = None

    @staticmethod
    def from_msg(msg: Dict[str, Any]) -> "MainSignals":
        sig = msg.get("sig") or {}
        return MainSignals(
            battle_type_flags=_as_int(sig.get("battleTypeFlags")),
            gMainBase=_as_int(sig.get("gMainBase")),
            cb1=_as_int(sig.get("cb1")),
            cb2=_as_int(sig.get("cb2")),
            script1_active=_as_int(sig.get("script1Active")),
            script2_active=_as_int(sig.get("script2Active")),
            palette_fade_active=_as_int(sig.get("paletteFadeActive")),
            player_avatar_flags=_as_int(sig.get("playerAvatarFlags")),
        )

    def hex_cb2(self) -> str:
        return "????????" if self.cb2 is None else f"{self.cb2:08X}"

    def hex_cb1(self) -> str:
        return "????????" if self.cb1 is None else f"{self.cb1:08X}"


@dataclass(frozen=True, slots=True)
class GameFlags:
    mode: Optional[str] = None
    in_battle: Optional[bool] = None
    in_overworld: Optional[bool] = None
    in_menu: Optional[bool] = None
    in_script: Optional[bool] = None
    in_dialog: Optional[bool] = None
    in_cutscene: Optional[bool] = None
    in_transition: Optional[bool] = None
    player_locked: Optional[bool] = None
    has_player_control: Optional[bool] = None
    cb2_is_overworld: Optional[bool] = None
    overworld_cb2: Optional[int] = None

    @staticmethod
    def from_msg(msg: Dict[str, Any]) -> "GameFlags":
        flags = msg.get("flags") or {}
        return GameFlags(
            mode=flags.get("mode"),
            in_battle=_as_bool(flags.get("in_battle")),
            in_overworld=_as_bool(flags.get("in_overworld")),
            in_menu=_as_bool(flags.get("in_menu")),
            in_script=_as_bool(flags.get("in_script")),
            in_dialog=_as_bool(flags.get("in_dialog")),
            in_cutscene=_as_bool(flags.get("in_cutscene")),
            in_transition=_as_bool(flags.get("in_transition")),
            player_locked=_as_bool(flags.get("player_locked")),
            has_player_control=_as_bool(flags.get("has_player_control")),
            cb2_is_overworld=_as_bool(flags.get("cb2_is_overworld")),
            overworld_cb2=_as_int(flags.get("overworld_cb2")),
        )

    def compact(self) -> str:
        # Nice one-liner for printing
        label = self.mode or "UNKNOWN"
        bits = []
        for name, val in [
            ("battle", self.in_battle),
            ("overworld", self.in_overworld),
            ("menu", self.in_menu),
            ("script", self.in_script),
            ("dialog", self.in_dialog),
            ("cutscene", self.in_cutscene),
            ("fade", self.in_transition),
            ("locked", self.player_locked),
            ("control", self.has_player_control),
        ]:
            if val is True:
                bits.append(name)
        return label + ((" | " + " ".join(bits)) if bits else "")


@dataclass(frozen=True, slots=True)
class GameState:
    frame: int
    party_base: int
    signals: MainSignals
    flags: GameFlags

    @staticmethod
    def from_msg(msg: Dict[str, Any]) -> "GameState":
        return GameState(
            frame=int(msg.get("frame", 0) or 0),
            party_base=int(msg.get("party_base", 0) or 0),
            signals=MainSignals.from_msg(msg),
            flags=GameFlags.from_msg(msg),
        )
