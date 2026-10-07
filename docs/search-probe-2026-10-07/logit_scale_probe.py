"""Logit scale and sharpness by checkpoint: plain self-play games, every own decision of side 0."""
import sys, os
import numpy as np, torch
sys.path.insert(0, "/Users/alexanderhuth/Code/bb-harness-search")
from play_harness import engine as E, search as S, tournament as T
from play_harness.policy import PolicySeat, load_checkpoint

STORE = "/Users/alexanderhuth/Code/bb-play-harness/.play-artifacts/checkpoints/%s/0000002999975936.bin"
rows = []

class Probe(PolicySeat):
    def decide(self, logits, support, deciding):
        out = super().decide(logits, support, deciding)
        if deciding and self.seat == 0:
            lg = torch.as_tensor(logits).reshape(-1).double().numpy()
            tuples, logp = S.joint_log_probabilities(logits, support, 1.0)
            p = np.exp(logp)
            ent = float(-(p[p > 0] * logp[p > 0]).sum())
            rows.append((len(tuples), float(lg.max() - lg.min()), float(np.abs(lg).max()), float(p[0]),
                         ent, float(logp[1]) if len(logp) > 1 else np.nan))
        return out

for name in sys.argv[1:]:
    path = STORE % name
    if not os.path.exists(path):
        print(name, "missing"); continue
    pol, _ = load_checkpoint(path)
    rows.clear()
    for seed in range(29930000, 29930006):
        T.play_match(pol, pol, seed, seat_factory=Probe)
    r = np.array([x for x in rows if x[0] >= 2])
    print(f"{name}: {len(r)} decisions with a choice | max |logit| median {np.median(r[:,2]):.0f} p90 {np.percentile(r[:,2],90):.0f} max {r[:,2].max():.0f}"
          f" | top action p > 0.99: {100*(r[:,3]>0.99).mean():.0f}%  p > 0.999999: {100*(r[:,3]>0.999999).mean():.0f}%"
          f" | mean entropy {r[:,4].mean():.3f} nats | second action log p median {np.nanmedian(r[:,5]):.0f}")
