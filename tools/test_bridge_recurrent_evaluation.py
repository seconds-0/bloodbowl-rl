import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bridge_recurrent_evaluation as bridge


class BridgeRecurrentEvaluationTests(unittest.TestCase):
    def plan(self, root: Path):
        checkpoint = root / "weights.bin"
        checkpoint.write_bytes(b"frozen")
        python = root / "venv/bin/python"
        return {
            "schema_version": 1, "checkpoint": str(checkpoint),
            "checkpoint_sha256": hashlib.sha256(b"frozen").hexdigest(),
            "cudart": str(root / "venv/lib/libcudart.so.12"),
            "arms": {
                "old": {"runtime_root": str(root / "old"), "python": str(python),
                        "expected_module_sha256": "a" * 64,
                        "expected_contract": "tail-bootstrap-v1"},
                "new": {"runtime_root": str(root / "new"), "python": str(python),
                        "expected_module_sha256": "b" * 64,
                        "expected_contract": "terminal-aware-tbptt-v1"}},
            "styles": ["contact", "cage"], "sides": ["home", "away"],
            "seeds": [7, 11], "games_per_seed": 2, "horizon": 1,
            "demo_reset_pct": 0, "gpu_id": 0, "max_decisions": 4096,
            "policy": {"hidden_size": 512, "num_layers": 3},
            "environment_sha256": bridge.EXPECTED_ENVIRONMENT_SHA256,
            "max_rollouts_per_cell": 8192, "max_trace_bytes": 32 * 1024 * 1024,
            "atol": 1e-6, "rtol": 1e-6, "qualification_only": True,
            "lineage_promotion": False,
        }

    def row(self, value=0.25):
        arrays = {
            "observations": np.arange(8, dtype=np.uint8).reshape(2, 4),
            "action_mask": np.ones((2, 8), dtype=np.uint8),
            "actions": np.asarray([[1, 32, 390], [2, 3, 4]], dtype=np.float32),
            "rewards": np.asarray([0, 1], dtype=np.float32),
            "terminals": np.asarray([0, 1], dtype=np.float32),
            "logprobs": np.asarray([value, -value], dtype=np.float32),
            "values": np.asarray([1 + value, 2 + value], dtype=np.float32),
        }
        return bridge.snapshot_record(arrays, step=0,
            cell={"style": "contact", "side": "home", "seed": 7})

    def test_plan_pins_contracts_matrix_and_lexical_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self.plan(Path(tmp))
            bridge.validate_plan(plan)
            path = Path(tmp) / "plan.json"
            path.write_text(json.dumps(plan))
            command = bridge.worker_command(Path("/driver.py"), path, Path("/out"), "old")
            self.assertEqual(command[0], plan["arms"]["old"]["python"])
            self.assertEqual(bridge.worker_environment(plan, "old")["PYTHONPATH"],
                f"{tmp}/old/vendor/PufferLib:{tmp}/old/tools")
            plan["arms"]["old"]["expected_contract"] = "terminal-aware-tbptt-v1"
            with self.assertRaisesRegex(bridge.BridgeFailure, "old arm contract"):
                bridge.validate_plan(plan)

    def test_snapshot_requires_actual_six_field_surface(self):
        arrays = {"observations": np.zeros((2, 4), dtype=np.uint8)}
        with self.assertRaisesRegex(bridge.BridgeFailure, "lacks"):
            bridge.snapshot_record(arrays, step=0, cell={})
        row = self.row()
        self.assertNotIn("values", row["fields"]["observations"])
        self.assertNotIn("values", row["fields"]["action_mask"])
        self.assertEqual(row["fields"]["actions"]["values"], [1.0, 32.0, 390.0, 2.0, 3.0, 4.0])

    def test_actual_native_tensor_record_schema_decodes(self):
        arrays = {
            "observations": np.arange(8, dtype=np.float32).reshape(2, 4),
            "action_mask": np.ones((2, 8), dtype=np.float32),
            "actions": np.asarray([[1, 32, 390], [2, 3, 4]], dtype=np.float32),
            "rewards": np.asarray([0, 1], dtype=np.float32),
            "terminals": np.asarray([0, 1], dtype=np.float32),
            "logprobs": np.asarray([0.25, -0.25], dtype=np.float32),
            "values": np.asarray([1.25, 2.25], dtype=np.float32),
        }
        raw = {"num_banks": 1, "num_buffers": 1, "decoder_outputs": [],
               "tensors": {key: {"dtype": "f32", "shape": list(value.shape),
                                   "data": value.astype("<f4").tobytes()}
                           for key, value in arrays.items()}}
        decoded = bridge._decode_snapshot(raw)
        for key, expected in arrays.items():
            np.testing.assert_array_equal(decoded[key], expected)
        raw["tensors"]["values"]["data"] = b"short"
        with self.assertRaisesRegex(bridge.BridgeFailure, "byte count"):
            bridge._decode_snapshot(raw)

    def test_eval_log_game_count_is_exact_cumulative_zero_or_one(self):
        self.assertEqual(bridge.completed_games({}, 0), 0)
        self.assertEqual(
            bridge.completed_games({"eval_episodes_completed": 0.0}, 0), 0)
        self.assertEqual(bridge.completed_games({"env/n": 0.0}, 0), 0)
        self.assertEqual(bridge.completed_games({"env/n": 1.0}, 0), 1)
        with self.assertRaisesRegex(bridge.BridgeFailure, "cumulative"):
            bridge.completed_games({"env/n": 2.0}, 0)
        with self.assertRaisesRegex(bridge.BridgeFailure, "exact integer"):
            bridge.completed_games({"env/n": 1.5}, 1)
        with self.assertRaisesRegex(bridge.BridgeFailure, "actual keys"):
            bridge.completed_games({"env/score_diff": 0.0}, 0)
        with self.assertRaisesRegex(bridge.BridgeFailure, "exact integer"):
            bridge.completed_games({}, 1)

    def test_stepwise_comparison_is_exact_for_discrete_and_tolerant_for_numeric(self):
        old = self.row()
        new = self.row(value=0.2500004)
        result = bridge.compare_traces([old], [new], atol=1e-6, rtol=0)
        self.assertEqual(result["paired_steps"], 1)
        self.assertGreater(result["max_abs_error"]["logprobs"], 0)
        new = self.row()
        new["fields"]["actions"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(bridge.BridgeFailure, "exact field actions"):
            bridge.compare_traces([old], [new], atol=1e-6, rtol=0)

    def test_numeric_drift_and_trace_alignment_fail_closed(self):
        old = self.row()
        new = self.row(value=0.251)
        with self.assertRaisesRegex(bridge.BridgeFailure, "numeric field logprobs"):
            bridge.compare_traces([old], [new], atol=1e-6, rtol=0)
        new = self.row()
        new["cell"]["seed"] = 8
        with self.assertRaisesRegex(bridge.BridgeFailure, "alignment"):
            bridge.compare_traces([old], [new], atol=1e-6, rtol=0)

    def test_source_contains_no_training_call_and_all_hard_fields_are_shared(self):
        source = Path(bridge.__file__).read_text()
        self.assertNotIn("backend.train(", source)
        self.assertNotIn("_C.train(", source)
        self.assertEqual(len(bridge.HARD_INTEGRITY_KEYS), 16)
        self.assertIn("actual_qualification_snapshot_calls", source)
        self.assertIn("qualification_snapshot(runner)", source)

    def test_loaded_and_post_eval_serializations_must_match_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before, after = root / "before.bin", root / "after.bin"
            before.write_bytes(b"frozen")
            after.write_bytes(b"frozen")
            expected = hashlib.sha256(b"frozen").hexdigest()
            self.assertEqual(
                bridge.validate_serialized_weights(before, after, expected), expected)
            before.write_bytes(b"silently-unloaded")
            with self.assertRaisesRegex(bridge.BridgeFailure, "pinned checkpoint"):
                bridge.validate_serialized_weights(before, after, expected)
            before.write_bytes(b"frozen")
            after.write_bytes(b"mutated")
            with self.assertRaisesRegex(bridge.BridgeFailure, "inference changed"):
                bridge.validate_serialized_weights(before, after, expected)

    def test_effective_config_forces_empty_nccl_and_hashes_canonically(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self.plan(Path(tmp))
            base = {"nccl_id": b"stale", "train": {}, "policy": {}, "vec": {},
                    "selfplay": {}, "env": {}}
            cell = {"style": "contact", "side": "home", "seed": 7}
            configured = bridge._cell_config(base, cell, plan)
            self.assertEqual(configured["nccl_id"], b"")
            self.assertEqual(configured["train"]["horizon"], 1)
            self.assertEqual(configured["policy"], {"hidden_size": 512, "num_layers": 3})
            self.assertEqual(
                bridge.canonical_sha256(configured),
                bridge.canonical_sha256(bridge.json_safe(configured)))


if __name__ == "__main__":
    unittest.main()
