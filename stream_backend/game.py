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

import torch

from pufferlib import pufferl as pufferl_mod
from pufferlib import torch_pufferl as tp

import json
import os

import decoder as dec

ACT_SIZES = [30, 33, 391]
TEAMSTAT_SIDES = ("home", "away")
TEST_STAT_KINDS = {"dodge", "gfi", "pickup"}


def greedy_logits(logits):
    """Argmax per head — broadcast mode plays its best move, no exploration."""
    return torch.stack([lg.argmax(-1).reshape(-1) for lg in logits], -1).int()

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

        if action_type == "BLOCK":
            tier = _block_tier_from_dice(msg.get("dice"))
            if tier is None:
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
                counted_tests.add((side, "pickup"))

        if dice_kind and dice_ok is not None:
            side = _side_from_actor(action.get("actor"), default_side)
            if side in self.stats and (side, dice_kind) not in counted_tests:
                self._inc_test(side, dice_kind, dice_ok)

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
                 macro=False):
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
        return {"t": "match_start", "match_id": self.match_id,
                "home": {"name": f"{hr} ({self.names[self.home_key]})", "roster": hr,
                         "color": TEAM_COLORS.get(hr, "#8b1a1a"),
                         "agent": self.names[self.home_key]},
                "away": {"name": f"{ar} ({self.names[self.away_key]})", "roster": ar,
                         "color": TEAM_COLORS.get(ar, "#1a4d8b"),
                         "agent": self.names[self.away_key]},
                "players": st["players"]}

    def snapshot_msg(self):
        st = dec.decode_state(self._home_obs_bytes())
        tag_positions(st["players"], self.home_team, self.away_team)
        st.update({"t": "snapshot", "match_id": self.match_id,
                   "win_prob": self._win_prob_cache,
                   "teamstats": self.teamstats.snapshot()})
        return st

    # -- one engine decision ---------------------------------------------------
    @torch.no_grad()
    def step(self):
        home_obs = self._home_obs_bytes()
        pre = dec.decode_state(home_obs)
        deciding_home = bool(home_obs[dec.CTX + 10])

        o = torch.as_tensor(self.obs, device=self.device)
        m = torch.as_tensor(self.mask, device=self.device).clone()

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
        post = dec.decode_state(self._home_obs_bytes())
        msg = self._delta(pre, post, atype, aarg, asq, cand, ev, deciding_home)

        if ended:
            end = {"t": "match_end", "score": pre["score"],
                   "winner": ("home" if pre["score"][0] > pre["score"][1] else
                              "away" if pre["score"][1] > pre["score"][0] else "draw"),
                   "next_match_in_s": 6}
            self._new_game()
            return msg, end
        return msg, None

    def _delta(self, pre, post, atype, aarg, asq, cand, ev, deciding_home):
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
            feed.append({"kind": an.lower(), "side": side, "text": f"{an.title()}!"})
        elif an == "BLOCK":
            feed.append({"kind": "block", "side": side, "text": "Block thrown"})
        elif an == "FOUL":
            feed.append({"kind": "foul", "side": side, "text": "Foul!"})
        if post["score"] != pre["score"]:
            who = "home" if post["score"][0] > pre["score"][0] else "away"
            feed.append({"kind": "td", "side": who, "text": "TOUCHDOWN!"})
        elif (post["active_team"] != pre["active_team"]
              and an not in ("END_TURN", "SETUP_DONE", "NONE")):
            feed.append({"kind": "turnover", "side": side, "text": "Turnover!"})

        action = dec.describe_action(atype, aarg, asq)
        action["probs"] = cand
        msg = {"t": "delta", "moves": moves, "ball": post["ball"],
               "score": post["score"] if post["score"] != pre["score"] else None,
               "turn": post["turn"] if post["turn"] != pre["turn"] else None,
               "active_team": post["active_team"],
               "action": action, "dice": None, "ev": ev,
               "win_prob": self._win_prob_cache, "feed": feed}
        changed = self.teamstats.update_from_delta(msg, side)
        msg["teamstats"] = self.teamstats.snapshot() if changed else None
        return msg

    def interesting(self, msg):
        return bool(msg.get("moves") or msg.get("feed") or msg.get("ev")
                    or msg.get("score"))
