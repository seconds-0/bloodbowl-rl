"""The loopback play server: HTTP static files, websocket protocol, a full game."""
import asyncio
import json
import os
import random
import socket

import pytest
import torch
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from play_harness import game as G
from play_harness.server import WEB_DIR, PlayServer

torch.set_num_threads(2)

ZERO_KEYS = ("illegal", "projection_collision", "error_episodes", "engine_rejections",
             "precheck_collisions", "api_rejections")
GAME_OPTIONS = {"seed": 11, "clock_mode": "off", "roster_mode": "both", "human_team": 6,
                "bot_team": 7, "human_side": "home", "think_ms": 0}


def _run(coro, timeout=600):
    return asyncio.run(asyncio.wait_for(coro, timeout))


def _loader(best_policy):
    def load(path, kernel="native"):
        return best_policy
    return load


async def _serve(tmp_path, best_policy, body, **kw):
    kw.setdefault("port", 0)
    server = PlayServer(games_dir=str(tmp_path / "games"), policy_loader=_loader(best_policy),
                        **kw)
    await server.start()
    try:
        return await body(server)
    finally:
        await server.close()


async def _http_get(port, path):
    """Raw HTTP/1.1 GET so the path reaches the server exactly as written."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode())
    await writer.drain()
    data = await asyncio.wait_for(reader.read(), 10)
    writer.close()
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split(" ")[1])
    headers = {}
    for line in lines[1:]:
        k, _, v = line.partition(":")
        headers[k.strip().lower()] = v.strip()
    return status, headers, body


class Client:
    def __init__(self, ws):
        self.ws = ws

    async def send(self, **msg):
        await self.ws.send(json.dumps({"v": 1, **msg}))

    async def send_raw(self, text):
        await self.ws.send(text)

    async def recv(self, timeout=120):
        msg = json.loads(await asyncio.wait_for(self.ws.recv(), timeout))
        assert msg.get("v") == 1, msg
        return msg

    async def expect(self, t, timeout=120):
        msg = await self.recv(timeout)
        assert msg["t"] == t, f"expected {t}, got {msg['t']}: {str(msg)[:300]}"
        return msg

    async def frames_then_state(self):
        """After an ack: at most one frames message, then exactly one state message."""
        frames = []
        msg = await self.recv()
        if msg["t"] == "frames":
            frames = msg["frames"]
            assert frames, "an empty frames message was sent"
            msg = await self.recv()
        assert msg["t"] == "state", f"expected state, got {msg['t']}"
        return frames, msg["snapshot"]


def _connect(server, **kw):
    return connect(f"ws://127.0.0.1:{server.port}/ws", proxy=None, max_size=None, **kw)


async def _hello(ws):
    client = Client(ws)
    hello = await client.expect("hello")
    return client, hello


async def _new_game(client, options=GAME_OPTIONS, rid="g1"):
    await client.send(t="new_game", rid=rid, options=options)
    started = await client.expect("game_started")
    assert started["rid"] == rid
    frames, snapshot = await client.frames_then_state()
    return started, frames, snapshot


def _legal_ids(legal):
    ids = [a["id"] for a in legal["actions"]]
    ids += [row[0] for row in (legal.get("compact") or {}).get("SETUP_PLACE", [])]
    return ids


def _check_policy_view(frame):
    view = frame.get("view")
    assert isinstance(view, dict), frame["step"]
    alts = view["alternatives"]
    assert alts, frame["step"]
    ps = [a["p"] for a in alts]
    assert all(0.0 <= p <= 1.0 for p in ps), ps
    assert sum(ps) <= 1.0 + 1e-4, ps
    assert sum(1 for a in alts if a["taken"]) == 1, alts


# ---- binding and HTTP ------------------------------------------------------
@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "::", "example.com"])
def test_server_refuses_non_loopback_hosts(host):
    with pytest.raises(ValueError, match="loopback only"):
        PlayServer(host=host, port=0)


def test_server_socket_is_bound_to_loopback(tmp_path, best_policy):
    async def body(server):
        assert server.port != 0
        names = [sock.getsockname() for sock in server.server.sockets]
        assert names
        assert all(name[0] == "127.0.0.1" for name in names), names
        assert server.url == f"http://127.0.0.1:{server.port}/"
    _run(_serve(tmp_path, best_policy, body))


def test_http_health_index_and_path_escapes(tmp_path, best_policy):
    async def body(server):
        status, headers, content = await _http_get(server.port, "/health")
        assert status == 200
        assert headers["content-type"] == "application/json"
        assert json.loads(content) == {"ok": True}
        index = os.path.join(WEB_DIR, "index.html")
        if os.path.isfile(index):
            status, headers, content = await _http_get(server.port, "/")
            assert status == 200
            assert headers["content-type"].startswith("text/html")
            with open(index, "rb") as f:
                assert content == f.read()
        for path in ("/../server.py", "/%2e%2e/server.py", "/..%2fserver.py",
                     "/../../play_harness/server.py", "/does-not-exist.js"):
            status, _, _ = await _http_get(server.port, path)
            assert status == 404, path
    _run(_serve(tmp_path, best_policy, body))


def test_http_serves_files_from_the_web_dir_only(tmp_path, best_policy):
    web = tmp_path / "web"
    (web / "js").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><title>t</title>")
    (web / "js" / "app.js").write_text("console.log(1);")
    (tmp_path / "secret.txt").write_text("outside the web dir")
    (tmp_path / "web-evil").mkdir()
    (tmp_path / "web-evil" / "x.txt").write_text("sibling with a shared prefix")

    async def body(server):
        status, headers, content = await _http_get(server.port, "/")
        assert status == 200 and content == b"<!doctype html><title>t</title>"
        assert headers["content-type"] == "text/html; charset=utf-8"
        assert headers["cache-control"] == "no-store"
        status, headers, content = await _http_get(server.port, "/js/app.js?v=3")
        assert status == 200 and content == b"console.log(1);"
        assert "javascript" in headers["content-type"]
        for path in ("/../secret.txt", "/js/../../secret.txt", "/../web-evil/x.txt",
                     "/%2e%2e/secret.txt", "/js"):
            status, _, _ = await _http_get(server.port, path)
            assert status == 404, path
    _run(_serve(tmp_path, best_policy, body, web_dir=str(web)))


# ---- websocket protocol ----------------------------------------------------
def test_hello_and_lobby(tmp_path, best_policy):
    if not os.path.exists(G.DEFAULT_CHECKPOINT):
        pytest.skip("chain 25 checkpoint not present")

    async def body(server):
        async with _connect(server) as ws:
            client, hello = await _hello(ws)
            assert hello == {"v": 1, "t": "hello", "protocol": 1, "has_game": False}
            await client.send(t="lobby", rid="L1")
            lobby = await client.expect("lobby")
            assert lobby["rid"] == "L1"
            assert lobby["has_game"] is False and lobby["game_options"] is None
            assert len(lobby["teams"]) == 30
            assert [t["id"] for t in lobby["teams"]] == list(range(30))
            assert all(t["name"] and t["key"] for t in lobby["teams"])
            chain25 = [c for c in lobby["checkpoints"] if c["path"] == G.DEFAULT_CHECKPOINT]
            assert len(chain25) == 1
            assert chain25[0]["ok"] is True and chain25[0]["error"] is None
            assert chain25[0]["sha8"] == "109c55d3"
            assert chain25[0]["step"] == 2999975936
            assert lobby["default_checkpoint"] == G.DEFAULT_CHECKPOINT
            assert lobby["flag_reasons"] == list(G.FLAG_REASONS)
            assert lobby["limits"] == {"think_max_ms": 5000, "clock_min": 15, "clock_max": 1800,
                                       "seed_max": 2 ** 31 - 1}
    _run(_serve(tmp_path, best_policy, body))


def test_complete_game_over_the_socket(tmp_path, best_policy):
    if not os.path.exists(G.DEFAULT_CHECKPOINT):
        pytest.skip("chain 25 checkpoint not present")

    async def body(server):
        async with _connect(server) as ws:
            client, _ = await _hello(ws)
            started, all_frames, snap = await _new_game(client)
            assert started["header"]["options"]["seed"] == 11
            assert started["header"]["checkpoint"]["path"] == G.DEFAULT_CHECKPOINT
            rng = random.Random(5)
            submissions = 0
            policy_frames = 0
            while snap["state"]["awaiting"] != "over":
                legal = snap["legal"]
                assert legal["awaiting"] == "human", legal["awaiting"]
                version = legal["state_version"]
                assert snap["state"]["state_version"] == version
                pick = rng.choice(_legal_ids(legal))
                submissions += 1
                await client.send(t="submit", rid=submissions, state_version=version,
                                  action_id=pick)
                ack = await client.recv()
                assert ack["t"] == "ack", ack
                assert ack["rid"] == submissions
                assert ack["state_version"] > version
                frames, snap = await client.frames_then_state()
                assert frames, "every applied step produces a frame"
                assert frames[0]["step"] == version
                assert frames[0]["actor"] == "human"
                assert snap["state"]["state_version"] == ack["state_version"]
                assert frames[-1]["state"]["state_version"] == ack["state_version"]
                for fr in frames:
                    if fr["actor"] == "policy":
                        policy_frames += 1
                        _check_policy_view(fr)
                    else:
                        assert "view" not in fr
                all_frames.extend(frames)
                assert submissions < 20000
            final_version = snap["state"]["state_version"]
            assert [fr["step"] for fr in all_frames] == list(range(final_version))
            assert policy_frames > 100
            assert snap["legal"]["actions"] == [] and snap["legal"]["prompt"] is None
            over = snap["over"]
            assert over["result"]["natural_completion"] is True
            assert snap["state"]["result"] == over["result"]
            for key in ZERO_KEYS:
                assert over["integrity"][key] == 0, (key, over["integrity"])
            assert over["integrity"]["forwards"] == over["integrity"]["c_steps"] == final_version
            rows = over["stats"]["rows"]
            assert rows and all(len(r) == 3 for r in rows)
            assert rows[0] == ["Touchdowns", *over["result"]["score"]]
            assert len(over["stats"]["teams"]) == 2
            # The finished game refuses further submissions.
            await client.send(t="submit", rid="late", state_version=final_version, action_id=0)
            err = await client.expect("error")
            assert err["reason"] == "match_over" and err["rid"] == "late"
            await client.expect("state")
        game_json = os.path.join(server.game.record_dir, "game.json")
        assert os.path.exists(game_json)
    _run(_serve(tmp_path, best_policy, body))


def test_stale_version_and_unknown_action_are_refused(tmp_path, best_policy):
    if not os.path.exists(G.DEFAULT_CHECKPOINT):
        pytest.skip("chain 25 checkpoint not present")

    async def body(server):
        async with _connect(server) as ws:
            client, _ = await _hello(ws)
            _, _, snap = await _new_game(client)
            version = snap["state"]["state_version"]
            legal_id = _legal_ids(snap["legal"])[0]
            bad = [({"state_version": version - 1, "action_id": legal_id}, "stale_state_version"),
                   ({"state_version": version + 3, "action_id": legal_id}, "stale_state_version"),
                   ({"action_id": legal_id}, "stale_state_version"),
                   ({"state_version": version, "action_id": 999999}, "unknown_action"),
                   ({"state_version": version, "action_id": -1}, "unknown_action"),
                   ({"state_version": version, "action_id": True}, "unknown_action"),
                   ({"state_version": version, "action_id": "0"}, "unknown_action"),
                   ({"state_version": version}, "unknown_action")]
            for i, (fields, reason) in enumerate(bad):
                await client.send(t="submit", rid=f"b{i}", **fields)
                err = await client.expect("error")
                assert err["reason"] == reason, (fields, err)
                assert err["rid"] == f"b{i}"
                assert err["state_version"] == version
                state = await client.expect("state")
                assert state["snapshot"]["state"]["state_version"] == version
                assert state["snapshot"]["legal"]["state_version"] == version
            await client.send(t="submit_path", rid="p", state_version=version, player=0, squares=[])
            err = await client.expect("error")
            assert err["reason"] == "bad_path" and err["state_version"] == version
            await client.expect("state")
            integrity = server.game.session.integrity()
            assert integrity["api_rejections"] == len(bad) + 1
            assert integrity["c_steps"] == version
            # A legal submission still works afterwards.
            await client.send(t="submit", rid="ok", state_version=version, action_id=legal_id)
            ack = await client.expect("ack")
            assert ack["state_version"] > version
            await client.frames_then_state()
    _run(_serve(tmp_path, best_policy, body))


def test_unknown_messages_bad_json_and_bad_options(tmp_path, best_policy):
    if not os.path.exists(G.DEFAULT_CHECKPOINT):
        pytest.skip("chain 25 checkpoint not present")

    async def body(server):
        async with _connect(server) as ws:
            client, _ = await _hello(ws)
            await client.send(t="submit", rid="s", state_version=0, action_id=0)
            err = await client.expect("error")
            assert err["reason"] == "no_game" and err["rid"] == "s"
            await client.send_raw("{not json")
            assert (await client.expect("error"))["reason"] == "bad_json"
            await client.send_raw("[1, 2, 3]")
            assert (await client.expect("error"))["reason"] == "bad_json"
            await client.send(t="new_game", rid="n", options={"seed": 0})
            err = await client.expect("error")
            assert err["reason"] == "bad_seed" and err["rid"] == "n"
            assert server.game is None
            await _new_game(client)
            await client.send(t="no_such_message", rid="u")
            err = await client.expect("error")
            assert err["reason"] == "unknown_message" and err["rid"] == "u"
            await client.send(t="lobby", rid="after")
            lobby = await client.expect("lobby")
            assert lobby["rid"] == "after" and lobby["has_game"] is True
            assert lobby["game_options"]["seed"] == 11
    _run(_serve(tmp_path, best_policy, body))


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def _origin_status(server, origin):
    try:
        async with _connect(server, origin=origin) as ws:
            await _hello(ws)
            return 101
    except InvalidStatus as exc:
        return exc.response.status_code


def test_foreign_origin_is_refused_at_handshake(tmp_path, best_policy):
    async def body(server):
        for origin in ("http://evil.example", f"http://evil.example:{server.port}",
                       "http://127.0.0.1.evil.example", "null"):
            assert await _origin_status(server, origin) == 403, origin
        # A client that sends no Origin header (not a browser) is allowed.
        async with _connect(server) as ws:
            await _hello(ws)
    _run(_serve(tmp_path, best_policy, body))


def test_loopback_origins_are_accepted_on_a_fixed_port(tmp_path, best_policy):
    port = _free_port()

    async def body(server):
        assert server.port == port
        for origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
            assert await _origin_status(server, origin) == 101, origin
        assert await _origin_status(server, f"http://127.0.0.1:{port + 1}") == 403
    _run(_serve(tmp_path, best_policy, body, port=port))


def test_loopback_origin_is_accepted_when_the_port_is_chosen_by_the_os(tmp_path, best_policy):
    async def body(server):
        assert await _origin_status(server, f"http://127.0.0.1:{server.port}") == 101
    _run(_serve(tmp_path, best_policy, body))
