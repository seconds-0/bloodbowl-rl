"""Tournament runner: trained checkpoints and the engine's scripted bots.

Each checkpoint seat is a PolicySeat stepped on EVERY env c_step (native
evaluation-mode recurrence), with fresh recurrent state and a fresh sampling
generator per match. Rosters are procgen as in training (random teams, training
skill-up settings), fixed by the engine seed.

Scripted bots (--bot NAME=contact|offense) are the env's own scripted opponents
(scripted_opponent_type 0 / 1). On the bot's turn the shim runs c_step through
its scripted_opponent branch, so the pick is bbe_contact_bot_pick or
bbe_offense_bot_pick on the live match, never a Python reimplementation. A bot
seat has no recurrent state and no sampling; the manifest records the bot kind
and the sha256 of its source files.

Schedule. A pair (A, B) plays game index i twice with the same engine seed
seed0 + i: leg "A_home" (A HOME, B AWAY), then leg "B_home" (B HOME, A AWAY).
The sampling seeds are keyed by side, so the swapped leg reuses both the
engine seed and the per-side sampling seeds; only which policy sits where
changes. Every pair uses the same seed list (common random numbers), and tasks
are interleaved by game index so a partial run stays balanced across pairs.

Integrity. A game is accepted only when it ends naturally (MATCH_OVER), every
hard counter is zero, and each seat made exactly one forward per engine step.
Any violation aborts the whole run.

Batching (--games-per-worker N, default 1). With N > 1 a worker keeps N games in
flight and runs ONE forward per policy per step over every seat that holds that
policy (BatchedGames). Each seat still owns its recurrent state and its sampling
generator and selects with the same code, so a game depends on its batch only
through float rounding in the matrix products: nearly every game takes the same
actions as at N = 1, a few do not, and the two settings agree in distribution.
N = 1 is the unbatched path, unchanged. The manifest records N and a resume
refuses a different one. See docs/play-harness/batched-tournaments-2026-09-17.md.

  OMP_NUM_THREADS=1 .venv/bin/python -m play_harness.tournament \\
      --games-per-pair 400 --workers 4 --out-dir .play-artifacts/tournaments/<stamp>
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import itertools
import json
import os
import platform
import queue
import struct
import subprocess
import sys
import time

from . import engine as E
from .policy import (NONE_TUPLE, PolicySeat, batched_forward, check_temperature,
                     load_checkpoint)

SCHEMA = "bbplay-tournament-game-v1"
MANIFEST_SCHEMA = "bbplay-tournament-v1"
MAX_DECISIONS = 4096
MAX_WORKERS = 4                  # default cap: protects a shared workstation
MAX_WORKERS_ENV = "BBPLAY_MAX_WORKERS"
GAMES_PER_WORKER_ENV = "BBPLAY_GAMES_PER_WORKER"
MAX_GAMES_PER_WORKER = 256
SOURCE_COMMIT_FILE = "SOURCE_COMMIT"
HARD_COUNTERS = ("illegal", "projection_collision", "error_episodes",
                 "rejected_submissions", "precheck_collisions")
LEGS = ("A_home", "B_home")
CHECKPOINT_BLOB = "0000002999975936.bin"
DEFAULT_CHECKPOINT_DIR = os.path.join(E.ROOT, ".play-artifacts", "checkpoints")


class IntegrityError(RuntimeError):
    pass


BOT_KINDS = tuple(E.BOT_TYPES)
BOT_SOURCES = ("puffer/bloodbowl/contact_bot.h", "puffer/bloodbowl/offense_bot.h",
               "play_harness/native/bbplay.c")
SCRIPTED_MODE = "scripted"


def sampling_seed(engine_seed, side, episode=0):
    """Per-side torch sampling seed; identical for both legs of a game.

    episode keys later matches on one engine seed (the exam's consecutive games
    per env row); episode 0 gives the historical tournament seeds.
    """
    return (int(engine_seed) * 1_000_003 + 17 + int(side)
            + int(episode) * 2_654_435_761) % (1 << 62)


class ScriptedBot:
    """A tournament player driven by the engine's scripted bot, not a policy."""

    def __init__(self, kind):
        if kind not in E.BOT_TYPES:
            raise ValueError(f"unknown bot {kind!r}; expected one of {sorted(E.BOT_TYPES)}")
        self.kind = kind
        self.bot_type = E.BOT_TYPES[kind]

    def __repr__(self):
        return f"ScriptedBot({self.kind!r})"


class BotSeat:
    """Seat for a ScriptedBot, stepped on every c_step like a PolicySeat.

    It holds no recurrent state and draws no random numbers. `forwards` counts
    step() calls so the runner's one-call-per-engine-step contract holds for
    both seats; on the bot's turn the runner applies the engine bot's pick with
    Engine.step_scripted.
    """

    scripted = True
    mode = SCRIPTED_MODE
    temperature = None

    def __init__(self, bot, seat, seed=0):
        if not isinstance(bot, ScriptedBot):
            raise TypeError("BotSeat needs a ScriptedBot")
        if seat not in (0, 1):
            raise ValueError("seat must be 0 (HOME) or 1 (AWAY)")
        self.policy = bot
        self.seat = seat
        self.seed = int(seed)
        self.forwards = 0
        self.decisions = 0

    def reset_match(self):
        self.forwards = 0
        self.decisions = 0

    def step(self, obs, support, deciding):
        self.forwards += 1
        if deciding:
            self.decisions += 1
            return {"tuple": None, "logprob": 0.0, "value": None, "logits": None}
        packed = list(support)
        if len(packed) != 1 or E.unpack_tuple(packed[0]) != NONE_TUPLE:
            raise AssertionError("waiting row must carry the singleton NONE support")
        return {"tuple": NONE_TUPLE, "logprob": 0.0, "value": None, "logits": None}


def bot_identity(kind, root=E.ROOT):
    """Manifest identity of a scripted bot: kind, env type, pick function, source hashes."""
    if kind not in E.BOT_TYPES:
        raise ValueError(f"unknown bot {kind!r}")
    sources = {}
    for rel in BOT_SOURCES:
        with open(os.path.join(root, rel), "rb") as f:
            sources[rel] = hashlib.sha256(f.read()).hexdigest()
    return {"kind": kind, "scripted_opponent_type": E.BOT_TYPES[kind],
            "pick_function": E.BOT_PICK_FUNCTIONS[kind], "source_sha256": sources}


def library_sha256(path=None):
    path = path or os.environ.get("BBPLAY_LIB", E.DEFAULT_LIB)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class Match:
    """One natural match in flight: the engine, both seats, the action trail and
    every per-step contract check.

    play_match drives one Match with a batch-1 forward per seat. The batched
    worker (run_batched) drives several and shares each policy's forward between
    them. Both go through the same observe / apply / record calls, so the
    contract and the record cannot drift between the two paths. All state lives
    on the instance; nothing is shared between two Matches.
    """

    def __init__(self, home_policy, away_policy, engine_seed, mode="sample", episode=0,
                 max_decisions=MAX_DECISIONS, lib=None, seat_factory=PolicySeat,
                 max_c_steps=200_000, modes=None, temperatures=(1.0, 1.0),
                 allow_decision_cap=False):
        modes = tuple(modes) if modes is not None else (mode, mode)
        temperatures = tuple(float(t) for t in temperatures)

        def seat_for(policy, side):
            seed = sampling_seed(engine_seed, side, episode)
            if isinstance(policy, ScriptedBot):
                return BotSeat(policy, side, seed=seed)
            return seat_factory(policy, side, mode=modes[side], seed=seed,
                                temperature=temperatures[side])

        self.engine_seed, self.episode = engine_seed, episode
        self.max_decisions, self.max_c_steps = max_decisions, max_c_steps
        self.allow_decision_cap = allow_decision_cap
        self.seats = (seat_for(home_policy, 0), seat_for(away_policy, 1))
        self.bots = tuple(s.policy if getattr(s, "scripted", False) else None
                          for s in self.seats)
        for seat in self.seats:
            seat.reset_match()
        self.eng = E.Engine(engine_seed, episode=episode, max_decisions=max_decisions, lib=lib)
        self.t0 = time.time()
        self.c_steps = 0
        self.trail = hashlib.sha256()
        self.logprob = [0.0, 0.0]

    def close(self):
        self.eng.close()

    def observe(self):
        """The deciding team, after checking the engine waits on a decision."""
        eng = self.eng
        if eng.status != E.STATUS_DECISION:
            raise IntegrityError(f"engine not at a decision before step {self.c_steps}: "
                                 f"status={eng.status}")
        team = eng.decision_team
        if team not in (0, 1):
            raise IntegrityError(f"decision team {team} at step {self.c_steps}")
        return team

    def seat_inputs(self, side):
        """(obs, support) for one seat's step; a bot seat takes no observation."""
        return (None if self.bots[side] else self.eng.obs(side)), self.eng.joint_support(side)

    def apply(self, team, outs):
        """Check both seats' outputs, apply the decider's action. True at the terminal."""
        eng, seats, bots = self.eng, self.seats, self.bots
        self.c_steps += 1
        c_steps = self.c_steps
        for s in (0, 1):
            if seats[s].forwards != c_steps:
                raise IntegrityError(f"seat {s} made {seats[s].forwards} forwards "
                                     f"over {c_steps} engine steps")
        if tuple(outs[1 - team]["tuple"]) != NONE_TUPLE:
            raise IntegrityError(f"waiting seat {1 - team} emitted {outs[1 - team]['tuple']}")
        if bots[team] is not None:
            idx = eng.scripted_bot_index(bots[team].bot_type)
            if idx < 0:
                raise IntegrityError(f"{bots[team].kind} bot found no pick at step "
                                     f"{c_steps}: rc={idx}")
            tup = eng.legal()[idx].tuple
            self.trail.update(struct.pack("<Biii", team, *tup))
            rc = eng.step_scripted(bots[team].bot_type, team)
        else:
            tup = tuple(int(v) for v in outs[team]["tuple"])
            if eng.tuple_index(*tup) < 0:
                raise IntegrityError(f"seat {team} tuple {tup} outside exact support")
            self.logprob[team] += float(outs[team]["logprob"])
            self.trail.update(struct.pack("<Biii", team, *tup))
            rc = eng.step(*tup)
        if rc == E.STEP_TERMINAL:
            return True
        if rc < 0:
            raise IntegrityError(f"engine refused seat {team} tuple {tup}: rc={rc}")
        return False

    def check_step_budget(self):
        if self.c_steps >= self.max_c_steps:
            raise IntegrityError(f"no terminal after {self.c_steps} steps")

    def record(self):
        """The finished game's record; raises IntegrityError unless it is acceptable."""
        eng, seats, bots, c_steps = self.eng, self.seats, self.bots, self.c_steps
        max_decisions, allow_decision_cap = self.max_decisions, self.allow_decision_cap
        logprob = self.logprob
        final = eng.final_match()
        counters = eng.counters()
        if final is None:
            raise IntegrityError("terminal step without a final match snapshot")
        natural = final.status == E.STATUS_MATCH_OVER
        truncated = counters["decisions_at_terminal"] >= max_decisions
        integrity = {k: counters[k] for k in HARD_COUNTERS}
        if not natural and not (allow_decision_cap and truncated):
            raise IntegrityError(f"match ended unnaturally: status={final.status}")
        if any(integrity.values()):
            raise IntegrityError(f"nonzero integrity counters: {integrity}")
        if counters["steps"] != c_steps:
            raise IntegrityError(f"engine applied {counters['steps']} steps, runner {c_steps}")
        if truncated and not allow_decision_cap:
            raise IntegrityError("decision budget reached at the terminal step")
        modes = tuple(s.mode for s in seats)
        temperatures = tuple(s.temperature for s in seats)
        return {
            "engine_seed": int(self.engine_seed), "episode": int(self.episode),
            "mode": modes[0] if modes[0] == modes[1] else "mixed",
            "modes": list(modes), "temperatures": list(temperatures),
            "bots": [b.kind if b else None for b in bots],
            "sampling_seeds": [seats[0].seed, seats[1].seed],
            "team_ids": [int(final.team_id[0]), int(final.team_id[1])],
            "teams": [eng.team_display(final.team_id[0]), eng.team_display(final.team_id[1])],
            "score": [int(final.score[0]), int(final.score[1])],
            "natural": bool(natural), "truncated": bool(truncated),
            "final_status": int(final.status),
            "half": int(final.half), "turns": [int(final.turn[0]), int(final.turn[1])],
            "c_steps": c_steps, "forwards": [seats[0].forwards, seats[1].forwards],
            "decisions": [seats[0].decisions, seats[1].decisions],
            "engine_decisions": counters["decisions_at_terminal"],
            "logprob_sum": [round(logprob[0], 4), round(logprob[1], 4)],
            "integrity": integrity, "action_trail_sha256": self.trail.hexdigest(),
            "final_digest": f"{eng.digest():016x}", "seconds": round(time.time() - self.t0, 3),
        }


def play_match(home_policy, away_policy, engine_seed, mode="sample", episode=0,
               max_decisions=MAX_DECISIONS, lib=None, seat_factory=PolicySeat,
               max_c_steps=200_000, modes=None, temperatures=(1.0, 1.0),
               step_limit=None, allow_decision_cap=False):
    """One natural match between two players. Returns (record, seats).

    A player is a policy (seated through seat_factory) or a ScriptedBot (seated
    as a BotSeat). modes / temperatures are (HOME, AWAY); modes defaults to
    `mode` for both, and bot seats ignore both. Raises IntegrityError on any
    violation of the tournament contract.

    Bench-only options, never used by the tournament CLI:
      step_limit          stop after this many c_steps without a terminal and
                          return (None, seats): the match is still in progress;
      allow_decision_cap  accept a match the env ended at max_decisions (the
                          native env counts it as a finished game) and mark the
                          record truncated instead of aborting.
    """
    match = Match(home_policy, away_policy, engine_seed, mode=mode, episode=episode,
                  max_decisions=max_decisions, lib=lib, seat_factory=seat_factory,
                  max_c_steps=max_c_steps, modes=modes, temperatures=temperatures,
                  allow_decision_cap=allow_decision_cap)
    seats = match.seats
    try:
        while True:
            team = match.observe()
            outs = [seats[s].step(*match.seat_inputs(s), s == team) for s in (0, 1)]
            if match.apply(team, outs):
                break
            if step_limit is not None and match.c_steps >= step_limit:
                return None, seats
            match.check_step_budget()
        return match.record(), seats
    finally:
        match.close()


def pair_seating(a, b, index, leg, seed0, mode="sample", specs=None):
    """Who sits where in one leg: (home, away, engine seed, modes, temperatures)."""
    if leg not in LEGS:
        raise ValueError(f"unknown leg {leg!r}")
    home, away = (a, b) if leg == "A_home" else (b, a)
    seed = int(seed0) + int(index)
    spec = lambda name: {"mode": mode, "temperature": 1.0, **((specs or {}).get(name) or {})}  # noqa: E731
    return (home, away, seed, (spec(home)["mode"], spec(away)["mode"]),
            (spec(home)["temperature"], spec(away)["temperature"]))


def pair_record(a, b, index, leg, home, away, record):
    """A match record from A's perspective."""
    a_side = 0 if leg == "A_home" else 1
    a_td, b_td = record["score"][a_side], record["score"][1 - a_side]
    return {"schema": SCHEMA, "pair": [a, b], "game_index": int(index), "leg": leg,
            "home": home, "away": away, "a_td": a_td, "b_td": b_td,
            "result_a": "W" if a_td > b_td else ("D" if a_td == b_td else "L"),
            **record}


def pair_game(policies, a, b, index, leg, seed0, mode="sample", lib=None,
              seat_factory=PolicySeat, specs=None):
    """One leg of one game of pair (a, b), recorded from A's perspective.

    specs maps a player name to {"mode", "temperature"}; a missing name plays
    `mode` at temperature 1.
    """
    home, away, seed, modes, temperatures = pair_seating(a, b, index, leg, seed0, mode, specs)
    record, _ = play_match(policies[home], policies[away], seed, lib=lib,
                           seat_factory=seat_factory, modes=modes, temperatures=temperatures)
    return pair_record(a, b, index, leg, home, away, record)


class _Slot:
    __slots__ = ("task", "home", "away", "match", "team", "inputs")


class BatchedGames:
    """Up to `slots` pair games in flight, one forward per policy per step.

    step() advances every game by one engine step:
      1. each game reports its deciding team and both seats' (obs, support);
      2. the policy seats are grouped by policy object and each group gets ONE
         batched_forward, so a pair of two checkpoints costs two forwards per step
         whatever the number of games, and a bot seat costs none;
      3. every seat selects from its own logits row through PolicySeat.decide, with
         its own generator, mode and temperature;
      4. each game applies its action through the same Match checks as play_match.
    A finished game leaves its slot and its record is returned. Nothing of it
    survives: the recurrent state and the generator live on the seats, the seats
    live on the Match, and add() builds a new Match with fresh seats. There is no
    batch-shaped state buffer to reset, so a slot cannot leak state into the next
    game. Seats must be PolicySeat-like (policy, state, decide).
    """

    def __init__(self, policies, seed0, slots, mode="sample", lib=None, specs=None,
                 seat_factory=PolicySeat):
        if int(slots) < 1:
            raise ValueError("slots must be at least 1")
        self.policies, self.seed0, self.slots = policies, seed0, int(slots)
        self.mode, self.lib, self.specs, self.seat_factory = mode, lib, specs, seat_factory
        self.games = []
        self.current_task = None         # the task being handled, for error reports
        self.forward_calls = 0
        self.forward_rows = 0

    @property
    def active(self):
        return len(self.games)

    @property
    def free(self):
        return self.slots - len(self.games)

    def add(self, task):
        if not self.free:
            raise RuntimeError("no free slot")
        a, b, index, leg = task
        if any(g.task == tuple(task) for g in self.games):
            raise RuntimeError(f"task {task} is already in flight")
        self.current_task = tuple(task)
        home, away, seed, modes, temperatures = pair_seating(a, b, index, leg, self.seed0,
                                                             self.mode, self.specs)
        slot = _Slot()
        slot.task, slot.home, slot.away = tuple(task), home, away
        slot.match = Match(self.policies[home], self.policies[away], seed, lib=self.lib,
                           seat_factory=self.seat_factory, modes=modes,
                           temperatures=temperatures)
        slot.team, slot.inputs = None, None
        self.games.append(slot)
        self.current_task = None
        return slot

    def step(self):
        """Advance every game in flight by one engine step; return finished records."""
        groups = {}                      # id(policy) -> (policy, seats, observations)
        for slot in self.games:
            self.current_task = slot.task
            match = slot.match
            slot.team = match.observe()
            slot.inputs = [match.seat_inputs(s) for s in (0, 1)]
            for s in (0, 1):
                if match.bots[s] is None:
                    seat = match.seats[s]
                    group = groups.setdefault(id(seat.policy), (seat.policy, [], []))
                    group[1].append(seat)
                    group[2].append(slot.inputs[s][0])
        self.current_task = None
        logits_of = {}                   # id(seat) -> that seat's logits row
        for policy, seats, observations in groups.values():
            logits = batched_forward(policy, seats, observations)
            self.forward_calls += 1
            self.forward_rows += len(seats)
            for row, seat in enumerate(seats):
                logits_of[id(seat)] = logits[row]
        finished, still = [], []
        for slot in self.games:
            self.current_task = slot.task
            match, team = slot.match, slot.team
            outs = []
            for s in (0, 1):
                seat, (_, support) = match.seats[s], slot.inputs[s]
                if match.bots[s] is not None:
                    outs.append(seat.step(None, support, s == team))
                else:
                    action, logprob = seat.decide(logits_of.pop(id(seat)), support, s == team)
                    outs.append({"tuple": action, "logprob": logprob})
            slot.inputs = None
            if match.apply(team, outs):
                try:
                    record = match.record()
                finally:
                    match.close()
                a, b, index, leg = slot.task
                finished.append(pair_record(a, b, index, leg, slot.home, slot.away, record))
            else:
                match.check_step_budget()
                still.append(slot)
        self.current_task = None
        if logits_of:
            raise AssertionError("a forward row was not consumed by its seat")
        self.games = still
        return finished

    def close(self):
        for slot in self.games:
            slot.match.close()
        self.games = []


def run_batched(policies, tasks, seed0, slots, mode="sample", lib=None, specs=None,
                seat_factory=PolicySeat):
    """Play `tasks` in one process with up to `slots` games in flight; yields records
    as games finish. The queue-fed worker does the same with tasks from a pipe."""
    runner = BatchedGames(policies, seed0, slots, mode=mode, lib=lib, specs=specs,
                          seat_factory=seat_factory)
    todo = list(tasks)[::-1]
    try:
        while todo or runner.active:
            while todo and runner.free:
                runner.add(todo.pop())
            yield from runner.step()
    finally:
        runner.close()


def schedule(names, games_per_pair, seed0, pairs=None):
    """Tasks (a, b, index, leg) interleaved by game index across pairs.

    pairs: None for the full round robin at games_per_pair, else a list of
    (a, b) or (a, b, n) with n games for that pair (default games_per_pair).
    A pair with fewer games stops at its last index while larger pairs go on.
    """
    if pairs is None:
        pairs = list(itertools.combinations(names, 2))
    sized = []
    for p in pairs:
        a, b = p[0], p[1]
        n = p[2] if len(p) > 2 and p[2] is not None else games_per_pair
        if n is None or n <= 0 or n % 2:
            raise ValueError(f"games for pair {a},{b} must be a positive even number")
        if a == b or a not in names or b not in names:
            raise ValueError(f"pair {a},{b} needs two distinct known players")
        sized.append((a, b, int(n)))
    if len({frozenset(p[:2]) for p in sized}) != len(sized):
        raise ValueError("duplicate pair")
    most = max(n for _, _, n in sized)
    return [(a, b, i, leg) for i in range(most // 2) for a, b, n in sized if i < n // 2
            for leg in LEGS]


def parse_pair(text):
    parts = text.split(",")
    if len(parts) not in (2, 3):
        raise ValueError(f"--pair wants A,B or A,B,N, got {text!r}")
    return (parts[0], parts[1], int(parts[2]) if len(parts) == 3 else None)


def parse_assignments(items, cast=str):
    out = {}
    for item in items:
        name, _, value = item.partition("=")
        if not name or not value:
            raise ValueError(f"expected NAME=VALUE, got {item!r}")
        out[name] = cast(value)
    return out


def legacy_manifest_specs(old):
    """Fill `players` and `pairs` into a manifest written before per-player specs.

    Such a run played every checkpoint at the run mode and T = 1, in the full
    round robin at games_per_pair, so a resume must match exactly that.
    """
    old = dict(old)
    names = list(old.get("checkpoints") or {})
    if "players" not in old:
        old["players"] = {n: {"mode": old.get("mode"), "temperature": 1.0} for n in names}
    if "pairs" not in old:
        old["pairs"] = [[a, b, old.get("games_per_pair")] for a, b in itertools.combinations(names, 2)]
    old.setdefault("bots", {})
    old.setdefault("bot_library_sha256", None)
    old.setdefault("games_per_worker", 1)    # runs before batching played one game at a time
    return old


def player_specs(names, mode, player_modes=None, temperatures=None, bots=None):
    """Per-player specs. Checkpoints get {mode, temperature}; bots get {bot: kind}
    and refuse mode or temperature overrides."""
    player_modes, temperatures, bots = player_modes or {}, temperatures or {}, bots or {}
    unknown = (set(player_modes) | set(temperatures) | set(bots)) - set(names)
    if unknown:
        raise ValueError(f"mode/temperature/bot for unknown players {sorted(unknown)}")
    tuned_bots = (set(player_modes) | set(temperatures)) & set(bots)
    if tuned_bots:
        raise ValueError(f"scripted bots take no mode or temperature: {sorted(tuned_bots)}")
    specs = {}
    for name in names:
        if name in bots:
            if bots[name] not in E.BOT_TYPES:
                raise ValueError(f"unknown bot {bots[name]!r} for {name}; "
                                 f"expected one of {sorted(E.BOT_TYPES)}")
            specs[name] = {"bot": bots[name]}
            continue
        m = player_modes.get(name, mode)
        if m not in ("sample", "argmax"):
            raise ValueError(f"unknown mode {m!r} for {name}")
        specs[name] = {"mode": m, "temperature": check_temperature(temperatures.get(name, 1.0))}
    return specs


def task_key(a, b, index, leg):
    return f"{a}|{b}|{index}|{leg}"


def check_record(rec):
    """Parent-side re-check of the contract on a finished record."""
    problems = []
    if not rec.get("natural"):
        problems.append("unnatural ending")
    if any(rec.get("integrity", {}).get(k, 1) for k in HARD_COUNTERS):
        problems.append(f"integrity {rec.get('integrity')}")
    if rec.get("forwards") != [rec.get("c_steps")] * 2:
        problems.append(f"forwards {rec.get('forwards')} vs c_steps {rec.get('c_steps')}")
    return problems


# ---- worker pool --------------------------------------------------------------
_W = {}


def _init_worker(checkpoints, kernel, mode, seed0, specs=None, bots=None):
    os.environ["OMP_NUM_THREADS"] = "1"
    import torch
    torch.set_num_threads(1)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass
    _W["lib"] = E.load_library()
    loaded = {}                      # one policy object per blob; seats hold all state
    for path in set(checkpoints.values()):
        loaded[path] = load_checkpoint(path, kernel=kernel)[0]
    _W["policies"] = {name: loaded[path] for name, path in checkpoints.items()}
    _W["policies"].update({name: ScriptedBot(kind) for name, kind in (bots or {}).items()})
    _W["mode"], _W["seed0"], _W["specs"] = mode, seed0, specs


def _run_task(task):
    a, b, index, leg = task
    try:
        rec = pair_game(_W["policies"], a, b, index, leg, _W["seed0"], mode=_W["mode"],
                        lib=_W["lib"], specs=_W["specs"])
        rec["pid"] = os.getpid()
        return rec
    except Exception as exc:  # returned so the parent can abort the pool cleanly
        return {"error": f"{type(exc).__name__}: {exc}", "task": list(task)}


@contextlib.contextmanager
def _pool_records(ctx, workers, initargs, pending):
    """N = 1: one game per worker at a time, the unbatched path."""
    with ctx.Pool(workers, initializer=_init_worker, initargs=initargs) as pool:
        yield pool.imap_unordered(_run_task, pending, chunksize=1)


def _batched_worker(worker_id, task_q, result_q, initargs, slots):
    """Worker process for N > 1: keep up to `slots` games in flight.

    Free slots are refilled from the task queue before every step. The worker
    blocks on the queue only when it has no game to step. A None task means the
    schedule is exhausted: finish the games in flight, report, exit.
    """
    runner = None
    try:
        _init_worker(*initargs)
        runner = BatchedGames(_W["policies"], _W["seed0"], slots, mode=_W["mode"],
                              lib=_W["lib"], specs=_W["specs"])
        draining = False
        while True:
            while not draining and runner.free:
                try:
                    task = task_q.get(block=not runner.active)
                except queue.Empty:
                    break
                if task is None:
                    draining = True
                else:
                    runner.add(tuple(task))
            if not runner.active:
                if draining:
                    break
                continue
            for rec in runner.step():
                rec["pid"] = os.getpid()
                result_q.put(rec)
        result_q.put({"worker_done": worker_id, "forward_calls": runner.forward_calls,
                      "forward_rows": runner.forward_rows})
    except BaseException as exc:  # reported so the parent can abort every worker
        task = getattr(runner, "current_task", None)
        result_q.put({"error": f"{type(exc).__name__}: {exc}", "task": list(task or ())})
    finally:
        if runner is not None:
            runner.close()


def batch_slots(games_per_worker, pending, workers):
    """Slots per worker: N, but no more than an even share of what is left to play,
    so a short run does not pile into the first workers while the others idle."""
    share = -(-int(pending) // max(1, int(workers)))
    return max(1, min(int(games_per_worker), share))


MAX_TASK_WINDOW = 16_000             # a multiprocessing queue holds about 32,000 entries


@contextlib.contextmanager
def _batched_records(ctx, workers, initargs, pending, games_per_worker, poll_seconds=5.0):
    """N > 1: records from `workers` processes that each batch several games.

    Yields an iterator of records, {"error": ...} dicts included, in finish order.
    A worker that dies without reporting becomes an error record. Leaving the
    context stops every worker, also when a worker failed to start.

    Tasks are fed as results come back: at most `window` games are handed out and
    not yet reported (twice what the workers hold in flight, so a free slot always
    finds a queued task). A multiprocessing queue is bounded by the OS, so putting a
    whole schedule in before reading any result can block the parent for good, with
    the workers blocked on a full result queue or already dead.
    """
    if not pending:
        yield iter(())
        return
    workers = min(int(workers), len(pending))
    slots = batch_slots(games_per_worker, len(pending), workers)
    window = max(workers, min(2 * workers * slots, MAX_TASK_WINDOW))
    procs, queues = [], []

    def records(task_q, result_q):
        outstanding = {task_key(*t) for t in pending}
        todo = iter(pending)
        state = {"submitted": 0, "reported": 0, "sentinels": False}

        def feed():
            while state["submitted"] - state["reported"] < window:
                task = next(todo, None)
                if task is None:
                    if not state["sentinels"]:
                        state["sentinels"] = True
                        for _ in procs:
                            task_q.put(None)
                    return
                task_q.put(tuple(task))
                state["submitted"] += 1

        feed()
        finished_workers = 0
        checked = time.time()
        while finished_workers < len(procs):
            try:
                rec = result_q.get(timeout=poll_seconds)
            except queue.Empty:
                rec = None
            if rec is None or time.time() - checked >= poll_seconds:
                # A worker killed from outside (the OOM killer, a signal) reports nothing.
                # Its games would never arrive, so stop now, not after the others finish.
                checked = time.time()
                dead = [p.pid for p in procs if p.exitcode not in (None, 0)]
                if dead or (rec is None and not any(p.is_alive() for p in procs)):
                    yield {"error": f"worker process(es) {dead or 'all'} exited without a "
                                    f"report ({len(outstanding)} games outstanding)", "task": []}
                    return
            if rec is None:
                continue
            if "worker_done" in rec:
                finished_workers += 1
                continue
            if "error" not in rec:
                key = task_key(*rec["pair"], rec["game_index"], rec["leg"])
                if key not in outstanding:
                    yield {"error": f"game {key} was reported twice or never scheduled",
                           "task": [*rec["pair"], rec["game_index"], rec["leg"]]}
                    return
                outstanding.discard(key)
                state["reported"] += 1
                feed()
            yield rec
        if outstanding:
            yield {"error": f"workers finished with {len(outstanding)} games unplayed, e.g. "
                            f"{sorted(outstanding)[0]}", "task": []}

    try:
        task_q, result_q = ctx.Queue(), ctx.Queue()
        queues += [task_q, result_q]
        for i in range(workers):
            proc = ctx.Process(target=_batched_worker, daemon=True,
                               args=(i, task_q, result_q, initargs, slots))
            proc.start()
            procs.append(proc)               # only started processes are cleaned up
        yield records(task_q, result_q)
    finally:
        for proc in procs:
            if proc.is_alive():
                proc.terminate()
        for proc in procs:
            proc.join(timeout=10)
        for q in queues:
            q.cancel_join_thread()
            q.close()


def games_per_worker_setting(value=None, environ=None):
    """--games-per-worker, else BBPLAY_GAMES_PER_WORKER, else 1 (unbatched)."""
    raw = value
    if raw is None:
        raw = (os.environ if environ is None else environ).get(GAMES_PER_WORKER_ENV)
    if raw is None or raw == "":
        return 1
    try:
        n = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"games per worker must be an integer in 1..{MAX_GAMES_PER_WORKER}, "
                         f"got {raw!r}")
    if not 1 <= n <= MAX_GAMES_PER_WORKER:
        raise ValueError(f"games per worker must be in 1..{MAX_GAMES_PER_WORKER}, got {raw!r}")
    return n


def discover_checkpoints(directory=DEFAULT_CHECKPOINT_DIR):
    out = {}
    if not os.path.isdir(directory):
        return out
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name, CHECKPOINT_BLOB)
        if os.path.exists(path) and os.path.exists(path + ".lineage.json"):
            out[name] = path
    return out


def worker_cap(environ=None):
    """Largest accepted --workers: MAX_WORKERS unless BBPLAY_MAX_WORKERS raises it.

    Every game is single-threaded, so a dedicated tournament box (see
    tools/droplet_tournament.py) sets the variable to its core count. Worker
    count never changes a game: sampling seeds are keyed by (engine seed, side).
    """
    raw = (os.environ if environ is None else environ).get(MAX_WORKERS_ENV)
    if raw is None or raw == "":
        return MAX_WORKERS
    try:
        cap = int(raw)
    except ValueError:
        raise ValueError(f"{MAX_WORKERS_ENV} must be a positive integer, got {raw!r}")
    if cap < 1:
        raise ValueError(f"{MAX_WORKERS_ENV} must be a positive integer, got {raw!r}")
    return cap


def _git_head(root=None):
    """HEAD of the checkout, else the SOURCE_COMMIT file a git-archive sync leaves."""
    root = root or E.ROOT
    try:
        return subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        pass
    try:
        with open(os.path.join(root, SOURCE_COMMIT_FILE)) as f:
            return f.read().strip() or None
    except OSError:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--checkpoint", action="append", default=[], metavar="NAME=BLOB",
                    help="repeatable; default every chain directory under "
                         ".play-artifacts/checkpoints")
    ap.add_argument("--bot", action="append", default=[], metavar="NAME=KIND",
                    help="repeatable; seat an engine scripted bot as player NAME, "
                         f"KIND one of {', '.join(BOT_KINDS)}")
    ap.add_argument("--games-per-pair", type=int, default=None,
                    help="even; split evenly between the two legs (default for --pair)")
    ap.add_argument("--pair", action="append", default=[], metavar="A,B[,N]",
                    help="repeatable; play only these pairs (A first), N games each; "
                         "default the full round robin")
    ap.add_argument("--seed0", type=int, default=20260915)
    ap.add_argument("--mode", default="sample", choices=["sample", "argmax"],
                    help="default selection mode for every player")
    ap.add_argument("--player-mode", action="append", default=[], metavar="NAME=MODE",
                    help="repeatable; per-player sample|argmax override")
    ap.add_argument("--temperature", action="append", default=[], metavar="NAME=T",
                    help="repeatable; per-player policy temperature (logits / T), default 1.0")
    ap.add_argument("--kernel", default="native", choices=["native", "torch"])
    ap.add_argument("--workers", type=int, default=MAX_WORKERS)
    ap.add_argument("--games-per-worker", type=int, default=None, metavar="N",
                    help="games each worker keeps in flight, sharing one batched forward "
                         f"per policy per step (default ${GAMES_PER_WORKER_ENV}, else 1 = "
                         "unbatched). N > 1 changes float rounding, so a few games take "
                         "other actions than at N = 1; registered gates run at 1")
    ap.add_argument("--max-tasks", type=int, default=None,
                    help="pilot: play only the first K scheduled tasks")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args(argv)
    try:
        cap = worker_cap()
    except ValueError as exc:
        raise SystemExit(str(exc))
    if not 1 <= args.workers <= cap:
        raise SystemExit(f"--workers must be 1..{cap} (raise the cap on a dedicated "
                         f"box with {MAX_WORKERS_ENV})")
    try:
        games_per_worker = games_per_worker_setting(args.games_per_worker)
    except ValueError as exc:
        raise SystemExit(str(exc))
    if os.environ.get("OMP_NUM_THREADS") != "1":
        raise SystemExit("set OMP_NUM_THREADS=1 (one thread per worker)")
    if args.checkpoint:
        checkpoints = dict(item.split("=", 1) for item in args.checkpoint)
    else:
        checkpoints = discover_checkpoints()
    try:
        bots = parse_assignments(args.bot)
    except ValueError as exc:
        raise SystemExit(str(exc))
    clash = set(bots) & set(checkpoints)
    if clash:
        raise SystemExit(f"names used by both a checkpoint and a bot: {sorted(clash)}")
    names = list(checkpoints) + list(bots)
    if len(names) < 2:
        raise SystemExit("need at least two players (checkpoints or bots)")
    try:
        pairs = [parse_pair(p) for p in args.pair] or None
        specs = player_specs(names, args.mode,
                             parse_assignments(args.player_mode),
                             parse_assignments(args.temperature, float), bots=bots)
        tasks = schedule(names, args.games_per_pair, args.seed0, pairs=pairs)
    except ValueError as exc:
        raise SystemExit(str(exc))
    pair_sizes = {}
    for a, b, _, _ in tasks:
        pair_sizes[(a, b)] = pair_sizes.get((a, b), 0) + 1

    os.makedirs(args.out_dir, exist_ok=True)
    games_path = os.path.join(args.out_dir, "games.jsonl")
    manifest_path = os.path.join(args.out_dir, "manifest.json")
    if args.max_tasks is not None:
        tasks = tasks[:args.max_tasks]

    provenance = {}
    for name, path in checkpoints.items():
        _, prov = load_checkpoint(path, kernel=args.kernel)
        lineage = prov["lineage"] or {}
        provenance[name] = {"path": prov["checkpoint_path"], "sha256": prov["checkpoint_sha256"],
                            "producer": lineage.get("producer"),
                            "compatibility": lineage.get("compatibility")}
    import torch
    bot_ids = {name: bot_identity(kind) for name, kind in bots.items()}
    if bots:
        E.load_library()             # build a stale shim before hashing it
    manifest = {"schema": MANIFEST_SCHEMA, "checkpoints": provenance,
                "bots": bot_ids,
                "bot_library_sha256": library_sha256() if bots else None,
                "games_per_pair": args.games_per_pair, "seed0": args.seed0,
                "mode": args.mode, "players": specs,
                "pairs": [[a, b, n] for (a, b), n in pair_sizes.items()],
                "kernel": args.kernel, "workers": args.workers,
                "games_per_worker": games_per_worker,
                "omp_num_threads": 1, "max_decisions": MAX_DECISIONS,
                "rosters": "procgen (home_team=away_team=-1), skillup 4/2/0.0",
                "legs": list(LEGS), "sampling_seed": "keyed by (engine seed, side)",
                "tasks": len(tasks), "harness_git_head": _git_head(),
                "torch": torch.__version__, "host": platform.node(),
                "python": sys.version.split()[0]}
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            old = legacy_manifest_specs(json.load(f))
        # bot_library_sha256 is the compiled shim a bot seat runs; the bot sources do not
        # cover bloodbowl.h, the engine helpers or the compiler flags, so a resume on a
        # different build would mix opponents. Checkpoint-only runs record None.
        # games_per_worker changes float rounding in the forward, so a resume at another
        # value would mix two slightly different samplers in one run; a manifest without
        # the key was played unbatched and counts as 1.
        for key in ("checkpoints", "bots", "bot_library_sha256", "games_per_pair", "seed0",
                    "mode", "players", "pairs", "kernel", "games_per_worker"):
            if old.get(key) != manifest[key]:
                raise SystemExit(f"existing manifest differs on {key} "
                                 f"({old.get(key)!r} vs {manifest[key]!r}); use a new --out-dir")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=1)

    done = set()
    if os.path.exists(games_path):
        with open(games_path) as f:
            for line in f:
                rec = json.loads(line)
                done.add(task_key(*rec["pair"], rec["game_index"], rec["leg"]))
    pending = [t for t in tasks if task_key(*t) not in done]
    print(f"{len(tasks)} tasks, {len(done)} already recorded, {len(pending)} to play, "
          f"{args.workers} workers"
          + (f", {games_per_worker} games per worker" if games_per_worker > 1 else ""),
          flush=True)

    import multiprocessing as mp
    ctx = mp.get_context("spawn")
    t0 = time.time()
    played = 0
    abort = None
    initargs = (checkpoints, args.kernel, args.mode, args.seed0, specs, bots)
    if games_per_worker == 1:
        source = _pool_records(ctx, args.workers, initargs, pending)
    else:
        source = _batched_records(ctx, args.workers, initargs, pending, games_per_worker)
    with open(games_path, "a") as out, source as records:
        for rec in records:
            problems = [rec["error"]] if "error" in rec else check_record(rec)
            if problems:
                abort = {"task": rec["task"] if "task" in rec
                         else [*rec["pair"], rec["game_index"], rec["leg"]],
                         "problems": problems, "played": played}
                break                    # leaving the context stops every worker
            out.write(json.dumps(rec, separators=(",", ":")) + "\n")
            out.flush()
            played += 1
            if played % 100 == 0 or played == len(pending):
                rate = played / (time.time() - t0)
                eta = (len(pending) - played) / rate if rate else float("inf")
                print(f"{played}/{len(pending)} games, {rate:.2f} games/s wall, "
                      f"eta {eta / 60:.1f} min", flush=True)
    wall = time.time() - t0
    if abort is not None:
        with open(os.path.join(args.out_dir, "ABORTED.json"), "w") as f:
            json.dump(abort, f, indent=1)
        print(f"ABORTED: {abort}", flush=True)
        return 2
    summary = {"played": played, "wall_seconds": round(wall, 1),
               "games_per_second_wall": round(played / wall, 3) if wall else None,
               "complete": len(done) + played == len(tasks)}
    if summary["complete"] and args.max_tasks is None:
        with open(os.path.join(args.out_dir, "COMPLETE.json"), "w") as f:
            json.dump(summary, f, indent=1)
    print(json.dumps(summary), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
