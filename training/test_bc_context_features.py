#!/usr/bin/env python
"""Local tests for Path-A BC context feature computation.

Run:
  python3 training/test_bc_context_features.py
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bc_context_features import (  # noqa: E402
    A_ACTIVATE,
    A_END_TURN,
    A_STEP,
    A_USE_REROLL,
    BBE_CTX_OFF,
    BBE_SCALAR_OFF,
    LAST_ACTION_STRIDE,
    RR_TEAM,
    compute_context_features,
    make_context_spec,
)


OBS_SIZE = 832
MASK_SIZE = 454


def rec_dtype():
    return np.dtype([
        ("replay", "<u4"), ("cmd", "<u4"), ("agent", "u1"), ("pad", "u1", (3,)),
        ("obs", "u1", (OBS_SIZE,)), ("mask", "u1", (MASK_SIZE,)),
        ("type", "u1"), ("arg", "u1"), ("sq", "<u2"),
    ])


def obs_key(half=1, my_turn=1, opp_turn=1, active=1):
    obs = np.zeros(OBS_SIZE, dtype=np.uint8)
    obs[BBE_SCALAR_OFF + 0] = half
    obs[BBE_SCALAR_OFF + 1] = my_turn
    obs[BBE_SCALAR_OFF + 2] = opp_turn
    obs[BBE_CTX_OFF + 11] = active
    return obs


def records(rows):
    out = np.zeros(len(rows), dtype=rec_dtype())
    for i, row in enumerate(rows):
        replay, cmd, agent, typ, arg, sq, key = row
        out[i]["replay"] = replay
        out[i]["cmd"] = cmd
        out[i]["agent"] = agent
        out[i]["obs"] = key
        out[i]["type"] = typ
        out[i]["arg"] = arg
        out[i]["sq"] = sq
    return out


def test_structural_resets_and_flags():
    k1 = obs_key(my_turn=1)
    k2 = obs_key(my_turn=2)
    recs = records([
        (100, 1, 0, A_ACTIVATE, 2, 390, k1),
        (100, 2, 0, A_STEP, 0, 10, k1),
        (100, 3, 0, A_USE_REROLL, RR_TEAM, 390, k1),
        (100, 4, 0, A_STEP, 0, 11, k1),
        (100, 5, 0, A_END_TURN, 0, 390, k1),
        (100, 6, 0, A_ACTIVATE, 5, 390, k2),
    ])

    feat, width, spec = compute_context_features(recs, OBS_SIZE, arm="structural")
    assert width == OBS_SIZE + 18
    flags = spec.player_flags_slice

    assert feat[0, spec.activation_index_col] == 0
    assert feat[0, flags.start + 2] == 0
    assert feat[1, spec.activation_index_col] == 1
    assert feat[1, flags.start + 2] == 1
    assert feat[2, spec.activation_index_col] == 2
    assert feat[2, spec.reroll_used_col] == 0
    assert feat[3, spec.activation_index_col] == 3
    assert feat[3, spec.reroll_used_col] == 1
    assert feat[4, flags.start + 2] == 1
    assert feat[5, spec.activation_index_col] == 0
    assert feat[5, spec.reroll_used_col] == 0
    assert feat[5, flags.start + 2] == 0
    assert feat[5, flags.start + 5] == 0


def test_last_action_boundaries_and_order():
    k = obs_key(my_turn=1)
    recs = records([
        # Deliberately unsorted input: output rows must align to original order.
        (200, 2, 0, A_STEP, 0, 12, k),
        (201, 1, 0, A_STEP, 0, 13, k),
        (200, 1, 0, A_ACTIVATE, 3, 390, k),
        (200, 1, 1, A_STEP, 0, 14, k),
    ])

    feat, width, spec = compute_context_features(recs, OBS_SIZE, arm="last_action_only")
    assert width == OBS_SIZE + 3 * LAST_ACTION_STRIDE

    prev = spec.last_action_lag_slice(0)
    present = prev.start
    type_start = prev.start + 1
    arg_col = prev.start + 1 + 30
    sq_col = arg_col + 1

    # row 0 follows row 2 in sorted (replay, agent, cmd) order.
    assert feat[0, present] == 1
    assert feat[0, type_start + A_ACTIVATE] == 1
    assert feat[0, arg_col] == 3 / 32
    assert feat[0, sq_col] == 1.0

    # Different replay and different agent must not inherit row 2.
    assert feat[1, present] == 0
    assert feat[3, present] == 0


def test_turn_key_change_clears_turnover_leakage():
    k1 = obs_key(my_turn=1)
    k2 = obs_key(my_turn=2)
    recs = records([
        (300, 1, 0, A_ACTIVATE, 1, 390, k1),
        # No explicit END_TURN: a turnover/drive boundary is visible in obs.
        (300, 2, 0, A_STEP, 0, 15, k2),
    ])
    feat, _width, spec = compute_context_features(
        recs, OBS_SIZE, arm="structural_last_action")

    assert feat[1, spec.activation_index_col] == 0
    assert feat[1, spec.player_flags_slice.start + 1] == 0
    assert feat[1, spec.last_action_lag_slice(0).start] == 0


def test_widths():
    assert make_context_spec("iid").width == 0
    assert make_context_spec("structural").width == 18
    assert make_context_spec("last_action_only").width == 99
    assert make_context_spec("structural_last_action").width == 117


def main():
    tests = [
        test_structural_resets_and_flags,
        test_last_action_boundaries_and_order,
        test_turn_key_change_clears_turnover_leakage,
        test_widths,
    ]
    for test in tests:
        test()
        print(f"{test.__name__}: OK")
    print(f"\nALL {len(tests)} TESTS PASSED")


if __name__ == "__main__":
    main()
