"""Keyboard-style USB RFID readers (they "type" the card number plus Enter)."""

from __future__ import annotations

import logging
import threading
import time

from ..events import EventBus

log = logging.getLogger(__name__)


class KeyAssembler:
    """Collects key names ('KEY_1', 'KEY_A', ...) until KEY_ENTER."""

    def __init__(self) -> None:
        self._chars: list[str] = []

    def feed(self, key_name: str) -> str | None:
        if key_name in ("KEY_ENTER", "KEY_KPENTER"):
            card, self._chars = "".join(self._chars), []
            return card or None
        if key_name.startswith("KEY_KP") and key_name[6:].isdigit():
            self._chars.append(key_name[6:])
        elif key_name.startswith("KEY_") and len(key_name) == 5 and key_name[4].isalnum():
            self._chars.append(key_name[4])
        # everything else (shift, ...) is ignored
        return None


class UsbReader(threading.Thread):
    def __init__(self, bus: EventBus, device_name: str) -> None:
        super().__init__(name="usb-reader", daemon=True)
        self.bus, self.device_name = bus, device_name
        self._halt = threading.Event()

    def stop(self) -> None:
        self._halt.set()

    def _open(self):
        import evdev  # optional dependency, only needed for this reader

        for path in evdev.list_devices():
            dev = evdev.InputDevice(path)
            if self.device_name.lower() in dev.name.lower():
                dev.grab()  # keep the digits out of the console
                return dev
        return None

    def run(self) -> None:
        import evdev

        while not self._halt.is_set():
            try:
                dev = self._open()
            except Exception:
                log.exception("cannot open USB reader")
                dev = None
            if dev is None:
                log.warning("USB reader %r not found, retrying", self.device_name)
                time.sleep(5)
                continue
            log.info("USB reader connected: %s", dev.name)
            assembler = KeyAssembler()
            try:
                for event in dev.read_loop():
                    if event.type == evdev.ecodes.EV_KEY and event.value == 1:
                        name = evdev.ecodes.KEY.get(event.code, "")
                        if isinstance(name, list):
                            name = name[0]
                        card = assembler.feed(name)
                        if card:
                            self.bus.post("card", id=card)
            except OSError:
                log.warning("USB reader disconnected")
            finally:
                try:
                    dev.close()
                except OSError:
                    pass
