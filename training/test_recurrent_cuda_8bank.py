#!/usr/bin/env python3
import contextlib
import io
import sys
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import qualify_recurrent_cuda as q
import qualify_recurrent_cuda_8bank as subject


def state_report(nonzero=False):
    entries = []
    for bank in range(9):
        rows = 536 if bank == 0 else 61
        for buffer in range(2):
            shape = [1, rows, 4]
            entries.append({
                "bank": bank, "buffer": buffer, "shape": shape,
                "active_rows": rows, "elements": rows * 4,
                "active_elements": rows * 4,
                "nonzero": 1 if nonzero else 0,
                "nonfinite": 0,
                "active_nonzero": 1 if nonzero else 0,
                "active_nonfinite": 0,
                "max_abs": 1.0 if nonzero else 0.0,
                "active_max_abs": 1.0 if nonzero else 0.0,
            })
    return {
        "num_banks": 9, "num_buffers": 2, "agents_per_buffer": 1024,
        "bank_layout": list(subject.EXPECTED_LAYOUT), "entries": entries,
    }


class StrictBackend:
    precision_bytes = 4
    rollout_transition_contract = "terminal-aware-tbptt-v1"

    def __init__(self):
        self.pending = False
        self.rollout_calls = 0
        self.train_calls = 0
        self.cleared = False
        self.graph = {role: 0 for role in ("rollout", "tail", "train")}

    def qualification_recurrent_state(self, _pufferl, clear):
        if clear:
            self.cleared = True
            return state_report(False)
        return state_report(self.pending and not self.cleared)

    def rollouts(self, _pufferl):
        if self.pending:
            raise RuntimeError("rollout overwrote unconsumed tail")
        self.pending = True
        self.cleared = False
        self.rollout_calls += 1
        self.graph["rollout"] += 128

    def train(self, _pufferl):
        if not self.pending:
            raise RuntimeError("train lacks fresh rollout")
        self.pending = False
        self.train_calls += 1
        self.graph["tail"] += 2
        self.graph["train"] += 8

    def qualification_graph_execution(self, _pufferl):
        return {
            "cudagraphs": 10,
            "captured": {role: True for role in self.graph},
            "handles_ready": {role: True for role in self.graph},
            "graph_launch_counts": dict(self.graph),
            "eager_execution_counts": {role: 0 for role in self.graph},
        }

    def qualification_snapshot(self, _pufferl, max_bytes, include_rollout):
        self.snapshot_limits = getattr(self, "snapshot_limits", []) + [max_bytes]
        self.snapshot_modes = getattr(self, "snapshot_modes", []) + [include_rollout]
        primary = list(range(536)) + list(range(1024, 1560))
        chunk = primary[(self.train_calls * 128) % len(primary):]
        if len(chunk) < 128:
            chunk += primary[:128 - len(chunk)]
        config = subject.profile_config(42)
        shapes = subject.terminal_snapshot_shapes(config)
        selected = np.asarray(
            (chunk * ((shapes["selected_rows"][0] + len(chunk) - 1) // len(chunk)))
            [:shapes["selected_rows"][0]], dtype=np.int32)
        arrays = {
            name: np.zeros(
                shape,
                dtype=(np.int32 if name in {
                    "selected_rows", "segment_initial_valid", "tail_valid"
                } else np.float32),
            )
            for name, shape in shapes.items()
        }
        arrays["selected_rows"] = selected
        arrays["mb_ratio"].fill(1.0)
        return {
            "max_bytes": max_bytes,
            "used_bytes": subject.snapshot_byte_budget(config)[
                "declared_exact_bytes"],
            "include_rollout": include_rollout,
            "tensors": {name: object() for name in shapes},
            **arrays,
            **{
                f"decoder_bank_{bank}_buffer_{buffer}": np.ones(
                    (536 if bank == 0 else 61, subject.ACTION_MASK_WIDTH + 1),
                    dtype=np.float32,
                )
                for bank in range(9) for buffer in range(2)
            },
        }

    def save_weights(self, _pufferl, path):
        Path(path).write_bytes(b"unchanged-primary-weights")

    def load_frozen_bank(self, _pufferl, bank, path):
        if not hasattr(self, "loaded"):
            self.loaded = []
        self.loaded.append((bank, Path(path).name))


class RatioDriftBackend(StrictBackend):
    def qualification_snapshot(self, pufferl, max_bytes, include_rollout):
        result = super().qualification_snapshot(pufferl, max_bytes, include_rollout)
        if self.train_calls:
            result["mb_ratio"][0] = np.float32(1.0001)
        return result


class EightBankQualificationTests(unittest.TestCase):
    IMPLEMENTATION = {
        "source_sha256": "a" * 64,
        "compiled_module_sha256": "b" * 64,
        "puffer_patch_bundle_sha256": "c" * 64,
    }
    RUNTIME_IDENTITY = {
        "environment_sha256": "a" * 64,
        "module_sha256": "b" * 64,
        "backend_sources_sha256": "d" * 64,
        "compiled_backend_sha256": "d" * 64,
        "compiled_env": "bloodbowl",
        "observation_abi": "obs-v7",
        "observation_version": 7,
        "action_abi": "exact-joint-v1",
        "rollout_transition_contract": "terminal-aware-tbptt-v1",
        "entropy_schedule_contract":
            "cosine-update-index-over-total-updates-fp32-v1",
        "precision_bytes": 4,
    }

    def write_screen_manifest(self, directory, *, patch_bundle="c" * 64):
        identity = self.RUNTIME_IDENTITY
        implementation = {
            "source_sha256": identity["environment_sha256"],
            "compiled_module_sha256": identity["module_sha256"],
            "compiled_backend_sources_sha256": identity["backend_sources_sha256"],
            "vendor_source_sha256": identity["backend_sources_sha256"],
            "puffer_patch_bundle_sha256": patch_bundle,
            "compiled_semantic_contract": {
                "env_name": identity["compiled_env"],
                "environment_source_sha256": identity["environment_sha256"],
                "exact_action_source_sha256": identity["compiled_backend_sha256"],
                "observation_abi": identity["observation_abi"],
                "observation_version": identity["observation_version"],
                "action_abi": identity["action_abi"],
                "rollout_transition_contract":
                    identity["rollout_transition_contract"],
                "entropy_schedule_contract":
                    identity["entropy_schedule_contract"],
                "precision_bytes": identity["precision_bytes"],
            },
        }
        path = Path(directory) / "SCREEN_MANIFEST.json"
        path.write_text(json.dumps({"contract": {"implementation": implementation}}))
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def write_pool(self, pool, *, qualification_only=False,
                   lineage_required=True):
        seeds = []
        for bank in range(8):
            name = f"{bank:016d}.bin"
            lineage_name = name + ".lineage.json"
            blob = bytes([bank]) * 8
            lineage = json.dumps({"bank": bank}).encode()
            (pool / name).write_bytes(blob)
            (pool / lineage_name).write_bytes(lineage)
            seeds.append({
                "bank": bank, "name": f"seed-{bank}", "file": name,
                "bytes": 8, "sha256": hashlib.sha256(blob).hexdigest(),
                "lineage_file": lineage_name,
                "lineage_sha256": hashlib.sha256(lineage).hexdigest(),
            })
        manifest = pool / "league_seeds.json"
        manifest.write_text(json.dumps({
            "lineage_required": lineage_required,
            "qualification_only": qualification_only,
            "expected_bytes": 8, "seeds": seeds,
        }))
        return manifest, {
            "ancestry": {"qualification_only": qualification_only}
        }

    def test_budget_covers_the_declared_public_update_limit(self):
        for calls in (11, 64, 96):
            config = subject.profile_config(42, calls)
            batch = config["vec"]["total_agents"] * config["train"]["horizon"]
            self.assertEqual(config["train"]["total_timesteps"] // batch, calls)
            self.assertEqual(config["train"]["learning_rate"], 0.0)
        with self.assertRaises(q.QualificationError):
            subject.profile_config(42, 10)

    def test_native_compact_patch_preserves_default_and_closed_schema(self):
        patch = (
            Path(__file__).with_name("puffer_compact_qualification_snapshot.patch")
            .read_text()
        )
        self.assertIn("bool include_rollout = true", patch)
        self.assertIn('py::arg("include_rollout") = true', patch)
        self.assertIn("if (include_rollout) {", patch)
        self.assertIn('result["include_rollout"] = include_rollout', patch)
        # Ratio/ownership evidence stays outside the conditional large surface.
        conditional_end = patch.index("+    }")
        self.assertGreater(patch.index('tensors["mb_ratio"]'), conditional_end)
        self.assertGreater(patch.index('tensors["selected_rows"]'), conditional_end)

    def test_terminal_native_patch_exposes_the_exact_compact_schema(self):
        terminal_patch = (
            Path(__file__).with_name("puffer_terminal_aware_native.patch")
            .read_text()
        )
        patch = terminal_patch + (
            Path(__file__).with_name("puffer_compact_qualification_snapshot.patch")
            .read_text()
        )
        expected = set(subject.terminal_snapshot_shapes(subject.profile_config(42)))
        actual = {
            name for name in expected
            if f'tensors["{name}"] = qualification_' in patch
        }
        self.assertEqual(actual, expected)
        self.assertIn(
            'm.attr("rollout_transition_contract") = "terminal-aware-tbptt-v1"',
            terminal_patch,
        )

    def test_profile_config_is_exact_and_lr_zero(self):
        config = subject.profile_config(42)
        self.assertEqual(config["vec"]["total_agents"], 2048)
        self.assertEqual(config["vec"]["num_buffers"], 2)
        self.assertEqual(config["vec"]["num_frozen_banks"], 8)
        self.assertEqual(config["vec"]["frozen_bank_pct"], 0.06)
        self.assertEqual(config["env"]["scripted_bank_mask"], 3)
        self.assertEqual(config["train"]["learning_rate"], 0.0)
        self.assertEqual(config["cudagraphs"], q.DEFAULT_CUDAGRAPH_WARMUP_EPOCHS)

    def test_layout_reports_all_eighteen_exact_groups(self):
        evidence = subject.validate_profile_layout(state_report())
        self.assertEqual(evidence["group_count"], 18)
        self.assertEqual(len(evidence["primary_rows"]), 1072)
        self.assertEqual(len(evidence["frozen_rows"]), 976)
        self.assertEqual(evidence["scripted_frozen_banks"], [0, 1])

    def test_layout_rejects_one_wrong_or_missing_group(self):
        wrong = state_report()
        wrong["entries"][3]["active_rows"] = 60
        with self.assertRaises(q.QualificationError):
            subject.validate_profile_layout(wrong)
        missing = state_report()
        missing["entries"].pop()
        with self.assertRaises(q.QualificationError):
            subject.validate_profile_layout(missing)

    def test_strict_lifecycle_reset_graph_boundary_and_ratio_coverage(self):
        backend = StrictBackend()
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            q, "decode_snapshot", side_effect=lambda value: {
                key: item for key, item in value.items() if isinstance(item, np.ndarray)
            }
        ):
            result, arrays = subject.exercise_profile(
                backend, object(), subject.profile_config(42), Path(directory),
                ratio_call_limit=64,
            )
        self.assertEqual(backend.rollout_calls, backend.train_calls)
        self.assertEqual(result["rollout_calls"], result["train_calls"])
        self.assertGreaterEqual(result["train_calls"], 11)
        self.assertTrue(result["graph_capture_exercised"])
        self.assertEqual(len(result["graph_execution_cycles"]), result["train_calls"])
        self.assertEqual(result["graph_execution_cycles"][0]["graph_delta"], {
            "rollout": 128, "tail": 2, "train": 8,
        })
        self.assertTrue(result["explicit_reset_zero"])
        self.assertEqual(result["weights_before_sha256"], result["weights_after_sha256"])
        self.assertEqual(len(result["ratio"]["covered_primary_rows"]), 1072)
        self.assertEqual(set(backend.snapshot_limits), {64 << 20})
        self.assertEqual(set(backend.snapshot_modes), {False})
        self.assertEqual(result["first_fresh_snapshot"]["decoder_group_count"], 18)
        self.assertEqual(
            result["first_fresh_snapshot"]["used_bytes"],
            subject.snapshot_byte_budget(subject.profile_config(42))[
                "declared_exact_bytes"],
        )
        self.assertNotIn("first_observations", arrays)

    def test_snapshot_budget_is_shape_bound_and_fail_closed(self):
        budget = subject.snapshot_byte_budget(subject.profile_config(42))
        self.assertEqual(budget["cap_bytes"], 64 << 20)
        self.assertEqual(budget["declared_exact_bytes"], 18_031_632)
        self.assertEqual(budget["declared_upper_bound_bytes"], 18_031_632)
        self.assertEqual(budget["tensor_shapes"], {
            "mb_ratio": (256, 64),
            "selected_rows": (256,),
            "segment_initial_states": (3, 2048, 512),
            "mb_initial_states": (3, 256, 512),
            "mb_observation_terminals": (256, 64),
            "segment_initial_valid": (2,),
            "tail_valid": (2,),
            "tail_values": (2048,),
            "tail_terminals": (2048,),
        })
        self.assertLessEqual(budget["declared_upper_bound_bytes"], budget["cap_bytes"])
        config = subject.profile_config(42)
        config["vec"]["total_agents"] = 65536
        with self.assertRaises(q.QualificationError):
            subject.snapshot_byte_budget(config)

    def test_compact_snapshot_rejects_wrong_native_mode_or_schema(self):
        backend = StrictBackend()
        budget = subject.snapshot_byte_budget(subject.profile_config(42))
        original = backend.qualification_snapshot
        backend.qualification_snapshot = lambda p, cap, compact: {
            **original(p, cap, compact), "include_rollout": True,
        }
        with mock.patch.object(q, "decode_snapshot", side_effect=lambda value: value):
            with self.assertRaises(q.QualificationError):
                subject.take_snapshot(backend, object(), budget)

    def test_compact_snapshot_rejects_missing_extra_wrong_shape_and_dtype(self):
        config = subject.profile_config(42)
        budget = subject.snapshot_byte_budget(config)
        decoder = lambda value: {
            key: item for key, item in value.items()
            if isinstance(item, np.ndarray)
        }
        for defect in ("missing", "extra", "shape", "dtype", "contract"):
            backend = StrictBackend()
            original = backend.qualification_snapshot

            def broken(pufferl, cap, compact, *, defect=defect):
                result = original(pufferl, cap, compact)
                if defect == "missing":
                    result["tensors"].pop("tail_terminals")
                elif defect == "extra":
                    result["tensors"]["old_rollout_terminals"] = object()
                elif defect == "shape":
                    result["mb_initial_states"] = np.zeros(
                        (3, 255, 512), dtype=np.float32)
                elif defect == "dtype":
                    result["segment_initial_valid"] = np.zeros((2,), dtype=np.float32)
                return result

            backend.qualification_snapshot = broken
            if defect == "contract":
                backend.rollout_transition_contract = "ppo-v1"
            with self.subTest(defect=defect), mock.patch.object(
                q, "decode_snapshot", side_effect=decoder
            ), self.assertRaises(q.QualificationError):
                subject.take_snapshot(backend, object(), budget)

    def test_loads_all_eight_real_manifest_blobs_in_bank_order(self):
        backend = StrictBackend()
        with tempfile.TemporaryDirectory() as directory:
            pool = Path(directory)
            manifest, validated = self.write_pool(pool)
            with mock.patch.object(
                subject.checkpoint_lineage, "validate_lineage",
                return_value=validated,
            ) as check, mock.patch.object(
                subject.checkpoint_lineage, "lineage_digest",
                return_value="d" * 64,
            ):
                evidence = subject.load_real_frozen_banks(
                    backend, object(), manifest,
                    expected_implementation=self.IMPLEMENTATION,
                    allow_qualification=False,
                )
        self.assertEqual(backend.loaded, [
            (bank, f"{bank:016d}.bin") for bank in range(8)
        ])
        self.assertEqual(evidence["loaded_bank_indices"], list(range(8)))
        self.assertEqual(check.call_count, 8)
        self.assertTrue(all(
            item["qualification_only"] is False for item in evidence["seeds"]))
        for call in check.call_args_list:
            self.assertEqual(call.kwargs["expected"], self.IMPLEMENTATION)
            self.assertIs(call.kwargs["require_eligible"], True)

    def test_qualification_mode_is_explicit_and_propagated(self):
        backend = StrictBackend()
        with tempfile.TemporaryDirectory() as directory:
            pool = Path(directory)
            manifest, validated = self.write_pool(pool, qualification_only=True)
            with self.assertRaisesRegex(
                q.QualificationError, "requires --allow-qualification"
            ):
                subject.load_real_frozen_banks(
                    backend, object(), manifest,
                    expected_implementation=self.IMPLEMENTATION,
                    allow_qualification=False,
                )
            with mock.patch.object(
                subject.checkpoint_lineage, "validate_lineage",
                return_value=validated,
            ) as check, mock.patch.object(
                subject.checkpoint_lineage, "lineage_digest",
                return_value="d" * 64,
            ):
                evidence = subject.load_real_frozen_banks(
                    backend, object(), manifest,
                    expected_implementation=self.IMPLEMENTATION,
                    allow_qualification=True,
                )
        self.assertTrue(all(item["qualification_only"] for item in evidence["seeds"]))
        self.assertTrue(all(
            call.kwargs["require_eligible"] is False
            for call in check.call_args_list))

    def test_cli_requires_hash_pinned_screen_manifest_and_defaults_to_eligible_lineage(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                subject.parse_args([
                    "--puffer-root", "/puffer", "--output", "/out",
                    "--league-manifest", "/pool/league_seeds.json",
                ])
        args = subject.parse_args([
            "--puffer-root", "/puffer", "--output", "/out",
            "--league-manifest", "/pool/league_seeds.json",
            "--screen-manifest", "/run/SCREEN_MANIFEST.json",
            "--screen-manifest-sha256", "a" * 64,
        ])
        self.assertFalse(args.allow_qualification)

    def test_screen_manifest_supplies_measured_patch_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, digest = self.write_screen_manifest(directory)
            evidence = subject.validate_screen_manifest(
                manifest, digest, self.RUNTIME_IDENTITY)
        self.assertEqual(evidence["sha256"], digest)
        self.assertEqual(evidence["puffer_patch_bundle_sha256"], "c" * 64)

    def test_arbitrary_patch_bundle_or_runtime_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, digest = self.write_screen_manifest(
                directory, patch_bundle="4" * 64)
            # The CLI has no free-form patch-bundle argument. The only accepted
            # value is the one inside the hash-pinned measured manifest.
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                subject.parse_args([
                    "--puffer-root", "/puffer", "--output", "/out",
                    "--league-manifest", "/pool/league_seeds.json",
                    "--patch-bundle-sha256", "4" * 64,
                ])
            for defect in (
                "digest", "module_sha256", "environment_sha256",
                "backend_sources_sha256", "compiled_backend_sha256",
                "compiled_env",
            ):
                identity = dict(self.RUNTIME_IDENTITY)
                supplied_digest = digest
                if defect == "digest":
                    supplied_digest = "0" * 64
                elif defect == "compiled_env":
                    identity[defect] = "other"
                else:
                    identity[defect] = "e" * 64
                with self.subTest(defect=defect), self.assertRaises(
                        q.QualificationError):
                    subject.validate_screen_manifest(
                        manifest, supplied_digest, identity)

    def test_old_manifest_and_missing_or_tampered_lineage_are_rejected(self):
        for defect in ("old", "missing", "tampered"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as directory:
                pool = Path(directory)
                manifest, _ = self.write_pool(
                    pool, lineage_required=(defect != "old"))
                data = json.loads(manifest.read_text())
                lineage = pool / data["seeds"][0]["lineage_file"]
                if defect == "missing":
                    lineage.unlink()
                elif defect == "tampered":
                    lineage.write_text("tampered")
                with self.assertRaises(q.QualificationError):
                    subject.load_real_frozen_banks(
                        StrictBackend(), object(), manifest,
                        expected_implementation=self.IMPLEMENTATION,
                        allow_qualification=True,
                    )

    def test_source_module_and_patch_lineage_mismatches_are_rejected(self):
        for key in self.IMPLEMENTATION:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                pool = Path(directory)
                manifest, _ = self.write_pool(pool)
                error = subject.checkpoint_lineage.LineageError(
                    f"{key} lineage mismatch")
                with mock.patch.object(
                    subject.checkpoint_lineage, "validate_lineage",
                    side_effect=error,
                ), self.assertRaisesRegex(q.QualificationError, key):
                    subject.load_real_frozen_banks(
                        StrictBackend(), object(), manifest,
                        expected_implementation=self.IMPLEMENTATION,
                        allow_qualification=True,
                    )

    def test_real_frozen_loading_rejects_tampered_blob(self):
        backend = StrictBackend()
        with tempfile.TemporaryDirectory() as directory:
            pool = Path(directory)
            manifest, _ = self.write_pool(pool)
            data = json.loads(manifest.read_text())
            (pool / data["seeds"][0]["file"]).write_bytes(b"tampered")
            with self.assertRaises(q.QualificationError):
                subject.load_real_frozen_banks(
                    backend, object(), manifest,
                    expected_implementation=self.IMPLEMENTATION,
                    allow_qualification=True,
                )

    def test_call_limit_cannot_claim_graph_capture(self):
        backend = StrictBackend()
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            q, "decode_snapshot", side_effect=lambda value: {
                key: item for key, item in value.items() if isinstance(item, np.ndarray)
            }
        ):
            with self.assertRaises(q.QualificationError):
                subject.exercise_profile(
                    backend, object(), subject.profile_config(42), Path(directory),
                    ratio_call_limit=10,
                )

    def test_graph_gate_rejects_eager_or_wrong_launch_delta(self):
        config = subject.profile_config(42)
        before = StrictBackend().qualification_graph_execution(object())
        after = {**before,
                 "graph_launch_counts": {"rollout": 127, "tail": 2, "train": 8}}
        with self.assertRaises(q.QualificationError):
            subject.validate_graph_cycle(before, after, config)
        after = {**before,
                 "graph_launch_counts": {"rollout": 128, "tail": 2, "train": 8},
                 "eager_execution_counts": {"rollout": 1, "tail": 0, "train": 0}}
        with self.assertRaises(q.QualificationError):
            subject.validate_graph_cycle(before, after, config)

    def test_ratio_failure_preserves_npz_and_per_call_distribution(self):
        backend = RatioDriftBackend()
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            q, "decode_snapshot", side_effect=lambda value: {
                key: item for key, item in value.items() if isinstance(item, np.ndarray)
            }
        ):
            root = Path(directory)
            with self.assertRaisesRegex(q.QualificationError, "ratio error"):
                subject.exercise_profile(
                    backend, object(), subject.profile_config(42, 64), root,
                    ratio_call_limit=64,
                )
            artifact = root / subject.PARTIAL_ARTIFACT_NAME
            progress = q._read_json(root / "PROGRESS.json")
            self.assertTrue(artifact.is_file())
            self.assertEqual(progress["completed_updates"], backend.train_calls)
            self.assertEqual(len(progress["ratio_calls"]), backend.train_calls)
            self.assertEqual(len(progress["graph_execution_cycles"]), backend.train_calls)
            self.assertGreater(
                progress["ratio_calls"][0]["max_abs_ratio_minus_one"], 2e-5
            )
            self.assertGreater(progress["ratio_calls"][0]["elements_over_atol"], 0)
            with np.load(artifact, allow_pickle=False) as saved:
                self.assertIn("selected_0", saved.files)
                self.assertIn("ratio_0", saved.files)

    def test_ratio_summary_is_json_safe_for_nonfinite_values(self):
        summary = subject.summarize_ratio_call(
            np.array([0, 1], dtype=np.int32),
            np.array([np.nan, np.inf], dtype=np.float32), atol=2e-5,
        )
        self.assertEqual(summary["nonfinite_elements"], 2)
        self.assertIsNone(summary["max_abs_ratio_minus_one"])
        json.dumps(summary, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
