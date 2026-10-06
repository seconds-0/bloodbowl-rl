"""What each activation of a match did: a read-only log kept beside a Match.

An activation runs from a team's ACTIVATE to its next turn-level action
(ACTIVATE or END_TURN), the other team's first turn-level action, or the end of
the match. It is filed under exactly one class, by what the coach chose in it:

  foul          a foul target was chosen
  pass_handoff  a pass or hand-off target was chosen
  blitz         a block target was chosen inside a declared Blitz
  block         a block target was chosen otherwise (a declared Block)
  moved         a step, jump or stand-up, and none of the above
  empty         the first choice after the declaration was END_ACTIVATION
  no_decision   the coach had no choice after ACTIVATE or DECLARE: the engine
                ended the activation (a failed activation roll, a turnover)
  other         anything else (a special action, a skill prompt then the end)

For `moved` activations whose player is on the pitch at both ends, with no
set-up in between, it sums the net displacement (Chebyshev, start square to
end square) and the change in two distances in squares: to the ball
(Chebyshev, the ball's square at each end) and to the team's own end zone
(x = 0 for HOME, x = 25 for AWAY; positive means upfield).

For a player with a trait that rolls when activated or declared (NEGATIVE_TRAITS)
it also counts: the activation, whether the player came out newly Distracted or
Rooted, whether it was `empty` or `no_decision`, and whether the team turn ended
in a turnover with this activation as its last.

Everything is read from the engine before the action is applied or after the
match; nothing is written to it.
"""
from __future__ import annotations

from . import engine as E

CLASSES = ("empty", "moved", "block", "blitz", "foul", "pass_handoff", "no_decision", "other")
NEGATIVE_TRAITS = ("bone_head", "really_stupid", "animal_savagery", "unchannelled_fury",
                   "take_root", "bloodlust")
KEYS = (tuple("act_" + c for c in CLASSES)
        + ("act_turnover", "moved_measured", "moved_displacement", "moved_d_ball",
           "moved_d_own_endzone",
           "neg_activations", "neg_failed", "neg_empty", "neg_no_decision", "neg_turnover",
           "neg_blocked"))
SETUP_TYPES = frozenset(("SETUP_PLACE", "SETUP_REMOVE", "SETUP_DONE", "KICK_TARGET", "TOUCHBACK"))
MOVES = frozenset(("STEP", "JUMP", "STAND_UP"))
ON_PITCH = E.LOCATIONS.index("on_pitch")
FLAG = {name: 1 << i for i, name in enumerate(E.PLAYER_FLAGS)}
OWN_ENDZONE_X = (0, E.PITCH_LEN - 1)
_TRAIT_IDS = {}


def negative_trait_ids(lib):
    """Skill ids of NEGATIVE_TRAITS in this shim, looked up by key once."""
    key = id(lib)
    if key not in _TRAIT_IDS:
        ids = set()
        for i in range(lib.bbp_skill_count()):
            name = lib.bbp_skill_key(i)
            if name and name.decode() in NEGATIVE_TRAITS:
                ids.add(i)
        if len(ids) != len(NEGATIVE_TRAITS):
            raise RuntimeError("the shim does not know every negative trait by key")
        _TRAIT_IDS[key] = frozenset(ids)
    return _TRAIT_IDS[key]


def ball_square(m):
    """The ball's square, or None when it is off the pitch."""
    state = E.BALL_STATES[m.ball.state]
    if state == "held" and m.ball.carrier < E.NUM_PLAYERS:
        p = m.players[m.ball.carrier]
        return (int(p.x), int(p.y))
    if state == "off_pitch":
        return None
    return (int(m.ball.x), int(m.ball.y))


def chebyshev(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


class ActivationLog:
    def __init__(self, eng):
        self.eng = eng
        self.stats = [dict.fromkeys(KEYS, 0), dict.fromkeys(KEYS, 0)]
        self._open = [None, None]
        self._setups = 0
        self._traits = negative_trait_ids(eng.lib)

    def on_action(self, team, name, tup):
        """Call before the action is applied."""
        if name in SETUP_TYPES:
            self._setups += 1
            return
        if name in ("ACTIVATE", "END_TURN"):
            m = self.eng.match()
            self._close(0, m)
            self._close(1, m)
            if name == "ACTIVATE":
                self._begin(team, tup, m)
            return
        a = self._open[team]
        if a is None:
            return
        if name == "DECLARE":
            a["kind"] = E.ACT_KINDS[tup[1]] if tup[1] < len(E.ACT_KINDS) else "OTHER"
            return
        if a["choices"] == 0 and name == "END_ACTIVATION":
            a["empty"] = True
        a["choices"] += 1
        if name in MOVES:
            a["moved"] = True
        elif name == "BLOCK_TARGET":
            a["block"] = True
        elif name == "FOUL_TARGET":
            a["foul"] = True
        elif name in ("PASS_TARGET", "HANDOFF_TARGET"):
            a["pass"] = True

    def finish(self, final_match):
        """Close what is open against the final state; returns the per-side stats."""
        self._close(0, final_match)
        self._close(1, final_match)
        return self.stats

    def _begin(self, team, tup, m):
        slot = next(act.arg for act in self.eng.legal() if act.tuple == tuple(tup))
        p = m.players[slot]
        self._open[team] = {
            "slot": slot, "kind": None, "choices": 0, "empty": False, "moved": False,
            "block": False, "foul": False, "pass": False,
            "start": (int(p.x), int(p.y)) if p.location == ON_PITCH else None,
            "ball": ball_square(m), "flags": int(p.flags), "setups": self._setups,
            "turnovers": int(m.turnovers_completed[team]),
            "negative": bool(self._traits & set(E.skills_of(p))),
        }

    def _close(self, team, m):
        a = self._open[team]
        if a is None:
            return
        self._open[team] = None
        s = self.stats[team]
        if a["foul"]:
            cls = "foul"
        elif a["pass"]:
            cls = "pass_handoff"
        elif a["block"]:
            cls = "blitz" if a["kind"] == "BLITZ" else "block"
        elif a["moved"]:
            cls = "moved"
        elif a["empty"]:
            cls = "empty"
        elif a["choices"] == 0:
            cls = "no_decision"
        else:
            cls = "other"
        s["act_" + cls] += 1
        turnover = int(m.turnovers_completed[team]) > a["turnovers"]
        s["act_turnover"] += int(turnover)
        p = m.players[a["slot"]]
        if (cls == "moved" and a["start"] is not None and a["setups"] == self._setups
                and p.location == ON_PITCH):
            end = (int(p.x), int(p.y))
            s["moved_measured"] += 1
            s["moved_displacement"] += chebyshev(end, a["start"])
            own = OWN_ENDZONE_X[team]
            s["moved_d_own_endzone"] += abs(end[0] - own) - abs(a["start"][0] - own)
            ball_end = ball_square(m)
            if a["ball"] is not None and ball_end is not None:
                s["moved_d_ball"] += chebyshev(end, ball_end) - chebyshev(a["start"], a["ball"])
        if a["negative"]:
            new = int(p.flags) & ~a["flags"]
            s["neg_activations"] += 1
            s["neg_failed"] += int(bool(new & (FLAG["distracted"] | FLAG["rooted"])))
            s["neg_empty"] += int(cls == "empty")
            s["neg_no_decision"] += int(cls == "no_decision")
            s["neg_blocked"] += int(cls in ("block", "blitz"))
            s["neg_turnover"] += int(turnover)
