# src/mgba/control_server_injector.py
from __future__ import annotations
import socket
from dataclasses import dataclass
from typing import Iterable, Optional

@dataclass(frozen=True)
class MGBAPress:
    keys: Iterable[str]   # ["A"] or ["UP","LEFT"]
    frames: int = 30       # how many frames to hold

class MGBASocketInjector:
    """
    Python hosts a server (7778). Lua connects to it.
    Then we send newline-delimited commands like: b"A 2\n" or b"UP+LEFT 6\n".
    """
    def __init__(self, host: str = "127.0.0.1", port: int = 7778):
        self.host = host
        self.port = port
        self._server: Optional[socket.socket] = None
        self._conn: Optional[socket.socket] = None

    def start(self) -> None:
        if self._server:
            return
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((self.host, self.port))
        s.listen(1)
        self._server = s
        print(f"[control] listening on {self.host}:{self.port} ...")

    def accept_if_needed(self) -> bool:
        """
        Accept Lua connection once. Blocks until connected the first time.
        Call this BEFORE starting mGBA Lua script (or right after), and it will connect quickly.
        """
        assert self._server is not None, "call start() first"
        if self._conn:
            return True
        conn, addr = self._server.accept()
        self._conn = conn
        print(f"[control] lua connected from {addr}")
        return True

    def send_press(self, press: MGBAPress) -> None:
        if not self._conn:
            raise RuntimeError("Lua control connection not established yet (call accept_if_needed())")
        keys_part = "+".join(press.keys) if press.keys else "NONE"
        line = f"{keys_part} {int(press.frames)}\n".encode("utf-8")
        self._conn.sendall(line)
