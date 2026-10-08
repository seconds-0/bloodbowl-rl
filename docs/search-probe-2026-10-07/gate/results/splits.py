"""Descriptive splits of the accepted search gate (made after the report was read; not part of the reading)."""
import json, math, sys, collections
import numpy as np
G = sys.argv[1]
recs = collections.defaultdict(dict)
with open(G) as f:
    for line in f:
        r = json.loads(line)
        recs[tuple(r["pair"])][(r["engine_seed"], r["leg"])] = r
def elo(w, l):
    return 400 * math.log10(w / l) if w and l else float("nan")
print("made after the report was read; raw counts, descriptive only")
for opp in ("chain37", "chain46"):
    S, C = recs[("c55m1s", opp)], recs[("c55m1", opp)]
    keys = sorted(S)
    assert keys == sorted(C)
    print(f"\n== against {opp}: {len(keys)} games an arm")
    # by shard
    print("by droplet (200 seeds each): S decisive share, C decisive share, S-C decisive-Elo")
    for j in range(8):
        ks = [k for k in keys if (S[k]["game_index"] // 200) == j]
        def wl(D):
            w = sum(D[k]["result_a"] == "W" for k in ks); l = sum(D[k]["result_a"] == "L" for k in ks); return w, l
        (sw, sl), (cw, cl) = wl(S), wl(C)
        print(f"  s{j+1}: {len(ks)} games  S {sw}/{sl} {sw/(sw+sl):.3f}  C {cw}/{cl} {cw/(cw+cl):.3f}  diff {elo(sw,sl)-elo(cw,cl):+.1f}")
    # by leg
    for leg in ("A_home", "B_home"):
        ks = [k for k in keys if k[1] == leg]
        sw = sum(S[k]["result_a"] == "W" for k in ks); sl = sum(S[k]["result_a"] == "L" for k in ks)
        cw = sum(C[k]["result_a"] == "W" for k in ks); cl = sum(C[k]["result_a"] == "L" for k in ks)
        print(f"  leg {leg}: S {sw/(sw+sl):.3f}  C {cw/(cw+cl):.3f}  diff {elo(sw,sl)-elo(cw,cl):+.1f}")
    # same-game comparison
    same = sum(S[k]["action_trail_sha256"] == C[k]["action_trail_sha256"] for k in keys)
    print(f"  games whose action trail equals the control's: {same}")
    tab = collections.Counter((C[k]["result_a"], S[k]["result_a"]) for k in keys if S[k]["action_trail_sha256"] != C[k]["action_trail_sha256"])
    print("  where the trails differ, control result -> search result:", dict(sorted(tab.items())))
    # paired TD difference, seed clusters
    seeds = sorted({k[0] for k in keys})
    def per_seed(D, fn):
        return np.array([sum(fn(D[(s, leg)]) for leg in ("A_home", "B_home")) / 2 for s in seeds])
    tdS = per_seed(S, lambda r: r["a_td"] - r["b_td"]); tdC = per_seed(C, lambda r: r["a_td"] - r["b_td"])
    aS = per_seed(S, lambda r: r["a_td"]); aC = per_seed(C, lambda r: r["a_td"])
    bS = per_seed(S, lambda r: r["b_td"]); bC = per_seed(C, lambda r: r["b_td"])
    wsS = per_seed(S, lambda r: {"W": 1, "D": .5, "L": 0}[r["result_a"]]); wsC = per_seed(C, lambda r: {"W": 1, "D": .5, "L": 0}[r["result_a"]])
    rng = np.random.default_rng(0)
    idx = rng.integers(0, len(seeds), size=(2000, len(seeds)))
    for name, d in (("TD difference per game, S minus C", tdS - tdC), ("own TD per game, S minus C", aS - aC), ("opponent TD per game, S minus C", bS - bC), ("win score, S minus C", wsS - wsC)):
        b = d[idx].mean(axis=1)
        print(f"  {name}: {d.mean():+.3f} [{np.percentile(b,2.5):+.3f}, {np.percentile(b,97.5):+.3f}]")
    secs = np.array([S[k]["seconds"] for k in keys]); print(f"  searched game seconds: mean {secs.mean():.1f}, median {np.median(secs):.1f}, max {secs.max():.1f}")
    dec = max(max(r["decisions"]) for r in list(S.values()) + list(C.values())); print(f"  longest side decision count {dec}; longest game {max(r['engine_decisions'] for r in list(S.values())+list(C.values()))} engine decisions")
