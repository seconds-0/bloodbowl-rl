"""Local play server: HTTP for the web UI plus one websocket, bound to loopback only.

One process runs one human game at a time. Several browser tabs may watch it;
every applied step is broadcast as playback frames followed by a state
snapshot. The server never builds engine actions: clients submit action ids
from the legal list of the current state version.

Websocket messages are JSON objects {"v": 1, "t": <type>, ...}; a client may
add "rid" and gets it echoed on the direct reply.

  client -> server   lobby, new_game {options}, resync, leave_game,
                     submit {state_version, action_id, follow?},
                     submit_path {state_version, player, squares},
                     path_odds {state_version, squares}, ready {state_version},
                     view {step}, flag {step, reasons, note},
                     survey {answers}, replay_flag {index}
  server -> client   hello, lobby, frames {frames}, state {snapshot},
                     path_odds, clock, view, flagged, surveyed, replay,
                     error {reason, state_version}
"""
from __future__ import annotations

import asyncio
import http
import json
import logging
import mimetypes
import os
import threading

from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.http11 import Response

from . import game as G

PROTOCOL = 1
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
LOOPBACK = ("127.0.0.1", "localhost", "::1")
log = logging.getLogger("play_harness.server")


def lobby_payload(checkpoint_dirs=None):
    cks = G.list_checkpoints(checkpoint_dirs)
    default = next((c["path"] for c in cks if c["path"] == G.DEFAULT_CHECKPOINT and c["ok"]),
                   next((c["path"] for c in cks if c["ok"]), None))
    return {"checkpoints": [{k: c[k] for k in ("path", "label", "sha8", "ok", "error", "name",
                                                "step")} for c in cks],
            "teams": G.team_list(), "default_checkpoint": default,
            "defaults": {"roster_mode": "random", "human_side": "home", "mode": "sample",
                         "think_ms": 600, "clock_mode": "display", "clock_seconds": 240},
            "limits": {"think_max_ms": G.THINK_MAX_MS, "clock_min": G.CLOCK_MIN_SECONDS,
                       "clock_max": G.CLOCK_MAX_SECONDS, "seed_max": G.SEED_MAX},
            "flag_reasons": list(G.FLAG_REASONS)}


class PlayServer:
    def __init__(self, host="127.0.0.1", port=8790, web_dir=WEB_DIR, checkpoint_dirs=None,
                 games_dir=G.GAMES_DIR, policy_loader=None, now=None, save_records=True):
        if host not in LOOPBACK:
            raise ValueError(f"refusing to bind {host!r}: the play server is loopback only")
        self.host = host
        self.port = port
        self.web_dir = web_dir
        self.checkpoint_dirs = checkpoint_dirs
        self.games_dir = games_dir
        self.policy_loader = policy_loader
        self.now = now
        self.save_records = save_records
        self.game = None
        self.clients = set()
        self.server = None
        self._work = threading.Lock()
        # Commands, game replacement and clock expiry run one at a time, and each
        # publishes before the next starts, so clients see states in order.
        self._dispatch_lock = asyncio.Lock()
        self._clock_task = None

    # ---- HTTP ------------------------------------------------------------
    def process_request(self, connection, request):
        path = request.path.split("?", 1)[0]
        if path == "/ws":
            # A page on another site must not drive the local game: only this
            # server's own loopback origins (or no Origin, as non-browser
            # clients send) may open the websocket.
            origin = request.headers.get("Origin")
            allowed = {f"http://{h}:{self.port}" for h in ("127.0.0.1", "localhost", "[::1]")}
            if origin is not None and origin not in allowed:
                return self._respond(403, b"origin not allowed", "text/plain; charset=utf-8")
            return None
        if path == "/health":
            return self._respond(200, b'{"ok": true}', "application/json")
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.normpath(os.path.join(self.web_dir, rel))
        if not full.startswith(os.path.normpath(self.web_dir) + os.sep) or not os.path.isfile(full):
            return self._respond(404, b"not found", "text/plain; charset=utf-8")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            return self._respond(200, f.read(), ctype)

    @staticmethod
    def _respond(status, body, ctype):
        # No framing by other pages (clickjacking), no MIME sniffing, no referrer.
        headers = Headers([("Content-Type", ctype), ("Content-Length", str(len(body))),
                           ("Cache-Control", "no-store"), ("Connection", "close"),
                           ("Content-Security-Policy", "frame-ancestors 'none'"),
                           ("X-Frame-Options", "DENY"), ("X-Content-Type-Options", "nosniff"),
                           ("Referrer-Policy", "no-referrer")])
        return Response(status, http.HTTPStatus(status).phrase, headers, body)

    # ---- websocket -------------------------------------------------------
    async def _send(self, ws, payload):
        try:
            await ws.send(json.dumps({"v": PROTOCOL, **payload}, separators=(",", ":")))
        except Exception:  # noqa: BLE001 - a closed tab must not break the game
            pass

    async def _broadcast(self, payload):
        text = json.dumps({"v": PROTOCOL, **payload}, separators=(",", ":"))
        for ws in list(self.clients):
            try:
                await ws.send(text)
            except Exception:  # noqa: BLE001
                self.clients.discard(ws)

    async def _run(self, fn, *args):
        def locked():
            with self._work:
                return fn(*args)
        return await asyncio.to_thread(locked)

    async def _publish_game(self):
        game = self.game
        if game is None:
            return
        frames, snapshot = await self._run(lambda: (game.take_frames(), game.snapshot()))
        if frames:
            await self._broadcast({"t": "frames", "frames": frames})
        await self._broadcast({"t": "state", "snapshot": snapshot})

    async def handler(self, ws):
        self.clients.add(ws)
        try:
            hello = {"t": "hello", "protocol": PROTOCOL, "has_game": self.game is not None}
            await self._send(ws, hello)
            if self.game is not None:
                snap = await self._run(self.game.snapshot)
                await self._send(ws, {"t": "state", "snapshot": snap})
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                    if not isinstance(msg, dict):
                        raise ValueError("not an object")
                except ValueError:
                    await self._send(ws, {"t": "error", "reason": "bad_json"})
                    continue
                try:
                    async with self._dispatch_lock:
                        await self.dispatch(ws, msg)
                except G.OptionError as exc:
                    await self._send(ws, {"t": "error", "reason": str(exc), "rid": msg.get("rid")})
                except Exception as exc:  # noqa: BLE001
                    log.exception("message failed")
                    await self._send(ws, {"t": "error", "reason": "server_error",
                                          "detail": f"{type(exc).__name__}: {exc}",
                                          "rid": msg.get("rid")})
        finally:
            self.clients.discard(ws)

    async def dispatch(self, ws, msg):
        t = msg.get("t")
        rid = msg.get("rid")
        game = self.game
        if t == "lobby":
            payload = await self._run(lobby_payload, self.checkpoint_dirs)
            payload.update({"t": "lobby", "rid": rid, "has_game": game is not None,
                            "game_options": game.options if game else None})
            await self._send(ws, payload)
        elif t == "new_game":
            checkpoints = await self._run(G.list_checkpoints, self.checkpoint_dirs)
            opts = G.normalize_options(msg.get("options"), n_teams=30, checkpoints=checkpoints)
            if game is not None:
                await self._run(game.abandon)

            def build():
                kw = {"games_dir": self.games_dir, "save_records": self.save_records}
                if self.policy_loader:
                    kw["policy_loader"] = self.policy_loader
                if self.now:
                    kw["now"] = self.now
                return G.GameController(opts, **kw)

            self.game = await self._run(build)
            await self._broadcast({"t": "game_started", "rid": rid,
                                   "header": self.game.header()})
            await self._publish_game()
        elif t == "leave_game":
            if game is not None:
                await self._run(game.abandon)
            self.game = None
            await self._broadcast({"t": "game_closed", "rid": rid})
        elif game is None:
            await self._send(ws, {"t": "error", "reason": "no_game", "rid": rid})
        elif msg.get("game_id") not in (None, game.game_id):
            # A request built for an earlier game must not act on this one, even
            # when its state version happens to match.
            await self._send(ws, {"t": "error", "reason": "stale_game", "rid": rid,
                                  "game_id": game.game_id})
        elif t == "resync":
            await self._send(ws, {"t": "state", "rid": rid, "snapshot": await self._run(game.snapshot)})
        elif t in ("submit", "submit_path"):
            fn = game.submit if t == "submit" else game.submit_path
            res = await self._run(fn, msg)
            if not res.get("ok"):
                await self._send(ws, {"t": "error", "reason": res.get("error"), "rid": rid,
                                      "state_version": res.get("state_version")})
                await self._send(ws, {"t": "state", "snapshot": await self._run(game.snapshot)})
                return
            await self._send(ws, {"t": "ack", "rid": rid, "state_version": res["state_version"],
                                  "steps_applied": res.get("steps_applied")})
            await self._publish_game()
        elif t == "path_odds":
            res = await self._run(game.path_odds, msg)
            await self._send(ws, {"t": "path_odds", "rid": rid, **res})
        elif t == "ready":
            info = await self._run(game.client_ready, msg.get("state_version"))
            await self._send(ws, {"t": "clock", "rid": rid, "clock": info})
        elif t == "view":
            step = msg.get("step")
            view = await self._run(game.view, step) if isinstance(step, int) else None
            await self._send(ws, {"t": "view", "rid": rid, "view": view})
        elif t == "flag":
            res = await self._run(game.flag, msg)
            await self._broadcast({"t": "flagged", "rid": rid, **res})
        elif t == "survey":
            res = await self._run(game.survey, msg)
            await self._send(ws, {"t": "surveyed", "rid": rid, **res})
        elif t == "replay_flag":
            res = await self._run(game.replay_flag, msg.get("index"))
            await self._send(ws, {"t": "replay", "rid": rid, **res})
        else:
            await self._send(ws, {"t": "error", "reason": "unknown_message", "rid": rid})

    async def _clock_loop(self):
        while True:
            await asyncio.sleep(0.25)
            game = self.game
            if game is None or game.options["clock_mode"] != "soft":
                continue
            async with self._dispatch_lock:
                if self.game is not game:
                    continue
                try:
                    res = await self._run(game.tick_clock)
                except Exception:  # noqa: BLE001
                    log.exception("clock tick failed")
                    continue
                if res and res.get("ok"):
                    await self._broadcast({"t": "clock_expired", "clock_steps": res["clock_steps"]})
                    await self._publish_game()

    async def start(self):
        self.server = await serve(self.handler, self.host, self.port,
                                  process_request=self.process_request,
                                  max_size=2 ** 20, ping_interval=20, ping_timeout=60)
        if self.port == 0:
            self.port = self.server.sockets[0].getsockname()[1]
        self._clock_task = asyncio.create_task(self._clock_loop())
        return self

    async def close(self):
        if self._clock_task:
            self._clock_task.cancel()
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        if self.game is not None:
            self.game.abandon()

    @property
    def url(self):
        return f"http://{self.host}:{self.port}/"
