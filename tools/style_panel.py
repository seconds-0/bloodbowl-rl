#!/usr/bin/env python3
"""style_panel.py - fixed six-number "how human does it play" panel for a
checkpoint, read from its scripted-bot exam logs. Read-only, stdlib only.

    python3 style_panel.py EXAM_DIR [EXAM_DIR ...]      # dirs searched recursively for *.log
    python3 style_panel.py --bundle FILE [FILE ...]     # "@@FILE <path>" + manifest + JSON lines
    options: --human docs/human-baseline.json   --cells   --json
             --result X.result.json [...]   add the trainer's end-of-run eval
                                            (also accepts a .jsonl of {"path","eval"})

Each exam log carries one BB_EVAL_MANIFEST line (bot_team, bot_type, checkpoint
hash) and cumulative PUFFER_ENV_JSON eval panels; the last one is the whole run.
The policy ("champion") is team 1 - bot_team. All numbers are per full game
from kickoff (the script refuses curriculum-start logs).

The six numbers and whose behaviour each one is (puffer/bloodbowl/bloodbowl.h,
bbe_count_action):
  TD     tds_t<policy>. Policy side only. Human: tds / 2.
  BLK    blocks_thrown_t<policy>: RESOLVED blocks (one per BB_A_CHOOSE_DIE).
         Policy side, +/- the red-dice blocks ("+/-" column), which the env
         books to the DEFENDER's team because the defender picks the die.
         Human: resolved blocks / 2.
  BALL   pass_attempts + handoff_attempts. Logged for both teams together, but
         both scripted bots score those declarations at -700 or worse, so in
         exam games this is the policy's. Human: (pass tests reached +
         hand-offs) / 2.
  RISK   dodge_attempts + gfi_attempts, BOTH teams (no per-team split in the
         log; the contact bot rushes a lot). Human: dodge + rush tests reached,
         both teams.
  POSS   possession_rate, BOTH teams pooled: share of completed team turns that
         ended holding the ball (touchdown turns count). Human: per-game mean.
  BLITZ  blitz declarations, BOTH teams (32 team turns a game, one blitz
         allowed per turn). No human reference has been measured.
"""
import json
import os
import re
import sys

MAN = "BB_EVAL_MANIFEST "
ENV = "PUFFER_ENV_JSON "
BOT = {0: "contact", 1: "offense"}
HUMAN_DEFAULT = os.path.expanduser("~/Code/bb-opt-build/docs/human-baseline.json")


def read_log(lines):
    """Return (manifest, final eval panel) from an iterable of log lines."""
    man, last = None, None
    for line in lines:
        if line.startswith(MAN) and man is None:
            man = json.loads(line[len(MAN):])
        elif line.startswith(ENV):
            try:
                p = json.loads(line[len(ENV):])
            except json.JSONDecodeError:
                continue
            if p.get("_puffer_phase_eval", 0) > 0 and p.get("n", 0) > 0:
                last = p
    return man, last


def label_of(path):
    m = re.search(r"exam-c(\d+)-s(\d+)", path)
    if m:
        return "c" + m.group(1), "s" + m.group(2)
    m = re.search(r"chain(\d+)[^/]*/exam-attempt(\d+)/s(\d+)", path)
    if m:
        return "c" + m.group(1), "s" + m.group(3)
    m = re.search(r"exam-r0chain(\d+)h?(?:-s(\d+))?/", path)
    if m:
        return "c" + m.group(1), "s" + (m.group(2) or "42")
    m = re.search(r"r0chain(\d+)", path)
    if m:
        return "c" + m.group(1), "-"
    return os.path.basename(os.path.dirname(path)) or path, "-"


def row(path, p, c, opp, bot):
    """One cell. c = policy team, opp = other team, bot = opponent label."""
    if p.get("demo_episodes", 0) > 0.01:
        raise SystemExit(f"{path}: curriculum starts (demo_episodes>0); not per-game")
    if p.get("illegal_frac", 0) != 0:
        raise SystemExit(f"{path}: illegal_frac is nonzero")
    red = p["blocks_thrown"] * (p.get("block_2dred_frac", 0.0) + p.get("block_3dred_frac", 0.0))
    chain, seed = label_of(path)
    return {
        "chain": chain, "seed": seed, "path": path, "bot": bot, "n": p["n"],
        "score": p[f"slot_{c}_score"],
        "td": p[f"tds_t{c}"], "td_opp": p[f"tds_t{opp}"],
        "blk": p[f"blocks_thrown_t{c}"], "blk_opp": p[f"blocks_thrown_t{opp}"],
        "blk_red": red,
        "decl": p["blocks"] + p["blitzes"], "blitz": p["blitzes"],
        "pass": p["pass_attempts"], "handoff": p["handoff_attempts"],
        "ball": p["pass_attempts"] + p["handoff_attempts"],
        "dodge": p["dodge_attempts"], "rush": p["gfi_attempts"],
        "risk": p["dodge_attempts"] + p["gfi_attempts"],
        "pickup": p["pickup_attempts"], "pickup_ok": p["pickup_success"],
        "poss": p["possession_rate"],
        "kd_inf": p["knockdowns_inflicted"], "kd_own": p["knockdowns_own"],
        "two_d": p.get("block_2d_frac", 0.0) + p.get("block_3d_frac", 0.0),
        "stall": p.get(f"stall_rolls_t{c}", float("nan")),
        "len": p["episode_length"],
    }


def exam_row(path, man, p):
    if man is None or p is None or "bot_team" not in man:
        return None  # not a scripted-bot exam log (e.g. a kickoff mirror)
    bt = int(man["bot_team"])
    return row(path, p, 1 - bt, bt, BOT.get(int(man["bot_type"]), "bot?"))


def gather(args, bundle):
    rows = []
    if bundle:
        for f in args:
            path, buf = None, []
            for line in open(f, errors="ignore"):
                if line.startswith("@@FILE "):
                    if path:
                        rows.append(exam_row(path, *read_log(buf)))
                    path, buf = line.split(None, 1)[1].strip(), []
                else:
                    buf.append(line)
            if path:
                rows.append(exam_row(path, *read_log(buf)))
    else:
        for d in args:
            for root, _, files in os.walk(d):
                for name in sorted(files):
                    if name.endswith(".log"):
                        path = os.path.join(root, name)
                        with open(path, errors="ignore") as fh:
                            rows.append(exam_row(path, *read_log(fh)))
    return [r for r in rows if r]


def gather_results(files):
    """End-of-run trainer eval: the learner is team 0; team 1 is the frozen
    pool, with the contact bot on one bank tag."""
    rows = []
    for f in files:
        if f.endswith(".jsonl"):
            recs = [json.loads(line) for line in open(f)]
            recs = [(r["path"], r.get("eval")) for r in recs]
        else:
            recs = [(f, json.load(open(f)).get("eval_metrics"))]
        for path, p in recs:
            if p:
                rows.append(row(path, p, 0, 1, "pool"))
    return rows


NUM = ["score", "td", "td_opp", "blk", "blk_opp", "blk_red", "decl", "blitz", "pass",
       "handoff", "ball", "dodge", "rush", "risk", "pickup", "pickup_ok", "poss",
       "kd_inf", "kd_own", "two_d", "stall", "len"]


def pool(rows):
    if not rows:
        return None
    n = sum(r["n"] for r in rows)
    out = {k: sum(r[k] * r["n"] for r in rows) / n for k in NUM}
    out["n"], out["cells"] = n, len(rows)
    return out


def human(path):
    b = json.load(open(path))
    return {
        "td": b["tds_per_game_bb2025_exact"] / 2,
        "blk": b["resolved_blocks_per_game_bb2025"] / 2,
        "ball": (b["pass_tests_reached_per_game_bb2025"] + b["handoff_per_game_bb2025"]) / 2,
        "risk": b["dodge_tests_reached_per_game_bb2025"] + b["rush_tests_reached_per_game_bb2025"],
        "poss": b["possession_rate_bb2025_per_game_mean"],
        "n": b["_possession_bb2025_games"],
    }


def chain_key(c):
    m = re.match(r"c(\d+)$", c)
    return (0, int(m.group(1))) if m else (1, c)


def take(av, flag):
    """Pop '--flag v1 v2 ...' (values up to the next --option) out of av."""
    if flag not in av:
        return []
    i = av.index(flag)
    j = i + 1
    while j < len(av) and not av[j].startswith("--"):
        j += 1
    vals = av[i + 1:j]
    del av[i:j]
    return vals


def main():
    av = sys.argv[1:]
    hp = (take(av, "--human") or [HUMAN_DEFAULT])[0]
    results = take(av, "--result")
    bundles = take(av, "--bundle")
    flags = {a for a in av if a.startswith("--")}
    dirs = [a for a in av if not a.startswith("--")]
    rows = gather(bundles, True) + gather(dirs, False)
    rrows = gather_results(results)
    if not rows and not rrows:
        raise SystemExit(__doc__)
    h = human(hp) if os.path.exists(hp) else None
    chains = sorted({r["chain"] for r in rows + rrows}, key=chain_key)
    out = {}
    for c in chains:
        cr = [r for r in rows if r["chain"] == c]
        out[c] = {"exam": pool(cr),
                  "contact": pool([r for r in cr if r["bot"] == "contact"]),
                  "offense": pool([r for r in cr if r["bot"] == "offense"]),
                  "pool": pool([r for r in rrows if r["chain"] == c])}
    if "--json" in flags:
        print(json.dumps({"human": h, "chains": out}, indent=1))
        return
    hdr = (f"{'ckpt':<6}{'vs':<9}{'games':>7}{'score':>7}{'TD':>7}{'BLK':>7}{'+/-':>6}"
           f"{'BALL':>8}{'RISK':>7}{'POSS':>7}{'BLITZ':>7}")
    print("STYLE PANEL, per game. TD and BLK: policy side. BALL: policy side vs bots,"
          " both teams vs pool. RISK, POSS, BLITZ: both teams.")
    print(hdr)
    print("-" * len(hdr))
    if h:
        print(f"{'human':<6}{'human':<9}{h['n']:>7.0f}{'':>7}{h['td']:>7.2f}{h['blk']:>7.1f}{'':>6}"
              f"{h['ball']:>8.3f}{h['risk']:>7.1f}{h['poss']:>7.3f}{'n/m':>7}")
    for c in chains:
        for kind, tag in (("exam", "bots"), ("pool", "pool")):
            a = out[c][kind]
            if a:
                print(f"{c:<6}{tag:<9}{a['n']:>7.0f}{a['score']:>7.3f}{a['td']:>7.2f}{a['blk']:>7.1f}"
                      f"{a['blk_red']:>6.1f}{a['ball']:>8.3f}{a['risk']:>7.1f}"
                      f"{a['poss']:>7.3f}{a['blitz']:>7.1f}")
    if "--cells" in flags:
        print("\ndetail by opponent (pooled over seeds and sides). TD/BLK are policy side,"
              " oTD/oBLK the opponent's; every other column is both teams.")
        print(f"{'ckpt':<6}{'vs':<9}{'games':>6}{'TD':>6}{'oTD':>6}{'BLK':>6}{'oBLK':>6}"
              f"{'decl':>6}{'blitz':>6}{'pass':>7}{'hoff':>7}{'dodge':>6}{'rush':>6}"
              f"{'pick':>6}{'pk_ok':>6}{'poss':>6}{'kdInf':>6}{'kdOwn':>6}{'2d+':>6}{'stall':>7}{'len':>6}")
        for c in chains:
            for b in ("contact", "offense", "pool"):
                a = out[c][b]
                if a:
                    print(f"{c:<6}{b:<9}{a['n']:>6.0f}{a['td']:>6.2f}{a['td_opp']:>6.2f}{a['blk']:>6.1f}"
                          f"{a['blk_opp']:>6.1f}{a['decl']:>6.1f}{a['blitz']:>6.1f}{a['pass']:>7.3f}"
                          f"{a['handoff']:>7.3f}{a['dodge']:>6.1f}{a['rush']:>6.1f}{a['pickup']:>6.1f}"
                          f"{a['pickup_ok']:>6.1f}{a['poss']:>6.3f}{a['kd_inf']:>6.1f}{a['kd_own']:>6.1f}"
                          f"{a['two_d']:>6.2f}{a['stall']:>7.3f}{a['len']:>6.0f}")


if __name__ == "__main__":
    main()
