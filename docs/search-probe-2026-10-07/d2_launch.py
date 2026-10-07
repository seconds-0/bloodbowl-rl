"""Launch the two processes of the third tail batch (D2_CHECK_PLAN.md), detached."""
import os, subprocess
D = os.path.dirname(os.path.abspath(__file__))
PY = "/Users/alexanderhuth/Code/bb-play-harness/.venv/bin/python"
CKPT = "/Users/alexanderhuth/Code/bb-play-harness/.play-artifacts/checkpoints/chain55/0000002999975936.bin"
env = dict(os.environ, BBPLAY_LIB=os.path.join(D, "libbbplay.dylib"), OMP_NUM_THREADS="1",
           PYTHONPATH=os.path.join(D, "src"))
for name, first, games in (("tail3a", 67, 66), ("tail3b", 133, 67)):
    argv = ["caffeinate", "-i", PY, os.path.join(D, "search_probe_diag.tail2_launched.py"), "tail-collect",
            "--checkpoint", CKPT, "--manifest", os.path.join(D, "src/puffer/config/rewards/r0_poss_half.json"),
            "--out-dir", os.path.join(D, name), "--first-game", str(first), "--games", str(games),
            "--per-class", "15", "--screen-rollouts", "16", "--rollouts", "128", "--seed0", "29100000",
            "--cap", "200"]
    log = open(os.path.join(D, name + ".log"), "w")
    p = subprocess.Popen(argv, cwd=os.path.join(D, "src"), env=env, stdin=subprocess.DEVNULL, stdout=log,
                         stderr=subprocess.STDOUT, start_new_session=True)
    print(name, "pid", p.pid)
