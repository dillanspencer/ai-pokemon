from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal
import struct
import json

# =========================
# Low-level helpers
# =========================

def u8(b: bytes, off: int) -> int:
    return b[off]

def u16le(b: bytes, off: int) -> int:
    return b[off] | (b[off + 1] << 8)

def u32le(b: bytes, off: int) -> int:
    return b[off] | (b[off + 1] << 8) | (b[off + 2] << 16) | (b[off + 3] << 24)

def read_u16_from(buf: bytes, off: int) -> int:
    return struct.unpack_from("<H", buf, off)[0]

def read_u32_from(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


# =========================
# Move DB model + loading
# =========================

MoveCategory = Literal["Physical", "Special", "Status"]

@dataclass(frozen=True, slots=True)
class MoveInfo:
    """
    Static move metadata from moves.json (Bulbapedia scrape).
    Use Optional for fields that can be null/None in your JSON.
    """
    id: int
    name: str
    type: str
    category: str  # could be MoveCategory if your JSON is guaranteed clean
    power: Optional[int] = None
    accuracy: Optional[int] = None
    pp: Optional[int] = None
    priority: Optional[int] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "MoveInfo":
        return MoveInfo(
            id=int(d.get("id", 0)),
            name=str(d.get("name", f"#{d.get('id', 0)}")),
            type=str(d.get("type", "?")),
            category=str(d.get("category", "?")),
            power=d.get("power", None),
            accuracy=d.get("accuracy", None),
            pp=d.get("pp", None),
            priority=d.get("priority", None),
        )


MoveDB = Dict[int, MoveInfo]


def load_move_db(path: str | Path) -> MoveDB:
    """
    Loads moves.json produced from the Bulbapedia table parse.
    Expected shape: list[{"id": 1, "name": "...", "type": "...", ...}, ...]
    Returns: dict keyed by move id -> MoveInfo
    """
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8", errors="replace"))

    db: MoveDB = {}
    for entry in data:
        mid = entry.get("id")
        if isinstance(mid, int):
            info = MoveInfo.from_dict(entry)
            db[info.id] = info
    return db


# =========================
# Gen 3 string decoding (optional)
# =========================

def decode_gen3_name(raw: bytes) -> str:
    cut = raw.find(b"\xFF")
    if cut != -1:
        raw = raw[:cut]
    out = []
    for c in raw:
        if 32 <= c <= 126:
            out.append(chr(c))
        else:
            out.append("?")
    return "".join(out).strip()


# =========================
# Data models
# =========================

@dataclass
class Stats:
    hp: int
    atk: int
    defe: int
    spe: int
    spa: int
    spd: int

@dataclass(frozen=True, slots=True)
class Move:
    """
    A learned move in party data (what the save/party struct stores).
    This is the *instance*: id + current PP.
    """
    move_id: int
    pp: int

    def is_empty(self) -> bool:
        return self.move_id == 0

    def info(self, move_db: MoveDB) -> Optional[MoveInfo]:
        return move_db.get(self.move_id)

    def display(self, move_db: MoveDB) -> str:
        if self.is_empty():
            return "—"
        info = self.info(move_db)
        if not info:
            return f"#{self.move_id} (PP {self.pp})"

        power_s = "—" if info.power is None else str(info.power)
        acc_s = "—" if info.accuracy is None else str(info.accuracy)
        return f"{info.name} [{info.type}/{info.category}] Pow {power_s} Acc {acc_s} (PP {self.pp})"


@dataclass
class EVs:
    hp: int
    atk: int
    defe: int
    spe: int
    spa: int
    spd: int

@dataclass
class ContestCondition:
    cool: int
    beauty: int
    cute: int
    smart: int
    tough: int
    feel: int

@dataclass
class IVs:
    hp: int
    atk: int
    defe: int
    spe: int
    spa: int
    spd: int
    is_egg: bool
    ability_index: int  # 0 or 1

@dataclass
class Origins:
    met_location: int
    origins_raw: int
    ot_gender_female: bool
    ball_id: int
    game_id: int
    level_met: int
    hatched: bool

@dataclass
class GrowthBlock:
    species_id: int
    held_item_id: int
    exp: int
    pp_bonuses: int
    friendship: int

@dataclass
class AttacksBlock:
    moves: List[Move]  # 4 moves max

@dataclass
class MiscBlock:
    pokerus: int
    met_location: int
    origins: Origins
    ivs: IVs
    ribbons_obedience: int  # bitfield

@dataclass
class DecryptedSubstructs:
    growth: GrowthBlock
    attacks: AttacksBlock
    evs: EVs
    contest: ContestCondition
    misc: MiscBlock

@dataclass
class PartyMon:
    slot: int

    # Header fields (unencrypted)
    personality: int
    ot_id: int
    nickname: str
    language: int
    misc_flags: int
    ot_name: str
    markings: int
    checksum: int

    # Party-only live fields
    status: int
    level: int
    current_hp: int
    total_hp: int
    stats: Stats

    # Decrypted game data
    data: Optional[DecryptedSubstructs] = None

    # Derived / convenience
    is_present: bool = False
    nature: Optional[int] = None
    shiny: Optional[bool] = None

    def moves_summary(self, move_db: MoveDB) -> str:
        if not self.data:
            return "Moves: (no data)"
        parts = [m.display(move_db) for m in self.data.attacks.moves]
        return "Moves: " + " | ".join(parts)

    def summary(self, move_db: Optional[MoveDB] = None) -> str:
        sp = self.data.growth.species_id if self.data else 0
        item = self.data.growth.held_item_id if self.data else 0

        base = (
            f"Slot {self.slot}: "
            f"Species={sp} Lv={self.level} HP={self.current_hp}/{self.total_hp} "
            f"Item={item} Nature={self.nature} Shiny={self.shiny}"
        )

        if move_db and self.data:
            return base + "\n  " + self.moves_summary(move_db)

        return base


# =========================
# Gen 3 decryption + parsing
# =========================

SUBSTRUCT_ORDER: List[tuple[str, str, str, str]] = [
    ("G", "A", "E", "M"),
    ("G", "A", "M", "E"),
    ("G", "E", "A", "M"),
    ("G", "E", "M", "A"),
    ("G", "M", "A", "E"),
    ("G", "M", "E", "A"),
    ("A", "G", "E", "M"),
    ("A", "G", "M", "E"),
    ("A", "E", "G", "M"),
    ("A", "E", "M", "G"),
    ("A", "M", "G", "E"),
    ("A", "M", "E", "G"),
    ("E", "G", "A", "M"),
    ("E", "G", "M", "A"),
    ("E", "A", "G", "M"),
    ("E", "A", "M", "G"),
    ("E", "M", "G", "A"),
    ("E", "M", "A", "G"),
    ("M", "G", "A", "E"),
    ("M", "G", "E", "A"),
    ("M", "A", "G", "E"),
    ("M", "A", "E", "G"),
    ("M", "E", "G", "A"),
    ("M", "E", "A", "G"),
]


def decrypt_data_block(personality: int, ot_id: int, encrypted48: bytes) -> bytes:
    key = (personality ^ ot_id) & 0xFFFFFFFF
    out = bytearray(encrypted48)
    for i in range(0, 48, 4):
        word = read_u32_from(encrypted48, i)
        dec = (word ^ key) & 0xFFFFFFFF
        struct.pack_into("<I", out, i, dec)
    return bytes(out)


def checksum16(decrypted48: bytes) -> int:
    s = 0
    for i in range(0, 48, 2):
        s = (s + read_u16_from(decrypted48, i)) & 0xFFFF
    return s


def parse_substructs(
    personality: int,
    ot_id: int,
    checksum_expected: int,
    encrypted48: bytes
) -> Optional[DecryptedSubstructs]:
    dec = decrypt_data_block(personality, ot_id, encrypted48)

    if checksum16(dec) != checksum_expected:
        return None

    order = SUBSTRUCT_ORDER[personality % 24]
    blocks: Dict[str, bytes] = {}
    for idx, tag in enumerate(order):
        blocks[tag] = dec[idx * 12 : (idx + 1) * 12]

    g = blocks["G"]
    growth = GrowthBlock(
        species_id=read_u16_from(g, 0x00),
        held_item_id=read_u16_from(g, 0x02),
        exp=read_u32_from(g, 0x04),
        pp_bonuses=u8(g, 0x08),
        friendship=u8(g, 0x09),
    )

    a = blocks["A"]
    moves: List[Move] = [
        Move(move_id=read_u16_from(a, 0x00), pp=u8(a, 0x08)),
        Move(move_id=read_u16_from(a, 0x02), pp=u8(a, 0x09)),
        Move(move_id=read_u16_from(a, 0x04), pp=u8(a, 0x0A)),
        Move(move_id=read_u16_from(a, 0x06), pp=u8(a, 0x0B)),
    ]
    attacks = AttacksBlock(moves=moves)

    e = blocks["E"]
    evs = EVs(
        hp=u8(e, 0x00),
        atk=u8(e, 0x01),
        defe=u8(e, 0x02),
        spe=u8(e, 0x03),
        spa=u8(e, 0x04),
        spd=u8(e, 0x05),
    )
    contest = ContestCondition(
        cool=u8(e, 0x06),
        beauty=u8(e, 0x07),
        cute=u8(e, 0x08),
        smart=u8(e, 0x09),
        tough=u8(e, 0x0A),
        feel=u8(e, 0x0B),
    )

    m = blocks["M"]
    pokerus = u8(m, 0x00)
    met_location = u8(m, 0x01)
    origins_raw = read_u16_from(m, 0x02)

    level_met = origins_raw & 0x7F
    game_id = (origins_raw >> 7) & 0x0F
    ball_id = (origins_raw >> 11) & 0x0F
    ot_gender_female = ((origins_raw >> 15) & 0x01) == 1
    hatched = (level_met == 0)

    origins = Origins(
        met_location=met_location,
        origins_raw=origins_raw,
        ot_gender_female=ot_gender_female,
        ball_id=ball_id,
        game_id=game_id,
        level_met=level_met,
        hatched=hatched,
    )

    iv_egg_ability = read_u32_from(m, 0x04)

    ivs = IVs(
        hp=(iv_egg_ability >> 0) & 0x1F,
        atk=(iv_egg_ability >> 5) & 0x1F,
        defe=(iv_egg_ability >> 10) & 0x1F,
        spe=(iv_egg_ability >> 15) & 0x1F,
        spa=(iv_egg_ability >> 20) & 0x1F,
        spd=(iv_egg_ability >> 25) & 0x1F,
        is_egg=((iv_egg_ability >> 30) & 0x01) == 1,
        ability_index=((iv_egg_ability >> 31) & 0x01),
    )

    ribbons_obedience = read_u32_from(m, 0x08)

    misc = MiscBlock(
        pokerus=pokerus,
        met_location=met_location,
        origins=origins,
        ivs=ivs,
        ribbons_obedience=ribbons_obedience,
    )

    return DecryptedSubstructs(growth=growth, attacks=attacks, evs=evs, contest=contest, misc=misc)


def compute_nature(personality: int) -> int:
    return personality % 25

def compute_shiny(personality: int, ot_id: int) -> bool:
    tid = ot_id & 0xFFFF
    sid = (ot_id >> 16) & 0xFFFF
    pid_lo = personality & 0xFFFF
    pid_hi = (personality >> 16) & 0xFFFF
    v = (tid ^ sid ^ pid_lo ^ pid_hi) & 0xFFFF
    return v < 8


def parse_party_mon(slot: int, mon100: bytes) -> PartyMon:
    personality = u32le(mon100, 0x00)
    ot_id = u32le(mon100, 0x04)
    nickname_raw = mon100[0x08:0x12]
    language = u8(mon100, 0x12)
    misc_flags = u8(mon100, 0x13)
    ot_name_raw = mon100[0x14:0x1B]
    markings = u8(mon100, 0x1B)
    checksum_expected = u16le(mon100, 0x1C)

    encrypted48 = mon100[0x20:0x50]

    status = u32le(mon100, 0x50)
    level = u8(mon100, 0x54)
    current_hp = u16le(mon100, 0x56)
    total_hp = u16le(mon100, 0x58)

    stats = Stats(
        hp=total_hp,
        atk=u16le(mon100, 0x5A),
        defe=u16le(mon100, 0x5C),
        spe=u16le(mon100, 0x5E),
        spa=u16le(mon100, 0x60),
        spd=u16le(mon100, 0x62),
    )

    data = parse_substructs(personality, ot_id, checksum_expected, encrypted48)

    mon = PartyMon(
        slot=slot,
        personality=personality,
        ot_id=ot_id,
        nickname=decode_gen3_name(nickname_raw),
        language=language,
        misc_flags=misc_flags,
        ot_name=decode_gen3_name(ot_name_raw),
        markings=markings,
        checksum=checksum_expected,
        status=status,
        level=level,
        current_hp=current_hp,
        total_hp=total_hp,
        stats=stats,
        data=data,
    )

    mon.nature = compute_nature(personality)
    mon.shiny = compute_shiny(personality, ot_id)

    if data and data.growth.species_id != 0 and total_hp != 0:
        mon.is_present = True

    return mon


def parse_party_bytes(party600: bytes) -> List[PartyMon]:
    if len(party600) < 600:
        raise ValueError("party600 must be 600 bytes (6 mons * 100 bytes)")
    mons: List[PartyMon] = []
    for i in range(6):
        mon100 = party600[i * 100 : (i + 1) * 100]
        mons.append(parse_party_mon(i + 1, mon100))
    return mons
