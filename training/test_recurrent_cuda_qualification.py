"""Contracts for the deployment-bound recurrent CUDA qualification gate."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

import numpy as np


ROOT = pathlib.Path(__file__).resolve().parents[1]
PATCH = ROOT / "training" / "puffer_recurrent_cuda_qualification.patch"
PRIO_PATCH = ROOT / "training" / "puffer_frozen_prio_mask.patch"
INSTALLER = ROOT / "tools" / "install_puffer_env.sh"
RUNNER = ROOT / "tools" / "qualify_recurrent_cuda.py"
SCREEN_LAUNCHER = ROOT / "tools" / "run_reward_screen.sh"
PLAN = ROOT / "docs" / "plans" / "recurrent-cuda-qualification.md"
QUALIFICATION_CHECKLIST = ROOT / "docs" / "qualification-2070-execution-checklist.md"
CANARY_CHECKLIST = ROOT / "docs" / "exact-action-canary-2070-execution-checklist.md"
AGENTS = ROOT / "AGENTS.md"
CLAUDE = ROOT / "CLAUDE.md"
PUFFER_SKILL = ROOT / ".claude" / "skills" / "puffer-env-dev" / "SKILL.md"
TRAINING_SKILL = ROOT / ".claude" / "skills" / "training-experiments" / "SKILL.md"
FLEET_SKILL = ROOT / ".claude" / "skills" / "fleet-ops" / "SKILL.md"


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
        frozen = [{"selected_rows": np.array([2], np.int32),
                   "ratios": np.ones((1, 2), np.float32)}]
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_ratio_calls(
                frozen, primary_rows={0}, frozen_rows={2}, atol=1e-6)

    def test_weight_identity_and_throughput_control_are_fail_closed(self):
        digest = hashlib.sha256(b"same weights").hexdigest()
        self.q.validate_weight_identity(digest, digest)
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_weight_identity(digest, "0" * 64)

        baseline = {
            "host": "rtx2070", "gpu": "RTX 2070", "precision_bytes": 4,
            "config_sha256": "a" * 64, "steps_per_second": 1000.0,
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
        candidate = dict(
            baseline, gpu="different", steps=2000, steps_per_second=2000.0
        )
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_throughput(
                candidate, baseline, max_regression_fraction=0.10)
        candidate = dict(
            baseline,
            config_sha256="b" * 64,
            steps=2000,
            steps_per_second=2000.0,
        )
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_throughput(
                candidate, baseline, max_regression_fraction=0.10)

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

    def test_module_identity_requires_exact_bloodbowl_lineage_and_source_hashes(self):
        digest = "a" * 64
        identity = {
            "module": "/puffer/pufferlib/_C.so",
            "puffer_root": "/puffer",
            "module_sha256": digest,
            "compiled_backend_sha256": digest,
            "backend_sources_sha256": digest,
            "environment_sha256": "b" * 64,
            "installed_snapshot_sha256": "b" * 64,
            "observation_abi": "obs-v5",
            "observation_version": 5,
            "action_abi": "exact-joint-v1",
            "precision_bytes": 4,
            "compiled_env": "bloodbowl",
            "qualification_surface": True,
        }
        self.q.validate_module_identity(identity, qualification_surface=True)
        expected = {
            "source_commit": self.q.CANDIDATE_SOURCE_COMMIT,
            "module_sha256": digest,
            "backend_sha256": digest,
            "environment_sha256": "b" * 64,
        }
        self.q.validate_expected_candidate_identity(identity, expected)
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_expected_candidate_identity(
                identity, dict(expected, backend_sha256="c" * 64)
            )
        predecessor_identity = dict(identity, qualification_surface=False)
        predecessor_expected = {
            "source_commit": self.q.PREDECESSOR_SOURCE_COMMIT,
            "module_sha256": expected["module_sha256"],
            "backend_sha256": expected["backend_sha256"],
            "environment_sha256": expected["environment_sha256"],
        }
        self.q.validate_expected_predecessor_identity(
            predecessor_identity, predecessor_expected
        )
        for key, value in (
            ("compiled_env", "other"),
            ("observation_abi", "obs-v4"),
            ("observation_version", 4),
            ("action_abi", "marginal"),
            ("precision_bytes", 2),
            ("compiled_backend_sha256", "c" * 64),
            ("environment_sha256", "bad"),
            ("qualification_surface", False),
        ):
            with self.subTest(key=key), self.assertRaises(
                    self.q.QualificationError):
                self.q.validate_module_identity(
                    dict(identity, **{key: value}), qualification_surface=True)

    def test_baseline_wrapper_requires_hashed_predecessor_cell(self):
        digest = "a" * 64
        identity = {
            "module": "/puffer/pufferlib/_C.so", "puffer_root": "/puffer",
            "module_sha256": digest, "compiled_backend_sha256": digest,
            "backend_sources_sha256": digest,
            "environment_sha256": "b" * 64,
            "installed_snapshot_sha256": "b" * 64,
            "observation_abi": "obs-v5", "observation_version": 5,
            "action_abi": "exact-joint-v1", "precision_bytes": 4,
            "compiled_env": "bloodbowl", "qualification_surface": False,
        }
        integrity = {key: 0.0 for key in self.q.HARD_INTEGRITY_KEYS}
        config = {"cudagraphs": self.q.DEFAULT_CUDAGRAPH_WARMUP_EPOCHS}
        config_digest = self.q.canonical_hash(config)
        throughput = {
            "host": "rtx2070", "gpu": "RTX 2070", "precision_bytes": 4,
            "config_sha256": config_digest, "steps_per_second": 1000.0,
            "hard_integrity_zero": True, "hard_integrity": integrity,
            "steps": 1000, "elapsed_seconds": 1.0,
            "median_rollout_seconds": 0.1, "p95_rollout_seconds": 0.2,
            "utilization": {},
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source_root = root / "source"
            puffer_root = source_root / "vendor" / "PufferLib"
            identity["puffer_root"] = str(puffer_root)
            identity["module"] = str(puffer_root / "pufferlib" / "_C.so")
            source = {
                "role": "predecessor",
                "source_root": str(source_root),
                "source_commit": self.q.PREDECESSOR_SOURCE_COMMIT,
                "puffer_root": str(puffer_root),
                "installer_check_sha256": "e" * 64,
            }
            runner_source = {
                "source_root": str(ROOT),
                "source_commit": "f" * 40,
                "runner_sha256": self.q.sha256(RUNNER),
            }
            cell = {
                "schema_version": self.q.SCHEMA_VERSION,
                "qualification_only": True, "accepted": True,
                "kind": "throughput", "preceding_runtime": True,
                "runner_sha256": self.q.sha256(RUNNER),
                "identity": identity, "throughput": throughput,
                "config": config, "config_sha256": config_digest,
                "predecessor_source": source,
                "runner_source": runner_source,
            }
            cell_path = root / "throughput-baseline.json"
            cell_path.write_text(json.dumps(cell), encoding="utf-8")
            wrapper = {
                "schema_version": self.q.SCHEMA_VERSION,
                "qualification_only": True,
                "role": "preceding_exact_action_throughput_baseline",
                "runner_sha256": self.q.sha256(RUNNER),
                "identity": identity, "throughput": throughput,
                "expected_predecessor": {
                    "source_commit": self.q.PREDECESSOR_SOURCE_COMMIT,
                    "module_sha256": digest,
                    "backend_sha256": digest,
                    "environment_sha256": "b" * 64,
                },
                "predecessor_source": source,
                "runner_source": runner_source,
                "cell_record": str(cell_path),
                "cell_record_sha256": self.q.sha256(cell_path),
            }
            wrapper_path = root / "THROUGHPUT_BASELINE.json"
            wrapper_path.write_text(json.dumps(wrapper), encoding="utf-8")
            with mock.patch.object(
                self.q, "validate_source_checkout_record", return_value=source
            ), mock.patch.object(
                self.q, "current_runner_source_identity", return_value=runner_source
            ), mock.patch.object(self.q, "validate_current_identity_files") as current:
                parsed = self.q.validate_baseline_artifact(wrapper_path)
            self.assertEqual(parsed["throughput"], throughput)
            current.assert_called_once_with(identity)

            with mock.patch.object(
                self.q, "validate_source_checkout_record", return_value=source
            ), mock.patch.object(
                self.q, "current_runner_source_identity", return_value=runner_source
            ), mock.patch.object(
                self.q,
                "validate_current_identity_files",
                side_effect=self.q.QualificationError("module binary drifted"),
            ), self.assertRaises(self.q.QualificationError):
                self.q.validate_baseline_artifact(wrapper_path)
            wrapper["role"] = "handwritten"
            wrapper_path.write_text(json.dumps(wrapper), encoding="utf-8")
            with mock.patch.object(
                self.q, "validate_source_checkout_record", return_value=source
            ), mock.patch.object(
                self.q, "current_runner_source_identity", return_value=runner_source
            ), self.assertRaises(self.q.QualificationError):
                self.q.validate_baseline_artifact(wrapper_path)

    def test_source_checkout_binding_requires_exact_clean_role_local_tree(self):
        commit = self.q.PREDECESSOR_SOURCE_COMMIT
        with tempfile.TemporaryDirectory() as temporary:
            source = pathlib.Path(temporary) / "source"
            puffer = source / "vendor" / "PufferLib"
            installer = source / "tools" / "install_puffer_env.sh"
            puffer.mkdir(parents=True)
            installer.parent.mkdir(parents=True)
            installer.write_text("#!/bin/sh\n", encoding="utf-8")
            completed = [
                mock.Mock(returncode=0, stdout=f"{source}\n", stderr=""),
                mock.Mock(returncode=0, stdout=f"{commit}\n", stderr=""),
                mock.Mock(returncode=0, stdout="", stderr=""),
                mock.Mock(returncode=0, stdout="drift check: OK\n", stderr=""),
            ]
            with mock.patch.object(
                self.q.subprocess, "run", side_effect=completed
            ) as run:
                identity = self.q.validate_source_checkout(
                    source, puffer, expected_commit=commit, role="predecessor"
                )
            self.assertEqual(identity["source_commit"], commit)
            self.assertEqual(identity["puffer_root"], str(puffer.resolve()))
            self.assertEqual(run.call_count, 4)
            self.q.require_output_outside_source(
                pathlib.Path(temporary) / "external", source, role="predecessor source"
            )
            with self.assertRaises(self.q.QualificationError):
                self.q.require_output_outside_source(
                    source / "runs" / "qualification",
                    source,
                    role="predecessor source",
                )

            with self.assertRaises(self.q.QualificationError):
                self.q.validate_source_checkout(
                    source,
                    pathlib.Path(temporary) / "shared-puffer",
                    expected_commit=commit,
                    role="predecessor",
                )
            for role, wrong_commit in (
                ("predecessor", self.q.CANDIDATE_SOURCE_COMMIT),
                ("candidate", self.q.PREDECESSOR_SOURCE_COMMIT),
            ):
                with self.subTest(role=role), self.assertRaises(
                    self.q.QualificationError
                ):
                    self.q.validate_source_checkout(
                        source, puffer, expected_commit=wrong_commit, role=role
                    )
            with self.assertRaises(self.q.QualificationError):
                self.q.validate_source_checkout(
                    self.q.PROTECTED_RECOVERY_ROOT,
                    self.q.PROTECTED_RECOVERY_ROOT / "vendor" / "PufferLib",
                    expected_commit=self.q.PREDECESSOR_SOURCE_COMMIT,
                    role="predecessor",
                )
            for roots in (
                (ROOT, ROOT, source),  # candidate equals control runner
                (ROOT, source, ROOT),  # predecessor equals control runner
                (source, ROOT, ROOT),  # predecessor equals candidate
            ):
                with self.subTest(roots=roots), self.assertRaises(
                    self.q.QualificationError
                ):
                    self.q.require_distinct_source_roots(*roots)
            dirty = [
                mock.Mock(returncode=0, stdout=f"{source}\n", stderr=""),
                mock.Mock(returncode=0, stdout=f"{commit}\n", stderr=""),
                mock.Mock(returncode=0, stdout="M puffer/bloodbowl/binding.c\n", stderr=""),
            ]
            with mock.patch.object(self.q.subprocess, "run", side_effect=dirty), \
                    self.assertRaises(self.q.QualificationError):
                self.q.validate_source_checkout(
                    source, puffer, expected_commit=commit, role="predecessor"
                )

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
            record_path = output / "construction.json"
            record_path.write_text("{}\n", encoding="utf-8")
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
            completed = mock.Mock(returncode=0, stdout="", stderr="")
            config = {"cudagraphs": 10}
            record = {
                "accepted": True,
                "qualification_only": True,
                "config": config,
                "config_sha256": self.q.canonical_hash(config),
            }
            with mock.patch.object(
                self.q.subprocess, "run", return_value=completed
            ) as run, mock.patch.object(self.q, "_read_json", return_value=record):
                self.q._run_worker(
                    args,
                    kind="construction",
                    name="construction",
                    cudagraphs=10,
                    output=output,
                )
            command = run.call_args.args[0]
            self.assertEqual(command[0], str(venv_python.absolute()))
            self.assertNotEqual(command[0], str(base_python.resolve()))
            cudagraph_flag = command.index("--cudagraphs")
            self.assertEqual(command[cudagraph_flag + 1], "10")
            minibatch_flag = command.index("--throughput-minibatch-size")
            self.assertEqual(command[minibatch_flag + 1], "16384")

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
        for kind in (
            "construction", "rollout", "terminal_auto", "terminal_control",
            "ratio", "throughput",
        ):
            with self.subTest(kind=kind):
                self.assertEqual(
                    self.q.validate_cell_cudagraphs(kind, 10), 10
                )
                self.assertEqual(
                    self.q._cell_config(kind, 10, args)["cudagraphs"], 10
                )
                with self.assertRaises(self.q.QualificationError):
                    self.q.validate_cell_cudagraphs(kind, 0)
        self.assertEqual(self.q.validate_cell_cudagraphs("rollout", -1), -1)
        for kind in (
            "construction", "terminal_auto", "terminal_control", "ratio",
            "throughput",
        ):
            with self.subTest(graph_off_kind=kind), self.assertRaises(
                self.q.QualificationError
            ):
                self.q.validate_cell_cudagraphs(kind, -1)
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertNotIn("cudagraphs=0", runner)
        self.assertEqual(
            runner.count("cudagraphs=DEFAULT_CUDAGRAPH_WARMUP_EPOCHS"), 7
        )

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

    def test_cudagraph_record_rejects_coherent_zero_warmup_mutation(self):
        record = {"config": {"cudagraphs": 10}}
        record["config_sha256"] = self.q.canonical_hash(record["config"])
        self.q.validate_cell_cudagraph_record(record, expected=10)

        record["config"]["cudagraphs"] = 0
        record["config_sha256"] = self.q.canonical_hash(record["config"])
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_cell_cudagraph_record(record, expected=10)

        record["config"]["cudagraphs"] = 10.0
        record["config_sha256"] = self.q.canonical_hash(record["config"])
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_cell_cudagraph_record(record, expected=10)

        record["config"]["cudagraphs"] = 10
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_cell_cudagraph_record(record, expected=10)

        record["config_sha256"] = self.q.canonical_hash(record["config"])
        record["throughput"] = {"config_sha256": "a" * 64}
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_cell_cudagraph_record(record, expected=10)

    def test_throughput_minibatch_matches_exact_canary_contract(self):
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
        rollout_quantum = (
            config["vec"]["total_agents"] * config["train"]["horizon"]
        )
        self.assertEqual(rollout_quantum, 131072)
        self.assertEqual(config["train"]["minibatch_size"], 16384)
        self.assertEqual(config["cudagraphs"], 10)

    def test_throughput_minibatch_parser_default_is_frozen(self):
        args = self.q.parse_args([
            "cell",
            "--puffer-root", "/tmp/puffer",
            "--kind", "throughput",
            "--cudagraphs", "10",
            "--output-json", "/tmp/throughput.json",
        ])
        self.assertEqual(self.q.DEFAULT_THROUGHPUT_MINIBATCH_SIZE, 16384)
        self.assertEqual(args.throughput_minibatch_size, 16384)

    def test_invalid_throughput_minibatch_fails_before_worker_dispatch(self):
        argv = [
            "cell",
            "--puffer-root", "/tmp/puffer",
            "--kind", "throughput",
            "--cudagraphs", "0",
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

    def test_operator_commands_freeze_canary_throughput_minibatch(self):
        for command, dispatch_name in (
            ("capture-throughput", "capture_throughput"),
            ("run", "run_qualification"),
        ):
            args = mock.Mock(
                command=command,
                ratio_call_limit=64,
                throughput_warmup_rollouts=2,
                throughput_timed_rollouts=8,
                throughput_agents=2048,
                throughput_horizon=64,
                throughput_minibatch_size=8192,
            )
            with self.subTest(command=command), mock.patch.object(
                self.q, "parse_args", return_value=args
            ), mock.patch.object(self.q, dispatch_name) as dispatch, self.assertRaises(
                self.q.QualificationError
            ):
                self.q.main([])
            dispatch.assert_not_called()

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

    def test_run_failure_record_never_writes_to_rejected_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            safe_output = root / "new-output"
            args = mock.Mock(command="run", output=safe_output)
            args.candidate_source_root = root / "candidate-source"
            args.predecessor_source_root = root / "predecessor-source"
            args.ratio_call_limit = 1
            args.throughput_warmup_rollouts = 0
            args.throughput_timed_rollouts = 1
            args.throughput_agents = 2048
            args.throughput_horizon = 64
            args.throughput_minibatch_size = 16384
            args.max_regression_fraction = self.q.DEFAULT_MAX_REGRESSION_FRACTION
            with mock.patch.object(self.q, "parse_args", return_value=args), \
                    mock.patch.object(
                        self.q, "run_qualification",
                        side_effect=self.q.QualificationError("expected failure"),
                    ), self.assertRaises(self.q.QualificationError):
                self.q.main([])
            failure = json.loads(
                (safe_output / "QUALIFICATION.json").read_text(encoding="utf-8")
            )
            self.assertFalse(failure["accepted"])

            occupied = root / "occupied"
            occupied.mkdir()
            sentinel = occupied / "QUALIFICATION.json"
            sentinel.write_text("do not replace", encoding="utf-8")
            args.output = occupied
            with mock.patch.object(self.q, "parse_args", return_value=args), \
                    mock.patch.object(
                        self.q, "run_qualification",
                        side_effect=self.q.QualificationError("expected failure"),
                    ), self.assertRaises(self.q.QualificationError):
                self.q.main([])
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "do not replace")

            inside_checkout = ROOT / ".qualification-must-not-write"
            args.output = inside_checkout
            with mock.patch.object(self.q, "parse_args", return_value=args), \
                    mock.patch.object(
                        self.q, "run_qualification",
                        side_effect=self.q.QualificationError("expected failure"),
                    ), self.assertRaises(self.q.QualificationError):
                self.q.main([])
            self.assertFalse(inside_checkout.exists())

            for forbidden in (
                args.candidate_source_root,
                args.predecessor_source_root,
                self.q.PROTECTED_RECOVERY_ROOT,
            ):
                args.output = forbidden / "qualification-output"
                with mock.patch.object(self.q, "parse_args", return_value=args), \
                        mock.patch.object(
                            self.q, "run_qualification",
                            side_effect=self.q.QualificationError("expected failure"),
                        ), self.assertRaises(self.q.QualificationError):
                    self.q.main([])
                self.assertFalse(args.output.exists())

    def test_run_failure_record_refuses_untrusted_baseline_source_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            candidate = root / "candidate-source"
            predecessor = root / "predecessor-source"
            baseline = root / "THROUGHPUT_BASELINE.json"
            candidate.mkdir()
            predecessor.mkdir()

            stale_source = root / "stale-predecessor-source"
            cases = (
                None,
                {},
                {"source_root": 7},
                {
                    "role": "predecessor",
                    "source_root": str(stale_source),
                    "source_commit": self.q.PREDECESSOR_SOURCE_COMMIT,
                    "puffer_root": str(stale_source / "vendor" / "PufferLib"),
                    "installer_check_sha256": "f" * 64,
                },
            )
            for index, predecessor_source in enumerate(cases):
                with self.subTest(predecessor_source=predecessor_source):
                    output_root = stale_source if index == len(cases) - 1 else predecessor
                    output = output_root / f"qualification-output-{index}"
                    wrapper = {"schema_version": self.q.SCHEMA_VERSION}
                    if predecessor_source is not None:
                        wrapper["predecessor_source"] = predecessor_source
                    baseline.write_text(json.dumps(wrapper), encoding="utf-8")
                    args = self.q.parse_args([
                        "run",
                        "--puffer-root", str(candidate / "vendor" / "PufferLib"),
                        "--output", str(output),
                        "--baseline-throughput", str(baseline),
                        "--candidate-source-root", str(candidate),
                        "--predecessor-source-root", str(predecessor),
                        "--expected-source-commit", self.q.CANDIDATE_SOURCE_COMMIT,
                        "--expected-candidate-module-sha256", "a" * 64,
                        "--expected-candidate-backend-sha256", "b" * 64,
                        "--expected-environment-sha256", "c" * 64,
                        "--expected-predecessor-source-commit",
                        self.q.PREDECESSOR_SOURCE_COMMIT,
                        "--expected-predecessor-module-sha256", "d" * 64,
                        "--expected-predecessor-backend-sha256", "e" * 64,
                    ])
                    with mock.patch.object(self.q, "parse_args", return_value=args), \
                            mock.patch.object(
                                self.q, "run_qualification",
                                side_effect=self.q.QualificationError(
                                    "expected malformed baseline failure"
                                ),
                            ), self.assertRaises(self.q.QualificationError):
                        self.q.main([])
                    self.assertFalse(output.exists())

            recorded = {"source_root": str(predecessor)}
            self.assertEqual(
                self.q.require_predecessor_source_root(predecessor, recorded),
                predecessor.resolve(),
            )
            with self.assertRaises(self.q.QualificationError):
                self.q.require_predecessor_source_root(stale_source, recorded)

    def test_predecessor_source_root_is_required_by_both_operator_commands(self):
        run_args = [
            "run",
            "--puffer-root", "/candidate/vendor/PufferLib",
            "--output", "/external/qualification",
            "--baseline-throughput", "/external/THROUGHPUT_BASELINE.json",
            "--candidate-source-root", "/candidate",
            "--predecessor-source-root", "/predecessor",
            "--expected-source-commit", self.q.CANDIDATE_SOURCE_COMMIT,
            "--expected-candidate-module-sha256", "a" * 64,
            "--expected-candidate-backend-sha256", "b" * 64,
            "--expected-environment-sha256", "c" * 64,
            "--expected-predecessor-source-commit",
            self.q.PREDECESSOR_SOURCE_COMMIT,
            "--expected-predecessor-module-sha256", "d" * 64,
            "--expected-predecessor-backend-sha256", "e" * 64,
        ]
        capture_args = [
            "capture-throughput",
            "--puffer-root", "/predecessor/vendor/PufferLib",
            "--output", "/external/baseline",
            "--predecessor-source-root", "/predecessor",
            "--expected-predecessor-source-commit",
            self.q.PREDECESSOR_SOURCE_COMMIT,
            "--expected-predecessor-module-sha256", "a" * 64,
            "--expected-predecessor-backend-sha256", "b" * 64,
            "--expected-environment-sha256", "c" * 64,
        ]
        for command_args in (run_args, capture_args):
            root_index = command_args.index("--predecessor-source-root")
            omitted = command_args[:root_index] + command_args[root_index + 2:]
            with self.subTest(command=command_args[0]), mock.patch("sys.stderr"), \
                    self.assertRaises(SystemExit) as raised:
                self.q.parse_args(omitted)
            self.assertEqual(raised.exception.code, 2)

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
    def test_canary_plan_contract_accounts_for_persistent_screen_lock(self):
        launcher = SCREEN_LAUNCHER.read_text(encoding="utf-8")
        self.assertEqual(
            hashlib.sha256(SCREEN_LAUNCHER.read_bytes()).hexdigest(),
            "8a08e846764a92306440d5e220e9d6ee894c4bc15a7ee1ee75e55c9c2b041df3",
        )
        self.assertIn(
            "exact-action-canary launcher is frozen at candidate "
            "a52fc6e2f4ece5a7ff16bb4791e3aca4dd72f2e3",
            launcher,
        )

        candidate = "a52fc6e2f4ece5a7ff16bb4791e3aca4dd72f2e3"
        candidate_launcher_bytes = subprocess.run(
            ["git", "show", f"{candidate}:tools/run_reward_screen.sh"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        self.assertEqual(
            hashlib.sha256(candidate_launcher_bytes).hexdigest(),
            "b4ffe9cd6652a0b5f003956015797c458863a8152adcc278b323ba0a329adda8",
        )
        candidate_launcher = candidate_launcher_bytes.decode("utf-8")
        self.assertIn('exec 8>"$OUT_DIR/.screen.lock"', candidate_launcher)
        self.assertIn("flock -n 8", candidate_launcher)
        self.assertIn("if destination.exists():", candidate_launcher)
        self.assertIn(
            'recorded.get("schema_version") != 1 or recorded.get("contract") != contract',
            candidate_launcher,
        )
        self.assertIn(
            "screen plan drift; changed top-level contract fields",
            candidate_launcher,
        )
        exists_start = candidate_launcher.index("if destination.exists():")
        create_else = candidate_launcher.index("\nelse:\n    payload =", exists_start)
        manifest_print = candidate_launcher.index(
            "\nprint(sha(destination))", create_else
        )
        existing_manifest_branch = candidate_launcher[exists_start:create_else]
        create_manifest_branch = candidate_launcher[create_else:manifest_print]
        self.assertIn('recorded.get("contract") != contract', existing_manifest_branch)
        self.assertNotIn("write_text", existing_manifest_branch)
        self.assertNotIn("replace(destination)", existing_manifest_branch)
        self.assertIn("temporary.write_text", create_manifest_branch)
        self.assertIn("temporary.replace(destination)", create_manifest_branch)

        freeze_start = candidate_launcher.index("freeze_screen_manifest() {")
        freeze_end = candidate_launcher.index(
            'SCREEN_MANIFEST_SHA="$(freeze_screen_manifest)"', freeze_start
        )
        frozen_contract_builder = candidate_launcher[freeze_start:freeze_end]
        self.assertNotIn("PLAN_ONLY", frozen_contract_builder)

        checklist = CANARY_CHECKLIST.read_text(encoding="utf-8")
        normalized_checklist = " ".join(checklist.split())
        for fragment in (
            "exact-action-canary-50m-s42-v2",
            "| `tools/run_reward_screen.sh` | "
            "`b4ffe9cd6652a0b5f003956015797c458863a8152adcc278b323ba0a329adda8` |",
            "exactly two regular files",
            "`SCREEN_MANIFEST.json` plus `.screen.lock`",
            "zero bytes",
            "( exec 9</home/rache/bloodbowl-rl-qualification-artifacts-20260722/"
            "exact-action-canary-50m-s42-v2/.screen.lock; flock -n 9 )",
            "closes FD 9 and releases the proof's",
            "pathname-form `flock`",
            "byte-identical to the pre-proof inventory",
            "It leaves the manifest byte-identical",
            "first live poll",
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "15271d946e404ddcd26e9fc075d44b9dbeaa268b6e5e9ffecf536abfd212a331",
            "6d69a4deb85698279f100079ee6bb3b785af9b36d97cefeb7cc4f11389ce35f7",
            "2756134a67dfc8010c13d16eb30533b82671580e6e5eb049f430f813ef7482e4",
            "68d92db88481fb9aaa06b0e31e80429f5da9904b20ef39e6ed15dcad3f551618",
            "exact-action-canary-50m-s42-v1-plan-rejected-files.tsv",
            "exact-action-canary-50m-s42-v1-plan-rejected-inventory.sha256",
            "exact-action-canary-50m-s42-v1-plan-rejection.txt",
            "mode<TAB>bytes<TAB>relative-path",
            "three octal permission",
            "sha256<TWO-SPACES>relative-path",
            "rejected, never-installed unit identity",
            "pre-proof inventory",
            "post-proof inventory",
            "deep-compares the complete nested `contract` object",
            "repeat the Gate 2",
            "Do not delete, relabel, launch, or reuse the v1 output",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, normalized_checklist)

        self.assertIn(
            "`bloodbowl-exact-action-canary-50m-s42-v1.service`; Gate 1 must prove",
            checklist,
        )
        for line in checklist.splitlines():
            with self.subTest(line=line):
                if "exact-action-canary-50m-s42-v1" not in line:
                    continue
                self.assertNotIn("PREFIX=", line)
                self.assertNotIn("OUT_DIR=", line)
                self.assertNotIn("ExecStart=", line)
                self.assertNotIn("Unit name:", line)
        self.assertIn("PREFIX=exact-action-canary-50m-s42-v2", checklist)
        self.assertIn("bloodbowl-exact-action-canary-50m-s42-v2.service", checklist)

        qualification = QUALIFICATION_CHECKLIST.read_text(encoding="utf-8")
        self.assertIn("zero-byte, released, hash-bound `.screen.lock`", qualification)
        self.assertIn("exactly two regular files", qualification)
        self.assertIn(
            "leaves `SCREEN_MANIFEST.json` byte-identical",
            " ".join(qualification.split()),
        )

        required_guidance = {
            AGENTS: (
                "run_reward_screen.sh creates $OUT_DIR/.screen.lock",
                "hash its mode/size with the manifest",
            ),
            CLAUDE: (
                "The frozen screen launcher intentionally creates and retains",
                "with both modes, sizes, and hashes bound",
            ),
            TRAINING_SKILL: (
                "The frozen screen launcher creates $OUT_DIR/.screen.lock",
                "Hash both and their modes/sizes",
            ),
            FLEET_SKILL: (
                "For canary plan-only closure, account for the launcher's persistent ownership inode",
                "bind both files' modes, sizes, and digests",
            ),
        }
        for path, fragments in required_guidance.items():
            with self.subTest(path=path):
                normalized = " ".join(
                    path.read_text(encoding="utf-8").replace("`", "").split()
                )
                for fragment in fragments:
                    self.assertIn(fragment, normalized)

    def test_operator_contract_uses_isolated_exact_action_predecessor(self):
        q = load_runner()
        predecessor = "afc8008933548438ca93c41341f5f08fdd294386"
        candidate = "a52fc6e2f4ece5a7ff16bb4791e3aca4dd72f2e3"
        plan = PLAN.read_text(encoding="utf-8")
        self.assertIn(predecessor, plan)
        self.assertIn(candidate, plan)
        self.assertIn("own pinned Puffer", plan)
        self.assertIn("different from the predecessor tree", plan)
        self.assertIn("--predecessor-source-root", plan)
        self.assertIn("--expected-predecessor-source-commit", plan)
        self.assertIn("--candidate-source-root", plan)
        self.assertIn("Independently pass `--predecessor-source-root`", plan)
        self.assertIn("Do not modify or reuse the recovery Puffer tree", plan)
        self.assertIn("`cudagraphs=10`", plan)
        self.assertNotIn("On the still-installed predecessor", plan)
        for path in (AGENTS, CLAUDE, PUFFER_SKILL, TRAINING_SKILL):
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                self.assertIn(predecessor, text)
                self.assertIn(candidate, text)
                self.assertIn("different isolated source", text)
                self.assertIn("recovery Puffer tree", text)
                self.assertIn("`cudagraphs=10`", text)

        runner = RUNNER.read_text(encoding="utf-8")
        self.assertEqual(q.PREDECESSOR_SOURCE_COMMIT, predecessor)
        self.assertEqual(q.CANDIDATE_SOURCE_COMMIT, candidate)
        self.assertEqual(
            q.PROTECTED_RECOVERY_ROOT,
            pathlib.Path("/home/rache/bloodbowl-rl-recovery-20260719"),
        )
        for argument in (
            "--predecessor-source-root",
            "--expected-predecessor-source-commit",
            "--candidate-source-root",
        ):
            self.assertIn(argument, runner)

    def test_native_patch_exposes_only_bounded_evidence_surfaces(self):
        patch = PATCH.read_text(encoding="utf-8")
        for fragment in (
            "qualification_recurrent_state",
            "qualification_snapshot",
            "QUALIFICATION_MAX_SNAPSHOT_BYTES",
            "snapshot exceeds qualification byte limit",
            'm.def("qualification_recurrent_state"',
            'm.def("qualification_snapshot"',
        ):
            self.assertIn(fragment, patch)
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
        recurrent_at = installer.index('RECURRENT_PATCH=')
        frozen_at = installer.index('FROZEN_PRIO_PATCH=')
        qualification_at = installer.index('QUALIFICATION_PATCH=')
        digest_at = installer.index('EXACT_BACKEND_HASH="$(exact_backend_hash)"')
        self.assertLess(recurrent_at, qualification_at)
        self.assertLess(recurrent_at, frozen_at)
        self.assertLess(frozen_at, qualification_at)
        self.assertLess(qualification_at, digest_at)
        for marker in (
            "eligible_agents", "qualification_recurrent_state",
            "qualification_snapshot", "apply --reverse --check --no-index",
        ):
            self.assertIn(marker, installer)


if __name__ == "__main__":
    unittest.main()
