"""Feedback records: flags, decision views, survey answers, flagged step replay."""
import ctypes
import json
import math
import os
import random

import numpy as np
import pytest
import torch

from play_harness import engine as E
from play_harness import game as G
from play_harness.alternatives import conditional_argmax_row
from play_harness.session import FLAG_SCHEMA, SCHEMA, match_json

torch.set_num_threads(2)

ZERO_KEYS = ("illegal", "projection_collision", "error_episodes", "engine_rejections",
             "precheck_collisions", "api_rejections")


def _loader(best_policy):
    def load(path, kernel="native"):
        return best_policy
    return load


def _controller(best_policy, games_dir, **raw):
    raw.setdefault("clock_mode", "off")
    opts = G.normalize_options(raw)
    return G.GameController(opts, policy_loader=_loader(best_policy), games_dir=str(games_dir))


def _play(gc, rng, until=None, stop=None):
    s = gc.session
    while not s.over and (until is None or s.version < until) and not (stop and stop(s)):
        legal = s.legal()
        ids = [a["id"] for a in legal["actions"]]
        ids += [row[0] for row in (legal.get("compact") or {}).get("SETUP_PLACE", [])]
        res = gc.submit({"action_id": rng.choice(ids), "state_version": legal["state_version"]})
        assert res["ok"], res
    return s


def _load(gc):
    with open(os.path.join(gc.record_dir, "game.json")) as f:
        return json.load(f)


def _roundtrip(value):
    return json.loads(json.dumps(value))


def _is_joined_declare(trace, step):
    return trace[step]["action_type"] == "DECLARE" and step > 0 and \
        trace[step - 1]["actor"] == "policy" and trace[step - 1]["action_type"] == "ACTIVATE"


def _activate_with_declare(trace, step):
    return trace[step]["action_type"] == "ACTIVATE" and step + 1 < len(trace) and \
        trace[step + 1]["actor"] == "policy" and trace[step + 1]["action_type"] == "DECLARE"


# ---- flags ----------------------------------------------------------------
def test_flag_on_a_policy_step_is_recorded_and_reloads(best_policy, tmp_path):
    gc = _controller(best_policy, tmp_path, seed=17)
    rng = random.Random(17)
    s = _play(gc, rng, until=200)
    assert not s.over
    assert not os.path.exists(gc.record_dir), "nothing is written before a flag or the end"
    policy_steps = [r["step"] for r in s.trace if r["actor"] == "policy"]
    step = policy_steps[len(policy_steps) // 2]
    note = "Why did it block with that player"
    res = gc.flag({"step": step, "reasons": ["Too risky", 5, None, "Wrong player"], "note": note})
    assert res["ok"] is True and res["flag_index"] == 0 and res["step"] == step
    summaries = res["flags"]
    assert len(summaries) == 1
    summary = summaries[0]
    assert (summary["index"], summary["step"], summary["note"]) == (0, step, note)
    assert summary["reasons"] == ["Too risky", "Wrong player"]
    assert isinstance(summary["label"], str) and summary["label"]
    assert summary["p"] is not None and 0.0 <= summary["p"] <= 1.0
    assert summary["half"] in (1, 2)

    doc = _load(gc)
    assert doc["header"]["schema"] == SCHEMA
    assert doc["result"] is None
    assert len(doc["flags"]) == 1
    entry = doc["flags"][0]
    assert entry["schema"] == FLAG_SCHEMA == "bbplay-flag-v1"
    assert entry["step"] == step and entry["note"] == note
    assert entry["reasons"] == ["Too risky", "Wrong player"]
    assert entry["record"] == _roundtrip(s.trace[step])
    assert entry["has_logits"] is True
    pre = bytes.fromhex(entry["pre_state_hex"])
    assert len(pre) == ctypes.sizeof(E.BbMatch)
    assert pre == s._pre_states[step]
    view = entry["view"]
    assert view["step"] in (step, step + 1)
    alts = view["alternatives"]
    assert alts and sum(1 for a in alts if a["taken"]) == 1
    assert isinstance(view["taken_rank"], int) and view["taken_rank"] >= 1
    assert view["sampled_first"] == (view["taken_rank"] == 1)
    assert view["value"] == view["record"]["policy_value"]
    assert isinstance(view["value"], float)

    assert _roundtrip(gc.snapshot()["flags"]) == _roundtrip(summaries)
    latest = gc.flag({"note": "latest"})
    assert latest["ok"] is True
    assert latest["step"] == max(r["step"] for r in s.trace if r["actor"] == "policy")
    _play(gc, rng)
    final = _load(gc)
    assert final["result"]["natural_completion"] is True
    assert final["flags"] == _roundtrip(s.flags)
    assert [f["step"] for f in final["flags"]] == [step, latest["step"]]


def test_flag_note_and_reasons_are_bounded(best_policy, tmp_path):
    gc = _controller(best_policy, tmp_path, seed=18)
    s = _play(gc, random.Random(18), until=120)
    step = next(r["step"] for r in s.trace if r["actor"] == "policy")
    res = gc.flag({"step": step, "note": "n" * 5000, "reasons": ["r" * 100] * 20})
    assert res["ok"] is True
    entry = _load(gc)["flags"][0]
    assert len(entry["note"]) == 4000
    assert len(entry["reasons"]) == 16 and all(len(r) == 64 for r in entry["reasons"])


def test_flag_on_an_unknown_step_is_refused(best_policy, tmp_path):
    gc = _controller(best_policy, tmp_path, seed=19)
    s = _play(gc, random.Random(19), until=120)
    for step in (-1, len(s.trace), 10 ** 6, "3", 2.5):
        assert gc.flag({"step": step, "note": "x"}) == {"ok": False, "error": "unknown_step"}
    assert s.flags == []
    assert not os.path.exists(gc.record_dir)


def test_flag_on_a_human_step_is_refused(best_policy, tmp_path):
    gc = _controller(best_policy, tmp_path, seed=20)
    s = _play(gc, random.Random(20), until=120)
    human = next(r["step"] for r in s.trace if r["actor"] == "human")
    res = gc.flag({"step": human, "note": "x"})
    assert res["ok"] is False
    assert s.flags == []


# ---- decision views --------------------------------------------------------
def test_decision_view_probabilities_match_the_trace(best_policy, tmp_path):
    joined = plain = 0
    for seed, side in ((23, "home"), (24, "away")):
        gc = _controller(best_policy, tmp_path, seed=seed, human_side=side)
        s = _play(gc, random.Random(seed))
        t = s.trace
        for r in t:
            st = r["step"]
            if r["actor"] != "policy":
                assert s.decision_view(st) is None
                continue
            if _activate_with_declare(t, st):
                assert s.decision_view(st) == s.decision_view(st + 1)
                continue
            view = s.decision_view(st)
            assert view["step"] == st and view["record"] is r
            alts = view["alternatives"]
            taken = [a for a in alts if a["taken"]]
            assert len(taken) == 1, alts
            if _is_joined_declare(t, st):
                assert view["joined"] is True
                want = math.exp(t[st - 1]["policy_logprob"]) * math.exp(r["policy_logprob"])
                joined += 1
            else:
                assert view["joined"] is False
                want = math.exp(r["policy_logprob"])
                plain += 1
            assert abs(taken[0]["p"] - want) <= 1e-4, (st, taken[0]["p"], want)
            assert view["taken_rank"] == taken[0]["rank"]
            assert (view["taken_rank"] == 1) == view["sampled_first"]
            ps = [a["p"] for a in alts]
            assert all(0.0 <= p <= 1.0 for p in ps) and sum(ps) <= 1.0 + 1e-4
            head = alts[:5]
            assert [a["rank"] for a in head] == list(range(1, len(head) + 1))
            assert all(head[i]["p"] >= head[i + 1]["p"] for i in range(len(head) - 1))
            assert view["options"] >= len(head)
        for bad in (-1, len(t), 10 ** 6):
            assert s.decision_view(bad) is None
    assert joined >= 10 and plain >= 100, (joined, plain)


def test_argmax_mode_takes_the_argmax_line(best_policy, tmp_path):
    gc = _controller(best_policy, tmp_path, seed=29, mode="argmax", human_side="away")
    s = _play(gc, random.Random(29))
    assert s.seat.mode == "argmax"
    n = 0
    for r in s.trace:
        if r["actor"] != "policy":
            continue
        st = r["step"]
        view = s.decision_view(st)
        assert view["mode"] == "argmax"
        assert view["argmax_taken"] is True, r
        rows = s.policy_windows[st]
        row = rows[conditional_argmax_row(s.policy_logits[st], rows)]
        assert (int(row[0]), int(row[4]), int(row[5])) == tuple(r["tuple"])
        n += 1
    assert n > 100


# ---- survey ----------------------------------------------------------------
def test_survey_validation_and_persistence(best_policy, tmp_path):
    gc = _controller(best_policy, tmp_path, seed=37)
    s = _play(gc, random.Random(37))
    assert s.over
    good = {"strength": 4, "ball_protection": "sometimes", "stalling": "no",
            "rules_bugs": "The blitz looked odd", "notes": "x" * 5000, "extra": "dropped"}
    res = gc.survey({"answers": good})
    assert res == {"ok": True, "record_dir": os.path.relpath(gc.record_dir, G.ROOT)}
    saved = _load(gc)["survey"]
    assert saved["strength"] == 4 and saved["ball_protection"] == "sometimes"
    assert saved["stalling"] == "no" and saved["rules_bugs"] == "The blitz looked odd"
    assert len(saved["notes"]) == 4000 and "extra" not in saved
    assert isinstance(saved["saved_at"], float)
    assert gc.over_payload()["survey"] == s.survey_answers

    bad = [({"strength": 0}, "bad_strength"), ({"strength": 6}, "bad_strength"),
           ({"strength": "4"}, "bad_strength"), ({"strength": 2.5}, "bad_strength"),
           ({"ball_protection": "maybe"}, "bad_ball_protection"),
           ({"ball_protection": "Yes"}, "bad_ball_protection"),
           ({"stalling": "sometimes"}, "bad_stalling"), ({"stalling": True}, "bad_stalling")]
    for answers, reason in bad:
        assert gc.survey({"answers": answers}) == {"ok": False, "error": reason}, answers
    for request in ({}, {"answers": None}, {"answers": "4"}, {"answers": [4]}):
        assert gc.survey(request) == {"ok": False, "error": "bad_survey"}
    assert _load(gc)["survey"] == saved, "refused answers must not overwrite the record"

    assert gc.survey({"answers": {"strength": 2}})["ok"] is True
    partial = _load(gc)["survey"]
    assert partial["strength"] == 2 and partial["ball_protection"] is None
    assert partial["stalling"] is None and partial["rules_bugs"] == "" and partial["notes"] == ""


def test_survey_refuses_a_boolean_strength(best_policy, tmp_path):
    gc = _controller(best_policy, tmp_path, seed=38)
    _play(gc, random.Random(38), until=60)
    assert gc.survey({"answers": {"strength": True}}) == {"ok": False, "error": "bad_strength"}


# ---- replay of a flagged step ---------------------------------------------
def test_replay_flag_shows_the_board_before_and_after(best_policy, tmp_path):
    gc = _controller(best_policy, tmp_path, seed=41)
    rng = random.Random(41)

    def has_policy_step(s):
        return any(r["actor"] == "policy" and r["action_type"] == "STEP" for r in s.trace)
    s = _play(gc, rng, stop=has_policy_step)
    assert has_policy_step(s)
    step = next(r["step"] for r in s.trace if r["actor"] == "policy" and r["action_type"] == "STEP")
    assert step + 1 < len(s.trace)
    res = gc.flag({"step": step, "reasons": ["Wasted time"]})
    rep = gc.replay_flag(res["flag_index"])
    assert rep["ok"] is True and rep["index"] == res["flag_index"]
    assert "pre_state_hex" not in rep["flag"]
    assert rep["flag"]["step"] == step and rep["flag"]["reasons"] == ["Wasted time"]
    pre, post = rep["pre"], rep["post"]
    assert pre == match_json(s.engine, s.pre_match(step))
    assert post == match_json(s.engine, s.pre_match(step + 1))
    assert pre["players"] != post["players"] or pre["procedure"] != post["procedure"]
    assert pre["procedure"]["proc"] == "MOVE"
    mover = pre["procedure"]["a"]
    before = next(p for p in pre["players"] if p["slot"] == mover)
    after = next(p for p in post["players"] if p["slot"] == mover)
    assert (before["x"], before["y"]) != (after["x"], after["y"])
    _roundtrip(rep)
    for bad in (-1, 1, "0", None, 1.0):
        assert gc.replay_flag(bad) == {"ok": False, "error": "unknown_flag"}


# ---- records ---------------------------------------------------------------
def test_record_directory_and_policy_logits(best_policy, tmp_path):
    games = tmp_path / "games"
    gc = _controller(best_policy, games, seed=31, human_side="away")
    assert os.path.dirname(gc.record_dir) == str(games)
    assert os.path.basename(gc.record_dir).endswith("-31")
    assert gc.saved is False and not os.path.exists(gc.record_dir)
    s = _play(gc, random.Random(31))
    assert gc.saved is True
    assert sorted(os.listdir(gc.record_dir)) == ["game.json", "policy_logits.npz"]
    doc = _load(gc)
    assert doc["header"]["schema"] == SCHEMA
    assert doc["header"]["human_seat"] == 1 and doc["header"]["policy_seat"] == 0
    assert doc["header"]["meta"]["options"] == _roundtrip(gc.options)
    assert doc["result"] == _roundtrip(s.result) and doc["result"]["natural_completion"] is True
    for key in ZERO_KEYS:
        assert doc["integrity"][key] == 0, key
    assert doc["trace"] == _roundtrip(s.trace) and len(doc["trace"]) == s.version
    assert doc["ui"]["options"] == _roundtrip(gc.options)
    assert doc["ui"]["stats"] == _roundtrip(gc.over_payload()["stats"])
    npz = np.load(os.path.join(gc.record_dir, "policy_logits.npz"))
    policy_steps = [r["step"] for r in s.trace if r["actor"] == "policy"]
    assert npz["steps"].tolist() == policy_steps == sorted(s.policy_logits)
    assert npz["logits"].shape == (len(policy_steps), sum(E.ACT_SIZES))
    assert npz["logits"].dtype == np.float32
    for i, st in enumerate(policy_steps):
        assert np.array_equal(npz["logits"][i], s.policy_logits[st])
