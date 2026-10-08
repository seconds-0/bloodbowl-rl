#!/usr/bin/env python3
"""A decision inside a kick-off Blitz turn is not a root (the bug of run et1, 2026-10-08).

  python test_kickoff_turn_roots.py                      # the unit tests
  python test_kickoff_turn_roots.py --harness EXPORT --lib LIB --checkpoint-store STORE
                                                        # also replays the two games that failed

The first launch of the registered probe stopped on "forced arm: the rule ended a
turn 2 times in one rollout" at chain 58, engine seed 29960001, step 26, and at
chain 59, engine seed 29960027, step 32. Both roots were END_TURN decisions inside
the kicking team's free turn from a Blitz kick-off result. With --harness the two
games are played again with the registered settings; each must complete, record
at least one end_turn decision left out as a kick-off turn decision, have no root
at the step that failed, and have a forced-arm maximum of 1 on every root. Without
the fix the replay fails with the message above. The unit tests restate the stack
rule on stand-in frames; the engine's side of it (a Blitz turn runs under MATCH,
KICKOFF and its end does not bump turns_completed) was read in the engine source
by the reviewer and shown by the replay, and is not asserted here.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import endturn_probe as EP  # noqa: E402

PROCS = ["NONE", "MATCH", "PREGAME", "SETUP", "KICKOFF", "TEAM_TURN", "ACTIVATION"]
SETTINGS = ["--seed0", "29960000", "--rollouts", "64", "--cap-end-turn", "24", "--cap-decline-block", "12",
            "--cap-activate", "4", "--match-roots", "3", "--match-rollouts", "64", "--alternatives", "3"]
FAILED = (("chain58", 1, 29960001, 26), ("chain59", 27, 29960027, 32))     # checkpoint, game index, engine seed, the failing root's step


def match(*procs, extra=()):
    """A stand-in for the engine's match: `procs` are the live frames, `extra` stale ones above the top."""
    frames = [types.SimpleNamespace(proc=PROCS.index(name)) for name in list(procs) + list(extra)]
    return types.SimpleNamespace(stack=frames, stack_top=len(procs))


def unit_tests():
    E = types.SimpleNamespace(PROCS=PROCS)
    assert EP.in_kickoff_turn(E, match("MATCH", "KICKOFF"))                    # the Blitz turn's own frame
    assert EP.in_kickoff_turn(E, match("MATCH", "KICKOFF", "ACTIVATION"))      # inside an activation of it
    assert not EP.in_kickoff_turn(E, match("MATCH", "TEAM_TURN"))              # an ordinary team turn
    assert not EP.in_kickoff_turn(E, match("MATCH", "TEAM_TURN", "ACTIVATION"))
    assert not EP.in_kickoff_turn(E, match("MATCH", "TEAM_TURN", extra=("KICKOFF",)))   # a stale frame above the top
    assert not EP.in_kickoff_turn(E, match())
    print("unit tests: ok")


def replay(args):
    for name, index, seed, bad_step in FAILED:
        out = tempfile.mkdtemp(prefix=f"kickoff-turn-{name}-")
        blob = os.path.join(os.path.expanduser(args.checkpoint_store), name, "0000002999975936.bin")
        argv = [sys.executable, os.path.join(HERE, "endturn_probe.py"), "worker", "--harness", args.harness,
                "--lib", args.lib, "--checkpoint", blob, "--checkpoint-name", name, "--out-dir", out,
                "--games", str(index + 1), "--index", str(index), "--of", str(index + 1)] + SETTINGS
        r = subprocess.run(argv, capture_output=True, text=True, env={**os.environ, "OMP_NUM_THREADS": "1"})
        assert r.returncode == 0, f"{name} seed {seed}: {r.stdout[-400:]} {r.stderr[-400:]}"
        games = [json.loads(line) for f in glob.glob(os.path.join(out, "games.w*.jsonl")) for line in open(f)]
        assert len(games) == 1 and games[0]["engine_seed"] == seed, games
        g = games[0]
        assert g["kickoff_turn_decisions"]["end_turn"] >= 1, g["kickoff_turn_decisions"]
        assert g["checks"]["forced_max"] == 1, g["checks"]
        roots = [json.loads(line) for f in glob.glob(os.path.join(out, "roots.w*.jsonl")) for line in open(f)]
        assert roots and all(r["engine_seed"] == seed for r in roots), len(roots)
        assert bad_step not in {r["step"] for r in roots}, f"step {bad_step} is still a root"
        assert all(max(max(row) for row in r["forced"]["forced"]) <= 1 for r in roots if "forced" in r)
        print(f"replay {name} seed {seed}: ok, left out {g['kickoff_turn_decisions']}, scratch {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--harness")
    ap.add_argument("--lib")
    ap.add_argument("--checkpoint-store", default="~/Code/bb-play-harness/.play-artifacts/checkpoints")
    args = ap.parse_args()
    unit_tests()
    if args.harness and args.lib:
        replay(args)
    else:
        print("replay skipped: give --harness and --lib")


if __name__ == "__main__":
    main()
