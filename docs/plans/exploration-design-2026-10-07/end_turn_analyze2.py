import json, sys, math
import numpy as np
rows = [json.loads(l) for l in open(sys.argv[1])]
rng = np.random.default_rng(0); GAMMA = 0.999
def bucket(lp0):
    p = math.exp(lp0)
    return "sat" if p >= 0.999999 else ("sharp" if p >= 0.99 else "open")
def boot(vals, games, reps=2000):
    vals = np.asarray(vals, float); games = np.asarray(games)
    ug = np.unique(games); idx = {g: np.flatnonzero(games == g) for g in ug}
    out = [vals[np.concatenate([idx[g] for g in rng.choice(ug, len(ug))])].mean() for _ in range(reps)]
    return np.percentile(out, [2.5, 97.5])
def ci(v, g):
    c = boot(v, g); return f"{np.mean(v):+.4f} [{c[0]:+.4f}, {c[1]:+.4f}]"
for kind in ("end_turn", "decline_block", "activate"):
    R = [r for r in rows if r["kind"] == kind and len(r["tuples"]) >= 2]
    print(f"== {kind}: {len(R)} roots, {len(set(r['game'] for r in R))} games. Differences are first alternative minus a0.")
    recs = []
    for r in R:
        G = np.array(r["returns"], float); Rw = np.array(r["reward_part"], float); V = np.array(r["bootstrap"], float); T = np.array(r["steps_each"], float)
        ok = np.isfinite(G).all(axis=0)
        G, Rw, V, T = G[:, ok], Rw[:, ok], V[:, ok], T[:, ok]
        disc = GAMMA ** T
        # G = Rw + disc * V ; undiscounted-bootstrap variant: Rw + V
        tax = (disc - 1.0) * V                      # what the per-step discount takes from the bootstrap
        n = G.shape[1]; d = G[1:] - G[0:1]
        a, b = np.arange(0, n // 2), np.arange(n // 2, n)
        best = int(np.argmax(d[:, a].mean(axis=1)))
        gb = d[best, b].mean(); seb = d[best, b].std(ddof=1) / math.sqrt(len(b)); ga = d[best, a].mean()
        recs.append(dict(game=r["game"], b=bucket(r["logp"][0]), dG=(G[1]-G[0]).mean(), dR=(Rw[1]-Rw[0]).mean(),
                         dV=(V[1]-V[0]).mean(), dTax=(tax[1]-tax[0]).mean(), V0=V[0].mean(), T1=T[1].mean(), T0=T[0].mean(),
                         judged=gb, flag=(gb > 0.02 and gb > 2*seb), big=(gb > 0.10 and gb > 2*seb), neg=(gb < -0.02 and gb < -2*seb),
                         rule=(gb if ga > 0.02 else 0.0)))
    for bk in ("open", "sharp", "sat", "all"):
        rr = [x for x in recs if bk == "all" or x["b"] == bk]
        if len(rr) < 2: continue
        g = [x["game"] for x in rr]
        f = lambda k: ci([x[k] for x in rr], g)
        print(f"  {bk:5s} n={len(rr):3d} return {f('dG')} = reward part {f('dR')} + undiscounted value {f('dV')} + discount on the bootstrap {f('dTax')}")
        print(f"        V after a0 mean {np.mean([x['V0'] for x in rr]):+.3f}; steps a0 {np.mean([x['T0'] for x in rr]):.1f}, alt {np.mean([x['T1'] for x in rr]):.1f}; "
              f"best-of judged {f('judged')}; >0.02&2se {np.mean([x['flag'] for x in rr]):.2f}; >0.10&2se {np.mean([x['big'] for x in rr]):.2f}; <-0.02&2se {np.mean([x['neg'] for x in rr]):.2f}; rule gain/root {f('rule')}")
