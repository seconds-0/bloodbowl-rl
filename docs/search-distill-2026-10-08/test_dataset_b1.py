#!/usr/bin/env python3
"""Tests of distill_dataset_b1.py (D445: the registered build, one game per forward).

On dev shards from a finished run of test_distill.py's chain (--dev-scratch:
its PLAN.dev.json, shard1, shard2): the tool's three split files must equal,
byte for byte, those of the registered `distill_dataset.py --batch-games 1`,
and it must refuse what the registered tool refuses, with the registered
tool's own message. Nothing here reads a registered run's shards.

  test_dataset_b1.py --harness EXPORT --checkpoint BLOB \\
      --dev-scratch FINISHED_TEST_SCRATCH --scratch FRESH_DIR
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import distill_common as C  # noqa: E402
import test_distill as T  # noqa: E402

RESULTS = []
SPLITS = ("train", "validation", "test")


def check(name, ok, detail):
    RESULTS.append((name, bool(ok), detail))
    print(("PASS  " if ok else "FAIL  ") + name + ": " + str(detail), flush=True)


def split_files(directory):
    return [p for p in (os.path.join(directory, "train.pt"),
                        os.path.join(directory, "validation.pt"),
                        os.path.join(directory, "locked", "test.pt")) if os.path.exists(p)]


def read_json(path):
    with open(path) as f:
        return json.load(f)


def both(ctx, tag, shard_dirs):
    """The registered tool at --batch-games 1 and this tool on the same shards."""
    extra = [a for k, v in shard_dirs.items() for a in ("--shard-dir", f"{k}={v}")]
    out_a = os.path.join(ctx["scratch"], f"{tag}-registered-b1")
    out_b = os.path.join(ctx["scratch"], f"{tag}-parallel")
    code_a, text_a = T.tool(ctx, "distill_dataset.py", *extra, "--batch-games", "1", out_dir=out_a)
    code_b, text_b = T.tool(ctx, "distill_dataset_b1.py", *extra, "--processes", "3",
                            out_dir=out_b)
    return code_a, text_a, code_b, text_b, out_a, out_b


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--harness", required=True)
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--dev-scratch", required=True)
    ap.add_argument("--scratch", required=True, help="a directory that does not exist yet")
    args = ap.parse_args(argv)
    if os.path.exists(args.scratch):
        raise SystemExit(f"{args.scratch} exists; choose a fresh --scratch")
    os.makedirs(args.scratch)
    dev = os.path.abspath(args.dev_scratch)
    plan_path = os.path.join(dev, "PLAN.dev.json")
    plan_sha = C.sha256_file(plan_path)
    plan, _ = C.load_plan(plan_path, plan_sha)
    if plan.get("name") != C.DEV_PLAN:
        raise SystemExit("--dev-scratch does not hold a dev plan")
    hx = C.Harness(args.harness)
    ctx = {"harness": os.path.abspath(args.harness), "checkpoint": os.path.abspath(args.checkpoint),
           "scratch": os.path.abspath(args.scratch), "plan": plan_path, "plan_sha": plan_sha}
    s1, s2 = os.path.join(dev, "shard1"), os.path.join(dev, "shard2")
    seed0 = int(plan["label"]["seed0"])

    code_a, text_a, code_b, text_b, out_a, out_b = both(ctx, "clean", {"dev-s1": s1, "dev-s2": s2})
    a = read_json(os.path.join(out_a, "DATASET.json")) if code_a == 0 else {}
    b = read_json(os.path.join(out_b, "DATASET.json")) if code_b == 0 else {}
    check("control: the registered tool builds both dev shards at --batch-games 1", code_a == 0,
          T.last_line(text_a)[-200:])
    check("the tool builds them and writes the same three files, byte for byte (the hashes the "
          "two DATASET.json record, and the files rehashed here)",
          code_b == 0 and all(a["files"][s]["sha256"] == b["files"][s]["sha256"] for s in SPLITS)
          and all(C.sha256_file(os.path.join(out_b, b["files"][s]["path"]))
                  == a["files"][s]["sha256"] for s in SPLITS),
          T.last_line(text_b)[-200:])
    differ = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    check("DATASET.json differs from the registered tool's only in `seconds` and `batch_games`; "
          "the tolerance recorded is the registered 1e-3",
          code_b == 0 and set(differ) <= {"seconds", "batch_games"}
          and b["logprob_tolerance"] == 1e-3 and b["complete"] is True,
          {"differ": differ, "largest difference": b.get("max_a0_logprob_difference")})
    build = read_json(os.path.join(out_b, "BUILD_B1.json")) if code_b == 0 else {}
    check("BUILD_B1.json names this tool's hash, the plan and the worker count",
          build.get("tool_sha256") == C.sha256_file(os.path.join(HERE, "distill_dataset_b1.py"))
          and build.get("plan_sha256") == plan_sha and build.get("processes") == 3,
          {k: build.get(k) for k in ("processes", "machine")})

    roots = [r for r in T.A.read_jsonl(os.path.join(s1, "roots.jsonl"))
             if not r["cap_rejected"] and C.split_of(r["engine_seed"], seed0) != "reserve"]
    target = roots[len(roots) // 2]

    def shifted(rows, games, other, complete):
        for r in rows:
            if (r["game"], r["step"]) == (target["game"], target["step"]):
                r["a0_logprob"] = r["a0_logprob"] + 0.002

    def stranger(rows, games, other, complete):
        for r in rows:
            if r["deviate"] or r["cap_rejected"] or \
                    C.split_of(r["engine_seed"], seed0) == "reserve":
                continue
            inside = {tuple(t) for t in r["tuples"]}
            outside = [t for t in r["support"] if tuple(hx.E.unpack_tuple(t)) not in inside]
            if len(r["tuples"]) == 4 and outside:
                r["tuples"][-1] = [int(v) for v in hx.E.unpack_tuple(outside[-1])]
                return
        raise AssertionError("no root to change")

    for tag, name, mutate, want in (
            ("shift", "one root's recorded log-probability 0.002 off", shifted,
             "log-probability differs"),
            ("stranger", "a recorded candidate replaced by another action of the support",
             stranger, "candidates are not the recorded")):
        bad = T.corrupt_shard(s1, os.path.join(ctx["scratch"], f"{tag}-copy"), mutate)
        problems, _ = T.A.shard_problems(bad, "dev-s1", plan, plan_sha)
        code_a, text_a, code_b, text_b, out_a, out_b = both(ctx, tag, {"dev-s1": bad, "dev-s2": s2})
        check(f"copy: {name}: both tools refuse with the registered message and write no split",
              not problems and code_a != 0 and want in text_a and code_b != 0 and want in text_b
              and not split_files(out_a) and not split_files(out_b)
              and not os.path.exists(os.path.join(out_b, "BUILD_B1.json")),
              {"registered": T.last_line(text_a)[-150:], "this tool": T.last_line(text_b)[-150:]})

    passed = sum(ok for _, ok, _ in RESULTS)
    print(f"{passed} of {len(RESULTS)} checks passed")
    with open(os.path.join(args.scratch, "RESULTS.json"), "w") as f:
        json.dump([{"test": n, "passed": ok, "detail": str(d)} for n, ok, d in RESULTS], f, indent=1)
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
