"""tools/search_acceptance.py: a run's masks, sampling offsets and search settings
are held to the registered plan, in the manifest and on every game, and each
searched game's own account of its search has to add up.

Synthetic records here; test_search_seat.py runs the same check on real runs.
"""
import copy
import hashlib
import importlib.util
import json
import os

import pytest

from play_harness import search as S

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPEC = importlib.util.spec_from_file_location(
    "search_acceptance", os.path.join(ROOT, "tools", "search_acceptance.py"))
sa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sa)

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
    return {"players": players, "games_per_worker": 1,
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
    players = plan()["players"]
    home, away = pair if leg == "A_home" else pair[::-1]
    names = (home, away)
    settings = [players[n].get("search") for n in names]
    masks = [players[n].get("masks") or None for n in names]
    bots = [players[n].get("bot") for n in names]
    # The identity pair and its plain pair are the same game.
    key = ("I/P" if pair in (("I", "C"), ("P", "C")) else "/".join(pair), index, leg)
    digest = hashlib.sha256(repr(key).encode()).hexdigest()
    rec = {"pair": list(pair), "game_index": index, "leg": leg, "home": home, "away": away,
           "engine_seed": SEED0 + index, "natural": True, "truncated": False,
           "integrity": {"illegal": 0, "error_episodes": 0}, "c_steps": 1200,
           "forwards": [1200, 1200],
           "modes": ["scripted" if b else "sample" for b in bots],
           "temperatures": [None if b else 1.0 for b in bots], "bots": bots,
           "masks": masks,
           "mask_stats": [{m: {"held": 9, "applied": 3, "fallback": 0, "mass": 0.2} for m in ms}
                          if ms else None for ms in masks],
           "seed_offsets": [players[n].get("sampling_offset", 0) for n in names],
           "action_trail_sha256": digest, "final_digest": digest[:16],
           "logprob_sum": [-500.25, -480.5], "score": [1, 0], "team_ids": [3, 7],
           "sampling_seeds": [11, 12]}
    if any(settings):
        rec.update({"search": settings,
                    "search_stats": [stats(s) if s else None for s in settings],
                    "search_seconds": [300.0 if s else None for s in settings],
                    "reward_manifest_sha256": SHA, "integrity_checks": list(CHECKS),
                    "final_state_sha256": digest, "sampling_state_sha256": digest[::-1]})
    return rec


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


def test_a_run_without_search_needs_no_search_block(tmp_path):
    p = plan()
    p["players"] = {k: v for k, v in p["players"].items() if k in ("C", "chain37", "P")}
    del p["search"]
    m = manifest()
    m["players"] = {k: v for k, v in m["players"].items() if k in p["players"]}
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
    assert problems == ["identity: no game of the pair ('I', 'C')"]
    assert counts["identity_games"] == 0


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
