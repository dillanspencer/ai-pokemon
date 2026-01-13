import json
import socket
from .models.pokemon import parse_party_bytes, load_move_db

HOST = "127.0.0.1"
PORT = 7777

move_db = load_move_db("src/models/moves.json")

def recv_line(sock: socket.socket, buffer: bytearray):
    while True:
        nl = buffer.find(b"\n")
        if nl != -1:
            line = buffer[:nl]
            del buffer[: nl + 1]
            return line.decode("utf-8", errors="replace")
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

                msg = json.loads(line)
                party_hex = msg["party_hex"]
                party_base = msg.get("party_base", 0)
                frame = msg.get("frame", 0)

                party_bytes = bytes.fromhex(party_hex)
                mons = parse_party_bytes(party_bytes)

                print(f"\nFrame={frame} base=0x{party_base:08X}")
                for mon in mons:
                    if not mon.is_present:
                        print(f"  Slot {mon.slot}: (empty)")
                        continue

                    g = mon.data.growth
                    a = mon.data.attacks
                    m = mon.data.misc
                    ev = mon.data.evs
                    iv = m.ivs

                    print(" ", mon.summary(move_db))
                    print(f"    OT={mon.ot_name} Nick={mon.nickname} Lang={mon.language} Markings={mon.markings}")
                    print(f"    Exp={g.exp} Friendship={g.friendship} Pokerus=0x{m.pokerus:02X}")
                    print(f"    EVs: {ev}")
                    print(f"    IVs: {iv}")
                    print(f"    Origins: ball={m.origins.ball_id} game={m.origins.game_id} lvl_met={m.origins.level_met} hatched={m.origins.hatched}")
                    print(f"    Moves: " + ", ".join([f"{mv.move_id}(pp{mv.pp})" for mv in a.moves if mv.move_id != 0]))
                    print(f"    RibbonsBits=0x{m.ribbons_obedience:08X}")

if __name__ == "__main__":
    main()
