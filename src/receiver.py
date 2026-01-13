import socket
from .helpers.receiver_parser import parse_ndjson_line
from .models.pokemon import load_move_db

HOST = "127.0.0.1"
PORT = 7777

move_db = load_move_db("src/models/moves.json")


def recv_line(sock: socket.socket, buffer: bytearray):
    while True:
        nl = buffer.find(b"\n")
        if nl != -1:
            line = buffer[:nl]
            del buffer[: nl + 1]
            return line.decode("utf-8", errors="replace").rstrip("\r")
        chunk = sock.recv(4096)
        if not chunk:
            return None
        buffer.extend(chunk)


def main():
    print(f"Listening on {HOST}:{PORT} ...")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(1)

        conn, addr = server.accept()
        with conn:
            print(f"Client connected from {addr}")
            buf = bytearray()

            while True:
                line = recv_line(conn, buf)
                if line is None:
                    print("Client disconnected.")
                    break

                parsed = parse_ndjson_line(line)
                print(parsed)
                if parsed is None:
                    tail = line[-120:] if len(line) > 120 else line
                    print(f"Bad JSON line (or incomplete). Tail: {tail!r}")
                    continue

                st = parsed.state
                print(
                    f"\nFrame={st.frame} base=0x{st.party_base:08X} "
                    f"[{st.flags.compact()}] "
                    f"cb2=0x{st.signals.hex_cb2()} cb1=0x{st.signals.hex_cb1()} "
                    f"battleTypeFlags={st.signals.battle_type_flags} "
                    f"s1={st.signals.script1_active} s2={st.signals.script2_active} "
                    f"fade={st.signals.palette_fade_active}"
                )

                for mon in parsed.party:
                    if not mon.is_present:
                        print(f"  Slot {mon.slot}: (empty)")
                        continue

                    g = mon.data.growth
                    a = mon.data.attacks
                    m = mon.data.misc

                    print(" ", mon.summary(move_db))
                    print(f"    OT={mon.ot_name} Nick={mon.nickname} Lang={mon.language} Markings={mon.markings}")
                    print(f"    Exp={g.exp} Friendship={g.friendship} Pokerus=0x{m.pokerus:02X}")
                    print(f"    EVs: {mon.data.evs}")
                    print(f"    IVs: {m.ivs}")
                    print(f"    Origins: ball={m.origins.ball_id} game={m.origins.game_id} lvl_met={m.origins.level_met} hatched={m.origins.hatched}")
                    print(f"    Moves: " + ", ".join([f"{mv.move_id}(pp{mv.pp})" for mv in a.moves if mv.move_id != 0]))
                    print(f"    RibbonsBits=0x{m.ribbons_obedience:08X}")


if __name__ == "__main__":
    main()
