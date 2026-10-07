"""The search seat in the tournament harness (tournament --search).

  identity     delta = infinity: the full search runs at every decision in scope
               and the game is the plain masked game, on 10 seeds;
  cross-tool   a tournament game with the search seat is the game search_ab.py
               plays for the same seed, orientation and setting;
  the shadow   the seat's opponent-view state is the opponent's real state when
               the opponent is the same network, and is kept the same way
               against a bot;
  opponents    a scripted bot and another network: the game runs, passes
               integrity, and with delta = infinity is the plain game;
  determinism  the same seed and setting give the same record, search statistics
               included, twice and at two worker counts;
  the flag     the manifest records the complete setting and a resume refuses
               another; a search seat is refused on the batched path;
  integrity    a failure in the real game or in a clone aborts the game.

Games here use a seeded random network at k = 2, n = 2, so a searched game takes
seconds. The same tests on the chain 55 checkpoint at the measured setting take
minutes a game and run only when BBPLAY_SEARCH_REAL=1 (see the last section).
"""
import contextlib
import io
import json
import math
import os
import re
import sys

import pytest
import torch

from play_harness import engine as E
from play_harness import policy as P
from play_harness import search as S
from play_harness import tournament as T
from play_harness.policy import MASKS, MaskedPolicySeat, PolicySeat, random_policy
from tools import search_ab as AB

from .conftest import ROOT
from .test_reward_manifest import FIXTURE, FIXTURE_SHA256

M1 = ("m1",)
QUICK = S.search_setting(2, 2, 0.0)                  # deviates on any clear gain
IDENTITY = S.search_setting(2, 2, math.inf)          # searches, never deviates
TIMING = ("seconds", "pid", "search_seconds")


@pytest.fixture(scope="module")
def net():
    return random_policy(seed=11, scale=0.05)


@pytest.fixture(scope="module")
def other_net():
    return random_policy(seed=12, scale=0.05)


def _essential(rec):
    return {k: v for k, v in rec.items() if k not in TIMING}


def play(home, away, seed, search=(None, None), offsets=(0, 1), masks=(M1, M1), **kwargs):
    return T.play_match(home, away, seed, masks=masks, seed_offsets=offsets, search=search,
                        **kwargs)


# ---- identity: delta = infinity is the plain masked game --------------------------------------
IDENTITY_SEEDS = tuple(range(41000, 41010))


@pytest.fixture(scope="module")
def identity_games(net):
    """Per seed: the plain m1 game and the same game with a searching seat that
    never deviates. The seat sits HOME on even seeds and AWAY on odd ones."""
    games = {}
    for seed in IDENTITY_SEEDS:
        side = seed % 2
        search = (IDENTITY, None) if side == 0 else (None, IDENTITY)
        plain, plain_seats = play(net, net, seed)
        searched, seats = play(net, net, seed, search=search)
        games[seed] = (side, plain, plain_seats, searched, seats)
    return games


def test_identity_delta_infinity_is_the_plain_m1_game_on_ten_seeds(identity_games):
    assert len(identity_games) == 10
    rollouts = 0
    for seed, (side, plain, plain_seats, searched, seats) in identity_games.items():
        assert type(seats[side]) is S.SearchSeat and type(seats[1 - side]) is MaskedPolicySeat
        assert all(type(s) is MaskedPolicySeat for s in plain_seats)
        # The action trail, the final state digest and the log-probability sums.
        for name in ("action_trail_sha256", "final_digest", "logprob_sum"):
            assert searched[name] == plain[name], (seed, name)
        # And everything else a plain record holds.
        assert {k: searched[k] for k in plain if k not in TIMING} == _essential(plain), seed
        # Nothing of the real seats was consumed or written: generators and
        # recurrent states end where the plain game's end.
        for real, base in zip(seats, plain_seats):
            assert torch.equal(real.generator.get_state(), base.generator.get_state())
            assert torch.equal(real.state, base.state)
            assert (real.forwards, real.decisions) == (base.forwards, base.decisions)
            assert real.mask_stats == base.mask_stats
        stats = searched["search_stats"][side]
        assert searched["search_stats"][1 - side] is None
        assert sum(stats["searched"].values()) > 50 and stats["rollouts"] > 0
        assert stats["deviations"] == {"turn": 0, "after_declare": 0}
        assert stats["predicted_gains"] == [] and stats["deviation_types"] == {}
        rollouts += stats["rollouts"]
    assert rollouts > 2000                               # run, then discarded


def test_a_searched_record_says_what_was_searched_and_checked(identity_games):
    single = 0
    for seed, (side, plain, _, rec, seats) in identity_games.items():
        assert rec["search"][side] == IDENTITY and rec["search"][1 - side] is None
        assert rec["reward_manifest_sha256"] == FIXTURE_SHA256
        assert rec["integrity_checks"] == list(AB.INTEGRITY_CHECKS)
        assert rec["masks"] == [["m1"], ["m1"]] and rec["seed_offsets"] == [0, 1]
        assert rec["natural"] and not rec["truncated"] and not any(rec["integrity"].values())
        stats = rec["search_stats"][side]
        assert set(stats) == {"in_scope", "searched", "deviations", "deviation_types",
                              "predicted_gains", "rollouts", "rollout_steps",
                              "rollout_forward_rows", "cap_rejected_rollouts",
                              "cap_rejected_decisions", "cutoff_rollouts", "error_rollouts",
                              "shadow_forwards"}
        assert set(stats["in_scope"]) == set(stats["searched"]) == {"turn", "after_declare"}
        assert all(stats["searched"][c] <= stats["in_scope"][c] for c in stats["searched"])
        searched = sum(stats["searched"].values())
        # Every searched decision ran its rollouts: 2 candidates x 2 rollouts here.
        assert stats["rollouts"] == 2 * 2 * searched
        assert stats["rollout_steps"] > stats["rollouts"]
        assert stats["rollout_forward_rows"] > stats["rollout_steps"]
        assert stats["error_rollouts"] == stats["cap_rejected_decisions"] == 0
        # Real forwards stay one per engine step per seat; the opponent-view
        # forwards are counted apart, one per engine step.
        assert rec["forwards"] == [rec["c_steps"]] * 2
        assert stats["shadow_forwards"] == rec["c_steps"]
        assert rec["search_seconds"][side] > 0 and rec["search_seconds"][1 - side] is None
        assert len(rec["final_state_sha256"]) == len(rec["sampling_state_sha256"]) == 64
        assert T.check_record(rec) == []
        single += sum(stats["in_scope"].values()) - searched
        # A plain game carries none of this.
        assert not set(plain) & {"search", "search_stats", "search_seconds", "integrity_checks",
                                 "reward_manifest_sha256", "final_state_sha256",
                                 "sampling_state_sha256"}
    # In scope but one legal action (under m1, the last player left in a turn):
    # not searched and not counted as searched.
    assert single >= 1
    broken = dict(next(iter(identity_games.values()))[3])
    assert T.check_record(dict(broken, integrity_checks=[]))
    side = next(iter(identity_games.values()))[0]
    stats = [None, None]
    stats[side] = dict(broken["search_stats"][side], error_rollouts=1)
    assert T.check_record(dict(broken, search_stats=stats))


# ---- cross-tool: the tournament's searched game is search_ab.py's -----------------------------
STAT_FIELDS = ("in_scope", "searched", "deviations", "deviation_types", "predicted_gains",
               "rollouts", "rollout_steps", "cap_rejected_rollouts", "cap_rejected_decisions",
               "cutoff_rollouts", "error_rollouts")
GAME_FIELDS = ("action_trail_sha256", "final_state_sha256", "sampling_state_sha256", "c_steps",
               "sampling_seeds", "team_ids", "integrity_checks")


def ab_plan(checkpoint, k, n, delta, seed):
    """A search_ab plan for one arm `s` that mirrors a tournament pair: seat A
    searches under m1, seat B is the same checkpoint under m1 on sampling offset 1."""
    return AB.validate_plan({
        "schema": AB.PLAN_SCHEMA, "name": "cross-tool", "source_commit": T._git_head(),
        "code_sha256": AB.code_sha256(), "checkpoint_sha256": checkpoint,
        "reward_manifest_sha256": FIXTURE_SHA256, "gamma": 0.999, "temperature": 1.0,
        "masks": {"a": ["m1"], "b": ["m1"]}, "sampling_offsets": {"a": 0, "b": 1},
        "max_decisions": 4096,
        "search": {"scope": ["turn", "after_declare"], "k": k, "n": n, "se_floor": AB.SE_FLOOR,
                   "candidates": AB.CANDIDATES, "max_rollout_steps": 200},
        "arms": [{"name": "plain", "delta": None}, {"name": "s", "delta": delta}],
        "identity": {"arm": "identity", "seeds_per_shard": 1},
        "shards": [{"name": "t1", "seed_start": seed, "seed_count": 1}],
        "cap_rejection_ceiling": 1.0,
        "bootstrap": {"reps": 200, "seed": 0, "quantiles": [2.5, 97.5]}})


def tournament_specs(setting):
    """The tournament's players for that plan: S searches, C is the plain copy."""
    return T.player_specs(["S", "C"], "sample", masks={"S": M1, "C": M1},
                          seed_offsets={"C": 1}, search={"S": setting})


def assert_same_game(ours, theirs, leg):
    """A tournament record against a search_ab record of the same game."""
    side = AB.LEGS.index(leg)                            # where the searching seat sat
    for name in GAME_FIELDS:
        assert ours[name] == theirs[name], name
    for name in STAT_FIELDS:
        assert ours["search_stats"][side][name] == theirs[name], name
    assert [ours["a_td"], ours["b_td"]] == [theirs["a_td"], theirs["b_td"]]
    assert ours["result_a"] == theirs["result_a"] and ours["leg"] == theirs["leg"] == leg
    assert ours["natural"] and theirs["natural"] and theirs["invalid"] == []
    setting = ours["search"][side]
    assert {k: v for k, v in theirs["settings"]["search"].items()} == \
        {k: setting[k] for k in theirs["settings"]["search"]}
    assert theirs["settings"]["gamma"] == setting["gamma"]
    assert theirs["hashes"]["reward_manifest_sha256"] == ours["reward_manifest_sha256"]


@pytest.mark.parametrize("seed, leg", [(31000, "A_home"), (31007, "B_home")])
def test_cross_tool_a_tournament_game_is_the_game_search_ab_plays(net, tmp_path,
                                                                 seed, leg):
    """The two tools seed alike (tournament.sampling_seed by side, the sampling
    offset by player, the engine by seed), so the same seed, orientation and
    setting must give the same game: the same action trail, final state, sampling
    state, and the same search statistics down to every predicted gain."""
    plan = ab_plan(AB.TEST_POLICY + "11", 2, 2, 0.0, seed)
    player = AB.Player(plan, "0" * 64, "t1", AB.TEST_POLICY + "11", FIXTURE)
    theirs = player.play(seed, leg, "s")
    ours = T.pair_game({"S": net, "C": net}, "S", "C", 0, leg, seed0=seed,
                       specs=tournament_specs(QUICK))
    assert_same_game(ours, theirs, leg)
    side = AB.LEGS.index(leg)
    assert sum(ours["search_stats"][side]["deviations"].values()) > 0
    # The search changed the game: this is not the plain game twice.
    plain = player.play(seed, leg, "plain")
    assert plain["action_trail_sha256"] != ours["action_trail_sha256"]
    # The deviations are in the record's log-probability sum: the played action's
    # probability under the policy, which is finite and differs from a0's.
    assert all(math.isfinite(v) for v in ours["logprob_sum"])


# ---- the shadow: the seat's opponent-view state ----------------------------------------------
def _stepped(match, steps, check):
    for _ in range(steps):
        team = match.observe()
        before = [getattr(s, "_after_declare", None) for s in match.seats]
        outs = [match.seats[s].step(*match.seat_inputs(s), s == team) for s in (0, 1)]
        check(team, before, outs)
        if match.apply(team, outs):
            return True
    return False


@pytest.mark.parametrize("side", [0, 1])
def test_the_shadow_is_the_opponents_state_when_the_opponent_is_the_same_network(
        net, side):
    """Self-play under the same masks: the opponent-view state the seat keeps must
    be the real opponent's recurrent state, bit for bit, on every engine step, and
    its reading of the opponent's last declaration must be the opponent's own.
    That is what search_ab.py handed its rollouts, read here without ever
    touching the opponent seat."""
    search = [None, None]
    search[side] = S.search_setting(2, 2, 0.0)
    match = T.Match(net, net, 43000 + side, masks=(MASKS, MASKS), seed_offsets=(0, 1),
                    search=tuple(search))
    seat, other = match.seats[side], match.seats[1 - side]
    seen = {"steps": 0, "declared": 0}

    def check(team, before, outs):
        assert torch.equal(seat.shadow, other.state)
        assert seat._opponent_declared == before[1 - side]
        seen["steps"] += 1
        seen["declared"] += bool(before[1 - side])

    try:
        _stepped(match, 400, check)
    finally:
        match.close()
    assert seen["steps"] == 400 and seen["declared"] > 3
    assert seat.stats["shadow_forwards"] == 400 == seat.forwards
    assert sum(seat.stats["searched"].values()) > 10
    assert seat.engine is None and seat.rollouts is None       # closed with its match


def test_the_shadow_against_a_bot_is_this_network_on_the_bots_row(net):
    """A bot has no network. The shadow is kept the same way: this seat's network
    forwarded on the bot's observation row once per engine step, from zero."""
    bot = T.ScriptedBot("offense")
    match = T.Match(net, bot, 43100, masks=(M1, None), search=(QUICK, None))
    seat = match.seats[0]
    reference = {"state": net.initial_state(1), "declared": False}

    def check(team, before, outs):
        _, _, reference["state"] = net.forward_eval(
            torch.from_numpy(match.eng.obs(1)).reshape(1, -1), reference["state"])
        assert torch.equal(seat.shadow, reference["state"])
        agent, last = match.eng.last_action()
        if agent == 1:
            reference["declared"] = last[0] == E.A["DECLARE"]
        assert seat._opponent_declared == reference["declared"]

    try:
        _stepped(match, 300, check)
    finally:
        match.close()
    assert torch.count_nonzero(seat.shadow) > 0 and seat.stats["shadow_forwards"] == 300


# ---- opponents: a bot, another network --------------------------------------------------------
@pytest.mark.parametrize("opponent", ["offense", "contact", "network"])
def test_a_search_seat_plays_a_bot_and_another_network(net, other_net, opponent):
    """The opponent is not this network, so the rollouts' opponent model is wrong
    by design. The game must still run and pass integrity, and with delta =
    infinity it must be the plain game against that opponent."""
    foe = other_net if opponent == "network" else T.ScriptedBot(opponent)
    masks = (M1, None)
    seed = 44000 + ["offense", "contact", "network"].index(opponent)
    plain, plain_seats = play(net, foe, seed, masks=masks, offsets=(0, 0))
    same, seats = play(net, foe, seed, masks=masks, offsets=(0, 0), search=(IDENTITY, None))
    for name in ("action_trail_sha256", "final_digest", "logprob_sum", "score", "c_steps"):
        assert same[name] == plain[name], name
    assert torch.equal(seats[0].generator.get_state(), plain_seats[0].generator.get_state())
    assert torch.equal(seats[0].state, plain_seats[0].state)
    searched, _ = play(net, foe, seed, masks=masks, offsets=(0, 0), search=(QUICK, None))
    for rec in (same, searched):
        stats = rec["search_stats"][0]
        assert rec["natural"] and not any(rec["integrity"].values())
        assert rec["integrity_checks"] == list(S.INTEGRITY_CHECKS)
        assert stats["error_rollouts"] == 0 and sum(stats["searched"].values()) > 20
        assert stats["shadow_forwards"] == rec["c_steps"] and T.check_record(rec) == []
        assert rec["bots"] == [None, None if opponent == "network" else opponent]
        assert rec["search"] == [rec["search"][0], None] and rec["masks"] == [["m1"], None]
    assert sum(searched["search_stats"][0]["deviations"].values()) > 0
    assert searched["action_trail_sha256"] != plain["action_trail_sha256"]


# ---- determinism ------------------------------------------------------------------------------
def test_the_same_seed_and_setting_give_the_same_record_twice(net):
    specs = tournament_specs(QUICK)
    players = {"S": net, "C": net}
    games = [T.pair_game(players, "S", "C", 2, "B_home", seed0=45000, specs=specs) for _ in range(2)]
    assert _essential(games[0]) == _essential(games[1])
    stats = games[0]["search_stats"][1]                   # B_home: S sat AWAY
    assert games[0]["search"] == [None, QUICK] and sum(stats["deviations"].values()) > 0
    assert len(stats["predicted_gains"]) == sum(stats["deviations"].values())
    assert all(gain > 0.0 for gain in stats["predicted_gains"])


def write_blob(folder, policy):
    """A random network as a checkpoint blob with its lineage sidecar, so the
    tournament's worker processes can load it."""
    from training.convert_checkpoint import torch_to_cuda
    blob = torch_to_cuda(policy.state_dict(), P.HIDDEN, P.LAYERS, E.OBS_SIZE, E.ACT_SIZES)
    path = os.path.join(str(folder), T.CHECKPOINT_BLOB)
    blob.astype("<f4").tofile(path)
    lineage = {"checkpoint": {"sha256": P.sha256_file(path)},
               "compatibility": {"observation_abi": P.OBS_ABI, "observation_version": 6,
                                 "action_abi": P.ACTION_ABI, "policy_hidden_size": P.HIDDEN,
                                 "policy_num_layers": P.LAYERS}}
    with open(path + ".lineage.json", "w") as f:
        json.dump(lineage, f)
    return path


@pytest.fixture(scope="module")
def blob(tmp_path_factory, net):
    path = write_blob(tmp_path_factory.mktemp("blob"), net)
    loaded, _ = P.load_checkpoint(path)
    for ours, theirs in zip(loaded.parameters(), net.parameters()):
        assert torch.equal(ours, theirs)                  # the blob is the test network
    return path


def cli(blob, out, *extra, workers=1, search="S=2:2:0", seed0=46000):
    args = ["--checkpoint", f"S={blob}", "--checkpoint", f"C={blob}", "--pair", "S,C,2",
            "--mask", "S=m1", "--mask", "C=m1", "--sampling-offset", "C=1",
            "--seed0", str(seed0), "--workers", str(workers), "--out-dir", str(out)]
    if search:
        args += ["--search", search]
    return T.main(args + list(extra))


@pytest.fixture(scope="module")
def identity_run(tmp_path_factory, blob):
    """A gate's identity sample in miniature, through the command line: I searches
    with delta inf, P is the same player without the search, both against C."""
    out = tmp_path_factory.mktemp("identity") / "run"
    patch = pytest.MonkeyPatch()
    patch.setenv("OMP_NUM_THREADS", "1")
    patch.delenv(T.GAMES_PER_WORKER_ENV, raising=False)
    text = io.StringIO()
    try:
        with contextlib.redirect_stdout(text):
            code = T.main(["--checkpoint", f"I={blob}", "--checkpoint", f"P={blob}",
                           "--checkpoint", f"C={blob}", "--pair", "I,C,2", "--pair", "P,C,2",
                           "--mask", "I=m1", "--mask", "P=m1", "--mask", "C=m1",
                           "--sampling-offset", "C=1", "--search", "I=2:2:inf",
                           "--seed0", "46100", "--workers", "1", "--out-dir", str(out)])
    finally:
        patch.undo()
    assert code == 0
    return {"out": out, "stdout": text.getvalue()}


def _games(folder):
    with open(os.path.join(str(folder), "games.jsonl")) as f:
        return {(g["game_index"], g["leg"]): g for g in map(json.loads, f)}


@pytest.fixture(scope="module")
def cli_runs(tmp_path_factory, blob):
    """The same two searched games through the command line, on one worker
    process and on two."""
    folder = tmp_path_factory.mktemp("cli")
    patch = pytest.MonkeyPatch()
    patch.setenv("OMP_NUM_THREADS", "1")
    patch.delenv(T.GAMES_PER_WORKER_ENV, raising=False)
    try:
        assert cli(blob, folder / "w1", workers=1) == 0
        assert cli(blob, folder / "w2", workers=2) == 0
    finally:
        patch.undo()
    return folder


def test_records_do_not_depend_on_the_worker_count(cli_runs, net):
    one, two = _games(cli_runs / "w1"), _games(cli_runs / "w2")
    assert sorted(one) == sorted(two) == [(0, "A_home"), (0, "B_home")]
    for key in one:
        assert _essential(one[key]) == _essential(two[key]), key
        assert T.check_record(one[key]) == []
        side = T.LEGS.index(key[1])
        assert one[key]["search"][side] == QUICK and one[key]["search"][1 - side] is None
        assert sum(one[key]["search_stats"][side]["searched"].values()) > 50
    # And the worker processes played what the in-process path plays.
    direct = T.pair_game({"S": net, "C": net}, "S", "C", 0, "A_home", seed0=46000,
                         specs=tournament_specs(QUICK))
    assert _essential(direct) == _essential(one[(0, "A_home")])


def test_the_manifest_records_the_setting_and_a_resume_refuses_another(cli_runs, blob,
                                                                      monkeypatch, capsys):
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.delenv(T.GAMES_PER_WORKER_ENV, raising=False)
    out = cli_runs / "w1"
    with open(out / "manifest.json") as f:
        manifest = json.load(f)
    assert manifest["players"]["S"] == {"mode": "sample", "temperature": 1.0, "masks": ["m1"],
                                        "search": QUICK}
    assert manifest["players"]["C"] == {"mode": "sample", "temperature": 1.0, "masks": ["m1"],
                                        "seed_offset": 1}
    assert manifest["games_per_worker"] == 1
    assert manifest["search"] == {
        "players": ["S"],
        "reward_manifest": {"name": "r0_poss_half", "sha256": FIXTURE_SHA256,
                            "file_sha256": manifest["search"]["reward_manifest"]["file_sha256"],
                            "path": "puffer/config/rewards/r0_poss_half.json"},
        "integrity_checks": list(S.INTEGRITY_CHECKS),
        "path": "unbatched (games_per_worker 1)"}
    assert len(manifest["search"]["reward_manifest"]["file_sha256"]) == 64
    assert os.path.exists(out / "COMPLETE.json")
    before = open(out / "games.jsonl").read()
    assert cli(blob, out) == 0                            # the same run resumes, plays nothing
    assert "2 already recorded, 0 to play" in capsys.readouterr().out
    assert open(out / "games.jsonl").read() == before
    for change in ("S=2:2:0.1", "S=2:4:0", "S=3:2:0", "S=2:2:inf", "S=default", None):
        with pytest.raises(SystemExit, match="existing manifest differs on players"):
            cli(blob, out, search=change)
    # What the setting rests on is checked too: another reward manifest or list
    # of integrity checks under the same player specs.
    for key, value in (("reward_manifest", {"name": "r0_full"}), ("integrity_checks", [])):
        changed = dict(manifest, search=dict(manifest["search"], **{key: value}))
        with open(out / "manifest.json", "w") as f:
            json.dump(changed, f)
        with pytest.raises(SystemExit, match="existing manifest differs on search"):
            cli(blob, out)
    with open(out / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=1)
    assert open(out / "games.jsonl").read() == before     # nothing was played or rewritten


def test_a_searched_run_prints_a_line_per_game_and_no_result(identity_run):
    """A searched game takes minutes and the droplet runner reads a silent log as
    a dead run, so every finished game is a progress line. It carries counts and
    a rate, never a game's result."""
    lines = identity_run["stdout"].splitlines()
    progress = [line for line in lines if " games/s wall" in line]
    assert [line.split(" games,")[0] for line in progress] == ["1/4", "2/4", "3/4", "4/4"]
    shape = re.compile(r"^\d+/\d+ games, [0-9.]+ games/s wall, eta [0-9.]+ min$")
    assert all(shape.match(line) for line in progress), progress
    assert lines[0] == "4 tasks, 0 already recorded, 4 to play, 1 workers"
    assert len(lines) == 6 and json.loads(lines[-1])["complete"] is True


def test_tournament_statistics_read_a_searched_run(cli_runs):
    """The droplet job runs tournament_stats on the finished run; the extra
    fields of a searched record must not trip it."""
    from play_harness import tournament_stats as TS
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = TS.main(["--run-dir", str(cli_runs / "w1"), "--reps", "50"])
    assert code in (0, None) and "S" in out.getvalue()


# ---- the unbatched path only ------------------------------------------------------------------
def test_a_search_seat_is_refused_on_the_batched_path(net, blob, tmp_path, monkeypatch):
    specs = tournament_specs(QUICK)
    players = {"S": net, "C": net}
    with pytest.raises(ValueError, match="unbatched path only"):
        list(T.run_batched(players, [("S", "C", 0, "A_home")], 47000, slots=2, specs=specs))
    runner = T.BatchedGames(players, 47000, slots=1, specs=specs)
    with pytest.raises(ValueError, match="--games-per-worker 1"):
        runner.add(("S", "C", 0, "B_home"))
    assert runner.active == 0
    # A pair without a search seat still batches beside it.
    plain = T.player_specs(["S", "C"], "sample", masks={"S": M1, "C": M1})
    assert T.BatchedGames(players, 47000, slots=1, specs=plain).add(("S", "C", 0, "A_home"))
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.delenv(T.GAMES_PER_WORKER_ENV, raising=False)
    with pytest.raises(SystemExit, match="unbatched path only"):
        cli(blob, tmp_path / "flag", "--games-per-worker", "2")
    monkeypatch.setenv(T.GAMES_PER_WORKER_ENV, "32")
    with pytest.raises(SystemExit, match="unbatched path only"):
        cli(blob, tmp_path / "env")
    assert not (tmp_path / "flag").exists() and not (tmp_path / "env").exists()


# ---- refusals ---------------------------------------------------------------------------------
def test_who_may_search(net):
    names = ["S", "C", "bot"]
    base = dict(bots={"bot": "offense"}, masks={"S": M1})
    specs = T.player_specs(names, "sample", search={"S": S.search_setting()}, **base)
    assert specs["S"]["search"] == S.search_setting() and "search" not in specs["C"]
    assert T.search_players(specs) == ["S"]
    assert T.pair_search("S", "C", specs) == (S.search_setting(), None)
    assert T.pair_search("bot", "S", specs) == (None, S.search_setting())
    assert T.player_specs(names, "sample", **base) == T.player_specs(names, "sample", search={},
                                                                     **base)
    assert T.search_manifest(T.player_specs(names, "sample", **base)) is None
    for kwargs, needle in (
            (dict(search={"C": S.search_setting()}), "needs an action mask"),
            (dict(search={"bot": S.search_setting()}), "scripted bots"),
            (dict(search={"zzz": S.search_setting()}), "unknown players"),
            (dict(search={"S": S.search_setting()}, player_modes={"S": "argmax"}), "sample mode"),
            (dict(search={"S": S.search_setting()}, temperatures={"S": 0.5}), "temperature 1"),
            (dict(search={"S": dict(S.search_setting(), gamma=0.9)}), "gamma")):
        with pytest.raises(ValueError, match=needle):
            T.player_specs(names, "sample", **{**base, **kwargs})
    setting = S.search_setting(2, 2, 0.0)
    for kwargs, needle in (
            (dict(masks=(None, M1), search=(setting, None)), "at least one action mask"),
            (dict(masks=(M1, M1), search=(setting, None), modes=("argmax", "sample")), "samples"),
            (dict(masks=(M1, M1), search=(setting, None), temperatures=(0.5, 1.0)),
             "temperature 1"),
            (dict(masks=(M1, M1), search=(setting, None),
                  seat_factory=lambda *a, **k: PolicySeat(*a, **k)), "default seat factory"),
            (dict(masks=(M1, M1), search=(dict(setting, max_rollout_steps=50), None)),
             "max_rollout_steps")):
        with pytest.raises(ValueError, match=needle):
            T.Match(net, net, 48000, **kwargs)
    with pytest.raises(ValueError, match="does not search"):
        T.Match(net, T.ScriptedBot("contact"), 48000, masks=(M1, None), search=(None, setting))


def test_a_match_pays_the_pinned_manifest_and_binds_its_search_seats(net, lib):
    match = T.Match(net, net, 49000, masks=(M1, M1), search=(QUICK, None))
    try:
        assert match.reward_manifest is S.pinned_reward_manifest(lib)
        assert match.eng.reward_table()["reward_possession"] == pytest.approx(0.015)
        seat, other = match.seats
        assert type(seat) is S.SearchSeat and type(other) is MaskedPolicySeat
        assert seat.engine is match.eng and seat.rollouts.seat == 0
        assert match.reward_limit == seat.reward_limit == pytest.approx(1.0 + 1e-6)
    finally:
        match.close()
    assert seat.engine is None
    # A game without a search seat runs on the session it always ran on: no shaping.
    plain = T.Match(net, net, 49000, masks=(M1, M1))
    try:
        assert plain.reward_manifest is None and not plain.searching
        assert plain.eng.reward_table()["reward_possession"] == 0.0
    finally:
        plain.close()


# ---- integrity: a failure aborts the game -------------------------------------------------------
def _capped(net, search=QUICK):
    """A searched game cut at 150 decisions: quick, and near its end the rollouts
    run into the cap their clones inherit."""
    return T.play_match(net, net, 32000, masks=(M1, M1), seed_offsets=(0, 1),
                        search=(search, None), max_decisions=150,
                        allow_decision_cap=True)


def test_a_rollout_that_ends_on_the_decision_cap_is_counted_and_plays_a0(net):
    rec, _ = _capped(net)
    stats = rec["search_stats"][0]
    assert rec["truncated"] and rec["c_steps"] == 150
    assert stats["cap_rejected_rollouts"] > 0 and stats["error_rollouts"] == 0
    assert 0 < stats["cap_rejected_decisions"] <= sum(stats["searched"].values())
    # It is the game search_ab.py plays under the same cap, rejection for rejection.
    plan = dict(ab_plan(AB.TEST_POLICY + "11", 2, 2, 0.0, 32000), max_decisions=150)
    theirs = AB.Player(plan, "0" * 64, "t1", AB.TEST_POLICY + "11", FIXTURE).play(
        32000, "A_home", "s")
    assert theirs["decision_cap"] and theirs["invalid"] == []
    for name in STAT_FIELDS:
        assert stats[name] == theirs[name], name
    assert rec["action_trail_sha256"] == theirs["action_trail_sha256"]


@pytest.mark.parametrize("fault, error, needle", [
    ("real_counter", T.IntegrityError, "hard counters {'illegal': 1} after step 1"),
    ("real_reward", T.IntegrityError, "a reward is not finite at step 1"),
    ("real_clip", T.IntegrityError, "beyond the clip threshold"),
    ("real_logits", T.IntegrityError, "a logit or value is not finite"),
    ("shadow", S.SearchIntegrityError, "the opponent-view state is not finite"),
    ("clone_counter", S.SearchIntegrityError,
     "a rollout failed at engine step .*: hard counters {'precheck_collisions': 1}"),
    ("clone_reward", S.SearchIntegrityError, "a rollout failed .*a reward that is not finite"),
    ("rule", S.SearchIntegrityError, "the deviation rule could not be applied .*not finite"),
    ("fallback", T.IntegrityError, "a mask gave way"),
])
def test_an_integrity_failure_in_the_real_game_or_a_clone_aborts_the_game(
        net, monkeypatch, fault, error, needle):
    counters, rewards = E.Engine.counters, E.Engine.last_rewards
    forward = net.forward_eval
    if fault == "real_counter":
        monkeypatch.setattr(E.Engine, "counters", lambda self: counters(self) if self.is_clone
                            else dict(counters(self), illegal=1))
    elif fault == "real_reward":
        # The reward of the seat that does not search, which no return counts.
        monkeypatch.setattr(E.Engine, "last_rewards", lambda self: rewards(self) if self.is_clone
                            else (rewards(self)[0], float("nan")))
    elif fault == "real_clip":
        monkeypatch.setattr(E.Engine, "last_rewards", lambda self: rewards(self) if self.is_clone
                            else (rewards(self)[0], -1.5))
    elif fault == "real_logits":
        step = PolicySeat.step
        monkeypatch.setattr(PolicySeat, "step", lambda self, *a: dict(
            step(self, *a), value=float("inf")) if self.seat == 1 else step(self, *a))
    elif fault == "shadow":
        # The seat's second forward of the game is its first on the opponent's
        # row (its first is its own, from the same zero state).
        calls = {"n": 0}

        def poisoned(obs, state):
            logits, value, new = forward(obs, state)
            calls["n"] += 1
            if calls["n"] == 2:
                new = new.clone()
                new[0, 0, 0] = float("nan")
            return logits, value, new
        monkeypatch.setattr(net, "forward_eval", poisoned)
    elif fault == "clone_counter":
        monkeypatch.setattr(E.Engine, "counters", lambda self: counters(self)
                            if not self.is_clone else dict(counters(self), precheck_collisions=1))
    elif fault == "clone_reward":
        monkeypatch.setattr(E.Engine, "last_rewards", lambda self: rewards(self)
                            if not self.is_clone else (rewards(self)[0], float("nan")))
    elif fault == "rule":
        def refuse(returns, delta):
            raise ValueError("a return is not finite")
        monkeypatch.setattr(S, "deviation", refuse)
    else:
        monkeypatch.setattr(MaskedPolicySeat, "_fresh_stats", lambda self: {
            m: {"held": 0, "applied": 0, "fallback": 1, "mass": 0.0} for m in self.masks})
    with pytest.raises(error, match=needle):
        _capped(net)


def test_search_statistics_never_reach_a_record_with_a_failed_rollout(net, monkeypatch):
    """Belt and braces: a seat whose counters say a rollout failed cannot leave a
    record, even if the failure itself was swallowed."""
    original = S.SearchSeat._reset_search

    def tainted(self):
        original(self)
        self.stats["error_rollouts"] = 1
    monkeypatch.setattr(S.SearchSeat, "_reset_search", tainted)
    with pytest.raises(T.IntegrityError, match="rollout\\(s\\) failed"):
        _capped(net, search=IDENTITY)


# ---- the chain 55 checkpoint at the measured setting (minutes a game) --------------------------
CHECKPOINTS = os.environ.get("BBPLAY_CHECKPOINT_DIR", os.path.join(
    os.path.dirname(ROOT), "bb-play-harness", ".play-artifacts", "checkpoints"))
D425_RECORDS = os.path.join(ROOT, ".play-artifacts", "search-ab")
REAL = pytest.mark.skipif(
    os.environ.get("BBPLAY_SEARCH_REAL") != "1"
    or not os.path.exists(os.path.join(CHECKPOINTS, "chain55", T.CHECKPOINT_BLOB)),
    reason="set BBPLAY_SEARCH_REAL=1 with the chain 55 checkpoint present: these play "
           "searched games at k = 4, n = 16, minutes each")


def _checkpoint(name):
    return P.load_checkpoint(os.path.join(CHECKPOINTS, name, T.CHECKPOINT_BLOB))[0]


def d425_record(seed, leg, arm):
    """The record D425's droplets left for one game, or None."""
    if not os.path.isdir(D425_RECORDS):
        return None
    for folder, _, files in os.walk(D425_RECORDS):
        if "games.jsonl" not in files or os.sep + "ab-d425" not in folder:
            continue
        with open(os.path.join(folder, "games.jsonl")) as f:
            for line in f:
                if f'"engine_seed": {seed},' in line:
                    record = json.loads(line)
                    if AB.record_key(record) == (seed, leg, arm):
                        return record
    return None


REAL_GAMES = [tuple(item.split(":")) for item in os.environ.get(
    "BBPLAY_SEARCH_REAL_GAMES", "29200000:A_home,29200001:B_home").split(",")]


@REAL
@pytest.mark.parametrize("seed, leg", [(int(seed), leg) for seed, leg in REAL_GAMES])
def test_real_cross_tool_chain55_search_is_the_s10_game_of_d425(seed, leg, capsys):
    """Chain 55 + m1 with the search seat at the default setting against chain 55
    + m1 plain on sampling offset 1, as a tournament game, against arm s10 of
    D425's plan for the same seed and orientation, played here by search_ab.py:
    every game field and every search statistic must be equal.

    The record D425's droplets left for the game is compared too and the fields
    that differ are printed, not asserted: that was another machine, so floats
    may round differently there (measured on three games: the same action trail,
    final state and counts; predicted gains equal to five decimals; another
    sampling-state digest, which hashes the recurrent state's floats)."""
    blob = os.path.join(CHECKPOINTS, "chain55", T.CHECKPOINT_BLOB)
    chain55, sha = _checkpoint("chain55"), P.sha256_file(blob)
    ours = T.pair_game({"S": chain55, "C": chain55}, "S", "C", 0, leg, seed0=seed,
                       specs=tournament_specs(S.search_setting()))
    side = AB.LEGS.index(leg)
    stats = ours["search_stats"][side]
    lines = [f"seed {seed} {leg}: {ours['seconds']} s, search {ours['search_seconds'][side]} s, "
             f"{ours['c_steps']} steps, searched {stats['searched']}, deviations "
             f"{stats['deviations']}, rollout steps {stats['rollout_steps']}, forward rows "
             f"{stats['rollout_forward_rows']}, trail {ours['action_trail_sha256'][:16]}"]
    theirs = d425_record(seed, leg, "s10")
    if theirs is not None:
        assert theirs["hashes"]["checkpoint_sha256"] == sha
        differ = [name for name in GAME_FIELDS if ours[name] != theirs[name]] + [
            name for name in STAT_FIELDS if stats[name] != theirs[name]]
        lines.append(f"D425's droplet record of this game ({theirs['runtime']['machine']}, torch "
                     f"{theirs['runtime']['torch']}) differs on: {differ or 'nothing'}")
    with capsys.disabled():
        print("".join(f"\n[real] {line}" for line in lines), file=sys.stderr)
    player = AB.Player(ab_plan(sha, 4, 16, 0.1, seed), "0" * 64, "t1", blob, FIXTURE)
    assert_same_game(ours, player.play(seed, leg, "s"), leg)


@REAL
@pytest.mark.parametrize("opponent", ["chain37", "offense"])
def test_real_chain55_search_against_another_checkpoint_and_a_bot(opponent, capsys):
    chain55 = _checkpoint("chain55")
    foe = T.ScriptedBot(opponent) if opponent in E.BOT_TYPES else _checkpoint(opponent)
    setting = S.parse_setting(os.environ.get("BBPLAY_SEARCH_REAL_SETTING", "default"))
    rec, _ = T.play_match(chain55, foe, 29900100, masks=(M1, None),
                          search=(setting, None))
    stats = rec["search_stats"][0]
    with capsys.disabled():
        print(f"\n[real] chain55 search vs {opponent}: {rec['seconds']} s, score {rec['score']}, "
              f"searched {stats['searched']}, deviations {stats['deviations']}, cutoffs "
              f"{stats['cutoff_rollouts']}, cap rejections {stats['cap_rejected_decisions']}",
              file=sys.stderr)
    assert rec["natural"] and not any(rec["integrity"].values()) and T.check_record(rec) == []
    assert rec["integrity_checks"] == list(S.INTEGRITY_CHECKS)
    assert stats["error_rollouts"] == 0 and stats["shadow_forwards"] == rec["c_steps"]
    assert sum(stats["searched"].values()) > 50
