"""Descriptive bench: the harness policy seat against the contact bot.

This is the behavioral half of the recurrence parity plan. It plays kickoff
matches through the same engine shim and PolicySeat the human harness uses and
reports W/D/L and TD for/against per seat. Policy sampling uses torch's RNG,
not curand, so trajectories diverge from native runs; compare distributions,
never individual games.

  .venv/bin/python -m play_harness.bench_vs_bot --checkpoint <blob> --games 100
"""
from __future__ import annotations

import argparse
import json
import os
import time

import torch

from . import engine as E
from .policy import PolicySeat, load_checkpoint


def play(policy, seat, seed, mode, sampling_seed, learner_only=False):
    eng = E.Engine(seed)
    ps = PolicySeat(policy, seat, mode=mode, seed=sampling_seed)
    steps = 0
    while True:
        deciding = eng.decision_team == seat
        if deciding or not learner_only:
            out = ps.step(eng.obs(seat), eng.joint_support(seat), deciding)
        if deciding:
            tup = out["tuple"]
        else:
            tup = eng.legal()[eng.contact_bot_index()].tuple
        rc = eng.step(*tup)
        steps += 1
        if rc == E.STEP_TERMINAL:
            break
        if rc < 0:
            raise RuntimeError(f"step refused rc={rc}")
    final = eng.final_match()
    c = eng.counters()
    mine, theirs = int(final.score[seat]), int(final.score[1 - seat])
    return {"seed": seed, "seat": seat, "td_for": mine, "td_against": theirs,
            "result": "W" if mine > theirs else ("D" if mine == theirs else "L"),
            "natural": final.status == E.STATUS_MATCH_OVER, "c_steps": steps,
            "forwards": ps.forwards, "integrity": {k: c[k] for k in
                                                   ("illegal", "projection_collision",
                                                    "error_episodes")}}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--games", type=int, default=100, help="games per seat")
    ap.add_argument("--mode", default="sample", choices=["sample", "argmax"])
    ap.add_argument("--kernel", default="native", choices=["native", "torch"])
    ap.add_argument("--learner-only", action="store_true",
                    help="control arm: step the policy only on its own decisions")
    ap.add_argument("--seed0", type=int, default=1)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "4")))
    policy, prov = load_checkpoint(args.checkpoint, kernel=args.kernel)
    games = []
    t0 = time.time()
    for seat in (0, 1):
        for i in range(args.games):
            games.append(play(policy, seat, args.seed0 + i, args.mode, 10_000 + i,
                              learner_only=args.learner_only))
    summary = {}
    for seat in (0, 1):
        g = [x for x in games if x["seat"] == seat]
        summary["home" if seat == 0 else "away"] = {
            "games": len(g),
            "W": sum(x["result"] == "W" for x in g), "D": sum(x["result"] == "D" for x in g),
            "L": sum(x["result"] == "L" for x in g),
            "td_for_per_game": sum(x["td_for"] for x in g) / len(g),
            "td_against_per_game": sum(x["td_against"] for x in g) / len(g),
            "natural_completion": all(x["natural"] for x in g),
            "integrity_zero": all(not any(x["integrity"].values()) for x in g),
            "forwards_equal_c_steps": all(x["forwards"] == x["c_steps"] for x in g)
            if not args.learner_only else None,
        }
    doc = {"checkpoint_sha256": prov["checkpoint_sha256"], "mode": args.mode,
           "kernel": args.kernel, "learner_only": args.learner_only,
           "opponent": "contact-bot", "seconds": round(time.time() - t0, 1),
           "summary": summary, "games": games}
    out = args.out or os.path.join(E.ROOT, ".play-artifacts", "bench",
                                   f"vs-contact-{args.mode}-{args.kernel}"
                                   f"{'-learner-only' if args.learner_only else ''}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(doc, f, indent=1)
    print(json.dumps({k: v for k, v in doc.items() if k != "games"}, indent=1))


if __name__ == "__main__":
    main()
