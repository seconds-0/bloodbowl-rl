"""Parity against a recorded fixture (bbplay-parity-fixture-v1).

With BBPLAY_PARITY_FIXTURE=<dir> this checks a real rig recording. Without it
a self-recorded fixture exercises the format and both checks end to end.
"""
import os

import pytest

from play_harness import parity
from play_harness.policy import load_checkpoint


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


@pytest.mark.skipif(not os.environ.get("BBPLAY_PARITY_FIXTURE"),
                    reason="no rig fixture (set BBPLAY_PARITY_FIXTURE)")
def test_rig_fixture_parity():
    manifest, arrays = parity.load_fixture(os.environ["BBPLAY_PARITY_FIXTURE"])
    assert manifest["precision_bytes"] == 4, "bf16 recordings are not parity evidence"
    checkpoint = os.environ["BBPLAY_CHECKPOINT"]
    kernel = os.environ.get("BBPLAY_KERNEL", "native")
    policy, prov = load_checkpoint(checkpoint, kernel=kernel)
    assert prov["checkpoint_sha256"] == manifest["checkpoint_sha256"]
    assert parity.check_env_parity(manifest, arrays) is None
    worst = parity.check_policy_parity(policy, manifest, arrays)
    tol = manifest.get("tolerance", {})
    assert worst["logprob"] <= tol.get("logprob", 1e-4), worst
    assert worst["value"] <= tol.get("value", 1e-4), worst
