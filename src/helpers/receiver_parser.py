from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..models.game_state import GameState
from ..models.pokemon import PartyMon, parse_party_bytes
from ..models.player import Player

import base64
import os
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ParsedFrame:
    raw: Dict[str, Any]
    state: GameState
    player: Player
    party: List[PartyMon]
    opponent_party: List[PartyMon]


def parse_ndjson_line(line: str) -> Optional[ParsedFrame]:
    """
    Parses one NDJSON line from mGBA.
    Returns None if the line is empty/invalid.
    Raises only on truly unexpected conditions.
    """
    line = line.strip()
    if not line:
        return None

    try:
        msg: Dict[str, Any] = json.loads(line)
    except json.JSONDecodeError:
        # caller can log; we return None so your loop continues
        return None

    state = GameState.from_msg(msg)

    player = Player.from_msg(msg)

    party_hex = msg.get("party_hex") or ""
    if not isinstance(party_hex, str):
        party_hex = ""

    opponent_party_hex = msg.get("opponent_party_hex") or ""
    if not isinstance(opponent_party_hex, str):
        opponent_party_hex = ""

    # Party can be missing in some debug modes; handle gracefully
    try:
        party_bytes = bytes.fromhex(party_hex) if party_hex else b""
    except ValueError:
        party_bytes = b""

    # Opponent party can be missing in some debug modes; handle gracefully
    try:
        opponent_party_bytes = bytes.fromhex(opponent_party_hex) if opponent_party_hex else b""
    except ValueError:
        opponent_party_bytes = b""

    party: List[PartyMon] = []
    if len(party_bytes) == 600:
        party = parse_party_bytes(party_bytes)

    opponent_party: List[PartyMon] = []
    if len(opponent_party_bytes) == 600:
        opponent_party = parse_party_bytes(opponent_party_bytes)

    return ParsedFrame(raw=msg, state=state, party=party, opponent_party=opponent_party, player=player)


def read_screenshot_b64_and_delete(path: str | os.PathLike) -> str | None:
    """
    Read PNG/JPG file, return base64 string (no data: prefix), then delete the file.
    Returns None if file doesn't exist yet (or cannot be read).
    """
    p = Path(path)

    if not p.exists():
        return None

    try:
        data = p.read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        return f'data:image/jpeg;base64,{b64}'
    except OSError:
        return None
    finally:
        # Best-effort cleanup
        try:
            p.unlink(missing_ok=True)  # py>=3.8 supports missing_ok
        except Exception:
            pass


def delete_all_screenshots(image_path: str) -> None:
    """
    Deletes all PNG screenshots in the same folder as image_path.
    Used when we detect a missed or stale screenshot.
    """
    folder = Path(image_path).parent

    if not folder.exists():
        return

    for p in folder.glob("*.png"):
        try:
            p.unlink()
        except Exception as e:
            print(f"[WARN] Failed to delete {p}: {e}")