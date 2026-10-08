#!/usr/bin/env python3
"""Search distillation: accept label shards against the plan, before any of them is used.

A shard directory is accepted when:
  - every file SHA256SUMS lists hashes to its value, and the shard's plan copy
    is this plan;
  - there is no FAILED.json, and COMPLETE.json names this plan's hash, the
    shard, the checkpoint's hash, the harness commit, the tool hashes, the
    reward manifest, the label settings and the integrity list, with every game
    natural and no failed rollout;
  - roots.jsonl, games.jsonl and other.jsonl hash to what COMPLETE.json recorded;
  - the games are exactly the shard's engine seeds, each once, each ended in the
    engine's match-over status with every hard counter zero, seat A on the side
    the game index gives, and each trail hashes to its recorded value;
  - the roots belong to those games in the counts the games recorded
    (min(per_class, searchable) per class), and the other-decision sample
    likewise;
  - every root has min(candidates, support size) x screen_rollouts finite
    returns, or is a cap rejection with none; a0 is its first candidate; the
    seat's rule recomputed here from the stored returns gives the stored
    decision, best alternative, gain and standard error; a label is the best
    alternative of a deviation root and of no other;
  - every deviation root has 2 x judge_pairs judgment returns; a missing return
    occurs only with a counted cap stop; the kept pairs, the fresh gain and the
    judged, false and confirmed flags recomputed here are the stored ones;
  - at most cap_rejection_ceiling of the shard's roots are cap rejections;
  - the counts in COMPLETE.json are the recount's.
With several shards, all must have run on one compiled engine library.

It reads records only. It imports nothing from the harness: the rule is
restated in deviation() below, and the tests hold it equal to the harness's.

  distill_accept.py --plan PLAN.json --expect-sha256 H --shard-dir NAME=DIR [...]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import distill_common as C  # noqa: E402

STATUS_MATCH_OVER = 2       # play_harness/engine.py; the tests check it against the export
HARD = ("illegal", "projection_collision", "error_episodes", "rejected_submissions",
        "precheck_collisions")
SETTING_KEYS = ("seed0", "per_class", "other_per_game", "candidates", "screen_rollouts",
                "delta", "judge_pairs", "judge_first_index", "judge_min_pairs", "masks")
MAX_PROBLEMS = 40


def deviation(returns, delta):
    """play_harness.search.deviation, operation for operation: (deviate, best
    alternative as a row index, its paired mean gain over a0, the floored
    standard error)."""
    returns = np.asarray(returns, dtype=np.float64)
    if returns.ndim != 2 or returns.shape[0] < 2 or returns.shape[1] < 2:
        raise ValueError("the deviation rule needs two candidates and two rollouts")
    if not np.isfinite(returns).all():
        raise ValueError("a return is not finite")
    returns = returns[:, np.isfinite(returns).all(axis=0)]
    n = returns.shape[1]
    index = np.arange(n)
    d = returns[1:, index] - returns[0, index]
    mean, se = d.mean(axis=1), d.std(axis=1, ddof=1) / np.sqrt(n)
    best = int(np.argmax(mean))
    floor = np.sqrt(returns.var(axis=1, ddof=1).mean() / n)
    gain, error = float(mean[best]), float(max(se[best], floor))
    return bool(gain > delta and gain > 2.0 * error), 1 + best, gain, error


def parse_sums(text):
    out = {}
    for line in text.splitlines():
        if line.strip():
            digest, name = line.split(None, 1)
            out[name.strip().lstrip("*")] = digest
    return out


def read_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def root_problems(r, label, where):
    """One root's record against the label settings."""
    out = []
    support = sorted(set(int(t) for t in r.get("support") or []))
    k = min(int(label["candidates"]), len(support))
    n = int(label["screen_rollouts"])
    tuples = r.get("tuples") or []
    if len(support) < 2 or r.get("support_size") != len(support):
        out.append(f"{where}: support size {r.get('support_size')} with {len(support)} tuples")
    if len(tuples) != k:
        out.append(f"{where}: {len(tuples)} candidates, min(candidates, support) is {k}")
    if not tuples or list(tuples[0]) != list(r.get("a0") or []):
        out.append(f"{where}: a0 is not the first candidate")
    if r.get("rollouts") != n:
        out.append(f"{where}: {r.get('rollouts')} screening rollouts, {n} registered")
    stops = r.get("stops") or {}
    if stops.get("error"):
        out.append(f"{where}: {stops['error']} failed rollout(s)")
    if r.get("cap_rejected"):
        if not stops.get("cap") or r.get("returns") is not None or r.get("deviate") or \
                r.get("label") is not None or r.get("judgment") is not None:
            out.append(f"{where}: a cap rejection that carries returns, a label or no cap stop")
        return out
    returns = r.get("returns")
    ok = isinstance(returns, list) and len(returns) == k and all(
        isinstance(row, list) and len(row) == n and all(
            isinstance(v, float) and math.isfinite(v) for v in row) for row in returns)
    if not ok or stops.get("cap"):
        out.append(f"{where}: not {k} x {n} finite screening returns")
        return out
    deviate, best, gain, se = deviation(returns, float(label["delta"]))
    if (r.get("deviate"), r.get("best"), r.get("gain"), r.get("se")) != (deviate, best, gain, se):
        out.append(f"{where}: stored rule result {(r.get('deviate'), r.get('best'), r.get('gain'), r.get('se'))} "
                   f"!= recomputed {(deviate, best, gain, se)}")
        return out
    j = r.get("judgment")
    if not deviate:
        if r.get("label") is not None or j is not None:
            out.append(f"{where}: a label or a judgment without a deviation")
        return out
    if list(r.get("label") or []) != list(tuples[best]):
        out.append(f"{where}: the label is not the best alternative")
    pairs = int(label["judge_pairs"])
    rows = (j or {}).get("returns")
    if not (isinstance(rows, list) and len(rows) == 2 and all(len(row) == pairs for row in rows)):
        out.append(f"{where}: not 2 x {pairs} judgment returns")
        return out
    if j.get("first_index") != label["judge_first_index"] or j.get("pairs") != pairs:
        out.append(f"{where}: judgment indices are not the registered ones")
    if (j.get("stops") or {}).get("error"):
        out.append(f"{where}: a failed judgment rollout")
    a0, alt = (np.array([np.nan if v is None else v for v in row], dtype=np.float64)
               for row in rows)
    valid = np.isfinite(a0) & np.isfinite(alt)
    missing = int(np.isnan(a0).sum() + np.isnan(alt).sum())
    capped = int(j.get("capped_rollouts") or 0)
    if missing != capped or capped != int((j.get("stops") or {}).get("cap") or 0):
        out.append(f"{where}: {missing} missing judgment returns against {capped} cap stops")
    kept = int(valid.sum())
    d = alt[valid] - a0[valid]
    fresh = float(d.mean()) if kept else None
    fresh_se = float(d.std(ddof=1) / math.sqrt(kept)) if kept > 1 else None
    judged = kept >= int(label["judge_min_pairs"])
    want = {"kept_pairs": kept, "dropped_pairs": pairs - kept, "judged": bool(judged),
            "fresh_gain": fresh, "fresh_se": fresh_se,
            "false": bool(judged and fresh <= 0.0),
            "confirmed": bool(judged and fresh_se is not None and fresh > 2.0 * fresh_se)}
    differ = [key for key, value in want.items() if j.get(key) != value]
    if differ:
        out.append(f"{where}: judgment fields {differ} differ from the recount")
    return out


def shard_problems(directory, shard, plan, plan_sha):
    """(problems, summary) for one shard directory. An empty list is acceptance."""
    problems, summary = [], {"shard": shard, "directory": os.path.abspath(directory)}
    spec = {s["name"]: s for s in plan["shards"]}.get(shard)
    if spec is None:
        return [f"{shard}: not a shard of this plan"], summary
    path = lambda name: os.path.join(directory, name)  # noqa: E731
    if os.path.exists(path("FAILED.json")):
        return [f"{shard}: FAILED.json is present"], summary
    for name in ("SHA256SUMS", "COMPLETE.json", "plan.json", "roots.jsonl", "games.jsonl",
                 "other.jsonl"):
        if not os.path.isfile(path(name)):
            return [f"{shard}: {name} is missing"], summary
    with open(path("SHA256SUMS")) as f:
        sums = parse_sums(f.read())
    for name in ("roots.jsonl", "games.jsonl", "other.jsonl", "COMPLETE.json", "plan.json"):
        if name not in sums:
            problems.append(f"{shard}: SHA256SUMS does not list {name}")
    for name, digest in sums.items():
        if not os.path.isfile(path(name)) or C.sha256_file(path(name)) != digest:
            problems.append(f"{shard}: {name} does not hash to its SHA256SUMS value")
    if C.sha256_file(path("plan.json")) != plan_sha:
        problems.append(f"{shard}: its plan copy is not this plan")
    with open(path("COMPLETE.json")) as f:
        complete = json.load(f)
    label = plan["label"]
    want = {"plan_sha256": plan_sha, "shard": shard,
            "checkpoint_sha256": plan["checkpoint"]["sha256"],
            "harness_commit": plan["harness_commit"], "tool_sha256": plan["tool_sha256"],
            "reward_manifest_sha256": plan["reward_manifest_sha256"],
            "settings": {key: label[key] for key in SETTING_KEYS},
            "integrity_checks": plan["integrity_checks"],
            "first_game": spec["first_game"], "games": spec["games"],
            "natural_games": spec["games"], "error_rollouts": 0,
            "search_gamma": label["gamma"], "max_rollout_steps": label["max_rollout_steps"],
            "scope": label["scope"]}
    for key, value in want.items():
        if complete.get(key) != value:
            problems.append(f"{shard}: COMPLETE.json {key} is {complete.get(key)!r}, "
                            f"the plan needs {value!r}")
    for kind in ("roots", "games", "other"):
        if C.sha256_file(path(f"{kind}.jsonl")) != complete.get(f"{kind}_sha256"):
            problems.append(f"{shard}: {kind}.jsonl is not the file COMPLETE.json recorded")
    if problems:
        return problems[:MAX_PROBLEMS], summary
    games, roots, other = (read_jsonl(path(f"{k}.jsonl")) for k in ("games", "roots", "other"))
    seed0, first, count = int(label["seed0"]), int(spec["first_game"]), int(spec["games"])
    per_class, other_cap = int(label["per_class"]), int(label["other_per_game"])
    if [g.get("game") for g in games] != list(range(first, first + count)):
        problems.append(f"{shard}: the games are not indexes {first} to {first + count - 1}, "
                        "each once")
        return problems, summary
    by_game = {}
    for g in games:
        where = f"{shard} game {g['game']}"
        by_game[g["game"]] = g
        if g.get("engine_seed") != seed0 + g["game"] or g.get("seat") != g["game"] % 2:
            problems.append(f"{where}: engine seed or seat is not the plan's")
        if g.get("natural") is not True or g.get("final_status") != STATUS_MATCH_OVER:
            problems.append(f"{where}: not a natural match end")
        integrity = g.get("integrity") or {}
        if sorted(integrity) != sorted(HARD) or any(integrity.values()):
            problems.append(f"{where}: integrity counters {integrity}")
        trail = g.get("trail") or []
        if len(trail) != g.get("steps") or C.trail_sha256(trail) != g.get("trail_sha256"):
            problems.append(f"{where}: the trail does not match its length or hash")
        counts = g.get("counts") or {}
        for cls in C.SCOPE:
            searchable = (counts.get("searchable") or {}).get(cls)
            if (g.get("kept") or {}).get(cls) != min(per_class, searchable or 0):
                problems.append(f"{where}: kept {cls} roots are not min(per_class, searchable)")
        if g.get("other_kept") != min(other_cap, counts.get("other_searchable") or 0):
            problems.append(f"{where}: the other-decision sample is not min(cap, searchable)")
    seen, per_game = set(), {}
    tally = {"roots": 0, "deviation": 0, "cap_rejected": 0, "false": 0, "confirmed": 0,
             "unjudged": 0, "dropped_pairs": 0, "kickoff_turn": 0}
    for r in roots:
        where = f"{shard} game {r.get('game')} step {r.get('step')}"
        g = by_game.get(r.get("game"))
        key = (r.get("game"), r.get("step"))
        if g is None or key in seen or r.get("class") not in C.SCOPE:
            problems.append(f"{where}: a root of no game of the shard, twice, or of no class")
            continue
        seen.add(key)
        cls = r["class"]
        per_game[(r["game"], cls)] = per_game.get((r["game"], cls), 0) + 1
        if r.get("engine_seed") != g["engine_seed"] or r.get("seat") != g["seat"] or \
                r.get("searchable") != g["counts"]["searchable"][cls] or \
                r.get("kept") != g["kept"][cls] or not 0 <= r["step"] < g["steps"] or \
                g["trail"][r["step"]][0] != g["seat"]:
            problems.append(f"{where}: does not agree with its game record")
        elif list(g["trail"][r["step"]][1:]) != list(r.get("a0") or []):
            problems.append(f"{where}: a0 is not the action the game played")
        problems += root_problems(r, label, where)
        j = r.get("judgment") or {}
        tally["roots"] += 1
        tally["deviation"] += bool(r.get("deviate"))
        tally["cap_rejected"] += bool(r.get("cap_rejected"))
        tally["kickoff_turn"] += bool(r.get("kickoff_turn"))
        tally["false"] += bool(j.get("false"))
        tally["confirmed"] += bool(j.get("confirmed"))
        tally["unjudged"] += bool(j) and not j.get("judged")
        tally["dropped_pairs"] += int(j.get("dropped_pairs") or 0)
        if len(problems) > MAX_PROBLEMS:
            break
    for g in games:
        for cls in C.SCOPE:
            if per_game.get((g["game"], cls), 0) != g["kept"][cls]:
                problems.append(f"{shard} game {g['game']}: {per_game.get((g['game'], cls), 0)} "
                                f"{cls} roots, the game kept {g['kept'][cls]}")
    other_count = {}
    for o in other:
        g = by_game.get(o.get("game"))
        if g is None or not 0 <= o.get("step", -1) < g["steps"] or \
                g["trail"][o["step"]][0] != g["seat"] or (o["game"], o["step"]) in seen:
            problems.append(f"{shard} game {o.get('game')} step {o.get('step')}: not an "
                            "out-of-scope decision of seat A in its game")
            continue
        other_count[o["game"]] = other_count.get(o["game"], 0) + 1
    for g in games:
        if other_count.get(g["game"], 0) != g["other_kept"]:
            problems.append(f"{shard} game {g['game']}: {other_count.get(g['game'], 0)} other "
                            f"decisions, the game kept {g['other_kept']}")
    if tally["cap_rejected"] > float(label["cap_rejection_ceiling"]) * max(tally["roots"], 1):
        problems.append(f"{shard}: {tally['cap_rejected']} cap rejections in {tally['roots']} "
                        f"roots, above the ceiling {label['cap_rejection_ceiling']}")
    recount = {"root_lines": tally["roots"], "other_lines": len(other),
               "deviation_roots": tally["deviation"], "cap_rejected_roots": tally["cap_rejected"],
               "false_labels": tally["false"], "confirmed_labels": tally["confirmed"],
               "unjudged_labels": tally["unjudged"],
               "dropped_judgment_pairs": tally["dropped_pairs"],
               "kickoff_turn_roots": tally["kickoff_turn"]}
    for key, value in recount.items():
        if complete.get(key) != value:
            problems.append(f"{shard}: COMPLETE.json {key} is {complete.get(key)!r}, the "
                            f"recount gives {value}")
    summary.update(recount, games=len(games), library_sha256=complete.get("library_sha256"),
                   torch=complete.get("torch"), wall_seconds=complete.get("wall_seconds"),
                   games_with_kickoff_turn_decision=complete.get(
                       "games_with_kickoff_turn_decision"))
    return problems[:MAX_PROBLEMS], summary


def accept(plan, plan_sha, shard_dirs):
    """(problems, summaries) over several shard directories ({name: directory})."""
    problems, summaries = [], []
    for shard, directory in shard_dirs.items():
        found, summary = shard_problems(directory, shard, plan, plan_sha)
        problems += found
        summaries.append(summary)
    libraries = {s.get("library_sha256") for s in summaries if "library_sha256" in s}
    if len(libraries) > 1:
        problems.append(f"the shards ran on {len(libraries)} different engine libraries")
    return problems, summaries


def accepted_line(summary):
    return (f"SHARD-ACCEPTED {summary['shard']}: {summary['games']} games, "
            f"{summary['root_lines']} roots, {summary['deviation_roots']} deviation roots "
            f"({summary['false_labels']} false, {summary['confirmed_labels']} confirmed, "
            f"{summary['unjudged_labels']} unjudged), {summary['cap_rejected_roots']} cap "
            f"rejections, {summary['kickoff_turn_roots']} kick-off turn roots, "
            f"{summary['other_lines']} other decisions; library "
            f"{str(summary['library_sha256'])[:12]}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plan", required=True)
    ap.add_argument("--expect-sha256", required=True)
    ap.add_argument("--shard-dir", action="append", default=[], metavar="NAME=DIR", required=True)
    args = ap.parse_args(argv)
    plan, plan_sha = C.load_plan(args.plan, args.expect_sha256)
    shard_dirs = dict(item.split("=", 1) for item in args.shard_dir)
    problems, summaries = accept(plan, plan_sha, shard_dirs)
    if problems:
        for p in problems:
            print(f"SHARD-REJECTED {p}")
        return 1
    for summary in summaries:
        print(accepted_line(summary))
    print(f"plan {os.path.abspath(args.plan)} sha256 {plan_sha}; this tool sha256 "
          f"{C.sha256_file(os.path.abspath(__file__))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
