#!/usr/bin/env python3
"""Milestone 0: hold the label tool's shard on the seen block against the 2026-10-07 screens.

The 200 games of seed block 29100000 were screened on 2026-10-07 by
tools/search_probe_diag.py (four batches, 6,000 roots, 87 tail roots, each
tail root judged on 128 fresh pairs to the end of the match with the return
to the first own turn end kept as `depth1`). The label tool, run on the same
seeds at the registered settings, must give the same roots, the same
candidates, the same 16-rollout returns, the same rule result and the same
labels. Its fresh judgment (128 pairs to the end of the own team turn, the
search's 200-step cut-off) must equal the old `depth1` returns wherever the
rollout stopped on a turn end or the match end, to float rounding: the old
rollouts ran on to the end of the match, so the forward that read a rollout's
value at its first turn end had other rows in its batch, and a batched matrix
product rounds by its batch. The tolerance is 1e-5 per return and 1e-6 per
root's fresh gain; the count of exactly equal returns is printed.

It reads records only and writes nothing but its report on stdout.

  check_m0_regeneration.py --shard DIR --seen DIR [--seen DIR ...]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np


RETURN_TOLERANCE = 1e-5
GAIN_TOLERANCE = 1e-6


def read_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--shard", required=True, help="the label tool's shard directory")
    ap.add_argument("--seen", action="append", required=True,
                    help="a 2026-10-07 batch directory (screen.jsonl, outcomes.jsonl)")
    args = ap.parse_args(argv)
    roots = {(r["game"], r["step"]): r for r in read_jsonl(os.path.join(args.shard, "roots.jsonl"))}
    seen, outcomes = {}, {}
    for folder in args.seen:
        for r in read_jsonl(os.path.join(folder, "screen.jsonl")):
            seen[(r["game"], r["step"])] = r
        for r in read_jsonl(os.path.join(folder, "outcomes.jsonl")):
            if r["set"] == "tail":
                outcomes[(r["game"], r["step"])] = r
    problems = []
    only_new, only_old = sorted(set(roots) - set(seen)), sorted(set(seen) - set(roots))
    if only_new or only_old:
        problems.append(f"{len(only_new)} roots only in the shard, {len(only_old)} only in the "
                        "seen screens")
    same = {"class": 0, "candidates": 0, "returns": 0, "rule": 0}
    worst_return, labels, old_labels, label_same = 0.0, 0, 0, 0
    for key in sorted(set(roots) & set(seen)):
        new, old = roots[key], seen[key]
        same["class"] += new["class"] == old["class"] and new["engine_seed"] == old["engine_seed"]
        same["candidates"] += new["tuples"] == old["tuples"]
        if new["returns"] is not None and np.shape(new["returns"]) == np.shape(old["returns"]):
            diff = float(np.abs(np.asarray(new["returns"]) - np.asarray(old["returns"])).max())
            worst_return = max(worst_return, diff)
            same["returns"] += diff == 0.0
        tail = old["band"] == "tail"
        old_labels += tail
        labels += bool(new["deviate"])
        same["rule"] += (bool(new["deviate"]) == tail and new["best"] == old["best"]
                         and new["gain"] == old["gain"] and new["se"] == old["se"])
        if tail and new["deviate"]:
            label_same += new["label"] == old["tuples"][old["best"]]
    n = len(set(roots) & set(seen))
    for name, count in same.items():
        if count != n:
            problems.append(f"{name}: {count} of {n} equal")
    judged, pairs, pairs_same, pairs_exact, cut, worst_gain, worst_pair = 0, 0, 0, 0, 0, 0.0, 0.0
    for key, old in outcomes.items():
        new = roots.get(key)
        if new is None or not new.get("judgment"):
            problems.append(f"game {key[0]} step {key[1]}: a seen tail root has no judgment")
            continue
        judged += 1
        mine = np.array([[np.nan if v is None else v for v in row]
                         for row in new["judgment"]["returns"]], dtype=float)
        theirs = np.asarray(old["metrics"]["depth1"], dtype=float)
        if mine.shape != theirs.shape:
            problems.append(f"game {key[0]} step {key[1]}: {mine.shape} judgment returns against "
                            f"{theirs.shape}")
            continue
        gap = np.abs(mine - theirs)
        pairs += gap.size
        pairs_exact += int((gap == 0.0).sum())
        pairs_same += int((gap < RETURN_TOLERANCE).sum())
        worst_pair = max(worst_pair, float(gap.max()))
        cut += int(new["judgment"]["stops"].get("cutoff", 0))
        if (gap < RETURN_TOLERANCE).all():
            old_gain = float((theirs[1] - theirs[0]).mean())
            worst_gain = max(worst_gain, abs(old_gain - new["judgment"]["fresh_gain"]))
    if judged != len(outcomes) or labels != old_labels or label_same != old_labels:
        problems.append(f"labels: {labels} in the shard, {old_labels} seen, {label_same} with the "
                        f"same action; {judged} of {len(outcomes)} seen tail roots judged")
    if pairs_same < pairs - cut:
        problems.append(f"{pairs - pairs_same} judgment returns differ from the seen depth1 "
                        f"returns by {RETURN_TOLERANCE} or more, more than the {cut} rollouts "
                        "that stopped on the cut-off")
    if worst_gain > GAIN_TOLERANCE:
        problems.append(f"a root's fresh gain differs from the seen one by {worst_gain}")
    false = sum(bool(r["judgment"]["false"]) for r in roots.values() if r.get("judgment"))
    confirmed = sum(bool(r["judgment"]["confirmed"]) for r in roots.values() if r.get("judgment"))
    print(f"{n} roots in both ({len(roots)} in the shard, {len(seen)} seen); equal class and "
          f"seed {same['class']}, candidates {same['candidates']}, all 16-rollout returns "
          f"{same['returns']} (largest difference {worst_return:.1e}), rule result (deviate, "
          f"best, gain, se) {same['rule']}")
    print(f"labels: {labels} in the shard, {old_labels} seen tail roots, {label_same} with the "
          f"same action; {false} false and {confirmed} confirmed by the shard's own judgment")
    print(f"judgments: {judged} seen tail roots; {pairs_same} of {pairs} per-rollout returns "
          f"within {RETURN_TOLERANCE} of the seen depth1 returns, {pairs_exact} exactly equal, "
          f"largest difference {worst_pair:.1e} ({cut} judgment rollouts stopped on the "
          f"200-step cut-off); largest difference of a root's fresh gain: {worst_gain:.1e}")
    if problems:
        for p in problems:
            print(f"REGENERATION-MISMATCH {p}")
        return 1
    print("REGENERATION-MATCHED the label tool reproduces the seen screens root for root")
    return 0


if __name__ == "__main__":
    sys.exit(main())
