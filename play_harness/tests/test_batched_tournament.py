"""Batched tournament workers (--games-per-worker N).

Two kinds of test, because a batched matrix product may round differently from a
batch-1 product:

  structural  RowwisePolicy computes every batch row with its own batch-1 forward,
              so rounding is out of the picture and a batched game must equal its
              unbatched game EXACTLY. These tests pin everything batching could
              break: cross-game leakage, per-game generators, slot refill and
              reset, bots, argmax, temperature, one policy on both seats.
  numeric     the real batched forward, checked against batch-1 logits for the
              same inputs within a tolerance at every step of real games, plus
              the measured share of games whose action trail still matches.
"""
import json
import os
import sys

import numpy as np
import pytest
import torch

from play_harness import engine as E
from play_harness import tournament as T
from play_harness.policy import PolicySeat, batched_forward, random_policy

from .conftest import CHAIN25

SEED0 = 900
# Batched against batch-1 outputs, relative to the largest magnitude in the row. The
# random test policies carry activations in the thousands and their logits are sums that
# cancel, so rounding shows up near 3e-5 of the row's scale (measured on the Mac). A row
# that read another game's state or observation would be off by the scale itself.
RELATIVE_TOLERANCE = 2e-4


class RowwisePolicy:
    """A policy whose batched forward is its batch-1 forward, row by row."""

    def __init__(self, inner):
        self.inner = inner
        self.batch_sizes = []

    def initial_state(self, batch=1):
        return self.inner.initial_state(batch)

    def forward_eval(self, obs, state):
        obs = torch.as_tensor(obs).reshape(state.shape[1], -1)
        self.batch_sizes.append(obs.shape[0])
        rows = [self.inner.forward_eval(obs[r:r + 1], state[:, r:r + 1])
                for r in range(obs.shape[0])]
        return (torch.cat([r[0] for r in rows], 0), torch.cat([r[1] for r in rows], 0),
                torch.cat([r[2] for r in rows], 1))


class CheckedPolicy:
    """The real batched forward, compared with batch-1 forwards of the same inputs."""

    def __init__(self, inner):
        self.inner = inner
        self.max_logit_diff = 0.0
        self.max_state_diff = 0.0
        self.rows = 0
        self.rows_bit_equal = 0
        self.max_batch = 0

    def initial_state(self, batch=1):
        return self.inner.initial_state(batch)

    def forward_eval(self, obs, state):
        obs = torch.as_tensor(obs).reshape(state.shape[1], -1)
        logits, value, new_state = self.inner.forward_eval(obs, state)
        self.max_batch = max(self.max_batch, obs.shape[0])
        for r in range(obs.shape[0]):
            one_logits, _, one_state = self.inner.forward_eval(obs[r:r + 1], state[:, r:r + 1])
            for name, one, many in (("max_logit_diff", one_logits[0], logits[r]),
                                    ("max_state_diff", one_state[:, 0], new_state[:, r])):
                scale = max(1.0, float(one.abs().max()))
                setattr(self, name, max(getattr(self, name),
                                        float((one - many).abs().max()) / scale))
            self.rows += 1
            self.rows_bit_equal += bool(torch.equal(one_logits[0], logits[r]))
        return logits, value, new_state


class ProbeSeat(PolicySeat):
    """Remembers the recurrent state its first forward was given."""

    first_input_state = None

    @property
    def state(self):
        if self.first_input_state is None:
            self.first_input_state = self._state.clone()
        return self._state

    @state.setter
    def state(self, value):
        self._state = value

    def reset_match(self):
        super().reset_match()
        self.first_input_state = None


def probe_factory(made):
    def factory(policy, seat, mode="sample", seed=0, temperature=1.0):
        s = ProbeSeat(policy, seat, mode=mode, seed=seed, temperature=temperature)
        made.append(s)
        return s
    return factory


@pytest.fixture(scope="module")
def raw():
    return {"A": random_policy(seed=1, scale=0.05), "B": random_policy(seed=2, scale=0.05)}


@pytest.fixture(scope="module")
def rowwise(raw):
    return {"A": RowwisePolicy(raw["A"]), "B": RowwisePolicy(raw["B"]),
            "contact": T.ScriptedBot("contact"), "offense": T.ScriptedBot("offense")}


TASKS = ([("A", "B", i, leg) for i in range(3) for leg in T.LEGS]
         + [("A", "offense", 0, "A_home"), ("A", "offense", 0, "B_home"),
            ("contact", "B", 1, "A_home"), ("contact", "offense", 2, "B_home")])


def _essential(rec):
    return {k: v for k, v in rec.items() if k not in ("seconds", "pid")}


def _key(rec):
    return (*rec["pair"], rec["game_index"], rec["leg"])


@pytest.fixture(scope="module")
def solo(raw):
    """Every task played alone through the unbatched path, on the plain policies."""
    players = {**raw, "contact": T.ScriptedBot("contact"), "offense": T.ScriptedBot("offense")}
    return {t: _essential(T.pair_game(players, *t, seed0=SEED0)) for t in TASKS}


# ---- structural: exact, rounding removed ---------------------------------------------
@pytest.mark.parametrize("slots", [2, 8])
def test_batched_games_equal_their_unbatched_games_exactly(rowwise, solo, slots):
    recs = list(T.run_batched(rowwise, TASKS, SEED0, slots))
    assert sorted(_key(r) for r in recs) == sorted(TASKS)
    for rec in recs:
        assert _essential(rec) == solo[_key(rec)]
        assert T.check_record(rec) == []
    assert max(rowwise["A"].batch_sizes) > 1            # the forward really was shared


def test_a_game_does_not_depend_on_its_batch(rowwise, solo):
    """The same game in two different batches, in different rows, beside different games."""
    game = ("A", "B", 1, "A_home")
    small = [game, ("A", "B", 0, "B_home")]
    large = [("A", "offense", 0, "A_home"), ("A", "B", 2, "A_home"), ("contact", "B", 1, "A_home"),
             game, ("A", "B", 2, "B_home")]
    seen = []
    for tasks in (small, large):
        recs = {_key(r): _essential(r) for r in T.run_batched(rowwise, tasks, SEED0, len(tasks))}
        seen.append(recs[game])
    assert seen[0] == seen[1] == solo[game]


def test_finished_slots_refill_with_fresh_state_and_generators(rowwise, solo):
    made = []
    runner = T.BatchedGames(rowwise, SEED0, 2, seat_factory=probe_factory(made))
    todo, recs, order, peak = list(TASKS[:6])[::-1], [], [], 0
    while todo or runner.active:
        while todo and runner.free:
            order.append(runner.add(todo.pop()).task)
        peak = max(peak, runner.active)
        recs += runner.step()
    assert peak == 2 and len(recs) == 6                 # four games entered a used slot
    assert len(made) == 12
    for seat in made:
        assert seat.first_input_state.shape == (3, 1, 512)
        assert torch.count_nonzero(seat.first_input_state) == 0
        assert torch.count_nonzero(seat.state) > 0      # and the game did move it
    assert len({id(s.generator) for s in made}) == 12   # one generator per seat
    for rec in recs:
        assert _essential(rec) == solo[_key(rec)]       # refilled games are their solo games
    assert not runner.games


def test_seat_state_is_a_private_copy(raw):
    seats = [PolicySeat(raw["A"], 0, seed=1), PolicySeat(raw["A"], 1, seed=2)]
    eng = E.Engine(SEED0)
    try:
        logits = batched_forward(raw["A"], seats, [eng.obs(0), eng.obs(1)])
    finally:
        eng.close()
    assert logits.shape == (2, sum(E.ACT_SIZES))
    assert seats[0].state.shape == seats[1].state.shape == (3, 1, 512)
    assert seats[0].state.data_ptr() != seats[1].state.data_ptr()
    before = seats[1].state.clone()
    seats[0].state.zero_()                               # writing one seat's state ...
    assert torch.equal(seats[1].state, before)           # ... cannot reach another's


def test_batched_forward_refuses_bad_batches(raw):
    seat = PolicySeat(raw["A"], 0)
    other = PolicySeat(raw["B"], 1)
    obs = [np.zeros(E.OBS_SIZE, dtype=np.uint8)] * 2
    with pytest.raises(ValueError):
        batched_forward(raw["A"], [seat, seat], obs)              # one seat twice
    with pytest.raises(ValueError):
        batched_forward(raw["A"], [seat, other], obs)             # a seat of another policy
    with pytest.raises(ValueError):
        batched_forward(raw["A"], [seat], obs)                    # rows do not match seats
    with pytest.raises(ValueError):
        batched_forward(raw["A"], [], [])


def test_bot_seats_cost_no_forward_and_two_policies_cost_two(rowwise):
    tasks = [("A", "offense", 0, "A_home"), ("contact", "B", 1, "A_home"),
             ("contact", "offense", 2, "B_home"), ("A", "B", 0, "A_home")]
    runner = T.BatchedGames(rowwise, SEED0, 4)
    for t in tasks:
        runner.add(t)
    recs, steps = [], 0
    while runner.active:
        recs += runner.step()
        steps += 1
    policy_seats = {("A", "offense"): 1, ("contact", "B"): 1, ("contact", "offense"): 0,
                    ("A", "B"): 2}
    assert runner.forward_rows == sum(policy_seats[tuple(r["pair"])] * r["c_steps"] for r in recs)
    assert runner.forward_calls <= 2 * steps             # never more than one per policy
    for rec in recs:
        assert rec["forwards"] == [rec["c_steps"]] * 2   # the bot seat still counts its steps
        assert rec["bots"] == [p if p in E.BOT_TYPES else None for p in (rec["home"], rec["away"])]


def test_argmax_and_temperature_reach_each_seat(rowwise, raw):
    specs = {"A": {"mode": "argmax", "temperature": 1.0},
             "B": {"mode": "sample", "temperature": 0.5}}
    tasks = [("A", "B", 4, leg) for leg in T.LEGS] + [("A", "B", 5, "A_home")]
    want = {t: _essential(T.pair_game(raw, *t, seed0=SEED0, specs=specs)) for t in tasks}
    recs = list(T.run_batched(rowwise, tasks, SEED0, 3, specs=specs))
    for rec in recs:
        assert _essential(rec) == want[_key(rec)]
        modes = dict(zip((rec["home"], rec["away"]), zip(rec["modes"], rec["temperatures"])))
        assert modes == {"A": ("argmax", 1.0), "B": ("sample", 0.5)}
    plain = _essential(T.pair_game(raw, *tasks[0], seed0=SEED0))
    assert want[tasks[0]]["action_trail_sha256"] != plain["action_trail_sha256"]


def test_one_policy_on_both_seats_shares_one_forward(raw):
    inner = raw["A"]
    shared = RowwisePolicy(inner)
    players = {"x": shared, "y": shared}
    tasks = [("x", "y", 0, "A_home"), ("x", "y", 1, "B_home")]
    want = {t: _essential(T.pair_game({"x": inner, "y": inner}, *t, seed0=SEED0)) for t in tasks}
    runner = T.BatchedGames(players, SEED0, 2)
    for t in tasks:
        runner.add(t)
    recs = runner.step()
    assert runner.forward_calls == 1 and runner.forward_rows == 4
    while runner.active:
        recs += runner.step()
    for rec in recs:
        assert _essential(rec) == want[_key(rec)]


class OutOfSupportSeat(PolicySeat):
    def decide(self, logits, support, deciding):
        action, logprob = super().decide(logits, support, deciding)
        return ((E.A["END_TURN"], 7, 7) if deciding else action), logprob


class SkippingSeat(PolicySeat):
    """Counts no forward on a waiting step: the every-step contract must catch it."""

    def decide(self, logits, support, deciding):
        action, logprob = super().decide(logits, support, deciding)
        if not deciding:
            self.forwards -= 1
        return action, logprob


@pytest.mark.parametrize("factory", [OutOfSupportSeat, SkippingSeat])
def test_contract_violations_abort_the_batch(raw, factory):
    runner = T.BatchedGames(raw, SEED0, 2, seat_factory=factory)
    runner.add(("A", "B", 0, "A_home"))
    runner.add(("A", "B", 1, "A_home"))
    with pytest.raises(T.IntegrityError):
        for _ in range(10_000):
            runner.step()
    assert runner.current_task is not None               # names the game for the abort report
    runner.close()
    assert not runner.games


def test_slots_and_tasks_are_guarded(raw):
    runner = T.BatchedGames(raw, SEED0, 1)
    runner.add(("A", "B", 0, "A_home"))
    with pytest.raises(RuntimeError):
        runner.add(("A", "B", 1, "A_home"))              # full
    runner.close()
    runner = T.BatchedGames(raw, SEED0, 2)
    runner.add(("A", "B", 0, "A_home"))
    with pytest.raises(RuntimeError):
        runner.add(("A", "B", 0, "A_home"))              # the same game twice
    runner.close()
    with pytest.raises(ValueError):
        T.BatchedGames(raw, SEED0, 0)


def test_batch_slots_and_setting():
    assert T.batch_slots(8, 1000, 8) == 8
    assert T.batch_slots(8, 10, 8) == 2                  # a short run is shared out
    assert T.batch_slots(8, 0, 8) == 1
    assert T.games_per_worker_setting(None, {}) == 1
    assert T.games_per_worker_setting(None, {T.GAMES_PER_WORKER_ENV: "16"}) == 16
    assert T.games_per_worker_setting(4, {T.GAMES_PER_WORKER_ENV: "16"}) == 4   # the flag wins
    for bad in ("0", "-2", "x", str(T.MAX_GAMES_PER_WORKER + 1)):
        with pytest.raises(ValueError):
            T.games_per_worker_setting(None, {T.GAMES_PER_WORKER_ENV: bad})


# ---- numeric: the real batched forward -----------------------------------------------
@pytest.mark.parametrize("slots", [2, 8])
def test_real_batched_forward_stays_within_tolerance_of_batch_one(raw, solo, slots, capsys):
    checked = {"A": CheckedPolicy(raw["A"]), "B": CheckedPolicy(raw["B"]),
               "contact": T.ScriptedBot("contact"), "offense": T.ScriptedBot("offense")}
    recs = list(T.run_batched(checked, TASKS, SEED0, slots))
    same = sum(r["action_trail_sha256"] == solo[_key(r)]["action_trail_sha256"] for r in recs)
    rows = checked["A"].rows + checked["B"].rows
    bit_equal = checked["A"].rows_bit_equal + checked["B"].rows_bit_equal
    diff = max(checked["A"].max_logit_diff, checked["B"].max_logit_diff)
    state_diff = max(checked["A"].max_state_diff, checked["B"].max_state_diff)
    with capsys.disabled():
        print(f"\n  N={slots}: {same}/{len(recs)} action trails equal the unbatched game; "
              f"{bit_equal}/{rows} forward rows bit-equal to batch 1; max relative diff "
              f"{diff:.3g} in the logits, {state_diff:.3g} in the state", file=sys.stderr)
    assert checked["A"].max_batch > 1
    assert diff <= RELATIVE_TOLERANCE and state_diff <= RELATIVE_TOLERANCE
    # Rounding may send a rare game down another path (docs: measured rate on a droplet).
    # Anything structural would change nearly every game.
    assert same >= len(recs) - 1
    for rec in recs:
        assert T.check_record(rec) == []


# ---- CLI: flag, manifest, resume, worker processes -----------------------------------
BOT_ARGS = ["--bot", "c=contact", "--bot", "o=offense", "--games-per-pair", "6", "--seed0", "4747"]


def _games(out):
    return {_key(g): _essential(g) for g in map(json.loads, open(out / "games.jsonl"))}


def test_cli_default_is_the_unbatched_path_and_n1_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.delenv(T.GAMES_PER_WORKER_ENV, raising=False)

    def refuse(*a, **kw):
        raise AssertionError("N = 1 must not reach the batched workers")
    monkeypatch.setattr(T, "_batched_records", refuse)
    base = BOT_ARGS + ["--workers", "1"]
    assert T.main(base + ["--out-dir", str(tmp_path / "default")]) == 0
    assert T.main(base + ["--games-per-worker", "1", "--out-dir", str(tmp_path / "one")]) == 0
    assert _games(tmp_path / "default") == _games(tmp_path / "one")
    assert len(_games(tmp_path / "one")) == 6
    manifests = [json.load(open(tmp_path / d / "manifest.json")) for d in ("default", "one")]
    assert manifests[0] == manifests[1] and manifests[0]["games_per_worker"] == 1
    players = {"c": T.ScriptedBot("contact"), "o": T.ScriptedBot("offense")}
    for key, rec in _games(tmp_path / "one").items():
        assert rec == _essential(T.pair_game(players, *key, seed0=4747))


def test_cli_batched_workers_play_the_schedule_once(tmp_path, monkeypatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.delenv(T.GAMES_PER_WORKER_ENV, raising=False)
    base = BOT_ARGS + ["--workers", "2"]
    assert T.main(base + ["--games-per-worker", "1", "--out-dir", str(tmp_path / "one")]) == 0

    def refuse(*a, **kw):
        raise AssertionError("N > 1 must not use the unbatched pool")
    monkeypatch.setattr(T, "_pool_records", refuse)
    out = tmp_path / "three"
    args = base + ["--games-per-worker", "3", "--out-dir", str(out)]
    assert T.main(args + ["--max-tasks", "4"]) == 0                # a partial run ...
    assert len(_games(out)) == 4 and not (out / "COMPLETE.json").exists()
    assert T.main(args) == 0                                       # ... resumed at the same N
    assert json.load(open(out / "manifest.json"))["games_per_worker"] == 3
    assert json.load(open(out / "COMPLETE.json"))["complete"] is True
    assert len(open(out / "games.jsonl").readlines()) == 6        # each game exactly once
    assert _games(out) == _games(tmp_path / "one")                # bot games carry no floats


def test_cli_resume_refuses_another_games_per_worker(tmp_path, monkeypatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.delenv(T.GAMES_PER_WORKER_ENV, raising=False)
    out = tmp_path / "run"
    base = BOT_ARGS + ["--workers", "1", "--max-tasks", "0", "--out-dir", str(out)]
    assert T.main(base + ["--games-per-worker", "4"]) == 0
    for other in (["--games-per-worker", "1"], ["--games-per-worker", "8"], []):
        with pytest.raises(SystemExit, match="games_per_worker"):
            T.main(base + other)
    assert T.main(base + ["--games-per-worker", "4"]) == 0
    monkeypatch.setenv(T.GAMES_PER_WORKER_ENV, "4")               # the variable is the fallback
    assert T.main(base) == 0
    monkeypatch.setenv(T.GAMES_PER_WORKER_ENV, "2")
    with pytest.raises(SystemExit, match="games_per_worker"):
        T.main(base)
    with pytest.raises(SystemExit):
        T.main(base + ["--games-per-worker", "0"])


def test_cli_manifest_without_the_key_counts_as_one(tmp_path, monkeypatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.delenv(T.GAMES_PER_WORKER_ENV, raising=False)
    out = tmp_path / "run"
    base = BOT_ARGS + ["--workers", "1", "--max-tasks", "0", "--out-dir", str(out)]
    assert T.main(base) == 0
    manifest = json.load(open(out / "manifest.json"))
    old = {k: v for k, v in manifest.items() if k != "games_per_worker"}
    assert T.legacy_manifest_specs(old)["games_per_worker"] == 1
    json.dump(old, open(out / "manifest.json", "w"))
    with pytest.raises(SystemExit, match="games_per_worker"):
        T.main(base + ["--games-per-worker", "2"])
    json.dump(old, open(out / "manifest.json", "w"))
    assert T.main(base) == 0                                       # the old run resumes at 1


def test_a_failing_worker_reports_and_the_run_stops():
    import multiprocessing as mp
    tasks = [("x", "o", i, leg) for i in range(2) for leg in T.LEGS]
    initargs = ({"x": "/nope/missing.bin"}, "native", "sample", 1, None, {"o": "offense"})
    with T._batched_records(mp.get_context("spawn"), 2, initargs, tasks, 2) as records:
        first = next(iter(records))
    assert "error" in first and "missing.bin" in first["error"]


class _DeadProcess:
    pid, exitcode = 4242, -9

    def __init__(self, **kw):
        pass

    def start(self):
        pass

    def is_alive(self):
        return False

    def terminate(self):
        raise AssertionError("a dead process is not terminated")

    def join(self, timeout=None):
        pass


class _SilentQueue:
    def put(self, item):
        pass

    def get(self, timeout=None):
        raise T.queue.Empty

    def cancel_join_thread(self):
        pass

    def close(self):
        pass


class _DeadContext:
    Process, Queue = _DeadProcess, _SilentQueue


def test_a_worker_killed_without_a_report_aborts_the_run():
    tasks = [("c", "o", 0, leg) for leg in T.LEGS]
    with T._batched_records(_DeadContext, 1, (), tasks, 2, poll_seconds=0.01) as records:
        got = list(records)
    assert len(got) == 1 and "exited without a report" in got[0]["error"]
    assert "2 games outstanding" in got[0]["error"]


@pytest.mark.skipif(not os.path.exists(CHAIN25), reason="chain 25 checkpoint not present")
def test_cli_batched_checkpoint_games(tmp_path, monkeypatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.delenv(T.GAMES_PER_WORKER_ENV, raising=False)
    base = ["--checkpoint", f"c25a={CHAIN25}", "--checkpoint", f"c25b={CHAIN25}",
            "--bot", "o=offense", "--pair", "c25a,c25b,4", "--pair", "c25a,o,2",
            "--workers", "1", "--seed0", "4848"]
    assert T.main(base + ["--out-dir", str(tmp_path / "one")]) == 0
    assert T.main(base + ["--games-per-worker", "6", "--out-dir", str(tmp_path / "six")]) == 0
    one, six = _games(tmp_path / "one"), _games(tmp_path / "six")
    assert one.keys() == six.keys() and len(six) == 6
    same = sum(one[k]["action_trail_sha256"] == six[k]["action_trail_sha256"] for k in one)
    assert same >= 5                                               # rounding: see the numeric test
    for key, rec in six.items():
        assert T.check_record(rec) == []
        for field in ("engine_seed", "sampling_seeds", "team_ids", "modes", "temperatures"):
            assert rec[field] == one[key][field]


REFERENCE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(CHAIN25))),
                         "tournaments", "c34-gate-20260916", "main")


@pytest.mark.skipif(sys.platform != "darwin" or not os.path.exists(REFERENCE),
                    reason="the chain 34 reference run was played on the Mac")
def test_unbatched_path_still_reproduces_the_reference_run():
    """N = 1 byte for byte: records played before batching existed come out the same."""
    from play_harness.policy import load_checkpoint
    ckpt = os.path.dirname(os.path.dirname(CHAIN25))
    ref = {_key(g): _essential(g) for g in map(json.loads, open(os.path.join(REFERENCE, "games.jsonl")))
           if g["game_index"] < 2}
    manifest = json.load(open(os.path.join(REFERENCE, "manifest.json")))
    players = {"offense": T.ScriptedBot("offense")}
    for name in ("chain34", "chain30"):
        blob = os.path.join(ckpt, name, T.CHECKPOINT_BLOB)
        if not os.path.exists(blob):
            pytest.skip(f"missing {blob}")
        players[name] = load_checkpoint(blob)[0]
    for task in [("chain34", "chain30", 0, "A_home"), ("chain34", "chain30", 1, "B_home"),
                 ("chain34", "offense", 0, "A_home")]:
        rec = T.pair_game(players, *task, manifest["seed0"], specs=manifest["players"])
        assert _essential(rec) == ref[task]
