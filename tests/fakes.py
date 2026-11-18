from __future__ import annotations

from typing import Any

from jukebox.players.base import Player, PlayerError


class FakePlayer(Player):
    def __init__(self, name: str = "fake", fail: bool = False) -> None:
        self.name, self.fail = name, fail
        self.calls: list[tuple] = []
        self.playing = False

    def _rec(self, *call: Any) -> None:
        if self.fail:
            raise PlayerError("boom")
        self.calls.append(call)

    def play(self, target): self._rec("play", target); self.playing = True
    def pause(self): self._rec("pause"); self.playing = False
    def resume(self): self._rec("resume"); self.playing = True
    def stop(self): self._rec("stop"); self.playing = False
    def next(self): self._rec("next")
    def prev(self): self._rec("prev")
    def seek(self, seconds): self._rec("seek", seconds)
    def set_volume(self, volume): self._rec("volume", volume)
    def is_playing(self): return self.playing


class FakeMpv:
    """Records commands; returns canned property values."""

    def __init__(self) -> None:
        self.commands: list[tuple] = []
        self.props: dict[str, Any] = {"playlist-pos": 0, "time-pos": 0.0}

    def command(self, *args: Any) -> Any:
        self.commands.append(args)
        if args[0] == "get_property":
            return self.props.get(args[1])
        return None

    def close(self) -> None:
        self.commands.append(("close",))


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now
