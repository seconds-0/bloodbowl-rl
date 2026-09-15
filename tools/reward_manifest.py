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
import sys
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

# Distance-channel form. A nonzero reward_dist_pbrs_gamma selects exact PBRS;
# zero, or its absence under schema 1, selects the legacy raw-delta ratchet
# (D226), which re-anchors across every possession gap, so carrying the ball
# forward and then losing it keeps the advance unrepaid. A launch must never
# reach that form by omission: a manifest either declares it with
# DISTANCE_MODE_KEY or is one of the historical manifests pinned below. Those
# cannot take the declaration, because their digests are quoted as provenance
# (DECISIONS.md; chain 9 and chain 14 record r0_poss_half as 433c7920...), so
# they are admitted by digest instead, and any edit to one loses the pass.
DISTANCE_MODE_KEY = "reward_dist_mode"
LEGACY_RAW_DELTA = "legacy_raw_delta"
LEGACY_RAW_DELTA_SHA256 = {
    "e5e6744b95085f9b5cd8c0e280cf532e90b39b539114cfaf9692dd2221f6026f": "p1_possession_only",
    "627468ec2e5d238b01606227cc5ffcfed764e391227fc76b517a946d29e7459d": "p2_gain_only",
    "152f1e6f94b46633ae5bceec345fa51705ebb73643b542cc339c70ca32198bc0": "r0_blockev_half",
    "bb7a5b95f50d79bb677ea00430a2b57171441d41ea7de660f8d89b89b62cabf6": "r0_dist_ball_half",
    "2a539b237c37d65c7f3bb9d79c76d5032b5ce845ad289ed78462d440d1cf4bd3": "r0_dist_half",
    "40469c83224b580e7c36b74260ac6eba89cd9ae7168666c2d5f1a5d4a96a7e41": "r0_dist_quarter",
    "14b718f28b2c925ea3279444dfbc679631c0cceea0f84d9e3547e3318ce6e90e": "r0_full",
    "616f5c58ea4c23c92ccf8e27b7357406f2dbd7b5519be6cc129de8a0c0cbd04a": "r0_gain_half",
    "65bc61aac33636e9e7ec8b992af0a4693a2717c14ea5d140d24ab22f953d8469": "r0_poss_half_gain_half",
    "7aa1d629208ec33a087558dc4e91d8319f057d5b3275e014e100441fbd3fcdf3": "r0_poss_half_rush_zero",
    "433c792018acdc01f8c7168e824c9389bf99df2307d3260283b7877df3f69d5c": "r0_poss_half",
    "76700762b665b8fa153935d638603cd020ac55e5acd05cb480e2bffe3368659e": "r0_poss_quarter",
    "729e9cd5f5292b20cd06ae2bf71a869ca2c7d3ea1ef7c0e86f2ed8f9ae4040c3": "r0_poss_zero",
    "5e31a13e5885c71c89af90f2ab504bbf7fcb94230ea33c834ba2d45fc9b930ae": "r2_no_possession",
}

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

    if DISTANCE_MODE_KEY in manifest:
        if manifest[DISTANCE_MODE_KEY] != LEGACY_RAW_DELTA:
            raise ValueError(
                f"{DISTANCE_MODE_KEY} may only declare {LEGACY_RAW_DELTA!r}")
        if reward.get("reward_dist_pbrs_gamma", 0.0) != 0.0:
            raise ValueError(
                f"{DISTANCE_MODE_KEY}={LEGACY_RAW_DELTA!r} contradicts a "
                "nonzero reward_dist_pbrs_gamma")

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


def distance_form(manifest: dict[str, Any], digest: str,
                  train_gamma: float) -> str:
    """Resolve the distance form a launch at train_gamma would train.

    Returns "exact_pbrs", LEGACY_RAW_DELTA, or "none"; raises ValueError for
    an exact-PBRS gamma other than train_gamma and for the legacy ratchet
    reached without a declaration or a pinned historical digest.
    """
    reward = manifest["reward"]
    gamma = reward.get("reward_dist_pbrs_gamma", 0.0)
    if gamma != 0.0:
        if not abs(gamma - train_gamma) <= 1e-9:
            raise ValueError(
                f"reward_dist_pbrs_gamma ({gamma!r}) != train gamma "
                f"({train_gamma!r}): the distance channels would not be exact "
                "PBRS under this trainer")
        return "exact_pbrs"
    if reward["reward_dist_ball"] == 0.0 and reward["reward_dist_endzone"] == 0.0:
        return "none"
    if (manifest.get(DISTANCE_MODE_KEY) == LEGACY_RAW_DELTA or
            digest in LEGACY_RAW_DELTA_SHA256):
        return LEGACY_RAW_DELTA
    raise ValueError(
        f"manifest {manifest['name']!r} ({digest}) has nonzero distance "
        "coefficients without reward_dist_pbrs_gamma, which selects the "
        "farmable legacy raw-delta form; set reward_dist_pbrs_gamma to the "
        f"train gamma, or declare \"{DISTANCE_MODE_KEY}\": "
        f"\"{LEGACY_RAW_DELTA}\"")


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
    output.add_argument(
        "--distance-form", action="store_true",
        help="print the resolved distance form (requires --train-gamma)")
    parser.add_argument(
        "--train-gamma", type=float,
        help="refuse the manifest unless its distance form is sound at this "
             "trainer gamma (see distance_form)")
    args = parser.parse_args()
    if args.distance_form and args.train_gamma is None:
        parser.error("--distance-form requires --train-gamma")
    return args


def main() -> int:
    args = parse_args()
    manifest, digest = load_manifest(args.manifest)
    form = None
    if args.train_gamma is not None:
        try:
            form = distance_form(manifest, digest, args.train_gamma)
        except ValueError as exc:
            print(f"refusing reward manifest {args.manifest}: {exc}",
                  file=sys.stderr)
            return 1
    rendered_args = cli_args(manifest)
    if args.distance_form:
        print(form)
    elif args.lines:
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
