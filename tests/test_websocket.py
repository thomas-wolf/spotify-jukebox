import base64
import hashlib
import os
import socket
import struct
import threading

import pytest

from jukebox.players.websocket import GUID, WebSocket, WebSocketError


def server_frame(opcode: int, payload: bytes, fin: bool = True) -> bytes:
    n = len(payload)
    head = bytes([(0x80 if fin else 0) | opcode])
    if n < 126:
        head += bytes([n])
    elif n < 65536:
        head += bytes([126]) + struct.pack("!H", n)
    else:
        head += bytes([127]) + struct.pack("!Q", n)
    return head + payload


def read_client_frame(sock: socket.socket) -> tuple[int, bytes]:
    def read(n):
        data = b""
        while len(data) < n:
            data += sock.recv(n - len(data))
        return data
    b1, b2 = read(2)
    assert b2 & 0x80, "client frames must be masked"
    n = b2 & 0x7F
    if n == 126:
        (n,) = struct.unpack("!H", read(2))
    elif n == 127:
        (n,) = struct.unpack("!Q", read(8))
    mask = read(4)
    return b1 & 0x0F, bytes(b ^ mask[i % 4] for i, b in enumerate(read(n)))


def make_pair(extra: bytes = b""):
    """A connected WebSocket (client side) and the raw socket of a fake server that already answered the handshake."""
    client, server = socket.socketpair()
    result = {}

    def serve():
        data = b""
        while b"\r\n\r\n" not in data:
            data += server.recv(4096)
        key = [ln.split(b":")[1].strip() for ln in data.split(b"\r\n") if ln.lower().startswith(b"sec-websocket-key")][0]
        accept = base64.b64encode(hashlib.sha1(key + GUID.encode()).digest())
        server.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                       b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n" + extra)
        result["done"] = True

    t = threading.Thread(target=serve)
    t.start()
    ws = WebSocket.handshake(client, "x:1")
    t.join()
    return ws, server


def test_handshake_and_text_roundtrip():
    ws, server = make_pair()
    ws.send_text('{"a": "ä"}')
    assert read_client_frame(server) == (1, '{"a": "ä"}'.encode())
    server.sendall(server_frame(1, b'{"type": "auth_state"}'))
    assert ws.recv_text() == '{"type": "auth_state"}'


def test_message_that_came_with_the_handshake_is_not_lost():
    ws, _ = make_pair(extra=server_frame(1, b"hello"))
    assert ws.recv_text() == "hello"


@pytest.mark.parametrize("size", [125, 126, 70000])
def test_long_messages(size):
    ws, server = make_pair()
    server.sendall(server_frame(1, b"x" * size))
    assert ws.recv_text() == "x" * size
    ws.send_text("y" * size)
    assert read_client_frame(server)[1] == b"y" * size


def test_fragmented_message_and_ping_in_between():
    ws, server = make_pair()
    server.sendall(server_frame(1, b"hel", fin=False) + server_frame(9, b"p") + server_frame(0, b"lo"))
    assert ws.recv_text() == "hello"
    assert read_client_frame(server) == (0xA, b"p")        # pong with the ping's payload


def test_timeout_in_the_middle_of_a_frame_loses_nothing():
    ws, server = make_pair()
    frame = server_frame(1, b"x" * 300)
    server.sendall(frame[:100])
    ws.sock.settimeout(0.05)
    with pytest.raises(TimeoutError):
        ws.recv_text()
    server.sendall(frame[100:])
    assert ws.recv_text() == "x" * 300


def test_close_frame_and_eof_raise():
    ws, server = make_pair()
    server.sendall(server_frame(8, struct.pack("!H", 1000)))
    with pytest.raises(WebSocketError):
        ws.recv_text()
    ws2, server2 = make_pair()
    server2.close()
    with pytest.raises(WebSocketError):
        ws2.recv_text()


def test_handshake_refused():
    client, server = socket.socketpair()
    server.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
    with pytest.raises(WebSocketError, match="403"):
        WebSocket.handshake(client, "x:1")
