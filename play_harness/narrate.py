"""Readable labels, game log lines and match statistics for the play UI.

Everything here reads engine state; nothing decides legality or changes the
match. Log lines are derived from the applied action plus the difference
between the match before and after the step, because the engine keeps no event
log of its own.
"""
from __future__ import annotations

from . import engine as E

TEST_KINDS = ["dodge", "rush", "pickup", "pass", "catch", "loner", "jump", "stand_up",
              "generic", "ttm"]
TEST_NAMES = {"dodge": "Dodge", "rush": "Rush", "pickup": "Pick-up", "pass": "Pass",
              "catch": "Catch", "loner": "Loner", "jump": "Jump", "stand_up": "Stand up",
              "generic": "Roll", "ttm": "Throw team-mate"}
FACE_NAMES = {1: "Attacker down", 2: "Both down", 3: "Push", 4: "Push", 5: "Stumble",
              6: "Pow"}
FACE_KEYS = {1: "skull", 2: "both", 3: "push", 4: "push", 5: "stumble", 6: "pow"}
KIND_NAMES = {"MOVE": "Move", "BLOCK": "Block", "BLITZ": "Blitz", "PASS": "Pass",
              "HANDOFF": "Hand-off", "FOUL": "Foul", "TTM": "Throw team-mate",
              "SECURE_BALL": "Secure the ball", "STAB": "Stab", "GAZE": "Hypnotic Gaze",
              "KTM": "Kick team-mate", "CHAINSAW": "Chainsaw", "BREATHE_FIRE": "Breathe Fire",
              "VOMIT": "Projectile Vomit"}
KIND_KEYS = {"MOVE": "m", "BLOCK": "b", "BLITZ": "z", "PASS": "p", "HANDOFF": "h",
             "FOUL": "f", "SECURE_BALL": "s", "TTM": "t", "KTM": "k", "STAB": "x",
             "GAZE": "g", "CHAINSAW": "c", "BREATHE_FIRE": "r", "VOMIT": "v"}
SPECIAL_NAMES = {1: "Stab", 2: "Hypnotic Gaze", 4: "Chainsaw", 5: "Breathe Fire",
                 6: "Projectile Vomit", 7: "Throw team-mate", 9: "Hit and Run"}
SOURCE_NAMES = {0: "Team re-roll", 1: "Skill re-roll", 2: "Pro", 3: "Leader"}
WEATHER_NAMES = {"sweltering": "Sweltering heat", "sunny": "Very sunny", "perfect": "Perfect",
                 "rain": "Pouring rain", "blizzard": "Blizzard"}


def top_frame(match):
    return match.stack[match.stack_top - 1] if match.stack_top > 0 else None


def proc_name(match):
    top = top_frame(match)
    return (E.PROCS[top.proc], int(top.phase)) if top is not None else ("NONE", 0)


def player_name(engine, match, slot):
    if slot is None or not 0 <= slot < E.NUM_PLAYERS:
        return "a player"
    p = match.players[slot]
    pos = engine.position_display(match.team_id[slot >> 4], p.position_id) or "Player"
    return f"#{(slot & 15) + 1} {pos}"


def team_name(engine, match, team):
    return engine.team_display(match.team_id[team]) or ("Home" if team == 0 else "Away")


def seg(text, team=None):
    return {"t": text, "team": team}


def _occupant(match, x, y):
    if not (0 <= x < E.PITCH_LEN and 0 <= y < E.PITCH_WID):
        return None
    v = int(match.grid[x][y])
    return v - 1 if v else None


def label_action(engine, match, t, arg, x, y):
    """Short label for one engine action at the given pre-state."""
    name = E.ACTION_TYPES[t] if 0 <= t < len(E.ACTION_TYPES) else str(t)
    proc, phase = proc_name(match)
    top = top_frame(match)
    mover = int(top.a) if top is not None and proc in ("MOVE", "ACTIVATION") and top.a < 32 else None
    pn = lambda s: player_name(engine, match, s)  # noqa: E731
    target = _occupant(match, x, y)
    if name == "SETUP_PLACE":
        return f"Place {pn(arg)} at {x},{y}"
    if name == "SETUP_REMOVE":
        return f"Move {pn(arg)} to reserves"
    if name == "SETUP_DONE":
        return "End setup"
    if name == "KICK_TARGET":
        return f"Kick to {x},{y}"
    if name == "TOUCHBACK":
        return f"Place the ball at {x},{y}" if arg == 0xFF else f"Give the ball to {pn(arg)}"
    if name == "ACTIVATE":
        return f"Activate {pn(arg)}"
    if name == "DECLARE":
        kind = E.ACT_KINDS[arg] if arg < len(E.ACT_KINDS) else str(arg)
        who = f" with {pn(mover)}" if mover is not None else ""
        return f"{KIND_NAMES.get(kind, kind)}{who}"
    if name == "END_TURN":
        return "End turn"
    if name == "STEP":
        return f"Move to {x},{y}"
    if name == "STAND_UP":
        return "Stand up"
    if name == "JUMP":
        return f"Jump to {x},{y}"
    if name in ("BLOCK_TARGET", "FOUL_TARGET", "HANDOFF_TARGET"):
        verb = {"BLOCK_TARGET": "Block", "FOUL_TARGET": "Foul",
                "HANDOFF_TARGET": "Hand off to"}[name]
        return f"{verb} {pn(target)}"
    if name == "PASS_TARGET":
        return f"Pass to {pn(target)}" if target is not None else f"Pass to {x},{y}"
    if name == "TTM_TARGET":
        return f"Throw team-mate to {x},{y}"
    if name == "SPECIAL_TARGET":
        return f"{SPECIAL_NAMES.get(arg, 'Special action')} on {pn(target)}"
    if name == "END_ACTIVATION":
        return "End activation"
    if name == "CHOOSE_DIE":
        faces = block_faces(match)
        return f"Pick {FACE_NAMES.get(faces[arg], 'die')}" if arg < len(faces) else f"Pick die {arg + 1}"
    if name == "PUSH_SQUARE":
        return {1: "Push into the crowd", 2: f"Chain push to {x},{y}"}.get(arg, f"Push to {x},{y}")
    if name == "FOLLOW_UP":
        return "Follow up" if arg else "Stay"
    if name == "USE_REROLL":
        if arg == 1:
            return f"Re-roll with {engine.skill_display(x) or 'skill'}"
        return SOURCE_NAMES.get(arg, "Re-roll")
    if name == "DECLINE_REROLL":
        return "No re-roll"
    if name == "USE_SKILL":
        return f"Use {engine.skill_display(arg) or 'skill'}"
    if name == "DECLINE_SKILL":
        return f"Decline {engine.skill_display(arg) or 'skill'}"
    if name == "APOTHECARY":
        return "Use the apothecary" if arg else "Keep the result"
    if name == "CHOOSE_OPTION":
        if arg == 0xFE:
            return "Decline"
        if proc == "PREGAME":
            return "Kick" if arg == 0 else "Receive"
        if proc == "CASUALTY":
            return "Keep the first result" if arg == 0 else "Take the new result"
        if proc == "FOUL":
            return "Argue the call" if arg == 1 else "Accept the send-off"
        return f"Choose option {arg + 1}"
    if name == "SECURE_BALL":
        return "Secure the ball"
    return name.replace("_", " ").capitalize()


def block_faces(match):
    top = top_frame(match)
    if top is None or E.PROCS[top.proc] != "BLOCK":
        return []
    nd = ((top.data >> 9) & 3) + 1
    return [(top.data >> (3 * i)) & 7 for i in range(nd)]


def in_team_turn(match, team):
    for i in range(match.stack_top):
        f = match.stack[i]
        if E.PROCS[f.proc] == "TEAM_TURN" and f.a == team:
            return True
    return False


class Narrator:
    """Turns applied steps into log entries and accumulates match statistics."""

    def __init__(self, engine):
        self.engine = engine
        self.entries = []
        self._turn_key = None
        self._half = None
        self._weather = None
        self._pending = {}   # mover -> {"dodge", "rush", "x", "y", "failed_kind"}
        self._shown_dice = None
        z = lambda: [0, 0]  # noqa: E731
        self.counts = {"blocks": z(), "cas": z(), "ko": z(), "dodges": z(), "dodges_made": z(),
                       "rushes": z(), "rushes_made": z(), "passes": z(), "handoffs": z(),
                       "fouls": z(), "decisions": z(), "sent_off": z()}

    # ---- helpers ---------------------------------------------------------
    def _emit(self, step, kind, parts, team=None, player=None):
        entry = {"step": step, "kind": kind, "parts": parts, "team": team}
        if player is not None:
            entry["player"] = player
        self.entries.append(entry)
        return entry

    def _pn(self, match, slot):
        return seg(player_name(self.engine, match, slot), slot >> 4 if slot is not None and slot < 32 else None)

    def _resolve_pending(self, step, post, score_changed):
        top = top_frame(post)
        testing = top is not None and E.PROCS[top.proc] == "TEST"
        done = []
        for mover, pend in self._pending.items():
            if testing and top.a == mover:
                if top.b < len(TEST_KINDS):
                    pend["failed_kind"] = TEST_KINDS[top.b]
                continue
            p = post.players[mover]
            ok = score_changed or (p.location == 0 and p.stance == 0 and
                                   p.x == pend["x"] and p.y == pend["y"])
            team = mover >> 4
            if ok:
                if pend["dodge"]:
                    self.counts["dodges_made"][team] += 1
                if pend["rush"]:
                    self.counts["rushes_made"][team] += 1
            else:
                failed = pend.get("failed_kind") or ("dodge" if pend["dodge"] else "rush")
                if pend["dodge"] and failed != "dodge":
                    self.counts["dodges_made"][team] += 1
                if pend["rush"] and failed != "rush":
                    self.counts["rushes_made"][team] += 1
            done.append(mover)
        for mover in done:
            del self._pending[mover]

    # ---- main entry ------------------------------------------------------
    def on_step(self, record, pre, post, over=False):
        eng = self.engine
        step = record["step"]
        t, arg, x, y = record["action"]
        name = record["action_type"]
        team = int(record["decision_team"])
        self.counts["decisions"][team] += 1
        proc, phase = proc_name(pre)
        top = top_frame(pre)
        mover = int(top.a) if top is not None and proc in ("MOVE", "ACTIVATION") and top.a < 32 else None
        out_start = len(self.entries)

        if self._weather is None:
            self._weather = int(pre.weather)
            wname = E.WEATHER[pre.weather] if pre.weather < len(E.WEATHER) else "?"
            self._emit(step, "event", [seg(f"Weather: {WEATHER_NAMES.get(wname, wname)}")])

        if name == "DECLARE" and mover is not None:
            kind = E.ACT_KINDS[arg] if arg < len(E.ACT_KINDS) else str(arg)
            self._emit(step, "action", [self._pn(pre, mover),
                                        seg(f" declares {KIND_NAMES.get(kind, kind)}")],
                       team, mover)
        elif name in ("STEP", "JUMP") and mover is not None:
            tests = record.get("tests") or {}
            if tests.get("dodge"):
                self.counts["dodges"][mover >> 4] += 1
            if tests.get("rush"):
                self.counts["rushes"][mover >> 4] += 1
            if tests.get("dodge") or tests.get("rush"):
                self._pending[mover] = {"dodge": bool(tests.get("dodge")),
                                        "rush": bool(tests.get("rush")), "x": x, "y": y}
            verb = " jumps" if name == "JUMP" else " moves"
            self._emit(step, "move", [self._pn(pre, mover), seg(verb)], team, mover)
        elif name == "STAND_UP" and mover is not None:
            self._emit(step, "action", [self._pn(pre, mover), seg(" stands up")], team, mover)
        elif name in ("BLOCK_TARGET", "FOUL_TARGET", "HANDOFF_TARGET", "PASS_TARGET",
                      "SPECIAL_TARGET", "TTM_TARGET") and mover is not None:
            target = _occupant(pre, x, y)
            blitz = top is not None and proc == "MOVE" and top.b < len(E.ACT_KINDS) and \
                E.ACT_KINDS[top.b] == "BLITZ"
            verb = {"BLOCK_TARGET": " blitzes " if blitz else " blocks ",
                    "FOUL_TARGET": " fouls ", "HANDOFF_TARGET": " hands off to ",
                    "PASS_TARGET": " passes to ", "TTM_TARGET": " throws a team-mate to ",
                    "SPECIAL_TARGET": f" uses {SPECIAL_NAMES.get(arg, 'a special action')} on "}[name]
            parts = [self._pn(pre, mover), seg(verb)]
            if target is not None:
                parts.append(self._pn(pre, target))
            else:
                parts.append(seg(f"{x},{y}"))
            self._emit(step, "action", parts, team, mover)
            key = {"BLOCK_TARGET": "blocks", "FOUL_TARGET": "fouls", "HANDOFF_TARGET": "handoffs",
                   "PASS_TARGET": "passes"}.get(name)
            if key:
                self.counts[key][mover >> 4] += 1
        elif name == "CHOOSE_DIE":
            faces = block_faces(pre)
            if arg < len(faces):
                self._emit(step, "roll", [seg(team_name(eng, pre, team), team),
                                          seg(f" picks {FACE_NAMES.get(faces[arg], 'a die')}")], team)
        elif name == "USE_REROLL":
            label = label_action(eng, pre, t, arg, x, y)
            self._emit(step, "action", [seg(team_name(eng, pre, team), team),
                                        seg(f": {label}")], team)
        elif name == "USE_SKILL":
            self._emit(step, "action", [seg(team_name(eng, pre, team), team),
                                        seg(f" uses {eng.skill_display(arg) or 'a skill'}")], team)
        elif name == "PUSH_SQUARE" and arg == 1:
            pushee = int(top.b) if top is not None and top.b < 32 else None
            self._emit(step, "event", [self._pn(pre, pushee), seg(" is pushed into the crowd")],
                       team, pushee)
        elif name == "FOLLOW_UP" and arg == 1 and top is not None and top.a < 32:
            self._emit(step, "action", [self._pn(pre, int(top.a)), seg(" follows up")], team)
        elif name == "APOTHECARY" and arg == 1:
            self._emit(step, "action", [seg(team_name(eng, pre, team), team),
                                        seg(" uses the apothecary")], team)
        elif name == "END_TURN":
            self._emit(step, "action", [seg(team_name(eng, pre, team), team),
                                        seg(" ends the turn")], team)
        elif name == "KICK_TARGET":
            self._emit(step, "action", [seg(team_name(eng, pre, team), team), seg(" kicks off")], team)
        elif name == "TOUCHBACK":
            if arg == 0xFF:
                self._emit(step, "event", [seg("Touchback: the ball is placed")], team)
            else:
                self._emit(step, "event", [seg("Touchback: "), self._pn(pre, arg),
                                           seg(" gets the ball")], team)
        elif name == "SETUP_DONE":
            self._emit(step, "action", [seg(team_name(eng, pre, team), team),
                                        seg(" finishes setup")], team)
        elif name == "CHOOSE_OPTION":
            if proc == "PREGAME":
                self._emit(step, "action", [seg(team_name(eng, pre, team), team),
                                            seg(" chooses to kick" if arg == 0 else " chooses to receive")],
                           team)
            elif proc == "FOUL":
                self._emit(step, "action", [seg(team_name(eng, pre, team), team),
                                            seg(" argues the call" if arg == 1 else " accepts the send-off")],
                           team)

        self._diff(step, pre, post, team)
        score_changed = any(post.score[i] != pre.score[i] for i in (0, 1))
        self._resolve_pending(step, post, score_changed)
        return self.entries[out_start:]

    def _diff(self, step, pre, post, acting_team):
        eng = self.engine
        # Block dice rolled into a decision window.
        faces = block_faces(post)
        top = top_frame(post)
        if faces and top is not None:
            key = (int(top.a), int(top.b), int(top.data))
            if key != self._shown_dice:
                self._shown_dice = key
                names = ", ".join(FACE_NAMES.get(f, "?") for f in faces)
                n = len(faces)
                self._emit(step, "roll", [self._pn(post, int(top.a)), seg(" rolls "),
                                          seg(f"{n} {'die' if n == 1 else 'dice'}: {names}")],
                           int(top.a) >> 4)
        else:
            self._shown_dice = None
        if top is not None and E.PROCS[top.proc] == "TEST" and top.a < 32 and \
                (pre.stack_top == 0 or E.PROCS[pre.stack[pre.stack_top - 1].proc] != "TEST"):
            kind = TEST_KINDS[top.b] if top.b < len(TEST_KINDS) else "generic"
            self._emit(step, "roll", [self._pn(post, int(top.a)),
                                      seg(f" fails a {TEST_NAMES[kind]} roll ({int(top.x)}+)")],
                       int(top.a) >> 4)
        for s in range(E.NUM_PLAYERS):
            a, b = pre.players[s], post.players[s]
            if b.location == 5:
                continue
            if a.location == 0 and b.location == 0:
                if a.stance == 0 and b.stance in (1, 2):
                    self._emit(step, "event", [self._pn(post, s),
                                               seg(" is down" if b.stance == 1 else " is stunned")],
                               s >> 4, s)
                elif a.stance == 1 and b.stance == 2:
                    self._emit(step, "event", [self._pn(post, s), seg(" is stunned")], s >> 4, s)
            if a.location != b.location:
                msg = {2: " is knocked out", 3: " is a casualty", 4: " is sent off"}.get(b.location)
                if msg and a.location in (0, 1):
                    self._emit(step, "event", [self._pn(post, s), seg(msg)], s >> 4, s)
                    victim_team = s >> 4
                    if b.location == 4:
                        self.counts["sent_off"][victim_team] += 1
                    elif victim_team != acting_team:
                        key = "cas" if b.location == 3 else "ko"
                        self.counts[key][acting_team] += 1
                elif a.location == 2 and b.location == 1:
                    self._emit(step, "event", [self._pn(post, s), seg(" recovers from the KO")],
                               s >> 4, s)
        if post.ball.state == 2 and post.ball.carrier < 32 and \
                not (pre.ball.state == 2 and pre.ball.carrier == post.ball.carrier):
            c = int(post.ball.carrier)
            self._emit(step, "event", [self._pn(post, c), seg(" has the ball")], c >> 4, c)
        for t in (0, 1):
            if post.score[t] > pre.score[t]:
                self._emit(step, "td", [seg("Touchdown for "), seg(team_name(eng, post, t), t)], t)
        if post.turnover and not pre.turnover:
            self._emit(step, "event", [seg("Turnover")], acting_team)
        if post.half != self._half and post.half in (1, 2):
            self._half = int(post.half)
            self._emit(step, "half", [seg("First half" if post.half == 1 else "Second half")])
        for t in (0, 1):
            if in_team_turn(post, t):
                key = (int(post.half), t, int(post.turn[t]))
                if key != self._turn_key:
                    self._turn_key = key
                    self._emit(step, "turn", [seg(team_name(eng, post, t), t),
                                              seg(f" turn {int(post.turn[t])}")], t)

    # ---- statistics ------------------------------------------------------
    def stats(self, final, stall=None, human_seat=0):
        c = self.counts

        def made(k):
            return [f"{c[k + '_made'][t]} of {c[k][t]}" for t in (0, 1)]

        rows = [
            ["Touchdowns", int(final.score[0]), int(final.score[1])],
            ["Blocks thrown", c["blocks"][0], c["blocks"][1]],
            ["Casualties caused", c["cas"][0], c["cas"][1]],
            ["Knock-outs caused", c["ko"][0], c["ko"][1]],
            ["Turnovers", int(final.turnovers_completed[0]), int(final.turnovers_completed[1])],
            ["Dodges made", *made("dodges")],
            ["Rushes made", *made("rushes")],
            ["Passes", c["passes"][0], c["passes"][1]],
            ["Hand-offs", c["handoffs"][0], c["handoffs"][1]],
            ["Fouls", c["fouls"][0], c["fouls"][1]],
        ]
        if stall is not None:
            rows.append(["Stalling rolls", stall["rolls"][0], stall["rolls"][1]])
        rows.append(["Decisions", c["decisions"][0], c["decisions"][1]])
        return {"rows": rows, "teams": [team_name(self.engine, final, 0),
                                        team_name(self.engine, final, 1)]}
