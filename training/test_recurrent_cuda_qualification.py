"""Contracts for the deployment-bound recurrent CUDA qualification gate."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import subprocess
import tempfile
import textwrap
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np


ROOT = pathlib.Path(__file__).resolve().parents[1]
PATCH = ROOT / "training" / "puffer_recurrent_cuda_qualification.patch"
PRIO_PATCH = ROOT / "training" / "puffer_frozen_prio_mask.patch"
LEAGUE_PATCH = ROOT / "training" / "selfplay_league.patch"
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

    def test_candidate_commit_is_explicitly_bound_to_clean_runner(self):
        commit = "f" * 40
        self.q.validate_candidate_source_authority(
            commit, {"source_commit": commit}
        )
        for supplied in ("e" * 40, "not-a-commit"):
            with self.subTest(supplied=supplied), self.assertRaisesRegex(
                self.q.QualificationError, "predeclared candidate"
            ):
                self.q.validate_candidate_source_authority(
                    supplied, {"source_commit": commit}
                )

    def test_schema_two_qualification_is_explicitly_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            artifact = pathlib.Path(temporary) / "QUALIFICATION.json"
            artifact.write_text(
                json.dumps({"schema_version": 2}), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                self.q.QualificationError, "schema version mismatch"
            ):
                self.q.validate_qualification(artifact)

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

    def test_qualification_source_identity_includes_selfplay_patch(self):
        relative = {
            path.relative_to(ROOT).as_posix()
            for path in self.q.qualification_source_paths(ROOT)
        }
        self.assertIn("training/selfplay_league.patch", relative)
        self.assertEqual(
            hashlib.sha256(LEAGUE_PATCH.read_bytes()).hexdigest(),
            self.q.sha256(LEAGUE_PATCH),
        )
        self.assertIn("pufferlib/selfplay.py", self.q.BACKEND_SOURCE_FILES)
        self.assertEqual(
            self.q.PREDECESSOR_BACKEND_SOURCE_FILES,
            (
                "pufferlib/pufferl.py",
                "pufferlib/torch_pufferl.py",
                "src/bindings.cu",
                "src/bindings_cpu.cpp",
                "src/kernels.cu",
                "src/pufferlib.cu",
                "src/vecenv.h",
            ),
        )
        self.assertNotIn(
            "pufferlib/selfplay.py", self.q.PREDECESSOR_BACKEND_SOURCE_FILES
        )

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

    def test_qualification_source_identity_rejects_selfplay_drift_and_deletion(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = pathlib.Path(temporary)
            for original in self.q.qualification_source_paths(ROOT):
                relative = original.relative_to(ROOT)
                copied = source / relative
                copied.parent.mkdir(parents=True, exist_ok=True)
                copied.write_bytes(original.read_bytes())
            recorded = self.q.qualification_source_identity(source)
            self.q.validate_qualification_source_identity(recorded, source)

            league = source / "training/selfplay_league.patch"
            pristine = league.read_bytes()
            league.write_bytes(pristine + b"\n# drift\n")
            with self.assertRaisesRegex(
                self.q.QualificationError, "source-file identity drifted"
            ):
                self.q.validate_qualification_source_identity(recorded, source)

            league.write_bytes(pristine)
            league.unlink()
            with self.assertRaisesRegex(
                self.q.QualificationError, "source-file identity is incomplete"
            ):
                self.q.validate_qualification_source_identity(recorded, source)

    def test_backend_identity_changes_with_selfplay_and_rejects_its_absence(self):
        with tempfile.TemporaryDirectory() as temporary:
            puffer = pathlib.Path(temporary)
            for index, relative in enumerate(self.q.BACKEND_SOURCE_FILES):
                path = puffer / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"surface-{index}\n".encode())
            before = self.q.backend_source_hash(puffer)
            selfplay = puffer / "pufferlib/selfplay.py"
            selfplay.write_bytes(b"changed-selfplay-semantics\n")
            after = self.q.backend_source_hash(puffer)
            self.assertNotEqual(before, after)
            selfplay.unlink()
            with self.assertRaises(self.q.QualificationError):
                self.q.backend_source_hash(puffer)

    def test_predecessor_keeps_historical_compiled_digest_but_binds_full_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            puffer = pathlib.Path(temporary)
            for index, relative in enumerate(self.q.BACKEND_SOURCE_FILES):
                path = puffer / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"surface-{index}\n".encode())
            module = puffer / "pufferlib/_C.so"
            module.write_bytes(b"predecessor-module\n")
            snapshot = puffer / "ocean/bloodbowl/.content_hash"
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_text("b" * 64 + "\n", encoding="ascii")

            compiled = self.q.backend_source_hash(
                puffer, source_files=self.q.PREDECESSOR_BACKEND_SOURCE_FILES
            )
            backend = SimpleNamespace(
                exact_action_source_hash=compiled,
                environment_source_hash="b" * 64,
                observation_abi="obs-v5",
                observation_version=5,
                action_abi="exact-joint-v1",
                precision_bytes=4,
                env_name="bloodbowl",
            )
            identity = self.q._module_identity(backend, module, puffer)

            self.assertIs(identity["qualification_surface"], False)
            self.assertEqual(identity["backend_sources_sha256"], compiled)
            self.assertEqual(
                identity["runtime_sources_sha256"],
                self.q.backend_source_hash(puffer),
            )
            self.q.validate_module_identity(identity, qualification_surface=False)
            self.q.validate_current_identity_files(identity)

            (puffer / "pufferlib/selfplay.py").write_bytes(
                b"changed-runtime-selfplay-semantics\n"
            )
            with self.assertRaisesRegex(
                self.q.QualificationError, "runtime sources drifted"
            ):
                self.q.validate_current_identity_files(identity)

    def test_candidate_compiled_and_runtime_digests_use_complete_registry(self):
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
                observation_abi="obs-v5",
                observation_version=5,
                action_abi="exact-joint-v1",
                precision_bytes=4,
                env_name="bloodbowl",
                qualification_recurrent_state=object(),
                qualification_snapshot=object(),
            )
            identity = self.q._module_identity(backend, module, puffer)

            self.assertIs(identity["qualification_surface"], True)
            self.assertEqual(identity["backend_sources_sha256"], compiled)
            self.assertEqual(identity["runtime_sources_sha256"], compiled)
            self.q.validate_module_identity(identity, qualification_surface=True)
            self.q.validate_current_identity_files(identity)

            missing_runtime = dict(identity)
            del missing_runtime["runtime_sources_sha256"]
            with self.assertRaisesRegex(
                self.q.QualificationError, "runtime_sources_sha256"
            ):
                self.q.validate_module_identity(
                    missing_runtime, qualification_surface=True
                )

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
            "runtime_sources_sha256": digest,
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
        candidate_commit = "f" * 40
        expected = {
            "source_commit": candidate_commit,
            "module_sha256": digest,
            "backend_sha256": digest,
            "environment_sha256": "b" * 64,
        }
        self.q.validate_expected_candidate_identity(
            identity, expected, authorized_source_commit=candidate_commit
        )
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_expected_candidate_identity(
                identity,
                dict(expected, backend_sha256="c" * 64),
                authorized_source_commit=candidate_commit,
            )
        with self.assertRaisesRegex(
            self.q.QualificationError, "predeclared authority"
        ):
            self.q.validate_expected_candidate_identity(
                identity,
                expected,
                authorized_source_commit="e" * 40,
            )
        predecessor_identity = dict(identity, qualification_surface=False)
        predecessor_expected = {
            "source_commit": self.q.PREDECESSOR_SOURCE_COMMIT,
            "module_sha256": expected["module_sha256"],
            "backend_sha256": expected["backend_sha256"],
            "runtime_sha256": predecessor_identity["runtime_sources_sha256"],
            "environment_sha256": expected["environment_sha256"],
        }
        self.q.validate_expected_predecessor_identity(
            predecessor_identity, predecessor_expected
        )
        with self.assertRaisesRegex(
            self.q.QualificationError, "frozen runtime_sha256"
        ):
            self.q.validate_expected_predecessor_identity(
                predecessor_identity,
                dict(predecessor_expected, runtime_sha256="c" * 64),
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
            "runtime_sources_sha256": digest,
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
                    "runtime_sha256": digest,
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

            wrapper["schema_version"] = 2
            wrapper_path.write_text(json.dumps(wrapper), encoding="utf-8")
            with self.assertRaisesRegex(
                self.q.QualificationError, "baseline schema version mismatch"
            ):
                self.q.validate_baseline_artifact(wrapper_path)
            wrapper["schema_version"] = self.q.SCHEMA_VERSION
            wrapper_path.write_text(json.dumps(wrapper), encoding="utf-8")

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
            with self.assertRaises(self.q.QualificationError):
                self.q.validate_source_checkout(
                    source,
                    puffer,
                    expected_commit="f" * 40,
                    role="predecessor",
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
                        "--expected-source-commit", "f" * 40,
                        "--expected-candidate-module-sha256", "a" * 64,
                        "--expected-candidate-backend-sha256", "b" * 64,
                        "--expected-environment-sha256", "c" * 64,
                        "--expected-predecessor-source-commit",
                        self.q.PREDECESSOR_SOURCE_COMMIT,
                        "--expected-predecessor-module-sha256", "d" * 64,
                        "--expected-predecessor-backend-sha256", "e" * 64,
                        "--expected-predecessor-runtime-sha256", "f" * 64,
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
            "--expected-source-commit", "f" * 40,
            "--expected-candidate-module-sha256", "a" * 64,
            "--expected-candidate-backend-sha256", "b" * 64,
            "--expected-environment-sha256", "c" * 64,
            "--expected-predecessor-source-commit",
            self.q.PREDECESSOR_SOURCE_COMMIT,
            "--expected-predecessor-module-sha256", "d" * 64,
            "--expected-predecessor-backend-sha256", "e" * 64,
            "--expected-predecessor-runtime-sha256", "f" * 64,
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
            "--expected-predecessor-runtime-sha256", "d" * 64,
            "--expected-environment-sha256", "c" * 64,
        ]
        for command_args in (run_args, capture_args):
            root_index = command_args.index("--predecessor-source-root")
            omitted = command_args[:root_index] + command_args[root_index + 2:]
            with self.subTest(command=command_args[0]), mock.patch("sys.stderr"), \
                    self.assertRaises(SystemExit) as raised:
                self.q.parse_args(omitted)
            self.assertEqual(raised.exception.code, 2)

            runtime_index = command_args.index(
                "--expected-predecessor-runtime-sha256"
            )
            omitted_runtime = (
                command_args[:runtime_index] + command_args[runtime_index + 2:]
            )
            with self.subTest(
                command=command_args[0], required="runtime"
            ), mock.patch("sys.stderr"), self.assertRaises(SystemExit) as raised:
                self.q.parse_args(omitted_runtime)
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
            "3845f6e79e5702f09f5620fa46ca3badfab5be658761e6295cd685a426aaec67",
        )
        self.assertIn("exact-action-canary is frozen", launcher)
        self.assertIn("a52fc6e2f4ece5a7ff16bb4791e3aca4dd72f2e3", launcher)
        self.assertIn("permanently rejected", launcher)
        self.assertIn("no replacement is authorized", launcher)
        self.assertNotIn("invoke that exact isolated checkout", launcher)

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
            "3af34715cfa0cc848c0c8ba2effa48a2916f0c1059d0760dcef3a97fb1030d91",
            "00e9c32cde253d8f3639c13985d3e30d181e40735cd027678afd9399e46e274a",
            "134f4cb066d43dd6e30e910b07e2da30308ffd89a8dbf8fd6939ecd1d1b2e5c9",
            "20f306a4c042e7fea8ed1fec3107eeb048ecf6ace212a1c82172f42cd32de9ed",
            "9f019876e51a9810c2ddcafa72afbbe96b623c9fc9c970c46a0c73f192f8bf42",
            "0592a95210e094c7942ffaa9af53a10d8e274991553e47e2366a5fa714902b0e",
            "Only a newly hash-bound authorization and the fresh v3 unit identity",
            "exact-action-canary-v3-execution/CANARY_AUTHORIZATION.json",
            "Every newly created prelaunch v3 validator capture, canonical unit/probe copy, authorization, inventory, status, and journal",
            "Do not rerun the launcher and do not rematerialize its output",
            "Run the independent manifest validator twice again",
            "fixed stopped-validation output to exist as an empty directory",
            "exact unit name `bloodbowl-exact-action-canary-50m-s42-v3.service`",
            "gate2-validator-{1,2}.{stdout,stderr,status}",
            "closed six-file validator set",
            "Canonical v3 unit source",
            "Install only the already hash-bound canonical unit bytes",
            "Gate 6 artifacts must be written only to the separately authorized stopped-validation output",
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
        self.assertIn(
            "- Unit name: `bloodbowl-exact-action-canary-50m-s42-v3.service`",
            checklist,
        )
        self.assertNotIn(
            "- Unit name: `bloodbowl-exact-action-canary-50m-s42-v2.service`",
            checklist,
        )
        self.assertNotIn(
            "The canary output path and unit name do not exist",
            checklist,
        )
        self.assertIn(
            "The accepted v2 canary output exists as exactly the unchanged regular",
            checklist,
        )
        self.assertIn(
            "Install only the already hash-bound canonical unit bytes below as\n"
            "`bloodbowl-exact-action-canary-50m-s42-v3.service`",
            checklist,
        )
        rejection_rows = {
            "Gate 3 authorization": (
                "exact-action-canary-v2-execution/CANARY_AUTHORIZATION.json",
                "3af34715cfa0cc848c0c8ba2effa48a2916f0c1059d0760dcef3a97fb1030d91",
            ),
            "v2 unit bytes": (
                "exact-action-canary-v2-execution/"
                "bloodbowl-exact-action-canary-50m-s42-v2.service",
                "00e9c32cde253d8f3639c13985d3e30d181e40735cd027678afd9399e46e274a",
            ),
            "Probe runner": (
                "exact-action-canary-v2-execution/gate4-synthetic-probes.sh",
                "134f4cb066d43dd6e30e910b07e2da30308ffd89a8dbf8fd6939ecd1d1b2e5c9",
            ),
            "Empty-probe journal": (
                "exact-action-canary-v2-execution/gate4-attempt1-empty-journal.txt",
                "20f306a4c042e7fea8ed1fec3107eeb048ecf6ace212a1c82172f42cd32de9ed",
            ),
            "Post-cleanup proof": (
                "exact-action-canary-v2-execution/gate4-attempt1-post-cleanup.txt",
                "9f019876e51a9810c2ddcafa72afbbe96b623c9fc9c970c46a0c73f192f8bf42",
            ),
            "Rejection record": (
                "exact-action-canary-v2-execution/gate4-attempt1-rejection.txt",
                "0592a95210e094c7942ffaa9af53a10d8e274991553e47e2366a5fa714902b0e",
            ),
        }
        rejection_root = (
            "/home/rache/bloodbowl-rl-qualification-artifacts-20260722/"
        )
        for label, (relative_path, digest) in rejection_rows.items():
            with self.subTest(rejected_artifact=label):
                self.assertIn(
                    f"| {label} | `{rejection_root}{relative_path}` | "
                    f"`{digest}` |",
                    checklist,
                )

        unit_block = checklist.split("```ini\n", 1)[1].split("\n```", 1)[0]
        self.assertIn('/usr/bin/printf "%%s" "$${out}"', unit_block)
        self.assertNotIn('/usr/bin/printf "%s" "$${out}"', unit_block)
        self.assertIn("$$(/usr/local/bin/nvidia-smi", unit_block)
        self.assertIn('test -z "$${stripped}"', unit_block)
        self.assertIn("bare `%s` is its user-shell", checklist)
        self.assertIn("`%%s` format escape", normalized_checklist)

        qualification = QUALIFICATION_CHECKLIST.read_text(encoding="utf-8")
        self.assertIn("zero-byte, released, hash-bound `.screen.lock`", qualification)
        self.assertIn("exactly two regular files", qualification)
        self.assertIn(
            "leaves `SCREEN_MANIFEST.json` byte-identical",
            " ".join(qualification.split()),
        )
        self.assertIn('`"%%s"` in unit', qualification)
        self.assertIn('bare `"%s"` is invalid', qualification)

        required_guidance = {
            AGENTS: (
                "run_reward_screen.sh creates $OUT_DIR/.screen.lock",
                "hash its mode/size with the manifest",
                "written %%s in unit bytes",
            ),
            CLAUDE: (
                "The frozen screen launcher intentionally creates and retains",
                "with both modes, sizes, and hashes bound",
                'printf "%%s" in unit bytes',
            ),
            TRAINING_SKILL: (
                "The frozen screen launcher creates $OUT_DIR/.screen.lock",
                "Hash both and their modes/sizes",
                'printf "%s" must be authored as printf "%%s"',
            ),
            FLEET_SKILL: (
                "For canary plan-only closure, account for the launcher's persistent ownership inode",
                "bind both files' modes, sizes, and digests",
                'Author an intended printf "%s" as printf "%%s"',
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
        rejected_candidate = "a52fc6e2f4ece5a7ff16bb4791e3aca4dd72f2e3"
        plan = PLAN.read_text(encoding="utf-8")
        checklist = QUALIFICATION_CHECKLIST.read_text(encoding="utf-8")
        self.assertIn(predecessor, plan)
        self.assertIn(rejected_candidate, plan)
        self.assertIn("own pinned Puffer", plan)
        self.assertIn("different from the predecessor tree", plan)
        self.assertIn("--predecessor-source-root", plan)
        self.assertIn("--expected-predecessor-source-commit", plan)
        self.assertIn("--candidate-source-root", plan)
        self.assertIn("Independently pass `--predecessor-source-root`", plan)
        self.assertIn("Do not modify or reuse the recovery Puffer tree", plan)
        self.assertIn("`cudagraphs=10`", plan)
        self.assertNotIn("On the still-installed predecessor", plan)
        self.assertNotIn(
            "Launch only from the exact isolated `a52fc6e2", plan
        )
        self.assertNotIn("checkout of exact candidate", plan)
        normalized_plan = " ".join(plan.split())
        self.assertIn(
            f"`{rejected_candidate}` attempt and all of its authorities are "
            "permanently rejected",
            normalized_plan,
        )
        self.assertEqual(
            checklist.count("--expected-predecessor-runtime-sha256"), 2
        )
        self.assertIn(
            "0bf5c09cdc5507bbdf28b3c4c470349c1fecca6b742d2252c27416f7250d14c8",
            checklist,
        )
        for path in (AGENTS, CLAUDE, PUFFER_SKILL, TRAINING_SKILL):
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                normalized = " ".join(text.split())
                self.assertIn(predecessor, text)
                self.assertIn(rejected_candidate, text)
                self.assertIn("different isolated source", text)
                self.assertIn("recovery Puffer tree", text)
                self.assertIn("`cudagraphs=10`", text)
                self.assertIn(
                    "candidate and control runner use the same "
                    "operator-predeclared merged commit",
                    normalized,
                )
                self.assertIn("clean `HEAD`", normalized)
                plain = normalized.replace("`", "")
                for stale_directive in (
                    "Keep exact candidate a52fc6e2",
                    "exact candidate is a52fc6e2",
                    "Launch the canary only from the exact immutable a52fc6e2",
                    "Launch only through the exact immutable a52fc6e2",
                    "Invoke that profile only from the exact isolated a52fc6e2",
                    "only the immutable a52fc6e2 checkout may launch",
                ):
                    self.assertNotIn(stale_directive, plain)

        runner = RUNNER.read_text(encoding="utf-8")
        self.assertEqual(q.PREDECESSOR_SOURCE_COMMIT, predecessor)
        self.assertFalse(hasattr(q, "CANDIDATE_SOURCE_COMMIT"))
        self.assertEqual(
            q.PROTECTED_RECOVERY_ROOT,
            pathlib.Path("/home/rache/bloodbowl-rl-recovery-20260719"),
        )
        for argument in (
            "--predecessor-source-root",
            "--expected-predecessor-source-commit",
            "--candidate-source-root",
            "--expected-source-commit",
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


if __name__ == "__main__":
    unittest.main()
