"""Engine scripted bots: the shim's scripted step, bots as tournament players, and
the bot exam bench's selection and statistics."""
import hashlib
import json
import math
import os
import random
import statistics

import pytest
import torch

from play_harness import bot_exam as X
from play_harness import engine as E
from play_harness import tournament as T
from play_harness import tournament_stats as S
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
    assert rec["natural"] and not rec["truncated"] and not any(rec["integrity"].values())
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


def test_sampling_seed_is_historical_at_episode_zero():
    for seed, side in ((0, 0), (20260915, 1), (4242, 0)):
        assert T.sampling_seed(seed, side) == (seed * 1_000_003 + 17 + side) % (1 << 62)
        assert T.sampling_seed(seed, side, 0) == T.sampling_seed(seed, side)
    assert len({T.sampling_seed(42, 1, k) for k in range(8)}) == 8


def test_step_limit_returns_in_progress_and_is_prefix_consistent(policy):
    full, _ = T.play_match(policy, T.ScriptedBot("offense"), 55)
    n = full["c_steps"]
    assert T.play_match(policy, T.ScriptedBot("offense"), 55, step_limit=n - 1)[0] is None
    assert T.play_match(policy, T.ScriptedBot("offense"), 55, step_limit=5)[0] is None
    capped, _ = T.play_match(policy, T.ScriptedBot("offense"), 55, step_limit=n)
    assert _essential(capped) == _essential(full)


def test_decision_cap_is_refused_unless_allowed(lib):
    with pytest.raises(T.IntegrityError):
        T.play_match(T.ScriptedBot("contact"), T.ScriptedBot("contact"), 12, lib=lib,
                     max_decisions=60)
    rec, _ = T.play_match(T.ScriptedBot("contact"), T.ScriptedBot("contact"), 12, lib=lib,
                          max_decisions=60, allow_decision_cap=True)
    assert rec["truncated"] and not rec["natural"] and rec["engine_decisions"] == 60


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


def test_sharpness_leaves_out_scripted_seats():
    games = [{"home": "p", "away": "bot", "logprob_sum": [-10.0, 0.0], "decisions": [50, 40],
              "modes": ["sample", "scripted"]},
             {"home": "bot", "away": "p", "logprob_sum": [0.0, -6.0], "decisions": [30, 30],
              "modes": ["scripted", "sample"]},
             {"home": "p", "away": "q", "logprob_sum": [-1.0, -2.0], "decisions": [10, 10]}]
    sharp = S.sharpness(games)
    assert set(sharp) == {"p", "q"}
    assert sharp["p"] == {"mean_logprob": -17.0 / 90, "decisions": 90}


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


# ---- bot exam selection ---------------------------------------------------------------
def test_stop_step_is_the_first_epoch_reaching_the_count():
    ends = [5, 70, 64, 130]
    assert X.stop_step(ends, 1, 64) == 64
    assert X.stop_step(ends, 2, 64) == 64
    assert X.stop_step(ends, 3, 64) == 128
    assert X.stop_step(ends, 4, 64) == 192
    assert X.stop_step(ends, 5, 64) is None
    with pytest.raises(ValueError):
        X.stop_step(ends, 0, 64)


def _length_fn(salt, lo, hi, multiple=1):
    def f(i, k):
        h = int(hashlib.sha256(f"{salt}|{i}|{k}".encode()).hexdigest(), 16)
        return (lo + h % (hi - lo + 1)) * multiple
    return f


@pytest.mark.parametrize("n_envs,eval_episodes,horizon,lo,hi,multiple", [
    (7, 11, 8, 3, 40, 1),
    (16, 30, 64, 20, 200, 1),
    (32, 40, 64, 1, 4, 64),            # every game ends exactly on an epoch boundary
    (5, 3, 64, 400, 900, 1),           # the stop comes before any env finishes twice
    (9, 50, 16, 5, 30, 1),             # several games per env
])
@pytest.mark.parametrize("salt", ["a", "b"])
def test_selection_matches_a_brute_force_lockstep_simulation(n_envs, eval_episodes, horizon,
                                                             lo, hi, multiple, salt):
    f = _length_fn(salt, lo, hi, multiple)
    ref_stop, ref_counted = X.lockstep_reference(f, n_envs, eval_episodes, horizon)
    requested = {}

    def play(requests):
        out = []
        for i, k, limit in requests:
            assert all((i, j) in requested and requested[(i, j)] is not None for j in range(k))
            length = f(i, k)
            done = limit is None or length <= limit
            requested[(i, k)] = length if done else None
            out.append(length if done else None)
        return out

    sel = X.select_exam_games(play, n_envs, eval_episodes, horizon)
    assert sel["stop_step"] == ref_stop
    assert sel["counted"] == ref_counted
    assert len(ref_counted) >= eval_episodes
    for i, k, start, end in sel["games"]:
        assert end - start == f(i, k)
    # no env plays past a game still running at the stop step
    for i in range(n_envs):
        ks = sorted(k for (j, k) in requested if j == i)
        assert ks == list(range(len(ks)))
        assert all(requested[(i, k)] is not None for k in ks[:-1])


def test_selection_refuses_a_player_that_breaks_its_contract():
    with pytest.raises(RuntimeError):
        X.select_exam_games(lambda reqs: [None] * len(reqs), 3, 2, 8)
    with pytest.raises(RuntimeError):
        X.select_exam_games(lambda reqs: [], 3, 2, 8)
    with pytest.raises(RuntimeError):                  # a length beyond the limit it was given
        X.select_exam_games(lambda reqs: [10 ** 6 if lim else 10 for _, _, lim in reqs], 3, 4, 8)


def test_cluster_mean_matches_the_ratio_estimator():
    rng = random.Random(4)
    values = [rng.randint(0, 3) for _ in range(60)]
    clusters = [rng.randint(0, 11) for _ in range(60)]
    got = X.cluster_mean(values, clusters)
    mean = sum(values) / len(values)
    sums = {}
    for v, c in zip(values, clusters):
        sums.setdefault(c, []).append(v)
    g = len(sums)
    var = g / (g - 1) * sum((sum(v) - mean * len(v)) ** 2 for v in sums.values()) / len(values) ** 2
    assert got["mean"] == pytest.approx(mean) and got["se"] == pytest.approx(math.sqrt(var))
    assert got["clusters"] == g and got["n"] == 60
    singles = X.cluster_mean(values, range(60))           # one game per env: the plain SE
    assert singles["se"] == pytest.approx(statistics.stdev(values) / math.sqrt(60))
    assert X.cluster_mean([1, 2], [0, 0])["se"] is None
    assert X.cluster_mean([], [])["mean"] is None


def test_cell_summary_counts_only_selected_games_from_the_champion_side():
    recs = [{"env": 0, "counted": True, "score": [2, 1], "truncated": False},
            {"env": 0, "counted": True, "score": [1, 1], "truncated": True},
            {"env": 1, "counted": True, "score": [0, 3], "truncated": False},
            {"env": 2, "counted": False, "score": [9, 0], "truncated": False}]
    away_bot = X.cell_summary(recs, bot_side=1)
    assert (away_bot["games"], away_bot["W"], away_bot["D"], away_bot["L"]) == (3, 1, 1, 1)
    assert away_bot["champion_td_per_game"]["mean"] == pytest.approx(1.0)
    assert away_bot["bot_td_per_game"]["mean"] == pytest.approx(5.0 / 3)
    assert away_bot["champion_score"]["mean"] == pytest.approx(0.5)
    assert away_bot["draw_rate"]["mean"] == pytest.approx(1.0 / 3)
    assert away_bot["truncated_games"] == 1 and away_bot["envs_with_counted_games"] == 2
    home_bot = X.cell_summary(recs, bot_side=0)
    assert home_bot["champion_td_per_game"]["mean"] == pytest.approx(5.0 / 3)
    assert (home_bot["W"], home_bot["L"]) == (1, 1)


def test_agreement_scales_the_exam_se_by_game_count():
    res = X.agreement(0.60, 0.02, 2000, 0.56, 2000)
    assert res["se_diff"] == pytest.approx(0.02 * math.sqrt(2))
    assert res["z"] == pytest.approx(0.04 / (0.02 * math.sqrt(2)))
    assert res["within_noise"]
    assert not X.agreement(0.66, 0.02, 2000, 0.56, 2000)["within_noise"]
    assert X.agreement(0.5, 0.02, 4000, 0.5, 1000)["se_diff"] == pytest.approx(
        math.sqrt(0.02 ** 2 + 0.04 ** 2))


def test_play_exam_game_keys_env_and_episode(policy, lib):
    bot = T.ScriptedBot("offense")
    rec = X.play_exam_game(policy, bot, 1, exam_seed=42, env=3, k=1, limit=None,
                           episode_offset=5, lib=lib)
    assert (rec["env"], rec["k"], rec["engine_seed"], rec["episode"]) == (3, 1, 45, 6)
    assert rec["bots"] == [None, "offense"] and rec["bot_side"] == 1
    assert rec["sampling_seeds"] == [T.sampling_seed(45, 0, 6), T.sampling_seed(45, 1, 6)]
    n = rec["c_steps"]
    assert X.play_exam_game(policy, bot, 1, 42, 3, 1, n - 1, episode_offset=5, lib=lib) is None
    again = X.play_exam_game(policy, bot, 1, 42, 3, 1, n, episode_offset=5, lib=lib)
    assert _essential(again) == _essential(rec)
    home = X.play_exam_game(policy, bot, 0, 42, 3, 1, None, episode_offset=5, lib=lib)
    assert home["bots"] == ["offense", None] and home["team_ids"] == rec["team_ids"]


def test_consecutive_exam_seeds_share_env_seeds_unless_the_episodes_differ(policy, lib):
    """The trap behind the first seed 43 bench: exam seed s + 1 env i is exam seed s
    env i + 1 at the same episode offset, so it is not a second draw."""
    bot = T.ScriptedBot("offense")
    shifted = X.play_exam_game(policy, bot, 1, exam_seed=43, env=0, k=0, limit=None, lib=lib)
    base = X.play_exam_game(policy, bot, 1, exam_seed=42, env=1, k=0, limit=None, lib=lib)
    drop = ("env", "seconds", "pid")
    assert {k: v for k, v in shifted.items() if k not in drop} == \
        {k: v for k, v in base.items() if k not in drop}
    offset = X.play_exam_game(policy, bot, 1, exam_seed=43, env=0, k=0, limit=None,
                              episode_offset=1000, lib=lib)
    assert offset["episode"] == 1000 and offset["engine_seed"] == 43
    assert offset["sampling_seeds"] != shifted["sampling_seeds"]
    assert offset["action_trail_sha256"] != shifted["action_trail_sha256"]


@pytest.mark.skipif(not os.path.exists(CHAIN25), reason="chain 25 checkpoint not present")
def test_bot_exam_cli_selects_resumes_and_refuses_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    out = tmp_path / "exam"
    args = ["--checkpoint", CHAIN25, "--bot", "offense", "--bot-side", "away",
            "--exam-seed", "42", "--envs", "3", "--eval-episodes", "4", "--horizon", "64",
            "--workers", "1", "--out-dir", str(out)]
    assert X.main(args) == 0
    summary = json.load(open(out / "summary.json"))
    selected = [json.loads(line) for line in open(out / "selected.jsonl")]
    counted = [s for s in selected if s["counted"]]
    assert summary["games"] == len(counted) >= 4
    assert summary["stop_step"] % 64 == 0
    assert all(s["end_step"] <= summary["stop_step"] for s in counted)
    assert all(s["end_step"] > summary["stop_step"] for s in selected if not s["counted"])
    ends = sorted(s["end_step"] for s in selected)
    assert summary["stop_step"] == X.stop_step(ends, 4, 64)
    manifest = json.load(open(out / "manifest.json"))
    assert manifest["bot"] == T.bot_identity("offense") and manifest["bot_side"] == "away"
    assert X.main(args) == 0
    assert json.load(open(out / "summary.json"))["games_played"] == 0      # resume replays nothing
    with pytest.raises(SystemExit):
        X.main([a if a != "42" else "43" for a in args])
