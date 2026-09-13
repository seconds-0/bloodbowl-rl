"""ctypes wrapper over the bbplay engine shim.

The shim compiles puffer/bloodbowl/bloodbowl.h as one translation unit, so
observations, masks, exact joint projection and c_step are the training env
itself. This module adds no rules: it reads state and forwards tuples.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from dataclasses import dataclass

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_SCRIPT = os.path.join(ROOT, "play_harness", "native", "build.sh")
LIB_EXT = "dylib" if sys.platform == "darwin" else "so"
DEFAULT_LIB = os.path.join(ROOT, "build", "play_harness", f"libbbplay.{LIB_EXT}")

ABI_VERSION = 1
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


def load_library(path=None, build_if_missing=True):
    global _LIB
    if _LIB is not None and path is None:
        return _LIB
    path = path or os.environ.get("BBPLAY_LIB", DEFAULT_LIB)
    if not os.path.exists(path):
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
        "bbp_destroy": ([c_p], None),
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
        "bbp_counters": ([c_p, ctypes.POINTER(ctypes.c_int32), ctypes.c_int], ctypes.c_int),
        "bbp_last_action": ([c_p, ctypes.POINTER(ctypes.c_uint8)], ctypes.c_int),
        "bbp_last_rewards": ([c_p, ctypes.POINTER(ctypes.c_float)], None),
        "bbp_state_digest": ([c_p], ctypes.c_uint64),
        "bbp_contact_bot_index": ([c_p], ctypes.c_int),
        "bbp_step_success": ([c_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                              ctypes.POINTER(ctypes.c_int32),
                              ctypes.POINTER(ctypes.c_float)], None),
        "bbp_reach": ([c_p, ctypes.c_int, ctypes.POINTER(ctypes.c_uint8),
                       ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_uint8),
                       ctypes.POINTER(ctypes.c_int8)], None),
        "bbp_block_ev": ([c_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                          ctypes.POINTER(ctypes.c_float)], None),
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


class Engine:
    """One match on the real env TU. Two agent rows, 0 = HOME, 1 = AWAY."""

    def __init__(self, seed, episode=0, home_team=-1, away_team=-1,
                 skillup_max_players=4, skillup_max_each=2,
                 skillup_secondary_pct=0.0, max_decisions=4096, lib=None):
        self.lib = lib or load_library()
        self.seed = int(seed)
        self.episode = int(episode)
        self.home_team = int(home_team)
        self.away_team = int(away_team)
        self._ptr = self.lib.bbp_create(
            ctypes.c_uint64(self.seed), self.episode, self.home_team,
            self.away_team, int(skillup_max_players), int(skillup_max_each),
            float(skillup_secondary_pct), int(max_decisions))
        if not self._ptr:
            raise MemoryError("bbp_create failed")
        cap = self.lib.bbp_legal_max()
        self._act_buf = (ctypes.c_uint8 * (4 * cap))()
        self._proj_buf = (ctypes.c_uint16 * (2 * cap))()
        self._support_buf = (ctypes.c_uint32 * cap)()
        self._cap = cap

    def close(self):
        if self._ptr:
            self.lib.bbp_destroy(self._ptr)
            self._ptr = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    # ---- raw env surface -------------------------------------------------
    def obs(self, agent):
        ptr = self.lib.bbp_obs(self._ptr, int(agent))
        return np.ctypeslib.as_array(ptr, shape=(OBS_SIZE,)).copy()

    def mask(self, agent):
        ptr = self.lib.bbp_mask(self._ptr, int(agent))
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
        buf = (ctypes.c_float * 2)()
        self.lib.bbp_last_rewards(self._ptr, buf)
        return float(buf[0]), float(buf[1])

    def digest(self):
        return int(self.lib.bbp_state_digest(self._ptr))

    def match(self):
        return BbMatch.from_buffer_copy(self.lib.bbp_match(self._ptr).contents)

    def final_match(self):
        ptr = self.lib.bbp_final_match(self._ptr)
        return BbMatch.from_buffer_copy(ptr.contents) if ptr else None

    def contact_bot_index(self):
        return self.lib.bbp_contact_bot_index(self._ptr)

    # ---- annotations -----------------------------------------------------
    def step_success(self, slot, x, y, is_blitz):
        tests = (ctypes.c_int32 * 3)()
        probs = (ctypes.c_float * 3)()
        self.lib.bbp_step_success(self._ptr, int(slot), int(x), int(y),
                                  int(bool(is_blitz)), tests, probs)
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
