"""RDM6300 125 kHz reader on a UART (9600 baud, 14-byte frames).

Frame: 0x02, 10 ASCII hex digits (tag), 2 ASCII hex digits (checksum), 0x03.
The checksum is the XOR of the five tag bytes.
"""

from __future__ import annotations

import logging
import os
import termios
import threading
import time

from ..events import EventBus

log = logging.getLogger(__name__)

STX, ETX = 0x02, 0x03
FRAME_LEN = 14


ID_FORMATS = ("raw", "dec", "float", "hex")


def parse_frame(frame: bytes, id_format: str = "raw") -> str | None:
    """Return the card id or None if the frame is malformed.

    Formats (the first three produce exactly the ids of the Phoniebox v2
    reader, so existing cards keep working):
      raw    12 characters as sent by the reader, tag + checksum: 070067315809
      dec    10 digits, zero padded, last 4 tag bytes:            0006762840
      float  two numbers, like the printed number on the tag:      103,12632
      hex    the 10 tag characters without checksum:               0700673158
    """
    if id_format not in ID_FORMATS:
        raise ValueError(f"id_format must be one of {ID_FORMATS}")
    if len(frame) != FRAME_LEN or frame[0] != STX or frame[-1] != ETX:
        return None
    try:
        tag_hex = frame[1:11].decode("ascii")
        tag = bytes.fromhex(tag_hex)
        checksum = int(frame[11:13].decode("ascii"), 16)
    except ValueError:
        return None
    expected = 0
    for b in tag:
        expected ^= b
    if expected != checksum:
        return None
    if id_format == "raw":
        return frame[1:13].decode("ascii")
    if id_format == "dec":
        return f"{int.from_bytes(tag[1:], 'big'):010d}"
    if id_format == "float":
        return f"{(tag[1] << 8) + tag[2]:d},{(tag[3] << 8) + tag[4]:05d}"
    return tag_hex.upper()


class FrameBuffer:
    """Re-synchronises on STX; feeds out complete frames."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        frames: list[bytes] = []
        for byte in data:
            if byte == STX:
                self._buf = bytearray([byte])
            elif self._buf:
                self._buf.append(byte)
                if byte == ETX or len(self._buf) >= FRAME_LEN:
                    frames.append(bytes(self._buf))
                    self._buf = bytearray()
        return frames


class Rdm6300Reader(threading.Thread):
    """Posts a card event once per presentation, not once per frame."""

    def __init__(self, bus: EventBus, port: str = "/dev/serial0",
                 id_format: str = "raw", release_after: float = 1.0) -> None:
        super().__init__(name="rdm6300", daemon=True)
        self.bus, self.port, self.id_format = bus, port, id_format
        self.release_after = release_after
        self._halt = threading.Event()

    def stop(self) -> None:
        self._halt.set()

    def _open(self) -> int:
        fd = os.open(self.port, os.O_RDONLY | os.O_NOCTTY)
        attrs = termios.tcgetattr(fd)
        attrs[0] = 0                                   # iflag
        attrs[1] = 0                                   # oflag
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[3] = 0                                   # lflag: raw
        attrs[4] = attrs[5] = termios.B9600
        attrs[6][termios.VMIN], attrs[6][termios.VTIME] = 0, 5  # 0.5 s read timeout
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        return fd

    def run(self) -> None:
        while not self._halt.is_set():
            try:
                fd = self._open()
            except OSError as exc:
                log.warning("RDM6300 port %s unavailable: %s", self.port, exc)
                time.sleep(5)
                continue
            buffer, present, last_seen = FrameBuffer(), None, 0.0
            try:
                while not self._halt.is_set():
                    for frame in buffer.feed(os.read(fd, 64)):
                        card = parse_frame(frame, self.id_format)
                        if card is None:
                            continue
                        last_seen = time.monotonic()
                        if card != present:
                            present = card
                            self.bus.post("card", id=card)
                    if present and time.monotonic() - last_seen > self.release_after:
                        present = None  # tag removed; the next presentation counts again
            except OSError:
                log.warning("RDM6300 read error", exc_info=True)
            finally:
                os.close(fd)
