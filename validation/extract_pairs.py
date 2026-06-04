#!/usr/bin/env python3
"""extract_pairs.py — build the BC pair corpus from normalized replays.

For every validation/normalized/<id>.jsonl (or just the ids given on the
command line): run the mapper (lockstep_map.py), then the lockstep runner
with --dump-pairs, landing one shard per replay at validation/pairs/<id>.bbp.
Prints per-replay yields and corpus totals (replays, pairs, pairs/replay,
bytes).

The .bbp format (v1) is documented in the comment block of
tools/bb_lockstep.c and in validation/README.md: a 16-byte header
("BBP1", version u32, obs_size u32 = 832, mask_size u32 = 454) followed by
1302-byte records (replay_id u32, cmd u32, agent u8, pad[3], obs[832],
mask[454], type u8, arg u8, sq u16, little-endian). Each shard is
re-validated here: header fields, size % record size, and the invariant
that every record's action targets are set in its own mask slices.

Stock python3, stdlib only. Consumers needing torch use
training/bc_pretrain.py with vendor/PufferLib/.venv/bin/python.

Usage:
  python3 validation/extract_pairs.py            # whole corpus
  python3 validation/extract_pairs.py 1907296    # specific replay id(s)
  python3 validation/extract_pairs.py --rebuild  # force `make lockstep` first
"""

import glob
import json
import os
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(ROOT, "build", "bb_lockstep")
PAIR_DIR = os.path.join(ROOT, "validation", "pairs")

MAGIC = b"BBP1"
VERSION = 1
OBS_SIZE = 832
MASK_SIZE = 454
HEAD_TYPE, HEAD_ARG, HEAD_SQ = 30, 33, 391
HEADER_LEN = 16
REC_LEN = 4 + 4 + 4 + OBS_SIZE + MASK_SIZE + 4  # 1302


def validate_shard(path):
    """Header + per-record invariant check; returns the record count."""
    with open(path, "rb") as f:
        raw = f.read()
    if len(raw) < HEADER_LEN:
        raise ValueError(f"{path}: truncated header")
    magic, ver, osz, msz = struct.unpack("<4sIII", raw[:HEADER_LEN])
    if magic != MAGIC or ver != VERSION or osz != OBS_SIZE or msz != MASK_SIZE:
        raise ValueError(f"{path}: bad header {magic} v{ver} obs={osz} mask={msz}")
    body = raw[HEADER_LEN:]
    if len(body) % REC_LEN:
        raise ValueError(f"{path}: body {len(body)}B not a multiple of {REC_LEN}")
    n = len(body) // REC_LEN
    for i in range(n):
        rec = body[i * REC_LEN:(i + 1) * REC_LEN]
        mask = rec[12 + OBS_SIZE:12 + OBS_SIZE + MASK_SIZE]
        a_type, a_arg = rec[-4], rec[-3]
        (a_sq,) = struct.unpack("<H", rec[-2:])
        if not (a_type < HEAD_TYPE and a_arg < HEAD_ARG and a_sq < HEAD_SQ):
            raise ValueError(f"{path} rec {i}: target out of head range")
        if not (mask[a_type] and mask[HEAD_TYPE + a_arg]
                and mask[HEAD_TYPE + HEAD_ARG + a_sq]):
            raise ValueError(f"{path} rec {i}: target not legal in stored mask")
    return n


def main() -> int:
    os.chdir(ROOT)
    args = [a for a in sys.argv[1:] if a != "--rebuild"]
    if "--rebuild" in sys.argv or not os.path.exists(RUNNER):
        subprocess.run(["make", "lockstep"], check=True, capture_output=True)
    os.makedirs(PAIR_DIR, exist_ok=True)

    if args:
        rids = args
    else:
        rids = sorted(os.path.basename(p).split(".")[0]
                      for p in glob.glob("validation/normalized/*.jsonl"))
    if not rids:
        print("no normalized replays — run validation/normalize_replay.py --all")
        return 1

    total_pairs = total_bytes = ok = 0
    for rid in rids:
        script = f"validation/lockstep/{rid}.jsonl"
        shard = os.path.join(PAIR_DIR, f"{rid}.bbp")
        m = subprocess.run([sys.executable, "validation/lockstep_map.py", rid],
                           capture_output=True, text=True)
        if m.returncode != 0 or not os.path.exists(script):
            print(f"  {rid}: MAP-FAIL {(m.stderr or '').strip()[-100:]}")
            continue
        r = subprocess.run([RUNNER, "--dump-pairs", shard, script],
                           capture_output=True, text=True)
        summary = None
        for line in r.stdout.splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("summary"):
                summary = rec
        if summary is None:
            print(f"  {rid}: RUN-FAIL {(r.stderr or r.stdout).strip()[-100:]}")
            continue
        n = validate_shard(shard)
        if n != summary.get("pairs"):
            raise ValueError(f"{rid}: shard has {n} records, "
                             f"runner reported {summary.get('pairs')}")
        size = os.path.getsize(shard)
        ok += 1
        total_pairs += n
        total_bytes += size
        print(f"  {rid}: {n:4d} pairs ({size} B, "
              f"{summary['pct_consumed']:.1f}% ops consumed)")

    per = total_pairs / ok if ok else 0.0
    print(f"\ncorpus: {ok}/{len(rids)} replays -> {total_pairs} pairs "
          f"({per:.1f} pairs/replay, {total_bytes} bytes) in {PAIR_DIR}")
    return 0 if ok == len(rids) else 1


if __name__ == "__main__":
    sys.exit(main())
