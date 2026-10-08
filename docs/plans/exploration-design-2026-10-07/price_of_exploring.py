import json, math, numpy as np, collections
D = "/Users/alexanderhuth/Code/bb-play-harness/.play-artifacts/search-diag-20261007/"
rows = [json.loads(l) for f in ("tail1/screen.jsonl", "tail2/screen.jsonl") for l in open(D + f)]
alt_gain = []; alt_lp = []; first_alt = []
tail_snr = []
for r in rows:
    G = np.array(r["returns"], float); ok = np.isfinite(G).all(axis=0); G = G[:, ok]
    if G.shape[0] < 2: continue
    d = G[1:] - G[0:1]
    for i in range(d.shape[0]):
        alt_gain.append(d[i].mean()); alt_lp.append(math.log(max(r["probs"][i+1], 1e-300)))
    first_alt.append(d[0].mean())
    if r["band"] == "tail":
        b = r["best"] - 1
        # single-sample advantage of the tail alternative against the mean return of a0 (a stand-in for V)
        adv = G[b+1] - G[0].mean()
        tail_snr.append((adv.mean(), adv.std(ddof=1), (adv > 0).mean(), d[b].std(ddof=1)))
alt_gain = np.array(alt_gain); alt_lp = np.array(alt_lp)
print("roots", len(rows), "alternative candidates", len(alt_gain))
print(f"mean gain of an alternative (top three by policy probability) over a0: {alt_gain.mean():+.4f}; median {np.median(alt_gain):+.4f}; "
      f"10th pct {np.percentile(alt_gain,10):+.4f}; share below -0.02: {(alt_gain<-0.02).mean():.2f}; share above +0.02: {(alt_gain>0.02).mean():.2f}")
print(f"mean gain of the most probable alternative: {np.mean(first_alt):+.4f}")
for lo, hi, name in ((math.log(1e-2), 1, ">=1e-2"), (math.log(1e-6), math.log(1e-2), "1e-6..1e-2"), (-50, math.log(1e-6), "e^-50..1e-6"), (-1e9, -50, "<e^-50")):
    m = (alt_lp >= lo) & (alt_lp < hi)
    print(f"  alternatives with prob {name:12s}: n={m.sum():5d} mean gain {alt_gain[m].mean():+.4f}; raw 16-rollout gain above +0.10: {(alt_gain[m]>0.10).mean():.3f}; below -0.10: {(alt_gain[m]<-0.10).mean():.3f}")
t = np.array(tail_snr)
print(f"tail roots {len(t)}: single-rollout advantage of the chosen alternative: mean {t[:,0].mean():.3f}, sd within root (mean) {t[:,1].mean():.3f}, share of single rollouts with positive advantage {t[:,2].mean():.2f}; paired sd {t[:,3].mean():.3f}")
allsd = [np.array(r['returns'], float)[0].std(ddof=1) for r in rows]
print(f"sd of a0's own return across rollouts, mean over roots: {np.nanmean(allsd):.3f}")
