"""Policy-vs-policy tournament runner: both seats are trained checkpoints.

Each seat is a PolicySeat stepped on EVERY env c_step (native evaluation-mode
recurrence), with fresh recurrent state and a fresh sampling generator per
match. Rosters are procgen as in training (random teams, training skill-up
settings), fixed by the engine seed.

Schedule. A pair (A, B) plays game index i twice with the same engine seed
seed0 + i: leg "A_home" (A HOME, B AWAY), then leg "B_home" (B HOME, A AWAY).
The sampling seeds are keyed by side, so the swapped leg reuses both the
engine seed and the per-side sampling seeds; only which policy sits where
changes. Every pair uses the same seed list (common random numbers), and tasks
are interleaved by game index so a partial run stays balanced across pairs.

Integrity. A game is accepted only when it ends naturally (MATCH_OVER), every
hard counter is zero, and each seat made exactly one forward per engine step.
Any violation aborts the whole run.

  OMP_NUM_THREADS=1 .venv/bin/python -m play_harness.tournament \\
      --games-per-pair 400 --workers 4 --out-dir .play-artifacts/tournaments/<stamp>
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import platform
import struct
import subprocess
import sys
import time

from . import engine as E
from .policy import NONE_TUPLE, PolicySeat, check_temperature, load_checkpoint

SCHEMA = "bbplay-tournament-game-v1"
MANIFEST_SCHEMA = "bbplay-tournament-v1"
MAX_DECISIONS = 4096
MAX_WORKERS = 4
HARD_COUNTERS = ("illegal", "projection_collision", "error_episodes",
                 "rejected_submissions", "precheck_collisions")
LEGS = ("A_home", "B_home")
CHECKPOINT_BLOB = "0000002999975936.bin"
DEFAULT_CHECKPOINT_DIR = os.path.join(E.ROOT, ".play-artifacts", "checkpoints")


class IntegrityError(RuntimeError):
    pass


def sampling_seed(engine_seed, side):
    """Per-side torch sampling seed; identical for both legs of a game."""
    return (int(engine_seed) * 1_000_003 + 17 + int(side)) % (1 << 62)


def play_match(home_policy, away_policy, engine_seed, mode="sample", episode=0,
               max_decisions=MAX_DECISIONS, lib=None, seat_factory=PolicySeat,
               max_c_steps=200_000, modes=None, temperatures=(1.0, 1.0)):
    """One natural match between two policies. Returns (record, seats).

    modes / temperatures are (HOME, AWAY); modes defaults to `mode` for both.
    Raises IntegrityError on any violation of the tournament contract.
    """
    modes = tuple(modes) if modes is not None else (mode, mode)
    temperatures = tuple(float(t) for t in temperatures)
    seats = (seat_factory(home_policy, 0, mode=modes[0], seed=sampling_seed(engine_seed, 0),
                          temperature=temperatures[0]),
             seat_factory(away_policy, 1, mode=modes[1], seed=sampling_seed(engine_seed, 1),
                          temperature=temperatures[1]))
    for seat in seats:
        seat.reset_match()
    eng = E.Engine(engine_seed, episode=episode, max_decisions=max_decisions, lib=lib)
    t0 = time.time()
    c_steps = 0
    trail = hashlib.sha256()
    logprob = [0.0, 0.0]
    try:
        while True:
            if eng.status != E.STATUS_DECISION:
                raise IntegrityError(f"engine not at a decision before step {c_steps}: "
                                     f"status={eng.status}")
            team = eng.decision_team
            if team not in (0, 1):
                raise IntegrityError(f"decision team {team} at step {c_steps}")
            outs = [seats[s].step(eng.obs(s), eng.joint_support(s), s == team)
                    for s in (0, 1)]
            c_steps += 1
            for s in (0, 1):
                if seats[s].forwards != c_steps:
                    raise IntegrityError(f"seat {s} made {seats[s].forwards} forwards "
                                         f"over {c_steps} engine steps")
            if tuple(outs[1 - team]["tuple"]) != NONE_TUPLE:
                raise IntegrityError(f"waiting seat {1 - team} emitted {outs[1 - team]['tuple']}")
            tup = tuple(int(v) for v in outs[team]["tuple"])
            if eng.tuple_index(*tup) < 0:
                raise IntegrityError(f"seat {team} tuple {tup} outside exact support")
            logprob[team] += float(outs[team]["logprob"])
            trail.update(struct.pack("<Biii", team, *tup))
            rc = eng.step(*tup)
            if rc == E.STEP_TERMINAL:
                break
            if rc < 0:
                raise IntegrityError(f"engine refused seat {team} tuple {tup}: rc={rc}")
            if c_steps >= max_c_steps:
                raise IntegrityError(f"no terminal after {c_steps} steps")
        final = eng.final_match()
        counters = eng.counters()
        if final is None:
            raise IntegrityError("terminal step without a final match snapshot")
        natural = final.status == E.STATUS_MATCH_OVER
        integrity = {k: counters[k] for k in HARD_COUNTERS}
        if not natural:
            raise IntegrityError(f"match ended unnaturally: status={final.status}")
        if any(integrity.values()):
            raise IntegrityError(f"nonzero integrity counters: {integrity}")
        if counters["steps"] != c_steps:
            raise IntegrityError(f"engine applied {counters['steps']} steps, runner {c_steps}")
        if counters["decisions_at_terminal"] >= max_decisions:
            raise IntegrityError("decision budget reached at the terminal step")
        record = {
            "engine_seed": int(engine_seed), "episode": int(episode),
            "mode": modes[0] if modes[0] == modes[1] else "mixed",
            "modes": list(modes), "temperatures": list(temperatures),
            "sampling_seeds": [seats[0].seed, seats[1].seed],
            "team_ids": [int(final.team_id[0]), int(final.team_id[1])],
            "teams": [eng.team_display(final.team_id[0]), eng.team_display(final.team_id[1])],
            "score": [int(final.score[0]), int(final.score[1])],
            "natural": bool(natural), "final_status": int(final.status),
            "half": int(final.half), "turns": [int(final.turn[0]), int(final.turn[1])],
            "c_steps": c_steps, "forwards": [seats[0].forwards, seats[1].forwards],
            "decisions": [seats[0].decisions, seats[1].decisions],
            "engine_decisions": counters["decisions_at_terminal"],
            "logprob_sum": [round(logprob[0], 4), round(logprob[1], 4)],
            "integrity": integrity, "action_trail_sha256": trail.hexdigest(),
            "final_digest": f"{eng.digest():016x}", "seconds": round(time.time() - t0, 3),
        }
        return record, seats
    finally:
        eng.close()


def pair_game(policies, a, b, index, leg, seed0, mode="sample", lib=None,
              seat_factory=PolicySeat, specs=None):
    """One leg of one game of pair (a, b), recorded from A's perspective.

    specs maps a player name to {"mode", "temperature"}; a missing name plays
    `mode` at temperature 1.
    """
    if leg not in LEGS:
        raise ValueError(f"unknown leg {leg!r}")
    home, away = (a, b) if leg == "A_home" else (b, a)
    seed = int(seed0) + int(index)
    spec = lambda name: {"mode": mode, "temperature": 1.0, **((specs or {}).get(name) or {})}  # noqa: E731
    record, _ = play_match(policies[home], policies[away], seed, lib=lib,
                           seat_factory=seat_factory,
                           modes=(spec(home)["mode"], spec(away)["mode"]),
                           temperatures=(spec(home)["temperature"], spec(away)["temperature"]))
    a_side = 0 if leg == "A_home" else 1
    a_td, b_td = record["score"][a_side], record["score"][1 - a_side]
    return {"schema": SCHEMA, "pair": [a, b], "game_index": int(index), "leg": leg,
            "home": home, "away": away, "a_td": a_td, "b_td": b_td,
            "result_a": "W" if a_td > b_td else ("D" if a_td == b_td else "L"),
            **record}


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
    return old


def player_specs(names, mode, player_modes=None, temperatures=None):
    player_modes, temperatures = player_modes or {}, temperatures or {}
    unknown = (set(player_modes) | set(temperatures)) - set(names)
    if unknown:
        raise ValueError(f"mode/temperature for unknown players {sorted(unknown)}")
    specs = {}
    for name in names:
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


def _init_worker(checkpoints, kernel, mode, seed0, specs=None):
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


def discover_checkpoints(directory=DEFAULT_CHECKPOINT_DIR):
    out = {}
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name, CHECKPOINT_BLOB)
        if os.path.exists(path) and os.path.exists(path + ".lineage.json"):
            out[name] = path
    return out


def _git_head():
    try:
        return subprocess.run(["git", "-C", E.ROOT, "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--checkpoint", action="append", default=[], metavar="NAME=BLOB",
                    help="repeatable; default every chain directory under "
                         ".play-artifacts/checkpoints")
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
    ap.add_argument("--max-tasks", type=int, default=None,
                    help="pilot: play only the first K scheduled tasks")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args(argv)
    if not 1 <= args.workers <= MAX_WORKERS:
        raise SystemExit(f"--workers must be 1..{MAX_WORKERS}")
    if os.environ.get("OMP_NUM_THREADS") != "1":
        raise SystemExit("set OMP_NUM_THREADS=1 (one thread per worker)")
    if args.checkpoint:
        checkpoints = dict(item.split("=", 1) for item in args.checkpoint)
    else:
        checkpoints = discover_checkpoints()
    names = list(checkpoints)
    if len(names) < 2:
        raise SystemExit("need at least two checkpoints")
    try:
        pairs = [parse_pair(p) for p in args.pair] or None
        specs = player_specs(names, args.mode,
                             parse_assignments(args.player_mode),
                             parse_assignments(args.temperature, float))
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
    manifest = {"schema": MANIFEST_SCHEMA, "checkpoints": provenance,
                "games_per_pair": args.games_per_pair, "seed0": args.seed0,
                "mode": args.mode, "players": specs,
                "pairs": [[a, b, n] for (a, b), n in pair_sizes.items()],
                "kernel": args.kernel, "workers": args.workers,
                "omp_num_threads": 1, "max_decisions": MAX_DECISIONS,
                "rosters": "procgen (home_team=away_team=-1), skillup 4/2/0.0",
                "legs": list(LEGS), "sampling_seed": "keyed by (engine seed, side)",
                "tasks": len(tasks), "harness_git_head": _git_head(),
                "torch": torch.__version__, "host": platform.node(),
                "python": sys.version.split()[0]}
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            old = legacy_manifest_specs(json.load(f))
        for key in ("checkpoints", "games_per_pair", "seed0", "mode", "players", "pairs",
                    "kernel"):
            if old.get(key) != manifest[key]:
                raise SystemExit(f"existing manifest differs on {key}; use a new --out-dir")
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
          f"{args.workers} workers", flush=True)

    import multiprocessing as mp
    ctx = mp.get_context("spawn")
    t0 = time.time()
    played = 0
    abort = None
    with open(games_path, "a") as out, ctx.Pool(
            args.workers, initializer=_init_worker,
            initargs=(checkpoints, args.kernel, args.mode, args.seed0, specs)) as pool:
        for rec in pool.imap_unordered(_run_task, pending, chunksize=1):
            problems = [rec["error"]] if "error" in rec else check_record(rec)
            if problems:
                abort = {"task": rec.get("task") or [*rec["pair"], rec["game_index"], rec["leg"]],
                         "problems": problems, "played": played}
                pool.terminate()
                break
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
