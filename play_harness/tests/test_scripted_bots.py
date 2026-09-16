"""Engine scripted bots: the shim's scripted step and bots as tournament players."""
import hashlib
import json
import os
import random

import pytest
import torch

from play_harness import engine as E
from play_harness import tournament as T
from play_harness.policy import PolicySeat, random_policy

from .conftest import CHAIN25, ROOT

KINDS = ("contact", "offense")


@pytest.fixture(scope="module")
def policy():
    return random_policy(seed=3, scale=0.05)


def _essential(rec):
    return {k: v for k, v in rec.items() if k not in ("seconds", "pid")}


# ---- shim ---------------------------------------------------------------------------
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("seed", [3, 4])
def test_step_scripted_equals_submitting_the_picked_tuple(lib, kind, seed):
    """c_step's scripted branch applies exactly the engine pick: same dice, same state,
    same rewards and counters as submitting that pick's tuple on a twin session."""
    bt = E.BOT_TYPES[kind]
    a, b = E.Engine(seed, lib=lib), E.Engine(seed, lib=lib)
    steps = 0
    while True:
        assert a.digest() == b.digest()
        team = a.decision_team
        idx = a.scripted_bot_index(bt)
        assert idx >= 0 and idx == b.scripted_bot_index(bt)
        tup = a.legal()[idx].tuple
        ra, rb = a.step_scripted(bt, team), b.step(*tup)
        steps += 1
        assert ra == rb
        assert a.last_action() == b.last_action()
        assert a.last_rewards() == b.last_rewards()
        if ra == E.STEP_TERMINAL:
            break
        assert ra == E.STEP_OK and steps < 100_000
    assert steps > 200
    fa, fb = a.final_match(), b.final_match()
    assert bytes(fa) == bytes(fb)
    assert a.counters() == b.counters()
    assert a.stall_counts() == b.stall_counts()
    assert a.digest() == b.digest()


def test_scripted_step_leaves_the_env_unscripted(lib):
    """After a scripted step the env must decode submitted tuples again. If the
    scripted fields stayed set, the bot would override team 0's random tuples."""
    rng = random.Random(9)
    a, b = E.Engine(21, lib=lib), E.Engine(21, lib=lib)
    bt = E.BOT_TYPES["offense"]
    team = a.decision_team
    tup = a.legal()[a.scripted_bot_index(bt)].tuple
    assert a.step_scripted(bt, team) == b.step(*tup) == E.STEP_OK
    overridden = 0
    for _ in range(400):
        assert a.digest() == b.digest()
        legal = a.legal()
        choices = [x for x in legal if a.tuple_index(*x.tuple) == x.index]
        pick = rng.choice(choices)
        bot = a.scripted_bot_index(bt)
        overridden += bot != pick.index
        ra, rb = a.step(*pick.tuple), b.step(*pick.tuple)
        assert ra == rb
        if ra == E.STEP_TERMINAL:
            break
    assert overridden > 20            # the random coach really departs from the bot


def test_scripted_step_refusals_leave_state_untouched(lib):
    eng = E.Engine(8, lib=lib)
    before = eng.digest()
    team = eng.decision_team
    assert eng.step_scripted(7, team) == E.STEP_BAD_BOT
    assert eng.step_scripted(-1, team) == E.STEP_BAD_BOT
    assert eng.step_scripted(E.BOT_TYPES["offense"], 1 - team) == E.STEP_NOT_BOT_TURN
    assert eng.step_scripted(E.BOT_TYPES["contact"], 2) == E.STEP_NOT_BOT_TURN
    assert eng.scripted_bot_index(5) == -2
    assert eng.digest() == before and eng.counters()["steps"] == 0
    assert eng.contact_bot_index() == eng.scripted_bot_index(E.BOT_TYPES["contact"]) >= 0
    while eng.step_scripted(E.BOT_TYPES["contact"], eng.decision_team) != E.STEP_TERMINAL:
        pass
    assert eng.step_scripted(E.BOT_TYPES["contact"], eng.decision_team) == E.STEP_OVER


def test_contact_and_offense_bots_are_different_policies(lib):
    differ = 0
    for seed in (1, 2, 3):
        eng = E.Engine(seed, lib=lib)
        for _ in range(3000):
            c, o = (eng.scripted_bot_index(E.BOT_TYPES[k]) for k in KINDS)
            differ += c != o
            if eng.step_scripted(E.BOT_TYPES["offense"], eng.decision_team) == E.STEP_TERMINAL:
                break
    assert differ > 50


def test_engine_bot_table_matches_the_env_config():
    ini = open(os.path.join(ROOT, "puffer", "config", "bloodbowl.ini")).read()
    assert "0 = contact bot, 1 = bashy cage-advance offense bot" in ini
    assert E.BOT_TYPES == {"contact": 0, "offense": 1}
    env = open(os.path.join(ROOT, "puffer", "bloodbowl", "bloodbowl.h")).read()
    assert ("act = env->scripted_opponent_type == 1\n"
            "                      ? bbe_offense_bot_pick(m, env->legal, env->n_legal)\n"
            "                      : bbe_contact_bot_pick(m, env->legal, env->n_legal);") in env
    shim = open(os.path.join(ROOT, "play_harness", "native", "bbplay.c")).read()
    for fn in E.BOT_PICK_FUNCTIONS.values():
        assert fn in shim


# ---- tournament players ---------------------------------------------------------------
def test_scripted_bot_and_bot_seat_validate():
    with pytest.raises(ValueError):
        T.ScriptedBot("cage")
    with pytest.raises(TypeError):
        T.BotSeat(object(), 0)
    with pytest.raises(ValueError):
        T.BotSeat(T.ScriptedBot("offense"), 2)
    seat = T.BotSeat(T.ScriptedBot("offense"), 1, seed=5)
    none = [E.pack_tuple(*T.NONE_TUPLE)]
    assert seat.step(None, none, False)["tuple"] == T.NONE_TUPLE
    assert seat.step(None, [1, 2], True)["tuple"] is None
    with pytest.raises(AssertionError):
        seat.step(None, [1, 2], False)
    assert (seat.forwards, seat.decisions) == (3, 1)
    seat.reset_match()
    assert (seat.forwards, seat.decisions, seat.mode, seat.temperature) == (0, 0, "scripted", None)


class RecordingSeat(PolicySeat):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.log = []

    def step(self, obs, support, deciding):
        before = self.state.clone()
        out = super().step(obs, support, deciding)
        self.log.append({"deciding": deciding, "before": before, "after": self.state.clone()})
        return out


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("bot_side", [0, 1])
def test_policy_vs_bot_match_contract(policy, monkeypatch, kind, bot_side):
    made, calls = [], []

    def factory(pol, seat, mode="sample", seed=0, temperature=1.0):
        s = RecordingSeat(pol, seat, mode=mode, seed=seed, temperature=temperature)
        made.append(s)
        return s

    real = E.Engine.step_scripted

    def spy(self, bot_type, team):
        calls.append((bot_type, team, self.decision_team))
        return real(self, bot_type, team)

    monkeypatch.setattr(E.Engine, "step_scripted", spy)
    bot = T.ScriptedBot(kind)
    players = (bot, policy) if bot_side == 0 else (policy, bot)
    rec, seats = T.play_match(*players, engine_seed=31, seat_factory=factory)
    assert len(made) == 1 and isinstance(seats[bot_side], T.BotSeat)
    ps = made[0]
    assert ps.seat == 1 - bot_side and seats[1 - bot_side] is ps
    assert rec["natural"] and not any(rec["integrity"].values())
    assert rec["forwards"] == [rec["c_steps"]] * 2 and T.check_record(rec) == []
    assert len(ps.log) == rec["c_steps"]                        # policy stepped on every c_step
    waiting = [e for e in ps.log if not e["deciding"]]
    assert len(waiting) == rec["decisions"][bot_side] > 50
    assert all(not torch.equal(e["before"], e["after"]) for e in waiting)
    assert calls and all(c == (E.BOT_TYPES[kind], bot_side, bot_side) for c in calls)
    assert len(calls) == rec["decisions"][bot_side]
    assert rec["decisions"][0] + rec["decisions"][1] == rec["c_steps"]
    assert rec["bots"][bot_side] == kind and rec["bots"][1 - bot_side] is None
    assert rec["modes"][bot_side] == "scripted" and rec["temperatures"][bot_side] is None
    assert rec["modes"][1 - bot_side] == "sample" and rec["temperatures"][1 - bot_side] == 1.0
    assert rec["mode"] == "mixed" and rec["logprob_sum"][bot_side] == 0.0


def test_policy_vs_bot_is_deterministic_and_bot_kind_matters(policy):
    one, _ = T.play_match(policy, T.ScriptedBot("offense"), 40)
    two, _ = T.play_match(policy, T.ScriptedBot("offense"), 40)
    other, _ = T.play_match(policy, T.ScriptedBot("contact"), 40)
    assert _essential(one) == _essential(two)
    assert one["action_trail_sha256"] != other["action_trail_sha256"]
    assert one["team_ids"] == other["team_ids"]               # rosters follow the engine seed


def test_bot_vs_bot_needs_no_policy(lib):
    rec, seats = T.play_match(T.ScriptedBot("contact"), T.ScriptedBot("offense"), 12, lib=lib)
    assert all(isinstance(s, T.BotSeat) for s in seats)
    assert rec["bots"] == ["contact", "offense"] and rec["mode"] == "scripted"
    assert rec["forwards"] == [rec["c_steps"]] * 2 and rec["logprob_sum"] == [0.0, 0.0]


def test_pair_game_swaps_the_bot_between_legs(policy):
    policies = {"P": policy, "off": T.ScriptedBot("offense")}
    specs = T.player_specs(["P", "off"], "sample", bots={"off": "offense"})
    legs = {leg: T.pair_game(policies, "P", "off", 2, leg, seed0=700, specs=specs)
            for leg in T.LEGS}
    a, b = legs["A_home"], legs["B_home"]
    assert a["engine_seed"] == b["engine_seed"] == 702 and a["team_ids"] == b["team_ids"]
    assert (a["home"], a["away"], a["bots"]) == ("P", "off", [None, "offense"])
    assert (b["home"], b["away"], b["bots"]) == ("off", "P", ["offense", None])
    assert (a["a_td"], a["b_td"]) == tuple(a["score"])
    assert (b["a_td"], b["b_td"]) == tuple(reversed(b["score"]))


def test_player_specs_with_bots():
    specs = T.player_specs(["p", "off", "con"], "argmax", {"p": "sample"}, {"p": 0.8},
                           bots={"off": "offense", "con": "contact"})
    assert specs == {"p": {"mode": "sample", "temperature": 0.8},
                     "off": {"bot": "offense"}, "con": {"bot": "contact"}}
    for kwargs in ({"temperatures": {"off": 0.5}}, {"player_modes": {"off": "argmax"}},
                   {"bots": {"off": "cage"}}, {"bots": {"zzz": "offense"}}):
        base = {"bots": {"off": "offense"}, **kwargs}
        with pytest.raises(ValueError):
            T.player_specs(["p", "off"], "sample", **base)


def test_bot_identity_hashes_the_bot_sources():
    ident = T.bot_identity("offense")
    assert ident["kind"] == "offense" and ident["scripted_opponent_type"] == 1
    assert ident["pick_function"] == "bbe_offense_bot_pick"
    assert set(ident["source_sha256"]) == set(T.BOT_SOURCES)
    for rel, digest in ident["source_sha256"].items():
        assert digest == hashlib.sha256(open(os.path.join(ROOT, rel), "rb").read()).hexdigest()
    assert T.bot_identity("contact")["pick_function"] == "bbe_contact_bot_pick"
    with pytest.raises(ValueError):
        T.bot_identity("cage")


def test_legacy_manifest_gains_empty_bots():
    old = {"checkpoints": {"a": {}, "b": {}}, "mode": "sample", "games_per_pair": 2}
    assert T.legacy_manifest_specs(old)["bots"] == {}
    assert T.legacy_manifest_specs({**old, "bots": {"x": 1}})["bots"] == {"x": 1}


def test_cli_bot_only_run_resumes_and_refuses_a_new_bot(tmp_path, monkeypatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.setattr(T, "discover_checkpoints", lambda *a, **k: {})
    out = tmp_path / "bots"
    args = ["--bot", "con=contact", "--bot", "off=offense", "--games-per-pair", "2",
            "--workers", "1", "--seed0", "808", "--out-dir", str(out)]
    assert T.main(args) == 0
    games = [json.loads(line) for line in open(out / "games.jsonl")]
    assert sorted(g["leg"] for g in games) == ["A_home", "B_home"]
    assert {tuple(g["bots"]) for g in games} == {("contact", "offense"), ("offense", "contact")}
    manifest = json.load(open(out / "manifest.json"))
    assert manifest["bots"] == {"con": T.bot_identity("contact"), "off": T.bot_identity("offense")}
    assert manifest["players"] == {"con": {"bot": "contact"}, "off": {"bot": "offense"}}
    assert manifest["bot_library_sha256"] == T.library_sha256()
    assert manifest["checkpoints"] == {}
    assert T.main(args) == 0
    assert len(open(out / "games.jsonl").readlines()) == 2
    with pytest.raises(SystemExit):
        T.main([a if a != "off=offense" else "off=contact" for a in args])
    with pytest.raises(SystemExit):
        T.main(["--bot", "only=offense", "--games-per-pair", "2", "--workers", "1",
                "--out-dir", str(tmp_path / "one")])


@pytest.mark.skipif(not os.path.exists(CHAIN25), reason="chain 25 checkpoint not present")
def test_cli_checkpoint_against_bot(tmp_path, monkeypatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    out = tmp_path / "run"
    args = ["--checkpoint", f"c25={CHAIN25}", "--bot", "off=offense", "--pair", "c25,off,2",
            "--workers", "1", "--seed0", "919", "--out-dir", str(out)]
    assert T.main(args) == 0
    games = [json.loads(line) for line in open(out / "games.jsonl")]
    assert sorted((g["home"], g["away"]) for g in games) == [("c25", "off"), ("off", "c25")]
    assert all(T.check_record(g) == [] for g in games)
    for g in games:
        side = 0 if g["home"] == "off" else 1
        assert g["bots"][side] == "offense" and g["modes"][side] == "scripted"
    manifest = json.load(open(out / "manifest.json"))
    assert set(manifest["checkpoints"]) == {"c25"} and set(manifest["bots"]) == {"off"}
    assert manifest["pairs"] == [["c25", "off", 2]]
    assert (out / "COMPLETE.json").exists()
    for bad in (["--bot", "c25=contact"], ["--temperature", "off=0.7"],
                ["--player-mode", "off=argmax"], ["--bot", "x=cage"]):
        with pytest.raises(SystemExit):
            T.main(args + bad)
