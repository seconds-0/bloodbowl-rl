#!/usr/bin/env python3
"""Acceptance of END_TURN probe records: one set of rules for the launcher (after
it fetched a shard) and for the analysis (before it computes anything).

A checkpoint's records are accepted when COMPLETE.json exists and names the
plan, the checkpoint, the harness commit, the tool files, the reward manifest,
the settings and the integrity checks of the plan; when no game is invalid and
no rollout failed; when the probe's own checks are inside their limits (every
class of a game with an eligible root had its identity check, at least one in
the shard); when
roots.jsonl and games.jsonl hash to what COMPLETE.json recorded; and when the
games are exactly the plan's engine seeds, each once, each a natural game with
zero hard counters, and the roots belong to those games.

A shard is accepted when its SHA256SUMS covers and matches every file, its
plan.json is the plan, its machine built the pinned commit, every checkpoint
of the shard is accepted and all of them ran on one engine library.

  endturn_accept.py --plan PLAN.json --expect-sha256 H --shard-dir NAME=DIR ...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

RESULT_FILES = ("roots.jsonl", "games.jsonl", "COMPLETE.json")
HARD_COUNTERS = ("illegal", "projection_collision", "error_episodes",
                 "rejected_submissions", "precheck_collisions")
LIMITS = {"component_sum_max_abs": 1e-4, "step_residual_max_abs": 1e-5, "depth1_max_abs": 1e-4}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_plan(path, expect):
    """(plan, sha256). Raises ValueError unless the file hashes to `expect`."""
    with open(path, "rb") as f:
        raw = f.read()
    got = hashlib.sha256(raw).hexdigest()
    if got != expect:
        raise ValueError(f"{path} hashes to {got}, not to the expected {expect}")
    return json.loads(raw), got


def parse_sums(text):
    out = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        m = re.match(r"^([0-9a-f]{64}) [ *](.+)$", line)
        if not m:
            raise ValueError(f"malformed SHA256SUMS line: {line!r}")
        out[m.group(2)] = m.group(1)
    return out


def read_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f]


def checkpoint_problems(directory, name, plan=None, plan_sha=None):
    """(problems, COMPLETE.json or None) for one checkpoint's record directory.
    Without a plan (a local smoke) the records are held to their own
    COMPLETE.json; with one, to the plan."""
    problems = []
    if os.path.exists(os.path.join(directory, "FAILED.json")):
        problems.append("FAILED.json is present: the run stopped on a failure")
    path = os.path.join(directory, "COMPLETE.json")
    if not os.path.isfile(path):
        return problems + ["no COMPLETE.json: the run is unfinished or failed"], None
    with open(path) as f:
        c = json.load(f)
    want = {"checkpoint": name, "invalid_games": 0, "error_rollouts": 0,
            "step_limit_rollouts": 0}
    if plan is not None:
        want.update({"plan_sha256": plan_sha, "registered": True,
                     "checkpoint_sha256": plan["checkpoints"][name]["sha256"],
                     "harness_commit": plan["harness_commit"],
                     "tool_sha256": plan["tool_sha256"],
                     "reward_manifest_sha256": plan["reward_manifest_sha256"],
                     "settings": plan["settings"],
                     "integrity_checks": plan["integrity_checks"]})
    for key, value in want.items():
        if c.get(key) != value:
            problems.append(f"COMPLETE.json {key} is {c.get(key)!r}, expected {value!r}")
    settings = c.get("settings") or {}
    games_n, seed0 = settings.get("games"), settings.get("seed0")
    if c.get("games") != games_n or c.get("natural_games") != games_n:
        problems.append(f"COMPLETE.json has {c.get('games')} games, {c.get('natural_games')} "
                        f"natural, of {games_n}")
    checks = c.get("checks") or {}
    # Every class of every game that had an eligible root (a turn arm with no capped
    # rollout) must have had its identity check, and the shard must have at least one.
    roots, eligible = checks.get("identity_roots"), checks.get("identity_eligible")
    if checks.get("identity_max_abs") != 0.0 or not isinstance(roots, int) or roots < 1 \
            or roots != eligible:
        problems.append(f"identity check: {roots} roots checked of {eligible} eligible, "
                        f"difference {checks.get('identity_max_abs')}")
    for key, limit in LIMITS.items():
        if not (isinstance(checks.get(key), (int, float)) and checks[key] <= limit):
            problems.append(f"check {key} is {checks.get(key)!r}, limit {limit}")
    if checks.get("forced_max", 99) > 1:
        problems.append("the forced arm ended a turn more than once in a rollout")
    for fname, key in (("roots.jsonl", "roots_sha256"), ("games.jsonl", "games_sha256")):
        fpath = os.path.join(directory, fname)
        if not os.path.isfile(fpath):
            problems.append(f"{fname} is missing")
        elif sha256_file(fpath) != c.get(key):
            problems.append(f"{fname} is not the file COMPLETE.json hashed")
    if problems or not isinstance(games_n, int) or not isinstance(seed0, int):
        return problems, c
    games = read_jsonl(os.path.join(directory, "games.jsonl"))
    if [g.get("engine_seed") for g in games] != [seed0 + i for i in range(games_n)] or \
            [g.get("game") for g in games] != list(range(games_n)):
        problems.append(f"games.jsonl does not hold exactly engine seeds {seed0} to "
                        f"{seed0 + games_n - 1}, each once and in order")
        return problems, c
    for g in games:
        integrity = g.get("integrity")
        if g.get("checkpoint") != name or g.get("natural") is not True or g.get("invalid") or \
                g.get("seat") != g["game"] % 2 or not isinstance(integrity, dict) or \
                set(integrity) != set(HARD_COUNTERS) or any(integrity.values()):
            problems.append(f"game {g.get('game')}: not a natural, valid game of {name} with "
                            f"zero hard counters")
    lines = {g["game"]: 0 for g in games}
    for r in read_jsonl(os.path.join(directory, "roots.jsonl")):
        game = r.get("game")
        if game not in lines or r.get("engine_seed") != seed0 + game or r.get("checkpoint") != name:
            problems.append(f"a root of game {game!r} does not belong to this run")
            break
        lines[game] += 1
    wrong = [g["game"] for g in games if lines[g["game"]] != g.get("root_lines")]
    if wrong:
        problems.append(f"roots.jsonl does not hold the roots games.jsonl counted "
                        f"(first game {wrong[0]})")
    if sum(lines.values()) != c.get("root_lines"):
        problems.append("roots.jsonl's line count is not COMPLETE.json's")
    return problems, c


def shard_problems(directory, shard, plan, plan_sha):
    """(problems, {checkpoint: COMPLETE.json}) for a fetched shard directory."""
    problems, completes = [], {}
    names = {s["name"]: s["checkpoints"] for s in plan["shards"]}.get(shard)
    if names is None:
        return [f"the plan has no shard {shard!r}"], completes
    sums_path = os.path.join(directory, "SHA256SUMS")
    if not os.path.isfile(sums_path):
        return ["no SHA256SUMS: not a fetched shard"], completes
    with open(sums_path) as f:
        sums = parse_sums(f.read())
    required = ["machine.json", "plan.json"] + [f"{ck}/{name}" for ck in names
                                                for name in RESULT_FILES]
    problems += [f"{name}: not listed in SHA256SUMS" for name in required if name not in sums]
    for name, want in sums.items():
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            problems.append(f"{name}: listed in SHA256SUMS and absent")
        elif sha256_file(path) != want:
            problems.append(f"{name}: does not hash to its SHA256SUMS entry")
    if problems:
        return problems, completes
    if sha256_file(os.path.join(directory, "plan.json")) != plan_sha:
        problems.append("the shard's plan.json is not the plan")
    with open(os.path.join(directory, "machine.json")) as f:
        if json.load(f).get("source_commit") != plan["harness_commit"]:
            problems.append("the shard's machine built another commit")
    for ck in names:
        found, complete = checkpoint_problems(os.path.join(directory, ck), ck, plan, plan_sha)
        problems += [f"{ck}: {p}" for p in found]
        if complete is not None:
            completes[ck] = complete
    libraries = {c.get("library_sha256") for c in completes.values()}
    if len(libraries) > 1:
        problems.append("the shard's checkpoints ran on different engine libraries")
    return problems, completes


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plan", required=True)
    ap.add_argument("--expect-sha256", required=True)
    ap.add_argument("--shard-dir", action="append", required=True, metavar="NAME=DIR")
    args = ap.parse_args(argv)
    try:
        plan, plan_sha = load_plan(args.plan, args.expect_sha256)
    except ValueError as exc:
        raise SystemExit(f"REFUSED: {exc}")
    bad = False
    for item in args.shard_dir:
        shard, _, directory = item.partition("=")
        problems, _ = shard_problems(directory, shard, plan, plan_sha)
        print(f"{shard}: " + ("ACCEPTED" if not problems else "NOT ACCEPTED\n  " + "\n  ".join(problems)))
        bad = bad or bool(problems)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
