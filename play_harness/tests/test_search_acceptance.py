"""tools/search_acceptance.py: a run's masks, sampling offsets and search settings
are held to the registered plan, in the manifest and on every game, and each
searched game's own account of its search has to add up.

Synthetic records here, written with the tournament's own record functions, and
one real run at the end. test_search_tournament.py runs the same check on its own
real runs.
"""
import copy
import hashlib
import importlib.util
import itertools
import json
import os

import pytest

from play_harness import search as S
from play_harness import tournament as T
from play_harness.policy import MaskedPolicySeat

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPEC = importlib.util.spec_from_file_location(
    "search_acceptance", os.path.join(ROOT, "tools", "search_acceptance.py"))
sa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sa)
GATE_SPEC = importlib.util.spec_from_file_location(
    "gate_acceptance", os.path.join(ROOT, "tools", "gate_acceptance.py"))
ga = importlib.util.module_from_spec(GATE_SPEC)
GATE_SPEC.loader.exec_module(ga)

SEED0 = 25100000
LEGS = ("A_home", "B_home")
SETTING = S.search_setting()
IDENTITY = S.search_setting(4, 16, float("inf"))
CHECKS = list(S.INTEGRITY_CHECKS)
SHA = S.REWARD_MANIFEST_SHA256
PAIRS = (("S", "C"), ("S", "chain37"), ("C", "chain37"), ("S", "offense"), ("I", "C"),
         ("P", "C"))


def plan():
    """A gate in miniature: S searches, C is the plain control on sampling offset
    1, chain37 and the bot are held out, I and P are the identity sample."""
    return {
        "seed0": SEED0, "pairs": [[a, b, 4] for a, b in PAIRS],
        "players": {
            "S": {"checkpoint": "chain55", "masks": ["m1"], "search": copy.deepcopy(SETTING)},
            "C": {"checkpoint": "chain55", "masks": ["m1"], "sampling_offset": 1},
            "chain37": {"checkpoint": "chain37", "masks": []},
            "offense": {"bot": "offense"},
            "I": {"checkpoint": "chain55", "masks": ["m1"], "search": copy.deepcopy(IDENTITY)},
            "P": {"checkpoint": "chain55", "masks": ["m1"]}},
        "search": {"reward_manifest_sha256": SHA, "integrity_checks": list(CHECKS),
                   "cap_rejection_ceiling": 0.01,
                   "identity": [{"search": ["I", "C"], "plain": ["P", "C"]}]}}


def manifest():
    players = {}
    for name, spec in plan()["players"].items():
        if "bot" in spec:
            players[name] = {"bot": spec["bot"]}
            continue
        players[name] = {"mode": "sample", "temperature": 1.0}
        if spec.get("masks"):
            players[name]["masks"] = spec["masks"]
        if spec.get("sampling_offset"):
            players[name]["seed_offset"] = spec["sampling_offset"]
        if spec.get("search"):
            players[name]["search"] = spec["search"]
    return {"players": players, "games_per_worker": 1, "seed0": SEED0,
            "pairs": [[a, b, 4] for a, b in PAIRS],
            "search": {"players": ["S", "I"], "reward_manifest": {"name": "r0_poss_half",
                                                                  "sha256": SHA},
                       "integrity_checks": list(CHECKS),
                       "path": "unbatched (games_per_worker 1)"}}


def stats(setting, steps=1200, deviations=(1, 2)):
    turn, after = deviations if setting["delta"] != "inf" else (0, 0)
    searched = {"turn": 100, "after_declare": 110}
    total = sum(searched.values())
    types = {}
    if turn:
        types["turn: ACTIVATE -> ACTIVATE"] = turn
    if after:
        types["after_declare: END_ACTIVATION -> STEP"] = after
    return {"in_scope": {"turn": 104, "after_declare": 111}, "searched": searched,
            "deviations": {"turn": turn, "after_declare": after}, "deviation_types": types,
            "predicted_gains": [0.1 + 0.01 * i for i in range(turn + after)],
            "rollouts": setting["k"] * setting["n"] * total - 3 * setting["n"],
            "rollout_steps": 250000, "rollout_forward_rows": 480000,
            "cap_rejected_rollouts": 0, "cap_rejected_decisions": 0, "cutoff_rollouts": 2,
            "error_rollouts": 0, "shadow_forwards": steps}


def game(pair, index, leg):
    """One record, with the fields and the functions the tournament writes it
    with: Match.record's dict wrapped by pair_record."""
    players = plan()["players"]
    home, away, seed, _, _ = T.pair_seating(*pair, index, leg, SEED0)
    names = (home, away)
    settings = [players[n].get("search") for n in names]
    masks = [players[n].get("masks") or None for n in names]
    bots = [players[n].get("bot") for n in names]
    offsets = [players[n].get("sampling_offset", 0) for n in names]
    modes = [T.SCRIPTED_MODE if b else "sample" for b in bots]
    # The identity pair and its plain pair are the same game.
    key = ("I/P" if pair in (("I", "C"), ("P", "C")) else "/".join(pair), index, leg)
    digest = hashlib.sha256(repr(key).encode()).hexdigest()
    rec = {"engine_seed": seed, "episode": 0,
           "mode": modes[0] if modes[0] == modes[1] else "mixed", "modes": modes,
           "temperatures": [None if b else 1.0 for b in bots], "bots": bots,
           "sampling_seeds": [(T.sampling_seed(seed, side) + offsets[side]
                               * T.SEED_OFFSET_STRIDE) % (1 << 62) for side in (0, 1)],
           "team_ids": [3, 7], "teams": ["Chaos Chosen", "Human"], "score": [1, 0],
           "natural": True, "truncated": False, "final_status": 2, "half": 2, "turns": [8, 8],
           "c_steps": 1200, "forwards": [1200, 1200], "decisions": [700, 500],
           "engine_decisions": 1200, "logprob_sum": [-500.25, -480.5],
           "integrity": {k: 0 for k in T.HARD_COUNTERS}, "action_trail_sha256": digest,
           "final_digest": digest[:16], "seconds": 1.5, "behaviour": [{}, {}],
           "masks": masks,
           "mask_stats": [{m: {"held": 9, "applied": 3, "fallback": 0, "mass": 0.2} for m in ms}
                          if ms else None for ms in masks],
           "seed_offsets": offsets}
    if any(settings):
        rec.update({"search": settings,
                    "search_stats": [stats(s) if s else None for s in settings],
                    "search_seconds": [300.0 if s else None for s in settings],
                    "reward_manifest_sha256": SHA, "integrity_checks": list(CHECKS),
                    "final_state_sha256": digest, "sampling_state_sha256": digest[::-1]})
    return T.pair_record(*pair, index, leg, home, away, rec)


def games():
    return [game(pair, i, leg) for pair in PAIRS for i in range(2) for leg in LEGS]


def write_run(folder, m, g):
    (folder / "manifest.json").write_text(json.dumps(m))
    (folder / "games.jsonl").write_text("".join(json.dumps(row) + "\n" for row in g))
    return str(folder)


def side_of(row, name):
    return (row["home"], row["away"]).index(name)


def first(rows, name):
    """The first game `name` plays, and the side it sits on."""
    row = next(r for r in rows if name in (r["home"], r["away"]))
    return row, side_of(row, name)


# ---- a run that is the plan -------------------------------------------------------------------
def test_a_run_that_matches_the_plan_is_accepted(tmp_path, capsys):
    run = write_run(tmp_path, manifest(), games())
    problems, counts = sa.accept(run, plan())
    assert problems == []
    assert counts["games"] == 24 and counts["searched_games"] == 16
    assert counts["searched"] == {"turn": 1600, "after_declare": 1760}
    assert counts["deviations"] == {"turn": 12, "after_declare": 24}     # none on I's games
    assert counts["identity_games"] == 4 and counts["error_rollouts"] == 0
    path = tmp_path / "PLAN.json"
    path.write_text(json.dumps(plan()))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    assert sa.main([str(path), run, "--expect-sha256", sha]) == 0
    out = capsys.readouterr().out
    assert out.startswith("SEARCH-ACCEPTED 16 searched games of 24 as registered; "
                          "after_declare 1760 searched / 24 deviations, "
                          "turn 1600 searched / 12 deviations; 0 cap-rejected decisions "
                          "(0.000%), 32 cutoff rollouts of ")
    assert "0 error rollouts; 4 identity game(s) equal to the plain game" in out
    assert sa.main([str(path), run, "--expect-sha256", "0" * 64]) == 1
    assert "SEARCH-REJECTED plan file hashes to" in capsys.readouterr().out


def test_the_default_setting_is_what_a_plan_carries():
    assert set(SETTING) == set(sa.SETTING_KEYS) == set(S.SETTING_KEYS)
    assert set(stats(SETTING)) == set(sa.STAT_KEYS)
    seat = S.SearchSeat.__new__(S.SearchSeat)
    seat.scope, seat.policy = S.SCOPE, type("P", (), {"initial_state": lambda self, n: None})()
    seat._reset_search()
    assert set(seat.stats) == set(sa.STAT_KEYS)           # the harness writes these keys


def test_the_names_this_tool_repeats_are_the_tournaments():
    """The tool imports nothing from the harness, so it repeats these."""
    assert sa.SCHEMA == T.SCHEMA and sa.LEGS == T.LEGS == ga.LEGS
    assert sa.HARD_COUNTERS == T.HARD_COUNTERS
    seat = MaskedPolicySeat.__new__(MaskedPolicySeat)
    seat.masks = ("m1",)
    assert tuple(seat._fresh_stats()["m1"]) == sa.MASK_STAT_KEYS
    assert sa.SCRIPTED_MODE == T.SCRIPTED_MODE and T.BotSeat.temperature is None
    for seed, side, offset in itertools.product((0, 7, SEED0, (1 << 61) + 5), (0, 1), (0, 1, 9)):
        assert sa.sampling_seed(seed, side, offset) == (
            T.sampling_seed(seed, side) + offset * T.SEED_OFFSET_STRIDE) % (1 << 62)


def test_a_run_without_search_needs_no_search_block(tmp_path):
    p = plan()
    p["players"] = {k: v for k, v in p["players"].items() if k in ("C", "chain37", "P")}
    p["pairs"] = [["C", "chain37", 4], ["P", "C", 4]]
    del p["search"]
    m = manifest()
    m["players"] = {k: v for k, v in m["players"].items() if k in p["players"]}
    m["pairs"] = [["P", "C", 4], ["C", "chain37", 4]]     # in any order
    del m["search"]
    m["games_per_worker"] = 32                            # plain games may batch
    rows = [r for r in games() if tuple(r["pair"]) in (("C", "chain37"), ("P", "C"))]
    assert sa.accept(write_run(tmp_path, m, rows), p)[0] == []
    # The same run with a search entry or search fields nobody registered.
    assert any("no player is registered to search" in x for x in sa.check_manifest(
        dict(m, search=manifest()["search"]), p))
    rows[0]["search"] = [None, None]                      # an explicit "none" is fine
    assert sa.check_games(rows, p)[0] == []
    rows[0]["integrity_checks"] = CHECKS
    assert any("no registered search, yet the game carries" in x
               for x in sa.check_games(rows, p)[0])


# ---- the manifest -----------------------------------------------------------------------------
@pytest.mark.parametrize("change, needle", [
    (lambda m: m["players"]["S"]["search"].update(k=8), "player S: manifest search setting"),
    (lambda m: m["players"]["S"]["search"].update(n=32), "player S: manifest search setting"),
    (lambda m: m["players"]["S"]["search"].update(delta=0.02), "player S: manifest search"),
    (lambda m: m["players"]["S"]["search"].update(scope=["turn", "declare", "after_declare"]),
     "player S: manifest search setting"),
    (lambda m: m["players"]["S"]["search"].update(max_rollout_steps=400), "player S: manifest"),
    (lambda m: m["players"]["S"]["search"].update(gamma=0.995), "player S: manifest search"),
    (lambda m: m["players"]["S"]["search"].update(opponent_model="the real seat"), "player S"),
    (lambda m: m["players"]["S"]["search"].update(reward_manifest_sha256="0" * 64), "player S"),
    (lambda m: m["players"]["S"].pop("search"), "player S: manifest search setting None"),
    (lambda m: m["players"]["C"].update(search=copy.deepcopy(SETTING)), "player C: manifest"),
    (lambda m: m["players"]["S"].update(masks=["m1", "m2"]), "player S: manifest masks"),
    (lambda m: m["players"]["C"].pop("seed_offset"), "player C: manifest sampling offset"),
    (lambda m: m["players"]["S"].update(seed_offset=1), "player S: manifest sampling offset"),
    (lambda m: m["players"].update(extra={"mode": "sample"}), "manifest players"),
    (lambda m: m["players"].pop("chain37"), "manifest players"),
    (lambda m: m.update(games_per_worker=32), "a searched run is played unbatched"),
    (lambda m: m.pop("search"), "the manifest has no search entry"),
    (lambda m: m["search"].update(players=["S"]), "manifest search players"),
    (lambda m: m["search"]["reward_manifest"].update(sha256="0" * 64),
     "manifest reward manifest"),
    (lambda m: m["search"]["integrity_checks"].pop(), "manifest's integrity checks"),
])
def test_a_manifest_off_the_plan_is_rejected(change, needle):
    m = manifest()
    assert sa.check_manifest(m, plan()) == []
    change(m)
    assert any(needle in problem for problem in sa.check_manifest(m, plan()))


def test_a_manifest_without_games_per_worker_was_played_unbatched():
    m = manifest()
    del m["games_per_worker"]
    assert sa.check_manifest(m, plan()) == []


# ---- the games --------------------------------------------------------------------------------
def _stat(rows, name="S", **change):
    row, side = first(rows, name)
    row["search_stats"][side].update(change)


def _nested(rows, key, cls, value, name="S"):
    row, side = first(rows, name)
    row["search_stats"][side][key][cls] = value


def _setting(rows, name="S", **change):
    row, side = first(rows, name)
    row["search"][side] = dict(row["search"][side], **change)


@pytest.mark.parametrize("change, needle", [
    # Per game: the setting on the searching player's side.
    (lambda g: _setting(g, k=8), "S's search setting"),
    (lambda g: _setting(g, n=8), "S's search setting"),
    (lambda g: _setting(g, delta=0.02), "S's search setting"),
    (lambda g: _setting(g, scope=["turn"]), "S's search setting"),
    (lambda g: _setting(g, max_rollout_steps=100), "S's search setting"),
    (lambda g: _setting(g, gamma=1.0), "S's search setting"),
    (lambda g: _setting(g, opponent_model="none"), "S's search setting"),
    (lambda g: _setting(g, reward_manifest_sha256="1" * 64), "S's search setting"),
    (lambda g: first(g, "S")[0].update(search=[None, None]), "S's search setting None"),
    (lambda g: first(g, "S")[0].pop("search"), "S's search setting None"),
    (lambda g: first(g, "chain37")[0].update(
        search=[copy.deepcopy(SETTING)] * 2), "chain37's search setting"),
    # Per game: what the session paid and what was checked.
    (lambda g: g[0].update(reward_manifest_sha256="2" * 64), "reward manifest 2222"),
    (lambda g: g[0].pop("reward_manifest_sha256"), "reward manifest None"),
    (lambda g: g[0].update(integrity_checks=CHECKS[:-1]), "integrity checks are not"),
    (lambda g: g[0].pop("integrity_checks"), "integrity checks are not"),
    (lambda g: g[0].update(truncated=True), "truncated True"),
    (lambda g: g[0].update(natural=False), "natural False"),
    (lambda g: g[0]["integrity"].update(illegal=1), "integrity {'illegal': 1}"),
    (lambda g: g[0].update(forwards=[1200, 1199]), "forwards [1200, 1199]"),
    (lambda g: g[0]["mask_stats"][0]["m1"].update(fallback=1), "1 mask fallback"),
    (lambda g: g[0].update(modes=["argmax", "sample"]), "outside sample mode"),
    (lambda g: g[0].update(temperatures=[0.5, 1.0]), "outside sample mode"),
    # Per game: masks and sampling offsets, searched or not.
    (lambda g: g[0].update(masks=[["m1", "m3"], ["m1"]]), "S played under masks ['m1', 'm3']"),
    (lambda g: g[0].update(seed_offsets=[0, 0]), "C on sampling offset 0, registered 1"),
    (lambda g: g[0].update(seed_offsets=[1, 1]), "S on sampling offset 1, registered 0"),
    (lambda g: first(g, "chain37")[0].update(masks=[["m1"], ["m1"]]),
     "chain37 played under masks ['m1']"),
    (lambda g: next(r for r in g if r["pair"] == ["C", "chain37"]).update(truncated=True),
     "['C', 'chain37'] seed 25100000 A_home: natural True, truncated True"),
    (lambda g: next(r for r in g if r["pair"] == ["P", "C"])["integrity"].update(illegal=2),
     "['P', 'C'] seed 25100000 A_home: integrity {'illegal': 2}"),
    (lambda g: g[0].update(home="stranger"), "an unregistered player"),
    # The search statistics have to add up.
    (lambda g: _stat(g, error_rollouts=1), "1 error rollout(s)"),
    (lambda g: _stat(g, shadow_forwards=1199), "1199 opponent-view forwards over 1200"),
    (lambda g: _stat(g, rollouts=0), "0 rollouts for 210 searched decisions"),
    (lambda g: _stat(g, rollouts=4 * 16 * 210 + 16), "rollouts for 210 searched decisions"),
    (lambda g: _stat(g, rollouts=2 * 16 * 210 - 16), "rollouts for 210 searched decisions"),
    (lambda g: _stat(g, rollout_steps=5), "5 rollout steps"),
    (lambda g: _stat(g, cutoff_rollouts=10 ** 6), "cutoff rollouts of"),
    (lambda g: _stat(g, cap_rejected_decisions=211, cap_rejected_rollouts=300),
     "cap rejections: 211 decisions"),
    (lambda g: _stat(g, cap_rejected_decisions=2, cap_rejected_rollouts=1), "cap rejections"),
    (lambda g: _stat(g, predicted_gains=[0.11, 0.12]), "3 deviations, 2 predicted gains"),
    (lambda g: _stat(g, predicted_gains=[0.11, 0.12, 0.05]), "a predicted gain below delta 0.1"),
    (lambda g: _stat(g, deviation_types={"turn: ACTIVATE -> ACTIVATE": 1}),
     "3 deviations, 3 predicted gains, 1 deviation types"),
    (lambda g: _stat(g, deviation_types={"declare: DECLARE:MOVE -> DECLARE:BLITZ": 3}),
     "a deviation outside the scope"),
    (lambda g: _nested(g, "searched", "turn", 105), "class turn: in scope 104, searched 105"),
    (lambda g: _nested(g, "deviations", "turn", 101), "class turn"),
    (lambda g: _nested(g, "searched", "declare", 3), "searched classes"),
    (lambda g: _nested(g, "deviations", "turn", -1), "not a non-negative integer"),
    (lambda g: _stat(g, rollouts=1.5), "not a non-negative integer"),
    (lambda g: _stat(g, extra=1), "search statistics need exactly"),
    (lambda g: first(g, "S")[0].update(search_stats=[None, None]), "search statistics need"),
    (lambda g: first(g, "S")[0].pop("search_stats"), "search statistics need exactly"),
    (lambda g: first(g, "S")[0].update(search_stats=[stats(SETTING)] * 2),
     "does not search and has search statistics"),
    # Identity: delta inf never deviates, and the game is the plain game.
    (lambda g: _nested(g, "deviations", "turn", 1, name="I"), "at delta inf"),
    (lambda g: first(g, "I")[0].update(action_trail_sha256="f" * 64),
     "differs from the plain game on ['action_trail_sha256']"),
    (lambda g: first(g, "I")[0].update(final_digest="0" * 16, score=[0, 0]),
     "differs from the plain game on ['final_digest', 'score']"),
    (lambda g: first(g, "I")[0].update(logprob_sum=[-500.25, -480.4]), "['logprob_sum']"),
    (lambda g: first(g, "P")[0].update(sampling_seeds=[11, 13]), "['sampling_seeds']"),
    (lambda g: _stat(g, name="I", rollouts=0), "0 rollouts for 210 searched"),
    (lambda g: g.remove(first(g, "P")[0]), "the plain pair ('P', 'C') has no such game"),
])
def test_a_game_off_the_plan_is_rejected(tmp_path, change, needle):
    rows = games()
    change(rows)
    problems, _ = sa.accept(write_run(tmp_path, manifest(), rows), plan())
    assert any(needle in problem for problem in problems), problems


def test_an_identity_pair_that_was_never_played_is_rejected(tmp_path):
    rows = [r for r in games() if tuple(r["pair"]) != ("I", "C")]
    problems, counts = sa.accept(write_run(tmp_path, manifest(), rows), plan())
    assert problems == ["('I', 'C'): 4 of the 4 registered games missing, e.g. "
                        "[(0, 'A_home'), (0, 'B_home'), (1, 'A_home')]",
                        "identity: no game of the pair ('I', 'C')"]
    assert counts["identity_games"] == 0
    problems, _ = sa.accept(write_run(tmp_path, manifest(), rows), without_schedule(plan()))
    assert problems == ["identity: no game of the pair ('I', 'C')"]


def test_cap_rejections_are_held_to_the_ceiling_per_pair():
    p = plan()
    rows = games()
    mine = [r for r in rows if tuple(r["pair"]) == ("S", "chain37")]
    assert len(mine) == 4                                # 840 searched decisions
    for row in mine[:2]:
        row["search_stats"][side_of(row, "S")].update(cap_rejected_decisions=4,
                                                      cap_rejected_rollouts=9)
    problems, counts = sa.check_games(rows, p)           # 8 of 840: under 1%
    assert problems == [] and counts["cap_rejected_decisions"] == 8
    row = mine[2]
    row["search_stats"][side_of(row, "S")].update(cap_rejected_decisions=1,
                                                  cap_rejected_rollouts=1)
    problems, _ = sa.check_games(rows, p)                # 9 of 840: above
    assert problems == ["('S', 'chain37'): 9 of S's 840 searched decisions had a cap "
                        "rejection, above the ceiling 0.01"]
    p["search"]["cap_rejection_ceiling"] = 0.02
    assert sa.check_games(rows, p)[0] == []


def test_many_problems_are_cut_short(tmp_path):
    rows = games()
    for row in rows:
        row["truncated"] = True                           # held against every game,
        row["forwards"] = [1200, 1100]                    # searched or not
    problems, _ = sa.accept(write_run(tmp_path, manifest(), rows), plan())
    assert len(problems) == sa.MAX_PROBLEMS + 1 and problems[-1] == "... and 8 more"
    assert sum("truncated True" in p for p in problems) == 20


# ---- the plan itself --------------------------------------------------------------------------
@pytest.mark.parametrize("change, needle", [
    (lambda p: p.pop("players"), "no players"),
    (lambda p: p["players"]["S"]["search"].pop("gamma"), "S's search setting needs exactly"),
    (lambda p: p["players"]["S"]["search"].update(extra=1), "S's search setting needs exactly"),
    (lambda p: p.pop("search"), "search.reward_manifest_sha256 is required"),
    (lambda p: p["search"].pop("integrity_checks"), "search.integrity_checks is required"),
    (lambda p: p["search"].pop("cap_rejection_ceiling"), "cap_rejection_ceiling is required"),
    (lambda p: p["search"].update(integrity_checks=[]), "must list the checks"),
    (lambda p: p["search"].update(cap_rejection_ceiling=2), "in [0, 1]"),
    (lambda p: p["search"].update(reward_manifest_sha256="0" * 64),
     "reward manifest is not search.reward_manifest_sha256"),
    (lambda p: p["players"]["S"].update(masks=[]), "S searches without a mask"),
    (lambda p: p["search"].update(identity=[{"search": ["S", "C"], "plain": ["P", "C"]}]),
     "with delta inf"),
    (lambda p: p["search"].update(identity=[{"search": ["P", "C"], "plain": ["P", "C"]}]),
     "exactly one searching player"),
    (lambda p: p["search"].update(identity=[{"search": ["I", "C"], "plain": ["S", "C"]}]),
     "must not search"),
    (lambda p: p["search"].update(identity=[{"search": ["I", "C"]}]), "an identity entry is"),
])
def test_an_incomplete_plan_is_refused_not_read_loosely(tmp_path, capsys, change, needle):
    p = plan()
    change(p)
    with pytest.raises(ValueError, match=needle.replace("[", r"\[").replace("]", r"\]")):
        sa.registered(p)
    run = write_run(tmp_path, manifest(), games())
    path = tmp_path / "PLAN.json"
    path.write_text(json.dumps(p))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    assert sa.main([str(path), run, "--expect-sha256", sha]) == 1
    assert capsys.readouterr().out.startswith("SEARCH-REJECTED plan: ")


# ---- who played, where, on which seed (review finding 1) --------------------------------------
def gate_plan():
    """What tools/gate_acceptance.py is given for the same run."""
    return {"seed0": SEED0, "games_per_worker": 1, "commit": "c" * 40,
            "pairs": [(a, b, 4) for a, b in PAIRS], "checkpoints": {}}


def without_schedule(p):
    """The plan without its pairs and seed0: what a caller of accept() may pass."""
    return {k: v for k, v in p.items() if k not in ("pairs", "seed0")}


def test_plain_games_filed_under_a_searched_pair_are_rejected():
    """The review's false pass: every record of the searched pair (S, C) replaced
    by a plain game between two other registered players, the scheduled pair key
    kept. gate_acceptance.py reads only that key and still passes, and this check
    read the settings off the record's own home and away."""
    rows = games()
    plain = {(r["game_index"], r["leg"]): r for r in rows if r["pair"] == ["C", "chain37"]}
    swapped = [dict(copy.deepcopy(plain[(r["game_index"], r["leg"])]), pair=["S", "C"])
               if r["pair"] == ["S", "C"] else r for r in rows]
    assert ga.check_games(swapped, gate_plan()) == []
    needle = "home and away ('C', 'chain37') are not the pair ['S', 'C'] seated for this leg"
    problems, _ = sa.check_games(swapped, without_schedule(plan()))
    assert len(problems) == 4 and sum(needle in x for x in problems) == 2, problems
    problems, _ = sa.check_games(swapped, plan())
    assert len(problems) == 5 and sum("seated for this leg" in x for x in problems) == 4
    assert problems[-1].startswith("('S', 'C'): 4 of the 4 registered games missing")


def _move(row, index):
    row.update(game_index=index, engine_seed=SEED0 + index)


@pytest.mark.parametrize("change, needle", [
    (lambda g: g[0].update(pair=["C", "S"]), "are not the pair ['C', 'S'] seated for this leg"),
    (lambda g: g[0].update(leg="B_home"), "are not the pair ['S', 'C'] seated for this leg"),
    (lambda g: g[0].update(home="C", away="S"), "seated for this leg"),
    (lambda g: g[0].update(away="chain37"), "seated for this leg"),
    (lambda g: g[0].update(pair="S,C"), "pair is not a list of two different players"),
    (lambda g: g[0].update(pair=["S", "C", "chain37"]), "pair is not a list of two different"),
    (lambda g: g[0].update(pair=["S", "S"], away="S"), "pair is not a list of two different"),
    (lambda g: g[0].pop("pair"), "pair is not a list of two different players"),
    (lambda g: g[0].update(leg="C_home"), "leg 'C_home' is not one of"),
    (lambda g: g[0].pop("leg"), "leg None is not one of"),
    (lambda g: g[0].pop("home"), "an unregistered player"),
    (lambda g: g[0].update(home=["S"]), "an unregistered player"),
    (lambda g: g[0].update(pair=["S", "P"], away="P"), "the pair is not registered"),
    (lambda g: g[0].update(pair=["C", "S"], home="C", away="S"), "the pair is not registered"),
    (lambda g: g[0].update(game_index=1), "engine seed 25100000 is not seed0 25100000 + game "
                                          "index 1"),
    (lambda g: g[0].update(engine_seed=SEED0 + 1), "engine seed 25100001 is not seed0"),
    (lambda g: g[0].update(engine_seed=str(SEED0)), "is not an integer"),
    (lambda g: g[0].pop("engine_seed"), "engine seed None is not an integer"),
    (lambda g: g[0].update(game_index=True), "game index True is not an integer >= 0"),
    (lambda g: g[0].update(game_index=-1, engine_seed=SEED0 - 1), "game index -1 is not"),
    (lambda g: g[0].pop("game_index"), "game index None is not an integer >= 0"),
    (lambda g: _move(g[0], 2), "game index 2 is outside the pair's 4 registered games"),
    (lambda g: g[0].update(episode=1), "episode 1 is not 0"),
    (lambda g: g[0].pop("episode"), "episode None is not 0"),
    (lambda g: g[0].update(schema="bbplay-exam-game-v1"), "schema 'bbplay-exam-game-v1'"),
    (lambda g: g[0].pop("schema"), "schema None"),
    (lambda g: g.append(copy.deepcopy(g[0])), "recorded more than once"),
    (lambda g: g.remove(g[0]), "('S', 'C'): 1 of the 4 registered games missing, e.g. "
                               "[(0, 'A_home')]"),
    (lambda g: g.insert(0, ["not", "a", "record"]), "a game record is not an object"),
])
def test_a_game_that_is_not_its_scheduled_seat_and_seed_is_rejected(tmp_path, change, needle):
    rows = games()
    change(rows)
    problems, _ = sa.accept(write_run(tmp_path, manifest(), rows), plan())
    assert any(needle in problem for problem in problems), problems


def test_a_plan_without_a_schedule_still_binds_seats_and_seeds(tmp_path, capsys):
    """pairs and seed0 are optional for a caller of accept(): seats are held to
    pair and leg and seeds to the manifest's seed0 either way. The command line
    refuses such a plan when a player searches."""
    p = without_schedule(plan())
    rows = games()
    run = write_run(tmp_path, manifest(), rows)
    problems, counts = sa.accept(run, p)
    assert problems == [] and counts["scheduled_pairs"] is None
    assert "no pairs in the plan: no schedule held" in sa.accepted_line(counts)
    for change, needle in (
            (lambda g: g[0].update(leg="B_home"), "seated for this leg"),
            (lambda g: g[0].update(engine_seed=SEED0 + 7), "is not seed0 25100000 + game index 0"),
            (lambda g: g.append(copy.deepcopy(g[0])), "recorded more than once")):
        rows = games()
        change(rows)
        problems, _ = sa.accept(write_run(tmp_path, manifest(), rows), p)
        assert any(needle in x for x in problems), problems
    # Not held without the plan's pairs: a pair nobody scheduled, a missing game.
    rows = games()
    rows[0].update(pair=["S", "P"], away="P")
    rows.remove(rows[5])
    problems, _ = sa.accept(write_run(tmp_path, manifest(), rows), p)
    assert not any("registered" in x and "pair" in x for x in problems)
    assert not any("missing" in x for x in problems)
    path = tmp_path / "PLAN.json"
    path.write_text(json.dumps(p))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    assert sa.main([str(path), run, "--expect-sha256", sha]) == 1
    assert capsys.readouterr().out == ("SEARCH-REJECTED plan: pairs and seed0 are required "
                                       "when a player searches\n")


@pytest.mark.parametrize("change, needle", [
    (lambda m: m.update(seed0=SEED0 + 1), "manifest seed0 25100001 != registered 25100000"),
    (lambda m: m.pop("seed0"), "manifest seed0 None is not an integer"),
    (lambda m: m.update(seed0=True), "manifest seed0 True is not an integer"),
    (lambda m: m["pairs"].pop(), "manifest pairs differ from the registered"),
    (lambda m: m["pairs"][0].__setitem__(2, 6), "manifest pairs differ from the registered"),
    (lambda m: m["pairs"].append(["S", "P", 4]), "manifest pairs differ from the registered"),
    (lambda m: m["pairs"][0].reverse(), "manifest pairs differ from the registered"),
    (lambda m: m.pop("pairs"), "manifest pairs differ from the registered"),
])
def test_a_manifest_off_the_schedule_is_rejected(change, needle):
    m = manifest()
    change(m)
    assert any(needle in problem for problem in sa.check_manifest(m, plan())), needle


def test_a_manifest_seed0_decides_the_seeds_when_the_plan_has_none(tmp_path):
    m = manifest()
    m["seed0"] = SEED0 + 100                               # the run says another block
    problems, _ = sa.accept(write_run(tmp_path, m, games()), without_schedule(plan()))
    assert sum("is not seed0 25100100 + game index" in p for p in problems) == 24


@pytest.mark.parametrize("change, needle", [
    (lambda p: p.update(pairs="S,C,4"), "pairs is a list of"),
    (lambda p: p["pairs"].append(["S", "C"]), "pairs is a list of"),
    (lambda p: p["pairs"].append(["S", "stranger", 4]), "pair ['S', 'stranger', 4] needs two"),
    (lambda p: p["pairs"].append(["S", "S", 4]), "pair ['S', 'S', 4] needs two"),
    (lambda p: p["pairs"].append(["P", "S", 3]), "a positive even number of games"),
    (lambda p: p["pairs"].append(["P", "S", 0]), "a positive even number of games"),
    (lambda p: p["pairs"].append(["P", "S", True]), "a positive even number of games"),
    (lambda p: p["pairs"].append(["C", "S", 4]), "pair ['C', 'S', 4] is listed twice"),
    (lambda p: p.update(seed0="25100000"), "seed0 must be an integer"),
    (lambda p: p.update(seed0=None), "seed0 must be an integer"),
    (lambda p: p["pairs"].remove(["I", "C", 4]), "identity pair ['I', 'C'] is not in pairs"),
    (lambda p: p["pairs"].remove(["P", "C", 4]), "identity's plain pair ['P', 'C'] is not in"),
    (lambda p: p["pairs"].__setitem__(5, ["P", "C", 2]), "has fewer games than"),
    (lambda p: p.pop("pairs"), "pairs and seed0 are required when a player searches"),
    (lambda p: p.pop("seed0"), "pairs and seed0 are required when a player searches"),
])
def test_a_plan_with_a_broken_schedule_is_refused(tmp_path, capsys, change, needle):
    p = plan()
    change(p)
    with pytest.raises(ValueError, match=needle.replace("[", r"\[").replace("]", r"\]")):
        sa.registered(p, require_schedule=True)
    run = write_run(tmp_path, manifest(), games())
    path = tmp_path / "PLAN.json"
    path.write_text(json.dumps(p))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    assert sa.main([str(path), run, "--expect-sha256", sha]) == 1
    assert capsys.readouterr().out.startswith("SEARCH-REJECTED plan: ")


# ---- identity evidence (review finding 2) -----------------------------------------------------
def _identity_rows(rows, names=("I", "P")):
    return [r for r in rows if r["pair"][0] in names and r["pair"][1] == "C"]


def _idle(row):
    """The record of an identity game whose seat searched nothing."""
    st = row["search_stats"][side_of(row, "I")]
    st.update(searched={c: 0 for c in st["searched"]}, rollouts=0, rollout_steps=0,
              rollout_forward_rows=0, cutoff_rollouts=0)


def test_identity_games_without_the_compared_fields_do_not_match():
    """The review's false pass: with every compared field removed from both
    records, absent equalled absent and all four identity games matched."""
    rows = games()
    for row in _identity_rows(rows):
        for field in sa.IDENTITY_FIELDS:
            del row[field]
    problems, matched = sa.check_identity(rows, plan())
    assert matched == 0
    assert sum(f"has no usable {list(sa.IDENTITY_FIELDS)}" in p for p in problems) == 4


def test_identity_games_that_searched_nothing_do_not_match():
    """The review's second false pass: searched and rollout counts at zero went
    around the "ran no search" rejection, which asked for searched decisions
    first."""
    rows = games()
    for row in _identity_rows(rows, names=("I",)):
        _idle(row)
    assert sa.check_games(rows, plan())[0] == []           # each record adds up on its own
    problems, matched = sa.check_identity(rows, plan())
    assert matched == 0 and sum("ran no search" in p for p in problems) == 4


def _both(rows, **change):
    """The same change on the first identity game and on its plain game."""
    for name in ("I", "P"):
        first(rows, name)[0].update(change)


@pytest.mark.parametrize("change, needle", (
    [(lambda g, f=f: first(g, "I")[0].pop(f), f"has no usable ['{f}']")
     for f in sa.IDENTITY_FIELDS]
    + [(lambda g, f=f: first(g, "P")[0].pop(f), f"the plain game has no usable ['{f}']")
       for f in sa.IDENTITY_FIELDS]
    + [(lambda g, f=f: _both(g, **{f: None}), f"has no usable ['{f}']")
       for f in sa.IDENTITY_FIELDS]
    + [  # Equal on both sides, and nothing a game could have recorded.
        (lambda g: _both(g, action_trail_sha256=""), "has no usable ['action_trail_sha256']"),
        (lambda g: _both(g, action_trail_sha256="F" * 64), "['action_trail_sha256']"),
        (lambda g: _both(g, final_digest="same"), "has no usable ['final_digest']"),
        (lambda g: _both(g, logprob_sum=[]), "has no usable ['logprob_sum']"),
        (lambda g: _both(g, logprob_sum=[float("nan"), 0.0]), "has no usable ['logprob_sum']"),
        (lambda g: _both(g, score="1-0"), "has no usable ['score']"),
        (lambda g: _both(g, c_steps=0, forwards=[0, 0]), "has no usable ['c_steps']"),
        (lambda g: _both(g, team_ids=[3]), "has no usable ['team_ids']"),
        (lambda g: _both(g, sampling_seeds=[True, False]), "has no usable ['sampling_seeds']"),
        # What the searching seat recorded.
        (lambda g: _idle(first(g, "I")[0]), "identity ('I', 'C') seed 25100000 A_home: ran no "
                                            "search"),
        (lambda g: first(g, "I")[0].update(search_stats=[None, None]),
         "identity ('I', 'C') seed 25100000 A_home: search statistics need exactly"),
        (lambda g: first(g, "I")[0].pop("search_stats"),
         "identity ('I', 'C') seed 25100000 A_home: search statistics need exactly"),
        (lambda g: _stat(g, name="I", rollouts=2 * 16 * 210 - 16),
         "identity ('I', 'C') seed 25100000 A_home: 6704 rollouts for 210 searched"),
        (lambda g: _nested(g, "deviations", "turn", 1, name="I"),
         "identity ('I', 'C') seed 25100000 A_home: "),
        (lambda g: g.append(copy.deepcopy(first(g, "I")[0])),
         "identity ('I', 'C') seed 25100000 A_home: recorded more than once"),
        (lambda g: g.append(copy.deepcopy(first(g, "P")[0])),
         "identity ('I', 'C') seed 25100000 A_home: recorded more than once"),
        (lambda g: g.remove(first(g, "I")[0]),
         "identity ('I', 'C'): 3 of the 4 registered games equal the plain game"),
        (lambda g: first(g, "I")[0].update(score=[0, 1]),
         "identity ('I', 'C'): 3 of the 4 registered games equal the plain game"),
    ]))
def test_an_identity_game_without_its_evidence_does_not_match(tmp_path, change, needle):
    rows = games()
    change(rows)
    problems, counts = sa.accept(write_run(tmp_path, manifest(), rows), plan())
    assert any(needle in problem for problem in problems), problems
    assert counts["identity_games"] == 3


def test_the_identity_count_is_held_only_when_the_plan_gives_one(tmp_path):
    rows = games()
    rows.remove(first(rows, "I")[0])
    problems, counts = sa.accept(write_run(tmp_path, manifest(), rows), without_schedule(plan()))
    assert problems == [] and counts["identity_games"] == 3


# ---- integrity evidence (review finding 3) ----------------------------------------------------
def test_a_record_without_its_integrity_evidence_is_rejected():
    """The review's false pass: one hard counter of five and no mask statistics.
    Only the counters present were read, and absent mask statistics had no
    fallback."""
    rows = games()
    for row in rows:
        row["integrity"] = {"illegal": 0}
        del row["mask_stats"]
    problems, _ = sa.check_games(rows, plan())
    assert sum("integrity counters ['illegal'] are not exactly" in p for p in problems) == 24
    assert sum("mask_stats is not a two-element list" in p for p in problems) == 24


def _mask(rows, name="S", **change):
    row, side = first(rows, name)
    row["mask_stats"][side]["m1"].update(change)


def _plain(rows):
    return next(r for r in rows if r["pair"] == ["C", "chain37"])


@pytest.mark.parametrize("change, needle", (
    [(lambda g, k=k: g[0]["integrity"].update({k: 1}), f"integrity {{'{k}': 1}}")
     for k in T.HARD_COUNTERS]
    + [(lambda g, k=k: g[0]["integrity"].pop(k), "are not exactly ['illegal', "
                                                 "'projection_collision', 'error_episodes', "
                                                 "'rejected_submissions', 'precheck_collisions']")
       for k in T.HARD_COUNTERS]
    + [
        (lambda g: g[0].pop("integrity"), "integrity counters None are not exactly"),
        (lambda g: g[0].update(integrity={}), "integrity counters [] are not exactly"),
        (lambda g: g[0].update(integrity=[0] * 5), "integrity counters [0, 0, 0, 0, 0] are not"),
        (lambda g: g[0]["integrity"].update(missing=0), "are not exactly"),
        (lambda g: g[0]["integrity"].update(illegal=False), "integrity {'illegal': False}"),
        (lambda g: g[0]["integrity"].update(illegal=None), "integrity {'illegal': None}"),
        (lambda g: g[0]["integrity"].update(illegal=0.0), "integrity {'illegal': 0.0}"),
        (lambda g: g[0]["integrity"].update(illegal="0"), "integrity {'illegal': '0'}"),
        (lambda g: _plain(g)["integrity"].pop("illegal"), "['C', 'chain37'] seed 25100000 "
                                                          "A_home: integrity counters"),
        # Mask statistics: there for exactly the masks of a masked side.
        (lambda g: g[0].pop("mask_stats"), "mask_stats is not a two-element list"),
        (lambda g: g[0].update(mask_stats=[]), "mask_stats is not a two-element list"),
        (lambda g: g[0].update(mask_stats=[None, None]),
         "S has mask statistics for None, registered masks ['m1']"),
        (lambda g: g[0]["mask_stats"].__setitem__(1, {}),
         "C has mask statistics for [], registered masks ['m1']"),
        (lambda g: g[0]["mask_stats"][0].update(m2=dict(g[0]["mask_stats"][0]["m1"])),
         "S has mask statistics for ['m1', 'm2'], registered masks ['m1']"),
        (lambda g: _plain(g)["mask_stats"].__setitem__(1, {}),
         "chain37 has mask statistics for [], registered masks []"),
        (lambda g: _plain(g).update(mask_stats=[dict(_plain(g)["mask_stats"][0])] * 2),
         "chain37 has mask statistics for ['m1'], registered masks []"),
        (lambda g: g[0]["mask_stats"][0].update(m1=None), "S's mask m1 statistics None"),
        (lambda g: g[0]["mask_stats"][0]["m1"].pop("fallback"), "S's mask m1 statistics"),
        (lambda g: g[0]["mask_stats"][0]["m1"].pop("held"), "S's mask m1 statistics"),
        (lambda g: _mask(g, extra=0), "S's mask m1 statistics"),
        (lambda g: _mask(g, fallback=False), "S's mask m1 statistics"),
        (lambda g: _mask(g, fallback="0"), "S's mask m1 statistics"),
        (lambda g: _mask(g, fallback=None), "S's mask m1 statistics"),
        (lambda g: _mask(g, fallback=0.0), "S's mask m1 statistics"),
        (lambda g: _mask(g, held=-1), "S's mask m1 statistics"),
        (lambda g: _mask(g, applied=1.5), "S's mask m1 statistics"),
        (lambda g: _mask(g, mass=float("nan")), "S's mask m1 statistics"),
        (lambda g: _mask(g, mass=None), "S's mask m1 statistics"),
        (lambda g: _mask(g, name="C", fallback=2), "2 mask fallback(s)"),
        # A plain game is held to it too.
        (lambda g: _plain(g)["mask_stats"][0]["m1"].update(fallback=1),
         "['C', 'chain37'] seed 25100000 A_home: 1 mask fallback(s)"),
        (lambda g: _plain(g).pop("mask_stats"),
         "['C', 'chain37'] seed 25100000 A_home: mask_stats is not a two-element list"),
    ]))
def test_a_game_without_its_integrity_evidence_is_rejected(tmp_path, change, needle):
    rows = games()
    change(rows)
    problems, _ = sa.accept(write_run(tmp_path, manifest(), rows), plan())
    assert any(needle in problem for problem in problems), problems


# ---- predicted gains (review finding 4) -------------------------------------------------------
@pytest.mark.parametrize("gain", [float("nan"), float("inf"), float("-inf"), True, "0.5", None,
                                  [0.5]])
def test_a_predicted_gain_that_is_not_a_finite_number_is_rejected(tmp_path, gain):
    """The review's false pass: NaN and infinity are not below delta, so they
    passed the comparison. A game is aborted before it records such a gain."""
    rows = games()
    _stat(rows, predicted_gains=[0.11, 0.12, gain])
    problems, _ = sa.accept(write_run(tmp_path, manifest(), rows), plan())
    assert any("a predicted gain is not a finite number" in p for p in problems), problems


def test_a_gain_recorded_at_delta_is_accepted():
    """The seat deviates on gain > delta and records the gain rounded to six
    decimals, so a recorded gain may equal delta and never lies below it."""
    rows = games()
    _stat(rows, predicted_gains=[0.1, 0.1, 0.100001])
    assert sa.check_games(rows, plan())[0] == []
    _stat(rows, predicted_gains=[0.1, 0.1, 0.099999])
    assert any("a predicted gain below delta 0.1" in p for p in sa.check_games(rows, plan())[0])


# ---- each side's seat: nothing read off a default (item 5) ------------------------------------
def _bot_game(rows):
    return next(r for r in rows if r["pair"] == ["S", "offense"])


def _unshifted(row, name):
    """The sampling seed `name` would have had without its sampling offset."""
    side = side_of(row, name)
    row["sampling_seeds"][side] = T.sampling_seed(row["engine_seed"], side)


@pytest.mark.parametrize("change, needle", [
    # Absent used to read as "unmasked", "offset 0", "any mode".
    (lambda g: _plain(g).pop("masks"), "masks is not a two-element list"),
    (lambda g: next(r for r in g if r["pair"] == ["S", "chain37"]).pop("seed_offsets"),
     "['S', 'chain37'] seed 25100000 A_home: seed_offsets is not a two-element list"),
    (lambda g: _plain(g).pop("modes"), "modes is not a two-element list"),
    (lambda g: _plain(g).pop("temperatures"), "temperatures is not a two-element list"),
    (lambda g: _plain(g).pop("bots"), "bots is not a two-element list"),
    (lambda g: _plain(g).pop("sampling_seeds"), "sampling_seeds is not a two-element list"),
    (lambda g: _plain(g).update(masks=[["m1"]]), "masks is not a two-element list"),
    # Bots.
    (lambda g: g[0].update(bots=[None, "offense"]), "C played as bot 'offense', registered None"),
    (lambda g: _bot_game(g).update(bots=[None, None]),
     "offense played as bot None, registered 'offense'"),
    (lambda g: _bot_game(g).update(bots=[None, "contact"]),
     "offense played as bot 'contact', registered 'offense'"),
    # Mode and temperature of a seat that does not search.
    (lambda g: g[0].update(modes=["sample", "argmax"]),
     "C played in mode 'argmax' at temperature 1.0, registered 'sample' at 1.0"),
    (lambda g: g[0].update(temperatures=[1.0, 0.5]),
     "C played in mode 'sample' at temperature 0.5, registered 'sample' at 1.0"),
    (lambda g: _plain(g).update(temperatures=[1.0, None]),
     "chain37 played in mode 'sample' at temperature None, registered 'sample' at 1.0"),
    (lambda g: _plain(g).update(temperatures=[True, 1.0]), "C played in mode 'sample' at "
                                                           "temperature True"),
    (lambda g: _bot_game(g).update(modes=["sample", "sample"], temperatures=[1.0, 1.0]),
     "offense played in mode 'sample' at temperature 1.0, registered 'scripted' at None"),
    (lambda g: g[0].update(temperatures=[True, 1.0]), "S searched outside sample mode"),
    # Masks, as the tournament writes them: a list, or None for an unmasked side.
    (lambda g: g[0].update(masks=[["m1"], None]), "C played under masks None, registered ['m1']"),
    (lambda g: g[0].update(masks=[["m1"], "m1"]), "C played under masks m1, registered ['m1']"),
    (lambda g: _plain(g).update(masks=[["m1"], []]),
     "chain37 played under masks [], registered None"),
    # Sampling offsets and the seeds they give.
    (lambda g: g[0].update(seed_offsets=[False, 1]), "S on sampling offset False, registered 0"),
    (lambda g: g[0].update(seed_offsets=[0, "1"]), "C on sampling offset 1, registered 1"),
    (lambda g: _unshifted(g[0], "C"), "C's sampling seed 25100075300018 is not 25101075300025, "
                                      "what engine seed 25100000 gives side 1 at sampling "
                                      "offset 1"),
    (lambda g: g[0]["sampling_seeds"].reverse(), "S's sampling seed"),
    (lambda g: g[0]["sampling_seeds"].__setitem__(0, 11), "S's sampling seed 11 is not"),
    (lambda g: g[0]["sampling_seeds"].__setitem__(0, None), "S's sampling seed None is not"),
    (lambda g: _both(g, sampling_seeds=[11, 12]), "I's sampling seed 11 is not"),
])
def test_a_side_that_was_not_seated_as_registered_is_rejected(tmp_path, change, needle):
    rows = games()
    change(rows)
    problems, _ = sa.accept(write_run(tmp_path, manifest(), rows), plan())
    assert any(needle in problem for problem in problems), problems


def test_the_plan_decides_mode_and_temperature(tmp_path):
    """A player the plan registers at another mode or temperature is held to
    that; one it says nothing about samples at temperature 1."""
    p, m, rows = plan(), manifest(), games()
    p["players"]["chain37"].update(mode="argmax", temperature=0.5)
    assert any("player chain37: manifest mode 'sample' at temperature 1.0 != registered "
               "'argmax' at 0.5" in x for x in sa.check_manifest(m, p))
    assert sum("chain37 played in mode 'sample' at temperature 1.0, registered 'argmax' at 0.5"
               in x for x in sa.check_games(rows, p)[0]) == 8
    m["players"]["chain37"].update(mode="argmax", temperature=0.5)
    for row in rows:
        if "chain37" in row["pair"]:
            side = side_of(row, "chain37")
            row["modes"][side], row["temperatures"][side] = "argmax", 0.5
    assert sa.accept(write_run(tmp_path, m, rows), p)[0] == []


@pytest.mark.parametrize("change, needle", [
    (lambda m: m["players"].update(offense={"bot": "contact"}),
     "player offense: manifest bot 'contact' != registered 'offense'"),
    (lambda m: m["players"].update(offense={"mode": "sample", "temperature": 1.0}),
     "player offense: manifest bot None != registered 'offense'"),
    (lambda m: m["players"]["offense"].update(mode="sample"),
     "player offense: manifest mode 'sample' at temperature None != registered None at None"),
    (lambda m: m["players"]["chain37"].update(bot="offense"),
     "player chain37: manifest bot 'offense' != registered None"),
    (lambda m: m["players"]["C"].update(mode="argmax"),
     "player C: manifest mode 'argmax' at temperature 1.0 != registered 'sample' at 1.0"),
    (lambda m: m["players"]["C"].update(temperature=0.7), "player C: manifest mode 'sample' at "
                                                          "temperature 0.7"),
    (lambda m: m["players"]["C"].pop("temperature"), "player C: manifest mode 'sample' at "
                                                     "temperature None"),
    (lambda m: m["players"]["C"].pop("mode"), "player C: manifest mode None"),
    (lambda m: m["players"].update(C="chain55"), "player C: manifest spec 'chain55' is not an "
                                                 "object"),
])
def test_a_manifest_player_off_the_plan_is_rejected(change, needle):
    m = manifest()
    change(m)
    assert any(needle in problem for problem in sa.check_manifest(m, plan())), needle


@pytest.mark.parametrize("change, needle", [
    (lambda p: p["players"].update(S="chain55"), "player S is not an object"),
    (lambda p: p["players"]["offense"].update(masks=["m1"]), "bot offense takes a kind and no"),
    (lambda p: p["players"]["offense"].update(mode="sample"), "bot offense takes a kind and no"),
    (lambda p: p["players"]["offense"].update(bot=1), "bot offense takes a kind and no"),
    (lambda p: p["players"]["C"].update(mode="greedy"), "player C's mode is sample or argmax"),
    (lambda p: p["players"]["C"].update(temperature=0), "player C's temperature must be a "
                                                        "number above 0"),
    (lambda p: p["players"]["C"].update(temperature=True), "player C's temperature must be"),
    (lambda p: p["players"]["S"].update(mode="argmax"), "S searches outside sample mode at "
                                                        "temperature 1"),
    (lambda p: p["players"]["S"].update(temperature=0.5), "S searches outside sample mode at "
                                                          "temperature 1"),
    (lambda p: p["players"]["C"].update(masks="m1"), "player C's masks must be a list of names"),
    (lambda p: p["players"]["C"].update(masks=["m1", "m1"]), "player C's masks must be a list"),
    (lambda p: p["players"]["C"].update(sampling_offset="1"), "player C's sampling_offset must "
                                                              "be an integer >= 0"),
    (lambda p: p["players"]["C"].update(sampling_offset=-1), "player C's sampling_offset must"),
    (lambda p: p["players"]["C"].update(sampling_offset=1.5), "player C's sampling_offset must"),
    (lambda p: p["players"]["C"].update(search={}), "C's search setting needs exactly"),
    (lambda p: p["players"]["C"].update(search=False), "C's search setting needs exactly"),
])
def test_a_plan_with_a_player_it_cannot_read_is_refused(change, needle):
    p = plan()
    change(p)
    with pytest.raises(ValueError, match=needle.replace("[", r"\[").replace("]", r"\]")):
        sa.registered(p)
