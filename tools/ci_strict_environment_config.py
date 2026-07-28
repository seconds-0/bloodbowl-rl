#!/usr/bin/env python3
"""Pinned Linux CPU integration gate for Blood Bowl environment config.

This script is intentionally narrower than the recurrent CUDA qualification.
It validates a freshly built production CPU module in the exact checked-out
Puffer tree, exercises valid full/sparse/BOTH configurations, and runs each
invalid class in a fresh process so an unexpected native exit or signal cannot
be mistaken for a clean Python ``ValueError``.
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any, Callable, Mapping

try:
    from puffer_source_manifest import (
        read_source_ledger,
        source_manifest_sha256,
    )
    from state_bank_contract import environment_source_sha256
except ModuleNotFoundError:  # Imported as tools.ci_strict_environment_config.
    from tools.puffer_source_manifest import (
        read_source_ledger,
        source_manifest_sha256,
    )
    from tools.state_bank_contract import environment_source_sha256


PUFFER_COMMIT = "9836f0d2e78889c1aaf189c04d161b6fc61a9386"
ENVIRONMENT_CONFIG_SCHEMA = "bloodbowl-environment-config-v1"
ENVIRONMENT_CONFIG_KEY_COUNT = 51
RAYLIB_ARCHIVE = "raylib-5.5_linux_amd64.tar.gz"
RAYLIB_SHA256 = "3d95ef03d5b38dfa55c0a16ca122d382134b078f0e5b270b52fe7eae0549c000"
EXPECTED_REQUIREMENTS = {
    "pip": "26.1.2",
    "setuptools": "83.0.0",
    "wheel": "0.47.0",
    "pybind11": "3.0.4",
    "numpy": "2.5.1",
    "torch": "2.9.1+cpu",
    "rich": "15.0.0",
    "rich-argparse": "1.8.0",
}
EXPECTED_REQUIREMENT_OPTIONS = (
    "--extra-index-url https://download.pytorch.org/whl/cpu",
)
EXPECTED_OBSERVATION_ABI = "obs-v6"
EXPECTED_OBSERVATION_VERSION = 6
EXPECTED_ACTION_ABI = "exact-joint-v1"
UNRELATED_ENVIRONMENT = "minimal"
UNRELATED_TOTAL_AGENTS = 8
VALID_PROFILE_NAMES = (
    "full-51-key",
    "empty-defaults",
    "sparse-qualification",
    "exact-bool-transport",
    "scripted-both",
)
COMPILED_LEDGER = "training/puffer_compiled_backend_sources.txt"
REQUIREMENTS_FILE = "training/strict_environment_config_ci_requirements.txt"
RAYLIB_DIGEST_FILE = "training/raylib-5.5_linux_amd64.sha256"
CASE_SENTINEL = "STRICT_CONFIG_CASE_JSON="


class StrictConfigCIError(RuntimeError):
    """The pinned CPU integration evidence is incomplete or inconsistent."""


class DerivedFloat(float):
    """A numeric subclass that the exact Python transport must reject."""


class DerivedInt(int):
    """An integer subclass that the exact Python transport must reject."""


class DerivedStr(str):
    """A string subclass that the exact Python transport must reject."""


class PoisonFloat:
    """A mutating numeric protocol that must never be evaluated."""

    def __init__(self, source: dict[Any, Any]):
        self.source = source
        self.called = False

    def __float__(self) -> float:
        self.called = True
        self.source.clear()
        self.source["mutated"] = 1
        raise AssertionError("custom __float__ must not run")


def _invalid_nonstring_key(_team_count: int) -> dict[Any, Any]:
    return {1: 0}


def _invalid_bytes_key(_team_count: int) -> dict[Any, Any]:
    return {b"seed": 1}


def _invalid_string_subclass(_team_count: int) -> dict[Any, Any]:
    return {DerivedStr("seed"): 1}


def _invalid_empty_key(_team_count: int) -> dict[Any, Any]:
    return {"": 1}


def _invalid_embedded_nul_key(_team_count: int) -> dict[Any, Any]:
    return {"seed\0trailing": 1}


def _invalid_nonascii_key(_team_count: int) -> dict[Any, Any]:
    return {"s\u00e9ed": 1}


def _invalid_lone_surrogate_key(_team_count: int) -> dict[Any, Any]:
    return {"\ud800": 1}


def _invalid_long_key(_team_count: int) -> dict[Any, Any]:
    return {"a" * 64: 1}


def _invalid_nonnumeric_value(_team_count: int) -> dict[Any, Any]:
    return {"seed": "nan"}


def _invalid_numeric_subclass(_team_count: int) -> dict[Any, Any]:
    return {"seed": DerivedFloat(1.0)}


def _invalid_integer_subclass(_team_count: int) -> dict[Any, Any]:
    return {"seed": DerivedInt(1)}


def _invalid_custom_float(_team_count: int) -> dict[Any, Any]:
    source: dict[Any, Any] = {}
    source["seed"] = PoisonFloat(source)
    return source


def _invalid_integer_transport(_team_count: int) -> dict[Any, Any]:
    return {"seed": 2**63}


def _invalid_exact_double_integer_range(_team_count: int) -> dict[Any, Any]:
    return {"seed": 2**53}


def _invalid_unknown_key(_team_count: int) -> dict[Any, Any]:
    return {"seedd": 1}


def _invalid_cardinality(_team_count: int) -> dict[Any, Any]:
    return {f"unknown_{index}": 0 for index in range(52)}


def _invalid_huge_cardinality(_team_count: int) -> dict[Any, Any]:
    return {f"unknown_{index}": 0 for index in range(100_000)}


def _invalid_seed_fraction(_team_count: int) -> dict[Any, Any]:
    return {"seed": 1.5}


def _invalid_seed_nan(_team_count: int) -> dict[Any, Any]:
    return {"seed": math.nan}


def _invalid_boolean_fraction(_team_count: int) -> dict[Any, Any]:
    return {"scripted_opponent": 0.5}


def _invalid_team(team_count: int) -> dict[Any, Any]:
    return {"force_home_team": team_count}


def _invalid_reward_high(_team_count: int) -> dict[Any, Any]:
    return {"reward_td": 1.0000001}


def _invalid_reward_nan(_team_count: int) -> dict[Any, Any]:
    return {"reward_td": math.nan}


def _invalid_gamma_negative(_team_count: int) -> dict[Any, Any]:
    return {"reward_dist_pbrs_gamma": -0.1}


def _invalid_gamma_nan(_team_count: int) -> dict[Any, Any]:
    return {"reward_dist_pbrs_gamma": math.nan}


def _invalid_gamma_underflow(_team_count: int) -> dict[Any, Any]:
    return {"reward_dist_pbrs_gamma": 1e-50}


def _invalid_statmatch_high(_team_count: int) -> dict[Any, Any]:
    return {"reward_statmatch_scale": 1.1}


def _invalid_bank_reset_negative(_team_count: int) -> dict[Any, Any]:
    return {"demo_reset_pct": -0.1}


def _invalid_bank_kind(_team_count: int) -> dict[Any, Any]:
    return {"state_bank_kind": 3}


def _invalid_bank_endzone_selector(_team_count: int) -> dict[Any, Any]:
    return {"demo_endzone_maxdist": -1}


def _invalid_bank_pickup_selector(_team_count: int) -> dict[Any, Any]:
    return {"demo_pickup_maxdist": -1}


def _invalid_bank_postkick_selector(_team_count: int) -> dict[Any, Any]:
    return {"demo_postkick_maxturn": -1}


def _invalid_bank_pass_selector(_team_count: int) -> dict[Any, Any]:
    return {"demo_pass_maxrange": -1}


def _invalid_skill_players(_team_count: int) -> dict[Any, Any]:
    return {"skillup_max_players": -1}


def _invalid_skill_each(_team_count: int) -> dict[Any, Any]:
    return {"skillup_max_each": 13}


def _invalid_unit_interval(_team_count: int) -> dict[Any, Any]:
    return {"skillup_secondary_pct": -0.1}


def _invalid_script_team(_team_count: int) -> dict[Any, Any]:
    return {"scripted_opponent_team": 3}


def _invalid_script_type(_team_count: int) -> dict[Any, Any]:
    return {"scripted_opponent_type": 2}


def _invalid_max_decisions(_team_count: int) -> dict[Any, Any]:
    return {"max_decisions": 0}


def _invalid_render_fps(_team_count: int) -> dict[Any, Any]:
    return {"render_fps": 0}


def _invalid_reward_cross_field(_team_count: int) -> dict[Any, Any]:
    return {
        "reward_carrier_exposure": 0.1,
        "reward_carrier_threat": 0.1,
    }


def _invalid_bank_inert_selector(_team_count: int) -> dict[Any, Any]:
    return {"demo_endzone_maxdist": 1}


def _invalid_bank_multiple_selectors(_team_count: int) -> dict[Any, Any]:
    return {
        "demo_endzone_maxdist": 1,
        "demo_pickup_maxdist": 1,
    }


# Name -> (configuration factory, stable diagnostic fragment).  These names
# become artifact evidence, so keep the set closed and explicit.
INVALID_CASES: Mapping[str, tuple[Callable[[int], dict[Any, Any]], str]] = {
    "nonstring-key": (
        _invalid_nonstring_key,
        "environment key must be an exact str",
    ),
    "bytes-key": (
        _invalid_bytes_key,
        "environment key must be an exact str",
    ),
    "string-subclass-key": (
        _invalid_string_subclass,
        "environment key must be an exact str",
    ),
    "empty-key": (
        _invalid_empty_key,
        "must match [a-z0-9_]+",
    ),
    "embedded-nul-key": (
        _invalid_embedded_nul_key,
        "must match [a-z0-9_]+",
    ),
    "nonascii-key": (
        _invalid_nonascii_key,
        "must match [a-z0-9_]+",
    ),
    "lone-surrogate-key": (
        _invalid_lone_surrogate_key,
        "environment key could not be encoded as UTF-8",
    ),
    "overlong-key": (
        _invalid_long_key,
        "must be at most 63 UTF-8 bytes",
    ),
    "nonnumeric-value": (
        _invalid_nonnumeric_value,
        "must have an exact bool, int, or float value",
    ),
    "numeric-subclass": (
        _invalid_numeric_subclass,
        "must have an exact bool, int, or float value",
    ),
    "integer-subclass": (
        _invalid_integer_subclass,
        "must have an exact bool, int, or float value",
    ),
    "custom-float-protocol": (
        _invalid_custom_float,
        "must have an exact bool, int, or float value",
    ),
    "integer-transport-overflow": (
        _invalid_integer_transport,
        "integer is outside the exact double transport range",
    ),
    "integer-exact-double-overflow": (
        _invalid_exact_double_integer_range,
        "integer is outside the exact double transport range",
    ),
    "unknown-numeric-key": (
        _invalid_unknown_key,
        "seedd must be a key in bloodbowl-environment-config-v1",
    ),
    "environment-cardinality": (
        _invalid_cardinality,
        "environment dictionary must contain at most 51 keys",
    ),
    "environment-huge-cardinality": (
        _invalid_huge_cardinality,
        "environment dictionary must contain at most 51 keys",
    ),
    "integer-fraction": (
        _invalid_seed_fraction,
        "seed must be an exact integer in [0, 2^53-1]",
    ),
    "seed-nan": (
        _invalid_seed_nan,
        "seed must be an exact integer in [0, 2^53-1]",
    ),
    "boolean-fraction": (
        _invalid_boolean_fraction,
        "scripted_opponent must be the exact boolean 0 or 1",
    ),
    "team-upper-bound": (
        _invalid_team,
        "force_home_team must be integer -1 or 0..BB_TEAM_COUNT-1",
    ),
    "invalid-env-before-vec-geometry": (
        _invalid_team,
        "force_home_team must be integer -1 or 0..BB_TEAM_COUNT-1",
    ),
    "reward-above-one": (
        _invalid_reward_high,
        "reward_td must be finite in [-1,1] and remain nonzero as float",
    ),
    "reward-nan": (
        _invalid_reward_nan,
        "reward_td must be finite in [-1,1] and remain nonzero as float",
    ),
    "gamma-negative": (
        _invalid_gamma_negative,
        "reward_dist_pbrs_gamma must be finite in [0,1]",
    ),
    "gamma-nan": (
        _invalid_gamma_nan,
        "reward_dist_pbrs_gamma must be finite in [0,1]",
    ),
    "gamma-float32-underflow": (
        _invalid_gamma_underflow,
        "reward_dist_pbrs_gamma must be finite in [0,1] and remain nonzero as float",
    ),
    "statmatch-above-one": (
        _invalid_statmatch_high,
        "reward_statmatch_scale must be finite in [0,1] and remain nonzero as float",
    ),
    "bank-reset-negative": (
        _invalid_bank_reset_negative,
        "demo_reset_pct must be finite in [0,1] and remain nonzero as float",
    ),
    "bank-kind-enum": (
        _invalid_bank_kind,
        "state_bank_kind must be the exact state-bank enum 0, 1, or 2",
    ),
    "bank-endzone-selector-negative": (
        _invalid_bank_endzone_selector,
        "demo_endzone_maxdist must be an exact integer in "
        "[0, BBE_STATE_BANK_MAX_DISTANCE]",
    ),
    "bank-pickup-selector-negative": (
        _invalid_bank_pickup_selector,
        "demo_pickup_maxdist must be an exact integer in "
        "[0, BBE_STATE_BANK_MAX_DISTANCE]",
    ),
    "bank-postkick-selector-negative": (
        _invalid_bank_postkick_selector,
        "demo_postkick_maxturn must be an exact integer in "
        "[0, BBE_STATE_BANK_MAX_TURN]",
    ),
    "bank-pass-selector-negative": (
        _invalid_bank_pass_selector,
        "demo_pass_maxrange must be an exact integer in "
        "[0, BBE_STATE_BANK_MAX_DISTANCE]",
    ),
    "skill-players-negative": (
        _invalid_skill_players,
        "skillup_max_players must be an exact integer in [0, BB_TEAM_SLOTS]",
    ),
    "skill-each-above-twelve": (
        _invalid_skill_each,
        "skillup_max_each must be an exact integer in [0, 12]",
    ),
    "unit-interval-negative": (
        _invalid_unit_interval,
        "skillup_secondary_pct must be finite in [0,1] and remain nonzero as float",
    ),
    "script-team-enum": (
        _invalid_script_team,
        "scripted_opponent_team must be the exact scripted-team enum 0, 1, or 2",
    ),
    "script-type-enum": (
        _invalid_script_type,
        "scripted_opponent_type must be the exact scripted-opponent type 0 or 1",
    ),
    "max-decisions-zero": (
        _invalid_max_decisions,
        "max_decisions must be an exact integer in [1, BBE_MAX_DECISIONS]",
    ),
    "render-fps-zero": (
        _invalid_render_fps,
        "render_fps must be an exact integer in [1, INT_MAX]",
    ),
    "reward-cross-field-conflict": (
        _invalid_reward_cross_field,
        "reward_carrier_threat must be zero when either "
        "reward_carrier_exposure field is nonzero",
    ),
    "bank-inert-selector-cross-field": (
        _invalid_bank_inert_selector,
        "demo_endzone_maxdist must be zero when demo_reset_pct is zero",
    ),
    "bank-multiple-selectors-cross-field": (
        _invalid_bank_multiple_selectors,
        "demo_endzone_maxdist must be the only nonzero state-bank selector",
    ),
}

# Every native ledger domain has a unique real-module subprocess case.  Keeping
# this mapping separate from the transport/structure/cross-field cases makes
# it possible for source-contract tests to compare the matrix against the
# ledger itself instead of blessing a hand-selected list of field names.
NATIVE_LEDGER_DOMAIN_CASES: Mapping[str, str] = {
    "SEED": "integer-fraction",
    "REWARD": "reward-above-one",
    "GAMMA": "gamma-negative",
    "STATMATCH": "statmatch-above-one",
    "BOOL": "boolean-fraction",
    "BANK_RESET": "bank-reset-negative",
    "BANK_KIND": "bank-kind-enum",
    "BANK_ENDZONE_SELECTOR": "bank-endzone-selector-negative",
    "BANK_PICKUP_SELECTOR": "bank-pickup-selector-negative",
    "BANK_POSTKICK_SELECTOR": "bank-postkick-selector-negative",
    "BANK_PASS_SELECTOR": "bank-pass-selector-negative",
    "BANK_TEAM": "team-upper-bound",
    "SKILL_PLAYERS": "skill-players-negative",
    "SKILL_EACH": "skill-each-above-twelve",
    "UNIT_INTERVAL": "unit-interval-negative",
    "SCRIPT_TEAM": "script-team-enum",
    "SCRIPT_TYPE": "script-type-enum",
    "MAX_DECISIONS": "max-decisions-zero",
    "RENDER_FPS": "render-fps-zero",
}
CROSS_FIELD_CASES = (
    "reward-cross-field-conflict",
    "bank-inert-selector-cross-field",
    "bank-multiple-selectors-cross-field",
)

INVALID_VEC_OVERRIDES: Mapping[str, dict[str, Any]] = {
    "invalid-env-before-vec-geometry": {
        "total_agents": math.nan,
        "num_buffers": 0,
    },
}


def _sha256_file(path: Path) -> str:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise StrictConfigCIError(f"cannot stat evidence file {path}: {exc}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise StrictConfigCIError(
            f"evidence file must be a regular non-symlink file: {path}"
        )
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1 << 20):
                digest.update(chunk)
    except OSError as exc:
        raise StrictConfigCIError(f"cannot hash evidence file {path}: {exc}") from exc
    return digest.hexdigest()


def _single_line(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise StrictConfigCIError(f"cannot read {path}: {exc}") from exc
    if not raw.endswith(b"\n") or b"\r" in raw or b"\0" in raw:
        raise StrictConfigCIError(f"{path} is not canonical newline-terminated text")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise StrictConfigCIError(f"{path} is not UTF-8") from exc
    if len(lines) != 1:
        raise StrictConfigCIError(f"{path} must contain exactly one line")
    return lines[0]


def _read_raylib_digest(repo_root: Path) -> str:
    line = _single_line(repo_root / RAYLIB_DIGEST_FILE)
    expected_line = f"{RAYLIB_SHA256}  {RAYLIB_ARCHIVE}"
    if line != expected_line:
        raise StrictConfigCIError(
            f"Raylib digest asset differs from the pinned identity: {line!r}"
        )
    return RAYLIB_SHA256


def _read_requirement_pins(repo_root: Path) -> dict[str, str]:
    path = repo_root / REQUIREMENTS_FILE
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise StrictConfigCIError(f"cannot read pinned requirements: {exc}") from exc
    pins: dict[str, str] = {}
    options: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("--"):
            options.append(stripped)
            continue
        if stripped.count("==") != 1:
            raise StrictConfigCIError(
                f"CI requirement is not an exact version pin: {stripped!r}"
            )
        name, version = stripped.split("==")
        normalized = name.lower().replace("_", "-")
        if (
            not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", normalized)
            or not version
            or normalized in pins
        ):
            raise StrictConfigCIError(
                f"invalid or duplicate CI requirement: {stripped!r}"
            )
        pins[normalized] = version
    if tuple(options) != EXPECTED_REQUIREMENT_OPTIONS:
        raise StrictConfigCIError(
            f"CI requirement options differ from the closed set: {options!r}"
        )
    if pins != EXPECTED_REQUIREMENTS:
        raise StrictConfigCIError(
            f"CI requirement pins differ from the closed set: {pins!r}"
        )
    return pins


def load_full_environment_config(puffer_root: Path) -> dict[str, float]:
    """Load the installed exact 51-key numeric ``[env]`` dictionary."""

    path = puffer_root / "config/bloodbowl.ini"
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        with path.open(encoding="utf-8") as handle:
            parser.read_file(handle)
    except (OSError, UnicodeError, configparser.Error) as exc:
        raise StrictConfigCIError(
            f"cannot read installed Blood Bowl config: {exc}"
        ) from exc
    if "env" not in parser:
        raise StrictConfigCIError("installed Blood Bowl config has no [env] section")
    raw = dict(parser["env"])
    if len(raw) != ENVIRONMENT_CONFIG_KEY_COUNT:
        raise StrictConfigCIError(
            f"installed [env] has {len(raw)} keys; expected "
            f"{ENVIRONMENT_CONFIG_KEY_COUNT}"
        )
    result: dict[str, float] = {}
    for key, value in raw.items():
        try:
            numeric = float(value)
        except ValueError as exc:
            raise StrictConfigCIError(
                f"installed [env] value is not numeric: {key}"
            ) from exc
        if not math.isfinite(numeric):
            raise StrictConfigCIError(f"installed [env] value is not finite: {key}")
        result[key] = numeric
    return result


def installed_team_count(puffer_root: Path) -> int:
    path = puffer_root / "ocean/bloodbowl/bb/gen_teams.h"
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise StrictConfigCIError(f"cannot read generated team ledger: {exc}") from exc
    match = re.search(
        r"typedef\s+enum\s*\{(?P<body>.*?)\bBB_TEAM_COUNT\b",
        source,
        re.DOTALL,
    )
    if match is None:
        raise StrictConfigCIError("generated team ledger has no BB_TEAM_COUNT enum")
    count = len(re.findall(r"\bBB_TEAM_[A-Z0-9_]+\b", match.group("body")))
    if count <= 0 or count > 1000:
        raise StrictConfigCIError(f"implausible generated team count: {count}")
    return count


def _path_beneath(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validated_venv_identity(
    puffer_root: Path,
    *,
    prefix: str | Path,
    executable: str | Path,
) -> tuple[Path, Path]:
    """Validate the venv without resolving its intentionally symlinked Python."""

    expected_prefix = (puffer_root / ".venv").resolve()
    lexical_prefix = Path(prefix).absolute()
    observed_prefix = lexical_prefix.resolve()
    if observed_prefix != expected_prefix:
        raise StrictConfigCIError(
            f"Python prefix is {observed_prefix}; expected isolated "
            f"Puffer venv {expected_prefix}"
        )
    # venv/bin/python is normally a symlink to the system interpreter. Resolve
    # the prefix, but preserve this lexical executable path as the qualifier
    # does; resolving it would incorrectly place it under /usr/bin.
    observed_executable = Path(executable).absolute()
    if not _path_beneath(observed_executable, lexical_prefix):
        raise StrictConfigCIError(
            f"Python executable escaped the Puffer venv: {observed_executable}"
        )
    return observed_prefix, observed_executable


def _load_cpu_backend(
    puffer_root: Path,
    *,
    expected_testing_role: bool = False,
) -> tuple[Any, Path]:
    puffer_root = puffer_root.resolve()
    if any(
        name == "pufferlib" or name.startswith("pufferlib.") for name in sys.modules
    ):
        raise StrictConfigCIError("pufferlib was imported before provenance validation")
    sys.path.insert(0, str(puffer_root))
    try:
        from pufferlib import _C  # type: ignore
    except Exception as exc:
        raise StrictConfigCIError(
            f"cannot import freshly built pufferlib._C: {exc}"
        ) from exc

    module_path = Path(_C.__file__).resolve()
    if not _path_beneath(module_path, puffer_root):
        raise StrictConfigCIError(
            f"pufferlib._C escaped the pinned clone: {module_path}"
        )
    if getattr(_C, "env_name", None) != "bloodbowl":
        raise StrictConfigCIError(
            f"compiled env_name is not bloodbowl: {getattr(_C, 'env_name', None)!r}"
        )
    if getattr(_C, "environment_config_schema", None) != ENVIRONMENT_CONFIG_SCHEMA:
        raise StrictConfigCIError(
            "compiled environment config schema is missing or stale"
        )
    if getattr(_C, "strict_env_config_testing", None) is not expected_testing_role:
        role = "testing" if expected_testing_role else "production"
        raise StrictConfigCIError(
            f"compiled CPU module is not the expected {role} config role"
        )
    if type(getattr(_C, "gpu", None)) is not int or _C.gpu != 0:
        raise StrictConfigCIError("strict CPU integration imported a non-CPU module")
    if type(getattr(_C, "precision_bytes", None)) is not int or _C.precision_bytes != 4:
        raise StrictConfigCIError("strict CPU integration requires fp32")
    if getattr(_C, "observation_abi", None) != EXPECTED_OBSERVATION_ABI:
        raise StrictConfigCIError("compiled observation ABI is missing or stale")
    if (
        type(getattr(_C, "observation_version", None)) is not int
        or _C.observation_version != EXPECTED_OBSERVATION_VERSION
    ):
        raise StrictConfigCIError("compiled observation version is missing or stale")
    if getattr(_C, "action_abi", None) != EXPECTED_ACTION_ABI:
        raise StrictConfigCIError("compiled action ABI is missing or stale")
    return _C, module_path


def _construct_reset_close(
    backend: Any,
    env: Mapping[Any, Any],
    *,
    profile: str,
    total_agents: int = 2,
    num_buffers: int = 1,
) -> dict[str, Any]:
    args = {
        "vec": {
            "total_agents": total_agents,
            "num_buffers": num_buffers,
        },
        "env": dict(env),
    }
    vec = None
    constructed = reset = closed = False
    try:
        vec = backend.create_vec(args, gpu=0)
        constructed = True
        vec.reset()
        reset = True
        result = {
            "profile": profile,
            "environment_keys": len(env),
            "constructed": constructed,
            "reset": reset,
            "total_agents": vec.total_agents,
            "obs_size": vec.obs_size,
            "action_heads": list(vec.act_sizes),
        }
    finally:
        if vec is not None:
            vec.close()
            closed = True
    result["closed"] = closed
    if not (constructed and reset and closed):
        raise StrictConfigCIError(
            f"{profile} did not complete construction/reset/close"
        )
    return result


def _header_macro(path: Path, name: str) -> str:
    try:
        source = path.read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        raise StrictConfigCIError(f"cannot read generated build header: {exc}") from exc
    match = re.search(
        rf'^#define {re.escape(name)} "([^"]+)"$',
        source,
        re.MULTILINE,
    )
    if match is None:
        raise StrictConfigCIError(f"generated build header lacks {name}")
    return match.group(1)


def _command_output(command: list[str], *, cwd: Path | None = None) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise StrictConfigCIError(
            f"version command failed: {' '.join(command)}: {exc}"
        ) from exc
    output = (completed.stdout + completed.stderr).strip()
    if not output:
        raise StrictConfigCIError(
            f"version command returned no evidence: {' '.join(command)}"
        )
    return output


def _installed_versions(pins: Mapping[str, str]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for name, expected in pins.items():
        try:
            value = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise StrictConfigCIError(
                f"pinned dependency is not installed: {name}"
            ) from exc
        if value != expected:
            raise StrictConfigCIError(
                f"installed {name} version is {value!r}; expected {expected!r}"
            )
        observed[name] = value
    return observed


def _run_invalid_cases(
    *,
    puffer_root: Path,
    team_count: int,
) -> list[dict[str, Any]]:
    script = Path(__file__).resolve()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(puffer_root)
    records: list[dict[str, Any]] = []
    for name in INVALID_CASES:
        command = [
            sys.executable,
            str(script),
            "_invalid-case",
            "--puffer-root",
            str(puffer_root),
            "--team-count",
            str(team_count),
            "--case",
            name,
        ]
        completed = subprocess.run(
            command,
            cwd=puffer_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        sentinel_lines = [
            line[len(CASE_SENTINEL) :]
            for line in completed.stdout.splitlines()
            if line.startswith(CASE_SENTINEL)
        ]
        if completed.returncode != 0 or len(sentinel_lines) != 1:
            raise StrictConfigCIError(
                f"invalid case {name!r} did not produce one clean rejection "
                f"(exit {completed.returncode}); stdout={completed.stdout[-2000:]!r}; "
                f"stderr={completed.stderr[-2000:]!r}"
            )
        try:
            record = json.loads(sentinel_lines[0])
        except json.JSONDecodeError as exc:
            raise StrictConfigCIError(
                f"invalid case {name!r} emitted malformed evidence"
            ) from exc
        expected_fragment = INVALID_CASES[name][1]
        if record != {
            "case": name,
            "diagnostic_fragment": expected_fragment,
            "exception_type": "ValueError",
            "expected_rejection": True,
        }:
            raise StrictConfigCIError(
                f"invalid case {name!r} emitted unexpected evidence: {record!r}"
            )
        records.append(record)
    return records


def _invalid_case(args: argparse.Namespace) -> int:
    factory, expected_fragment = INVALID_CASES[args.case]
    backend, _module_path = _load_cpu_backend(args.puffer_root)
    env = factory(args.team_count)
    custom_float = env.get("seed") if args.case == "custom-float-protocol" else None
    initial_items = tuple(env.items())
    vec_config = INVALID_VEC_OVERRIDES.get(
        args.case,
        {"total_agents": 2, "num_buffers": 1},
    )
    vec = None
    try:
        vec = backend.create_vec(
            {
                "vec": vec_config,
                "env": env,
            },
            gpu=0,
        )
    except ValueError as exc:
        message = str(exc)
        if expected_fragment not in message:
            raise StrictConfigCIError(
                f"{args.case} raised the wrong ValueError: {message}"
            ) from exc
        if args.case == "custom-float-protocol" and (
            not isinstance(custom_float, PoisonFloat)
            or custom_float.called
            or tuple(env.items()) != initial_items
        ):
            raise StrictConfigCIError(
                "custom __float__ was evaluated or mutated its source dictionary"
            )
        print(
            CASE_SENTINEL
            + json.dumps(
                {
                    "case": args.case,
                    "diagnostic_fragment": expected_fragment,
                    "exception_type": "ValueError",
                    "expected_rejection": True,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except Exception as exc:
        raise StrictConfigCIError(
            f"{args.case} reached an unrelated exception: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    finally:
        if vec is not None:
            vec.close()
    raise StrictConfigCIError(f"{args.case} was unexpectedly accepted")


def _require_stage_record(
    record: object,
    expected: Mapping[str, int],
    *,
    location: str,
) -> dict[str, int]:
    if not isinstance(record, dict):
        raise StrictConfigCIError(f"{location} stage evidence is not a dictionary")
    if set(record) != set(expected):
        raise StrictConfigCIError(f"{location} stage keys differ: {sorted(record)!r}")
    normalized: dict[str, int] = {}
    for key, expected_value in expected.items():
        value = record[key]
        if type(value) is not int or value != expected_value:
            raise StrictConfigCIError(
                f"{location} stage {key} is {value!r}; expected {expected_value}"
            )
        normalized[key] = value
    return normalized


def _test_role(args: argparse.Namespace) -> int:
    puffer_root = args.puffer_root.resolve()
    output = args.output.resolve()
    backend, module_path = _load_cpu_backend(
        puffer_root,
        expected_testing_role=True,
    )
    production_gate_rejected = False
    try:
        if getattr(backend, "strict_env_config_testing", None) is not False:
            raise StrictConfigCIError(
                "compiled CPU module is not the production config role"
            )
    except StrictConfigCIError:
        production_gate_rejected = True
    if not production_gate_rejected:
        raise StrictConfigCIError("test-role module passed the production role gate")

    stage_keys = {
        "normalize_calls": 0,
        "normalize_gil_held_calls": 0,
        "create_static_vec_calls": 0,
        "cuda_get_device_count_calls": 0,
        "create_pufferl_impl_calls": 0,
    }
    before = _require_stage_record(
        backend.strict_env_config_test_stages(reset=True),
        stage_keys,
        location="initial",
    )

    team_count = installed_team_count(puffer_root)
    try:
        backend.create_vec(
            {
                "vec": {"total_agents": math.nan, "num_buffers": 0},
                "env": {"force_home_team": team_count},
            },
            gpu=0,
        )
    except ValueError as exc:
        diagnostic = str(exc)
        fragment = "force_home_team must be integer -1 or " "0..BB_TEAM_COUNT-1"
        if fragment not in diagnostic:
            raise StrictConfigCIError(
                f"test-role rejection used the wrong diagnostic: {diagnostic}"
            ) from exc
    else:
        raise StrictConfigCIError("test-role module accepted invalid team config")

    failed = _require_stage_record(
        backend.strict_env_config_test_stages(reset=True),
        {
            **stage_keys,
            "normalize_calls": 1,
            "normalize_gil_held_calls": 1,
        },
        location="invalid construction",
    )
    positive = _construct_reset_close(
        backend,
        {"seed": 271828, "max_decisions": 1},
        profile="instrumented-sparse",
    )
    succeeded = _require_stage_record(
        backend.strict_env_config_test_stages(reset=True),
        {
            **stage_keys,
            "normalize_calls": 1,
            "normalize_gil_held_calls": 1,
            "create_static_vec_calls": 1,
        },
        location="valid construction",
    )
    evidence = {
        "schema_version": 1,
        "status": "accepted",
        "module": str(module_path),
        "module_sha256": _sha256_file(module_path),
        "environment_config_schema": backend.environment_config_schema,
        "strict_env_config_testing": backend.strict_env_config_testing,
        "production_gate_rejected": production_gate_rejected,
        "initial_stages": before,
        "invalid_stages": failed,
        "valid_stages": succeeded,
        "valid_profile": positive,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"strict environment CPU test-role integration: accepted ({output})")
    return 0


def _unrelated_environment(args: argparse.Namespace) -> int:
    puffer_root = args.puffer_root.resolve()
    output = args.output.resolve()
    if any(
        name == "pufferlib" or name.startswith("pufferlib.") for name in sys.modules
    ):
        raise StrictConfigCIError("pufferlib was imported before provenance validation")
    sys.path.insert(0, str(puffer_root))
    try:
        from pufferlib import _C  # type: ignore
    except Exception as exc:
        raise StrictConfigCIError(
            f"cannot import unrelated-environment CPU module: {exc}"
        ) from exc
    module_path = Path(_C.__file__).resolve()
    if not _path_beneath(module_path, puffer_root):
        raise StrictConfigCIError(
            f"unrelated module escaped the pinned clone: {module_path}"
        )
    if getattr(_C, "env_name", None) != UNRELATED_ENVIRONMENT:
        raise StrictConfigCIError(
            f"unrelated CPU module is not minimal: {getattr(_C, 'env_name', None)!r}"
        )
    if hasattr(_C, "environment_config_schema"):
        raise StrictConfigCIError(
            "marker-absent environment unexpectedly exports the Blood Bowl schema"
        )
    if getattr(_C, "strict_env_config_testing", None) is not False:
        raise StrictConfigCIError(
            "marker-absent environment is not in the production role"
        )
    if type(getattr(_C, "gpu", None)) is not int or _C.gpu != 0:
        raise StrictConfigCIError("unrelated-environment check imported a GPU module")

    profile = _construct_reset_close(
        _C,
        {"legacy_string_metadata": "preserve historical generic skip"},
        profile="minimal-string-valued-env",
        total_agents=UNRELATED_TOTAL_AGENTS,
    )
    evidence = {
        "schema_version": 1,
        "status": "accepted",
        "module": str(module_path),
        "module_sha256": _sha256_file(module_path),
        "env_name": _C.env_name,
        "environment_config_schema_present": hasattr(_C, "environment_config_schema"),
        "strict_env_config_testing": _C.strict_env_config_testing,
        "valid_profile": profile,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"unrelated environment compatibility: accepted ({output})")
    return 0


def _run(args: argparse.Namespace) -> int:
    repo_root = args.repo_root.resolve()
    puffer_root = args.puffer_root.resolve()
    raylib_archive = args.raylib_archive.resolve()
    output = args.output.resolve()

    pins = _read_requirement_pins(repo_root)
    expected_raylib_sha256 = _read_raylib_digest(repo_root)
    if raylib_archive.name != RAYLIB_ARCHIVE:
        raise StrictConfigCIError(
            f"Raylib archive has the wrong name: {raylib_archive.name}"
        )
    raylib_sha256 = _sha256_file(raylib_archive)
    if raylib_sha256 != expected_raylib_sha256:
        raise StrictConfigCIError(
            f"Raylib archive digest is {raylib_sha256}; "
            f"expected {expected_raylib_sha256}"
        )

    commit = _command_output(
        ["git", "rev-parse", "HEAD"], cwd=puffer_root
    ).splitlines()[-1]
    if commit != PUFFER_COMMIT:
        raise StrictConfigCIError(
            f"Puffer commit is {commit}; expected {PUFFER_COMMIT}"
        )
    observed_prefix, observed_executable = _validated_venv_identity(
        puffer_root,
        prefix=sys.prefix,
        executable=sys.executable,
    )

    backend, module_path = _load_cpu_backend(puffer_root)
    full_config = load_full_environment_config(puffer_root)
    team_count = installed_team_count(puffer_root)
    successful_profiles = [
        _construct_reset_close(backend, full_config, profile="full-51-key"),
        _construct_reset_close(
            backend,
            {},
            profile="empty-defaults",
        ),
        _construct_reset_close(
            backend,
            {"seed": 271828, "max_decisions": 1},
            profile="sparse-qualification",
        ),
        _construct_reset_close(
            backend,
            {
                "seed": 271830,
                "macro_moves": True,
                "reward_injury_value_scaled": False,
                "max_decisions": 1,
            },
            profile="exact-bool-transport",
        ),
        _construct_reset_close(
            backend,
            {
                "seed": 271829,
                "scripted_opponent": 1,
                "scripted_opponent_type": 0,
                "scripted_opponent_team": 2,
                "max_decisions": 1,
            },
            profile="scripted-both",
        ),
    ]
    if (
        tuple(profile["profile"] for profile in successful_profiles)
        != VALID_PROFILE_NAMES
    ):
        raise StrictConfigCIError("valid construction profile set drifted")

    ledger = read_source_ledger(
        repo_root / COMPILED_LEDGER,
        expected_count=9,
    )
    backend_sources_sha256 = source_manifest_sha256(puffer_root, ledger)
    compiled_backend_sha256 = getattr(backend, "exact_action_source_hash", None)
    header = puffer_root / "src/exact_action_build_hash.h"
    header_backend_sha256 = _header_macro(header, "PUFFER_EXACT_ACTION_SOURCE_HASH")
    if not (backend_sources_sha256 == compiled_backend_sha256 == header_backend_sha256):
        raise StrictConfigCIError(
            "compiled/on-disk/header backend source digests disagree"
        )

    installed_environment_root = puffer_root / "ocean/bloodbowl"
    environment_sha256 = environment_source_sha256(installed_environment_root)
    content_hash = _single_line(installed_environment_root / ".content_hash")
    compiled_environment_sha256 = getattr(backend, "environment_source_hash", None)
    header_environment_sha256 = _header_macro(header, "PUFFER_ENV_SOURCE_HASH")
    if not (
        environment_sha256
        == content_hash
        == compiled_environment_sha256
        == header_environment_sha256
    ):
        raise StrictConfigCIError(
            "compiled/on-disk/header environment source digests disagree"
        )

    invalid_records = _run_invalid_cases(
        puffer_root=puffer_root,
        team_count=team_count,
    )
    standalone = puffer_root / "bloodbowl"
    evidence = {
        "schema_version": 1,
        "status": "accepted",
        "puffer": {
            "commit": commit,
            "root": str(puffer_root),
            "module": str(module_path),
            "module_sha256": _sha256_file(module_path),
            "standalone": str(standalone.resolve()),
            "standalone_sha256": _sha256_file(standalone),
        },
        "raylib": {
            "archive": RAYLIB_ARCHIVE,
            "sha256": raylib_sha256,
        },
        "runtime": {
            "python": {
                "implementation": sys.implementation.name,
                "version": sys.version,
                "executable": str(observed_executable),
                "prefix": str(observed_prefix),
            },
            "packages": _installed_versions(pins),
            "requirements_options": list(EXPECTED_REQUIREMENT_OPTIONS),
            "clang": _command_output(["clang", "--version"]),
            "cxx": _command_output(["c++", "--version"]),
            "openmp_packages": {
                "libomp-dev": _command_output(
                    ["dpkg-query", "-W", "-f=${Version}", "libomp-dev"]
                ),
                "libomp5": _command_output(
                    ["dpkg-query", "-W", "-f=${Version}", "libomp5"]
                ),
            },
        },
        "contracts": {
            "env_name": backend.env_name,
            "environment_config_schema": backend.environment_config_schema,
            "strict_env_config_testing": backend.strict_env_config_testing,
            "gpu": backend.gpu,
            "precision_bytes": backend.precision_bytes,
            "observation_abi": backend.observation_abi,
            "observation_version": backend.observation_version,
            "action_abi": backend.action_abi,
            "compiled_backend_sources": list(ledger),
            "backend_sources_sha256": backend_sources_sha256,
            "compiled_backend_sha256": compiled_backend_sha256,
            "header_backend_sha256": header_backend_sha256,
            "environment_source_sha256": environment_sha256,
            "recorded_environment_source_sha256": content_hash,
            "compiled_environment_source_sha256": compiled_environment_sha256,
            "header_environment_source_sha256": header_environment_sha256,
            "installed_config_sha256": _sha256_file(
                puffer_root / "config/bloodbowl.ini"
            ),
            "environment_config_key_count": len(full_config),
            "team_count": team_count,
        },
        "valid_profiles": successful_profiles,
        "native_ledger_domain_cases": dict(NATIVE_LEDGER_DOMAIN_CASES),
        "cross_field_cases": list(CROSS_FIELD_CASES),
        "invalid_cases": invalid_records,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"strict environment CPU integration: accepted ({output})")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run")
    run.add_argument("--repo-root", type=Path, required=True)
    run.add_argument("--puffer-root", type=Path, required=True)
    run.add_argument("--raylib-archive", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)

    invalid = subparsers.add_parser("_invalid-case")
    invalid.add_argument("--puffer-root", type=Path, required=True)
    invalid.add_argument("--team-count", type=int, required=True)
    invalid.add_argument("--case", choices=tuple(INVALID_CASES), required=True)

    test_role = subparsers.add_parser("test-role")
    test_role.add_argument("--puffer-root", type=Path, required=True)
    test_role.add_argument("--output", type=Path, required=True)

    unrelated = subparsers.add_parser("unrelated-environment")
    unrelated.add_argument("--puffer-root", type=Path, required=True)
    unrelated.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "run":
        return _run(args)
    if args.command == "_invalid-case":
        return _invalid_case(args)
    if args.command == "test-role":
        return _test_role(args)
    if args.command == "unrelated-environment":
        return _unrelated_environment(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except StrictConfigCIError as exc:
        print(f"strict environment CPU integration failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
