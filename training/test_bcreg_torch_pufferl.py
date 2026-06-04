#!/usr/bin/env python
"""test_bcreg_torch_pufferl.py — validation for the BC-regularized PPO patch.

Verifies the local patch to vendor/PufferLib/pufferlib/torch_pufferl.py
(training/torch_pufferl_bcreg.patch; DECISIONS.md D27):

  1. OFF-MODE REGRESSION (bit-identity): with --train.bc-coef 0.0 the patched
     trainer must be bit-identical to pristine upstream. We extract the
     pristine file from the vendored repo's git HEAD, run N seeded epochs
     under pristine and patched code, and require identical per-epoch loss
     dicts (full float precision) and an identical final-parameter sha256.
  2. ON-MODE LEARNING: with bc_coef > 0, bc_loss must decrease over epochs
     and the PPO losses must stay finite.

Determinism notes: the torch backend has no internal seeding, so each
subprocess seeds torch/numpy itself before building anything; the env C side
is PCG-seeded from [env] seed; num_threads=1 + num_buffers=1 + the no-OMP
Mac _C build keep env stepping single-threaded. torch.set_num_threads is
pinned so CPU reduction order is stable.

Run with the PufferLib venv (requires a --float CPU/CUDA _C build):
  vendor/PufferLib/.venv/bin/python training/test_bcreg_torch_pufferl.py
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUFFER = os.path.join(ROOT, "vendor", "PufferLib")
TARGET = os.path.join(PUFFER, "pufferlib", "torch_pufferl.py")
SENTINEL = "BCREG|"


# --------------------------------------------------------------------------
# Inner mode: run N seeded epochs, print losses + parameter hash.
# --------------------------------------------------------------------------
def run_epochs(epochs, bc_coef, total_agents=64, minibatch=1024):
    sys.path.insert(0, PUFFER)
    import numpy as np
    import torch

    torch.set_num_threads(4)
    torch.manual_seed(42)
    np.random.seed(42)

    saved_argv, sys.argv = sys.argv, [sys.argv[0]]  # load_config parses argv
    from pufferlib.pufferl import load_config
    args = load_config("bloodbowl")
    sys.argv = saved_argv

    args["world_size"] = 1
    args["vec"].update(total_agents=total_agents, num_buffers=1, num_threads=1)
    args["train"].update(minibatch_size=minibatch, bc_coef=bc_coef,
                         total_timesteps=epochs * total_agents *
                         args["train"]["horizon"])

    from pufferlib.torch_pufferl import PuffeRL
    pufferl = PuffeRL.create_pufferl(args)
    for _ in range(epochs):
        pufferl.rollouts()
        pufferl.train()
        losses = {k: f"{v:.17g}" for k, v in sorted(pufferl.losses.items())}
        print(f"{SENTINEL}losses {json.dumps(losses)}", flush=True)

    h = hashlib.sha256()
    for name, p in sorted(pufferl.policy.state_dict().items()):
        h.update(name.encode())
        h.update(p.detach().cpu().numpy().tobytes())
    print(f"{SENTINEL}params {h.hexdigest()}", flush=True)
    pufferl.close()


# --------------------------------------------------------------------------
# Orchestrator: pristine-vs-patched off-mode diff + on-mode learning check.
# --------------------------------------------------------------------------
def run_child(epochs, bc_coef):
    out = subprocess.run(
        [sys.executable, os.path.abspath(__file__), "--mode", "run",
         "--epochs", str(epochs), "--bc-coef", str(bc_coef)],
        capture_output=True, text=True, cwd=ROOT, timeout=900)
    if out.returncode != 0:
        sys.stderr.write(out.stdout[-4000:] + out.stderr[-4000:])
        raise SystemExit(f"child run failed (bc_coef={bc_coef})")
    return [l[len(SENTINEL):] for l in out.stdout.splitlines()
            if l.startswith(SENTINEL)]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", default="check", choices=["check", "run"])
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--bc-coef", type=float, default=0.0)
    args = ap.parse_args()

    if args.mode == "run":
        run_epochs(args.epochs, args.bc_coef)
        return

    # 1. Off-mode bit-identity: pristine HEAD file vs patched file, bc_coef 0.
    pristine = subprocess.run(
        ["git", "-C", PUFFER, "show", "HEAD:pufferlib/torch_pufferl.py"],
        capture_output=True, text=True, check=True).stdout
    with open(TARGET) as f:
        patched = f.read()
    if "LOCAL PATCH (bloodbowl-rl): BC-regularized PPO" not in patched:
        raise SystemExit(f"{TARGET} does not contain the BC-reg patch — "
                         "apply training/torch_pufferl_bcreg.patch first")

    backup = tempfile.NamedTemporaryFile(delete=False, suffix=".py").name
    shutil.copy2(TARGET, backup)
    try:
        with open(TARGET, "w") as f:
            f.write(pristine)
        out_pristine = run_child(args.epochs, 0.0)
    finally:
        shutil.copy2(backup, TARGET)
        os.unlink(backup)
    out_patched_off = run_child(args.epochs, 0.0)

    if out_pristine != out_patched_off:
        for a, b in zip(out_pristine, out_patched_off):
            if a != b:
                print(f"PRISTINE: {a}\nPATCHED:  {b}")
        raise SystemExit("OFF-MODE REGRESSION: patched(bc_coef=0) != pristine")
    print(f"[1/2] off-mode bit-identity OK — {args.epochs} epochs, "
          f"identical losses, params sha256 {out_pristine[-1].split()[-1][:16]}…")

    # 2. On-mode: bc_loss decreases, PPO losses finite.
    on_epochs = max(args.epochs, 6)
    out_on = run_child(on_epochs, 0.5)
    rows = [json.loads(l.split(" ", 1)[1]) for l in out_on if l.startswith("losses")]
    bc = [float(r["bc_loss"]) for r in rows]
    accs = [float(r["bc_acc"]) for r in rows]
    for r in rows:
        for k in ("policy_loss", "value_loss", "entropy", "approx_kl"):
            v = float(r[k])
            assert v == v and abs(v) < 1e4, f"PPO loss {k}={v} not sane"
    assert bc[-1] < bc[0], f"bc_loss did not decrease: {bc[0]:.4f} -> {bc[-1]:.4f}"
    print(f"[2/2] on-mode OK — bc_loss {bc[0]:.4f} -> {bc[-1]:.4f} over "
          f"{on_epochs} epochs (acc {accs[0]:.3f} -> {accs[-1]:.3f}); "
          "PPO losses finite")
    print("BC-reg patch validation PASSED")


if __name__ == "__main__":
    main()
