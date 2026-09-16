"""Parity against a recorded fixture (bbplay-parity-fixture-v1).

The rig test runs when native CUDA fixtures are present, at
BBPLAY_PARITY_FIXTURE or by default .play-artifacts/parity/native-20260916
(tools/parity/native_parity_queue.sh output, copied from the rig). It skips
cleanly when no fixture exists. Without it a self-recorded fixture exercises the
format and both checks end to end.
"""
import json
import os

import pytest

from play_harness import parity
from play_harness.policy import load_checkpoint

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RIG_FIXTURE = os.environ.get(
    "BBPLAY_PARITY_FIXTURE",
    os.path.join(ROOT, ".play-artifacts", "parity", "native-20260916"))
RIG_CHECKPOINT = os.environ.get(
    "BBPLAY_PARITY_CHECKPOINT",
    os.path.join(ROOT, ".play-artifacts", "checkpoints", "chain30", "0000002999975936.bin"))


def _rig_fixture_paths():
    if not os.path.isdir(RIG_FIXTURE):
        return []
    paths = []
    for path in parity.find_fixtures(RIG_FIXTURE):
        with open(os.path.join(path, "manifest.json")) as f:
            if str(json.load(f).get("backend", "")).startswith("native-cuda"):
                paths.append(path)
    return paths


def test_self_recorded_fixture_round_trips(tmp_path, best_policy):
    policy, prov = best_policy
    out = parity.record_self_fixture(str(tmp_path / "fx"), policy, seed=77, policy_row=1,
                                     max_steps=700,
                                     checkpoint_sha256=prov.get("checkpoint_sha256"))
    manifest, arrays = parity.load_fixture(out)
    assert arrays["deciding"].sum() > 50 and (1 - arrays["deciding"]).sum() > 50
    worst = parity.check_policy_parity(policy, manifest, arrays)
    assert worst["logprob"] < 1e-5 and worst["value"] < 1e-6 and worst["logits"] == 0.0
    assert parity.check_env_parity(manifest, arrays) is None


@pytest.mark.skipif(not _rig_fixture_paths(),
                    reason=f"no native CUDA fixture under {RIG_FIXTURE} "
                           "(set BBPLAY_PARITY_FIXTURE)")
def test_rig_fixture_parity():
    """Every rig trace must replay byte-identically on the shim and both harness
    kernels must meet parity.ACCEPTANCE against the native CUDA distributions."""
    if not os.path.exists(RIG_CHECKPOINT):
        pytest.skip(f"checkpoint not present: {RIG_CHECKPOINT}")
    paths = _rig_fixture_paths()
    policies, digest = {}, None
    for kernel in os.environ.get("BBPLAY_PARITY_KERNELS", "torch,native").split(","):
        policies[kernel], prov = load_checkpoint(RIG_CHECKPOINT, kernel=kernel)
        digest = prov["checkpoint_sha256"]
    for path in paths:
        manifest, arrays = parity.load_fixture(path)
        assert manifest["precision_bytes"] == 4, "bf16 recordings are not parity evidence"
        assert manifest["checkpoint_sha256"] == digest, path
        for key in ("logits", "support", "terminal"):
            assert key in arrays, f"{path}: rig fixture lacks {key}"
    result = parity.compare_fixtures(paths, policies)
    assert result["env_mismatch_fixtures"] == 0, [
        (f["path"], f["env_first_mismatch_step"]) for f in result["fixtures"]]
    assert result["consistency_violations"] == 0
    assert {f["policy_row"] for f in result["fixtures"]} == {0, 1}, "both seats required"
    assert any((f["terminal_steps"] or 0) > 0 for f in result["fixtures"]), \
        "at least one terminal reset required"
    for kernel, agg in result["kernels"].items():
        assert agg["verdict"]["pass"], (kernel, agg["verdict"], parity.summary_table(result))
