"""A minimal WebSocket client (RFC 6455) on the standard library: text frames in both directions, ping/pong,
close, fragmented messages. No TLS, no extensions, no compression; enough for a local JSON API such as Soloist's.
"""

from __future__ import annotations

import base64
import hashlib
import os
import socket
import struct

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
OP_CONT, OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA
MAX_MESSAGE = 4 * 1024 * 1024


class WebSocketError(OSError):
    """Handshake failed, protocol violation or connection closed."""


class WebSocket:
    def __init__(self, sock: socket.socket, leftover: bytes = b"") -> None:
        self.sock = sock
        self._buf = leftover
        self._partial = b""
        self._started = False

    # -- connect -----------------------------------------------------------------
    @classmethod
    def connect(cls, host: str, port: int, path: str = "/", timeout: float = 5.0) -> "WebSocket":
        sock = socket.create_connection((host, port), timeout=timeout)
        try:
            return cls.handshake(sock, f"{host}:{port}", path)
        except BaseException:
            sock.close()
            raise

    @classmethod
    def handshake(cls, sock: socket.socket, host: str, path: str = "/") -> "WebSocket":
        key = base64.b64encode(os.urandom(16)).decode()
        request = (f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        sock.sendall(request.encode())
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                raise WebSocketError("connection closed during the handshake")
            data += chunk
            if len(data) > 65536:
                raise WebSocketError("handshake response too long")
        head, _, rest = data.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        if len(lines[0].split()) < 2 or lines[0].split()[1] != "101":
            raise WebSocketError(f"handshake refused: {lines[0]}")
        headers = {k.strip().lower(): v.strip() for k, _, v in (ln.partition(":") for ln in lines[1:])}
        expected = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
        if headers.get("sec-websocket-accept") != expected:
            raise WebSocketError("handshake: wrong Sec-WebSocket-Accept")
        return cls(sock, rest)

    # -- sending -----------------------------------------------------------------
    def _send(self, opcode: int, payload: bytes) -> None:
        n = len(payload)
        if n < 126:
            header = struct.pack("!BB", 0x80 | opcode, 0x80 | n)
        elif n < 65536:
            header = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, n)
        else:
            header = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, n)
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def send_text(self, text: str) -> None:
        self._send(OP_TEXT, text.encode())

    def close(self) -> None:
        try:
            self._send(OP_CLOSE, struct.pack("!H", 1000))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    # -- receiving ---------------------------------------------------------------
    # A socket timeout (OSError) can interrupt any recv(); nothing is consumed from the buffer until a whole
    # frame is there, and half-received fragmented messages are kept, so the next call just carries on.
    def _parse(self) -> tuple[bool, int, bytes] | None:
        buf = self._buf
        if len(buf) < 2:
            return None
        fin, opcode = bool(buf[0] & 0x80), buf[0] & 0x0F
        masked, length, pos = bool(buf[1] & 0x80), buf[1] & 0x7F, 2
        if length == 126:
            if len(buf) < 4:
                return None
            (length,), pos = struct.unpack("!H", buf[2:4]), 4
        elif length == 127:
            if len(buf) < 10:
                return None
            (length,), pos = struct.unpack("!Q", buf[2:10]), 10
        if length > MAX_MESSAGE:
            raise WebSocketError("message too large")
        mask = None
        if masked:                                       # servers do not mask, but accept it
            if len(buf) < pos + 4:
                return None
            mask, pos = buf[pos:pos + 4], pos + 4
        if len(buf) < pos + length:
            return None
        payload = buf[pos:pos + length]
        if mask:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._buf = buf[pos + length:]
        return fin, opcode, payload

    def _frame(self) -> tuple[bool, int, bytes]:
        while True:
            parsed = self._parse()
            if parsed is not None:
                return parsed
            chunk = self.sock.recv(65536)
            if not chunk:
                raise WebSocketError("connection closed")
            self._buf += chunk

    def recv_text(self) -> str:
        """The next text message; answers pings itself. Raises WebSocketError when the connection ends, and the
        socket's timeout (an OSError) when none arrives in time; call again to continue."""
        while True:
            fin, opcode, payload = self._frame()
            if opcode == OP_PING:
                self._send(OP_PONG, payload)
            elif opcode == OP_PONG:
                continue
            elif opcode == OP_CLOSE:
                try:
                    self._send(OP_CLOSE, payload[:2])
                except OSError:
                    pass
                raise WebSocketError("closed by the server")
            elif opcode in (OP_TEXT, OP_BINARY):
                self._partial = payload
                self._started = True
            elif opcode == OP_CONT and self._started:
                self._partial += payload
                if len(self._partial) > MAX_MESSAGE:
                    raise WebSocketError("message too large")
            else:
                raise WebSocketError(f"unexpected frame (opcode {opcode})")
            if fin and opcode in (OP_TEXT, OP_BINARY, OP_CONT):
                message, self._partial, self._started = self._partial, b"", False
                return message.decode()
