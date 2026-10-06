#!/usr/bin/env python3
"""human_prior_report.py: print the report's tables from the run JSON files.

  python3 analysis/human_prior_report.py runs/human-prior-20261005 > tables.md

Reads <run>/final_*/result.json (training/human_prior.py,
training/human_prior_seq.py) and <run>/audit/audit.json
(analysis/human_prior_audit.py). Stdlib only; it computes nothing new.
"""
import json
import os
import sys


def load(path):
    return json.load(open(path)) if os.path.exists(path) else None


def pct(x, digits=1):
    return "n/a" if x is None else f"{100 * x:.{digits}f}%"


def iv(d, scale=1.0, digits=3):
    if d is None:
        return "n/a"
    return f"{scale * d['value']:.{digits}f} [{scale * d['lo']:.{digits}f}, {scale * d['hi']:.{digits}f}]"


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out) + "\n"


def prior_tables(run):
    runs = {name: load(os.path.join(run, f"final_{name}", "result.json"))
            for name in ("prefix", "default", "everything", "n100", "n200", "withbias")}
    print("### Training subset against held-out subset (60 replays never trained on)\n")
    rows = []
    for name, label in (("prefix", "prefix only"), ("default", "prefix + closed-equal (default)"),
                        ("everything", "everything (stamps 0-4)")):
        r = runs[name]
        if not r:
            continue
        cells = [label, f"{r['train']['records']['prefix']:,} + {r['train']['records']['reseat']:,}"]
        for ev in ("prefix", "prefix+closed_equal", "everything"):
            o = r["eval"].get(ev, {}).get("overall")
            cells.append("n/a" if not o else f"{pct(o['exact'])} / {o['nll']:.3f}")
        rows.append(cells)
    print(table(["trained on", "train records (prefix + re-seated)",
                 "held-out prefix: exact / NLL", "held-out prefix + closed-equal",
                 "held-out everything"], rows))
    d = runs["default"]
    if not d:
        return
    e = d["eval"]["prefix+closed_equal"]
    o = e["overall"]
    print(f"Held-out records in the default subset: {o['n']:,} "
          f"({e['records']['prefix']:,} prefix + {e['records']['reseat']:,} re-seated). "
          f"Exact {pct(o['exact'])} [{pct(o['exact_interval']['lo'])}, "
          f"{pct(o['exact_interval']['hi'])}] (replay-clustered).\n")
    print("### Default prior, by head (held-out, default subset)\n")
    rows = []
    for h in ("type", "arg", "square"):
        rows.append([h, pct(o[f"acc_{h}"]), f"{o[f'n_{h}_choice']:,}",
                     pct(o.get(f"acc_{h}_choice")), f"{o.get(f'mean_p_{h}_choice', 0):.3f}",
                     f"{o.get(f'conf_{h}_choice', 0):.3f}"])
    print(table(["head", "accuracy, all rows", "rows with a choice", "accuracy there",
                 "mean p(human) there", "mean top probability there"], rows))
    print(f"All three heads right: {pct(o['exact'])}. Mean probability on the human's "
          f"joint action: {o['mean_p_human']:.3f}. NLL {o['nll']:.3f} nats. "
          f"Type-head ECE {e['type_head_calibration']['ece']:.3f}.\n")

    def group(title, key, names=None):
        print(f"### Default prior, {title} (held-out, default subset)\n")
        rows = []
        for name, v in e[key].items():
            if not v.get("n"):
                continue
            rows.append([(names or {}).get(name, name), f"{v['n']:,}", pct(v["exact"]),
                         pct(v["acc_type"]), pct(v["acc_arg"]), pct(v["acc_square"]),
                         f"{v['mean_p_human']:.3f}", f"{v['nll']:.2f}"])
        print(table(["", "n", "exact", "type", "arg", "square", "mean p(human)", "NLL"], rows))

    group("by action family", "by_family")
    group("by half", "by_half")
    group("by team-turn band", "by_turn_band")
    group("by provenance", "by_provenance")
    ev = d["eval"]["everything"]["by_provenance"]
    print("Same prior on every held-out re-seated record, by span stamp: " + "; ".join(
        f"stamp {k[-1]}: n {v['n']:,}, exact {pct(v['exact'])}, NLL {v['nll']:.2f}"
        for k, v in ev.items() if k.startswith("reseat_stamp")) + ".\n")

    print("### Learning curve (default subset, held-out default subset)\n")
    rows = []
    for name in ("n100", "n200", "default"):
        r = runs[name]
        if not r:
            continue
        o = r["eval"]["prefix+closed_equal"]["overall"]
        rows.append([r["train"]["replays"],
                     f"{r['train']['records']['prefix'] + r['train']['records']['reseat']:,}",
                     pct(o["exact"]), f"{o['nll']:.3f}", f"{o['mean_p_human']:.3f}"])
    print(table(["training replays", "training records", "exact", "NLL", "mean p(human)"], rows))
    b = runs["withbias"]
    if b:
        ob = b["eval"]["prefix+closed_equal"]["overall"]
        print(f"With biases (not convertible): exact {pct(ob['exact'])}, NLL {ob['nll']:.3f}, "
              f"against bias-free {pct(o['exact'])}, NLL {o['nll']:.3f}.\n")
    s = load(os.path.join(run, "final_seq16", "result.json"))
    if s:
        c = s["carried"]
        print(f"Sequences of {s['seq_len']} with carried state: exact "
              f"{pct(c['exact']['mean'])} [{pct(c['exact']['lo'])}, {pct(c['exact']['hi'])}], "
              f"NLL {c['nll']:.3f}; by position in the window {c['exact_by_position']}; "
              f"the same net at zero state: exact {pct(s['same_net_zero_state']['exact'])}, "
              f"NLL {s['same_net_zero_state']['nll']:.3f}.\n")


NETS = ("prior", "chain41", "chain36", "chain9")


def audit_tables(run):
    a = load(os.path.join(run, "audit", "audit.json"))
    if not a:
        return
    print(f"Human states: {a['human_subset']}; {a['human_records']} records from "
          f"{a['human_replays']} held-out replays.\n")
    print("### A1. P(net picks the human's action), by family (zero state, human masks)\n")
    rows = []
    for fam, r in a["A1_by_family"].items():
        rows.append([fam, f"{r['n']:,}"] + [f"{r[k]['mean_p_human']:.3f} / {pct(r[k]['argmax_exact'], 0)}"
                                           for k in NETS]
                    + [iv(r["u1_prior_minus_chain41"], digits=2),
                       f"{r['u2_prior_minus_uniform']['value']:.2f}",
                       "yes" if r["usable_target"] else "no"])
    print(table(["family", "n"] + [f"{k}: mean p / argmax match" for k in NETS]
                + ["U1: log p prior - chain 41", "U2: prior - uniform", "usable target"], rows))
    print("### A2. Marginal family rates on human states, per 1,000 decisions\n")
    f = a["A2_family_rates"]
    rows = [[fam, f"{1000 * f['human'][i]:.1f}"] + [f"{1000 * f[k][i]:.1f}" for k in NETS]
            for i, fam in enumerate(f["families"])]
    print(table(["family", "human"] + list(NETS), rows))
    print("### A3. Declarations where the kind is legal (human states)\n")
    rows = []
    for kind, r in a["A3_declarations_where_legal"].items():
        rows.append([kind.title(), f"{r['n_legal']:,}", iv(r["human_rate"])]
                    + [f"{r[k]['rate_t1']['value']:.3f} / {r[k]['rate_argmax']:.3f}" for k in NETS]
                    + [iv(r["human_over_chain41"], digits=2), iv(r["prior_over_human"], digits=2)])
    print(table(["kind", "n legal", "human rate"] + [f"{k}: T=1 / argmax" for k in NETS]
                + ["human / chain 41", "prior / human"], rows))
    r = a["A4_end_turn_with_players_left"]
    print("### A4. Ending the turn while a player could still be activated (human states)\n")
    print(table(["n", "human rate"] + [f"{k}: T=1 / argmax" for k in NETS],
                [[f"{r['n']:,}", iv(r["human_rate"])]
                 + [f"{r[k]['rate_t1']['value']:.3f} / {r[k]['rate_argmax']:.3f}" for k in NETS]]))

    print("### B1 and C. Declarations where the kind is legal (chain 41's own states)\n")
    b = a["B_counts"]
    print(f"{b['decisions']:,} decisions, {b['games']} self-play games, "
          f"{b['declarations']:,} declarations.\n")
    rows = []
    for kind, r in a["B1_declarations_where_legal"].items():
        rows.append([kind.title(), f"{r['n_legal']:,}", f"{r['chain41_sampled_rate']:.3f}",
                     f"{r['chain41']['rate_t1']['value']:.3f}",
                     f"{r['prior']['rate_t1']['value']:.3f}", iv(r["prior_over_chain41"], digits=2),
                     f"{r['chain9']['rate_t1']['value']:.3f}", iv(r["chain9_over_chain41"], digits=2),
                     f"{r['chain36']['rate_t1']['value']:.3f}",
                     f"{r['chain41_zero_state']['rate_t1']['value']:.3f}"])
    print(table(["kind", "n legal", "chain 41 sampled", "chain 41 T=1", "prior", "prior / chain 41",
                 "chain 9", "chain 9 / chain 41", "chain 36", "chain 41 at zero state"], rows))
    r = a["B2_end_turn_with_players_left"]
    print("### B2. Ending the turn while a player could still be activated (chain 41's states)\n")
    print(table(["n", "chain 41 sampled", "chain 41", "prior", "chain 9", "chain 36"],
                [[f"{r['n']:,}", f"{r['chain41_sampled_rate']:.3f}"]
                 + [f"{r[k]['rate_t1']['value']:.3f}" for k in ("chain41", "prior", "chain9", "chain36")]]))
    print("### B3. Family rates on chain 41's states, per 1,000 decisions\n")
    f = a["B3_family_rates"]
    rows = [[fam, f"{1000 * f['chain41_sampled'][i]:.1f}"]
            + [f"{1000 * f[k][i]:.1f}" for k in ("prior", "chain9", "chain36")]
            for i, fam in enumerate(f["families"])]
    print(table(["family", "chain 41 did", "prior wants", "chain 9 wants", "chain 36 wants"], rows))
    print("### B4 and C. Mean KL by decision context (chain 41's states, nats)\n")
    rows = []
    for r in a["B4_kl_by_context"][:14]:
        rows.append([r["context"], f"{r['n']:,}", pct(r["share_of_decisions"]),
                     f"{r['kl_prior__chain41']['value']:.2f}", f"{r['kl_chain41__prior']['value']:.2f}",
                     f"{r['kl_chain9__chain41']['value']:.2f}", f"{r['kl_chain41__chain9']['value']:.2f}",
                     f"{r['kl_chain36__chain41']['value']:.2f}",
                     f"{r['kl_chain41_zero_state__chain41']['value']:.2f}",
                     "yes" if r["would_act"] else "no"])
    o = a["B4_kl_overall"]
    rows.append(["ALL", f"{o['n']:,}", "100%", iv(o["kl_prior__chain41"], digits=2),
                 iv(o["kl_chain41__prior"], digits=2), iv(o["kl_chain9__chain41"], digits=2),
                 iv(o["kl_chain41__chain9"], digits=2), iv(o["kl_chain36__chain41"], digits=2),
                 iv(o["kl_chain41_zero_state__chain41"], digits=2), ""])
    print(table(["context (legal types)", "n", "share", "KL(prior || c41)", "KL(c41 || prior)",
                 "KL(c9 || c41)", "KL(c41 || c9)", "KL(c36 || c41)", "KL(c41 zero || c41)",
                 "KL(prior || c41) >= 0.10"], rows))
    print("Mean log-probability of the action chain 41 took: " + ", ".join(
        f"{k} {v:.2f}" for k, v in a["B4_log_p_of_chain41_action"].items()) + ".\n")
    print("### Opportunity per team turn\n")
    rows = []
    for name, o in (("humans (held-out, default subset)", a["A5_opportunity"]),
                    ("chain 41 self-play", a["B5_opportunity"])):
        rows.append([name, f"{o['team_turns']:,}", f"{o['declarations_per_turn']:.2f}"]
                    + [f"{o[k]['legal_per_turn']:.2f} / {o[k]['declared_per_turn']:.2f}"
                       for k in ("BLOCK", "BLITZ", "PASS", "HANDOFF", "FOUL")])
    print(table(["", "team turns", "declarations per turn"]
                + [f"{k}: legal / declared per turn" for k in ("Block", "Blitz", "Pass", "Hand-off", "Foul")],
                rows))
    print("### D. Added after the first read of the gate (not pre-registered)\n")
    h1, o1 = (a["D1_declared_block_then_no_block_human_states"],
              a["D1_declared_block_then_no_block_own_states"])
    print("D1. After a Block declaration with a target available, ending the "
          "activation without throwing the block:\n")
    print(table(["states", "n", "what was done", "prior", "chain 41", "chain 36", "chain 9"], [
        ["human (held-out)", f"{h1['n']:,}", "humans " + iv(h1["human_rate"])]
        + [f"{h1[k]['rate_t1']['value']:.3f}" for k in ("prior", "chain41", "chain36", "chain9")],
        ["chain 41's own", f"{o1['n']:,}", f"chain 41 {o1['chain41_sampled_rate']:.3f}"]
        + [f"{o1[k]['rate_t1']['value']:.3f}" for k in ("prior", "chain41", "chain36", "chain9")]]))
    h2, o2 = a["D2_empty_activations_human"], a["D2_empty_activations_chain41"]
    print("D2. Activations that end at once (the decision after the declaration "
          "is END_ACTIVATION):\n")
    print(table(["declared", "humans: n", "humans: ended at once", "chain 41: n",
                 "chain 41: ended at once"],
                [[k.title(), f"{h2[k]['n']:,}", pct(h2[k]["ended_at_once"]),
                  f"{o2[k]['n']:,}", pct(o2[k]["ended_at_once"])] for k in h2]))
    h3, o3 = a["D3_team_turn_human"], a["D3_team_turn_chain41"]
    print("D3. The shape of a team turn:\n")
    print(table(["", "team turns", "activations per turn",
                 "turns ended by choice with a player still to activate"],
                [["humans (held-out, default subset)", f"{h3['team_turns']:,}",
                  f"{h3['activations_per_turn']:.2f}",
                  pct(h3["voluntary_end_with_players_left_per_turn"])],
                 ["chain 41 self-play", f"{o3['team_turns']:,}",
                  f"{o3['activations_per_turn']:.2f}",
                  pct(o3["voluntary_end_with_players_left_per_turn"])]]))
    d4 = a["D4_mean_p_of_chain41_action"]
    print("D4. Mean probability each net gives the action chain 41 took "
          "(chain 41's states):\n")
    rows = [[k, f"{v['n']:,}"] + [f"{v[m]:.2f}" for m in (
        "chain41", "chain41_zero_state", "chain36", "chain9", "prior")]
        for k, v in sorted(d4.items(), key=lambda kv: -kv[1]["n"])[:14]]
    print(table(["context", "n", "chain 41 (as played)", "chain 41 at zero state",
                 "chain 36", "chain 9", "prior"], rows))
    print("### The five examples\n")
    for i, x in enumerate(a["B6_examples"], 1):
        print(f"{i}. **{x['context']}** (game {x['game']}, step {x['c_step']}, symmetric KL "
              f"{x['symmetric_kl']:.2f}). Half {x['half']}, turn {x['turn_own']} "
              f"(opponent {x['turn_opp']}), score {x['score_own']}-{x['score_opp']}, ball "
              f"{x['ball']}. Acting player: {x['acting_player']}. Chain 41 did: "
              f"**{x['chain41_did']}** (its p {x['chain41_p_of_that']:.2f}; prior's p "
              f"{x['prior_p_of_that']:.2f}). Chain 41's top: "
              + "; ".join(f"{t['action']} {t['p']:.2f}" for t in x["chain41_top"])
              + ". Prior's top: "
              + "; ".join(f"{t['action']} {t['p']:.2f}" for t in x["prior_top"]) + ".")
    print()
    print("### Verdict (computed by the registered rule)\n")
    print("```json")
    print(json.dumps(a["verdict"], indent=1))
    print("```")


if __name__ == "__main__":
    run_dir = sys.argv[1]
    prior_tables(run_dir)
    audit_tables(run_dir)
