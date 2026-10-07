"""ctypes wrapper over the bbplay engine shim.

The shim compiles puffer/bloodbowl/bloodbowl.h as one translation unit, so
observations, masks, exact joint projection and c_step are the training env
itself. This module adds no rules: it reads state and forwards tuples.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_SCRIPT = os.path.join(ROOT, "play_harness", "native", "build.sh")
LIB_EXT = "dylib" if sys.platform == "darwin" else "so"
DEFAULT_LIB = os.path.join(ROOT, "build", "play_harness", f"libbbplay.{LIB_EXT}")

ABI_VERSION = 5
OBS_SIZE = 2782
OBS_VERSION = 6
MASK_SIZE = 454
ACT_SIZES = (30, 33, 391)
PITCH_LEN = 26
PITCH_WID = 15
NUM_PLAYERS = 32
ARG_NONE = 32
SQ_NONE = 390

STEP_OK = 0
STEP_TERMINAL = 1
STEP_REJECTED = -1
STEP_NO_DECISION = -2
STEP_COLLISION = -3
STEP_OVER = -4
STEP_NOT_BOT_TURN = -5
STEP_BAD_BOT = -6

# The dice stream id of every real session (c_reset in bloodbowl.h). A search
# clone is refused it.
REAL_DICE_STREAM = 1
CLONE_REFUSALS = {
    -1: "bad arguments (the target must be a clone other than the source)",
    -2: "the stream id is the real dice stream's",
    -3: "the source session already reached a terminal step",
}

# The env's scripted_opponent_type values (puffer/config/bloodbowl.ini) and the
# engine pick function each one dispatches to in c_step.
BOT_TYPES = {"contact": 0, "offense": 1}
BOT_PICK_FUNCTIONS = {"contact": "bbe_contact_bot_pick", "offense": "bbe_offense_bot_pick"}

STATUS_RUNNING = 0
STATUS_DECISION = 1
STATUS_MATCH_OVER = 2
STATUS_ERROR = 3

# bb_action_type (engine/include/bb/bb_actions.h)
ACTION_TYPES = [
    "NONE", "SETUP_PLACE", "SETUP_REMOVE", "SETUP_DONE", "KICK_TARGET",
    "TOUCHBACK", "ACTIVATE", "DECLARE", "END_TURN", "STEP", "STAND_UP", "JUMP",
    "BLOCK_TARGET", "PASS_TARGET", "HANDOFF_TARGET", "FOUL_TARGET",
    "TTM_TARGET", "SECURE_BALL", "PICKUP_DECLINE", "END_ACTIVATION",
    "CHOOSE_DIE", "PUSH_SQUARE", "FOLLOW_UP", "USE_REROLL", "DECLINE_REROLL",
    "USE_SKILL", "DECLINE_SKILL", "APOTHECARY", "CHOOSE_OPTION",
    "SPECIAL_TARGET",
]
A = {name: i for i, name in enumerate(ACTION_TYPES)}

# bb_act_kind (bb_actions.h)
ACT_KINDS = [
    "MOVE", "BLOCK", "BLITZ", "PASS", "HANDOFF", "FOUL", "TTM", "SECURE_BALL",
    "STAB", "GAZE", "KTM", "CHAINSAW", "BREATHE_FIRE", "VOMIT",
]
REROLL_SOURCES = ["TEAM", "SKILL", "PRO", "LEADER"]

# bb_proc (bb_match.h)
PROCS = [
    "NONE", "MATCH", "PREGAME", "SETUP", "KICKOFF", "TEAM_TURN", "ACTIVATION",
    "MOVE", "DODGE", "RUSH", "PICKUP", "BLOCK", "PUSH", "KNOCKDOWN", "ARMOUR",
    "INJURY", "CASUALTY", "PASS", "CATCH", "SCATTER", "THROW_IN", "HANDOFF",
    "FOUL", "TTM", "TEST", "TOUCHDOWN", "TURNOVER", "END_DRIVE", "KO_RECOVERY",
]
LOCATIONS = ["on_pitch", "reserves", "ko", "cas", "sent_off", "absent"]
STANCES = ["standing", "prone", "stunned", "stunned_used"]
BALL_STATES = ["off_pitch", "on_ground", "held", "in_air"]
WEATHER = ["sweltering", "sunny", "perfect", "rain", "blizzard"]
PLAYER_FLAGS = [
    "used", "activating", "distracted", "has_ball", "blitzed", "rooted",
    "hypnotized", "used_skill_a", "used_skill_b", "secured_ball", "no_tz",
    "eye_gouged",
]


class BbSkillset(ctypes.Structure):
    _fields_ = [("w", ctypes.c_uint64 * 3)]


class BbPlayer(ctypes.Structure):
    _fields_ = [
        ("skills", BbSkillset),
        ("ma", ctypes.c_int8), ("st", ctypes.c_int8), ("ag", ctypes.c_int8),
        ("pa", ctypes.c_int8), ("av", ctypes.c_int8),
        ("x", ctypes.c_uint8), ("y", ctypes.c_uint8),
        ("location", ctypes.c_uint8), ("stance", ctypes.c_uint8),
        ("flags", ctypes.c_uint16),
        ("moved", ctypes.c_uint8), ("rushes", ctypes.c_uint8),
        ("position_id", ctypes.c_uint8), ("star_id", ctypes.c_uint8),
        ("niggling", ctypes.c_int8), ("spp_game", ctypes.c_uint8),
        ("skill_rr_used", ctypes.c_uint16),
        ("p_loner", ctypes.c_int8), ("p_bloodlust", ctypes.c_int8),
    ]


class BbBall(ctypes.Structure):
    _fields_ = [("state", ctypes.c_uint8), ("x", ctypes.c_uint8),
                ("y", ctypes.c_uint8), ("carrier", ctypes.c_uint8)]


class BbFrame(ctypes.Structure):
    _fields_ = [
        ("proc", ctypes.c_uint8), ("phase", ctypes.c_uint8),
        ("a", ctypes.c_uint8), ("b", ctypes.c_uint8),
        ("x", ctypes.c_uint8), ("y", ctypes.c_uint8),
        ("data", ctypes.c_uint16),
    ]


U8x2 = ctypes.c_uint8 * 2


class BbMatch(ctypes.Structure):
    _fields_ = [
        ("players", BbPlayer * NUM_PLAYERS),
        ("grid", (ctypes.c_uint8 * PITCH_WID) * PITCH_LEN),
        ("ball", BbBall),
        ("half", ctypes.c_uint8),
        ("turn", U8x2), ("score", U8x2),
        ("active_team", ctypes.c_uint8), ("kicking_team", ctypes.c_uint8),
        ("weather", ctypes.c_uint8),
        ("rerolls", U8x2), ("rerolls_start", U8x2), ("bonus_rerolls", U8x2),
        ("blitz_used", ctypes.c_uint8), ("pass_used", ctypes.c_uint8),
        ("handoff_used", ctypes.c_uint8), ("foul_used", ctypes.c_uint8),
        ("ttm_used", ctypes.c_uint8), ("ktm_used", ctypes.c_uint8),
        ("secure_used", ctypes.c_uint8),
        ("bribes", U8x2), ("fan_factor", U8x2), ("cheer_assist", U8x2),
        ("surfs", U8x2), ("apothecary", U8x2), ("coach_ejected", U8x2),
        ("stack", BbFrame * 32),
        ("stack_top", ctypes.c_uint8), ("status", ctypes.c_uint8),
        ("decision_team", ctypes.c_uint8), ("turnover", ctypes.c_uint8),
        ("ret", ctypes.c_uint16),
        ("step_count", ctypes.c_uint32),
        ("team_id", U8x2),
        ("turns_completed", U8x2), ("turns_completed_held", U8x2),
        ("turnovers_completed", U8x2),
    ]


def _expected_layout():
    return [
        ctypes.sizeof(BbMatch), ctypes.sizeof(BbPlayer), ctypes.sizeof(BbFrame),
        BbMatch.grid.offset, BbMatch.ball.offset, BbMatch.half.offset,
        BbMatch.stack.offset, BbMatch.stack_top.offset, BbMatch.status.offset,
        BbMatch.decision_team.offset, BbMatch.step_count.offset,
        BbMatch.team_id.offset, BbMatch.turnovers_completed.offset,
        BbPlayer.ma.offset, BbPlayer.x.offset, BbPlayer.flags.offset,
        BbPlayer.position_id.offset, BbPlayer.p_bloodlust.offset,
    ]


def build_library(out_path=DEFAULT_LIB):
    subprocess.run(["bash", BUILD_SCRIPT], check=True, capture_output=True,
                   env={**os.environ,
                        "BBPLAY_BUILD_DIR": os.path.dirname(out_path)})
    return out_path


_LIB = None


def library_is_stale(path=DEFAULT_LIB):
    """True when the shim library is missing or older than its sources."""
    if not os.path.exists(path):
        return True
    built = os.path.getmtime(path)
    sources = [os.path.join(ROOT, "play_harness", "native", "bbplay.c"), BUILD_SCRIPT]
    return any(os.path.getmtime(src) > built for src in sources if os.path.exists(src))


def load_library(path=None, build_if_missing=True):
    global _LIB
    if _LIB is not None and path is None:
        return _LIB
    path = path or os.environ.get("BBPLAY_LIB", DEFAULT_LIB)
    if library_is_stale(path):
        if not build_if_missing:
            raise FileNotFoundError(path)
        build_library(path)
    lib = ctypes.CDLL(path)
    c_p = ctypes.c_void_p
    sig = {
        "bbp_abi_version": ([], ctypes.c_int),
        "bbp_obs_size": ([], ctypes.c_int),
        "bbp_obs_version": ([], ctypes.c_int),
        "bbp_mask_size": ([], ctypes.c_int),
        "bbp_legal_max": ([], ctypes.c_int),
        "bbp_team_count": ([], ctypes.c_int),
        "bbp_skill_count": ([], ctypes.c_int),
        "bbp_layout": ([ctypes.POINTER(ctypes.c_int32), ctypes.c_int], ctypes.c_int),
        "bbp_create": ([ctypes.c_uint64, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                        ctypes.c_int, ctypes.c_int, ctypes.c_float, ctypes.c_int], c_p),
        "bbp_reward_field_count": ([], ctypes.c_int),
        "bbp_reward_field_name": ([ctypes.c_int], ctypes.c_char_p),
        "bbp_reward_table_error": ([ctypes.POINTER(ctypes.c_float), ctypes.c_int],
                                   ctypes.c_int),
        "bbp_create_rewards": ([ctypes.c_uint64, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_float, ctypes.c_int,
                                ctypes.POINTER(ctypes.c_float), ctypes.c_int], c_p),
        "bbp_reward_table": ([c_p, ctypes.POINTER(ctypes.c_float), ctypes.c_int],
                             ctypes.c_int),
        "bbp_destroy": ([c_p], None),
        "bbp_clone_refusal": ([c_p, ctypes.c_uint64], ctypes.c_int),
        "bbp_clone_for_search": ([c_p, ctypes.c_uint64, ctypes.c_uint64], c_p),
        "bbp_copy_into": ([c_p, c_p, ctypes.c_uint64, ctypes.c_uint64], ctypes.c_int),
        "bbp_free_clone": ([c_p], None),
        "bbp_test_copy_dice": ([c_p, c_p], None),
        "bbp_test_stall_attached": ([c_p], ctypes.c_int),
        "bbp_obs": ([c_p, ctypes.c_int], ctypes.POINTER(ctypes.c_uint8)),
        "bbp_mask": ([c_p, ctypes.c_int], ctypes.POINTER(ctypes.c_uint8)),
        "bbp_match": ([c_p], ctypes.POINTER(BbMatch)),
        "bbp_final_match": ([c_p], ctypes.POINTER(BbMatch)),
        "bbp_status": ([c_p], ctypes.c_int),
        "bbp_decision_team": ([c_p], ctypes.c_int),
        "bbp_n_legal": ([c_p], ctypes.c_int),
        "bbp_legal": ([c_p, ctypes.POINTER(ctypes.c_uint8),
                       ctypes.POINTER(ctypes.c_uint16), ctypes.c_int], ctypes.c_int),
        "bbp_joint_support": ([c_p, ctypes.c_int, ctypes.POINTER(ctypes.c_uint32),
                               ctypes.c_int], ctypes.c_int),
        "bbp_tuple_index": ([c_p, ctypes.c_int, ctypes.c_int, ctypes.c_int], ctypes.c_int),
        "bbp_step": ([c_p, ctypes.c_int, ctypes.c_int, ctypes.c_int], ctypes.c_int),
        "bbp_peek_legal": ([c_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                            ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_uint16),
                            ctypes.c_int], ctypes.c_int),
        "bbp_counters": ([c_p, ctypes.POINTER(ctypes.c_int32), ctypes.c_int], ctypes.c_int),
        "bbp_last_action": ([c_p, ctypes.POINTER(ctypes.c_uint8)], ctypes.c_int),
        "bbp_last_rewards": ([c_p, ctypes.POINTER(ctypes.c_float)], None),
        "bbp_state_digest": ([c_p], ctypes.c_uint64),
        "bbp_env_digest": ([c_p], ctypes.c_uint64),
        "bbp_session_bytes": ([], ctypes.c_int),
        "bbp_contact_bot_index": ([c_p], ctypes.c_int),
        "bbp_scripted_bot_index": ([c_p, ctypes.c_int], ctypes.c_int),
        "bbp_step_scripted": ([c_p, ctypes.c_int, ctypes.c_int], ctypes.c_int),
        "bbp_step_success": ([c_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.POINTER(ctypes.c_int32),
                              ctypes.POINTER(ctypes.c_float)], None),
        "bbp_reach": ([c_p, ctypes.c_int, ctypes.POINTER(ctypes.c_uint8),
                       ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_uint8),
                       ctypes.POINTER(ctypes.c_int8)], None),
        "bbp_block_ev": ([c_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                          ctypes.POINTER(ctypes.c_float)], None),
        "bbp_path_odds": ([c_p, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int8),
                           ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int32),
                           ctypes.POINTER(ctypes.c_float)], ctypes.c_int),
        "bbp_stall_counts": ([c_p, ctypes.POINTER(ctypes.c_int32)], ctypes.c_int),
        "bbp_can_score_without_dice": ([c_p, ctypes.c_int], ctypes.c_int),
        "bbp_count_assists": ([c_p, ctypes.c_int, ctypes.c_int], ctypes.c_int),
        "bbp_tackle_zones": ([c_p, ctypes.c_int, ctypes.c_int, ctypes.c_int], ctypes.c_int),
        "bbp_team_display": ([ctypes.c_int], ctypes.c_char_p),
        "bbp_team_key": ([ctypes.c_int], ctypes.c_char_p),
        "bbp_position_display": ([ctypes.c_int, ctypes.c_int], ctypes.c_char_p),
        "bbp_skill_display": ([ctypes.c_int], ctypes.c_char_p),
        "bbp_skill_key": ([ctypes.c_int], ctypes.c_char_p),
    }
    for name, (argtypes, restype) in sig.items():
        fn = getattr(lib, name)
        fn.argtypes = argtypes
        fn.restype = restype
    if lib.bbp_abi_version() != ABI_VERSION:
        raise RuntimeError("bbplay ABI version mismatch; rebuild the shim")
    if (lib.bbp_obs_size(), lib.bbp_obs_version(), lib.bbp_mask_size()) != \
            (OBS_SIZE, OBS_VERSION, MASK_SIZE):
        raise RuntimeError("bbplay shim is not obs-v6 / 454-bit masks")
    buf = (ctypes.c_int32 * 32)()
    n = lib.bbp_layout(buf, 32)
    got = list(buf[:n])
    if got != _expected_layout():
        raise RuntimeError(f"bb_match layout mismatch: C {got} vs ctypes "
                           f"{_expected_layout()}")
    if path == DEFAULT_LIB or _LIB is None:
        _LIB = lib
    return lib


@dataclass(frozen=True)
class LegalAction:
    index: int
    type: int
    arg: int
    x: int
    y: int
    proj_arg: int
    proj_sq: int

    @property
    def type_name(self):
        return ACTION_TYPES[self.type]

    @property
    def tuple(self):
        return (self.type, self.proj_arg, self.proj_sq)


def pack_tuple(t, arg, sq):
    return int(t) | (int(arg) << 10) | (int(sq) << 20)


def unpack_tuple(packed):
    packed = int(packed)
    return packed & 1023, (packed >> 10) & 1023, (packed >> 20) & 1023


# The shim's reasons for refusing a reward table (bbp_reward_table_error).
REWARD_TABLE_ERRORS = {
    -1: "wrong number of coefficients",
    1: "a coefficient is not finite or lies outside [-1, 1]",
    2: "reward_carrier_threat cannot be combined with reward_carrier_exposure",
    3: "reward_carrier_threat cannot be combined with reward_k_assist",
    4: "exact-PBRS distance coefficients must be >= 0",
    5: "the reward envelope exceeds the trainer clamp",
    6: "reward_dist_pbrs_gamma must lie in [0, 1]",
    7: "an int coefficient (a flag) is not exactly 0 or 1",
}
# Coefficients a schema-1 manifest must omit. Schema 1 means their legacy value
# (tools/reward_manifest.py SCHEMA2_ONLY_FLOAT_KEYS), which is 0.
SCHEMA1_ABSENT_REWARDS = ("reward_dist_pbrs_gamma",)
REWARD_INT_FIELDS = ("reward_injury_value_scaled",)


def reward_fields(lib=None):
    """The shim's reward coefficient names, in the order of its table."""
    lib = lib or load_library()
    return [lib.bbp_reward_field_name(i).decode()
            for i in range(lib.bbp_reward_field_count())]


def reward_table(rewards, lib=None):
    """A complete {name: value} reward mapping as the shim's float table.

    Every coefficient must be named: one left out is not the same as zero.
    """
    lib = lib or load_library()
    names = reward_fields(lib)
    missing = sorted(set(names) - set(rewards))
    unknown = sorted(set(rewards) - set(names))
    if missing or unknown:
        raise ValueError(f"reward table: missing {missing}, unknown {unknown}")
    table = (ctypes.c_float * len(names))(*[float(rewards[n]) for n in names])
    err = lib.bbp_reward_table_error(table, len(names))
    if err:
        raise ValueError(f"reward table refused: {REWARD_TABLE_ERRORS.get(err, err)}")
    return table


def load_reward_manifest(path, lib=None):
    """A reward manifest (puffer/config/rewards/*.json) as an Engine reward table.

    Returns {"name", "sha256", "file_sha256", "rewards"}. sha256 is the digest
    of the canonical manifest, the one tools/reward_manifest.py prints and the
    ledger quotes; file_sha256 is the digest of the file's bytes. The canonical
    form is repeated here because tools/ is not shipped to tournament droplets;
    test_reward_independence.py holds the two to the same digest.
    """
    with open(path, "rb") as f:
        raw = f.read()
    manifest = json.loads(raw)
    reward = manifest.get("reward")
    if manifest.get("schema_version") not in (1, 2) or not isinstance(reward, dict):
        raise ValueError(f"{path}: not a schema 1 or 2 reward manifest")
    # Normalised as tools/reward_manifest.py normalises before it hashes. A flag
    # must already be 0 or 1: truncating 0.9 to 0 would give a malformed
    # manifest the digest of a valid one.
    for key, value in reward.items():
        if key in REWARD_INT_FIELDS:
            if isinstance(value, bool):
                value = int(value)
            if not isinstance(value, (int, float)) or value not in (0, 1):
                raise ValueError(f"{path}: {key} must be 0 or 1")
            reward[key] = int(value)
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{path}: {key} must be numeric")
        else:
            reward[key] = float(value)
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False).encode("utf-8")
    rewards = dict(reward)
    if manifest["schema_version"] == 1:
        for key in SCHEMA1_ABSENT_REWARDS:
            if key in rewards:
                raise ValueError(f"{path}: a schema 1 manifest must not carry {key}")
            rewards[key] = 0.0
    reward_table(rewards, lib)
    return {"name": manifest.get("name"), "sha256": hashlib.sha256(canonical).hexdigest(),
            "file_sha256": hashlib.sha256(raw).hexdigest(), "rewards": rewards}


class CloneRefused(ValueError):
    """The shim would not copy a session for search (CLONE_REFUSALS)."""


def _u64(value):
    return ctypes.c_uint64(int(value) & 0xFFFFFFFFFFFFFFFF)


class Engine:
    """One match on the real env TU. Two agent rows, 0 = HOME, 1 = AWAY.

    rewards: a complete {coefficient: value} mapping (load_reward_manifest), so
    last_rewards() is the training reward. Without it the session pays the
    objective terms only (touchdown, win, draw) and no shaping.
    """

    def __init__(self, seed, episode=0, home_team=-1, away_team=-1,
                 skillup_max_players=4, skillup_max_each=2,
                 skillup_secondary_pct=0.0, max_decisions=4096, lib=None, rewards=None):
        self.lib = lib or load_library()
        self.seed = int(seed)
        self.episode = int(episode)
        self.home_team = int(home_team)
        self.away_team = int(away_team)
        args = (ctypes.c_uint64(self.seed), self.episode, self.home_team,
                self.away_team, int(skillup_max_players), int(skillup_max_each),
                float(skillup_secondary_pct), int(max_decisions))
        if rewards is None:
            self._ptr = self.lib.bbp_create(*args)
        else:
            table = reward_table(rewards, self.lib)
            self._ptr = self.lib.bbp_create_rewards(*args, table, len(table))
        if not self._ptr:
            raise MemoryError("bbp_create failed")
        self.is_clone = False
        self._alloc_buffers()

    def _alloc_buffers(self):
        cap = self.lib.bbp_legal_max()
        self._act_buf = (ctypes.c_uint8 * (4 * cap))()
        self._proj_buf = (ctypes.c_uint16 * (2 * cap))()
        self._support_buf = (ctypes.c_uint32 * cap)()
        self._cap = cap

    def close(self):
        if self._ptr:
            (self.lib.bbp_free_clone if self.is_clone else self.lib.bbp_destroy)(self._ptr)
            self._ptr = None

    # ---- search clones ---------------------------------------------------
    def clone_for_search(self, seed, stream):
        """A copy of this session on its own dice stream, PCG32(seed, stream).

        The copy never holds this session's dice: it is always reseeded, and the
        real stream's id is refused. Step and read it like any Engine; once it
        reaches the end of the match it refuses steps and observations. Nothing
        done to it changes this session.
        """
        ptr = self.lib.bbp_clone_for_search(self._ptr, _u64(seed), _u64(stream))
        if not ptr:
            refusal = self.lib.bbp_clone_refusal(self._ptr, _u64(stream))
            if refusal:
                raise CloneRefused(CLONE_REFUSALS[refusal])
            raise MemoryError("bbp_clone_for_search failed")
        clone = object.__new__(type(self))
        clone.lib = self.lib
        clone.seed, clone.episode = self.seed, self.episode
        clone.home_team, clone.away_team = self.home_team, self.away_team
        clone._ptr = ptr
        clone.is_clone = True
        clone._alloc_buffers()
        return clone

    def copy_from(self, source, seed, stream):
        """clone_for_search into this clone, reusing its allocation."""
        refusal = self.lib.bbp_copy_into(self._ptr, source._ptr, _u64(seed), _u64(stream))
        if refusal:
            raise CloneRefused(CLONE_REFUSALS[refusal])
        return self

    def _test_copy_dice_from(self, source):
        """TEST ONLY: take `source`'s dice stream (bbp_test_copy_dice)."""
        self.lib.bbp_test_copy_dice(self._ptr, source._ptr)

    def _test_stall_attached(self):
        """TEST ONLY: this thread's stalling sink is this session's tally."""
        return bool(self.lib.bbp_test_stall_attached(self._ptr))

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    # ---- raw env surface -------------------------------------------------
    def obs(self, agent):
        ptr = self.lib.bbp_obs(self._ptr, int(agent))
        if not ptr:
            raise ValueError("no observation: bad agent, or a clone past the end of its match")
        return np.ctypeslib.as_array(ptr, shape=(OBS_SIZE,)).copy()

    def mask(self, agent):
        ptr = self.lib.bbp_mask(self._ptr, int(agent))
        if not ptr:
            raise ValueError("no mask: bad agent, or a clone past the end of its match")
        return np.ctypeslib.as_array(ptr, shape=(MASK_SIZE,)).copy()

    @property
    def status(self):
        return self.lib.bbp_status(self._ptr)

    @property
    def decision_team(self):
        return self.lib.bbp_decision_team(self._ptr)

    def legal(self):
        n = self.lib.bbp_legal(self._ptr, self._act_buf, self._proj_buf, self._cap)
        acts = np.ctypeslib.as_array(self._act_buf, shape=(4 * self._cap,))
        proj = np.ctypeslib.as_array(self._proj_buf, shape=(2 * self._cap,))
        return [LegalAction(i, int(acts[4 * i]), int(acts[4 * i + 1]),
                            int(acts[4 * i + 2]), int(acts[4 * i + 3]),
                            int(proj[2 * i]), int(proj[2 * i + 1]))
                for i in range(n)]

    def joint_support(self, agent):
        n = self.lib.bbp_joint_support(self._ptr, int(agent), self._support_buf,
                                       self._cap)
        return np.ctypeslib.as_array(self._support_buf, shape=(self._cap,))[:n].copy()

    def tuple_index(self, t, arg, sq):
        return self.lib.bbp_tuple_index(self._ptr, int(t), int(arg), int(sq))

    def step(self, t, arg, sq):
        return self.lib.bbp_step(self._ptr, int(t), int(arg), int(sq))

    def peek_legal(self, t, arg, sq):
        """Legal actions after applying a tuple on a scratch copy (no side effects)."""
        n = self.lib.bbp_peek_legal(self._ptr, int(t), int(arg), int(sq),
                                    self._act_buf, self._proj_buf, self._cap)
        if n < 0:
            return None
        acts = np.ctypeslib.as_array(self._act_buf, shape=(4 * self._cap,))
        proj = np.ctypeslib.as_array(self._proj_buf, shape=(2 * self._cap,))
        return [LegalAction(i, int(acts[4 * i]), int(acts[4 * i + 1]),
                            int(acts[4 * i + 2]), int(acts[4 * i + 3]),
                            int(proj[2 * i]), int(proj[2 * i + 1]))
                for i in range(n)]

    def counters(self):
        buf = (ctypes.c_int32 * 16)()
        self.lib.bbp_counters(self._ptr, buf, 16)
        keys = ["illegal", "projection_collision", "error_episodes",
                "rejected_submissions", "precheck_collisions", "steps",
                "terminal", "final_valid", "final_status", "decisions",
                "episode", "decisions_at_terminal"]
        return dict(zip(keys, (int(v) for v in buf[:len(keys)])))

    def last_action(self):
        buf = (ctypes.c_uint8 * 4)()
        agent = self.lib.bbp_last_action(self._ptr, buf)
        return agent, tuple(int(v) for v in buf)

    def last_rewards(self):
        """The latest step's reward for (HOME, AWAY), whoever decided it."""
        buf = (ctypes.c_float * 2)()
        self.lib.bbp_last_rewards(self._ptr, buf)
        return float(buf[0]), float(buf[1])

    def reward_table(self):
        """The session's reward coefficients, {name: value}."""
        names = reward_fields(self.lib)
        buf = (ctypes.c_float * len(names))()
        self.lib.bbp_reward_table(self._ptr, buf, len(names))
        return {n: float(v) for n, v in zip(names, buf)}

    def digest(self):
        return int(self.lib.bbp_state_digest(self._ptr))

    def env_digest(self):
        """digest() widened to the legal list, caches, counters and output buffers,
        with every reward field left out (bbp_env_digest)."""
        return int(self.lib.bbp_env_digest(self._ptr))

    def match(self):
        return BbMatch.from_buffer_copy(self.lib.bbp_match(self._ptr).contents)

    def turns_completed(self):
        """(HOME, AWAY) team turns completed so far: the engine's monotonic counters,
        bumped where a team turn ends, a touchdown that unwinds the turn included."""
        m = self.lib.bbp_match(self._ptr).contents
        return int(m.turns_completed[0]), int(m.turns_completed[1])

    def score(self):
        """(HOME, AWAY) touchdowns so far."""
        m = self.lib.bbp_match(self._ptr).contents
        return int(m.score[0]), int(m.score[1])

    def final_match(self):
        ptr = self.lib.bbp_final_match(self._ptr)
        return BbMatch.from_buffer_copy(ptr.contents) if ptr else None

    def contact_bot_index(self):
        return self.lib.bbp_contact_bot_index(self._ptr)

    def scripted_bot_index(self, bot_type):
        """Index into legal() of the engine bot's pick: -1 no decision, -2 bad type."""
        return self.lib.bbp_scripted_bot_index(self._ptr, int(bot_type))

    def step_scripted(self, bot_type, team):
        """Let the engine bot decide for `team` through c_step's scripted branch."""
        return self.lib.bbp_step_scripted(self._ptr, int(bot_type), int(team))

    # ---- annotations -----------------------------------------------------
    def step_success(self, slot, x, y, is_blitz, act_kind=-1):
        tests = (ctypes.c_int32 * 3)()
        probs = (ctypes.c_float * 3)()
        self.lib.bbp_step_success(self._ptr, int(slot), int(x), int(y),
                                  int(bool(is_blitz)), int(act_kind), tests, probs)
        return list(tests), [float(p) for p in probs]

    def reach(self, mover):
        dodges = (ctypes.c_uint8 * 390)()
        gfis = (ctypes.c_uint8 * 390)()
        length = (ctypes.c_uint8 * 390)()
        prev = (ctypes.c_int8 * 780)()
        self.lib.bbp_reach(self._ptr, int(mover), dodges, gfis, length, prev)
        return (np.array(dodges[:], dtype=np.uint8), np.array(gfis[:], dtype=np.uint8),
                np.array(length[:], dtype=np.uint8),
                np.array(prev[:], dtype=np.int8).reshape(390, 2))

    def block_ev(self, att, dfn, is_blitz):
        out = (ctypes.c_float * 6)()
        self.lib.bbp_block_ev(self._ptr, int(att), int(dfn), int(bool(is_blitz)), out)
        keys = ["p_def_down", "p_att_down", "p_def_removed", "p_att_removed",
                "p_ball_out", "p_turnover"]
        return {k: round(float(v), 4) for k, v in zip(keys, out)}

    def path_odds(self, slot, squares, is_blitz, act_kind=-1):
        """Per-step (rush, dodge, pickup) tests and probabilities along a path.

        act_kind is the declared bb_act_kind index (Secure the Ball changes the
        pick-up target), or -1 when unknown.
        """
        squares = list(squares)[:32]
        n = len(squares)
        if n == 0:
            return []
        xy = (ctypes.c_int8 * (2 * n))(*[int(v) for sq in squares for v in sq])
        tests = (ctypes.c_int32 * (3 * n))()
        probs = (ctypes.c_float * (3 * n))()
        done = self.lib.bbp_path_odds(self._ptr, int(slot), n, xy, int(bool(is_blitz)),
                                      int(act_kind), tests, probs)
        return [{"tests": [int(tests[3 * i + k]) for k in range(3)],
                 "probs": [float(probs[3 * i + k]) for k in range(3)]} for i in range(done)]

    def stall_counts(self):
        buf = (ctypes.c_int32 * 8)()
        self.lib.bbp_stall_counts(self._ptr, buf)
        v = list(buf)
        return {"rolls": v[0:2], "acted": v[2:4], "turnovers": v[4:6], "turn_ends": v[6:8]}

    def can_score_without_dice(self, carrier):
        return bool(self.lib.bbp_can_score_without_dice(self._ptr, int(carrier)))

    def count_assists(self, for_slot, against_slot):
        return self.lib.bbp_count_assists(self._ptr, int(for_slot), int(against_slot))

    def tackle_zones(self, team, x, y):
        return self.lib.bbp_tackle_zones(self._ptr, int(team), int(x), int(y))

    # ---- names -----------------------------------------------------------
    def team_display(self, team_id):
        v = self.lib.bbp_team_display(int(team_id))
        return v.decode() if v else None

    def team_key(self, team_id):
        v = self.lib.bbp_team_key(int(team_id))
        return v.decode() if v else None

    def position_display(self, team_id, position_id):
        v = self.lib.bbp_position_display(int(team_id), int(position_id))
        return v.decode() if v else None

    def skill_display(self, skill_id):
        v = self.lib.bbp_skill_display(int(skill_id))
        return v.decode() if v else None


def skills_of(player):
    out = []
    for word in range(3):
        w = int(player.skills.w[word])
        bit = 0
        while w:
            if w & 1:
                out.append(word * 64 + bit)
            w >>= 1
            bit += 1
    return out
