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
    A_CHOOSE_OPTION,
    A_DECLINE_REROLL,
    A_END_TURN,
    A_PUSH_SQUARE,
    A_SPECIAL_TARGET,
    A_STEP,
    A_USE_REROLL,
    BBE_CTX_OFF,
    BBE_SCALAR_OFF,
    LAST_ACTION_STRIDE,
    RR_TEAM,
    _obs_turn_key,
    action_head_applicability,
    compute_context_features,
    make_context_spec,
)


OBS_SIZE = 832
OBS_V4_SIZE = 2782
MASK_SIZE = 454


def rec_dtype(obs_size=OBS_SIZE):
    return np.dtype([
        ("replay", "<u4"), ("cmd", "<u4"), ("agent", "u1"), ("pad", "u1", (3,)),
        ("obs", "u1", (obs_size,)), ("mask", "u1", (MASK_SIZE,)),
        ("type", "u1"), ("arg", "u1"), ("sq", "<u2"),
    ])


def obs_key(obs_size=OBS_SIZE, half=1, my_turn=1, opp_turn=1, active=1):
    obs = np.zeros(obs_size, dtype=np.uint8)
    obs[BBE_SCALAR_OFF + 0] = half
    obs[BBE_SCALAR_OFF + 1] = my_turn
    obs[BBE_SCALAR_OFF + 2] = opp_turn
    obs[BBE_CTX_OFF + 11] = active
    return obs


def records(rows, obs_size=OBS_SIZE):
    out = np.zeros(len(rows), dtype=rec_dtype(obs_size))
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


def test_obs_v4_contract_constants_and_turn_key():
    assert BBE_CTX_OFF == 32 * 24
    assert BBE_CTX_OFF == 768
    assert BBE_SCALAR_OFF == BBE_CTX_OFF + 16
    assert BBE_SCALAR_OFF == 784
    assert BBE_SCALAR_OFF + 48 == 832

    k = obs_key(OBS_V4_SIZE, half=2, my_turn=3, opp_turn=4, active=1)
    rec = records([(10, 1, 0, A_STEP, 0, 390, k)], obs_size=OBS_V4_SIZE)[0]
    assert _obs_turn_key(rec) == (2, 3, 4, 1)


def test_structural_resets_and_flags():
    k1 = obs_key(my_turn=1)
    k2 = obs_key(my_turn=2)
    recs = records([
        (100, 1, 0, A_ACTIVATE, 2, 390, k1),
        (100, 2, 0, A_STEP, 0, 10, k1),
        (100, 3, 0, A_USE_REROLL, RR_TEAM, 390, k1),
        (100, 4, 0, A_ACTIVATE, 5, 390, k1),
        (100, 5, 0, A_STEP, 0, 11, k1),
        (100, 6, 0, A_END_TURN, 0, 390, k1),
        (100, 7, 0, A_ACTIVATE, 6, 390, k2),
    ])

    feat, width, spec = compute_context_features(recs, OBS_SIZE, arm="structural")
    assert width == OBS_SIZE + 18
    flags = spec.player_flags_slice
    activations = spec.own_activations_this_turn_col

    assert feat[0, activations] == 0
    assert feat[0, flags.start + 2] == 0
    assert feat[1, activations] == 1 / 16
    assert feat[1, flags.start + 2] == 1
    assert feat[2, activations] == 1 / 16
    assert feat[2, spec.reroll_used_col] == 0
    assert feat[3, activations] == 1 / 16
    assert feat[3, spec.reroll_used_col] == 1
    assert feat[3, flags.start + 5] == 0
    assert feat[4, activations] == 2 / 16
    assert feat[4, flags.start + 5] == 1
    assert feat[5, activations] == 2 / 16
    assert feat[5, flags.start + 2] == 1
    assert feat[6, activations] == 0
    assert feat[6, spec.reroll_used_col] == 0
    assert feat[6, flags.start + 2] == 0
    assert feat[6, flags.start + 5] == 0


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

    assert feat[1, spec.own_activations_this_turn_col] == 0
    assert feat[1, spec.player_flags_slice.start + 1] == 0
    assert feat[1, spec.last_action_lag_slice(0).start] == 0


def test_action_head_applicability_sets():
    app = action_head_applicability(np.array([
        A_PUSH_SQUARE,
        A_SPECIAL_TARGET,
        A_CHOOSE_OPTION,
        A_END_TURN,
        A_DECLINE_REROLL,
    ], dtype=np.uint8))

    assert app[0].tolist() == [True, True, True]
    assert app[1].tolist() == [True, True, True]
    assert app[2].tolist() == [True, True, False]
    assert app[3].tolist() == [True, False, False]
    assert app[4].tolist() == [True, False, False]


def test_widths():
    assert make_context_spec("iid").width == 0
    assert make_context_spec("structural").width == 18
    assert make_context_spec("last_action_only").width == 99
    assert make_context_spec("structural_last_action").width == 117


def main():
    tests = [
        test_obs_v4_contract_constants_and_turn_key,
        test_structural_resets_and_flags,
        test_last_action_boundaries_and_order,
        test_turn_key_change_clears_turnover_leakage,
        test_action_head_applicability_sets,
        test_widths,
    ]
    for test in tests:
        test()
        print(f"{test.__name__}: OK")
    print(f"\nALL {len(tests)} TESTS PASSED")


if __name__ == "__main__":
    main()
