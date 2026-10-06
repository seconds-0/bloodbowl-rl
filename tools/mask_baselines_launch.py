#!/usr/bin/env python3
"""Launch the m1 baseline runs for the training rung, one throwaway droplet each.

  tools/mask_baselines_launch.py [RUN ...]        # default: every run

Runs, players, masks, sampling offsets and seed blocks are the ones registered
in docs/play-harness/masked-copy-baselines-2026-10-05.md, section 0. Each run is
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

# player -> (checkpoint chain, masks, sampling offset). A masked copy that meets
# its own plain checkpoint carries a sampling offset, so the two sides never
# share a sampling stream.
PLAYERS = {
    "chain37": ("chain37", None, 0),
    "chain41": ("chain41", None, 0),
    "chain41m1": ("chain41", "m1", 0),
    "chain42": ("chain42", None, 0),
    "chain42m1": ("chain42", "m1", 0),
    "chain42m1s": ("chain42", "m1", 1),
    "chain47": ("chain47", None, 0),
    "chain47m1s": ("chain47", "m1", 1),
    "chain48": ("chain48", None, 0),
    "chain48m1s": ("chain48", "m1", 1),
}
# run -> (seed block, [(A, B)]); every pair plays GAMES games on the block's seeds.
# c37-42 and c37-41 share one seed block on two droplets.
RUNS = {
    "c42-self": (24500000, [("chain42m1s", "chain42")]),
    "c42-c41": (24600000, [("chain42m1", "chain41m1"), ("chain42", "chain41")]),
    "c37-42": (24700000, [("chain42m1", "chain37"), ("chain42", "chain37")]),
    "c37-41": (24700000, [("chain41m1", "chain37"), ("chain41", "chain37")]),
    "c47-self": (24800000, [("chain47m1s", "chain47")]),
    "c48-self": (24900000, [("chain48m1s", "chain48")]),
}


def run_name(run):
    return f"maskb-{run}-{STAMP}"


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
