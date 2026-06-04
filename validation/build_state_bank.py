#!/usr/bin/env python3
"""build_state_bank.py — build the demo-state reset bank from normalized replays.

For every validation/normalized/<id>.jsonl (or just the ids given on the
command line): run the mapper (lockstep_map.py), then the lockstep runner
with --dump-states, landing one shard per replay at
validation/states/<id>.bbs, then concatenate every shard into
validation/states/bank.bbs — the file tools/install_puffer_env.sh stages to
resources/bloodbowl/state_bank.bbs for the env's demo-state reset curriculum
(demo_reset_pct; docs/rl-best-practices.md hole #2).

The .bbs format (v1) is documented in the comment block of
tools/bb_lockstep.c and in validation/README.md: a 16-byte header
("BBS1", version u32, match_size u32 = sizeof(bb_match), engine_fp u32)
followed by (12 + match_size)-byte records (replay_id u32, cmd u32, half u8,
turn u8, pad[2], raw bb_match blob). Each shard is re-validated here (header
fields, record sizing, half/turn sanity) and all shards must agree on
match_size + engine_fp before concatenation — a mixed-build bank would feed
the env garbage states.

Prints corpus totals and the per-half/turn histogram of banked states. READ
THE HISTOGRAM: it is the curriculum's start-state distribution. While the
lockstep consumes only the opening ~8-18% of each replay, the bank is
opening-biased (half 1, turns 1-3); it deepens automatically as mapper
coverage improves.

Stock python3, stdlib only.

Usage:
  python3 validation/build_state_bank.py            # whole corpus
  python3 validation/build_state_bank.py 1907296    # specific replay id(s)
  python3 validation/build_state_bank.py --rebuild  # force `make lockstep`
"""

import glob
import json
import os
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(ROOT, "build", "bb_lockstep")
STATE_DIR = os.path.join(ROOT, "validation", "states")
BANK = os.path.join(STATE_DIR, "bank.bbs")

MAGIC = b"BBS1"
VERSION = 1
HEADER_LEN = 16
REC_META = 12  # replay_id u32, cmd u32, half u8, turn u8, pad[2]
MAX_HALF = 3   # 1, 2 (+3 = overtime when enabled)
MAX_TURN = 8


def read_shard(path):
    """Validate one shard; returns (header_bytes, body_bytes, [(half, turn)])."""
    with open(path, "rb") as f:
        raw = f.read()
    if len(raw) < HEADER_LEN:
        raise ValueError(f"{path}: truncated header")
    magic, ver, msz, fp = struct.unpack("<4sIII", raw[:HEADER_LEN])
    if magic != MAGIC or ver != VERSION:
        raise ValueError(f"{path}: bad header {magic} v{ver}")
    body = raw[HEADER_LEN:]
    rec_len = REC_META + msz
    if len(body) % rec_len:
        raise ValueError(f"{path}: body {len(body)}B not a multiple of {rec_len}")
    meta = []
    for i in range(len(body) // rec_len):
        rid, cmd, half, turn = struct.unpack(
            "<IIBB", body[i * rec_len:i * rec_len + 10])
        if not (1 <= half <= MAX_HALF and 1 <= turn <= MAX_TURN):
            raise ValueError(f"{path} rec {i}: half/turn {half}/{turn} out of range")
        meta.append((half, turn))
    return raw[:HEADER_LEN], body, meta


def main() -> int:
    os.chdir(ROOT)
    args = [a for a in sys.argv[1:] if a != "--rebuild"]
    if "--rebuild" in sys.argv or not os.path.exists(RUNNER):
        os.makedirs("build", exist_ok=True)
        subprocess.run(["make", "lockstep"], check=True, capture_output=True)
    os.makedirs(STATE_DIR, exist_ok=True)

    if args:
        rids = args
    else:
        rids = sorted(os.path.basename(p).split(".")[0]
                      for p in glob.glob("validation/normalized/*.jsonl"))
    if not rids:
        print("no normalized replays — run validation/normalize_replay.py --all")
        return 1

    header = None
    bodies = []
    hist = {}  # (half, turn) -> count
    total_states = ok = 0
    for rid in rids:
        script = f"validation/lockstep/{rid}.jsonl"
        shard = os.path.join(STATE_DIR, f"{rid}.bbs")
        m = subprocess.run([sys.executable, "validation/lockstep_map.py", rid],
                           capture_output=True, text=True)
        if m.returncode != 0 or not os.path.exists(script):
            print(f"  {rid}: MAP-FAIL {(m.stderr or '').strip()[-100:]}")
            continue
        r = subprocess.run([RUNNER, "--dump-states", shard, script],
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
        hdr, body, meta = read_shard(shard)
        if len(meta) != summary.get("states"):
            raise ValueError(f"{rid}: shard has {len(meta)} records, "
                             f"runner reported {summary.get('states')}")
        if header is None:
            header = hdr
        elif hdr != header:
            raise ValueError(f"{rid}: shard header differs from the first shard "
                             "(mixed engine builds?) — rebuild all shards")
        bodies.append(body)
        for ht in meta:
            hist[ht] = hist.get(ht, 0) + 1
        ok += 1
        total_states += len(meta)
        print(f"  {rid}: {len(meta):3d} states "
              f"({summary['pct_consumed']:.1f}% ops consumed)")

    if header is None:
        print("no shards produced — nothing to bank")
        return 1
    with open(BANK, "wb") as f:
        f.write(header)
        for body in bodies:
            f.write(body)
    _, _, msz, fp = struct.unpack("<4sIII", header)

    per = total_states / ok if ok else 0.0
    print(f"\nbank: {ok}/{len(rids)} replays -> {total_states} states "
          f"({per:.1f} states/replay, {os.path.getsize(BANK)} bytes, "
          f"match_size={msz}, engine_fp={fp:#010x}) at {BANK}")
    print("\nper-half/turn histogram of banked states "
          "(the curriculum's start distribution — watch the opening bias):")
    print("  turn    " + "".join(f"{t:5d}" for t in range(1, MAX_TURN + 1)))
    for half in range(1, MAX_HALF + 1):
        row = [hist.get((half, t), 0) for t in range(1, MAX_TURN + 1)]
        if sum(row) == 0 and half > 2:
            continue
        print(f"  half {half} " + "".join(f"{c:5d}" for c in row))
    return 0 if ok == len(rids) else 1


if __name__ == "__main__":
    sys.exit(main())
