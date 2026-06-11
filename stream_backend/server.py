"""server.py — Blood Bowl Live game server (protocol v1).

Plays an endless series of games between two checkpoints on the torch backend
and fans state deltas out over WebSocket per docs/stream-protocol.md.

  python server.py --ckpt-a A_torch.bin --ckpt-b B_torch.bin \
                   [--port 8787] [--pace 0.6] [--record fixture.jsonl] \
                   [--max-games N]

--record writes every broadcast message to a JSONL file (this is how
mock/fixture_match.jsonl is produced). --max-games exits after N games
(use 1 for fixture recording).
"""
import argparse
import asyncio
import json
import time

import random

import websockets

from game import Match

# curated rotation: (home, away) team ids — contrast-heavy matchups for TV
MATCHUPS = [(29, 7), (22, 12), (13, 24), (6, 18), (8, 22), (16, 11),
            (3, 29), (26, 10), (15, 0), (23, 13), (28, 7), (2, 19)]

PROTO = 1


class Hub:
    def __init__(self):
        self.clients = set()
        self.seq = 0
        self.last_snapshot = None
        self.record_fh = None

    def stamp(self, msg):
        self.seq += 1
        msg["v"] = PROTO
        msg["seq"] = self.seq
        return msg

    async def send_one(self, ws, msg):
        try:
            await ws.send(json.dumps(msg))
        except Exception:
            self.clients.discard(ws)

    async def broadcast(self, msg):
        msg = self.stamp(msg)
        if msg["t"] == "snapshot":
            self.last_snapshot = msg
        if self.record_fh:
            self.record_fh.write(json.dumps(msg) + "\n")
            self.record_fh.flush()
        if self.clients:
            data = json.dumps(msg)
            dead = []
            for ws in self.clients:
                try:
                    await ws.send(data)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.clients.discard(ws)


async def client_handler(hub, match, ws):
    hub.clients.add(ws)
    await hub.send_one(ws, {"v": PROTO, "t": "hello", "seq": hub.seq,
                            "proto": PROTO, "server": "bbstream/0.1",
                            "match_id": match.match_id, "sprite_base": "art/"})
    # replay match_start so mid-match joiners get team names/colors
    await hub.send_one(ws, hub.stamp(match.match_start_msg()))
    snap = hub.stamp(match.snapshot_msg())
    hub.last_snapshot = snap
    await hub.send_one(ws, snap)
    try:
        async for raw in ws:
            try:
                m = json.loads(raw)
            except Exception:
                continue
            if m.get("t") == "resync":
                await hub.send_one(ws, hub.stamp(match.snapshot_msg()))
    except Exception:
        pass
    finally:
        hub.clients.discard(ws)


async def game_loop(hub, match, pace, max_games=0):
    games = 0
    await hub.broadcast(match.match_start_msg())
    await hub.broadcast(match.snapshot_msg())
    deltas = 0
    while True:
        msg, end = await asyncio.to_thread(match.step)
        await hub.broadcast(msg)
        deltas += 1
        if deltas % 100 == 0:
            await hub.broadcast(match.snapshot_msg())
        if end:
            await hub.broadcast(end)
            games += 1
            if max_games and games >= max_games:
                return
            await asyncio.sleep(end.get("next_match_in_s", 6))
            deltas = 0
            await hub.broadcast(match.match_start_msg())
            await hub.broadcast(match.snapshot_msg())
            continue
        await asyncio.sleep(pace if match.interesting(msg) else pace / 5)


async def heartbeat(hub):
    while True:
        await asyncio.sleep(15)
        await hub.broadcast({"t": "ping"})


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt-a", required=True)
    ap.add_argument("--ckpt-b", required=True)
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--pace", type=float, default=0.6)
    ap.add_argument("--record", default=None)
    ap.add_argument("--max-games", type=int, default=2)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--macro", action="store_true", help="v5 path-actions env")
    a = ap.parse_args()

    home, away = random.choice(MATCHUPS)
    if random.random() < 0.5:
        home, away = away, home
    match = Match(a.ckpt_a, a.ckpt_b, seed=a.seed, home_team=home, away_team=away,
                  macro=a.macro)
    hub = Hub()
    if a.record:
        hub.record_fh = open(a.record, "w")

    async with websockets.serve(lambda ws: client_handler(hub, match, ws),
                                "0.0.0.0", a.port):
        print(f"bbstream live on :{a.port} (pace {a.pace}s)", flush=True)
        hb = asyncio.create_task(heartbeat(hub))
        try:
            # exits after max_games -> process ends -> systemd respawns with a
            # fresh random matchup (the rotation mechanism)
            await game_loop(hub, match, a.pace, a.max_games)
        finally:
            hb.cancel()
            if hub.record_fh:
                hub.record_fh.close()


if __name__ == "__main__":
    asyncio.run(main())
