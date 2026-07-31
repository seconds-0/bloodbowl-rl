#!/usr/bin/env python3
"""Independently verify and seal an F5 foundation evidence directory."""

from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any, NoReturn


ROOT = Path(__file__).resolve().parents[1]
SAFE_SYSTEM_PATH = (
    "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/usr/local/sbin:"
    "/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/swift/usr/bin"
)
SAFE_PASSTHROUGH_ENV_NAMES = (
    "TMPDIR",
    "TMP",
    "TEMP",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)
EVIDENCE_SCHEMA = "bloodbowl-f5-foundation-evidence-v1"
VERDICT_SCHEMA = "bloodbowl-f5-foundation-verdict-v1"
PUFFER_COMMIT = "9836f0d2e78889c1aaf189c04d161b6fc61a9386"
FIXTURE_ROLE = "f5-fixed-state-v1"
PUFFER_ENTRYPOINT_BODY = (
    b"import sys\n"
    b"from pufferlib.pufferl import main\n"
    b"if __name__ == '__main__':\n"
    b"    if sys.argv[0].endswith('.exe'):\n"
    b"        sys.argv[0] = sys.argv[0][:-4]\n"
    b"    sys.exit(main())\n"
)
PUFFER_ENTRYPOINT_NORMALIZED = (
    b"#!<puffer-python>\n" + PUFFER_ENTRYPOINT_BODY
)
PUFFER_INTERPRETER_PROBE = r"""
import json
import sys

result = {
    "implementation": sys.implementation.name,
    "platlibdir": sys.platlibdir,
    "version": ".".join(str(value) for value in sys.version_info[:3]),
}
print(json.dumps(
    result,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=True,
    allow_nan=False,
))
"""
PUFFER_STARTUP_RUNTIME_PROBE = r"""
import json
import site
import sitecustomize
import sys

result = {
    "base_prefix": sys.base_prefix,
    "dont_write_bytecode": bool(sys.flags.dont_write_bytecode),
    "implementation": sys.implementation.name,
    "isolated": sys.flags.isolated,
    "no_site": sys.flags.no_site,
    "platlibdir": sys.platlibdir,
    "prefix": sys.prefix,
    "sitecustomize_is_sys": sitecustomize is sys,
    "sys_path": sys.path,
    "user_site_enabled": site.ENABLE_USER_SITE,
    "version": ".".join(str(value) for value in sys.version_info[:3]),
}
print(json.dumps(
    result,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=True,
    allow_nan=False,
))
"""
PUFFER_DISTRIBUTION_PROBE = r"""
import importlib.metadata
import json
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

root = Path(sys.argv[1]).resolve(strict=True)
distribution = importlib.metadata.distribution("pufferlib")
direct = json.loads(distribution.read_text("direct_url.json"))
parsed = urlparse(direct["url"])
if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
    raise SystemExit("pufferlib editable source is not a local file URL")
source = Path(unquote(parsed.path)).resolve(strict=True)
result = {
    "name": distribution.metadata["Name"],
    "version": distribution.version,
    "editable": direct.get("dir_info", {}).get("editable"),
    "source_matches_pinned_root": source == root,
}
print(json.dumps(
    result,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=True,
    allow_nan=False,
))
"""
INDEPENDENT_ORDINARY_MODULE_PROBE = r"""
import hashlib
import json
import sys
from pathlib import Path

tools = Path(sys.argv[1]).resolve(strict=True)
root = Path(sys.argv[2]).resolve(strict=True)
sys.path.insert(0, str(tools))
import state_bank_contract as contract
sys.path.insert(0, str(root))
from pufferlib import _C

module = Path(_C.__file__).resolve(strict=True)
result = {
    "schema": "bloodbowl-f5-ordinary-module-v1",
    "module_path": module.relative_to(root).as_posix(),
    "module_sha256": hashlib.sha256(module.read_bytes()).hexdigest(),
    "module_contract": {
        "env_name": getattr(_C, "env_name", None),
        "gpu": int(bool(getattr(_C, "gpu", False))),
        "observation_abi": getattr(_C, "observation_abi", None),
        "observation_version": getattr(_C, "observation_version", None),
        "action_abi": getattr(_C, "action_abi", None),
        "rollout_transition_contract": getattr(
            _C, "rollout_transition_contract", None),
        "entropy_schedule_contract": getattr(
            _C, "entropy_schedule_contract", None),
        "environment_config_schema": getattr(
            _C, "environment_config_schema", None),
        "strict_env_config_testing": getattr(
            _C, "strict_env_config_testing", None),
        "exact_action_source_sha256": getattr(
            _C, "exact_action_source_hash", None),
        "environment_source_sha256": getattr(
            _C, "environment_source_hash", None),
    },
    "qualification_fixture": contract.qualification_fixture_from_module(_C),
    "state_bank": contract.contract_from_module(_C),
}
print(json.dumps(
    result,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=True,
    allow_nan=False,
))
"""
FULL_BBS_SHA256 = (
    "c984e22178901539157be062764dcaff1efac345836dffb5be17a5b7537447a1"
)
F5_BBS_SHA256 = (
    "0fe8f1ea3f0470bef2c43709947d2bd3a9fd418b0b7b9d5ca93003e720702e71"
)
MATCH_SHA256 = (
    "aab28e6e08184d05a6912d033899916d0228984c38c87e606ee3f2a5d25ac9f2"
)
TRACE_SHA256 = (
    "456e336e5eaa92e4e5fdedfb753d237a163e9a8e4e58ff09fa8979d2a91f4300"
)
HEADER_SHA256 = (
    "a9f506a5440f55ce92febd0fdabd16ef3604f6d5dee4f05f0c896ac47c951760"
)
DEPENDENCY_REQUIREMENTS_SHA256 = (
    "010a1f6a785d9c7e7b421f345eeae10a177891fae7e56454111da18c0bed9aa6"
)
DEPENDENCY_IDENTITY_SCOPE = (
    "canonical-installed-distribution-name-version-snapshot;"
    "not-wheel-byte-lock"
)
SEALED_EDITABLE_PTH_NAME = "pufferlib-editable.pth"
SEALED_SITE_BOOTSTRAP_LINE = (
    "import sys;sys.modules['sitecustomize']=sys\n"
)
RAYLIB_INPUTS = {
    ("darwin", "arm64"): {
        "directory": "raylib-5.5_macos",
        "archive_sha256":
            "930c67b676963c6cffbd965814664523081ecbf3d30fc9df4211d0064aa6ba39",
        "library_sha256":
            "5517f19555ce6e19540ac534bb5d5bf08ba45660d14642db4878f079a9f1b7da",
    },
    ("linux", "x86_64"): {
        "directory": "raylib-5.5_linux_amd64",
        "archive_sha256":
            "3d95ef03d5b38dfa55c0a16ca122d382134b078f0e5b270b52fe7eae0549c000",
        "library_sha256":
            "3323cbf14ec6e640e19d63e230e68c3a530be3e9a9d416435eab82160e9e9ccc",
    },
}
PRISTINE_PUFFER_NATIVE_INPUT_PATHS = tuple(
    sorted(
        {"raylib-archives"}
        | {value["directory"] for value in RAYLIB_INPUTS.values()}
    )
)
FOUNDATION_CFLAGS = (
    "-std=c11 -O2 -g -Wall -Wextra -Werror -Iengine/include"
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
REFERENCE_SUPPORT_COUNTS = (
    (2, 11, 1),
    (1, 4, 1),
    (2, 1, 8),
    (2, 1, 8),
    (2, 1, 8),
    (2, 1, 8),
    (2, 1, 8),
    (2, 1, 8),
)
REFERENCE_MATCH_BEFORE_SHA256 = (
    MATCH_SHA256,
    "39c88a6163afd3b52799a46d64736021abe16d75a0b3e5e0be20b41a862764fb",
    "d4da99c706eb3714e5d6da3f031ef7e6440c8d7562442e63d3ced861ee82275a",
    "2e9c1c607b62e9afd51942170e2f804b0ed0acdf8ea5026e74ba73e24583bd2a",
    "3d22e8b15ecb97ac262625bd041f15625c8a98caa955eee361330aeba4d845ee",
    "8ec53d84b8d2aea0da9c1cb392933d46e6cd82f4e8cf8880ee9e85217b6885ed",
    "7882ef239430fa217ded224b2c5a5cc506e37423a4bb09bd0d3573ffe994ba1e",
    "523ec3d2c01a9cbe69ffb592e0a6efd2bccd266eb85d0a3969c64692360c0be1",
)
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
ROLLOUT_EFFECTIVE_MASK_SHA256 = (
    (
        "21985bfb28f780a7d811d1f6a2bb8a4d525ade5abab8d84375dc228252825253",
        "99037d2f21c321449a7c60969f63aed41d6dd8f9b9c6283d03fb485003b96017",
    ),
    (
        "77381f23172abd74a314157a16bff2a6d18958da13e17bbd821a478372f38f35",
        "99037d2f21c321449a7c60969f63aed41d6dd8f9b9c6283d03fb485003b96017",
    ),
    (
        "700e776704349219e00813ed94bba536fc81e5988c1f1c7093e5d0bef5425f42",
        "99037d2f21c321449a7c60969f63aed41d6dd8f9b9c6283d03fb485003b96017",
    ),
    (
        "ba478b8a87ca4cdb58ece94737e9e36bd90801311eead055dae2002391659e2d",
        "99037d2f21c321449a7c60969f63aed41d6dd8f9b9c6283d03fb485003b96017",
    ),
    (
        "85f31a3350d70d1bb21a35a6c47993d33753c3bb593b0c2e06b8635f0c62af80",
        "99037d2f21c321449a7c60969f63aed41d6dd8f9b9c6283d03fb485003b96017",
    ),
    (
        "8c2986757b62d59f1a3ebbccabcd3b9f92f0751d7f1741a8478e4c02d1da5ec2",
        "99037d2f21c321449a7c60969f63aed41d6dd8f9b9c6283d03fb485003b96017",
    ),
    (
        "2c29c3ef53fdd330c2b80cf8884832d4c128763896bdf56ec1c55a6500bb3afe",
        "99037d2f21c321449a7c60969f63aed41d6dd8f9b9c6283d03fb485003b96017",
    ),
    (
        "e149705bf111e46e316e41fa33644de64416368cc9492398da2d64d0f47fc8b0",
        "99037d2f21c321449a7c60969f63aed41d6dd8f9b9c6283d03fb485003b96017",
    ),
)
AUTORESET_OBS_SHA256 = (
    "b93e05d2140335b1ced4b85d8c4d75a3a68f50e7425d2791968b8b509d530f67"
)
AUTORESET_MASK_SHA256 = (
    "4e09752de7862ca03914be419360f163bfb1162a75565de4895765da62ff8e5c"
)
RANDOM_EPISODES = 100_000
RANDOM_SEED = 245
EXPECTED_RANDOM_BASELINE = {
    "schema": "bloodbowl-f5-random-baseline-v1",
    "seed": RANDOM_SEED,
    "episodes": RANDOM_EPISODES,
    "decisions": 800_000,
    "agent_steps": 1_600_000,
    "successes": 0,
    "tds_t1": 0,
    "early_terminals": 0,
    "illegal": 0,
    "collisions": 0,
    "dice": 472_158,
    "test_windows": 11_396,
    "fixture_resets": RANDOM_EPISODES,
    "reward_totals": [0, 0],
    "episode_lengths": [0, 0, 0, 0, 0, 0, 0, RANDOM_EPISODES],
}
EXPECTED_MODULE_LOG = {
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
EXPECTED_MASKED_RANDOM_ZERO_INTEGRITY_KEYS = (
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
EXPECTED_MASKED_RANDOM_INTEGRITY = {
    key: 0.0 for key in EXPECTED_MASKED_RANDOM_ZERO_INTEGRITY_KEYS
}
EXPECTED_MASKED_RANDOM_INTEGRITY.update(
    {
        "n": 1000.0,
        "episode_length": 8.0,
        "reward_samples_per_episode": 16.0,
        "tds_t0": 0.0,
        "tds_t1": 0.0,
    }
)
EXPECTED_MASKED_RANDOM = {
    "episodes": 1000,
    "seed": 245,
    "sampler": "sequential-conditional-unique-uniform-v1",
    "reference_fallbacks": 0,
    "decisions": 8000,
    "agent_steps": 16000,
    "episode_length_min": 8,
    "episode_length_max": 8,
    "episode_length_mean": 8.0,
    "exact_autoresets": 1000,
    "successes": 0,
    "tds_t0": 0,
    "tds_t1": 0,
    "dice": {"exposed": False},
    "illegal_frac": 0.0,
    "projection_collisions": 0,
    "joint_support_rows_checked": 18_002,
    "error_episodes": 0.0,
    "reward_nonfinite_frac": 0.0,
    "integrity": EXPECTED_MASKED_RANDOM_INTEGRITY,
}
EXPECTED_LIFECYCLE_STEPS = [
    {
        "id": "ordinary-install",
        "command": [
            "/bin/bash",
            "tools/install_puffer_env.sh",
            "<pinned-puffer-root>",
        ],
        "exit_code": 0,
    },
    {
        "id": "ordinary-cpu-build",
        "command": [
            "/usr/bin/env",
            "CC=<resolved-puffer-cc>",
            "CXX=<resolved-puffer-cxx>",
            "/bin/bash",
            "./build.sh",
            "bloodbowl",
            "--cpu",
        ],
        "exit_code": 0,
    },
    {
        "id": "ordinary-fast-build",
        "command": [
            "/usr/bin/env",
            "CC=<resolved-puffer-cc>",
            "CXX=<resolved-puffer-cxx>",
            "/bin/bash",
            "./build.sh",
            "bloodbowl",
            "--fast",
        ],
        "exit_code": 0,
    },
    {
        "id": "ordinary-check",
        "command": [
            "/bin/bash",
            "tools/install_puffer_env.sh",
            "--check",
            "<pinned-puffer-root>",
        ],
        "exit_code": 0,
    },
    {
        "id": "ordinary-module-none",
        "command": [
            "<puffer-python>",
            "-B",
            "-I",
            "<ordinary-module-role-probe-v1>",
            "<source-tools>",
            "<pinned-puffer-root>",
        ],
        "exit_code": 0,
    },
    {
        "id": "f5-check-rejects-ordinary",
        "command": [
            "/bin/bash",
            "tools/install_f5_trainability_env.sh",
            "--check",
            "<pinned-puffer-root>",
        ],
        "exit_code": 1,
    },
    {
        "id": "f5-stage",
        "command": [
            "/bin/bash",
            "tools/install_f5_trainability_env.sh",
            "<pinned-puffer-root>",
        ],
        "exit_code": 0,
    },
    {
        "id": "f5-cpu-rebuild",
        "command": [
            "/usr/bin/env",
            "CC=<resolved-puffer-cc>",
            "CXX=<resolved-puffer-cxx>",
            "/bin/bash",
            "./build.sh",
            "bloodbowl",
            "--cpu",
        ],
        "exit_code": 0,
    },
    {
        "id": "f5-check",
        "command": [
            "/bin/bash",
            "tools/install_f5_trainability_env.sh",
            "--check",
            "<pinned-puffer-root>",
        ],
        "exit_code": 0,
    },
    {
        "id": "f5-install-rejects-already-staged",
        "command": [
            "/bin/bash",
            "tools/install_f5_trainability_env.sh",
            "<pinned-puffer-root>",
        ],
        "exit_code": 1,
    },
    {
        "id": "f5-module-proof",
        "command": [
            "<puffer-python>",
            "-B",
            "-I",
            "tools/check_f5_trainability_module.py",
            "--puffer-root",
            "<pinned-puffer-root>",
            "--output",
            "puffer-module.json",
        ],
        "exit_code": 0,
    },
    {
        "id": "ordinary-install-rejects-f5",
        "command": [
            "/bin/bash",
            "tools/install_puffer_env.sh",
            "<pinned-puffer-root>",
        ],
        "exit_code": 1,
    },
    {
        "id": "production-ablation-rejects-f5",
        "command": [
            "/bin/bash",
            "<launcher-projection>/tools/run_reward_ablation.sh",
        ],
        "exit_code": 1,
    },
    {
        "id": "production-screen-rejects-f5",
        "command": [
            "/bin/bash",
            "<launcher-projection>/tools/run_reward_screen.sh",
        ],
        "exit_code": 1,
    },
]
EXPECTED_ORDINARY_QUALIFICATION_FIXTURE = {
    "enabled": 0,
    "role": "none",
    "schema": "none",
    "qualification_only": 0,
    "match_sha256": "unused",
    "bbs_sha256": "unused",
    "bundle_sha256": "unused",
    "bbs_source_id": 0,
    "authored_source_id": 0,
    "reference_trace_schema": "none",
    "reference_trace_sha256": "unused",
    "max_decisions": 0,
    "reward_contract": "none",
}
EXPECTED_NO_BANK_STATE = {
    "contract_schema": "none",
    "producer_schema": "none",
    "authorization_schema": "none",
    "strata_schema": "bloodbowl-legacy-state-bank-strata-v1",
    "kind_value": 0,
    "kind": "none",
    "ruleset": "none",
    "bank_sha256": "unused",
    "producer_manifest_sha256": "unused",
    "training_contract_sha256": "unused",
    "producer_engine_source_sha256": "unused",
    "loader_engine_source_sha256": "unused",
    "bytes": 0,
    "records": 0,
    "bbs_version": 0,
    "match_size": 0,
    "engine_fingerprint": 0,
    "contract_identity": "none",
    "bank_path": "unused",
    "producer_manifest_path": "unused",
    "training_contract_path": "unused",
}
EXPECTED_COMMANDS = [
    [
        "make",
        "-B",
        "CC=<resolved-cc>",
        f"CFLAGS={FOUNDATION_CFLAGS}",
        "LDFLAGS=",
        "build/f5_trainability_foundation",
        "build/puffer_f5_trainability_tests",
        "build/f5_trainability_diagnostics",
    ],
    [
        "build/f5_trainability_foundation",
        "generate",
        "--output",
        "task",
    ],
    [
        "build/f5_trainability_foundation",
        "verify",
        "--input",
        "task",
    ],
    ["build/puffer_f5_trainability_tests"],
    ["build/f5_trainability_diagnostics", "reference"],
    ["build/f5_trainability_diagnostics", "enumerate"],
    [
        "build/f5_trainability_diagnostics",
        "random",
        "--episodes",
        str(RANDOM_EPISODES),
        "--seed",
        str(RANDOM_SEED),
    ],
    *[step["command"] for step in EXPECTED_LIFECYCLE_STEPS],
]
GENERATOR = ROOT / "build/f5_trainability_foundation"
C_TEST = ROOT / "build/puffer_f5_trainability_tests"
DIAGNOSTICS = ROOT / "build/f5_trainability_diagnostics"
MODULE_CHECKER = ROOT / "tools/check_f5_trainability_module.py"
ENV_CONFIG = ROOT / "training/f5_trainability_env.json"
CHECKED_FIXTURE_HEADER = (
    ROOT / "puffer/bloodbowl/f5_trainability_fixture.generated.h"
)
MAX_JSON_BYTES = 8 << 20


class FoundationVerificationError(RuntimeError):
    """The evidence directory is incomplete, mutated, or noncanonical."""


def fail(message: str) -> NoReturn:
    raise FoundationVerificationError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            fail(f"duplicate JSON key {key!r}")
        value[key] = item
    return value


def load_json(path: Path) -> dict[str, Any]:
    payload = read_regular_bytes(
        path,
        maximum=MAX_JSON_BYTES,
        location=str(path),
    )
    return load_json_bytes(payload, str(path))


def exact_keys(value: dict[str, Any], expected: set[str], location: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        observed = set(value) if isinstance(value, dict) else set()
        fail(
            f"{location} keys differ; missing={sorted(expected - observed)}, "
            f"unknown={sorted(observed - expected)}"
        )


def exact_json_equal(actual: Any, expected: Any) -> bool:
    """Compare JSON values without Python's bool/int equality aliasing."""

    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return (
            set(actual) == set(expected)
            and all(
                exact_json_equal(actual[key], expected[key])
                for key in expected
            )
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            exact_json_equal(left, right)
            for left, right in zip(actual, expected)
        )
    return actual == expected


def require_exact(actual: Any, expected: Any, location: str) -> None:
    if not exact_json_equal(actual, expected):
        fail(f"{location} differs")


def require_sha256(value: Any, location: str) -> str:
    if (
        type(value) is not str
        or re.fullmatch(r"[0-9a-f]{64}", value) is None
    ):
        fail(f"{location} is not a lowercase SHA-256")
    return value


def read_regular_bytes(path: Path, *, maximum: int, location: str) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        fail(f"cannot open {location}: {exc}")
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size <= 0
            or before.st_size > maximum
        ):
            fail(f"{location} is not a bounded singly linked regular file")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            block = os.read(descriptor, min(remaining, 1 << 20))
            if not block:
                fail(f"{location} became truncated while being read")
            chunks.append(block)
            remaining -= len(block)
        if os.read(descriptor, 1):
            fail(f"{location} grew while being read")
        after = os.fstat(descriptor)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if identity_after != identity_before:
            fail(f"{location} changed while being read")
        return b"".join(chunks)
    except OSError as exc:
        fail(f"cannot read {location}: {exc}")
    finally:
        os.close(descriptor)


def load_json_bytes(payload: bytes, location: str) -> dict[str, Any]:
    try:
        value = json.loads(
            payload.decode("ascii"),
            object_pairs_hook=_pairs,
            parse_constant=lambda token: fail(
                f"{location} contains nonfinite {token}"
            ),
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        fail(f"cannot parse {location}: {exc}")
    if not isinstance(value, dict):
        fail(f"{location} root is not an object")
    return value


def reject_worker_verdicts(value: Any, location: str = "evidence") -> None:
    if isinstance(value, dict):
        forbidden = {"accepted", "passed"} & set(value)
        if forbidden:
            fail(f"{location} contains worker-authored verdict keys {forbidden}")
        for key, item in value.items():
            reject_worker_verdicts(item, f"{location}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_worker_verdicts(item, f"{location}[{index}]")


def run_checked(
    command: list[str],
    *,
    cwd: Path = ROOT,
    timeout: int = 900,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    if environment is None:
        environment = isolated_python_environment()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        fail(f"verification command could not run: {command!r}: {exc}")
    if completed.returncode != 0:
        fail(
            f"verification command failed ({completed.returncode}): "
            f"{command!r}; stdout={completed.stdout[-3000:]!r}; "
            f"stderr={completed.stderr[-3000:]!r}"
        )
    return completed


def foundation_compiler() -> Path:
    raw = shutil.which("cc", path=SAFE_SYSTEM_PATH)
    if raw is None:
        fail("the sealed foundation compiler cc is absent")
    try:
        compiler = Path(raw).resolve(strict=True)
    except OSError as exc:
        fail(f"cannot resolve the sealed foundation compiler: {exc}")
    if not compiler.is_file():
        fail(f"sealed foundation compiler is not a file: {compiler}")
    return compiler


def foundation_build_environment() -> dict[str, str]:
    environment = isolated_python_environment()
    environment["LC_ALL"] = "C"
    return environment


def isolated_python_environment() -> dict[str, str]:
    environment = {
        name: os.environ[name]
        for name in SAFE_PASSTHROUGH_ENV_NAMES
        if name in os.environ
    }
    environment["PATH"] = SAFE_SYSTEM_PATH
    environment["LC_ALL"] = "C"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = "/dev/null"
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    return environment


def git_output(root: Path, *arguments: str) -> str:
    return run_checked(
        ["git", "-C", str(root), *arguments], cwd=root, timeout=30
    ).stdout.strip()


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("ascii")


def atomic_write(path: Path, payload: bytes) -> None:
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


def validate_source(evidence: dict[str, Any]) -> None:
    source = evidence["source"]
    exact_keys(source, {"commit", "tree", "dirty", "status"}, "source")
    if source["dirty"] is not False or source["status"] != []:
        fail("authoritative evidence must come from a clean source tree")
    if source["commit"] != git_output(ROOT, "rev-parse", "HEAD"):
        fail("evidence source commit is not current HEAD")
    if source["tree"] != git_output(ROOT, "rev-parse", "HEAD^{tree}"):
        fail("evidence source tree is not current HEAD tree")
    if git_output(
        ROOT, "status", "--porcelain=v1", "--untracked-files=all"
    ):
        fail("source worktree became dirty before independent verification")


def validate_platform(evidence: dict[str, Any]) -> None:
    compiler = foundation_compiler()
    build_environment = foundation_build_environment()
    compiler_output = run_checked(
        [str(compiler), "--version"],
        timeout=30,
        environment=build_environment,
    ).stdout
    compiler_lines = compiler_output.splitlines()
    if not compiler_lines:
        fail("compiler did not publish a version identity")
    compiler_target = run_checked(
        [str(compiler), "-dumpmachine"],
        timeout=30,
        environment=build_environment,
    ).stdout.strip()
    if not compiler_target or "\n" in compiler_target:
        fail("compiler did not publish one target identity")
    expected = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "sys_platform": sys.platform,
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_cache_tag": sys.implementation.cache_tag,
        "compiler_executable": str(compiler),
        "compiler_sha256": sha256_file(compiler),
        "compiler_version": compiler_lines[0],
        "compiler_target": compiler_target,
        "cflags": FOUNDATION_CFLAGS,
        "ldflags": "",
    }
    exact_keys(evidence["platform"], set(expected), "platform")
    require_exact(evidence["platform"], expected, "platform receipt")


def validate_artifacts(root: Path, evidence: dict[str, Any]) -> None:
    manifest = evidence["artifacts"]
    if not isinstance(manifest, dict) or not manifest:
        fail("artifact manifest is empty or malformed")
    expected_files: set[str] = set()
    expected_directories: set[str] = set()
    for relative, description in manifest.items():
        if (
            not isinstance(relative, str)
            or not relative
            or relative in {"evidence.json", "verdict.json"}
            or relative.startswith("/")
            or "\\" in relative
            or Path(relative).as_posix() != relative
            or Path(relative).as_posix() in {".", ".."}
            or ".." in Path(relative).parts
            or not isinstance(description, dict)
        ):
            fail(f"artifact manifest entry is unsafe: {relative!r}")
        expected_files.add(relative)
        parent = Path(relative).parent
        while parent.as_posix() != ".":
            expected_directories.add(parent.as_posix())
            parent = parent.parent

    observed_files: set[str] = set()
    observed_directories: set[str] = set()

    def walk(directory: Path, relative_directory: Path) -> None:
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            fail(f"cannot enumerate evidence directory {directory}: {exc}")
        for entry in entries:
            relative_path = relative_directory / entry.name
            relative = relative_path.as_posix()
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                fail(f"cannot stat evidence entry {relative}: {exc}")
            if stat.S_ISLNK(info.st_mode):
                fail(f"evidence contains symlink {relative}")
            if stat.S_ISDIR(info.st_mode):
                observed_directories.add(relative)
                walk(Path(entry.path), relative_path)
            elif stat.S_ISREG(info.st_mode):
                if info.st_nlink != 1:
                    fail(f"evidence file is multiply linked: {relative}")
                observed_files.add(relative)
            else:
                fail(f"evidence contains non-regular entry {relative}")

    walk(root, Path())
    allowed_files = expected_files | {"evidence.json"}
    if observed_files != allowed_files:
        fail(
            "artifact membership differs; "
            f"missing={sorted(allowed_files - observed_files)}, "
            f"extra={sorted(observed_files - allowed_files)}"
        )
    if observed_directories != expected_directories:
        fail(
            "artifact directory membership differs; "
            f"missing={sorted(expected_directories - observed_directories)}, "
            f"extra={sorted(observed_directories - expected_directories)}"
        )
    for relative, description in manifest.items():
        exact_keys(description, {"bytes", "sha256"}, f"artifacts.{relative}")
        path = root / relative
        if (
            type(description["bytes"]) is not int
            or description["bytes"] != path.stat().st_size
            or description["sha256"] != sha256_file(path)
        ):
            fail(f"artifact identity differs: {relative}")


def validate_task(
    root: Path, evidence: dict[str, Any], *, generator: Path
) -> None:
    task_summary = evidence["task"]
    exact_keys(
        task_summary,
        {
            "path",
            "sha256",
            "full_bundle_sha256",
            "f5_bbs_sha256",
            "raw_match_sha256",
            "reference_trace_sha256",
            "generated_header_sha256",
        },
        "task",
    )
    expected = {
        "path": "task/task.json",
        "full_bundle_sha256": FULL_BBS_SHA256,
        "f5_bbs_sha256": F5_BBS_SHA256,
        "raw_match_sha256": MATCH_SHA256,
        "reference_trace_sha256": TRACE_SHA256,
        "generated_header_sha256": HEADER_SHA256,
    }
    for key, wanted in expected.items():
        if task_summary[key] != wanted:
            fail(f"task summary {key} differs")
    task_path = root / "task/task.json"
    if task_summary["sha256"] != sha256_file(task_path):
        fail("task descriptor digest differs")
    task = load_json(task_path)
    anchors = {
        "schema": "bloodbowl-trainability-task-v1",
        "qualification_only": True,
        "qualification_fixture_role": FIXTURE_ROLE,
        "full_bundle_records": 26,
        "full_bundle_sha256": FULL_BBS_SHA256,
        "f5_bbs_sha256": F5_BBS_SHA256,
        "raw_match_sha256": MATCH_SHA256,
        "generated_header_sha256": HEADER_SHA256,
        "proof_source_id": "0xA9000019",
        "durable_source_id": "0xAE00001A",
        "reference_trace_sha256": TRACE_SHA256,
        "max_decisions": 8,
    }
    for key, wanted in anchors.items():
        if task.get(key) != wanted or type(task[key]) is not type(wanted):
            fail(f"task descriptor {key} differs")
    hashes = {
        "task/authored-proof-bundle.bbs": FULL_BBS_SHA256,
        "task/f5.bbs": F5_BBS_SHA256,
        "task/f5.match": MATCH_SHA256,
        "task/reference-trace.json": TRACE_SHA256,
        "task/f5_trainability_fixture.generated.h": HEADER_SHA256,
    }
    for relative, wanted in hashes.items():
        if sha256_file(root / relative) != wanted:
            fail(f"task artifact {relative} differs")
    generated_header = root / "task/f5_trainability_fixture.generated.h"
    checked_header = read_regular_bytes(
        CHECKED_FIXTURE_HEADER,
        maximum=1 << 20,
        location="checked-in F5 generated fixture header",
    )
    if (
        hashlib.sha256(checked_header).hexdigest() != HEADER_SHA256
        or generated_header.read_bytes() != checked_header
    ):
        fail("checked-in F5 fixture header differs from fresh generator output")
    run_checked([str(generator), "verify", "--input", str(root / "task")])


def validate_reference(
    root: Path, evidence: dict[str, Any], *, diagnostics: Path
) -> None:
    summary = evidence["reference"]
    exact_keys(
        summary,
        {
            "path",
            "sha256",
            "episodes",
            "decisions",
            "home_meaningful_rows",
            "away_null_rows",
            "agent_steps",
        },
        "reference",
    )
    expected = {
        "path": "reference.json",
        "episodes": 1,
        "decisions": 8,
        "home_meaningful_rows": 8,
        "away_null_rows": 8,
        "agent_steps": 16,
    }
    for key, wanted in expected.items():
        if summary[key] != wanted:
            fail(f"reference summary {key} differs")
    path = root / "reference.json"
    if summary["sha256"] != sha256_file(path):
        fail("reference evidence digest differs")
    reference = load_json(path)
    exact_keys(
        reference,
        {"schema", "fixture_role", "transitions", "summary"},
        "reference diagnostic",
    )
    if (
        reference["schema"] != "bloodbowl-f5-reference-diagnostic-v1"
        or reference["fixture_role"] != FIXTURE_ROLE
        or not isinstance(reference["transitions"], list)
        or len(reference["transitions"]) != 8
    ):
        fail("reference diagnostic identity differs")
    transition_keys = {
        "decision",
        "heads",
        "decision_team",
        "support_counts",
        "waiting_singleton",
        "match_before_sha256",
        "obs_sha256",
        "mask_sha256",
        "rewards",
        "terminals",
        "dice",
        "illegal",
        "collisions",
    }
    for offset, row in enumerate(reference["transitions"]):
        decision = offset + 1
        exact_keys(row, transition_keys, f"reference transition {decision}")
        expected = {
            "decision": decision,
            "heads": list(REFERENCE_HEADS[offset]),
            "decision_team": 0,
            "support_counts": list(REFERENCE_SUPPORT_COUNTS[offset]),
            "waiting_singleton": True,
            "match_before_sha256": REFERENCE_MATCH_BEFORE_SHA256[offset],
            "obs_sha256": list(REFERENCE_OBS_SHA256[offset]),
            "mask_sha256": list(REFERENCE_MASK_SHA256[offset]),
            "rewards": [0, 0] if decision < 8 else [1, -1],
            "terminals": [0, 0] if decision < 8 else [1, 1],
            "dice": 0,
            "illegal": 0,
            "collisions": 0,
        }
        require_exact(row, expected, f"reference transition {decision}")
    if not exact_json_equal(reference["summary"], {
        "completed_episodes": 1,
        "tds_t0": 1,
        "tds_t1": 0,
        "episode_length": 8,
        "dice": 0,
        "illegal": 0,
        "collisions": 0,
        "illegal_fraction": 0,
        "error_episodes": 0,
        "demo_episodes": 0,
        "state_bank_config_episodes": 0,
        "reward_samples": 16,
        "reward_nonzero_samples": 2,
        "reward_clipped_samples": 0,
        "reward_nonfinite_samples": 0,
        "reward_clip_episodes": 0,
        "reward_nonfinite_episodes": 0,
        "reward_component_touchdown": 1,
        "reward_component_residual": 0,
        "reward_component_mismatch_samples": 0,
        "reward_component_nonfinite_samples": 0,
        "reward_terminal_suppressed_signed": 0,
        "reward_terminal_suppressed_abs": 0,
        "reward_postclip_return": 1,
        "autoreset_match_sha256": MATCH_SHA256,
    }):
        fail("reference diagnostic summary differs")
    reproduced = run_checked([str(diagnostics), "reference"]).stdout.encode(
        "ascii"
    )
    if canonical_json(json.loads(reproduced)) != path.read_bytes():
        fail("reference diagnostic did not reproduce byte-identically")


def validate_baselines(
    root: Path, evidence: dict[str, Any], *, diagnostics: Path
) -> None:
    safe_summary = evidence["safe_baseline"]
    exact_keys(
        safe_summary,
        {"path", "sha256", "trajectories", "probability"},
        "safe_baseline",
    )
    safe_path = root / "safe-enumeration.json"
    if (
        safe_summary["path"] != "safe-enumeration.json"
        or safe_summary["sha256"] != sha256_file(safe_path)
        or safe_summary["trajectories"] != 721
    ):
        fail("safe baseline summary differs")
    safe = load_json(safe_path)
    exact_keys(
        safe,
        {
            "schema",
            "safe_zero_dice_trajectories",
            "safe_probability",
            "safe_probability_numerator",
            "safe_probability_denominator",
            "selected_probability",
            "selected_probability_numerator",
            "selected_probability_denominator",
            "nodes",
        },
        "safe enumeration",
    )
    rational_fields = (
        "safe_probability_numerator",
        "safe_probability_denominator",
        "selected_probability_numerator",
        "selected_probability_denominator",
    )
    if any(
        type(safe[field]) is not int or safe[field] <= 0
        for field in rational_fields
    ):
        fail("safe enumeration exact rational fields are not positive integers")
    if (
        safe["schema"] != "bloodbowl-f5-safe-enumeration-v1"
        or safe["safe_zero_dice_trajectories"] != 721
        or Fraction(
            safe["safe_probability_numerator"],
            safe["safe_probability_denominator"],
        )
        != Fraction(4567, 9_227_468_800)
        or Fraction(
            safe["selected_probability_numerator"],
            safe["selected_probability_denominator"],
        )
        != Fraction(1, 1_476_395_008)
        or safe["nodes"] != 37206
        or not math.isclose(
            safe["safe_probability"],
            4.949352957985618e-7,
            rel_tol=0,
            abs_tol=1e-19,
        )
        or not math.isclose(
            safe["selected_probability"],
            6.773255088112571e-10,
            rel_tol=0,
            abs_tol=1e-24,
        )
        or safe_summary["probability"] != safe["safe_probability"]
    ):
        fail("safe enumeration values differ")
    reproduced_safe = run_checked(
        [str(diagnostics), "enumerate"], timeout=900
    ).stdout
    if canonical_json(json.loads(reproduced_safe)) != safe_path.read_bytes():
        fail("safe enumeration did not reproduce byte-identically")

    random_summary = evidence["random_baseline"]
    exact_keys(
        random_summary,
        {"path", "sha256", "episodes", "seed", "successes"},
        "random_baseline",
    )
    random_path = root / "random-baseline.json"
    if (
        random_summary["path"] != "random-baseline.json"
        or random_summary["sha256"] != sha256_file(random_path)
    ):
        fail("random baseline summary identity differs")
    random = load_json(random_path)
    exact_keys(
        random,
        {
            "schema",
            "seed",
            "episodes",
            "decisions",
            "agent_steps",
            "successes",
            "tds_t1",
            "early_terminals",
            "illegal",
            "collisions",
            "dice",
            "test_windows",
            "fixture_resets",
            "reward_totals",
            "episode_lengths",
        },
        "random baseline",
    )
    if (
        not exact_json_equal(random, EXPECTED_RANDOM_BASELINE)
        or not exact_json_equal(
            random_summary,
            {
                "path": "random-baseline.json",
                "sha256": sha256_file(random_path),
                "episodes": RANDOM_EPISODES,
                "seed": RANDOM_SEED,
                "successes": 0,
            },
        )
    ):
        fail("frozen random baseline differs")
    reproduced_random = run_checked(
        [
            str(diagnostics),
            "random",
            "--episodes",
            str(RANDOM_EPISODES),
            "--seed",
            str(RANDOM_SEED),
        ],
        timeout=900,
    ).stdout
    if canonical_json(json.loads(reproduced_random)) != random_path.read_bytes():
        fail("random baseline did not reproduce byte-identically")


def _environment_source_sha256(path: Path) -> str:
    value = run_checked(
        [
            sys.executable,
            "-B",
            "-I",
            "-S",
            str(ROOT / "tools/state_bank_contract.py"),
            "environment-source-sha256",
            "--root",
            str(path),
            "--plain",
        ],
        timeout=60,
    ).stdout.strip()
    return require_sha256(value, f"environment source identity for {path}")


def _expected_direct_requirements(sys_platform: str) -> dict[str, str]:
    torch_version = {
        "darwin": "2.9.1",
        "linux": "2.9.1+cpu",
    }.get(sys_platform)
    if torch_version is None:
        fail(f"unsupported Puffer dependency platform {sys_platform!r}")
    return {
        "numpy": "2.5.1",
        "rich": "15.0.0",
        "rich-argparse": "1.8.0",
        "torch": torch_version,
    }


def _query_puffer_runtime(puffer_root: Path) -> dict[str, Any]:
    """Collect an outer-verifier-owned venv/import receipt."""

    script = r"""
import importlib.metadata
import json
import platform
import re
import sys
import sysconfig
from pathlib import Path

root = Path(sys.argv[1]).resolve(strict=True)
venv = (root / ".venv").resolve(strict=True)
if Path(sys.prefix).resolve(strict=True) != venv:
    raise SystemExit("runtime prefix escaped the Puffer venv")

site_directories = []
for key in ("purelib", "platlib"):
    path = Path(sysconfig.get_paths()[key]).resolve(strict=True)
    path.relative_to(venv)
    if path not in site_directories:
        site_directories.append(path)

def canonical_name(value):
    return re.sub(r"[-_.]+", "-", value).lower()

installed = {}
for distribution in importlib.metadata.distributions(
        path=[str(path) for path in site_directories]):
    raw_name = distribution.metadata.get("Name")
    version = distribution.version
    if not isinstance(raw_name, str) or not raw_name or not version:
        raise SystemExit("installed distribution lacks a name or version")
    name = canonical_name(raw_name)
    if name in installed:
        raise SystemExit("duplicate installed distribution metadata: " + name)
    installed[name] = version

sys.path.insert(0, str(root))
import numpy
import rich
import rich_argparse
import torch
import pufferlib.torch_pufferl as torch_pufferl
from pufferlib import _C

def module_path(module):
    raw = getattr(module, "__file__", None)
    if not isinstance(raw, str):
        raise SystemExit("imported module has no file")
    return str(Path(raw).resolve(strict=True))

direct_names = ("numpy", "rich", "rich-argparse", "torch")
contract_names = (
    "env_name",
    "gpu",
    "observation_abi",
    "observation_version",
    "action_abi",
    "rollout_transition_contract",
    "state_bank_kind",
    "state_bank_kind_name",
    "qualification_fixture_enabled",
    "qualification_fixture_role",
    "qualification_fixture_schema",
    "qualification_fixture_qualification_only",
    "qualification_fixture_match_sha256",
    "qualification_fixture_bbs_sha256",
    "qualification_fixture_bundle_sha256",
    "qualification_fixture_bbs_source_id",
    "qualification_fixture_authored_source_id",
    "qualification_fixture_reference_trace_schema",
    "qualification_fixture_reference_trace_sha256",
    "qualification_fixture_max_decisions",
    "qualification_fixture_reward_contract",
    "qualification_fixture_environment_source_sha256",
)
result = {
    "python_executable": str(Path(sys.executable).absolute()),
    "python_prefix": str(venv),
    "python_implementation": platform.python_implementation(),
    "python_version": platform.python_version(),
    "python_cache_tag": sys.implementation.cache_tag,
    "sys_platform": sys.platform,
    "machine": platform.machine().lower(),
    "direct_requirements": {
        name: installed[name] for name in direct_names
    },
    "distributions": [
        {"name": name, "version": installed[name]}
        for name in sorted(installed)
    ],
    "torch_version": str(torch.__version__),
    "torch_cuda_version": torch.version.cuda,
    "torch_cuda_available": torch.cuda.is_available(),
    "torch_file": module_path(torch),
    "torch_collector_path": module_path(torch_pufferl),
    "compiled_module_path": module_path(_C),
    "compiled_module_contract": {
        name: getattr(_C, name) for name in contract_names
    },
    "collector_uses_compiled_module": getattr(torch_pufferl, "_C", None) is _C,
    "import_paths": {
        "numpy": module_path(numpy),
        "rich": module_path(rich),
        "rich-argparse": module_path(rich_argparse),
        "torch": module_path(torch),
        "torch-collector": module_path(torch_pufferl),
    },
}
print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
"""
    completed = run_checked(
        [
            str(puffer_root / ".venv/bin/python"),
            "-B",
            "-I",
            "-c",
            script,
            str(puffer_root),
        ],
        cwd=puffer_root,
        timeout=300,
        environment=isolated_python_environment(),
    )
    return load_json_bytes(
        completed.stdout.encode("ascii"), "independent Puffer runtime receipt"
    )


def _validate_distribution_snapshot(
    puffer_root: Path,
    runtime: dict[str, Any],
    live: dict[str, Any],
) -> dict[str, Any]:
    venv = (puffer_root / ".venv").resolve(strict=True)
    requirements_payload = read_regular_bytes(
        ROOT / "training/f5_trainability_requirements.txt",
        maximum=1 << 20,
        location="sealed F5 dependency requirements",
    )
    if (
        hashlib.sha256(requirements_payload).hexdigest()
        != DEPENDENCY_REQUIREMENTS_SHA256
    ):
        fail("sealed F5 dependency requirements identity differs")
    snapshot_path = venv / "f5_trainability_distributions.json"
    digest_path = venv / "f5_trainability_distributions.sha256"
    snapshot_payload = read_regular_bytes(
        snapshot_path,
        maximum=1 << 20,
        location="Puffer dependency name/version snapshot",
    )
    digest_payload = read_regular_bytes(
        digest_path,
        maximum=65,
        location="Puffer dependency snapshot digest",
    )
    snapshot_sha256 = hashlib.sha256(snapshot_payload).hexdigest()
    if digest_payload != (snapshot_sha256 + "\n").encode("ascii"):
        fail("Puffer dependency snapshot digest content differs")
    snapshot = load_json_bytes(
        snapshot_payload, "Puffer dependency name/version snapshot"
    )
    if snapshot_payload != canonical_json(snapshot):
        fail("Puffer dependency snapshot is not canonical JSON")
    exact_keys(
        snapshot,
        {
            "schema",
            "requirements_sha256",
            "direct_requirements",
            "python",
            "platform",
            "distributions",
        },
        "Puffer dependency snapshot",
    )
    exact_keys(
        live,
        {
            "python_executable",
            "python_prefix",
            "python_implementation",
            "python_version",
            "python_cache_tag",
            "sys_platform",
            "machine",
            "direct_requirements",
            "distributions",
            "torch_version",
            "torch_cuda_version",
            "torch_cuda_available",
            "torch_file",
            "torch_collector_path",
            "compiled_module_path",
            "compiled_module_contract",
            "collector_uses_compiled_module",
            "import_paths",
        },
        "independent Puffer runtime receipt",
    )
    supported_platforms = {
        ("darwin", "arm64"),
        ("linux", "x86_64"),
    }
    if (
        type(live["sys_platform"]) is not str
        or type(live["machine"]) is not str
        or (live["sys_platform"], live["machine"]) not in supported_platforms
        or live["sys_platform"] != sys.platform
        or live["machine"] != platform.machine().lower()
    ):
        fail("Puffer venv platform differs from the supported verifier host")
    direct = _expected_direct_requirements(live["sys_platform"])
    expected_python = {
        "implementation": "cpython",
        "version": live["python_version"],
    }
    expected_platform = {
        "sys_platform": live["sys_platform"],
        "machine": live["machine"],
    }
    if (
        live["python_implementation"] != "CPython"
        or live["python_cache_tag"] != "cpython-312"
        or type(live["python_version"]) is not str
        or re.fullmatch(r"3\.12\.\d+", live["python_version"]) is None
        or not exact_json_equal(live["direct_requirements"], direct)
        or live["torch_version"] != direct["torch"]
        or live["torch_cuda_version"] is not None
        or live["torch_cuda_available"] is not False
    ):
        fail("Puffer venv Python/Torch runtime identity differs")
    expected_snapshot_fields = {
        "schema": "bloodbowl-f5-python-distributions-v1",
        "requirements_sha256": DEPENDENCY_REQUIREMENTS_SHA256,
        "direct_requirements": direct,
        "python": expected_python,
        "platform": expected_platform,
        "distributions": live["distributions"],
    }
    require_exact(
        snapshot,
        expected_snapshot_fields,
        "live installed-distribution name/version snapshot",
    )
    distributions = snapshot["distributions"]
    if type(distributions) is not list or not distributions:
        fail("Puffer dependency snapshot has no distributions")
    names: list[str] = []
    for index, distribution in enumerate(distributions):
        exact_keys(
            distribution,
            {"name", "version"},
            f"Puffer distribution {index}",
        )
        name = distribution["name"]
        version = distribution["version"]
        if (
            type(name) is not str
            or type(version) is not str
            or not name
            or not version
            or re.sub(r"[-_.]+", "-", name).lower() != name
        ):
            fail(f"Puffer distribution {index} identity is noncanonical")
        names.append(name)
    if names != sorted(names) or len(names) != len(set(names)):
        fail("Puffer distribution snapshot is not sorted and unique")

    import_paths = live["import_paths"]
    exact_keys(
        import_paths,
        {"numpy", "rich", "rich-argparse", "torch", "torch-collector"},
        "Puffer imported dependency paths",
    )
    for name in ("numpy", "rich", "rich-argparse", "torch"):
        raw = import_paths[name]
        if type(raw) is not str:
            fail(f"Puffer imported {name} path is not text")
        imported = Path(raw).resolve(strict=True)
        try:
            imported.relative_to(venv)
        except ValueError:
            fail(f"Puffer imported {name} escaped its venv")
    collector_path = (
        puffer_root / "pufferlib/torch_pufferl.py"
    ).resolve(strict=True)
    read_regular_bytes(
        collector_path,
        maximum=16 << 20,
        location="pinned Puffer Torch collector",
    )
    if Path(import_paths["torch-collector"]).resolve(strict=True) != collector_path:
        fail("Puffer Torch collector import escaped the pinned checkout")
    torch_path = Path(live["torch_file"]).resolve(strict=True)
    read_regular_bytes(
        torch_path,
        maximum=16 << 20,
        location="imported Puffer Torch package entrypoint",
    )
    if Path(import_paths["torch"]).resolve(strict=True) != torch_path:
        fail("Puffer Torch import path receipt is inconsistent")

    exact_keys(
        runtime,
        {
            "python_executable",
            "python_prefix",
            "python_implementation",
            "python_version",
            "python_cache_tag",
            "torch_version",
            "torch_file",
            "torch_file_sha256",
            "torch_cuda_version",
            "torch_cuda_available",
            "torch_collector_path",
            "torch_collector_sha256",
            "distributions_snapshot_sha256",
            "distributions_snapshot_bytes",
            "distributions_digest_file_sha256",
            "requirements_sha256",
            "direct_requirements",
        },
        "Puffer module runtime",
    )
    runtime_expected = {
        "python_executable": live["python_executable"],
        "python_prefix": live["python_prefix"],
        "python_implementation": live["python_implementation"],
        "python_version": live["python_version"],
        "python_cache_tag": live["python_cache_tag"],
        "torch_version": live["torch_version"],
        "torch_file": live["torch_file"],
        "torch_file_sha256": sha256_file(torch_path),
        "torch_cuda_version": None,
        "torch_cuda_available": False,
        "torch_collector_path": live["torch_collector_path"],
        "torch_collector_sha256": sha256_file(collector_path),
        "distributions_snapshot_sha256": snapshot_sha256,
        "distributions_snapshot_bytes": len(snapshot_payload),
        "distributions_digest_file_sha256": hashlib.sha256(
            digest_payload
        ).hexdigest(),
        "requirements_sha256": DEPENDENCY_REQUIREMENTS_SHA256,
        "direct_requirements": direct,
    }
    require_exact(runtime, runtime_expected, "Puffer module runtime receipt")
    return {
        "scope": DEPENDENCY_IDENTITY_SCOPE,
        "requirements_sha256": DEPENDENCY_REQUIREMENTS_SHA256,
        "snapshot_sha256": snapshot_sha256,
        "snapshot_bytes": len(snapshot_payload),
        "digest_file_sha256": hashlib.sha256(digest_payload).hexdigest(),
        "direct_requirements": direct,
        "torch_version": direct["torch"],
        "torch_collector_sha256": sha256_file(collector_path),
    }


def _expected_reference_transition(offset: int) -> dict[str, Any]:
    decision = offset + 1
    return {
        "decision": decision,
        "heads": list(REFERENCE_HEADS[offset]),
        "decision_team": 0,
        "support_counts": list(REFERENCE_SUPPORT_COUNTS[offset]),
        "waiting_singleton": True,
        "match_before_sha256": REFERENCE_MATCH_BEFORE_SHA256[offset],
        "obs_sha256": list(REFERENCE_OBS_SHA256[offset]),
        "mask_sha256": list(REFERENCE_MASK_SHA256[offset]),
        "rewards": [0, 0] if decision < 8 else [1, -1],
        "terminals": [0, 0] if decision < 8 else [1, 1],
        "dice": 0,
        "illegal": 0,
        "collisions": 0,
    }


def _expected_module_transition(offset: int) -> dict[str, Any]:
    decision = offset + 1
    return {
        "decision": decision,
        "heads": list(REFERENCE_HEADS[offset]),
        "active_row": 0,
        "waiting_row": 1,
        "joint_counts": [REFERENCE_ACTIVE_COUNTS[offset], 1],
        "joint_support_sha256": REFERENCE_JOINT_SUPPORT_SHA256[offset],
        "obs_sha256": list(REFERENCE_OBS_SHA256[offset]),
        "mask_sha256": list(REFERENCE_MASK_SHA256[offset]),
        "rewards": [0.0, 0.0] if decision < 8 else [1.0, -1.0],
        "terminals": [0.0, 0.0] if decision < 8 else [1.0, 1.0],
    }


def validate_module_transitions(
    transitions: Any, reference_transitions: Any
) -> None:
    if (
        type(transitions) is not list
        or len(transitions) != 8
        or type(reference_transitions) is not list
        or len(reference_transitions) != 8
    ):
        fail("Puffer/reference transition count differs")
    module_keys = {
        "decision",
        "heads",
        "active_row",
        "waiting_row",
        "joint_counts",
        "joint_support_sha256",
        "obs_sha256",
        "mask_sha256",
        "rewards",
        "terminals",
    }
    for offset, (transition, reference) in enumerate(
        zip(transitions, reference_transitions)
    ):
        decision = offset + 1
        exact_keys(
            transition, module_keys, f"Puffer module transition {decision}"
        )
        require_exact(
            transition,
            _expected_module_transition(offset),
            f"Puffer module transition {decision}",
        )
        require_exact(
            reference,
            _expected_reference_transition(offset),
            f"cross-bound reference transition {decision}",
        )
        for field in ("decision", "heads", "obs_sha256", "mask_sha256"):
            require_exact(
                transition[field],
                reference[field],
                f"Puffer/reference transition {decision} {field}",
            )
        require_exact(
            transition["rewards"],
            [float(value) for value in reference["rewards"]],
            f"Puffer/reference transition {decision} rewards",
        )
        require_exact(
            transition["terminals"],
            [float(value) for value in reference["terminals"]],
            f"Puffer/reference transition {decision} terminals",
        )


def validate_module_log(value: Any, location: str) -> None:
    exact_keys(value, set(EXPECTED_MODULE_LOG), location)
    require_exact(value, EXPECTED_MODULE_LOG, location)


def validate_rollout_tail(value: Any) -> None:
    exact_keys(
        value,
        {
            "slot",
            "reward",
            "terminal",
            "terminal_bootstrap",
            "ninth_environment_action",
            "environment_step_calls",
            "policy_forward_calls",
            "policy_tail_value_emission",
            "recurrent_state_inputs",
            "recurrent_state_after_actions",
            "recurrent_initial_state_was_cleared",
            "recurrent_tail_state_was_cleared",
            "collector",
            "advantage",
            "log",
        },
        "Puffer Torch rollout tail",
    )
    expected_header = {
        "slot": 8,
        "reward": [1.0, -1.0],
        "terminal": [1.0, 1.0],
        "terminal_bootstrap": [0.0, 0.0],
        "ninth_environment_action": False,
        "environment_step_calls": 8,
        "policy_forward_calls": 9,
        "policy_tail_value_emission": ["nan", "+inf"],
        "recurrent_state_inputs": [
            0.0,
            1.0,
            2.0,
            3.0,
            4.0,
            5.0,
            6.0,
            7.0,
            0.0,
        ],
        "recurrent_state_after_actions": [8.0],
        "recurrent_initial_state_was_cleared": True,
        "recurrent_tail_state_was_cleared": True,
    }
    for key, expected in expected_header.items():
        require_exact(value[key], expected, f"Puffer Torch rollout tail {key}")

    collector = value["collector"]
    exact_keys(
        collector,
        {
            "rewards",
            "terminals",
            "actions",
            "obs_sha256",
            "effective_mask_sha256",
            "pending_rewards",
            "pending_terminals",
            "global_step",
            "tail_valid",
        },
        "Puffer Torch collector",
    )
    expected_collector = {
        "rewards": [[0.0, 0.0] for _ in range(8)],
        "terminals": [[0.0, 0.0] for _ in range(8)],
        "actions": [
            [list(heads), [0, 32, 390]] for heads in REFERENCE_HEADS
        ],
        "obs_sha256": [list(rows) for rows in REFERENCE_OBS_SHA256],
        "effective_mask_sha256": [
            list(rows) for rows in ROLLOUT_EFFECTIVE_MASK_SHA256
        ],
        "pending_rewards": [1.0, -1.0],
        "pending_terminals": [1.0, 1.0],
        "global_step": 16,
        "tail_valid": True,
    }
    require_exact(
        collector, expected_collector, "Puffer Torch collector receipt"
    )

    advantage = value["advantage"]
    exact_keys(
        advantage,
        {
            "consumer",
            "calls",
            "gamma",
            "gae_lambda",
            "values",
            "final_slot",
        },
        "Puffer Torch advantage",
    )
    for key, expected in {
        "consumer": "puff_advantage_cpu",
        "calls": 1,
        "gamma": 0.99,
        "gae_lambda": 0.95,
        "final_slot": [1.0, -1.0],
    }.items():
        require_exact(advantage[key], expected, f"Puffer advantage {key}")
    values = advantage["values"]
    if (
        type(values) is not list
        or len(values) != 2
        or any(type(row) is not list or len(row) != 8 for row in values)
    ):
        fail("Puffer advantage value matrix shape differs")
    decay = 0.99 * 0.95
    for row, sign in enumerate((1.0, -1.0)):
        for step in range(8):
            observed = values[row][step]
            expected = sign * decay ** (7 - step)
            if (
                type(observed) is not float
                or not math.isfinite(observed)
                or observed == 0.0
                or not math.isclose(
                    observed, expected, rel_tol=2e-6, abs_tol=2e-6
                )
            ):
                fail(f"Puffer advantage value [{row}][{step}] differs")
    validate_module_log(value["log"], "Puffer Torch rollout log")


def validate_masked_random(value: Any) -> None:
    exact_keys(value, set(EXPECTED_MASKED_RANDOM), "Puffer masked random")
    require_exact(value, EXPECTED_MASKED_RANDOM, "Puffer masked random receipt")
    if value["joint_support_rows_checked"] != 2 * (
        1 + value["decisions"] + value["exact_autoresets"]
    ):
        fail("Puffer masked-random support-row coverage count is inconsistent")
    for key in ("illegal_frac", "error_episodes", "reward_nonfinite_frac"):
        require_exact(
            value[key],
            value["integrity"][key],
            f"Puffer masked-random integrity cross-binding {key}",
        )
    require_exact(
        value["episode_length_mean"],
        value["integrity"]["episode_length"],
        "Puffer masked-random episode-length cross-binding",
    )
    for key in ("tds_t0", "tds_t1"):
        require_exact(
            float(value[key]),
            value["integrity"][key],
            f"Puffer masked-random touchdown cross-binding {key}",
        )


def validate_vectorization(value: Any) -> None:
    expected = {
        "total_agents": 4,
        "environments": 2,
        "episode_decisions": 8,
        "completed_episodes": 2,
        "terminal_rewards": [1.0, -1.0, 1.0, -1.0],
        "all_terminal": True,
        "exact_autoreset": True,
    }
    exact_keys(value, set(expected), "Puffer two-environment oracle")
    require_exact(value, expected, "Puffer two-environment oracle")


def _read_lifecycle_stream(
    root: Path,
    description: Any,
    *,
    expected_path: str,
    location: str,
) -> bytes:
    exact_keys(description, {"path", "bytes", "sha256"}, location)
    if description["path"] != expected_path:
        fail(f"{location} path differs")
    path = root / expected_path
    try:
        info = path.lstat()
    except OSError as exc:
        fail(f"cannot stat {location}: {exc}")
    if (
        path.is_symlink()
        or not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_size < 0
        or info.st_size > 16 << 20
    ):
        fail(f"{location} is not a bounded singly linked regular file")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        fail(f"cannot read {location}: {exc}")
    if (
        type(description["bytes"]) is not int
        or description["bytes"] != len(payload)
        or description["sha256"] != hashlib.sha256(payload).hexdigest()
    ):
        fail(f"{location} byte/hash identity differs")
    return payload


def _validate_ordinary_module_receipt(
    value: dict[str, Any], *, environment_source_sha256: str
) -> None:
    exact_keys(
        value,
        {
            "schema",
            "module_path",
            "module_sha256",
            "module_contract",
            "qualification_fixture",
            "state_bank",
        },
        "ordinary module receipt",
    )
    if (
        value["schema"] != "bloodbowl-f5-ordinary-module-v1"
        or type(value["module_path"]) is not str
        or not value["module_path"].startswith("pufferlib/_C.cpython-312-")
        or not value["module_path"].endswith(".so")
    ):
        fail("ordinary module receipt identity differs")
    require_sha256(value["module_sha256"], "ordinary module SHA-256")
    contract_expected = {
        "env_name": "bloodbowl",
        "gpu": 0,
        "observation_abi": "obs-v6",
        "observation_version": 6,
        "action_abi": "exact-joint-v1",
        "rollout_transition_contract": "tail-bootstrap-v1",
        "entropy_schedule_contract":
            "cosine-update-index-over-total-updates-fp32-v1",
        "environment_config_schema": "bloodbowl-environment-config-v1",
        "strict_env_config_testing": False,
        "environment_source_sha256": environment_source_sha256,
    }
    contract = value["module_contract"]
    exact_keys(
        contract,
        set(contract_expected) | {"exact_action_source_sha256"},
        "ordinary module contract",
    )
    for key, expected in contract_expected.items():
        require_exact(
            contract[key], expected, f"ordinary module contract {key}"
        )
    require_sha256(
        contract["exact_action_source_sha256"],
        "ordinary exact-action source SHA-256",
    )
    require_exact(
        value["qualification_fixture"],
        EXPECTED_ORDINARY_QUALIFICATION_FIXTURE,
        "ordinary qualification fixture",
    )
    require_exact(
        value["state_bank"],
        EXPECTED_NO_BANK_STATE,
        "ordinary no-bank contract",
    )


def _expected_puffer_build_toolchain() -> dict[str, Any]:
    if (
        (sys.platform, platform.machine().lower())
        not in {("darwin", "arm64"), ("linux", "x86_64")}
    ):
        fail("unsupported Puffer lifecycle build platform")
    result: dict[str, Any] = {
        "schema": "bloodbowl-f5-puffer-build-toolchain-v1",
        "platform": sys.platform,
        "machine": platform.machine().lower(),
    }
    for key, command in (("cc", "clang"), ("cxx", "clang++")):
        raw = shutil.which(command, path=SAFE_SYSTEM_PATH)
        if raw is None:
            fail(f"sealed Puffer build compiler is absent: {command}")
        executable = Path(raw).resolve(strict=True)
        version = run_checked(
            [str(executable), "--version"], timeout=30
        ).stdout.splitlines()
        target = run_checked(
            [str(executable), "-dumpmachine"], timeout=30
        ).stdout.strip()
        if not version or not target or "\n" in target:
            fail(f"sealed Puffer compiler identity is incomplete: {executable}")
        result[key] = {
            "path": str(executable),
            "sha256": sha256_file(executable),
            "version": version[0],
            "target": target,
        }
    return result


def _expected_puffer_raylib_input(puffer_root: Path) -> dict[str, Any]:
    expected = RAYLIB_INPUTS.get(
        (sys.platform, platform.machine().lower())
    )
    if expected is None:
        fail("unsupported Raylib build-input platform")
    archive_directory = puffer_root / "raylib-archives"
    extracted_directory = puffer_root / expected["directory"]
    for directory, location in (
        (archive_directory, "pinned Raylib archive cache"),
        (extracted_directory, "pinned Raylib extracted input"),
    ):
        try:
            metadata = directory.lstat()
        except OSError as exc:
            fail(f"cannot inspect {location}: {exc}")
        if directory.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
            fail(f"{location} is not a real directory")

    archive_relative = (
        f"raylib-archives/{expected['directory']}.tar.gz"
    )
    library_relative = f"{expected['directory']}/lib/libraylib.a"
    archive_payload = read_regular_bytes(
        puffer_root / archive_relative,
        maximum=64 << 20,
        location="pinned Raylib release archive",
    )
    library_payload = read_regular_bytes(
        puffer_root / library_relative,
        maximum=32 << 20,
        location="pinned Raylib static library",
    )
    archive_digest = sha256_bytes(archive_payload)
    library_digest = sha256_bytes(library_payload)
    if archive_digest != expected["archive_sha256"]:
        fail("retained Raylib archive differs from the platform pin")
    if library_digest != expected["library_sha256"]:
        fail("linked Raylib library differs from the platform pin")
    return {
        "schema": "bloodbowl-f5-raylib-input-v2",
        "release": "5.5",
        "directory": expected["directory"],
        "archive_path": archive_relative,
        "archive_bytes": len(archive_payload),
        "archive_sha256": archive_digest,
        "library_path": library_relative,
        "library_bytes": len(library_payload),
        "library_sha256": library_digest,
    }


def _expected_puffer_pyvenv_input(
    puffer_root: Path,
) -> dict[str, Any]:
    config_path = puffer_root / ".venv/pyvenv.cfg"
    payload = read_regular_bytes(
        config_path,
        maximum=4096,
        location="sealed Puffer pyvenv.cfg",
    )
    try:
        text_value = payload.decode("utf-8")
    except UnicodeError as exc:
        fail(f"sealed Puffer pyvenv.cfg is not UTF-8: {exc}")
    values: dict[str, str] = {}
    for line in text_value.splitlines():
        if " = " not in line:
            fail("sealed Puffer pyvenv.cfg has a noncanonical line")
        key, value = line.split(" = ", 1)
        if not key or key in values or not value:
            fail("sealed Puffer pyvenv.cfg has duplicate/empty fields")
        values[key] = value
    expected_keys = {
        "home",
        "include-system-site-packages",
        "version",
        "executable",
        "command",
    }
    if (
        set(values) != expected_keys
        or values["include-system-site-packages"] != "false"
        or re.fullmatch(r"3\.12\.[0-9]+", values["version"]) is None
    ):
        fail("sealed Puffer pyvenv.cfg contract differs")
    try:
        configured_executable = Path(
            values["executable"]
        ).resolve(strict=True)
        configured_home_python = (
            Path(values["home"]) / "python3.12"
        ).resolve(strict=True)
        actual_executable = (
            puffer_root / ".venv/bin/python"
        ).resolve(strict=True)
    except OSError as exc:
        fail(f"sealed Puffer base interpreter cannot resolve: {exc}")
    if (
        configured_executable != actual_executable
        or configured_home_python != actual_executable
    ):
        fail("sealed Puffer base interpreter identity differs")
    try:
        runtime_payload = run_checked(
            [
                str(puffer_root / ".venv/bin/python"),
                "-B",
                "-I",
                "-S",
                "-c",
                PUFFER_INTERPRETER_PROBE,
            ],
            cwd=puffer_root,
            timeout=30,
        ).stdout.encode("ascii")
        runtime = json.loads(runtime_payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        fail(f"sealed Puffer interpreter probe is malformed: {exc}")
    expected_runtime = {
        "implementation": "cpython",
        "platlibdir": "lib",
        "version": values["version"],
    }
    if (
        runtime_payload != canonical_json(runtime)
        or runtime != expected_runtime
    ):
        fail(
            "sealed Puffer interpreter must be exact CPython 3.12 with "
            f"platlibdir=lib: {runtime!r}"
        )
    return {
        "path": ".venv/pyvenv.cfg",
        "bytes": len(payload),
        "sha256": sha256_bytes(payload),
        "include_system_site_packages": False,
        "version": values["version"],
        "implementation": runtime["implementation"],
        "platlibdir": runtime["platlibdir"],
        "base_python": str(actual_executable),
        "base_python_sha256": sha256_file(actual_executable),
    }


def _expected_puffer_startup_runtime_input(
    puffer_root: Path,
    pyvenv: dict[str, Any],
    site_packages: Path,
) -> dict[str, Any]:
    try:
        runtime_payload = run_checked(
            [
                str(puffer_root / ".venv/bin/python"),
                "-B",
                "-I",
                "-c",
                PUFFER_STARTUP_RUNTIME_PROBE,
            ],
            cwd=puffer_root,
            timeout=30,
        ).stdout.encode("ascii")
        runtime = json.loads(runtime_payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        fail(f"sealed Puffer startup runtime probe is malformed: {exc}")
    expected_keys = {
        "base_prefix",
        "dont_write_bytecode",
        "implementation",
        "isolated",
        "no_site",
        "platlibdir",
        "prefix",
        "sitecustomize_is_sys",
        "sys_path",
        "user_site_enabled",
        "version",
    }
    if (
        runtime_payload != canonical_json(runtime)
        or not isinstance(runtime, dict)
        or set(runtime) != expected_keys
    ):
        fail("sealed Puffer startup runtime receipt is noncanonical")
    expected_scalars = {
        "dont_write_bytecode": True,
        "implementation": pyvenv["implementation"],
        "isolated": 1,
        "no_site": 0,
        "platlibdir": pyvenv["platlibdir"],
        "sitecustomize_is_sys": True,
        "user_site_enabled": False,
        "version": pyvenv["version"],
    }
    for key, expected in expected_scalars.items():
        if type(runtime[key]) is not type(expected) or runtime[key] != expected:
            fail(
                "sealed Puffer startup runtime scalar differs: "
                f"{key}={runtime[key]!r}"
            )
    if (
        not isinstance(runtime["base_prefix"], str)
        or not isinstance(runtime["prefix"], str)
    ):
        fail("sealed Puffer startup prefixes are not strings")
    try:
        base_prefix = Path(runtime["base_prefix"]).resolve(strict=True)
        prefix = Path(runtime["prefix"]).resolve(strict=True)
        expected_prefix = (puffer_root / ".venv").resolve(strict=True)
    except OSError as exc:
        fail(f"sealed Puffer startup prefixes cannot resolve: {exc}")
    if prefix != expected_prefix:
        fail("sealed Puffer startup prefix differs from the prepared venv")
    sys_path = runtime["sys_path"]
    if (
        not isinstance(sys_path, list)
        or not sys_path
        or any(not isinstance(item, str) or not item for item in sys_path)
    ):
        fail(
            "sealed Puffer startup sys.path is not a nonempty string list"
        )
    exact_root = str(puffer_root)
    exact_site_packages = str(site_packages)
    if (
        sys_path.count(exact_root) != 1
        or sys_path.count(exact_site_packages) != 1
    ):
        fail(
            "sealed Puffer startup sys.path does not contain the exact "
            "Puffer root and venv site-packages once"
        )
    for item in sys_path:
        if item in {exact_root, exact_site_packages}:
            continue
        candidate = Path(item)
        if not candidate.is_absolute():
            fail(
                f"sealed Puffer startup has a relative sys.path entry: {item!r}"
            )
        try:
            candidate.resolve(strict=False).relative_to(base_prefix)
        except ValueError:
            fail(
                "sealed Puffer startup imported a path outside the trusted "
                f"base stdlib, venv, and pinned root: {item!r}"
            )
    return {
        "schema": "bloodbowl-f5-python-startup-runtime-v1",
        "base_prefix": str(base_prefix),
        "prefix": str(prefix),
        "implementation": runtime["implementation"],
        "version": runtime["version"],
        "platlibdir": runtime["platlibdir"],
        "isolated": runtime["isolated"],
        "no_site": runtime["no_site"],
        "dont_write_bytecode": runtime["dont_write_bytecode"],
        "user_site_enabled": runtime["user_site_enabled"],
        "sitecustomize_is_sys": runtime["sitecustomize_is_sys"],
        "sys_path": sys_path,
    }


def _expected_puffer_python_startup_input(
    puffer_root: Path,
) -> dict[str, Any]:
    if "\n" in str(puffer_root) or "\r" in str(puffer_root):
        fail("Puffer root cannot be represented as one path-hook line")
    venv = puffer_root / ".venv"
    for relative in (
        ".",
        "bin",
        "lib",
        "lib/python3.12",
        "lib/python3.12/site-packages",
    ):
        directory = venv if relative == "." else venv / relative
        try:
            metadata = directory.lstat()
            resolved = directory.resolve(strict=True)
            resolved.relative_to(venv.resolve(strict=True))
        except (OSError, ValueError) as exc:
            fail(f"sealed Puffer venv directory {relative} escaped: {exc}")
        if directory.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
            fail(
                f"sealed Puffer venv directory {relative} is not real"
            )
    site_packages = venv / "lib/python3.12/site-packages"
    try:
        entries = {entry.name for entry in os.scandir(site_packages)}
    except OSError as exc:
        fail(f"cannot inspect sealed Puffer site-packages: {exc}")
    pth_names = {name for name in entries if name.endswith(".pth")}
    forbidden = {
        name
        for name in entries
        if (
            name.endswith(".egg-link")
            or name.startswith("sitecustomize")
            or name.startswith("usercustomize")
            or name.startswith(
                "__editable___pufferlib_4_0_0_finder"
            )
        )
    }
    cache = site_packages / "__pycache__"
    cached_finders: set[str] = set()
    if os.path.lexists(cache):
        try:
            cache_metadata = cache.lstat()
            cached_finders = {
                entry.name
                for entry in os.scandir(cache)
                if entry.name.startswith(
                    "__editable___pufferlib_4_0_0_finder"
                )
            }
        except OSError as exc:
            fail(f"cannot inspect Puffer startup bytecode cache: {exc}")
        if cache.is_symlink() or not stat.S_ISDIR(cache_metadata.st_mode):
            fail("Puffer startup bytecode cache is not a real directory")
    if (
        pth_names != {SEALED_EDITABLE_PTH_NAME}
        or forbidden
        or cached_finders
    ):
        fail(
            "Puffer executable/path startup hooks are not exactly sealed: "
            f"pth={sorted(pth_names)!r}, "
            f"forbidden={sorted(forbidden)!r}, "
            f"cached_finders={sorted(cached_finders)!r}"
        )
    relative = (
        ".venv/lib/python3.12/site-packages/"
        + SEALED_EDITABLE_PTH_NAME
    )
    payload = read_regular_bytes(
        puffer_root / relative,
        maximum=4096,
        location="sealed Puffer editable path hook",
    )
    expected_payload = (
        SEALED_SITE_BOOTSTRAP_LINE + str(puffer_root) + "\n"
    ).encode("utf-8")
    if payload != expected_payload:
        fail("sealed Puffer editable path hook escaped the pinned root")
    pyvenv = _expected_puffer_pyvenv_input(puffer_root)
    return {
        "schema": "bloodbowl-f5-python-startup-input-v1",
        "pyvenv": pyvenv,
        "site_packages":
            ".venv/lib/python3.12/site-packages",
        "pth_path": relative,
        "pth_bytes": len(payload),
        "pth_sha256": sha256_bytes(payload),
        "executable_pth_files": [relative],
        "base_sitecustomize_blocked": True,
        "sitecustomize_entries": [],
        "editable_finder_entries": [],
        "runtime": _expected_puffer_startup_runtime_input(
            puffer_root, pyvenv, site_packages
        ),
    }


def _puffer_replay_environment(
    puffer_root: Path, toolchain: dict[str, Any]
) -> dict[str, str]:
    environment = foundation_build_environment()
    for name in (
        "EXTRA_CFLAGS",
        "PRECISION",
        "PUFFER_STRICT_ENV_CONFIG_TESTING",
        "CUDA_HOME",
        "CUDA_PATH",
        "NVCC_ARCH",
    ):
        environment.pop(name, None)
    environment["PATH"] = SAFE_SYSTEM_PATH
    environment["PUFFER_INSTALL_PYTHON"] = str(
        Path(sys.executable).resolve(strict=True)
    )
    environment["PUFFER_BUILD_PYTHON"] = str(
        puffer_root / ".venv/bin/python"
    )
    environment["CC"] = toolchain["cc"]["path"]
    environment["CXX"] = toolchain["cxx"]["path"]
    return environment


def _require_independent_ordinary_binding(
    worker_module: dict[str, Any],
    worker_authority_sha256: str,
    worker_git_status: list[str],
    independent: dict[str, Any],
) -> None:
    exact_keys(
        independent,
        {
            "schema",
            "commit",
            "git_tree",
            "initial_git_status_sha256",
            "final_git_status",
            "final_git_status_sha256",
            "environment_source_sha256",
            "authority_sha256",
            "module_receipt",
            "native_build_inputs",
            "python_startup_input",
        },
        "independent ordinary replay",
    )
    if independent["schema"] != "bloodbowl-f5-independent-ordinary-replay-v1":
        fail("independent ordinary replay schema differs")
    if (
        independent["initial_git_status_sha256"]
        != sha256_bytes(canonical_json([]))
        or type(independent["final_git_status"]) is not list
        or any(
            type(line) is not str
            for line in independent["final_git_status"]
        )
        or independent["final_git_status_sha256"]
        != sha256_bytes(
            canonical_json(independent["final_git_status"])
        )
    ):
        fail("independent ordinary replay Git status receipt differs")
    require_exact(
        worker_module,
        independent["module_receipt"],
        "worker/independent ordinary module binding",
    )
    require_exact(
        worker_authority_sha256,
        independent["authority_sha256"],
        "worker/independent ordinary authority binding",
    )
    require_exact(
        worker_git_status,
        independent["final_git_status"],
        "worker/independent ordinary Git status binding",
    )


def _independently_replay_ordinary(
    live_puffer_root: Path,
    *,
    environment_source_sha256: str,
    toolchain: dict[str, Any],
) -> dict[str, Any]:
    python_startup_input = _expected_puffer_python_startup_input(
        live_puffer_root
    )
    expected_tree = git_output(
        live_puffer_root, "rev-parse", f"{PUFFER_COMMIT}^{{tree}}"
    )
    expected_raylib = RAYLIB_INPUTS.get(
        (sys.platform, platform.machine().lower())
    )
    if expected_raylib is None:
        fail("unsupported independent ordinary replay platform")
    live_archive_relative = (
        f"raylib-archives/{expected_raylib['directory']}.tar.gz"
    )
    live_archive = read_regular_bytes(
        live_puffer_root / live_archive_relative,
        maximum=64 << 20,
        location="live Raylib archive for independent ordinary replay",
    )
    if sha256_bytes(live_archive) != expected_raylib["archive_sha256"]:
        fail("independent ordinary replay source archive differs")

    with tempfile.TemporaryDirectory(
        prefix="f5-independent-ordinary-"
    ) as directory:
        temporary = Path(directory).resolve(strict=True)
        replay = temporary / "PufferLib"
        run_checked(
            [
                "git",
                "clone",
                "--quiet",
                "--no-hardlinks",
                "--no-checkout",
                str(live_puffer_root),
                str(replay),
            ],
            cwd=temporary,
            timeout=300,
        )
        run_checked(
            [
                "git",
                "-C",
                str(replay),
                "checkout",
                "--quiet",
                "--detach",
                PUFFER_COMMIT,
            ],
            cwd=temporary,
            timeout=300,
        )
        initial_status = git_output(
            replay,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ).splitlines()
        initial_owned = [
            relative
            for relative in (
                "bloodbowl",
                "config/bloodbowl.ini",
                "ocean/bloodbowl",
                "src/exact_action_build_hash.h",
            )
            if os.path.lexists(replay / relative)
        ]
        initial_modules = sorted(
            path.name
            for path in (replay / "pufferlib").glob("_C*")
            if os.path.lexists(path)
        )
        try:
            initial_native_inputs = sorted(
                entry.name
                for entry in os.scandir(replay)
                if entry.name.startswith("raylib")
            )
        except OSError as exc:
            fail(
                "cannot inspect independent replay native inputs: "
                f"{exc}"
            )
        if (
            git_output(replay, "rev-parse", "HEAD") != PUFFER_COMMIT
            or git_output(replay, "rev-parse", "HEAD^{tree}") != expected_tree
            or initial_status
            or initial_owned
            or initial_modules
            or initial_native_inputs
        ):
            fail(
                "independent ordinary replay did not begin from the "
                "pristine pinned tree"
            )

        live_venv = live_puffer_root / ".venv"
        try:
            live_venv_metadata = live_venv.lstat()
        except OSError as exc:
            fail(f"cannot inspect live Puffer venv for replay: {exc}")
        if live_venv.is_symlink() or not stat.S_ISDIR(
            live_venv_metadata.st_mode
        ):
            fail("live Puffer venv for replay is not a real directory")
        try:
            os.symlink(live_venv, replay / ".venv", target_is_directory=True)
        except OSError as exc:
            fail(f"cannot project the sealed Puffer venv into replay: {exc}")

        archive_directory = replay / "raylib-archives"
        try:
            archive_directory.mkdir(mode=0o700)
        except OSError as exc:
            fail(f"cannot create independent Raylib archive cache: {exc}")
        replay_archive = archive_directory / (
            f"{expected_raylib['directory']}.tar.gz"
        )
        atomic_write(replay_archive, live_archive)
        replay_environment = _puffer_replay_environment(replay, toolchain)
        run_checked(
            [
                "/bin/bash",
                str(ROOT / "tools/install_puffer_env.sh"),
                str(replay),
            ],
            timeout=1800,
            environment=replay_environment,
        )
        for mode in ("--cpu", "--fast"):
            run_checked(
                ["/bin/bash", "./build.sh", "bloodbowl", mode],
                cwd=replay,
                timeout=1800,
                environment=replay_environment,
            )
        run_checked(
            [
                "/bin/bash",
                str(ROOT / "tools/install_puffer_env.sh"),
                "--check",
                str(replay),
            ],
            timeout=600,
            environment=replay_environment,
        )
        replay_environment_hash = _environment_source_sha256(
            replay / "ocean/bloodbowl"
        )
        require_exact(
            replay_environment_hash,
            environment_source_sha256,
            "independent ordinary replay environment source",
        )
        native_build_inputs = {
            "raylib": _expected_puffer_raylib_input(replay)
        }
        probe = run_checked(
            [
                str(replay / ".venv/bin/python"),
                "-B",
                "-I",
                "-c",
                INDEPENDENT_ORDINARY_MODULE_PROBE,
                str(ROOT / "tools"),
                str(replay),
            ],
            cwd=replay,
            timeout=300,
            environment=replay_environment,
        )
        try:
            module_receipt = json.loads(probe.stdout)
        except (UnicodeError, json.JSONDecodeError) as exc:
            fail(f"independent ordinary module receipt is malformed: {exc}")
        if probe.stdout.encode("ascii") != canonical_json(module_receipt):
            fail("independent ordinary module receipt is noncanonical")
        _validate_ordinary_module_receipt(
            module_receipt,
            environment_source_sha256=environment_source_sha256,
        )
        module_binary = replay / module_receipt["module_path"]
        module_payload = read_regular_bytes(
            module_binary,
            maximum=1 << 30,
            location="independently rebuilt ordinary Puffer module",
        )
        require_exact(
            module_receipt["module_sha256"],
            sha256_bytes(module_payload),
            "independently rebuilt ordinary module SHA-256",
        )
        authority_payload = read_regular_bytes(
            replay / "src/exact_action_build_hash.h",
            maximum=1 << 20,
            location="independently rebuilt ordinary authority",
        )
        final_status = git_output(
            replay,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ).splitlines()
        return {
            "schema": "bloodbowl-f5-independent-ordinary-replay-v1",
            "commit": PUFFER_COMMIT,
            "git_tree": expected_tree,
            "initial_git_status_sha256": sha256_bytes(
                canonical_json(initial_status)
            ),
            "final_git_status": final_status,
            "final_git_status_sha256": sha256_bytes(
                canonical_json(final_status)
            ),
            "environment_source_sha256": replay_environment_hash,
            "authority_sha256": sha256_bytes(authority_payload),
            "module_receipt": module_receipt,
            "native_build_inputs": native_build_inputs,
            "python_startup_input": python_startup_input,
        }


def validate_puffer_lifecycle(
    root: Path,
    *,
    puffer_root: Path,
    puffer: dict[str, Any],
    module: dict[str, Any],
    module_binary: Path,
    current_status: list[str],
    installed_content_hash: str,
) -> dict[str, Any]:
    if (
        puffer["lifecycle_evidence"] != "puffer-lifecycle.json"
        or puffer["lifecycle_evidence_sha256"]
        != sha256_file(root / "puffer-lifecycle.json")
    ):
        fail("Puffer lifecycle evidence identity differs")
    lifecycle = load_json(root / "puffer-lifecycle.json")
    exact_keys(
        lifecycle,
        {
            "schema",
            "puffer_commit",
            "scope",
            "source_contracts",
            "build_toolchain",
            "native_build_inputs",
            "initial",
            "ordinary",
            "steps",
            "final",
        },
        "Puffer lifecycle",
    )
    if (
        lifecycle["schema"] != "bloodbowl-f5-puffer-lifecycle-v1"
        or lifecycle["puffer_commit"] != PUFFER_COMMIT
    ):
        fail("Puffer lifecycle schema/pin differs")
    require_exact(
        lifecycle["scope"],
        {
            "caller_designated_tree_mutated_in_place": True,
            "puffer_tree_embedded_in_evidence": False,
            "live_final_tree_required_for_verification": True,
            "cpu_foundation_only": True,
            "x86_validation": "pending-external",
            "nvidia_validation": "pending-external",
            "ppo_learning": "out-of-scope",
        },
        "Puffer lifecycle scope",
    )
    source_paths = (
        "tools/install_puffer_env.sh",
        "tools/install_f5_trainability_env.sh",
        "training/puffer_portable_simd_flags.patch",
        "training/puffer_raylib_pin.patch",
        "tools/run_reward_ablation.sh",
        "tools/run_reward_screen.sh",
    )
    source_contracts = lifecycle["source_contracts"]
    exact_keys(
        source_contracts, set(source_paths), "Puffer lifecycle source contracts"
    )
    for relative in source_paths:
        require_exact(
            source_contracts[relative],
            sha256_file(ROOT / relative),
            f"Puffer lifecycle source contract {relative}",
        )
    expected_toolchain = _expected_puffer_build_toolchain()
    require_exact(
        lifecycle["build_toolchain"],
        expected_toolchain,
        "Puffer lifecycle build toolchain",
    )
    require_exact(
        lifecycle["native_build_inputs"],
        {"raylib": _expected_puffer_raylib_input(puffer_root)},
        "Puffer lifecycle native build inputs",
    )

    initial = lifecycle["initial"]
    exact_keys(
        initial,
        {
            "commit",
            "git_status",
            "git_tree",
            "absent_owned_paths",
            "absent_compiled_modules",
            "absent_native_build_inputs",
            "prepared_venv_python",
            "prepared_venv_python_sha256",
            "prepared_venv_puffer_entrypoint",
            "prepared_venv_puffer_entrypoint_sha256",
            "prepared_venv_puffer_entrypoint_normalized_sha256",
            "prepared_venv_puffer_interpreter",
            "prepared_venv_puffer_interpreter_sha256",
            "prepared_python_startup",
            "prepared_pufferlib_distribution",
        },
        "Puffer lifecycle initial state",
    )
    initial_tree = git_output(puffer_root, "rev-parse", "HEAD^{tree}")
    if (
        initial["commit"] != PUFFER_COMMIT
        or initial["git_status"] != []
        or initial["git_tree"] != initial_tree
        or puffer["lifecycle_initial_git_tree"] != initial_tree
        or initial["absent_owned_paths"]
        != [
            "bloodbowl",
            "config/bloodbowl.ini",
            "ocean/bloodbowl",
            "src/exact_action_build_hash.h",
        ]
        or initial["absent_compiled_modules"] is not True
        or initial["absent_native_build_inputs"]
        != list(PRISTINE_PUFFER_NATIVE_INPUT_PATHS)
        or initial["prepared_venv_python"] != ".venv/bin/python"
        or initial["prepared_venv_puffer_entrypoint"] != ".venv/bin/puffer"
        or initial["prepared_venv_puffer_interpreter"]
        != ".venv/bin/python"
    ):
        fail("Puffer lifecycle did not begin from the exact pristine state")
    prepared_python = puffer_root / ".venv/bin/python"
    prepared_python_binary = prepared_python.resolve(strict=True)
    require_exact(
        initial["prepared_venv_python_sha256"],
        sha256_file(prepared_python_binary),
        "Puffer lifecycle prepared Python",
    )
    require_exact(
        initial["prepared_venv_puffer_interpreter_sha256"],
        sha256_file(prepared_python_binary),
        "Puffer lifecycle entrypoint interpreter",
    )
    require_exact(
        initial["prepared_python_startup"],
        _expected_puffer_python_startup_input(puffer_root),
        "Puffer lifecycle sealed Python startup input",
    )
    entrypoint = puffer_root / ".venv/bin/puffer"
    try:
        entrypoint_metadata = entrypoint.lstat()
        entrypoint_payload = entrypoint.read_bytes()
    except OSError as exc:
        fail(f"cannot inspect prepared Puffer entrypoint: {exc}")
    if (
        entrypoint.is_symlink()
        or not stat.S_ISREG(entrypoint_metadata.st_mode)
        or entrypoint_metadata.st_nlink != 1
        or not os.access(entrypoint, os.X_OK)
    ):
        fail(
            "prepared Puffer entrypoint is not an executable singly linked "
            "regular non-link file"
        )
    expected_entrypoint = (
        f"#!{puffer_root / '.venv/bin/python'}\n".encode("utf-8")
        + PUFFER_ENTRYPOINT_BODY
    )
    if entrypoint_payload != expected_entrypoint:
        fail("prepared Puffer entrypoint content differs")
    require_exact(
        initial["prepared_venv_puffer_entrypoint_sha256"],
        sha256_bytes(entrypoint_payload),
        "Puffer lifecycle entrypoint",
    )
    require_exact(
        initial["prepared_venv_puffer_entrypoint_normalized_sha256"],
        sha256_bytes(PUFFER_ENTRYPOINT_NORMALIZED),
        "Puffer lifecycle normalized entrypoint",
    )
    try:
        prepared_distribution = json.loads(
            run_checked(
                [
                    str(prepared_python),
                    "-B",
                    "-I",
                    "-c",
                    PUFFER_DISTRIBUTION_PROBE,
                    str(puffer_root),
                ],
                timeout=30,
            ).stdout
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        fail(f"prepared pufferlib distribution probe is malformed: {exc}")
    expected_distribution = {
        "name": "pufferlib",
        "version": "4.0.0",
        "editable": True,
        "source_matches_pinned_root": True,
    }
    require_exact(
        prepared_distribution,
        expected_distribution,
        "live prepared pufferlib distribution",
    )
    require_exact(
        initial["prepared_pufferlib_distribution"],
        expected_distribution,
        "Puffer lifecycle prepared pufferlib distribution",
    )

    ordinary = lifecycle["ordinary"]
    exact_keys(
        ordinary,
        {
            "after_step",
            "authority_sha256",
            "environment_snapshot_sha256",
            "git_status",
            "git_status_sha256",
            "module_evidence",
            "module_evidence_sha256",
        },
        "Puffer lifecycle ordinary phase",
    )
    ordinary_path = root / "ordinary-module.json"
    if (
        ordinary["after_step"] != "ordinary-module-none"
        or ordinary["module_evidence"] != "ordinary-module.json"
        or ordinary["module_evidence_sha256"] != sha256_file(ordinary_path)
        or ordinary["environment_snapshot_sha256"] != installed_content_hash
        or type(ordinary["git_status"]) is not list
        or any(type(line) is not str for line in ordinary["git_status"])
        or ordinary["git_status_sha256"]
        != sha256_bytes(canonical_json(ordinary["git_status"]))
    ):
        fail("Puffer ordinary phase identity differs")
    require_sha256(
        ordinary["authority_sha256"], "ordinary authority SHA-256"
    )
    ordinary_module = load_json(ordinary_path)
    _validate_ordinary_module_receipt(
        ordinary_module,
        environment_source_sha256=installed_content_hash,
    )

    steps = lifecycle["steps"]
    if type(steps) is not list or len(steps) != len(
        EXPECTED_LIFECYCLE_STEPS
    ):
        fail("Puffer lifecycle step count differs")
    stream_payloads: dict[str, tuple[bytes, bytes]] = {}
    for sequence, (step, expected) in enumerate(
        zip(steps, EXPECTED_LIFECYCLE_STEPS), start=1
    ):
        location = f"Puffer lifecycle step {sequence}"
        exact_keys(
            step,
            {
                "sequence",
                "id",
                "command",
                "expected_exit_code",
                "exit_code",
                "stdout",
                "stderr",
            },
            location,
        )
        if (
            step["sequence"] != sequence
            or step["id"] != expected["id"]
            or not exact_json_equal(step["command"], expected["command"])
            or step["expected_exit_code"] != expected["exit_code"]
            or step["exit_code"] != expected["exit_code"]
        ):
            fail(f"{location} command/order/exit receipt differs")
        prefix = f"puffer-lifecycle/{sequence:02d}-{expected['id']}"
        stdout = _read_lifecycle_stream(
            root,
            step["stdout"],
            expected_path=prefix + ".stdout.txt",
            location=location + " stdout",
        )
        stderr = _read_lifecycle_stream(
            root,
            step["stderr"],
            expected_path=prefix + ".stderr.txt",
            location=location + " stderr",
        )
        for leaked in (str(puffer_root).encode(), str(ROOT).encode()):
            if leaked in stdout or leaked in stderr:
                fail(f"{location} retained a non-normalized absolute path")
        stream_payloads[expected["id"]] = (stdout, stderr)

    ordinary_stdout = canonical_json(ordinary_module)
    if stream_payloads["ordinary-module-none"][0] != ordinary_stdout:
        fail("ordinary module command output differs from its JSON artifact")
    required_markers = {
        "ordinary-install": (
            b"installed: <pinned-puffer-root>/ocean/bloodbowl",
            b"",
        ),
        "ordinary-cpu-build": (b"Compiling CPU training backend", b""),
        "ordinary-fast-build": (b"Built: ./bloodbowl", b""),
        "ordinary-check": (b"drift check: OK", b""),
        "f5-check-rejects-ordinary": (
            b"",
            b"qualification authority differs",
        ),
        "f5-stage": (b"f5-fixed-state-v1", b""),
        "f5-cpu-rebuild": (b"Compiling CPU training backend", b""),
        "f5-check": (b"F5 qualification drift check: OK", b""),
        "f5-install-rejects-already-staged": (
            b"",
            b"f5-fixed-state-v1 is already staged",
        ),
        "ordinary-install-rejects-f5": (
            b"",
            b"ordinary Puffer lifecycle rejects "
            b"qualification_fixture_role=f5-fixed-state-v1 (enabled=1)",
        ),
        "production-ablation-rejects-f5": (
            b"",
            b"production reward launcher requires an ordinary role-none "
            b"Puffer build",
        ),
        "production-screen-rejects-f5": (
            b"",
            b"production reward screen requires an ordinary role-none "
            b"Puffer build",
        ),
    }
    for step_id, (stdout_marker, stderr_marker) in required_markers.items():
        stdout, stderr = stream_payloads[step_id]
        if (
            stdout_marker and stdout_marker not in stdout
        ) or (
            stderr_marker and stderr_marker not in stderr
        ):
            fail(f"Puffer lifecycle step {step_id} lacks its result marker")
    role_rejection_marker = (
        b"ordinary Puffer lifecycle rejects "
        b"qualification_fixture_role=f5-fixed-state-v1 (enabled=1)"
    )
    for step_id in (
        "production-ablation-rejects-f5",
        "production-screen-rejects-f5",
    ):
        if role_rejection_marker not in stream_payloads[step_id][1]:
            fail(f"{step_id} did not expose the actual installer rejection")

    final = lifecycle["final"]
    exact_keys(
        final,
        {
            "commit",
            "git_status",
            "git_status_sha256",
            "authority_sha256",
            "environment_snapshot_sha256",
            "module_path",
            "module_sha256",
            "qualification_fixture_enabled",
            "qualification_fixture_role",
            "compiled_gpu",
            "state_bank_kind",
            "state_bank_kind_name",
        },
        "Puffer lifecycle final state",
    )
    expected_final = {
        "commit": PUFFER_COMMIT,
        "git_status": current_status,
        "git_status_sha256": hashlib.sha256(
            canonical_json(current_status)
        ).hexdigest(),
        "authority_sha256": sha256_file(
            puffer_root / "src/exact_action_build_hash.h"
        ),
        "environment_snapshot_sha256": installed_content_hash,
        "module_path": module_binary.relative_to(puffer_root).as_posix(),
        "module_sha256": sha256_file(module_binary),
        "qualification_fixture_enabled": True,
        "qualification_fixture_role": FIXTURE_ROLE,
        "compiled_gpu": 0,
        "state_bank_kind": 0,
        "state_bank_kind_name": "none",
    }
    require_exact(final, expected_final, "Puffer lifecycle final state")
    if (
        ordinary["authority_sha256"] == final["authority_sha256"]
        or ordinary_module["module_sha256"] == final["module_sha256"]
        or ordinary_module["module_path"] != final["module_path"]
        or module["module_sha256"] != final["module_sha256"]
    ):
        fail("Puffer lifecycle ordinary/F5 build transition is not distinct")
    independent_ordinary = _independently_replay_ordinary(
        puffer_root,
        environment_source_sha256=installed_content_hash,
        toolchain=expected_toolchain,
    )
    _require_independent_ordinary_binding(
        ordinary_module,
        ordinary["authority_sha256"],
        ordinary["git_status"],
        independent_ordinary,
    )
    return {
        "schema": lifecycle["schema"],
        "steps": len(steps),
        "initial_git_tree": initial_tree,
        "ordinary_module_sha256": ordinary_module["module_sha256"],
        "final_module_sha256": final["module_sha256"],
        "independent_ordinary_replay": {
            "schema": independent_ordinary["schema"],
            "commit": independent_ordinary["commit"],
            "git_tree": independent_ordinary["git_tree"],
            "initial_git_status_sha256": independent_ordinary[
                "initial_git_status_sha256"
            ],
            "final_git_status_sha256": independent_ordinary[
                "final_git_status_sha256"
            ],
            "environment_source_sha256": independent_ordinary[
                "environment_source_sha256"
            ],
            "authority_sha256": independent_ordinary["authority_sha256"],
            "module_sha256": independent_ordinary[
                "module_receipt"
            ]["module_sha256"],
            "native_build_inputs": independent_ordinary[
                "native_build_inputs"
            ],
            "python_startup_input": independent_ordinary[
                "python_startup_input"
            ],
        },
        "puffer_tree_embedded": False,
    }


def validate_puffer(root: Path, evidence: dict[str, Any]) -> dict[str, Any]:
    puffer = evidence["puffer"]
    puffer_keys = {
        "validated",
        "commit",
        "status",
        "authority_sha256",
        "environment_snapshot_sha256",
        "module_evidence",
        "module_evidence_sha256",
        "dependency_identity_scope",
        "requirements_sha256",
        "distributions_snapshot_sha256",
        "distributions_snapshot_bytes",
        "distributions_digest_file_sha256",
        "direct_requirements",
        "torch_version",
        "torch_cpu_only",
        "torch_collector_sha256",
        "lifecycle_evidence",
        "lifecycle_evidence_sha256",
        "lifecycle_initial_git_tree",
    }
    exact_keys(puffer, puffer_keys, "puffer")
    if (
        puffer["validated"] is not True
        or puffer["commit"] != PUFFER_COMMIT
        or puffer["module_evidence"] != "puffer-module.json"
        or puffer["dependency_identity_scope"] != DEPENDENCY_IDENTITY_SCOPE
        or puffer["torch_cpu_only"] is not True
    ):
        fail("fresh sealed Puffer validation is absent, unpinned, or overstated")
    module_path = root / "puffer-module.json"
    if puffer["module_evidence_sha256"] != sha256_file(module_path):
        fail("Puffer module evidence digest differs")
    module = load_json(module_path)
    exact_keys(
        module,
        {
            "schema",
            "puffer_commit",
            "module_path",
            "module_sha256",
            "module_contract",
            "environment_config",
            "runtime",
            "vectorization",
            "transitions",
            "rollout_tail",
            "masked_random",
            "autoreset",
            "log",
        },
        "Puffer module evidence",
    )
    if (
        module["schema"] != "bloodbowl-f5-puffer-module-v1"
        or module["puffer_commit"] != PUFFER_COMMIT
        or type(module["module_path"]) is not str
        or not Path(module["module_path"]).is_absolute()
    ):
        fail("Puffer module evidence identity differs")
    raw_module_binary = Path(module["module_path"])
    read_regular_bytes(
        raw_module_binary,
        maximum=1 << 30,
        location="compiled Puffer module",
    )
    module_binary = raw_module_binary.resolve(strict=True)
    if (
        module_binary.parent.name != "pufferlib"
        or not module_binary.name.startswith("_C.cpython-312-")
        or module_binary.suffix != ".so"
    ):
        fail("compiled Puffer module path does not identify the sealed ABI")
    puffer_root = module_binary.parent.parent.resolve(strict=True)
    if Path(
        git_output(puffer_root, "rev-parse", "--show-toplevel")
    ).resolve(strict=True) != puffer_root:
        fail("Puffer module did not resolve to a Git worktree root")
    startup_input = _expected_puffer_python_startup_input(puffer_root)
    current_status = git_output(
        puffer_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    ).splitlines()
    if (
        any(type(line) is not str for line in puffer["status"])
        or not exact_json_equal(puffer["status"], current_status)
        or git_output(puffer_root, "rev-parse", "HEAD") != PUFFER_COMMIT
        or module["module_sha256"] != sha256_file(module_binary)
    ):
        fail("Puffer module/source identity differs")

    authority = puffer_root / "src/exact_action_build_hash.h"
    authority_payload = read_regular_bytes(
        authority,
        maximum=1 << 20,
        location="Puffer exact-action build authority",
    )
    content_hash_path = puffer_root / "ocean/bloodbowl/.content_hash"
    content_hash_payload = read_regular_bytes(
        content_hash_path,
        maximum=65,
        location="installed Puffer environment content hash",
    )
    try:
        installed_content_hash = content_hash_payload.decode("ascii").removesuffix(
            "\n"
        )
    except UnicodeError as exc:
        fail(f"installed Puffer environment content hash is not ASCII: {exc}")
    require_sha256(installed_content_hash, "installed environment content hash")
    if content_hash_payload != (installed_content_hash + "\n").encode("ascii"):
        fail("installed Puffer environment content hash is noncanonical")
    if (
        puffer["authority_sha256"]
        != hashlib.sha256(authority_payload).hexdigest()
        or puffer["environment_snapshot_sha256"] != installed_content_hash
    ):
        fail("Puffer authority/environment snapshot receipt differs")

    run_checked(
        [
            "/bin/bash",
            str(ROOT / "tools/install_f5_trainability_env.sh"),
            "--check",
            str(puffer_root),
        ],
        timeout=300,
        environment=isolated_python_environment(),
    )
    current_environment_hash = _environment_source_sha256(
        ROOT / "puffer/bloodbowl"
    )
    installed_environment_hash = _environment_source_sha256(
        puffer_root / "ocean/bloodbowl"
    )
    if (
        current_environment_hash != installed_environment_hash
        or current_environment_hash != installed_content_hash
    ):
        fail("installed Puffer environment is not the current source closure")

    environment_config = load_json(root / "environment-config.json")
    source_environment_config = load_json(ENV_CONFIG)
    if (
        len(environment_config) != 51
        or not exact_json_equal(environment_config, source_environment_config)
        or not exact_json_equal(module["environment_config"], environment_config)
    ):
        fail("Puffer module exact 51-field environment config differs")
    for key, item in environment_config.items():
        if (
            type(key) is not str
            or isinstance(item, bool)
            or type(item) not in (int, float)
        ):
            fail("Puffer environment config contains a nonnumeric field")

    contract_expected = {
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
        "qualification_fixture_bbs_sha256": F5_BBS_SHA256,
        "qualification_fixture_bundle_sha256": FULL_BBS_SHA256,
        "qualification_fixture_bbs_source_id": 0xA9000019,
        "qualification_fixture_authored_source_id": 0xAE00001A,
        "qualification_fixture_reference_trace_schema":
            "bloodbowl-f5-reference-trace-v1",
        "qualification_fixture_reference_trace_sha256": TRACE_SHA256,
        "qualification_fixture_max_decisions": 8,
        "qualification_fixture_reward_contract":
            "touchdown-zero-sum-only-v1",
        "qualification_fixture_environment_source_sha256":
            current_environment_hash,
    }
    exact_keys(
        module["module_contract"],
        set(contract_expected),
        "Puffer compiled module contract",
    )
    require_exact(
        module["module_contract"],
        contract_expected,
        "Puffer compiled module contract",
    )

    live = _query_puffer_runtime(puffer_root)
    dependency = _validate_distribution_snapshot(
        puffer_root, module["runtime"], live
    )
    if (
        type(live["compiled_module_path"]) is not str
        or Path(live["compiled_module_path"]).resolve(strict=True)
        != module_binary
        or live["collector_uses_compiled_module"] is not True
    ):
        fail("independent Puffer import resolved a different compiled module")
    exact_keys(
        live["compiled_module_contract"],
        set(contract_expected),
        "independently imported Puffer module contract",
    )
    require_exact(
        live["compiled_module_contract"],
        contract_expected,
        "independently imported Puffer module contract",
    )
    top_dependency_expected = {
        "dependency_identity_scope": dependency["scope"],
        "requirements_sha256": dependency["requirements_sha256"],
        "distributions_snapshot_sha256": dependency["snapshot_sha256"],
        "distributions_snapshot_bytes": dependency["snapshot_bytes"],
        "distributions_digest_file_sha256": dependency[
            "digest_file_sha256"
        ],
        "direct_requirements": dependency["direct_requirements"],
        "torch_version": dependency["torch_version"],
        "torch_cpu_only": True,
        "torch_collector_sha256": dependency["torch_collector_sha256"],
    }
    for key, expected in top_dependency_expected.items():
        require_exact(puffer[key], expected, f"puffer.{key}")
    lifecycle = validate_puffer_lifecycle(
        root,
        puffer_root=puffer_root,
        puffer=puffer,
        module=module,
        module_binary=module_binary,
        current_status=current_status,
        installed_content_hash=installed_content_hash,
    )

    reference = load_json(root / "reference.json")
    validate_module_transitions(
        module["transitions"], reference["transitions"]
    )
    validate_rollout_tail(module["rollout_tail"])
    validate_masked_random(module["masked_random"])
    validate_vectorization(module["vectorization"])
    autoreset_expected = {
        "obs_sha256": AUTORESET_OBS_SHA256,
        "mask_sha256": AUTORESET_MASK_SHA256,
        "exact": True,
    }
    exact_keys(module["autoreset"], set(autoreset_expected), "Puffer autoreset")
    require_exact(
        module["autoreset"], autoreset_expected, "Puffer autoreset receipt"
    )
    validate_module_log(module["log"], "Puffer direct-oracle log")
    require_exact(
        module["rollout_tail"]["log"],
        module["log"],
        "Puffer collector/direct log binding",
    )
    require_exact(
        module["rollout_tail"]["collector"]["obs_sha256"],
        [transition["obs_sha256"] for transition in module["transitions"]],
        "Puffer collector/direct observation binding",
    )

    with tempfile.TemporaryDirectory(prefix="f5-module-verify-") as directory:
        reproduced = Path(directory) / "module.json"
        run_checked(
            [
                str(puffer_root / ".venv/bin/python"),
                "-B",
                "-I",
                str(MODULE_CHECKER),
                "--puffer-root",
                str(puffer_root),
                "--output",
                str(reproduced),
            ],
            timeout=300,
            environment=isolated_python_environment(),
        )
        if reproduced.read_bytes() != module_path.read_bytes():
            fail("Puffer module diagnostic did not reproduce byte-identically")
    return {
        "commit": PUFFER_COMMIT,
        "module_sha256": module["module_sha256"],
        "environment_source_sha256": current_environment_hash,
        "dependency_identity_scope": dependency["scope"],
        "dependency_snapshot_sha256": dependency["snapshot_sha256"],
        "torch_version": dependency["torch_version"],
        "torch_cpu_only": True,
        "python_startup_input": startup_input,
        "lifecycle": lifecycle,
    }


def validate_binaries(evidence: dict[str, Any], *, fresh_c_test: Path) -> None:
    binaries = evidence["binaries"]
    expected_paths = {
        GENERATOR.name: GENERATOR,
        C_TEST.name: C_TEST,
        DIAGNOSTICS.name: DIAGNOSTICS,
    }
    if set(binaries) != set(expected_paths):
        fail("binary manifest membership differs")
    for name, path in expected_paths.items():
        description = binaries[name]
        exact_keys(description, {"bytes", "sha256"}, f"binaries.{name}")
        if (
            description["bytes"] != path.stat().st_size
            or description["sha256"] != sha256_file(path)
        ):
            fail(f"binary identity differs: {name}")
    run_checked([str(fresh_c_test)])


def build_fresh_tools(directory: Path) -> tuple[Path, Path, Path]:
    build = directory / "build"
    generator = build / GENERATOR.name
    c_test = build / C_TEST.name
    diagnostics = build / DIAGNOSTICS.name
    compiler = foundation_compiler()
    run_checked(
        [
            "make",
            "-B",
            f"CC={compiler}",
            f"CFLAGS={FOUNDATION_CFLAGS}",
            "LDFLAGS=",
            f"BUILD={build}",
            str(generator),
            str(c_test),
            str(diagnostics),
        ],
        timeout=900,
        environment=foundation_build_environment(),
    )
    for path in (generator, c_test, diagnostics):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            fail(f"fresh qualification build did not produce {path.name}")
    return generator, c_test, diagnostics


def verify(root: Path) -> dict[str, Any]:
    if root.is_symlink():
        fail("evidence root must not be a symlink")
    root = root.resolve(strict=True)
    if not root.is_dir():
        fail("evidence root is not a real directory")
    verdict_path = root / "verdict.json"
    try:
        verdict_info = verdict_path.lstat()
    except FileNotFoundError:
        verdict_info = None
    if verdict_info is not None:
        if (
            verdict_path.is_symlink()
            or not stat.S_ISREG(verdict_info.st_mode)
            or verdict_info.st_nlink != 1
        ):
            fail("preexisting verdict is not a singly linked regular file")
        verdict_path.unlink()
    evidence_path = root / "evidence.json"
    evidence_payload = read_regular_bytes(
        evidence_path,
        maximum=MAX_JSON_BYTES,
        location="foundation evidence",
    )
    evidence_sha256 = sha256_bytes(evidence_payload)
    evidence = load_json_bytes(evidence_payload, "foundation evidence")
    if evidence_payload != canonical_json(evidence):
        fail("foundation evidence JSON is not canonical")
    reject_worker_verdicts(evidence)
    exact_keys(
        evidence,
        {
            "schema",
            "qualification_only",
            "fixture_role",
            "source",
            "task",
            "reference",
            "safe_baseline",
            "random_baseline",
            "puffer",
            "binaries",
            "platform",
            "external_gates",
            "commands",
            "artifacts",
        },
        "evidence",
    )
    if (
        evidence["schema"] != EVIDENCE_SCHEMA
        or evidence["qualification_only"] is not True
        or evidence["fixture_role"] != FIXTURE_ROLE
    ):
        fail("foundation evidence identity differs")
    if evidence["external_gates"] != {
        "exact_pin_x86": "pending-external",
        "nvidia_schema11": "pending-external",
        "ppo_learning": "out-of-scope",
    }:
        fail("external validation boundary is misstated")
    if not exact_json_equal(evidence["commands"], EXPECTED_COMMANDS):
        fail("ordered foundation command record differs")
    validate_source(evidence)
    validate_platform(evidence)
    validate_artifacts(root, evidence)
    with tempfile.TemporaryDirectory(
        prefix="f5-foundation-independent-build-"
    ) as build_directory:
        generator, c_test, diagnostics = build_fresh_tools(
            Path(build_directory)
        )
        validate_task(root, evidence, generator=generator)
        validate_reference(root, evidence, diagnostics=diagnostics)
        validate_baselines(root, evidence, diagnostics=diagnostics)
        validate_binaries(evidence, fresh_c_test=c_test)
    puffer = validate_puffer(root, evidence)
    return {
        "schema": VERDICT_SCHEMA,
        "accepted": True,
        "scope": "local-cpu-foundation-only",
        "qualification_only": True,
        "fixture_role": FIXTURE_ROLE,
        "evidence_sha256": evidence_sha256,
        "source_commit": evidence["source"]["commit"],
        "puffer": puffer,
        "reference_episodes": 1,
        "reference_successes": 1,
        "random_episodes": evidence["random_baseline"]["episodes"],
        "random_successes": evidence["random_baseline"]["successes"],
        "safe_zero_dice_trajectories": 721,
        "external_gates": evidence["external_gates"],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_dir", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    verdict_path: Path | None = None
    try:
        requested_root = args.artifact_dir.absolute()
        if requested_root.is_symlink():
            fail("evidence root must not be a symlink")
        validated_root = requested_root.resolve(strict=True)
        if not validated_root.is_dir():
            fail("evidence root is not a real directory")
        verdict_path = validated_root / "verdict.json"
        verdict = verify(validated_root)
        atomic_write(verdict_path, canonical_json(verdict))
    except (
        FoundationVerificationError,
        OSError,
        subprocess.SubprocessError,
        ValueError,
    ) as exc:
        if verdict_path is not None:
            try:
                verdict_info = verdict_path.lstat()
            except FileNotFoundError:
                verdict_info = None
            if (
                verdict_info is not None
                and not verdict_path.is_symlink()
                and stat.S_ISREG(verdict_info.st_mode)
                and verdict_info.st_nlink == 1
            ):
                verdict_path.unlink()
        print(f"F5 foundation verification failed: {exc}", file=sys.stderr)
        return 2
    print(verdict_path)
    return 0


if __name__ == "__main__":
    if (
        sys.flags.dont_write_bytecode != 1
        or sys.flags.isolated != 1
        or sys.flags.no_site != 1
    ):
        print(
            "F5 foundation verifier must be invoked with "
            "`python3 -B -I -S tools/verify_f5_trainability_foundation.py ...`",
            file=sys.stderr,
        )
        raise SystemExit(2)
    raise SystemExit(main())
