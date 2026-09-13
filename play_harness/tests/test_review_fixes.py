"""Regressions for the Phase B review: game identity, ordered publication, framing
headers, follow-up pairs, joined argmax flags, argmax tie-breaks, Secure the Ball odds."""
import asyncio
import json
import random

import numpy as np
import torch
from websockets.asyncio.client import connect

from play_harness import engine as E
from play_harness.alternatives import conditional_argmax_row
from play_harness.policy import select_joint

from .test_feedback_records import _controller, _play
from .test_server_protocol import GAME_OPTIONS, _http_get, _run, _serve

torch.set_num_threads(2)

SECURE_BALL = E.ACT_KINDS.index("SECURE_BALL")
RAIN = E.WEATHER.index("rain")


async def _recv(ws, timeout=120):
    return json.loads(await asyncio.wait_for(ws.recv(), timeout))


async def _until(ws, t, timeout=120):
    seen = []
    while True:
        msg = await _recv(ws, timeout)
        seen.append(msg)
        if msg["t"] == t:
            return msg, seen


def _first_id(legal):
    if legal["actions"]:
        return legal["actions"][0]["id"]
    return legal["compact"]["SETUP_PLACE"][0][0]


def test_a_request_built_for_a_replaced_game_is_refused(tmp_path, best_policy):
    async def body(server):
        async with connect(f"ws://127.0.0.1:{server.port}/ws", max_size=None) as ws:
            await _until(ws, "hello")
            await ws.send(json.dumps({"v": 1, "t": "new_game", "options": GAME_OPTIONS, "rid": 1}))
            first, _ = await _until(ws, "state")
            gid_a = first["snapshot"]["header"]["game_id"]
            await ws.send(json.dumps({"v": 1, "t": "new_game", "options": GAME_OPTIONS, "rid": 2}))
            second, _ = await _until(ws, "state")
            gid_b = second["snapshot"]["header"]["game_id"]
            assert gid_a != gid_b
            legal = second["snapshot"]["legal"]
            # Same seed, so the version and the id list match game A's; only the game id differs.
            assert legal["state_version"] == first["snapshot"]["legal"]["state_version"]
            await ws.send(json.dumps({"v": 1, "t": "submit", "game_id": gid_a, "rid": 3,
                                      "state_version": legal["state_version"],
                                      "action_id": _first_id(legal)}))
            err, _ = await _until(ws, "error")
            assert err["reason"] == "stale_game" and err["game_id"] == gid_b
            await ws.send(json.dumps({"v": 1, "t": "resync", "rid": 4}))
            snap, _ = await _until(ws, "state")
            assert snap["snapshot"]["state"]["state_version"] == legal["state_version"]
            assert snap["snapshot"]["header"]["game_id"] == gid_b
            await ws.send(json.dumps({"v": 1, "t": "submit", "game_id": gid_b, "rid": 5,
                                      "state_version": legal["state_version"],
                                      "action_id": _first_id(legal)}))
            ack, _ = await _until(ws, "ack")
            assert ack["state_version"] > legal["state_version"]
    _run(_serve(tmp_path, best_policy, body))


def test_publications_arrive_in_command_order(tmp_path, best_policy):
    """Commands sent back to back are dispatched and published one at a time."""
    async def body(server):
        async with connect(f"ws://127.0.0.1:{server.port}/ws", max_size=None) as ws:
            await _until(ws, "hello")
            await ws.send(json.dumps({"v": 1, "t": "new_game", "options": GAME_OPTIONS}))
            state, _ = await _until(ws, "state")
            rng = random.Random(3)
            versions = [state["snapshot"]["state"]["state_version"]]
            for i in range(40):
                legal = state["snapshot"]["legal"]
                if legal["awaiting"] != "human":
                    break
                ids = [a["id"] for a in legal["actions"]]
                ids += [row[0] for row in (legal.get("compact") or {}).get("SETUP_PLACE", [])]
                await ws.send(json.dumps({"v": 1, "t": "submit", "rid": i,
                                          "state_version": legal["state_version"],
                                          "action_id": rng.choice(ids)}))
                await ws.send(json.dumps({"v": 1, "t": "resync", "rid": 1000 + i}))
                # Expect: ack, frames?, state (submit), then state (resync), in that order.
                ack, seen = await _until(ws, "ack")
                assert not any(m["t"] == "state" for m in seen), "a state overtook the ack"
                state, _ = await _until(ws, "state")
                resync, _ = await _until(ws, "state")
                assert resync["rid"] == 1000 + i
                versions.append(state["snapshot"]["state"]["state_version"])
                versions.append(resync["snapshot"]["state"]["state_version"])
                assert resync["snapshot"]["state"]["state_version"] == \
                    state["snapshot"]["state"]["state_version"]
            assert versions == sorted(versions) and len(versions) > 10
    _run(_serve(tmp_path, best_policy, body))


def test_http_responses_forbid_framing_and_sniffing(tmp_path, best_policy):
    async def body(server):
        for path in ("/health", "/", "/missing-file.js"):
            status, headers, _ = await _http_get(server.port, path)
            assert status in (200, 404)
            assert headers.get("content-security-policy") == "frame-ancestors 'none'", path
            assert headers.get("x-frame-options") == "DENY", path
            assert headers.get("x-content-type-options") == "nosniff", path
    _run(_serve(tmp_path, best_policy, body))


def _select_player_prompt(s):
    legal = s.legal()
    p = legal["prompt"]
    return bool(p and p["kind"] == "select_player" and
                any(a["type"] == "ACTIVATE" and a["declare"] for a in legal["actions"]))


def test_follow_ups_are_limited_to_the_supported_pairs(best_policy, tmp_path):
    gc = _controller(best_policy, tmp_path, seed=1, human_side="home")
    s = _play(gc, random.Random(1), stop=_select_player_prompt)
    assert _select_player_prompt(s)
    legal = s.legal()
    v = legal["state_version"]
    end = next(a for a in legal["actions"] if a["type"] == "END_TURN")
    for follow in ({"type": "END_TURN", "arg": 0}, {"type": "DECLARE", "arg": 0}, "DECLARE", 7):
        res = gc.submit({"action_id": end["id"], "state_version": v, "follow": follow})
        assert res == {"ok": False, "error": "unsupported_follow", "state_version": v}, follow
        assert s.version == v
    act = next(a for a in legal["actions"] if a["type"] == "ACTIVATE" and a["declare"])
    kind = act["declare"][0]
    res = gc.submit({"action_id": act["id"], "state_version": v,
                     "follow": {"type": "DECLARE", "arg": E.ACT_KINDS.index(kind)}})
    assert res["ok"] and res["followed"], res
    assert [r["action_type"] for r in res["applied"][:2]] == ["ACTIVATE", "DECLARE"]
    assert all(r["actor"] == "human" for r in res["applied"][:2])
    assert s.integrity()["forwards"] == s.version


def _took_argmax(s, step):
    rows = s.policy_windows[step]
    row = rows[conditional_argmax_row(s.policy_logits[step], rows)]
    return (int(row[0]), int(row[4]), int(row[5])) == tuple(s.trace[step]["tuple"])


def test_joined_views_mark_argmax_only_when_both_decisions_were_argmax(best_policy, tmp_path):
    checked = off_argmax_activations = 0
    for seed in (23, 24):
        gc = _controller(best_policy, tmp_path / str(seed), seed=seed, mode="sample")
        s = _play(gc, random.Random(seed))
        for rec in s.trace:
            step = rec["step"]
            if rec["actor"] != "policy" or rec["action_type"] != "DECLARE" or step == 0:
                continue
            prev = s.trace[step - 1]
            if prev["actor"] != "policy" or prev["action_type"] != "ACTIVATE":
                continue
            view = s.decision_view(step)
            assert view["joined"]
            want = _took_argmax(s, step - 1) and _took_argmax(s, step)
            assert view["argmax_taken"] == want, step
            assert sum(1 for a in view["alternatives"] if a["argmax"]) <= 1
            off_argmax_activations += not _took_argmax(s, step - 1)
            checked += 1
    assert checked > 20
    print(f"joined views checked {checked}, off-argmax activations {off_argmax_activations}")


def test_conditional_argmax_breaks_ties_by_head_index_like_select_joint():
    logits = torch.zeros(sum(E.ACT_SIZES))
    step = E.A["STEP"]
    logits[step] = 5.0
    # Legal-row order puts square 2 before square 1; both square logits tie at 0.
    rows = np.array([[step, 32, 2, 0, 32, 2], [step, 32, 1, 0, 32, 1]], dtype=np.int16)
    support = np.array([E.pack_tuple(step, 32, 2), E.pack_tuple(step, 32, 1)], dtype=np.uint32)
    tup, _, _ = select_joint(logits, support, "argmax")
    row = rows[conditional_argmax_row(logits.numpy(), rows)]
    assert tup == (step, 32, 1)
    assert (int(row[0]), int(row[4]), int(row[5])) == tup


def test_secure_the_ball_pickup_odds_use_the_flat_target(lib):
    found = 0
    for seed in range(1, 60):
        eng = E.Engine(seed)
        rng = random.Random(seed)
        for _ in range(4000):
            legal = eng.legal()
            m = eng.match()
            top = m.stack[m.stack_top - 1]
            pick = next((la for la in legal if la.type_name == "DECLARE" and la.arg == SECURE_BALL),
                        None)
            if pick is None and E.PROCS[top.proc] == "MOVE" and top.b == SECURE_BALL and \
                    m.ball.state == E.BALL_STATES.index("on_ground"):
                steps = [la for la in legal if la.type_name == "STEP"]
                onto = [la for la in steps if (la.x, la.y) == (m.ball.x, m.ball.y)]
                if onto:
                    la = onto[0]
                    target = 3 if m.weather == RAIN else 2
                    want = (7 - target) / 6
                    tests, probs = eng.step_success(top.a, la.x, la.y, False, SECURE_BALL)
                    assert tests[2] == 1 and abs(probs[2] - want) < 1e-6
                    odds = eng.path_odds(top.a, [(la.x, la.y)], False, SECURE_BALL)
                    assert odds[0]["tests"][2] == 1 and abs(odds[0]["probs"][2] - want) < 1e-6
                    # An ordinary move prices the same pick-up from AG instead.
                    _, plain = eng.step_success(top.a, la.x, la.y, False, E.ACT_KINDS.index("MOVE"))
                    ag_target = int(m.players[top.a].ag)
                    if ag_target > target:
                        assert plain[2] < probs[2]
                    found += 1
                    pick = la
                elif steps:
                    pick = min(steps, key=lambda s: max(abs(s.x - m.ball.x), abs(s.y - m.ball.y)))
            if pick is None:
                pick = rng.choice(legal)
            if eng.step(*pick.tuple) == E.STEP_TERMINAL:
                break
        if found >= 3:
            break
    assert found >= 3
