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

import decoder as dec

ACT_SIZES = [30, 33, 391]


class Match:
    def __init__(self, ckpt_a, ckpt_b, seed=None):
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
        self.match_id = f"m_{int(time.time())}_{self.game_no}"

    # -- protocol message builders -------------------------------------------
    def _home_obs_bytes(self):
        t = self.obs[0]
        return bytes(t.cpu().numpy()) if self.gpu else bytes(t.numpy())

    def match_start_msg(self):
        st = dec.decode_state(self._home_obs_bytes())
        return {"t": "match_start", "match_id": self.match_id,
                "home": {"name": self.names[self.home_key], "roster": "procgen",
                         "color": "#8b1a1a", "agent": self.names[self.home_key]},
                "away": {"name": self.names[self.away_key], "roster": "procgen",
                         "color": "#1a4d8b", "agent": self.names[self.away_key]},
                "players": st["players"]}

    def snapshot_msg(self):
        st = dec.decode_state(self._home_obs_bytes())
        st.update({"t": "snapshot", "match_id": self.match_id,
                   "win_prob": self._win_prob_cache})
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
        if post["score"] != pre["score"]:
            who = "home" if post["score"][0] > pre["score"][0] else "away"
            feed.append({"kind": "td", "side": who, "text": "TOUCHDOWN!"})
        elif (post["active_team"] != pre["active_team"]
              and an not in ("END_TURN", "SETUP_DONE", "NONE")):
            feed.append({"kind": "turnover", "side": side, "text": "Turnover!"})

        action = dec.describe_action(atype, aarg, asq)
        action["probs"] = cand
        return {"t": "delta", "moves": moves, "ball": post["ball"],
                "score": post["score"] if post["score"] != pre["score"] else None,
                "turn": post["turn"] if post["turn"] != pre["turn"] else None,
                "active_team": post["active_team"],
                "action": action, "dice": None, "ev": ev,
                "win_prob": self._win_prob_cache, "feed": feed}

    def interesting(self, msg):
        return bool(msg.get("moves") or msg.get("feed") or msg.get("ev")
                    or msg.get("score"))
