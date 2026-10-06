#!/usr/bin/env python3
"""Launch the masked-copy arms, one throwaway droplet each, detached.

  tools/mask_arms_launch.py [ARM ...]        # default: every arm

Arms, masks and seed blocks are the ones registered in
docs/play-harness/masked-copy-2026-10-05.md. Each arm is one
`tools/droplet_tournament.py run` in its own session under caffeinate; that
tool creates the droplet, runs, verifies, destroys it and prints the cost.
Logs go to .play-artifacts/logs/<run name>.log in this checkout.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKPOINTS = os.environ.get(
    "BBPLAY_CHECKPOINT_DIR",
    os.path.expanduser("~/Code/bb-play-harness/.play-artifacts/checkpoints"))
BLOB = os.path.join(CHECKPOINTS, "chain41", "0000002999975936.bin")
OUT = os.path.join(ROOT, ".play-artifacts", "tournaments")
LOGS = os.path.join(ROOT, ".play-artifacts", "logs")
STAMP = "20261005"
GAMES = 3200
# arm -> (player A, masks on A, seed block)
ARMS = {
    "m1": ("chain41m1", "m1", 23000000),
    "m2": ("chain41m2", "m2", 23100000),
    "m3": ("chain41m3", "m3", 23200000),
    "m123": ("chain41m123", "m1,m2,m3", 23300000),
    "control": ("chain41c", None, 23400000),
}


def run_name(arm):
    return f"mask-{arm}-{STAMP}"


def argv_for(arm, commit):
    player, masks, seed0 = ARMS[arm]
    argv = ["caffeinate", "-i", sys.executable, os.path.join(ROOT, "tools", "droplet_tournament.py"),
            "run", "--name", run_name(arm), "--seed0", str(seed0), "--games-per-worker", "32",
            "--commit", commit, "--out-root", OUT, "--max-hours", "1.5",
            "--checkpoint", f"{player}={BLOB}", "--checkpoint", f"chain41={BLOB}",
            "--pair", f"{player},chain41,{GAMES}"]
    if masks:
        argv += ["--tournament-arg=--mask", f"--tournament-arg={player}={masks}"]
    return argv


def main(argv=None):
    arms = list(argv if argv is not None else sys.argv[1:]) or list(ARMS)
    unknown = [a for a in arms if a not in ARMS]
    if unknown:
        raise SystemExit(f"unknown arm(s) {unknown}; known: {list(ARMS)}")
    commit = subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], check=True,
                            capture_output=True, text=True).stdout.strip()
    os.makedirs(LOGS, exist_ok=True)
    for arm in arms:
        if os.path.exists(os.path.join(OUT, run_name(arm), "main")):
            raise SystemExit(f"{run_name(arm)} already has results")
        log = open(os.path.join(LOGS, run_name(arm) + ".log"), "ab")
        proc = subprocess.Popen(argv_for(arm, commit), stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True, cwd=ROOT)
        print(run_name(arm), "pid", proc.pid, "commit", commit[:12], flush=True)


if __name__ == "__main__":
    main()
