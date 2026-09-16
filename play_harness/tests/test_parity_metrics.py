"""Comparator math and trace format for torch-vs-native parity (parity.py)."""
import ctypes
import json
import os
import re
import shutil
import subprocess

import numpy as np
import pytest
import torch

from play_harness import engine as E
from play_harness import parity as P
from play_harness.policy import random_policy, select_joint

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def _row(fill=0.0):
    return np.full(E.MASK_SIZE, fill, dtype=np.float64)


def _manual_softmax(x):
    x = np.asarray(x, dtype=np.float64)
    e = np.exp(x - x.max())
    return e / e.sum()


# ------------------------------------------------------------------ math
def test_masked_log_softmax_matches_manual_and_is_neg_inf_outside():
    x = np.array([1.0, 3.0, -2.0, 5.0])
    m = np.array([True, True, False, False])
    got = P.masked_log_softmax(x, m)
    want = np.log(_manual_softmax([1.0, 3.0]))
    assert np.allclose(got[:2], want, atol=1e-12)
    assert np.isneginf(got[2:]).all()


def test_masked_log_softmax_large_logits_stay_finite():
    x = np.array([1488.0, 1487.0, -900.0])
    got = P.masked_log_softmax(x, np.ones(3, dtype=bool))
    assert np.isfinite(got).all()
    assert abs(np.exp(got).sum() - 1.0) < 1e-12


def test_masked_log_softmax_refuses_empty_mask():
    with pytest.raises(ValueError):
        P.masked_log_softmax(np.zeros(4), np.zeros(4, dtype=bool))


def test_head_probs_normalize_per_head_masked_and_unmasked():
    rng = np.random.default_rng(3)
    logits = rng.normal(size=(5, E.MASK_SIZE)) * 20
    masks = rng.random((5, E.MASK_SIZE)) < 0.3
    for a, b in P.HEAD_BOUNDS:
        masks[:, a] = True  # every head keeps at least one legal value
    for probs in (P.head_probs(logits), P.head_probs(logits, masks)):
        for a, b in P.HEAD_BOUNDS:
            assert np.allclose(probs[:, a:b].sum(axis=1), 1.0, atol=1e-12)
    masked = P.head_probs(logits, masks)
    assert (masked[~masks] == 0.0).all()


def test_per_head_tv_identical_disjoint_and_hand_value():
    p = P.head_probs(_row())
    assert np.all(P.per_head_tv(p, p) == 0.0)
    a, b = _row(), _row()
    a[0], b[1] = 1.0, 1.0
    pa = P.head_probs(a, (a > 0) | (np.arange(E.MASK_SIZE) >= 30))
    pb = P.head_probs(b, (b > 0) | (np.arange(E.MASK_SIZE) >= 30))
    assert P.per_head_tv(pa, pb)[0] == pytest.approx(1.0)
    q1, q2 = np.zeros(E.MASK_SIZE), np.zeros(E.MASK_SIZE)
    q1[[0, 1]] = [0.7, 0.3]
    q2[[0, 1]] = [0.4, 0.6]
    assert P.per_head_tv(q1, q2)[0] == pytest.approx(0.3)


def _support(tuples):
    return np.array([E.pack_tuple(*t) for t in tuples], dtype=np.uint32)


TUPLES = [(9, 32, 10), (9, 32, 11), (12, 3, 20), (12, 3, 21), (12, 4, 20), (8, 32, 390)]


def test_joint_distribution_is_product_of_conditionals():
    rng = np.random.default_rng(7)
    logits = rng.normal(size=E.MASK_SIZE) * 3
    uniq, probs = P.joint_distribution(logits, _support(TUPLES + [TUPLES[0]]))
    assert uniq.shape[0] == len(TUPLES)  # duplicates collapse
    assert probs.sum() == pytest.approx(1.0, abs=1e-12)
    heads = P.split_heads(logits)
    for packed, p in zip(uniq, probs):
        tup = E.unpack_tuple(packed)
        masks = P.conditional_masks(_support(TUPLES), tup)
        manual = 1.0
        for h in range(3):
            lp = P.masked_log_softmax(heads[h], masks[h])
            manual *= np.exp(lp[tup[h]])
        assert p == pytest.approx(manual, rel=1e-12)


@pytest.mark.parametrize("head", ["float64", "native_fp32", "harness_fp32"])
def test_joint_distribution_sums_to_one_for_every_head_arithmetic(head):
    rng = np.random.default_rng(13)
    logits = (rng.normal(size=E.MASK_SIZE) * 400).astype(np.float32)
    _, probs = P.joint_distribution(logits, _support(TUPLES), head)
    assert probs.sum() == pytest.approx(1.0, abs=1e-6)
    assert (probs >= 0).all()


def test_joint_tv_zero_symmetric_bounded_and_type_only_change():
    rng = np.random.default_rng(11)
    la = rng.normal(size=E.MASK_SIZE)
    lb = la + rng.normal(size=E.MASK_SIZE) * 0.5
    sup = _support(TUPLES)
    assert P.joint_tv(la, la, sup) == 0.0
    assert P.joint_tv(la, lb, sup) == pytest.approx(P.joint_tv(lb, la, sup))
    assert 0.0 <= P.joint_tv(la, lb, sup) <= 1.0
    # Changing only type logits: joint TV equals the type-head TV.
    lc = la.copy()
    lc[9] += 2.0
    types = np.zeros(E.MASK_SIZE, dtype=bool)
    types[[8, 9, 12]] = True
    types[30:] = True
    tv_head0 = P.per_head_tv(P.head_probs(la, types), P.head_probs(lc, types))[0]
    assert P.joint_tv(la, lc, sup) == pytest.approx(tv_head0, rel=1e-10)


def test_conditional_masks_match_select_joint_masks():
    rng = np.random.default_rng(5)
    logits = torch.from_numpy(rng.normal(size=E.MASK_SIZE).astype(np.float32))
    sup = _support(TUPLES)
    tup, _, masks = select_joint(logits, sup, mode="argmax")
    for got, want in zip(P.conditional_masks(sup, tup), masks):
        assert np.array_equal(got, want)


def test_unsampled_branch_support_difference_is_invisible_to_masks():
    """The documented limit of the native mask check: two supports that differ
    only on a branch the sampler did not take yield identical conditional masks."""
    a = _support([(9, 32, 10), (12, 3, 20)])
    b = _support([(9, 32, 10), (12, 3, 21)])
    for ma, mb in zip(P.conditional_masks(a, (9, 32, 10)), P.conditional_masks(b, (9, 32, 10))):
        assert np.array_equal(ma, mb)
    rng = np.random.default_rng(2)
    logits = rng.normal(size=E.MASK_SIZE)
    assert P.joint_distribution(logits, a)[0].tolist() != P.joint_distribution(logits, b)[0].tolist()


def test_joint_logprob_float64_matches_torch_sampler():
    rng = np.random.default_rng(9)
    logits = rng.normal(size=E.MASK_SIZE).astype(np.float32) * 4
    sup = _support(TUPLES)
    tup, lp, masks = select_joint(torch.from_numpy(logits), sup, mode="argmax")
    assert P.joint_logprob(logits, masks, tup) == pytest.approx(lp, abs=1e-5)


# ------------------------------------------------------ native fp32 sampler
def test_native_fp32_codex_two_logit_example():
    x = np.array([1000.0, 1000.0], dtype=np.float32)
    m = np.array([True, True])
    eff, lse, probs32 = P.native_fp32_head(x, m)
    assert float(lse) == pytest.approx(1000.693176, abs=1e-4)
    assert eff[0] == pytest.approx(0.49998546, abs=5e-8)
    assert eff[1] == pytest.approx(0.50001454, abs=5e-8)
    assert eff.sum() == pytest.approx(1.0, abs=1e-12)
    f64 = P.float64_head(x, m)
    assert f64.tolist() == [0.5, 0.5]
    assert 0.5 * np.abs(eff - f64).sum() == pytest.approx(1.45e-5, abs=2e-7)
    # the harness sampler (torch fp32 log_softmax) does not share the bias
    assert 0.5 * np.abs(P.harness_fp32_head(x, m) - f64).sum() < 1e-7


@pytest.fixture(scope="module")
def sampler_ref(tmp_path_factory):
    cc = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    if cc is None:
        pytest.skip("no C compiler")
    out = tmp_path_factory.mktemp("ref") / "libsampler_ref.so"
    subprocess.run([cc, "-O0", "-ffp-contract=off", "-shared", "-fPIC",
                    os.path.join(HERE, "native_sampler_ref.c"), "-o", str(out), "-lm"],
                   check=True, capture_output=True)
    lib = ctypes.CDLL(str(out))
    fp = ctypes.POINTER(ctypes.c_float)
    lib.head_sample.argtypes = [fp, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int, ctypes.c_float,
                                fp, fp, fp]
    lib.head_sample.restype = ctypes.c_int

    def run(x, m, u):
        x = np.ascontiguousarray(x, dtype=np.float32)
        mm = np.ascontiguousarray(m, dtype=np.uint8)
        cum = np.zeros(x.shape[0], dtype=np.float32)
        lse, logp = ctypes.c_float(), ctypes.c_float()
        a = lib.head_sample(x.ctypes.data_as(fp), mm.ctypes.data_as(ctypes.POINTER(ctypes.c_ubyte)),
                            x.shape[0], ctypes.c_float(u), ctypes.byref(lse), cum.ctypes.data_as(fp),
                            ctypes.byref(logp))
        return a, lse.value, cum, logp.value
    return run


def _random_heads(n, seed):
    rng = np.random.default_rng(seed)
    heads = []
    for i in range(n):
        size = E.ACT_SIZES[i % 3]
        scale = (1.0, 50.0, 1000.0)[(i // 3) % 3]
        x = (rng.normal(size=size) * scale).astype(np.float32)
        m = rng.random(size) < rng.uniform(0.05, 0.9)
        m[rng.integers(size)] = True
        if i % 5 == 0:  # exact ties at the top
            top = np.nonzero(m)[0][:3]
            x[top] = x[m].max()
        heads.append((x, m))
    return heads


def test_native_fp32_head_matches_c_transliteration(sampler_ref):
    ulp1 = float(np.spacing(np.float32(1.0)))
    for x, m in _random_heads(240, seed=21):
        eff, lse, probs32 = P.native_fp32_head(x, m)
        _, c_lse, c_cum, _ = sampler_ref(x, m, 0.5)
        assert abs(float(lse) - c_lse) <= 2 * float(np.spacing(np.float32(abs(c_lse) + 1)))
        cum = np.add.accumulate(probs32[m], dtype=np.float32)
        assert np.abs(cum - c_cum[m]).max() <= 8 * ulp1 * max(1, m.sum() // 16)
        assert eff.sum() == pytest.approx(1.0, abs=1e-12)
    two = np.array([1000.0, 1000.0], dtype=np.float32)
    _, c_lse, c_cum, _ = sampler_ref(two, np.array([1, 1]), 0.99999)
    eff, _, _ = P.native_fp32_head(two, np.array([True, True]))
    assert eff[0] == pytest.approx(float(c_cum[0]), abs=ulp1)
    assert 1.0 - float(c_cum[0]) == pytest.approx(eff[1], abs=ulp1)


def test_native_fp32_sample_head_matches_c_selection(sampler_ref):
    rng = np.random.default_rng(22)
    checked = 0
    for x, m in _random_heads(120, seed=23):
        _, _, probs32 = P.native_fp32_head(x, m)
        cum = np.add.accumulate(probs32[m], dtype=np.float32)
        for u in rng.random(20).astype(np.float32):
            if np.abs(cum - u).min() < 1e-5:
                continue  # a one-unit difference in expf may move a boundary draw
            a, lp = P.native_fp32_sample_head(x, m, u)
            c_a, c_lse, _, c_logp = sampler_ref(x, m, float(u))
            assert a == c_a
            assert lp == pytest.approx(c_logp, abs=4 * float(np.spacing(np.float32(abs(c_lse) + 1))))
            checked += 1
    assert checked > 1500


def test_native_fp32_logprob_matches_select_joint_on_moderate_logits():
    rng = np.random.default_rng(31)
    logits = (rng.normal(size=E.MASK_SIZE) * 3).astype(np.float32)
    sup = _support(TUPLES)
    tup, lp, masks = select_joint(torch.from_numpy(logits), sup, mode="argmax")
    assert P.native_fp32_logprob(logits, masks, tup) == pytest.approx(lp, abs=1e-5)


# ---------------------------------------------------------------- format
def _synthetic_arrays(t_steps=6, seed=0):
    rng = np.random.default_rng(seed)
    sup_rows, masks, actions, deciding, env_tuple = [], [], [], [], []
    for t in range(t_steps):
        if t % 2 == 0:
            sup = _support(TUPLES)
            tup = TUPLES[t % len(TUPLES)]
            deciding.append(1)
        else:
            sup = np.array([P.NONE_PACKED], dtype=np.uint32)
            tup = (0, 32, 390)
            deciding.append(0)
        sup_rows.append(sup)
        masks.append(np.concatenate(P.conditional_masks(sup, tup)).astype(np.uint8))
        actions.append(tup)
        env_tuple.append(TUPLES[t % len(TUPLES)])
    logits = rng.normal(size=(t_steps, E.MASK_SIZE)).astype(np.float32)
    arrays = {
        "obs": rng.integers(0, 255, size=(t_steps, E.OBS_SIZE), dtype=np.uint8),
        "reset": np.array([1] + [0] * (t_steps - 1), dtype=np.uint8),
        "terminal": np.array([1] + [0] * (t_steps - 1), dtype=np.uint8),
        "deciding": np.array(deciding, dtype=np.uint8),
        "masks": np.stack(masks),
        "actions": np.array(actions, dtype=np.int32),
        "value": rng.normal(size=t_steps).astype(np.float32),
        "env_tuple": np.array(env_tuple, dtype=np.int32),
        "logits": logits,
    }
    arrays["logprob"] = np.array([P.native_fp32_logprob(logits[t], P.split_masks(arrays["masks"][t]),
                                                        arrays["actions"][t])
                                  for t in range(t_steps)], dtype=np.float32)
    arrays["support"], arrays["support_offsets"] = P.pack_support(sup_rows)
    arrays["probs"] = P.head_probs(logits, arrays["masks"]).astype(np.float32)
    return arrays


def _manifest(row=0, backend="synthetic"):
    return {"schema": P.SCHEMA, "backend": backend, "checkpoint_sha256": None,
            "module_sha256": None, "precision_bytes": 4, "kernel": None, "policy_row": row,
            "env": {"seed": 1, "episode": 0}, "opponent": "none", "tolerance": {}}


def test_pack_support_round_trip():
    rows = [np.array([1, 2, 3], dtype=np.uint32), np.array([7], dtype=np.uint32)]
    flat, off = P.pack_support(rows)
    arrays = {"support": flat, "support_offsets": off}
    assert off.tolist() == [0, 3, 4]
    assert P.support_at(arrays, 0).tolist() == [1, 2, 3]
    assert P.support_at(arrays, 1).tolist() == [7]


def test_save_load_round_trip_find_and_refuse_overwrite(tmp_path):
    arrays = _synthetic_arrays()
    root = tmp_path / "root"
    P.save_fixture(str(root / "a-row0"), _manifest(0), arrays)
    P.save_fixture(str(root / "a-row1"), _manifest(1), arrays)
    assert [os.path.basename(p) for p in P.find_fixtures(str(root))] == ["a-row0", "a-row1"]
    assert P.find_fixtures(str(root / "a-row1")) == [str(root / "a-row1")]
    manifest, loaded = P.load_fixture(str(root / "a-row0"))
    assert manifest["policy_row"] == 0
    for k, v in arrays.items():
        assert np.array_equal(loaded[k], v), k
    with pytest.raises(FileExistsError):
        P.save_fixture(str(root / "a-row0"), _manifest(0), arrays)


def test_load_refuses_wrong_schema(tmp_path):
    arrays = _synthetic_arrays()
    P.save_fixture(str(tmp_path / "fx"), _manifest(), arrays)
    with open(tmp_path / "fx" / "manifest.json") as f:
        m = json.load(f)
    m["schema"] = "other"
    with open(tmp_path / "fx" / "manifest.json", "w") as f:
        json.dump(m, f)
    with pytest.raises(ValueError):
        P.load_fixture(str(tmp_path / "fx"))


@pytest.mark.parametrize("mutate", [
    lambda a: a.update(obs=a["obs"][:, :100]),
    lambda a: a.update(obs=a["obs"].astype(np.int16)),
    lambda a: a.pop("value"),
    lambda a: a.update(logits=a["logits"][:-1]),
    lambda a: a.pop("support_offsets"),
    lambda a: a.update(support_offsets=a["support_offsets"][::-1].copy()),
])
def test_validate_arrays_rejects_malformed(mutate):
    arrays = _synthetic_arrays()
    mutate(arrays)
    with pytest.raises(ValueError):
        P.validate_arrays(arrays)


def test_consistency_clean_on_synthetic():
    cons = P.fixture_consistency(_synthetic_arrays())
    assert cons["violations"] == 0, cons
    assert cons["masks_vs_support_mismatch_steps"] == 0
    assert cons["recorded_logprob_vs_recorded_logits_max_abs"] < 1e-5
    assert cons["recorded_logprob_vs_native_fp32_sampler_max_abs"] == 0.0
    assert cons["recorded_probs_vs_recorded_logits_max_abs"] < 1e-6


@pytest.mark.parametrize("kind,mutate", [
    ("masks_differ_from_support", lambda a: a["masks"].__setitem__((0, 5), 1 - a["masks"][0, 5])),
    ("action_outside_support", lambda a: a["actions"].__setitem__((0, 2), 77)),
    ("waiting_row_not_singleton_none", lambda a: a["actions"].__setitem__((1, 0), 9)),
    ("reset_differs_from_terminal", lambda a: a["reset"].__setitem__(3, 1)),
    ("step0_not_reset", lambda a: a["reset"].__setitem__(0, 0)),
])
def test_consistency_detects_violations(kind, mutate):
    arrays = _synthetic_arrays()
    mutate(arrays)
    cons = P.fixture_consistency(arrays)
    assert cons["violations"] >= 1
    assert kind in {d["kind"] for d in cons["details"]}
    if kind == "masks_differ_from_support":
        assert cons["masks_vs_support_mismatch_steps"] == 1


def test_compare_logits_identical_and_step0_offset():
    arrays = _synthetic_arrays()
    same = P.compare_logits(arrays, arrays["logits"], arrays["value"])
    for key in ("logit_max_abs_diff", "head_prob_max_abs_diff", "masked_head_prob_max_abs_diff",
                "value_max_abs_diff", "forward_joint_tv_max", "forward_joint_tv_mean"):
        assert same[key] == 0.0, key
    # identical logits still leave the native-fp32 vs torch-fp32 sampler arithmetic gap
    assert 0.0 <= same["sampler_joint_tv_max"] < 1e-6
    assert same["logprob_max_abs_diff"] < 1e-5
    assert same["unmasked_head_argmax_agreement"] == [1.0, 1.0, 1.0]
    assert same["first_step_logit_abs_diff_over_tolerance"] is None
    shifted = arrays["logits"].copy()
    shifted[0, 9] += 0.5  # a type logit that is in the step-0 support
    diff = P.compare_logits(arrays, shifted, arrays["value"])
    assert diff["logit_step0_max_abs_diff"] == pytest.approx(0.5, abs=1e-6)
    assert diff["first_step_logit_abs_diff_over_tolerance"] == 0
    assert diff["forward_joint_tv_max"] > 1e-3
    assert diff["sampler_joint_tv_max"] == pytest.approx(diff["forward_joint_tv_max"], rel=1e-3)
    agg = P.aggregate([same, diff])
    assert agg["logit_step0_max_abs_diff"] == diff["logit_step0_max_abs_diff"]
    assert agg["forward_joint_tv_mean"] == pytest.approx(
        (same["forward_joint_tv_sum"] + diff["forward_joint_tv_sum"]) / (2 * same["deciding_steps"]))
    v = P.verdict(agg, consistency_violations=0, env_mismatches=0)
    assert not v["pass"] and not v["checks"]["logit_step0_max_abs_diff"]
    assert P.verdict(P.aggregate([same]), 0, 0)["pass"]
    assert not P.verdict(P.aggregate([same]), 1, 0)["pass"]
    assert not P.verdict(P.aggregate([same]), 0, 1)["pass"]
    assert not P.verdict(P.aggregate([same]), 0, 0, masks_vs_support_mismatch_steps=1)["pass"]


def test_compare_logits_sampler_family_sees_fp32_tie_bias():
    """Codex's example inside a fixture: equal logits of 1000 on two legal types.
    The forward family reads zero; the sampler family reads the native bias."""
    arrays = _synthetic_arrays()
    logits = np.zeros_like(arrays["logits"])
    logits[:, 8] = logits[:, 9] = logits[:, 12] = 1000.0
    arrays["logits"] = logits
    arrays["logprob"] = np.array([P.native_fp32_logprob(logits[t], P.split_masks(arrays["masks"][t]),
                                                        arrays["actions"][t])
                                  for t in range(logits.shape[0])], dtype=np.float32)
    out = P.compare_logits(arrays, logits, arrays["value"])
    assert out["forward_joint_tv_max"] == 0.0
    assert out["sampler_joint_tv_max"] > 1e-5


# ------------------------------------------------------ suite completeness
RUNS = ("md4096_s42", "md150_s43")


def _write_suite(root, runs=RUNS, envs=(0, 1, 2, 3), dry_run=False):
    arrays = _synthetic_arrays(t_steps=2)
    doc = {"dry_run": dry_run, "runs": {}}
    for run in runs:
        os.makedirs(os.path.join(root, run), exist_ok=True)
        with open(os.path.join(root, run, "RUN.json"), "w") as f:
            json.dump({"fixtures": []}, f)
        for e in envs:
            for r in (0, 1):
                P.save_fixture(os.path.join(root, run, f"{run}-env{e}-row{r}"),
                               _manifest(r, backend="native-cuda-fp32"), arrays)
        doc["runs"][run] = {"fixtures": 8, "consistency_violations": 0}
    with open(os.path.join(root, "RESULT_COMPLETE.json"), "w") as f:
        json.dump(doc, f)


def test_check_native_suite_complete_and_each_failure(tmp_path):
    root = str(tmp_path / "suite")
    _write_suite(root)
    assert P.check_native_suite(root, RUNS) == []
    shutil.rmtree(os.path.join(root, "md150_s43", "md150_s43-env3-row1"))
    assert any("missing fixture" in p for p in P.check_native_suite(root, RUNS))
    root2 = str(tmp_path / "partial")
    _write_suite(root2, runs=RUNS[:1])
    assert any("runs" in p for p in P.check_native_suite(root2, RUNS))
    root3 = str(tmp_path / "dry")
    _write_suite(root3, dry_run=True)
    assert any("dry_run" in p for p in P.check_native_suite(root3, RUNS))
    root4 = str(tmp_path / "unfinished")
    _write_suite(root4)
    os.remove(os.path.join(root4, "RESULT_COMPLETE.json"))
    assert P.check_native_suite(root4, RUNS) == [f"missing {root4}/RESULT_COMPLETE.json"]


def test_queue_runs_match_the_suite_expected_by_the_rig_test():
    from play_harness.tests.test_parity_fixture import EXPECTED_RUNS
    src = open(os.path.join(ROOT, "tools", "parity", "native_parity_queue.sh")).read()
    line = re.search(r'^RUNS=\((.*)\)$', src, re.M).group(1)
    assert tuple(re.findall(r'"(\S+) ', line)) == EXPECTED_RUNS


# ------------------------------------------------------- end to end (CPU)
def test_selfplay_trace_env_parity_across_terminals_and_kernel_compare(tmp_path):
    policy = random_policy(seed=4, scale=0.05, kernel="native")
    paths = P.record_selfplay_trace(str(tmp_path / "fx"), policy, "t", seed=123, episode=1,
                                    steps=160, max_decisions=40, sampling_seed=3)
    assert len(paths) == 2
    for path in paths:
        manifest, arrays = P.load_fixture(path)
        assert arrays["reset"][1:].sum() >= 2, "trace must cross terminals"
        assert 0 < arrays["deciding"].sum() < arrays["deciding"].shape[0]
        assert P.fixture_consistency(arrays)["violations"] == 0
        assert P.check_env_parity(manifest, arrays) is None
        assert P.find_episode(manifest, arrays) == 1
        t_reset = int(np.nonzero(arrays["reset"][1:])[0][0]) + 1
        bad = dict(arrays)
        bad["obs"] = arrays["obs"].copy()
        bad["obs"][t_reset + 2, 5] ^= 1
        assert P.check_env_parity(manifest, bad) == t_reset + 2
        bad = dict(arrays)
        bad["reset"] = arrays["reset"].copy()
        bad["reset"][t_reset] = 0
        assert P.check_env_parity(manifest, bad) == t_reset
    policies = {"native": policy, "torch": random_policy(seed=4, scale=0.05, kernel="torch")}
    result = P.compare_fixtures(paths, policies)
    native = result["kernels"]["native"]
    assert native["logit_max_abs_diff"] == 0.0 and native["forward_joint_tv_max"] == 0.0
    assert native["value_max_abs_diff"] == 0.0
    assert native["sampler_joint_tv_max"] < 1e-5
    assert native["verdict"]["pass"], native["verdict"]
    torch_k = result["kernels"]["torch"]
    assert torch_k["forward_joint_tv_max"] < 1e-4 and torch_k["verdict"]["pass"]
    assert result["env_mismatch_fixtures"] == 0 and result["consistency_violations"] == 0
    assert result["masks_vs_support_mismatch_steps"] == 0
    json.dumps(result, allow_nan=False)
