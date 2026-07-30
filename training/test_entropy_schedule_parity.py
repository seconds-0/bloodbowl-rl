"""Red source, installer, and authorization contracts for entropy parity.

The executable schedule and raw-artifact oracle lives in
``verify_entropy_schedule_parity.py``.  This suite watches the Puffer patch
boundary that cannot execute on a non-NVIDIA development host: stable device
state, graph ordering, raw pre-narrowing validation, compiled markers, patch
stack ownership, and the deliberately retained production guards.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TRAINING = ROOT / "training"
PATCH = TRAINING / "puffer_entropy_schedule_parity.patch"
ROLLOUT_PATCH = TRAINING / "puffer_rollout_transition_closure.patch"
QUALIFICATION_PATCH = TRAINING / "puffer_recurrent_cuda_qualification.patch"
RECURRENT_PATCH = TRAINING / "puffer_recurrent_eval_state.patch"
INSTALLER = ROOT / "tools/install_puffer_env.sh"
SCREEN = ROOT / "tools/run_reward_screen.sh"
ARM = ROOT / "tools/run_reward_ablation.sh"
COMPILED_LEDGER = TRAINING / "puffer_compiled_backend_sources.txt"

CONTRACT = "cosine-update-index-over-total-updates-fp32-v1"


def _added_text(patch: Path) -> str:
    if not patch.is_file():
        raise AssertionError(
            "watched fail: training/puffer_entropy_schedule_parity.patch "
            "does not exist"
        )
    additions = []
    for line in patch.read_text(encoding="utf-8").splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            additions.append(line[1:])
    return "\n".join(additions)


def _patch_names(source: str) -> list[str]:
    return re.findall(r'training/([^"/]+\.patch)', source)


def _selected_puffer_source(relative: str) -> str | None:
    root = os.environ.get("PUFFER_ENTROPY_TEST_ROOT")
    if not root:
        return None
    path = Path(root).resolve() / relative
    if not path.is_file():
        raise AssertionError(f"selected Puffer source is missing: {path}")
    return path.read_text(encoding="utf-8")


def _source_or_additions(relative: str) -> str:
    selected = _selected_puffer_source(relative)
    if selected is not None:
        return selected
    return _added_text(PATCH)


def _stripped_source_lines(source: str) -> tuple[str, ...]:
    return tuple(
        line.strip()
        for line in source.splitlines()
        if line.strip()
    )


def _require_exact_subsequence(
    source: str,
    expected: tuple[str, ...],
    label: str,
) -> None:
    lines = _stripped_source_lines(source)
    matches = sum(
        lines[index : index + len(expected)] == expected
        for index in range(len(lines) - len(expected) + 1)
    )
    if matches != 1:
        raise AssertionError(
            f"{label} must occur exactly once as a closed statement "
            f"sequence, found {matches}"
        )


def _extract_braced_definition(source: str, signature: str) -> str:
    if source.count(signature) != 1:
        raise AssertionError(
            f"selected source must contain exactly one {signature!r}"
        )
    start = source.index(signature)
    opening = source.find("{", start + len(signature))
    if opening < 0:
        raise AssertionError(f"{signature!r} has no opening brace")
    depth = 0
    for index in range(opening, len(source)):
        character = source[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"{signature!r} has no closing brace")


def _extract_semicolon_terminated_definition(
    source: str,
    signature: str,
) -> str:
    definition = _extract_braced_definition(source, signature)
    start = source.index(signature)
    end = start + len(definition)
    terminator = re.match(r"\s*;", source[end:])
    if terminator is None:
        raise AssertionError(f"{signature!r} has no terminating semicolon")
    return source[start : end + terminator.end()]


_PUBLIC_TRAIN_WRAPPER = (
    "pybind11::dict train(pybind11::object pufferl_obj) {",
    "PuffeRL& pufferl = pufferl_obj.cast<PuffeRL&>();",
    "require_idle_entropy_transaction(pufferl);",
    "require_public_training_mode(pufferl);",
    "{",
    "PublicEntropyTransaction entropy_transaction(pufferl);",
    "{",
    "require_fresh_training_tail(pufferl);",
    "pybind11::gil_scoped_release no_gil;",
    "entropy_transaction.begin_dispatch();",
    "train_impl(pufferl);",
    "consume_training_tail(pufferl);",
    "}",
    "entropy_transaction.complete();",
    "}",
    "pybind11::dict losses;",
    "return losses;",
    "}",
)

_ENTROPY_TRANSACTION_PREFIX = (
    "explicit PublicEntropyTransaction(PuffeRL& pufferl)",
    ": pufferl_(pufferl) {",
    "require_idle_entropy_transaction(pufferl_);",
    "if (pufferl_.hypers.total_agents <= 0 ||",
    "pufferl_.hypers.horizon <= 0 ||",
    "static_cast<long long>(pufferl_.hypers.total_agents) >",
    "static_cast<long long>(",
    "std::numeric_limits<long>::max())",
    "/ static_cast<long long>(pufferl_.hypers.horizon)) {",
    "throw std::runtime_error(",
    '"training batch is invalid before update dispatch");',
    "}",
    "long batch_size =",
    "static_cast<long>(pufferl_.hypers.total_agents)",
    "* static_cast<long>(pufferl_.hypers.horizon);",
    "long total_updates =",
    "pufferl_.hypers.total_timesteps / batch_size;",
    "if (pufferl_.epoch < 0 || pufferl_.epoch >= total_updates) {",
    "throw std::runtime_error(",
    '"training update exceeds configured total updates");',
    "}",
    "pufferl_.defer_entropy_schedule_commit = true;",
)

_ENTROPY_TRANSACTION_CLASS = (
    "class PublicEntropyTransaction {",
    "public:",
    *_ENTROPY_TRANSACTION_PREFIX,
    "}",
    "~PublicEntropyTransaction() noexcept {",
    "if (!complete_) {",
    "pufferl_.defer_entropy_schedule_commit = false;",
    "pufferl_.entropy_schedule_commit_pending = false;",
    "if (dispatch_started_) {",
    "pufferl_.training_failed = true;",
    "}",
    "}",
    "}",
    "void begin_dispatch() noexcept {",
    "dispatch_started_ = true;",
    "}",
    "void complete() {",
    "if (!dispatch_started_) {",
    "throw std::runtime_error(",
    '"public training entropy commit preceded update dispatch");',
    "}",
    "try {",
    "commit_pending_entropy_schedule_update(pufferl_);",
    "} catch (...) {",
    "pufferl_.training_failed = true;",
    "pufferl_.defer_entropy_schedule_commit = false;",
    "pufferl_.entropy_schedule_commit_pending = false;",
    "throw;",
    "}",
    "pufferl_.defer_entropy_schedule_commit = false;",
    "complete_ = true;",
    "}",
    "private:",
    "PuffeRL& pufferl_;",
    "bool dispatch_started_ = false;",
    "bool complete_ = false;",
    "};",
)

_IDLE_ENTROPY_TRANSACTION_GUARD = (
    "static void require_idle_entropy_transaction(PuffeRL& pufferl) {",
    "if (pufferl.training_failed) {",
    "throw std::runtime_error(",
    '"training object is unusable after an incomplete update");',
    "}",
    "if (pufferl.defer_entropy_schedule_commit) {",
    "throw std::runtime_error(",
    '"operation is unavailable during an active training transaction");',
    "}",
    "if (pufferl.entropy_schedule_commit_pending) {",
    "throw std::runtime_error(",
    '"training object has stale pending entropy evidence");',
    "}",
    "}",
)

_BASE_PYOBJECT_NATIVE_SURFACES = (
    ("log", "pybind11::dict puf_log(pybind11::object pufferl_obj)"),
    (
        "eval_log",
        "pybind11::dict puf_eval_log(pybind11::object pufferl_obj)",
    ),
    (
        "python_vec_recv",
        "void python_vec_recv(pybind11::object pufferl_obj, int buf)",
    ),
    (
        "python_vec_send",
        "void python_vec_send(pybind11::object pufferl_obj, int buf)",
    ),
    ("render", "void render(pybind11::object pufferl_obj, int env_id)"),
    (
        "rollouts",
        "void guarded_rollouts(pybind11::object pufferl_obj)",
    ),
    ("train", "pybind11::dict train(pybind11::object pufferl_obj)"),
    (
        "save_weights",
        "void save_weights(pybind11::object pufferl_obj,",
    ),
    (
        "load_weights",
        "void load_weights(pybind11::object pufferl_obj,",
    ),
    (
        "set_evaluation_mode",
        "void guarded_set_evaluation_mode("
        "\n        pybind11::object pufferl_obj, bool enabled)",
    ),
    (
        "add_frozen_bank",
        "int py_add_frozen_bank(py::object pufferl_obj, int slice_size,",
    ),
    (
        "load_frozen_bank",
        "void py_load_frozen_bank(py::object pufferl_obj, int bank_idx,",
    ),
    (
        "set_agent_perm",
        "void py_set_agent_perm(py::object pufferl_obj,",
    ),
    (
        "set_env_tags",
        "void py_set_env_tags(py::object pufferl_obj,",
    ),
    (
        "count_aligned",
        "int py_count_aligned(py::object pufferl_obj, int tag_value,",
    ),
    ("num_envs", "int py_num_envs(py::object pufferl_obj)"),
    (
        "uptime",
        'm.def("uptime", [](py::object pufferl_obj) -> double',
    ),
)

_QUALIFICATION_PYOBJECT_NATIVE_SURFACES = (
    (
        "qualification_recurrent_state",
        "py::dict qualification_recurrent_state(",
    ),
    (
        "qualification_policy_weights",
        "py::dict qualification_policy_weights(",
    ),
    (
        "qualification_snapshot",
        "py::dict qualification_snapshot(",
    ),
    (
        "qualification_entropy_overrun_state",
        "py::dict qualification_entropy_overrun_state(",
    ),
    (
        "qualification_entropy_gradient_state",
        "py::dict qualification_entropy_gradient_state(",
    ),
    (
        "qualification_graph_execution",
        "py::dict qualification_graph_execution(py::object pufferl_obj)",
    ),
    (
        "qualification_consume_tail",
        "py::dict qualification_consume_tail(py::object pufferl_obj)",
    ),
)

_PYOBJECT_REGISTRATION_TARGETS = {
    "log": "puf_log",
    "eval_log": "puf_eval_log",
    "python_vec_recv": "python_vec_recv",
    "python_vec_send": "python_vec_send",
    "render": "render",
    "rollouts": "rollouts",
    "train": "train",
    "save_weights": "save_weights",
    "load_weights": "load_weights",
    "set_evaluation_mode": "set_evaluation_mode",
    "add_frozen_bank": "py_add_frozen_bank",
    "load_frozen_bank": "py_load_frozen_bank",
    "set_agent_perm": "py_set_agent_perm",
    "set_env_tags": "py_set_env_tags",
    "count_aligned": "py_count_aligned",
    "num_envs": "py_num_envs",
    "qualification_recurrent_state": "qualification_recurrent_state",
    "qualification_policy_weights": "qualification_policy_weights",
    "qualification_snapshot": "qualification_snapshot",
    "qualification_entropy_overrun_state": (
        "qualification_entropy_overrun_state"
    ),
    "qualification_entropy_gradient_state": (
        "qualification_entropy_gradient_state"
    ),
    "qualification_graph_execution": "qualification_graph_execution",
    "qualification_consume_tail": "qualification_consume_tail",
}

_NATIVE_GUARDED_REPLACEMENTS = {
    "set_evaluation_mode": {
        "raw_target": "set_evaluation_mode",
        "guarded_target": "guarded_set_evaluation_mode",
        "signature": (
            "void guarded_set_evaluation_mode("
            "\n        pybind11::object pufferl_obj, bool enabled)"
        ),
        "delegation": "set_evaluation_mode(pufferl_obj, enabled);",
        "binding": (
            'm.attr("set_evaluation_mode") = py::cpp_function(\n'
            "        &guarded_set_evaluation_mode,\n"
            '        py::name("set_evaluation_mode"), py::scope(m),\n'
            '        py::arg("pufferl"), py::arg("enabled"));'
        ),
    },
    "rollouts": {
        "raw_target": "rollouts",
        "guarded_target": "guarded_rollouts",
        "signature": "void guarded_rollouts(pybind11::object pufferl_obj)",
        "delegation": "rollouts(pufferl_obj);",
        "binding": (
            'm.attr("rollouts") = py::cpp_function(\n'
            "        &guarded_rollouts,\n"
            '        py::name("rollouts"), py::scope(m),\n'
            '        py::arg("pufferl"));'
        ),
    },
}

_NUM_PARAMS_SIGNATURE = (
    '.def("num_params", [](PuffeRL& self) -> int64_t'
)
_PYOBJECT_CAST = re.compile(
    r"^(?:PuffeRL&|auto&) pufferl = "
    r"pufferl_obj\.cast<PuffeRL&>\(\);$"
)
_IDLE_PYOBJECT_CALL = "require_idle_entropy_transaction(pufferl);"
_IDLE_DIRECT_REFERENCE_CALL = "require_idle_entropy_transaction(self);"


def _assert_closed_idle_entropy_transaction_guard(source: str) -> None:
    guard = _extract_braced_definition(
        source,
        "static void require_idle_entropy_transaction(PuffeRL& pufferl)",
    )
    if _stripped_source_lines(guard) != _IDLE_ENTROPY_TRANSACTION_GUARD:
        raise AssertionError(
            "selected source differs from the closed idle entropy "
            "transaction guard"
        )


def _executable_body_lines(definition: str) -> tuple[str, ...]:
    body = definition[definition.index("{") + 1 :]
    return tuple(
        line
        for line in _stripped_source_lines(body)
        if not line.startswith("//")
    )


def _assert_pyobject_idle_guard_is_first(
    source: str,
    signature: str,
) -> None:
    definition = _extract_braced_definition(source, signature)
    executable = _executable_body_lines(definition)
    if definition.count("pufferl_obj.cast<PuffeRL&>();") != 1:
        raise AssertionError(
            f"{signature!r} must contain exactly one PuffeRL cast"
        )
    if definition.count(_IDLE_PYOBJECT_CALL) != 1:
        raise AssertionError(
            f"{signature!r} must contain exactly one idle transaction guard"
        )
    if len(executable) < 2 or _PYOBJECT_CAST.fullmatch(
        executable[0]
    ) is None or executable[1] != _IDLE_PYOBJECT_CALL:
        raise AssertionError(
            f"{signature!r} must cast PuffeRL and call its idle transaction "
            "guard as the first two executable statements"
        )


def _assert_guarded_native_public_replacement(
    source: str,
    registered_name: str,
) -> None:
    contract = _NATIVE_GUARDED_REPLACEMENTS[registered_name]
    raw_registration = (
        f'm.def("{registered_name}", &{contract["raw_target"]});'
    )
    binding = contract["binding"]
    if source.count(raw_registration) != 1:
        raise AssertionError(
            f"{registered_name!r} must retain exactly one causal raw "
            "registration before its guarded replacement"
        )
    if source.count(binding) != 1:
        raise AssertionError(
            f"{registered_name!r} must have exactly one closed guarded "
            "py::cpp_function replacement with preserved metadata"
        )
    if source.count(f'm.attr("{registered_name}")') != 1:
        raise AssertionError(
            f"{registered_name!r} must have exactly one effective module "
            "attribute replacement"
        )
    binding_operations = re.findall(
        rf'm\.(def|attr)\("{re.escape(registered_name)}"',
        source,
    )
    if binding_operations != ["def", "attr"]:
        raise AssertionError(
            f"{registered_name!r} must have exactly one raw registration "
            "followed by one final guarded module binding"
        )
    raw_at = source.index(raw_registration)
    binding_at = source.index(binding)
    stable_trailing_anchor = source.index(
        'm.def("python_vec_send", &python_vec_send);',
        binding_at,
    )
    if not raw_at < binding_at < stable_trailing_anchor:
        raise AssertionError(
            f"{registered_name!r} guarded replacement must overwrite its "
            "raw registration before the stable python_vec_send anchor"
        )

    definition = _extract_braced_definition(
        source,
        contract["signature"],
    )
    executable = _executable_body_lines(definition)
    expected = (
        "PuffeRL& pufferl = pufferl_obj.cast<PuffeRL&>();",
        _IDLE_PYOBJECT_CALL,
        contract["delegation"],
        "}",
    )
    if executable != expected:
        raise AssertionError(
            f"{registered_name!r} guarded replacement must cast, reject, "
            "and only then delegate to its unexposed implementation"
        )
    if (
        f'py::name("{registered_name}")' not in binding
        or "py::scope(m)" not in binding
    ):
        raise AssertionError(
            f"{registered_name!r} guarded replacement must preserve its "
            "public name and module"
        )


def _assert_direct_reference_idle_guard_is_first(
    source: str,
    signature: str,
) -> None:
    definition = _extract_braced_definition(source, signature)
    executable = _executable_body_lines(definition)
    if definition.count(_IDLE_DIRECT_REFERENCE_CALL) != 1:
        raise AssertionError(
            f"{signature!r} must contain exactly one direct-reference idle "
            "transaction guard"
        )
    if not executable or executable[0] != _IDLE_DIRECT_REFERENCE_CALL:
        raise AssertionError(
            f"{signature!r} must call its idle transaction guard as the "
            "first executable statement"
        )


def _remove_executable_line(definition: str, statement: str) -> str:
    lines = definition.splitlines()
    matches = [
        index for index, line in enumerate(lines)
        if line.strip() == statement
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"expected one mutation target {statement!r}, found "
            f"{len(matches)}"
        )
    del lines[matches[0]]
    return "\n".join(lines)


def _swap_first_two_executable_lines(definition: str) -> str:
    executable_indices = [
        index
        for index, line in enumerate(definition.splitlines())
        if line.strip() and not line.strip().startswith("//")
    ]
    # The signature itself can span several lines and is executable only after
    # the opening brace. Locate body statements instead of counting signature
    # lines.
    opening_line = definition[: definition.index("{")].count("\n")
    body_indices = [
        index for index in executable_indices if index > opening_line
    ]
    if len(body_indices) < 2:
        raise AssertionError("callable mutation fixture has fewer than two actions")
    lines = definition.splitlines()
    first, second = body_indices[:2]
    first_indent = lines[first][: len(lines[first]) - len(lines[first].lstrip())]
    second_indent = lines[second][
        : len(lines[second]) - len(lines[second].lstrip())
    ]
    first_text = lines[first].strip()
    second_text = lines[second].strip()
    lines[first] = first_indent + second_text
    lines[second] = second_indent + first_text
    return "\n".join(lines)


def _assert_guard_precedes_state_access(
    source: str,
    signature: str,
) -> None:
    definition = _extract_braced_definition(source, signature)
    cast_marker = "pufferl_obj.cast<PuffeRL&>();"
    guard_marker = "require_idle_entropy_transaction(pufferl);"
    if definition.count(cast_marker) != 1:
        raise AssertionError(
            f"{signature!r} must contain exactly one PuffeRL cast"
        )
    if definition.count(guard_marker) != 1:
        raise AssertionError(
            f"{signature!r} must contain exactly one idle transaction guard"
        )
    cast_end = definition.index(cast_marker) + len(cast_marker)
    guard_at = definition.index(guard_marker)
    if guard_at < cast_end or "pufferl." in definition[cast_end:guard_at]:
        raise AssertionError(
            f"{signature!r} accesses mutable training state before its "
            "idle transaction guard"
        )


def _assert_qualification_idle_guard_is_fatal_first(
    source: str,
    signature: str,
) -> None:
    definition = _extract_braced_definition(source, signature)
    cast_statement = "PuffeRL& pufferl = pufferl_obj.cast<PuffeRL&>();"
    guard_statement = "require_idle_entropy_transaction(pufferl);"
    if definition.count(cast_statement) != 1:
        raise AssertionError(
            f"{signature!r} must contain exactly one PuffeRL cast"
        )
    if definition.count(guard_statement) != 1:
        raise AssertionError(
            f"{signature!r} must contain exactly one idle transaction guard"
        )

    body = definition[definition.index("{") + 1 :]
    if _stripped_source_lines(body)[:2] != (
        cast_statement,
        guard_statement,
    ):
        raise AssertionError(
            f"{signature!r} must cast PuffeRL and call its idle transaction "
            "guard as the first two executable statements"
        )


def _f32(value: float) -> float:
    return struct.unpack("=f", struct.pack("=f", value))[0]


def _f32_bits(value: float) -> int:
    return struct.unpack("=I", struct.pack("=f", value))[0]


def _tree_reduce_f32(values: list[float]) -> float:
    if not values or len(values) & (len(values) - 1):
        raise AssertionError("binary32 tree-reduction input must be power-of-two")
    reduced = [_f32(value) for value in values]
    stride = len(reduced) // 2
    while stride:
        for index in range(stride):
            reduced[index] = _f32(reduced[index] + reduced[index + stride])
        stride //= 2
    return reduced[0]


def _assert_closed_native_public_train(source: str) -> None:
    wrapper = _extract_braced_definition(
        source,
        "pybind11::dict train(pybind11::object pufferl_obj)",
    )
    if _stripped_source_lines(wrapper) != _PUBLIC_TRAIN_WRAPPER:
        raise AssertionError(
            "selected source differs from the closed public train wrapper"
        )
    transaction = _extract_semicolon_terminated_definition(
        source,
        "class PublicEntropyTransaction",
    )
    if _stripped_source_lines(transaction) != _ENTROPY_TRANSACTION_CLASS:
        raise AssertionError(
            "selected source differs from the closed public entropy "
            "transaction class"
        )


class EntropySchedulePatchStackTests(unittest.TestCase):
    def test_patch_is_owned_once_in_every_causal_stack(self) -> None:
        self.assertTrue(
            PATCH.is_file(),
            "watched fail: create the reviewed entropy schedule patch",
        )
        installer = INSTALLER.read_text(encoding="utf-8")
        screen = SCREEN.read_text(encoding="utf-8")
        arm = ARM.read_text(encoding="utf-8")

        self.assertIn(
            'ENTROPY_SCHEDULE_PATCH="$ROOT/training/'
            'puffer_entropy_schedule_parity.patch"',
            installer,
        )
        for marker in (
            '"$ENTROPY_SCHEDULE_PATCH"',
            "entropy_schedule_sources_valid",
            "entropy_schedule_contract",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, installer)

        installer_order = (
            installer.index("# Frozen PPO rows"),
            installer.index("# Entropy-schedule objective parity"),
            installer.index("# Bounded CUDA qualification surfaces"),
        )
        self.assertEqual(installer_order, tuple(sorted(installer_order)))

        for source in (screen, arm):
            names = _patch_names(source)
            self.assertEqual(
                names.count("puffer_entropy_schedule_parity.patch"),
                1,
            )
            self.assertLess(
                names.index("puffer_frozen_prio_mask.patch"),
                names.index("puffer_entropy_schedule_parity.patch"),
            )
            self.assertLess(
                names.index("puffer_entropy_schedule_parity.patch"),
                names.index("puffer_recurrent_cuda_qualification.patch"),
            )

        final_reverse = installer.split(
            "for overlapping_patch in", 1
        )[1].split("; do", 1)[0]
        self.assertIn('"$ENTROPY_SCHEDULE_PATCH"', final_reverse)

    def test_compiled_source_registry_already_closes_over_changed_sources(
        self,
    ) -> None:
        entries = [
            line.strip()
            for line in COMPILED_LEDGER.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(len(entries), 15)
        for expected in (
            "pufferlib/pufferl.py",
            "pufferlib/sweep.py",
            "pufferlib/torch_pufferl.py",
            "src/bindings.cu",
            "src/bindings_cpu.cpp",
            "src/pufferlib.cu",
        ):
            self.assertIn(expected, entries)

    def test_installer_validity_gate_tracks_hardened_entropy_surfaces(
        self,
    ) -> None:
        installer = INSTALLER.read_text(encoding="utf-8")
        gate = installer.split(
            "entropy_schedule_sources_valid() {", 1
        )[1].split(
            "\n}\n\nentropy_qualification_guards_valid()", 1
        )[0]
        qualification_gate = installer.split(
            "entropy_qualification_guards_valid() {", 1
        )[1].split(
            "\n}\n\nstrict_environment_config_sources_valid()", 1
        )[0]
        for marker in (
            "if self.epoch < 0 or self.epoch >= self.total_epochs:",
            "self._training_failed = True",
            "training object is unavailable during or after an "
            "incomplete update",
            "if isinstance(value, np.generic):",
            "value = value.item()",
            "params[name] = value",
            "static void require_idle_entropy_transaction(PuffeRL& pufferl) {",
            "if (pufferl.defer_entropy_schedule_commit) {",
            "if (pufferl.entropy_schedule_commit_pending) {",
            "if (pufferl.training_failed) {",
            "require_idle_entropy_transaction(pufferl",
            "block_losses[LOSS_ENT_COEF][tid] = "
            "idx == 0 ? ent_coef : 0.0f;",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, gate)
        self.assertIn(
            '"$PUFFER/pufferlib/sweep.py"',
            gate,
        )
        self.assertIn(
            '"$PUFFER/src/bindings.cu"',
            gate,
        )
        self.assertIn(
            '"$PUFFER/src/pufferlib.cu"',
            gate,
        )
        self.assertIn(
            'case "$idle_call_count" in',
            gate,
        )
        self.assertIn(
            "18|25) ;;",
            gate,
            "the entropy-phase gate must accept only the complete guarded "
            "entropy-only callable surface or "
            "complete qualification call count",
        )
        self.assertIn(
            '[ "$failed_line" -lt "$defer_line" ]',
            gate,
            "fatal poison must be checked before transient transaction state",
        )
        self.assertIn(
            '[ "$defer_line" -lt "$pending_line" ]',
            gate,
            "deferred state must be checked before pending evidence",
        )
        self.assertIn(
            "params[name] = spaces[name].unnormalize(flat_sample[idx])",
            gate,
            "the gate must explicitly reject the legacy direct sweep "
            "assignment",
        )
        self.assertIn(
            "block_losses[LOSS_ENT_COEF][tid] = ent_coef * inv_NT;",
            gate,
            "the gate must explicitly reject reconstructed coefficient "
            "telemetry",
        )
        self.assertIn(
            ')" -eq 25 ]',
            qualification_gate,
            "the full-stack gate must reject a tree missing any guarded "
            "qualification callable",
        )
        self.assertGreaterEqual(
            installer.count("entropy_qualification_guards_valid"),
            3,
            "the full-stack guard must be defined and checked during both "
            "installation and --check",
        )

    def test_installer_validity_functions_execute_at_both_causal_phases(
        self,
    ) -> None:
        installer = INSTALLER.read_text(encoding="utf-8")

        def shell_function(name: str, next_name: str) -> str:
            start_marker = f"{name}() {{"
            end_marker = f"\n}}\n\n{next_name}() {{"
            start = installer.index(start_marker)
            end = installer.index(end_marker, start) + 2
            return installer[start:end]

        functions = "\n\n".join((
            shell_function(
                "entropy_schedule_sources_valid",
                "entropy_qualification_guards_valid",
            ),
            shell_function(
                "entropy_qualification_guards_valid",
                "strict_environment_config_sources_valid",
            ),
        ))

        with tempfile.TemporaryDirectory() as temporary:
            puffer = Path(temporary)

            def write(relative: str, source: str) -> None:
                path = puffer / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source, encoding="utf-8")

            torch_source = """
ENTROPY_SCHEDULE_CONTRACT = "cosine-update-index-over-total-updates-fp32-v1"
def entropy_schedule_point():
    pass
if self.epoch < 0 or self.epoch >= self.total_epochs:
    pass
self._training_failed = True
raise RuntimeError(
    "training object is unavailable during or after an incomplete update")
def _copy_public_callable_metadata(guarded, method):
    pass
def _reject_incomplete_update_set_evaluation_mode(method):
    pass
def _reject_incomplete_update_rollouts(method):
    pass
PuffeRL.set_evaluation_mode = \\
    _reject_incomplete_update_set_evaluation_mode(
        PuffeRL.set_evaluation_mode)
PuffeRL.rollouts = _reject_incomplete_update_rollouts(PuffeRL.rollouts)
"""
            sweep_source = """
if isinstance(value, np.generic):
    value = value.item()
params[name] = value
"""
            binding_prefix = """
static void require_idle_entropy_transaction(PuffeRL& pufferl) {
    if (pufferl.training_failed) {
    }
    if (pufferl.defer_entropy_schedule_commit) {
    }
    if (pufferl.entropy_schedule_commit_pending) {
    }
}
""" + (
                "require_idle_entropy_transaction(pufferl_);\n"
                + "require_idle_entropy_transaction(pufferl);\n" * 17
                + "void guarded_set_evaluation_mode(\n"
                + "void guarded_rollouts(pybind11::object pufferl_obj)\n"
                + 'm.attr("set_evaluation_mode") = py::cpp_function(\n'
                + 'm.attr("rollouts") = py::cpp_function(\n'
                + 'py::name("set_evaluation_mode"), py::scope(m),\n'
                + 'py::name("rollouts"), py::scope(m),\n'
                + 'm.attr("entropy_schedule_contract") = '
                '"cosine-update-index-over-total-updates-fp32-v1";\n'
            )
            native_source = """
FloatTensor ent_coef;
const float* ent_coef;
block_losses[LOSS_ENT_COEF][tid] = idx == 0 ? ent_coef : 0.0f;
LOSS_ENT_COEF
LOSS_ENT_TERM
"""
            cpu_binding = """
m.attr("entropy_schedule_contract") = "cosine-update-index-over-total-updates-fp32-v1";
"""

            write("pufferlib/torch_pufferl.py", torch_source)
            write("pufferlib/sweep.py", sweep_source)
            write("src/bindings.cu", binding_prefix)
            write("src/bindings_cpu.cpp", cpu_binding)
            write("src/pufferlib.cu", native_source)

            def gate_succeeds(name: str) -> bool:
                script = (
                    f"{functions}\n"
                    'PUFFER="$1"\n'
                    f"{name}\n"
                )
                result = subprocess.run(
                    ["bash", "-c", script, "entropy-gate", str(puffer)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                return result.returncode == 0

            self.assertTrue(
                gate_succeeds("entropy_schedule_sources_valid"),
                "the entropy patch's 18-call causal phase must validate",
            )
            self.assertFalse(
                gate_succeeds("entropy_qualification_guards_valid"),
                "the entropy-only phase must not impersonate the full stack",
            )

            final_binding = (
                binding_prefix
                + "require_idle_entropy_transaction(pufferl);\n" * 7
            )
            write("src/bindings.cu", final_binding)
            self.assertTrue(
                gate_succeeds("entropy_schedule_sources_valid"),
                "the complete 25-call tree must remain idempotently valid",
            )
            self.assertTrue(
                gate_succeeds("entropy_qualification_guards_valid"),
                "the complete 25-call tree must satisfy the qualification gate",
            )

            write(
                "src/bindings.cu",
                binding_prefix
                + "require_idle_entropy_transaction(pufferl);\n" * 6,
            )
            self.assertFalse(
                gate_succeeds("entropy_schedule_sources_valid"),
                "a partial 24-call qualification state must fail closed",
            )

            write("src/bindings.cu", final_binding)
            mutation_cases = (
                (
                    "pufferlib/torch_pufferl.py",
                    torch_source,
                    torch_source.replace(
                        "self.epoch < 0 or ", "", 1
                    ),
                ),
                (
                    "pufferlib/sweep.py",
                    sweep_source,
                    sweep_source.replace(
                        "params[name] = value",
                        "params[name] = spaces[name].unnormalize("
                        "flat_sample[idx])",
                        1,
                    ),
                ),
                (
                    "src/bindings.cu",
                    final_binding,
                    final_binding.replace(
                        "    if (pufferl.training_failed) {\n"
                        "    }\n"
                        "    if (pufferl.defer_entropy_schedule_commit) {",
                        "    if (pufferl.defer_entropy_schedule_commit) {\n"
                        "    }\n"
                        "    if (pufferl.training_failed) {",
                        1,
                    ),
                ),
                (
                    "src/pufferlib.cu",
                    native_source,
                    native_source.replace(
                        "idx == 0 ? ent_coef : 0.0f",
                        "ent_coef * inv_NT",
                        1,
                    ),
                ),
            )
            for relative, valid, mutated in mutation_cases:
                with self.subTest(relative=relative):
                    write(relative, mutated)
                    self.assertFalse(
                        gate_succeeds("entropy_schedule_sources_valid"),
                    )
                    write(relative, valid)

    def test_qualification_guard_is_recut_but_shell_guards_remain(self) -> None:
        qualification_patch = QUALIFICATION_PATCH.read_text(encoding="utf-8")
        self.assertNotIn(
            "CUDA graph training with entropy annealing is disabled until",
            qualification_patch,
            "the constructor guard must be removed by recutting the "
            "qualification patch, not deleted by a later patch",
        )

        arm = ARM.read_text(encoding="utf-8")
        screen = SCREEN.read_text(encoding="utf-8")
        arm_guard = (
            'if [ "$DRY_RUN" != "1" ] && '
            '[ "$CUDAGRAPHS" -ge 0 ] && '
            '[ "$ANNEAL_ENT_COEF" = "1" ]; then'
        )
        screen_guard = (
            'if [ "$PLAN_ONLY" != "1" ] && '
            '[ "$CUDAGRAPHS" -ge 0 ] && '
            '[ "$ANNEAL_ENT_COEF" = "1" ]; then'
        )
        self.assertIn(arm_guard, arm)
        self.assertIn(screen_guard, screen)
        self.assertLess(arm.index(arm_guard), arm.index('META_ARGS=('))
        self.assertLess(
            screen.index(screen_guard),
            screen.index('mkdir -p "$OUT_DIR"'),
        )
        for source in (arm, screen):
            self.assertIn("BLOCKED_UNQUALIFIED_ENTROPY_SCHEDULE", source)
            self.assertIn("implemented_pending_nvidia", source)


class NativeEntropyObjectiveSourceTests(unittest.TestCase):
    def test_device_scalar_is_stable_fp32_and_kernel_owned(self) -> None:
        source = _source_or_additions("src/pufferlib.cu")
        for marker in (
            "const float* ent_coef",
            "FloatTensor ent_coef",
            ".ent_coef = {.shape = {1}}",
            "alloc_register(alloc, &bufs.ent_coef)",
            "float ent_coef = *a.ent_coef",
            "LOSS_ENT_COEF",
            "LOSS_ENT_TERM",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, source)

        self.assertIn("-ent_coef * total_entropy", source)
        self.assertIn("dL * (-ent_coef)", source)
        self.assertNotIn(
            "dL * (-a.ent_coef)",
            source,
            "gradient must use the one kernel-local device value",
        )
        self.assertNotIn(
            "- a.ent_coef * total_entropy",
            source,
            "forward loss must use the one kernel-local device value",
        )

    def test_checked_same_stream_copy_and_successful_epoch_commit(self) -> None:
        source = _selected_puffer_source("src/pufferlib.cu")
        if source is None:
            additions = _added_text(PATCH)
            for marker in (
                "cudaMemcpyAsync",
                "cudaMemcpyHostToDevice",
                "train_stream",
                "entropy coefficient copy failed",
            ):
                self.assertIn(marker, additions)
            self.assertIn(
                "training CUDA execution failed",
                ROLLOUT_PATCH.read_text(encoding="utf-8"),
                "the rollout-owned post-training synchronization failure "
                "must remain in the causal patch stack",
            )
            return

        copy_at = source.index("cudaMemcpyAsync(\n        pufferl.ppo_bufs_puf.ent_coef.data")
        replay_at = source.index(
            "cudaGraphLaunch(\n                    pufferl.train_cudagraph",
            copy_at,
        )
        capture_at = source.index("cudaStreamBeginCapture", copy_at)
        self.assertLess(copy_at, replay_at)
        self.assertLess(copy_at, capture_at)
        copy_end = source.index(";", copy_at)
        self.assertIn("train_stream", source[copy_at:copy_end])

        synchronize = source.index(
            "cudaStreamSynchronize(train_stream)", replay_at
        )
        epoch_commit = source.index("pufferl.epoch =", synchronize)
        self.assertLess(synchronize, epoch_commit)

    def test_public_overrun_guard_precedes_tail_access_and_dispatch(self) -> None:
        selected = _selected_puffer_source("src/bindings.cu")
        if selected is not None:
            _assert_closed_native_public_train(selected)
            return

        additions = _added_text(PATCH)
        _require_exact_subsequence(
            additions,
            _ENTROPY_TRANSACTION_PREFIX,
            "entropy transaction pre-dispatch prefix",
        )
        _require_exact_subsequence(
            additions,
            (
                "{",
                "PublicEntropyTransaction entropy_transaction(pufferl);",
                "entropy_transaction.begin_dispatch();",
                "}",
                "entropy_transaction.complete();",
            ),
            "entropy transaction public-wrapper additions",
        )
        recurrent = RECURRENT_PATCH.read_text(encoding="utf-8")
        self.assertEqual(
            recurrent.count(
                "+    require_public_training_mode(pufferl);\n"
                "     {"
            ),
            1,
            "the recurrent patch must place the public-mode guard "
            "immediately before the existing public training block",
        )

    def test_idle_transaction_guard_closes_entropy_owned_entrypoints(
        self,
    ) -> None:
        entropy_additions = _added_text(PATCH)
        qualification_additions = _added_text(QUALIFICATION_PATCH)
        _assert_closed_idle_entropy_transaction_guard(entropy_additions)
        self.assertEqual(
            entropy_additions.count(
                "require_idle_entropy_transaction(pufferl);"
            ),
            17,
            "every base py-object callable except close must use the shared "
            "idle guard",
        )
        self.assertEqual(
            entropy_additions.count(
                "require_idle_entropy_transaction(pufferl_);"
            ),
            1,
            "the public train transaction must use the shared idle guard",
        )
        self.assertEqual(
            qualification_additions.count(
                "require_idle_entropy_transaction(pufferl);"
            ),
            7,
            "every object-bound qualification callable must reject an "
            "active or poisoned public train",
        )
        self.assertEqual(
            entropy_additions.count(
                _IDLE_DIRECT_REFERENCE_CALL
            ),
            1,
            "PuffeRL.num_params must independently guard its direct "
            "reference before reading training state",
        )

        selected = _selected_puffer_source("src/bindings.cu")
        if selected is None:
            selected = entropy_additions
        _assert_closed_idle_entropy_transaction_guard(selected)
        if _selected_puffer_source("src/bindings.cu") is not None:
            for _, signature in (
                *_BASE_PYOBJECT_NATIVE_SURFACES,
                *_QUALIFICATION_PYOBJECT_NATIVE_SURFACES,
            ):
                with self.subTest(signature=signature):
                    _assert_pyobject_idle_guard_is_first(
                        selected,
                        signature,
                    )
            _assert_direct_reference_idle_guard_is_first(
                selected,
                _NUM_PARAMS_SIGNATURE,
            )

        mutated = selected.replace(
            "if (pufferl.training_failed) {",
            "if (__SWAP_ENTROPY_GUARD__) {",
            1,
        ).replace(
            "if (pufferl.defer_entropy_schedule_commit) {",
            "if (pufferl.training_failed) {",
            1,
        ).replace(
            "if (__SWAP_ENTROPY_GUARD__) {",
            "if (pufferl.defer_entropy_schedule_commit) {",
            1,
        )
        with self.assertRaisesRegex(
            AssertionError,
            "closed idle entropy transaction guard",
        ):
            _assert_closed_idle_entropy_transaction_guard(mutated)

    def test_all_registered_native_pufferl_callables_close_poison_surface(
        self,
    ) -> None:
        selected = _selected_puffer_source("src/bindings.cu")
        if selected is None:
            self.skipTest(
                "set PUFFER_ENTROPY_TEST_ROOT to authenticate the complete "
                "native registration surface"
            )

        self.assertEqual(len(_BASE_PYOBJECT_NATIVE_SURFACES), 17)
        self.assertEqual(len(_QUALIFICATION_PYOBJECT_NATIVE_SURFACES), 7)
        for registered_name, signature in (
            *_BASE_PYOBJECT_NATIVE_SURFACES,
            *_QUALIFICATION_PYOBJECT_NATIVE_SURFACES,
        ):
            with self.subTest(surface=registered_name):
                self.assertEqual(
                    selected.count(f'm.def("{registered_name}"'),
                    1,
                    f"{registered_name!r} must remain registered exactly once",
                )
                if registered_name == "uptime":
                    self.assertEqual(
                        selected.count(signature),
                        1,
                        "uptime must remain registered through its guarded "
                        "inline lambda",
                    )
                else:
                    target = _PYOBJECT_REGISTRATION_TARGETS[registered_name]
                    registration = re.compile(
                        rf'm\.def\("{re.escape(registered_name)}",\s*'
                        rf"&{re.escape(target)}(?:,|\);)"
                    )
                    self.assertEqual(
                        len(registration.findall(selected)),
                        1,
                        f"{registered_name!r} must remain bound to "
                        f"{target!r}",
                    )
                if registered_name in _NATIVE_GUARDED_REPLACEMENTS:
                    _assert_guarded_native_public_replacement(
                        selected,
                        registered_name,
                    )
                _assert_pyobject_idle_guard_is_first(selected, signature)

                definition = _extract_braced_definition(
                    selected,
                    signature,
                )
                without_guard = _remove_executable_line(
                    definition,
                    _IDLE_PYOBJECT_CALL,
                )
                with self.assertRaisesRegex(
                    AssertionError,
                    "exactly one idle transaction guard",
                ):
                    _assert_pyobject_idle_guard_is_first(
                        without_guard,
                        signature,
                    )

                reordered = _swap_first_two_executable_lines(definition)
                with self.assertRaisesRegex(
                    AssertionError,
                    "first two executable statements",
                ):
                    _assert_pyobject_idle_guard_is_first(
                        reordered,
                        signature,
                    )

                if registered_name in _NATIVE_GUARDED_REPLACEMENTS:
                    binding = _NATIVE_GUARDED_REPLACEMENTS[
                        registered_name
                    ]["binding"]
                    without_replacement = selected.replace(binding, "", 1)
                    with self.assertRaisesRegex(
                        AssertionError,
                        "guarded py::cpp_function replacement",
                    ):
                        _assert_guarded_native_public_replacement(
                            without_replacement,
                            registered_name,
                        )
                    without_name = selected.replace(
                        f'py::name("{registered_name}")',
                        'py::name("__metadata_drift__")',
                        1,
                    )
                    with self.assertRaisesRegex(
                        AssertionError,
                        "guarded py::cpp_function replacement",
                    ):
                        _assert_guarded_native_public_replacement(
                            without_name,
                            registered_name,
                        )
                    without_scope = selected.replace(
                        binding,
                        binding.replace(", py::scope(m)", "", 1),
                        1,
                    )
                    with self.assertRaisesRegex(
                        AssertionError,
                        "guarded py::cpp_function replacement",
                    ):
                        _assert_guarded_native_public_replacement(
                            without_scope,
                            registered_name,
                        )
                    with_sibling = selected.replace(
                        binding,
                        binding.replace(
                            "py::scope(m),",
                            "py::scope(m), py::sibling(m),",
                            1,
                        ),
                        1,
                    )
                    with self.assertRaisesRegex(
                        AssertionError,
                        "guarded py::cpp_function replacement",
                    ):
                        _assert_guarded_native_public_replacement(
                            with_sibling,
                            registered_name,
                        )
                    later_raw_rebind = (
                        selected
                        + f'\nm.def("{registered_name}", '
                        f'&{_NATIVE_GUARDED_REPLACEMENTS[registered_name]["raw_target"]});\n'
                    )
                    with self.assertRaisesRegex(
                        AssertionError,
                        "exactly one causal raw registration",
                    ):
                        _assert_guarded_native_public_replacement(
                            later_raw_rebind,
                            registered_name,
                        )

        self.assertEqual(
            selected.count('.def("num_params"'),
            1,
            "PuffeRL.num_params must remain registered exactly once",
        )
        _assert_direct_reference_idle_guard_is_first(
            selected,
            _NUM_PARAMS_SIGNATURE,
        )
        num_params = _extract_braced_definition(
            selected,
            _NUM_PARAMS_SIGNATURE,
        )
        without_num_params_guard = _remove_executable_line(
            num_params,
            _IDLE_DIRECT_REFERENCE_CALL,
        )
        with self.assertRaisesRegex(
            AssertionError,
            "exactly one direct-reference idle transaction guard",
        ):
            _assert_direct_reference_idle_guard_is_first(
                without_num_params_guard,
                _NUM_PARAMS_SIGNATURE,
            )
        reordered_num_params = _swap_first_two_executable_lines(num_params)
        with self.assertRaisesRegex(
            AssertionError,
            "first executable statement",
        ):
            _assert_direct_reference_idle_guard_is_first(
                reordered_num_params,
                _NUM_PARAMS_SIGNATURE,
            )

        close_signature = "void puf_close(pybind11::object pufferl_obj)"
        close_definition = _extract_braced_definition(
            selected,
            close_signature,
        )
        self.assertEqual(
            selected.count('m.def("close", &puf_close);'),
            1,
            "close must remain the sole registered poison-state escape hatch",
        )
        self.assertNotIn(
            "require_idle_entropy_transaction(",
            close_definition,
            "close must remain callable so a poisoned object can release "
            "resources",
        )
        self.assertRegex(
            _executable_body_lines(close_definition)[0],
            _PYOBJECT_CAST,
        )

    def test_qualification_idle_guard_is_fatal_first(self) -> None:
        selected = _selected_puffer_source("src/bindings.cu")
        source = (
            selected
            if selected is not None
            else "\n".join(
                (
                    _added_text(PATCH),
                    _added_text(QUALIFICATION_PATCH),
                )
            )
        )
        signatures = (
            "py::dict qualification_entropy_overrun_state(",
            "py::dict qualification_entropy_gradient_state(",
        )
        for signature in signatures:
            with self.subTest(signature=signature):
                _assert_qualification_idle_guard_is_fatal_first(
                    source,
                    signature,
                )

        signature = signatures[0]
        definition = _extract_braced_definition(source, signature)
        validation = _extract_braced_definition(
            definition,
            "if (max_bytes == 0 || "
            "max_bytes > QUALIFICATION_MAX_SNAPSHOT_BYTES)",
        )
        without_validation = definition.replace(validation, "", 1)
        cast_statement = (
            "PuffeRL& pufferl = pufferl_obj.cast<PuffeRL&>();"
        )
        reordered_definition = without_validation.replace(
            cast_statement,
            f"{validation}\n    {cast_statement}",
            1,
        )
        self.assertNotEqual(reordered_definition, definition)
        reordered_source = source.replace(
            definition,
            reordered_definition,
            1,
        )
        with self.assertRaisesRegex(
            AssertionError,
            "first two executable statements",
        ):
            _assert_qualification_idle_guard_is_fatal_first(
                reordered_source,
                signature,
            )

    def test_closed_public_wrapper_rejects_pretransaction_mutation(self) -> None:
        selected = _selected_puffer_source("src/bindings.cu")
        if selected is None:
            selected = "\n".join(
                (
                    *_IDLE_ENTROPY_TRANSACTION_GUARD,
                    "",
                    *_ENTROPY_TRANSACTION_CLASS,
                    "",
                    *_PUBLIC_TRAIN_WRAPPER,
                )
            )
        _assert_closed_native_public_train(selected)
        mutated = selected.replace(
            "PublicEntropyTransaction entropy_transaction(pufferl);",
            "pufferl.profile.accum[PROF_TRAIN] += 1.0f;\n"
            "PublicEntropyTransaction entropy_transaction(pufferl);",
            1,
        )
        with self.assertRaisesRegex(
            AssertionError,
            "closed public train wrapper",
        ):
            _assert_closed_native_public_train(mutated)
        indent = (
            "    "
            if "    require_idle_entropy_transaction(pufferl);\n"
            "    require_public_training_mode(pufferl);" in selected
            else ""
        )
        idle_then_mode = (
            f"{indent}require_idle_entropy_transaction(pufferl);\n"
            f"{indent}require_public_training_mode(pufferl);"
        )
        self.assertEqual(selected.count(idle_then_mode), 1)
        masked_fatal = selected.replace(
            idle_then_mode,
            f"{indent}require_public_training_mode(pufferl);\n"
            f"{indent}require_idle_entropy_transaction(pufferl);",
            1,
        )
        with self.assertRaisesRegex(
            AssertionError,
            "closed public train wrapper",
        ):
            _assert_closed_native_public_train(masked_fatal)

    def test_closed_public_transaction_rejects_lifecycle_mutations(
        self,
    ) -> None:
        selected = _selected_puffer_source("src/bindings.cu")
        if selected is None:
            selected = "\n".join(
                (
                    *_ENTROPY_TRANSACTION_CLASS,
                    "",
                    *_PUBLIC_TRAIN_WRAPPER,
                )
            )
        _assert_closed_native_public_train(selected)
        transaction = _extract_semicolon_terminated_definition(
            selected,
            "class PublicEntropyTransaction",
        )
        canonical = "\n".join(_ENTROPY_TRANSACTION_CLASS)
        mutations = {
            "destructor requires incomplete transaction": (
                "if (!complete_) {",
                "if (complete_) {",
            ),
            "destructor clears deferred publication": (
                "if (!complete_) {\n"
                "pufferl_.defer_entropy_schedule_commit = false;",
                "if (!complete_) {\n"
                "pufferl_.defer_entropy_schedule_commit = true;",
            ),
            "destructor clears pending evidence": (
                "pufferl_.defer_entropy_schedule_commit = false;\n"
                "pufferl_.entropy_schedule_commit_pending = false;\n"
                "if (dispatch_started_) {",
                "pufferl_.defer_entropy_schedule_commit = false;\n"
                "pufferl_.entropy_schedule_commit_pending = true;\n"
                "if (dispatch_started_) {",
            ),
            "destructor does not poison before dispatch": (
                "if (dispatch_started_) {\n"
                "pufferl_.training_failed = true;\n"
                "}\n"
                "}\n"
                "}\n"
                "void begin_dispatch() noexcept {",
                "pufferl_.training_failed = true;\n"
                "}\n"
                "}\n"
                "void begin_dispatch() noexcept {",
            ),
            "begin dispatch records mutation eligibility": (
                "dispatch_started_ = true;",
                "dispatch_started_ = false;",
            ),
            "complete requires prior dispatch": (
                "if (!dispatch_started_) {\n"
                "throw std::runtime_error(",
                "if (dispatch_started_) {\n"
                "throw std::runtime_error(",
            ),
            "complete commits pending evidence": (
                "commit_pending_entropy_schedule_update(pufferl_);",
                "discard_pending_entropy_schedule_update(pufferl_);",
            ),
            "commit failure poisons training": (
                "} catch (...) {\n"
                "pufferl_.training_failed = true;",
                "} catch (...) {\n"
                "pufferl_.training_failed = false;",
            ),
            "commit failure clears deferred publication": (
                "} catch (...) {\n"
                "pufferl_.training_failed = true;\n"
                "pufferl_.defer_entropy_schedule_commit = false;",
                "} catch (...) {\n"
                "pufferl_.training_failed = true;\n"
                "pufferl_.defer_entropy_schedule_commit = true;",
            ),
            "commit failure clears pending evidence": (
                "pufferl_.training_failed = true;\n"
                "pufferl_.defer_entropy_schedule_commit = false;\n"
                "pufferl_.entropy_schedule_commit_pending = false;\n"
                "throw;",
                "pufferl_.training_failed = true;\n"
                "pufferl_.defer_entropy_schedule_commit = false;\n"
                "pufferl_.entropy_schedule_commit_pending = true;\n"
                "throw;",
            ),
            "commit failure rethrows": (
                "pufferl_.entropy_schedule_commit_pending = false;\n"
                "throw;\n"
                "}\n"
                "pufferl_.defer_entropy_schedule_commit = false;",
                "pufferl_.entropy_schedule_commit_pending = false;\n"
                "return;\n"
                "}\n"
                "pufferl_.defer_entropy_schedule_commit = false;",
            ),
            "successful commit clears deferred publication": (
                "}\n"
                "pufferl_.defer_entropy_schedule_commit = false;\n"
                "complete_ = true;\n"
                "}",
                "}\n"
                "pufferl_.defer_entropy_schedule_commit = true;\n"
                "complete_ = true;\n"
                "}",
            ),
            "successful commit marks transaction complete": (
                "pufferl_.defer_entropy_schedule_commit = false;\n"
                "complete_ = true;\n"
                "}",
                "pufferl_.defer_entropy_schedule_commit = false;\n"
                "complete_ = false;\n"
                "}",
            ),
            "dispatch flag starts false": (
                "bool dispatch_started_ = false;",
                "bool dispatch_started_ = true;",
            ),
            "complete flag starts false": (
                "bool complete_ = false;",
                "bool complete_ = true;",
            ),
        }
        for invariant, (before, after) in mutations.items():
            with self.subTest(invariant=invariant):
                self.assertEqual(
                    canonical.count(before),
                    1,
                    f"mutation fixture is ambiguous for {invariant}",
                )
                mutated_transaction = canonical.replace(
                    before,
                    after,
                    1,
                )
                mutated = selected.replace(
                    transaction,
                    mutated_transaction,
                    1,
                )
                with self.assertRaisesRegex(
                    AssertionError,
                    "closed public entropy transaction class",
                ):
                    _assert_closed_native_public_train(mutated)

    def test_warmup_restores_scalar_and_all_schedule_evidence(self) -> None:
        source = _source_or_additions("src/pufferlib.cu")
        for marker in (
            "entropy_schedule_update_count",
            "entropy_loss_minibatch_count",
            "entropy_first_update",
            "entropy_last_update",
            "entropy_first_coefficient",
            "entropy_last_coefficient",
            "entropy_schedule_valid",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, source)
        self.assertGreaterEqual(
            source.count("ppo_bufs_puf.ent_coef.data"),
            3,
            "allocate/use/reset must all name the stable scalar",
        )

    def test_tail_validity_cuda_read_failure_poisons_training_object(self) -> None:
        selected = _selected_puffer_source("src/bindings.cu")
        source = (
            selected
            if selected is not None
            else _added_text(ROLLOUT_PATCH)
        )
        failure = source.index(
            '"training could not read tail-record validity"'
        )
        helper = source.rfind(
            "require_fresh_training_tail",
            0,
            failure,
        )
        self.assertNotEqual(
            helper,
            -1,
            "tail validation must have one named rollout-owned helper",
        )
        copy_at = source.find("cudaMemcpy(", helper, failure)
        self.assertNotEqual(
            copy_at,
            -1,
            "the helper must read the device validity tensor before "
            "reporting a read failure",
        )
        branch = source.rfind(
            "if (status != cudaSuccess)",
            helper,
            failure,
        )
        self.assertNotEqual(
            branch,
            -1,
            "the CUDA status must control the failure branch",
        )
        self.assertIn(
            "pufferl.training_failed = true;",
            source[branch:failure],
            "a CUDA failure must not leave the public training object "
            "nominally reusable; the latch belongs to the earliest "
            "rollout-owned tail-read block so the causal patch stack remains "
            "independently reverse-applicable",
        )

    def test_entropy_coefficient_telemetry_is_bit_exact_for_irregular_rows(
        self,
    ) -> None:
        coefficient = _f32(0.001)
        row_count = 7
        reciprocal = _f32(_f32(1.0) / _f32(row_count))
        legacy_contribution = _f32(coefficient * reciprocal)
        legacy_lanes = [
            legacy_contribution if index < row_count else _f32(0.0)
            for index in range(256)
        ]
        legacy = _tree_reduce_f32(legacy_lanes)
        self.assertNotEqual(
            _f32_bits(legacy),
            _f32_bits(coefficient),
            "NT=7 must remain a non-vacuous oracle for the legacy "
            "coefficient-times-inverse telemetry",
        )
        exact_lanes = [
            coefficient if index == 0 else _f32(0.0)
            for index in range(256)
        ]
        exact = _tree_reduce_f32(exact_lanes)
        self.assertEqual(_f32_bits(exact), _f32_bits(coefficient))

        source = _source_or_additions("src/pufferlib.cu")
        exact_assignment = (
            "block_losses[LOSS_ENT_COEF][tid] = "
            "idx == 0 ? ent_coef : 0.0f;"
        )
        self.assertEqual(source.count(exact_assignment), 1)
        self.assertNotIn(
            "block_losses[LOSS_ENT_COEF][tid] = ent_coef * inv_NT;",
            source,
        )

        profile = _source_or_additions("tests/profile_kernels.cu")
        for marker in (
            "PPO_ENTROPY_TELEMETRY_IRREGULAR_ROWS = 7",
            "PPO_ENTROPY_TELEMETRY_IRREGULAR_ROWS, A)",
            "result.losses[LOSS_ENT_COEF] !="
            " result.requested_coefficient",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, " ".join(profile.split()))

        mutated = source.replace(exact_assignment, (
            "block_losses[LOSS_ENT_COEF][tid] = ent_coef * inv_NT;"
        ), 1)
        self.assertNotIn(exact_assignment, mutated)
        self.assertIn(
            "block_losses[LOSS_ENT_COEF][tid] = ent_coef * inv_NT;",
            mutated,
        )

    def test_profile_fixture_uses_mutable_device_coefficient(self) -> None:
        source = _source_or_additions("tests/profile_kernels.cu")
        for marker in (
            "ent_coef_t",
            "alloc_register(&p->alloc, &p->ent_coef_t)",
            ".ent_coef = p->ent_coef_t.data",
            "LOSS_ENT_COEF",
            "LOSS_ENT_TERM",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, source)


class EntropyValidationAndTelemetrySourceTests(unittest.TestCase):
    def test_sweep_values_cross_the_strict_config_boundary_as_builtins(
        self,
    ) -> None:
        source = _source_or_additions("pufferlib/sweep.py")
        expected = (
            "value = spaces[name].unnormalize(flat_sample[idx])",
            "if isinstance(value, np.generic):",
            "value = value.item()",
            "params[name] = value",
        )
        if _selected_puffer_source("pufferlib/sweep.py") is not None:
            expected += ("idx += 1",)
        _require_exact_subsequence(
            source,
            expected,
            "NumPy sweep scalar normalization",
        )
        self.assertNotIn(
            "params[name] = spaces[name].unnormalize(flat_sample[idx])",
            source,
        )

    def test_selected_sweep_values_pass_strict_config_validation(
        self,
    ) -> None:
        root = os.environ.get("PUFFER_ENTROPY_TEST_ROOT")
        python = os.environ.get("PUFFER_TORCH_TEST_PYTHON")
        if not root or not python:
            self.skipTest(
                "selected Puffer root and Python are not configured"
            )
        probe = r"""
import json
import sys

import numpy as np

sys.path.insert(0, sys.argv[1])
from pufferlib import pufferl
from pufferlib.sweep import Hyperparameters

sweep = {
    "metric": "score",
    "goal": "maximize",
    "train": {
        "ent_coef": {
            "distribution": "log_normal",
            "min": 0.001,
            "max": 0.1,
            "scale": "auto",
        },
        "replay_ratio": {
            "distribution": "uniform",
            "min": 0.5,
            "max": 2.0,
            "scale": "auto",
        },
        "minibatch_size": {
            "distribution": "int_uniform",
            "min": 4,
            "max": 8,
            "scale": "auto",
        },
    },
}
suggested = Hyperparameters(sweep, verbose=False).to_dict(
    np.asarray([0.0, 0.0, -1.0], dtype=np.float64)
)
train = suggested["train"]
types = {
    name: type(train[name]).__name__
    for name in ("ent_coef", "replay_ratio", "minibatch_size")
}
if types != {
    "ent_coef": "float",
    "replay_ratio": "float",
    "minibatch_size": "int",
}:
    raise AssertionError(types)
validated = pufferl.validate_entropy_schedule_config({
    "train": {
        "total_timesteps": 32,
        "horizon": 4,
        "minibatch_size": train["minibatch_size"],
        "replay_ratio": train["replay_ratio"],
        "ent_coef": train["ent_coef"],
        "min_ent_coef_ratio": 0.1,
        "anneal_ent_coef": True,
    },
    "vec": {"total_agents": 4},
})
print(json.dumps({
    "types": types,
    "ent_coef": validated["base_coefficient"],
    "minibatches_per_update": validated["minibatches_per_update"],
}, sort_keys=True))
"""
        result = subprocess.run(
            [python, "-c", probe, str(Path(root).resolve())],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            payload["types"],
            {
                "ent_coef": "float",
                "minibatch_size": "int",
                "replay_ratio": "float",
            },
        )
        self.assertGreater(payload["minibatches_per_update"], 0)

    def test_torch_helper_uses_applied_fp32_value_and_success_commit(self) -> None:
        source = _source_or_additions("pufferlib/torch_pufferl.py")
        for marker in (
            f'ENTROPY_SCHEDULE_CONTRACT = "{CONTRACT}"',
            "def entropy_schedule_point(",
            '"c_real"',
            '"c_applied"',
            "current_ent_coef",
            "entropy_term",
            "total_loss",
            "entropy_schedule_contract",
            "entropy_applied_update_index",
            "entropy_loss_minibatch_count",
            "if self.epoch < 0 or self.epoch >= self.total_epochs:",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, source)
        self.assertNotIn(
            "if self.epoch >= self.total_epochs:",
            source,
            "Torch must reject negative as well as exhausted update indices",
        )
        self.assertNotIn(
            "- config['ent_coef']*entropy_loss",
            source,
            "Torch may not retain the fixed-base objective",
        )
        self.assertNotIn(
            "self.total_epochs = max(1,",
            source,
            "zero-update configurations must fail rather than coerce",
        )

    def test_raw_validation_precedes_native_narrowing_and_cuda_discovery(
        self,
    ) -> None:
        source = _source_or_additions("src/bindings.cu")
        for marker in (
            "anneal_ent_coef must be an exact boolean or 0/1",
            "ent_coef must be finite, nonnegative, and representable as float32",
            "min_ent_coef_ratio must be finite and in [0, 1]",
            "training has zero complete updates",
            "training has zero minibatches per update",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, source)

        selected = _selected_puffer_source("src/bindings.cu")
        if selected is not None:
            validate_at = selected.index(
                "anneal_ent_coef must be an exact boolean or 0/1"
            )
            narrow_at = selected.index("hypers.anneal_ent_coef =", validate_at)
            cuda_at = selected.index("cudaGetDeviceCount", validate_at)
            self.assertLess(validate_at, narrow_at)
            self.assertLess(validate_at, cuda_at)

    def test_shared_python_validation_is_explicit_and_repeated_per_rank(
        self,
    ) -> None:
        source = _source_or_additions("pufferlib/pufferl.py")
        for marker in (
            "validate_entropy_schedule_config",
            "training has zero complete updates",
            "training has zero minibatches per update",
            "validate_config(args)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, source)
        selected = _selected_puffer_source("pufferlib/pufferl.py")
        if selected is not None:
            validator = selected[
                selected.index("def validate_entropy_schedule_config"):
                selected.index("def guard_scripted_training")
            ]
            self.assertNotIn("assert ", validator)
            train = selected[selected.index("def train("):]
            self.assertGreaterEqual(
                train.count("validate_config(args)"),
                2,
                "effective per-rank configuration must be revalidated",
            )

    def test_compiled_markers_and_closed_interval_telemetry_exist(self) -> None:
        for relative in ("src/bindings.cu", "src/bindings_cpu.cpp"):
            source = _source_or_additions(relative)
            self.assertIn(
                f'm.attr("entropy_schedule_contract") = "{CONTRACT}";',
                source,
            )

        native = _source_or_additions("src/bindings.cu")
        for marker in (
            '"schedule_update_count"',
            '"loss_minibatch_count"',
            '"first_update_index"',
            '"last_update_index"',
            '"first_effective_coefficient"',
            '"last_effective_coefficient"',
            '"interval_role"',
            '"entropy_term"',
            '"entropy_coefficient"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, native)


if __name__ == "__main__":
    unittest.main()
