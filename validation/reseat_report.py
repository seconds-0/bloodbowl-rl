#!/usr/bin/env python3
"""reseat_report.py: measure a lockstep_reseat.py run.

Reads the shards and JSONL files under a run directory and prints:
  1. the seat audit: how often a state rebuilt from the replay differs from
     the state the engine reached legally, field by field;
  2. the forced-re-seat test: records written after a forced re-seat at every
     boundary, compared byte for byte with the prefix-aligned records of the
     same decisions, mismatches by observation field;
  3. the yield: records, spans aligned, re-seats, by half and turn, and
     action-family counts per 100 replays, prefix-only versus with re-seat;
  4. label integrity, read from the shards alone: every record's action must
     be inside its own exact conditional masks.

Usage:
  python3 validation/reseat_report.py runs/x [--json out.json]
Stock python3, stdlib only.
"""
import argparse
import collections
import json
import os
import statistics
import struct
import sys

OBS, MASK = 2782, 454
HEAD_TYPE, HEAD_ARG, HEAD_SQ = 30, 33, 391
REC = 12 + OBS + MASK + 4
CTX, SCAL, TZ, A1 = 768, 784, 832, 1612

A_NAMES = {
    1: "SETUP_PLACE", 2: "SETUP_REMOVE", 3: "SETUP_DONE", 4: "KICK_TARGET",
    5: "TOUCHBACK", 6: "ACTIVATE", 7: "DECLARE", 8: "END_TURN", 9: "STEP",
    10: "STAND_UP", 11: "JUMP", 12: "BLOCK_TARGET", 13: "PASS_TARGET",
    14: "HANDOFF_TARGET", 15: "FOUL_TARGET", 16: "TTM_TARGET",
    17: "SECURE_BALL", 19: "END_ACTIVATION", 20: "CHOOSE_DIE",
    21: "PUSH_SQUARE", 22: "FOLLOW_UP", 23: "USE_REROLL",
    24: "DECLINE_REROLL", 25: "USE_SKILL", 26: "DECLINE_SKILL",
    27: "APOTHECARY", 28: "CHOOSE_OPTION", 29: "SPECIAL_TARGET",
}
DECLARE = {0: "move", 1: "block", 2: "blitz", 3: "pass", 4: "hand-off",
           5: "foul", 6: "throw team-mate", 7: "secure ball", 8: "stab"}
FAMILIES = ("move", "block", "blitz", "pass", "hand-off", "foul",
            "END_TURN", "BLOCK_TARGET", "PASS_TARGET", "HANDOFF_TARGET",
            "FOUL_TARGET")
PROC_TEAM_TURN = 5   # bb_proc: everything from TEAM_TURN up runs inside a turn

PLAYER_COLS = ["x", "y", "location", "stance", "flags_lo", "flags_hi", "ma",
               "st", "ag", "pa", "av"] + ["skill"] * 12 + ["tz_count"]
CTX_COLS = ["ball_state", "ball_x", "ball_y", "ball_carrier", "top_proc",
            "top_phase", "frame_a", "frame_b", "test_target", "pending_x",
            "decision_is_me", "active_is_me", "pending_y", "block_face",
            "block_face", "block_face"]
SCAL_COLS = ["half", "turn_me", "turn_opp", "score_me", "score_opp",
             "rerolls_me", "rerolls_opp", "weather", "blitz_used", "pass_used",
             "handoff_used", "foul_used", "ttm_used", "secure_used", "apo_me",
             "apo_opp", "bribes_me", "bribes_opp", "kicking_is_me",
             "mover_moved", "mover_rushes", "test_kind", "window_flags",
             "act_kind", "cas_roll_a", "cas_roll_b", "stack_flags",
             "placement_budget", "move_target", "ktm_used", "s30", "s31"] + \
            ["option_table"] * 16


def obs_field(i):
    if i < CTX:
        side = "own" if i // 24 < 16 else "opp"
        return f"player.{side}.{PLAYER_COLS[i % 24]}"
    if i < SCAL:
        return "ctx." + CTX_COLS[i - CTX]
    if i < TZ:
        return "scalar." + SCAL_COLS[i - SCAL]
    if i < A1:
        return "tz_plane.mine" if i < TZ + 390 else "tz_plane.theirs"
    return ("plane.p_def_down", "plane.p_att_down", "plane.step_success")[(i - A1) // 390]


def records(path, magic):
    """Yield record byte strings from a shard (raises on a bad header)."""
    with open(path, "rb") as f:
        head = f.read(16)
        if len(head) < 16:
            return
        m, ver, osz, msz = struct.unpack("<4sIII", head)
        if m != magic or ver != 4 or osz != OBS or msz != MASK:
            raise ValueError(f"{path}: bad header {m} v{ver} {osz}/{msz}")
        while True:
            rec = f.read(REC)
            if len(rec) < REC:
                if rec:
                    raise ValueError(f"{path}: truncated record")
                return
            yield rec


def target_in_mask(rec):
    obs0 = 12
    mask = rec[obs0 + OBS: obs0 + OBS + MASK]
    typ = rec[REC - 4]
    arg = rec[REC - 3]
    sq = rec[REC - 2] | (rec[REC - 1] << 8)
    return (typ < HEAD_TYPE and mask[typ] == 1 and
            arg < HEAD_ARG and mask[HEAD_TYPE + arg] == 1 and
            sq < HEAD_SQ and mask[HEAD_TYPE + HEAD_ARG + sq] == 1)


def classify(rec):
    """(half, turn of the active team or 0 outside a team turn, family)."""
    o = 12
    half = rec[o + SCAL]
    proc = rec[o + CTX + 4]
    active_me = rec[o + CTX + 11]
    turn = rec[o + SCAL + 1] if active_me else rec[o + SCAL + 2]
    # stack-flag bit 4 = a KICKOFF frame is on the stack (Charge! activations)
    in_turn = proc >= PROC_TEAM_TURN and not (rec[o + SCAL + 26] & 4)
    typ, arg = rec[REC - 4], rec[REC - 3]
    name = A_NAMES.get(typ, str(typ))
    fam = DECLARE.get(arg, f"declare:{arg}") if typ == 7 else name
    return half, (turn if in_turn else 0), name, fam


def q(a, x):
    return a[min(len(a) - 1, int(x * len(a)))] if a else 0


def tally(paths, magic):
    c = {"n": 0, "half_turn": collections.Counter(), "fam": collections.Counter(),
         "type": collections.Counter(), "bad_label": 0, "per_replay": {}}
    for rid, path in paths:
        n = 0
        if os.path.exists(path):
            for rec in records(path, magic):
                n += 1
                half, turn, name, fam = classify(rec)
                c["half_turn"][(half, turn)] += 1
                c["type"][name] += 1
                c["fam"][fam] += 1
                if not target_in_mask(rec):
                    c["bad_label"] += 1
        c["per_replay"][rid] = n
        c["n"] += n
    return c


def dist_line(label, per):
    v = sorted(per)
    return (f"{label}: total {sum(v)}; per replay mean {statistics.mean(v):.1f} "
            f"median {statistics.median(v):.0f} p25 {q(v, .25)} p75 {q(v, .75)} "
            f"p90 {q(v, .9)} max {v[-1]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir")
    ap.add_argument("--json")
    ap.add_argument("--skip-force", action="store_true")
    a = ap.parse_args()
    D = a.run_dir
    out = {}
    rows = {m: [json.loads(l) for l in open(os.path.join(D, f"{m}.jsonl"))]
            for m in ("audit", "force", "reseat")
            if os.path.exists(os.path.join(D, f"{m}.jsonl"))}
    rids = [r["rid"] for r in rows["reseat"]]
    N = len(rids)

    # ---- 1. seat audit ------------------------------------------------------
    BOOK = ("p.moved_rushes", "p.skill_rr_used", "p.spp_game", "step_count",
            "turns_completed", "ret", "surfs", "bonus_rerolls")
    print("=== 1. SEAT AUDIT (state rebuilt from the replay vs the engine's own) ===")
    for part in (("clean", "tolerated") if "audit" in rows else ()):
        nb = 0
        toks, fails, classes = (collections.Counter() for _ in range(3))
        for r in rows["audit"]:
            au = r["audit"][part]
            nb += au["boundaries"]
            toks.update(au["tokens"])
            fails.update(au["build_fail"])
            classes.update(au["classes"])
        built = nb - sum(fails.values())
        lab = ("where the mapper knows of no divergence" if part == "clean" else
               "where the mapper tolerates a known engine divergence")
        print(f"-- prefix boundaries {lab}: {nb}; rebuilt {built}; "
              f"could not rebuild {sum(fails.values())} {dict(fails)}")
        for k, lab in (("observable_equal", "equal in every observed or rule-read field"),
                       ("hard", "differ on the pitch (squares, stance, ball, score, clock)"),
                       ("soft", "differ in resources or statuses (re-rolls, Bribes, ...)"),
                       ("derived", "differ in a mapper-derived latch (USED, BLITZED, ...)")):
            print(f"   {classes[k]:6d} {100 * classes[k] / max(built, 1):6.2f}%  {lab}")
        print("   by field (boundaries; bookkeeping fields last):")
        for t, v in sorted(toks.items(), key=lambda kv: (kv[0].startswith(BOOK), -kv[1])):
            print(f"   {v:6d} {100 * v / max(built, 1):6.2f}%  {t}")
        out[f"audit_prefix_{part}"] = {
            "boundaries": nb, "built": built, "build_fail": dict(fails),
            "tokens": dict(toks), "classes": dict(classes)}
    if "reseat" in rows:
        nb = soft = 0
        toks, status = collections.Counter(), collections.Counter()
        for r in rows["reseat"]:
            cl = r["close"]
            nb += cl["boundaries"]
            soft += cl["soft_drift"]
            toks.update(cl["tokens"])
            status.update(cl["status"])
        print(f"-- boundaries reached WITHOUT a stop inside re-seated provenance: {nb}")
        for code, lab in (("1", "engine equalled the replay in every field the seat carries"),
                          ("4", "pitch matched; a resource, status or latch differed"),
                          ("2", "engine was off the replay on the pitch")):
            print(f"   {status[code]:6d} {100 * status[code] / max(nb, 1):6.2f}%  {lab}")
        print("   (the engine is re-synced to the replay at each of these either way)")
        print("   by field:")
        for t, v in sorted(toks.items(), key=lambda kv: (kv[0].startswith(BOOK), -kv[1])):
            if not t.startswith(BOOK):
                print(f"   {v:6d} {100 * v / max(nb, 1):6.2f}%  {t}")
        out["close_reseated"] = {"boundaries": nb, "status": dict(status),
                                 "soft_drift": soft, "tokens": dict(toks)}

    # ---- 2. forced re-seat --------------------------------------------------
    if "force" in rows and not a.skip_force:
        print("\n=== 2. FORCED RE-SEAT AT EVERY BOUNDARY vs PREFIX RECORDS ===")
        # A forced segment is "equal" when the state the seat built matched the
        # engine's own in every observed or rule-read field (class mask without
        # hard / soft / derived). Records written from such a state must equal
        # the prefix records byte for byte: any difference there is a defect
        # of the mechanism itself. In the other segments the seat deliberately
        # changed something, and the fields that differ say what.
        tot = same = short = longer = forced_segments = 0
        st = {k: {"records": 0, "differ": 0, "mask": 0, "label": 0,
                  "fields": collections.Counter(), "examples": []}
              for k in ("equal", "changed")}
        for r in rows["force"]:
            rid = r["rid"]
            forced_segments += r["reseats"]
            base = list(records(os.path.join(D, "pairs", f"{rid}.bbp"), b"BBP1"))
            f = list(records(os.path.join(D, "force", f"{rid}.bbp"), b"BBP1")) + \
                list(records(os.path.join(D, "force", f"{rid}.bbr"), b"BBR1"))
            tot += 1
            short += len(f) < len(base)
            longer += len(f) > len(base)
            ok = len(f) == len(base)
            dirty = False   # a "changed" segment came earlier in this replay
            last_seg = 0
            for i in range(min(len(f), len(base))):
                x, y = base[i], f[i]
                seg = y[9] | (y[10] << 8)
                if seg == 0:
                    continue        # before the first forced re-seat
                if seg != last_seg:
                    last_seg = seg
                    m = r["forced"].get(str(seg), 0)
                    if m & 7:
                        dirty = True
                # bytes 9..11 are provenance (segment, span status), not data
                k = st["changed" if dirty else "equal"]
                k["records"] += 1
                if x[:9] == y[:9] and x[12:] == y[12:]:
                    continue
                ok = False
                k["differ"] += 1
                seen = set()
                for j in range(OBS):
                    if x[12 + j] != y[12 + j]:
                        seen.add(obs_field(j))
                k["fields"].update(seen)
                if x[12 + OBS:12 + OBS + MASK] != y[12 + OBS:12 + OBS + MASK]:
                    k["mask"] += 1
                if x[REC - 4:] != y[REC - 4:] or x[:9] != y[:9]:
                    k["label"] += 1
                if len(k["examples"]) < 4:
                    k["examples"].append((rid, i, seg, sorted(seen)[:6]))
            same += ok
        print(f"replays {tot}; forced re-seats applied {forced_segments}; replays whose "
              f"forced records all equal the prefix records: {same}; forced run "
              f"stopped earlier in {short}, later in {longer}")
        for name, lab in (("equal", "after seats that matched the engine's state (and no "
                                    "changed seat earlier in the replay)"),
                          ("changed", "after a seat that changed an observed field")):
            k = st[name]
            n = max(k["records"], 1)
            print(f"-- records {lab}: {k['records']}; differing {k['differ']} "
                  f"({100 * k['differ'] / n:.3f}%); mask differs {k['mask']}; "
                  f"label differs {k['label']}")
            for fld, v in k["fields"].most_common(14):
                print(f"   {v:6d} records differ in {fld}")
            for e in k["examples"]:
                print("   e.g.", e)
        out["force"] = {"replays": tot, "identical_replays": same,
                        "stopped_earlier": short, "stopped_later": longer,
                        "forced_reseats": forced_segments,
                        **{name: {"records": k["records"], "differ": k["differ"],
                                  "mask_differs": k["mask"], "label_differs": k["label"],
                                  "fields": dict(k["fields"])}
                           for name, k in st.items()}}

    # ---- 3. yield -----------------------------------------------------------
    print("\n=== 3. YIELD ===")
    pre = tally([(r, os.path.join(D, "pairs", f"{r}.bbp")) for r in rids], b"BBP1")
    res = tally([(r, os.path.join(D, "pairs_reseat", f"{r}.bbr")) for r in rids], b"BBR1")
    both = {r: pre["per_replay"][r] + res["per_replay"][r] for r in rids}
    dec_total = {r["rid"]: r["decisions_total"] for r in rows["reseat"]}
    print(dist_line("prefix-aligned records (.bbp)", pre["per_replay"].values()))
    print(dist_line("re-seated records (.bbr)     ", res["per_replay"].values()))
    print(dist_line("both                         ", both.values()))
    sd = sum(dec_total.values())
    print(f"decisions in the mapper scripts: {sd}; harvested prefix "
          f"{100 * pre['n'] / sd:.1f}%, with re-seat {100 * (pre['n'] + res['n']) / sd:.1f}%")
    sh = sorted(100 * both[r] / dec_total[r] for r in rids)
    print(f"share of a replay's decisions harvested: median {statistics.median(sh):.1f}% "
          f"p10 {q(sh, .1):.1f}% p90 {q(sh, .9):.1f}%")
    S = [r["summary"] for r in rows["reseat"]]
    spans = sum(s["spans"] for s in S)
    al = sum(s["spans_aligned"] for s in S)
    rs = sorted(s["reseats"] for s in S)
    dr = sum(s["spans_drift"] for s in S)
    print(f"boundary-to-boundary spans (team turns, a drive's set-up and kick-off "
          f"counted with the turn before it): {spans}; aligned end to end {al} "
          f"({100 * al / spans:.1f}%); reached the boundary but off the replay on "
          f"the pitch {dr} ({100 * dr / spans:.1f}%)")
    print(f"re-seats per replay: mean {statistics.mean(rs):.1f} median "
          f"{statistics.median(rs):.0f} p90 {q(rs, .9)} max {rs[-1]}; total {sum(rs)}")
    print(f"divergences {sum(s['divergences'] for s in S)}; decisions lost while "
          f"waiting for a boundary {sum(s['lost_decisions'] for s in S)}; boundaries "
          f"refused by the mapper {sum(s['seat_refused'] for s in S)}, by the runner "
          f"{sum(s['seat_failed'] for s in S)}; replays ending lost "
          f"{sum(1 for s in S if s['ended_lost'])}")
    why = collections.Counter()
    for r in rows["reseat"]:
        why.update(r["seat_skips"])
    print("   boundaries skipped while lost, by reason:", dict(why.most_common()))
    cause = collections.Counter()
    for r in rows["reseat"]:
        for e in r["reseats"]:
            cause[e["cause"]] += 1
    print("   re-seats by the class of the divergence before them:",
          dict(cause.most_common()))
    # hazard: divergences per 1000 records, prefix vs re-seated segments
    dv_pre = sum(1 for r in rows["reseat"] for d in r["divergences"] if d["seg"] == 0)
    dv_res = sum(1 for r in rows["reseat"] for d in r["divergences"] if d["seg"] > 0)
    print(f"stops per 1000 records: prefix {1000 * dv_pre / max(pre['n'], 1):.2f} "
          f"({dv_pre} stops), re-seated segments "
          f"{1000 * dv_res / max(res['n'], 1):.2f} ({dv_res} stops)")
    cls = {0: collections.Counter(), 1: collections.Counter()}
    for r in rows["reseat"]:
        for d in r["divergences"]:
            cls[1 if d["seg"] > 0 else 0][d["class"]] += 1
    print("   stop classes, prefix:  ", dict(cls[0].most_common()))
    print("   stop classes, re-seated:", dict(cls[1].most_common()))

    def ht(c, label):
        n = max(c["n"], 1)
        h2 = sum(v for (h, t), v in c["half_turn"].items() if h == 2)
        late = sum(v for (h, t), v in c["half_turn"].items() if t >= 5)
        early = sum(v for (h, t), v in c["half_turn"].items() if h == 1 and t in (1, 2))
        setup = sum(v for (h, t), v in c["half_turn"].items() if t == 0)
        print(f"{label}: half two {100 * h2 / n:.1f}%; team turns 5 to 8 (either half) "
              f"{100 * late / n:.1f}%; half one turns 1 to 2 {100 * early / n:.1f}%; "
              f"set-up and kick-off {100 * setup / n:.1f}%")
        return {"half2": h2 / n, "turn5to8": late / n, "h1_turn1to2": early / n,
                "setup_kickoff": setup / n}

    allc = {"n": pre["n"] + res["n"],
            "half_turn": pre["half_turn"] + res["half_turn"],
            "fam": pre["fam"] + res["fam"], "type": pre["type"] + res["type"]}
    out["yield"] = {
        "replays": N, "prefix_records": pre["n"], "reseat_records": res["n"],
        "decisions_total": sd, "spans": spans, "spans_aligned": al,
        "reseats_total": sum(rs), "reseats_median": statistics.median(rs),
        "prefix_dist": ht(pre, "prefix only "),
        "reseat_dist": ht(res, "re-seated   "),
        "both_dist": ht(allc, "both        ")}
    print("records by half and team turn (0 = set-up / kick-off):")
    print("   half turn   prefix  re-seated     both")
    for h in (1, 2):
        for t in range(0, 9):
            p_, r_ = pre["half_turn"][(h, t)], res["half_turn"][(h, t)]
            print(f"   {h:4d} {t:4d} {p_:8d} {r_:10d} {p_ + r_:8d}")
    K = 100 / N
    print("per 100 replays:        prefix    with re-seat   ratio")
    fam = {}
    for f in FAMILIES:
        p_, b_ = pre["fam"][f] * K, (pre["fam"][f] + res["fam"][f]) * K
        fam[f] = [round(p_, 1), round(b_, 1)]
        print(f"   {f:16s} {p_:10.1f} {b_:14.1f} {b_ / p_ if p_ else 0:7.1f}x")
    print(f"   {'all records':16s} {pre['n'] * K:10.1f} {(pre['n'] + res['n']) * K:14.1f} "
          f"{(pre['n'] + res['n']) / max(pre['n'], 1):7.1f}x")
    out["families_per_100"] = fam

    # ---- 4. label integrity -------------------------------------------------
    print("\n=== 4. LABEL INTEGRITY (from the shards alone) ===")
    print(f"prefix records with the action outside its own exact masks: "
          f"{pre['bad_label']} of {pre['n']}")
    print(f"re-seated records with the action outside its own exact masks: "
          f"{res['bad_label']} of {res['n']}")
    # how the span each re-seated record sits in ended (third pad byte)
    st = collections.Counter()
    for r in rids:
        path = os.path.join(D, "pairs_reseat", f"{r}.bbr")
        if os.path.exists(path):
            for rec in records(path, b"BBR1"):
                st[rec[11]] += 1
    n = max(res["n"], 1)
    for code, lab in ((1, "span closed; engine equal to the replay's boundary state"),
                      (4, "span closed; pitch equal, a resource / status / latch not"),
                      (2, "span closed without a stop but off the replay on the pitch"),
                      (3, "span closed against the mapper's mirror only (no seat)"),
                      (0, "span never closed (a stop came first, or the script ended)")):
        print(f"   {st[code]:7d} {100 * st[code] / n:5.1f}%  {lab}")
    out["integrity"] = {"prefix_bad_label": pre["bad_label"],
                        "reseat_bad_label": res["bad_label"],
                        "reseat_by_span_status": {str(k): v for k, v in st.items()}}
    if a.json:
        with open(a.json, "w") as f:
            json.dump(out, f, indent=1, sort_keys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
