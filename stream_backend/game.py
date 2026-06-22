"""game.py — one live Blood Bowl match between two torch checkpoints,
yielding protocol-v1 messages (see docs/stream-protocol.md).

Torch backend (logits + value exposed). Reuses PuffeRL.create_pufferl for the
fully-wired vec+policy, then runs a custom 2-policy decision loop modeled on
PuffeRL.rollouts (torch_pufferl.py): forward both sides, mask, sample, step
via gpu_step/cpu_step with _actions_for_vec_step.
"""
import copy
import sys
import time

try:
    import torch
    from pufferlib import pufferl as pufferl_mod
    from pufferlib import torch_pufferl as tp
    _TORCH_IMPORT_ERROR = None
except (ImportError, ModuleNotFoundError) as e:
    torch = None
    pufferl_mod = None
    tp = None
    _TORCH_IMPORT_ERROR = e

import json
import os

import decoder as dec

ACT_SIZES = [30, 33, 391]
TEAMSTAT_SIDES = ("home", "away")
TEST_STAT_KINDS = {"dodge", "gfi", "pickup"}

BB_A_ACTIVATE = 6
BB_A_DECLARE = 7
BB_A_STEP = 9
BB_A_STAND_UP = 10
BB_A_JUMP = 11
BB_A_BLOCK_TARGET = 12
BB_A_PASS_TARGET = 13
BB_A_HANDOFF_TARGET = 14
BB_A_FOUL_TARGET = 15
BB_A_CHOOSE_DIE = 20

BB_PROC_MOVE = 7
BB_PROC_BLOCK = 11
BB_PROC_PUSH = 12

BB_PF_DISTRACTED = 1 << 2
BB_PF_NO_TZ = 1 << 10

SK_BIG_HAND = 36
SK_EXTRA_ARMS = 39
SK_PREHENSILE_TAIL = 44
SK_TWO_HEADS = 46
SK_BREAK_TACKLE = 62
SK_DRUNKARD = 82
SK_NO_BALL = 89
SK_STUNTY = 99
SK_TITCHY = 104

DICE_SOURCE_INFERRED = "inferred_from_state"


def greedy_logits(logits):
    """Argmax per head — broadcast mode plays its best move, no exploration."""
    return torch.stack([lg.argmax(-1).reshape(-1) for lg in logits], -1).int()


def _torch_no_grad():
    if torch is not None:
        return torch.no_grad()
    return lambda fn: fn

_ROSTERS = json.load(open(os.path.join(os.path.dirname(__file__), "rosters.json")))
TEAM_COLORS = {
    "Wood Elf": "#2e7d32", "Dwarf": "#b8860b", "Orc": "#33691e",
    "Human": "#1565c0", "Skaven": "#6d4c41", "Dark Elf": "#4a148c",
    "High Elf": "#90caf9", "Elven Union": "#00897b", "Amazon": "#c62828",
    "Norse": "#455a64", "Chaos Chosen": "#7b1fa2", "Khorne": "#b71c1c",
    "Shambling Undead": "#37474f", "Necromantic Horror": "#263238",
    "Lizardmen": "#00acc1", "Goblin": "#558b2f", "Halfling": "#8d6e63",
    "Ogre": "#5d4037", "Snotling": "#7cb342", "Vampire": "#880e4f",
    "Tomb Kings": "#c0a060", "Nurgle": "#827717", "Black Orc": "#212121",
    "Imperial Nobility": "#9e9d24", "Bretonnian": "#283593",
    "Old World Alliance": "#6a1b9a", "Chaos Dwarf": "#bf360c",
    "Chaos Renegades": "#4e342e", "Underworld Denizens": "#33691e",
    "Gnome": "#00695c",
}


def _empty_team_stats():
    return {
        "blocks": 0,
        "tier": [0, 0, 0],       # good, even, bad
        "dodge": [0, 0],         # success, attempts
        "gfi": [0, 0],
        "pickup": [0, 0],
        "turnovers": 0,
        "pass": 0,
        "handoff": 0,
        "foul": 0,
    }


def _side_from_actor(actor, fallback=None):
    if isinstance(actor, int) and 0 <= actor < 32:
        return "home" if actor < 16 else "away"
    return fallback


def _side_from_active(active_team):
    if active_team == 0:
        return "home"
    if active_team == 1:
        return "away"
    return None


def _player_by_slot(state, slot):
    if not isinstance(slot, int):
        return None
    players = state.get("players") or []
    if 0 <= slot < len(players):
        return players[slot]
    return None


def _slot_num(slot):
    return (slot % 16) + 1 if isinstance(slot, int) else "?"


def _actor_text(slot):
    return f"#{_slot_num(slot)}"


def _ctx_from_obs(obs):
    def slot_at(i):
        v = obs[dec.CTX + i]
        return v - 1 if v > 0 else None
    return {
        "proc": obs[dec.CTX + 4],
        "phase": obs[dec.CTX + 5],
        "a": slot_at(6),
        "b": slot_at(7),
        "test_target": obs[dec.CTX + 8] or None,
    }


def _raw_flags(obs, slot):
    if not isinstance(slot, int) or not (0 <= slot < 32):
        return 0
    o = slot * 24
    return int(obs[o + 4]) | (int(obs[o + 5]) << 8)


def _has_skill(player, skill):
    return isinstance(player, dict) and skill in (player.get("skills") or [])


def _exerts_tz(player, obs):
    if not isinstance(player, dict) or player.get("loc") != "pitch":
        return False
    if player.get("stance") != "standing":
        return False
    flags = _raw_flags(obs, player.get("slot"))
    return (flags & (BB_PF_DISTRACTED | BB_PF_NO_TZ)) == 0


def _adjacent(a, b):
    if not a or not b:
        return False
    dx = abs(int(a["x"]) - int(b["x"]))
    dy = abs(int(a["y"]) - int(b["y"]))
    return (dx or dy) and dx <= 1 and dy <= 1


def _adjacent_xy(player, x, y):
    if not isinstance(player, dict):
        return False
    dx = abs(int(player.get("x", -99)) - int(x))
    dy = abs(int(player.get("y", -99)) - int(y))
    return (dx or dy) and dx <= 1 and dy <= 1


def _test_target(stat_target, modifiers):
    needed = int(stat_target or 6) - int(modifiers or 0)
    return max(2, min(6, needed))


def _opp_tz_at(obs, side, x, y):
    if not (0 <= x < dec.PITCH_W and 0 <= y < dec.PITCH_H):
        return 0
    idx = y * dec.PITCH_W + x
    # The stream decodes the HOME observation. Its first TZ plane is home TZs,
    # second is away TZs, so the acting side's opposing plane depends on side.
    off = dec.TZ_OFF + (dec.TZ_PLANE if side == "home" else 0)
    return int(obs[off + idx])


def _titchy_markers_at(pre, obs, side, x, y):
    n = 0
    for q in pre.get("players") or []:
        if q.get("side") == side:
            continue
        if _has_skill(q, SK_TITCHY) and _exerts_tz(q, obs) and _adjacent_xy(q, x, y):
            n += 1
    return n


def _prehensile_tail_marks(pre, obs, mover):
    for q in pre.get("players") or []:
        if q.get("side") == mover.get("side"):
            continue
        if (_has_skill(q, SK_PREHENSILE_TAIL) and _exerts_tz(q, obs)
                and _adjacent(q, mover)):
            return True
    return False


def _gfi_target(pre, obs, mover, to_x, to_y, is_blitz=False):
    mod = 0
    if pre.get("weather") == "blizzard":
        mod -= 1
    if _has_skill(mover, SK_DRUNKARD):
        mod -= 1
    return _test_target(2, mod)


def _dodge_target(pre, obs, mover, to_x, to_y, side):
    dest_tz = _opp_tz_at(obs, side, to_x, to_y)
    mod = -dest_tz
    if _has_skill(mover, SK_TWO_HEADS):
        mod += 1
    if _has_skill(mover, SK_STUNTY):
        mod += dest_tz
    else:
        mod += _titchy_markers_at(pre, obs, side, to_x, to_y)
    if _has_skill(mover, SK_TITCHY):
        mod += 1
    if _has_skill(mover, SK_BREAK_TACKLE):
        mod += 2 if (mover.get("stats") or {}).get("st", 0) >= 5 else 1
    if _prehensile_tail_marks(pre, obs, mover):
        mod -= 1
    return _test_target((mover.get("stats") or {}).get("ag", 6), mod)


def _pickup_target(pre, obs, mover, to_x, to_y, side):
    if _has_skill(mover, SK_NO_BALL):
        return None
    dest_tz = _opp_tz_at(obs, side, to_x, to_y)
    rain = pre.get("weather") == "rain"
    mod = -dest_tz - (1 if rain else 0)
    if _has_skill(mover, SK_EXTRA_ARMS):
        mod += 1
    if _has_skill(mover, SK_BIG_HAND):
        mod += dest_tz + (1 if rain else 0)
    return _test_target((mover.get("stats") or {}).get("ag", 6), mod)


def _d6_dice(label, target, ok, slot, note=None):
    d = {
        "kind": "d6",
        "label": label,
        "target": target,
        "roll": None,
        "ok": bool(ok),
        "actor": slot,
        "source": DICE_SOURCE_INFERRED,
    }
    if note:
        d["note"] = note
    return d


def _d6_feed(dice, side):
    target = dice.get("target")
    target_txt = f" {target}+" if isinstance(target, int) else ""
    outcome = "succeeds" if dice.get("ok") else "fails"
    return {
        "kind": _dice_test_kind(dice),
        "side": side,
        "ok": bool(dice.get("ok")),
        "text": f"{_actor_text(dice.get('actor'))} {dice.get('label')}{target_txt} {outcome}",
    }


def _stance_down(player):
    if not isinstance(player, dict):
        return False
    return (player.get("loc") in ("ko", "cas")
            or player.get("stance") in ("prone", "stunned", "ko", "cas", "sent_off"))


def _standing_on_pitch(player):
    return (isinstance(player, dict) and player.get("loc") == "pitch"
            and player.get("stance") == "standing")


def _materially_moved_to(player, x, y):
    return isinstance(player, dict) and player.get("x") == x and player.get("y") == y


def _block_result(pre, post, post_ctx, att, defender):
    a0, a1 = _player_by_slot(pre, att), _player_by_slot(post, att)
    d0, d1 = _player_by_slot(pre, defender), _player_by_slot(post, defender)
    att_down = _standing_on_pitch(a0) and _stance_down(a1)
    def_down = _standing_on_pitch(d0) and _stance_down(d1)
    def_moved = (d0 and d1 and d0.get("loc") == "pitch" and d1.get("loc") == "pitch"
                 and (d0.get("x"), d0.get("y")) != (d1.get("x"), d1.get("y")))
    if att_down and def_down:
        return "Both Down"
    if def_down:
        return "Defender Down"
    if att_down:
        return "Attacker Down"
    if def_moved or (post_ctx and post_ctx.get("proc") == BB_PROC_PUSH):
        return "Push"
    if post_ctx and post_ctx.get("proc") == BB_PROC_BLOCK and post_ctx.get("phase") in (4, 5):
        return "Both Down"
    return "Resolving"


def _block_tier_label(ndice, red):
    if red and ndice >= 2:
        return "bad"
    if ndice == 1:
        return "even"
    return "good"


def _norm_test_kind(label):
    s = str(label or "").strip().lower().replace("_", " ").replace("-", " ")
    if s in ("dodge",):
        return "dodge"
    if s in ("gfi", "go for it", "rush", "rushing"):
        return "gfi"
    if s in ("pickup", "pick up", "pick up ball", "pick up roll"):
        return "pickup"
    return None


def _dice_test_kind(dice):
    if not isinstance(dice, dict) or dice.get("kind") != "d6":
        return None
    return _norm_test_kind(dice.get("label"))


def _dice_ok(dice):
    if not isinstance(dice, dict):
        return None
    if isinstance(dice.get("ok"), bool):
        return dice["ok"]
    roll, target = dice.get("roll"), dice.get("target")
    if isinstance(roll, int) and isinstance(target, int):
        return roll >= target
    return None


def _text_says_failure(text):
    s = str(text or "").lower()
    return any(w in s for w in (
        "fail", "failed", "trips", "stumbles", "fumbles", "drops", "skulls"
    ))


def _text_says_pickup_try(text):
    s = str(text or "").lower()
    return any(w in s for w in ("reaches", "tries", "attempts"))


def _block_tier_from_value(value):
    if value is None:
        return None
    if isinstance(value, str):
        s = value.lower().replace("_", "-")
        if s in ("good", "attacker", "attacker-choice", "2d", "3d"):
            return 0
        if s in ("even", "1d"):
            return 1
        if s in ("bad", "defender", "defender-choice", "2d-red", "3d-red",
                 "red"):
            return 2
    if isinstance(value, int):
        # Engine tiers: 0=1d, 1=2d, 2=3d, 3=2d-red, 4=3d-red.
        if value in (1, 2):
            return 0
        if value == 0:
            return 1
        if value in (3, 4):
            return 2
    return None


def _block_tier_from_ev(ev):
    if not isinstance(ev, dict):
        return 1
    for key in ("tier", "block_tier", "dice_tier"):
        explicit = _block_tier_from_value(ev.get(key))
        if explicit is not None:
            return explicit

    dice = ev.get("dice") or ev.get("dice_count") or ev.get("ndice")
    red = bool(ev.get("red") or ev.get("defender_choice"))
    if isinstance(dice, int):
        if red and dice >= 2:
            return 2
        if dice == 1:
            return 1
        if dice >= 2:
            return 0

    p_def, p_att = ev.get("p_def_down"), ev.get("p_att_down")
    if isinstance(p_def, (int, float)) and isinstance(p_att, (int, float)):
        # EV is weaker than the engine's raw dice tier, but it is what the
        # Python stream currently exposes. Keep ambiguous 1d-like cases even.
        if p_att >= 0.30 or p_att > p_def + 0.05:
            return 2
        if p_def >= 0.52 and p_att <= 0.20:
            return 0
    return 1


def _block_tier_from_dice(dice):
    if not isinstance(dice, dict) or dice.get("kind") != "block":
        return None
    for key in ("tier", "block_tier", "dice_tier"):
        explicit = _block_tier_from_value(dice.get(key))
        if explicit is not None:
            return explicit
    rolls = dice.get("rolls")
    if isinstance(rolls, list):
        red = bool(dice.get("red") or dice.get("defender_choice"))
        if red and len(rolls) >= 2:
            return 2
        if len(rolls) == 1:
            return 1
        if len(rolls) >= 2:
            return 0
    return None


class TeamStatsAccumulator:
    """Per-game web-stream team stats.

    The update hook consumes the same protocol delta/feed/dice object that is
    broadcast once per engine decision, so a continuation or macro loop cannot
    double-count unless it also emits multiple real stream events.
    """

    def __init__(self):
        self.stats = {side: _empty_team_stats() for side in TEAMSTAT_SIDES}

    def snapshot(self):
        return copy.deepcopy(self.stats)

    def _team(self, side):
        if side not in self.stats:
            return None
        return self.stats[side]

    def _inc_block(self, side, tier):
        team = self._team(side)
        if team is None:
            return
        team["blocks"] += 1
        team["tier"][tier] += 1

    def _inc_test(self, side, kind, ok):
        team = self._team(side)
        if team is None or kind not in TEST_STAT_KINDS:
            return
        team[kind][1] += 1
        if ok:
            team[kind][0] += 1

    def _inc_plain(self, side, key):
        team = self._team(side)
        if team is not None:
            team[key] += 1

    def update_from_delta(self, msg, default_side=None):
        before = self.snapshot()
        action = msg.get("action") or {}
        action_type = str(action.get("type") or "").upper()
        action_side = _side_from_actor(action.get("actor"), default_side)
        dice_items = [d for d in (msg.get("dice_seq") or []) if isinstance(d, dict)]
        if not dice_items and isinstance(msg.get("dice"), dict):
            dice_items = [msg["dice"]]
        block_dice = next((d for d in dice_items if d.get("kind") == "block"), None)
        target_only = any((f.get("phase") == "target") for f in (msg.get("feed") or [])
                          if isinstance(f, dict))

        if action_type == "CHOOSE_DIE" or block_dice:
            tier = _block_tier_from_dice(block_dice)
            if tier is None:
                tier = _block_tier_from_ev(msg.get("ev"))
            self._inc_block(action_side, tier)
        elif action_type == "BLOCK" and not target_only:
            # Legacy fixture compatibility: older stream deltas counted block
            # target decisions as the only available block signal. New deltas
            # mark those feed entries with phase=target and count CHOOSE_DIE.
            tier = _block_tier_from_ev(msg.get("ev"))
            self._inc_block(action_side, tier)
        elif action_type == "PASS":
            self._inc_plain(action_side, "pass")
        elif action_type == "HANDOFF":
            self._inc_plain(action_side, "handoff")
        elif action_type == "FOUL":
            self._inc_plain(action_side, "foul")

        dice = msg.get("dice")
        dice_kind = _dice_test_kind(dice)
        dice_ok = _dice_ok(dice)
        counted_tests = set()
        pickup_try = {"home": 0, "away": 0}
        pickup_ok = {"home": 0, "away": 0}

        for f in msg.get("feed") or []:
            kind = str(f.get("kind") or "").lower()
            side = f.get("side") or default_side
            if side not in self.stats:
                continue
            if kind == "turnover":
                self._inc_plain(side, "turnovers")
            elif kind in ("pass", "handoff", "foul"):
                if kind.upper() != action_type:
                    self._inc_plain(side, kind)
            elif kind in ("dodge", "gfi"):
                ok = dice_ok if dice_kind == kind else f.get("ok", f.get("success"))
                if ok is None:
                    ok = not _text_says_failure(f.get("text"))
                self._inc_test(side, kind, bool(ok))
                counted_tests.add((side, kind))
            elif kind == "pickup":
                text = f.get("text")
                explicit = f.get("ok", f.get("success"))
                if explicit is True:
                    pickup_ok[side] += 1
                elif explicit is False or _text_says_failure(text):
                    pickup_try[side] += 1
                elif _text_says_pickup_try(text):
                    pickup_try[side] += 1
                else:
                    pickup_ok[side] += 1

        for side in TEAMSTAT_SIDES:
            saw_pickup_feed = pickup_try[side] > 0 or pickup_ok[side] > 0
            for _ in range(pickup_try[side]):
                self._inc_test(side, "pickup", False)
            for _ in range(pickup_ok[side]):
                # A standalone "pickup ok" feed represents a successful test;
                # a paired try+ok in the same delta should remain one attempt.
                if pickup_try[side] > 0:
                    self.stats[side]["pickup"][0] += 1
                    pickup_try[side] -= 1
                else:
                    self._inc_test(side, "pickup", True)
            if saw_pickup_feed:
                counted_tests.add((side, "pickup"))

        for d in dice_items:
            kind = _dice_test_kind(d)
            ok = _dice_ok(d)
            if kind and ok is not None:
                side = _side_from_actor(d.get("actor"), action_side or default_side)
                if side in self.stats and (side, kind) not in counted_tests:
                    self._inc_test(side, kind, ok)
                    counted_tests.add((side, kind))

        return self.stats != before


def tag_positions(players, home_team, away_team):
    """Attach position name + icon to player dicts by nearest stat-line
    against the pinned roster (obs carries no position/team identity)."""
    for p in players:
        if not p.get("present"):
            continue
        tid = home_team if p["side"] == "home" else away_team
        if tid is None or tid < 0 or tid >= len(_ROSTERS):
            continue
        best, bd = None, 1e9
        st = p["stats"]
        for pos in _ROSTERS[tid]["positions"]:
            d = (abs(pos["ma"] - st["ma"]) + 2 * abs(pos["st"] - st["st"])
                 + abs(pos["ag"] - st["ag"]) + abs(pos["pa"] - st["pa"])
                 + abs(pos["av"] - st["av"])
                 + 0.25 * abs(pos["nskills"] - len(p["skills"])))
            if d < bd:
                bd, best = d, pos
        if best:
            p["position"] = best["name"]
            p["icon"] = best["icon"]
    return players


class Match:
    def __init__(self, ckpt_a, ckpt_b, seed=None, home_team=-1, away_team=-1,
                 macro=False, scripted="off", scripted_type=1):
        if torch is None or pufferl_mod is None or tp is None:
            raise RuntimeError(
                "Match requires torch and pufferlib; pure helpers such as "
                "TeamStatsAccumulator can be imported without them"
            ) from _TORCH_IMPORT_ERROR
        _argv = sys.argv
        sys.argv = [_argv[0], "--slowly"]   # load_config parses argv; shield ours
        try:
            args = pufferl_mod.load_config("bloodbowl")
        finally:
            sys.argv = _argv
        args["train"]["horizon"] = 1
        args["vec"]["total_agents"] = 2
        args["vec"]["num_buffers"] = 1
        args["vec"]["num_threads"] = 1
        args["selfplay"]["enabled"] = 0
        args["env"]["macro_moves"] = 1 if macro else 0
        args["env"]["force_home_team"] = home_team
        args["env"]["force_away_team"] = away_team
        # Scripted-bot spectating: drive a team (or both) with the C cage bot
        # instead of a policy. team code 0=home, 1=away, 2=both (bot-vs-bot).
        self.scripted = scripted
        _steam = {"home": 0, "away": 1, "both": 2}.get(scripted)
        if _steam is not None:
            args["env"]["scripted_opponent"] = 1
            args["env"]["scripted_opponent_team"] = _steam
            args["env"]["scripted_opponent_type"] = scripted_type
        args["load_model_path"] = ckpt_a
        if seed is not None:
            args["env"]["seed"] = seed

        self.p = tp.PuffeRL.create_pufferl(args)   # vec + policy A wired
        self.device = self.p.device
        self.gpu = self.p.gpu
        self.vec = self.p._vec
        self.obs = self.p.vec_obs                  # (2,2782) view (cpu or cuda)
        self.mask = self.p.vec_action_mask         # (2,454) HOST view
        self.terms = self.p.vec_terminals

        self.home_team, self.away_team = home_team, away_team
        pol_b = copy.deepcopy(self.p.policy)
        sd = torch.load(ckpt_b, map_location=self.device)
        sd = {k.replace("module.", ""): v for k, v in sd.items()}
        pol_b.load_state_dict(sd)
        pol_b.eval()
        self.pols = {"a": self.p.policy.eval(), "b": pol_b}
        short = lambda p: p.split("/")[-1].replace("_torch", "").replace(".bin", "")
        self.names = {"a": short(ckpt_a), "b": short(ckpt_b)}
        self.game_no = 0
        self._win_prob_cache = 0.5
        self._new_game()

    def _new_game(self):
        self.game_no += 1
        self.home_key = "a" if self.game_no % 2 == 1 else "b"
        self.away_key = "b" if self.home_key == "a" else "a"
        self.state_h = self.pols[self.home_key].initial_state(1, self.device)
        self.state_a = self.pols[self.away_key].initial_state(1, self.device)
        self.first_blood_done = False
        self.teamstats = TeamStatsAccumulator()
        self.active_actor = None
        self.active_kind = None
        self.move_used = {}
        self.pending_blitz = None
        self.match_id = f"m_{int(time.time())}_{self.game_no}"

    # -- protocol message builders -------------------------------------------
    def _home_obs_bytes(self):
        t = self.obs[0]
        return bytes(t.cpu().numpy()) if self.gpu else bytes(t.numpy())

    def match_start_msg(self):
        st = dec.decode_state(self._home_obs_bytes())
        tag_positions(st["players"], self.home_team, self.away_team)
        hr = _ROSTERS[self.home_team]["name"] if 0 <= self.home_team < 30 else "procgen"
        ar = _ROSTERS[self.away_team]["name"] if 0 <= self.away_team < 30 else "procgen"
        # Scripted teams are tied to the board side (home/away), not the policy
        # key — label them "cage-bot" so the broadcast names what's actually playing.
        home_agent = ("cage-bot" if self.scripted in ("home", "both")
                      else self.names[self.home_key])
        away_agent = ("cage-bot" if self.scripted in ("away", "both")
                      else self.names[self.away_key])
        return {"t": "match_start", "match_id": self.match_id,
                "home": {"name": f"{hr} ({home_agent})", "roster": hr,
                         "color": TEAM_COLORS.get(hr, "#8b1a1a"),
                         "agent": home_agent},
                "away": {"name": f"{ar} ({away_agent})", "roster": ar,
                         "color": TEAM_COLORS.get(ar, "#1a4d8b"),
                         "agent": away_agent},
                "players": st["players"]}

    def snapshot_msg(self):
        st = dec.decode_state(self._home_obs_bytes())
        tag_positions(st["players"], self.home_team, self.away_team)
        st.update({"t": "snapshot", "match_id": self.match_id,
                   "win_prob": self._win_prob_cache,
                   "teamstats": self.teamstats.snapshot()})
        return st

    def _actor_for_action(self, atype, aarg, pre_ctx):
        if atype == BB_A_ACTIVATE and isinstance(aarg, int) and 0 <= aarg < 32:
            return aarg
        if atype in (BB_A_STEP, BB_A_STAND_UP, BB_A_JUMP, BB_A_BLOCK_TARGET,
                     BB_A_PASS_TARGET, BB_A_HANDOFF_TARGET, BB_A_FOUL_TARGET):
            if pre_ctx.get("proc") == BB_PROC_MOVE and pre_ctx.get("a") is not None:
                return pre_ctx["a"]
        if atype == BB_A_CHOOSE_DIE and pre_ctx.get("proc") == BB_PROC_BLOCK:
            return pre_ctx.get("a")
        return self.active_actor

    def _choose_die_count(self, mask_row):
        if not mask_row:
            return None
        start = ACT_SIZES[0]
        # CHOOSE_DIE offers arg 0..ndice-1. The factored mask can contain
        # other arg values for unusual states, so only trust the block-die band.
        n = 0
        for i in range(3):
            try:
                if mask_row[start + i]:
                    n += 1
            except IndexError:
                return None
        return n or None

    def _infer_d6_tests(self, pre, post, pre_obs, atype, asq, actor):
        if not isinstance(actor, int) or asq >= dec.PITCH_W * dec.PITCH_H:
            return []
        side = _side_from_actor(actor, "home")
        mover = _player_by_slot(pre, actor)
        after = _player_by_slot(post, actor)
        if not mover or not after:
            return []
        to_x, to_y = dec.sq_xy(asq)
        tests = []

        def append(label, target, ok, note=None):
            tests.append(_d6_dice(label, target, ok, actor, note=note))

        if atype == BB_A_BLOCK_TARGET and self.active_kind == "BLITZ":
            used = self.move_used.get(actor, 0)
            ma = (mover.get("stats") or {}).get("ma", 0)
            if used >= ma:
                target = _gfi_target(pre, pre_obs, mover, mover.get("x", -1),
                                     mover.get("y", -1), is_blitz=True)
                append("GFI", target, _standing_on_pitch(after),
                       note="rush-to-block; exact die face is not exposed")
            return tests

        if atype != BB_A_STEP:
            return []

        reached_target = _materially_moved_to(after, to_x, to_y)
        if not reached_target:
            # Tentacles and similar pre-move interrupts can cancel a step before
            # the mover rolls the advertised dodge/rush tests. No roll was made.
            return []

        used = self.move_used.get(actor, 0)
        ma = (mover.get("stats") or {}).get("ma", 0)
        gfi = used >= ma
        dodge = int(pre_obs[actor * 24 + 23]) > 0
        pickup = (pre.get("ball") or {}).get("state") == "on_ground" and [
            to_x, to_y] == [(pre.get("ball") or {}).get("x"), (pre.get("ball") or {}).get("y")]

        # Rush resolves before dodge; a failed rush prevents later tests.
        if gfi:
            if _stance_down(after):
                append("GFI", _gfi_target(pre, pre_obs, mover, to_x, to_y),
                       False, note="exact die face is not exposed")
                return tests
            append("GFI", _gfi_target(pre, pre_obs, mover, to_x, to_y),
                   True, note="exact die face is not exposed")

        # If a rush and dodge both happened and the player ends down, the
        # Python stream cannot distinguish "rush succeeded, dodge failed" from
        # "rush failed" because the engine does not export the consumed TEST
        # return. The branch above conservatively assigns the down result to
        # the first test in engine order.
        if dodge:
            if _stance_down(after):
                append("Dodge", _dodge_target(pre, pre_obs, mover, to_x, to_y, side),
                       False, note="exact die face is not exposed")
                return tests
            append("Dodge", _dodge_target(pre, pre_obs, mover, to_x, to_y, side),
                   True, note="exact die face is not exposed")

        if pickup:
            held = ((post.get("ball") or {}).get("state") == "held"
                    and (post.get("ball") or {}).get("carrier") == actor)
            append("Pickup", _pickup_target(pre, pre_obs, mover, to_x, to_y, side),
                   held, note=("No Ball auto-fail; no D6 was rolled"
                               if _has_skill(mover, SK_NO_BALL)
                               else "exact die face is not exposed"))
        return tests

    def _infer_block_dice(self, pre, post, post_ctx, pre_ctx, action, mask_row,
                          deciding_home):
        if action.get("type") != "CHOOSE_DIE" or pre_ctx.get("proc") != BB_PROC_BLOCK:
            return None
        att, defender = pre_ctx.get("a"), pre_ctx.get("b")
        if att is None or defender is None:
            return None
        ndice = self._choose_die_count(mask_row) or 1
        red = (_side_from_actor(att) != ("home" if deciding_home else "away"))
        return {
            "kind": "block",
            "label": "Block",
            "rolls": None,
            "picked": action.get("die_index"),
            "result": _block_result(pre, post, post_ctx, att, defender),
            "ndice": ndice,
            "tier": _block_tier_label(ndice, red),
            "red": red,
            "attacker": att,
            "defender": defender,
            "source": DICE_SOURCE_INFERRED,
            "note": "block die faces are stored inside the engine frame and are not exposed to the Python stream",
        }

    def _declare_feed(self, action, side):
        if action.get("type") != "DECLARE":
            return None
        kind = str(action.get("kind") or "ACTION").upper()
        k = _norm_test_kind(kind) or kind.lower().replace(" ", "_")
        if k not in ("move", "block", "blitz", "pass", "handoff", "foul"):
            k = "move"
        return {"kind": k, "side": side,
                "text": f"{_actor_text(action.get('actor'))} starts {kind}"}

    def _finish_blitz_if_needed(self, pre, post, action, feed):
        if not self.pending_blitz:
            return
        actor = self.pending_blitz.get("actor")
        if self.pending_blitz.get("block_thrown"):
            self.pending_blitz = None
            return
        after = _player_by_slot(post, actor)
        ended = (
            action.get("type") in ("END_ACTIVATION", "END_TURN")
            or post.get("active_team") != pre.get("active_team")
            or (after and _stance_down(after))
        )
        if ended:
            feed.append({"kind": "blitz", "side": self.pending_blitz.get("side"),
                         "text": f"{_actor_text(actor)} blitz ends: no block thrown"})
            self.pending_blitz = None

    def _update_stream_state(self, pre, post, atype, action, actor):
        if action.get("type") == "ACTIVATE":
            self.active_actor = actor
            self.active_kind = None
            if isinstance(actor, int):
                self.move_used[actor] = 0
            return
        if action.get("type") == "DECLARE":
            self.active_kind = str(action.get("kind") or "").upper()
            if self.active_kind == "BLITZ":
                self.pending_blitz = {"actor": self.active_actor,
                                      "side": _side_from_actor(self.active_actor),
                                      "block_thrown": False}
            return
        if action.get("type") == "STAND_UP" and isinstance(actor, int):
            before, after = _player_by_slot(pre, actor), _player_by_slot(post, actor)
            if before and after and before.get("stance") == "prone" and after.get("stance") == "standing":
                ma = (before.get("stats") or {}).get("ma", 0)
                self.move_used[actor] = self.move_used.get(actor, 0) + min(3, ma)
        if action.get("type") == "MOVE" and isinstance(actor, int):
            before, after = _player_by_slot(pre, actor), _player_by_slot(post, actor)
            if before and after and (before.get("x"), before.get("y")) != (after.get("x"), after.get("y")):
                self.move_used[actor] = self.move_used.get(actor, 0) + 1
        if action.get("type") == "JUMP" and isinstance(actor, int):
            before, after = _player_by_slot(pre, actor), _player_by_slot(post, actor)
            if before and after and (before.get("x"), before.get("y")) != (after.get("x"), after.get("y")):
                self.move_used[actor] = self.move_used.get(actor, 0) + 2
        if (action.get("type") == "BLOCK" and self.active_kind == "BLITZ"
                and isinstance(actor, int)):
            self.move_used[actor] = self.move_used.get(actor, 0) + 1
        if action.get("type") in ("END_ACTIVATION", "END_TURN") or post.get("active_team") != pre.get("active_team"):
            self.active_actor = None
            self.active_kind = None

    # -- one engine decision ---------------------------------------------------
    @_torch_no_grad()
    def step(self):
        home_obs = self._home_obs_bytes()
        pre = dec.decode_state(home_obs)
        pre_ctx = _ctx_from_obs(home_obs)
        deciding_home = bool(home_obs[dec.CTX + 10])

        o = torch.as_tensor(self.obs, device=self.device)
        m = torch.as_tensor(self.mask, device=self.device).clone()
        mask_row_t = m[0 if deciding_home else 1].detach().cpu()
        mask_row = mask_row_t.numpy().astype(int).tolist()

        lg_h, val_h, self.state_h = self.pols[self.home_key].forward_eval(
            o[[0]], self.state_h)
        lg_a, _val_a, self.state_a = self.pols[self.away_key].forward_eval(
            o[[1]], self.state_a)
        lg_h = tp.apply_action_mask(lg_h, m[[0]], ACT_SIZES)
        lg_a = tp.apply_action_mask(lg_a, m[[1]], ACT_SIZES)
        if getattr(self, "greedy", True):
            act_h, act_a = greedy_logits(lg_h), greedy_logits(lg_a)
        else:
            act_h, _, _ = tp.sample_logits(lg_h)
            act_a, _, _ = tp.sample_logits(lg_a)

        lg = lg_h if deciding_home else lg_a
        act_raw = (act_h if deciding_home else act_a).reshape(-1).tolist()
        atype, aarg, asq = int(act_raw[0]), int(act_raw[1]), int(act_raw[2])
        ego_sq = asq
        if not deciding_home:
            atype, aarg, asq = dec.unmirror_action(atype, aarg, asq)
        actor_hint = self._actor_for_action(atype, aarg, pre_ctx)

        probs_type = torch.softmax(lg[0].float(), -1).reshape(-1)
        k = min(3, max(1, int((probs_type > 0.005).sum().item())))
        top = torch.topk(probs_type, k=k)
        cand = [[dec.ACTION_TYPES.get(int(i), str(int(i))), round(float(p), 3)]
                for p, i in zip(top.values, top.indices) if float(p) > 0.005]

        ev = None
        if atype == 12 and ego_sq < 390:                # BLOCK declaration
            src = home_obs if deciding_home else bytes(
                self.obs[1].cpu().numpy() if self.gpu else self.obs[1].numpy())
            ev = dec.block_ev_for_square(src, *dec.sq_xy(ego_sq))

        self._win_prob_cache = round(float(torch.sigmoid(val_h.reshape(-1).float())[0]), 3)

        action_t = torch.cat([act_h, act_a], 0)
        flat = tp._actions_for_vec_step(action_t)
        if self.gpu:
            flat = flat.cuda()
            self.vec.gpu_step(flat.data_ptr())
            torch.cuda.synchronize()
        else:
            self.vec.cpu_step(flat.data_ptr())

        t = self.terms
        ended = bool(float(t[0]) > 0 or float(t[1]) > 0)
        post_obs = self._home_obs_bytes()
        post = dec.decode_state(post_obs)
        post_ctx = _ctx_from_obs(post_obs)
        msg = self._delta(pre, post, home_obs, pre_ctx, post_ctx, atype, aarg,
                          asq, cand, ev, deciding_home, actor_hint, mask_row)
        self._update_stream_state(pre, post, atype, msg.get("action") or {}, actor_hint)

        if ended:
            end = {"t": "match_end", "score": pre["score"],
                   "winner": ("home" if pre["score"][0] > pre["score"][1] else
                              "away" if pre["score"][1] > pre["score"][0] else "draw"),
                   "next_match_in_s": 6}
            self._new_game()
            return msg, end
        return msg, None

    def _delta(self, pre, post, pre_obs, pre_ctx, post_ctx, atype, aarg, asq,
               cand, ev, deciding_home, actor_hint, mask_row):
        moves, feed = [], []
        side = "home" if deciding_home else "away"
        for a, b in zip(pre["players"], post["players"]):
            if (a["x"], a["y"], a["stance"], a["loc"]) != (b["x"], b["y"], b["stance"], b["loc"]):
                moves.append({"slot": b["slot"], "x": b["x"], "y": b["y"],
                              "stance": (b["stance"] if b["loc"] == "pitch" else b["loc"])})
                if a["loc"] == "pitch" and b["loc"] in ("ko", "cas"):
                    kind = b["loc"]
                    e = {"kind": kind, "side": "home" if b["slot"] < 16 else "away",
                         "text": f"#{b['slot'] % 16 + 1} {'casualty!' if kind == 'cas' else 'KO’d'}"}
                    if kind == "cas" and not self.first_blood_done:
                        e["first_blood"] = True
                        self.first_blood_done = True
                    feed.append(e)
                elif a["stance"] == "standing" and b["stance"] in ("prone", "stunned"):
                    feed.append({"kind": "block",
                                 "side": "home" if b["slot"] < 16 else "away",
                                 "text": f"#{b['slot'] % 16 + 1} knocked down"})
        an = dec.ACTION_TYPES.get(atype, "?")
        if an in ("PASS", "HANDOFF"):
            feed.append({"kind": an.lower(), "side": side,
                         "text": f"{_actor_text(actor_hint)} {an.lower()}s"})
        elif an == "BLOCK":
            tx, ty = dec.sq_xy(asq) if asq < dec.PITCH_W * dec.PITCH_H else (-1, -1)
            target = next((p for p in pre.get("players") or []
                           if p.get("loc") == "pitch" and p.get("x") == tx
                           and p.get("y") == ty and p.get("side") != side), None)
            feed.append({"kind": "block", "side": side, "phase": "target",
                         "text": f"{_actor_text(actor_hint)} targets a block"
                                 + (f" on #{_slot_num(target['slot'])}" if target else "")})
        elif an == "FOUL":
            feed.append({"kind": "foul", "side": side,
                         "text": f"{_actor_text(actor_hint)} fouls"})
        if post["score"] != pre["score"]:
            who = "home" if post["score"][0] > pre["score"][0] else "away"
            feed.append({"kind": "td", "side": who, "text": "TOUCHDOWN!"})
        elif (post["active_team"] != pre["active_team"]
              and an not in ("END_TURN", "SETUP_DONE", "NONE")):
            feed.append({"kind": "turnover", "side": side, "text": "Turnover!"})

        action = dec.describe_action(atype, aarg, asq, actor_hint=actor_hint)
        if atype == BB_A_CHOOSE_DIE:
            action["die_index"] = aarg
        action["probs"] = cand
        decl = self._declare_feed(action, side)
        if decl:
            feed.append(decl)
        dice_items = self._infer_d6_tests(pre, post, pre_obs, atype, asq, actor_hint)
        block_dice = self._infer_block_dice(pre, post, post_ctx, pre_ctx, action,
                                            mask_row, deciding_home)
        if block_dice:
            dice_items.append(block_dice)
            att = block_dice.get("attacker")
            defender = block_dice.get("defender")
            if self.pending_blitz and self.pending_blitz.get("actor") == att:
                self.pending_blitz["block_thrown"] = True
            feed.append({"kind": "block", "side": _side_from_actor(att, side),
                         "text": (f"{_actor_text(att)} throws block on "
                                  f"{_actor_text(defender)}: {block_dice.get('result')}")})
        for d in dice_items:
            if d.get("kind") == "d6":
                feed.append(_d6_feed(d, _side_from_actor(d.get("actor"), side)))
        self._finish_blitz_if_needed(pre, post, action, feed)
        msg = {"t": "delta", "moves": moves, "ball": post["ball"],
               "score": post["score"] if post["score"] != pre["score"] else None,
               "turn": post["turn"] if post["turn"] != pre["turn"] else None,
               "active_team": post["active_team"],
               "action": action, "dice": (dice_items[0] if dice_items else None),
               "ev": ev,
               "win_prob": self._win_prob_cache, "feed": feed}
        if len(dice_items) > 1:
            msg["dice_seq"] = dice_items
        changed = self.teamstats.update_from_delta(msg, side)
        msg["teamstats"] = self.teamstats.snapshot() if changed else None
        return msg

    def interesting(self, msg):
        return bool(msg.get("moves") or msg.get("feed") or msg.get("ev")
                    or msg.get("score"))
