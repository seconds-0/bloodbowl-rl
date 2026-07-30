#!/usr/bin/env python3
"""Tests for the executable CPU Torch entropy-objective verifier."""

from __future__ import annotations

import builtins
import json
import hashlib
import importlib.util
import inspect
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from unittest import mock
import warnings


TRAINING_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = TRAINING_DIR.parent
if str(TRAINING_DIR) not in sys.path:
    sys.path.insert(0, str(TRAINING_DIR))

import verify_torch_entropy_objective as verifier  # noqa: E402


def _puffer_module_state() -> dict[str, types.ModuleType]:
    return {
        name: module
        for name, module in sys.modules.items()
        if name == "pufferlib" or name.startswith("pufferlib.")
    }


def _replace_puffer_module_state(
    modules: dict[str, types.ModuleType],
) -> None:
    for name in tuple(sys.modules):
        if name == "pufferlib" or name.startswith("pufferlib."):
            sys.modules.pop(name, None)
    sys.modules.update(modules)


def _process_import_state() -> tuple[object, object, object, list[object]]:
    return (
        signal.getsignal(signal.SIGINT),
        sys.excepthook,
        warnings.filters,
        list(warnings.filters),
    )


def _restore_process_import_state(
    state: tuple[object, object, object, list[object]],
) -> None:
    sigint_handler, excepthook, filter_object, filter_contents = state
    sys.excepthook = excepthook
    warnings.filters = filter_object
    warnings.filters[:] = filter_contents
    if signal.getsignal(signal.SIGINT) != sigint_handler:
        signal.signal(signal.SIGINT, sigint_handler)


def _write_source_fixture(
    root: Path,
    *,
    train_order: tuple[str, str, str],
    train_decoy: tuple[str, str, str] | None = None,
    pre_overrun: tuple[str, ...] = (),
    pre_minibatch: tuple[str, ...] = (),
    minibatch_prefix: tuple[str, ...] = (),
    objective_in_loop_else: bool = False,
) -> None:
    (root / "pufferlib").mkdir()
    (root / "src").mkdir()
    ordered_calls = "\n".join(
        textwrap.indent(call, "            ") for call in train_order
    )
    minibatch_prefix_source = "\n".join(
        textwrap.indent(statement, "            ")
        for statement in minibatch_prefix
    )
    if minibatch_prefix_source:
        minibatch_prefix_source += "\n"
    if objective_in_loop_else:
        minibatch_block = (
            "        num_minibatches = self.num_minibatches\n"
            "        for mb in range(num_minibatches):\n"
            "            pass\n"
            "        else:\n"
            f"{ordered_calls}"
        )
    else:
        minibatch_block = (
            "        num_minibatches = self.num_minibatches\n"
            "        for mb in range(num_minibatches):\n"
            f"{minibatch_prefix_source}"
            f"{ordered_calls}"
        )
    decoy = ""
    if train_decoy is not None:
        decoy_lines = "\n".join(train_decoy)
        decoy = f'        """Source-order decoy only:\n{decoy_lines}\n        """\n'
    pre_overrun_source = "".join(
        f"{textwrap.indent(statement, '        ')}\n"
        for statement in pre_overrun
    )
    pre_minibatch_source = "".join(
        f"{textwrap.indent(statement, '        ')}\n"
        for statement in pre_minibatch
    )
    torch_source = f"""
ENTROPY_SCHEDULE_CONTRACT = "{verifier.CONTRACT}"

def entropy_schedule_point():
    return None

def apply_action_mask():
    return None

def sample_joint_logits():
    return None

def sample_logits():
    return None

class PuffeRL:
    def __init__(self):
        self._training_failed = False

    @property
    def uptime(self):
        if self._training_failed:
            raise RuntimeError(
                '{verifier.EXPECTED_FAILED_UPDATE_ERROR}')
        return 0.0

    @property
    def sps(self):
        if self._training_failed:
            raise RuntimeError(
                '{verifier.EXPECTED_FAILED_UPDATE_ERROR}')
        return 0.0

    def num_params(self):
        if self._training_failed:
            raise RuntimeError(
                '{verifier.EXPECTED_FAILED_UPDATE_ERROR}')
        return 0

    def enable_entropy_gradient_qualification(self):
        if self._training_failed:
            raise RuntimeError(
                '{verifier.EXPECTED_FAILED_UPDATE_ERROR}')
        return None

    def rollouts(self):
        return None

    def train(self):
        if self._training_failed:
            raise RuntimeError(
                '{verifier.EXPECTED_FAILED_UPDATE_ERROR}')
        if not self.reset_state or self.evaluation_mode:
            raise RuntimeError(
                'training requires reset_state=True and evaluation_mode=False')
        prof = self.profile
        losses = defaultdict(float)
{pre_overrun_source}
        if self.epoch < 0 or self.epoch >= self.total_epochs:
            raise RuntimeError(
                'training update exceeds configured total_updates')
        if not self.tail_valid:
            raise RuntimeError(
                'training requires one fresh tail record')
        self._training_failed = True
        current_ent_coef = torch.tensor(
            0.0
        )
        entropy_term = -current_ent_coef * entropy_loss
        loss = pg_loss + config['vf_coef']*v_loss + entropy_term
        losses['entropy_coefficient'] += current_ent_coef
        losses['entropy_term'] += entropy_term
        losses['total_loss'] += loss
{decoy}
{pre_minibatch_source}
{minibatch_block}
        self._train_log_interval = None
        self._training_failed = False

    def _prepare_train_log(self):
        return None

    def _format_train_log(self):
        return None

    def _log(self):
        if self._training_failed:
            raise RuntimeError(
                '{verifier.EXPECTED_FAILED_UPDATE_ERROR}')
        return None

    def log(self):
        if self._training_failed:
            raise RuntimeError(
                '{verifier.EXPECTED_FAILED_UPDATE_ERROR}')
        return self._log()

    def eval_log(self):
        if self._training_failed:
            raise RuntimeError(
                '{verifier.EXPECTED_FAILED_UPDATE_ERROR}')
        return self._log()

    def set_evaluation_mode(self, enabled):
        enabled = bool(enabled)
        return None

    def qualification_entropy_gradient_state(self):
        if self._training_failed:
            raise RuntimeError(
                '{verifier.EXPECTED_FAILED_UPDATE_ERROR}')
        return None

    def save_weights(self, path):
        if self._training_failed:
            raise RuntimeError(
                '{verifier.EXPECTED_FAILED_UPDATE_ERROR}')
        return None

    def load_weights(self, path):
        if self._training_failed:
            raise RuntimeError(
                '{verifier.EXPECTED_FAILED_UPDATE_ERROR}')
        return None

    def render(self, env_id=0):
        if self._training_failed:
            raise RuntimeError(
                '{verifier.EXPECTED_FAILED_UPDATE_ERROR}')
        return None

    def close(self):
        return None

def _copy_public_callable_metadata(guarded, method):
    guarded.__name__ = method.__name__
    guarded.__qualname__ = method.__qualname__
    guarded.__doc__ = method.__doc__
    guarded.__module__ = method.__module__
    guarded.__annotations__ = dict(getattr(method, '__annotations__', {{}}))
    return guarded

def _reject_incomplete_update_set_evaluation_mode(method):
    def guarded(self, enabled):
        if self._training_failed:
            raise RuntimeError(
                '{verifier.EXPECTED_FAILED_UPDATE_ERROR}')
        return method(self, enabled)
    return _copy_public_callable_metadata(guarded, method)

def _reject_incomplete_update_rollouts(method):
    def guarded(self):
        if self._training_failed:
            raise RuntimeError(
                '{verifier.EXPECTED_FAILED_UPDATE_ERROR}')
        return method(self)
    return _copy_public_callable_metadata(guarded, method)

PuffeRL.set_evaluation_mode = (
    _reject_incomplete_update_set_evaluation_mode(
        PuffeRL.set_evaluation_mode
    )
)
PuffeRL.rollouts = _reject_incomplete_update_rollouts(PuffeRL.rollouts)
"""
    (root / "pufferlib" / "torch_pufferl.py").write_text(torch_source, encoding="utf-8")
    (root / "pufferlib" / "pufferl.py").write_text(
        "def validate_entropy_schedule_config(args):\n" "    return args\n",
        encoding="utf-8",
    )
    marker = 'm.attr("entropy_schedule_contract") = ' f'"{verifier.CONTRACT}";\n'
    (root / "src" / "bindings_cpu.cpp").write_text(marker, encoding="utf-8")
    (root / "src" / "bindings.cu").write_text(marker, encoding="utf-8")


def _synthetic_run(
    case: str,
    update_index: int,
    base_coefficient: float,
    anneal_enabled: bool,
) -> dict[str, object]:
    point = verifier.oracle_schedule_point(
        base_coefficient=base_coefficient,
        anneal_enabled=anneal_enabled,
        min_coefficient_ratio=verifier.MIN_COEFFICIENT_RATIO,
        update_index=update_index,
        total_updates=verifier.TOTAL_UPDATES,
    )
    coefficient = float(point["c_applied"])
    probability = 1.0 / (1.0 + math.exp(-verifier.THETA))
    entropy_derivative = -verifier.THETA * probability * (1.0 - probability)
    gradient = -coefficient * entropy_derivative
    entropy = verifier.oracle_binary_entropy()
    entropy_term = -coefficient * entropy
    policy_loss = 0.125
    value_loss = 0.5
    return {
        "case": case,
        "update_index": update_index,
        "anneal_enabled": anneal_enabled,
        "base_coefficient": base_coefficient,
        "applied_coefficient": coefficient,
        "entropy_hook_coefficients": [
            coefficient,
            coefficient,
        ],
        "preclip_gradients": [gradient, gradient],
        "optimizer_gradients": [gradient, gradient],
        "operation_order": [
            "backward",
            "clip",
            "step",
            "backward",
            "clip",
            "step",
        ],
        "policy_loss": policy_loss,
        "value_loss": value_loss,
        "entropy": entropy,
        "entropy_term": entropy_term,
        "total_loss": (
            policy_loss + verifier.VF_COEFFICIENT * value_loss + entropy_term
        ),
        "minibatch_count": verifier.MINIBATCHES_PER_UPDATE,
        "exact_joint_positive_entropy": entropy,
    }


def _synthetic_evidence() -> dict[str, object]:
    run_specs = (
        ("annealed_first", 0, verifier.BASE_COEFFICIENT, True),
        (
            "annealed_middle",
            verifier.TOTAL_UPDATES // 2,
            verifier.BASE_COEFFICIENT,
            True,
        ),
        (
            "annealed_last",
            verifier.TOTAL_UPDATES - 1,
            verifier.BASE_COEFFICIENT,
            True,
        ),
        (
            "disabled_middle",
            verifier.TOTAL_UPDATES // 2,
            verifier.BASE_COEFFICIENT,
            False,
        ),
        ("zero_middle", verifier.TOTAL_UPDATES // 2, 0.0, True),
    )
    runs = [
        _synthetic_run(case, index, base, enabled)
        for case, index, base, enabled in run_specs
    ]
    by_case = {str(run["case"]): run for run in runs}
    probability = 1.0 / (1.0 + math.exp(-verifier.THETA))
    entropy_derivative = -verifier.THETA * probability * (1.0 - probability)
    enabled_coefficient = float(by_case["annealed_middle"]["applied_coefficient"])
    disabled_coefficient = float(by_case["disabled_middle"]["applied_coefficient"])
    enabled_delta = -enabled_coefficient * entropy_derivative
    disabled_delta = -disabled_coefficient * entropy_derivative
    middle_point = verifier.oracle_schedule_point(
        base_coefficient=verifier.BASE_COEFFICIENT,
        anneal_enabled=True,
        min_coefficient_ratio=verifier.MIN_COEFFICIENT_RATIO,
        update_index=verifier.TOTAL_UPDATES // 2,
        total_updates=verifier.TOTAL_UPDATES,
    )
    clip_max = getattr(verifier, "ACTIVE_CLIP_MAX_GRAD_NORM", 0.005)
    clip_pre = [0.02, -0.015]
    clip_expected = [
        value
        * min(1.0, clip_max / (abs(value) + 1.0e-6))
        for value in clip_pre
    ]
    return {
        "schema_version": verifier.SCHEMA_VERSION,
        "contract": verifier.CONTRACT,
        "identity": {
            "git_commit": "a" * 40,
            "pufferl_sha256": "b" * 64,
            "torch_pufferl_sha256": "c" * 64,
            "extension_sha256": "d" * 64,
            "extension_mode": "compiled",
            "extension_contract": verifier.CONTRACT,
        },
        "schedule": {
            "total_updates": verifier.TOTAL_UPDATES,
            "base_coefficient": verifier.BASE_COEFFICIENT,
            "min_coefficient_ratio": verifier.MIN_COEFFICIENT_RATIO,
            "minibatches_per_update": (verifier.MINIBATCHES_PER_UPDATE),
            "point_indices": list(verifier.POINT_INDICES),
            "points": [
                verifier.oracle_schedule_point(
                    base_coefficient=verifier.BASE_COEFFICIENT,
                    anneal_enabled=True,
                    min_coefficient_ratio=(verifier.MIN_COEFFICIENT_RATIO),
                    update_index=index,
                    total_updates=verifier.TOTAL_UPDATES,
                )
                for index in verifier.POINT_INDICES
            ],
        },
        "runs": runs,
        "clipping_control": {
            "max_grad_norm": clip_max,
            "preclip_gradients": clip_pre,
            "optimizer_gradients": clip_expected.copy(),
            "expected_gradients": clip_expected,
            "minibatch_count": verifier.MINIBATCHES_PER_UPDATE,
            "operation_order": [
                "backward",
                "clip",
                "step",
                "backward",
                "clip",
                "step",
            ],
        },
        "gradient_oracle": {
            "theta": verifier.THETA,
            "binary_probability": probability,
            "entropy_derivative": entropy_derivative,
            "enabled_delta": enabled_delta,
            "enabled_expected": enabled_delta,
            "disabled_delta": disabled_delta,
            "disabled_expected": disabled_delta,
            "scale_ratio_actual": (disabled_delta / enabled_delta),
            "scale_ratio_expected": (disabled_coefficient / enabled_coefficient),
            "max_grad_norm": verifier.MAX_GRAD_NORM,
        },
        "guards": {
            "overrun": {
                "error": ("training update exceeds configured total_updates"),
                "negative_epoch_rejected": True,
                "epoch_unchanged": True,
                "tail_unchanged": True,
                "weights_unchanged": True,
                "optimizer_unchanged": True,
                "ratio_unchanged": True,
                "telemetry_unchanged": True,
                "fixture_state_unchanged": True,
                "cpu_rng_unchanged": True,
                "cuda_rng_unchanged": True,
                "policy_forward_unchanged": True,
            },
            "zero_minibatch": {
                "error": verifier.EXPECTED_ZERO_MINIBATCH_ERROR,
                "rejected_before_vec_access": True,
            },
            "failed_update": {
                "recoverable_preflights": {
                    "reset_state_nonfatal": True,
                    "evaluation_mode_nonfatal": True,
                    "negative_epoch_nonfatal": True,
                    "exhausted_epoch_nonfatal": True,
                    "missing_tail_nonfatal": True,
                    "missing_tail_qualification_preserved": True,
                },
                "minibatch_abort": {
                    "error_type": "_InjectedTrainingAbort",
                    "fatal_error": verifier.EXPECTED_FAILED_UPDATE_ERROR,
                    "weight_changed": True,
                    "optimizer_changed": True,
                    "epoch_uncommitted": True,
                    "latch_armed": True,
                    "retry_state_unchanged": True,
                    "retry_rng_unchanged": True,
                    "retry_policy_forward_unchanged": True,
                    "retry_optimizer_unchanged": True,
                    "uptime_rejected": True,
                    "sps_rejected": True,
                    "num_params_rejected": True,
                    "qualification_enable_rejected": True,
                    "mode_switch_rejected": True,
                    "mode_argument_not_coerced": True,
                    "rollout_rejected": True,
                    "log_rejected": True,
                    "eval_log_rejected": True,
                    "qualification_rejected": True,
                    "save_rejected": True,
                    "save_created_no_file": True,
                    "load_rejected": True,
                    "render_rejected": True,
                    "close_succeeded": True,
                },
                "post_loop_abort": {
                    "error_type": "_InjectedTrainingAbort",
                    "fatal_error": verifier.EXPECTED_FAILED_UPDATE_ERROR,
                    "weight_changed": True,
                    "optimizer_changed": True,
                    "epoch_uncommitted": True,
                    "latch_armed": True,
                    "retry_state_unchanged": True,
                    "retry_rng_unchanged": True,
                    "retry_policy_forward_unchanged": True,
                    "retry_optimizer_unchanged": True,
                    "uptime_rejected": True,
                    "sps_rejected": True,
                    "num_params_rejected": True,
                    "qualification_enable_rejected": True,
                    "mode_switch_rejected": True,
                    "mode_argument_not_coerced": True,
                    "rollout_rejected": True,
                    "log_rejected": True,
                    "eval_log_rejected": True,
                    "qualification_rejected": True,
                    "save_rejected": True,
                    "save_created_no_file": True,
                    "load_rejected": True,
                    "render_rejected": True,
                    "close_succeeded": True,
                },
                "post_class_callable_contract": {
                    "set_evaluation_mode_signature_preserved": True,
                    "rollouts_signature_preserved": True,
                    "set_evaluation_mode_metadata_preserved": True,
                    "rollouts_metadata_preserved": True,
                    "dunder_wrapped_alias_absent": True,
                    "standard_unwrap_is_identity": True,
                },
                "success_clear": {
                    "first_update_committed": True,
                    "latch_cleared": True,
                    "second_update_committed": True,
                    "second_latch_cleared": True,
                },
            },
        },
        "telemetry": {
            "eval_before_read": {
                "loss_empty": True,
                "schedule_absent": True,
                "interval_preserved": True,
            },
            "train_read": {
                "loss_present": True,
                "contract": verifier.CONTRACT,
                "first_update_index": verifier.TOTAL_UPDATES // 2,
                "last_update_index": verifier.TOTAL_UPDATES // 2,
                "update_count": 1,
                "loss_minibatch_count": (verifier.MINIBATCHES_PER_UPDATE),
                "c_applied": middle_point["c_applied"],
            },
            "read_clear": {
                "loss_empty": True,
                "schedule_absent": True,
            },
            "evaluation_mode_clear": {
                "loss_empty": True,
                "schedule_absent": True,
            },
        },
    }


class TorchEntropyOracleTests(unittest.TestCase):
    def test_n20_first_middle_last_binary32_schedule(self) -> None:
        points = [
            verifier.oracle_schedule_point(
                base_coefficient=verifier.BASE_COEFFICIENT,
                anneal_enabled=True,
                min_coefficient_ratio=verifier.MIN_COEFFICIENT_RATIO,
                update_index=index,
                total_updates=verifier.TOTAL_UPDATES,
            )
            for index in verifier.POINT_INDICES
        ]
        self.assertEqual(
            [point["update_index"] for point in points],
            [0, 10, 19],
        )
        self.assertEqual(points[0]["progress"], 0.0)
        self.assertEqual(points[1]["progress"], 0.5)
        self.assertEqual(points[2]["progress"], 0.95)
        self.assertAlmostEqual(points[0]["c_real"], 0.2)
        self.assertAlmostEqual(points[1]["c_real"], 0.11)
        self.assertGreater(points[2]["c_real"], 0.02)
        self.assertLess(points[2]["c_real"], points[1]["c_real"])
        self.assertNotEqual(points[0]["c_applied"], points[0]["c_real"])

    def test_disabled_and_zero_base_oracles(self) -> None:
        disabled = verifier.oracle_schedule_point(
            base_coefficient=verifier.BASE_COEFFICIENT,
            anneal_enabled=False,
            min_coefficient_ratio=verifier.MIN_COEFFICIENT_RATIO,
            update_index=10,
            total_updates=verifier.TOTAL_UPDATES,
        )
        zero = verifier.oracle_schedule_point(
            base_coefficient=0.0,
            anneal_enabled=True,
            min_coefficient_ratio=verifier.MIN_COEFFICIENT_RATIO,
            update_index=10,
            total_updates=verifier.TOTAL_UPDATES,
        )
        self.assertEqual(
            disabled["c_applied"],
            verifier._binary32(verifier.BASE_COEFFICIENT),
        )
        self.assertEqual(zero["c_real"], 0.0)
        self.assertEqual(zero["c_applied"], 0.0)


class ClosedEvidenceTests(unittest.TestCase):
    def test_synthetic_evidence_is_valid_and_canonical_json(self) -> None:
        evidence = _synthetic_evidence()
        self.assertIs(verifier.validate_evidence(evidence), evidence)
        rendered = verifier.canonical_json(evidence)
        self.assertEqual(json.loads(rendered), evidence)
        self.assertNotIn("NaN", rendered)

    def test_closed_schema_and_semantic_tampering_are_rejected(self) -> None:
        mutations: list[tuple[str, dict[str, object]]] = []

        extra = _synthetic_evidence()
        extra["surprise"] = True
        mutations.append(("top-level extra", extra))

        missing = _synthetic_evidence()
        del missing["guards"]["overrun"]["tail_unchanged"]
        mutations.append(("nested missing", missing))

        coefficient = _synthetic_evidence()
        coefficient["runs"][1]["entropy_hook_coefficients"][1] += 0.01
        mutations.append(("per-minibatch coefficient", coefficient))

        schedule_base = _synthetic_evidence()
        schedule_base["schedule"]["base_coefficient"] += 5.0e-6
        mutations.append(("schedule base drift", schedule_base))

        schedule_ratio = _synthetic_evidence()
        schedule_ratio["schedule"]["min_coefficient_ratio"] += 3.0e-6
        mutations.append(("schedule ratio drift", schedule_ratio))

        clipping = _synthetic_evidence()
        clipping["runs"][1]["optimizer_gradients"][0] += 0.01
        mutations.append(("clipping mismatch", clipping))

        inactive_clipping = _synthetic_evidence()
        inactive_clipping["clipping_control"][
            "optimizer_gradients"
        ] = inactive_clipping["clipping_control"][
            "preclip_gradients"
        ].copy()
        mutations.append(("active clipping did not execute", inactive_clipping))

        wrong_clip_oracle = _synthetic_evidence()
        wrong_clip_oracle["clipping_control"]["expected_gradients"][0] *= 0.5
        mutations.append(("active clipping oracle drift", wrong_clip_oracle))

        wrong_clip_order = _synthetic_evidence()
        wrong_clip_order["clipping_control"]["operation_order"][1:3] = [
            "step",
            "clip",
        ]
        mutations.append(("active clipping operation order", wrong_clip_order))

        wrong_run_order = _synthetic_evidence()
        wrong_run_order["runs"][1]["operation_order"][1:3] = [
            "step",
            "clip",
        ]
        mutations.append(("run operation order", wrong_run_order))

        decomposition = _synthetic_evidence()
        decomposition["runs"][1]["total_loss"] += 0.01
        mutations.append(("total decomposition", decomposition))

        for offset in (1.0, 1.0e-3):
            entropy_offset = _synthetic_evidence()
            offset_run = entropy_offset["runs"][1]
            offset_run["entropy"] += offset
            offset_run["exact_joint_positive_entropy"] += offset
            offset_run["entropy_term"] = (
                -offset_run["applied_coefficient"] * offset_run["entropy"]
            )
            offset_run["total_loss"] = (
                offset_run["policy_loss"]
                + verifier.VF_COEFFICIENT * offset_run["value_loss"]
                + offset_run["entropy_term"]
            )
            mutations.append(
                (f"coordinated entropy offset {offset}", entropy_offset)
            )

        gradient = _synthetic_evidence()
        gradient["gradient_oracle"]["enabled_delta"] *= -1.0
        mutations.append(("gradient sign", gradient))

        run_gradient = _synthetic_evidence()
        run_gradient["runs"][1]["preclip_gradients"][0] += 0.01
        run_gradient["runs"][1]["optimizer_gradients"][0] += 0.01
        mutations.append(("raw gradient linkage", run_gradient))

        overrun = _synthetic_evidence()
        overrun["guards"]["overrun"]["weights_unchanged"] = False
        mutations.append(("overrun mutation", overrun))

        stale_eval = _synthetic_evidence()
        stale_eval["telemetry"]["evaluation_mode_clear"]["schedule_absent"] = False
        mutations.append(("stale evaluation", stale_eval))

        nonfinite = _synthetic_evidence()
        nonfinite["runs"][0]["entropy"] = float("nan")
        mutations.append(("nonfinite", nonfinite))

        for label, evidence in mutations:
            with self.subTest(label=label):
                with self.assertRaises(verifier.VerificationError):
                    verifier.validate_evidence(evidence)

    def test_test_stub_evidence_requires_explicit_opt_in(self) -> None:
        evidence = _synthetic_evidence()
        evidence["identity"]["extension_mode"] = "test_stub"
        with self.assertRaisesRegex(
            verifier.VerificationError, "not qualification evidence"
        ):
            verifier.validate_evidence(evidence)
        self.assertIs(
            verifier.validate_evidence(evidence, allow_test_stub=True),
            evidence,
        )

    def test_input_is_not_normalized_before_closed_schema_validation(
        self,
    ) -> None:
        evidence = _synthetic_evidence()
        evidence["guards"]["overrun"]["epoch_unchanged"] = 1
        with self.assertRaisesRegex(verifier.VerificationError, "must be a boolean"):
            verifier.validate_evidence(evidence)

    def test_semantic_integer_fields_reject_equal_float_and_bool_impostors(
        self,
    ) -> None:
        mutations = []

        schema = _synthetic_evidence()
        schema["schema_version"] = 1.0
        mutations.append(("schema_version float", schema))

        total_updates = _synthetic_evidence()
        total_updates["schedule"]["total_updates"] = 20.0
        mutations.append(("total_updates float", total_updates))

        minibatches = _synthetic_evidence()
        minibatches["schedule"]["minibatches_per_update"] = 2.0
        mutations.append(("schedule minibatches float", minibatches))

        point_indices = _synthetic_evidence()
        point_indices["schedule"]["point_indices"][0] = False
        mutations.append(("point index bool", point_indices))

        point = _synthetic_evidence()
        point["schedule"]["points"][0]["update_index"] = 0.0
        mutations.append(("point update float", point))

        run_update = _synthetic_evidence()
        run_update["runs"][0]["update_index"] = 0.0
        mutations.append(("run update float", run_update))

        run_minibatches = _synthetic_evidence()
        run_minibatches["runs"][0]["minibatch_count"] = 2.0
        mutations.append(("run minibatches float", run_minibatches))

        telemetry_update = _synthetic_evidence()
        telemetry_update["telemetry"]["train_read"]["update_count"] = True
        mutations.append(("telemetry update bool", telemetry_update))

        telemetry_minibatches = _synthetic_evidence()
        telemetry_minibatches["telemetry"]["train_read"][
            "loss_minibatch_count"
        ] = 2.0
        mutations.append(("telemetry minibatches float", telemetry_minibatches))

        telemetry_first = _synthetic_evidence()
        telemetry_first["telemetry"]["train_read"]["first_update_index"] = 10.0
        mutations.append(("telemetry first update float", telemetry_first))

        telemetry_last = _synthetic_evidence()
        telemetry_last["telemetry"]["train_read"]["last_update_index"] = 10.0
        mutations.append(("telemetry last update float", telemetry_last))

        clipping_minibatches = _synthetic_evidence()
        clipping_minibatches["clipping_control"]["minibatch_count"] = 2.0
        mutations.append(("clipping minibatches float", clipping_minibatches))

        for label, evidence in mutations:
            with self.subTest(label=label):
                with self.assertRaises(verifier.VerificationError):
                    verifier.validate_evidence(evidence)

    def test_guard_evidence_rejects_arbitrary_nonempty_error_text(self) -> None:
        overrun = _synthetic_evidence()
        overrun["guards"]["overrun"]["error"] = "unrelated failure"
        zero = _synthetic_evidence()
        zero["guards"]["zero_minibatch"]["error"] = "unrelated failure"
        for label, evidence in (("overrun", overrun), ("zero minibatch", zero)):
            with self.subTest(label=label):
                with self.assertRaises(verifier.VerificationError):
                    verifier.validate_evidence(evidence)

    def test_huge_json_integer_is_reported_as_verification_error(self) -> None:
        evidence = _synthetic_evidence()
        evidence["runs"][0]["entropy"] = 10**10000
        with self.assertRaisesRegex(
            verifier.VerificationError,
            "must be finite",
        ):
            verifier.validate_evidence(evidence)


class SourceGateTests(unittest.TestCase):
    def test_verifier_calls_real_train_and_captures_before_clip(self) -> None:
        source = Path(verifier.__file__).read_text(encoding="utf-8")
        train_call = source.index("trainer.train()")
        hook = source.index("policy.theta.register_hook")
        optimizer_capture = source.index("self.step_gradients.append")
        self.assertLess(hook, train_call)
        self.assertIn("entropy.register_hook", source)
        self.assertIn("preclip_gradients", source)
        self.assertIn("optimizer_gradients", source)
        self.assertIn("_execute_active_clipping_control", source)
        self.assertIn("expected_gradients", source)
        self.assertIn("sample_joint_logits(", source)
        self.assertIn("exact_joint_positive_entropy", source)
        self.assertLess(optimizer_capture, train_call)
        extension_path_check = source.index(
            '_selected_module_path(extension, root, "pufferlib._C")'
        )
        extension_contract_check = source.index("extension_contract = getattr(")
        self.assertLess(extension_path_check, extension_contract_check)

    def test_verifier_seeds_policy_and_exact_joint_sampling(self) -> None:
        source = Path(verifier.__file__).read_text(encoding="utf-8")
        self.assertIn("torch.manual_seed(902_177)", source)
        self.assertIn("torch.manual_seed(730_021)", source)
        self.assertNotIn("torch.cuda.is_available()", source)

    def test_source_gate_closes_failed_update_latch_order_and_surfaces(
        self,
    ) -> None:
        valid_order = (
            "loss.backward()",
            "torch.nn.utils.clip_grad_norm_(\n"
            "    self.policy.parameters(), config['max_grad_norm'])",
            "self.optimizer.step()",
        )
        mutations = (
            (
                "train fatal guard",
                "    def train(self):\n"
                "        if self._training_failed:\n"
                "            raise RuntimeError(\n"
                f"                '{verifier.EXPECTED_FAILED_UPDATE_ERROR}')\n"
                "        if not self.reset_state or self.evaluation_mode:\n",
                "    def train(self):\n"
                "        if not self.reset_state or self.evaluation_mode:\n",
                "first statement",
            ),
            (
                "latch arm",
                "        if not self.tail_valid:\n"
                "            raise RuntimeError(\n"
                "                'training requires one fresh tail record')\n"
                "        self._training_failed = True\n",
                "        self._training_failed = True\n"
                "        if not self.tail_valid:\n"
                "            raise RuntimeError(\n"
                "                'training requires one fresh tail record')\n",
                "arm its fatal latch immediately",
            ),
            (
                "latch clear",
                "        self._train_log_interval = None\n"
                "        self._training_failed = False\n",
                "        self._training_failed = False\n"
                "        self._train_log_interval = None\n",
                "final successful publication",
            ),
            (
                "rollout wrapper guard",
                "def _reject_incomplete_update_rollouts(method):\n"
                "    def guarded(self):\n"
                "        if self._training_failed:\n"
                "            raise RuntimeError(\n"
                f"                '{verifier.EXPECTED_FAILED_UPDATE_ERROR}')\n"
                "        return method(self)\n",
                "def _reject_incomplete_update_rollouts(method):\n"
                "    def guarded(self):\n"
                "        return method(self)\n",
                "post-class failed-update wrapper contract",
            ),
            (
                "log guard",
                "    def _log(self):\n"
                "        if self._training_failed:\n"
                "            raise RuntimeError(\n"
                f"                '{verifier.EXPECTED_FAILED_UPDATE_ERROR}')\n"
                "        return None\n",
                "    def _log(self):\n"
                "        return None\n",
                "PuffeRL._log",
            ),
            (
                "qualification guard",
                "    def qualification_entropy_gradient_state(self):\n"
                "        if self._training_failed:\n"
                "            raise RuntimeError(\n"
                f"                '{verifier.EXPECTED_FAILED_UPDATE_ERROR}')\n"
                "        return None\n",
                "    def qualification_entropy_gradient_state(self):\n"
                "        return None\n",
                "qualification_entropy_gradient_state",
            ),
            (
                "save guard",
                "    def save_weights(self, path):\n"
                "        if self._training_failed:\n"
                "            raise RuntimeError(\n"
                f"                '{verifier.EXPECTED_FAILED_UPDATE_ERROR}')\n"
                "        return None\n",
                "    def save_weights(self, path):\n"
                "        return None\n",
                "PuffeRL.save_weights",
            ),
        )
        for label, old, new, expected_error in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _write_source_fixture(root, train_order=valid_order)
                source_path = root / "pufferlib" / "torch_pufferl.py"
                source = source_path.read_text(encoding="utf-8")
                self.assertEqual(source.count(old), 1)
                source_path.write_text(
                    source.replace(old, new, 1),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    verifier.VerificationError,
                    expected_error,
                ):
                    verifier.validate_selected_source(root)

        guarded_headers = {
            "uptime": "    def uptime(self):",
            "sps": "    def sps(self):",
            "num_params": "    def num_params(self):",
            "enable_entropy_gradient_qualification": (
                "    def enable_entropy_gradient_qualification(self):"
            ),
            "qualification_entropy_gradient_state": (
                "    def qualification_entropy_gradient_state(self):"
            ),
            "train": "    def train(self):",
            "_log": "    def _log(self):",
            "log": "    def log(self):",
            "eval_log": "    def eval_log(self):",
            "save_weights": "    def save_weights(self, path):",
            "load_weights": "    def load_weights(self, path):",
            "render": "    def render(self, env_id=0):",
        }
        failed_guard = (
            "        if self._training_failed:\n"
            "            raise RuntimeError(\n"
            f"                '{verifier.EXPECTED_FAILED_UPDATE_ERROR}')\n"
        )
        self.assertEqual(
            frozenset(guarded_headers),
            frozenset(verifier.INLINE_FAILED_UPDATE_GUARDED_METHODS),
        )
        for method_name, header in guarded_headers.items():
            with (
                self.subTest(public_surface=method_name),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                _write_source_fixture(root, train_order=valid_order)
                source_path = root / "pufferlib" / "torch_pufferl.py"
                source = source_path.read_text(encoding="utf-8")
                guarded_header = f"{header}\n{failed_guard}"
                self.assertEqual(source.count(guarded_header), 1)
                source_path.write_text(
                    source.replace(guarded_header, f"{header}\n", 1),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    verifier.VerificationError,
                    rf"PuffeRL\.{re.escape(method_name)}",
                ):
                    verifier.validate_selected_source(root)

        post_class_factory_headers = {
            "set_evaluation_mode": (
                "def _reject_incomplete_update_set_evaluation_mode(method):\n"
                "    def guarded(self, enabled):"
            ),
            "rollouts": (
                "def _reject_incomplete_update_rollouts(method):\n"
                "    def guarded(self):"
            ),
        }
        self.assertEqual(
            frozenset(post_class_factory_headers),
            frozenset(verifier.POST_CLASS_FAILED_UPDATE_GUARDED_METHODS),
        )
        post_class_guard = (
            "\n        if self._training_failed:\n"
            "            raise RuntimeError(\n"
            f"                '{verifier.EXPECTED_FAILED_UPDATE_ERROR}')"
        )
        for method_name, header in post_class_factory_headers.items():
            with (
                self.subTest(post_class_surface=method_name),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                _write_source_fixture(root, train_order=valid_order)
                source_path = root / "pufferlib" / "torch_pufferl.py"
                source = source_path.read_text(encoding="utf-8")
                target = header + post_class_guard
                self.assertEqual(source.count(target), 1)
                source_path.write_text(
                    source.replace(target, header, 1),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    verifier.VerificationError,
                    "post-class failed-update wrapper contract",
                ):
                    verifier.validate_selected_source(root)

    def test_source_gate_closes_post_class_wrapper_identity(self) -> None:
        valid_order = (
            "loss.backward()",
            "torch.nn.utils.clip_grad_norm_(\n"
            "    self.policy.parameters(), config['max_grad_norm'])",
            "self.optimizer.step()",
        )
        mutations = (
            (
                "signature",
                "    def guarded(self, enabled):",
                "    def guarded(self, enabled=True):",
                "post-class failed-update wrapper contract",
            ),
            (
                "module metadata",
                "    guarded.__module__ = method.__module__",
                "    guarded.__module__ = __name__",
                "post-class failed-update wrapper contract",
            ),
            (
                "effective assignment",
                (
                    "PuffeRL.rollouts = "
                    "_reject_incomplete_update_rollouts(PuffeRL.rollouts)"
                ),
                "PuffeRL.rollouts = PuffeRL.rollouts",
                "post-class failed-update wrapper contract",
            ),
            (
                "duplicate earlier store",
                "def _copy_public_callable_metadata(guarded, method):",
                (
                    "PuffeRL.rollouts = PuffeRL.rollouts\n\n"
                    "def _copy_public_callable_metadata(guarded, method):"
                ),
                "store exactly once to PuffeRL.rollouts",
            ),
        )
        for label, old, new, expected_error in mutations:
            with (
                self.subTest(label=label),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                _write_source_fixture(root, train_order=valid_order)
                source_path = root / "pufferlib" / "torch_pufferl.py"
                source = source_path.read_text(encoding="utf-8")
                self.assertEqual(source.count(old), 1)
                source_path.write_text(
                    source.replace(old, new, 1),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    verifier.VerificationError,
                    expected_error,
                ):
                    verifier.validate_selected_source(root)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_source_fixture(root, train_order=valid_order)
            source_path = root / "pufferlib" / "torch_pufferl.py"
            source = source_path.read_text(encoding="utf-8")
            marker = "def _copy_public_callable_metadata(guarded, method):"
            self.assertEqual(source.count(marker), 1)
            source_path.write_text(
                source.replace(
                    marker,
                    "UNSAFE.__wrapped__ = None\n\n" + marker,
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                verifier.VerificationError,
                "must not expose.*__wrapped__",
            ):
                verifier.validate_selected_source(root)

    def test_post_class_wrappers_preserve_runtime_contract_and_guard_coercion(
        self,
    ) -> None:
        valid_order = (
            "loss.backward()",
            "torch.nn.utils.clip_grad_norm_(\n"
            "    self.policy.parameters(), config['max_grad_norm'])",
            "self.optimizer.step()",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_source_fixture(root, train_order=valid_order)
            source_path = root / "pufferlib" / "torch_pufferl.py"
            spec = importlib.util.spec_from_file_location(
                "_synthetic_torch_pufferl_wrapper_contract",
                source_path,
            )
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            contract = verifier._verify_post_class_wrapper_runtime_contract(
                module
            )
            self.assertEqual(
                frozenset(contract),
                verifier.POST_CLASS_CALLABLE_CONTRACT_KEYS,
            )
            self.assertTrue(all(contract.values()))
            self.assertEqual(
                str(inspect.signature(module.PuffeRL.set_evaluation_mode)),
                "(self, enabled)",
            )
            self.assertEqual(
                str(inspect.signature(module.PuffeRL.rollouts)),
                "(self)",
            )
            trainer = object.__new__(module.PuffeRL)
            trainer._training_failed = True

            class ExplosiveTruthiness:
                def __init__(self) -> None:
                    self.calls = 0

                def __bool__(self) -> bool:
                    self.calls += 1
                    raise AssertionError("unexpected truthiness coercion")

            enabled = ExplosiveTruthiness()
            with self.assertRaisesRegex(
                RuntimeError,
                re.escape(verifier.EXPECTED_FAILED_UPDATE_ERROR),
            ):
                trainer.set_evaluation_mode(enabled)
            self.assertEqual(enabled.calls, 0)
            with self.assertRaisesRegex(
                RuntimeError,
                re.escape(verifier.EXPECTED_FAILED_UPDATE_ERROR),
            ):
                trainer.rollouts()
            self.assertEqual(
                str(inspect.signature(trainer.set_evaluation_mode)),
                "(enabled)",
            )
            self.assertEqual(
                str(inspect.signature(trainer.rollouts)),
                "()",
            )
            self.assertIs(
                inspect.unwrap(module.PuffeRL.set_evaluation_mode),
                module.PuffeRL.set_evaluation_mode,
            )
            self.assertIs(
                inspect.unwrap(module.PuffeRL.rollouts),
                module.PuffeRL.rollouts,
            )

    def test_source_gate_enforces_backward_clip_step_order(self) -> None:
        valid_order = (
            "loss.backward()",
            "torch.nn.utils.clip_grad_norm_(\n"
            "    self.policy.parameters(), config['max_grad_norm'])",
            "self.optimizer.step()",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_source_fixture(root, train_order=valid_order)
            verifier.validate_selected_source(root)

        invalid_order = (
            "loss.backward()",
            "self.optimizer.step()",
            "torch.nn.utils.clip_grad_norm_(\n"
            "    self.policy.parameters(), config['max_grad_norm'])",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_source_fixture(root, train_order=invalid_order)
            with self.assertRaisesRegex(
                verifier.VerificationError,
                "loss.backward.*clip_grad_norm_.*optimizer.step",
            ):
                verifier.validate_selected_source(root)

    def test_source_gate_ignores_docstring_call_order_decoys(self) -> None:
        valid_order = (
            "loss.backward()",
            "torch.nn.utils.clip_grad_norm_(\n"
            "    self.policy.parameters(), config['max_grad_norm'])",
            "self.optimizer.step()",
        )
        invalid_order = (
            "self.optimizer.step()",
            "loss.backward()",
            "torch.nn.utils.clip_grad_norm_(\n"
            "    self.policy.parameters(), config['max_grad_norm'])",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_source_fixture(
                root,
                train_order=invalid_order,
                train_decoy=valid_order,
            )
            with self.assertRaisesRegex(
                verifier.VerificationError,
                "loss.backward.*clip_grad_norm_.*optimizer.step",
            ):
                verifier.validate_selected_source(root)

    def test_source_gate_requires_the_real_torch_clipper_receiver(self) -> None:
        fake_clipper = (
            "loss.backward()",
            "fake.clip_grad_norm_(\n"
            "    self.policy.parameters(), config['max_grad_norm'])",
            "self.optimizer.step()",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_source_fixture(root, train_order=fake_clipper)
            with self.assertRaisesRegex(
                verifier.VerificationError,
                "clip_grad_norm_",
            ):
                verifier.validate_selected_source(root)

    def test_source_gate_rejects_a_nonexecuting_clipper_branch(self) -> None:
        conditional_clipper = (
            "loss.backward()",
            "if False:\n"
            "    torch.nn.utils.clip_grad_norm_(\n"
            "        self.policy.parameters(), config['max_grad_norm'])",
            "self.optimizer.step()",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_source_fixture(root, train_order=conditional_clipper)
            with self.assertRaisesRegex(
                verifier.VerificationError,
                "directly in its.*num_minibatches",
            ):
                verifier.validate_selected_source(root)

    def test_source_gate_rejects_an_entire_unreachable_decoy_block(self) -> None:
        unreachable_decoy_and_aliases = (
            "if False:\n"
            "    loss.backward()\n"
            "    torch.nn.utils.clip_grad_norm_(\n"
            "        self.policy.parameters(), config['max_grad_norm'])\n"
            "    self.optimizer.step()",
            "backward = loss.backward\n"
            "step = self.optimizer.step\n"
            "clip = torch.nn.utils.clip_grad_norm_\n"
            "backward()\n"
            "step()",
            "clip(self.policy.parameters(), config['max_grad_norm'])",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_source_fixture(
                root,
                train_order=unreachable_decoy_and_aliases,
            )
            with self.assertRaisesRegex(
                verifier.VerificationError,
                "loss.backward.*clip_grad_norm_.*optimizer.step",
            ):
                verifier.validate_selected_source(root)

    def test_source_gate_rejects_exact_calls_in_a_nested_function(self) -> None:
        nested_decoy_and_aliases = (
            "def never_called_exact_order_decoy():\n"
            "    loss.backward()\n"
            "    torch.nn.utils.clip_grad_norm_(\n"
            "        self.policy.parameters(), config['max_grad_norm'])\n"
            "    self.optimizer.step()",
            "backward = loss.backward\n"
            "step = self.optimizer.step\n"
            "clip = torch.nn.utils.clip_grad_norm_\n"
            "backward()\n"
            "step()",
            "clip(self.policy.parameters(), config['max_grad_norm'])",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_source_fixture(
                root,
                train_order=nested_decoy_and_aliases,
            )
            with self.assertRaisesRegex(
                verifier.VerificationError,
                "loss.backward",
            ):
                verifier.validate_selected_source(root)

    def test_source_gate_binds_full_parameter_iterator_and_default_l2(self) -> None:
        invalid_clips = (
            (
                "subset",
                "torch.nn.utils.clip_grad_norm_(\n"
                "    list(self.policy.parameters())[:1], "
                "config['max_grad_norm'])",
            ),
            (
                "l1 norm",
                "torch.nn.utils.clip_grad_norm_(\n"
                "    self.policy.parameters(), config['max_grad_norm'], "
                "norm_type=1.0)",
            ),
            (
                "literal bound",
                "torch.nn.utils.clip_grad_norm_(\n"
                "    self.policy.parameters(), 0.5)",
            ),
        )
        for label, clip_call in invalid_clips:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _write_source_fixture(
                    root,
                    train_order=(
                        "loss.backward()",
                        clip_call,
                        "self.optimizer.step()",
                    ),
                )
                with self.assertRaisesRegex(
                    verifier.VerificationError,
                    "exactly self.policy.parameters.*config.*max_grad_norm",
                ):
                    verifier.validate_selected_source(root)

    def test_source_gate_requires_direct_minibatch_loop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_source_fixture(
                root,
                train_order=(
                    "if self._entropy_gradient_qualification_enabled:\n"
                    "    loss.backward()\n"
                    "    torch.nn.utils.clip_grad_norm_(\n"
                    "        self.policy.parameters(), config['max_grad_norm'])\n"
                    "    self.optimizer.step()",
                    "backward = loss.backward\n"
                    "step = self.optimizer.step\n"
                    "backward()\n"
                    "step()",
                    "pass",
                ),
            )
            with self.assertRaisesRegex(
                verifier.VerificationError,
                "directly in its.*num_minibatches",
            ):
                verifier.validate_selected_source(root)

    def test_source_gate_rejects_conditionally_short_circuited_calls(self) -> None:
        conditional_pairs = (
            (
                "self.device == 'cpu' and "
                "torch.nn.utils.clip_grad_norm_(\n"
                "    self.policy.parameters(), config['max_grad_norm'])",
                "self.device == 'cpu' and self.optimizer.step()",
            ),
            (
                "torch.nn.utils.clip_grad_norm_(\n"
                "    self.policy.parameters(), config['max_grad_norm']) "
                "if self.device == 'cpu' else None",
                "self.optimizer.step() if self.device == 'cpu' else None",
            ),
        )
        for clip_call, step_call in conditional_pairs:
            with self.subTest(clip_call=clip_call), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _write_source_fixture(
                    root,
                    train_order=(
                        "loss.backward()",
                        clip_call,
                        step_call,
                    ),
                )
                with self.assertRaisesRegex(
                    verifier.VerificationError,
                    "unconditional standalone expression",
                ):
                    verifier.validate_selected_source(root)

    def test_source_gate_rejects_loop_control_that_can_skip_objective(
        self,
    ) -> None:
        valid_order = (
            "loss.backward()",
            "torch.nn.utils.clip_grad_norm_(\n"
            "    self.policy.parameters(), config['max_grad_norm'])",
            "self.optimizer.step()",
        )
        skip_operations = (
            "if self.device != 'cpu':\n    continue",
            "if self.device != 'cpu':\n    break",
            "if self.device != 'cpu':\n    return None",
        )
        for operation in skip_operations:
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _write_source_fixture(
                    root,
                    train_order=valid_order,
                    minibatch_prefix=(operation,),
                )
                with self.assertRaisesRegex(
                    verifier.VerificationError,
                    "control flow that can skip",
                ):
                    verifier.validate_selected_source(root)

    def test_source_gate_rejects_objective_calls_in_for_else(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_source_fixture(
                root,
                train_order=(
                    "loss.backward()",
                    "torch.nn.utils.clip_grad_norm_(\n"
                    "    self.policy.parameters(), config['max_grad_norm'])",
                    "self.optimizer.step()",
                ),
                objective_in_loop_else=True,
            )
            with self.assertRaisesRegex(
                verifier.VerificationError,
                "directly in its.*num_minibatches",
            ):
                verifier.validate_selected_source(root)

    def test_source_gate_rejects_function_exit_before_minibatch_loop(
        self,
    ) -> None:
        for operation in (
            "if self.device != 'cpu':\n    return None",
            "if self.device != 'cpu':\n    yield None",
        ):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _write_source_fixture(
                    root,
                    train_order=(
                        "loss.backward()",
                        "torch.nn.utils.clip_grad_norm_(\n"
                        "    self.policy.parameters(), "
                        "config['max_grad_norm'])",
                        "self.optimizer.step()",
                    ),
                    pre_minibatch=(operation,),
                )
                with self.assertRaisesRegex(
                    verifier.VerificationError,
                    "control flow that can skip",
                ):
                    verifier.validate_selected_source(root)

    def test_source_gate_rejects_any_operation_before_overrun_guard(self) -> None:
        pre_guard_operations = (
            "self.values.add_(123.0)",
            "torch.rand(1)",
            "self.pending_rewards.zero_()",
            "self.losses['pre_guard'] = 1.0",
            "losses = defaultdict(int)",
            "losses = defaultdict(float, {'pre_guard': 1.0})",
            "self.policy(self.observations)",
            "self.optimizer.zero_grad()",
        )
        valid_order = (
            "loss.backward()",
            "torch.nn.utils.clip_grad_norm_(\n"
            "    self.policy.parameters(), config['max_grad_norm'])",
            "self.optimizer.step()",
        )
        for operation in pre_guard_operations:
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _write_source_fixture(
                    root,
                    train_order=valid_order,
                    pre_overrun=(operation,),
                )
                with self.assertRaisesRegex(
                    verifier.VerificationError,
                    "overrun guard must precede",
                ):
                    verifier.validate_selected_source(root)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_source_fixture(root, train_order=valid_order)
            source_path = root / "pufferlib" / "torch_pufferl.py"
            source = source_path.read_text(encoding="utf-8")
            source_path.write_text(
                source.replace(
                    "                'training update exceeds configured "
                    "total_updates')\n"
                    "        if not self.tail_valid:",
                    "                'training update exceeds configured "
                    "total_updates')\n"
                    "        losses['before_latch'] += 1.0\n"
                    "        if not self.tail_valid:",
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                verifier.VerificationError,
                "must not read or mutate",
            ):
                verifier.validate_selected_source(root)

    def test_source_gate_rejects_upper_only_epoch_guard(self) -> None:
        valid_order = (
            "loss.backward()",
            "torch.nn.utils.clip_grad_norm_(\n"
            "    self.policy.parameters(), config['max_grad_norm'])",
            "self.optimizer.step()",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_source_fixture(root, train_order=valid_order)
            source_path = root / "pufferlib" / "torch_pufferl.py"
            source = source_path.read_text(encoding="utf-8")
            source_path.write_text(
                source.replace(
                    "self.epoch < 0 or "
                    "self.epoch >= self.total_epochs",
                    "self.epoch >= self.total_epochs",
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                verifier.VerificationError,
                "public.*bounds guard",
            ):
                verifier.validate_selected_source(root)

    def test_trusted_clipper_detects_drift_and_restores_both_aliases(self) -> None:
        def genuine(*_args: object, **_kwargs: object) -> None:
            return None

        def fake(*_args: object, **_kwargs: object) -> None:
            return None

        clip_module = types.SimpleNamespace(clip_grad_norm_=genuine)
        utils_module = types.SimpleNamespace(
            clip_grad_norm_=genuine,
            clip_grad=clip_module,
        )
        nn_module = types.SimpleNamespace(utils=utils_module)
        torch = types.SimpleNamespace(nn=nn_module)
        trust = verifier._capture_trusted_torch_clipper(torch)

        utils_module.clip_grad_norm_ = fake
        clip_module.clip_grad_norm_ = fake
        with self.assertRaisesRegex(
            verifier.VerificationError,
            "changed after trusted Torch capture",
        ):
            verifier._require_trusted_torch_clipper(torch, trust)

        verifier._restore_trusted_torch_clipper(torch, trust)
        self.assertIs(torch.nn, nn_module)
        self.assertIs(torch.nn.utils, utils_module)
        self.assertIs(torch.nn.utils.clip_grad, clip_module)
        self.assertIs(torch.nn.utils.clip_grad_norm_, genuine)
        self.assertIs(torch.nn.utils.clip_grad.clip_grad_norm_, genuine)

    def test_trusted_clipper_detects_in_place_function_drift(self) -> None:
        def genuine_base(value: float = 2.0) -> float:
            return value

        def decorate(function):
            def wrapper(*args, **kwargs):
                return function(*args, **kwargs)

            wrapper.__wrapped__ = function
            return wrapper

        genuine = decorate(genuine_base)

        def fake(*_args, **_kwargs):
            return -1.0

        clip_module = types.SimpleNamespace(clip_grad_norm_=genuine)
        utils_module = types.SimpleNamespace(
            clip_grad_norm_=genuine,
            clip_grad=clip_module,
        )
        torch = types.SimpleNamespace(
            nn=types.SimpleNamespace(utils=utils_module),
        )
        trust = verifier._capture_trusted_torch_clipper(torch)

        genuine.__closure__[0].cell_contents = fake
        with self.assertRaisesRegex(
            verifier.VerificationError,
            "changed after trusted Torch capture",
        ):
            verifier._require_trusted_torch_clipper(torch, trust)
        verifier._restore_trusted_torch_clipper(torch, trust)
        self.assertEqual(genuine(), 2.0)

        genuine.__wrapped__.__defaults__ = (1.0,)
        with self.assertRaisesRegex(
            verifier.VerificationError,
            "changed after trusted Torch capture",
        ):
            verifier._require_trusted_torch_clipper(torch, trust)
        verifier._restore_trusted_torch_clipper(torch, trust)
        self.assertEqual(genuine(), 2.0)

    def test_optimizer_does_not_expose_mutable_operation_events(self) -> None:
        class FakeParameter:
            grad = None

            def detach(self):
                return self

            def new_tensor(self, values):
                return list(values)

        optimizer = verifier._RecordingOptimizer(
            FakeParameter(),
        )
        self.assertFalse(hasattr(optimizer, "operation_events"))

    def test_identity_rejects_source_drift_from_validated_bytes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "pufferl.py"
            torch_path = root / "torch_pufferl.py"
            config_path.write_bytes(b"config-before\n")
            torch_path.write_bytes(b"torch-before\n")
            source = {
                "root": root,
                "config_path": config_path,
                "torch_path": torch_path,
                "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
                "torch_sha256": hashlib.sha256(torch_path.read_bytes()).hexdigest(),
            }
            torch_path.write_bytes(b"torch-after!\n")
            with self.assertRaisesRegex(
                verifier.VerificationError,
                "changed after initial source validation",
            ):
                verifier._identity(
                    source,
                    verifier._make_extension_stub(),
                    "test_stub",
                )

    def test_source_rejection_occurs_before_dependency_import(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pufferlib").mkdir()
            (root / "src").mkdir()
            (root / "pufferlib" / "torch_pufferl.py").write_text(
                "def entropy_schedule_point():\n    return None\n",
                encoding="utf-8",
            )
            (root / "pufferlib" / "pufferl.py").write_text(
                "def validate_entropy_schedule_config(args):\n" "    return args\n",
                encoding="utf-8",
            )
            marker = (
                'm.attr("entropy_schedule_contract") = ' f'"{verifier.CONTRACT}";\n'
            )
            (root / "src" / "bindings_cpu.cpp").write_text(marker, encoding="utf-8")
            (root / "src" / "bindings.cu").write_text(marker, encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(verifier.__file__)),
                    "--puffer-root",
                    str(root),
                    "--allow-test-extension-stub",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("lacks required objective surfaces", result.stderr)
        self.assertNotIn("No module named 'torch'", result.stderr)

    def test_selected_import_restores_process_globals_after_success(
        self,
    ) -> None:
        def imported_excepthook(
            _kind: type[BaseException],
            _value: BaseException,
            _traceback: object,
        ) -> None:
            return None

        def imported_sigint_handler(_signal: int, _frame: object) -> None:
            return None

        shell = types.SimpleNamespace(
            _showtraceback=object(),
            showtraceback=object(),
            showsyntaxerror=object(),
        )
        shell_state = (
            shell._showtraceback,
            shell.showtraceback,
            shell.showsyntaxerror,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            package = types.ModuleType("pufferlib")
            config_module = types.ModuleType("pufferlib.pufferl")
            torch_module = types.ModuleType("pufferlib.torch_pufferl")
            previous_modules = _puffer_module_state()
            previous_path = list(sys.path)
            previous_process = _process_import_state()
            imported = None

            def import_module(name: str) -> types.ModuleType:
                if name == "pufferlib":
                    sys.excepthook = imported_excepthook
                    warnings.filters = [
                        ("ignore", None, Warning, None, 0),
                    ]
                    shell._showtraceback = object()
                    shell.showtraceback = object()
                    shell.showsyntaxerror = object()
                    signal.signal(
                        signal.SIGINT,
                        imported_sigint_handler,
                    )
                    return package
                if name == "pufferlib.pufferl":
                    return config_module
                if name == "pufferlib.torch_pufferl":
                    return torch_module
                raise AssertionError(f"unexpected import: {name}")

            try:
                with (
                    mock.patch.object(
                        verifier.importlib,
                        "import_module",
                        side_effect=import_module,
                    ),
                    mock.patch.object(
                        verifier,
                        "_selected_module_path",
                        return_value=root / "selected",
                    ),
                    mock.patch.object(
                        builtins,
                        "get_ipython",
                        return_value=shell,
                        create=True,
                    ),
                ):
                    _config, _torch, _extension, imported = (
                        verifier._import_selected_puffer(
                            {"root": root},
                            allow_test_extension_stub=True,
                        )
                    )

                self.assertEqual(
                    signal.getsignal(signal.SIGINT),
                    previous_process[0],
                )
                self.assertIs(sys.excepthook, previous_process[1])
                self.assertIs(warnings.filters, previous_process[2])
                self.assertEqual(warnings.filters, previous_process[3])
                self.assertIs(shell._showtraceback, shell_state[0])
                self.assertIs(shell.showtraceback, shell_state[1])
                self.assertIs(shell.showsyntaxerror, shell_state[2])
            finally:
                if imported is not None:
                    verifier._restore_puffer_modules(
                        imported["state"]["old_modules"],
                    )
                sys.path[:] = previous_path
                _replace_puffer_module_state(previous_modules)
                _restore_process_import_state(previous_process)

    def test_process_state_restores_absent_ipython_traceback_attributes(
        self,
    ) -> None:
        original = object()
        shell = types.SimpleNamespace(_showtraceback=original)
        with mock.patch.object(
            builtins,
            "get_ipython",
            return_value=shell,
            create=True,
        ):
            state = verifier._capture_selected_import_process_state()
            shell._showtraceback = object()
            shell.showtraceback = object()
            shell.showsyntaxerror = object()
            verifier._restore_selected_import_process_state(state)

        self.assertEqual(set(vars(shell)), {"_showtraceback"})
        self.assertIs(shell._showtraceback, original)

    def test_process_state_tolerates_broken_get_ipython_hook(self) -> None:
        with mock.patch.object(
            builtins,
            "get_ipython",
            side_effect=RuntimeError("broken embedding hook"),
            create=True,
        ):
            state = verifier._capture_selected_import_process_state()
            self.assertIsNone(state["ipython_shell"])
            self.assertIsNone(state["ipython_attributes"])
            verifier._restore_selected_import_process_state(state)

    def test_selected_import_restores_process_state_for_base_exceptions(
        self,
    ) -> None:
        def imported_excepthook(
            _kind: type[BaseException],
            _value: BaseException,
            _traceback: object,
        ) -> None:
            return None

        def imported_sigint_handler(_signal: int, _frame: object) -> None:
            return None

        for exception in (KeyboardInterrupt(), SystemExit(17)):
            with self.subTest(exception=type(exception).__name__), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                shell = types.SimpleNamespace(
                    _showtraceback=object(),
                    showtraceback=object(),
                    showsyntaxerror=object(),
                )
                shell_state = (
                    shell._showtraceback,
                    shell.showtraceback,
                    shell.showsyntaxerror,
                )
                sentinel = types.ModuleType("pufferlib")
                previous = _puffer_module_state()
                old_path = list(sys.path)
                old_process = _process_import_state()
                _replace_puffer_module_state({"pufferlib": sentinel})

                def interrupting_import(_name: str) -> types.ModuleType:
                    sys.excepthook = imported_excepthook
                    warnings.filters = [
                        ("ignore", None, Warning, None, 0),
                    ]
                    shell._showtraceback = object()
                    shell.showtraceback = object()
                    shell.showsyntaxerror = object()
                    signal.signal(
                        signal.SIGINT,
                        imported_sigint_handler,
                    )
                    raise exception

                try:
                    with (
                        mock.patch.object(
                            verifier.importlib,
                            "import_module",
                            side_effect=interrupting_import,
                        ),
                        mock.patch.object(
                            builtins,
                            "get_ipython",
                            return_value=shell,
                            create=True,
                        ),
                    ):
                        with self.assertRaises(type(exception)):
                            verifier._import_selected_puffer(
                                {"root": root},
                                allow_test_extension_stub=True,
                            )
                    self.assertEqual(sys.path, old_path)
                    self.assertEqual(
                        _puffer_module_state(),
                        {"pufferlib": sentinel},
                    )
                    self.assertEqual(
                        signal.getsignal(signal.SIGINT),
                        old_process[0],
                    )
                    self.assertIs(sys.excepthook, old_process[1])
                    self.assertIs(warnings.filters, old_process[2])
                    self.assertEqual(warnings.filters, old_process[3])
                    self.assertIs(shell._showtraceback, shell_state[0])
                    self.assertIs(shell.showtraceback, shell_state[1])
                    self.assertIs(shell.showsyntaxerror, shell_state[2])
                finally:
                    sys.path[:] = old_path
                    _replace_puffer_module_state(previous)
                    _restore_process_import_state(old_process)

    def test_selected_import_restores_after_post_import_base_exception(
        self,
    ) -> None:
        def imported_excepthook(
            _kind: type[BaseException],
            _value: BaseException,
            _traceback: object,
        ) -> None:
            return None

        def imported_sigint_handler(_signal: int, _frame: object) -> None:
            return None

        for exception in (KeyboardInterrupt(), SystemExit(17)):
            with self.subTest(exception=type(exception).__name__), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                sentinel = types.ModuleType("pufferlib")
                package = types.ModuleType("pufferlib")
                config_module = types.ModuleType("pufferlib.pufferl")
                torch_module = types.ModuleType("pufferlib.torch_pufferl")
                previous = _puffer_module_state()
                old_path = list(sys.path)
                old_process = _process_import_state()
                _replace_puffer_module_state({"pufferlib": sentinel})
                modules = iter((package, config_module, torch_module))

                def import_module(_name: str) -> types.ModuleType:
                    sys.excepthook = imported_excepthook
                    warnings.filters = [
                        ("ignore", None, Warning, None, 0),
                    ]
                    signal.signal(
                        signal.SIGINT,
                        imported_sigint_handler,
                    )
                    return next(modules)

                try:
                    with (
                        mock.patch.object(
                            verifier.importlib,
                            "import_module",
                            side_effect=import_module,
                        ),
                        mock.patch.object(
                            verifier,
                            "_selected_module_path",
                            side_effect=(
                                root / "pufferlib" / "__init__.py",
                                exception,
                            ),
                        ),
                    ):
                        with self.assertRaises(type(exception)):
                            verifier._import_selected_puffer(
                                {"root": root},
                                allow_test_extension_stub=True,
                            )
                    self.assertEqual(sys.path, old_path)
                    self.assertEqual(
                        _puffer_module_state(),
                        {"pufferlib": sentinel},
                    )
                    self.assertEqual(
                        signal.getsignal(signal.SIGINT),
                        old_process[0],
                    )
                    self.assertIs(sys.excepthook, old_process[1])
                    self.assertIs(warnings.filters, old_process[2])
                    self.assertEqual(warnings.filters, old_process[3])
                finally:
                    sys.path[:] = old_path
                    _replace_puffer_module_state(previous)
                    _restore_process_import_state(old_process)

    def test_selected_import_restores_when_extension_contract_interrupts(
        self,
    ) -> None:
        class InterruptingExtension:
            __file__ = "/selected/pufferlib/_C.so"

            def __init__(self, exception: BaseException) -> None:
                self.exception = exception

            @property
            def entropy_schedule_contract(self) -> str:
                raise self.exception

        for exception in (KeyboardInterrupt(), SystemExit(17)):
            with self.subTest(exception=type(exception).__name__), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                sentinel = types.ModuleType("pufferlib")
                package = types.ModuleType("pufferlib")
                package._C = InterruptingExtension(exception)
                config_module = types.ModuleType("pufferlib.pufferl")
                torch_module = types.ModuleType("pufferlib.torch_pufferl")
                previous = _puffer_module_state()
                old_path = list(sys.path)
                _replace_puffer_module_state({"pufferlib": sentinel})
                try:
                    with (
                        mock.patch.object(
                            verifier.importlib,
                            "import_module",
                            side_effect=(
                                package,
                                config_module,
                                torch_module,
                            ),
                        ),
                        mock.patch.object(
                            verifier,
                            "_selected_module_path",
                            return_value=root / "selected",
                        ),
                    ):
                        with self.assertRaises(type(exception)):
                            verifier._import_selected_puffer(
                                {"root": root},
                                allow_test_extension_stub=False,
                            )
                    self.assertEqual(sys.path, old_path)
                    self.assertEqual(
                        _puffer_module_state(),
                        {"pufferlib": sentinel},
                    )
                finally:
                    sys.path[:] = old_path
                    _replace_puffer_module_state(previous)

    def test_selected_puffer_source_contract_when_requested(self) -> None:
        raw_root = os.environ.get("PUFFER_ENTROPY_TEST_ROOT")
        if not raw_root:
            self.skipTest("PUFFER_ENTROPY_TEST_ROOT is not set")
        result = verifier.validate_selected_source(raw_root)
        self.assertEqual(result["root"], Path(raw_root).expanduser().resolve())


class TorchIntegrationTests(unittest.TestCase):
    def _command(self) -> list[str]:
        raw_root = os.environ.get("PUFFER_ENTROPY_TEST_ROOT")
        raw_python = os.environ.get("PUFFER_TORCH_TEST_PYTHON")
        if not raw_root or not raw_python:
            self.skipTest(
                "PUFFER_ENTROPY_TEST_ROOT and " "PUFFER_TORCH_TEST_PYTHON are not set"
            )
        command = [
            raw_python,
            str(Path(verifier.__file__)),
            "--puffer-root",
            raw_root,
        ]
        if os.environ.get("PUFFER_ENTROPY_ALLOW_TEST_STUB") == "1":
            command.append("--allow-test-extension-stub")
        return command

    def _run(self) -> dict[str, object]:
        result = subprocess.run(
            self._command(),
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        evidence = json.loads(result.stdout)
        verifier.validate_evidence(
            evidence,
            allow_test_stub=(os.environ.get("PUFFER_ENTROPY_ALLOW_TEST_STUB") == "1"),
        )
        return evidence

    def test_execute_restores_selected_import_process_globals(self) -> None:
        raw_root = os.environ.get("PUFFER_ENTROPY_TEST_ROOT")
        if not raw_root:
            self.skipTest("PUFFER_ENTROPY_TEST_ROOT is not set")
        before = _process_import_state()
        try:
            evidence = verifier.execute_verification(
                raw_root,
                allow_test_extension_stub=(
                    os.environ.get("PUFFER_ENTROPY_ALLOW_TEST_STUB") == "1"
                ),
            )
            self.assertEqual(
                evidence["identity"]["extension_mode"],
                (
                    "test_stub"
                    if os.environ.get("PUFFER_ENTROPY_ALLOW_TEST_STUB") == "1"
                    else "compiled"
                ),
            )
            self.assertEqual(
                signal.getsignal(signal.SIGINT),
                before[0],
            )
            self.assertIs(sys.excepthook, before[1])
            self.assertIs(warnings.filters, before[2])
            self.assertEqual(warnings.filters, before[3])
        finally:
            _restore_process_import_state(before)

    def test_execute_restores_selected_import_ipython_hooks(self) -> None:
        raw_root = os.environ.get("PUFFER_ENTROPY_TEST_ROOT")
        if not raw_root:
            self.skipTest("PUFFER_ENTROPY_TEST_ROOT is not set")
        shell = types.SimpleNamespace(
            _showtraceback=object(),
            showtraceback=object(),
            showsyntaxerror=object(),
        )
        before = (
            shell._showtraceback,
            shell.showtraceback,
            shell.showsyntaxerror,
        )
        with mock.patch.object(
            builtins,
            "get_ipython",
            return_value=shell,
            create=True,
        ):
            evidence = verifier.execute_verification(
                raw_root,
                allow_test_extension_stub=(
                    os.environ.get("PUFFER_ENTROPY_ALLOW_TEST_STUB") == "1"
                ),
            )
        self.assertEqual(
            evidence["identity"]["extension_mode"],
            (
                "test_stub"
                if os.environ.get("PUFFER_ENTROPY_ALLOW_TEST_STUB") == "1"
                else "compiled"
            ),
        )
        self.assertIs(shell._showtraceback, before[0])
        self.assertIs(shell.showtraceback, before[1])
        self.assertIs(shell.showsyntaxerror, before[2])

    def test_real_cpu_train_objective_and_repeatability(self) -> None:
        first = self._run()
        second = self._run()
        self.assertEqual(first, second)
        self.assertEqual(
            [run["case"] for run in first["runs"]],
            [
                "annealed_first",
                "annealed_middle",
                "annealed_last",
                "disabled_middle",
                "zero_middle",
            ],
        )
        for run in first["runs"]:
            self.assertEqual(
                len(run["preclip_gradients"]),
                verifier.MINIBATCHES_PER_UPDATE,
            )
            self.assertEqual(
                run["preclip_gradients"],
                run["optimizer_gradients"],
            )
        control = first["clipping_control"]
        for before, after, expected in zip(
            control["preclip_gradients"],
            control["optimizer_gradients"],
            control["expected_gradients"],
            strict=True,
        ):
            self.assertGreater(abs(before), 2.0 * abs(after))
            self.assertAlmostEqual(after, expected, places=7)

    def test_overrun_runtime_snapshot_rejects_each_pre_guard_mutation(
        self,
    ) -> None:
        raw_root = os.environ.get("PUFFER_ENTROPY_TEST_ROOT")
        raw_python = os.environ.get("PUFFER_TORCH_TEST_PYTHON")
        if not raw_root or not raw_python:
            self.skipTest(
                "PUFFER_ENTROPY_TEST_ROOT and "
                "PUFFER_TORCH_TEST_PYTHON are not set"
            )
        probe = """
import importlib
import sys

sys.path.insert(0, sys.argv[1])
import verify_torch_entropy_objective as verifier

root = sys.argv[2]
mutation = sys.argv[3]
source = verifier.validate_selected_source(root)
torch = importlib.import_module("torch")
_, torch_module, _, imported = verifier._import_selected_puffer(
    source,
    allow_test_extension_stub=True,
)
original_train = torch_module.PuffeRL.train

def mutated_train(self):
    if mutation == "values":
        self.values.add_(123.0)
    elif mutation == "cpu_rng":
        torch.rand(1)
    elif mutation == "recurrent_state":
        self.state = (torch.ones(1),)
    elif mutation == "pending_rewards":
        self.pending_rewards.add_(1.0)
    elif mutation == "optimizer_state":
        self.optimizer.state_tensor.add_(1.0)
    elif mutation == "policy_buffer":
        self.policy.qualification_buffer.add_(1.0)
    elif mutation == "policy_unregistered_attribute":
        self.policy.unregistered_counter += 1
    elif mutation == "telemetry":
        self.losses["pre_guard"] = 1.0
    elif mutation == "policy_forward":
        self.policy(self.observations.transpose(0, 1))
    else:
        raise AssertionError(f"unknown mutation: {mutation}")
    return original_train(self)

torch_module.PuffeRL.train = mutated_train
try:
    verifier._verify_overrun_guard(torch_module, torch)
except verifier.VerificationError as exc:
    if "mutated state before rejecting" not in str(exc):
        raise
else:
    raise AssertionError(f"overrun mutation was accepted: {mutation}")
finally:
    verifier._restore_puffer_modules(imported["state"]["old_modules"])
"""
        mutations = (
            "values",
            "cpu_rng",
            "recurrent_state",
            "pending_rewards",
            "optimizer_state",
            "policy_buffer",
            "policy_unregistered_attribute",
            "telemetry",
            "policy_forward",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                result = subprocess.run(
                    [
                        raw_python,
                        "-c",
                        probe,
                        str(TRAINING_DIR),
                        raw_root,
                        mutation,
                    ],
                    cwd=REPOSITORY_ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=120,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
