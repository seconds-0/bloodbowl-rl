"""Share of the search's predicted gain that sits at saturated decisions.
Reads the search probe's existing records only (no games played)."""
import json, math, sys, collections
import numpy as np
D = "/Users/alexanderhuth/Code/bb-play-harness/.play-artifacts/search-diag-20261007/"

def load(f):
    return [json.loads(l) for l in open(D + f)]

def bucket(p):
    if p >= 0.999999: return "3 sat  (a0 >= 0.999999)"
    if p >= 0.99: return "2 sharp (0.99 to 0.999999)"
    return "1 open (a0 < 0.99)"

def lp(p):
    return -1e9 if p <= 0 else math.log(p)

print("=== tail screens (16 rollouts per candidate; tail rule = gain > 0.10 and > 2 floored se as flagged by the tool: band == 'tail')")
rows = load("tail1/screen.jsonl") + load("tail2/screen.jsonl")
print("roots", len(rows), "bands", collections.Counter(r["band"] for r in rows))
tab = collections.defaultdict(lambda: dict(n=0, tail=0, band=0, gain_tail=0.0, gain_band=0.0))
for r in rows:
    p0 = r["probs"][0]
    for key in (bucket(p0), "all"):
        for cls in (r["class"], "both"):
            t = tab[(cls, key)]
            t["n"] += 1
            if r["band"] == "tail":
                t["tail"] += 1; t["gain_tail"] += r["gain"]
            elif r["band"] == "band":
                t["band"] += 1; t["gain_band"] += r["gain"]
tot_tail = tab[("both","all")]["gain_tail"]; tot_band = tab[("both","all")]["gain_band"]
for k in sorted(tab):
    t = tab[k]
    print(f"{k[0]:14s} {k[1]:28s} n={t['n']:5d} share_of_roots={t['n']/tab[(k[0],'all')]['n']:.3f} "
          f"tail={t['tail']:3d} ({100*t['tail']/t['n']:.2f}%) band={t['band']:3d} ({100*t['band']/t['n']:.2f}%) "
          f"tail_gain_share={t['gain_tail']/tot_tail if tot_tail else 0:.3f} band_gain_share={t['gain_band']/tot_band if tot_band else 0:.3f}")

print()
print("a0 is the policy's most probable candidate:", sum(r["a0_rank"] == 1 for r in rows), "of", len(rows))
tails = [r for r in rows if r["band"] == "tail"]
bands = [r for r in rows if r["band"] == "band"]
def alt_lp(r):
    return lp(r["probs"][r["best"]])
for name, rs in (("tail", tails), ("band", bands)):
    a = np.array([alt_lp(r) for r in rs])
    print(f"{name}: n={len(rs)} chosen alternative log-prob: median {np.median(a):.1f}, "
          f"share below ln(1e-2) {np.mean(a < math.log(1e-2)):.2f}, below ln(1e-4) {np.mean(a < math.log(1e-4)):.2f}, "
          f"below ln(1e-6) {np.mean(a < math.log(1e-6)):.2f}, below -20 {np.mean(a < -20):.2f}, below -50 {np.mean(a < -50):.2f}")
    a0 = np.array([r["probs"][0] for r in rs])
    print(f"   a0 prob >= 0.999999: {np.mean(a0 >= 0.999999):.2f}; >= 0.99: {np.mean(a0 >= 0.99):.2f}; a0 rank 1: {np.mean([r['a0_rank']==1 for r in rs]):.2f}")
print()
print("tail deviations by (class, a0 type -> chosen type):")
c = collections.Counter((r["class"], r["types"][0], r["types"][r["best"]]) for r in tails)
for k, v in c.most_common(): print("  ", v, k)
print("all roots by (class, a0 type), with saturation share and tail rate:")
c2 = collections.defaultdict(lambda: [0, 0, 0])
for r in rows:
    k = (r["class"], r["types"][0])
    c2[k][0] += 1; c2[k][1] += r["probs"][0] >= 0.999999; c2[k][2] += r["band"] == "tail"
for k, v in sorted(c2.items(), key=lambda kv: -kv[1][0]):
    print(f"   {str(k):40s} n={v[0]:4d} saturated={v[1]/v[0]:.2f} tail={v[2]:3d} ({100*v[2]/v[0]:.1f}%)")

print()
print("=== run 1 (240 roots, 128 rollouts; choose best alternative on rollouts 0-63, judge on 64-127)")
rows1 = load("run1/roots.jsonl")
tab = collections.defaultdict(lambda: dict(n=0, dev=0, judged=0.0, flagged=0))
for r in rows1:
    R = np.array(r["returns"])  # candidates x rollouts
    if R.shape[0] < 2: continue
    sel = R[:, :64]; jud = R[:, 64:]
    d_sel = sel[1:] - sel[0:1]
    b = int(np.argmax(d_sel.mean(axis=1))) + 1
    g_sel = d_sel[b-1].mean()
    dj = jud[b] - jud[0]
    gj = dj.mean(); sej = dj.std(ddof=1) / math.sqrt(len(dj))
    p0 = r["probs"][0]
    for key in (bucket(p0), "all"):
        t = tab[key]; t["n"] += 1
        if g_sel > 0.02:
            t["dev"] += 1; t["judged"] += gj
            if gj > 0.02 and gj > 2 * sej: t["flagged"] += 1
tot = tab["all"]["judged"]
for k in sorted(tab):
    t = tab[k]
    print(f"{k:28s} n={t['n']:3d} deviates(sel gain>0.02)={t['dev']:3d} judged>0.02&2se={t['flagged']:3d} "
          f"judged gain per root={t['judged']/t['n']:.4f} share of judged gain={t['judged']/tot:.3f}")
