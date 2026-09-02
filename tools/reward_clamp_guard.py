#!/usr/bin/env python3
"""Refuse a reward manifest whose PBRS terminal payback can breach PPO's clamp.

D226 made the distance channels exact discounted PBRS so a closed cycle sums to
`(gamma-1) * sum(Phi) <= 0` and cannot be farmed. That guarantee is only real if
the terminal repayment actually lands: PBRS requires `Phi(terminal) = 0`, so the
terminal step emits `-Phi(s_T-1)` in ONE shot, while the matching `+Phi`
increments were earned a square at a time on the way up.

PPO clamps each agent-step reward to [-1, 1]. The increments are individually
far too small to clip; the one-shot repayment is not. So a manifest whose
potential can exceed the clamp keeps part of a debt it was supposed to repay --
the telescoping property breaks in the agent's favour, on exactly the behaviour
the shaping exists to teach. Same defect class as D182 and D226.

`tools/reward_manifest.py` already bounds each piece SEPARATELY -- `25 * k_fetch
<= 1`, `25 * k_carry <= 1`, `abs(td) + abs(win) <= 1` -- and `s0_both` sits at
exactly 1.0 on two of the three. What no check covered is that they land on the
SAME agent-step: the terminal that repays the potential is also the step that
pays the TD and the win/loss bonus. This guard is that missing joint bound.

Deliberately a launch-time gate rather than a manifest-schema rule: the schema
digests are quoted as provenance by completed experiments, so tightening
`validate_manifest` would retroactively invalidate manifests that already ran.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reward_manifest import load_manifest  # noqa: E402

# The one place BB_PITCH_LEN is defined. Read rather than hardcoded so a pitch
# resize cannot silently invalidate the bound.
PITCH_LEN_HEADER = Path("engine/include/bb/bb_types.h")
_PITCH_LEN_RE = re.compile(r"^\s*#define\s+BB_PITCH_LEN\s+(\d+)\s*$", re.M)

# PPO clamps every agent-step reward to this magnitude (see the `fminf(1.0f,
# fmaxf(-1.0f, raw))` clip telemetry in puffer/bloodbowl/bloodbowl.h).
CLAMP = 1.0


def read_pitch_len(root: Path) -> int:
    """BB_PITCH_LEN as the engine defines it."""
    header = root / PITCH_LEN_HEADER
    match = _PITCH_LEN_RE.search(header.read_text())
    if match is None:
        raise ValueError(f"could not find #define BB_PITCH_LEN in {header}")
    return int(match.group(1))


def worst_case_terminal(reward: dict, pitch_len: int) -> float:
    """Largest terminal magnitude the distance channels can force.

    Both potentials are `k * (D_max - dist)` with `D_max = BB_PITCH_LEN - 1`, so
    each is maximised at distance 0. Summing them is deliberately conservative:
    the two channels are in fact mutually exclusive (fetch needs the ball
    ON_GROUND, carry needs it HELD), so this over-states the reachable payback
    and the guard errs toward refusing.
    """
    d_max = float(pitch_len - 1)
    payback = (float(reward["reward_dist_ball"])
               + float(reward["reward_dist_endzone"])) * d_max
    return payback - float(reward["reward_td"])


def check(manifest: dict, pitch_len: int) -> str | None:
    """Return a refusal message, or None when the manifest is clamp-safe."""
    reward = manifest["reward"]
    # Legacy schema-1 raw-delta shaping has different semantics and must stay
    # bit-identical; it never emits a one-shot terminal payback at all.
    gamma = float(reward.get("reward_dist_pbrs_gamma", 0.0))
    if gamma <= 0.0:
        return None

    d_max = pitch_len - 1
    k_fetch = float(reward["reward_dist_ball"])
    k_carry = float(reward["reward_dist_endzone"])
    td = float(reward["reward_td"])
    worst = worst_case_terminal(reward, pitch_len)
    if worst < CLAMP:
        return None
    return (
        "reward manifest {name!r} can breach the PPO reward clamp on its PBRS "
        "terminal payback: worst-case terminal magnitude "
        "(reward_dist_ball {k_fetch} + reward_dist_endzone {k_carry}) * "
        "(BB_PITCH_LEN-1 = {d_max}) - reward_td {td} = {worst:.6f} >= {clamp} "
        "-- the clamp would truncate the one-shot repayment of shaping the "
        "agent already banked a square at a time, so the exact-PBRS "
        "telescoping guarantee (gamma={gamma}) does not hold. Scale "
        "reward_dist_ball/reward_dist_endzone down until this is < {clamp}."
    ).format(name=manifest.get("name", "<unnamed>"), k_fetch=k_fetch,
             k_carry=k_carry, d_max=d_max, td=td, worst=worst, clamp=CLAMP,
             gamma=gamma)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", help="path to a puffer/config/rewards/*.json")
    parser.add_argument("--root", default=".",
                        help="repo root holding engine/include (default: .)")
    args = parser.parse_args()

    manifest, _digest = load_manifest(args.manifest)
    message = check(manifest, read_pitch_len(Path(args.root)))
    if message is None:
        return 0
    print(message, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
