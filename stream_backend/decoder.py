"""decoder.py — reconstruct game state from a HOME-agent obs-v4 observation.

Byte map per the 2026-06-10 obs-v4 layout audit (puffer/bloodbowl/bloodbowl.h):
  [0..767]    32 player records x 24B (home agent: row == slot, ABSOLUTE coords)
  [768..783]  ball + decision context
  [784..831]  scalars (egocentric: my_* = HOME because we always decode the
              home agent's obs; away values are the opp_* fields)
  [1612..2001] A1 plane: P(def down)*255 per square (block targets, MOVE proc)
  [2002..2391] A2 plane: P(att down)*255 per square
  [2392..2781] B plane: P(step success)*255 per square
Square index: idx = y*26 + x (x in [0,25], y in [0,14]).

IMPORTANT: only decode the HOME agent's obs row — the away agent's is
x-mirrored and team-swapped (ego encoding). All protocol output is absolute.
"""

PITCH_W, PITCH_H = 26, 15
CTX, SCAL = 768, 784
A1_OFF, A2_OFF, B_OFF = 1612, 2002, 2392

LOC = {0: "off", 1: "pitch", 2: "reserves", 3: "ko", 4: "cas"}
STANCE = {0: "standing", 1: "prone", 2: "stunned"}
BALL_STATE = {0: "off_pitch", 1: "on_ground", 2: "held", 3: "in_air"}
WEATHER = {0: "nice", 1: "rain", 2: "blizzard", 3: "high_wind", 4: "intense_sun"}

# action type enum (bb_actions.h) -> protocol action names + spatial flag
ACTION_TYPES = {
    0: "NONE", 1: "SETUP_PLACE", 2: "SETUP_REMOVE", 3: "SETUP_DONE",
    4: "KICK_TARGET", 5: "TOUCHBACK", 6: "ACTIVATE", 7: "DECLARE",
    8: "END_TURN", 9: "MOVE", 10: "STAND_UP", 11: "JUMP",
    12: "BLOCK", 13: "PASS", 14: "HANDOFF", 15: "FOUL", 16: "TTM",
    17: "SECURE_BALL", 18: "PICKUP_DECLINE", 19: "END_ACTIVATION",
    20: "CHOOSE_DIE", 21: "PUSH", 22: "FOLLOW_UP", 23: "USE_REROLL",
    24: "DECLINE_REROLL", 25: "USE_SKILL", 26: "DECLINE_SKILL",
    27: "APOTHECARY", 28: "CHOOSE_OPTION", 29: "SPECIAL_TARGET",
}
SPATIAL_TYPES = {1, 4, 9, 11, 12, 13, 14, 15, 16, 21, 29}

# skill id+1 table is engine-internal; expose ids, frontend shows numbers v1.

def sq_xy(idx):
    return (idx % PITCH_W, idx // PITCH_W)


def decode_players(obs):
    """obs: bytes-like 2782 (HOME agent row). Returns list of 32 player dicts."""
    out = []
    for slot in range(32):
        o = slot * 24
        x1, y1 = obs[o], obs[o + 1]
        p = {
            "slot": slot,
            "side": "home" if slot < 16 else "away",
            "x": x1 - 1 if x1 > 0 else -1,
            "y": y1 - 1 if y1 > 0 else -1,
            "loc": LOC.get(obs[o + 2], "off"),
            "stance": STANCE.get(obs[o + 3], "standing"),
            "has_ball": bool(obs[o + 4] & 0x02),  # BB_PF_HAS_BALL bit 1
            "stats": {"ma": obs[o + 6], "st": obs[o + 7], "ag": obs[o + 8],
                      "pa": obs[o + 9], "av": obs[o + 10]},
            "skills": [obs[o + 11 + i] - 1 for i in range(12) if obs[o + 11 + i]],
        }
        # absent player slot (all zero record): mark not present
        p["present"] = not (x1 == 0 and obs[o + 2] == 0 and obs[o + 6] == 0)
        out.append(p)
    return out


def decode_ball(obs):
    bx, by = obs[CTX + 1], obs[CTX + 2]
    return {
        "state": BALL_STATE.get(obs[CTX], "off_pitch"),
        "x": bx - 1 if bx > 0 else -1,
        "y": by - 1 if by > 0 else -1,
        "carrier": obs[CTX + 3] - 1 if obs[CTX + 3] > 0 else None,
    }


def decode_scalars(obs):
    s = obs
    return {
        "half": s[SCAL],
        "turn": [s[SCAL + 1], s[SCAL + 2]],       # [home, away] (home obs: my=home)
        "score": [s[SCAL + 3], s[SCAL + 4]],
        "rerolls": [s[SCAL + 5], s[SCAL + 6]],
        "weather": WEATHER.get(s[SCAL + 7], "nice"),
        "home_active": bool(s[CTX + 11]),          # my_team_active on home obs
        "home_deciding": bool(s[CTX + 10]),
    }


def decode_state(obs):
    """Full snapshot-shaped state dict (protocol fields) from home obs."""
    sc = decode_scalars(obs)
    return {
        "score": sc["score"],
        "half": sc["half"],
        "turn": sc["turn"],
        "active_team": 0 if sc["home_active"] else 1,
        "weather": sc["weather"],
        "ball": decode_ball(obs),
        "players": decode_players(obs),
    }


def block_ev_for_square(obs, x, y):
    """ev card from A1/A2 planes for a block targeting (x,y). Home obs only."""
    idx = y * PITCH_W + x
    a1, a2 = obs[A1_OFF + idx], obs[A2_OFF + idx]
    if a1 == 0 and a2 == 0:
        return None
    return {"p_def_down": round(a1 / 255.0, 3), "p_att_down": round(a2 / 255.0, 3),
            "p_ball_out": None, "p_turnover": None}


def describe_action(atype, arg, sq, actor_hint=None):
    """(type,arg,sq) heads -> protocol action dict (absolute coords from a
    HOME-side action; for away actions the caller must un-mirror sq x)."""
    name = ACTION_TYPES.get(atype, f"T{atype}")
    d = {"type": name, "actor": actor_hint, "target": None}
    if atype in SPATIAL_TYPES and sq < 390:
        d["target"] = list(sq_xy(sq))
    if atype in (6,) and arg < 32:  # ACTIVATE names a player slot
        d["actor"] = arg
    return d


def unmirror_sq(sq):
    """Away-agent square index -> absolute square index (x -> 25-x)."""
    if sq >= 390:
        return sq
    x, y = sq_xy(sq)
    return y * PITCH_W + (PITCH_W - 1 - x)


def unmirror_action(atype, arg, sq):
    """Away-agent action heads -> absolute (type, arg_slot, sq).
    arg slots are ego (slot^16 for away); spatial sq is x-mirrored."""
    if arg < 32:
        arg = arg ^ 16
    if atype in SPATIAL_TYPES:
        sq = unmirror_sq(sq)
    return atype, arg, sq
