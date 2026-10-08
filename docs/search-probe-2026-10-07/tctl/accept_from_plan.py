#!/usr/bin/env python3
"""Accept a merged gate run against its registered PLAN.json, before anything is scored.

  python accept_from_plan.py PLAN.json RUN_DIR --expect-sha256 <sha256 of PLAN.json>

Four checks, all required:

1. tools/gate_acceptance.py of the registered harness commit, with every
   argument taken from the plan: the exact pairs, games per pair, seed block,
   both legs of every seed exactly once, games per worker, harness commit,
   checkpoint identity of every player, sample mode at temperature 1, natural
   endings, zero integrity counters.
2. What that tool does not look at, because it predates action masks: every
   player's masks in the manifest and on its side of every game are the
   plan's, no player carries a sampling offset, no game was truncated, every
   game's final status is the engine's match-over status, both sides' decision
   counts are positive and add up to the engine steps, and the kernel is the
   plan's.
3. tools/search_acceptance.py of the registered harness commit against the
   same plan: each player's search setting in the manifest and on its side of
   every game, the pair and seat of every record, the reward manifest and the
   integrity checks of every searched game, its search statistics, the cap
   rejection ceiling, and the identity pairs. It also holds every player's
   mode and temperature in the manifest and on its side of every game.
4. The replay check, when the plan has a "reference" block: every game of
   each listed pair equals the reference run's game of the reference pair on
   the same engine seed and leg (the fields the plan lists), the reference
   record file hashes to the plan's value, and this run's compiled library is
   the reference run's.

The plan file must hash to --expect-sha256 (the hash committed to the ledger
before launch) and both acceptance tools must hash to the values the plan
records, on disk and at the registered commit. Writes
RUN_DIR/GATE_ACCEPTANCE.txt and exits 0 only when every check passes.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


STATUS_MATCH_OVER = 2       # play_harness/engine.py; checked against it in main()


def acceptance_plan(plan):
    """The dict tools/gate_acceptance.py checks against, built from PLAN.json."""
    shas = plan["checkpoints_sha256"]
    return {"seed0": plan["seed0"], "games_per_worker": plan["games_per_worker"],
            "commit": plan["harness_commit"],
            "pairs": [(a, b, int(n)) for a, b, n in plan["pairs"]],
            "checkpoints": {name: shas[spec["checkpoint"]]
                            for name, spec in plan["players"].items() if "checkpoint" in spec},
            "temperatures": {name: float(spec["temperature"])
                             for name, spec in plan["players"].items()
                             if float(spec.get("temperature", 1.0)) != 1.0}}


def replay_problems(run_dir, plan):
    """The replayed pairs against the reference run: (problems, games compared)."""
    ref = plan["reference"]
    ref_dir = os.path.expanduser(ref["run_dir"])
    ref_games = os.path.join(ref_dir, "games.jsonl")
    problems = []
    if sha256_file(ref_games) != ref["games_sha256"]:
        return [f"{ref_games} is not the registered reference record file"], 0
    with open(os.path.join(ref_dir, "manifest.json")) as f:
        ref_manifest = json.load(f)
    with open(os.path.join(run_dir, "manifest.json")) as f:
        manifest = json.load(f)
    if ref_manifest.get("library_sha256") != ref["library_sha256"]:
        problems.append("the reference manifest's library is not the registered one")
    if ref_manifest.get("harness_git_head") != ref["harness_commit"]:
        problems.append("the reference manifest's harness commit is not the registered one")
    if manifest.get("library_sha256") != ref["library_sha256"]:
        problems.append(f"library {manifest.get('library_sha256')} != the reference run's "
                        f"{ref['library_sha256']}")
    want = {tuple(e["reference_pair"]): tuple(e["pair"]) for e in ref["replay"]}
    counts = {tuple(a_b_n[:2]): int(a_b_n[2]) for a_b_n in plan["pairs"]}
    reference = {}
    with open(ref_games) as f:
        for line in f:
            if line.strip():
                g = json.loads(line)
                pair = want.get(tuple(g["pair"]))
                if pair and 0 <= g["engine_seed"] - plan["seed0"] < counts[pair] // 2:
                    reference[(pair, g["engine_seed"], g["leg"])] = g
    compared = 0
    swap = {tuple(e["reference_pair"])[0]: tuple(e["pair"])[0] for e in ref["replay"]}
    with open(os.path.join(run_dir, "games.jsonl")) as f:
        for line in f:
            if not line.strip():
                continue
            g = json.loads(line)
            pair = tuple(g["pair"])
            if pair not in want.values():
                continue
            where = f"{pair} seed {g.get('engine_seed')} {g.get('leg')}"
            r = reference.pop((pair, g.get("engine_seed"), g.get("leg")), None)
            if r is None:
                problems.append(f"{where}: the reference run has no such game")
                continue
            compared += 1
            for key in ref["fields"]:
                if key not in g or key not in r or g[key] != r[key]:
                    problems.append(f"{where}: {key} {g.get(key)!r} != the reference's {r.get(key)!r}")
            for key in ("home", "away"):
                if g.get(key) != swap.get(r.get(key), r.get(key)):
                    problems.append(f"{where}: {key} {g.get(key)!r} is not the reference's seat")
    for pair in sorted(set(want.values())):
        left = sum(1 for k in reference if k[0] == pair)
        if left:
            problems.append(f"{pair}: {left} reference games were not replayed")
    expected = sum(counts[pair] for pair in set(want.values()))
    if compared != expected:
        problems.append(f"{compared} games compared with the reference, {expected} registered")
    return problems[:40], compared


def mask_problems(run_dir, plan):
    """Masks, sampling offsets and truncation: the checks the stock tool lacks."""
    problems = []
    want = {name: sorted(spec.get("masks") or []) for name, spec in plan["players"].items()}
    with open(os.path.join(run_dir, "manifest.json")) as f:
        manifest = json.load(f)
    players = manifest.get("players") or {}
    if sorted(players) != sorted(want):
        problems.append(f"manifest players {sorted(players)} != registered {sorted(want)}")
    if manifest.get("kernel") != plan["kernel"]:
        problems.append(f"kernel {manifest.get('kernel')!r} != registered {plan['kernel']!r}")
    for name, masks in want.items():
        spec = players.get(name) or {}
        if sorted(spec.get("masks") or []) != masks:
            problems.append(f"player {name}: manifest masks {spec.get('masks')} != registered {masks}")
        if spec.get("seed_offset"):
            problems.append(f"player {name}: sampling offset {spec.get('seed_offset')}, none registered")
    counts = {"games": 0, "masked_sides": 0, "truncated": 0, "mask_fallbacks": 0}
    with open(os.path.join(run_dir, "games.jsonl")) as f:
        for line in f:
            if not line.strip():
                continue
            g = json.loads(line)
            counts["games"] += 1
            where = f"{g.get('pair')} seed {g.get('engine_seed')} {g.get('leg')}"
            if g.get("truncated") is not False:
                counts["truncated"] += 1
                problems.append(f"{where}: truncated is {g.get('truncated')!r}")
            status = g.get("final_status")
            if isinstance(status, bool) or status != STATUS_MATCH_OVER:
                problems.append(f"{where}: final_status is {status!r}, not the engine's "
                                f"match-over status {STATUS_MATCH_OVER}")
            decisions, steps = g.get("decisions"), g.get("c_steps")
            if not (isinstance(decisions, list) and len(decisions) == 2
                    and all(isinstance(d, int) and not isinstance(d, bool) and d > 0
                            for d in decisions)
                    and sum(decisions) == g.get("engine_decisions") == steps):
                problems.append(f"{where}: decisions {decisions!r}, engine_decisions "
                                f"{g.get('engine_decisions')!r}, c_steps {steps!r} do not agree")
            if any(g.get("seed_offsets") or [0, 0]):
                problems.append(f"{where}: sampling offsets {g.get('seed_offsets')}")
            for side, name in ((0, g.get("home")), (1, g.get("away"))):
                got = sorted((g.get("masks") or [None, None])[side] or [])
                if name not in want:
                    problems.append(f"{where}: unregistered player {name!r}")
                elif got != want[name]:
                    problems.append(f"{where}: {name} played under {got}, registered {want[name]}")
                stats = (g.get("mask_stats") or [None, None])[side]
                if got:
                    counts["masked_sides"] += 1
                    if not stats or sorted(stats) != got:
                        problems.append(f"{where}: {name} has no mask statistics for {got}")
                    else:
                        counts["mask_fallbacks"] += sum(v["fallback"] for v in stats.values())
                elif stats:
                    problems.append(f"{where}: unmasked {name} carries mask statistics")
    return problems[:40], counts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("plan")
    ap.add_argument("run_dir")
    ap.add_argument("--expect-sha256", required=True,
                    help="the PLAN.json hash committed before launch")
    args = ap.parse_args(argv)
    plan_sha = sha256_file(args.plan)
    if plan_sha != args.expect_sha256.lower():
        print(f"GATE-REJECTED plan file hashes to {plan_sha}, not the committed {args.expect_sha256}")
        return 1
    with open(args.plan) as f:
        plan = json.load(f)
    root = os.path.expanduser(plan["harness_worktree"])
    tool = os.path.join(root, "tools", "gate_acceptance.py")
    search_tool = os.path.join(root, "tools", "search_acceptance.py")
    problems = []
    for path, key in ((tool, "tool_sha256"), (search_tool, "search_tool_sha256")):
        name = os.path.basename(path)
        if sha256_file(path) != plan["acceptance"][key]:
            problems.append(f"{path} is not the registered acceptance tool")
        committed = subprocess.run(
            ["git", "-C", root, "show", plan["harness_commit"] + ":tools/" + name],
            capture_output=True).stdout
        if hashlib.sha256(committed).hexdigest() != plan["acceptance"][key]:
            problems.append(f"tools/{name} at the registered harness commit is not the "
                            "registered acceptance tool")
    sys.path.insert(0, os.path.join(root, "tools"))
    import gate_acceptance
    import search_acceptance
    engine_source = subprocess.run(
        ["git", "-C", root, "show", plan["harness_commit"] + ":play_harness/engine.py"],
        capture_output=True, text=True).stdout
    if f"STATUS_MATCH_OVER = {STATUS_MATCH_OVER}\n" not in engine_source:
        problems.append("the engine's match-over status at the registered commit is not "
                        f"{STATUS_MATCH_OVER}")
    acc = acceptance_plan(plan)
    total = sum(n for _a, _b, n in acc["pairs"])
    if total != plan["total_games"] or len(acc["pairs"]) != len(plan["pairs"]):
        problems.append(f"plan lists {total} games, total_games says {plan['total_games']}")
    problems += gate_acceptance.accept(args.run_dir, acc)
    extra, counts = mask_problems(args.run_dir, plan)
    problems += extra
    search_line = None
    try:
        search_found, search_counts = search_acceptance.accept(args.run_dir, plan, require_schedule=True)
        if not search_found:
            search_line = search_acceptance.accepted_line(search_counts)
    except ValueError as exc:
        search_found = [str(exc)]
    problems += [f"search: {p}" for p in search_found]
    replay_line = None
    if plan.get("reference"):
        replay_found, compared = replay_problems(args.run_dir, plan)
        problems += [f"replay: {p}" for p in replay_found]
        replay_line = (f"REPLAY-ACCEPTED {compared} games equal to the reference run's on "
                       f"{', '.join(plan['reference']['fields'])}; library "
                       f"{plan['reference']['library_sha256'][:8]} as the reference's")
    integrity = {}
    unnatural = 0
    with open(os.path.join(args.run_dir, "games.jsonl")) as f:
        for line in f:
            if line.strip():
                g = json.loads(line)
                unnatural += g.get("natural") is not True
                for k, v in (g.get("integrity") or {}).items():
                    integrity[k] = integrity.get(k, 0) + v
    if problems:
        lines = [f"GATE-REJECTED {p}" for p in problems]
    else:
        lines = [
            f"GATE-ACCEPTED {total} games, {len(acc['pairs'])} pairs, seed0 {acc['seed0']}, "
            f"games_per_worker {acc['games_per_worker']}, commit {acc['commit'][:7]}",
            f"MASKS-ACCEPTED {counts['masked_sides']} masked sides in {counts['games']} games as "
            f"registered, no sampling offsets, {counts['truncated']} truncated, "
            f"{counts['mask_fallbacks']} mask fallbacks",
            search_line,
        ] + ([replay_line] if replay_line else [])
    lines += [f"integrity totals {json.dumps(integrity, sort_keys=True)}; unnatural endings {unnatural}",
              f"plan {os.path.abspath(args.plan)} sha256 {plan_sha}",
              f"acceptance tool sha256 {sha256_file(tool)}; search acceptance tool sha256 "
              f"{sha256_file(search_tool)}; this script sha256 {sha256_file(__file__)}",
              f"games.jsonl sha256 {sha256_file(os.path.join(args.run_dir, 'games.jsonl'))}"]
    with open(os.path.join(args.run_dir, "GATE_ACCEPTANCE.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
