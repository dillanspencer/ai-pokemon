from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Callable, Iterable, Iterator, Optional

from .helpers.receiver_parser import parse_ndjson_line

HOST_DEFAULT = "127.0.0.1"
PORT_DEFAULT = 7777


def recv_line(sock: socket.socket, buffer: bytearray) -> Optional[str]:
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


def stream_parsed_frames(
    host: str = HOST_DEFAULT,
    port: int = PORT_DEFAULT,
) -> Iterator[object]:
    """
    Blocking generator.
    Yields ParsedFrame objects (whatever parse_ndjson_line returns on success).
    Skips bad/incomplete JSON lines.
    """
    print(f"Listening on {host}:{port} ...")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen(1)

        conn, addr = server.accept()
        with conn:
            print(f"Client connected from {addr}")
            buf = bytearray()

            while True:
                line = recv_line(conn, buf)
                if line is None:
                    print("Client disconnected.")
                    return

                parsed = parse_ndjson_line(line)
                if parsed is None:
                    tail = line[-120:] if len(line) > 120 else line
                    print(f"Bad JSON line (or incomplete). Tail: {tail!r}")
                    continue

                yield parsed