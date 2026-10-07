"""tools/search_ab.py: the whole-game offline A/B of the rollout search.

Three kinds of test:
  the plan      its schema, the hash that binds every command to it, the tasks
                of a shard;
  real games    a small shard played with a seeded random network: the identity
                arm equals the plain arm and the tournament's plain game, a
                search arm deviates, records do not depend on the process
                count, a killed run resumes without replaying a game;
  the report    acceptance and statistics on synthetic records.
"""
import copy
import hashlib
import json
import math
import os

import numpy as np
import pytest
import torch

from play_harness import engine as E
from play_harness import search as S
from play_harness import tournament as T
from play_harness.policy import random_policy
from tools import search_ab as AB

from .conftest import ROOT
from .test_reward_manifest import FIXTURE, FIXTURE_SHA256

POLICY = AB.TEST_POLICY + "11"
EXAMPLE = os.path.join(ROOT, "tools", "search_ab_plan.example.json")


def make_plan(**over):
    plan = {
        "schema": AB.PLAN_SCHEMA, "name": "test", "source_commit": T._git_head(),
        "code_sha256": AB.code_sha256(), "checkpoint_sha256": POLICY,
        "reward_manifest_sha256": FIXTURE_SHA256, "gamma": 0.999, "temperature": 1.0,
        "masks": {"a": ["m1"], "b": ["m1"]}, "sampling_offsets": {"a": 0, "b": 1},
        "max_decisions": 4096,
        "search": {"scope": ["turn", "after_declare"], "k": 2, "n": 2, "se_floor": AB.SE_FLOOR,
                   "candidates": AB.CANDIDATES, "max_rollout_steps": 200},
        "arms": [{"name": "plain", "delta": None}, {"name": "s0", "delta": 0.0}],
        "identity": {"arm": "identity", "seeds_per_shard": 1},
        "shards": [{"name": "t1", "seed_start": 31000, "seed_count": 1}],
        "cap_rejection_ceiling": 1.0,
        "bootstrap": {"reps": 200, "seed": 0, "quantiles": [2.5, 97.5]}}
    plan.update(over)
    return plan


def write_plan(folder, plan):
    path = os.path.join(str(folder), "plan.json")
    raw = json.dumps(plan, indent=1).encode()
    with open(path, "wb") as f:
        f.write(raw)
    return path, hashlib.sha256(raw).hexdigest()


def play(plan_path, sha, shard, out, processes=1):
    return AB.main(["play", "--plan", plan_path, "--expect-sha256", sha, "--shard", shard,
                    "--checkpoint", POLICY, "--manifest", FIXTURE, "--processes",
                    str(processes), "--out-dir", str(out)])


# ---- the plan -----------------------------------------------------------------------------
def test_the_example_plan_is_a_valid_plan():
    with open(EXAMPLE) as f:
        plan = AB.validate_plan(json.load(f))
    assert plan["search"]["n"] == 16 and plan["search"]["k"] == 4
    assert AB.plan_arms(plan) == {"plain": None, "s10": 0.1, "s02": 0.02, "identity": math.inf}
    assert AB.plain_arm(plan) == "plain"
    assert plan["reward_manifest_sha256"] == FIXTURE_SHA256


@pytest.mark.parametrize("mutate, needle", [
    (lambda p: p.pop("gamma"), "missing ['gamma']"),
    (lambda p: p.update(extra=1), "unknown ['extra']"),
    (lambda p: p.update(schema="other"), "schema"),
    (lambda p: p.update(source_commit="HEAD"), "source_commit"),
    (lambda p: p.update(gamma=1), "gamma"),
    (lambda p: p.update(temperature=0.5), "temperature"),
    (lambda p: p["masks"].pop("b"), "masks"),
    (lambda p: p["sampling_offsets"].update(b=-1), "offsets"),
    (lambda p: p["search"].update(scope=["turn", "kickoff"]), "scope"),
    (lambda p: p["search"].update(k=1), "search.k"),
    (lambda p: p["search"].update(se_floor="none"), "se_floor"),
    (lambda p: p["search"].update(candidates="top k"), "candidates"),
    (lambda p: p["arms"].append({"name": "plain2", "delta": None}), "exactly one arm"),
    (lambda p: p["arms"].append({"name": "s0", "delta": 0.5}), "names must differ"),
    (lambda p: p["arms"].append({"name": "identity", "delta": 0.5}), "names must differ"),
    (lambda p: p["arms"][1].update(delta=float("inf")), "finite"),
    (lambda p: p["arms"][1].update(delta=-0.1), "finite"),
    (lambda p: p["identity"].update(seeds_per_shard=2), "identity sample"),
    (lambda p: p["shards"].append({"name": "t2", "seed_start": 31000, "seed_count": 3}),
     "repeats a seed"),
    (lambda p: p["shards"].append({"name": "t1", "seed_start": 5, "seed_count": 1}),
     "shard names"),
    (lambda p: p.update(cap_rejection_ceiling=2.0), "ceiling"),
    (lambda p: p["bootstrap"].update(quantiles=[5, 95]), "bootstrap"),
])
def test_a_plan_that_is_not_complete_and_consistent_is_refused(mutate, needle):
    plan = make_plan()
    AB.validate_plan(copy.deepcopy(plan))
    mutate(plan)
    with pytest.raises(ValueError, match="plan: .*" + needle.replace("[", r"\[")
                       .replace("]", r"\]")):
        AB.validate_plan(plan)


def test_every_command_refuses_a_plan_that_does_not_hash_to_the_expected_value(tmp_path):
    path, sha = write_plan(tmp_path, make_plan())
    assert AB.load_plan(path, sha)[1] == sha
    assert AB.load_plan(path, sha.upper() + "\n")[1] == sha
    wrong = "0" * 64
    with pytest.raises(SystemExit, match="not the expected"):
        AB.load_plan(path, wrong)
    with pytest.raises(SystemExit, match="not the expected"):
        play(path, wrong, "t1", tmp_path / "out")
    assert not (tmp_path / "out").exists()                 # refused before anything is made
    with pytest.raises(SystemExit, match="not the expected"):
        AB.main(["report", "--plan", path, "--expect-sha256", wrong, str(tmp_path)])
    # One byte of the plan changed: the old hash no longer opens it.
    with open(path, "ab") as f:
        f.write(b"\n")
    with pytest.raises(SystemExit, match="not the expected"):
        AB.load_plan(path, sha)


def test_a_plan_binds_the_checkpoint_the_manifest_and_the_code(tmp_path):
    for field, value in (("checkpoint_sha256", AB.TEST_POLICY + "12"),
                         ("reward_manifest_sha256", "1" * 64), ("code_sha256", "2" * 64),
                         ("source_commit", "3" * 40)):
        path, sha = write_plan(tmp_path, make_plan(**{field: value}))
        with pytest.raises(SystemExit, match=field):
            play(path, sha, "t1", tmp_path / field)
        assert not os.path.exists(tmp_path / field / "games.jsonl")
    path, sha = write_plan(tmp_path, make_plan())
    with pytest.raises(SystemExit, match="no shard"):
        play(path, sha, "nope", tmp_path / "x")


def test_a_shard_plays_every_arm_seed_by_seed_with_the_identity_sample_first():
    plan = make_plan(
        arms=[{"name": "plain", "delta": None}, {"name": "s10", "delta": 0.1},
              {"name": "s02", "delta": 0.02}],
        identity={"arm": "identity", "seeds_per_shard": 2},
        shards=[{"name": "t1", "seed_start": 100, "seed_count": 3},
                {"name": "t2", "seed_start": 500, "seed_count": 2}])
    AB.validate_plan(plan)
    tasks = AB.shard_tasks(plan, "t1")
    assert tasks[:8] == [(100, "A_home", "plain"), (100, "A_home", "s10"), (100, "A_home", "s02"),
                         (100, "A_home", "identity"), (100, "B_home", "plain"),
                         (100, "B_home", "s10"), (100, "B_home", "s02"),
                         (100, "B_home", "identity")]
    assert len(tasks) == 3 * 2 * 3 + 2 * 2                  # identity on the first two seeds
    assert [t for t in tasks if t[0] == 102] == [(102, leg, arm) for leg in AB.LEGS
                                                 for arm in ("plain", "s10", "s02")]
    # Any prefix of the order covers the arms alike, give or take one game.
    for cut in range(1, len(tasks)):
        counts = [sum(t[2] == arm for t in tasks[:cut]) for arm in ("plain", "s10", "s02")]
        assert max(counts) - min(counts) <= 1
    everything = AB.plan_tasks(plan)
    assert len(everything) == len(set(everything)) == len(tasks) + 2 * 2 * 3 + 2 * 2
    assert AB.shard_of(plan, 501) == "t2" and AB.shard_of(plan, 103) is None
    settings = AB.game_settings(plan, "identity")
    assert settings["search"]["delta"] == "inf" and settings["search"]["n"] == 2
    assert AB.game_settings(plan, "plain")["search"] is None
    assert AB.game_settings(plan, "s10")["search"]["delta"] == 0.1


# ---- the decision -------------------------------------------------------------------------
def test_candidates_are_a0_then_the_rest_by_probability_with_ties_in_packed_order():
    A = E.A
    support = np.asarray([E.pack_tuple(A["ACTIVATE"], arg, E.SQ_NONE) for arg in (7, 3, 5, 9, 1)],
                         dtype=np.uint32)
    logits = torch.zeros(sum(E.ACT_SIZES))
    logits[E.ACT_SIZES[0] + 9] = 2.0                         # player 9 is the favourite
    logits[E.ACT_SIZES[0] + 5] = 1.0
    tuples, probs = S.joint_probabilities(logits, support)
    assert [E.unpack_tuple(t)[1] for t in tuples] == [9, 5, 1, 3, 7]   # ties: packed order
    a0 = E.pack_tuple(A["ACTIVATE"], 3, E.SQ_NONE)           # plain play sampled a tied one
    order = AB.candidate_order(tuples, a0, 4)
    assert [E.unpack_tuple(tuples[i])[1] for i in order] == [3, 9, 5, 1]
    # a0 is the favourite: it is not listed twice.
    order = AB.candidate_order(tuples, E.pack_tuple(A["ACTIVATE"], 9, E.SQ_NONE), 4)
    assert [E.unpack_tuple(tuples[i])[1] for i in order] == [9, 5, 1, 3]
    # Fewer legal actions than k: all of them, a0 first.
    two, _ = S.joint_probabilities(logits, support[:2])
    order = AB.candidate_order(two, E.pack_tuple(A["ACTIVATE"], 7, E.SQ_NONE), 4)
    assert [E.unpack_tuple(two[i])[1] for i in order] == [7, 3]


def test_the_deviation_rule_and_its_floor():
    rng = np.random.default_rng(0)
    base = rng.normal(1.0, 0.1, 16)
    returns = np.stack([base, base + 0.15, base + 0.05, base - 0.2])
    deviate, best, gain, se = AB.decide(returns, 0.10)
    assert (deviate, best) == (True, 1) and gain == pytest.approx(0.15)
    # The difference is constant, so the standard error is the floor exactly:
    # sqrt(mean over candidates of per-rollout return variance / n).
    assert se == pytest.approx(math.sqrt(returns.var(axis=1, ddof=1).mean() / 16))
    assert AB.decide(returns, 0.15)[0] is False             # must EXCEED delta
    assert AB.decide(returns, 0.02)[0] is True
    assert AB.decide(returns, math.inf)[0] is False         # the identity arm never deviates
    # Above delta but not above two standard errors: a0.
    noisy = np.stack([base, base + rng.normal(0.3, 1.0, 16)])
    d, _, gain, se = AB.decide(noisy, 0.10)
    assert gain > 0.10 and gain <= 2 * se and d is False
    # With the floor a small-sample constant difference between noisy candidates
    # is not a certainty.
    wide = rng.normal(1.0, 0.5, 16)
    assert AB.decide(np.stack([wide, wide + 0.12]), 0.10) == (False, 1, pytest.approx(0.12),
                                                              pytest.approx(wide.std(ddof=1) / 4))


def test_the_clip_threshold_is_the_headers(lib):
    rewards = E.load_reward_manifest(FIXTURE, lib)["rewards"]
    assert AB.reward_clip_threshold(rewards) == pytest.approx(1.0)       # max(1.0, 25 * 0.04)
    exact = dict(rewards, reward_dist_pbrs_gamma=0.999)
    assert AB.reward_clip_threshold(exact) == pytest.approx(1.0 + 0.5 + 1.0)
    header = open(os.path.join(ROOT, "puffer", "bloodbowl", "bloodbowl.h")).read()
    body = header.split("static float bbe_reward_clip_threshold(const Bloodbowl* env) {")[1]
    body = body.split("\n}\n")[0]
    for piece in ("fabsf(env->reward_td) + (win > draw ? win : draw)",
                  "BBE_POT_DMAX * fabsf(env->reward_dist_ball)",
                  "return objective + fetch + carry", "objective > distance ? objective"):
        assert piece in body


# ---- real games -----------------------------------------------------------------------------
@pytest.fixture(scope="module")
def shard(tmp_path_factory):
    """One seed, both orientations: plain, a search arm that deviates on any
    gain, and the identity arm. n = 2 and k = 2 keep it to seconds."""
    folder = tmp_path_factory.mktemp("ab")
    path, sha = write_plan(folder, make_plan())
    assert play(path, sha, "t1", folder / "out") == 0
    records = AB.load_records(str(folder / "out" / "games.jsonl"))
    return {"plan": path, "sha": sha, "out": str(folder / "out"),
            "records": {AB.record_key(r): r for r in records}}


def test_a_shard_leaves_one_record_per_planned_game(shard):
    plan = make_plan()
    assert sorted(shard["records"]) == sorted(AB.shard_tasks(plan, "t1"))
    for key, r in shard["records"].items():
        assert r["natural"] and not r["decision_cap"] and r["invalid"] == []
        assert not any(r["integrity"].values())
        assert r["settings"] == AB.game_settings(plan, key[2])
        assert r["hashes"] == {"plan_sha256": shard["sha"], "checkpoint_sha256": POLICY,
                               "reward_manifest_sha256": FIXTURE_SHA256,
                               "source_commit": T._git_head(),
                               "code_sha256": AB.code_sha256()}
        run = r["runtime"]
        assert run["library_sha256"] == T.library_sha256() and len(run["library_sha256"]) == 64
        assert (run["abi"], run["obs_version"], run["obs_size"]) == (E.ABI_VERSION, 6, E.OBS_SIZE)
        assert run["precision"] == "torch.float32" and run["torch_threads"] == 1
        assert run["torch"] == torch.__version__ and run["numpy"] == np.__version__
        assert run["processes"] == 1 and run["hostname"]
        assert r["result_a"] == ("W" if r["a_td"] > r["b_td"] else
                                 "D" if r["a_td"] == r["b_td"] else "L")
        assert len(r["final_state_sha256"]) == len(r["sampling_state_sha256"]) == 64
        assert set(r["in_scope"]) == {"turn", "after_declare"}
        assert all(r["searched"][c] <= r["in_scope"][c] for c in r["searched"])
    with open(os.path.join(shard["out"], "COMPLETE.json")) as f:
        assert json.load(f)["games"] == 6


def test_the_identity_arm_is_the_plain_game_with_the_search_run_and_discarded(shard):
    for leg in AB.LEGS:
        plain = shard["records"][(31000, leg, "plain")]
        identity = shard["records"][(31000, leg, "identity")]
        for name in AB.IDENTITY_FIELDS + ("result_a", "a_td", "b_td", "c_steps", "in_scope",
                                          "searched", "sampling_seeds", "team_ids"):
            assert identity[name] == plain[name], (leg, name)
        searched = sum(identity["searched"].values())
        assert searched > 50
        # Every searched decision ran its rollouts: two to four per decision here.
        assert 2 * searched <= identity["rollouts"] <= 4 * searched
        assert identity["rollout_steps"] > identity["rollouts"]
        assert identity["deviations"] == {"turn": 0, "after_declare": 0}
        assert plain["rollouts"] == plain["rollout_steps"] == 0
        assert sum(plain["searched"].values()) == searched   # counted, not run


def test_the_plain_arm_is_the_tournaments_plain_game(shard):
    """The existing plain path: tournament.play_match under m1 on both seats, the
    second seat on sampling offset 1. Its session pays no reward manifest; T12
    holds that this cannot change the game."""
    policy = random_policy(seed=11, scale=0.05)
    for leg, offsets in (("A_home", (0, 1)), ("B_home", (1, 0))):
        record, _ = T.play_match(policy, policy, 31000, masks=(("m1",), ("m1",)),
                                 seed_offsets=offsets)
        ours = shard["records"][(31000, leg, "plain")]
        assert ours["action_trail_sha256"] == record["action_trail_sha256"]
        assert ours["c_steps"] == record["c_steps"]
        assert ours["sampling_seeds"] == record["sampling_seeds"]
        a = AB.LEGS.index(leg)
        assert [ours["a_td"], ours["b_td"]] == [record["score"][a], record["score"][1 - a]]


def test_a_search_arm_deviates_and_then_plays_another_game(shard):
    for leg in AB.LEGS:
        plain = shard["records"][(31000, leg, "plain")]
        searched = shard["records"][(31000, leg, "s0")]
        total = sum(searched["deviations"].values())
        assert total > 0 and total == len(searched["predicted_gains"])
        assert total == sum(searched["deviation_types"].values())
        assert all(g > 0.0 for g in searched["predicted_gains"])   # delta 0: any gain
        assert all(key.split(": ")[0] in ("turn", "after_declare") and " -> " in key
                   for key in searched["deviation_types"])
        assert searched["action_trail_sha256"] != plain["action_trail_sha256"]
        assert searched["sampling_seeds"] == plain["sampling_seeds"]
        assert searched["team_ids"] == plain["team_ids"]     # same seed, same rosters
        assert searched["cutoff_rollouts"] >= 0 and searched["error_rollouts"] == 0


def test_the_report_passes_this_shard_and_refuses_it_without_the_test_switch(shard, tmp_path,
                                                                             capsys):
    out = tmp_path / "report"
    base = ["report", "--plan", shard["plan"], "--expect-sha256", shard["sha"], shard["out"]]
    assert AB.main(base + ["--allow-test-policy", "--out-dir", str(out)]) == 0
    text = capsys.readouterr().out
    assert "ACCEPTANCE: PASS" in text and "decisive Elo" in text and "identity: 2 game(s)" in text
    sums = dict(line.split("  ")[::-1] for line in open(out / "SHA256SUMS").read().splitlines())
    assert set(sums) == {"t1/games.jsonl", "report.txt", "report.json", "plan.json"}
    assert sums["plan.json"] == shard["sha"]
    assert sums["report.txt"] == hashlib.sha256((out / "report.txt").read_bytes()).hexdigest()
    with open(os.path.join(shard["out"], "games.jsonl"), "rb") as f:
        assert sums["t1/games.jsonl"] == hashlib.sha256(f.read()).hexdigest()
    # A test policy is not a checkpoint: no statistic is printed for it.
    assert AB.main(base) == 2
    text = capsys.readouterr().out
    assert text.startswith("ACCEPTANCE: FAIL") and "test policy" in text
    assert "win score" not in text and "Elo" not in text


@pytest.fixture(scope="module")
def capped(tmp_path_factory):
    """Two seeds cut at 150 decisions: quick games for the process and resume tests."""
    folder = tmp_path_factory.mktemp("capped")
    plan = make_plan(max_decisions=150,
                     shards=[{"name": "t1", "seed_start": 32000, "seed_count": 2}])
    path, sha = write_plan(folder, plan)
    assert play(path, sha, "t1", folder / "p1") == 0
    return {"plan": path, "sha": sha, "folder": folder, "tasks": AB.shard_tasks(plan, "t1")}


def _essential(record):
    out = {k: v for k, v in record.items() if k != "seconds"}
    out["runtime"] = {k: v for k, v in record["runtime"].items() if k != "processes"}
    return out


def test_records_do_not_depend_on_the_number_of_processes(capped):
    assert play(capped["plan"], capped["sha"], "t1", capped["folder"] / "p2", processes=2) == 0
    one = AB.load_records(str(capped["folder"] / "p1" / "games.jsonl"))
    two = AB.load_records(str(capped["folder"] / "p2" / "games.jsonl"))
    assert [AB.record_key(r) for r in one] == capped["tasks"]        # the planned order
    assert sorted(map(AB.record_key, two)) == sorted(capped["tasks"])
    by_key = {AB.record_key(r): r for r in two}
    for record in one:
        assert _essential(by_key[AB.record_key(record)]) == _essential(record)
    assert {r["runtime"]["processes"] for r in two} == {2}
    assert {r["runtime"]["torch_threads"] for r in two} == {1}


def test_a_game_that_ends_on_the_decision_cap_is_recorded_and_refused(capped, capsys):
    records = AB.load_records(str(capped["folder"] / "p1" / "games.jsonl"))
    assert all(r["decision_cap"] and not r["natural"] and r["invalid"] == [] for r in records)
    assert all(r["c_steps"] == 150 for r in records)
    # Rollouts near the cap end on it: counted as cap rejections, never as errors.
    searched = [r for r in records if r["arm"] != "plain"]
    assert sum(r["cap_rejected_rollouts"] for r in searched) > 0
    assert all(r["cap_rejected_decisions"] <= sum(r["searched"].values()) for r in searched)
    assert all(r["error_rollouts"] == 0 for r in searched)
    assert AB.main(["report", "--plan", capped["plan"], "--expect-sha256", capped["sha"],
                    "--allow-test-policy", str(capped["folder"] / "p1")]) == 2
    text = capsys.readouterr().out
    assert "did not end naturally (decision cap)" in text and "win score" not in text


def test_a_killed_run_resumes_with_only_the_missing_games(capped, tmp_path, capsys):
    source = capped["folder"] / "p1" / "games.jsonl"
    lines = source.read_text().splitlines(keepends=True)
    out = tmp_path / "resumed"
    out.mkdir()
    (out / "run.json").write_text((capped["folder"] / "p1" / "run.json").read_text())
    kept = lines[:3] + lines[5:7]                       # a gap, and the tail missing
    (out / "games.jsonl").write_text("".join(kept) + lines[7][:200])     # killed mid-write
    assert play(capped["plan"], capped["sha"], "t1", out) == 0
    text = capsys.readouterr().out
    assert f"{len(lines)} games, 5 already played, {len(lines) - 5} to play" in text
    after = (out / "games.jsonl").read_text().splitlines(keepends=True)
    assert after[:5] == kept                            # finished records are not rewritten
    assert len(after) == len(lines)
    again = {AB.record_key(json.loads(line)): json.loads(line) for line in after}
    for line in lines:
        record = json.loads(line)
        assert _essential(again[AB.record_key(record)]) == _essential(record)
    # A complete directory plays nothing more.
    assert play(capped["plan"], capped["sha"], "t1", out) == 0
    assert "0 to play" in capsys.readouterr().out
    assert (out / "games.jsonl").read_text().splitlines(keepends=True) == after
    # Another plan cannot take the directory over.
    other, other_sha = write_plan(tmp_path, make_plan(max_decisions=151, shards=[
        {"name": "t1", "seed_start": 32000, "seed_count": 2}]))
    with pytest.raises(SystemExit, match="another plan or shard"):
        play(other, other_sha, "t1", out)
    # A broken line in the middle is not a kill: refuse.
    (out / "games.jsonl").write_text(after[0] + "{broken\n" + after[1])
    with pytest.raises(ValueError, match="line 2"):
        AB.load_records(str(out / "games.jsonl"))


# ---- the report on synthetic records ---------------------------------------------------------
def synthetic_plan(seeds=40, **over):
    plan = make_plan(
        checkpoint_sha256="a" * 64,
        arms=[{"name": "plain", "delta": None}, {"name": "s10", "delta": 0.1}],
        identity={"arm": "identity", "seeds_per_shard": 2},
        shards=[{"name": "t1", "seed_start": 1000, "seed_count": seeds // 2},
                {"name": "t2", "seed_start": 5000, "seed_count": seeds // 2}],
        cap_rejection_ceiling=0.01, **over)
    return AB.validate_plan(plan), "f" * 64


def fake(plan, sha, key, result="D", a_td=1, b_td=1, **over):
    seed, leg, arm = key
    shard = AB.shard_of(plan, seed)
    search = AB.plan_arms(plan)[arm] is not None
    digest = hashlib.sha256(f"{seed}{leg}{arm if arm == 's10' else ''}".encode()).hexdigest()
    record = {
        "schema": AB.SCHEMA, "shard": shard, "engine_seed": seed, "leg": leg, "arm": arm,
        "settings": AB.game_settings(plan, arm), "result_a": result, "a_td": a_td, "b_td": b_td,
        "c_steps": 1200, "natural": True, "decision_cap": False, "invalid": [],
        "integrity": {k: 0 for k in T.HARD_COUNTERS}, "team_ids": [1, 2],
        "sampling_seeds": [1, 2], "in_scope": {"turn": 100, "after_declare": 100},
        "searched": {"turn": 90, "after_declare": 100},
        "deviations": {"turn": 2 if arm == "s10" else 0, "after_declare": 1 if arm == "s10" else 0},
        "deviation_types": {"turn: ACTIVATE -> ACTIVATE": 2, "after_declare: STEP -> STEP": 1}
        if arm == "s10" else {},
        "predicted_gains": [0.2, 0.15, 0.3] if arm == "s10" else [],
        "rollouts": 12000 if search else 0, "rollout_steps": 300000 if search else 0,
        "cap_rejected_rollouts": 0, "cap_rejected_decisions": 0, "cutoff_rollouts": 0,
        "error_rollouts": 0, "seconds": 60.0 if search else 1.0,
        "action_trail_sha256": digest, "final_state_sha256": digest,
        "sampling_state_sha256": digest,
        "hashes": {"plan_sha256": sha, "checkpoint_sha256": plan["checkpoint_sha256"],
                   "reward_manifest_sha256": plan["reward_manifest_sha256"],
                   "source_commit": plan["source_commit"], "code_sha256": plan["code_sha256"]},
        "runtime": {"library_sha256": "c" * 64, "abi": 5, "obs_version": 6, "obs_size": 2782,
                    "torch": "2.14.0", "numpy": "2.5.3", "python": "3.12.3",
                    "precision": "torch.float32", "torch_threads": 1, "processes": 8,
                    "hostname": "host-" + shard, "machine": "x86_64", "kernel": "6.8"}}
    record.update(over)
    return record


def synthetic_records(plan, sha, lift=0.0, seed=0):
    """Plain is a coin flip; the search arm repeats plain's result except that a
    share `lift` of plain's losses become wins."""
    rng = np.random.default_rng(seed)
    records, plain = [], {}
    for key in AB.plan_tasks(plan):
        s, leg, arm = key
        if arm in ("plain", "identity"):
            if (s, leg) not in plain:
                plain[(s, leg)] = rng.choice(["W", "D", "L"], p=[0.4, 0.2, 0.4])
            result = plain[(s, leg)]
        else:
            result = plain[(s, leg)]
            if result == "L" and rng.random() < lift:
                result = "W"
        td = {"W": (2, 1), "D": (1, 1), "L": (1, 2)}[result]
        records.append(fake(plan, sha, key, result, *td))
    return records


def test_an_accepted_run_has_no_problems_and_the_statistics_recover_what_was_planted():
    plan, sha = synthetic_plan(seeds=200)
    records = synthetic_records(plan, sha, lift=0.5)
    assert AB.accept(plan, sha, records) == []
    summary = AB.summarize(plan, records)
    base, arm, contrast = summary["arms"]["plain"], summary["arms"]["s10"], \
        summary["contrasts"]["s10"]
    assert base["games"] == arm["games"] == 400 and summary["seeds"] == 200
    assert base["W"] + base["D"] + base["L"] == 400
    assert base["win_score"][0] == pytest.approx((base["W"] + 0.5 * base["D"]) / 400)
    for stat in (base["win_score"], base["td_diff"], base["elo_decisive"]):
        assert stat[1] < stat[0] < stat[2]                  # an interval around the point
    assert base["win_score"][2] - base["win_score"][1] < 0.12
    assert abs(base["win_score"][0] - 0.5) < 0.06 and abs(base["td_diff"][0]) < 0.12
    assert base["decisive_share"][0] == pytest.approx(base["W"] / (base["W"] + base["L"]))
    assert base["elo_decisive"][0] == pytest.approx(
        400 / math.log(10) * math.log(base["W"] / base["L"]))
    # Half of 40% losses became wins: +0.2 win score, +0.4 TD difference, paired.
    assert contrast["pairs"] == 400
    assert contrast["win_score"][0] == pytest.approx(0.2, abs=0.04)
    assert contrast["td_diff"][0] == pytest.approx(0.4, abs=0.08)
    assert contrast["win_score"][1] > 0.1 and contrast["elo_decisive"][1] > 0
    assert contrast["win_score"][0] == pytest.approx(arm["win_score"][0] - base["win_score"][0])
    assert contrast["elo_decisive"][0] == pytest.approx(
        arm["elo_decisive"][0] - base["elo_decisive"][0])
    # Arms are resampled together: the paired interval is far narrower than the
    # two arms' own intervals would give if they were resampled apart.
    paired = contrast["win_score"][2] - contrast["win_score"][1]
    apart = math.hypot(arm["win_score"][2] - arm["win_score"][1],
                       base["win_score"][2] - base["win_score"][1])
    assert paired < 0.75 * apart
    assert arm["deviations_per_game"] == {"turn": 2.0, "after_declare": 1.0}
    assert arm["mean_predicted_gain"] == pytest.approx(0.65 / 3)
    assert arm["slowdown"] == pytest.approx(60.0) and base["slowdown"] == 1.0
    assert base["mean_predicted_gain"] is None
    assert summary["identity"]["games"] == 8 and summary["identity"]["shards"] == ["t1", "t2"]
    assert summary["hosts"] == {"t1": ["host-t1"], "t2": ["host-t2"]}
    text = AB.format_report(plan, sha, summary)
    for needle in ("ACCEPTANCE: PASS", "percentile bootstrap at 2.5 and 97.5",
                   "200 replicates, generator seed 0", "Each search arm minus the plain arm",
                   "identity: 8 game(s)", "replicates left out"):
        assert needle in text


def test_identical_arms_have_a_contrast_of_exactly_zero():
    plan, sha = synthetic_plan(seeds=40)
    records = synthetic_records(plan, sha, lift=0.0)
    contrast = AB.summarize(plan, records)["contrasts"]["s10"]
    assert contrast["win_score"] == [0.0, 0.0, 0.0]         # zero in every replicate
    assert contrast["elo_decisive"] == [0.0, 0.0, 0.0]
    assert contrast["same_result"] == 1.0 and contrast["same_game"] == 0.0


def test_a_replicate_without_a_decisive_game_is_left_out_and_counted():
    plan, sha = synthetic_plan(seeds=4)
    records = [fake(plan, sha, key, "D") for key in AB.plan_tasks(plan)]
    # One decisive plain game: most replicates of 4 seeds have none... some do.
    for r in records:
        if r["arm"] == "plain" and r["engine_seed"] == 1000 and r["leg"] == "A_home":
            r.update(result_a="W", a_td=2)
    assert AB.accept(plan, sha, records) == []
    summary = AB.summarize(plan, records)
    plain, arm = summary["arms"]["plain"], summary["arms"]["s10"]
    assert 0 < plain["replicates_without_a_decisive_game"] < 200
    assert arm["replicates_without_a_decisive_game"] == 200
    assert math.isnan(arm["decisive_share"][0]) and math.isnan(arm["elo_decisive"][1])
    assert plain["decisive_share"][0] == 1.0                # the point: one win, no loss
    assert arm["win_score"] == [0.5, 0.5, 0.5]
    assert "s10 200" in AB.format_report(plan, sha, summary)


def _drop(records, key):
    return [r for r in records if AB.record_key(r) != key]


def _edit(records, key, **fields):
    out = copy.deepcopy(records)
    for r in out:
        if AB.record_key(r) == key:
            for name, value in fields.items():
                if isinstance(value, dict) and isinstance(r.get(name), dict):
                    r[name].update(value)
                else:
                    r[name] = value
    return out


KEY = (1005, "B_home", "s10")
IDENT = (1000, "A_home", "identity")


@pytest.mark.parametrize("change, needle", [
    (lambda rs, p, s: _drop(rs, KEY), "1 planned game(s) missing"),
    (lambda rs, p, s: rs + [copy.deepcopy(rs[0])], "present more than once"),
    (lambda rs, p, s: rs + [fake(p, s, (1005, "B_home", "identity"))], "the plan does not hold"),
    (lambda rs, p, s: _edit(rs, KEY, invalid=["step 5: a reward is not finite"]),
     "arm s10 is UNREAD: 1 invalid game(s)"),
    (lambda rs, p, s: _edit(rs, KEY, natural=False, decision_cap=True),
     "did not end naturally (decision cap)"),
    (lambda rs, p, s: [dict(r, cap_rejected_decisions=3) if r["arm"] == "s10" else r
                       for r in rs], "above the ceiling 0.01"),
    (lambda rs, p, s: _edit(rs, KEY, hashes={"checkpoint_sha256": "b" * 64}),
     "checkpoint_sha256 is"),
    (lambda rs, p, s: _edit(rs, KEY, hashes={"code_sha256": "b" * 64}), "code_sha256 is"),
    (lambda rs, p, s: _edit(rs, KEY, hashes={"plan_sha256": "b" * 64}), "plan_sha256 is"),
    (lambda rs, p, s: _edit(rs, KEY, hashes={"source_commit": "b" * 40}), "source_commit is"),
    (lambda rs, p, s: _edit(rs, KEY, settings={"gamma": 0.995}), "settings are not the plan's"),
    (lambda rs, p, s: _edit(rs, KEY, settings={"masks": {"a": ["m1"], "b": []}}),
     "settings are not the plan's"),
    (lambda rs, p, s: _edit(rs, KEY, shard="t2"), "played by shard t2"),
    (lambda rs, p, s: _edit(rs, KEY, runtime={"library_sha256": "d" * 64}),
     "shard t1: library_sha256 differs"),
    (lambda rs, p, s: _edit(rs, KEY, runtime={"torch": "2.13.0"}), "shard t1: torch differs"),
    (lambda rs, p, s: _edit(rs, KEY, runtime={"abi": 4}), "shard t1: abi differs"),
    (lambda rs, p, s: [dict(r, runtime=dict(r["runtime"], torch_threads=2))
                       if r["shard"] == "t2" else r for r in rs], "more than one torch thread"),
    (lambda rs, p, s: _edit(rs, IDENT, action_trail_sha256="e" * 64),
     "identity failed: 1 of 8"),
    (lambda rs, p, s: _edit(rs, IDENT, final_state_sha256="e" * 64), "identity failed"),
    (lambda rs, p, s: _edit(rs, IDENT, sampling_state_sha256="e" * 64), "identity failed"),
    (lambda rs, p, s: _edit(rs, IDENT, rollouts=0), "ran no search"),
    (lambda rs, p, s: _edit(rs, KEY, schema="other"), "not a search-ab-game-v1 record"),
])
def test_acceptance_names_each_way_a_run_can_fail(change, needle):
    plan, sha = synthetic_plan(seeds=40)
    records = synthetic_records(plan, sha)
    assert AB.accept(plan, sha, records) == []
    problems = AB.accept(plan, sha, change(records, plan, sha))
    assert any(needle in p for p in problems), problems


def test_acceptance_allows_a_cap_rejection_share_at_the_ceiling_and_another_host_per_shard():
    plan, sha = synthetic_plan(seeds=40)
    records = synthetic_records(plan, sha)
    searched = sum(sum(r["searched"].values()) for r in records if r["arm"] == "s10")
    spread = int(searched * 0.01)                             # exactly the ceiling
    first = next(r for r in records if r["arm"] == "s10")
    first["cap_rejected_decisions"] = spread
    first["cap_rejected_rollouts"] = spread * 3
    # A relaunched shard runs on another droplet: the hostname may differ.
    records[-1]["runtime"]["hostname"] = "host-t2-relaunched"
    assert AB.accept(plan, sha, records) == []
    summary = AB.summarize(plan, records)
    assert summary["arms"]["s10"]["cap_rejection_share"] == pytest.approx(0.01, abs=1e-4)
    assert summary["hosts"]["t2"] == ["host-t2", "host-t2-relaunched"]
    plan_test, _ = synthetic_plan(seeds=40)
    plan_test["checkpoint_sha256"] = POLICY
    with_test = [dict(r, hashes=dict(r["hashes"], checkpoint_sha256=POLICY))
                 for r in synthetic_records(plan_test, sha)]
    assert any("test policy" in p for p in AB.accept(plan_test, sha, with_test))
    assert AB.accept(plan_test, sha, with_test, allow_test_policy=True) == []


def test_report_prints_no_statistic_for_a_run_it_does_not_accept(tmp_path, capsys):
    plan, _ = synthetic_plan(seeds=40)
    path, sha = write_plan(tmp_path, plan)
    for name in ("t1", "t2"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "run.json").write_text(json.dumps({"plan_sha256": sha, "shard": name}))
        records = [r for r in synthetic_records(plan, sha, lift=0.5) if r["shard"] == name]
        if name == "t2":
            records = records[:-1]                             # one game short
        (folder / "games.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    args = ["report", "--plan", path, "--expect-sha256", sha, str(tmp_path / "t1"),
            str(tmp_path / "t2"), "--out-dir", str(tmp_path / "out")]
    assert AB.main(args) == 2
    text = capsys.readouterr().out
    assert text.startswith("ACCEPTANCE: FAIL") and "1 planned game(s) missing" in text
    for word in ("win score", "Elo", "TD difference", "W/D/L"):
        assert word not in text
    assert os.listdir(tmp_path / "out") == ["acceptance_failed.txt"]
    # The same shard given twice is not two shards.
    assert AB.main(["report", "--plan", path, "--expect-sha256", sha, str(tmp_path / "t1"),
                    str(tmp_path / "t1")]) == 2
    assert "same shard" in capsys.readouterr().out
    # A directory played under another plan is not read at all.
    (tmp_path / "t2" / "run.json").write_text(json.dumps({"plan_sha256": "0" * 64,
                                                          "shard": "t2"}))
    with pytest.raises(SystemExit, match="played under plan"):
        AB.main(args)
