#!/usr/bin/env python3
"""Exercise the sealed F5 role through a freshly built Puffer CPU module."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import subprocess
import sys
import tempfile
from typing import Any


PUFFER_COMMIT = "9836f0d2e78889c1aaf189c04d161b6fc61a9386"
SCHEMA = "bloodbowl-f5-puffer-module-v1"
FIXTURE_ROLE = "f5-fixed-state-v1"
MATCH_SHA256 = (
    "aab28e6e08184d05a6912d033899916d0228984c38c87e606ee3f2a5d25ac9f2"
)
BBS_SHA256 = (
    "0fe8f1ea3f0470bef2c43709947d2bd3a9fd418b0b7b9d5ca93003e720702e71"
)
BUNDLE_SHA256 = (
    "c984e22178901539157be062764dcaff1efac345836dffb5be17a5b7537447a1"
)
TRACE_SHA256 = (
    "456e336e5eaa92e4e5fdedfb753d237a163e9a8e4e58ff09fa8979d2a91f4300"
)
REFERENCE_HEADS = (
    (6, 6, 390),
    (7, 0, 390),
    (9, 32, 254),
    (9, 32, 229),
    (9, 32, 204),
    (9, 32, 179),
    (9, 32, 154),
    (9, 32, 129),
)
NULL_HEADS = (0, 32, 390)
REFERENCE_ACTIVE_COUNTS = (12, 4, 9, 9, 9, 9, 9, 9)
REFERENCE_JOINT_SUPPORT_SHA256 = (
    "fba790cb22fd9e3a77878bddb44ffc2a6e27d6af0dad3864dc9a1c2612c9196a",
    "dab385f74466b09e7e2b579206988befa1025981c1f483dda7bbcf2cf5bac4c2",
    "952549d09d22b479366f8e0c65d48ad5f4820fb5201f97a8d91922d8fc7fa762",
    "8d94ab01617a665c0ea7c1bd0bda24433e6825ad07f6ae989e5c09b81805692c",
    "94fdb992e4aeffc8d473b894f8fd833a37cf3ae6dc54a06cd0de1a27b0681486",
    "ab5ad5f08495989d9cde19b317772f165c288d44a73a95611dd34e350896fce4",
    "40791203d17602c23c01b438a1c003fb1e5b776bd93294dfb66d23709d09408f",
    "27aab4fac0fb3cde8405cb49908ad75db6a8a60358c8026b0fef60ca987e8dc3",
)
REFERENCE_OBS_SHA256 = (
    (
        "81408d6974177509745d73ceca653ca0f5d976b7f163c889543959bc14172ecc",
        "a9d024952b2473131f16e721f37add745ac27443cc69e3f31e312d254181bb7f",
    ),
    (
        "5d461c23dc27914ce6b780cd1a6c42f0b759f53b18406111324fbd2956e7fee3",
        "33ba632d7bd43a1d3b37394f776eaa6de824cc0a7964d3391da40f064b5dbec7",
    ),
    (
        "e291d9db2d97209de397c765c8a31bb6079b55f686f8da4ad5726a44fe48caaf",
        "509cbf35f077a87a46b6bf8be9b196826de3d85ea942b9ccbcddd40eb25f0104",
    ),
    (
        "c9a6ead287cce1f42684d415421c87c1a001da5c9f5e6ca4f6bd874f82e469f1",
        "b5af4abc580a6622eddf6a9bfa0348aeb804e67343da4a864bb03c120d00948f",
    ),
    (
        "2a91a027d75992e2407998da98151ba5c7dd899accca66a1ccd74a1240534acc",
        "10c60ffa1c107f5ddb7dce888ae5bf663f7613ad47571abb0f585cf95f4afe2e",
    ),
    (
        "39520dbcadbee8e8f51326cc4951065935cf9e5c0a0accb47548b324dad039f9",
        "b24705f1fa1a6842817a623f964cacb2fb40cccb63d2d043cddf58fc43c15c0e",
    ),
    (
        "4fdbb57025293225c236c527fab0e36ffee8a0a6df3a140023f8e4be6828842c",
        "24bf5cc1fbb280bab644c2ba888202a7a199fcf20c5c644ceec7e5738bf2c848",
    ),
    (
        "f4795792b0f89c61e0c60503b67f515181035bfa24d678139956518c9f83da81",
        "9c2a815fef0df5e9a8f93214017f3eebdc501c6041776eeb59d6dc2700804967",
    ),
)
REFERENCE_MASK_SHA256 = (
    (
        "dcb8b53d29f4a08a41df6076eed7c44166ed4071de198ac79560df93dc3f840e",
        "99037d2f21c321449a7c60969f63aed41d6dd8f9b9c6283d03fb485003b96017",
    ),
    (
        "77381f23172abd74a314157a16bff2a6d18958da13e17bbd821a478372f38f35",
        "99037d2f21c321449a7c60969f63aed41d6dd8f9b9c6283d03fb485003b96017",
    ),
    (
        "c303cd14125fb72c2b5554d55d7fee3ee73b24650b9a444b8c48805c3a7286a5",
        "99037d2f21c321449a7c60969f63aed41d6dd8f9b9c6283d03fb485003b96017",
    ),
    (
        "fead28355d630bf3e340d1c8b6c9bef92d83d95dbea466a8fd54fa5d92bc91b9",
        "99037d2f21c321449a7c60969f63aed41d6dd8f9b9c6283d03fb485003b96017",
    ),
    (
        "f032eda7dcbfa891fb2c15007f53baeb816be6658117c59aa042e7fbd1319cac",
        "99037d2f21c321449a7c60969f63aed41d6dd8f9b9c6283d03fb485003b96017",
    ),
    (
        "7b5543c14a910c9f08eec1cf61804b4165bb61e24e46555392556bd97bd99de7",
        "99037d2f21c321449a7c60969f63aed41d6dd8f9b9c6283d03fb485003b96017",
    ),
    (
        "9dc6ae857d37b33b3c1a120fea611d2329b53c7e0996bb28c9638482be37bade",
        "99037d2f21c321449a7c60969f63aed41d6dd8f9b9c6283d03fb485003b96017",
    ),
    (
        "126058b29e7ccb1b02a38aac8c60d7872bb466c38b7b737c9e065ab5302e9504",
        "99037d2f21c321449a7c60969f63aed41d6dd8f9b9c6283d03fb485003b96017",
    ),
)
RANDOM_MODULE_EPISODES = 1000
RANDOM_MODULE_SEED = 245
RANDOM_ZERO_INTEGRITY_LOG_KEYS = (
    "illegal_frac",
    "error_episodes",
    "reward_clip_frac",
    "reward_clip_frac_nonzero",
    "reward_clip_excess",
    "reward_clip_terminal_samples_per_episode",
    "reward_clip_nonterminal_samples_per_episode",
    "reward_clipped_samples_per_episode",
    "reward_nonfinite_frac",
    "reward_nonfinite_samples_per_episode",
    "reward_clip_episodes",
    "reward_nonfinite_episodes",
    "reward_component_mismatch_samples_per_episode",
    "reward_component_nonfinite_samples_per_episode",
    "reward_component_residual",
    "reward_terminal_suppressed_signed",
    "reward_terminal_suppressed_abs",
    "reward_clip_signed_delta",
    "reward_postclip_return",
    "reward_nonzero_samples_per_episode",
    "reward_episode_abs_max_mean",
    "statmatch_term",
    "demo_episodes",
    "demo_fallbacks",
    "demo_uniform_episode_frac_all",
    "demo_endzone_episode_frac_all",
    "demo_pickup_episode_frac_all",
    "demo_postkick_episode_frac_all",
    "demo_pass_episode_frac_all",
    "state_bank_config_episode_frac_all",
    "demo_selector_threshold_mean_configured",
    "demo_selector_eligible_mean_configured",
    "reward_component_setup_done",
    "reward_component_setup_autofix",
    "reward_component_ball_gain",
    "reward_component_ball_loss",
    "reward_component_distance_ball",
    "reward_component_distance_endzone",
    "reward_component_injury_inflicted",
    "reward_component_injury_taken",
    "reward_component_send_off",
    "reward_component_touchback",
    "reward_component_surf_inflicted",
    "reward_component_surf_taken",
    "reward_component_block_exposure",
    "reward_component_block_self_injury",
    "reward_component_block_sequence",
    "reward_component_block_turnover",
    "reward_component_possession",
    "reward_component_block_assist",
    "reward_component_rush",
    "reward_component_carrier_exposure",
    "reward_component_carrier_exposure_soft",
    "reward_component_carrier_threat",
    "reward_component_defensive_threat",
    "reward_component_defensive_threat_soft",
    "reward_component_touchdown",
    "reward_component_result_winloss",
    "reward_component_result_draw",
    "reward_component_statmatch",
    *(f"hist_n_bank_{index}" for index in range(8)),
)

ROOT = Path(__file__).resolve().parents[1]
ENV_CONFIG_PATH = ROOT / "training/f5_trainability_env.json"


def _load_environment_config() -> dict[str, int | float]:
    try:
        value = json.loads(ENV_CONFIG_PATH.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModuleCheckError(
            f"cannot load exact F5 environment config: {exc}"
        ) from exc
    if (
        not isinstance(value, dict)
        or len(value) != 51
        or any(
            not isinstance(key, str)
            or isinstance(item, bool)
            or not isinstance(item, (int, float))
            for key, item in value.items()
        )
    ):
        raise ModuleCheckError(
            "exact F5 environment config is not a 51-key numeric object"
        )
    return value


class ModuleCheckError(RuntimeError):
    """The built module did not satisfy the sealed F5 contract."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: Any) -> None:
    payload = (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("ascii")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _git_output(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.stdout.strip()


def _path_beneath(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _require_module_contract(module: Any) -> dict[str, Any]:
    expected: dict[str, Any] = {
        "env_name": "bloodbowl",
        "gpu": 0,
        "observation_abi": "obs-v6",
        "observation_version": 6,
        "action_abi": "exact-joint-v1",
        "rollout_transition_contract": "tail-bootstrap-v1",
        "state_bank_kind": 0,
        "state_bank_kind_name": "none",
        "qualification_fixture_enabled": True,
        "qualification_fixture_role": FIXTURE_ROLE,
        "qualification_fixture_schema": "bloodbowl-trainability-task-v1",
        "qualification_fixture_qualification_only": True,
        "qualification_fixture_match_sha256": MATCH_SHA256,
        "qualification_fixture_bbs_sha256": BBS_SHA256,
        "qualification_fixture_bundle_sha256": BUNDLE_SHA256,
        "qualification_fixture_bbs_source_id": 0xA9000019,
        "qualification_fixture_authored_source_id": 0xAE00001A,
        "qualification_fixture_reference_trace_schema":
            "bloodbowl-f5-reference-trace-v1",
        "qualification_fixture_reference_trace_sha256": TRACE_SHA256,
        "qualification_fixture_max_decisions": 8,
        "qualification_fixture_reward_contract":
            "touchdown-zero-sum-only-v1",
    }
    observed: dict[str, Any] = {}
    for attribute, wanted in expected.items():
        if not hasattr(module, attribute):
            raise ModuleCheckError(f"compiled module lacks {attribute}")
        value = getattr(module, attribute)
        if type(value) is not type(wanted) or value != wanted:
            raise ModuleCheckError(
                f"compiled {attribute} is {value!r}; expected {wanted!r}"
            )
        observed[attribute] = value
    environment_source = getattr(
        module, "qualification_fixture_environment_source_sha256", None
    )
    if (
        not isinstance(environment_source, str)
        or len(environment_source) != 64
        or any(character not in "0123456789abcdef" for character in environment_source)
    ):
        raise ModuleCheckError(
            "compiled qualification environment-source identity is invalid"
        )
    observed["qualification_fixture_environment_source_sha256"] = (
        environment_source
    )
    return observed


def _ctypes_bytes(pointer: int, size: int) -> bytes:
    if pointer <= 0 or size <= 0:
        raise ModuleCheckError("module exposed a null or invalid buffer")
    return bytes((ctypes.c_ubyte * size).from_address(pointer))


def _canonical_sha256(value: Any) -> str:
    payload = (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _row_hashes(payload: bytes, row_size: int) -> list[str]:
    if row_size <= 0 or len(payload) != 2 * row_size:
        raise ModuleCheckError("module row buffer has an unexpected size")
    return [
        hashlib.sha256(payload[offset : offset + row_size]).hexdigest()
        for offset in (0, row_size)
    ]


def _joint_rows(vec: Any) -> list[list[tuple[int, int, int]]]:
    capacity = int(vec.joint_action_capacity)
    if capacity <= 0:
        raise ModuleCheckError("module exposes no exact joint support")
    offsets = (ctypes.c_int * vec.total_agents).from_address(
        int(vec.joint_action_offsets_ptr)
    )
    counts = (ctypes.c_int * vec.total_agents).from_address(
        int(vec.joint_action_counts_ptr)
    )
    packed = (ctypes.c_uint32 * capacity).from_address(
        int(vec.joint_actions_ptr)
    )
    rows: list[list[tuple[int, int, int]]] = []
    expected_offset = 0
    for row in range(vec.total_agents):
        offset = int(offsets[row])
        count = int(counts[row])
        if (
            offset != expected_offset
            or count <= 0
            or offset + count > capacity
        ):
            raise ModuleCheckError(
                f"joint-support row {row} is not a contiguous packed slice"
            )
        decoded = []
        for index in range(offset, offset + count):
            value = int(packed[index])
            decoded.append(
                (value & 0x3FF, (value >> 10) & 0x3FF, value >> 20)
            )
        if len(set(decoded)) != len(decoded):
            raise ModuleCheckError(
                f"joint-support row {row} contains a projection collision"
            )
        rows.append(decoded)
        expected_offset += count
    return rows


def _find_reference_row(
    rows: list[list[tuple[int, int, int]]],
    expected: tuple[int, int, int],
    decision_index: int,
) -> tuple[int, int, str]:
    if decision_index < 0 or decision_index >= len(REFERENCE_HEADS):
        raise ModuleCheckError("reference decision index is out of range")
    if len(rows) != 2:
        raise ModuleCheckError("reference support does not have two agent rows")
    active = [row for row, support in enumerate(rows) if expected in support]
    if len(active) != 1:
        raise ModuleCheckError(
            f"reference tuple {expected!r} occurs in {len(active)} rows"
        )
    active_row = active[0]
    waiting_row = 1 - active_row
    if active_row != 0 or waiting_row != 1:
        raise ModuleCheckError(
            "reference route is not Home-active/Away-waiting"
        )
    if rows[waiting_row] != [NULL_HEADS]:
        raise ModuleCheckError(
            f"waiting support is not the null singleton: {rows[waiting_row]!r}"
        )
    if len(rows[active_row]) != REFERENCE_ACTIVE_COUNTS[decision_index]:
        raise ModuleCheckError(
            f"decision {decision_index + 1} active packed-support count differs"
        )
    digest = _canonical_sha256(rows)
    if digest != REFERENCE_JOINT_SUPPORT_SHA256[decision_index]:
        raise ModuleCheckError(
            f"decision {decision_index + 1} packed joint support differs"
        )
    return active_row, waiting_row, digest


def _assert_environment_abi(vec: Any) -> None:
    if (
        vec.total_agents != 2
        or vec.obs_size != 2782
        or list(vec.act_sizes) != [30, 33, 391]
        or vec.action_mask_size != 454
        or vec.joint_action_capacity != 8974
    ):
        raise ModuleCheckError("compiled vector ABI differs from F5 contract")


def _finite_log_number(log: dict[str, Any], key: str) -> float:
    value = log.get(key)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise ModuleCheckError(f"module log {key} is not a finite number")
    return float(value)


def _exact_log(log: dict[str, Any]) -> dict[str, float]:
    expected = {
        "n": 1.0,
        "tds_t0": 1.0,
        "tds_t1": 0.0,
        "episode_length": 8.0,
        "episode_return": 1.0,
        "score_diff": 1.0,
        "reward_component_touchdown": 1.0,
        "reward_postclip_return": 1.0,
        "reward_samples_per_episode": 16.0,
        "reward_nonzero_samples_per_episode": 2.0,
        "illegal_frac": 0.0,
        "error_episodes": 0.0,
        "reward_clip_episodes": 0.0,
        "reward_clip_excess": 0.0,
        "reward_clip_frac": 0.0,
        "reward_clip_frac_nonzero": 0.0,
        "reward_nonfinite_episodes": 0.0,
        "reward_nonfinite_frac": 0.0,
        "reward_nonfinite_samples_per_episode": 0.0,
        "reward_component_mismatch_samples_per_episode": 0.0,
        "reward_component_nonfinite_samples_per_episode": 0.0,
        "reward_component_residual": 0.0,
        "reward_terminal_suppressed_abs": 0.0,
        "reward_terminal_suppressed_signed": 0.0,
        "demo_episodes": 0.0,
        "demo_fallbacks": 0.0,
        "state_bank_config_episode_frac_all": 0.0,
        **{f"hist_n_bank_{index}": 0.0 for index in range(8)},
    }
    result: dict[str, float] = {}
    for key, wanted in expected.items():
        value = _finite_log_number(log, key)
        if value != wanted:
            raise ModuleCheckError(
                f"module log {key} is {value!r}; expected {wanted}"
            )
        result[key] = value
    return result


def _run_direct_oracle(
    module: Any,
    environment_config: dict[str, int | float],
) -> dict[str, Any]:
    vec = None
    transitions: list[dict[str, Any]] = []
    try:
        vec = module.create_vec(
            {
                "vec": {"total_agents": 2, "num_buffers": 1},
                "env": dict(environment_config),
            },
            gpu=0,
        )
        _assert_environment_abi(vec)
        vec.reset()
        initial_obs = _ctypes_bytes(vec.obs_ptr, 2 * vec.obs_size)
        initial_mask = _ctypes_bytes(
            vec.action_mask_ptr, 2 * vec.action_mask_size
        )
        rewards = (ctypes.c_float * 2).from_address(int(vec.rewards_ptr))
        terminals = (ctypes.c_float * 2).from_address(int(vec.terminals_ptr))
        actions = (ctypes.c_float * 6)()
        final_active = -1
        final_waiting = -1

        for index, expected in enumerate(REFERENCE_HEADS):
            decision = index + 1
            obs = _ctypes_bytes(vec.obs_ptr, 2 * vec.obs_size)
            mask = _ctypes_bytes(
                vec.action_mask_ptr, 2 * vec.action_mask_size
            )
            obs_sha256 = _row_hashes(obs, vec.obs_size)
            mask_sha256 = _row_hashes(mask, vec.action_mask_size)
            if obs_sha256 != list(REFERENCE_OBS_SHA256[index]):
                raise ModuleCheckError(
                    f"decision {decision} observation identity differs"
                )
            if mask_sha256 != list(REFERENCE_MASK_SHA256[index]):
                raise ModuleCheckError(
                    f"decision {decision} action-mask identity differs"
                )
            rows = _joint_rows(vec)
            active, waiting, support_sha256 = _find_reference_row(
                rows, expected, index
            )
            final_active, final_waiting = active, waiting
            for row in range(2):
                base = 3 * row
                values = expected if row == active else NULL_HEADS
                actions[base : base + 3] = values
            vec.cpu_step(ctypes.addressof(actions))
            row = {
                "decision": decision,
                "heads": list(expected),
                "active_row": active,
                "waiting_row": waiting,
                "joint_counts": [len(support) for support in rows],
                "joint_support_sha256": support_sha256,
                "obs_sha256": obs_sha256,
                "mask_sha256": mask_sha256,
                "rewards": [float(rewards[0]), float(rewards[1])],
                "terminals": [float(terminals[0]), float(terminals[1])],
            }
            if decision < 8 and (
                row["rewards"] != [0.0, 0.0]
                or row["terminals"] != [0.0, 0.0]
            ):
                raise ModuleCheckError(
                    f"decision {decision} emitted an early reward/terminal"
                )
            transitions.append(row)

        if final_active != 0 or final_waiting != 1:
            raise ModuleCheckError("reference route did not retain Home/Away rows")
        if (
            rewards[final_active] != 1.0
            or rewards[final_waiting] != -1.0
            or list(terminals) != [1.0, 1.0]
        ):
            raise ModuleCheckError("eighth transition lost reward or terminal")
        autoreset_obs = _ctypes_bytes(vec.obs_ptr, 2 * vec.obs_size)
        autoreset_mask = _ctypes_bytes(
            vec.action_mask_ptr, 2 * vec.action_mask_size
        )
        if autoreset_obs != initial_obs or autoreset_mask != initial_mask:
            raise ModuleCheckError("autoreset did not reproduce initial buffers")
        reset_rows = _joint_rows(vec)
        _find_reference_row(reset_rows, REFERENCE_HEADS[0], 0)
        exact_log = _exact_log(vec.log())
    finally:
        if vec is not None:
            vec.close()

    return {
        "transitions": transitions,
        "autoreset": {
            "obs_sha256": hashlib.sha256(initial_obs).hexdigest(),
            "mask_sha256": hashlib.sha256(initial_mask).hexdigest(),
            "exact": True,
        },
        "log": exact_log,
    }


def _run_two_environment_oracle(
    module: Any,
    environment_config: dict[str, int | float],
) -> dict[str, Any]:
    """Prove vector seed derivation remains usable beyond environment zero."""

    vec = None
    try:
        vec = module.create_vec(
            {
                "vec": {"total_agents": 4, "num_buffers": 1},
                "env": dict(environment_config),
            },
            gpu=0,
        )
        if (
            vec.total_agents != 4
            or vec.obs_size != 2782
            or list(vec.act_sizes) != [30, 33, 391]
            or vec.action_mask_size != 454
            or vec.joint_action_capacity != 17_948
        ):
            raise ModuleCheckError(
                "two-environment vector ABI differs from F5 contract"
            )
        vec.reset()
        initial_obs = _ctypes_bytes(vec.obs_ptr, 4 * vec.obs_size)
        initial_mask = _ctypes_bytes(
            vec.action_mask_ptr, 4 * vec.action_mask_size
        )
        if (
            initial_obs[: 2 * vec.obs_size]
            != initial_obs[2 * vec.obs_size :]
            or initial_mask[: 2 * vec.action_mask_size]
            != initial_mask[2 * vec.action_mask_size :]
        ):
            raise ModuleCheckError(
                "identical F5 fixtures do not reset to identical buffers"
            )
        rewards = (ctypes.c_float * 4).from_address(int(vec.rewards_ptr))
        terminals = (ctypes.c_float * 4).from_address(int(vec.terminals_ptr))
        actions = (ctypes.c_float * 12)()
        for index, expected in enumerate(REFERENCE_HEADS):
            rows = _joint_rows(vec)
            if len(rows) != 4:
                raise ModuleCheckError(
                    "two-environment vector did not expose four support rows"
                )
            for environment_index in range(2):
                first = 2 * environment_index
                _find_reference_row(rows[first : first + 2], expected, index)
                actions[3 * first : 3 * first + 3] = expected
                actions[3 * (first + 1) : 3 * (first + 1) + 3] = NULL_HEADS
            vec.cpu_step(ctypes.addressof(actions))
            if index < 7 and (
                list(rewards) != [0.0, 0.0, 0.0, 0.0]
                or list(terminals) != [0.0, 0.0, 0.0, 0.0]
            ):
                raise ModuleCheckError(
                    "two-environment route emitted an early reward/terminal"
                )
        if (
            list(rewards) != [1.0, -1.0, 1.0, -1.0]
            or list(terminals) != [1.0, 1.0, 1.0, 1.0]
        ):
            raise ModuleCheckError(
                "two-environment route lost terminal touchdown outcomes"
            )
        autoreset_obs = _ctypes_bytes(vec.obs_ptr, 4 * vec.obs_size)
        autoreset_mask = _ctypes_bytes(
            vec.action_mask_ptr, 4 * vec.action_mask_size
        )
        if autoreset_obs != initial_obs or autoreset_mask != initial_mask:
            raise ModuleCheckError(
                "two-environment autoreset did not reproduce initial buffers"
            )
        rows = _joint_rows(vec)
        for environment_index in range(2):
            first = 2 * environment_index
            _find_reference_row(
                rows[first : first + 2], REFERENCE_HEADS[0], 0
            )
    finally:
        if vec is not None:
            vec.close()

    return {
        "total_agents": 4,
        "environments": 2,
        "episode_decisions": 8,
        "completed_episodes": 2,
        "terminal_rewards": [1.0, -1.0, 1.0, -1.0],
        "all_terminal": True,
        "exact_autoreset": True,
    }


class _CountedCpuVec:
    """Delegate to a real VecEnv while making a ninth step a hard failure."""

    def __init__(self, vec: Any, maximum_steps: int):
        self._vec = vec
        self.maximum_steps = maximum_steps
        self.cpu_steps = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._vec, name)

    def cpu_step(self, action_pointer: int) -> None:
        if self.cpu_steps >= self.maximum_steps:
            raise ModuleCheckError("Torch collector attempted a ninth action")
        self.cpu_steps += 1
        self._vec.cpu_step(action_pointer)


def _runtime_identity(puffer_root: Path, torch: Any) -> dict[str, Any]:
    venv = (puffer_root / ".venv").resolve(strict=True)
    if Path(sys.prefix).resolve(strict=True) != venv:
        raise ModuleCheckError("module checker is not running in Puffer's venv")
    torch_path = Path(torch.__file__).resolve(strict=True)
    if not _path_beneath(torch_path, venv):
        raise ModuleCheckError("Torch was not imported from Puffer's venv")
    if torch.version.cuda is not None or torch.cuda.is_available():
        raise ModuleCheckError("F5 foundation requires a CPU-only Torch runtime")
    distributions_path = venv / "f5_trainability_distributions.json"
    digest_path = venv / "f5_trainability_distributions.sha256"
    collector_path = (
        puffer_root / "pufferlib/torch_pufferl.py"
    ).resolve(strict=True)
    distributions_sha256 = _sha256_file(distributions_path)
    try:
        digest_payload = digest_path.read_text(encoding="ascii")
        distributions = json.loads(
            distributions_path.read_text(encoding="ascii")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModuleCheckError(
            f"cannot read sealed Puffer distribution identity: {exc}"
        ) from exc
    if digest_payload != distributions_sha256 + "\n":
        raise ModuleCheckError("sealed Puffer distribution digest differs")
    expected_torch_version = {
        "darwin": "2.9.1",
        "linux": "2.9.1+cpu",
    }.get(sys.platform)
    expected_direct = {
        "numpy": "2.5.1",
        "rich": "15.0.0",
        "rich-argparse": "1.8.0",
        "torch": expected_torch_version,
    }
    requirements_sha256 = _sha256_file(
        ROOT / "training/f5_trainability_requirements.txt"
    )
    if (
        expected_torch_version is None
        or not isinstance(distributions, dict)
        or distributions.get("schema")
        != "bloodbowl-f5-python-distributions-v1"
        or distributions.get("requirements_sha256") != requirements_sha256
        or distributions.get("direct_requirements") != expected_direct
        or distributions.get("python")
        != {
            "implementation": sys.implementation.name,
            "version": platform.python_version(),
        }
        or str(torch.__version__) != expected_torch_version
    ):
        raise ModuleCheckError("sealed Puffer distribution schema differs")
    return {
        "python_executable": str(Path(sys.executable).absolute()),
        "python_prefix": str(venv),
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "python_cache_tag": sys.implementation.cache_tag,
        "torch_version": str(torch.__version__),
        "torch_file": str(torch_path),
        "torch_file_sha256": _sha256_file(torch_path),
        "torch_cuda_version": None,
        "torch_cuda_available": False,
        "torch_collector_path": str(collector_path),
        "torch_collector_sha256": _sha256_file(collector_path),
        "distributions_snapshot_sha256": distributions_sha256,
        "distributions_snapshot_bytes": distributions_path.stat().st_size,
        "distributions_digest_file_sha256": _sha256_file(digest_path),
        "requirements_sha256": requirements_sha256,
        "direct_requirements": distributions["direct_requirements"],
    }


def _run_torch_rollout(
    module: Any,
    environment_config: dict[str, int | float],
    torch: Any,
    torch_pufferl: Any,
) -> dict[str, Any]:
    class DiagnosticReferencePolicy(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.diagnostic_parameter = torch.nn.Parameter(
                torch.zeros(1, dtype=torch.float32)
            )
            self.calls = 0
            self.nonfinite_tail_emitted = False
            self.recurrent_state_inputs: list[float] = []

        def initial_state(
            self, batch_size: int, device: str
        ) -> tuple[Any, ...]:
            return (
                torch.full(
                    (1, batch_size, 1),
                    17.0,
                    dtype=torch.float32,
                    device=device,
                ),
            )

        def forward_eval(
            self, observations: Any, state: tuple[Any, ...]
        ) -> tuple[list[Any], Any, tuple[Any, ...]]:
            if len(state) != 1 or state[0].shape != (
                1, observations.shape[0], 1
            ):
                raise ModuleCheckError(
                    "diagnostic recurrent state shape differs"
                )
            state_values = state[0].detach().cpu().unique().tolist()
            if len(state_values) != 1:
                raise ModuleCheckError(
                    "diagnostic recurrent rows diverged unexpectedly"
                )
            self.recurrent_state_inputs.append(float(state_values[0]))
            batch = observations.shape[0]
            trace_index = min(self.calls, len(REFERENCE_HEADS) - 1)
            target = REFERENCE_HEADS[trace_index]
            logits = []
            for size, selected in zip((30, 33, 391), target):
                head = torch.full(
                    (batch, size),
                    -1000.0,
                    dtype=torch.float32,
                    device=observations.device,
                )
                head[:, selected] = 1000.0
                logits.append(head)
            if self.calls == len(REFERENCE_HEADS):
                value = torch.tensor(
                    [[float("nan")], [float("inf")]],
                    dtype=torch.float32,
                    device=observations.device,
                )
                self.nonfinite_tail_emitted = True
            else:
                value = torch.zeros(
                    (batch, 1),
                    dtype=torch.float32,
                    device=observations.device,
                )
            self.calls += 1
            return logits, value, (state[0] + 1.0,)

    args = {
        "vec": {"total_agents": 2, "num_buffers": 1},
        "train": {
            "horizon": 8,
            "total_timesteps": 16,
            "minibatch_size": 16,
            "replay_ratio": 1.0,
            "ent_coef": 0.0,
            "anneal_ent_coef": False,
            "min_ent_coef_ratio": 0.0,
            "learning_rate": 0.0,
            "beta1": 0.9,
            "eps": 1e-8,
        },
        "reset_state": True,
        "world_size": 1,
    }
    raw_vec = None
    prior_rng_state = torch.random.get_rng_state()
    try:
        torch.manual_seed(0xF5)
        raw_vec = module.create_vec(
            {
                "vec": dict(args["vec"]),
                "env": dict(environment_config),
            },
            gpu=0,
        )
        _assert_environment_abi(raw_vec)
        counted_vec = _CountedCpuVec(raw_vec, len(REFERENCE_HEADS))
        policy = DiagnosticReferencePolicy()
        collector = torch_pufferl.PuffeRL(
            args, counted_vec, policy, verbose=False
        )
        if collector.device != "cpu" or collector.gpu:
            raise ModuleCheckError("Torch diagnostic did not select CPU rollout")
        collector.rollouts()

        if counted_vec.cpu_steps != 8:
            raise ModuleCheckError(
                f"Torch collector made {counted_vec.cpu_steps} environment steps"
            )
        if policy.calls != 9 or not policy.nonfinite_tail_emitted:
            raise ModuleCheckError(
                "Torch policy did not emit the diagnostic nonfinite tail values"
            )
        if policy.recurrent_state_inputs != [
            0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 0.0
        ]:
            raise ModuleCheckError(
                "Torch collector recurrent reset/tail-state sequence differs"
            )
        if (
            len(collector.state) != 1
            or collector.state[0].detach().cpu().unique().tolist() != [8.0]
        ):
            raise ModuleCheckError(
                "Torch collector recurrent action state did not reach slot eight"
            )
        observed_actions = [
            [
                [int(value) for value in collector.actions[step, row].tolist()]
                for row in range(2)
            ]
            for step in range(8)
        ]
        expected_actions = [
            [list(heads), list(NULL_HEADS)] for heads in REFERENCE_HEADS
        ]
        if observed_actions != expected_actions:
            raise ModuleCheckError("Torch collector did not execute exact F5 actions")
        collector_obs_sha256: list[list[str]] = []
        collector_mask_sha256: list[list[str]] = []
        if collector.action_masks is None:
            raise ModuleCheckError("Torch collector did not retain action masks")
        for step in range(8):
            step_obs_hashes = []
            step_mask_hashes = []
            for row in range(2):
                observation = (
                    collector.observations[step, row]
                    .detach()
                    .cpu()
                    .contiguous()
                    .numpy()
                    .tobytes()
                )
                effective_mask = (
                    collector.action_masks[step, row]
                    .detach()
                    .cpu()
                    .contiguous()
                )
                for offset, selected in zip(
                    (0, 30, 63), observed_actions[step][row]
                ):
                    if int(effective_mask[offset + selected].item()) != 1:
                        raise ModuleCheckError(
                            "Torch action escaped its retained conditional mask"
                        )
                step_obs_hashes.append(hashlib.sha256(observation).hexdigest())
                step_mask_hashes.append(
                    hashlib.sha256(
                        effective_mask.numpy().tobytes()
                    ).hexdigest()
                )
            if step_obs_hashes != list(REFERENCE_OBS_SHA256[step]):
                raise ModuleCheckError(
                    f"Torch collector observation {step + 1} differs"
                )
            collector_obs_sha256.append(step_obs_hashes)
            collector_mask_sha256.append(step_mask_hashes)

        collector_rewards = collector.rewards.detach().cpu().tolist()
        collector_terminals = collector.terminals.detach().cpu().tolist()
        if collector_rewards != [[0.0, 0.0]] * 8:
            raise ModuleCheckError(
                "Torch collector reward slots violate delayed-tail transport"
            )
        if collector_terminals != [[0.0, 0.0]] * 8:
            raise ModuleCheckError(
                "Torch collector terminal slots violate delayed-tail transport"
            )
        tail_rewards = collector.tail_rewards.detach().cpu().tolist()
        tail_terminals = collector.tail_terminals.detach().cpu().tolist()
        tail_values = collector.tail_values.detach().cpu().tolist()
        if (
            tail_rewards != [1.0, -1.0]
            or tail_terminals != [1.0, 1.0]
            or tail_values != [0.0, 0.0]
            or not collector.tail_valid
        ):
            raise ModuleCheckError("Torch collector tail record differs")
        if (
            collector.pending_rewards.detach().cpu().tolist() != [1.0, -1.0]
            or collector.pending_terminals.detach().cpu().tolist()
            != [1.0, 1.0]
        ):
            raise ModuleCheckError("Torch pending transition differs from tail")
        if collector.global_step != 16:
            raise ModuleCheckError("Torch collector global step differs")
        exact_log = _exact_log(collector.env_logs)

        values = collector.values.T.contiguous()
        rewards = collector.rewards.T.contiguous()
        terminals = collector.terminals.T.contiguous()
        if (
            values.is_cuda
            or torch_pufferl._C is not module
            or not callable(getattr(module, "puff_advantage_cpu", None))
        ):
            raise ModuleCheckError(
                "Torch advantage path is not the compiled CPU module"
            )
        advantages = torch.zeros_like(values)
        gamma = 0.99
        gae_lambda = 0.95
        advantage_calls = 0
        torch_pufferl.compute_puff_advantage(
            values,
            rewards,
            terminals,
            collector.ratio,
            collector.tail_values,
            collector.tail_rewards,
            collector.tail_terminals,
            advantages,
            gamma,
            gae_lambda,
            1.0,
            1.0,
        )
        advantage_calls += 1
        observed_advantages = advantages.detach().cpu().tolist()
        decay = gamma * gae_lambda
        expected_advantages = [
            [
                sign * decay ** (7 - step)
                for step in range(8)
            ]
            for sign in (1.0, -1.0)
        ]
        for row in range(2):
            for step in range(8):
                value = observed_advantages[row][step]
                if (
                    not math.isfinite(value)
                    or value == 0.0
                    or not math.isclose(
                        value,
                        expected_advantages[row][step],
                        rel_tol=2e-6,
                        abs_tol=2e-6,
                    )
                ):
                    raise ModuleCheckError(
                        "compiled CPU advantage did not consume the terminal tail"
                    )
        if (
            observed_advantages[0][-1] != 1.0
            or observed_advantages[1][-1] != -1.0
            or advantage_calls != 1
        ):
            raise ModuleCheckError(
                "compiled CPU advantage final slot is degenerate or duplicated"
            )
    finally:
        torch.random.set_rng_state(prior_rng_state)
        if raw_vec is not None:
            raw_vec.close()

    return {
        "slot": 8,
        "reward": tail_rewards,
        "terminal": tail_terminals,
        "terminal_bootstrap": tail_values,
        "ninth_environment_action": False,
        "environment_step_calls": counted_vec.cpu_steps,
        "policy_forward_calls": policy.calls,
        "policy_tail_value_emission": ["nan", "+inf"],
        "recurrent_state_inputs": policy.recurrent_state_inputs,
        "recurrent_state_after_actions": [8.0],
        "recurrent_initial_state_was_cleared": True,
        "recurrent_tail_state_was_cleared": True,
        "collector": {
            "rewards": collector_rewards,
            "terminals": collector_terminals,
            "actions": observed_actions,
            "obs_sha256": collector_obs_sha256,
            "effective_mask_sha256": collector_mask_sha256,
            "pending_rewards": [1.0, -1.0],
            "pending_terminals": [1.0, 1.0],
            "global_step": 16,
            "tail_valid": True,
        },
        "advantage": {
            "consumer": "puff_advantage_cpu",
            "calls": advantage_calls,
            "gamma": gamma,
            "gae_lambda": gae_lambda,
            "values": observed_advantages,
            "final_slot": [
                observed_advantages[0][-1],
                observed_advantages[1][-1],
            ],
        },
        "log": exact_log,
    }


def _sample_conditional_joint(
    support: list[tuple[int, int, int]],
    generator: random.Random,
) -> tuple[int, int, int]:
    candidates = support
    selected: list[int] = []
    for head in range(3):
        values = sorted({candidate[head] for candidate in candidates})
        if not values:
            raise ModuleCheckError("conditional random sampler has empty support")
        value = values[generator.randrange(len(values))]
        selected.append(value)
        candidates = [
            candidate for candidate in candidates
            if candidate[head] == value
        ]
    result = tuple(selected)
    if result not in support:
        raise ModuleCheckError("conditional random sampler escaped joint support")
    return result


def _run_masked_random_smoke(
    module: Any,
    environment_config: dict[str, int | float],
) -> dict[str, Any]:
    vec = None
    try:
        vec = module.create_vec(
            {
                "vec": {"total_agents": 2, "num_buffers": 1},
                "env": dict(environment_config),
            },
            gpu=0,
        )
        _assert_environment_abi(vec)
        vec.reset()
        initial_obs = _ctypes_bytes(vec.obs_ptr, 2 * vec.obs_size)
        initial_mask = _ctypes_bytes(
            vec.action_mask_ptr, 2 * vec.action_mask_size
        )
        initial_rows = _joint_rows(vec)
        if _canonical_sha256(initial_rows) != REFERENCE_JOINT_SUPPORT_SHA256[0]:
            raise ModuleCheckError("random smoke initial support identity differs")
        support_rows_checked = len(initial_rows)
        rewards = (ctypes.c_float * 2).from_address(int(vec.rewards_ptr))
        terminals = (ctypes.c_float * 2).from_address(int(vec.terminals_ptr))
        actions = (ctypes.c_float * 6)()
        generator = random.Random(RANDOM_MODULE_SEED)
        completed = 0
        episode_decisions = 0
        total_decisions = 0
        episode_lengths: list[int] = []
        home_touchdowns = 0
        away_touchdowns = 0
        exact_resets = 0

        while completed < RANDOM_MODULE_EPISODES:
            rows = _joint_rows(vec)
            support_rows_checked += len(rows)
            for row, support in enumerate(rows):
                selected = _sample_conditional_joint(support, generator)
                actions[3 * row : 3 * row + 3] = selected
            vec.cpu_step(ctypes.addressof(actions))
            episode_decisions += 1
            total_decisions += 1
            emitted_rewards = [float(rewards[0]), float(rewards[1])]
            emitted_terminals = [float(terminals[0]), float(terminals[1])]
            if not all(math.isfinite(value) for value in emitted_rewards):
                raise ModuleCheckError("random module smoke emitted nonfinite reward")
            if emitted_rewards not in (
                [0.0, 0.0],
                [1.0, -1.0],
                [-1.0, 1.0],
            ):
                raise ModuleCheckError(
                    "random module smoke violated objective-only zero-sum reward"
                )
            if emitted_terminals not in ([0.0, 0.0], [1.0, 1.0]):
                raise ModuleCheckError(
                    "random module smoke emitted asymmetric terminal flags"
                )
            if emitted_rewards != [0.0, 0.0] and emitted_terminals != [1.0, 1.0]:
                raise ModuleCheckError(
                    "random module smoke emitted nonterminal objective reward"
                )
            if emitted_terminals == [0.0, 0.0]:
                if episode_decisions >= 8:
                    raise ModuleCheckError(
                        "random module smoke exceeded decision cap"
                    )
                continue

            if episode_decisions < 1 or episode_decisions > 8:
                raise ModuleCheckError(
                    "random module smoke episode length is invalid"
                )
            if emitted_rewards == [1.0, -1.0]:
                home_touchdowns += 1
            elif emitted_rewards == [-1.0, 1.0]:
                away_touchdowns += 1
            episode_lengths.append(episode_decisions)
            episode_decisions = 0
            completed += 1
            reset_rows = _joint_rows(vec)
            support_rows_checked += len(reset_rows)
            if (
                _ctypes_bytes(vec.obs_ptr, 2 * vec.obs_size) != initial_obs
                or _ctypes_bytes(
                    vec.action_mask_ptr, 2 * vec.action_mask_size
                )
                != initial_mask
                or _canonical_sha256(reset_rows)
                != REFERENCE_JOINT_SUPPORT_SHA256[0]
            ):
                raise ModuleCheckError(
                    "random module smoke autoreset identity differs"
                )
            exact_resets += 1

        log = vec.log()
        integrity = {
            key: _finite_log_number(log, key)
            for key in RANDOM_ZERO_INTEGRITY_LOG_KEYS
        }
        unexpected_integrity = {
            key: value for key, value in integrity.items() if value != 0.0
        }
        if unexpected_integrity:
            raise ModuleCheckError(
                "random module smoke hard-integrity ledger is nonzero: "
                f"{unexpected_integrity!r}"
            )
        integrity.update({
            "n": _finite_log_number(log, "n"),
            "episode_length": _finite_log_number(log, "episode_length"),
            "reward_samples_per_episode": _finite_log_number(
                log, "reward_samples_per_episode"
            ),
            "tds_t0": _finite_log_number(log, "tds_t0"),
            "tds_t1": _finite_log_number(log, "tds_t1"),
        })
        if (
            integrity["n"] != float(RANDOM_MODULE_EPISODES)
            or integrity["episode_length"] != 8.0
            or integrity["reward_samples_per_episode"] != 16.0
        ):
            raise ModuleCheckError(
                "random module smoke count ledger differs"
            )
        if not math.isclose(
            integrity["tds_t0"],
            home_touchdowns / RANDOM_MODULE_EPISODES,
            rel_tol=1e-6,
            abs_tol=1e-7,
        ) or not math.isclose(
            integrity["tds_t1"],
            away_touchdowns / RANDOM_MODULE_EPISODES,
            rel_tol=1e-6,
            abs_tol=1e-7,
        ):
            raise ModuleCheckError("random module touchdown log differs")
        mean_length = total_decisions / RANDOM_MODULE_EPISODES
        if not math.isclose(
            integrity["episode_length"],
            mean_length,
            rel_tol=1e-6,
            abs_tol=1e-7,
        ):
            raise ModuleCheckError("random module episode-length log differs")
    finally:
        if vec is not None:
            vec.close()

    return {
        "episodes": RANDOM_MODULE_EPISODES,
        "seed": RANDOM_MODULE_SEED,
        "sampler": "sequential-conditional-unique-uniform-v1",
        "reference_fallbacks": 0,
        "decisions": total_decisions,
        "agent_steps": 2 * total_decisions,
        "episode_length_min": min(episode_lengths),
        "episode_length_max": max(episode_lengths),
        "episode_length_mean": mean_length,
        "exact_autoresets": exact_resets,
        "successes": home_touchdowns + away_touchdowns,
        "tds_t0": home_touchdowns,
        "tds_t1": away_touchdowns,
        "dice": {"exposed": False},
        "illegal_frac": integrity["illegal_frac"],
        "projection_collisions": 0,
        "joint_support_rows_checked": support_rows_checked,
        "error_episodes": integrity["error_episodes"],
        "reward_nonfinite_frac": integrity["reward_nonfinite_frac"],
        "integrity": integrity,
    }


def run_check(puffer_root: Path) -> dict[str, Any]:
    puffer_root = puffer_root.resolve(strict=True)
    environment_config = _load_environment_config()
    if _git_output(puffer_root, "rev-parse", "HEAD") != PUFFER_COMMIT:
        raise ModuleCheckError("Puffer checkout is not at the pinned commit")
    if any(
        name == "pufferlib" or name.startswith("pufferlib.")
        for name in sys.modules
    ):
        raise ModuleCheckError("pufferlib was imported before provenance checks")
    sys.path.insert(0, str(puffer_root))
    try:
        from pufferlib import _C  # type: ignore
    except Exception as exc:
        raise ModuleCheckError(f"cannot import built Puffer module: {exc}") from exc
    module_path = Path(_C.__file__).resolve(strict=True)
    if not _path_beneath(module_path, puffer_root):
        raise ModuleCheckError(f"module escaped pinned checkout: {module_path}")
    module_contract = _require_module_contract(_C)
    try:
        import torch  # type: ignore
        import pufferlib.torch_pufferl as torch_pufferl  # type: ignore
    except Exception as exc:
        raise ModuleCheckError(
            f"cannot import sealed Puffer Torch collector: {exc}"
        ) from exc
    torch_pufferl_path = Path(torch_pufferl.__file__).resolve(strict=True)
    if not _path_beneath(torch_pufferl_path, puffer_root):
        raise ModuleCheckError(
            f"Torch collector escaped pinned checkout: {torch_pufferl_path}"
        )

    runtime = _runtime_identity(puffer_root, torch)
    vectorization = _run_two_environment_oracle(_C, environment_config)
    direct = _run_direct_oracle(_C, environment_config)
    rollout_tail = _run_torch_rollout(
        _C, environment_config, torch, torch_pufferl
    )
    if rollout_tail["log"] != direct["log"]:
        raise ModuleCheckError(
            "Torch rollout log differs from the separate direct oracle"
        )
    masked_random = _run_masked_random_smoke(_C, environment_config)

    return {
        "schema": SCHEMA,
        "puffer_commit": PUFFER_COMMIT,
        "module_path": str(module_path),
        "module_sha256": _sha256_file(module_path),
        "module_contract": module_contract,
        "environment_config": environment_config,
        "runtime": runtime,
        "vectorization": vectorization,
        "transitions": direct["transitions"],
        "rollout_tail": rollout_tail,
        "masked_random": masked_random,
        "autoreset": direct["autoreset"],
        "log": direct["log"],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puffer-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run_check(args.puffer_root)
        _atomic_json(args.output, result)
    except (ModuleCheckError, OSError, subprocess.SubprocessError) as exc:
        print(f"F5 Puffer module check failed: {exc}", file=sys.stderr)
        return 2
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
