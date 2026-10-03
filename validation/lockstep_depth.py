#!/usr/bin/env python3
"""lockstep_depth.py — measure how deep lockstep gets into each replay.

Per replay: normalize -> map -> bb_lockstep (--dump-pairs, --dump-states,
BB_LOCKSTEP_TRACE=1), then record where the first divergence sits in the
replay: decisions consumed (act + place ops applied = pair records), the
share of the script's decisions, the FUMBBL command number, the replay's own
(half, round, mode) at that command, the diverging op, and the engine proc
stack at the divergence.

lockstep_report.py's pct_consumed counts every skip op in the file, including
the ones after the divergence, so it overstates depth; this script counts
only what was applied before the stop.

Usage:
  python3 validation/lockstep_depth.py --ids ids.txt --out runs/x/depth.jsonl
      [--jobs 4] [--no-normalize] [--compare-dir <other checkout>/validation]
Stock python3, stdlib only. One JSON line per replay in --out.
"""
import argparse
import concurrent.futures
import filecmp
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RUNNER = os.path.join(ROOT, "build", "bb_lockstep")

A_NAMES = {
    1: "SETUP_PLACE", 2: "SETUP_REMOVE", 3: "SETUP_DONE", 4: "KICK_TARGET",
    5: "TOUCHBACK", 6: "ACTIVATE", 7: "DECLARE", 8: "END_TURN", 9: "STEP",
    10: "STAND_UP", 11: "JUMP", 12: "BLOCK_TARGET", 13: "PASS_TARGET",
    14: "HANDOFF_TARGET", 15: "FOUL_TARGET", 16: "TTM_TARGET",
    17: "SECURE_BALL", 19: "END_ACTIVATION", 20: "CHOOSE_DIE",
    21: "PUSH_SQUARE", 22: "FOLLOW_UP", 23: "USE_REROLL",
    24: "DECLINE_REROLL", 25: "USE_SKILL", 26: "DECLINE_SKILL",
    27: "APOTHECARY", 28: "CHOOSE_OPTION", 29: "SPECIAL_TARGET",
}


def turn_index(norm_path):
    """[(cmd, half, round, mode)] change points + nCommands from the
    normalized stream."""
    seq, ncmd = [], 0
    with open(norm_path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("type") == "meta":
                ncmd = r.get("nCommands") or 0
            if "half" in r and "turn" in r and "cmd" in r:
                k = (r["half"], r["turn"], r.get("mode"))
                if not seq or seq[-1][1:] != k:
                    seq.append((r["cmd"],) + k)
    return seq, ncmd


def locate(seq, cmd):
    cur = (0, 0, "startGame")
    for c, h, t, m in seq:
        if c > cmd:
            break
        cur = (h, t, m)
    return cur


def one(job):
    rid, do_norm, cmp_dir = job
    row = {"rid": rid}
    t0 = time.time()
    norm = os.path.join(HERE, "normalized", f"{rid}.jsonl")
    script = os.path.join(HERE, "lockstep", f"{rid}.jsonl")
    if do_norm:
        n = subprocess.run([sys.executable, os.path.join(HERE, "normalize_replay.py"), rid],
                           capture_output=True, text=True)
        row["norm_rc"] = n.returncode
        if n.returncode != 0 or not os.path.exists(norm):
            row["fail"] = "normalize"
            row["err"] = (n.stderr or n.stdout).strip()[-300:]
            return row
    m = subprocess.run([sys.executable, os.path.join(HERE, "lockstep_map.py"), rid],
                       capture_output=True, text=True)
    row["map_rc"] = m.returncode
    if m.returncode != 0 or not os.path.exists(script):
        row["fail"] = "map"
        row["err"] = (m.stderr or m.stdout).strip()[-300:]
        return row
    if cmp_dir:
        for kind, p in (("norm", norm), ("script", script)):
            other = os.path.join(cmp_dir, "normalized" if kind == "norm" else "lockstep",
                                 f"{rid}.jsonl")
            row[f"{kind}_same_as_ref"] = (os.path.exists(other) and
                                          filecmp.cmp(p, other, shallow=False))
    os.makedirs(os.path.join(HERE, "pairs"), exist_ok=True)
    os.makedirs(os.path.join(HERE, "states"), exist_ok=True)
    shard = os.path.join(HERE, "pairs", f"{rid}.bbp")
    states = os.path.join(HERE, "states", f"{rid}.bbs")
    env = dict(os.environ, BB_LOCKSTEP_TRACE="1")
    r = subprocess.run([RUNNER, "--dump-pairs", shard, "--dump-states", states, script],
                       capture_output=True, text=True, env=env)
    row["run_rc"] = r.returncode
    div = summary = None
    for line in r.stdout.splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("summary"):
            summary = rec
        elif "class" in rec:
            div = rec
    if summary is None:
        row["fail"] = "run"
        row["err"] = (r.stderr or r.stdout).strip()[-300:]
        return row
    trace = r.stderr.strip().splitlines()
    ops = [json.loads(l) for l in open(script, encoding="utf-8")]
    nonskip = [o for o in ops if o["op"] != "skip"]
    applied = summary["ops_applied"] - summary["skips"]
    decisions_total = sum(1 for o in ops if o["op"] in ("act", "place"))
    seq, ncmd = turn_index(norm)
    row.update(pairs=summary.get("pairs"), states=summary.get("states"),
               decisions_total=decisions_total, ops_total=len(ops),
               nonskip_total=len(nonskip), nonskip_applied=applied,
               ncmd=ncmd, diverged=summary["diverged"],
               pct_consumed_runner=summary["pct_consumed"],
               unmapped_skills=summary["unmapped_skills"],
               engine_status=summary["engine_status"],
               last_turn=list(seq[-1][1:]) if seq else None)
    if div:
        dop = nonskip[applied] if applied < len(nonskip) else None
        h, t, mode = locate(seq, div["cmd"])
        row.update(cls=div["class"], cmd=div["cmd"], ours=div["ours"],
                   theirs=div["theirs"], half=h, round=t, mode=mode,
                   div_op=dop, context=div.get("context"),
                   trace_last=trace[-1] if trace else None,
                   trace_prev=trace[-2] if len(trace) > 1 else None)
        # skips sitting between the last applied op and the diverging op
        idx = ops.index(dop) if dop is not None else len(ops)
        near = []
        for o in ops[max(0, idx - 12):idx]:
            if o["op"] == "skip":
                near.append(o.get("what"))
        row["skips_before"] = near
    else:
        row.update(cls="CLEAN", cmd=ncmd)
    row["secs"] = round(time.time() - t0, 2)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--no-normalize", action="store_true")
    ap.add_argument("--compare-dir")
    a = ap.parse_args()
    rids = open(a.ids).read().split()
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    jobs = [(r, not a.no_normalize, a.compare_dir) for r in rids]
    t0 = time.time()
    done = 0
    with open(a.out, "w") as out, \
            concurrent.futures.ProcessPoolExecutor(max_workers=a.jobs) as ex:
        for row in ex.map(one, jobs):
            out.write(json.dumps(row) + "\n")
            done += 1
            if done % 20 == 0 or done == len(jobs):
                print(f"[{done}/{len(jobs)}] {time.time() - t0:.0f}s last={row['rid']} "
                      f"{row.get('fail') or row.get('cls')}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
