"""Bot exam bench: a checkpoint against an engine scripted bot, selected like the rig exam.

The rig exam (`tools/eval_vs_contact_bot.sh` with NATIVE=1, 12M steps) is a
frozen native eval: 2048 agent rows = 1024 envs on seeds SEED + i, the scripted
bot on one side of every env (`scripted_opponent_type`, `scripted_opponent_team`),
kickoff starts (`demo_reset_pct 0`), procgen rosters at the bloodbowl.ini
skill-up settings, horizon 64. At the train-to-eval boundary every env restarts
a fresh game (static_vec_reset) and recurrent state is zeroed. The native eval
logger is cumulative, and pufferl stops at the first 64-step epoch whose
cumulative completed-game count reaches eval_episodes. A cell therefore holds
the games that FINISHED by that epoch, which over-represents short games; games
still in progress are never counted.

This bench plays the same matches through the harness (PolicySeat stepped on
every c_step, BotSeat applying the engine bot through c_step's scripted branch)
and applies that selection exactly:

  * env i plays consecutive games on engine seed exam_seed + i, episodes
    episode_offset + k, back to back, so game k finishes at vec step
    L_0 + ... + L_k;
  * the stop step is the smallest multiple of `horizon` at which at least
    eval_episodes games have finished; the cell is every game finished by then.

Only games that can finish by the stop step are played to completion; a game
known to run past it is cut off at the stop step (play_match step_limit) and not
counted. Games the env ends at max_decisions are counted with their score, as
the native log does.

What cannot be matched: the exam's eval games start after a 91-epoch training
phase, so each env's episode index (and so its roster and dice draws) depends
on training-phase game lengths; the bench uses episode_offset + k instead, the
same procgen distribution but different draws.

Consecutive exam seeds share env seeds: env i on seed 43 is env i + 1 on seed
42. On the rig the training phase shifts each env's episodes and curand draws
differently, so the two exam seeds are different draws. Here nothing does, so
a second exam seed at the same episode_offset replays the first one shifted by
one env. Give every exam seed its own --episode-offset (the 2026-09-15 chain 30
bench used 0 for seed 42 and 1000 for seed 43). The champion samples with
torch, not curand. eval_episodes is not recorded in the repo; 2000 is inferred
from the exam's cell sizes (2027-2058 games, one epoch of overshoot).

  OMP_NUM_THREADS=1 .venv/bin/python -m play_harness.bot_exam \\
      --checkpoint .play-artifacts/checkpoints/chain30/0000002999975936.bin \\
      --bot offense --bot-side away --exam-seed 42 --workers 4 \\
      --out-dir .play-artifacts/bot-exam/chain30-offense-away-s42
"""
from __future__ import annotations

import argparse
import json
import math
import os
import platform
import sys
import time

from . import engine as E
from . import tournament as T
from .policy import load_checkpoint

SCHEMA = "bbplay-bot-exam-game-v1"
MANIFEST_SCHEMA = "bbplay-bot-exam-v1"
EXAM_ENVS = 1024
EXAM_HORIZON = 64
EXAM_EVAL_EPISODES = 2000
SIDES = {"home": 0, "away": 1}
MAX_ROUNDS = 64


# ---- selection ------------------------------------------------------------------
def stop_step(completions, eval_episodes, horizon):
    """Smallest multiple of horizon with at least eval_episodes completions at or
    before it, or None when the known completions never reach eval_episodes."""
    ends = sorted(int(c) for c in completions)
    if eval_episodes <= 0 or horizon <= 0:
        raise ValueError("eval_episodes and horizon must be positive")
    if len(ends) < eval_episodes:
        return None
    step = ends[eval_episodes - 1]
    return -(-step // horizon) * horizon


def select_exam_games(play, n_envs, eval_episodes, horizon, max_rounds=MAX_ROUNDS):
    """Drive consecutive games per env until the exam's stop step is exact.

    play(requests) takes a list of (env, k, limit) and returns, per request, the
    game's length in c_steps when it finished within `limit` steps (limit None =
    play to the end), else None (still in progress after `limit` steps).

    The stop step computed from the known completions is an upper bound on the
    true one, because every unknown completion only adds to the counts. Once no
    env can finish another game by that bound, the known counts are exact up to
    it and the bound is the true stop step.

    Returns {"stop_step", "games": [(env, k, start, end)], "counted": set of
    (env, k), "rounds", "requests"}.
    """
    lengths = [[] for _ in range(n_envs)]
    running_past = [False] * n_envs
    rounds = 0
    requests_made = 0
    while True:
        ends = [c for env in lengths for c in _cumulative(env)]
        stop = stop_step(ends, eval_episodes, horizon)
        requests = []
        for i in range(n_envs):
            start = sum(lengths[i])
            if running_past[i]:
                continue
            if stop is None:
                requests.append((i, len(lengths[i]), None))
            elif start < stop:
                requests.append((i, len(lengths[i]), stop - start))
        if not requests:
            break
        rounds += 1
        if rounds > max_rounds:
            raise RuntimeError(f"no stop step after {max_rounds} rounds")
        requests_made += len(requests)
        results = play(requests)
        if len(results) != len(requests):
            raise RuntimeError("play returned a different number of results")
        for (i, k, limit), length in zip(requests, results):
            if length is None:
                if limit is None:
                    raise RuntimeError(f"env {i} game {k} did not finish without a limit")
                running_past[i] = True
            else:
                if limit is not None and not 0 < length <= limit:
                    raise RuntimeError(f"env {i} game {k} length {length} outside limit {limit}")
                lengths[i].append(int(length))
    games = []
    for i, env in enumerate(lengths):
        start = 0
        for k, length in enumerate(env):
            games.append((i, k, start, start + length))
            start += length
    counted = {(i, k) for i, k, _, end in games if end <= stop}
    return {"stop_step": stop, "games": games, "counted": counted, "rounds": rounds,
            "requests": requests_made}


def _cumulative(lengths):
    total = 0
    for length in lengths:
        total += length
        yield total


def lockstep_reference(game_length, n_envs, eval_episodes, horizon, max_steps=10**7):
    """Brute-force vec simulation of the exam loop, for tests: every env steps once
    per vec step, the log is read after each horizon-step epoch, and the run stops
    at the first epoch with at least eval_episodes completions."""
    remaining = [game_length(i, 0) for i in range(n_envs)]
    episode = [0] * n_envs
    completed = []
    step = 0
    while step < max_steps:
        for _ in range(horizon):
            step += 1
            for i in range(n_envs):
                remaining[i] -= 1
                if remaining[i] == 0:
                    completed.append((i, episode[i]))
                    episode[i] += 1
                    remaining[i] = game_length(i, episode[i])
        if len(completed) >= eval_episodes:
            return step, set(completed)
    raise RuntimeError("reference simulation did not stop")


# ---- statistics -------------------------------------------------------------------
def cluster_mean(values, clusters):
    """Mean of per-game values with an env-clustered (ratio estimator) standard error.

    A cell's games on one env are selected jointly (a long first game crowds out
    a second), so the SE treats each env's games as one cluster.
    """
    values, clusters = list(values), list(clusters)
    n = len(values)
    if n == 0:
        return {"mean": None, "se": None, "n": 0, "clusters": 0}
    mean = sum(values) / n
    sums = {}
    for v, c in zip(values, clusters):
        s = sums.setdefault(c, [0.0, 0])
        s[0] += v
        s[1] += 1
    g = len(sums)
    if g < 2:
        return {"mean": mean, "se": None, "n": n, "clusters": g}
    resid = sum((y - mean * m) ** 2 for y, m in sums.values())
    se = math.sqrt(g / (g - 1) * resid) / n
    return {"mean": mean, "se": se, "n": n, "clusters": g}


def cell_summary(records, bot_side):
    """Exam-cell metrics from counted game records, champion = 1 - bot_side."""
    champ = 1 - bot_side
    rows = [r for r in records if r.get("counted")]
    envs = [r["env"] for r in rows]
    champ_td = [r["score"][champ] for r in rows]
    bot_td = [r["score"][bot_side] for r in rows]
    score = [1.0 if a > b else (0.5 if a == b else 0.0) for a, b in zip(champ_td, bot_td)]
    draw = [1.0 if a == b else 0.0 for a, b in zip(champ_td, bot_td)]
    return {
        "games": len(rows),
        "W": sum(s == 1.0 for s in score), "D": sum(s == 0.5 for s in score),
        "L": sum(s == 0.0 for s in score),
        "champion_td_per_game": cluster_mean(champ_td, envs),
        "bot_td_per_game": cluster_mean(bot_td, envs),
        "champion_score": cluster_mean(score, envs),
        "draw_rate": cluster_mean(draw, envs),
        "truncated_games": sum(bool(r.get("truncated")) for r in rows),
        "envs_with_counted_games": len(set(envs)),
    }


def agreement(bench_mean, bench_se, bench_n, exam_mean, exam_n):
    """Bench minus exam: the difference, an approximate 95% interval and z.

    The exam log carries no per-game spread, so the exam's SE is approximated as
    the bench SE scaled to the exam's game count, and the exam's own seed
    covariance is ignored. `difference_detected` says the interval excludes 0
    under that approximation. This is a difference test, not an equivalence
    test: a False value does not show the two are close, only that this sample
    did not detect a gap; read the interval for the offsets it still allows.
    """
    exam_se = bench_se * math.sqrt(bench_n / exam_n)
    se = math.sqrt(bench_se ** 2 + exam_se ** 2)
    diff = bench_mean - exam_mean
    return {"diff": diff, "se_diff": se, "z": diff / se if se else None,
            "diff_ci95": [diff - 1.96 * se, diff + 1.96 * se],
            "difference_detected": abs(diff) > 1.96 * se}


# ---- resume ------------------------------------------------------------------------
# A resume reuses cached games, so every setting that changes a game must match.
# library_sha256 is the compiled engine and bots: the bot source hashes do not cover
# bloodbowl.h, the engine helpers or the compiler flags.
RESUME_KEYS = ("checkpoint", "bot", "bot_side", "exam_seed", "envs", "eval_episodes",
               "horizon", "episode_offset", "mode", "kernel", "max_decisions",
               "library_sha256")


def resume_conflict(old, new):
    """First manifest key on which a run directory's existing manifest differs, or None."""
    for key in RESUME_KEYS:
        if old.get(key) != new.get(key):
            return key
    return None


# ---- games ------------------------------------------------------------------------
_W = {}


def _init_worker(checkpoint, kernel, bot, bot_side, exam_seed, episode_offset, mode):
    os.environ["OMP_NUM_THREADS"] = "1"
    import torch
    torch.set_num_threads(1)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass
    _W["lib"] = E.load_library()
    _W["policy"] = load_checkpoint(checkpoint, kernel=kernel)[0]
    _W["bot"] = T.ScriptedBot(bot)
    _W.update(bot_side=bot_side, exam_seed=exam_seed, episode_offset=episode_offset, mode=mode)


def play_exam_game(policy, bot, bot_side, exam_seed, env, k, limit, episode_offset=0,
                   mode="sample", lib=None):
    """Game k on env row `env`. Returns a record, or None if still running at `limit`."""
    players = (bot, policy) if bot_side == 0 else (policy, bot)
    rec, _ = T.play_match(players[0], players[1], exam_seed + env,
                          episode=episode_offset + k, mode=mode, lib=lib,
                          step_limit=limit, allow_decision_cap=True)
    if rec is None:
        return None
    rec = {"schema": SCHEMA, "env": int(env), "k": int(k), "bot": bot.kind,
           "bot_side": int(bot_side), **rec}
    if rec["forwards"] != [rec["c_steps"]] * 2:
        raise T.IntegrityError(f"forwards {rec['forwards']} vs c_steps {rec['c_steps']}")
    return rec


def _run_task(task):
    env, k, limit = task
    try:
        rec = play_exam_game(_W["policy"], _W["bot"], _W["bot_side"], _W["exam_seed"], env, k,
                             limit, episode_offset=_W["episode_offset"], mode=_W["mode"],
                             lib=_W["lib"])
        return {"task": [env, k, limit], "record": rec}
    except Exception as exc:  # returned so the parent can abort the pool cleanly
        return {"task": [env, k, limit], "error": f"{type(exc).__name__}: {exc}"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--bot", required=True, choices=T.BOT_KINDS)
    ap.add_argument("--bot-side", required=True, choices=sorted(SIDES),
                    help="the bot's side, as in the exam's cell names (contact AWAY = bot AWAY)")
    ap.add_argument("--exam-seed", type=int, default=42)
    ap.add_argument("--envs", type=int, default=EXAM_ENVS)
    ap.add_argument("--eval-episodes", type=int, default=EXAM_EVAL_EPISODES)
    ap.add_argument("--horizon", type=int, default=EXAM_HORIZON)
    ap.add_argument("--episode-offset", type=int, default=0,
                    help="first episode index per env; use a distinct offset per exam seed, "
                         "because exam seed s + 1 env i is exam seed s env i + 1")
    ap.add_argument("--mode", default="sample", choices=["sample", "argmax"])
    ap.add_argument("--kernel", default="native", choices=["native", "torch"])
    ap.add_argument("--workers", type=int, default=T.MAX_WORKERS)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args(argv)
    if not 1 <= args.workers <= T.MAX_WORKERS:
        raise SystemExit(f"--workers must be 1..{T.MAX_WORKERS}")
    if os.environ.get("OMP_NUM_THREADS") != "1":
        raise SystemExit("set OMP_NUM_THREADS=1 (one thread per worker)")
    if args.envs < 1 or args.eval_episodes < 1 or args.horizon < 1:
        raise SystemExit("--envs, --eval-episodes and --horizon must be positive")
    bot_side = SIDES[args.bot_side]

    _, prov = load_checkpoint(args.checkpoint, kernel=args.kernel)
    E.load_library()
    import torch
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "checkpoint": {"path": prov["checkpoint_path"], "sha256": prov["checkpoint_sha256"],
                       "producer": (prov["lineage"] or {}).get("producer")},
        "bot": T.bot_identity(args.bot), "bot_side": args.bot_side,
        "exam_seed": args.exam_seed, "envs": args.envs, "eval_episodes": args.eval_episodes,
        "horizon": args.horizon, "episode_offset": args.episode_offset, "mode": args.mode,
        "kernel": args.kernel, "max_decisions": T.MAX_DECISIONS,
        "rosters": "procgen (home_team=away_team=-1), skillup 4/2/0.0, kickoff starts",
        "selection": "games finished by the first horizon multiple with >= eval_episodes "
                     "completions; consecutive games per env on seed exam_seed + env",
        "library_sha256": T.library_sha256(), "workers": args.workers,
        "harness_git_head": T._git_head(), "torch": torch.__version__,
        "host": platform.node(), "python": sys.version.split()[0],
    }
    os.makedirs(args.out_dir, exist_ok=True)
    manifest_path = os.path.join(args.out_dir, "manifest.json")
    games_path = os.path.join(args.out_dir, "games.jsonl")
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            old = json.load(f)
        key = resume_conflict(old, manifest)
        if key is not None:
            raise SystemExit(f"existing manifest differs on {key} "
                             f"({old.get(key)!r} vs {manifest[key]!r}); use a new --out-dir")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=1)

    # Cache of played games: (env, k) -> finished record, or the longest limit
    # it is known to run past. Both are deterministic, so a resume reuses them.
    finished, running_past = {}, {}
    if os.path.exists(games_path):
        with open(games_path) as f:
            for line in f:
                row = json.loads(line)
                key = (row["env"], row["k"])
                if row.get("in_progress_after") is not None:
                    running_past[key] = max(running_past.get(key, 0), row["in_progress_after"])
                else:
                    finished[key] = row

    import multiprocessing as mp
    ctx = mp.get_context("spawn")
    t0 = time.time()
    played = [0]
    with open(games_path, "a") as out, ctx.Pool(
            args.workers, initializer=_init_worker,
            initargs=(args.checkpoint, args.kernel, args.bot, bot_side, args.exam_seed,
                      args.episode_offset, args.mode)) as pool:

        def play(requests):
            todo = []
            for env, k, limit in requests:
                rec = finished.get((env, k))
                if rec is not None and (limit is None or rec["c_steps"] <= limit):
                    continue
                if rec is None and limit is not None and running_past.get((env, k), 0) >= limit:
                    continue
                if rec is None:
                    todo.append((env, k, limit))
            for res in pool.imap_unordered(_run_task, todo, chunksize=2):
                if "error" in res:
                    pool.terminate()
                    with open(os.path.join(args.out_dir, "ABORTED.json"), "w") as f:
                        json.dump(res, f, indent=1)
                    raise SystemExit(f"ABORTED: {res}")
                env, k, limit = res["task"]
                rec = res["record"]
                if rec is None:
                    running_past[(env, k)] = max(running_past.get((env, k), 0), limit)
                    row = {"schema": SCHEMA, "env": env, "k": k, "in_progress_after": limit}
                else:
                    finished[(env, k)] = rec
                    row = rec
                out.write(json.dumps(row, separators=(",", ":")) + "\n")
                out.flush()
                played[0] += 1
                if played[0] % 200 == 0:
                    rate = played[0] / (time.time() - t0)
                    print(f"{played[0]} games played, {rate:.2f} games/s wall", flush=True)
            results = []
            for env, k, limit in requests:
                rec = finished.get((env, k))
                results.append(rec["c_steps"] if rec is not None
                               and (limit is None or rec["c_steps"] <= limit) else None)
            return results

        sel = select_exam_games(play, args.envs, args.eval_episodes, args.horizon)
    records = []
    for env, k, start, end in sel["games"]:
        rec = dict(finished[(env, k)])
        rec.update(start_step=start, end_step=end, counted=(env, k) in sel["counted"])
        records.append(rec)
    summary = {"cell": f"{args.bot} {args.bot_side.upper()}", "exam_seed": args.exam_seed,
               "stop_step": sel["stop_step"], "stop_epoch": sel["stop_step"] // args.horizon,
               "rounds": sel["rounds"], "games_played": played[0],
               "games_finished_known": len(records), "wall_seconds": round(time.time() - t0, 1),
               **cell_summary(records, bot_side)}
    with open(os.path.join(args.out_dir, "selected.jsonl"), "w") as f:
        for rec in records:
            f.write(json.dumps({k: rec[k] for k in ("env", "k", "start_step", "end_step",
                                                    "counted", "score", "truncated",
                                                    "team_ids")},
                               separators=(",", ":")) + "\n")
    with open(os.path.join(args.out_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
