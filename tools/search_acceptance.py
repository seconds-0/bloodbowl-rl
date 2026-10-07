#!/usr/bin/env python3
"""Check a finished tournament run's search settings against a registered plan.

tools/gate_acceptance.py holds a run to its pairs, seeds, commit and checkpoint
hashes. It predates action masks, sampling offsets and the search seat and looks
at none of them, and it reads a game's pair without asking who sat in it. This
check holds every game to the seats its pair and leg give it, holds every
player's masks, sampling offset and search setting to the plan, in the manifest
and on that player's side of every game, and reads what each searched game
recorded about its search. Both checks are needed; neither replaces the other.

  tools/search_acceptance.py PLAN.json RUN_DIR --expect-sha256 <sha256 of PLAN.json>

What it reads from the plan (other keys are ignored):

  "players": {NAME: {"masks": [...],            # [] or absent: unmasked
                     "sampling_offset": K,      # 0 or absent: none
                     "search": {...}}},         # absent: the player does not search
  "pairs": [[A, B, GAMES], ...],                # the schedule, as the gate plan lists it
  "seed0": N,                                   # game i of a pair runs on seed N + i
  "search": {"reward_manifest_sha256": "...",   # required when a player searches
             "integrity_checks": [...],
             "cap_rejection_ceiling": 0.01,
             "identity": [{"search": [A, B], "plain": [C, D]}]}   # optional

A player's "search" is the complete setting as the harness writes it into the
manifest: scope, k, n, delta, max_rollout_steps, horizon, gamma, reward_manifest,
reward_manifest_sha256, opponent_model, candidates, se_floor. Print the default
with:  python -c "import json; from play_harness import search as S;
print(json.dumps(S.search_setting(), indent=1))"

"pairs" and "seed0" are required on the command line when a player searches.
accept() takes a plan without them: seats and seeds are then still held (seeds
to the manifest's seed0), but not which pairs played or how many games.

Checked:
  the plan   pairs are two different registered players with a positive even
             number of games, no pair twice; seed0 is an integer; an identity
             entry's two pairs are in pairs and the plain pair has as many games.
  manifest   the registered players and no others; each one's masks, sampling
             offset and search setting; an integer seed0, equal to the plan's;
             pairs equal to the plan's. With a searching player: games_per_worker
             1, the reward manifest hash and the list of integrity checks.
             Without one: no search entry.
  each game  the record is an object of the tournament's schema; pair is two
             different players and leg is A_home or B_home; home and away are
             the pair seated for that leg, both registered, and the pair is in
             the plan's pairs; game_index is an integer >= 0 inside the pair's
             registered games; engine_seed is seed0 + game_index; episode is 0;
             no (pair, game_index, leg) is recorded twice.
             Then, with the players the pair and leg name: masks, sampling
             offsets and search setting of each side equal to the plan's; a
             natural untruncated ending; exactly the tournament's five hard
             counters, each an integer zero; mask statistics for exactly the
             masks of a masked side and none for an unmasked side, each with
             non-negative integer held, applied and fallback and a mass, and no
             fallback; one real forward per seat per engine step; a game without
             a searching player carries no search fields. For a game with one:
             the reward manifest hash, the list of integrity checks, one
             opponent-view forward per engine step, the searching seat in sample
             mode at temperature 1, and the search statistics: in scope >=
             searched >=
             deviations in every class of the setting's scope, one predicted
             gain and one deviation type per deviation, no error rollout,
             rollouts between 2n and kn per searched decision, every predicted
             gain a finite number at least delta, and no deviation at all when
             delta is inf.
  each pair  every game the plan registers for it is there; the share of a
             searching player's searched decisions that had a cap rejection is
             at most the plan's ceiling.
  identity   for each listed pair of pairs: the `search` pair (whose searching
             player has delta inf) has a game, and every one of its games has
             exactly one game of the `plain` pair on the same seed and leg and
             equals it on action trail, final digest, log-probability sums,
             score, steps, rosters and sampling seeds. Each of those fields must
             be there in both records and be what a game writes (a 64-digit and
             a 16-digit hex digest, two finite numbers, two integers, a positive
             integer). The searching seat's statistics pass the checks above,
             with at least one searched decision, so at least 2n rollouts for
             each, and no deviation. When the plan lists pairs, the number of
             games that match is the number registered for the `search` pair.

Exit 0 and print SEARCH-ACCEPTED only when every check passes. Stdlib only.
"""
import argparse
import collections
import hashlib
import json
import math
import os
import sys

SETTING_KEYS = ("scope", "k", "n", "delta", "max_rollout_steps", "horizon", "gamma",
                "reward_manifest", "reward_manifest_sha256", "opponent_model", "candidates",
                "se_floor")
STAT_KEYS = ("in_scope", "searched", "deviations", "deviation_types", "predicted_gains",
             "rollouts", "rollout_steps", "rollout_forward_rows", "cap_rejected_rollouts",
             "cap_rejected_decisions", "cutoff_rollouts", "error_rollouts", "shadow_forwards")
SEARCH_FIELDS = ("search", "search_stats", "search_seconds", "reward_manifest_sha256",
                 "integrity_checks", "final_state_sha256", "sampling_state_sha256")
# As play_harness/tournament.py writes them. This tool imports nothing from the
# harness, so the names are repeated here and a test holds them equal.
SCHEMA = "bbplay-tournament-game-v1"
LEGS = ("A_home", "B_home")
HARD_COUNTERS = ("illegal", "projection_collision", "error_episodes",
                 "rejected_submissions", "precheck_collisions")
MASK_STAT_KEYS = ("held", "applied", "fallback", "mass")
SCRIPTED_MODE = "scripted"                # a bot seat's mode; its temperature is None
SEED_OFFSET_STRIDE = 1_000_000_007
MAX_PROBLEMS = 40


def _int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is(value, want):
    """Equal, and not a boolean standing in for a number."""
    return value == want and isinstance(value, bool) == isinstance(want, bool)


def _real(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and \
        math.isfinite(value)


def _hex(value, length):
    return isinstance(value, str) and len(value) == length and \
        set(value) <= set("0123456789abcdef")


def _two(value, test=lambda item: True):
    """A list of exactly two items that each pass `test`."""
    return isinstance(value, list) and len(value) == 2 and all(test(item) for item in value)


# What an identity game and its plain game are compared on, and what each field
# has to be before it counts as evidence: a field absent from both records, or
# empty in both, is equal and proves nothing.
IDENTITY_SHAPES = {
    "action_trail_sha256": lambda v: _hex(v, 64),
    "final_digest": lambda v: _hex(v, 16),
    "logprob_sum": lambda v: _two(v, _real),
    "score": lambda v: _two(v, _int),
    "c_steps": lambda v: _int(v) and v > 0,
    "team_ids": lambda v: _two(v, _int),
    "sampling_seeds": lambda v: _two(v, _int),
}
IDENTITY_FIELDS = tuple(IDENTITY_SHAPES)


def sampling_seed(engine_seed, side, offset):
    """The sampling seed the tournament gives a side of a game: its
    sampling_seed() at episode 0, shifted by the player's sampling offset the
    way Match seats it."""
    seed = (engine_seed * 1_000_003 + 17 + side) % (1 << 62)
    return (seed + offset * SEED_OFFSET_STRIDE) % (1 << 62) if offset else seed


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scheduled(plan, names):
    """The plan's schedule: ({(A, B): games} or None, seed0 or None). Raises
    ValueError on a list of pairs or a seed0 that cannot be read."""
    seed0 = None
    if "seed0" in plan:
        seed0 = plan["seed0"]
        if not _int(seed0):
            raise ValueError(f"plan: seed0 must be an integer, got {seed0!r}")
    if "pairs" not in plan:
        return None, seed0
    pairs = {}
    if not isinstance(plan["pairs"], list) or not all(
            isinstance(item, list) and len(item) == 3 for item in plan["pairs"]):
        raise ValueError("plan: pairs is a list of [A, B, games]")
    for item in plan["pairs"]:
        a, b, n = item
        if not isinstance(a, str) or not isinstance(b, str) or a == b or a not in names \
                or b not in names:
            raise ValueError(f"plan: pair {item} needs two different registered players")
        if not _int(n) or n <= 0 or n % len(LEGS):
            raise ValueError(f"plan: pair {item} needs a positive even number of games")
        if (a, b) in pairs or (b, a) in pairs:
            raise ValueError(f"plan: pair {item} is listed twice")
        pairs[(a, b)] = n
    return pairs, seed0


def registered(plan, require_schedule=False):
    """Raise ValueError unless the plan's player settings are complete. Returns
    {name: {"masks", "offset", "search", "bot", "mode", "temperature"}} and the
    plan's search block.

    require_schedule: also refuse a plan in which a player searches and that
    does not list its pairs and seed0. The command line asks for it."""
    if not isinstance(plan, dict):
        raise ValueError("plan: not an object")
    players = plan.get("players")
    if not isinstance(players, dict) or not players:
        raise ValueError("plan: no players")
    out = {}
    for name, spec in players.items():
        if not isinstance(spec, dict):
            raise ValueError(f"plan: player {name} is not an object")
        if spec.get("bot") is not None:
            if not isinstance(spec["bot"], str) or any(
                    spec.get(key) for key in ("masks", "sampling_offset", "search", "mode",
                                              "temperature")):
                raise ValueError(f"plan: bot {name} takes a kind and no mask, sampling "
                                 "offset, search, mode or temperature")
            out[name] = {"masks": [], "offset": 0, "search": None, "bot": spec["bot"],
                         "mode": SCRIPTED_MODE, "temperature": None}
            continue
        search = spec.get("search")
        if search is not None and (not isinstance(search, dict)
                                   or set(search) != set(SETTING_KEYS)):
            raise ValueError(f"plan: player {name}'s search setting needs exactly "
                             f"{list(SETTING_KEYS)}")
        masks = spec.get("masks") or []
        if not isinstance(masks, list) or not all(isinstance(m, str) for m in masks) or \
                len(set(masks)) != len(masks):
            raise ValueError(f"plan: player {name}'s masks must be a list of names")
        offset = spec.get("sampling_offset") or 0
        if not _int(offset) or offset < 0:
            raise ValueError(f"plan: player {name}'s sampling_offset must be an integer >= 0")
        mode, temperature = spec.get("mode", "sample"), spec.get("temperature", 1.0)
        if mode not in ("sample", "argmax"):
            raise ValueError(f"plan: player {name}'s mode is sample or argmax")
        if not _real(temperature) or temperature <= 0:
            raise ValueError(f"plan: player {name}'s temperature must be a number above 0")
        if search and (mode != "sample" or temperature != 1.0):
            raise ValueError(f"plan: player {name} searches outside sample mode at "
                             "temperature 1")
        out[name] = {"masks": sorted(masks), "offset": offset, "search": search, "bot": None,
                     "mode": mode, "temperature": temperature}
    block = plan.get("search") or {}
    if any(p["search"] for p in out.values()):
        for key in ("reward_manifest_sha256", "integrity_checks", "cap_rejection_ceiling"):
            if key not in block:
                raise ValueError(f"plan: search.{key} is required when a player searches")
        if not isinstance(block["integrity_checks"], list) or not block["integrity_checks"]:
            raise ValueError("plan: search.integrity_checks must list the checks")
        if not 0.0 <= float(block["cap_rejection_ceiling"]) <= 1.0:
            raise ValueError("plan: search.cap_rejection_ceiling must be in [0, 1]")
        for name, p in out.items():
            if p["search"] and p["search"]["reward_manifest_sha256"] != \
                    block["reward_manifest_sha256"]:
                raise ValueError(f"plan: player {name}'s reward manifest is not "
                                 "search.reward_manifest_sha256")
            if p["search"] and not p["masks"]:
                raise ValueError(f"plan: player {name} searches without a mask")
    for item in block.get("identity") or []:
        if set(item) != {"search", "plain"} or len(item["search"]) != 2 or \
                len(item["plain"]) != 2:
            raise ValueError("plan: an identity entry is {search: [A, B], plain: [C, D]}")
        searching = [n for n in item["search"] if (out.get(n) or {}).get("search")]
        if len(searching) != 1 or out[searching[0]]["search"]["delta"] != "inf":
            raise ValueError(f"plan: identity pair {item['search']} needs exactly one "
                             "searching player, with delta inf")
        if any((out.get(n) or {"search": 1})["search"] for n in item["plain"]):
            raise ValueError(f"plan: identity's plain pair {item['plain']} must not search")
    pairs, seed0 = scheduled(plan, out)
    if require_schedule and any(p["search"] for p in out.values()) and \
            (pairs is None or seed0 is None):
        raise ValueError("plan: pairs and seed0 are required when a player searches")
    if pairs is not None:
        for item in block.get("identity") or []:
            search, plain = tuple(item["search"]), tuple(item["plain"])
            if search not in pairs:
                raise ValueError(f"plan: identity pair {item['search']} is not in pairs")
            if plain not in pairs:
                raise ValueError(f"plan: identity's plain pair {item['plain']} is not in pairs")
            if pairs[plain] < pairs[search]:
                raise ValueError(f"plan: identity's plain pair {item['plain']} has fewer "
                                 f"games than {item['search']}")
    return out, block


def check_manifest(manifest, plan):
    want, block = registered(plan)
    pairs, seed0 = scheduled(plan, want)
    problems = []
    if not _int(manifest.get("seed0")):
        problems.append(f"manifest seed0 {manifest.get('seed0')!r} is not an integer")
    elif seed0 is not None and manifest["seed0"] != seed0:
        problems.append(f"manifest seed0 {manifest['seed0']} != registered {seed0}")
    if pairs is not None:
        listed = sorted([a, b, n] for (a, b), n in pairs.items())
        got = manifest.get("pairs")
        if not isinstance(got, list) or sorted(got, key=repr) != sorted(listed, key=repr):
            problems.append(f"manifest pairs differ from the registered: {got} != {listed}")
    players = manifest.get("players") or {}
    if sorted(players) != sorted(want):
        problems.append(f"manifest players {sorted(players)} != registered {sorted(want)}")
    for name, reg in want.items():
        if name not in players:
            continue                                        # reported above
        spec = players[name]
        if not isinstance(spec, dict):
            problems.append(f"player {name}: manifest spec {spec!r} is not an object")
            continue
        if spec.get("bot") != reg["bot"]:
            problems.append(f"player {name}: manifest bot {spec.get('bot')!r} != registered "
                            f"{reg['bot']!r}")
        # A bot's spec is its kind alone; the tournament seats it as scripted.
        mode, temperature = (None, None) if reg["bot"] else (reg["mode"], reg["temperature"])
        if spec.get("mode") != mode or not _is(spec.get("temperature"), temperature):
            problems.append(f"player {name}: manifest mode {spec.get('mode')!r} at temperature "
                            f"{spec.get('temperature')!r} != registered {mode!r} at "
                            f"{temperature!r}")
        masks = spec.get("masks", [])
        if not isinstance(masks, list) or sorted(masks, key=repr) != reg["masks"]:
            problems.append(f"player {name}: manifest masks {spec.get('masks')} != registered "
                            f"{reg['masks']}")
        if not _is(spec.get("seed_offset", 0), reg["offset"]):
            problems.append(f"player {name}: manifest sampling offset "
                            f"{spec.get('seed_offset')} != registered {reg['offset']}")
        if spec.get("search") != reg["search"]:
            problems.append(f"player {name}: manifest search setting "
                            f"{spec.get('search')} != registered {reg['search']}")
    searching = sorted(name for name, reg in want.items() if reg["search"])
    entry = manifest.get("search")
    if not searching:
        if entry:
            problems.append("the manifest has a search entry and no player is registered "
                            "to search")
        return problems
    gpw = manifest.get("games_per_worker")
    if (1 if gpw is None else gpw) != 1:
        problems.append(f"games_per_worker {gpw}: a searched run is played unbatched (1)")
    if not isinstance(entry, dict):
        problems.append("the manifest has no search entry")
        return problems
    if sorted(entry.get("players") or []) != searching:
        problems.append(f"manifest search players {entry.get('players')} != registered "
                        f"{searching}")
    got = (entry.get("reward_manifest") or {}).get("sha256")
    if got != block["reward_manifest_sha256"]:
        problems.append(f"manifest reward manifest {got} != registered "
                        f"{block['reward_manifest_sha256']}")
    if entry.get("integrity_checks") != block["integrity_checks"]:
        problems.append("the manifest's integrity checks are not the registered list")
    return problems


def _stat_problems(stats, setting, c_steps):
    """What is wrong with one searching seat's statistics for one game."""
    if not isinstance(stats, dict) or set(stats) != set(STAT_KEYS):
        return [f"search statistics need exactly {list(STAT_KEYS)}"]
    out = []
    scope = list(setting["scope"])
    for key in ("in_scope", "searched", "deviations"):
        if sorted(stats[key]) != sorted(scope):
            out.append(f"{key} classes {sorted(stats[key])} != the setting's scope {scope}")
    if out:
        return out
    numbers = [stats[k][c] for k in ("in_scope", "searched", "deviations") for c in scope] + [
        stats[k] for k in STAT_KEYS[5:]]
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in numbers):
        return ["a search count is not a non-negative integer"]
    for c in scope:
        if not stats["in_scope"][c] >= stats["searched"][c] >= stats["deviations"][c]:
            out.append(f"class {c}: in scope {stats['in_scope'][c]}, searched "
                       f"{stats['searched'][c]}, deviations {stats['deviations'][c]}")
    searched = sum(stats["searched"].values())
    deviations = sum(stats["deviations"].values())
    gains, types = stats["predicted_gains"], stats["deviation_types"]
    if not isinstance(gains, list) or not all(_real(gain) for gain in gains):
        return out + ["a predicted gain is not a finite number"]
    if len(gains) != deviations or sum(types.values()) != deviations:
        out.append(f"{deviations} deviations, {len(gains)} predicted gains, "
                   f"{sum(types.values())} deviation types")
    if any(key.split(": ")[0] not in scope for key in types):
        out.append(f"a deviation outside the scope: {sorted(types)}")
    if stats["error_rollouts"]:
        out.append(f"{stats['error_rollouts']} error rollout(s)")
    if stats["shadow_forwards"] != c_steps:
        out.append(f"{stats['shadow_forwards']} opponent-view forwards over {c_steps} steps")
    k, n = setting["k"], setting["n"]
    if not 2 * n * searched <= stats["rollouts"] <= k * n * searched:
        out.append(f"{stats['rollouts']} rollouts for {searched} searched decisions at "
                   f"k {k}, n {n}")
    if stats["rollout_steps"] < stats["rollouts"]:
        out.append(f"{stats['rollout_steps']} rollout steps for {stats['rollouts']} rollouts")
    if stats["cap_rejected_decisions"] > searched or \
            stats["cap_rejected_rollouts"] < stats["cap_rejected_decisions"] or \
            stats["cap_rejected_rollouts"] > stats["rollouts"]:
        out.append(f"cap rejections: {stats['cap_rejected_decisions']} decisions, "
                   f"{stats['cap_rejected_rollouts']} rollouts")
    if stats["cutoff_rollouts"] > stats["rollouts"]:
        out.append(f"{stats['cutoff_rollouts']} cutoff rollouts of {stats['rollouts']}")
    if setting["delta"] == "inf":
        if deviations:
            out.append(f"{deviations} deviation(s) at delta inf")
    elif any(gain < setting["delta"] for gain in gains):
        # Not a strict comparison: the seat deviates on gain > delta and records
        # the gain rounded to six decimals, which can equal delta.
        out.append(f"a predicted gain below delta {setting['delta']}")
    return out


def _seat_problems(g, want, pairs):
    """What is wrong with who a record says played, and on which seat. The
    record's home and away are held to its pair and leg, so that every later
    check reads the settings of the players the schedule put there."""
    out = []
    pair, leg = g.get("pair"), g.get("leg")
    names = (g.get("home"), g.get("away"))
    if any(not isinstance(name, str) or name not in want for name in names):
        out.append(f"an unregistered player in {names}")
    if not _two(pair, lambda name: isinstance(name, str)) or pair[0] == pair[1]:
        return out + ["pair is not a list of two different players"]
    if leg not in LEGS:
        return out + [f"leg {leg!r} is not one of {list(LEGS)}"]
    if names != (tuple(pair) if leg == LEGS[0] else tuple(pair[::-1])):
        out.append(f"home and away {names} are not the pair {pair} seated for this leg")
    if pairs is not None and tuple(pair) not in pairs:
        out.append("the pair is not registered")
    return out


def _side_problems(g, names, want):
    """What is wrong with how a record says each side was seated: bot, mode,
    temperature, masks, sampling offset and the sampling seed that offset
    gives. An absent field is a problem, never a default."""
    out = [f"{key} is not a two-element list" for key in
           ("bots", "modes", "temperatures", "masks", "seed_offsets", "sampling_seeds")
           if not _two(g.get(key))]
    if out:
        return out
    for side, name in enumerate(names):
        reg = want[name]
        if g["bots"][side] != reg["bot"]:
            out.append(f"{name} played as bot {g['bots'][side]!r}, registered {reg['bot']!r}")
        mode, temperature = g["modes"][side], g["temperatures"][side]
        if mode != reg["mode"] or not _is(temperature, reg["temperature"]):
            out.append(f"{name} searched outside sample mode at temperature 1" if reg["search"]
                       else f"{name} played in mode {mode!r} at temperature {temperature!r}, "
                            f"registered {reg['mode']!r} at {reg['temperature']!r}")
        masks = g["masks"][side]
        if (sorted(masks, key=repr) if isinstance(masks, list) else masks) != \
                (reg["masks"] or None):
            out.append(f"{name} played under masks {masks}, registered {reg['masks'] or None}")
        if not _is(g["seed_offsets"][side], reg["offset"]):
            out.append(f"{name} on sampling offset {g['seed_offsets'][side]}, registered "
                       f"{reg['offset']}")
        if _int(g.get("engine_seed")):
            seed = sampling_seed(g["engine_seed"], side, reg["offset"])
            if not _is(g["sampling_seeds"][side], seed):
                out.append(f"{name}'s sampling seed {g['sampling_seeds'][side]} is not {seed}, "
                           f"what engine seed {g['engine_seed']} gives side {side} at sampling "
                           f"offset {reg['offset']}")
    return out


def _integrity_problems(g, names, want):
    """What is wrong with a record's integrity evidence: the hard counters, and
    the statistics of each mask a side played under. Missing evidence is a
    problem like a nonzero counter."""
    out = []
    integrity = g.get("integrity")
    if not isinstance(integrity, dict) or set(integrity) != set(HARD_COUNTERS):
        got = list(integrity) if isinstance(integrity, dict) else integrity
        out.append(f"integrity counters {got} are not exactly {list(HARD_COUNTERS)}")
    if isinstance(integrity, dict):
        bad = {k: v for k, v in integrity.items() if not _int(v) or v}
        if bad:
            out.append(f"integrity {bad}")
    mask_stats = g.get("mask_stats")
    if not _two(mask_stats):
        return out + ["mask_stats is not a two-element list"]
    fallbacks = 0
    for name, got in zip(names, mask_stats):
        masks = want[name]["masks"]
        if (sorted(got) if isinstance(got, dict) else got) != (masks or None):
            out.append(f"{name} has mask statistics for "
                       f"{sorted(got) if isinstance(got, dict) else got}, registered masks "
                       f"{masks}")
            continue
        for mask, stats in (got or {}).items():
            if not isinstance(stats, dict) or set(stats) != set(MASK_STAT_KEYS) or \
                    any(not _int(stats[k]) or stats[k] < 0 for k in MASK_STAT_KEYS[:3]) or \
                    not _real(stats["mass"]) or stats["mass"] < 0:
                out.append(f"{name}'s mask {mask} statistics {stats} are not non-negative "
                           f"{list(MASK_STAT_KEYS)}")
            else:
                fallbacks += stats["fallback"]
    if fallbacks:
        out.append(f"{fallbacks} mask fallback(s)")
    return out


def _seed_problems(g, seed0, games_in_pair):
    """What is wrong with which game of its pair a record says it is."""
    out = []
    index, seed = g.get("game_index"), g.get("engine_seed")
    if not _int(index) or index < 0:
        out.append(f"game index {index!r} is not an integer >= 0")
    elif games_in_pair is not None and index >= games_in_pair // len(LEGS):
        out.append(f"game index {index} is outside the pair's {games_in_pair} registered games")
    if not _int(seed):
        out.append(f"engine seed {seed!r} is not an integer")
    elif seed0 is not None and _int(index) and seed != seed0 + index:
        out.append(f"engine seed {seed} is not seed0 {seed0} + game index {index}")
    if not _int(g.get("episode")) or g["episode"] != 0:
        out.append(f"episode {g.get('episode')!r} is not 0")
    if g.get("schema") != SCHEMA:
        out.append(f"schema {g.get('schema')!r} is not {SCHEMA!r}")
    return out


def check_games(games, plan, seed0=None):
    """(problems, counts) for the games of a run. seed0 is the manifest's; the
    plan's, when it has one, is used instead."""
    want, block = registered(plan)
    pairs, plan_seed0 = scheduled(plan, want)
    seed0 = seed0 if plan_seed0 is None else plan_seed0
    problems = []
    counts = {"games": 0, "searched_games": 0, "rollouts": 0, "cutoff_rollouts": 0,
              "cap_rejected_decisions": 0, "error_rollouts": 0,
              "searched": collections.Counter(), "deviations": collections.Counter(),
              "scheduled_pairs": None if pairs is None else len(pairs)}
    per_pair = collections.defaultdict(lambda: [0, 0])     # (pair, player): searched, rejected
    seen = collections.Counter()                            # (pair, game index, leg)
    for g in games:
        counts["games"] += 1
        if not isinstance(g, dict):
            problems.append("a game record is not an object")
            continue
        where = f"{g.get('pair')} seed {g.get('engine_seed')} {g.get('leg')}"
        found = _seat_problems(g, want, pairs)
        if found:
            problems += [f"{where}: {p}" for p in found]
            continue
        names = (g["home"], g["away"])
        pair = tuple(g["pair"])
        found = _seed_problems(g, seed0, None if pairs is None else pairs[pair])
        problems += [f"{where}: {p}" for p in found]
        if not found:
            seen[(pair, g["game_index"], g["leg"])] += 1
            if seen[(pair, g["game_index"], g["leg"])] == 2:
                problems.append(f"{where}: recorded more than once")
        problems += [f"{where}: {p}" for p in _side_problems(g, names, want)]
        if g.get("natural") is not True or g.get("truncated") is not False:
            problems.append(f"{where}: natural {g.get('natural')!r}, truncated "
                            f"{g.get('truncated')!r}")
        problems += [f"{where}: {p}" for p in _integrity_problems(g, names, want)]
        if g.get("forwards") != [g.get("c_steps")] * 2:
            problems.append(f"{where}: forwards {g.get('forwards')} over {g.get('c_steps')} "
                            "steps")
        if not any(want[name]["search"] for name in names):
            # The tournament writes none of these keys into such a game.
            extra = sorted(key for key in SEARCH_FIELDS
                           if key in g and (key != "search" or g[key] != [None, None]))
            if extra:
                problems.append(f"{where}: no registered search, yet the game carries {extra}")
            continue
        counts["searched_games"] += 1
        if g.get("reward_manifest_sha256") != block["reward_manifest_sha256"]:
            problems.append(f"{where}: reward manifest {g.get('reward_manifest_sha256')} != "
                            f"registered {block['reward_manifest_sha256']}")
        if g.get("integrity_checks") != block["integrity_checks"]:
            problems.append(f"{where}: its integrity checks are not the registered list")
        for key in ("final_state_sha256", "sampling_state_sha256"):
            if not _hex(g.get(key), 64):
                problems.append(f"{where}: {key} {g.get(key)!r} is not a sha256")
        # A record without search or search_stats reads as one whose seats did
        # not search, which the checks below then hold against the plan.
        settings, all_stats = g.get("search", [None, None]), g.get("search_stats", [None, None])
        seconds = g.get("search_seconds")
        broken = [key for key, value in (("search", settings), ("search_stats", all_stats),
                                         ("search_seconds", seconds)) if not _two(value)]
        if broken:
            problems += [f"{where}: {key} is not a two-element list" for key in broken]
            continue
        for side, name in enumerate(names):
            setting = want[name]["search"]
            if settings[side] != setting:
                problems.append(f"{where}: {name}'s search setting {settings[side]} != "
                                f"registered {setting}")
            if not setting:
                if all_stats[side] is not None:
                    problems.append(f"{where}: {name} does not search and has search statistics")
                if seconds[side] is not None:
                    problems.append(f"{where}: {name} does not search and has search_seconds "
                                    f"{seconds[side]}")
                continue
            if not _real(seconds[side]) or seconds[side] < 0:
                problems.append(f"{where}: {name}'s search_seconds {seconds[side]} is not a "
                                "number >= 0")
            found = _stat_problems(all_stats[side], setting, g.get("c_steps"))
            problems += [f"{where}: {name}: {p}" for p in found]
            if found:
                continue
            stats = all_stats[side]
            for c in setting["scope"]:
                counts["searched"][c] += stats["searched"][c]
                counts["deviations"][c] += stats["deviations"][c]
            for key in ("rollouts", "cutoff_rollouts", "cap_rejected_decisions",
                        "error_rollouts"):
                counts[key] += stats[key]
            cell = per_pair[(tuple(g.get("pair") or ()), name)]
            cell[0] += sum(stats["searched"].values())
            cell[1] += stats["cap_rejected_decisions"]
    for (pair, name), (searched, rejected) in sorted(per_pair.items()):
        ceiling = float(block["cap_rejection_ceiling"])
        if searched and rejected / searched > ceiling:
            problems.append(f"{pair}: {rejected} of {name}'s {searched} searched decisions had "
                            f"a cap rejection, above the ceiling {ceiling}")
    for pair, n in sorted((pairs or {}).items()):
        missing = sorted((i, leg) for i in range(n // len(LEGS)) for leg in LEGS
                         if not seen[(pair, i, leg)])
        if missing:
            problems.append(f"{pair}: {len(missing)} of the {n} registered games missing, "
                            f"e.g. {missing[:3]}")
    counts["searched"], counts["deviations"] = dict(counts["searched"]), dict(counts["deviations"])
    return problems, counts


def check_identity(games, plan):
    """(problems, identity games that matched) for the plan's identity entries.

    A game of the `search` pair matches when the `plain` pair has exactly one
    game on its seed and leg, every compared field is there in both and equal,
    and the searching seat's statistics add up, searched at least one decision
    and never deviated. Every game of the pair must match, and when the plan
    lists pairs, as many as it registers for the pair."""
    want, block = registered(plan)
    pairs, _ = scheduled(plan, want)
    problems, matched = [], 0
    by_pair = collections.defaultdict(lambda: collections.defaultdict(list))
    for g in games:
        # check_games reports a record this cannot place.
        if isinstance(g, dict) and _two(g.get("pair"), lambda name: isinstance(name, str)) \
                and _int(g.get("engine_seed")) and g.get("leg") in LEGS:
            by_pair[tuple(g["pair"])][(g["engine_seed"], g["leg"])].append(g)
    for item in block.get("identity") or []:
        search, plain = tuple(item["search"]), tuple(item["plain"])
        name = next(n for n in search if want[n]["search"])
        if not by_pair.get(search):
            problems.append(f"identity: no game of the pair {search}")
            continue
        here = 0
        for key, found in sorted(by_pair[search].items()):
            where = f"identity {search} seed {key[0]} {key[1]}"
            base = by_pair.get(plain, {}).get(key, [])
            if not base:
                problems.append(f"{where}: the plain pair {plain} has no such game")
                continue
            if len(found) > 1 or len(base) > 1:
                problems.append(f"{where}: recorded more than once")
                continue
            game, base = found[0], base[0]
            unusable = [[f for f, usable in IDENTITY_SHAPES.items() if not usable(rec.get(f))]
                        for rec in (game, base)]
            if unusable[0] or unusable[1]:
                problems.append(f"{where}: has no usable {unusable[0]}" if unusable[0] else
                                f"{where}: the plain game has no usable {unusable[1]}")
                continue
            differ = [f for f in IDENTITY_FIELDS if game[f] != base[f]]
            if differ:
                problems.append(f"{where}: differs from the plain game on {differ}")
                continue
            # The seat the pair and leg give the searching player.
            side = search.index(name) if key[1] == LEGS[0] else 1 - search.index(name)
            stats = game.get("search_stats")
            stats = stats[side] if _two(stats) else None
            wrong = _stat_problems(stats, want[name]["search"], game["c_steps"])
            if wrong:
                problems.append(f"{where}: {wrong[0]}")
                continue
            if not sum(stats["searched"].values()):
                problems.append(f"{where}: ran no search")
                continue
            here += 1
        matched += here
        if pairs is not None and here != pairs[search]:
            problems.append(f"identity {search}: {here} of the {pairs[search]} registered "
                            "games equal the plain game")
    return problems, matched


def accept(run_dir, plan, require_schedule=False):
    """(problems, counts) for a run directory; no problems means accepted."""
    registered(plan, require_schedule)
    with open(os.path.join(run_dir, "manifest.json")) as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict):
        raise ValueError("manifest.json is not an object")
    with open(os.path.join(run_dir, "games.jsonl")) as handle:
        games = [json.loads(line) for line in handle if line.strip()]
    problems = check_manifest(manifest, plan)
    seed0 = manifest.get("seed0")
    found, counts = check_games(games, plan, seed0 if _int(seed0) else None)
    more, counts["identity_games"] = check_identity(games, plan)
    problems += found + more
    if len(problems) > MAX_PROBLEMS:
        problems = problems[:MAX_PROBLEMS] + [f"... and {len(problems) - MAX_PROBLEMS} more"]
    return problems, counts


def accepted_line(counts):
    searched = sum(counts["searched"].values())
    share = counts["cap_rejected_decisions"] / searched if searched else 0.0
    by_class = ", ".join(f"{c} {counts['searched'][c]} searched / {counts['deviations'][c]} "
                         "deviations" for c in sorted(counts["searched"]))
    return (f"SEARCH-ACCEPTED {counts['searched_games']} searched games of {counts['games']} "
            f"as registered; {by_class or 'no searched decision'}; "
            f"{counts['cap_rejected_decisions']} cap-rejected decisions "
            f"({share * 100:.3f}%), {counts['cutoff_rollouts']} cutoff rollouts of "
            f"{counts['rollouts']}, {counts['error_rollouts']} error rollouts; "
            f"{counts['identity_games']} identity game(s) equal to the plain game; "
            + ("no pairs in the plan: no schedule held" if counts["scheduled_pairs"] is None
               else f"{counts['scheduled_pairs']} pair(s) held to the plan's schedule"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("plan")
    parser.add_argument("run_dir")
    parser.add_argument("--expect-sha256", required=True,
                        help="the PLAN.json hash committed before launch")
    args = parser.parse_args(argv)
    plan_sha = sha256_file(args.plan)
    if plan_sha != args.expect_sha256.strip().lower():
        print(f"SEARCH-REJECTED plan file hashes to {plan_sha}, not the committed "
              f"{args.expect_sha256}")
        return 1
    with open(args.plan) as handle:
        plan = json.load(handle)
    try:
        problems, counts = accept(args.run_dir, plan, require_schedule=True)
    except ValueError as exc:
        print(f"SEARCH-REJECTED {exc}")
        return 1
    if problems:
        for problem in problems:
            print(f"SEARCH-REJECTED {problem}")
        return 1
    print(accepted_line(counts))
    print(f"plan {os.path.abspath(args.plan)} sha256 {plan_sha}; this tool sha256 "
          f"{sha256_file(os.path.abspath(__file__))}; games.jsonl sha256 "
          f"{sha256_file(os.path.join(args.run_dir, 'games.jsonl'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
