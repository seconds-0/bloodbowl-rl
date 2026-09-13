"""Full matches through the JSON API with the policy on the other seat."""
import json
import os
import time
from collections import Counter

from play_harness.drivers import ContactBotDriver, CoverageDriver, play_to_completion
from play_harness.policy import PolicySeat
from play_harness.session import GameSession, ScriptedSeat

from .conftest import ROOT

N_MATCHES = int(os.environ.get("BBPLAY_N_MATCHES", "10"))
ZERO_KEYS = ("illegal", "projection_collision", "error_episodes", "engine_rejections",
             "precheck_collisions", "api_rejections")


def _check(session):
    integrity = session.integrity()
    assert session.over, "match did not finish"
    assert integrity["natural_completion"], session.result
    for key in ZERO_KEYS:
        assert integrity[key] == 0, (key, integrity)
    assert integrity["forwards"] == integrity["c_steps"] == len(session.trace)
    assert session.result["decisions"] < 4096
    return integrity


def test_ten_full_matches_against_the_policy(best_policy):
    policy, prov = best_policy
    summaries = []
    submitted = set()
    presented = Counter()
    for i in range(N_MATCHES):
        human_seat = i % 2
        driver = CoverageDriver(seed=100 + i, submitted=submitted) if i % 4 < 2 \
            else ContactBotDriver()
        seat = PolicySeat(policy, 1 - human_seat, mode="sample", seed=200 + i,
                          provenance=prov)
        t0 = time.time()
        session = GameSession(seat, human_seat=human_seat, seed=1000 + i)
        submissions = play_to_completion(session, driver)
        integrity = _check(session)
        presented.update(session.presented_counts)
        summaries.append({"match": i, "human_seat": human_seat,
                          "driver": type(driver).__name__,
                          "teams": [t["name"] for t in session.state()["teams"]],
                          "score": session.result["score"], "c_steps": session.version,
                          "human_submissions": submissions,
                          "policy_decisions": seat.decisions, "forwards": seat.forwards,
                          "seconds": round(time.time() - t0, 2), "integrity": integrity})
    out = os.path.join(ROOT, ".play-artifacts", "test-runs", "ten_matches.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump({"policy": {k: v for k, v in prov.items() if k != "lineage"},
                   "matches": summaries, "presented_counts": dict(presented),
                   "submitted_types": sorted(submitted)}, f, indent=1)
    assert len(summaries) == N_MATCHES
    frequent = {t for t, n in presented.items() if n >= 3}
    assert frequent <= submitted, frequent - submitted


def test_rare_windows_are_drivable_from_the_human_seat():
    """Random play on both seats to surface rare windows (apothecary, wrestle,
    interception, argue the call, high kick) and drive each from the human seat."""
    submitted = set()
    presented = Counter()
    prompts = set()
    for i in range(int(os.environ.get("BBPLAY_N_RANDOM_MATCHES", "40"))):
        human_seat = i % 2
        seat = ScriptedSeat(1 - human_seat, kind="random", seed=300 + i)
        session = GameSession(seat, human_seat=human_seat, seed=5000 + i)
        play_to_completion(session, CoverageDriver(seed=400 + i, submitted=submitted))
        _check(session)
        presented.update(session.presented_counts)
        prompts |= session.presented_prompts
    out = os.path.join(ROOT, ".play-artifacts", "test-runs", "rare_windows.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump({"presented_counts": dict(presented), "submitted": sorted(submitted),
                   "prompts": sorted(prompts)}, f, indent=1)
    frequent = {t for t, n in presented.items() if n >= 3}
    assert frequent <= submitted, frequent - submitted
    assert "unknown" not in prompts
