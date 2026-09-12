import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
import hashlib
import os
import shutil


PATH = Path(__file__).with_name("frozen_scripted_eval.py")
SPEC = importlib.util.spec_from_file_location("frozen_scripted_eval", PATH)
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


class FakePufferl:
    @staticmethod
    def unroll_nested_dict(value):
        return value.items()


class FakeBackend:
    def __init__(self, games):
        self.games = games
        self.train_calls = 0
        self.closed = False

    def create_pufferl(self, args):
        self.args = copy.deepcopy(args)
        return {"step": 0, "completed": []}

    def load_weights(self, runner, checkpoint):
        self.checkpoint = checkpoint

    def set_evaluation_mode(self, runner, value):
        self.evaluation_mode = value

    def rollouts(self, runner):
        runner["completed"].append(self.games[runner["step"]])
        runner["step"] += 1

    def eval_log(self, runner):
        rows = runner["completed"]
        n = len(rows)
        return {"env/n": n, **{
            f"env/{key}": sum(row.get(key, 0.0) for row in rows) / n
            for key in MOD.PER_GAME_METRICS
        }}

    def train(self, runner):
        self.train_calls += 1
        raise AssertionError("evaluation called train")

    def close(self, runner):
        self.closed = True


class FrozenScriptedEvalTests(unittest.TestCase):
    def make_source_root(self, root):
        (root / "puffer/bloodbowl").mkdir(parents=True)
        (root / "engine/include/bb").mkdir(parents=True)
        (root / "engine/src").mkdir(parents=True)
        (root / "puffer/bloodbowl/env.c").write_text("environment\n")
        (root / "engine/include/bb/a.h").write_text("header\n")
        (root / "engine/src/a.c").write_text("source\n")
        os.symlink("../../engine/include/bb", root / "puffer/bloodbowl/bb")
        os.symlink("../../engine/src", root / "puffer/bloodbowl/engine")
        os.symlink("../include/bb", root / "engine/src/bb")

    def make_two_source_roots(self, parent):
        runtime = parent / "runtime"
        snapshot = parent / "snapshot"
        self.make_source_root(runtime)
        shutil.copytree(runtime, snapshot, symlinks=True)
        return runtime, snapshot

    def test_old_generic_tree_hash_rejects_canonical_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_source_root(root)
            from run_reward_candidate_transfer import RunnerError, tree_sha256
            with self.assertRaisesRegex(RunnerError, "unsupported entry"):
                tree_sha256(root / "puffer/bloodbowl")

    def test_source_closure_accepts_exact_runtime_and_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, snapshot = self.make_two_source_roots(Path(directory))
            expected = MOD.source_closure(runtime)["sha256"]
            got = MOD.validate_source_closures(
                runtime_root=runtime, snapshot_root=snapshot,
                expected_sha256=expected)
            self.assertEqual(got["files"], 3)

    def test_source_closure_rejects_changed_runtime_c_file(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, snapshot = self.make_two_source_roots(Path(directory))
            expected = MOD.source_closure(snapshot)["sha256"]
            (runtime / "engine/src/a.c").write_text("corrupted\n")
            with self.assertRaisesRegex(RuntimeError, "closures differ"):
                MOD.validate_source_closures(
                    runtime_root=runtime, snapshot_root=snapshot,
                    expected_sha256=expected)

    def test_source_closure_rejects_unlisted_injected_source(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, snapshot = self.make_two_source_roots(Path(directory))
            expected = MOD.source_closure(snapshot)["sha256"]
            (runtime / "engine/src/injected.c").write_text("injected\n")
            with self.assertRaisesRegex(RuntimeError, "closures differ"):
                MOD.validate_source_closures(
                    runtime_root=runtime, snapshot_root=snapshot,
                    expected_sha256=expected)

    def test_source_closure_rejects_wrong_recomputed_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, snapshot = self.make_two_source_roots(Path(directory))
            with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
                MOD.validate_source_closures(
                    runtime_root=runtime, snapshot_root=snapshot,
                    expected_sha256="a" * 64)

    def test_source_closure_rejects_retargeted_link(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, _ = self.make_two_source_roots(Path(directory))
            (runtime / "puffer/bloodbowl/bb").unlink()
            os.symlink("../../engine/src", runtime / "puffer/bloodbowl/bb")
            with self.assertRaisesRegex(RuntimeError, "links mismatch|retargeted"):
                MOD.source_closure(runtime)

    def test_source_closure_rejects_unexpected_link(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, _ = self.make_two_source_roots(Path(directory))
            os.symlink("../../engine/src", runtime / "puffer/bloodbowl/extra")
            with self.assertRaisesRegex(RuntimeError, "links mismatch"):
                MOD.source_closure(runtime)

    def test_source_closure_rejects_symlinked_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real-puffer"
            real.mkdir()
            os.symlink(real, root / "puffer")
            with self.assertRaisesRegex(RuntimeError, "parent.*symlink"):
                MOD.source_closure(root)

    def test_backend_source_hash_matches_sha256sum_bundle_format(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src/a.c").write_bytes(b"a\n")
            (root / "src/b.c").write_bytes(b"b\n")
            sources = ("src/a.c", "src/b.c")
            payload = b"".join(
                f"{hashlib.sha256((root / name).read_bytes()).hexdigest()}  {name}\n".encode()
                for name in sources)
            self.assertEqual(
                MOD.backend_source_hash(root, sources),
                hashlib.sha256(payload).hexdigest())

    def test_backend_source_registry_rejects_unsafe_and_duplicate_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "registry.txt"
            registry.write_text("src/a.c\n../escape.c\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "unsafe"):
                MOD.load_backend_source_registry(registry)
            registry.write_text("src/a.c\nsrc/a.c\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "duplicate"):
                MOD.load_backend_source_registry(registry)

    def test_evaluation_construction_overrides_fractional_training_replay(self):
        args = MOD.configure_args(
            {"train": {"replay_ratio": 0.25}, "vec": {}, "env": {}},
            learner_side="home", style="contact", seed=6001, max_decisions=4096)
        # Native construction allocates training buffers even for rollout-only use.
        # One H1 two-agent minibatch must survive its integer minibatch count.
        self.assertEqual(args["train"]["replay_ratio"], 1.0)

    def test_learner_perspective_and_no_training(self):
        backend = FakeBackend([
            {"perf": 1.0, "tds_t0": 2.0, "tds_t1": 1.0, "score_diff": 1.0},
            {"perf": 0.5, "tds_t0": 0.0, "tds_t1": 0.0, "score_diff": 0.0},
            {"perf": 0.0, "tds_t0": 0.0, "tds_t1": 1.0, "score_diff": -1.0},
        ])
        args = MOD.configure_args(
            {"train": {}, "vec": {}, "env": {}}, learner_side="away",
            style="contact", seed=42, max_decisions=4096)
        streamed = []
        rows = MOD.run_cell(
            pufferl=FakePufferl, backend=backend, args=args,
            checkpoint=Path("policy.bin"), checkpoint_sha256="a" * 64,
            runtime_identity_sha256="b" * 64, style="contact",
            learner_side="away", seed=42, games=3, max_decisions=4096,
            max_rollouts_per_game=2, max_seconds_per_cell=10,
            on_game=streamed.append)
        self.assertEqual([row["result"] for row in rows],
                         ["loss", "draw", "win"])
        self.assertEqual([row["game_rng_seed"] for row in rows],
                         [7961, 15880, 23799])
        self.assertEqual(backend.train_calls, 0)
        self.assertTrue(backend.evaluation_mode)
        self.assertTrue(backend.closed)
        self.assertEqual(backend.args["vec"]["total_agents"], 2)
        self.assertFalse(backend.args["reset_state"])
        self.assertEqual(streamed, rows)

    def test_native_float32_length_means_reconstruct_exact_counts(self):
        import struct
        f32 = lambda x: struct.unpack("f", struct.pack("f", x))[0]
        previous = {"n": 0.0, **{key: 0.0 for key in MOD.PER_GAME_METRICS}}
        total = 0
        for n, decisions in enumerate([1234, 1432, 1379, 1188, 1321] * 6 + [799, 1765], 1):
            total += decisions
            logs = {f"env/{key}": 0.0 for key in MOD.PER_GAME_METRICS}
            logs.update({"env/n": n, "env/perf": 0.5,
                         "env/episode_length": f32(total / n)})
            row = MOD.game_from_cumulative(
                logs=logs, previous=previous, bot_team=1, style="contact",
                base_seed=6001, checkpoint_sha256="a" * 64,
                runtime_identity_sha256="b" * 64, max_decisions=4096)
            self.assertEqual(row["decisions"], decisions)
            MOD.update_previous(previous, logs)

    def test_native_count_decoder_rejects_fractional_and_ambiguous_means(self):
        for mean, n in [(1234.01, 1), (float(1 << 24), 1)]:
            with self.assertRaises(RuntimeError):
                MOD.exact_integer_total_from_float32_mean(mean, n)

    def test_delta_rejects_batched_completions(self):
        with self.assertRaisesRegex(RuntimeError, "exactly one new game"):
            MOD.cumulative_delta(0.5, 2, 0.0, 0)

    def test_game_rejects_integrity_failure(self):
        previous = {"n": 0.0, **{key: 0.0 for key in MOD.PER_GAME_METRICS}}
        logs = {f"env/{key}": 0.0 for key in MOD.PER_GAME_METRICS}
        logs.update({
            "env/n": 1, "env/perf": 0.5,
            "env/reward_clip_terminal_samples_per_episode": 1.0,
        })
        with self.assertRaisesRegex(RuntimeError, "integrity gates"):
            MOD.game_from_cumulative(
                logs=logs, previous=previous, bot_team=1, style="contact",
                base_seed=42, checkpoint_sha256="a" * 64,
                runtime_identity_sha256="b" * 64, max_decisions=4096)

    def test_game_rejects_tiny_nonzero_integrity_value(self):
        previous = {"n": 0.0, **{key: 0.0 for key in MOD.PER_GAME_METRICS}}
        logs = {f"env/{key}": 0.0 for key in MOD.PER_GAME_METRICS}
        logs.update({"env/n": 1, "env/perf": 0.5,
                     "env/reward_clip_excess": 1e-7})
        with self.assertRaisesRegex(RuntimeError, "integrity gates"):
            MOD.game_from_cumulative(
                logs=logs, previous=previous, bot_team=1, style="contact",
                base_seed=42, checkpoint_sha256="a" * 64,
                runtime_identity_sha256="b" * 64, max_decisions=4096)

    def test_game_rejects_illegal_action_fraction(self):
        previous = {"n": 0.0, **{key: 0.0 for key in MOD.PER_GAME_METRICS}}
        logs = {f"env/{key}": 0.0 for key in MOD.PER_GAME_METRICS}
        logs.update({"env/n": 1, "env/perf": 0.5,
                     "env/illegal_frac": 0.001})
        with self.assertRaisesRegex(RuntimeError, "illegal_frac"):
            MOD.game_from_cumulative(
                logs=logs, previous=previous, bot_team=1, style="contact",
                base_seed=42, checkpoint_sha256="a" * 64,
                runtime_identity_sha256="b" * 64, max_decisions=4096)

    def test_game_rejects_missing_integrity_field(self):
        previous = {"n": 0.0, **{key: 0.0 for key in MOD.PER_GAME_METRICS}}
        logs = {f"env/{key}": 0.0 for key in MOD.PER_GAME_METRICS}
        logs.update({"env/n": 1, "env/perf": 0.5})
        del logs["env/error_episodes"]
        with self.assertRaisesRegex(RuntimeError, "missing required fields"):
            MOD.game_from_cumulative(
                logs=logs, previous=previous, bot_team=1, style="contact",
                base_seed=42, checkpoint_sha256="a" * 64,
                runtime_identity_sha256="b" * 64, max_decisions=4096)

    def test_uint64_rng_seed_wrap(self):
        previous = {"n": 0.0, **{key: 0.0 for key in MOD.PER_GAME_METRICS}}
        logs = {f"env/{key}": 0.0 for key in MOD.PER_GAME_METRICS}
        logs.update({"env/n": 1, "env/perf": 0.5})
        row = MOD.game_from_cumulative(
            logs=logs, previous=previous, bot_team=1, style="contact",
            base_seed=MOD.UINT64_MASK, checkpoint_sha256="a" * 64,
            runtime_identity_sha256="b" * 64, max_decisions=4096)
        self.assertEqual(row["game_rng_seed"], 7918)

    def test_summary(self):
        rows = [
            {"result": "win", "match_points": 1.0, "td_diff": 2},
            {"result": "draw", "match_points": 0.5, "td_diff": 0},
            {"result": "loss", "match_points": 0.0, "td_diff": -1},
        ]
        got = MOD.summarize(rows)
        self.assertEqual(got["games"], 3)
        self.assertAlmostEqual(got["match_score"], 0.5)
        self.assertAlmostEqual(got["mean_td_diff"], 1 / 3)

    def test_runtime_bridge_reason_is_explicit(self):
        parsed = MOD.parse_args([
            "--checkpoint", "p.bin", "--output", "out",
            "--games-per-cell", "1", "--seed", "42",
            "--source-snapshot-root", "/snapshot",
            "--source-closure-sha256", "a" * 64,
            "--runtime-root", "/frozen/runtime",
            "--runtime-bridge-reason", "bridge eval after terminal repair",
        ])
        self.assertEqual(parsed.runtime_root, Path("/frozen/runtime"))
        self.assertEqual(parsed.runtime_bridge_reason,
                         "bridge eval after terminal repair")

    def test_inference_memory_contract_is_exact_and_legacy_is_explicit(self):
        current = 'terminal-aware-tbptt-v1'
        old = 'tail-bootstrap-v1'
        MOD.validate_memory_contract(current, current, None)
        MOD.validate_memory_contract(old, old, 'frozen common-seed evaluation bridge')
        for actual, expected, reason in (
            (old, current, 'bridge'), (current, old, 'bridge'),
            (old, old, None), (old, old, '  '), ('unknown', 'unknown', 'bridge'),
        ):
            with self.subTest(actual=actual, expected=expected, reason=reason):
                with self.assertRaises(RuntimeError):
                    MOD.validate_memory_contract(actual, expected, reason)

    def test_external_evaluator_helpers_are_pinned_outside_runtime(self):
        paths = MOD.external_helper_paths(Path(MOD.__file__))
        self.assertEqual(paths["checkpoint_lineage"],
                         Path(MOD.__file__).resolve().parent / "checkpoint_lineage.py")
        self.assertEqual(set(paths), {"checkpoint_lineage"})
        source = Path(MOD.__file__).read_text()
        self.assertIn("evaluation helper import escaped the external pinned package", source)
        self.assertIn('["/usr/bin/bash", str(root / "tools/install_puffer_env.sh")', source)

    def test_config_clears_inherited_script_selectors_and_selfplay(self):
        args = {
            "train": {}, "vec": {}, "selfplay": {"enabled": 1},
            "env": {"scripted_bank_tag": 7, "scripted_bank_mask": 129},
        }
        got = MOD.configure_args(
            args, learner_side="home", style="contact", seed=42,
            max_decisions=4096)
        self.assertEqual(got["selfplay"]["enabled"], 0)
        self.assertEqual(got["env"]["scripted_bank_tag"], 0)
        self.assertEqual(got["env"]["scripted_bank_mask"], 0)


if __name__ == "__main__":
    unittest.main()
