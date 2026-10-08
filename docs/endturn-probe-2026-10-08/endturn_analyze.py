#!/usr/bin/env python3
"""Tables and readings of the END_TURN probe (PLAN.md) from accepted records.

Registered use. Nothing is computed unless every check passes:
  - the plan file hashes to --expect-sha256;
  - this script and endturn_accept.py hash to the plan's local_sha256 entries;
  - every --shard-dir is an accepted shard of the plan (endturn_accept.py:
    file hashes, provenance, integrity, exact game and seed coverage);
  - all shards ran on one engine library.

  endturn_analyze.py --plan PLAN.json --expect-sha256 H \\
      --shard-dir chain55=RUNS/et1/chain55 --shard-dir chain58=RUNS/et1/chain58 ... \\
      [--out report.txt] [--json report.json]

Smoke use, for unregistered local runs of endturn_probe.py. The records are
held to their own COMPLETE.json and the report is marked as a smoke:

  endturn_analyze.py --smoke-run chain55=DIR --smoke-run chain58=DIR

Every interval is a 95% percentile bootstrap that resamples games (engine
seeds), 2,000 replicates, generator seed 0. All checkpoints play the same seeds
and one draw of seeds is applied to all of them, so contrasts are paired by
seed. "Per decision" is a ratio estimate: each root carries the weight
(decisions of its class in its game) / (roots kept from them). Section 8 gives
every estimate and every contrast again with equal weight per game (the 29
single reward components: in the JSON summary only). Every number of a root is
computed over the same valid rollout indices as its returns.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import endturn_accept as ACCEPT  # noqa: E402

GAMMA = 0.999
REPS, BOOT_SEED = 2000, 0
DELTA, BIG = 0.02, 0.10
MIN_HALF = 8          # valid rollout indices a root needs in each half of the turn arm
MIN_PAIRS = 16        # valid rollout pairs a root needs in the forced and the match arm
BUCKETS = ("open (a0 < 0.99)", "sharp (0.99 to 0.999999)", "saturated (>= 0.999999)")
FAMILIES = {
    "block and rush charges": ("block_sequence", "block_turnover", "rush"),
    "block pay (exposure)": ("block_exposure",),
    "ball": ("distance_ball", "distance_endzone", "possession", "ball_gain", "touchdown"),
    "result and final step": ("result_winloss", "result_draw", "terminal_or_residual"),
}
CHARGES, BALL = "block and rush charges", "ball"
LOCAL_FILES = ("endturn_analyze.py", "endturn_accept.py")


def bucket(logp0):
    p = math.exp(logp0)
    return BUCKETS[2] if p >= 0.999999 else (BUCKETS[1] if p >= 0.99 else BUCKETS[0])


def turn_parts(R, B, T):
    """Reward part and discount tax of returns R with bootstraps B after T steps."""
    disc = GAMMA ** T
    return R - disc * B, (disc - 1.0) * B


def root_stats(r):
    """Everything the tables need from one root, as a flat dict; None when the
    root is dropped (the reason is counted by the caller)."""
    if "turn" not in r:
        return None, "no alternative"
    R = np.array(r["turn"]["returns"], dtype=np.float64)
    B = np.array(r["turn"]["bootstrap"], dtype=np.float64)
    T = np.array(r["turn"]["steps"], dtype=np.float64)
    n = R.shape[1]
    ok = np.isfinite(R).all(axis=0)                       # the registered drop rule: per index
    half_a, half_b = np.arange(n) < n // 2, np.arange(n) >= n // 2
    if (ok & half_a).sum() < MIN_HALF or (ok & half_b).sum() < MIN_HALF:
        return None, "too few valid rollouts"
    reward, tax = turn_parts(R, B, T)
    out = {"game": r["engine_seed"], "class": r["class"], "bucket": bucket(r["logp"][0]),
           "w": r["seen_in_game"] / max(r["kept_in_game"], 1), "dropped": float((~ok).sum())}
    d1 = (R[1] - R[0])[ok]
    out.update(td_a0=float(R[0][ok].mean() - r["root_value"]),
               d=float(d1.mean()), d_reward=float((reward[1] - reward[0])[ok].mean()),
               d_value=float((B[1] - B[0])[ok].mean()), d_tax=float((tax[1] - tax[0])[ok].mean()),
               v_a0=float(B[0][ok].mean()), steps_alt=float(T[1][ok].mean()))
    # What the first alternative's continuation did, over the same valid indices.
    more = np.array(r["turn"]["more_activations"], dtype=np.float64)[1][ok]
    out.update(more=float(more.mean()), more_none=float((more == 0).mean()),
               alt_block=float(np.array(r["turn"]["block"], dtype=np.float64)[1][ok].mean()),
               alt_steps=float(np.array(r["turn"]["own_steps"], dtype=np.float64)[1][ok].mean()))
    # Would the first alternative's margin be above zero as measured, with half the
    # discount part, and without it (behaviour and critic held fixed)?
    out.update(pos=float(out["d"] > 0), pos_half=float(out["d"] - 0.5 * out["d_tax"] > 0),
               pos_none=float(out["d"] - out["d_tax"] > 0))
    out["flip"] = out["pos_none"] - out["pos"]
    # E3: select on rollout indices 0..n/2-1, judge on n/2..n-1, as registered; an
    # index without a return is left out of its own half and the halves do not move.
    d = R[1:] - R[0:1]
    a, b = ok & half_a, ok & half_b
    best = int(np.argmax(d[:, a].mean(axis=1)))
    gb = float(d[best, b].mean())
    seb = float(d[best, b].std(ddof=1) / math.sqrt(b.sum()))
    out.update(judged=gb, better=float(gb > DELTA and gb > 2 * seb),
               big=float(gb > BIG and gb > 2 * seb), worse=float(gb < -DELTA and gb < -2 * seb))
    if "forced" in r:
        Rf_all = np.array(r["forced"]["returns"], dtype=np.float64)
        Rf = Rf_all[0]
        Bf = np.array(r["forced"]["bootstrap"], dtype=np.float64)[0]
        Tf = np.array(r["forced"]["steps"], dtype=np.float64)[0]
        okf = ok & np.isfinite(Rf_all).all(axis=0)            # the drop rule covers every forced candidate
        if okf.sum() >= MIN_PAIRS:
            rewf, taxf = turn_parts(Rf, Bf, Tf)
            out.update(f=float((Rf - R[0])[okf].mean()),
                       f_reward=float((rewf - reward[0])[okf].mean()),
                       f_value=float((Bf - B[0])[okf].mean()),
                       f_tax=float((taxf - tax[0])[okf].mean()),
                       f_share=float(np.array(r["forced"]["forced"], dtype=np.float64)[0][okf].mean()),
                       d_minus_f=float((R[1] - Rf)[okf].mean()))
    if "match" in r and r["match"]["valid_pairs"] >= MIN_PAIRS:
        m = r["match"]
        pair = np.array(m["pair_valid"], dtype=bool)
        out["wm"] = r["seen_in_game"]                         # divided by the game's match roots below
        for g, values in m["g_end"].items():
            v = np.array(values, dtype=np.float64)
            out["m_end_" + g] = float((v[1] - v[0])[pair].mean())
        gd = np.array(m["g_depth"], dtype=np.float64)
        for depth in range(gd.shape[0]):
            out[f"m_depth{depth + 1}"] = float((gd[depth, 1] - gd[depth, 0])[pair].mean())
        own, opp = np.array(m["td_own"], dtype=np.float64), np.array(m["td_opp"], dtype=np.float64)
        margin = own - opp
        out["m_td"] = float((margin[1] - margin[0])[pair].mean())
        win = (margin > 0) + 0.5 * (margin == 0)
        out["m_win"] = float((win[1] - win[0])[pair].mean())
        out["m_cmr"] = out["m_depth1"] - out["m_end_0.999"]
        end = np.array(m["g_end"]["0.999"], dtype=np.float64)
        out["m_pair_sd_end"] = float((end[1] - end[0])[pair].std(ddof=1))
        out["m_valid_share"] = m["valid_pairs"] / m["rollouts"]
        diff = np.array(m["component_diff_mean"], dtype=np.float64)   # (horizon, channel)
        out["channels_end"], out["channels_depth2"] = diff[-1], diff[1]
    return out, None


class Run:
    def __init__(self, name, directory, complete):
        self.name, self.dir, self.complete = name, directory, complete
        self.games = ACCEPT.read_jsonl(os.path.join(directory, "games.jsonl"))
        raw = ACCEPT.read_jsonl(os.path.join(directory, "roots.jsonl"))
        self.seeds = [g["engine_seed"] for g in self.games]
        self.raw_roots = len(raw)
        self.dropped = {}
        self.roots = []
        for r in raw:
            stats, why = root_stats(r)
            if stats is None:
                self.dropped[why] = self.dropped.get(why, 0) + 1
            else:
                self.roots.append(stats)
        per_game = {}
        for s in self.roots:
            if "wm" in s:
                per_game[s["game"]] = per_game.get(s["game"], 0) + 1
        for s in self.roots:
            if "wm" in s:
                s["wm"] = s["wm"] / per_game[s["game"]]
        self.channels = complete["channels"]
        for s in self.roots:
            if "channels_end" in s:
                for family, members in FAMILIES.items():
                    idx = [self.channels.index(m) for m in members]
                    s["fam_end_" + family] = float(sum(s["channels_end"][i] for i in idx))
                    s["fam_d2_" + family] = float(sum(s["channels_depth2"][i] for i in idx))
                for i, channel in enumerate(self.channels):
                    s["ch_end_" + channel] = float(s["channels_end"][i])
                    s["ch_d2_" + channel] = float(s["channels_depth2"][i])


def always(_s):
    return True


def by_class(cls):
    return lambda s: s["class"] == cls


class Estimator:
    """Estimates on one seed list and one draw of seeds shared by every run."""

    def __init__(self, seeds):
        self.seeds = seeds
        self.index = {seed: i for i, seed in enumerate(seeds)}
        self.picks = np.random.default_rng(BOOT_SEED).integers(0, len(seeds), size=(REPS, len(seeds)))
        self.per_game = []                                 # (label, estimate) for section 8

    def sums(self, run, key, weight, select):
        out = np.zeros((4, len(self.seeds)))
        for s in run.roots:
            if key in s and select(s):
                w, x = s[weight], s[key]
                out[:, self.index[s["game"]]] += (w * x, w, x, 1.0)
        return out

    def from_sums(self, sums, label=None):
        """{'point','lo','hi','boot'} per decision, and 'game': the same with equal
        weight per game over the games that have a root."""
        picks = self.picks

        def finish(point, boot):
            ok = np.isfinite(boot)
            lo, hi = np.percentile(boot[ok], [2.5, 97.5]) if ok.any() else (np.nan, np.nan)
            return {"point": float(point), "lo": float(lo), "hi": float(hi), "boot": boot,
                    "se": float(np.std(boot[ok], ddof=1)) if ok.sum() > 1 else float("nan")}
        den = sums[1][picks].sum(axis=1)
        dec = finish(sums[0].sum() / sums[1].sum() if sums[1].sum() > 0 else np.nan,
                     np.where(den > 0, sums[0][picks].sum(axis=1) / np.where(den > 0, den, 1.0), np.nan))
        has = sums[3] > 0
        means = np.where(has, sums[2] / np.where(has, sums[3], 1.0), 0.0)
        gden = has[picks].sum(axis=1)
        dec["game"] = finish(means[has].mean() if has.any() else np.nan,
                             np.where(gden > 0, means[picks].sum(axis=1) / np.where(gden > 0, gden, 1.0),
                                      np.nan))
        if label:
            self.per_game.append((label, dec["game"]))
        return dec

    def est(self, run, key, weight="w", select=always, label=None):
        return self.from_sums(self.sums(run, key, weight, select),
                              f"{run.name}: {label}" if label else None)

    def style(self, run, numerator, label=None):
        sums = np.zeros((4, len(self.seeds)))
        for g in run.games:
            x, turns = g["counts"][numerator], g["own_turns"]
            sums[:, self.index[g["engine_seed"]]] = (x, turns, x / max(turns, 1), 1.0)
        return self.from_sums(sums, f"{run.name}: {label}" if label else None)

    def combine(self, parts, label=None):
        """A linear combination [(weight, estimate), ...] on the shared draw, per
        decision and, under 'game', with equal weight per game."""
        def one(items):
            point = sum(w * e["point"] for w, e in items)
            boot = sum(w * e["boot"] for w, e in items)
            ok = np.isfinite(boot)
            lo, hi = np.percentile(boot[ok], [2.5, 97.5]) if ok.any() else (np.nan, np.nan)
            return {"point": float(point), "lo": float(lo), "hi": float(hi), "boot": boot,
                    "se": float(np.std(boot[ok], ddof=1)) if ok.sum() > 1 else float("nan")}
        out = one(parts)
        if all("game" in e for _, e in parts):
            out["game"] = one([(w, e["game"]) for w, e in parts])
            if label:
                self.per_game.append((label, out["game"]))
        return out


def fmt(e, digits=4):
    if not np.isfinite(e["point"]):
        return "n/a"
    return f"{e['point']:+.{digits}f} [{e['lo']:+.{digits}f}, {e['hi']:+.{digits}f}]"


def below(e):
    return bool(np.isfinite(e["hi"]) and e["hi"] < 0)


def above(e):
    return bool(np.isfinite(e["lo"]) and e["lo"] > 0)


def sign_word(e):
    return "entirely below zero" if below(e) else ("entirely above zero" if above(e) else "spans zero")


def brief(e):
    return {k: e[k] for k in ("point", "lo", "hi", "se")}


def default_contrasts(names):
    out = {}
    if {"chain55", "chain59"} <= set(names):
        out["seed: chain59 - chain55 (both lambda 0.95)"] = {"chain59": 1.0, "chain55": -1.0}
    if {"chain55", "chain58"} <= set(names):
        out["chain58 - chain55 (lambda 0.97 - 0.95, seed 42)"] = {"chain58": 1.0, "chain55": -1.0}
    if {"chain58", "chain59"} <= set(names):
        out["chain58 - chain59"] = {"chain58": 1.0, "chain59": -1.0}
    if {"chain55", "chain58", "chain59"} <= set(names):
        out["chain58 - mean(chain55, chain59)"] = {"chain58": 1.0, "chain55": -0.5, "chain59": -0.5}
    if {"chain59", "chain60"} <= set(names):
        out["chain60 - chain59 (lambda 0.97 - 0.95, seed 2042)"] = {"chain60": 1.0, "chain59": -1.0}
    if {"chain55", "chain58", "chain59", "chain60"} <= set(names):
        out["lambda, mean of the two seeds"] = {"chain58": 0.5, "chain55": -0.5,
                                                "chain60": 0.5, "chain59": -0.5}
        out["lambda by seed interaction"] = {"chain58": 1.0, "chain55": -1.0,
                                             "chain60": -1.0, "chain59": 1.0}
    if {"chain49", "chain55"} <= set(names):
        out["chain55 - chain49 (child - parent)"] = {"chain55": 1.0, "chain49": -1.0}
    return out


def report(runs, header, chain60_planned):
    lines, summary = list(header), {"runs": {}, "contrasts": {}, "readings": {}}
    add = lines.append
    E = Estimator(runs[0].seeds)
    by_name = {r.name: r for r in runs}
    core = {}                                              # (run, key) -> estimate, for sections 6 and 7

    add("0. Runs")
    for run in runs:
        c = run.complete
        add(f"  {run.name}: {len(run.games)} games, {run.raw_roots} root lines, "
            f"{len(run.roots)} used; dropped {run.dropped or 'none'}; rollouts lost to the decision "
            f"cap {c['capped_rollouts']}; identity roots {c['checks']['identity_roots']}; "
            f"library {c['library_sha256'][:12]}")
        add(f"      checks {c['checks']}")
        summary["runs"][run.name] = {"games": len(run.games), "root_lines": run.raw_roots,
                                     "roots_used": len(run.roots), "dropped": run.dropped,
                                     "capped_rollouts": c["capped_rollouts"]}
    add("")

    add("1. Turn arm (E1, E7, E8, E9): most probable alternative minus the action played, under the")
    add("   checkpoint's own evaluator (shaped reward to the actual end of the team turn plus its own")
    add("   critic there). Per decision.")
    for run in runs:
        acts = E.style(run, "activate", "activations per own team turn")
        ends = E.style(run, "end_turn", "END_TURN chosen per own team turn")
        core[(run.name, "activations")] = acts
        add(f"  {run.name}: activations per own team turn in these games {fmt(acts, 3)}; END_TURN "
            f"chosen per own team turn {fmt(ends, 3)}")
        summary["runs"][run.name]["turn"] = {}
        for cls in ("end_turn", "decline_block", "activate"):
            sel = by_class(cls)
            n = sum(1 for s in run.roots if sel(s))
            if not n:
                continue
            e = {k: E.est(run, k, "w", sel, f"turn arm, {cls}, {k}")
                 for k in ("d", "d_reward", "d_value", "d_tax", "v_a0", "steps_alt", "more",
                           "more_none", "td_a0", "pos", "pos_half", "pos_none", "flip", "alt_block",
                           "alt_steps", "dropped")}
            if cls == "end_turn":
                for k in ("d", "d_value", "d_tax", "flip", "more_none"):
                    core[(run.name, k)] = e[k]
            seen = sum(g["seen"][cls] for g in run.games)
            add(f"    {cls:14s} roots {n:5d} of {seen} decisions | return {fmt(e['d'])}")
            add(f"    {'':14s} = reward part {fmt(e['d_reward'])} + critic value {fmt(e['d_value'])} "
                f"+ discount on the bootstrap {fmt(e['d_tax'])}")
            add(f"    {'':14s} critic value after the action played {e['v_a0']['point']:+.3f}; alternative "
                f"runs {e['steps_alt']['point']:.1f} engine steps, holds {e['more']['point']:.2f} further "
                f"activations (none in {100 * e['more_none']['point']:.0f}% of rollouts), throws a block in "
                f"{100 * e['alt_block']['point']:.0f}% and moves {e['alt_steps']['point']:.1f} squares")
            add(f"    {'':14s} return of the action played minus the critic's value at the root "
                f"{fmt(e['td_a0'])}; rollout indices dropped per root {e['dropped']['point']:.3f}")
            add(f"    {'':14s} share of decisions with the alternative's margin above zero: as measured "
                f"{fmt(e['pos'], 3)}; with half the discount part {fmt(e['pos_half'], 3)}; without it "
                f"{fmt(e['pos_none'], 3)}; without minus as measured {fmt(e['flip'], 3)}")
            summary["runs"][run.name]["turn"][cls] = {k: brief(v) for k, v in e.items()}
    add("")

    add("2. Forced arm (E2, end_turn roots): exactly one more activation, then END_TURN, minus END_TURN now.")
    for run in runs:
        sel = by_class("end_turn")
        if not any("f" in s for s in run.roots):
            continue
        e = {k: E.est(run, k, "w", sel, f"forced arm, {k}")
             for k in ("f", "f_reward", "f_value", "f_tax", "f_share", "d_minus_f")}
        core[(run.name, "f")], core[(run.name, "d_minus_f")] = e["f"], e["d_minus_f"]
        add(f"  {run.name}: return {fmt(e['f'])} = reward part {fmt(e['f_reward'])} + critic value "
            f"{fmt(e['f_value'])} + discount {fmt(e['f_tax'])}")
        add(f"  {'':{len(run.name)}s}  the turn was ended by the rule in {100 * e['f_share']['point']:.0f}% of "
            f"rollouts; free continuation minus forced (E1 - E2) {fmt(e['d_minus_f'])}")
        summary["runs"][run.name]["forced"] = {k: brief(v) for k, v in e.items()}
    add("")

    add("3. E3, a noisy test over up to three alternatives: the one with the highest mean gain on rollout")
    add(f"   indices 0 to 31, judged on indices 32 to 63. Shares of decisions (better: above +{DELTA}; large:")
    add(f"   above +{BIG}; worse: below -{DELTA}; each also by more than two standard errors).")
    for run in runs:
        for cls in ("end_turn", "decline_block", "activate"):
            rows = [("all", by_class(cls))]
            if cls == "end_turn":
                rows += [(b, (lambda s, b=b: s["class"] == "end_turn" and s["bucket"] == b))
                         for b in BUCKETS]
            for label, sel in rows:
                n = sum(1 for s in run.roots if sel(s))
                if not n:
                    continue
                e = {k: E.est(run, k, "w", sel, f"E3, {cls}, {label}, {k}")
                     for k in ("better", "big", "worse", "judged")}
                add(f"  {run.name} {cls:14s} {label:26s} n={n:5d} better {fmt(e['better'], 3)} "
                    f"large {fmt(e['big'], 3)} worse {fmt(e['worse'], 3)} | judged gain {fmt(e['judged'])}")
                summary["runs"][run.name].setdefault("e3", {})[f"{cls}/{label}"] = \
                    {k: brief(v) for k, v in e.items()}
    add("")

    add("4. Match arm (E4, E6, a sample of end_turn roots): most probable ACTIVATE minus END_TURN, each")
    add("   played to the end of the match. depth k = shaped reward to the k-th own turn end plus the")
    add("   critic there.")
    for run in runs:
        n = sum(1 for s in run.roots if "wm" in s)
        if not n:
            continue
        keys = ["m_depth1", "m_depth2", "m_depth3", "m_end_0.999", "m_end_0.9995", "m_end_1.0",
                "m_cmr", "m_td", "m_win", "m_pair_sd_end", "m_valid_share"]
        e = {k: E.est(run, k, "wm", always, f"match arm, {k}") for k in keys}
        for k in ("m_end_0.999", "m_cmr", "m_td"):
            core[(run.name, k)] = e[k]
        add(f"  {run.name}: {n} roots, valid pairs {100 * e['m_valid_share']['point']:.1f}%, "
            f"spread of one pair's difference to the match end {e['m_pair_sd_end']['point']:.3f}")
        add(f"    critic at depth 1 {fmt(e['m_depth1'])} | depth 2 {fmt(e['m_depth2'])} | depth 3 "
            f"{fmt(e['m_depth3'])}")
        add(f"    realised shaped return to the match end: gamma 0.999 {fmt(e['m_end_0.999'])} | "
            f"0.9995 {fmt(e['m_end_0.9995'])} | 1.0 {fmt(e['m_end_1.0'])}")
        add(f"    critic at depth 1 minus realised (gamma 0.999) {fmt(e['m_cmr'])}")
        add(f"    touchdown difference {fmt(e['m_td'])} | win score {fmt(e['m_win'])}")
        summary["runs"][run.name]["match"] = {k: brief(v) for k, v in e.items()}
    add("")

    add("5. Reward components (E5, match arm): alternative minus END_TURN, discounted at 0.999, summed to")
    add("   the match end and to the second own turn end. Families are PLAN.md's. The single components'")
    add("   equal-weight-per-game versions are in the JSON summary only.")
    for run in runs:
        if not any("channels_end" in s for s in run.roots):
            continue
        add(f"  {run.name}:")
        summary["runs"][run.name]["families"], summary["runs"][run.name]["channels"] = {}, {}
        for family in FAMILIES:
            e_end = E.est(run, "fam_end_" + family, "wm", always, f"family {family}, match end")
            e_d2 = E.est(run, "fam_d2_" + family, "wm", always, f"family {family}, second turn end")
            core[(run.name, "fam_end_" + family)], core[(run.name, "fam_d2_" + family)] = e_end, e_d2
            add(f"   family {family:24s} match end {fmt(e_end)} | second own turn end {fmt(e_d2)}")
            summary["runs"][run.name]["families"][family] = {"end": brief(e_end), "depth2": brief(e_d2)}
        table = []
        for channel in run.channels:
            e_end = E.est(run, "ch_end_" + channel, "wm")
            e_d2 = E.est(run, "ch_d2_" + channel, "wm")
            summary["runs"][run.name]["channels"][channel] = {
                "end": brief(e_end), "depth2": brief(e_d2),
                "end_per_game": brief(e_end["game"]), "depth2_per_game": brief(e_d2["game"])}
            if e_end["point"] != 0.0 or e_d2["point"] != 0.0:
                table.append((abs(e_end["point"]), channel, e_end, e_d2))
        for _, channel, e_end, e_d2 in sorted(table, key=lambda t: (-t[0], t[1])):
            add(f"     {channel:22s} match end {fmt(e_end)} | second own turn end {fmt(e_d2)}")
    add("")

    add("6. Contrasts between checkpoints (paired by seed). 'detectable' = 2.8 bootstrap standard errors")
    add("   (80% power, 5% two-sided).")
    labels = [("E1, turn arm, end_turn", "d"), ("E1, critic value part", "d_value"),
              ("E1, discount part", "d_tax"), ("E2, forced arm", "f"),
              ("realised margin, gamma 0.999", "m_end_0.999"), ("critic minus realised", "m_cmr"),
              ("touchdown difference", "m_td"), ("activations per own team turn", "activations")]
    contrasts = default_contrasts(list(by_name))
    if not contrasts:
        add("   none of the plan's contrasts has all its checkpoints among the inputs")
    for cname, weights in contrasts.items():
        add(f"   {cname}  ({' '.join(f'{w:+g}*{n}' for n, w in weights.items())})")
        summary["contrasts"][cname] = {}
        for label, key in labels:
            if any((n, key) not in core for n in weights):
                continue
            c = E.combine([(w, core[(n, key)]) for n, w in weights.items()],
                          f"contrast {cname}: {label}")
            digits = 3 if key == "activations" else 4
            add(f"      {label:34s} {fmt(c, digits)}  detectable {2.8 * c['se']:.{digits}f}")
            summary["contrasts"][cname][label] = {**brief(c), "per_game": brief(c["game"])}
    add("")

    add("7. Readings by PLAN.md's rules (sections 5 and 8). Each line states the rule's numbers; a rule that")
    add("   cannot be evaluated says so.")
    lines += readings(E, by_name, core, summary["readings"], chain60_planned)
    add("")

    add("8. Every estimate and contrast above with equal weight per game (games without a root of the")
    add("   kind left out). The readings of section 7 use the per-decision versions.")
    for label, e in E.per_game:
        digits = 3 if ("share" in label or "per own team turn" in label or ", pos" in label
                       or "E3" in label) else 4
        label = label if len(label) <= 96 else label[:93] + "..."
        add(f"   {label:96s} {fmt(e, digits)}")
    summary["per_game"] = {label: brief(e) for label, e in E.per_game}
    return "\n".join(lines) + "\n", summary


def readings(E, runs, core, out, chain60_planned):
    """Sections 5 and 8 of PLAN.md, evaluated mechanically. chain60_planned: the
    plan has a chain60 shard, so question 7's two-seed rule governs rule L."""
    text = []

    def say(key, line, value=None):
        text.append("   " + line)
        out[key] = {"text": line, "value": value}

    def get(name, key):
        return core.get((name, key))

    # Question 1.
    e = get("chain55", "d")
    if e is None:
        say("q1", "Q1: not evaluated (chain55 is not among the inputs).")
    else:
        say("q1", f"Q1: chain55's E1 is {fmt(e)}: {sign_word(e)}. "
            + ("The exploratory margin repeats." if below(e) else "The exploratory margin does not repeat."),
            below(e))
    # Question 2, per checkpoint.
    for name in runs:
        d, none = get(name, "d_minus_f"), get(name, "more_none")
        if d is None or none is None:
            continue
        inside = bool(d["lo"] >= -0.002 and d["hi"] <= 0.002)
        further = 1.0 - none["point"]
        ok = inside and further < 0.10
        say(f"q2/{name}", f"Q2 {name}: E1 - E2 is {fmt(d)} ({'inside' if inside else 'not inside'} "
            f"+-0.002); a further activation in {100 * further:.1f}% of free rollouts "
            f"({'under' if further < 0.10 else 'not under'} 10%): "
            + ("E1 prices one more activation." if ok else "quote E2; E1 prices a longer turn."), ok)
    # Question 3, per checkpoint: two descriptive statements, no cause named.
    for name in runs:
        real, cmr = get(name, "m_end_0.999"), get(name, "m_cmr")
        if real is None:
            continue
        say(f"q3/{name}", f"Q3 {name}: realised margin {fmt(real)} ({sign_word(real)}); critic at depth 1 "
            f"minus realised {fmt(cmr)} ({sign_word(cmr)}).",
            {"realised": sign_word(real), "critic_minus_realised": sign_word(cmr)})
    # Question 4, per checkpoint.
    named = {}
    for name in runs:
        found = []
        for family in FAMILIES:
            for horizon, key in (("match end", "fam_end_"), ("second turn end", "fam_d2_")):
                e = get(name, key + family)
                if e is not None and (below(e) or above(e)):
                    found.append(f"{family} at the {horizon} ({'below' if below(e) else 'above'} zero)")
        if get(name, "fam_end_" + CHARGES) is not None:
            named[name] = found
            say(f"q4/{name}", f"Q4 {name}: families whose interval excludes zero: "
                + ("; ".join(found) if found else "none") + ".", found)
    # Question 7.
    need = [get(n, "d") for n in ("chain55", "chain58", "chain59")]
    lam = None                                             # +1: chain 58 less negative, by the rule
    if any(e is None for e in need):
        say("q7", "Q7: not evaluated (needs chain55, chain58 and chain59).")
    else:
        m55, m58, m59 = need
        d55 = E.combine([(1.0, m58), (-1.0, m55)])
        d59 = E.combine([(1.0, m58), (-1.0, m59)])
        gap = abs(m59["point"] - m55["point"])
        same = (above(d55) and above(d59)) or (below(d55) and below(d59))
        beyond = min(abs(d55["point"]), abs(d59["point"])) > gap
        rule_b = bool(same and beyond)
        say("q7b", f"Q7 (range rule): chain58 - chain55 {fmt(d55)}, chain58 - chain59 {fmt(d59)}, seed gap "
            f"|chain59 - chain55| {gap:.4f}. Both intervals exclude zero with one sign: "
            f"{'yes' if same else 'no'}; the smaller difference exceeds the seed gap: "
            f"{'yes' if beyond else 'no'}. " + ("Chain 58 differs from both lambda 0.95 checkpoints by more "
                                               "than they differ from each other." if rule_b else
                                               "No difference beyond the seed gap is shown."), rule_b)
        m60 = get("chain60", "d")
        if m60 is None and chain60_planned:
            say("q7a", "Q7 (two-seed rule): not evaluated (chain60 is in the plan and not among the "
                "accepted inputs). Rule L's first condition is not met.")
        elif m60 is None:
            lam = (1 if d55["point"] > 0 else -1) if rule_b else None
            say("q7a", "Q7 (two-seed rule): not evaluated (the plan has no chain60); the range rule "
                "above governs rule L.")
        else:
            d60 = E.combine([(1.0, m60), (-1.0, m59)])
            both = (above(d55) and above(d60)) or (below(d55) and below(d60))
            lam = (1 if d55["point"] > 0 else -1) if both else None
            say("q7a", f"Q7 (two-seed rule): chain58 - chain55 {fmt(d55)}, chain60 - chain59 {fmt(d60)}. "
                + ("The lambda 0.97 minus 0.95 difference has the same sign at both seeds, each interval "
                   "excluding zero." if both else "The same sign at both seeds is not shown."), bool(both))
    # Section 8, governed by chain 58.
    g = "chain58"
    e1, tax, flip, real, cmr = (get(g, k) for k in ("d", "d_tax", "flip", "m_end_0.999", "m_cmr"))
    if e1 is None or real is None:
        say("s8", "Section 8: not evaluated (chain58 is not among the inputs). Reported without a "
            "recommendation.", None)
        return text
    charges, ball = get(g, "fam_end_" + CHARGES), get(g, "fam_end_" + BALL)
    r_main = below(real) and below(charges) and abs(charges["point"]) >= 0.5 * abs(real["point"])
    r_rule = bool(r_main and not below(ball))
    say("s8/R", f"R (reward pointer, chain58): realised margin {fmt(real)} below zero: "
        f"{'yes' if below(real) else 'no'}; block and rush charges at the match end {fmt(charges)} below "
        f"zero: {'yes' if below(charges) else 'no'}; at least half the realised margin: "
        f"{'yes' if abs(charges['point']) >= 0.5 * abs(real['point']) else 'no'}; ball family "
        f"{fmt(ball)} also below zero: {'yes' if below(ball) else 'no'}. R holds: "
        f"{'yes' if r_rule else 'no'}.", r_rule)

    def gamma_points(name):
        a, b, c = get(name, "d"), get(name, "d_tax"), get(name, "flip")
        if a is None:
            return None
        return bool(abs(b["point"]) >= 0.25 * abs(a["point"]) and c["point"] >= 0.10)
    others = [gamma_points(n) for n in ("chain55", "chain59")]
    g_rule = bool(below(cmr) and below(e1) and abs(tax["point"]) >= 0.25 * abs(e1["point"])
                  and flip["point"] >= 0.10 and above(flip) and all(o is True for o in others))
    say("s8/G", f"G (gamma, chain58): critic minus realised {fmt(cmr)} below zero: "
        f"{'yes' if below(cmr) else 'no'}; E1 {fmt(e1)} below zero: {'yes' if below(e1) else 'no'}; "
        f"discount part {tax['point']:+.4f} at least a quarter of E1: "
        f"{'yes' if abs(tax['point']) >= 0.25 * abs(e1['point']) else 'no'}; share flipped without the "
        f"discount {fmt(flip, 3)} at least 0.10 with its interval above zero: "
        f"{'yes' if flip['point'] >= 0.10 and above(flip) else 'no'}; the two point conditions also hold "
        f"for chain55 and chain59: {others}. G holds: {'yes' if g_rule else 'no'}.", g_rule)
    c55, c59 = get("chain55", "m_cmr"), get("chain59", "m_cmr")
    if c55 is None or c59 is None:
        l_rule = False
        say("s8/L", "L (lambda): not evaluated (needs chain55 and chain59). L holds: no.", False)
    else:
        contrast = E.combine([(1.0, cmr), (-0.5, c55), (-0.5, c59)])
        nearer = abs(cmr["point"]) < min(abs(c55["point"]), abs(c59["point"]))
        l_rule = bool(lam == 1 and nearer and (below(contrast) or above(contrast)))
        say("s8/L", f"L (lambda): question 7 holds with chain58 the less negative: "
            f"{'yes' if lam == 1 else 'no'}; |critic minus realised| of chain58 {abs(cmr['point']):.4f} "
            f"below both chain55 {abs(c55['point']):.4f} and chain59 {abs(c59['point']):.4f}: "
            f"{'yes' if nearer else 'no'}; chain58 minus their mean {fmt(contrast)} excludes zero: "
            f"{'yes' if below(contrast) or above(contrast) else 'no'}. L holds: "
            f"{'yes' if l_rule else 'no'}.", l_rule)
    if r_main and below(ball):
        outcome = ("R's first three conditions hold and the ball family is also below zero: two "
                   "families are named. Reported without a recommendation.")
    elif r_rule and (g_rule or l_rule):
        outcome = "R holds together with a critic-side rule: reported without a recommendation."
    elif r_rule:
        outcome = "R alone: the probe points at a reward arm on the block and rush charges."
    elif g_rule and l_rule:
        outcome = "G and L both hold: lambda 0.97 first, gamma 0.9995 as the arm after it."
    elif l_rule:
        outcome = "L alone: the probe points at lambda 0.97."
    elif g_rule:
        outcome = "G alone: the probe points at gamma 0.9995."
    else:
        outcome = "No rule holds: reported without a recommendation."
    say("s8", "Section 8 outcome: " + outcome, outcome)
    return text


def refuse(why):
    raise SystemExit("REFUSED, nothing was computed:\n  " + "\n  ".join(why))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plan", default=None)
    ap.add_argument("--expect-sha256", default=None)
    ap.add_argument("--shard-dir", action="append", default=[], metavar="SHARD=DIR")
    ap.add_argument("--smoke-run", action="append", default=[], metavar="NAME=DIR")
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    if bool(args.shard_dir) == bool(args.smoke_run):
        raise SystemExit("give --shard-dir (with --plan and --expect-sha256) or --smoke-run, not both")
    mine = {name: ACCEPT.sha256_file(os.path.join(HERE, name)) for name in LOCAL_FILES}
    runs, header, chain60_planned = [], [], False
    if args.shard_dir:
        if not (args.plan and args.expect_sha256):
            raise SystemExit("--shard-dir needs --plan and --expect-sha256")
        try:
            plan, plan_sha = ACCEPT.load_plan(args.plan, args.expect_sha256)
        except ValueError as exc:
            refuse([str(exc)])
        why = [f"{name} is not the file the plan names ({sha[:12]})" for name, sha in mine.items()
               if plan["local_sha256"].get(name) != sha]
        seen = set()
        for item in args.shard_dir:
            shard, _, directory = item.partition("=")
            if not directory or shard in seen:
                why.append(f"--shard-dir {item!r}: give each shard once as SHARD=DIR")
                continue
            seen.add(shard)
            problems, completes = ACCEPT.shard_problems(directory, shard, plan, plan_sha)
            why += [f"shard {shard}: {p}" for p in problems]
            if not problems:
                runs += [Run(ck, os.path.join(directory, ck), c) for ck, c in completes.items()]
        if len({r.complete["library_sha256"] for r in runs}) > 1:
            why.append("the shards ran on different engine libraries: "
                       + ", ".join(f"{r.name} {r.complete['library_sha256'][:12]}" for r in runs))
        if why:
            refuse(why)
        chain60_planned = "chain60" in plan["checkpoints"]
        absent = sorted(set(plan["checkpoints"]) - {r.name for r in runs})
        header = [f"END_TURN probe, plan {plan['name']} ({plan_sha}); purpose: {plan['purpose']}",
                  f"accepted shards: {', '.join(sorted(seen))}; checkpoints of the plan not among the "
                  f"inputs (unread): {', '.join(absent) or 'none'}",
                  "this script and endturn_accept.py are the files the plan names", ""]
    else:
        why = []
        for item in args.smoke_run:
            name, _, directory = item.partition("=")
            problems, complete = ACCEPT.checkpoint_problems(directory, name)
            why += [f"{name}: {p}" for p in problems]
            if not problems:
                runs.append(Run(name, directory, complete))
        if why:
            refuse(why)
        header = ["SMOKE, NOT EVIDENCE: unregistered local records, held only to their own COMPLETE.json.",
                  "Intervals over a handful of games mean nothing.", ""]
    if len({tuple(r.seeds) for r in runs}) != 1:
        refuse(["the runs do not share one seed list"])
    text, summary = report(runs, header, chain60_planned)
    sys.stdout.write(text)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(summary, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
