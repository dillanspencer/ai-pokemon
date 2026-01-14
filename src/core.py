from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from .models.pokemon import load_move_db
from .receiver import stream_parsed_frames
from .ai.openai_client import AIConfig, OpenAIBrain
from .ai.policy import CallPolicy

HOST = "127.0.0.1"
PORT = 7777


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

    lines = []
    lines.append(f"Frame: {st.frame}")
    lines.append(f"Flags: {st.flags.compact()}")
    lines.append(
        f"cb1={st.signals.hex_cb1()} cb2={st.signals.hex_cb2()} "
        f"battleTypeFlags={st.signals.battle_type_flags} "
        f"script1={st.signals.script1_active} script2={st.signals.script2_active} "
        f"fade={st.signals.palette_fade_active}"
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


def main():
    move_db = load_move_db("src/models/moves.json")

    brain = OpenAIBrain(AIConfig(model="gpt-5.2", temperature=0.2))
    policy = CallPolicy()

    for parsed in stream_parsed_frames(HOST, PORT):
        sig = build_signature(parsed)

        if not policy.should_call(sig):
            continue

        summary = build_state_summary(parsed, move_db)
        print("\n=== State Summary ===")
        print(summary)
        # decision = brain.decide_next_input(state_summary=summary)

        # # For now, just print.
        # # Next step: route this to your "input injector" module.
        # print("\n=== AI Decision ===")
        # print(decision)


if __name__ == "__main__":
    main()
