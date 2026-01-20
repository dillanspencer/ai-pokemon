from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from .models.pokemon import load_move_db
from .receiver import stream_parsed_frames
from .ai.openai_client import AIConfig, OpenAIBrain
from .ai.policy import CallPolicy
from .helpers.receiver_parser import read_screenshot_b64_and_delete, delete_all_screenshots
from .mgba.input_injector import MGBASocketInjector
from .mgba.decision_adapter import decision_to_press


HOST = "127.0.0.1"
PORT = 7777

IMAGE_PATH = "src/mgba/rom/Pokemon - Emerald Version (USA, Europe)-0.png"

CONF_THRESHOLD = 0

def build_signature(parsed: Any) -> str:
    """
    Produce a small string that changes when the situation changes.
    Tune this over time.
    """
    st = parsed.state
    sig_parts = [
        str(st.flags.compact()),
        # st.signals.hex_cb1(),
        # st.signals.hex_cb2(),
        # str(st.signals.battle_type_flags),
        # "s1" + str(int(st.signals.script1_active)),
        # "s2" + str(int(st.signals.script2_active)),
        # "fade" + str(int(st.signals.palette_fade_active)),
    ]
    # Add party HP/species if you want:
    # for mon in parsed.party: sig_parts.append(f"{mon.data.growth.species_id}:{mon.data.misc.current_hp}")
    return "|".join(sig_parts)


def build_state_summary(parsed: Any, move_db: Dict[int, Any]) -> str:
    """
    Convert rich parsed frame -> compact, AI-friendly text.
    Keep it short; include only what matters for decisions.
    """
    st = parsed.state
    player = parsed.player

    lines = []
    lines.append(f"Frame: {st.frame}")
    lines.append(f"Flags: {st.flags.compact()}")
    lines.append(
        f"cb1={st.signals.hex_cb1()} cb2={st.signals.hex_cb2()} "
        f"battleTypeFlags={st.signals.battle_type_flags} "
        f"script1={st.signals.script1_active} script2={st.signals.script2_active} "
        f"fade={st.signals.palette_fade_active}"
    )
    lines.append(
        f"Player at map {player.map_group}-{player.map_num}, "
        f"pos ({player.x},{player.y}), objEventId={player.object_event_id}"
    )

    lines.append("Your party:")
    for mon in parsed.party:
        if not mon.is_present:
            lines.append(f"- Slot {mon.slot}: empty")
            continue
        # Your model already has nice summary(move_db)
        lines.append(f"- {mon.summary(move_db)}")

    # Optional opponent party when in battle
    if getattr(parsed, "opponent_party", None) is not None:
        lines.append("Opponent party:")
        for mon in parsed.opponent_party:
            if not mon.is_present:
                lines.append(f"- Slot {mon.slot}: empty")
                continue
            lines.append(f"- {mon.summary(move_db)}")

    return "\n".join(lines)


def build_state_object(parsed: Any, move_db: Dict[int, Any]) -> Dict[str, Any]:
    """
    Convert rich parsed frame -> compact, AI-friendly dict.
    Keep it short; include only what matters for decisions.
    """
    st = parsed.state

    player = parsed.player

    obj: Dict[str, Any] = {}

    obj["player"] = {
        "map_group": player.map_group,
        "map_num": player.map_num,
        "x": player.x,
        "y": player.y,
        "object_event_id": player.object_event_id,
    }

    obj["party"] = []
    for mon in parsed.party:
        if not mon.is_present:
            obj["party"].append({"slot": mon.slot, "present": False})
            continue
        obj["party"].append({
            "slot": mon.slot,
            "present": True,
            "summary": mon.summary(move_db),
        })

    # Optional opponent party when in battle
    if getattr(parsed, "opponent_party", None) is not None:
        obj["opponent_party"] = []
        for mon in parsed.opponent_party:
            if not mon.is_present:
                obj["opponent_party"].append({"slot": mon.slot, "present": False})
                continue
            obj["opponent_party"].append({
                "slot": mon.slot,
                "present": True,
                "summary": mon.summary(move_db),
            })

    return obj



def main():
    move_db = load_move_db("src/models/moves.json")

    brain = OpenAIBrain(AIConfig(model="gpt-5.2", temperature=0.2))
    policy = CallPolicy()

    injector = MGBASocketInjector(HOST, PORT + 1)
    injector.start()

    delete_all_screenshots(IMAGE_PATH)

    memory = []
    mem_idx = 0

    for parsed in stream_parsed_frames(HOST, PORT):
        injector.accept_if_needed()

        sig = build_signature(parsed)
        screenshot_b64 = read_screenshot_b64_and_delete(IMAGE_PATH)

        if not screenshot_b64:
            print("No screenshot found; skipping this frame.")
            delete_all_screenshots(IMAGE_PATH)
            continue

        if not policy.should_call(sig):
            continue

        # summary = build_state_summary(parsed, move_db)
        # print("\n=== State Summary ===")
        # print(summary)
        # continue

        state_obj = build_state_object(parsed, move_db)
        state = {
            "state": state_obj,
            "memory": memory,
        }
        print("\n=== State Object ===")
        print(state)
        decision = brain.decide_next_input(state=state, img64=screenshot_b64)
       
        conf = float(decision.get("confidence", 0.0))

        if conf >= CONF_THRESHOLD:
            press = decision_to_press(decision)
            injector.send_press(press)

        mem = decision.get("memory_update")
        if mem is not None and isinstance(mem, dict):
            mem["confidence"] = conf
            mem["index"] = mem_idx
            mem_idx += 1
        if isinstance(mem, dict):
            memory.append(mem)
            # limit to last 10 memories
            memory = memory[-10:]

        # # For now, just print.
        # # Next step: route this to your "input injector" module.
        print("\n=== AI Decision ===")
        print(decision)


if __name__ == "__main__":
    main()
