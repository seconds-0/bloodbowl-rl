#!/usr/bin/env python3
"""Check a finished tournament run against a registered gate plan.

The shard merge only checks shards against each other, so a launch that omits a
whole pair still merges cleanly. This check holds the run to the plan itself:
the exact pairs, games per pair, seed block, both legs of every seed exactly
once, games per worker, harness commit, checkpoint identities, sample mode at
unit temperature, natural endings and zero integrity counters.

A plan may register other temperatures: plan["temperatures"] maps a player name
to its temperature (--temperature NAME=T), every other checkpoint player stays
at 1.0, and then each side of every game is held to its own player's value.

Exit 0 and print GATE-ACCEPTED only when every check passes.
"""
import argparse
import collections
import json
import os
import sys

LEGS = ("A_home", "B_home")


def parse_pair(text):
    parts = text.split(",")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(f"--pair wants A,B,N, got {text!r}")
    return parts[0], parts[1], int(parts[2])


def parse_temperature(text):
    name, sep, value = text.partition("=")
    try:
        t = float(value)
    except ValueError:
        t = float("nan")
    if not sep or not name or not (0.0 < t < float("inf")):
        raise argparse.ArgumentTypeError(f"--temperature wants NAME=T with T above 0, got {text!r}")
    return name, t


def registered_temperature(plan, name):
    return float((plan.get("temperatures") or {}).get(name, 1.0))


def parse_checkpoint(text):
    name, sep, sha = text.partition("=")
    if not sep or len(sha) != 64:
        raise argparse.ArgumentTypeError(f"--checkpoint wants NAME=SHA256, got {text!r}")
    return name, sha.lower()


def check_manifest(manifest, plan):
    problems = []
    if manifest.get("seed0") != plan["seed0"]:
        problems.append(f"seed0 {manifest.get('seed0')} != registered {plan['seed0']}")
    gpw = manifest.get("games_per_worker")
    gpw = 1 if gpw is None else gpw
    if gpw != plan["games_per_worker"]:
        problems.append(f"games_per_worker {gpw} != registered {plan['games_per_worker']}")
    if manifest.get("harness_git_head") != plan["commit"]:
        problems.append(f"harness commit {manifest.get('harness_git_head')} != registered {plan['commit']}")
    if manifest.get("mode") != "sample":
        problems.append(f"mode {manifest.get('mode')!r} is not 'sample'")
    got_pairs = sorted((a, b, n) for a, b, n in manifest.get("pairs") or [])
    want_pairs = sorted(plan["pairs"])
    if got_pairs != want_pairs:
        missing = [p for p in want_pairs if p not in got_pairs]
        extra = [p for p in got_pairs if p not in want_pairs]
        problems.append(f"pairs differ from the registered plan: missing {missing}, unexpected {extra}")
    players = manifest.get("players") or {}
    for name, spec in players.items():
        if "bot" in spec:
            if name in (plan.get("temperatures") or {}):
                problems.append(f"a temperature is registered for the scripted bot {name}")
            continue
        want = registered_temperature(plan, name)
        if spec.get("mode") != "sample" or spec.get("temperature") != want:
            problems.append(f"player {name} is not sample mode at temperature {want}: {spec}")
    unknown = sorted(set(plan.get("temperatures") or {}) - set(players))
    if unknown:
        problems.append(f"temperatures registered for players the manifest does not have: {unknown}")
    checkpoints = manifest.get("checkpoints") or {}
    for name, sha in plan["checkpoints"].items():
        got = (checkpoints.get(name) or {}).get("sha256")
        if got != sha:
            problems.append(f"checkpoint {name} sha256 {got} != registered {sha}")
    unexpected = sorted(set(checkpoints) - set(plan["checkpoints"]))
    if unexpected:
        problems.append(f"unregistered checkpoints in the manifest: {unexpected}")
    return problems


def side_temperature_problems(game, pair, plan):
    """With registered temperatures, each side's value is its own player's: a registered checkpoint
    samples at its temperature, anyone else is a scripted bot with none."""
    where = f"{pair} seed {game.get('engine_seed')} {game.get('leg')}"
    seats = (game.get("home"), game.get("away"))
    if game.get("leg") not in LEGS or set(seats) != set(pair) or \
            seats[0] != pair[0 if game.get("leg") == "A_home" else 1]:
        return [f"{where}: home {seats[0]!r} and away {seats[1]!r} are not the pair's seats for this leg"]
    modes, temperatures = game.get("modes"), game.get("temperatures")
    if not (isinstance(modes, list) and isinstance(temperatures, list)
            and len(modes) == len(temperatures) == 2):
        return [f"{where}: modes {modes!r} and temperatures {temperatures!r} are not one value a side"]
    problems = []
    for name, mode, temperature in zip(seats, modes, temperatures):
        checkpoint = name in plan["checkpoints"]
        if (mode == "scripted") == checkpoint:
            problems.append(f"{where}: {name} played in mode {mode!r}, "
                            + ("a registered checkpoint samples" if checkpoint else "a bot is scripted"))
        want = registered_temperature(plan, name) if checkpoint else None
        if isinstance(temperature, bool) or temperature != want:
            problems.append(f"{where}: {name} played at temperature {temperature!r}, registered {want!r}")
    return problems


def check_games(games, plan):
    problems = []
    want = {(a, b): n for a, b, n in plan["pairs"]}
    seen = collections.defaultdict(collections.Counter)
    for game in games:
        pair = tuple(game.get("pair") or ())
        if pair not in want:
            problems.append(f"game for an unregistered pair {pair}")
            continue
        seen[pair][(game.get("engine_seed"), game.get("leg"))] += 1
        if game.get("natural") is not True:
            problems.append(f"{pair} seed {game.get('engine_seed')} {game.get('leg')}: not a natural ending")
        bad = {k: v for k, v in (game.get("integrity") or {"missing": 1}).items() if v}
        if bad:
            problems.append(f"{pair} seed {game.get('engine_seed')} {game.get('leg')}: integrity {bad}")
        for mode in game.get("modes") or [game.get("mode")]:
            if mode not in ("sample", "scripted"):
                problems.append(f"{pair} seed {game.get('engine_seed')}: mode {mode!r}")
        if plan.get("temperatures"):
            problems += side_temperature_problems(game, pair, plan)
        else:
            for temperature in game.get("temperatures") or []:
                if temperature not in (None, 1.0):
                    problems.append(f"{pair} seed {game.get('engine_seed')}: temperature {temperature}")
    for pair, n in sorted(want.items()):
        if n % len(LEGS):
            problems.append(f"{pair}: {n} games is not a whole number of seeds")
            continue
        expected = {(plan["seed0"] + i, leg) for i in range(n // len(LEGS)) for leg in LEGS}
        got = seen.get(pair, collections.Counter())
        missing = expected - set(got)
        extra = set(got) - expected
        dupes = [key for key, count in got.items() if count > 1]
        if missing:
            problems.append(f"{pair}: {len(missing)} scheduled games missing, e.g. {sorted(missing)[:3]}")
        if extra:
            problems.append(f"{pair}: {len(extra)} games outside the seed block, e.g. {sorted(extra, key=str)[:3]}")
        if dupes:
            problems.append(f"{pair}: {len(dupes)} games recorded more than once, e.g. {sorted(dupes, key=str)[:3]}")
    total = sum(want.values())
    if len(games) != total:
        problems.append(f"{len(games)} games recorded != {total} registered")
    return problems[:40]


def accept(run_dir, plan):
    with open(os.path.join(run_dir, "manifest.json")) as handle:
        manifest = json.load(handle)
    with open(os.path.join(run_dir, "games.jsonl")) as handle:
        games = [json.loads(line) for line in handle if line.strip()]
    complete_path = os.path.join(run_dir, "COMPLETE.json")
    problems = []
    if not os.path.exists(complete_path):
        problems.append("COMPLETE.json is missing")
    else:
        with open(complete_path) as handle:
            if json.load(handle).get("complete") is not True:
                problems.append("COMPLETE.json does not say complete")
    return problems + check_manifest(manifest, plan) + check_games(games, plan)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--seed0", type=int, required=True)
    parser.add_argument("--games-per-worker", type=int, required=True)
    parser.add_argument("--commit", required=True, help="full harness commit the gate was registered at")
    parser.add_argument("--pair", type=parse_pair, action="append", required=True, metavar="A,B,N")
    parser.add_argument("--checkpoint", type=parse_checkpoint, action="append", default=[], metavar="NAME=SHA256")
    parser.add_argument("--temperature", type=parse_temperature, action="append", default=[], metavar="NAME=T",
                        help="repeatable; a player registered at a temperature other than 1.0")
    args = parser.parse_args(argv)
    plan = {"seed0": args.seed0, "games_per_worker": args.games_per_worker, "commit": args.commit,
            "pairs": list(args.pair), "checkpoints": dict(args.checkpoint),
            "temperatures": dict(args.temperature)}
    problems = accept(args.run_dir, plan)
    if problems:
        for problem in problems:
            print(f"GATE-REJECTED {problem}")
        return 1
    print(f"GATE-ACCEPTED {sum(n for _, _, n in plan['pairs'])} games, {len(plan['pairs'])} pairs, "
          f"seed0 {plan['seed0']}, games_per_worker {plan['games_per_worker']}, commit {plan['commit'][:7]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
