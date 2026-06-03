#!/usr/bin/env python3
"""lockstep_report.py — run the lockstep differential across the corpus.

For every validation/normalized/*.jsonl: map -> run -> collect the first
divergence + consumption stats; print a markdown report. Divergences are the
PRODUCT (validation layer 7): the ranked classes below are the work queue
for v1 triage.

Usage: python3 validation/lockstep_report.py [--rebuild]
"""
import collections
import glob
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(ROOT, "build", "bb_lockstep")


def main() -> int:
    os.chdir(ROOT)
    if "--rebuild" in sys.argv or not os.path.exists(RUNNER):
        subprocess.run(["make", "lockstep"], check=True, capture_output=True)

    rows = []
    classes = collections.Counter()
    skips = collections.Counter()
    for nf in sorted(glob.glob("validation/normalized/*.jsonl")):
        rid = os.path.basename(nf).split(".")[0]
        sf = f"validation/lockstep/{rid}.jsonl"
        m = subprocess.run(
            [sys.executable, "validation/lockstep_map.py", rid],
            capture_output=True, text=True)
        if m.returncode != 0 or not os.path.exists(sf):
            rows.append((rid, "MAP-FAIL", 0, 0.0, (m.stderr or "").strip()[-120:]))
            classes["map-fail"] += 1
            continue
        # Skip-op histogram from the script itself.
        with open(sf) as f:
            for line in f:
                rec = json.loads(line)
                if rec.get("op") == "skip":
                    skips[rec.get("what", "?")] += 1
        r = subprocess.run([RUNNER, sf], capture_output=True, text=True)
        div, summary = None, None
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
            rows.append((rid, "RUN-FAIL", 0, 0.0, (r.stderr or r.stdout).strip()[-120:]))
            classes["run-fail"] += 1
            continue
        cls = div["class"] if div else "CLEAN"
        classes[cls] += 1
        rows.append((rid, cls, div["cmd"] if div else summary["ops_total"],
                     summary["pct_consumed"], (div or {}).get("ours", "")[:90]))

    rows.sort(key=lambda r: -r[3])
    print("# Lockstep differential v0 — corpus report\n")
    print("| replay | first-divergence class | at cmd | % ops consumed |")
    print("|---|---|---|---|")
    for rid, cls, cmd, pct, _ in rows:
        print(f"| {rid} | {cls} | {cmd} | {pct:.1f}% |")
    n = len(rows) or 1
    avg = sum(r[3] for r in rows) / n
    print(f"\n**{len(rows)} replays; mean consumption before divergence: {avg:.1f}%**\n")
    print("## Divergence classes (ranked)\n")
    for cls, c in classes.most_common():
        print(f"- {cls}: {c}")
    print("\n## Skip histogram (unmapped mechanics)\n")
    for what, c in skips.most_common(15):
        print(f"- {what}: {c}")
    print("\n## Sample divergence details\n")
    for rid, cls, cmd, pct, detail in rows[:5]:
        if detail:
            print(f"- {rid} @ {cmd} [{cls}]: {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
