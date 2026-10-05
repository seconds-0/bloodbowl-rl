#!/usr/bin/env python3
"""lockstep_reseat.py: run the turn-boundary re-seat prototype over replays.

PROTOTYPE, measurement only. Nothing this writes is training input: re-seated
records land in .bbr shards that the BBP readers refuse (see the re-seat
comment block in tools/bb_lockstep.c and validation/README.md, "Re-seat").

Per replay (scripts must exist; --map re-runs lockstep_map.py first) it runs
tools/bb_lockstep three ways and keeps every JSON line the runner prints:

  audit   --seat-audit                 at every boundary reached in lockstep,
                                       rebuild the state from the seat and
                                       list each field that differs from the
                                       engine's own, legally reached state
  force   --force-reseat               TEST: replace the state at EVERY
                                       boundary although nothing diverged;
                                       its records must equal the prefix
                                       records byte for byte
  reseat  --reseat --seat-audit        the prototype itself: resume at the
                                       next seatable boundary after every
                                       divergence

Outputs under --out-dir:
  pairs/<id>.bbp          prefix-aligned records (identical to --dump-pairs)
  pairs_reseat/<id>.bbr   records written after a re-seat
  states/<id>.bbs         state bank (prefix only; nothing after a re-seat)
  force/<id>.bbp|.bbr     the forced-re-seat test shards
  audit.jsonl, force.jsonl, reseat.jsonl   one line per replay

Usage:
  python3 validation/lockstep_reseat.py --ids ids.txt --out-dir runs/x \\
      [--jobs 4] [--map] [--modes audit,force,reseat]
Stock python3, stdlib only. Report with validation/reseat_report.py.
"""
import argparse
import collections
import concurrent.futures
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RUNNER = os.path.join(ROOT, "build", "bb_lockstep")


def run_lines(args):
    r = subprocess.run([RUNNER] + args, capture_output=True, text=True)
    out = []
    for line in r.stdout.splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return r.returncode, out, r.stderr


def split(lines):
    row = {"summary": None, "divergences": [], "reseats": [], "audits": [],
           "seat_skips": [], "closes": [], "forced": []}
    for rec in lines:
        if rec.get("summary"):
            row["summary"] = rec
        elif rec.get("audit"):
            row["audits"].append(rec)
        elif rec.get("reseat"):
            row["reseats"].append(rec)
        elif rec.get("close"):
            row["closes"].append(rec)
        elif rec.get("forced"):
            row["forced"].append(rec)
        elif rec.get("seat_skip"):
            row["seat_skips"].append(rec)
        elif "class" in rec:
            rec.pop("context", None)
            row["divergences"].append(rec)
    return row


SD_HARD, SD_SOFT, SD_DERIVED, SD_BOOK = 1, 2, 4, 8


def audit_summary(audits):
    """Collapse per-boundary audit lines (prefix boundaries only: the runner
    audits where the mirror-based expect passed). Split by `tol`: at a "clean"
    boundary the mapper knows of no divergence it tolerates, so a difference
    there is the seat's error or drift nobody modelled; at a "tolerated" one
    the engine is knowingly off the replay."""
    out = {}
    for name, sel in (("clean", lambda a: not a.get("tol")),
                      ("tolerated", lambda a: a.get("tol"))):
        toks = collections.Counter()
        fails = collections.Counter()
        masks = collections.Counter()
        rows = [a for a in audits if sel(a)]
        for a in rows:
            if "build_fail" in a:
                fails[a["build_fail"]] += 1
                continue
            for t in filter(None, a["diff"].split(",")):
                if t.startswith("rerolls(") and a.get("rr_known"):
                    t = "rerolls.known_to_mapper" + t[7:]
                toks[t] += 1
            for bit, cls in ((SD_HARD, "hard"), (SD_SOFT, "soft"),
                             (SD_DERIVED, "derived"), (SD_BOOK, "book")):
                if a["mask"] & bit:
                    masks[cls] += 1
            if not a["mask"] & (SD_HARD | SD_SOFT | SD_DERIVED):
                masks["observable_equal"] += 1
        out[name] = {"boundaries": len(rows), "build_fail": dict(fails),
                     "tokens": dict(toks), "classes": dict(masks)}
    return out


def close_summary(closes):
    """Boundaries reached without a stop inside re-seated provenance: how the
    engine, after playing the span, compared with the replay's own state."""
    toks = collections.Counter()
    status = collections.Counter()
    soft = 0
    for c in closes:
        status[str(c["status"])] += 1
        if c["mask"] & SD_SOFT:
            soft += 1
        for t in filter(None, c["diff"].split(",")):
            toks[t] += 1
    return {"boundaries": len(closes), "status": dict(status),
            "soft_drift": soft, "tokens": dict(toks)}


def one(job):
    rid, out_dir, modes, do_map = job
    t0 = time.time()
    script = os.path.join(HERE, "lockstep", f"{rid}.jsonl")
    res = {"rid": rid}
    if do_map:
        m = subprocess.run([sys.executable, os.path.join(HERE, "lockstep_map.py"),
                            rid, "--quiet"], capture_output=True, text=True)
        if m.returncode != 0:
            res["fail"] = "map: " + (m.stderr or m.stdout)[-300:]
            return res
    if not os.path.exists(script):
        res["fail"] = "no script"
        return res
    ops = [json.loads(l) for l in open(script, encoding="utf-8")]
    res["decisions_total"] = sum(
        1 for o in ops if o["op"] == "place" or
        (o["op"] == "act" and not o.get("nopair")))
    exps = [o for o in ops if o["op"] == "expect"]
    res["boundaries_total"] = len(exps)
    res["seat_refusals"] = dict(collections.Counter(
        o["seat"]["refuse"] for o in exps
        if "seat" in o and "refuse" in o["seat"]))
    if "audit" in modes:
        rc, lines, err = run_lines(["--seat-audit", script])
        row = split(lines)
        res["audit"] = {"rc": rc, "summary": row["summary"],
                        "audit": audit_summary(row["audits"])}
    if "force" in modes:
        d = os.path.join(out_dir, "force")
        rc, lines, err = run_lines([
            "--force-reseat", "--dump-pairs", os.path.join(d, f"{rid}.bbp"),
            "--dump-pairs-reseat", os.path.join(d, f"{rid}.bbr"),
            "--dump-states", os.path.join(d, f"{rid}.bbs"), script])
        row = split(lines)
        res["force"] = {"rc": rc, "summary": row["summary"],
                        "divergences": row["divergences"],
                        "reseats": (row["summary"] or {}).get("reseats", 0),
                        # segment -> class mask of what the seat changed there
                        "forced": {str(f["seg"]): f["mask"] for f in row["forced"]},
                        "seat_skips": dict(collections.Counter(
                            s["why"] for s in row["seat_skips"]))}
    if "reseat" in modes:
        rc, lines, err = run_lines([
            "--reseat", "--seat-audit",
            "--dump-pairs", os.path.join(out_dir, "pairs", f"{rid}.bbp"),
            "--dump-pairs-reseat", os.path.join(out_dir, "pairs_reseat", f"{rid}.bbr"),
            "--dump-states", os.path.join(out_dir, "states", f"{rid}.bbs"),
            script])
        row = split(lines)
        res["reseat"] = {"rc": rc, "summary": row["summary"],
                         "divergences": row["divergences"],
                         "reseats": row["reseats"],
                         "seat_skips": dict(collections.Counter(
                             s["why"] for s in row["seat_skips"])),
                         "audit": audit_summary(row["audits"]),
                         "close": close_summary(row["closes"])}
    res["secs"] = round(time.time() - t0, 2)
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ids", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--map", action="store_true")
    ap.add_argument("--modes", default="audit,force,reseat")
    a = ap.parse_args()
    modes = [m for m in a.modes.split(",") if m]
    rids = open(a.ids).read().split()
    out_dir = os.path.abspath(a.out_dir)
    for d in ("pairs", "pairs_reseat", "states", "force"):
        os.makedirs(os.path.join(out_dir, d), exist_ok=True)
    files = {m: open(os.path.join(out_dir, f"{m}.jsonl"), "w") for m in modes}
    jobs = [(r, out_dir, modes, a.map) for r in rids]
    t0 = time.time()
    done = fails = 0
    with concurrent.futures.ProcessPoolExecutor(max_workers=a.jobs) as ex:
        for res in ex.map(one, jobs):
            done += 1
            if "fail" in res:
                fails += 1
                print(f"FAIL {res['rid']}: {res['fail']}", flush=True)
            base = {k: v for k, v in res.items() if k not in modes}
            for m in modes:
                if m in res:
                    files[m].write(json.dumps(dict(base, **res[m])) + "\n")
            if done % 25 == 0 or done == len(jobs):
                print(f"[{done}/{len(jobs)}] {time.time() - t0:.0f}s "
                      f"last={res['rid']} fails={fails}", flush=True)
    for f in files.values():
        f.close()
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
