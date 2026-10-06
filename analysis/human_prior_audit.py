#!/usr/bin/env python
"""human_prior_audit.py: the offline audit that gates a human-prior trainer term.

Thresholds, definitions and the verdict rule are in
docs/human-prior-v1-2026-10-05.md, section 0, committed before this script
existed. This script computes the numbers and applies that rule; it does not
choose anything.

  A  held-out HUMAN states: every net at zero recurrent state, the records'
     own conditional masks.
  B  CHAIN 41's OWN states (tools/selfplay_dump.py): chain 41 as played
     (carried state), the prior at zero state, full joint distributions over
     the exact support.
  C  the same comparison between chain 41 and chain 9 (and chain 36, and
     chain 41 at zero state) on chain 41's states.

Every net, the prior included, is loaded through the play harness's
load_checkpoint from a native flat blob and run with its forward.

  <harness>/.venv/bin/python analysis/human_prior_audit.py \\
      --prior runs/x/prior_default/prior.bin --pairs-dir ... --reseat-dir ... \\
      --replay-ids runs/reseat-20261005/ids.txt --selfplay runs/x/selfplay41 \\
      --out-dir runs/x/audit
"""

import argparse
import ctypes
import glob
import json
import os
import sys
import time

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "training"))

import bc_pretrain as bc  # noqa: E402
import human_prior as hp  # noqa: E402

ACT_SIZES = hp.ACT_SIZES
T, K = hp.T, hp.K
N_BOOT = 2000
KINDS = ("BLOCK", "BLITZ", "PASS", "HANDOFF", "FOUL")
GATE_KINDS = ("BLOCK", "BLITZ")
RATIO_MIN, GAP_MIN = 1.5, 0.05
FAITHFUL = (0.80, 1.25)
U1_MIN, U2_MIN, ACT_KL_MIN = 0.20, 0.50, 0.10


# ---- bootstrap helpers ---------------------------------------------------

def _cluster_sums(clusters, *columns):
    ids, inverse = np.unique(clusters, return_inverse=True)
    return [np.bincount(inverse, weights=np.asarray(c, dtype=np.float64),
                        minlength=len(ids)) for c in columns]


def ratio_interval(num, den, clusters, seed=0):
    """sum(num) / sum(den) with a cluster-bootstrap 95% interval."""
    if len(num) == 0 or np.sum(den) == 0:
        return None
    n_sum, d_sum = _cluster_sums(clusters, num, den)
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(n_sum), size=(N_BOOT, len(n_sum)))
    boot = n_sum[pick].sum(axis=1) / np.maximum(d_sum[pick].sum(axis=1), 1e-300)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return {"value": float(np.sum(num) / np.sum(den)), "lo": float(lo), "hi": float(hi)}


def mean_interval(values, clusters, seed=0):
    """mean(values) with a cluster-bootstrap 95% interval."""
    if len(values) == 0:
        return None
    ones = np.ones(len(values))
    out = ratio_interval(values, ones, clusters, seed)
    out["n"] = int(len(values))
    return out


# ---- joint distributions over an exact support -----------------------------

def _group_logsumexp(x, group, n_groups):
    top = np.full(n_groups, -np.inf)
    np.maximum.at(top, group, x)
    total = np.bincount(group, weights=np.exp(x - top[group]), minlength=n_groups)
    return top + np.log(total)


class Support:
    """The packed joint supports of a block of decisions, grouped once."""

    def __init__(self, packed, offsets):
        packed = np.asarray(packed, dtype=np.int64)
        offsets = np.asarray(offsets, dtype=np.int64)
        self.n = len(offsets) - 1
        counts = np.diff(offsets)
        dec = np.repeat(np.arange(self.n), counts)
        # The engine can list one tuple twice (two identical push squares,
        # seen once in 60,000 decisions). The sampler treats the support as a
        # set, so a duplicate must not carry mass twice.
        key = np.unique(dec * (1 << 30) + packed)
        self.dec, packed = key >> 30, key & ((1 << 30) - 1)
        self.duplicates = int(len(dec) - len(key))
        self.type = packed & 1023
        self.arg = (packed >> 10) & 1023
        self.sq = (packed >> 20) & 1023
        key_t = self.dec * 30 + self.type
        self.uniq_t, self.inv_t = np.unique(key_t, return_inverse=True)
        key_ta = key_t * 33 + self.arg
        self.uniq_ta, self.inv_ta = np.unique(key_ta, return_inverse=True)
        self.ta_group = np.searchsorted(self.uniq_t, self.uniq_ta // 33)
        self.family = hp.action_family(self.type, self.arg)

    def joint_logp(self, logits):
        """log p of every support tuple under the sequential exact-joint sampler
        (type, then arg given type, then square given type and arg)."""
        logits = np.asarray(logits, dtype=np.float64)
        ut_dec, ut_type = self.uniq_t // 30, self.uniq_t % 30
        z_type = _group_logsumexp(logits[ut_dec, ut_type], ut_dec, self.n)
        lp_type = logits[self.dec, self.type] - z_type[self.dec]
        uta_dec, uta_arg = self.uniq_ta // 990, self.uniq_ta % 33
        z_arg = _group_logsumexp(
            logits[uta_dec, 30 + uta_arg], self.ta_group, len(self.uniq_t))
        lp_arg = logits[self.dec, 30 + self.arg] - z_arg[self.inv_t]
        sq_logit = logits[self.dec, 63 + self.sq]
        z_sq = _group_logsumexp(sq_logit, self.inv_ta, len(self.uniq_ta))
        return lp_type + lp_arg + (sq_logit - z_sq[self.inv_ta])

    def kl(self, lp, lq):
        """KL(p || q) per decision."""
        return np.bincount(self.dec, weights=np.exp(lp) * (lp - lq), minlength=self.n)

    def mass(self, lp, select):
        """Probability mass per decision on the tuples where `select` holds."""
        return np.bincount(self.dec[select], weights=np.exp(lp[select]), minlength=self.n)

    def family_mass(self, lp):
        key = self.dec * len(hp.FAMILIES) + self.family
        return np.bincount(key, weights=np.exp(lp),
                           minlength=self.n * len(hp.FAMILIES)
                           ).reshape(self.n, len(hp.FAMILIES))

    def type_sets(self):
        """Bitmask of the legal action types of each decision."""
        bits = np.zeros(self.n, dtype=np.int64)
        np.bitwise_or.at(bits, self.uniq_t // 30, 1 << (self.uniq_t % 30))
        return bits


def context_name(bits):
    return "|".join(hp.ACTION_NAMES[i] for i in range(30) if (int(bits) >> i) & 1)


# ---- part A: human states ----------------------------------------------------

def audit_human(nets, data, out):
    scored = {}
    for name, policy in nets.items():
        print(f"A: scoring {name} on {len(data)} held-out human records", flush=True)
        scored[name] = hp.collect(policy, data, keep_probs=True, progress=f"A/{name}")
    ref = scored["prior"]
    replay, family = ref["replay"], ref["family"]
    human_type, human_arg = ref["type"], ref["arg"]
    n = len(replay)
    declare = human_type == T["DECLARE"]
    # A declaration is always the only legal type, so wherever DECLARE is
    # legal the human chose it and the argument mask is the full kind mask.
    declare_legal = ref["mask_type"][:, T["DECLARE"]]
    assert np.array_equal(declare, declare_legal), "DECLARE legal but not chosen"
    assert np.all(ref["mask_type"][declare].sum(axis=1) == 1)
    uniform_lp = -(np.log(ref["nlegal0"]) + np.log(ref["nlegal1"]) + np.log(ref["nlegal2"]))

    lp = {k: s["lp0"] + s["lp1"] + s["lp2"] for k, s in scored.items()}
    exact = {k: s["hit0"] & s["hit1"] & s["hit2"] for k, s in scored.items()}

    # A1: per family, P(net picks the human's action), and the usable-target rule.
    a1 = {}
    for i, fam in enumerate(hp.FAMILIES + ("ALL",)):
        sel = np.ones(n, dtype=bool) if fam == "ALL" else family == i
        if not sel.any():
            continue
        row = {"n": int(sel.sum())}
        for k in scored:
            row[k] = {"mean_p_human": float(np.exp(lp[k][sel]).mean()),
                      "argmax_exact": float(exact[k][sel].mean()),
                      "mean_logp": float(lp[k][sel].mean())}
        row["uniform_mean_logp"] = float(uniform_lp[sel].mean())
        row["u1_prior_minus_chain41"] = mean_interval(
            (lp["prior"] - lp["chain41"])[sel], replay[sel])
        row["u2_prior_minus_uniform"] = mean_interval(
            (lp["prior"] - uniform_lp)[sel], replay[sel])
        u1, u2 = row["u1_prior_minus_chain41"], row["u2_prior_minus_uniform"]
        row["usable_target"] = bool(
            u1["value"] >= U1_MIN and u1["lo"] > 0 and u2["value"] >= U2_MIN)
        a1[fam] = row
    out["A1_by_family"] = a1

    # A2: marginal family rates, humans against each net's expected mass.
    fam_of_type = hp.action_family(np.arange(30), np.zeros(30, dtype=np.int64))
    kind_family = hp.action_family(np.full(33, T["DECLARE"]), np.arange(33))
    a2 = {"human": np.bincount(family, minlength=len(hp.FAMILIES)) / n}
    for k, s in scored.items():
        mass = np.zeros(len(hp.FAMILIES))
        p_type = s["p_type"].astype(np.float64)
        for t in range(30):
            if t == T["DECLARE"]:
                continue
            mass[fam_of_type[t]] += p_type[:, t].sum()
        p_kind = s["p_arg"][declare].astype(np.float64)
        for a in range(33):
            mass[kind_family[a]] += p_kind[:, a].sum()
        a2[k] = mass / n
    out["A2_family_rates"] = {
        "families": list(hp.FAMILIES),
        **{k: [float(x) for x in v] for k, v in a2.items()}}

    # A3: declaration kinds where legal.
    a3 = {}
    for kind in KINDS:
        legal = declare & ref["mask_arg"][:, K[kind]]
        if not legal.any():
            continue
        chose = (human_arg == K[kind]) & legal
        row = {"n_legal": int(legal.sum()),
               "replays": int(len(np.unique(replay[legal]))),
               "human_rate": mean_interval(chose[legal].astype(float), replay[legal])}
        for k, s in scored.items():
            p = s["p_arg"][legal, K[kind]].astype(np.float64)
            top = s["p_arg"][legal].argmax(axis=1) == K[kind]
            row[k] = {"rate_t1": mean_interval(p, replay[legal]),
                      "rate_argmax": float(top.mean())}
            row[f"human_over_{k}"] = ratio_interval(
                chose[legal].astype(float), p, replay[legal])
        row["prior_over_human"] = ratio_interval(
            scored["prior"]["p_arg"][legal, K[kind]].astype(np.float64),
            chose[legal].astype(float), replay[legal])
        a3[kind] = row
    out["A3_declarations_where_legal"] = a3
    out["A3_declarations"] = {
        "n": int(declare.sum()),
        "human_kind_share": {
            kind: float((human_arg[declare] == K[kind]).mean()) for kind in hp.ACT_KINDS},
        **{k: {kind: float(s["p_arg"][declare, K[kind]].mean()) for kind in hp.ACT_KINDS}
           for k, s in scored.items()}}

    # A4: ending the turn while a player could still be activated.
    both = ref["mask_type"][:, T["ACTIVATE"]] & ref["mask_type"][:, T["END_TURN"]]
    ended = (human_type == T["END_TURN"]) & both
    a4 = {"n": int(both.sum()),
          "human_rate": mean_interval(ended[both].astype(float), replay[both])}
    for k, s in scored.items():
        p = s["p_type"][both, T["END_TURN"]].astype(np.float64)
        a4[k] = {"rate_t1": mean_interval(p, replay[both]),
                 "rate_argmax": float((s["p_type"][both].argmax(axis=1) == T["END_TURN"]).mean())}
    out["A4_end_turn_with_players_left"] = a4

    # Opportunity: how often a declaration offers the kind, per team turn.
    agent = ref_agent(data, n)
    key = (replay * 2 + agent) * 1000 + ref["half"] * 20 + ref["turn"]
    in_turn = declare & (ref["turn"] >= 1)
    out["A5_opportunity"] = opportunity(
        key[in_turn], ref["mask_arg"][in_turn], human_arg[in_turn])

    # ---- D: added after the first read of the gate (NOT pre-registered) ----
    # D1: follow-through. The decision right after a Block declaration: throw
    # the block or end the activation without throwing it.
    n_types = ref["mask_type"].sum(axis=1)
    follow = (n_types == 2) & ref["mask_type"][:, T["BLOCK_TARGET"]] & ref[
        "mask_type"][:, T["END_ACTIVATION"]]
    d1 = {"n": int(follow.sum()),
          "human_rate": mean_interval(
              (human_type[follow] == T["END_ACTIVATION"]).astype(float), replay[follow])}
    for k, s in scored.items():
        d1[k] = {"rate_t1": mean_interval(
            s["p_type"][follow, T["END_ACTIVATION"]].astype(np.float64), replay[follow])}
    out["D1_declared_block_then_no_block_human_states"] = d1
    # D2: an activation that ends at once: the record after a declaration, by
    # the same coach in the same replay, is END_ACTIVATION.
    nxt = np.r_[(replay[1:] == replay[:-1]) & (agent[1:] == agent[:-1]), False]
    next_type = np.r_[human_type[1:], -1]
    d2 = {}
    for kind in ("MOVE", "BLOCK", "BLITZ", "PASS"):
        sel = declare & (human_arg == K[kind]) & nxt
        d2[kind] = {"n": int(sel.sum()), "ended_at_once": float(
            (next_type[sel] == T["END_ACTIVATION"]).mean()) if sel.any() else None}
    out["D2_empty_activations_human"] = d2
    # D3: the shape of a team turn.
    both = ref["mask_type"][:, T["ACTIVATE"]] & ref["mask_type"][:, T["END_TURN"]]
    turns = len(np.unique(key[in_turn]))
    out["D3_team_turn_human"] = {
        "team_turns": int(turns),
        "activations_per_turn": float(in_turn.sum() / turns),
        "voluntary_end_with_players_left_per_turn": float(
            ((human_type == T["END_TURN"]) & both & (ref["turn"] >= 1)).sum() / turns),
        "note": "turns are counted from the declarations present; a turn cut by a "
                "lockstep stop is counted with the decisions it has"}
    return scored


_AGENT_CACHE = {}


def ref_agent(data, n):
    """The agent byte of every record, in iteration order."""
    if id(data) not in _AGENT_CACHE:
        _AGENT_CACHE[id(data)] = np.concatenate(
            [np.asarray(r["agent"], dtype=np.int64) for r in data.iter_record_batches(4096)])
    agent = _AGENT_CACHE[id(data)]
    assert len(agent) == n
    return agent


def opportunity(turn_key, kind_mask, declared):
    """Per team turn: declarations, how many offered each kind, how many took it."""
    turns = len(np.unique(turn_key))
    out = {"team_turns": int(turns), "declarations_per_turn": float(len(turn_key) / turns)}
    for kind in KINDS:
        legal = kind_mask[:, K[kind]]
        out[kind] = {
            "legal_share_of_declarations": float(legal.mean()),
            "legal_per_turn": float(legal.sum() / turns),
            "declared_per_turn": float((declared == K[kind]).sum() / turns)}
    return out


# ---- parts B and C: chain 41's own states --------------------------------------

def audit_selfplay(prior, chain41, dump_dir, out, harness):
    manifest = json.load(open(os.path.join(dump_dir, "manifest.json")))
    names = manifest["policies"]              # actor, then the shadows
    E = harness.E
    match_size = manifest["match_size"]
    assert match_size == ctypes.sizeof(E.BbMatch)
    half_off = E.BbMatch.half.offset
    turn_off = E.BbMatch.turn.offset
    cols = {}

    def add(key, value):
        cols.setdefault(key, []).append(value)

    pairs = [("prior", "chain41")] + [(n, "chain41") for n in names[1:]] + [
        ("chain41_zero_state", "chain41")]
    examples_pool = []
    chunks = sorted(glob.glob(os.path.join(dump_dir, "chunk_*.npz")))
    for ci, path in enumerate(chunks):
        z = np.load(path)
        obs, meta, action = z["obs"], z["meta"], z["action"].astype(np.int64)
        n = len(obs)
        sup = Support(z["support"], z["support_off"])
        logits = {"chain41": z["logits"][:, 0]}
        for j, name in enumerate(names[1:], start=1):
            logits[name] = z["logits"][:, j]
        obs_t = torch.from_numpy(obs)
        zero = {"prior": prior, "chain41_zero_state": chain41}
        for name, policy in zero.items():
            rows = [hp.forward_logits(policy, obs_t[i:i + 4096]).numpy()
                    for i in range(0, n, 4096)]
            logits[name] = np.concatenate(rows)
        lp = {name: sup.joint_logp(lg) for name, lg in logits.items()}
        bits = sup.type_sets()
        add("context", bits)
        add("game", meta[:, 0].astype(np.int64))
        add("c_step", meta[:, 1].astype(np.int64))
        add("seat", meta[:, 2].astype(np.int64))
        match = z["match"]
        seat = meta[:, 2].astype(np.int64)
        add("half", match[:, half_off].astype(np.int64))
        add("turn", match[np.arange(n), turn_off + seat].astype(np.int64))
        chosen = (sup.type == action[sup.dec, 0]) & (sup.arg == action[sup.dec, 1]) & (
            sup.sq == action[sup.dec, 2])
        assert chosen.sum() == n, "a sampled action is missing from its support"
        add("action_type", action[:, 0])
        add("action_arg", action[:, 1])
        for a, b in pairs:
            add(f"kl_{a}__{b}", sup.kl(lp[a], lp[b]))
            add(f"kl_{b}__{a}", sup.kl(lp[b], lp[a]))
        is_declare = sup.type == T["DECLARE"]
        for name in logits:
            add(f"fam_{name}", sup.family_mass(lp[name]))
            add(f"p_end_turn_{name}", sup.mass(lp[name], sup.type == T["END_TURN"]))
            add(f"p_end_activation_{name}",
                sup.mass(lp[name], sup.type == T["END_ACTIVATION"]))
            for kind in KINDS:
                add(f"p_{kind}_{name}", sup.mass(lp[name], is_declare & (sup.arg == K[kind])))
            add(f"lp_action_{name}", lp[name][chosen][np.argsort(sup.dec[chosen])])
        for kind in KINDS:
            legal = np.zeros(n, dtype=bool)
            legal[sup.dec[is_declare & (sup.arg == K[kind])]] = True
            add(f"legal_{kind}", legal)
        sym = sup.kl(lp["prior"], lp["chain41"]) + sup.kl(lp["chain41"], lp["prior"])
        add("sym", sym)
        add("chunk", np.full(n, ci))
        add("row", np.arange(n))
        print(f"B: chunk {ci + 1}/{len(chunks)} ({n} decisions)", flush=True)
        del z
    c = {k: np.concatenate(v) for k, v in cols.items()}
    n = len(c["game"])
    game = c["game"]
    declare_ctx = c["context"] == (1 << T["DECLARE"])
    out["B_counts"] = {"decisions": int(n), "games": int(len(np.unique(game))),
                       "declarations": int(declare_ctx.sum())}

    # Gate B and anchor C: declaration kinds where legal.
    others = ["prior"] + names[1:] + ["chain41_zero_state"]
    b1 = {}
    for kind in KINDS:
        legal = declare_ctx & c[f"legal_{kind}"]
        if not legal.any():
            continue
        g = game[legal]
        sampled = (c["action_type"][legal] == T["DECLARE"]) & (
            c["action_arg"][legal] == K[kind])
        row = {"n_legal": int(legal.sum()),
               "chain41_sampled_rate": float(sampled.mean()),
               "chain41": {"rate_t1": mean_interval(c[f"p_{kind}_chain41"][legal], g)}}
        for name in others:
            row[name] = {"rate_t1": mean_interval(c[f"p_{kind}_{name}"][legal], g)}
            row[f"{name}_over_chain41"] = ratio_interval(
                c[f"p_{kind}_{name}"][legal], c[f"p_{kind}_chain41"][legal], g)
        b1[kind] = row
    out["B1_declarations_where_legal"] = b1

    both = (c["context"] == ((1 << T["ACTIVATE"]) | (1 << T["END_TURN"])))
    b2 = {"n": int(both.sum()),
          "chain41_sampled_rate": float((c["action_type"][both] == T["END_TURN"]).mean())}
    for name in ["chain41"] + others:
        b2[name] = {"rate_t1": mean_interval(c[f"p_end_turn_{name}"][both], game[both])}
    out["B2_end_turn_with_players_left"] = b2

    # Family mass on chain 41's states: what it did against what each net wants.
    sampled_family = hp.action_family(c["action_type"], c["action_arg"])
    out["B3_family_rates"] = {
        "families": list(hp.FAMILIES),
        "chain41_sampled": [float(x) for x in
                            np.bincount(sampled_family, minlength=len(hp.FAMILIES)) / n],
        **{name: [float(x) for x in c[f"fam_{name}"].mean(axis=0)]
           for name in ["chain41"] + others}}

    # KL by decision context.
    contexts, inverse = np.unique(c["context"], return_inverse=True)
    rows = []
    for i, bits in enumerate(contexts):
        sel = inverse == i
        row = {"context": context_name(bits), "n": int(sel.sum()),
               "share_of_decisions": float(sel.mean()),
               "sym_kl_sum_prior": float(c["sym"][sel].sum())}
        for a, b in pairs:
            row[f"kl_{a}__{b}"] = mean_interval(c[f"kl_{a}__{b}"][sel], game[sel])
            row[f"kl_{b}__{a}"] = mean_interval(c[f"kl_{b}__{a}"][sel], game[sel])
        row["would_act"] = bool(row["kl_prior__chain41"]["value"] >= ACT_KL_MIN)
        rows.append(row)
    rows.sort(key=lambda r: -r["sym_kl_sum_prior"])
    out["B4_kl_by_context"] = rows
    overall = {"n": int(n)}
    for a, b in pairs:
        overall[f"kl_{a}__{b}"] = mean_interval(c[f"kl_{a}__{b}"], game)
        overall[f"kl_{b}__{a}"] = mean_interval(c[f"kl_{b}__{a}"], game)
    out["B4_kl_overall"] = overall
    out["B4_log_p_of_chain41_action"] = {
        name: float(c[f"lp_action_{name}"].mean()) for name in ["chain41"] + others}

    # Opportunity per team turn on chain 41's own games.
    in_turn = declare_ctx & (c["turn"] >= 1)
    key = (game * 2 + c["seat"]) * 1000 + c["half"] * 20 + c["turn"]
    kind_mask = np.zeros((int(in_turn.sum()), 33), dtype=bool)
    for kind in KINDS:
        kind_mask[:, K[kind]] = c[f"legal_{kind}"][in_turn]
    out["B5_opportunity"] = opportunity(key[in_turn], kind_mask, c["action_arg"][in_turn])
    out["B5_opportunity"]["decisions_per_game"] = float(n / len(np.unique(game)))

    # ---- D: added after the first read of the gate (NOT pre-registered) ----
    follow = c["context"] == ((1 << T["BLOCK_TARGET"]) | (1 << T["END_ACTIVATION"]))
    d1 = {"n": int(follow.sum()),
          "chain41_sampled_rate": float(
              (c["action_type"][follow] == T["END_ACTIVATION"]).mean())}
    for name in ["chain41"] + others:
        d1[name] = {"rate_t1": mean_interval(
            c[f"p_end_activation_{name}"][follow], game[follow])}
    out["D1_declared_block_then_no_block_own_states"] = d1
    order = np.lexsort((c["c_step"], game))
    g_s, seat_s = game[order], c["seat"][order]
    type_s, arg_s = c["action_type"][order], c["action_arg"][order]
    ctx_s = c["context"][order]
    nxt = np.r_[(g_s[1:] == g_s[:-1]) & (seat_s[1:] == seat_s[:-1]), False]
    next_type = np.r_[type_s[1:], -1]
    d2 = {}
    for kind in ("MOVE", "BLOCK", "BLITZ", "PASS"):
        sel = (ctx_s == (1 << T["DECLARE"])) & (arg_s == K[kind]) & nxt
        d2[kind] = {"n": int(sel.sum()), "ended_at_once": float(
            (next_type[sel] == T["END_ACTIVATION"]).mean()) if sel.any() else None}
    out["D2_empty_activations_chain41"] = d2
    turns = len(np.unique(key[in_turn]))
    out["D3_team_turn_chain41"] = {
        "team_turns": int(turns),
        "activations_per_turn": float(in_turn.sum() / turns),
        "voluntary_end_with_players_left_per_turn": float(
            ((c["action_type"] == T["END_TURN"]) & both & (c["turn"] >= 1)).sum() / turns)}
    # D4: how much probability each net gives the action chain 41 took. KL
    # against a near-deterministic policy is dominated by its logit scale;
    # this is the bounded reading of the same comparison.
    d4 = {}
    for i, bits in enumerate(contexts):
        sel = inverse == i
        if sel.sum() < 400:
            continue
        d4[context_name(bits)] = {"n": int(sel.sum()), **{
            name: float(np.exp(c[f"lp_action_{name}"][sel]).mean())
            for name in ["chain41"] + others}}
    d4["ALL"] = {"n": int(n), **{
        name: float(np.exp(c[f"lp_action_{name}"]).mean()) for name in ["chain41"] + others}}
    out["D4_mean_p_of_chain41_action"] = d4

    # Five examples by the registered rule.
    setup_bits = sum(1 << T[name] for name in (
        "SETUP_PLACE", "SETUP_REMOVE", "SETUP_DONE", "KICK_TARGET", "TOUCHBACK"))
    picks = []
    for row in rows:
        bits = next(b for b in contexts if context_name(b) == row["context"])
        if int(bits) & setup_bits:
            continue
        sel = np.flatnonzero(c["context"] == bits)
        order = sel[np.argsort(c["sym"][sel], kind="stable")]
        pick = order[min(len(order) - 1, int(0.9 * len(order)))]
        picks.append((row["context"], int(c["chunk"][pick]), int(c["row"][pick]),
                      float(c["sym"][pick])))
        if len(picks) == 5:
            break
    out["B6_examples"] = [
        render_example(dump_dir, chunks, ctx, ci, ri, sym, prior, harness, names)
        for ctx, ci, ri, sym in picks]
    return c


def render_example(dump_dir, chunks, ctx, ci, ri, sym, prior, harness, names):
    E = harness.E
    lib = E.load_library(os.path.join(ROOT, "build", "play_harness_probe",
                                      "libbbplay." + E.LIB_EXT), build_if_missing=False)
    z = np.load(chunks[ci])
    lo, hi = z["support_off"][ri], z["support_off"][ri + 1]
    sup = Support(z["support"][lo:hi], np.array([0, hi - lo]))
    seat = int(z["meta"][ri, 2])
    m = E.BbMatch.from_buffer_copy(z["match"][ri].tobytes())
    llo, lhi = z["legal_off"][ri], z["legal_off"][ri + 1]
    legal = z["legal"][llo:lhi]

    def player(slot):
        p = m.players[slot]
        team = slot // 16
        name = lib.bbp_position_display(int(m.team_id[team]), int(p.position_id))
        side = "own" if team == seat else "opp"
        return f"{side} {name.decode() if name else '?'} at ({p.x},{p.y})"

    def describe(t, a, s):
        hits = legal[(legal[:, 4] == a) & (legal[:, 5] == s) & (legal[:, 0] == t)]
        name = hp.ACTION_NAMES[t]
        if len(hits) == 0:
            return f"{name} arg={a} sq={s}"
        _t, arg, x, y = (int(v) for v in hits[0][:4])
        if name == "DECLARE":
            return f"declare {hp.ACT_KINDS[arg].title()}"
        if name == "ACTIVATE":
            return f"activate {player(arg)}"
        if name in ("END_TURN", "END_ACTIVATION", "STAND_UP", "DECLINE_REROLL",
                    "SETUP_DONE"):
            return name.lower().replace("_", " ")
        if name == "CHOOSE_DIE":
            return f"choose die {arg}"
        if name in ("FOLLOW_UP", "APOTHECARY", "USE_REROLL", "USE_SKILL",
                    "DECLINE_SKILL", "CHOOSE_OPTION"):
            return f"{name.lower().replace('_', ' ')} {arg}"
        target = ""
        if name in ("BLOCK_TARGET", "FOUL_TARGET", "HANDOFF_TARGET") and x < 26 and y < 15:
            slot = int(m.grid[x][y]) - 1          # grid holds slot + 1, 0 = empty
            if 0 <= slot < 32:
                target = f" ({player(slot)})"
        return f"{name.lower().replace('_', ' ')} ({x},{y}){target}"

    obs_t = torch.from_numpy(z["obs"][ri:ri + 1])
    lp_prior = sup.joint_logp(hp.forward_logits(prior, obs_t).numpy())
    lp_c41 = sup.joint_logp(z["logits"][ri:ri + 1, 0])

    def top(lp, k=3):
        order = np.argsort(-lp)[:k]
        return [{"action": describe(int(sup.type[i]), int(sup.arg[i]), int(sup.sq[i])),
                 "p": float(np.exp(lp[i]))} for i in order]

    act = [int(v) for v in z["action"][ri]]
    idx = int(np.flatnonzero((sup.type == act[0]) & (sup.arg == act[1]) & (sup.sq == act[2]))[0])
    activating = [s for s in range(32) if (m.players[s].flags >> 1) & 1]
    ball = E.BALL_STATES[m.ball.state]
    if ball == "held" and m.ball.carrier < 32:
        ball = f"held by {player(int(m.ball.carrier))}"
    elif ball == "on_ground":
        ball = f"on the ground at ({m.ball.x},{m.ball.y})"
    return {
        "context": ctx, "game": int(z["meta"][ri, 0]), "c_step": int(z["meta"][ri, 1]),
        "symmetric_kl": sym, "half": int(m.half),
        "turn_own": int(m.turn[seat]), "turn_opp": int(m.turn[1 - seat]),
        "score_own": int(m.score[seat]), "score_opp": int(m.score[1 - seat]),
        "ball": ball,
        "acting_player": player(activating[0]) if activating else None,
        "legal_tuples": int(sup.n and len(sup.type)),
        "chain41_did": describe(*act), "chain41_p_of_that": float(np.exp(lp_c41[idx])),
        "prior_p_of_that": float(np.exp(lp_prior[idx])),
        "chain41_top": top(lp_c41), "prior_top": top(lp_prior),
    }


# ---- verdict -----------------------------------------------------------------

def verdict(out):
    v = {"thresholds": {"ratio_min": RATIO_MIN, "gap_min": GAP_MIN, "faithful": FAITHFUL,
                        "u1_min": U1_MIN, "u2_min": U2_MIN, "act_kl_min": ACT_KL_MIN}}
    proceed = []
    for kind in GATE_KINDS:
        b = out["B1_declarations_where_legal"][kind]
        a = out["A3_declarations_where_legal"][kind]
        rb = b["prior_over_chain41"]
        gap_b = b["prior"]["rate_t1"]["value"] - b["chain41"]["rate_t1"]["value"]
        gate_b = bool(rb["value"] >= RATIO_MIN and rb["lo"] > 1.0 and gap_b >= GAP_MIN)
        ra = a["human_over_chain41"]
        gap_a = a["human_rate"]["value"] - a["chain41"]["rate_t1"]["value"]
        gate_a = bool(ra["value"] >= RATIO_MIN and ra["lo"] > 1.0 and gap_a >= GAP_MIN)
        fid = a["prior_over_human"]["value"]
        faithful = bool(FAITHFUL[0] <= fid <= FAITHFUL[1])
        v[kind] = {"gate_B": gate_b, "gate_B_ratio": rb, "gate_B_gap": gap_b,
                   "gate_A": gate_a, "gate_A_ratio": ra, "gate_A_gap": gap_a,
                   "prior_over_human": fid, "prior_faithful": faithful,
                   "proceed": bool(gate_b and gate_a and faithful)}
        if v[kind]["proceed"]:
            proceed.append(kind)
    if proceed:
        v["verdict"] = "PROCEED for " + " and ".join(proceed)
    elif not any(v[k]["gate_B"] for k in GATE_KINDS):
        v["verdict"] = ("HUMAN-STATES ONLY (reported as stop)"
                        if any(v[k]["gate_A"] for k in GATE_KINDS) else "STOP")
    else:
        v["verdict"] = "STOP (gate B passes but gate A or prior fidelity does not)"
    decl = next(r for r in out["B4_kl_by_context"] if r["context"] == "DECLARE")
    v["anchor_C_declarations"] = {
        "kl_prior__chain41": decl["kl_prior__chain41"]["value"],
        "kl_chain41__prior": decl["kl_chain41__prior"]["value"],
        "kl_chain9__chain41": decl["kl_chain9__chain41"]["value"],
        "kl_chain41__chain9": decl["kl_chain41__chain9"]["value"],
    }
    c = v["anchor_C_declarations"]
    v["anchor_C_prior_gap_is_larger_than_lineage_drift"] = bool(
        c["kl_prior__chain41"] >= 2 * c["kl_chain9__chain41"]
        and c["kl_chain41__prior"] >= 2 * c["kl_chain41__chain9"])
    return v


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prior", required=True, help="native blob of the prior")
    ap.add_argument("--checkpoint-dir", default=os.path.join(
        hp.DEFAULT_HARNESS, ".play-artifacts", "checkpoints"))
    ap.add_argument("--pairs-dir", required=True)
    ap.add_argument("--reseat-dir", required=True)
    ap.add_argument("--replay-ids", required=True)
    ap.add_argument("--selfplay", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--harness-root", default=hp.DEFAULT_HARNESS)
    ap.add_argument("--threads", type=int, default=4)
    args = ap.parse_args(argv)
    torch.set_num_threads(args.threads)
    os.makedirs(args.out_dir, exist_ok=True)
    harness = hp.load_harness(args.harness_root)
    t0 = time.time()

    def load(path):
        policy, prov = harness.load_checkpoint(path, kernel="native")
        return policy, prov["checkpoint_sha256"]

    blob = "0000002999975936.bin"
    nets, shas = {}, {}
    nets["prior"], shas["prior"] = load(args.prior)
    for name in ("chain41", "chain9", "chain36"):
        nets[name], shas[name] = load(os.path.join(args.checkpoint_dir, name, blob))

    replay_ids = bc.load_replay_ids(args.replay_ids)
    _train_order, holdout = hp.holdout_split(replay_ids)
    index = bc.ShardIndex.from_directory(
        args.pairs_dir, replay_ids=replay_ids, cache_size=64, reseat_dir=args.reseat_dir)
    data = bc.LazyReplayDataset(
        index, [r for r in holdout if r in set(index.nonempty_replay_ids)])
    out = {"schema": "human-prior-audit-v1", "checkpoint_sha256": shas,
           "human_subset": index.subset_label,
           "human_records": data.provenance_counts, "human_replays": len(data.replay_ids),
           "selfplay": os.path.abspath(args.selfplay)}
    print(f"human states: {index.subset_label}; {data.provenance_counts}", flush=True)
    audit_human(nets, data, out)
    index.close()
    audit_selfplay(nets["prior"], nets["chain41"], args.selfplay, out, harness)
    out["verdict"] = verdict(out)
    out["seconds"] = round(time.time() - t0, 1)
    with open(os.path.join(args.out_dir, "audit.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out["verdict"], indent=1))
    print(f"human-state numbers used: {out['human_subset']}", flush=True)


if __name__ == "__main__":
    main()
