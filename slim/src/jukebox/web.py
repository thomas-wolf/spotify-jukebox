"""Small web interface: assign cards, see what plays, basic controls.

Standard library only. It runs in a thread of the jukebox process; anything that touches the players is
posted to the event bus so it runs on the main loop. There is no authentication: bind it to a trusted network.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from . import events as ev
from .config import Card, save_cards
from .importer import normalize_spotify
from ._page import PAGE

log = logging.getLogger(__name__)

AUDIO_EXT = {".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".m4b", ".aac", ".wav", ".wma", ".aiff", ".ac3"}
MAX_BODY = 64 * 1024
_ARG_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class BadRequest(ValueError):
    pass


def validate_card(actions, card_id: str, data: dict) -> Card:
    card_id = (card_id or "").strip()
    if not card_id or len(card_id) > 64:
        raise BadRequest("card id is required (max 64 characters)")
    name = str(data.get("name", "")).strip()[:100]
    play, action = (data.get("play") or "").strip(), (data.get("action") or "").strip()
    if bool(play) == bool(action):
        raise BadRequest("give either a target to play or an action")
    if action:
        if action not in actions:
            raise BadRequest(f"unknown action {action!r}")
        args = data.get("args") or {}
        if not isinstance(args, dict) or not all(
            _ARG_KEY.match(str(k)) and isinstance(v, (int, float, str, bool)) for k, v in args.items()
        ):
            raise BadRequest("invalid arguments")
        return Card(card_id, name, action=action, args=dict(args))
    if play.startswith(("http://", "https://", "spotify:")):
        uri = normalize_spotify(play)
        if uri is None:
            raise BadRequest("not a recognisable Spotify link or URI")
        return Card(card_id, name, play=uri)
    scheme, _, rest = play.partition(":")
    rest = rest.strip()
    if scheme not in ("folder", "file") or rest.startswith("/"):
        raise BadRequest("target must be a Spotify link, folder:<path> or file:<path>")
    rest = rest.strip("/")
    if not rest or ".." in Path(rest).parts:
        raise BadRequest("target must be a Spotify link, folder:<path> or file:<path>")
    return Card(card_id, name, play=f"{scheme}:{rest}")


def list_folders(root: Path, depth: int = 3, limit: int = 2000) -> list[str]:
    found: list[str] = []
    if not root.is_dir():
        return found
    base = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        if len(d.parts) - base >= depth:
            dirnames[:] = []
        dirnames[:] = sorted(n for n in dirnames if not n.startswith("."))
        if d != root and any(Path(f).suffix.lower() in AUDIO_EXT for f in filenames):
            found.append("/".join(d.parts[base:]))
        if len(found) >= limit:
            break
    return sorted(found, key=str.lower)


class Web:
    def __init__(self, app, cards_path: Path, local_root: Path, host: str, port: int) -> None:
        self.app, self.cards_path, self.local_root = app, cards_path, local_root
        self.lock = threading.Lock()
        self.state = {"playing": False, "target": None, "name": "", "volume": app.players.volume,
                      "error": "", "last_card": None, "last_card_time": 0.0}
        for name in (ev.CARD, ev.CARD_UNKNOWN, ev.PLAYING, ev.PAUSED, ev.STOPPED, ev.VOLUME, ev.ERROR):
            app.bus.subscribe(name, self._on_event)
        self.server = ThreadingHTTPServer((host, port), self._handler())
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.1), name="web", daemon=True)

    @property
    def port(self) -> int:
        return self.server.server_address[1]

    def start(self) -> None:
        self.thread.start()
        log.info("web interface on port %d", self.port)

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    # -- state, fed by bus events (runs on the main loop) -----------------------
    def _on_event(self, e) -> None:
        with self.lock:
            s = self.state
            if e.name in (ev.CARD, ev.CARD_UNKNOWN):
                s["last_card"], s["last_card_time"] = e.data.get("id"), time.time()
            elif e.name == ev.PLAYING:
                s["playing"], s["error"] = True, ""
                if e.data.get("target"):
                    s["target"], s["name"] = e.data["target"], e.data.get("name", "")
            elif e.name == ev.PAUSED:
                s["playing"] = False
            elif e.name == ev.STOPPED:
                s["playing"], s["target"], s["name"] = False, None, ""
            elif e.name == ev.VOLUME:
                s["volume"] = e.data["value"]
            elif e.name == ev.ERROR:
                s["error"] = e.data.get("message", "")

    def snapshot(self) -> dict:
        with self.lock:
            s = dict(self.state)
        s["max_volume"] = self.app.max_volume
        last = s["last_card"]
        card = next((c for k, c in list(self.app.cards.items()) if last and k.lower() == last.lower()), None)
        s["last_card_known"] = card is not None
        s["last_card_name"] = card.name if card else ""
        return s

    def cards_json(self) -> list[dict]:
        return [{"id": c.id, "name": c.name, "play": c.play, "action": c.action, "args": c.args}
                for c in list(self.app.cards.values())]

    def save(self) -> None:
        save_cards(self.cards_path, self.app.cards.values())

    # -- http ------------------------------------------------------------------
    def _handler(self):
        web = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "jukebox"

            def log_message(self, fmt, *args):
                log.debug("web %s", fmt % args)

            def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, obj, code: int = 200) -> None:
                self._send(code, json.dumps(obj).encode())

            def _body(self) -> dict:
                if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                    raise BadRequest("Content-Type must be application/json")
                n = int(self.headers.get("Content-Length") or 0)
                if n > MAX_BODY:
                    raise BadRequest("request too large")
                try:
                    data = json.loads(self.rfile.read(n) or b"{}")
                except json.JSONDecodeError:
                    raise BadRequest("invalid JSON") from None
                if not isinstance(data, dict):
                    raise BadRequest("JSON object expected")
                return data

            def _route(self, method: str) -> None:
                path = self.path.split("?", 1)[0]
                try:
                    if method == "GET":
                        if path == "/":
                            return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
                        if path == "/api/state":
                            return self._json(web.snapshot())
                        if path == "/api/cards":
                            return self._json(web.cards_json())
                        if path == "/api/folders":
                            return self._json(list_folders(web.local_root))
                        if path == "/api/actions":
                            return self._json(sorted(web.app.actions))
                    elif path == "/api/action" and method == "POST":
                        data = self._body()
                        name = str(data.get("name", ""))
                        if name not in web.app.actions:
                            raise BadRequest(f"unknown action {name!r}")
                        args = data.get("args") or {}
                        if not isinstance(args, dict):
                            raise BadRequest("invalid arguments")
                        web.app.bus.post(ev.ACTION, name=name, args=args)
                        return self._json({"ok": True})
                    elif path.startswith("/api/cards/"):
                        rest = path[len("/api/cards/"):]
                        if method == "POST" and rest.endswith("/play"):
                            card_id = unquote(rest[:-len("/play")])
                            self._body()
                            web.app.bus.post(ev.CARD, id=card_id)
                            return self._json({"ok": True})
                        card_id = unquote(rest)
                        if method == "PUT":
                            card = validate_card(web.app.actions, card_id, self._body())
                            web.app.set_card(card)
                            web.save()
                            return self._json({"ok": True})
                        if method == "DELETE":
                            if not web.app.remove_card(card_id):
                                return self._json({"error": "no such card"}, 404)
                            web.save()
                            return self._json({"ok": True})
                    return self._json({"error": "not found"}, 404)
                except BadRequest as exc:
                    self._json({"error": str(exc)}, 400)
                except OSError as exc:
                    log.error("web: %s", exc)
                    self._json({"error": f"could not save: {exc}"}, 500)
                except Exception:
                    log.exception("web request failed")
                    self._json({"error": "internal error"}, 500)

            def do_GET(self): self._route("GET")
            def do_POST(self): self._route("POST")
            def do_PUT(self): self._route("PUT")
            def do_DELETE(self): self._route("DELETE")

        return Handler
