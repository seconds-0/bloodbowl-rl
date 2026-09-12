#!/usr/bin/env python3
"""Unit and watched-integration tests for entropy schedule verification."""

from __future__ import annotations

from copy import deepcopy
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest


TRAINING_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = TRAINING_DIR.parent
if str(TRAINING_DIR) not in sys.path:
    sys.path.insert(0, str(TRAINING_DIR))

import verify_entropy_schedule_parity as verifier  # noqa: E402


def _schedule(*, total_updates: int = 4) -> dict[str, object]:
    return {
        "contract": verifier.CONTRACT,
        "base_coefficient": 0.1,
        "anneal_enabled": True,
        "min_coefficient_ratio": 0.25,
        "total_updates": total_updates,
    }


def _training(*, total_updates: int = 4) -> dict[str, object]:
    batch_size = 16
    return {
        "total_timesteps": total_updates * batch_size,
        "total_agents": 4,
        "horizon": 4,
        "batch_size": batch_size,
        "replay_ratio": "1/2",
        "minibatch_size": 4,
        "total_updates": total_updates,
        "minibatches_per_update": 2,
    }


def _identity() -> dict[str, str]:
    return {
        "puffer_git_commit": "a" * 40,
        "torch_source_sha256": "b" * 64,
        "native_source_sha256": "c" * 64,
        "patch_sha256": "d" * 64,
    }


def _trace(
    backend: str,
    schedule: dict[str, object],
    training: dict[str, object],
    identity: dict[str, str],
) -> dict[str, object]:
    minibatches = int(training["minibatches_per_update"])
    updates = []
    for index in range(int(schedule["total_updates"])):
        point = verifier.entropy_schedule_point(schedule, index)
        entropy = 1.25 + 0.125 * index
        if backend == "native_graph":
            graph_delta, eager_delta = minibatches, 0
        elif backend == "native_eager":
            graph_delta, eager_delta = 0, minibatches
        else:
            graph_delta, eager_delta = 0, 0
        updates.append(
            {
                "update_index": index,
                "progress": point["progress"],
                "c_real": point["c_real"],
                "c_applied": point["c_applied"],
                "entropy": entropy,
                "entropy_term": -point["c_applied"] * entropy,
                "minibatch_count": minibatches,
                "graph_train_count_delta": graph_delta,
                "eager_train_count_delta": eager_delta,
            }
        )
    return {
        "schema_version": verifier.SCHEMA_VERSION,
        "backend": backend,
        "contract": verifier.CONTRACT,
        "schedule_sha256": verifier.canonical_sha256(schedule),
        "identity": dict(identity),
        "total_updates": schedule["total_updates"],
        "minibatches_per_update": minibatches,
        "updates": updates,
    }


def _valid_artifact() -> dict[str, object]:
    schedule = _schedule()
    training = _training()
    identity = _identity()
    payload = {
        "contract": verifier.CONTRACT,
        "schedule": schedule,
        "training": training,
        "identity": identity,
        "cells": {
            backend: _trace(backend, schedule, training, identity)
            for backend in verifier.BACKENDS
        },
    }
    return verifier.seal_cell_matrix(payload)


def _reseal(artifact: dict[str, object]) -> dict[str, object]:
    return verifier.seal_cell_matrix(artifact["payload"])


class EntropyScheduleOracleTests(unittest.TestCase):
    def test_contract_name_and_binary64_to_binary32_boundary(self) -> None:
        self.assertEqual(
            verifier.CONTRACT,
            "cosine-update-index-over-total-updates-fp32-v1",
        )
        point = verifier.entropy_schedule_point(_schedule(), 0)
        packed = struct.unpack("!f", struct.pack("!f", 0.1))[0]
        self.assertEqual(point["c_real"], 0.1)
        self.assertEqual(point["c_applied"], packed)
        self.assertNotEqual(point["c_real"], point["c_applied"])

    def test_cosine_uses_update_index_over_total_updates(self) -> None:
        schedule = _schedule()
        before_start = verifier.entropy_schedule_point(schedule, -1)
        start = verifier.entropy_schedule_point(schedule, 0)
        midpoint = verifier.entropy_schedule_point(schedule, 2)
        last_legal = verifier.entropy_schedule_point(schedule, 3)
        post_final = verifier.entropy_schedule_point(schedule, 4)
        beyond_final = verifier.entropy_schedule_point(schedule, 40)
        self.assertEqual(before_start["progress"], 0.0)
        self.assertAlmostEqual(before_start["c_real"], 0.1)
        self.assertEqual(start["progress"], 0.0)
        self.assertAlmostEqual(start["c_real"], 0.1)
        self.assertEqual(midpoint["progress"], 0.5)
        self.assertAlmostEqual(midpoint["c_real"], 0.0625)
        self.assertEqual(last_legal["progress"], 0.75)
        self.assertGreater(last_legal["c_real"], 0.025)
        self.assertEqual(post_final["progress"], 1.0)
        self.assertAlmostEqual(post_final["c_real"], 0.025)
        self.assertEqual(beyond_final["progress"], 1.0)
        self.assertAlmostEqual(beyond_final["c_real"], 0.025)

    def test_single_update_starts_at_base_and_post_final_reaches_floor(self) -> None:
        schedule = _schedule(total_updates=1)
        only_update = verifier.entropy_schedule_point(schedule, 0)
        post_final = verifier.entropy_schedule_point(schedule, 1)
        self.assertEqual(only_update["progress"], 0.0)
        self.assertAlmostEqual(only_update["c_real"], 0.1)
        self.assertEqual(post_final["progress"], 1.0)
        self.assertAlmostEqual(post_final["c_real"], 0.025)

    def test_disabled_schedule_is_constant(self) -> None:
        schedule = _schedule()
        schedule["anneal_enabled"] = False
        for index in (0, 1, 3, 4, 100):
            with self.subTest(index=index):
                point = verifier.entropy_schedule_point(schedule, index)
                self.assertEqual(point["c_real"], 0.1)
                self.assertEqual(
                    point["c_applied"],
                    struct.unpack("!f", struct.pack("!f", 0.1))[0],
                )

    def test_zero_base_coefficient_is_valid(self) -> None:
        schedule = _schedule()
        schedule["base_coefficient"] = 0.0
        point = verifier.entropy_schedule_point(schedule, 2)
        self.assertEqual(point["c_real"], 0.0)
        self.assertEqual(point["c_applied"], 0.0)

    def test_total_update_and_minibatch_helpers_use_floor_semantics(self) -> None:
        self.assertEqual(verifier.total_updates(65, 4, 4), 4)
        self.assertEqual(verifier.minibatches_per_update("1/3", 100, 8), 4)
        self.assertEqual(verifier.minibatches_per_update("0.25", 64, 8), 2)
        self.assertEqual(verifier.minibatches_per_update("0.1", 10, 1), 1)
        with self.assertRaisesRegex(
            verifier.VerificationError, "zero minibatches"
        ):
            verifier.minibatches_per_update(
                "0.09999999403953552", 10, 1
            )

    def test_minibatch_helper_matches_runtime_binary64_operation_order(
        self,
    ) -> None:
        ratio = struct.unpack("!f", bytes.fromhex("3f47ea21"))[0]
        batch_size = 1_386_466_366
        minibatch_size = 1_082_714_148
        runtime_value = (
            float(ratio)
            * float(batch_size)
            / float(minibatch_size)
        )
        self.assertEqual(runtime_value, 1.0)
        self.assertEqual(
            verifier.minibatches_per_update(
                repr(ratio),
                batch_size,
                minibatch_size,
            ),
            1,
        )

    def test_helpers_reject_zero_loop_counts_and_boolean_counts(self) -> None:
        with self.assertRaisesRegex(verifier.VerificationError, "zero complete"):
            verifier.total_updates(15, 4, 4)
        with self.assertRaisesRegex(verifier.VerificationError, "zero minibatches"):
            verifier.minibatches_per_update("0.1", 32, 64)
        with self.assertRaises(verifier.VerificationError):
            verifier.total_updates(True, 4, 4)
        with self.assertRaises(verifier.VerificationError):
            verifier.minibatches_per_update(True, 32, 4)

    def test_raw_schedule_schema_and_domain_are_strict(self) -> None:
        mutations = []

        extra = _schedule()
        extra["surprise"] = 1
        mutations.append(extra)

        wrong_contract = _schedule()
        wrong_contract["contract"] = "cosine"
        mutations.append(wrong_contract)

        bool_base = _schedule()
        bool_base["base_coefficient"] = True
        mutations.append(bool_base)

        negative_base = _schedule()
        negative_base["base_coefficient"] = -0.1
        mutations.append(negative_base)

        nan_base = _schedule()
        nan_base["base_coefficient"] = math.nan
        mutations.append(nan_base)

        bad_bool = _schedule()
        bad_bool["anneal_enabled"] = 1
        mutations.append(bad_bool)

        bad_ratio = _schedule()
        bad_ratio["min_coefficient_ratio"] = 1.01
        mutations.append(bad_ratio)

        zero_updates = _schedule()
        zero_updates["total_updates"] = 0
        mutations.append(zero_updates)

        for mutation in mutations:
            with self.subTest(mutation=mutation):
                with self.assertRaises(verifier.VerificationError):
                    verifier.validate_raw_schedule(mutation)

    def test_raw_training_recomputes_declared_counts(self) -> None:
        training = _training()
        self.assertEqual(
            verifier.validate_raw_training(training)["total_updates"], 4
        )
        wrong_updates = dict(training)
        wrong_updates["total_updates"] = 3
        with self.assertRaisesRegex(
            verifier.VerificationError, "total_updates=3"
        ):
            verifier.validate_raw_training(wrong_updates)
        wrong_minibatches = dict(training)
        wrong_minibatches["minibatches_per_update"] = 3
        with self.assertRaisesRegex(
            verifier.VerificationError, "minibatches_per_update=3"
        ):
            verifier.validate_raw_training(wrong_minibatches)
        float_ratio = dict(training)
        float_ratio["replay_ratio"] = 0.5
        with self.assertRaisesRegex(
            verifier.VerificationError, "exact rational string"
        ):
            verifier.validate_raw_training(float_ratio)


class EntropyCellArtifactTests(unittest.TestCase):
    def assert_resealed_mutation_rejected(
        self, mutate, expected_message: str | None = None
    ) -> None:
        artifact = deepcopy(_valid_artifact())
        mutate(artifact["payload"])
        artifact = _reseal(artifact)
        context = self.assertRaises(verifier.VerificationError)
        with context:
            verifier.validate_cell_matrix(artifact)
        if expected_message is not None:
            self.assertIn(expected_message, str(context.exception))

    def test_valid_closed_three_cell_matrix(self) -> None:
        summary = verifier.validate_cell_matrix(_valid_artifact())
        self.assertEqual(summary["contract"], verifier.CONTRACT)
        self.assertEqual(summary["total_updates"], 4)
        self.assertEqual(summary["minibatches_per_update"], 2)
        self.assertEqual(summary["validated_cells"], list(verifier.BACKENDS))

    def test_digest_rejects_unresealed_tampering(self) -> None:
        artifact = _valid_artifact()
        artifact["payload"]["cells"]["torch"]["updates"][0]["entropy"] = 99.0
        with self.assertRaisesRegex(
            verifier.VerificationError, "digest mismatch"
        ):
            verifier.validate_cell_matrix(artifact)

    def test_closed_parent_rejects_extra_field(self) -> None:
        def mutate(payload):
            payload["unreviewed_metadata"] = "not allowed"

        self.assert_resealed_mutation_rejected(mutate, "non-closed schema")

    def test_matrix_rejects_missing_cell(self) -> None:
        def mutate(payload):
            del payload["cells"]["native_graph"]

        self.assert_resealed_mutation_rejected(mutate, "missing")

    def test_frozen_schedule_is_rejected(self) -> None:
        def mutate(payload):
            row0 = payload["cells"]["torch"]["updates"][0]
            row1 = payload["cells"]["torch"]["updates"][1]
            row1["c_real"] = row0["c_real"]
            row1["c_applied"] = row0["c_applied"]
            row1["entropy_term"] = -row1["c_applied"] * row1["entropy"]

        self.assert_resealed_mutation_rejected(mutate, "binary64 oracle")

    def test_shifted_update_indices_are_rejected(self) -> None:
        def mutate(payload):
            payload["cells"]["torch"]["updates"][1]["update_index"] = 2

        self.assert_resealed_mutation_rejected(
            mutate, "contiguous zero-based index"
        )

    def test_n_minus_one_denominator_mutation_is_rejected(self) -> None:
        def mutate(payload):
            schedule = payload["schedule"]
            index = schedule["total_updates"] - 1
            base = schedule["base_coefficient"]
            floor = base * schedule["min_coefficient_ratio"]
            wrong_progress = index / (schedule["total_updates"] - 1)
            wrong_real = floor + 0.5 * (base - floor) * (
                1.0 + math.cos(math.pi * wrong_progress)
            )
            wrong_applied = struct.unpack(
                "!f", struct.pack("!f", wrong_real)
            )[0]
            row = payload["cells"]["torch"]["updates"][index]
            row["progress"] = wrong_progress
            row["c_real"] = wrong_real
            row["c_applied"] = wrong_applied
            row["entropy_term"] = -wrong_applied * row["entropy"]

        self.assert_resealed_mutation_rejected(
            mutate, "update_index/total_updates"
        )

    def test_wrong_entropy_loss_sign_is_rejected(self) -> None:
        def mutate(payload):
            row = payload["cells"]["torch"]["updates"][2]
            row["entropy_term"] = abs(row["entropy_term"])

        self.assert_resealed_mutation_rejected(
            mutate, "-c_applied * entropy"
        )

    def test_zero_entropy_witness_is_rejected(self) -> None:
        def mutate(payload):
            row = payload["cells"]["torch"]["updates"][2]
            row["entropy"] = 0.0
            row["entropy_term"] = 0.0

        self.assert_resealed_mutation_rejected(
            mutate, "strictly positive"
        )

    def test_minibatch_row_count_is_rejected(self) -> None:
        def mutate(payload):
            payload["cells"]["torch"]["updates"][0][
                "minibatch_count"
            ] = 3

        self.assert_resealed_mutation_rejected(
            mutate, "minibatch_count mismatches"
        )

    def test_graph_and_eager_counter_mutations_are_rejected(self) -> None:
        def mutate_graph(payload):
            payload["cells"]["native_graph"]["updates"][0][
                "graph_train_count_delta"
            ] = 0

        def mutate_eager(payload):
            payload["cells"]["native_eager"]["updates"][0][
                "eager_train_count_delta"
            ] = 0

        self.assert_resealed_mutation_rejected(
            mutate_graph, "execution counters"
        )
        self.assert_resealed_mutation_rejected(
            mutate_eager, "execution counters"
        )

    def test_cell_identity_mutation_is_rejected(self) -> None:
        def mutate(payload):
            payload["cells"]["native_graph"]["identity"][
                "patch_sha256"
            ] = "e" * 64

        self.assert_resealed_mutation_rejected(
            mutate, "identity does not match"
        )

    def test_schedule_digest_inside_trace_rejects_rebound_parent(self) -> None:
        def mutate(payload):
            payload["schedule"]["base_coefficient"] = 0.2

        self.assert_resealed_mutation_rejected(
            mutate, "wrong schedule_sha256"
        )


class TorchSourceProbeUnitTests(unittest.TestCase):
    def test_missing_helper_and_telemetry_fail_cleanly_before_import(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "pufferlib"
            package.mkdir()
            (package / "torch_pufferl.py").write_text(
                "raise RuntimeError('must not import old source')\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                verifier.VerificationError,
                "lacks entropy parity integration",
            ):
                verifier.execute_torch_source_schedule(
                    root, _schedule(), [0, 3, 4]
                )


class WatchedPufferSourceIntegrationTests(unittest.TestCase):
    """Red until the exact Puffer source/patch carries the new contract."""

    def test_watched_puffer_source_or_patch_contract(self) -> None:
        selected_root = os.environ.get("PUFFER_ENTROPY_TEST_ROOT")
        if selected_root:
            schedule = _schedule()
            verifier.validate_torch_source_contract(selected_root)
            points = verifier.execute_torch_source_schedule(
                selected_root, schedule, [0, 1, 3, 4]
            )
            self.assertEqual(
                [point["update_index"] for point in points],
                [0, 1, 3, 4],
            )
            return

        patch = TRAINING_DIR / "puffer_entropy_schedule_parity.patch"
        self.assertTrue(
            patch.is_file(),
            "watched integration is intentionally red: create "
            "training/puffer_entropy_schedule_parity.patch, or set "
            "PUFFER_ENTROPY_TEST_ROOT to the exact patched Puffer source tree",
        )
        added_lines = []
        for line in patch.read_text(encoding="utf-8").splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                added_lines.append(line[1:])
        additions = "\n".join(added_lines)
        required_markers = (
            verifier.CONTRACT,
            "ENTROPY_SCHEDULE_CONTRACT",
            "def entropy_schedule_point(",
            "entropy_schedule_contract",
            "entropy_applied_update_index",
            "entropy_c_real",
            "entropy_c_applied",
            "entropy_term",
        )
        for marker in required_markers:
            with self.subTest(marker=marker):
                self.assertIn(
                    marker,
                    additions,
                    f"watched Puffer patch lacks required marker {marker!r}",
                )


if __name__ == "__main__":
    unittest.main()

