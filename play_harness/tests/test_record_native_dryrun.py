"""The rig recorder's dry-run backend end to end (tools/parity/record_native.py):
lockstep, the native-support mirror pointer interface, and the writer."""
import hashlib
import importlib.util
import json
import os

import pytest

from play_harness import parity as P

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="module")
def recorder():
    spec = importlib.util.spec_from_file_location(
        "record_native", os.path.join(ROOT, "tools", "parity", "record_native.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def blob(tmp_path_factory):
    """Any file works for the dry run; its sha256 is only pinned and recorded."""
    path = tmp_path_factory.mktemp("ck") / "c.bin"
    path.write_bytes(b"dry run checkpoint")
    return str(path), hashlib.sha256(path.read_bytes()).hexdigest()


def _run(recorder, blob, out, *extra):
    return recorder.main(["--backend", "dry-run", "--live", "/nonexistent-live",
                          "--checkpoint", blob[0], "--expect-sha256", blob[1], "--out", str(out),
                          "--trace", "t", "--seed", "42", "--steps", "90", "--envs", "0,1",
                          "--max-decisions", "40", *extra])


def test_dry_run_records_native_support_through_the_mirror(recorder, blob, tmp_path):
    out = tmp_path / "rec"
    assert _run(recorder, blob, out) == 0
    run = json.load(open(out / "RUN.json"))
    assert run["native_support_capture"]["available"] is True
    # the fake vec starts one reset behind, like create_static_vec vs create_pufferl
    assert run["native_support_capture"]["resets_to_align"] == 1
    assert run["consistency_violations"] == 0
    paths = P.find_fixtures(str(out))
    assert len(paths) == 4
    for path in paths:
        manifest, arrays = P.load_fixture(path)
        assert "native_support" in arrays
        cons = P.fixture_consistency(arrays)
        assert cons["native_vs_shim_support_mismatch_steps"] == 0
        assert cons["masks_vs_support_mismatch_steps"] == 0
        assert cons["recorded_logprob_vs_native_fp32_sampler_max_abs"] == 0.0
        assert arrays["terminal"][1:].sum() >= 1
        assert P.check_env_parity(manifest, arrays) is None


def test_dry_run_corrupted_native_support_is_a_violation(recorder, blob, tmp_path):
    out = tmp_path / "rec"
    assert _run(recorder, blob, out, "--dry-corrupt-support-step", "7") == 4
    run = json.load(open(out / "RUN.json"))
    bad = [f for f in run["fixtures"] if f["native_vs_shim_support_mismatch_steps"]]
    assert [(f["env_index"], f["policy_row"], f["native_vs_shim_support_mismatch_steps"])
            for f in bad] == [(0, 0, 1)]


def test_dry_run_mirror_failure_is_recorded_not_fatal(recorder, blob, tmp_path):
    out = tmp_path / "rec"
    assert _run(recorder, blob, out, "--dry-mirror-fail") == 0
    run = json.load(open(out / "RUN.json"))
    assert run["native_support_capture"]["available"] is False
    assert "injected" in run["native_support_capture"]["error"]
    _, arrays = P.load_fixture(P.find_fixtures(str(out))[0])
    assert "native_support" not in arrays and "support" in arrays


def test_native_only_flags_are_refused(recorder, blob, tmp_path):
    rc = recorder.main(["--backend", "native", "--checkpoint", blob[0], "--expect-sha256", blob[1],
                        "--out", str(tmp_path / "x"), "--trace", "t", "--dry-mirror-fail"])
    assert rc == 2
