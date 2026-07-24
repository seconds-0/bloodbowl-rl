"""Contracts for the recurrent CUDA qualification smoke test.

Every test here maps to a bug this repo actually hit: recurrent state that was
not zero at construction, cudagraph capture that diverged from the graph-off
path, PPO sampling frozen rows at prio_alpha=0, a compiled module whose obs ABI
did not match its source tree, reward counters that were silently absent rather
than zero, and a CUDA runtime that reported no device because `_C` was imported
before the first CUDART call.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import pathlib
import subprocess
import tempfile
import textwrap
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from tools import puffer_cuda_runtime as cuda_runtime


ROOT = pathlib.Path(__file__).resolve().parents[1]
PATCH = ROOT / "training" / "puffer_recurrent_cuda_qualification.patch"
PRIO_PATCH = ROOT / "training" / "puffer_frozen_prio_mask.patch"
LEAGUE_PATCH = ROOT / "training" / "selfplay_league.patch"
INSTALLER = ROOT / "tools" / "install_puffer_env.sh"
RUNNER = ROOT / "tools" / "qualify_recurrent_cuda.py"
CUDA_RUNTIME_WRAPPER = ROOT / "tools" / "puffer_cuda_runtime.py"


def cuda_runtime_evidence() -> dict:
    return {
        "schema_version": 1,
        "library": {
            "requested_soname": "libcudart.so.12",
            "resolved_path": "/usr/lib/x86_64-linux-gnu/libcudart.so.12.4.127",
            "sha256": "d" * 64,
        },
        "cuda_visible_devices": "0",
        "before_extension_import": {
            "stage": "before_extension_import",
            "return_code": 0,
            "device_count": 1,
            "error_name": "cudaSuccess",
            "error_string": "no error",
        },
        "after_extension_import": {
            "stage": "after_extension_import",
            "return_code": 0,
            "device_count": 1,
            "error_name": "cudaSuccess",
            "error_string": "no error",
        },
    }


def load_runner():
    spec = importlib.util.spec_from_file_location("qualify_recurrent_cuda", RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {RUNNER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class QualificationValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.q = load_runner()

    # ------------------------------------------------------- recurrent state

    def test_state_gate_requires_every_primary_and_frozen_buffer_exactly_zero(self):
        clean = {
            "num_banks": 2,
            "num_buffers": 1,
            "entries": [
                {"bank": 0, "buffer": 0, "shape": [1, 2, 4],
                 "elements": 8, "active_rows": 1, "active_elements": 4,
                 "nonzero": 0, "nonfinite": 0, "max_abs": 0.0,
                 "active_nonzero": 0, "active_nonfinite": 0,
                 "active_max_abs": 0.0},
                {"bank": 1, "buffer": 0, "shape": [1, 1, 4],
                 "elements": 4, "active_rows": 1, "active_elements": 4,
                 "nonzero": 0, "nonfinite": 0, "max_abs": 0.0,
                 "active_nonzero": 0, "active_nonfinite": 0,
                 "active_max_abs": 0.0},
            ]
        }
        self.q.validate_zero_state(clean, expected_banks=2, expected_buffers=1)
        for key, value in (("nonzero", 1), ("nonfinite", 1), ("max_abs", 1e-8)):
            bad = json.loads(json.dumps(clean))
            bad["entries"][1][key] = value
            with self.subTest(key=key), self.assertRaises(self.q.QualificationError):
                self.q.validate_zero_state(
                    bad, expected_banks=2, expected_buffers=1)
        # A missing frozen bank/buffer is a coverage failure, not a pass.
        partial = json.loads(json.dumps(clean))
        del partial["entries"][1]
        with self.assertRaisesRegex(
            self.q.QualificationError, "state coverage mismatch"
        ):
            self.q.validate_zero_state(
                partial, expected_banks=2, expected_buffers=1)

    def test_nonzero_state_gate_requires_activity_in_every_bank_buffer(self):
        report = {"num_banks": 2, "num_buffers": 1, "entries": [
            {"bank": 0, "buffer": 0, "shape": [1, 2, 4],
             "elements": 8, "active_rows": 1, "active_elements": 4,
             "nonzero": 2, "nonfinite": 0, "max_abs": 0.5,
             "active_nonzero": 2, "active_nonfinite": 0,
             "active_max_abs": 0.5},
            {"bank": 1, "buffer": 0, "shape": [1, 1, 4],
             "elements": 4, "active_rows": 1, "active_elements": 4,
             "nonzero": 1, "nonfinite": 0, "max_abs": 0.25,
             "active_nonzero": 1, "active_nonfinite": 0,
             "active_max_abs": 0.25},
        ]}
        self.q.validate_nonzero_state(
            report, expected_banks=2, expected_buffers=1)
        report["entries"][1]["active_nonzero"] = 0
        report["entries"][1]["active_max_abs"] = 0.0
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_nonzero_state(
                report, expected_banks=2, expected_buffers=1)

    def test_row_partition_is_derived_from_recorded_bank_layout(self):
        report = {
            "num_banks": 2, "num_buffers": 2, "agents_per_buffer": 4,
            "bank_layout": [0, 2, 4],
        }
        primary, frozen = self.q.derive_row_partition(report, total_agents=8)
        self.assertEqual(primary, {0, 1, 4, 5})
        self.assertEqual(frozen, {2, 3, 6, 7})
        for bad_layout in ([0, 4], [0, 0, 4], [1, 2, 4], [0, 2, 5]):
            with self.subTest(layout=bad_layout), self.assertRaises(
                    self.q.QualificationError):
                self.q.derive_row_partition(
                    dict(report, bank_layout=bad_layout), total_agents=8)
        # One bank means no real frozen partition to prove disjointness against.
        with self.assertRaisesRegex(
            self.q.QualificationError, "real frozen bank"
        ):
            self.q.derive_row_partition(
                {"num_banks": 1, "num_buffers": 2, "agents_per_buffer": 4,
                 "bank_layout": [0, 4]},
                total_agents=8,
            )

    # ------------------------------------------------- rollout / PPO evidence

    def test_snapshot_comparison_is_exact_for_discrete_and_tolerant_for_float(self):
        left = {
            "observations": np.array([[[1, 2]]], dtype=np.float32),
            "actions": np.array([[[2, 3, 4]]], dtype=np.float32),
            "terminals": np.array([[1]], dtype=np.float32),
            "action_mask": np.array([[[1, 0, 1]]], dtype=np.float32),
            "rewards": np.array([[0]], dtype=np.float32),
            "values": np.array([[0.125]], dtype=np.float32),
            "logprobs": np.array([[-0.75]], dtype=np.float32),
        }
        right = {key: value.copy() for key, value in left.items()}
        right["values"][0, 0] += 5e-7
        self.q.compare_snapshots(left, right, atol=1e-6, require_all_terminal=True)
        right["actions"][0, 0, 0] = 1
        with self.assertRaises(self.q.QualificationError):
            self.q.compare_snapshots(left, right, atol=1e-6)

    def test_snapshot_rejects_nonfinite_shape_dtype_and_missing_fields(self):
        base = {
            "observations": np.zeros((1, 2, 3), np.float32),
            "actions": np.zeros((1, 2, 3), np.float32),
            "terminals": np.ones((1, 2), np.float32),
            "action_mask": np.ones((1, 2, 4), np.float32),
            "rewards": np.zeros((1, 2), np.float32),
            "values": np.zeros((1, 2), np.float32),
            "logprobs": np.zeros((1, 2), np.float32),
        }
        for mutate in ("missing", "shape", "dtype", "nan"):
            other = {key: value.copy() for key, value in base.items()}
            if mutate == "missing":
                del other["values"]
            elif mutate == "shape":
                other["values"] = np.zeros((2, 1), np.float32)
            elif mutate == "dtype":
                other["values"] = np.zeros((1, 2), np.float64)
            else:
                other["values"][0, 0] = np.nan
            with self.subTest(mutate=mutate), self.assertRaises(
                    self.q.QualificationError):
                self.q.compare_snapshots(base, other, atol=1e-6)

    def test_decoder_parity_requires_matching_bank_buffer_coverage(self):
        left = {
            "decoder_bank_0_buffer_0": np.zeros((2, 3), np.float32),
            "decoder_bank_1_buffer_0": np.zeros((2, 3), np.float32),
        }
        right = {key: value.copy() for key, value in left.items()}
        self.q.compare_decoder_outputs(left, right, atol=1e-6)
        del right["decoder_bank_1_buffer_0"]
        with self.assertRaisesRegex(
            self.q.QualificationError, "coverage mismatch"
        ):
            self.q.compare_decoder_outputs(left, right, atol=1e-6)

    def test_ratio_aggregation_requires_finite_unity_and_complete_primary_coverage(self):
        calls = [
            {"selected_rows": np.array([0, 0], np.int32),
             "ratios": np.ones((2, 2), np.float32)},
            {"selected_rows": np.array([1, 0], np.int32),
             "ratios": np.ones((2, 2), np.float32)},
        ]
        verdict = self.q.validate_ratio_calls(
            calls, primary_rows={0, 1}, frozen_rows={2, 3}, atol=1e-6)
        self.assertEqual(verdict["covered_primary_rows"], [0, 1])

        with self.assertRaises(self.q.QualificationError):
            self.q.validate_ratio_calls(
                calls[:1], primary_rows={0, 1}, frozen_rows={2, 3}, atol=1e-6)
        bad = [{"selected_rows": np.array([0], np.int32),
                "ratios": np.array([[1.01]], np.float32)}]
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_ratio_calls(
                bad, primary_rows={0}, frozen_rows={1}, atol=1e-6)
        nonfinite = [{"selected_rows": np.array([0], np.int32),
                      "ratios": np.array([[np.nan]], np.float32)}]
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_ratio_calls(
                nonfinite, primary_rows={0}, frozen_rows={1}, atol=1e-6)
        frozen = [{"selected_rows": np.array([2], np.int32),
                   "ratios": np.ones((1, 2), np.float32)}]
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_ratio_calls(
                frozen, primary_rows={0}, frozen_rows={2}, atol=1e-6)

    def test_weight_identity_and_throughput_comparison_are_fail_closed(self):
        digest = hashlib.sha256(b"same weights").hexdigest()
        self.q.validate_weight_identity(digest, digest)
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_weight_identity(digest, "0" * 64)

        baseline = {
            "host": "rtx2070", "gpu": "RTX 2070", "precision_bytes": 4,
            "config": {"cudagraphs": 10, "vec": {"total_agents": 4096}},
            "steps_per_second": 1000.0,
            "hard_integrity_zero": True,
            "steps": 1000, "elapsed_seconds": 1.0,
            "median_rollout_seconds": 0.1, "p95_rollout_seconds": 0.2,
            "hard_integrity": {
                key: 0.0 for key in self.q.HARD_INTEGRITY_KEYS
            },
            "utilization": {},
        }
        candidate = dict(baseline, steps=950, steps_per_second=950.0)
        self.q.validate_throughput(
            candidate, baseline, max_regression_fraction=0.10)
        candidate["steps"] = 899
        candidate["steps_per_second"] = 899.0
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_throughput(
                candidate, baseline, max_regression_fraction=0.10)
        # A faster number measured on a different GPU or config is not a pass.
        for key, value in (
            ("gpu", "different"),
            ("host", "other-host"),
            ("config", {"cudagraphs": 10, "vec": {"total_agents": 512}}),
        ):
            candidate = dict(
                baseline, steps=2000, steps_per_second=2000.0, **{key: value}
            )
            with self.subTest(key=key), self.assertRaisesRegex(
                self.q.QualificationError, key
            ):
                self.q.validate_throughput(
                    candidate, baseline, max_regression_fraction=0.10)
        # Missing integrity counters cannot be read as zero counters.
        candidate = dict(baseline, hard_integrity={})
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_throughput(
                candidate, baseline, max_regression_fraction=0.10)

    # -------------------------------------------------- integrity counters

    def test_hard_integrity_rejects_redundant_nonzero_reward_counters(self):
        self.assertEqual(self.q.HARD_INTEGRITY_KEYS, (
            "illegal_frac",
            "reward_clip_frac",
            "reward_clip_frac_nonzero",
            "reward_clip_excess",
            "reward_clip_signed_delta",
            "reward_clipped_samples_per_episode",
            "reward_clip_terminal_samples_per_episode",
            "reward_clip_nonterminal_samples_per_episode",
            "reward_nonfinite_frac",
            "reward_nonfinite_samples_per_episode",
            "reward_clip_episodes",
            "reward_nonfinite_episodes",
            "reward_component_mismatch_samples_per_episode",
            "reward_component_nonfinite_samples_per_episode",
            "error_episodes",
            "demo_fallbacks",
        ))
        counters = (
            "reward_clip_signed_delta",
            "reward_clipped_samples_per_episode",
            "reward_clip_terminal_samples_per_episode",
            "reward_clip_nonterminal_samples_per_episode",
            "reward_nonfinite_samples_per_episode",
        )
        for key in counters:
            integrity = {
                field: 0.0 for field in self.q.HARD_INTEGRITY_KEYS
            }
            integrity[key] = 1e-12
            with self.subTest(key=key), self.assertRaisesRegex(
                    self.q.QualificationError, key):
                self.q.validate_hard_integrity(integrity)
        missing = {
            field: 0.0 for field in self.q.HARD_INTEGRITY_KEYS
            if field != "reward_clip_signed_delta"
        }
        with self.assertRaisesRegex(
                self.q.QualificationError, "reward_clip_signed_delta"):
            self.q.validate_hard_integrity(missing)

    def test_every_transition_cell_requires_bound_exact_zero_integrity(self):
        self.assertEqual(
            self.q.TRANSITION_CELL_KINDS,
            frozenset({
                "rollout", "terminal_auto", "terminal_control", "ratio",
                "throughput",
            }),
        )
        integrity = {key: 0.0 for key in self.q.HARD_INTEGRITY_KEYS}
        for kind in sorted(self.q.TRANSITION_CELL_KINDS):
            payload = {
                "hard_integrity": dict(integrity),
                "hard_integrity_zero": True,
            }
            record = {
                "kind": kind,
                **({"throughput": payload} if kind == "throughput" else payload),
            }
            with self.subTest(kind=kind):
                self.q.validate_transition_cell_integrity(record, kind)

            bad = json.loads(json.dumps(record))
            target = bad["throughput"] if kind == "throughput" else bad
            target["hard_integrity"]["reward_clip_signed_delta"] = 1e-12
            with self.subTest(kind=kind, mutation="nonzero"), self.assertRaisesRegex(
                    self.q.QualificationError, "reward_clip_signed_delta"):
                self.q.validate_transition_cell_integrity(bad, kind)

            missing = json.loads(json.dumps(record))
            target = missing["throughput"] if kind == "throughput" else missing
            del target["hard_integrity"]
            with self.subTest(kind=kind, mutation="missing"), self.assertRaises(
                    self.q.QualificationError):
                self.q.validate_transition_cell_integrity(missing, kind)

        with self.assertRaisesRegex(
                self.q.QualificationError, "does not execute transitions"):
            self.q.validate_transition_cell_integrity(
                {"kind": "construction"}, "construction"
            )

    def test_integrity_probe_runs_bounded_rollouts_and_binds_record(self):
        integrity = {key: 0.0 for key in self.q.HARD_INTEGRITY_KEYS}
        backend = mock.Mock()
        backend.log.return_value = {"env": integrity}
        pufferl = object()
        record = {}

        self.q.bind_transition_integrity(
            backend, pufferl, record, additional_rollouts=16
        )

        self.assertEqual(backend.rollouts.call_count, 16)
        backend.log.assert_called_once_with(pufferl)
        self.assertEqual(record["hard_integrity"], integrity)
        self.assertIs(record["hard_integrity_zero"], True)

    # --------------------------------------------------- compiled provenance

    def test_qualification_surface_rejects_either_partial_binding(self):
        for binding in self.q.QUALIFICATION_SURFACE_BINDINGS:
            with self.subTest(binding=binding), self.assertRaisesRegex(
                self.q.QualificationError, "qualification surface is partial"
            ):
                self.q.qualification_surface_state(
                    SimpleNamespace(**{binding: object()})
                )
        self.assertIs(self.q.qualification_surface_state(SimpleNamespace()), False)
        self.assertIs(
            self.q.qualification_surface_state(SimpleNamespace(**{
                binding: object()
                for binding in self.q.QUALIFICATION_SURFACE_BINDINGS
            })),
            True,
        )

    def test_backend_identity_changes_with_selfplay_and_rejects_its_absence(self):
        self.assertIn("pufferlib/selfplay.py", self.q.BACKEND_SOURCE_FILES)
        with tempfile.TemporaryDirectory() as temporary:
            puffer = pathlib.Path(temporary)
            for index, relative in enumerate(self.q.BACKEND_SOURCE_FILES):
                path = puffer / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"surface-{index}\n".encode())
            before = self.q.backend_source_hash(puffer)
            selfplay = puffer / "pufferlib/selfplay.py"
            selfplay.write_bytes(b"changed-selfplay-semantics\n")
            self.assertNotEqual(before, self.q.backend_source_hash(puffer))
            selfplay.unlink()
            with self.assertRaises(self.q.QualificationError):
                self.q.backend_source_hash(puffer)

    def test_compiled_digest_must_equal_source_and_installed_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            puffer = pathlib.Path(temporary)
            for index, relative in enumerate(self.q.BACKEND_SOURCE_FILES):
                path = puffer / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"candidate-{index}\n".encode())
            module = puffer / "pufferlib/_C.so"
            module.write_bytes(b"candidate-module\n")
            snapshot = puffer / "ocean/bloodbowl/.content_hash"
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_text("b" * 64 + "\n", encoding="ascii")

            compiled = self.q.backend_source_hash(puffer)
            backend = SimpleNamespace(
                exact_action_source_hash=compiled,
                environment_source_hash="b" * 64,
                observation_abi="obs-v6",
                observation_version=6,
                action_abi="exact-joint-v1",
                precision_bytes=4,
                env_name="bloodbowl",
                qualification_recurrent_state=object(),
                qualification_snapshot=object(),
            )
            identity = self.q._module_identity(backend, module, puffer)
            self.assertIs(identity["qualification_surface"], True)
            self.assertEqual(identity["backend_sources_sha256"], compiled)
            self.assertEqual(
                identity["installed_snapshot_sha256"],
                identity["environment_sha256"],
            )
            self.q.validate_module_identity(identity)

            # A module built from other bytes than the tree it sits in fails,
            # and so does one whose installed snapshot lags its own build.
            with self.assertRaisesRegex(
                self.q.QualificationError, "backend source digest"
            ):
                self.q.validate_module_identity(
                    dict(identity, compiled_backend_sha256="c" * 64)
                )
            with self.assertRaisesRegex(
                self.q.QualificationError, "installed environment digest"
            ):
                self.q.validate_module_identity(
                    dict(identity, installed_snapshot_sha256="c" * 64)
                )
            with self.assertRaisesRegex(
                self.q.QualificationError, "backend_sources_sha256"
            ):
                incomplete = dict(identity)
                del incomplete["backend_sources_sha256"]
                self.q.validate_module_identity(incomplete)

    def test_module_identity_requires_exact_bloodbowl_obs_v6_fp32_lineage(self):
        digest = "a" * 64
        identity = {
            "module": "/puffer/pufferlib/_C.so",
            "puffer_root": "/puffer",
            "module_sha256": digest,
            "compiled_backend_sha256": digest,
            "backend_sources_sha256": digest,
            "environment_sha256": "b" * 64,
            "installed_snapshot_sha256": "b" * 64,
            "observation_abi": "obs-v6",
            "observation_version": 6,
            "action_abi": "exact-joint-v1",
            "precision_bytes": 4,
            "compiled_env": "bloodbowl",
            "qualification_surface": True,
        }
        self.q.validate_module_identity(identity)
        # obs-v4, obs-v5 and obs-v6 are all 2782 bytes: only this provenance
        # separates them, and BF16 cannot satisfy the ratio contract.
        for key, value in (
            ("compiled_env", "other"),
            ("observation_abi", "obs-v4"),
            ("observation_version", 4),
            ("action_abi", "marginal"),
            ("precision_bytes", 2),
            ("environment_sha256", "bad"),
            ("qualification_surface", False),
            ("module", "/elsewhere/pufferlib/_C.so"),
        ):
            with self.subTest(key=key), self.assertRaises(
                    self.q.QualificationError):
                self.q.validate_module_identity(dict(identity, **{key: value}))

    def test_cells_must_share_one_module_identity(self):
        identity = {"module_sha256": "a" * 64}
        with mock.patch.object(
            self.q, "validate_module_identity", side_effect=lambda value: dict(value)
        ):
            self.assertEqual(
                self.q._require_same_identity(
                    [{"identity": identity}, {"identity": dict(identity)}]
                ),
                identity,
            )
            with self.assertRaisesRegex(
                self.q.QualificationError, "identity drifted between cells"
            ):
                self.q._require_same_identity(
                    [{"identity": identity}, {"identity": {"module_sha256": "b" * 64}}]
                )

    # ------------------------------------------------------- CUDA init order

    def test_backend_load_preflights_cudart_before_importing_the_extension(self):
        source = RUNNER.read_text(encoding="utf-8")
        body = source[source.index("def _load_backend("):source.index("def _module_identity(")]
        begin = body.index("begin_cuda_runtime_preflight()")
        imported = body.index("from pufferlib import _C")
        finish = body.index("finish_cuda_runtime_preflight(")
        self.assertLess(begin, imported, "CUDART must initialize before _C import")
        self.assertLess(imported, finish, "device count must be rechecked after import")

    def test_cuda_runtime_evidence_is_fail_closed(self):
        evidence = cuda_runtime_evidence()
        self.q.validate_cuda_runtime_evidence(evidence)
        mutations = (
            ("before_extension_import", "return_code", 100),
            ("before_extension_import", "device_count", 0),
            ("after_extension_import", "return_code", 100),
            ("after_extension_import", "device_count", 2),
            ("library", "sha256", "bad"),
        )
        for section, key, value in mutations:
            mutated = json.loads(json.dumps(evidence))
            mutated[section][key] = value
            with self.subTest(section=section, key=key), self.assertRaises(
                self.q.CudaRuntimePreflightError
            ):
                self.q.validate_cuda_runtime_evidence(mutated)
        malformed = json.loads(json.dumps(evidence))
        malformed["unexpected"] = True
        with self.assertRaises(cuda_runtime.CudaRuntimePreflightError):
            cuda_runtime.validate_cuda_runtime_evidence(malformed)
        malformed = json.loads(json.dumps(evidence))
        del malformed["cuda_visible_devices"]
        with self.assertRaises(cuda_runtime.CudaRuntimePreflightError):
            cuda_runtime.validate_cuda_runtime_evidence(malformed)
        malformed = json.loads(json.dumps(evidence))
        malformed["before_extension_import"]["error_name"] = "cudaErrorNoDevice"
        with self.assertRaises(cuda_runtime.CudaRuntimePreflightError):
            cuda_runtime.validate_cuda_runtime_evidence(malformed)

        with tempfile.TemporaryDirectory() as temporary:
            library = pathlib.Path(temporary) / "libcudart.so.12.4.127"
            library.write_bytes(b"frozen CUDA runtime")
            current = cuda_runtime_evidence()
            current["library"]["resolved_path"] = str(library.resolve())
            current["library"]["sha256"] = hashlib.sha256(
                library.read_bytes()
            ).hexdigest()
            cuda_runtime.validate_cuda_runtime_library_file(current)
            library.write_bytes(b"drifted CUDA runtime")
            with self.assertRaisesRegex(
                cuda_runtime.CudaRuntimePreflightError, "digest drifted"
            ):
                cuda_runtime.validate_cuda_runtime_library_file(current)

    def test_cuda_runtime_native_probe_checks_return_code_and_count(self):
        runtime = SimpleNamespace()

        def device_count(pointer):
            pointer._obj.value = 1
            return 0

        runtime.cudaGetDeviceCount = mock.Mock(side_effect=device_count)
        runtime.cudaGetErrorName = mock.Mock(return_value=b"cudaSuccess")
        runtime.cudaGetErrorString = mock.Mock(return_value=b"no error")
        with mock.patch.object(
            cuda_runtime.ctypes, "CDLL", return_value=runtime
        ), mock.patch.object(
            cuda_runtime, "_resolved_cuda_runtime_path",
            return_value=pathlib.Path(__file__),
        ):
            handle, evidence = cuda_runtime.begin_cuda_runtime_preflight()
            completed = cuda_runtime.finish_cuda_runtime_preflight(handle, evidence)
        self.assertEqual(completed["before_extension_import"]["device_count"], 1)
        self.assertEqual(completed["after_extension_import"]["device_count"], 1)
        self.assertEqual(runtime.cudaGetDeviceCount.call_count, 2)

        def no_device(pointer):
            pointer._obj.value = 1
            return 100

        runtime.cudaGetDeviceCount = mock.Mock(side_effect=no_device)
        runtime.cudaGetErrorName = mock.Mock(return_value=b"cudaErrorNoDevice")
        runtime.cudaGetErrorString = mock.Mock(return_value=b"no device")
        with mock.patch.object(
            cuda_runtime.ctypes, "CDLL", return_value=runtime
        ), mock.patch.object(
            cuda_runtime, "_resolved_cuda_runtime_path",
            return_value=pathlib.Path(__file__),
        ), self.assertRaisesRegex(
            cuda_runtime.CudaRuntimePreflightError, "return_code=100"
        ):
            cuda_runtime.begin_cuda_runtime_preflight()

    def test_qualification_cells_require_one_cuda_runtime_identity(self):
        evidence = cuda_runtime_evidence()
        records = [
            {"cuda_runtime_preflight": evidence},
            {"cuda_runtime_preflight": json.loads(json.dumps(evidence))},
        ]
        self.assertEqual(self.q._require_same_cuda_runtime(records), evidence)
        records[1]["cuda_runtime_preflight"]["library"]["sha256"] = "e" * 64
        with self.assertRaisesRegex(
            self.q.QualificationError, "CUDA runtime drifted"
        ):
            self.q._require_same_cuda_runtime(records)

    def test_puffer_entrypoint_preflights_before_import_and_rechecks_after(self):
        events = []
        handle = object()
        evidence = cuda_runtime_evidence()

        def begin():
            events.append("begin")
            return handle, evidence

        def import_main():
            events.append("import")

            def puffer_main():
                events.append("main")
                return 0

            return puffer_main

        def finish(observed_handle, observed_evidence):
            self.assertIs(observed_handle, handle)
            self.assertIs(observed_evidence, evidence)
            events.append("finish")
            return evidence

        def publish(observed_evidence):
            self.assertIs(observed_evidence, evidence)
            events.append("publish")
            return {"schema_version": 1}

        with mock.patch.object(
            cuda_runtime, "begin_cuda_runtime_preflight", side_effect=begin
        ), mock.patch.object(
            cuda_runtime, "_import_puffer_main", side_effect=import_main
        ), mock.patch.object(
            cuda_runtime, "finish_cuda_runtime_preflight", side_effect=finish
        ), mock.patch.object(
            cuda_runtime, "validate_cuda_runtime_evidence"
        ), mock.patch.object(
            cuda_runtime, "_publish_runtime_evidence", side_effect=publish
        ), mock.patch("builtins.print"):
            self.assertEqual(cuda_runtime.main(), 0)
        self.assertEqual(
            events, ["begin", "import", "finish", "publish", "main"]
        )

        with mock.patch.object(
            cuda_runtime,
            "begin_cuda_runtime_preflight",
            side_effect=cuda_runtime.CudaRuntimePreflightError("no device"),
        ), mock.patch.object(cuda_runtime, "_import_puffer_main") as imported, \
                self.assertRaises(cuda_runtime.CudaRuntimePreflightError):
            cuda_runtime.main()
        imported.assert_not_called()

        puffer_main = mock.Mock(return_value=0)
        with mock.patch.object(
            cuda_runtime,
            "begin_cuda_runtime_preflight",
            return_value=(handle, evidence),
        ), mock.patch.object(
            cuda_runtime, "_import_puffer_main", return_value=puffer_main
        ), mock.patch.object(
            cuda_runtime,
            "finish_cuda_runtime_preflight",
            side_effect=cuda_runtime.CudaRuntimePreflightError("poisoned"),
        ), self.assertRaises(cuda_runtime.CudaRuntimePreflightError):
            cuda_runtime.main()
        puffer_main.assert_not_called()
        wrapper_source = CUDA_RUNTIME_WRAPPER.read_text(encoding="utf-8")
        self.assertIn("from pufferlib import _C", wrapper_source)
        self.assertIn("_remove_script_directory_from_import_path()", wrapper_source)

        puffer_main = mock.Mock(return_value=0)
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
            cuda_runtime,
            "begin_cuda_runtime_preflight",
            return_value=(handle, evidence),
        ), mock.patch.object(
            cuda_runtime, "_import_puffer_main", return_value=puffer_main
        ), mock.patch.object(
            cuda_runtime,
            "finish_cuda_runtime_preflight",
            return_value=evidence,
        ), mock.patch.object(
            cuda_runtime, "validate_cuda_runtime_evidence"
        ), self.assertRaisesRegex(
            cuda_runtime.CudaRuntimePreflightError, "paths are mandatory"
        ):
            cuda_runtime.main()
        puffer_main.assert_not_called()

    def test_trainer_wrapper_publishes_its_own_runtime_evidence_before_main(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary).resolve()
            manifest_path = root / "run.manifest.json"
            evidence_path = root / "run.cuda-runtime.json"
            evidence = cuda_runtime_evidence()
            manifest = {
                "schema_version": 1,
                "cuda_runtime_wrapper_sha256": hashlib.sha256(
                    CUDA_RUNTIME_WRAPPER.read_bytes()
                ).hexdigest(),
                "cuda_runtime_evidence_status": "pending",
                "cuda_runtime_evidence_path": str(evidence_path),
                "cuda_launcher_probe_library_path": evidence["library"][
                    "resolved_path"
                ],
                "cuda_launcher_probe_library_sha256": evidence["library"][
                    "sha256"
                ],
                "cuda_launcher_probe_device_count": "1",
                "cuda_launcher_probe_visible_devices": "0",
            }
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8"
            )
            events = []
            puffer_main = mock.Mock(side_effect=lambda: events.append("main"))
            with mock.patch.dict(
                os.environ,
                {
                    "PUFFER_CUDA_RUNTIME_MANIFEST": str(manifest_path),
                    "PUFFER_CUDA_RUNTIME_EVIDENCE": str(evidence_path),
                },
                clear=False,
            ), mock.patch.object(
                cuda_runtime,
                "begin_cuda_runtime_preflight",
                return_value=(object(), evidence),
            ), mock.patch.object(
                cuda_runtime, "_import_puffer_main", return_value=puffer_main
            ), mock.patch.object(
                cuda_runtime,
                "finish_cuda_runtime_preflight",
                return_value=evidence,
            ), mock.patch.object(
                cuda_runtime, "validate_cuda_runtime_evidence"
            ), mock.patch("builtins.print"):
                self.assertEqual(cuda_runtime.main(), 0)
            self.assertEqual(events, ["main"])
            finalized = json.loads(manifest_path.read_text(encoding="utf-8"))
            sidecar = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(finalized["cuda_runtime_evidence_status"], "accepted")
            self.assertEqual(finalized["cuda_runtime_evidence"], evidence)
            self.assertEqual(sidecar["runtime_evidence"], evidence)

            # The trainer's own evidence must match the launcher's expectation.
            puffer_main.reset_mock()
            finalized["cuda_runtime_evidence_status"] = "pending"
            finalized["cuda_launcher_probe_device_count"] = "2"
            finalized.pop("cuda_runtime_evidence")
            finalized.pop("cuda_runtime_evidence_sha256")
            manifest_path.write_text(
                json.dumps(finalized, sort_keys=True) + "\n", encoding="utf-8"
            )
            evidence_path.unlink()
            with mock.patch.dict(
                os.environ,
                {
                    "PUFFER_CUDA_RUNTIME_MANIFEST": str(manifest_path),
                    "PUFFER_CUDA_RUNTIME_EVIDENCE": str(evidence_path),
                },
                clear=False,
            ), mock.patch.object(
                cuda_runtime,
                "begin_cuda_runtime_preflight",
                return_value=(object(), evidence),
            ), mock.patch.object(
                cuda_runtime, "_import_puffer_main", return_value=puffer_main
            ), mock.patch.object(
                cuda_runtime,
                "finish_cuda_runtime_preflight",
                return_value=evidence,
            ), mock.patch.object(
                cuda_runtime, "validate_cuda_runtime_evidence"
            ), mock.patch("builtins.print"), self.assertRaises(
                cuda_runtime.CudaRuntimePreflightError
            ):
                cuda_runtime.main()
            puffer_main.assert_not_called()

    # ------------------------------------------------- graph capture / config

    def test_graph_capture_requires_production_warmup_boundary(self):
        args = mock.Mock(
            seed=271828,
            throughput_agents=2048,
            throughput_buffers=2,
            throughput_threads=16,
            throughput_horizon=64,
            throughput_hidden=512,
            throughput_layers=3,
            throughput_minibatch_size=16384,
        )
        self.assertEqual(self.q.DEFAULT_CUDAGRAPH_WARMUP_EPOCHS, 10)
        for kind in self.q.CELL_KINDS:
            with self.subTest(kind=kind):
                self.assertEqual(self.q.validate_cell_cudagraphs(kind, 10), 10)
                self.assertEqual(
                    self.q._cell_config(kind, 10, args)["cudagraphs"], 10
                )
                # 0 captures the graph before CUDA lazy initialization.
                with self.assertRaises(self.q.QualificationError):
                    self.q.validate_cell_cudagraphs(kind, 0)
        self.assertEqual(self.q.validate_cell_cudagraphs("rollout", -1), -1)
        for kind in set(self.q.CELL_KINDS) - {"rollout"}:
            with self.subTest(graph_off_kind=kind), self.assertRaises(
                self.q.QualificationError
            ):
                self.q.validate_cell_cudagraphs(kind, -1)

    def test_cell_rejects_zero_warmup_before_runtime_dispatch(self):
        argv = [
            "cell",
            "--puffer-root", "/tmp/puffer",
            "--kind", "throughput",
            "--cudagraphs", "0",
            "--output-json", "/tmp/throughput.json",
        ]
        with mock.patch.object(self.q, "run_cell") as run_cell, self.assertRaises(
            self.q.QualificationError
        ):
            self.q.main(argv)
        run_cell.assert_not_called()

    def test_cell_record_must_report_the_graph_mode_it_ran(self):
        record = {
            "config": {"cudagraphs": 10},
            "cuda_runtime_preflight": cuda_runtime_evidence(),
        }
        self.q.validate_cell_cudagraph_record(record, expected=10)
        for observed in (0, -1, 10.0, None):
            with self.subTest(observed=observed), self.assertRaises(
                self.q.QualificationError
            ):
                self.q.validate_cell_cudagraph_record(
                    dict(record, config={"cudagraphs": observed}), expected=10
                )
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_cell_cudagraph_record(
                {"config": {"cudagraphs": 10}, "cuda_runtime_preflight": {}},
                expected=10,
            )

    def test_throughput_minibatch_matches_rollout_quantum(self):
        args = mock.Mock(
            seed=271828,
            throughput_agents=2048,
            throughput_buffers=2,
            throughput_threads=16,
            throughput_horizon=64,
            throughput_hidden=512,
            throughput_layers=3,
            throughput_minibatch_size=16384,
        )
        config = self.q._cell_config("throughput", 10, args)
        self.assertEqual(
            config["vec"]["total_agents"] * config["train"]["horizon"], 131072
        )
        self.assertEqual(config["train"]["minibatch_size"], 16384)
        self.assertEqual(config["cudagraphs"], 10)
        self.assertEqual(self.q.DEFAULT_THROUGHPUT_MINIBATCH_SIZE, 16384)
        self.assertEqual(
            self.q.parse_args([
                "cell",
                "--puffer-root", "/tmp/puffer",
                "--kind", "throughput",
                "--cudagraphs", "10",
                "--output-json", "/tmp/throughput.json",
            ]).throughput_minibatch_size,
            16384,
        )

    def test_qualification_minibatch_must_fit_rollout_contract(self):
        base = {
            "cudagraphs": 10,
            "seed": 271828,
            "total_agents": 2048,
            "num_buffers": 2,
            "num_threads": 16,
            "horizon": 64,
            "max_decisions": 64,
            "hidden_size": 512,
            "num_layers": 3,
            "frozen_banks": 1,
            "frozen_bank_pct": 0.1,
            "learning_rate": 0.0,
        }
        for invalid in (0, 6144, 16383, 24576, 131136):
            with self.subTest(minibatch_size=invalid), self.assertRaises(
                self.q.QualificationError
            ):
                self.q.qualification_args(**base, minibatch_size=invalid)

    def test_invalid_throughput_minibatch_fails_before_worker_dispatch(self):
        argv = [
            "cell",
            "--puffer-root", "/tmp/puffer",
            "--kind", "throughput",
            "--cudagraphs", "10",
            "--output-json", "/tmp/throughput.json",
            "--throughput-agents", "2048",
            "--throughput-horizon", "64",
            "--throughput-minibatch-size", "6144",
        ]
        with mock.patch.object(self.q, "run_cell") as run_cell, self.assertRaises(
            self.q.QualificationError
        ):
            self.q.main(argv)
        run_cell.assert_not_called()

    # ------------------------------------------------------- driver behaviour

    def test_worker_preserves_explicit_venv_python_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            base_python = root / "managed-python"
            base_python.write_text("binary placeholder\n", encoding="utf-8")
            venv_python = root / "venv" / "bin" / "python"
            venv_python.parent.mkdir(parents=True)
            venv_python.symlink_to(base_python)
            puffer = root / "puffer"
            output = root / "output"
            puffer.mkdir()
            output.mkdir()
            args = mock.Mock(
                python=venv_python,
                puffer_root=puffer,
                seed=271828,
                ratio_call_limit=64,
                throughput_agents=2048,
                throughput_buffers=2,
                throughput_threads=16,
                throughput_horizon=64,
                throughput_hidden=512,
                throughput_layers=3,
                throughput_minibatch_size=16384,
                throughput_warmup_rollouts=2,
                throughput_timed_rollouts=8,
                cell_timeout_seconds=1800,
            )
            record = {
                "accepted": True,
                "config": {"cudagraphs": 10},
                "cuda_runtime_preflight": cuda_runtime_evidence(),
            }
            with mock.patch.object(
                self.q.subprocess, "run",
                return_value=mock.Mock(returncode=0, stdout="", stderr=""),
            ) as run, mock.patch.object(self.q, "_read_json", return_value=record):
                self.q._run_worker(
                    args, kind="construction", name="construction",
                    cudagraphs=10, output=output,
                )
            command = run.call_args.args[0]
            # Resolving the symlink would run the base interpreter, not the venv.
            self.assertEqual(command[0], str(venv_python.absolute()))
            self.assertNotEqual(command[0], str(base_python.resolve()))
            self.assertEqual(command[command.index("--cudagraphs") + 1], "10")
            self.assertEqual(
                command[command.index("--throughput-minibatch-size") + 1], "16384"
            )

    def test_worker_rejects_a_cell_that_ran_a_different_graph_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            python = root / "python"
            python.write_text("binary placeholder\n", encoding="utf-8")
            args = mock.Mock(
                python=python, puffer_root=root, seed=1, ratio_call_limit=64,
                throughput_agents=2048, throughput_buffers=2,
                throughput_threads=16, throughput_horizon=64,
                throughput_hidden=512, throughput_layers=3,
                throughput_minibatch_size=16384, throughput_warmup_rollouts=2,
                throughput_timed_rollouts=8, cell_timeout_seconds=1800,
            )
            record = {
                "accepted": True,
                "config": {"cudagraphs": 10},
                "cuda_runtime_preflight": cuda_runtime_evidence(),
            }
            with mock.patch.object(
                self.q.subprocess, "run",
                return_value=mock.Mock(returncode=0, stdout="", stderr=""),
            ), mock.patch.object(
                self.q, "_read_json", return_value=record
            ), self.assertRaisesRegex(
                self.q.QualificationError, "cudagraph warmup"
            ):
                self.q._run_worker(
                    args, kind="rollout", name="graph-off", cudagraphs=-1,
                    output=root,
                )

    def test_run_is_rerunnable_over_an_existing_output_directory(self):
        """The harness is a smoke test, not a one-shot notarized event."""
        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary) / "qualification"
            output.mkdir()
            stale = output / "QUALIFICATION.json"
            stale.write_text("stale verdict\n", encoding="utf-8")
            args = mock.Mock(output=output)
            with mock.patch.object(
                self.q, "_run_worker", side_effect=RuntimeError("worker reached")
            ) as worker, self.assertRaisesRegex(RuntimeError, "worker reached"):
                self.q.run_qualification(args)
            worker.assert_called_once()

    def test_top_level_acceptance_is_and_of_all_named_mandatory_gates(self):
        gates = {name: {"accepted": True} for name in self.q.MANDATORY_GATES}
        verdict = self.q.combine_gate_verdicts(gates)
        self.assertTrue(verdict["accepted"])
        gates["ratio"]["accepted"] = False
        verdict = self.q.combine_gate_verdicts(gates)
        self.assertFalse(verdict["accepted"])
        del gates["throughput"]
        with self.assertRaises(self.q.QualificationError):
            self.q.combine_gate_verdicts(gates)


class QualificationPatchContractTests(unittest.TestCase):
    """The native evidence patch must expose measurement, not mutation."""

    def test_native_patch_exposes_only_bounded_evidence_surfaces(self):
        patch = PATCH.read_text(encoding="utf-8")
        for fragment in (
            "qualification_recurrent_state",
            "qualification_snapshot",
            "QUALIFICATION_MAX_SNAPSHOT_BYTES",
            "snapshot exceeds qualification byte limit",
            'm.def("qualification_recurrent_state"',
            'm.def("qualification_snapshot"',
            "cudaError_t device_status = cudaGetDeviceCount(&device_count)",
            "device_status != cudaSuccess || device_count <= 0",
            "CUDA device discovery failed:",
        ):
            self.assertIn(fragment, patch)
        self.assertIn(
            '-    assert(device_count > 0 && "CUDA is not available");', patch
        )
        for forbidden in (
            "set_weights_ptr", "set_observations", "set_terminals",
            "set_rng_state", "set_actions",
        ):
            self.assertNotIn(forbidden, patch)

    def test_state_report_covers_primary_and_every_frozen_bank_buffer(self):
        patch = PATCH.read_text(encoding="utf-8")
        for fragment in (
            "1 + pufferl.num_frozen_banks",
            "pufferl.frozen_banks[bank - 1].buffer_states",
            "pufferl.hypers.num_buffers",
            'entry["nonzero"]',
            'entry["nonfinite"]',
            'entry["max_abs"]',
            'entry["active_nonzero"]',
            'entry["active_nonfinite"]',
            'entry["active_max_abs"]',
            "cudaStreamSynchronize(pufferl.default_stream)",
        ):
            self.assertIn(fragment, patch)

    def test_ratio_report_exposes_selected_rows_and_real_recomputed_tensor(self):
        patch = PATCH.read_text(encoding="utf-8")
        self.assertIn("pufferl.train_buf.mb_ratio", patch)
        self.assertIn("pufferl.prio_bufs.idx", patch)
        self.assertNotIn("from_float(1.0f), numel(pufferl.train_buf.mb_ratio", patch)

    def test_priority_patch_masks_frozen_rows_even_at_zero_alpha(self):
        patch = PRIO_PATCH.read_text(encoding="utf-8")
        for fragment in (
            "t % agents_per_buffer < primary_per_buffer",
            ": 0.0f",
            "eligible_agents",
            "bufs.mb_prio.data, eligible_agents",
            "last_eligible",
            "i == last_eligible ? 1.0f",
            "invalid prioritized replay row layout",
        ):
            self.assertIn(fragment, patch)
        # Zero advantage raised to the zero power has unit weight, so the ratio
        # cell has to run at prio_alpha=0 with a real frozen bank present.
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn('"prio_alpha": 0.0', runner)
        self.assertIn("frozen_banks=1", runner)
        self.assertIn("total_agents=8", runner)
        self.assertIn("num_buffers=2", runner)
        self.assertIn('"PPO selected a frozen-bank row"', runner)

    def test_decoder_snapshot_is_limited_to_recorded_active_rows(self):
        patch = PATCH.read_text(encoding="utf-8")
        self.assertIn("active_output.shape[0] = active_rows", patch)
        self.assertIn('entry["active_rows"] = active_rows', patch)

    def test_installer_applies_patch_last_and_hashes_compiled_surfaces(self):
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("puffer_recurrent_cuda_qualification.patch", installer)
        self.assertIn("training/selfplay_league.patch", installer)
        recurrent_at = installer.index(
            'echo "applied:   recurrent evaluation-state boundaries'
        )
        frozen_at = installer.index(
            'echo "applied:   exact frozen-row exclusion'
        )
        qualification_at = installer.index(
            'echo "applied:   bounded recurrent CUDA qualification evidence'
        )
        digest_at = installer.index('EXACT_BACKEND_HASH="$(exact_backend_hash)"')
        league_at = installer.index(
            'echo "applied:   training/selfplay_league.patch ->'
        )
        self.assertLess(recurrent_at, qualification_at)
        self.assertLess(recurrent_at, frozen_at)
        self.assertLess(frozen_at, qualification_at)
        self.assertLess(league_at, digest_at)
        self.assertLess(qualification_at, digest_at)
        backend_hash = installer[
            installer.index("exact_backend_hash()"):
            installer.index('if [ "$MODE" = "check" ]')
        ]
        self.assertIn("pufferlib/selfplay.py", backend_hash)
        self.assertIn(
            'git -C "$PUFFER" apply --reverse --check --no-index',
            installer,
        )
        league_patch = LEAGUE_PATCH.read_text(encoding="utf-8")
        self.assertIn("Patch copy: training/selfplay_league.patch", league_patch)
        self.assertIn("league_preseed", league_patch)
        for marker in (
            "eligible_agents", "qualification_recurrent_state",
            "qualification_snapshot", "apply --reverse --check --no-index",
            "Patch copy: training/selfplay_league.patch",
        ):
            self.assertIn(marker, installer)

    def test_real_installer_selfplay_state_machine_is_fail_closed(self):
        upstream_selfplay = textwrap.dedent('''\
            """Pool storage is disk-only (paths held in memory; weights only on GPU when
            loaded as the frozen bank). Stride-eviction preserves temporal coverage when
            the pool exceeds its cap.
            """
            import os

            import numpy as np
            ''') + ("# fixture padding\n" * 150) + textwrap.dedent('''\
            def setup(pufferl, backend, args, run_id):
                sp = args['selfplay']
                num_banks = 2
                perm = []
                tags = []
                backend.set_agent_perm(pufferl, perm)
                backend.set_env_tags(pufferl, tags)

                pool_dir = os.path.join(args['checkpoint_dir'], args['env_name'], run_id, 'pool')
                os.makedirs(pool_dir, exist_ok=True)
                bootstrap_path = os.path.join(pool_dir, f'{pufferl.global_step:016d}.bin')
                backend.save_weights(pufferl, bootstrap_path)
                # Load bootstrap into every bank — they'll diverge as each bank's swap fires.
                for b in range(num_banks):
                    backend.load_frozen_bank(pufferl, b, bootstrap_path)

                elo_init = float(sp.get('elo_init', 0.0))
                elo_k    = float(sp.get('elo_k',    16.0))
                banks_state = []
                for b in range(num_banks):
                    banks_state.append({
                        'cur_opp_path': bootstrap_path,
                        'cur_opp_elo': elo_init,
                        'hist_score': 0.0,
                        'hist_n': 0.0,
                    })

                # state fixture padding 1
                # state fixture padding 2
                # state fixture padding 3
                # state fixture padding 4
                # state fixture padding 5
                # state fixture padding 6
                # state fixture padding 7
                # state fixture padding 8
                # state fixture padding 9

                return {
                    'pool_dir': pool_dir,
                    'pool': [{'path': bootstrap_path, 'elo': elo_init}],
                    'rng': rng,
                    'max_size': int(sp['max_size']),
                    'min_games': int(sp['min_games']),
                }
            ''')
        dashboard_markers = "\n".join((
            "if i == 160:",
            "PUFFER_ENV_JSON",
            "'_puffer_schema': 2",
            "'_puffer_final_reprint'",
            "'_puffer_eval_episodes_completed'",
            "phase_eval=phase_eval, phase_epoch=epoch",
            "metrics.setdefault",
        ))
        with tempfile.TemporaryDirectory() as temporary:
            puffer = pathlib.Path(temporary) / "PufferLib"
            (puffer / "pufferlib").mkdir(parents=True)
            (puffer / "src").mkdir()
            (puffer / "config").mkdir()
            (puffer / "build.sh").write_text("fixture\n", encoding="utf-8")
            (puffer / "pufferlib/pufferl.py").write_text(
                dashboard_markers, encoding="utf-8"
            )
            (puffer / "pufferlib/torch_pufferl.py").write_text(
                "historical full-pickle state dicts\nsample_joint_logits\n",
                encoding="utf-8",
            )
            selfplay = puffer / "pufferlib/selfplay.py"
            selfplay.write_text(upstream_selfplay, encoding="utf-8")
            (puffer / "pufferlib/sweep.py").write_text(
                "match_enemy_model_path\n", encoding="utf-8"
            )
            for relative, contents in {
                "src/vecenv.h": "joint_action_offsets\n",
                "src/pufferlib.cu": "fixture stops after selfplay\n",
                "src/bindings.cu": "fixture\n",
                "src/bindings_cpu.cpp": "fixture\n",
                "src/kernels.cu": "fixture\n",
            }.items():
                (puffer / relative).write_text(contents, encoding="utf-8")

            def install(*arguments: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [str(INSTALLER), *arguments, str(puffer)],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    timeout=60,
                )

            applicable = subprocess.run(
                [
                    "git", "-C", str(puffer), "apply", "--check",
                    "--no-index", str(LEAGUE_PATCH),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(applicable.returncode, 0, applicable.stderr)
            first = install()
            self.assertNotEqual(first.returncode, 0)
            self.assertIn(
                "applied:   training/selfplay_league.patch",
                first.stdout,
                first.stderr,
            )
            self.assertIn("exact joint-action backend support is incomplete", first.stderr)
            patched = selfplay.read_bytes()
            self.assertIn(b"Patch copy: training/selfplay_league.patch", patched)
            subprocess.run(
                [
                    "git", "-C", str(puffer), "apply", "--reverse", "--check",
                    "--no-index", str(LEAGUE_PATCH),
                ],
                check=True,
                capture_output=True,
            )

            second = install()
            self.assertNotEqual(second.returncode, 0)
            self.assertNotIn("applied:   training/selfplay_league.patch", second.stdout)
            self.assertNotIn("selfplay league patch", second.stderr)
            self.assertEqual(selfplay.read_bytes(), patched)

            checked = install("--check")
            self.assertNotEqual(checked.returncode, 0)
            self.assertNotIn("selfplay league patch", checked.stderr)
            self.assertIn("exact-action backend marker missing", checked.stderr)

            subprocess.run(
                [
                    "git", "-C", str(puffer), "apply", "--reverse",
                    "--no-index", str(LEAGUE_PATCH),
                ],
                check=True,
                capture_output=True,
            )
            self.assertEqual(selfplay.read_text(encoding="utf-8"), upstream_selfplay)
            unapplied = install("--check")
            self.assertNotEqual(unapplied.returncode, 0)
            self.assertIn("installed selfplay league patch is missing or stale", unapplied.stderr)

            subprocess.run(
                [
                    "git", "-C", str(puffer), "apply", "--no-index",
                    str(LEAGUE_PATCH),
                ],
                check=True,
                capture_output=True,
            )
            partial = selfplay.read_text(encoding="utf-8").replace(
                "        seed_paths = [bootstrap_path] * num_banks\n", "", 1
            )
            self.assertIn("Patch copy: training/selfplay_league.patch", partial)
            selfplay.write_text(partial, encoding="utf-8")
            stale = install("--check")
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn("installed selfplay league patch is missing or stale", stale.stderr)

            selfplay.unlink()
            missing = install("--check")
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("installed selfplay league patch is missing or stale", missing.stderr)


if __name__ == "__main__":
    unittest.main()
