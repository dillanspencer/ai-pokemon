from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..models.game_state import GameState
from ..models.pokemon import PartyMon, parse_party_bytes


@dataclass(frozen=True, slots=True)
class ParsedFrame:
    raw: Dict[str, Any]
    state: GameState
    party: List[PartyMon]


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

    party_hex = msg.get("party_hex") or ""
    if not isinstance(party_hex, str):
        party_hex = ""

    # Party can be missing in some debug modes; handle gracefully
    try:
        party_bytes = bytes.fromhex(party_hex) if party_hex else b""
    except ValueError:
        party_bytes = b""

    party: List[PartyMon] = []
    if len(party_bytes) == 600:
        party = parse_party_bytes(party_bytes)

    return ParsedFrame(raw=msg, state=state, party=party)
