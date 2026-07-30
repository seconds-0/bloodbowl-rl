#!/usr/bin/env python3
"""Execute and verify PufferLib's real CPU Torch entropy objective.

The repository owns a patch against an external, pinned PufferLib checkout.
This verifier therefore accepts an explicit checkout root, validates the
relevant source contract before importing any Puffer module, and then calls
the selected checkout's real ``torch_pufferl.PuffeRL.train`` method.

The deterministic fixture isolates the PPO objective from rollout and
advantage computation. It uses the real exact-joint sampler to produce a
positive-entropy action mask, runs two minibatches per update, captures the
entropy upstream gradient and the policy parameter gradient during
``loss.backward()``, and compares the latter with an independent analytic
binary-categorical entropy derivative. The optimizer deliberately does not
mutate weights; it records the gradient after ``clip_grad_norm_`` so the
pre-clipping hook and optimizer observation prove that clipping was inactive.
A separate active-clipping control sets a small norm bound and independently
proves that the optimizer observes the clipped gradient, not the raw gradient.

Normal verification requires a built Puffer extension. The explicit
``--allow-test-extension-stub`` option exists only so an unbuilt patched source
tree can be exercised locally. Stub use is recorded in the closed evidence.
"""

from __future__ import annotations

import argparse
import ast
import builtins
from collections.abc import Mapping, Sequence
import hashlib
import importlib
import inspect
import json
import math
from pathlib import Path
import signal
import struct
import subprocess
import sys
import tempfile
import time
import types
from typing import Any
import weakref
import warnings


CONTRACT = "cosine-update-index-over-total-updates-fp32-v1"
SCHEMA_VERSION = 3
TOTAL_UPDATES = 20
MINIBATCHES_PER_UPDATE = 2
BASE_COEFFICIENT = 0.2
MIN_COEFFICIENT_RATIO = 0.1
THETA = 0.4
MAX_GRAD_NORM = 1_000_000.0
ACTIVE_CLIP_MAX_GRAD_NORM = 0.005
CLIP_NORM_EPSILON = 1.0e-6
VF_COEFFICIENT = 0.5
POINT_INDICES = (0, TOTAL_UPDATES // 2, TOTAL_UPDATES - 1)
EXPECTED_OVERRUN_ERROR = "training update exceeds configured total_updates"
EXPECTED_FAILED_UPDATE_ERROR = (
    "training object is unavailable during or after an incomplete update"
)
EXPECTED_ZERO_MINIBATCH_ERROR = (
    "training has zero minibatches per update: increase replay_ratio or "
    "batch_size, or decrease minibatch_size"
)
FAILED_UPDATE_GUARDED_METHODS = (
    "uptime",
    "sps",
    "num_params",
    "enable_entropy_gradient_qualification",
    "qualification_entropy_gradient_state",
    "set_evaluation_mode",
    "rollouts",
    "train",
    "_log",
    "log",
    "eval_log",
    "save_weights",
    "load_weights",
    "render",
)
POST_CLASS_FAILED_UPDATE_GUARDED_METHODS = (
    "set_evaluation_mode",
    "rollouts",
)
INLINE_FAILED_UPDATE_GUARDED_METHODS = tuple(
    name
    for name in FAILED_UPDATE_GUARDED_METHODS
    if name not in POST_CLASS_FAILED_UPDATE_GUARDED_METHODS
)
POST_CLASS_WRAPPER_PARAMETERS = {
    "set_evaluation_mode": ("self", "enabled"),
    "rollouts": ("self",),
}
_IPYTHON_TRACEBACK_ATTRIBUTES = (
    "_showtraceback",
    "showtraceback",
    "showsyntaxerror",
)

TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "contract",
        "identity",
        "schedule",
        "runs",
        "clipping_control",
        "gradient_oracle",
        "guards",
        "telemetry",
    }
)
IDENTITY_KEYS = frozenset(
    {
        "git_commit",
        "pufferl_sha256",
        "torch_pufferl_sha256",
        "extension_sha256",
        "extension_mode",
        "extension_contract",
    }
)
SCHEDULE_KEYS = frozenset(
    {
        "total_updates",
        "base_coefficient",
        "min_coefficient_ratio",
        "minibatches_per_update",
        "point_indices",
        "points",
    }
)
POINT_KEYS = frozenset({"update_index", "progress", "c_real", "c_applied"})
RUN_KEYS = frozenset(
    {
        "case",
        "update_index",
        "anneal_enabled",
        "base_coefficient",
        "applied_coefficient",
        "entropy_hook_coefficients",
        "preclip_gradients",
        "optimizer_gradients",
        "operation_order",
        "policy_loss",
        "value_loss",
        "entropy",
        "entropy_term",
        "total_loss",
        "minibatch_count",
        "exact_joint_positive_entropy",
    }
)
CLIPPING_CONTROL_KEYS = frozenset(
    {
        "max_grad_norm",
        "preclip_gradients",
        "optimizer_gradients",
        "expected_gradients",
        "minibatch_count",
        "operation_order",
    }
)
GRADIENT_KEYS = frozenset(
    {
        "theta",
        "binary_probability",
        "entropy_derivative",
        "enabled_delta",
        "enabled_expected",
        "disabled_delta",
        "disabled_expected",
        "scale_ratio_actual",
        "scale_ratio_expected",
        "max_grad_norm",
    }
)
GUARD_KEYS = frozenset({"overrun", "zero_minibatch", "failed_update"})
OVERRUN_KEYS = frozenset(
    {
        "error",
        "negative_epoch_rejected",
        "epoch_unchanged",
        "tail_unchanged",
        "weights_unchanged",
        "optimizer_unchanged",
        "ratio_unchanged",
        "telemetry_unchanged",
        "fixture_state_unchanged",
        "cpu_rng_unchanged",
        "cuda_rng_unchanged",
        "policy_forward_unchanged",
    }
)
ZERO_MINIBATCH_KEYS = frozenset({"error", "rejected_before_vec_access"})
FAILED_UPDATE_KEYS = frozenset(
    {
        "recoverable_preflights",
        "minibatch_abort",
        "post_loop_abort",
        "post_class_callable_contract",
        "success_clear",
    }
)
RECOVERABLE_PREFLIGHT_KEYS = frozenset(
    {
        "reset_state_nonfatal",
        "evaluation_mode_nonfatal",
        "negative_epoch_nonfatal",
        "exhausted_epoch_nonfatal",
        "missing_tail_nonfatal",
        "missing_tail_qualification_preserved",
    }
)
FAILED_UPDATE_CASE_KEYS = frozenset(
    {
        "error_type",
        "fatal_error",
        "weight_changed",
        "optimizer_changed",
        "epoch_uncommitted",
        "latch_armed",
        "retry_state_unchanged",
        "retry_rng_unchanged",
        "retry_policy_forward_unchanged",
        "retry_optimizer_unchanged",
        "uptime_rejected",
        "sps_rejected",
        "num_params_rejected",
        "qualification_enable_rejected",
        "mode_switch_rejected",
        "mode_argument_not_coerced",
        "rollout_rejected",
        "log_rejected",
        "eval_log_rejected",
        "qualification_rejected",
        "save_rejected",
        "save_created_no_file",
        "load_rejected",
        "render_rejected",
        "close_succeeded",
    }
)
POST_CLASS_CALLABLE_CONTRACT_KEYS = frozenset(
    {
        "set_evaluation_mode_signature_preserved",
        "rollouts_signature_preserved",
        "set_evaluation_mode_metadata_preserved",
        "rollouts_metadata_preserved",
        "dunder_wrapped_alias_absent",
        "standard_unwrap_is_identity",
    }
)
FAILED_UPDATE_SUCCESS_KEYS = frozenset(
    {
        "first_update_committed",
        "latch_cleared",
        "second_update_committed",
        "second_latch_cleared",
    }
)
TELEMETRY_KEYS = frozenset(
    {
        "eval_before_read",
        "train_read",
        "read_clear",
        "evaluation_mode_clear",
    }
)
EVAL_TELEMETRY_KEYS = frozenset({"loss_empty", "schedule_absent", "interval_preserved"})
TRAIN_TELEMETRY_KEYS = frozenset(
    {
        "loss_present",
        "contract",
        "first_update_index",
        "last_update_index",
        "update_count",
        "loss_minibatch_count",
        "c_applied",
    }
)
CLEAR_TELEMETRY_KEYS = frozenset({"loss_empty", "schedule_absent"})


class VerificationError(RuntimeError):
    """Raised when source, runtime behavior, or evidence violates the contract."""


def _fail(message: str) -> None:
    raise VerificationError(message)


class _TrustedTorchClipper:
    """Torch clipping objects captured before selected Puffer code executes."""

    __slots__ = (
        "nn_module",
        "utils_module",
        "clip_module",
        "clip_grad_norm",
        "clip_code",
        "clip_defaults",
        "clip_kwdefaults",
        "clip_closure",
        "clip_closure_values",
        "clip_wrapped",
        "clip_wrapped_code",
        "clip_wrapped_defaults",
        "clip_wrapped_kwdefaults",
        "clip_wrapped_closure",
        "clip_wrapped_closure_values",
    )

    def __init__(
        self,
        nn_module: Any,
        utils_module: Any,
        clip_module: Any,
        clip_grad_norm: Any,
    ) -> None:
        self.nn_module = nn_module
        self.utils_module = utils_module
        self.clip_module = clip_module
        self.clip_grad_norm = clip_grad_norm
        self.clip_code = getattr(clip_grad_norm, "__code__", None)
        self.clip_defaults = getattr(
            clip_grad_norm,
            "__defaults__",
            None,
        )
        kwdefaults = getattr(clip_grad_norm, "__kwdefaults__", None)
        self.clip_kwdefaults = (
            None if kwdefaults is None else dict(kwdefaults)
        )
        self.clip_closure = tuple(
            getattr(clip_grad_norm, "__closure__", None) or ()
        )
        self.clip_closure_values = tuple(
            cell.cell_contents for cell in self.clip_closure
        )
        self.clip_wrapped = getattr(
            clip_grad_norm,
            "__wrapped__",
            None,
        )
        self.clip_wrapped_code = getattr(
            self.clip_wrapped,
            "__code__",
            None,
        )
        self.clip_wrapped_defaults = getattr(
            self.clip_wrapped,
            "__defaults__",
            None,
        )
        wrapped_kwdefaults = getattr(
            self.clip_wrapped,
            "__kwdefaults__",
            None,
        )
        self.clip_wrapped_kwdefaults = (
            None
            if wrapped_kwdefaults is None
            else dict(wrapped_kwdefaults)
        )
        self.clip_wrapped_closure = tuple(
            getattr(self.clip_wrapped, "__closure__", None) or ()
        )
        self.clip_wrapped_closure_values = tuple(
            cell.cell_contents for cell in self.clip_wrapped_closure
        )


def _trusted_clipper_function_drifted(
    trust: _TrustedTorchClipper,
) -> bool:
    function = trust.clip_grad_norm
    closure = tuple(getattr(function, "__closure__", None) or ())
    try:
        closure_values = tuple(cell.cell_contents for cell in closure)
        wrapped_closure = tuple(
            getattr(trust.clip_wrapped, "__closure__", None) or ()
        )
        wrapped_closure_values = tuple(
            cell.cell_contents for cell in wrapped_closure
        )
    except ValueError:
        return True
    kwdefaults = getattr(function, "__kwdefaults__", None)
    wrapped_kwdefaults = getattr(
        trust.clip_wrapped,
        "__kwdefaults__",
        None,
    )
    return (
        getattr(function, "__code__", None) is not trust.clip_code
        or getattr(function, "__defaults__", None) != trust.clip_defaults
        or (
            None if kwdefaults is None else dict(kwdefaults)
        )
        != trust.clip_kwdefaults
        or len(closure) != len(trust.clip_closure)
        or any(
            actual is not expected
            for actual, expected in zip(
                closure,
                trust.clip_closure,
                strict=True,
            )
        )
        or any(
            actual is not expected
            for actual, expected in zip(
                closure_values,
                trust.clip_closure_values,
                strict=True,
            )
        )
        or getattr(function, "__wrapped__", None)
        is not trust.clip_wrapped
        or getattr(trust.clip_wrapped, "__code__", None)
        is not trust.clip_wrapped_code
        or getattr(trust.clip_wrapped, "__defaults__", None)
        != trust.clip_wrapped_defaults
        or (
            None
            if wrapped_kwdefaults is None
            else dict(wrapped_kwdefaults)
        )
        != trust.clip_wrapped_kwdefaults
        or len(wrapped_closure) != len(trust.clip_wrapped_closure)
        or any(
            actual is not expected
            for actual, expected in zip(
                wrapped_closure,
                trust.clip_wrapped_closure,
                strict=True,
            )
        )
        or any(
            actual is not expected
            for actual, expected in zip(
                wrapped_closure_values,
                trust.clip_wrapped_closure_values,
                strict=True,
            )
        )
    )


def _restore_trusted_clipper_function(
    trust: _TrustedTorchClipper,
) -> None:
    function = trust.clip_grad_norm
    if trust.clip_code is not None:
        function.__code__ = trust.clip_code
    if hasattr(function, "__defaults__"):
        function.__defaults__ = trust.clip_defaults
    if hasattr(function, "__kwdefaults__"):
        function.__kwdefaults__ = (
            None
            if trust.clip_kwdefaults is None
            else dict(trust.clip_kwdefaults)
        )
    for cell, value in zip(
        trust.clip_closure,
        trust.clip_closure_values,
        strict=True,
    ):
        cell.cell_contents = value
    if trust.clip_wrapped is None:
        if hasattr(function, "__wrapped__"):
            del function.__wrapped__
    else:
        function.__wrapped__ = trust.clip_wrapped
        if trust.clip_wrapped_code is not None:
            trust.clip_wrapped.__code__ = trust.clip_wrapped_code
        if hasattr(trust.clip_wrapped, "__defaults__"):
            trust.clip_wrapped.__defaults__ = (
                trust.clip_wrapped_defaults
            )
        if hasattr(trust.clip_wrapped, "__kwdefaults__"):
            trust.clip_wrapped.__kwdefaults__ = (
                None
                if trust.clip_wrapped_kwdefaults is None
                else dict(trust.clip_wrapped_kwdefaults)
            )
        for cell, value in zip(
            trust.clip_wrapped_closure,
            trust.clip_wrapped_closure_values,
            strict=True,
        ):
            cell.cell_contents = value


def _capture_trusted_torch_clipper(torch: Any) -> _TrustedTorchClipper:
    """Capture the real public/canonical clipper before Puffer imports."""

    nn_module = torch.nn
    utils_module = nn_module.utils
    clip_module = utils_module.clip_grad
    public = utils_module.clip_grad_norm_
    canonical = clip_module.clip_grad_norm_
    if public is not canonical or not callable(public):
        _fail("Torch clip_grad_norm_ is not the canonical library function")
    return _TrustedTorchClipper(
        nn_module,
        utils_module,
        clip_module,
        public,
    )


def _require_trusted_torch_clipper(
    torch: Any,
    trust: _TrustedTorchClipper,
) -> None:
    """Reject selected-code changes to either Torch clipping alias."""

    try:
        drifted = (
            _trusted_clipper_function_drifted(trust)
            or
            torch.nn is not trust.nn_module
            or torch.nn.utils is not trust.utils_module
            or torch.nn.utils.clip_grad is not trust.clip_module
            or torch.nn.utils.clip_grad_norm_ is not trust.clip_grad_norm
            or (
                torch.nn.utils.clip_grad.clip_grad_norm_
                is not trust.clip_grad_norm
            )
        )
    except (AttributeError, TypeError):
        drifted = True
    if drifted:
        _fail("Torch clip_grad_norm_ changed after trusted Torch capture")


def _restore_trusted_torch_clipper(
    torch: Any,
    trust: _TrustedTorchClipper,
) -> None:
    """Restore both aliases and their captured module topology."""

    _restore_trusted_clipper_function(trust)
    torch.nn = trust.nn_module
    trust.nn_module.utils = trust.utils_module
    trust.utils_module.clip_grad = trust.clip_module
    trust.utils_module.clip_grad_norm_ = trust.clip_grad_norm
    trust.clip_module.clip_grad_norm_ = trust.clip_grad_norm


_OPTIMIZER_STEP_MONITORS: weakref.WeakKeyDictionary[Any, Any] = (
    weakref.WeakKeyDictionary()
)


def _require_exact_keys(
    value: Any, expected: frozenset[str], label: str
) -> dict[str, Any]:
    if type(value) is not dict:
        _fail(f"{label} must be a raw object")
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        _fail(f"{label} has a non-closed schema " f"(missing={missing}, extra={extra})")
    return value


def _require_bool(value: Any, label: str) -> bool:
    if type(value) is not bool:
        _fail(f"{label} must be a boolean")
    return value


def _require_int(
    value: Any, label: str, *, minimum: int = 0, maximum: int = (1 << 53) - 1
) -> int:
    if type(value) is not int:
        _fail(f"{label} must be an integer")
    if value < minimum or value > maximum:
        _fail(f"{label} must be in [{minimum}, {maximum}], got {value}")
    return value


def _require_number(value: Any, label: str) -> float:
    if type(value) not in (int, float):
        _fail(f"{label} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        _fail(f"{label} must be finite")
    if not math.isfinite(result):
        _fail(f"{label} must be finite")
    return result


def _require_expected_int(value: Any, expected: int, label: str) -> int:
    result = _require_int(value, label)
    if result != expected:
        _fail(f"{label}={result!r}, expected {expected!r}")
    return result


def _close(
    actual: float,
    expected: float,
    *,
    atol: float = 2.0e-6,
    rtol: float = 2.0e-5,
) -> bool:
    return abs(actual - expected) <= atol + rtol * abs(expected)


def _assert_close(
    actual: Any,
    expected: Any,
    label: str,
    *,
    atol: float = 2.0e-6,
    rtol: float = 2.0e-5,
) -> None:
    left = _require_number(actual, label)
    right = _require_number(expected, f"{label} oracle")
    if not _close(left, right, atol=atol, rtol=rtol):
        _fail(f"{label}={left!r} differs from oracle {right!r}")


def _binary32(value: float) -> float:
    try:
        result = struct.unpack("!f", struct.pack("!f", value))[0]
    except (OverflowError, struct.error) as exc:
        _fail(f"value is not finite IEEE binary32: {exc}")
    if not math.isfinite(result):
        _fail("value rounds to non-finite IEEE binary32")
    return result


def oracle_schedule_point(
    *,
    base_coefficient: float,
    anneal_enabled: bool,
    min_coefficient_ratio: float,
    update_index: int,
    total_updates: int,
) -> dict[str, int | float]:
    """Stdlib-only binary64 schedule with one explicit binary32 boundary."""

    base = _require_number(base_coefficient, "base_coefficient")
    ratio = _require_number(min_coefficient_ratio, "min_coefficient_ratio")
    enabled = _require_bool(anneal_enabled, "anneal_enabled")
    index = _require_int(update_index, "update_index")
    updates = _require_int(total_updates, "total_updates", minimum=1)
    if base < 0.0:
        _fail("base_coefficient must be nonnegative")
    if not 0.0 <= ratio <= 1.0:
        _fail("min_coefficient_ratio must be in [0, 1]")
    progress = min(max(float(index) / float(updates), 0.0), 1.0)
    if enabled:
        floor = base * ratio
        c_real = floor + 0.5 * (base - floor) * (1.0 + math.cos(math.pi * progress))
    else:
        c_real = base
    return {
        "update_index": index,
        "progress": progress,
        "c_real": c_real,
        "c_applied": _binary32(c_real),
    }


def oracle_binary_entropy() -> float:
    """Independent binary-categorical entropy for the fixed policy fixture."""

    probability = 1.0 / (1.0 + math.exp(-THETA))
    complement = 1.0 - probability
    return -(
        probability * math.log(probability)
        + complement * math.log(complement)
    )


def _bounded_source(path: Path, root: Path, label: str) -> tuple[str, str]:
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        _fail(f"{label} resolves outside the selected Puffer root")
    if not resolved.is_file():
        _fail(f"{label} is not a regular file: {resolved}")
    if resolved.stat().st_size > 4_000_000:
        _fail(f"{label} exceeds the 4 MB source verifier limit")
    try:
        raw_source = resolved.read_bytes()
        source = raw_source.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        _fail(f"cannot read {label}: {exc}")
    return source, hashlib.sha256(raw_source).hexdigest()


def _function_names(tree: ast.AST) -> set[str]:
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _class_methods(tree: ast.AST, class_name: str) -> set[str]:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                child.name
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
    return set()


def validate_selected_source(puffer_root: str | Path) -> dict[str, Any]:
    """Validate objective integration before importing selected Puffer code."""

    root = Path(puffer_root).expanduser().resolve()
    if not root.is_dir():
        _fail(f"selected Puffer root is not a directory: {root}")
    torch_path = root / "pufferlib" / "torch_pufferl.py"
    config_path = root / "pufferlib" / "pufferl.py"
    torch_source, torch_digest = _bounded_source(
        torch_path, root, "pufferlib/torch_pufferl.py"
    )
    config_source, config_digest = _bounded_source(
        config_path, root, "pufferlib/pufferl.py"
    )
    try:
        torch_tree = ast.parse(torch_source, filename=str(torch_path))
        config_tree = ast.parse(config_source, filename=str(config_path))
    except SyntaxError as exc:
        _fail(f"selected Puffer source does not parse: {exc}")

    torch_functions = _function_names(torch_tree)
    methods = _class_methods(torch_tree, "PuffeRL")
    required_functions = {
        "entropy_schedule_point",
        "apply_action_mask",
        "sample_joint_logits",
        "sample_logits",
    }
    missing_functions = sorted(required_functions - torch_functions)
    required_methods = {
        "_prepare_train_log",
        "_format_train_log",
        "close",
        *FAILED_UPDATE_GUARDED_METHODS,
    }
    missing_methods = sorted(required_methods - methods)
    if missing_functions or missing_methods:
        _fail(
            "selected Torch source lacks required objective surfaces "
            f"(functions={missing_functions}, methods={missing_methods})"
        )
    if "validate_entropy_schedule_config" not in _function_names(config_tree):
        _fail("selected config source lacks entropy schedule validation")

    required_fragments = (
        f'ENTROPY_SCHEDULE_CONTRACT = "{CONTRACT}"',
        "current_ent_coef = torch.tensor(",
        "entropy_term = -current_ent_coef * entropy_loss",
        "loss = pg_loss + config['vf_coef']*v_loss + entropy_term",
        "loss.backward()",
        "clip_grad_norm_",
        "self.optimizer.step()",
        "self._training_failed = False",
        "self._training_failed = True",
        EXPECTED_FAILED_UPDATE_ERROR,
        "losses['entropy_coefficient'] += current_ent_coef",
        "losses['entropy_term'] += entropy_term",
        "losses['total_loss'] += loss",
        "self._train_log_interval = None",
    )
    missing_fragments = [
        fragment for fragment in required_fragments if fragment not in torch_source
    ]
    if missing_fragments:
        _fail(
            "selected Torch source lacks required entropy objective text: "
            + ", ".join(repr(value) for value in missing_fragments)
        )
    puffer_class = None
    for node in torch_tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "PuffeRL":
            puffer_class = node
            break
    if puffer_class is None:
        _fail("selected Torch source lacks PuffeRL")
    method_nodes = {
        child.name: child
        for child in puffer_class.body
        if isinstance(child, ast.FunctionDef)
    }
    train_node = method_nodes.get("train")
    if train_node is None:
        _fail("selected Torch source lacks PuffeRL.train")

    def is_self_attribute(node: ast.AST, attribute: str) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and node.attr == attribute
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        )

    def is_exact_runtime_error(
        statement: ast.stmt,
        message: str,
    ) -> bool:
        exception = statement.exc if isinstance(statement, ast.Raise) else None
        return (
            isinstance(exception, ast.Call)
            and isinstance(exception.func, ast.Name)
            and exception.func.id == "RuntimeError"
            and len(exception.args) == 1
            and not exception.keywords
            and isinstance(exception.args[0], ast.Constant)
            and exception.args[0].value == message
            and statement.cause is None
        )

    def is_failed_update_guard(statement: ast.stmt) -> bool:
        return (
            isinstance(statement, ast.If)
            and not statement.orelse
            and len(statement.body) == 1
            and is_self_attribute(statement.test, "_training_failed")
            and is_exact_runtime_error(
                statement.body[0],
                EXPECTED_FAILED_UPDATE_ERROR,
            )
        )

    def is_training_failed_assignment(
        statement: ast.stmt,
        value: bool,
    ) -> bool:
        return (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and is_self_attribute(
                statement.targets[0],
                "_training_failed",
            )
            and isinstance(statement.value, ast.Constant)
            and statement.value.value is value
        )

    if not train_node.body or not is_failed_update_guard(train_node.body[0]):
        _fail(
            "selected PuffeRL.train must reject a failed or in-flight "
            "update as its first statement"
        )

    for method_name in INLINE_FAILED_UPDATE_GUARDED_METHODS:
        method = method_nodes.get(method_name)
        if (
            method is None
            or not method.body
            or not is_failed_update_guard(method.body[0])
        ):
            _fail(
                f"selected PuffeRL.{method_name} must reject a failed or "
                "in-flight update as its first statement"
            )

    expected_wrapper_tail = ast.parse(
        f"""
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
            raise RuntimeError({EXPECTED_FAILED_UPDATE_ERROR!r})
        return method(self, enabled)
    return _copy_public_callable_metadata(guarded, method)

def _reject_incomplete_update_rollouts(method):
    def guarded(self):
        if self._training_failed:
            raise RuntimeError({EXPECTED_FAILED_UPDATE_ERROR!r})
        return method(self)
    return _copy_public_callable_metadata(guarded, method)

PuffeRL.set_evaluation_mode = (
    _reject_incomplete_update_set_evaluation_mode(
        PuffeRL.set_evaluation_mode
    )
)
PuffeRL.rollouts = _reject_incomplete_update_rollouts(PuffeRL.rollouts)
"""
    ).body
    actual_wrapper_tail = torch_tree.body[-len(expected_wrapper_tail) :]
    expected_wrapper_shape = [
        ast.dump(node, include_attributes=False)
        for node in expected_wrapper_tail
    ]
    actual_wrapper_shape = [
        ast.dump(node, include_attributes=False)
        for node in actual_wrapper_tail
    ]
    if actual_wrapper_shape != expected_wrapper_shape:
        _fail(
            "selected Torch source must end with the exact post-class "
            "failed-update wrapper contract for PuffeRL.set_evaluation_mode "
            "and PuffeRL.rollouts"
        )
    wrapper_function_names = {
        "_copy_public_callable_metadata",
        "_reject_incomplete_update_set_evaluation_mode",
        "_reject_incomplete_update_rollouts",
    }
    for function_name in wrapper_function_names:
        definitions = [
            node
            for node in torch_tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == function_name
        ]
        if len(definitions) != 1:
            _fail(
                "selected Torch source must define exactly one post-class "
                f"wrapper helper {function_name}"
            )
    for method_name in POST_CLASS_FAILED_UPDATE_GUARDED_METHODS:
        stores = [
            node
            for node in ast.walk(torch_tree)
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.ctx, ast.Store)
                and node.attr == method_name
                and isinstance(node.value, ast.Name)
                and node.value.id == "PuffeRL"
            )
        ]
        if len(stores) != 1:
            _fail(
                "selected Torch source must store exactly once to "
                f"PuffeRL.{method_name}"
            )
    if any(
        (
            isinstance(node, ast.Attribute)
            and node.attr == "__wrapped__"
        )
        or (
            isinstance(node, ast.Constant)
            and node.value == "__wrapped__"
        )
        for node in ast.walk(torch_tree)
    ):
        _fail(
            "selected Torch source must not expose an unguarded method "
            "through __wrapped__"
        )

    init_node = method_nodes.get("__init__")
    if init_node is None:
        _fail("selected PuffeRL lacks __init__")
    init_false = [
        statement
        for statement in init_node.body
        if is_training_failed_assignment(statement, False)
    ]
    if len(init_false) != 1:
        _fail(
            "selected PuffeRL.__init__ must initialize exactly one "
            "_training_failed false latch"
        )

    def is_public_mode_guard(statement: ast.stmt) -> bool:
        if (
            not isinstance(statement, ast.If)
            or statement.orelse
            or len(statement.body) != 1
            or not is_exact_runtime_error(
                statement.body[0],
                "training requires reset_state=True and evaluation_mode=False",
            )
        ):
            return False
        test = statement.test
        return (
            isinstance(test, ast.BoolOp)
            and isinstance(test.op, ast.Or)
            and len(test.values) == 2
            and isinstance(test.values[0], ast.UnaryOp)
            and isinstance(test.values[0].op, ast.Not)
            and is_self_attribute(test.values[0].operand, "reset_state")
            and is_self_attribute(test.values[1], "evaluation_mode")
        )

    def is_profile_binding(statement: ast.stmt) -> bool:
        return (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == "prof"
            and is_self_attribute(statement.value, "profile")
        )

    def is_local_losses_binding(statement: ast.stmt) -> bool:
        return (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == "losses"
            and isinstance(statement.value, ast.Call)
            and not statement.value.keywords
            and len(statement.value.args) == 1
            and isinstance(statement.value.func, ast.Name)
            and statement.value.func.id == "defaultdict"
            and isinstance(statement.value.args[0], ast.Name)
            and statement.value.args[0].id == "float"
        )

    def is_overrun_guard(statement: ast.stmt) -> bool:
        if (
            not isinstance(statement, ast.If)
            or statement.orelse
            or len(statement.body) != 1
            or not is_exact_runtime_error(
                statement.body[0],
                EXPECTED_OVERRUN_ERROR,
            )
        ):
            return False
        test = statement.test
        if (
            not isinstance(test, ast.BoolOp)
            or not isinstance(test.op, ast.Or)
            or len(test.values) != 2
        ):
            return False
        lower, upper = test.values
        return (
            isinstance(lower, ast.Compare)
            and is_self_attribute(lower.left, "epoch")
            and len(lower.ops) == 1
            and isinstance(lower.ops[0], ast.Lt)
            and len(lower.comparators) == 1
            and isinstance(lower.comparators[0], ast.Constant)
            and type(lower.comparators[0].value) is int
            and lower.comparators[0].value == 0
            and isinstance(upper, ast.Compare)
            and is_self_attribute(upper.left, "epoch")
            and len(upper.ops) == 1
            and isinstance(upper.ops[0], ast.GtE)
            and len(upper.comparators) == 1
            and is_self_attribute(upper.comparators[0], "total_epochs")
        )

    overrun_guards = [
        statement
        for statement in train_node.body
        if is_overrun_guard(statement)
    ]
    if len(overrun_guards) != 1:
        _fail(
            "selected PuffeRL.train must contain exactly one direct "
            "public epoch bounds guard"
        )
    overrun_index = train_node.body.index(overrun_guards[0])
    safe_prelude = train_node.body[:overrun_index]
    if (
        len(safe_prelude) != 4
        or not is_failed_update_guard(safe_prelude[0])
        or not is_public_mode_guard(safe_prelude[1])
        or not is_profile_binding(safe_prelude[2])
        or not is_local_losses_binding(safe_prelude[3])
    ):
        _fail(
            "selected PuffeRL.train overrun guard must precede all stateful "
            "training work and trainer mutation; its prelude must be the "
            "exact fatal and read-only public-mode guards followed by "
            "adjacent local profile and empty loss-accumulator bindings"
        )

    def is_fresh_tail_guard(statement: ast.stmt) -> bool:
        if (
            not isinstance(statement, ast.If)
            or statement.orelse
            or len(statement.body) != 1
            or not is_exact_runtime_error(
                statement.body[0],
                "training requires one fresh tail record",
            )
        ):
            return False
        return (
            isinstance(statement.test, ast.UnaryOp)
            and isinstance(statement.test.op, ast.Not)
            and is_self_attribute(statement.test.operand, "tail_valid")
        )

    tail_guards = [
        statement
        for statement in train_node.body
        if is_fresh_tail_guard(statement)
    ]
    armed = [
        statement
        for statement in train_node.body
        if is_training_failed_assignment(statement, True)
    ]
    cleared = [
        statement
        for statement in train_node.body
        if is_training_failed_assignment(statement, False)
    ]
    if len(tail_guards) != 1 or len(armed) != 1 or len(cleared) != 1:
        _fail(
            "selected PuffeRL.train must contain one fresh-tail guard, "
            "one latch arm, and one latch clear"
        )
    tail_index = train_node.body.index(tail_guards[0])
    arm_index = train_node.body.index(armed[0])
    clear_index = train_node.body.index(cleared[0])
    if arm_index != tail_index + 1:
        _fail(
            "selected PuffeRL.train must arm its fatal latch immediately "
            "after recoverable mode/epoch/tail preflights"
        )
    losses_binding_index = train_node.body.index(safe_prelude[3])
    if any(
        isinstance(node, ast.Name) and node.id == "losses"
        for statement in train_node.body[losses_binding_index + 1 : arm_index]
        for node in ast.walk(statement)
    ):
        _fail(
            "selected PuffeRL.train must not read or mutate its local loss "
            "accumulator before the tail preflight and fatal latch arm"
        )
    if clear_index != len(train_node.body) - 1:
        _fail(
            "selected PuffeRL.train must clear its fatal latch only as "
            "the final successful publication statement"
        )

    class TrainExecutionCallVisitor(ast.NodeVisitor):
        """Visit the train body without treating nested definitions as live."""

        def __init__(self) -> None:
            self.calls: list[ast.Call] = []

        def visit_Call(self, node: ast.Call) -> None:
            self.calls.append(node)
            self.generic_visit(node)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            if node is train_node:
                self.generic_visit(node)

        def visit_AsyncFunctionDef(
            self,
            node: ast.AsyncFunctionDef,
        ) -> None:
            if node is train_node:
                self.generic_visit(node)

        def visit_Lambda(self, node: ast.Lambda) -> None:
            del node

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            del node

    call_visitor = TrainExecutionCallVisitor()
    call_visitor.visit(train_node)
    calls = call_visitor.calls

    def is_loss_backward(call: ast.Call) -> bool:
        function = call.func
        return (
            isinstance(function, ast.Attribute)
            and function.attr == "backward"
            and isinstance(function.value, ast.Name)
            and function.value.id == "loss"
        )

    def dotted_name(node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = dotted_name(node.value)
            return f"{parent}.{node.attr}" if parent is not None else None
        return None

    def is_clip_grad_norm(call: ast.Call) -> bool:
        return dotted_name(call.func) == "torch.nn.utils.clip_grad_norm_"

    def is_policy_parameters_call(node: ast.expr) -> bool:
        return (
            isinstance(node, ast.Call)
            and not node.args
            and not node.keywords
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "parameters"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "policy"
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "self"
        )

    def is_max_grad_norm_lookup(node: ast.expr) -> bool:
        return (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "config"
            and isinstance(node.slice, ast.Constant)
            and node.slice.value == "max_grad_norm"
        )

    def is_optimizer_step(call: ast.Call) -> bool:
        function = call.func
        receiver = function.value if isinstance(function, ast.Attribute) else None
        return (
            isinstance(function, ast.Attribute)
            and function.attr == "step"
            and isinstance(receiver, ast.Attribute)
            and receiver.attr == "optimizer"
            and isinstance(receiver.value, ast.Name)
            and receiver.value.id == "self"
        )

    def unique_call_position(predicate: Any, label: str) -> tuple[int, int]:
        matches = [call for call in calls if predicate(call)]
        if len(matches) != 1:
            _fail(
                "selected PuffeRL.train must contain exactly one "
                f"{label} call, found {len(matches)}"
            )
        return (matches[0].lineno, matches[0].col_offset)

    backward_at = unique_call_position(is_loss_backward, "loss.backward")
    clip_at = unique_call_position(is_clip_grad_norm, "clip_grad_norm_")
    step_at = unique_call_position(is_optimizer_step, "self.optimizer.step")
    clip_call = next(call for call in calls if is_clip_grad_norm(call))
    if (
        len(clip_call.args) != 2
        or clip_call.keywords
        or not is_policy_parameters_call(clip_call.args[0])
        or not is_max_grad_norm_lookup(clip_call.args[1])
    ):
        _fail(
            "selected PuffeRL.train must call clip_grad_norm_ with "
            "exactly self.policy.parameters() and "
            "config['max_grad_norm']"
        )

    parents = {
        child: parent
        for parent in ast.walk(train_node)
        for child in ast.iter_child_nodes(parent)
    }

    def containing_statement(call_position: tuple[int, int]) -> ast.stmt:
        call = next(
            candidate
            for candidate in calls
            if (candidate.lineno, candidate.col_offset) == call_position
        )
        node: ast.AST = call
        while not isinstance(node, ast.stmt):
            node = parents[node]
        return node

    def statement_list_location(
        statement: ast.stmt,
    ) -> tuple[ast.AST, str, int] | None:
        for owner in ast.walk(train_node):
            for field, value in ast.iter_fields(owner):
                if isinstance(value, list):
                    for index, candidate in enumerate(value):
                        if candidate is statement:
                            return owner, field, index
        return None

    statements = [
        containing_statement(position)
        for position in (backward_at, clip_at, step_at)
    ]
    matched_calls = [
        next(
            call
            for call in calls
            if (call.lineno, call.col_offset) == position
        )
        for position in (backward_at, clip_at, step_at)
    ]
    if any(
        not isinstance(statement, ast.Expr) or statement.value is not call
        for statement, call in zip(
            statements,
            matched_calls,
            strict=True,
        )
    ):
        _fail(
            "selected PuffeRL.train must use loss.backward(), "
            "clip_grad_norm_, and optimizer.step as unconditional "
            "standalone expression statements"
        )
    statement_locations = [
        statement_list_location(statement) for statement in statements
    ]

    block_owner = (
        statement_locations[0][0]
        if all(location is not None for location in statement_locations)
        else None
    )
    direct_minibatch_loop = (
        isinstance(block_owner, ast.For)
        and block_owner in train_node.body
        and isinstance(block_owner.target, ast.Name)
        and block_owner.target.id == "mb"
        and isinstance(block_owner.iter, ast.Call)
        and isinstance(block_owner.iter.func, ast.Name)
        and block_owner.iter.func.id == "range"
        and len(block_owner.iter.args) == 1
        and not block_owner.iter.keywords
        and isinstance(block_owner.iter.args[0], ast.Name)
        and block_owner.iter.args[0].id == "num_minibatches"
        and all(
            location is not None
            and location[0] is block_owner
            and location[1] == "body"
            for location in statement_locations
        )
    )
    same_executable_block = (
        all(location is not None for location in statement_locations)
        and statement_locations[0][2]
        < statement_locations[1][2]
        < statement_locations[2][2]
    )
    if not direct_minibatch_loop:
        _fail(
            "selected PuffeRL.train must place loss.backward(), "
            "clip_grad_norm_, and optimizer.step directly in its "
            "for mb in range(num_minibatches) loop"
        )
    step_statement_index = statement_locations[2][2]

    def nested_definition_between(
        node: ast.AST,
        ancestor: ast.AST,
    ) -> bool:
        current = node
        while current is not ancestor:
            current = parents.get(current)
            if current is None:
                return True
            if current is ancestor:
                return False
            if isinstance(
                current,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.Lambda,
                    ast.ClassDef,
                ),
            ):
                return True
        return False

    train_prefix = train_node.body[: train_node.body.index(block_owner)]
    early_function_exit = any(
        isinstance(node, (ast.Return, ast.Yield, ast.YieldFrom))
        and not nested_definition_between(node, train_node)
        for statement in train_prefix
        for node in ast.walk(statement)
    )
    loop_prefix = block_owner.body[: step_statement_index + 1]
    skipping_loop_control = False
    for statement in loop_prefix:
        for node in ast.walk(statement):
            if isinstance(node, (ast.Return, ast.Yield, ast.YieldFrom)):
                if not nested_definition_between(node, block_owner):
                    skipping_loop_control = True
                    break
            if not isinstance(node, (ast.Break, ast.Continue)):
                continue
            if nested_definition_between(node, block_owner):
                continue
            enclosing_loop = parents.get(node)
            while enclosing_loop is not None and not isinstance(
                enclosing_loop,
                (ast.For, ast.AsyncFor, ast.While),
            ):
                enclosing_loop = parents.get(enclosing_loop)
            if enclosing_loop is block_owner:
                skipping_loop_control = True
                break
        if skipping_loop_control:
            break
    if early_function_exit or skipping_loop_control:
        _fail(
            "selected PuffeRL.train contains control flow that can skip "
            "the unconditional minibatch backward/clip/step sequence"
        )
    if not (backward_at < clip_at < step_at and same_executable_block):
        _fail(
            "selected PuffeRL.train must order loss.backward(), "
            "clip_grad_norm_, then optimizer.step in one executable block"
        )

    marker = f'm.attr("entropy_schedule_contract") = "{CONTRACT}";'
    binding_sources = (
        root / "src" / "bindings_cpu.cpp",
        root / "src" / "bindings.cu",
    )
    for binding_path in binding_sources:
        binding_source, _binding_digest = _bounded_source(
            binding_path, root, str(binding_path.relative_to(root))
        )
        if marker not in binding_source:
            _fail(
                f"{binding_path.relative_to(root)} lacks the compiled "
                "entropy schedule contract marker"
            )

    return {
        "root": root,
        "torch_path": torch_path.resolve(),
        "config_path": config_path.resolve(),
        "torch_source": torch_source,
        "config_source": config_source,
        "torch_sha256": torch_digest,
        "config_sha256": config_digest,
    }


def _git_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD^{commit}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _fail(f"cannot resolve selected Puffer git commit: {exc}")
    commit = result.stdout.strip()
    if len(commit) not in (40, 64) or any(
        char not in "0123456789abcdef" for char in commit
    ):
        _fail("selected Puffer git commit is not lowercase hexadecimal")
    return commit


def _selected_module_path(module: Any, root: Path, label: str) -> Path:
    raw_path = getattr(module, "__file__", None)
    if not isinstance(raw_path, str):
        _fail(f"{label} has no source path")
    path = Path(raw_path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        _fail(f"{label} imported from outside selected root: {path}")
    return path


def _make_extension_stub() -> types.ModuleType:
    stub = types.ModuleType("pufferlib._C")
    stub.precision_bytes = 4
    stub.gpu = False
    stub.entropy_schedule_contract = CONTRACT
    stub.env_name = None
    stub.get_utilization = lambda _gpu_id: {}
    return stub


def _capture_selected_import_process_state() -> dict[str, Any]:
    ipython_shell = None
    ipython_attributes = None
    get_ipython = getattr(builtins, "get_ipython", None)
    if callable(get_ipython):
        try:
            ipython_shell = get_ipython()
        except Exception:
            ipython_shell = None
    if ipython_shell is not None:
        namespace = getattr(ipython_shell, "__dict__", None)
        if isinstance(namespace, dict):
            ipython_attributes = {
                name: (name in namespace, namespace.get(name))
                for name in _IPYTHON_TRACEBACK_ATTRIBUTES
            }
        else:
            ipython_attributes = {
                name: (
                    hasattr(ipython_shell, name),
                    getattr(ipython_shell, name, None),
                )
                for name in _IPYTHON_TRACEBACK_ATTRIBUTES
            }
    return {
        "sigint_handler": signal.getsignal(signal.SIGINT),
        "sys_excepthook": sys.excepthook,
        "warning_filters_object": warnings.filters,
        "warning_filters": list(warnings.filters),
        "ipython_shell": ipython_shell,
        "ipython_attributes": ipython_attributes,
    }


def _restore_selected_import_process_state(
    state: Mapping[str, Any],
) -> None:
    ipython_shell = state["ipython_shell"]
    ipython_attributes = state["ipython_attributes"]
    if ipython_shell is not None and ipython_attributes is not None:
        namespace = getattr(ipython_shell, "__dict__", None)
        if isinstance(namespace, dict):
            for name, (present, value) in ipython_attributes.items():
                if present:
                    namespace[name] = value
                else:
                    namespace.pop(name, None)
        else:
            for name, (present, value) in ipython_attributes.items():
                if present:
                    setattr(ipython_shell, name, value)
                elif hasattr(ipython_shell, name):
                    delattr(ipython_shell, name)
    filter_object = state["warning_filters_object"]
    filter_object[:] = state["warning_filters"]
    warnings.filters = filter_object
    sys.excepthook = state["sys_excepthook"]
    old_sigint = state["sigint_handler"]
    current_sigint = signal.getsignal(signal.SIGINT)
    if current_sigint is not old_sigint and current_sigint != old_sigint:
        signal.signal(signal.SIGINT, old_sigint)


def _import_selected_puffer(
    source: Mapping[str, Any], *, allow_test_extension_stub: bool
) -> tuple[Any, Any, Any, dict[str, Any]]:
    """Import selected modules after source validation and return old state."""

    root = source["root"]
    old_path = list(sys.path)
    process_state = _capture_selected_import_process_state()
    old_modules = {
        key: value
        for key, value in sys.modules.items()
        if key == "pufferlib" or key.startswith("pufferlib.")
    }
    for key in list(old_modules):
        sys.modules.pop(key, None)
    sys.path.insert(0, str(root))
    try:
        package = importlib.import_module("pufferlib")
        _selected_module_path(package, root, "pufferlib package")
        if allow_test_extension_stub:
            extension = _make_extension_stub()
            package._C = extension
            sys.modules["pufferlib._C"] = extension
        config_module = importlib.import_module("pufferlib.pufferl")
        torch_module = importlib.import_module("pufferlib.torch_pufferl")
        extension = getattr(package, "_C", None)
    except BaseException as exc:
        for key in list(sys.modules):
            if key == "pufferlib" or key.startswith("pufferlib."):
                sys.modules.pop(key, None)
        sys.modules.update(old_modules)
        sys.path[:] = old_path
        _restore_selected_import_process_state(process_state)
        if not isinstance(exc, Exception):
            raise
        _fail(
            "selected Puffer import failed after source validation "
            f"({type(exc).__name__}: {exc})"
        )
    sys.path[:] = old_path

    try:
        _selected_module_path(config_module, root, "pufferlib.pufferl")
        _selected_module_path(torch_module, root, "pufferlib.torch_pufferl")
        if not allow_test_extension_stub:
            _selected_module_path(extension, root, "pufferlib._C")
        extension_contract = getattr(
            extension,
            "entropy_schedule_contract",
            None,
        )
        if extension_contract != CONTRACT:
            _fail(
                "compiled extension entropy_schedule_contract is absent "
                "or wrong"
            )
    except BaseException as exc:
        _restore_puffer_modules(old_modules)
        _restore_selected_import_process_state(process_state)
        if not isinstance(exc, Exception):
            raise
        if isinstance(exc, VerificationError):
            raise
        _fail(
            "selected Puffer post-import validation failed "
            f"({type(exc).__name__}: {exc})"
        )
    _restore_selected_import_process_state(process_state)
    state = {
        "old_modules": old_modules,
        "process_state": process_state,
    }
    mode = "test_stub" if allow_test_extension_stub else "compiled"
    return (
        config_module,
        torch_module,
        extension,
        {
            "state": state,
            "mode": mode,
        },
    )


def _restore_puffer_modules(old_modules: Mapping[str, Any]) -> None:
    for key in list(sys.modules):
        if key == "pufferlib" or key.startswith("pufferlib."):
            sys.modules.pop(key, None)
    sys.modules.update(old_modules)


class _RecordingOptimizer:
    """Observe post-clipping gradients without mutating policy weights."""

    def __init__(
        self,
        parameter: Any,
    ) -> None:
        self.parameter = parameter
        self.param_groups = [{"lr": 0.0}]
        self.step_gradients: list[float] = []
        self.step_calls = 0
        self.zero_calls = 0
        self.state_tensor = parameter.detach().new_tensor([0.375])

    def step(self) -> None:
        self.step_calls += 1
        if self.parameter.grad is None:
            _fail("optimizer observed a missing policy gradient")
        monitor = _OPTIMIZER_STEP_MONITORS.get(self)
        if monitor is None:
            _fail("optimizer step lacks a verifier-owned clip monitor")
        monitor()
        self.step_gradients.append(float(self.parameter.grad.detach().item()))

    def zero_grad(self) -> None:
        self.zero_calls += 1
        self.parameter.grad = None

    def state_dict(self) -> dict[str, Any]:
        return {
            "state_tensor": self.state_tensor.detach().clone(),
            "param_groups": [dict(group) for group in self.param_groups],
            "step_gradients": list(self.step_gradients),
            "step_calls": self.step_calls,
            "zero_calls": self.zero_calls,
        }


class _InjectedTrainingAbort(BaseException):
    """A non-Exception sentinel proving the latch covers BaseException."""


class _MutatingOptimizer(_RecordingOptimizer):
    """Mutate parameter and optimizer state, optionally aborting on one step."""

    def __init__(
        self,
        parameter: Any,
        *,
        abort_on_step: int | None,
    ) -> None:
        super().__init__(parameter)
        self.abort_on_step = abort_on_step

    def step(self) -> None:
        self.step_calls += 1
        if self.parameter.grad is None:
            _fail("mutating optimizer observed a missing policy gradient")
        self.step_gradients.append(
            float(self.parameter.grad.detach().item())
        )
        self.parameter.detach().add_(0.125)
        self.state_tensor.add_(1.0)
        if self.abort_on_step == self.step_calls:
            raise _InjectedTrainingAbort(
                f"injected abort at optimizer step {self.step_calls}"
            )


class _NoopVec:
    def __init__(self) -> None:
        self.reset_calls = 0
        self.render_calls = 0
        self.close_calls = 0

    def reset(self) -> None:
        self.reset_calls += 1

    def render(self, _env_id: int) -> None:
        self.render_calls += 1

    def close(self) -> None:
        self.close_calls += 1


def _install_deterministic_advantage(torch_module: Any, torch: Any) -> Any:
    original = torch_module.compute_puff_advantage

    def deterministic_advantage(
        values: Any,
        rewards: Any,
        terminals: Any,
        ratio: Any,
        tail_values: Any,
        tail_rewards: Any,
        tail_terminals: Any,
        advantages: Any,
        gamma: float,
        gae_lambda: float,
        vtrace_rho_clip: float,
        vtrace_c_clip: float,
    ) -> Any:
        del (
            rewards,
            terminals,
            ratio,
            tail_values,
            tail_rewards,
            tail_terminals,
            gamma,
            gae_lambda,
            vtrace_rho_clip,
            vtrace_c_clip,
        )
        if tuple(values.shape) != (1, 2):
            _fail(
                "objective fixture received an unexpected advantage shape "
                f"{tuple(values.shape)!r}"
            )
        fixture = torch.tensor([[-1.0, 1.0]], dtype=values.dtype, device=values.device)
        advantages.copy_(fixture)
        return advantages

    torch_module.compute_puff_advantage = deterministic_advantage
    return original


def _make_policy(torch: Any) -> Any:
    class BinaryPolicy(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.theta = torch.nn.Parameter(torch.tensor(THETA, dtype=torch.float32))
            self.register_buffer(
                "qualification_buffer",
                torch.tensor([0.625], dtype=torch.float32),
            )
            self.unregistered_counter = 0

        def forward(self, observations: Any) -> tuple[list[Any], Any]:
            batch = observations.reshape(-1, observations.shape[-1]).shape[0]
            score = self.theta.expand(batch)
            logits = torch.stack((score, torch.zeros_like(score)), dim=-1)
            value = torch.zeros(
                (batch, 1), dtype=torch.float32, device=observations.device
            )
            return [logits], value

    return BinaryPolicy()


def _make_trainer(
    torch_module: Any,
    torch: Any,
    *,
    update_index: int,
    base_coefficient: float,
    anneal_enabled: bool,
    max_grad_norm: float = MAX_GRAD_NORM,
    operation_events: list[str] | None = None,
) -> tuple[Any, Any, _RecordingOptimizer, float]:
    policy = _make_policy(torch)
    horizon = 2
    total_agents = 1
    observations = torch.zeros((horizon, total_agents, 1), dtype=torch.float32)

    with torch.no_grad():
        behavior_logits, _ = policy(observations.transpose(0, 1))
        packed = torch.tensor([0, 1, 0, 1], dtype=torch.int32)
        offsets = torch.tensor([0, 2], dtype=torch.int32)
        counts = torch.tensor([2, 2], dtype=torch.int32)
        torch.manual_seed(730_021)
        actions, logprobs, behavior_entropy, masks = torch_module.sample_joint_logits(
            behavior_logits, packed, offsets, counts, [2]
        )
    exact_joint_entropy = float(behavior_entropy.mean().item())
    _assert_close(
        exact_joint_entropy,
        oracle_binary_entropy(),
        "exact-joint fixture entropy",
        atol=2.0e-6,
        rtol=2.0e-5,
    )
    if not bool(masks.bool().all().item()):
        _fail("exact-joint fixture did not preserve both legal actions")

    trainer = torch_module.PuffeRL.__new__(torch_module.PuffeRL)
    trainer.profile = torch_module.Profile(gpu=False)
    trainer.reset_state = True
    trainer.evaluation_mode = False
    trainer.device = "cpu"
    trainer.epoch = update_index
    trainer.total_epochs = TOTAL_UPDATES
    trainer.entropy_config = {
        "base_coefficient": base_coefficient,
        "anneal_enabled": anneal_enabled,
        "min_coefficient_ratio": MIN_COEFFICIENT_RATIO,
    }
    trainer.config = {
        "horizon": horizon,
        "minibatch_size": horizon * total_agents,
        "prio_beta0": 0.4,
        "prio_alpha": 0.0,
        "clip_coef": 0.2,
        "vf_clip_coef": 0.2,
        "learning_rate": 0.0,
        "anneal_lr": False,
        "min_lr_ratio": 0.1,
        "gamma": 0.99,
        "gae_lambda": 0.95,
        "vtrace_rho_clip": 1.0,
        "vtrace_c_clip": 1.0,
        "vf_coef": VF_COEFFICIENT,
        "max_grad_norm": max_grad_norm,
    }
    trainer.total_agents = total_agents
    trainer.batch_size = horizon * total_agents
    trainer.minibatch_segments = 1
    trainer.num_minibatches = MINIBATCHES_PER_UPDATE
    trainer.ratio = torch.ones((total_agents, horizon), dtype=torch.float32)
    trainer.observations = observations
    trainer.actions = actions.reshape(horizon, total_agents, 1).to(dtype=torch.float32)
    trainer.values = torch.zeros((horizon, total_agents), dtype=torch.float32)
    trainer.logprobs = logprobs.reshape(horizon, total_agents)
    trainer.rewards = torch.zeros((horizon, total_agents), dtype=torch.float32)
    trainer.terminals = torch.zeros((horizon, total_agents), dtype=torch.float32)
    trainer.action_masks = masks.reshape(horizon, total_agents, 2).to(dtype=torch.uint8)
    trainer.mask_size = 2
    trainer.act_sizes_list = [2]
    trainer.tail_values = torch.zeros(total_agents, dtype=torch.float32)
    trainer.tail_rewards = torch.zeros(total_agents, dtype=torch.float32)
    trainer.tail_terminals = torch.zeros(total_agents, dtype=torch.float32)
    trainer.tail_valid = True
    trainer.policy = policy
    trainer.model_size = sum(
        parameter.numel() for parameter in policy.parameters()
    )
    optimizer = _RecordingOptimizer(policy.theta)
    if operation_events is not None:
        def observe_optimizer_step() -> None:
            if not operation_events or operation_events[-1] != "clip":
                _fail(
                    "optimizer step did not immediately follow the real "
                    "gradient clip"
                )
            operation_events.append("step")

        _OPTIMIZER_STEP_MONITORS[optimizer] = observe_optimizer_step
    trainer.optimizer = optimizer
    trainer.losses = {}
    trainer._train_log_interval = None
    # The production qualification capture is opt-in. This verifier observes
    # gradients with local hooks and must leave that heavier surface disabled.
    trainer._entropy_gradient_qualification_enabled = False
    trainer._entropy_gradient_qualification_state = None
    trainer._training_failed = False
    trainer.state = ()
    trainer.pending_rewards = torch.zeros(total_agents)
    trainer.pending_terminals = torch.zeros(total_agents)
    trainer._vec = _NoopVec()
    trainer.gpu = False
    trainer.world_size = 1
    trainer.global_step = 0
    trainer.last_log_step = 0
    trainer.last_log_time = time.time()
    trainer.start_time = time.time()
    trainer.args = {"gpu_id": 0}
    trainer.env_logs = {}
    return trainer, policy, optimizer, exact_joint_entropy


def _expected_operation_order() -> list[str]:
    return [
        event
        for _ in range(MINIBATCHES_PER_UPDATE)
        for event in ("backward", "clip", "step")
    ]


def _verify_operation_order(events: Any, label: str) -> list[str]:
    expected = _expected_operation_order()
    if type(events) is not list or events != expected:
        _fail(
            f"{label} operation order differs: "
            f"observed={events!r}, expected={expected!r}"
        )
    return events


def _install_clip_monitor(
    torch: Any,
    trust: _TrustedTorchClipper,
    operation_events: list[str],
    *,
    expected_parameters: tuple[Any, ...],
    expected_max_grad_norm: float,
) -> Any:
    """Wrap and delegate to Torch's real clipper while binding live order."""

    _require_trusted_torch_clipper(torch, trust)

    def monitored_clip_grad_norm_(
        parameters: Any,
        max_norm: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if _trusted_clipper_function_drifted(trust):
            _fail(
                "trusted Torch clip_grad_norm_ function changed "
                "during selected train"
            )
        if args or kwargs:
            _fail(
                "real gradient clip received unexpected norm options"
            )
        actual_parameters = tuple(parameters)
        if (
            len(actual_parameters) != len(expected_parameters)
            or any(
                actual is not expected
                for actual, expected in zip(
                    actual_parameters,
                    expected_parameters,
                    strict=True,
                )
            )
        ):
            _fail("real gradient clip received the wrong policy parameters")
        _assert_close(
            max_norm,
            expected_max_grad_norm,
            "real gradient clip max norm",
            atol=0.0,
            rtol=0.0,
        )
        if not operation_events or operation_events[-1] != "backward":
            _fail(
                "real gradient clip did not immediately follow "
                "loss.backward"
            )
        result = trust.clip_grad_norm(
            actual_parameters,
            max_norm,
        )
        operation_events.append("clip")
        return result

    torch.nn.utils.clip_grad_norm_ = monitored_clip_grad_norm_
    return monitored_clip_grad_norm_


def _restore_clip_monitor(
    torch: Any,
    trust: _TrustedTorchClipper,
    monitored_clip_grad_norm: Any,
) -> bool:
    """Restore both aliases and report any selected-code drift."""

    try:
        drifted = (
            torch.nn is not trust.nn_module
            or torch.nn.utils is not trust.utils_module
            or torch.nn.utils.clip_grad is not trust.clip_module
            or (
                torch.nn.utils.clip_grad_norm_
                is not monitored_clip_grad_norm
            )
            or (
                torch.nn.utils.clip_grad.clip_grad_norm_
                is not trust.clip_grad_norm
            )
        )
    except (AttributeError, TypeError):
        drifted = True
    _restore_trusted_torch_clipper(torch, trust)
    return drifted


def _execute_run(
    torch_module: Any,
    torch: Any,
    trust: _TrustedTorchClipper,
    *,
    case: str,
    update_index: int,
    base_coefficient: float,
    anneal_enabled: bool,
) -> tuple[dict[str, Any], Any]:
    torch.manual_seed(902_177)
    operation_events: list[str] = []
    trainer, policy, optimizer, exact_joint_entropy = _make_trainer(
        torch_module,
        torch,
        update_index=update_index,
        base_coefficient=base_coefficient,
        anneal_enabled=anneal_enabled,
        operation_events=operation_events,
    )
    preclip_gradients: list[float] = []
    entropy_hook_coefficients: list[float] = []
    def record_parameter_gradient(gradient: Any) -> Any:
        preclip_gradients.append(float(gradient.detach().item()))
        operation_events.append("backward")
        return gradient

    parameter_hook = policy.theta.register_hook(record_parameter_gradient)
    original_sample_logits = torch_module.sample_logits
    monitored_clip_grad_norm = _install_clip_monitor(
        torch,
        trust,
        operation_events,
        expected_parameters=(policy.theta,),
        expected_max_grad_norm=MAX_GRAD_NORM,
    )

    def monitored_sample_logits(logits: Any, action: Any = None) -> Any:
        sampled_action, logprob, entropy = original_sample_logits(logits, action=action)
        if torch.is_grad_enabled() and entropy.requires_grad:
            count = entropy.numel()

            def record_entropy_gradient(gradient: Any) -> Any:
                coefficients = -gradient.detach().reshape(-1) * float(count)
                reference = coefficients[0]
                if not bool(
                    torch.allclose(
                        coefficients,
                        reference.expand_as(coefficients),
                        atol=1.0e-7,
                        rtol=1.0e-6,
                    )
                ):
                    _fail(
                        "one minibatch used a non-constant entropy "
                        "coefficient across objective elements"
                    )
                entropy_hook_coefficients.append(float(reference.item()))
                return gradient

            entropy.register_hook(record_entropy_gradient)
        return sampled_action, logprob, entropy

    torch_module.sample_logits = monitored_sample_logits
    clipper_drifted = False
    try:
        trainer.train()
    finally:
        torch_module.sample_logits = original_sample_logits
        clipper_drifted = _restore_clip_monitor(
            torch,
            trust,
            monitored_clip_grad_norm,
        )
        _OPTIMIZER_STEP_MONITORS.pop(optimizer, None)
        parameter_hook.remove()
    if clipper_drifted:
        _fail("Torch clip_grad_norm_ changed during selected train")

    if len(preclip_gradients) != MINIBATCHES_PER_UPDATE:
        _fail(
            "parameter backward hook count differs from minibatch count "
            f"({len(preclip_gradients)} != {MINIBATCHES_PER_UPDATE})"
        )
    if len(entropy_hook_coefficients) != MINIBATCHES_PER_UPDATE:
        _fail(
            "entropy backward hook count differs from minibatch count "
            f"({len(entropy_hook_coefficients)} != "
            f"{MINIBATCHES_PER_UPDATE})"
        )
    if optimizer.step_calls != MINIBATCHES_PER_UPDATE:
        _fail("optimizer step count differs from minibatch count")
    if optimizer.zero_calls != MINIBATCHES_PER_UPDATE:
        _fail("optimizer zero_grad count differs from minibatch count")
    _verify_operation_order(operation_events, case)
    for index, (before, after) in enumerate(
        zip(preclip_gradients, optimizer.step_gradients, strict=True)
    ):
        _assert_close(
            after,
            before,
            f"{case} minibatch {index} post-clip gradient",
            atol=2.0e-7,
            rtol=2.0e-6,
        )
        if abs(before) >= MAX_GRAD_NORM:
            _fail(f"{case} minibatch {index} could have clipped")

    oracle_point = oracle_schedule_point(
        base_coefficient=base_coefficient,
        anneal_enabled=anneal_enabled,
        min_coefficient_ratio=MIN_COEFFICIENT_RATIO,
        update_index=update_index,
        total_updates=TOTAL_UPDATES,
    )
    applied = float(oracle_point["c_applied"])
    for index, observed in enumerate(entropy_hook_coefficients):
        _assert_close(
            observed,
            applied,
            f"{case} minibatch {index} entropy coefficient",
            atol=2.0e-7,
            rtol=2.0e-6,
        )

    losses = trainer.losses
    required_losses = (
        "policy_loss",
        "value_loss",
        "entropy",
        "entropy_coefficient",
        "entropy_term",
        "total_loss",
    )
    for field in required_losses:
        if field not in losses:
            _fail(f"{case} training losses omit {field!r}")
    entropy = _require_number(losses["entropy"], f"{case}.entropy")
    entropy_term = _require_number(losses["entropy_term"], f"{case}.entropy_term")
    policy_loss = _require_number(losses["policy_loss"], f"{case}.policy_loss")
    value_loss = _require_number(losses["value_loss"], f"{case}.value_loss")
    total_loss = _require_number(losses["total_loss"], f"{case}.total_loss")
    _assert_close(
        entropy,
        oracle_binary_entropy(),
        f"{case}.entropy analytic value",
        atol=2.0e-6,
        rtol=2.0e-5,
    )
    _assert_close(
        losses["entropy_coefficient"],
        applied,
        f"{case}.entropy_coefficient",
        atol=2.0e-7,
        rtol=2.0e-6,
    )
    _assert_close(
        entropy_term,
        -applied * entropy,
        f"{case}.entropy_term decomposition",
    )
    _assert_close(
        total_loss,
        policy_loss + trainer.config["vf_coef"] * value_loss + entropy_term,
        f"{case}.total_loss decomposition",
    )
    if entropy <= 0.0:
        _fail(f"{case} entropy is not positive")
    if applied > 0.0 and entropy_term >= 0.0:
        _fail(f"{case} signed entropy term is not negative")
    if applied == 0.0 and entropy_term != 0.0:
        _fail(f"{case} zero-base entropy term is not zero")
    if trainer.epoch != update_index + 1:
        _fail(f"{case} successful train did not commit exactly one epoch")
    if trainer.tail_valid is not False:
        _fail(f"{case} successful train did not consume the tail token")

    record = {
        "case": case,
        "update_index": update_index,
        "anneal_enabled": anneal_enabled,
        "base_coefficient": base_coefficient,
        "applied_coefficient": applied,
        "entropy_hook_coefficients": entropy_hook_coefficients,
        "preclip_gradients": preclip_gradients,
        "optimizer_gradients": optimizer.step_gradients,
        "operation_order": operation_events,
        "policy_loss": policy_loss,
        "value_loss": value_loss,
        "entropy": entropy,
        "entropy_term": entropy_term,
        "total_loss": total_loss,
        "minibatch_count": MINIBATCHES_PER_UPDATE,
        "exact_joint_positive_entropy": exact_joint_entropy,
    }
    return record, trainer


def _scalar_clip_oracle(gradient: float, max_grad_norm: float) -> float:
    """Independent scalar specialization of Torch's p=2 norm clipping."""

    raw = _require_number(gradient, "active clipping raw gradient")
    limit = _require_number(max_grad_norm, "active clipping max_grad_norm")
    if limit <= 0.0:
        _fail("active clipping max_grad_norm must be positive")
    scale = min(1.0, limit / (abs(raw) + CLIP_NORM_EPSILON))
    return raw * scale


def _execute_active_clipping_control(
    torch_module: Any,
    torch: Any,
    trust: _TrustedTorchClipper,
) -> dict[str, Any]:
    """Prove the real train path clips before the optimizer observes gradients."""

    torch.manual_seed(902_177)
    operation_events: list[str] = []
    trainer, policy, optimizer, _ = _make_trainer(
        torch_module,
        torch,
        update_index=TOTAL_UPDATES // 2,
        base_coefficient=BASE_COEFFICIENT,
        anneal_enabled=False,
        max_grad_norm=ACTIVE_CLIP_MAX_GRAD_NORM,
        operation_events=operation_events,
    )
    preclip_gradients: list[float] = []

    def record_parameter_gradient(gradient: Any) -> Any:
        preclip_gradients.append(float(gradient.detach().item()))
        operation_events.append("backward")
        return gradient

    parameter_hook = policy.theta.register_hook(record_parameter_gradient)
    monitored_clip_grad_norm = _install_clip_monitor(
        torch,
        trust,
        operation_events,
        expected_parameters=(policy.theta,),
        expected_max_grad_norm=ACTIVE_CLIP_MAX_GRAD_NORM,
    )
    clipper_drifted = False
    try:
        trainer.train()
    finally:
        clipper_drifted = _restore_clip_monitor(
            torch,
            trust,
            monitored_clip_grad_norm,
        )
        _OPTIMIZER_STEP_MONITORS.pop(optimizer, None)
        parameter_hook.remove()
    if clipper_drifted:
        _fail("Torch clip_grad_norm_ changed during selected train")

    if len(preclip_gradients) != MINIBATCHES_PER_UPDATE:
        _fail("active clipping backward-hook count differs from minibatches")
    if optimizer.step_calls != MINIBATCHES_PER_UPDATE:
        _fail("active clipping optimizer step count differs from minibatches")
    if optimizer.zero_calls != MINIBATCHES_PER_UPDATE:
        _fail("active clipping optimizer zero count differs from minibatches")
    if len(optimizer.step_gradients) != MINIBATCHES_PER_UPDATE:
        _fail("active clipping optimizer gradient count differs from minibatches")
    _verify_operation_order(operation_events, "active clipping")

    expected_gradients = []
    for index, (before, observed) in enumerate(
        zip(
            preclip_gradients,
            optimizer.step_gradients,
            strict=True,
        )
    ):
        if abs(before) <= 2.0 * ACTIVE_CLIP_MAX_GRAD_NORM:
            _fail(
                f"active clipping minibatch {index} lacks a nonvacuous "
                "pre-clip gradient"
            )
        expected = _scalar_clip_oracle(
            before,
            ACTIVE_CLIP_MAX_GRAD_NORM,
        )
        _assert_close(
            observed,
            expected,
            f"active clipping minibatch {index} optimizer gradient",
            atol=2.0e-7,
            rtol=2.0e-5,
        )
        if _close(observed, before, atol=2.0e-7, rtol=2.0e-6):
            _fail(
                f"active clipping minibatch {index} did not change "
                "the optimizer-observed gradient"
            )
        expected_gradients.append(expected)
    return {
        "max_grad_norm": ACTIVE_CLIP_MAX_GRAD_NORM,
        "preclip_gradients": preclip_gradients,
        "optimizer_gradients": optimizer.step_gradients,
        "expected_gradients": expected_gradients,
        "minibatch_count": MINIBATCHES_PER_UPDATE,
        "operation_order": operation_events,
    }


def _verify_gradient_oracle(runs: Mapping[str, Mapping[str, Any]]) -> dict[str, float]:
    enabled = runs["annealed_middle"]
    disabled = runs["disabled_middle"]
    zero = runs["zero_middle"]
    probability = 1.0 / (1.0 + math.exp(-THETA))
    entropy_derivative = -THETA * probability * (1.0 - probability)
    enabled_expected = -float(enabled["applied_coefficient"]) * entropy_derivative
    disabled_expected = -float(disabled["applied_coefficient"]) * entropy_derivative
    enabled_deltas = []
    disabled_deltas = []
    for minibatch in range(MINIBATCHES_PER_UPDATE):
        baseline = float(zero["preclip_gradients"][minibatch])
        enabled_delta = float(enabled["preclip_gradients"][minibatch]) - baseline
        disabled_delta = float(disabled["preclip_gradients"][minibatch]) - baseline
        _assert_close(
            enabled_delta,
            enabled_expected,
            f"enabled minibatch {minibatch} entropy gradient delta",
            atol=5.0e-7,
            rtol=2.0e-5,
        )
        _assert_close(
            disabled_delta,
            disabled_expected,
            f"disabled minibatch {minibatch} entropy gradient delta",
            atol=5.0e-7,
            rtol=2.0e-5,
        )
        if enabled_delta <= 0.0 or disabled_delta <= 0.0:
            _fail("entropy gradient has the wrong sign")
        enabled_deltas.append(enabled_delta)
        disabled_deltas.append(disabled_delta)
    enabled_delta = sum(enabled_deltas) / len(enabled_deltas)
    disabled_delta = sum(disabled_deltas) / len(disabled_deltas)
    scale_ratio_actual = disabled_delta / enabled_delta
    scale_ratio_expected = float(disabled["applied_coefficient"]) / float(
        enabled["applied_coefficient"]
    )
    _assert_close(
        scale_ratio_actual,
        scale_ratio_expected,
        "enabled/disabled entropy gradient scale ratio",
        atol=2.0e-5,
        rtol=2.0e-4,
    )
    return {
        "theta": THETA,
        "binary_probability": probability,
        "entropy_derivative": entropy_derivative,
        "enabled_delta": enabled_delta,
        "enabled_expected": enabled_expected,
        "disabled_delta": disabled_delta,
        "disabled_expected": disabled_expected,
        "scale_ratio_actual": scale_ratio_actual,
        "scale_ratio_expected": scale_ratio_expected,
        "max_grad_norm": MAX_GRAD_NORM,
    }


def _snapshot_mutable_value(
    value: Any,
    torch: Any,
    *,
    active_objects: set[int] | None = None,
) -> Any:
    """Create an equality-safe structural snapshot of the CPU fixture state."""

    active = set() if active_objects is None else active_objects
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        return {"float_hex": value.hex()}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {
            "bytes_sha256": hashlib.sha256(bytes(value)).hexdigest(),
            "bytes_length": len(value),
        }
    if torch.is_tensor(value):
        detached = value.detach().cpu().contiguous()
        gradient = value.grad if bool(value.is_leaf) else None
        return {
            "tensor_dtype": str(detached.dtype),
            "tensor_shape": list(detached.shape),
            "tensor_values": detached.reshape(-1).tolist(),
            "requires_grad": bool(value.requires_grad),
            "gradient": (
                None
                if gradient is None
                else _snapshot_mutable_value(
                    gradient,
                    torch,
                    active_objects=active,
                )
            ),
        }
    if isinstance(value, Mapping):
        pairs = [
            (
                _snapshot_mutable_value(key, torch, active_objects=active),
                _snapshot_mutable_value(item, torch, active_objects=active),
            )
            for key, item in value.items()
        ]
        pairs.sort(
            key=lambda pair: json.dumps(
                pair[0],
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return {"mapping": pairs}
    if isinstance(value, (list, tuple)):
        return {
            "sequence_type": type(value).__name__,
            "items": [
                _snapshot_mutable_value(item, torch, active_objects=active)
                for item in value
            ],
        }
    if isinstance(value, (set, frozenset)):
        items = [
            _snapshot_mutable_value(item, torch, active_objects=active)
            for item in value
        ]
        items.sort(
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return {
            "set_type": type(value).__name__,
            "items": items,
        }
    if isinstance(value, torch.nn.Module):
        object_id = id(value)
        if object_id in active:
            return {
                "cycle_type": (
                    f"{type(value).__module__}.{type(value).__qualname__}"
                )
            }
        active.add(object_id)
        try:
            parameters = {
                name: _snapshot_mutable_value(
                    parameter,
                    torch,
                    active_objects=active,
                )
                for name, parameter in value.named_parameters()
            }
            buffers = {
                name: _snapshot_mutable_value(
                    buffer,
                    torch,
                    active_objects=active,
                )
                for name, buffer in value.named_buffers()
            }
            children = {
                name: _snapshot_mutable_value(
                    child,
                    torch,
                    active_objects=active,
                )
                for name, child in value.named_children()
            }
            attributes = {
                str(name): _snapshot_mutable_value(
                    item,
                    torch,
                    active_objects=active,
                )
                for name, item in sorted(
                    vars(value).items(),
                    key=lambda pair: str(pair[0]),
                )
                if name not in {"_parameters", "_buffers", "_modules"}
            }
        finally:
            active.remove(object_id)
        return {
            "module_type": (
                f"{type(value).__module__}.{type(value).__qualname__}"
            ),
            "training": bool(value.training),
            "parameters": parameters,
            "buffers": buffers,
            "children": children,
            "attributes": attributes,
        }
    if (
        hasattr(value, "dtype")
        and hasattr(value, "shape")
        and callable(getattr(value, "tobytes", None))
    ):
        payload = value.tobytes(order="C")
        return {
            "array_type": (
                f"{type(value).__module__}.{type(value).__qualname__}"
            ),
            "array_dtype": str(value.dtype),
            "array_shape": list(value.shape),
            "array_sha256": hashlib.sha256(payload).hexdigest(),
        }
    object_id = id(value)
    if object_id in active:
        return {
            "cycle_type": (
                f"{type(value).__module__}.{type(value).__qualname__}"
            )
        }
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, Mapping):
        active.add(object_id)
        try:
            state = {
                str(name): _snapshot_mutable_value(
                    item,
                    torch,
                    active_objects=active,
                )
                for name, item in sorted(
                    attributes.items(),
                    key=lambda pair: str(pair[0]),
                )
            }
        finally:
            active.remove(object_id)
        state_dict = getattr(value, "state_dict", None)
        if callable(state_dict):
            state["__state_dict__"] = _snapshot_mutable_value(
                state_dict(),
                torch,
                active_objects=active,
            )
        return {
            "object_type": (
                f"{type(value).__module__}.{type(value).__qualname__}"
            ),
            "attributes": state,
        }
    return {
        "opaque_type": (
            f"{type(value).__module__}.{type(value).__qualname__}"
        )
    }


def _snapshot_overrun_fixture(trainer: Any, torch: Any) -> Any:
    return _snapshot_mutable_value(
        vars(trainer),
        torch,
    )


def _cuda_rng_snapshot(torch: Any) -> tuple[Any, ...]:
    cuda = getattr(torch, "cuda", None)
    is_initialized = getattr(cuda, "is_initialized", None)
    if cuda is None or not callable(is_initialized) or not is_initialized():
        return ()
    get_states = getattr(cuda, "get_rng_state_all", None)
    if not callable(get_states):
        _fail("initialized Torch CUDA runtime lacks get_rng_state_all")
    return tuple(state.detach().cpu().clone() for state in get_states())


def _rng_snapshots_equal(
    before: Sequence[Any],
    after: Sequence[Any],
    torch: Any,
) -> bool:
    return len(before) == len(after) and all(
        bool(torch.equal(left, right))
        for left, right in zip(before, after, strict=True)
    )


def _verify_epoch_guard_at(
    torch_module: Any,
    torch: Any,
    *,
    update_index: int,
    label: str,
) -> dict[str, Any]:
    trainer, policy, optimizer, _ = _make_trainer(
        torch_module,
        torch,
        update_index=update_index,
        base_coefficient=BASE_COEFFICIENT,
        anneal_enabled=True,
    )
    trainer.ratio.fill_(7.0)
    trainer.losses = {"sentinel": 11.0}
    trainer._train_log_interval = {"sentinel": 13}
    policy_forward_calls = 0

    def record_policy_forward(
        _module: Any,
        _arguments: Any,
        _output: Any,
    ) -> None:
        nonlocal policy_forward_calls
        policy_forward_calls += 1

    forward_hook = policy.register_forward_hook(record_policy_forward)
    before_epoch = trainer.epoch
    before_tail = trainer.tail_valid
    before_weight = policy.theta.detach().clone()
    before_ratio = trainer.ratio.detach().clone()
    before_losses = dict(trainer.losses)
    before_interval = dict(trainer._train_log_interval)
    before_optimizer = (optimizer.step_calls, optimizer.zero_calls)
    before_fixture = _snapshot_overrun_fixture(trainer, torch)
    before_cpu_rng = torch.get_rng_state().detach().cpu().clone()
    before_cuda_rng = _cuda_rng_snapshot(torch)
    before_forward_calls = policy_forward_calls
    try:
        try:
            trainer.train()
        except RuntimeError as exc:
            error = str(exc)
        else:
            _fail(f"Torch train accepted {label}")
    finally:
        after_fixture = _snapshot_overrun_fixture(trainer, torch)
        after_cpu_rng = torch.get_rng_state().detach().cpu().clone()
        after_cuda_rng = _cuda_rng_snapshot(torch)
        after_forward_calls = policy_forward_calls
        forward_hook.remove()
    if error != EXPECTED_OVERRUN_ERROR:
        _fail(f"Torch {label} guard returned the wrong error: {error!r}")
    result = {
        "error": error,
        "epoch_unchanged": trainer.epoch == before_epoch,
        "tail_unchanged": trainer.tail_valid is before_tail,
        "weights_unchanged": bool(torch.equal(policy.theta.detach(), before_weight)),
        "optimizer_unchanged": (
            optimizer.step_calls,
            optimizer.zero_calls,
        )
        == before_optimizer,
        "ratio_unchanged": bool(torch.equal(trainer.ratio, before_ratio)),
        "telemetry_unchanged": (
            trainer.losses == before_losses
            and trainer._train_log_interval == before_interval
        ),
        "fixture_state_unchanged": after_fixture == before_fixture,
        "cpu_rng_unchanged": bool(torch.equal(after_cpu_rng, before_cpu_rng)),
        "cuda_rng_unchanged": _rng_snapshots_equal(
            before_cuda_rng,
            after_cuda_rng,
            torch,
        ),
        "policy_forward_unchanged": (
            after_forward_calls == before_forward_calls
        ),
    }
    if not all(value for key, value in result.items() if key != "error"):
        _fail(f"Torch {label} guard mutated state before rejecting")
    return result


def _verify_overrun_guard(torch_module: Any, torch: Any) -> dict[str, Any]:
    upper = _verify_epoch_guard_at(
        torch_module,
        torch,
        update_index=TOTAL_UPDATES,
        label="upper-bound epoch",
    )
    lower = _verify_epoch_guard_at(
        torch_module,
        torch,
        update_index=-1,
        label="negative epoch",
    )
    upper["negative_epoch_rejected"] = (
        lower["error"] == EXPECTED_OVERRUN_ERROR
        and all(
            value
            for key, value in lower.items()
            if key != "error"
        )
    )
    if upper["negative_epoch_rejected"] is not True:
        _fail("Torch negative epoch guard is incomplete")
    return upper


def _expect_failed_update_rejection(
    operation: Any,
    label: str,
) -> str:
    try:
        operation()
    except RuntimeError as exc:
        error = str(exc)
    except BaseException as exc:
        _fail(
            f"{label} raised {type(exc).__name__} instead of the fixed "
            "failed-update error"
        )
    else:
        _fail(f"{label} accepted a failed or in-flight trainer")
    if error != EXPECTED_FAILED_UPDATE_ERROR:
        _fail(f"{label} returned the wrong failed-update error: {error!r}")
    return error


def _verify_post_class_wrapper_runtime_contract(
    torch_module: Any,
) -> dict[str, bool]:
    methods = {
        name: vars(torch_module.PuffeRL).get(name)
        for name in POST_CLASS_FAILED_UPDATE_GUARDED_METHODS
    }

    def metadata_preserved(name: str) -> bool:
        method = methods[name]
        return (
            isinstance(method, types.FunctionType)
            and method.__name__ == name
            and method.__qualname__ == f"PuffeRL.{name}"
            and method.__module__ == torch_module.__name__
        )

    def signature_preserved(name: str) -> bool:
        method = methods[name]
        if not isinstance(method, types.FunctionType):
            return False
        direct = inspect.signature(method, follow_wrapped=False)
        standard = inspect.signature(method)
        if direct != standard:
            return False
        parameters = tuple(direct.parameters.values())
        return (
            tuple(parameter.name for parameter in parameters)
            == POST_CLASS_WRAPPER_PARAMETERS[name]
            and all(
                parameter.kind
                is inspect.Parameter.POSITIONAL_OR_KEYWORD
                and parameter.default is inspect.Parameter.empty
                and parameter.annotation is inspect.Parameter.empty
                for parameter in parameters
            )
            and direct.return_annotation is inspect.Signature.empty
        )

    dunder_wrapped_alias_absent = all(
        isinstance(method, types.FunctionType)
        and not hasattr(method, "__wrapped__")
        and "__wrapped__" not in method.__dict__
        for method in methods.values()
    )
    standard_unwrap_is_identity = all(
        isinstance(method, types.FunctionType)
        and inspect.unwrap(method) is method
        for method in methods.values()
    )
    result = {
        "set_evaluation_mode_signature_preserved": (
            signature_preserved("set_evaluation_mode")
        ),
        "rollouts_signature_preserved": signature_preserved("rollouts"),
        "set_evaluation_mode_metadata_preserved": (
            metadata_preserved("set_evaluation_mode")
        ),
        "rollouts_metadata_preserved": metadata_preserved("rollouts"),
        "dunder_wrapped_alias_absent": dunder_wrapped_alias_absent,
        "standard_unwrap_is_identity": standard_unwrap_is_identity,
    }
    if not all(result.values()):
        _fail(
            "Torch post-class failed-update wrappers do not preserve their "
            "public callable contract or publish __wrapped__"
        )
    return result


def _verify_recoverable_training_preflights(
    torch_module: Any,
    torch: Any,
) -> dict[str, bool]:
    mode_error = (
        "training requires reset_state=True and evaluation_mode=False"
    )
    cases = (
        ("reset_state_nonfatal", "reset_state", False, mode_error),
        ("evaluation_mode_nonfatal", "evaluation_mode", True, mode_error),
        (
            "negative_epoch_nonfatal",
            "epoch",
            -1,
            EXPECTED_OVERRUN_ERROR,
        ),
        (
            "exhausted_epoch_nonfatal",
            "epoch",
            TOTAL_UPDATES,
            EXPECTED_OVERRUN_ERROR,
        ),
        (
            "missing_tail_nonfatal",
            "tail_valid",
            False,
            "training requires one fresh tail record",
        ),
    )
    results: dict[str, bool] = {}
    missing_tail_state_preserved = False
    for label, attribute, value, expected_error in cases:
        trainer, _policy, _optimizer, _ = _make_trainer(
            torch_module,
            torch,
            update_index=0,
            base_coefficient=BASE_COEFFICIENT,
            anneal_enabled=True,
        )
        setattr(trainer, attribute, value)
        qualification_sentinel = {"sentinel": 947}
        trainer._entropy_gradient_qualification_enabled = True
        trainer._entropy_gradient_qualification_state = (
            qualification_sentinel
        )
        before = _snapshot_overrun_fixture(trainer, torch)
        before_cpu_rng = torch.get_rng_state().detach().cpu().clone()
        before_cuda_rng = _cuda_rng_snapshot(torch)
        try:
            trainer.train()
        except RuntimeError as exc:
            error = str(exc)
        except BaseException as exc:
            _fail(
                f"Torch {label} raised unexpected "
                f"{type(exc).__name__}: {exc}"
            )
        else:
            _fail(f"Torch {label} preflight was accepted")
        after = _snapshot_overrun_fixture(trainer, torch)
        after_cpu_rng = torch.get_rng_state().detach().cpu().clone()
        after_cuda_rng = _cuda_rng_snapshot(torch)
        result = (
            error == expected_error
            and trainer._training_failed is False
            and after == before
            and bool(torch.equal(after_cpu_rng, before_cpu_rng))
            and _rng_snapshots_equal(
                before_cuda_rng,
                after_cuda_rng,
                torch,
            )
        )
        if not result:
            _fail(
                f"Torch {label} preflight was not recoverable and "
                "mutation-free"
            )
        results[label] = True
        if label == "missing_tail_nonfatal":
            missing_tail_state_preserved = (
                trainer._entropy_gradient_qualification_state
                is qualification_sentinel
            )
    results["missing_tail_qualification_preserved"] = (
        missing_tail_state_preserved
    )
    if not missing_tail_state_preserved:
        _fail(
            "Torch missing-tail preflight cleared qualification evidence"
        )
    return results


def _verify_failed_update_case(
    torch_module: Any,
    torch: Any,
    *,
    post_loop_abort: bool,
) -> dict[str, Any]:
    update_index = TOTAL_UPDATES - 1 if post_loop_abort else 7
    trainer, policy, _original_optimizer, _ = _make_trainer(
        torch_module,
        torch,
        update_index=update_index,
        base_coefficient=BASE_COEFFICIENT,
        anneal_enabled=True,
    )
    optimizer = _MutatingOptimizer(
        policy.theta,
        abort_on_step=None if post_loop_abort else 2,
    )
    trainer.optimizer = optimizer
    if post_loop_abort:
        def abort_prepare_log(
            _self: Any,
            _losses: Any,
            _entropy_point: Any,
        ) -> Any:
            raise _InjectedTrainingAbort(
                "injected post-loop telemetry abort"
            )

        trainer._prepare_train_log = types.MethodType(
            abort_prepare_log,
            trainer,
        )

    initial_weight = policy.theta.detach().clone()
    initial_optimizer_state = optimizer.state_tensor.detach().clone()
    initial_epoch = trainer.epoch
    try:
        trainer.train()
    except _InjectedTrainingAbort as exc:
        error_type = type(exc).__name__
    except BaseException as exc:
        _fail(
            "failed-update fixture propagated the wrong exception: "
            f"{type(exc).__name__}: {exc}"
        )
    else:
        _fail("failed-update fixture did not propagate BaseException")

    epoch_uncommitted = trainer.epoch == initial_epoch
    latch_armed = trainer._training_failed is True
    weight_changed = not bool(
        torch.equal(policy.theta.detach(), initial_weight)
    )
    optimizer_changed = (
        optimizer.step_calls > 0
        and not bool(
            torch.equal(
                optimizer.state_tensor.detach(),
                initial_optimizer_state,
            )
        )
    )
    if not all(
        (
            epoch_uncommitted,
            latch_armed,
            weight_changed,
            optimizer_changed,
        )
    ):
        _fail(
            "failed-update fixture did not prove partial mutation plus "
            "an armed, uncommitted transaction"
        )

    # Deliberately make every weaker preflight invalid. Fatal state must be
    # authoritative even after a final-index, post-loop failure.
    trainer.evaluation_mode = False
    trainer.epoch = trainer.total_epochs
    trainer.tail_valid = False
    trainer.num_minibatches = 1
    trainer.global_step = 1
    policy_forward_calls = 0

    def record_policy_forward(
        _module: Any,
        _arguments: Any,
        _output: Any,
    ) -> None:
        nonlocal policy_forward_calls
        policy_forward_calls += 1

    hook = policy.register_forward_hook(record_policy_forward)
    before_retry = _snapshot_overrun_fixture(trainer, torch)
    before_cpu_rng = torch.get_rng_state().detach().cpu().clone()
    before_cuda_rng = _cuda_rng_snapshot(torch)
    before_forward_calls = policy_forward_calls
    before_optimizer = (
        optimizer.step_calls,
        optimizer.zero_calls,
        optimizer.state_tensor.detach().clone(),
    )
    temporary = tempfile.TemporaryDirectory()
    temporary_path = Path(temporary.name)
    load_checkpoint = temporary_path / "load.pt"
    poisoned_checkpoint = temporary_path / "poisoned.pt"
    replacement_state = {
        key: torch.full_like(value, 9.25)
        for key, value in policy.state_dict().items()
    }
    torch.save(replacement_state, load_checkpoint)
    try:
        fatal_error = _expect_failed_update_rejection(
            trainer.train,
            "Torch train retry",
        )
        uptime_error = _expect_failed_update_rejection(
            lambda: trainer.uptime,
            "Torch uptime",
        )
        sps_error = _expect_failed_update_rejection(
            lambda: trainer.sps,
            "Torch sps",
        )
        num_params_error = _expect_failed_update_rejection(
            trainer.num_params,
            "Torch num_params",
        )
        qualification_enable_error = _expect_failed_update_rejection(
            trainer.enable_entropy_gradient_qualification,
            "Torch entropy-gradient qualification enable",
        )
        same_mode_error = _expect_failed_update_rejection(
            lambda: trainer.set_evaluation_mode(False),
            "Torch same-value evaluation-mode switch",
        )
        mode_switch_error = _expect_failed_update_rejection(
            lambda: trainer.set_evaluation_mode(True),
            "Torch evaluation-mode switch",
        )

        class ExplosiveTruthiness:
            def __init__(self) -> None:
                self.bool_calls = 0

            def __bool__(self) -> bool:
                self.bool_calls += 1
                raise AssertionError(
                    "poisoned evaluation-mode argument was coerced"
                )

        explosive_enabled = ExplosiveTruthiness()
        explosive_mode_error = _expect_failed_update_rejection(
            lambda: trainer.set_evaluation_mode(explosive_enabled),
            "Torch explosive evaluation-mode switch",
        )
        rollout_error = _expect_failed_update_rejection(
            trainer.rollouts,
            "Torch rollout",
        )
        log_error = _expect_failed_update_rejection(
            trainer.log,
            "Torch log",
        )
        eval_error = _expect_failed_update_rejection(
            trainer.eval_log,
            "Torch eval_log",
        )
        qualification_error = _expect_failed_update_rejection(
            lambda: trainer.qualification_entropy_gradient_state(
                max_bytes=0,
            ),
            "Torch entropy-gradient qualification",
        )
        save_error = _expect_failed_update_rejection(
            lambda: trainer.save_weights(poisoned_checkpoint),
            "Torch save_weights",
        )
        save_created_no_file = not poisoned_checkpoint.exists()
        original_torch_load = torch.load
        load_calls = 0

        def counted_torch_load(*args: Any, **kwargs: Any) -> Any:
            nonlocal load_calls
            load_calls += 1
            return original_torch_load(*args, **kwargs)

        torch.load = counted_torch_load
        try:
            load_error = _expect_failed_update_rejection(
                lambda: trainer.load_weights(load_checkpoint),
                "Torch load_weights",
            )
        finally:
            torch.load = original_torch_load
        render_error = _expect_failed_update_rejection(
            lambda: trainer.render(-1),
            "Torch render",
        )
        after_retry = _snapshot_overrun_fixture(trainer, torch)
        after_cpu_rng = torch.get_rng_state().detach().cpu().clone()
        after_cuda_rng = _cuda_rng_snapshot(torch)
        after_forward_calls = policy_forward_calls
        trainer.close()
        close_succeeded = (
            trainer._vec.close_calls == 1
            and trainer._training_failed is True
        )
    finally:
        hook.remove()
        temporary.cleanup()

    retry_optimizer_unchanged = (
        optimizer.step_calls == before_optimizer[0]
        and optimizer.zero_calls == before_optimizer[1]
        and bool(
            torch.equal(
                optimizer.state_tensor.detach(),
                before_optimizer[2],
            )
        )
    )
    result = {
        "error_type": error_type,
        "fatal_error": fatal_error,
        "weight_changed": weight_changed,
        "optimizer_changed": optimizer_changed,
        "epoch_uncommitted": epoch_uncommitted,
        "latch_armed": latch_armed,
        "retry_state_unchanged": after_retry == before_retry,
        "retry_rng_unchanged": (
            bool(torch.equal(after_cpu_rng, before_cpu_rng))
            and _rng_snapshots_equal(
                before_cuda_rng,
                after_cuda_rng,
                torch,
            )
        ),
        "retry_policy_forward_unchanged": (
            after_forward_calls == before_forward_calls
        ),
        "retry_optimizer_unchanged": retry_optimizer_unchanged,
        "uptime_rejected": uptime_error == EXPECTED_FAILED_UPDATE_ERROR,
        "sps_rejected": sps_error == EXPECTED_FAILED_UPDATE_ERROR,
        "num_params_rejected": (
            num_params_error == EXPECTED_FAILED_UPDATE_ERROR
        ),
        "qualification_enable_rejected": (
            qualification_enable_error == EXPECTED_FAILED_UPDATE_ERROR
        ),
        "mode_switch_rejected": (
            same_mode_error == EXPECTED_FAILED_UPDATE_ERROR
            and mode_switch_error == EXPECTED_FAILED_UPDATE_ERROR
        ),
        "mode_argument_not_coerced": (
            explosive_mode_error == EXPECTED_FAILED_UPDATE_ERROR
            and explosive_enabled.bool_calls == 0
        ),
        "rollout_rejected": rollout_error == EXPECTED_FAILED_UPDATE_ERROR,
        "log_rejected": log_error == EXPECTED_FAILED_UPDATE_ERROR,
        "eval_log_rejected": eval_error == EXPECTED_FAILED_UPDATE_ERROR,
        "qualification_rejected": (
            qualification_error == EXPECTED_FAILED_UPDATE_ERROR
        ),
        "save_rejected": save_error == EXPECTED_FAILED_UPDATE_ERROR,
        "save_created_no_file": save_created_no_file,
        "load_rejected": (
            load_error == EXPECTED_FAILED_UPDATE_ERROR
            and load_calls == 0
        ),
        "render_rejected": render_error == EXPECTED_FAILED_UPDATE_ERROR,
        "close_succeeded": close_succeeded,
    }
    for key, value in result.items():
        if key in {"error_type", "fatal_error"}:
            continue
        if value is not True:
            _fail(f"failed-update proof {key} is false")
    return result


def _verify_successful_update_latch_clear(
    torch_module: Any,
    torch: Any,
) -> dict[str, bool]:
    trainer, policy, _original_optimizer, _ = _make_trainer(
        torch_module,
        torch,
        update_index=0,
        base_coefficient=BASE_COEFFICIENT,
        anneal_enabled=True,
    )
    trainer.optimizer = _MutatingOptimizer(
        policy.theta,
        abort_on_step=None,
    )
    trainer.train()
    first_update_committed = trainer.epoch == 1
    latch_cleared = trainer._training_failed is False
    trainer.tail_valid = True
    trainer.train()
    result = {
        "first_update_committed": first_update_committed,
        "latch_cleared": latch_cleared,
        "second_update_committed": trainer.epoch == 2,
        "second_latch_cleared": trainer._training_failed is False,
    }
    if not all(result.values()):
        _fail(
            "successful Torch updates did not clear the fatal latch "
            "after complete publication"
        )
    return result


def _verify_failed_update_latch(
    torch_module: Any,
    torch: Any,
    post_class_callable_contract: Mapping[str, bool],
) -> dict[str, Any]:
    return {
        "recoverable_preflights": (
            _verify_recoverable_training_preflights(
                torch_module,
                torch,
            )
        ),
        "minibatch_abort": _verify_failed_update_case(
            torch_module,
            torch,
            post_loop_abort=False,
        ),
        "post_loop_abort": _verify_failed_update_case(
            torch_module,
            torch,
            post_loop_abort=True,
        ),
        "post_class_callable_contract": dict(
            post_class_callable_contract
        ),
        "success_clear": _verify_successful_update_latch_clear(
            torch_module,
            torch,
        ),
    }


def _verify_zero_minibatch_guard(
    torch_module: Any,
) -> dict[str, Any]:
    class UntouchableVec:
        def __init__(self) -> None:
            object.__setattr__(self, "access_count", 0)

        def __getattribute__(self, name: str) -> Any:
            if name == "access_count":
                return object.__getattribute__(self, name)
            object.__setattr__(
                self,
                "access_count",
                object.__getattribute__(self, "access_count") + 1,
            )
            raise AssertionError(
                "invalid construction touched the vector before validation"
            )

    args = {
        "reset_state": True,
        "train": {
            "total_timesteps": 40,
            "horizon": 2,
            "minibatch_size": 2,
            "replay_ratio": 0.49,
            "ent_coef": BASE_COEFFICIENT,
            "anneal_ent_coef": True,
            "min_ent_coef_ratio": MIN_COEFFICIENT_RATIO,
        },
        "vec": {"total_agents": 1},
    }
    vec = UntouchableVec()
    try:
        torch_module.PuffeRL(args, vec, object(), verbose=False)
    except ValueError as exc:
        error = str(exc)
    else:
        _fail("Torch construction accepted zero minibatches per update")
    if error != EXPECTED_ZERO_MINIBATCH_ERROR:
        _fail(f"zero-minibatch construction returned wrong error: {error!r}")
    if vec.access_count != 0:
        _fail("zero-minibatch construction touched the vector")
    return {
        "error": error,
        "rejected_before_vec_access": True,
    }


def _verify_telemetry(
    torch_module: Any,
    torch: Any,
    trust: _TrustedTorchClipper,
) -> dict[str, Any]:
    record, trainer = _execute_run(
        torch_module,
        torch,
        trust,
        case="telemetry_middle",
        update_index=TOTAL_UPDATES // 2,
        base_coefficient=BASE_COEFFICIENT,
        anneal_enabled=True,
    )
    interval = trainer._train_log_interval
    eval_before = trainer.eval_log()
    eval_result = {
        "loss_empty": eval_before.get("loss") == {},
        "schedule_absent": "entropy_schedule" not in eval_before,
        "interval_preserved": trainer._train_log_interval is interval,
    }
    if not all(eval_result.values()):
        _fail("eval_log leaked or cleared pending training telemetry")

    train_read = trainer.log()
    schedule = train_read.get("entropy_schedule")
    if type(schedule) is not dict:
        _fail("train log omitted entropy_schedule")
    expected_schedule = {
        "entropy_schedule_contract": CONTRACT,
        "entropy_first_applied_update_index": TOTAL_UPDATES // 2,
        "entropy_applied_update_index": TOTAL_UPDATES // 2,
        "entropy_update_count": 1,
        "entropy_loss_minibatch_count": MINIBATCHES_PER_UPDATE,
        "entropy_c_real": oracle_schedule_point(
            base_coefficient=BASE_COEFFICIENT,
            anneal_enabled=True,
            min_coefficient_ratio=MIN_COEFFICIENT_RATIO,
            update_index=TOTAL_UPDATES // 2,
            total_updates=TOTAL_UPDATES,
        )["c_real"],
        "entropy_c_applied": record["applied_coefficient"],
    }
    if frozenset(schedule) != frozenset(expected_schedule):
        _fail("train entropy_schedule telemetry has a non-closed schema")
    for key, expected in expected_schedule.items():
        actual = schedule[key]
        if type(expected) is float:
            _assert_close(actual, expected, f"train log {key}")
        elif actual != expected:
            _fail(f"train log {key}={actual!r}, expected {expected!r}")
    train_loss = train_read.get("loss")
    train_result = {
        "loss_present": (
            type(train_loss) is dict
            and "entropy_term" in train_loss
            and "total_loss" in train_loss
        ),
        "contract": schedule["entropy_schedule_contract"],
        "first_update_index": schedule["entropy_first_applied_update_index"],
        "last_update_index": schedule["entropy_applied_update_index"],
        "update_count": schedule["entropy_update_count"],
        "loss_minibatch_count": schedule["entropy_loss_minibatch_count"],
        "c_applied": schedule["entropy_c_applied"],
    }
    if train_result["loss_present"] is not True:
        _fail("training log omitted objective losses")

    second_read = trainer.log()
    read_clear = {
        "loss_empty": second_read.get("loss") == {},
        "schedule_absent": "entropy_schedule" not in second_read,
    }
    if not all(read_clear.values()):
        _fail("training telemetry was not read-clear")

    _, mode_trainer = _execute_run(
        torch_module,
        torch,
        trust,
        case="telemetry_mode_switch",
        update_index=TOTAL_UPDATES // 2,
        base_coefficient=BASE_COEFFICIENT,
        anneal_enabled=True,
    )
    mode_trainer.set_evaluation_mode(True)
    mode_eval = mode_trainer.eval_log()
    evaluation_mode_clear = {
        "loss_empty": mode_eval.get("loss") == {},
        "schedule_absent": "entropy_schedule" not in mode_eval,
    }
    if not all(evaluation_mode_clear.values()):
        _fail("evaluation mode exposed stale training telemetry")
    return {
        "eval_before_read": eval_result,
        "train_read": train_result,
        "read_clear": read_clear,
        "evaluation_mode_clear": evaluation_mode_clear,
    }


def _identity(
    source: Mapping[str, Any], extension: Any, extension_mode: str
) -> dict[str, str]:
    try:
        config_digest = hashlib.sha256(source["config_path"].read_bytes()).hexdigest()
        torch_digest = hashlib.sha256(source["torch_path"].read_bytes()).hexdigest()
    except OSError as exc:
        _fail(f"cannot rehash selected Puffer source: {exc}")
    if config_digest != source["config_sha256"]:
        _fail("pufferlib/pufferl.py changed after initial source validation")
    if torch_digest != source["torch_sha256"]:
        _fail("pufferlib/torch_pufferl.py changed after initial source " "validation")
    if extension_mode == "compiled":
        extension_path = _selected_module_path(
            extension, source["root"], "pufferlib._C"
        )
        try:
            extension_digest = hashlib.sha256(extension_path.read_bytes()).hexdigest()
        except OSError as exc:
            _fail(f"cannot hash selected compiled extension: {exc}")
    else:
        extension_digest = hashlib.sha256(
            f"explicit-test-stub:{CONTRACT}".encode("ascii")
        ).hexdigest()
    return {
        "git_commit": _git_commit(source["root"]),
        "pufferl_sha256": config_digest,
        "torch_pufferl_sha256": torch_digest,
        "extension_sha256": extension_digest,
        "extension_mode": extension_mode,
        "extension_contract": CONTRACT,
    }


def execute_verification(
    puffer_root: str | Path,
    *,
    allow_test_extension_stub: bool = False,
) -> dict[str, Any]:
    """Run the full CPU objective proof against one selected source tree."""

    source = validate_selected_source(puffer_root)
    process_state = _capture_selected_import_process_state()
    try:
        return _execute_verification_after_source_validation(
            source,
            allow_test_extension_stub=allow_test_extension_stub,
        )
    finally:
        _restore_selected_import_process_state(process_state)


def _execute_verification_after_source_validation(
    source: Mapping[str, Any],
    *,
    allow_test_extension_stub: bool,
) -> dict[str, Any]:
    torch = importlib.import_module("torch")
    trust = _capture_trusted_torch_clipper(torch)
    try:
        config_module, torch_module, extension, imported = (
            _import_selected_puffer(
                source,
                allow_test_extension_stub=allow_test_extension_stub,
            )
        )
    except BaseException:
        _restore_trusted_torch_clipper(torch, trust)
        raise
    del config_module
    try:
        post_class_callable_contract = (
            _verify_post_class_wrapper_runtime_contract(torch_module)
        )
        _require_trusted_torch_clipper(torch, trust)
        if bool(getattr(extension, "gpu", False)):
            _fail("CPU objective verifier imported a GPU extension")
        initial_identity = _identity(source, extension, imported["mode"])
        original_advantage = _install_deterministic_advantage(torch_module, torch)
        try:
            run_records = []
            run_specs = (
                ("annealed_first", 0, BASE_COEFFICIENT, True),
                (
                    "annealed_middle",
                    TOTAL_UPDATES // 2,
                    BASE_COEFFICIENT,
                    True,
                ),
                (
                    "annealed_last",
                    TOTAL_UPDATES - 1,
                    BASE_COEFFICIENT,
                    True,
                ),
                (
                    "disabled_middle",
                    TOTAL_UPDATES // 2,
                    BASE_COEFFICIENT,
                    False,
                ),
                ("zero_middle", TOTAL_UPDATES // 2, 0.0, True),
            )
            trainers: dict[str, Any] = {}
            for case, update_index, base, enabled in run_specs:
                record, trainer = _execute_run(
                    torch_module,
                    torch,
                    trust,
                    case=case,
                    update_index=update_index,
                    base_coefficient=base,
                    anneal_enabled=enabled,
                )
                run_records.append(record)
                trainers[case] = trainer
            del trainers
            runs_by_case = {record["case"]: record for record in run_records}
            gradient_oracle = _verify_gradient_oracle(runs_by_case)
            clipping_control = _execute_active_clipping_control(
                torch_module,
                torch,
                trust,
            )
            guards = {
                "overrun": _verify_overrun_guard(torch_module, torch),
                "zero_minibatch": _verify_zero_minibatch_guard(torch_module),
                "failed_update": _verify_failed_update_latch(
                    torch_module,
                    torch,
                    post_class_callable_contract,
                ),
            }
            telemetry = _verify_telemetry(torch_module, torch, trust)
        finally:
            torch_module.compute_puff_advantage = original_advantage

        points = [
            oracle_schedule_point(
                base_coefficient=BASE_COEFFICIENT,
                anneal_enabled=True,
                min_coefficient_ratio=MIN_COEFFICIENT_RATIO,
                update_index=index,
                total_updates=TOTAL_UPDATES,
            )
            for index in POINT_INDICES
        ]
        applied = [float(point["c_applied"]) for point in points]
        if not applied[0] > applied[1] > applied[2]:
            _fail("N=20 entropy schedule did not move first > middle > last")
        final_identity = _identity(source, extension, imported["mode"])
        if final_identity != initial_identity:
            _fail(
                "selected Puffer source, extension, or git identity "
                "changed during objective verification"
            )
        evidence = {
            "schema_version": SCHEMA_VERSION,
            "contract": CONTRACT,
            "identity": initial_identity,
            "schedule": {
                "total_updates": TOTAL_UPDATES,
                "base_coefficient": BASE_COEFFICIENT,
                "min_coefficient_ratio": MIN_COEFFICIENT_RATIO,
                "minibatches_per_update": MINIBATCHES_PER_UPDATE,
                "point_indices": list(POINT_INDICES),
                "points": points,
            },
            "runs": run_records,
            "clipping_control": clipping_control,
            "gradient_oracle": gradient_oracle,
            "guards": guards,
            "telemetry": telemetry,
        }
        validate_evidence(
            evidence,
            allow_test_stub=allow_test_extension_stub,
        )
        return evidence
    finally:
        try:
            _restore_puffer_modules(imported["state"]["old_modules"])
            _restore_selected_import_process_state(
                imported["state"]["process_state"],
            )
        finally:
            _restore_trusted_torch_clipper(torch, trust)


def validate_evidence(raw: Any, *, allow_test_stub: bool = False) -> dict[str, Any]:
    """Validate the verifier's closed JSON-compatible evidence schema."""

    evidence = _require_exact_keys(raw, TOP_LEVEL_KEYS, "evidence")
    _require_expected_int(
        evidence["schema_version"],
        SCHEMA_VERSION,
        "evidence.schema_version",
    )
    if evidence["contract"] != CONTRACT:
        _fail("evidence has the wrong contract")
    identity = _require_exact_keys(
        evidence["identity"], IDENTITY_KEYS, "evidence.identity"
    )
    for field in (
        "git_commit",
        "pufferl_sha256",
        "torch_pufferl_sha256",
        "extension_sha256",
    ):
        value = identity[field]
        expected_lengths = (40, 64) if field == "git_commit" else (64,)
        if (
            type(value) is not str
            or len(value) not in expected_lengths
            or any(char not in "0123456789abcdef" for char in value)
        ):
            _fail(f"evidence.identity.{field} is not a lowercase digest")
    if identity["extension_mode"] not in ("compiled", "test_stub"):
        _fail("evidence.identity.extension_mode is invalid")
    if identity["extension_mode"] == "test_stub" and not allow_test_stub:
        _fail(
            "test-stub evidence is not qualification evidence; "
            "allow_test_stub must be explicit"
        )
    if identity["extension_contract"] != CONTRACT:
        _fail("evidence identity has the wrong extension contract")

    schedule = _require_exact_keys(
        evidence["schedule"], SCHEDULE_KEYS, "evidence.schedule"
    )
    _require_expected_int(
        schedule["total_updates"],
        TOTAL_UPDATES,
        "evidence.schedule.total_updates",
    )
    _require_expected_int(
        schedule["minibatches_per_update"],
        MINIBATCHES_PER_UPDATE,
        "evidence.schedule.minibatches_per_update",
    )
    _assert_close(
        schedule["base_coefficient"],
        BASE_COEFFICIENT,
        "evidence schedule base coefficient",
        atol=0.0,
        rtol=0.0,
    )
    _assert_close(
        schedule["min_coefficient_ratio"],
        MIN_COEFFICIENT_RATIO,
        "evidence schedule minimum ratio",
        atol=0.0,
        rtol=0.0,
    )
    point_indices = schedule["point_indices"]
    if type(point_indices) is not list or len(point_indices) != len(POINT_INDICES):
        _fail("evidence schedule point_indices are wrong")
    for ordinal, (actual, expected) in enumerate(
        zip(point_indices, POINT_INDICES, strict=True)
    ):
        _require_expected_int(
            actual,
            expected,
            f"evidence.schedule.point_indices[{ordinal}]",
        )
    points = schedule["points"]
    if type(points) is not list or len(points) != len(POINT_INDICES):
        _fail("evidence schedule points must contain first/middle/last")
    for ordinal, (point, index) in enumerate(zip(points, POINT_INDICES, strict=True)):
        point = _require_exact_keys(
            point, POINT_KEYS, f"evidence.schedule.points[{ordinal}]"
        )
        expected = oracle_schedule_point(
            base_coefficient=BASE_COEFFICIENT,
            anneal_enabled=True,
            min_coefficient_ratio=MIN_COEFFICIENT_RATIO,
            update_index=index,
            total_updates=TOTAL_UPDATES,
        )
        for field, expected_value in expected.items():
            actual = point[field]
            if type(expected_value) is float:
                _assert_close(
                    actual,
                    expected_value,
                    f"schedule point {ordinal}.{field}",
                    atol=2.0e-8 if field == "c_applied" else 2.0e-12,
                    rtol=2.0e-7 if field == "c_applied" else 2.0e-12,
                )
            else:
                _require_expected_int(
                    actual,
                    expected_value,
                    f"evidence.schedule.points[{ordinal}].{field}",
                )

    runs = evidence["runs"]
    if type(runs) is not list or len(runs) != 5:
        _fail("evidence.runs must contain exactly five controls")
    expected_cases = (
        "annealed_first",
        "annealed_middle",
        "annealed_last",
        "disabled_middle",
        "zero_middle",
    )
    if tuple(run.get("case") for run in runs if type(run) is dict) != (expected_cases):
        _fail("evidence.runs cases are absent, duplicated, or out of order")
    expected_run_specs = (
        ("annealed_first", 0, BASE_COEFFICIENT, True),
        (
            "annealed_middle",
            TOTAL_UPDATES // 2,
            BASE_COEFFICIENT,
            True,
        ),
        (
            "annealed_last",
            TOTAL_UPDATES - 1,
            BASE_COEFFICIENT,
            True,
        ),
        (
            "disabled_middle",
            TOTAL_UPDATES // 2,
            BASE_COEFFICIENT,
            False,
        ),
        ("zero_middle", TOTAL_UPDATES // 2, 0.0, True),
    )
    for ordinal, (run, expected_spec) in enumerate(
        zip(runs, expected_run_specs, strict=True)
    ):
        run = _require_exact_keys(run, RUN_KEYS, f"evidence.runs[{ordinal}]")
        expected_case, expected_index, expected_base, expected_enabled = expected_spec
        if run["case"] != expected_case:
            _fail(f"evidence.runs[{ordinal}] has the wrong case")
        _require_expected_int(
            run["update_index"],
            expected_index,
            f"evidence.runs[{ordinal}].update_index",
        )
        if (
            _require_bool(
                run["anneal_enabled"],
                f"evidence.runs[{ordinal}].anneal_enabled",
            )
            is not expected_enabled
        ):
            _fail(f"evidence.runs[{ordinal}] has wrong anneal_enabled")
        _assert_close(
            run["base_coefficient"],
            expected_base,
            f"evidence.runs[{ordinal}].base_coefficient",
            atol=0.0,
            rtol=0.0,
        )
        _require_expected_int(
            run["minibatch_count"],
            MINIBATCHES_PER_UPDATE,
            f"evidence.runs[{ordinal}].minibatch_count",
        )
        for list_field in (
            "entropy_hook_coefficients",
            "preclip_gradients",
            "optimizer_gradients",
        ):
            values = run[list_field]
            if type(values) is not list or len(values) != (MINIBATCHES_PER_UPDATE):
                _fail(
                    f"evidence.runs[{ordinal}].{list_field} must contain "
                    "one value per minibatch"
                )
            for index, value in enumerate(values):
                _require_number(
                    value,
                    f"evidence.runs[{ordinal}].{list_field}[{index}]",
                )
        _verify_operation_order(
            run["operation_order"],
            f"evidence.runs[{ordinal}]",
        )
        coefficient = _require_number(
            run["applied_coefficient"],
            f"evidence.runs[{ordinal}].applied_coefficient",
        )
        expected_coefficient = oracle_schedule_point(
            base_coefficient=expected_base,
            anneal_enabled=expected_enabled,
            min_coefficient_ratio=MIN_COEFFICIENT_RATIO,
            update_index=expected_index,
            total_updates=TOTAL_UPDATES,
        )["c_applied"]
        _assert_close(
            coefficient,
            expected_coefficient,
            f"evidence.runs[{ordinal}] applied coefficient",
            atol=2.0e-8,
            rtol=2.0e-7,
        )
        for value in run["entropy_hook_coefficients"]:
            _assert_close(
                value,
                coefficient,
                f"evidence.runs[{ordinal}] hook coefficient",
                atol=2.0e-7,
                rtol=2.0e-6,
            )
        for before, after in zip(
            run["preclip_gradients"],
            run["optimizer_gradients"],
            strict=True,
        ):
            _assert_close(
                before,
                after,
                f"evidence.runs[{ordinal}] non-clipping proof",
                atol=2.0e-7,
                rtol=2.0e-6,
            )
            if abs(float(before)) >= MAX_GRAD_NORM:
                _fail(
                    f"evidence.runs[{ordinal}] does not prove clipping " "was inactive"
                )
        entropy = _require_number(run["entropy"], f"evidence.runs[{ordinal}].entropy")
        _assert_close(
            entropy,
            oracle_binary_entropy(),
            f"evidence.runs[{ordinal}] entropy analytic value",
            atol=2.0e-6,
            rtol=2.0e-5,
        )
        entropy_term = _require_number(
            run["entropy_term"],
            f"evidence.runs[{ordinal}].entropy_term",
        )
        _assert_close(
            entropy_term,
            -coefficient * entropy,
            f"evidence.runs[{ordinal}] signed entropy term",
        )
        policy_loss = _require_number(
            run["policy_loss"],
            f"evidence.runs[{ordinal}].policy_loss",
        )
        value_loss = _require_number(
            run["value_loss"],
            f"evidence.runs[{ordinal}].value_loss",
        )
        total_loss = _require_number(
            run["total_loss"],
            f"evidence.runs[{ordinal}].total_loss",
        )
        _assert_close(
            total_loss,
            policy_loss + VF_COEFFICIENT * value_loss + entropy_term,
            f"evidence.runs[{ordinal}] total decomposition",
        )
        if entropy <= 0.0:
            _fail(f"evidence.runs[{ordinal}] entropy is not positive")
        if coefficient > 0.0 and entropy_term >= 0.0:
            _fail(f"evidence.runs[{ordinal}] entropy term has the wrong sign")
        if coefficient == 0.0 and entropy_term != 0.0:
            _fail(f"evidence.runs[{ordinal}] zero coefficient term is nonzero")
        exact_joint_entropy = _require_number(
            run["exact_joint_positive_entropy"],
            f"evidence.runs[{ordinal}].exact_joint_positive_entropy",
        )
        _assert_close(
            exact_joint_entropy,
            oracle_binary_entropy(),
            f"evidence.runs[{ordinal}] exact-joint analytic entropy",
            atol=2.0e-6,
            rtol=2.0e-5,
        )

    clipping = _require_exact_keys(
        evidence["clipping_control"],
        CLIPPING_CONTROL_KEYS,
        "evidence.clipping_control",
    )
    _assert_close(
        clipping["max_grad_norm"],
        ACTIVE_CLIP_MAX_GRAD_NORM,
        "evidence active clipping max_grad_norm",
        atol=0.0,
        rtol=0.0,
    )
    _require_expected_int(
        clipping["minibatch_count"],
        MINIBATCHES_PER_UPDATE,
        "evidence.clipping_control.minibatch_count",
    )
    _verify_operation_order(
        clipping["operation_order"],
        "evidence.clipping_control",
    )
    clipping_lists = {}
    for field in (
        "preclip_gradients",
        "optimizer_gradients",
        "expected_gradients",
    ):
        values = clipping[field]
        if type(values) is not list or len(values) != MINIBATCHES_PER_UPDATE:
            _fail(
                f"evidence.clipping_control.{field} must contain "
                "one value per minibatch"
            )
        clipping_lists[field] = [
            _require_number(
                value,
                f"evidence.clipping_control.{field}[{index}]",
            )
            for index, value in enumerate(values)
        ]
    for index, (before, observed, claimed_expected) in enumerate(
        zip(
            clipping_lists["preclip_gradients"],
            clipping_lists["optimizer_gradients"],
            clipping_lists["expected_gradients"],
            strict=True,
        )
    ):
        if abs(before) <= 2.0 * ACTIVE_CLIP_MAX_GRAD_NORM:
            _fail(
                f"evidence active clipping minibatch {index} is vacuous"
            )
        expected = _scalar_clip_oracle(
            before,
            ACTIVE_CLIP_MAX_GRAD_NORM,
        )
        _assert_close(
            claimed_expected,
            expected,
            f"evidence active clipping minibatch {index} oracle",
            atol=2.0e-7,
            rtol=2.0e-5,
        )
        _assert_close(
            observed,
            expected,
            f"evidence active clipping minibatch {index} optimizer gradient",
            atol=2.0e-7,
            rtol=2.0e-5,
        )
        if _close(observed, before, atol=2.0e-7, rtol=2.0e-6):
            _fail(
                f"evidence active clipping minibatch {index} did not clip"
            )

    gradient = _require_exact_keys(
        evidence["gradient_oracle"],
        GRADIENT_KEYS,
        "evidence.gradient_oracle",
    )
    for key, value in gradient.items():
        _require_number(value, f"evidence.gradient_oracle.{key}")
    _assert_close(
        gradient["theta"],
        THETA,
        "evidence gradient theta",
        atol=0.0,
        rtol=0.0,
    )
    probability = 1.0 / (1.0 + math.exp(-THETA))
    entropy_derivative = -THETA * probability * (1.0 - probability)
    _assert_close(
        gradient["binary_probability"],
        probability,
        "evidence gradient probability",
        atol=2.0e-12,
        rtol=2.0e-12,
    )
    _assert_close(
        gradient["entropy_derivative"],
        entropy_derivative,
        "evidence entropy derivative",
        atol=2.0e-12,
        rtol=2.0e-12,
    )
    _assert_close(
        gradient["max_grad_norm"],
        MAX_GRAD_NORM,
        "evidence max_grad_norm",
        atol=0.0,
        rtol=0.0,
    )
    runs_by_case = {run["case"]: run for run in runs}
    enabled_run = runs_by_case["annealed_middle"]
    disabled_run = runs_by_case["disabled_middle"]
    zero_run = runs_by_case["zero_middle"]
    enabled_deltas = [
        float(value) - float(baseline)
        for value, baseline in zip(
            enabled_run["preclip_gradients"],
            zero_run["preclip_gradients"],
            strict=True,
        )
    ]
    disabled_deltas = [
        float(value) - float(baseline)
        for value, baseline in zip(
            disabled_run["preclip_gradients"],
            zero_run["preclip_gradients"],
            strict=True,
        )
    ]
    enabled_observed = sum(enabled_deltas) / len(enabled_deltas)
    disabled_observed = sum(disabled_deltas) / len(disabled_deltas)
    if enabled_observed <= 0.0 or disabled_observed <= 0.0:
        _fail("evidence entropy gradient has the wrong sign")
    enabled_expected = -float(enabled_run["applied_coefficient"]) * entropy_derivative
    disabled_expected = -float(disabled_run["applied_coefficient"]) * entropy_derivative
    for ordinal, delta in enumerate(enabled_deltas):
        _assert_close(
            delta,
            enabled_expected,
            f"evidence enabled minibatch {ordinal} delta",
            atol=5.0e-7,
            rtol=2.0e-5,
        )
    for ordinal, delta in enumerate(disabled_deltas):
        _assert_close(
            delta,
            disabled_expected,
            f"evidence disabled minibatch {ordinal} delta",
            atol=5.0e-7,
            rtol=2.0e-5,
        )
    _assert_close(
        gradient["enabled_delta"],
        enabled_observed,
        "evidence enabled run linkage",
        atol=5.0e-7,
        rtol=2.0e-5,
    )
    _assert_close(
        gradient["disabled_delta"],
        disabled_observed,
        "evidence disabled run linkage",
        atol=5.0e-7,
        rtol=2.0e-5,
    )
    _assert_close(
        gradient["enabled_expected"],
        enabled_expected,
        "evidence enabled analytic linkage",
        atol=5.0e-7,
        rtol=2.0e-5,
    )
    _assert_close(
        gradient["disabled_expected"],
        disabled_expected,
        "evidence disabled analytic linkage",
        atol=5.0e-7,
        rtol=2.0e-5,
    )
    _assert_close(
        gradient["enabled_delta"],
        gradient["enabled_expected"],
        "evidence enabled gradient",
        atol=5.0e-7,
        rtol=2.0e-5,
    )
    _assert_close(
        gradient["disabled_delta"],
        gradient["disabled_expected"],
        "evidence disabled gradient",
        atol=5.0e-7,
        rtol=2.0e-5,
    )
    _assert_close(
        gradient["scale_ratio_actual"],
        gradient["scale_ratio_expected"],
        "evidence gradient scale ratio",
        atol=2.0e-5,
        rtol=2.0e-4,
    )
    _assert_close(
        gradient["scale_ratio_actual"],
        disabled_observed / enabled_observed,
        "evidence observed gradient scale linkage",
        atol=2.0e-5,
        rtol=2.0e-4,
    )
    _assert_close(
        gradient["scale_ratio_expected"],
        float(disabled_run["applied_coefficient"])
        / float(enabled_run["applied_coefficient"]),
        "evidence expected gradient scale linkage",
        atol=2.0e-5,
        rtol=2.0e-4,
    )

    guards = _require_exact_keys(evidence["guards"], GUARD_KEYS, "evidence.guards")
    overrun = _require_exact_keys(
        guards["overrun"], OVERRUN_KEYS, "evidence.guards.overrun"
    )
    if overrun["error"] != EXPECTED_OVERRUN_ERROR:
        _fail("evidence overrun error is wrong")
    for key in OVERRUN_KEYS - {"error"}:
        if _require_bool(overrun[key], f"evidence.guards.overrun.{key}") is not True:
            _fail(f"evidence overrun proof {key} is false")
    zero = _require_exact_keys(
        guards["zero_minibatch"],
        ZERO_MINIBATCH_KEYS,
        "evidence.guards.zero_minibatch",
    )
    if zero["error"] != EXPECTED_ZERO_MINIBATCH_ERROR:
        _fail("evidence zero-minibatch error is wrong")
    if (
        _require_bool(
            zero["rejected_before_vec_access"],
            "evidence.guards.zero_minibatch.rejected_before_vec_access",
        )
        is not True
    ):
        _fail("zero-minibatch construction reached the vector")

    failed_update = _require_exact_keys(
        guards["failed_update"],
        FAILED_UPDATE_KEYS,
        "evidence.guards.failed_update",
    )
    recoverable = _require_exact_keys(
        failed_update["recoverable_preflights"],
        RECOVERABLE_PREFLIGHT_KEYS,
        "evidence.guards.failed_update.recoverable_preflights",
    )
    for key, value in recoverable.items():
        if (
            _require_bool(
                value,
                "evidence.guards.failed_update."
                f"recoverable_preflights.{key}",
            )
            is not True
        ):
            _fail(f"failed-update recoverable-preflight proof {key} is false")
    callable_contract = _require_exact_keys(
        failed_update["post_class_callable_contract"],
        POST_CLASS_CALLABLE_CONTRACT_KEYS,
        "evidence.guards.failed_update.post_class_callable_contract",
    )
    for key, value in callable_contract.items():
        if (
            _require_bool(
                value,
                "evidence.guards.failed_update."
                f"post_class_callable_contract.{key}",
            )
            is not True
        ):
            _fail(f"failed-update callable-contract proof {key} is false")
    for case_name in ("minibatch_abort", "post_loop_abort"):
        case = _require_exact_keys(
            failed_update[case_name],
            FAILED_UPDATE_CASE_KEYS,
            f"evidence.guards.failed_update.{case_name}",
        )
        if case["error_type"] != "_InjectedTrainingAbort":
            _fail(f"failed-update {case_name} used the wrong abort type")
        if case["fatal_error"] != EXPECTED_FAILED_UPDATE_ERROR:
            _fail(f"failed-update {case_name} used the wrong fatal error")
        for key in FAILED_UPDATE_CASE_KEYS - {
            "error_type",
            "fatal_error",
        }:
            if (
                _require_bool(
                    case[key],
                    f"evidence.guards.failed_update.{case_name}.{key}",
                )
                is not True
            ):
                _fail(f"failed-update {case_name} proof {key} is false")
    success_clear = _require_exact_keys(
        failed_update["success_clear"],
        FAILED_UPDATE_SUCCESS_KEYS,
        "evidence.guards.failed_update.success_clear",
    )
    for key, value in success_clear.items():
        if (
            _require_bool(
                value,
                f"evidence.guards.failed_update.success_clear.{key}",
            )
            is not True
        ):
            _fail(f"failed-update success-clear proof {key} is false")

    telemetry = _require_exact_keys(
        evidence["telemetry"], TELEMETRY_KEYS, "evidence.telemetry"
    )
    eval_before = _require_exact_keys(
        telemetry["eval_before_read"],
        EVAL_TELEMETRY_KEYS,
        "evidence.telemetry.eval_before_read",
    )
    train_read = _require_exact_keys(
        telemetry["train_read"],
        TRAIN_TELEMETRY_KEYS,
        "evidence.telemetry.train_read",
    )
    read_clear = _require_exact_keys(
        telemetry["read_clear"],
        CLEAR_TELEMETRY_KEYS,
        "evidence.telemetry.read_clear",
    )
    mode_clear = _require_exact_keys(
        telemetry["evaluation_mode_clear"],
        CLEAR_TELEMETRY_KEYS,
        "evidence.telemetry.evaluation_mode_clear",
    )
    for label, block in (
        ("eval_before_read", eval_before),
        ("read_clear", read_clear),
        ("evaluation_mode_clear", mode_clear),
    ):
        for key, value in block.items():
            if _require_bool(value, f"evidence.telemetry.{label}.{key}") is not True:
                _fail(f"evidence telemetry {label}.{key} is false")
    if (
        _require_bool(
            train_read["loss_present"],
            "evidence.telemetry.train_read.loss_present",
        )
        is not True
    ):
        _fail("evidence train_read does not contain objective losses")
    if train_read["contract"] != CONTRACT:
        _fail("evidence train_read has wrong contract")
    _require_expected_int(
        train_read["update_count"],
        1,
        "evidence.telemetry.train_read.update_count",
    )
    _require_expected_int(
        train_read["loss_minibatch_count"],
        MINIBATCHES_PER_UPDATE,
        "evidence.telemetry.train_read.loss_minibatch_count",
    )
    _require_expected_int(
        train_read["first_update_index"],
        TOTAL_UPDATES // 2,
        "evidence.telemetry.train_read.first_update_index",
    )
    _require_expected_int(
        train_read["last_update_index"],
        TOTAL_UPDATES // 2,
        "evidence.telemetry.train_read.last_update_index",
    )
    _assert_close(
        train_read["c_applied"],
        oracle_schedule_point(
            base_coefficient=BASE_COEFFICIENT,
            anneal_enabled=True,
            min_coefficient_ratio=MIN_COEFFICIENT_RATIO,
            update_index=TOTAL_UPDATES // 2,
            total_updates=TOTAL_UPDATES,
        )["c_applied"],
        "evidence train_read applied coefficient",
        atol=2.0e-8,
        rtol=2.0e-7,
    )
    return evidence


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        _fail(f"evidence is not canonical JSON: {exc}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puffer-root", required=True, type=Path)
    parser.add_argument(
        "--allow-test-extension-stub",
        action="store_true",
        help=(
            "explicitly permit a minimal CPU _C stub for an unbuilt source "
            "tree; never use this for qualification evidence"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        evidence = execute_verification(
            args.puffer_root,
            allow_test_extension_stub=args.allow_test_extension_stub,
        )
        output = canonical_json(evidence)
    except (OSError, VerificationError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            "FAIL: objective execution raised " f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
