#!/usr/bin/env python3
"""Launch the masked-copy follow-up runs, one throwaway droplet each, detached.

  tools/mask_followup_launch.py [RUN ...]        # default: every run

Runs, players, masks, sampling offsets and seed blocks are the ones registered
in docs/play-harness/masked-copy-followup-2026-10-05.md, section 0. Each run is
one `tools/droplet_tournament.py run` in its own session under caffeinate.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKPOINTS = os.environ.get(
    "BBPLAY_CHECKPOINT_DIR",
    os.path.expanduser("~/Code/bb-play-harness/.play-artifacts/checkpoints"))
BLOB = "0000002999975936.bin"
OUT = os.path.join(ROOT, ".play-artifacts", "tournaments")
LOGS = os.path.join(ROOT, ".play-artifacts", "logs")
STAMP = "20261005"
GAMES = 3200
M1, PLAIN = "chain41m1", "chain41"

# Players other than plain chain 41: name -> (checkpoint chain, masks, sampling offset)
PLAYERS = {
    PLAIN: ("chain41", None, 0),
    M1: ("chain41", "m1", 0),
    "chain41m12": ("chain41", "m1,m2", 0),
    "chain41b": ("chain41", None, 1),
    "chain41m1b": ("chain41", "m1", 1),
    "chain27": ("chain27", None, 0),
    "chain36": ("chain36", None, 0),
    "chain47": ("chain47", None, 0),
}
BOTS = ("offense", "contact")
# run -> (seed block, [(A, B)]); every pair plays GAMES games on the block's seeds
RUNS = {
    "t-offense": (23500000, [(M1, "offense"), (PLAIN, "offense")]),
    "t-contact": (23600000, [(M1, "contact"), (PLAIN, "contact")]),
    "t-chain27": (23700000, [(M1, "chain27"), (PLAIN, "chain27")]),
    "t-chain36": (23800000, [(M1, "chain36"), (PLAIN, "chain36")]),
    "t-chain47": (23900000, [(M1, "chain47"), (PLAIN, "chain47")]),
    "m12": (24000000, [("chain41m12", PLAIN)]),
    "null": (24100000, [("chain41b", PLAIN)]),
    "both-m1": (24200000, [("chain41m1b", M1)]),
}


def run_name(run):
    return f"maskf-{run}-{STAMP}"


def argv_for(run, commit):
    seed0, pairs = RUNS[run]
    argv = ["caffeinate", "-i", sys.executable, os.path.join(ROOT, "tools", "droplet_tournament.py"),
            "run", "--name", run_name(run), "--seed0", str(seed0), "--games-per-worker", "32",
            "--commit", commit, "--out-root", OUT, "--max-hours", "1.5"]
    names = []
    for pair in pairs:
        for name in pair:
            if name not in names:
                names.append(name)
    for name in names:
        if name in BOTS:
            argv += ["--bot", f"{name}={name}"]
            continue
        chain, masks, offset = PLAYERS[name]
        argv += ["--checkpoint", f"{name}={os.path.join(CHECKPOINTS, chain, BLOB)}"]
        if masks:
            argv += ["--tournament-arg=--mask", f"--tournament-arg={name}={masks}"]
        if offset:
            argv += ["--tournament-arg=--sampling-offset", f"--tournament-arg={name}={offset}"]
    for a, b in pairs:
        argv += ["--pair", f"{a},{b},{GAMES}"]
    return argv


def main(argv=None):
    runs = list(argv if argv is not None else sys.argv[1:]) or list(RUNS)
    unknown = [r for r in runs if r not in RUNS]
    if unknown:
        raise SystemExit(f"unknown run(s) {unknown}; known: {list(RUNS)}")
    commit = subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], check=True,
                            capture_output=True, text=True).stdout.strip()
    os.makedirs(LOGS, exist_ok=True)
    for run in runs:
        if os.path.exists(os.path.join(OUT, run_name(run), "main")):
            raise SystemExit(f"{run_name(run)} already has results")
        log = open(os.path.join(LOGS, run_name(run) + ".log"), "ab")
        proc = subprocess.Popen(argv_for(run, commit), stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True, cwd=ROOT)
        print(run_name(run), "pid", proc.pid, "commit", commit[:12], flush=True)


if __name__ == "__main__":
    main()
