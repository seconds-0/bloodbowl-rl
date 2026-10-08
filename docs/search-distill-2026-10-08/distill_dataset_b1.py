#!/usr/bin/env python3
"""Search distillation: the registered dataset build, one game per forward (D445).

The label tool runs the seat one game per forward. The registered dataset tool,
distill_dataset.py, runs 32 games per forward by default, and float32 arithmetic
rounds a forward of 32 games differently from a forward of one. This tool calls
the registered build function, distill_dataset.build, unchanged: the same shard
acceptance, replay, digests, observation hashes, rebuilt supports and classes,
candidate rule and the registered 1e-3 agreement of a0's log-probability at
every root. The one thing it replaces is how the network is run over a game's
observation rows: each game alone, one game per forward, as
`distill_dataset.py --batch-games 1` does, in --processes worker processes so
that the full plan takes hours and not half a day. It changes no acceptance
rule and no plan-bound file. Its test requires its three split files to equal,
byte for byte, those of `distill_dataset.py --batch-games 1`.

It is meant to run on a machine of the label stage's kind (the stage commands
run it on a droplet through distill_dataset_droplet.py). It does not check the
machine: the registered agreement rule decides, here as anywhere.

Same arguments as distill_dataset.py, less --batch-games, plus --processes.
BUILD_B1.json in --out-dir records the machine, the worker count and this
tool's hash. DATASET.json's `batch_games` is the registered tool's field and
here counts the games replayed between two rounds of forwards, not the games
per forward, which is one.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import platform
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import distill_common as C  # noqa: E402
import distill_dataset as DS  # noqa: E402

CHUNK = 32          # games replayed between two rounds of forwards (the registered default)
_FEATS = None


def _start(harness, checkpoint):
    """A worker: its own harness import, its own copy of the original network."""
    global _FEATS
    os.environ["OMP_NUM_THREADS"] = "1"
    hx = C.Harness(harness)
    policy, _ = hx.load_policy(checkpoint)
    _FEATS = DS.Features(hx, policy)


def _one(job):
    """One game, alone: the registered Features.run on a batch of one."""
    rows, wanted = job
    return _FEATS.run([rows], [wanted])[0]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--harness", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--expect-sha256", required=True)
    ap.add_argument("--checkpoint", required=True, help="the plan's original checkpoint blob")
    ap.add_argument("--shard-dir", action="append", default=[], metavar="NAME=DIR", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--processes", type=int, required=True)
    args = ap.parse_args(argv)
    if args.processes < 1:
        raise SystemExit("--processes must be at least 1")
    args.batch_games = CHUNK
    registered_run = DS.Features.run
    pool = multiprocessing.get_context("spawn").Pool(
        args.processes, initializer=_start,
        initargs=(os.path.abspath(args.harness), os.path.abspath(args.checkpoint)))

    def run(feats, rows, wanted):
        return pool.map(_one, list(zip(rows, wanted)), chunksize=1)

    DS.Features.run = run
    try:
        code = DS.build(args)
    finally:
        DS.Features.run = registered_run
        pool.close()
        pool.join()
    with open(os.path.join(args.out_dir, "BUILD_B1.json"), "w") as f:
        json.dump({"schema": "search-distill-build-b1-v1",
                   "forward": "one game per forward (the registered Features.run on a batch of "
                              "one), in worker processes",
                   "processes": args.processes, "games_replayed_between_forward_rounds": CHUNK,
                   "tool_sha256": C.sha256_file(os.path.abspath(__file__)),
                   "registered_build": "distill_dataset.build, unchanged; tolerance "
                                       f"{DS.LOGPROB_TOLERANCE:g}",
                   "plan_sha256": args.expect_sha256,
                   "machine": {"machine": platform.machine(), "system": platform.system(),
                               "release": platform.release(), "node": platform.node(),
                               "processor": platform.processor()}}, f, indent=1)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
