from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class Player:
    object_event_id: int
    x: int
    y: int
    map_group: int
    map_num: int

    @staticmethod
    def from_msg(msg: dict) -> "Player":
        player_data = msg.get("player") or {}
        return Player(
            object_event_id=int(player_data.get("objectEventId") or 0),
            x=int(player_data.get("x") or 0),
            y=int(player_data.get("y") or 0),
            map_group=int(player_data.get("mapGroup") or 0),
            map_num=int(player_data.get("mapNum") or 0),
        )