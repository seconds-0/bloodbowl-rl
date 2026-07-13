#!/usr/bin/env python
"""test_bcreg_torch_pufferl.py — validation for the BC-regularized PPO patch.

Verifies the BC-only maintenance patch for
vendor/PufferLib/pufferlib/torch_pufferl.py
(training/torch_pufferl_bcreg.patch; DECISIONS.md D27):

  1. INSTALL CONTRACT: current vendor HEAD's complete BC implementation is
     recognized without patching. On the supported fallback base (current
     HEAD with only BC-owned hunks removed), the patch applies cleanly and
     reconstructs HEAD byte-for-byte without owning action-mask/asymmetry code.
  2. OFF-MODE REGRESSION (bit-identity): with --train.bc-coef 0.0 the installed
     trainer is bit-identical to the reconstructed no-BC base. N seeded epochs
     must produce identical loss dictionaries and final-parameter sha256.
  3. ON-MODE LEARNING: with bc_coef > 0, an explicit BBP2 obs-v4 fixture must
     load, bc_loss must decrease, and the PPO losses must stay finite.

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
import struct
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUFFER = os.path.join(ROOT, "vendor", "PufferLib")
TARGET = os.path.join(PUFFER, "pufferlib", "torch_pufferl.py")
PATCH = os.path.join(ROOT, "training", "torch_pufferl_bcreg.patch")
SENTINEL = "BCREG|"
OBS_V4_SIZE = 2782
ACT_SIZES = (30, 33, 391)
MASK_SIZE = sum(ACT_SIZES)

BC_REQUIRED = (
    "LOCAL PATCH (bloodbowl-rl): BC-regularized PPO",
    "_BC_MAGIC, _BC_VERSIONS, _BC_HEADER_LEN",
    "def _bc_resolve_pairs_dir(",
    "def _bc_load_pairs(",
    "self.bc_coef0 = float(config.get('bc_coef'",
    "self.bc_anneal = bool(config.get('bc_coef_anneal'",
    "bc_coef = self.bc_coef0",
    "bc_loss, bc_acc = _bc_loss_and_acc(",
    "loss = loss + bc_coef * bc_loss",
    "losses['bc_coef'] +=",
)


def has_complete_bcreg(source):
    """Require every runtime integration point, not just the banner marker."""
    return all(snippet in source for snippet in BC_REQUIRED)


def apply_patch_to_source(source, *, reverse=False, check_only=False):
    """Apply the stored patch in an isolated one-file git fixture."""
    with tempfile.TemporaryDirectory(prefix="bcreg-patch-") as td:
        target = os.path.join(td, "pufferlib", "torch_pufferl.py")
        os.makedirs(os.path.dirname(target))
        with open(target, "w") as f:
            f.write(source)
        subprocess.run(["git", "init", "-q"], cwd=td, check=True)
        cmd = ["git", "apply", "--whitespace=nowarn"]
        if reverse:
            cmd.append("--reverse")
        if check_only:
            cmd.append("--check")
        cmd.append(PATCH)
        out = subprocess.run(cmd, cwd=td, capture_output=True, text=True)
        if out.returncode != 0:
            detail = (out.stdout + out.stderr).strip()
            direction = "reverse-apply" if reverse else "apply"
            raise AssertionError(f"BC patch cannot {direction}: {detail}")
        with open(target) as f:
            return f.read()


def install_bcreg(source):
    """Idempotent installer: complete current vendor sources need no patch."""
    if has_complete_bcreg(source):
        return source, False
    apply_patch_to_source(source, check_only=True)
    installed = apply_patch_to_source(source)
    if not has_complete_bcreg(installed):
        raise AssertionError("BC patch applied but runtime integration is incomplete")
    return installed, True


def validate_patch_contract(pristine):
    """Prove current-HEAD idempotency and supported no-BC reinstallation."""
    with open(PATCH) as f:
        patch = f.read()
    added = [line[1:] for line in patch.splitlines()
             if line.startswith("+") and not line.startswith("+++")]
    for fragment in (
        "def apply_action_mask(",
        "self.vec_action_mask =",
        "self.frozen_path =",
        "self.learner_rows =",
    ):
        if any(fragment in line for line in added):
            raise AssertionError(
                f"BC patch duplicates current non-BC runtime: {fragment}")

    if not has_complete_bcreg(pristine):
        raise AssertionError("current vendor HEAD lacks a complete BC implementation")
    recognized, applied = install_bcreg(pristine)
    assert not applied and recognized == pristine, (
        "complete current vendor HEAD must be recognized without patching")

    # The supported fallback base is current HEAD with only BC-owned hunks
    # removed. Action masking/asymmetric training remain owned by vendor HEAD.
    no_bc = apply_patch_to_source(pristine, reverse=True)
    assert not has_complete_bcreg(no_bc), "reverse patch did not remove BC runtime"
    for fragment in ("def apply_action_mask(", "self.vec_action_mask =",
                     "self.frozen_path ="):
        assert fragment in no_bc, f"BC patch wrongly owns {fragment}"

    reinstalled, applied = install_bcreg(no_bc)
    assert applied, "no-BC fallback base was incorrectly treated as complete"
    assert reinstalled == pristine, (
        "fallback patch did not reconstruct the exact current BC runtime")
    return no_bc, reinstalled


def write_obs_v4_fixture(pairs_dir, records=128):
    """Write a small deterministic BBP2 corpus with the exact obs-v4 ABI."""
    os.makedirs(pairs_dir, exist_ok=True)
    path = os.path.join(pairs_dir, "obs-v4-fixture.bbp")
    obs = bytes(OBS_V4_SIZE)
    mask = bytearray(MASK_SIZE)
    offset = 0
    for size in ACT_SIZES:
        # Two legal alternatives per head keep the fixture sparse like the
        # real factored mask while making six CPU updates a strong BC signal.
        mask[offset] = 1
        mask[offset + 1] = 1
        offset += size
    mask = bytes(mask)
    with open(path, "wb") as f:
        f.write(struct.pack("<4sIII", b"BBP1", 2, OBS_V4_SIZE, MASK_SIZE))
        for i in range(records):
            f.write(struct.pack("<IIB3x", i // 16, i, i & 1))
            f.write(obs)
            f.write(mask)
            f.write(struct.pack("<BBH", 0, 0, 0))
    return path


# --------------------------------------------------------------------------
# Inner mode: run N seeded epochs, print losses + parameter hash.
# --------------------------------------------------------------------------
def run_epochs(epochs, bc_coef, pairs_dir, total_agents=64, minibatch=1024):
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
                         bc_pairs_dir=os.path.abspath(pairs_dir), bc_batch=128,
                         total_timesteps=epochs * total_agents *
                         args["train"]["horizon"])

    from pufferlib.torch_pufferl import PuffeRL
    pufferl = PuffeRL.create_pufferl(args)
    assert pufferl._vec.obs_size == OBS_V4_SIZE, (
        f"test vector is obs {pufferl._vec.obs_size}, expected obs-v4 "
        f"{OBS_V4_SIZE}")
    assert tuple(pufferl._vec.act_sizes) == ACT_SIZES
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
def run_child(epochs, bc_coef, pairs_dir):
    out = subprocess.run(
        [sys.executable, os.path.abspath(__file__), "--mode", "run",
         "--epochs", str(epochs), "--bc-coef", str(bc_coef),
         "--pairs-dir", pairs_dir],
        capture_output=True, text=True, cwd=ROOT, timeout=900)
    if out.returncode != 0:
        sys.stderr.write(out.stdout[-4000:] + out.stderr[-4000:])
        raise SystemExit(f"child run failed (bc_coef={bc_coef})")
    return [line[len(SENTINEL):] for line in out.stdout.splitlines()
            if line.startswith(SENTINEL)]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", default="check", choices=["check", "run"])
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--bc-coef", type=float, default=0.0)
    ap.add_argument("--pairs-dir")
    args = ap.parse_args()

    if args.mode == "run":
        if args.pairs_dir:
            run_epochs(args.epochs, args.bc_coef, args.pairs_dir)
        else:
            with tempfile.TemporaryDirectory(prefix="bcreg-obs-v4-") as td:
                write_obs_v4_fixture(td)
                run_epochs(args.epochs, args.bc_coef, td)
        return

    # 1. Maintenance contract: current HEAD is already complete/idempotent;
    # the BC-only fallback patch reconstructs it from a no-BC current base.
    pristine = subprocess.run(
        ["git", "-C", PUFFER, "show", "HEAD:pufferlib/torch_pufferl.py"],
        capture_output=True, text=True, check=True).stdout
    unpatched, patched = validate_patch_contract(pristine)
    print("[1/3] patch contract OK — current HEAD recognized complete; "
          "BC-only fallback cleanly reconstructs it")

    # 2. Off-mode bit-identity: reconstructed no-BC source vs installed BC.
    backup = tempfile.NamedTemporaryFile(delete=False, suffix=".py").name
    shutil.copy2(TARGET, backup)
    try:
        with tempfile.TemporaryDirectory(prefix="bcreg-obs-v4-") as pairs_dir:
            write_obs_v4_fixture(pairs_dir)
            with open(TARGET, "w") as f:
                f.write(unpatched)
            out_pristine = run_child(args.epochs, 0.0, pairs_dir)

            with open(TARGET, "w") as f:
                f.write(patched)
            out_patched_off = run_child(args.epochs, 0.0, pairs_dir)

            if out_pristine != out_patched_off:
                for a, b in zip(out_pristine, out_patched_off):
                    if a != b:
                        print(f"PRISTINE: {a}\nPATCHED:  {b}")
                raise SystemExit(
                    "OFF-MODE REGRESSION: patched(bc_coef=0) != pristine")
            print(f"[2/3] off-mode bit-identity OK — {args.epochs} epochs, "
                  "identical losses, params sha256 "
                  f"{out_pristine[-1].split()[-1][:16]}…")

            # 3. On-mode: bc_loss decreases, PPO losses finite.
            on_epochs = max(args.epochs, 6)
            out_on = run_child(on_epochs, 0.5, pairs_dir)
    finally:
        shutil.copy2(backup, TARGET)
        os.unlink(backup)

    rows = [json.loads(line.split(" ", 1)[1]) for line in out_on
            if line.startswith("losses")]
    bc = [float(r["bc_loss"]) for r in rows]
    accs = [float(r["bc_acc"]) for r in rows]
    for r in rows:
        for k in ("policy_loss", "value_loss", "entropy", "approx_kl"):
            v = float(r[k])
            assert v == v and abs(v) < 1e4, f"PPO loss {k}={v} not sane"
    assert bc[-1] < bc[0], f"bc_loss did not decrease: {bc[0]:.4f} -> {bc[-1]:.4f}"
    print(f"[3/3] on-mode OK — bc_loss {bc[0]:.4f} -> {bc[-1]:.4f} over "
          f"{on_epochs} epochs (acc {accs[0]:.3f} -> {accs[-1]:.3f}); "
          "PPO losses finite")
    print("BC-reg patch validation PASSED")


if __name__ == "__main__":
    main()
