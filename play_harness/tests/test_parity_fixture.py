"""Parity against a recorded fixture (bbplay-parity-fixture-v1).

Rig fixtures live at BBPLAY_PARITY_FIXTURE, by default
.play-artifacts/parity/native-20260916 (the output of
tools/parity/native_parity_queue.sh copied from the rig).

  test_rig_suite_parity         the queued suite: RESULT_COMPLETE.json, every
                                planned run, env and seat, then the acceptance
                                gates for both kernels. Skips until the suite is
                                present; fails on a partial suite.
  test_rig_partial_fixture_integrity
                                any native fixtures, complete or not: env replay
                                and recorder consistency only. No distribution
                                gates and no completeness claim.

Without fixtures both skip cleanly; a self-recorded fixture exercises the format
and both checks end to end.
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
# Must equal RUNS in tools/parity/native_parity_queue.sh (guarded by
# test_parity_metrics.test_queue_runs_match_the_suite_expected_by_the_rig_test).
EXPECTED_RUNS = ("md4096_s42", "md150_s43")
EXPECTED_ENVS = (0, 1, 2, 3)
TRUNCATED_RUN = "md150_s43"


def _native_fixture_paths():
    if not os.path.isdir(RIG_FIXTURE):
        return []
    paths = []
    for path in parity.find_fixtures(RIG_FIXTURE):
        with open(os.path.join(path, "manifest.json")) as f:
            if str(json.load(f).get("backend", "")).startswith("native-cuda"):
                paths.append(path)
    return paths


def _suite_present():
    return os.path.isfile(os.path.join(RIG_FIXTURE, "RESULT_COMPLETE.json"))


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


@pytest.mark.skipif(not _native_fixture_paths(),
                    reason=f"no native CUDA fixture under {RIG_FIXTURE}")
def test_rig_partial_fixture_integrity():
    """Whatever native fixtures exist replay byte-identically and are internally
    consistent. This makes no claim about suite completeness or distributions."""
    for path in _native_fixture_paths():
        manifest, arrays = parity.load_fixture(path)
        assert manifest["precision_bytes"] == 4, "bf16 recordings are not parity evidence"
        assert parity.check_env_parity(manifest, arrays) is None, path
        cons = parity.fixture_consistency(arrays)
        assert cons["violations"] == 0, (path, cons["details"])


@pytest.mark.skipif(not _suite_present(),
                    reason=f"no completed native suite (RESULT_COMPLETE.json) under {RIG_FIXTURE}")
def test_rig_suite_parity():
    """The complete queued suite replays byte-identically on the shim and both
    harness kernels meet parity.ACCEPTANCE against the native distributions."""
    problems = parity.check_native_suite(RIG_FIXTURE, EXPECTED_RUNS, EXPECTED_ENVS)
    assert not problems, problems
    if not os.path.exists(RIG_CHECKPOINT):
        pytest.skip(f"checkpoint not present: {RIG_CHECKPOINT}")
    paths = _native_fixture_paths()
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
        if os.path.basename(os.path.dirname(path)) == TRUNCATED_RUN:
            assert arrays["terminal"][1:].sum() > 0, f"{path}: truncated run has no terminal"
    result = parity.compare_fixtures(paths, policies)
    assert result["env_mismatch_fixtures"] == 0, [
        (f["path"], f["env_first_mismatch_step"]) for f in result["fixtures"]]
    assert result["consistency_violations"] == 0
    assert result["masks_vs_support_mismatch_steps"] == 0
    natural = [f for f in result["fixtures"] if not f["path"].startswith(TRUNCATED_RUN)]
    assert any((f["terminal_steps"] or 0) > 0 for f in natural), \
        "the default-budget run must include a natural terminal"
    for kernel, agg in result["kernels"].items():
        assert agg["verdict"]["pass"], (kernel, agg["verdict"], parity.summary_table(result))
