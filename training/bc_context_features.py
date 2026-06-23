#!/usr/bin/env python
"""Load-time temporal context features for BC pair records.

Path A only: features are derived from the already-extracted .bbp action
stream sorted by (replay, agent, cmd), then appended to the policy input by
the BC trainer. The engine observation is not changed here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence, Tuple, Union

import numpy as np


# bb_actions.h mirrors. Keep local so this module has no C/Puffer dependency.
A_SETUP_PLACE = 1
A_SETUP_REMOVE = 2
A_SETUP_DONE = 3
A_KICK_TARGET = 4
A_TOUCHBACK = 5
A_ACTIVATE = 6
A_DECLARE = 7
A_END_TURN = 8
A_STEP = 9
A_STAND_UP = 10
A_JUMP = 11
A_BLOCK_TARGET = 12
A_PASS_TARGET = 13
A_HANDOFF_TARGET = 14
A_FOUL_TARGET = 15
A_TTM_TARGET = 16
A_SECURE_BALL = 17
A_PICKUP_DECLINE = 18
A_END_ACTIVATION = 19
A_CHOOSE_DIE = 20
A_PUSH_SQUARE = 21
A_FOLLOW_UP = 22
A_USE_REROLL = 23
A_DECLINE_REROLL = 24
A_USE_SKILL = 25
A_DECLINE_SKILL = 26
A_APOTHECARY = 27
A_CHOOSE_OPTION = 28
A_SPECIAL_TARGET = 29

RR_TEAM = 0

ACT_SIZES = (30, 33, 391)
ARG_SENTINEL = 32
SQ_SENTINEL = 390

OWN_TEAM_SLOTS = 16
OWN_ACTIVATIONS_DENOM = OWN_TEAM_SLOTS
LAST_ACTION_DEPTH = 3
LAST_ACTION_STRIDE = 1 + ACT_SIZES[0] + 1 + 1  # present, type one-hot, arg, sq

# Obs layout offsets that are stable across obs-v3/v4.
BBE_CTX_OFF = 32 * 24
BBE_SCALAR_OFF = BBE_CTX_OFF + 16

SPATIAL_ACTION_TYPES = frozenset({
    A_SETUP_PLACE,
    A_KICK_TARGET,
    A_STEP,
    A_JUMP,
    A_BLOCK_TARGET,
    A_PASS_TARGET,
    A_HANDOFF_TARGET,
    A_FOUL_TARGET,
    A_TTM_TARGET,
    A_PUSH_SQUARE,
    A_SPECIAL_TARGET,
})

ARG_ACTION_TYPES = frozenset({
    A_SETUP_PLACE,
    A_SETUP_REMOVE,
    A_TOUCHBACK,
    A_ACTIVATE,
    A_DECLARE,
    A_PUSH_SQUARE,
    A_CHOOSE_DIE,
    A_FOLLOW_UP,
    A_USE_REROLL,
    A_USE_SKILL,
    A_DECLINE_SKILL,
    A_APOTHECARY,
    A_CHOOSE_OPTION,
    A_SPECIAL_TARGET,
})


@dataclass(frozen=True)
class ContextFeatureSpec:
    """Feature layout description for an arm."""

    arm: str
    include_structural: bool
    include_last_action: bool
    own_team_slots: int = OWN_TEAM_SLOTS
    last_action_depth: int = LAST_ACTION_DEPTH

    @property
    def structural_width(self) -> int:
        return 2 + self.own_team_slots if self.include_structural else 0

    @property
    def last_action_width(self) -> int:
        if not self.include_last_action:
            return 0
        return self.last_action_depth * LAST_ACTION_STRIDE

    @property
    def width(self) -> int:
        return self.structural_width + self.last_action_width

    @property
    def own_activations_this_turn_col(self) -> Optional[int]:
        return 0 if self.include_structural else None

    @property
    def reroll_used_col(self) -> Optional[int]:
        return 1 if self.include_structural else None

    @property
    def player_flags_slice(self) -> slice:
        if not self.include_structural:
            return slice(0, 0)
        return slice(2, 2 + self.own_team_slots)

    @property
    def last_action_slice(self) -> slice:
        if not self.include_last_action:
            return slice(self.structural_width, self.structural_width)
        start = self.structural_width
        return slice(start, start + self.last_action_width)

    def last_action_lag_slice(self, lag: int) -> slice:
        """Return the slice for lag 0/1/2, where lag 0 is previous action."""
        if not self.include_last_action:
            return slice(self.structural_width, self.structural_width)
        if lag < 0 or lag >= self.last_action_depth:
            raise IndexError(lag)
        start = self.last_action_slice.start + lag * LAST_ACTION_STRIDE
        return slice(start, start + LAST_ACTION_STRIDE)

    def summary(self) -> str:
        parts = []
        if self.include_structural:
            parts.append(f"structural={self.structural_width}")
        if self.include_last_action:
            parts.append(f"last_action={self.last_action_width}")
        if not parts:
            parts.append("none")
        return ", ".join(parts)


ARM_ALIASES = {
    "iid": "iid",
    "none": "iid",
    "baseline": "iid",
    "structural": "structural",
    "struct": "structural",
    "structural-only": "structural",
    "structural_only": "structural",
    "structural+last-action": "structural_last_action",
    "structural+last_action": "structural_last_action",
    "structural-last-action": "structural_last_action",
    "structural_last_action": "structural_last_action",
    "all": "structural_last_action",
    "last-action-only": "last_action_only",
    "last_action_only": "last_action_only",
    "last-action": "last_action_only",
    "last_action": "last_action_only",
}


def make_context_spec(
    arm: str = "iid",
    features: Optional[Union[str, Sequence[str]]] = None,
    own_team_slots: int = OWN_TEAM_SLOTS,
    last_action_depth: int = LAST_ACTION_DEPTH,
) -> ContextFeatureSpec:
    """Resolve an A/B arm or explicit feature list into a layout spec."""

    if features is not None:
        toks = _feature_tokens(features)
        include_structural = "structural" in toks
        include_last_action = "last_action" in toks
        if not include_structural and not include_last_action:
            canon = "iid"
        elif include_structural and not include_last_action:
            canon = "structural"
        elif include_structural and include_last_action:
            canon = "structural_last_action"
        else:
            canon = "last_action_only"
    else:
        canon = ARM_ALIASES.get(arm)
        if canon is None:
            known = ", ".join(sorted(ARM_ALIASES))
            raise ValueError(f"unknown context arm {arm!r}; known: {known}")
        include_structural = canon in ("structural", "structural_last_action")
        include_last_action = canon in ("structural_last_action", "last_action_only")

    return ContextFeatureSpec(
        arm=canon,
        include_structural=include_structural,
        include_last_action=include_last_action,
        own_team_slots=own_team_slots,
        last_action_depth=last_action_depth,
    )


def _feature_tokens(features: Union[str, Sequence[str]]) -> set[str]:
    if isinstance(features, str):
        raw: Iterable[str] = features.replace("+", ",").split(",")
    else:
        raw = features
    toks = set()
    for tok in raw:
        t = tok.strip().lower().replace("-", "_")
        if not t or t in ("none", "iid", "baseline"):
            continue
        if t in ("struct", "structural", "structural_only"):
            toks.add("structural")
        elif t in ("last", "last_action", "last_actions", "last_action_only"):
            toks.add("last_action")
        else:
            raise ValueError(f"unknown context feature token {tok!r}")
    return toks


def infer_obs_size(records: np.ndarray) -> Optional[int]:
    if records.dtype.names and "obs" in records.dtype.names:
        return int(records.dtype["obs"].shape[0])
    return None


def compute_context_features(
    records: np.ndarray,
    obs_size: Optional[int] = None,
    arm: str = "iid",
    features: Optional[Union[str, Sequence[str]]] = None,
    own_team_slots: int = OWN_TEAM_SLOTS,
    last_action_depth: int = LAST_ACTION_DEPTH,
) -> Tuple[np.ndarray, Optional[int], ContextFeatureSpec]:
    """Compute Path-A context features aligned to the input record order.

    The stream state is updated after each record because the stored obs is the
    decision state before the action target. END_TURN and obs clock changes
    reset the stream so context does not leak across turns, agents, or replays.
    """

    spec = make_context_spec(
        arm=arm,
        features=features,
        own_team_slots=own_team_slots,
        last_action_depth=last_action_depth,
    )
    if obs_size is None:
        obs_size = infer_obs_size(records)

    n = len(records)
    out = np.zeros((n, spec.width), dtype=np.float32)
    if n == 0 or spec.width == 0:
        return out, (None if obs_size is None else obs_size + spec.width), spec

    required = {"replay", "agent", "cmd", "type", "arg", "sq"}
    names = set(records.dtype.names or ())
    missing = sorted(required - names)
    if missing:
        raise ValueError(f"records missing required fields: {missing}")

    order = np.lexsort((
        np.arange(n, dtype=np.int64),
        records["cmd"].astype(np.uint64),
        records["agent"].astype(np.uint64),
        records["replay"].astype(np.uint64),
    ))

    stream_key = None
    turn_key = None
    own_activations_this_turn = 0
    reroll_used = 0.0
    activated = np.zeros(spec.own_team_slots, dtype=np.float32)
    last_actions: list[tuple[int, int, int]] = []

    def reset_state() -> None:
        nonlocal own_activations_this_turn, reroll_used, activated, last_actions
        own_activations_this_turn = 0
        reroll_used = 0.0
        activated = np.zeros(spec.own_team_slots, dtype=np.float32)
        last_actions = []

    for row in order:
        rec = records[row]
        next_stream_key = (int(rec["replay"]), int(rec["agent"]))
        if next_stream_key != stream_key:
            stream_key = next_stream_key
            turn_key = None
            reset_state()

        next_turn_key = _obs_turn_key(rec)
        if next_turn_key is not None:
            if turn_key is None:
                turn_key = next_turn_key
            elif next_turn_key != turn_key:
                turn_key = next_turn_key
                reset_state()

        if spec.include_structural:
            out[row, spec.own_activations_this_turn_col] = _clip01(
                own_activations_this_turn, OWN_ACTIVATIONS_DENOM)
            out[row, spec.reroll_used_col] = reroll_used
            out[row, spec.player_flags_slice] = activated

        if spec.include_last_action:
            _write_last_actions(out[row], spec, last_actions)

        typ = int(rec["type"])
        arg = int(rec["arg"])
        sq = int(rec["sq"])

        if typ == A_END_TURN:
            turn_key = None
            reset_state()
            continue

        if typ == A_USE_REROLL and arg == RR_TEAM:
            reroll_used = 1.0
        if typ == A_ACTIVATE:
            if 0 <= arg < spec.own_team_slots:
                activated[arg] = 1.0
            own_activations_this_turn += 1

        if spec.include_last_action:
            last_actions.insert(0, (typ, arg, sq))
            del last_actions[spec.last_action_depth:]

    return out, (None if obs_size is None else obs_size + spec.width), spec


def _obs_turn_key(rec: np.void) -> Optional[tuple[int, int, int, int]]:
    if "obs" not in (rec.dtype.names or ()):
        return None
    obs = rec["obs"]
    if obs.shape[0] <= BBE_SCALAR_OFF + 2 or obs.shape[0] <= BBE_CTX_OFF + 11:
        return None
    return (
        int(obs[BBE_SCALAR_OFF + 0]),  # half
        int(obs[BBE_SCALAR_OFF + 1]),  # my turn
        int(obs[BBE_SCALAR_OFF + 2]),  # opponent turn
        int(obs[BBE_CTX_OFF + 11]),    # my team is active
    )


def _write_last_actions(
    row: np.ndarray,
    spec: ContextFeatureSpec,
    last_actions: Sequence[tuple[int, int, int]],
) -> None:
    for lag, (typ, arg, sq) in enumerate(last_actions[:spec.last_action_depth]):
        sl = spec.last_action_lag_slice(lag)
        off = sl.start
        row[off] = 1.0
        if 0 <= typ < ACT_SIZES[0]:
            row[off + 1 + typ] = 1.0
        row[off + 1 + ACT_SIZES[0]] = _clip01(arg, ARG_SENTINEL)
        row[off + 1 + ACT_SIZES[0] + 1] = _clip01(sq, SQ_SENTINEL)


def _clip01(value: int, denom: int) -> float:
    return float(min(max(int(value), 0), denom)) / float(denom)


def action_head_applicability(records_or_types: np.ndarray) -> np.ndarray:
    """Return bool [N,3] applicability for type/arg/square CE and metrics."""

    if isinstance(records_or_types, np.ndarray) and records_or_types.dtype.names:
        types = records_or_types["type"]
    else:
        types = records_or_types
    types = np.asarray(types, dtype=np.uint8)
    app = np.zeros((types.shape[0], 3), dtype=np.bool_)
    app[:, 0] = True
    app[:, 1] = np.isin(types, tuple(ARG_ACTION_TYPES))
    app[:, 2] = np.isin(types, tuple(SPATIAL_ACTION_TYPES))
    return app


def feature_names(spec: ContextFeatureSpec) -> list[str]:
    names: list[str] = []
    if spec.include_structural:
        names.extend(["own_activations_this_turn", "team_reroll_used"])
        names.extend(f"own_player_{i}_activated" for i in range(spec.own_team_slots))
    if spec.include_last_action:
        for lag in range(spec.last_action_depth):
            prefix = f"last{lag + 1}"
            names.append(f"{prefix}_present")
            names.extend(f"{prefix}_type_{i}" for i in range(ACT_SIZES[0]))
            names.append(f"{prefix}_arg_norm")
            names.append(f"{prefix}_sq_norm")
    assert len(names) == spec.width, (len(names), spec.width)
    return names
