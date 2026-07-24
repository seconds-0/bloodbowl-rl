#!/usr/bin/env python3
"""Validate and render complete, hashable Blood Bowl reward manifests.

Historical launchers carry different baked-in reward recipes and Puffer's CLI
is last-wins. A causal run therefore needs a COMPLETE override for every
reward field, not a handful of changed coefficients. This tool rejects missing
or unknown keys, checks the trainer's scalar clamp contract, prints a canonical
SHA-256, and emits one CLI token per line for safe Bash array loading.

Example:
  mapfile -t REWARD_ARGS < <(
    python3 tools/reward_manifest.py puffer/config/rewards/r0_full.json --lines)
  puffer train bloodbowl "${REWARD_ARGS[@]}" ...
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shlex
from pathlib import Path
from typing import Any


REWARD_FLOAT_KEYS = (
    "reward_td",
    "reward_win",
    "reward_draw",
    "reward_setup_done",
    "reward_setup_autofix",
    "reward_ball_gain",
    "reward_ball_loss",
    "reward_dist_ball",
    "reward_dist_endzone",
    "reward_dist_pbrs_gamma",
    "reward_injury_inflicted",
    "reward_injury_taken",
    "reward_send_off",
    "reward_kickoff_touchback",
    "reward_surf_taken",
    "reward_surf_inflicted",
    "reward_k_kd",
    "reward_k_value",
    "reward_k_self_injury",
    "reward_k_ball",
    "reward_k_seq",
    "reward_k_turnover",
    "reward_possession",
    "reward_k_assist",
    "reward_rush_cost",
    "reward_carrier_exposure",
    "reward_carrier_exposure_soft",
    "reward_carrier_threat",
    "reward_defensive_threat",
    "reward_defensive_threat_soft",
    "reward_statmatch_scale",
)
REWARD_INT_KEYS = ("reward_injury_value_scaled",)

# Keys introduced after schema 1. A schema-1 manifest must NOT carry them: its
# digest is quoted as provenance by completed experiments and in DECISIONS.md, so
# adding a field to those files would silently invalidate every reference. Schema
# 1 therefore *means* the legacy behaviour for each of these (raw delta-Phi for
# the distance channels), which is a documented semantic, not an inherited
# default. Schema 2 must state every one of them explicitly.
SCHEMA2_ONLY_FLOAT_KEYS = ("reward_dist_pbrs_gamma",)
MAX_SCHEMA_VERSION = 2

# The vendored trainer's reward clamp, applied in both backends by
# training/puffer_reward_clamp_range.patch and mirrored as
# BBE_TRAINER_REWARD_CLAMP in puffer/bloodbowl/bloodbowl.h. It is a
# NaN/pathology guard, not a design bound: clipping a shaped reward SUM voids
# Ng-Harada-Russell policy invariance, so the launch-time job is to prove the
# design never reaches it (D234).
TRAINER_REWARD_CLAMP = 8.0
MAX_PITCH_DELTA = 25.0  # BB_PITCH_LEN - 1 (x coordinates 0..25)

REQUIRED_KEYS = REWARD_FLOAT_KEYS + REWARD_INT_KEYS


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    version = manifest.get("schema_version")
    if version not in (1, 2):
        raise ValueError(
            f"reward manifest schema_version must be 1 or {MAX_SCHEMA_VERSION}")
    if not isinstance(manifest.get("name"), str) or not manifest["name"].strip():
        raise ValueError("reward manifest needs a non-empty name")
    reward = manifest.get("reward")
    if not isinstance(reward, dict):
        raise ValueError("reward manifest needs an object named 'reward'")

    keys = set(reward)
    required = set(REQUIRED_KEYS)
    if version < 2:
        required -= set(SCHEMA2_ONLY_FLOAT_KEYS)
    missing = sorted(required - keys)
    unknown = sorted(keys - required)
    if missing:
        raise ValueError(f"missing reward keys: {', '.join(missing)}")
    if unknown:
        raise ValueError(f"unknown reward keys: {', '.join(unknown)}")

    for key in REWARD_FLOAT_KEYS:
        if key not in reward:
            continue  # schema-1 manifest, legacy semantics (see above)
        value = reward[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} must be numeric")
        value = float(value)
        if not math.isfinite(value) or abs(value) > 1.0:
            raise ValueError(
                f"{key}={value!r} must be finite and within [-1,1]")
        reward[key] = value
    for key in REWARD_INT_KEYS:
        value = reward[key]
        if isinstance(value, bool):
            value = int(value)
        if value not in (0, 1):
            raise ValueError(f"{key} must be 0 or 1")
        reward[key] = int(value)

    # A touchdown that decides a non-drawn match receives both terms on one
    # agent-step. Other shaping can also co-fire and is monitored at runtime,
    # but this deterministic objective stack must be safe before launch.
    #
    # D234: this used to be `abs(td) + abs(win) <= 1.0`, which existed solely
    # to fit the trainer's old +-1 clamp -- and the bound was WRONG, not merely
    # tight: it ignored the exact-PBRS terminal payback, which lands on the very
    # same emission, so a manifest could satisfy it and still be truncated
    # live. The bound is now the full derived envelope against the widened
    # clamp, mirroring bbe_reward_clip_threshold in puffer/bloodbowl/bloodbowl.h
    # term for term. Keep the two in sync.
    objective_bound = abs(reward["reward_td"]) + max(
        abs(reward["reward_win"]), abs(reward["reward_draw"]))
    fetch_reach = MAX_PITCH_DELTA * abs(reward["reward_dist_ball"])
    carry_reach = MAX_PITCH_DELTA * abs(reward["reward_dist_endzone"])
    if reward.get("reward_dist_pbrs_gamma", 0.0) > 0.0:
        # Exact PBRS emits on every transition, so the terminal payback
        # -Phi(s_T-1) ADDS to the objective stack.
        envelope = objective_bound + fetch_reach + carry_reach
        # Phi = k*(D_max - dist) must stay >= 0, or every sign conclusion the
        # channel rests on inverts. The env aborts on this too.
        for key in ("reward_dist_ball", "reward_dist_endzone"):
            if reward[key] < 0.0:
                raise ValueError(
                    f"{key}={reward[key]!r} must be >= 0 under exact PBRS so "
                    "the potential stays non-negative")
    else:
        # Legacy raw-delta emits nothing at the terminal and is skipped on any
        # step where a team scored, so a distance delta and the objective stack
        # can never co-fire: the bound is their max, not their sum.
        envelope = max(objective_bound, fetch_reach, carry_reach)
    if envelope > TRAINER_REWARD_CLAMP + 1e-9:
        raise ValueError(
            "reward design envelope can exceed the trainer clamp "
            f"{TRAINER_REWARD_CLAMP}: derived envelope = {envelope}")

    # A same-team catch, throw-in, or hand-off can move the carrier from one
    # extreme x-coordinate to the other while remaining in the carry regime;
    # an analogous loose-ball relocation can move the nearest-player fetch
    # potential. Both channels are priced per square. The 20M R0 preflight
    # empirically clipped the historical .05/.20 recipe in exactly these
    # long-jump-sized increments, so reject any coefficient whose channel can
    # cross the whole objective budget on a single move.
    #
    # D234 keeps this per-channel bound at 1.0 even though the trainer clamp
    # moved to 8. It was never really a clamp-fitting rule: it caps how much of
    # the total reward a single scaffold channel may be worth over a full-pitch
    # move, and relaxing it would let distance shaping outweigh the match
    # objective outright. The clamp-fitting job now belongs to the derived
    # envelope check above.
    fetch_bound = fetch_reach
    if fetch_bound > 1.0 + 1e-9:
        raise ValueError(
            "full-pitch fetch potential can outweigh the match objective: "
            f"25 * abs(reward_dist_ball) = {fetch_bound}")
    carry_bound = carry_reach
    if carry_bound > 1.0 + 1e-9:
        raise ValueError(
            "full-pitch carry potential can outweigh the match objective: "
            f"25 * abs(reward_dist_endzone) = {carry_bound}")

    if (reward["reward_carrier_threat"] != 0.0 and
            (reward["reward_carrier_exposure"] != 0.0 or
             reward["reward_carrier_exposure_soft"] != 0.0)):
        raise ValueError(
            "reward_carrier_threat cannot coexist with carrier_exposure arms")
    if (reward["reward_carrier_threat"] != 0.0 and
            reward["reward_k_assist"] != 0.0):
        raise ValueError(
            "reward_carrier_threat cannot coexist with reward_k_assist")
    if reward["reward_statmatch_scale"] != 0.0:
        raise ValueError(
            "statmatch reward is quarantined: its historical BB2025 targets "
            "mix editions and incompatible event semantics; keep it at zero")

    return manifest


def canonical_bytes(manifest: dict[str, Any]) -> bytes:
    return json.dumps(
        manifest, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf-8")


def load_manifest(path: str | Path) -> tuple[dict[str, Any], str]:
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)
    manifest = validate_manifest(raw)
    digest = hashlib.sha256(canonical_bytes(manifest)).hexdigest()
    return manifest, digest


def _format_value(value: float | int) -> str:
    if isinstance(value, int):
        return str(value)
    return format(value, ".9g")


def cli_args(manifest: dict[str, Any]) -> list[str]:
    reward = manifest["reward"]
    args = []
    for key in REQUIRED_KEYS:
        # A schema-1 manifest legitimately omits the schema-2 keys. Emitting a
        # token for one anyway would be worse than omitting it: the env's own
        # default is the legacy behaviour that schema 1 means, so silence here
        # is the accurate statement, and validate_manifest has already proved
        # the omission is confined to exactly those keys.
        if key not in reward:
            continue
        args.extend((f"--env.{key.replace('_', '-')}",
                     _format_value(reward[key])))
    return args


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    output = parser.add_mutually_exclusive_group()
    output.add_argument(
        "--lines", action="store_true",
        help="print one CLI token per line (safe for Bash mapfile)")
    output.add_argument(
        "--shell", action="store_true",
        help="print a shell-quoted one-line argument string")
    output.add_argument(
        "--json", action="store_true",
        help="print name/hash/CLI args as JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest, digest = load_manifest(args.manifest)
    rendered_args = cli_args(manifest)
    if args.lines:
        print("\n".join(rendered_args))
    elif args.shell:
        print(shlex.join(rendered_args))
    else:
        print(json.dumps({
            "name": manifest["name"],
            "sha256": digest,
            "cli_args": rendered_args,
        }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
