import json, sys, math, collections
import numpy as np
rows = [json.loads(l) for l in open(sys.argv[1])]
rng = np.random.default_rng(0)
def bucket(lp0):
    p = math.exp(lp0)
    return "sat (a0>=0.999999)" if p >= 0.999999 else ("sharp (0.99..)" if p >= 0.99 else "open (a0<0.99)")
def boot(vals, games, reps=2000):
    vals = np.asarray(vals, float); games = np.asarray(games)
    ug = np.unique(games); idx = {g: np.flatnonzero(games == g) for g in ug}
    out = []
    for _ in range(reps):
        pick = rng.choice(ug, len(ug)); ii = np.concatenate([idx[g] for g in pick])
        out.append(vals[ii].mean())
    return np.percentile(out, [2.5, 97.5])
for kind in ("end_turn", "decline_block"):
    R = [r for r in rows if r["kind"] == kind and len(r["tuples"]) >= 2]
    print(f"== {kind}: {len(R)} roots from {len(set(r['game'] for r in R))} games; rollouts per candidate {len(R[0]['returns'][0])}")
    recs = []
    for r in R:
        G = np.array(r["returns"], float)
        G = G[:, np.isfinite(G).all(axis=0)]
        n = G.shape[1]; d = G[1:] - G[0:1]
        a, b = np.arange(0, n // 2), np.arange(n // 2, n)
        best = int(np.argmax(d[:, a].mean(axis=1)))
        gb = d[best, b].mean(); seb = d[best, b].std(ddof=1) / math.sqrt(len(b))
        ga = d[best, a].mean()
        recs.append(dict(game=r["game"], b=bucket(r["logp"][0]), alt1=d[0].mean(), alt1_se=d[0].std(ddof=1)/math.sqrt(n),
                         sel=ga, judged=gb, se=seb, rule=(gb if ga > 0.02 else 0.0), rule10=(gb if ga > 0.10 else 0.0),
                         flag=(gb > 0.02 and gb > 2 * seb), big=(gb > 0.10 and gb > 2 * seb), neg=(gb < -0.02 and gb < -2*seb),
                         lp_alt=r["logp"][1 + best], steps0=r["steps"][0], steps1=r["steps"][1]))
    for bk in ("open (a0<0.99)", "sharp (0.99..)", "sat (a0>=0.999999)", "all"):
        rr = [x for x in recs if bk == "all" or x["b"] == bk]
        if not rr: continue
        g = [x["game"] for x in rr]
        m1 = np.mean([x["alt1"] for x in rr]); c1 = boot([x["alt1"] for x in rr], g)
        mr = np.mean([x["rule"] for x in rr]); cr = boot([x["rule"] for x in rr], g)
        mj = np.mean([x["judged"] for x in rr]); cj = boot([x["judged"] for x in rr], g)
        print(f"  {bk:20s} n={len(rr):3d} | most probable alternative minus a0: {m1:+.4f} [{c1[0]:+.4f}, {c1[1]:+.4f}]"
              f" | half-A best judged on half B: {mj:+.4f} [{cj[0]:+.4f}, {cj[1]:+.4f}]"
              f" | judged >0.02 & 2se: {np.mean([x['flag'] for x in rr]):.2f}, >0.10 & 2se: {np.mean([x['big'] for x in rr]):.2f}, < -0.02 & 2se: {np.mean([x['neg'] for x in rr]):.2f}"
              f" | rule(0.02) gain per root {mr:+.4f} [{cr[0]:+.4f}, {cr[1]:+.4f}]"
              f" | alt log-prob median {np.median([x['lp_alt'] for x in rr]):.0f}")
    print(f"  mean engine steps per rollout: a0 {np.mean([x['steps0'] for x in recs]):.1f}, first alternative {np.mean([x['steps1'] for x in recs]):.1f}")
