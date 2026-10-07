"""How small are the log-probabilities of the search's candidates? Plain c55+m1 v chain37 games."""
import sys, collections
import numpy as np, torch
sys.path.insert(0, "/Users/alexanderhuth/Code/bb-harness-search")
from play_harness import engine as E, search as S, tournament as T
from play_harness.policy import MaskedPolicySeat, load_checkpoint, restrict_support

C = "/Users/alexanderhuth/Code/bb-play-harness/.play-artifacts/checkpoints/%s/0000002999975936.bin"
p55, _ = load_checkpoint(C % "chain55"); p37, _ = load_checkpoint(C % "chain37")
rows = []

class Probe(MaskedPolicySeat):
    def decide(self, logits, support, deciding):
        declared = self._after_declare
        out = super().decide(logits, support, deciding)
        if deciding:
            sup, _ = restrict_support(support, self.masks, declared)
            cls = S.decision_class({int(t) & 1023 for t in sup}, declared)
            if cls in S.SCOPE and len(sup) >= 2:
                lg = torch.as_tensor(logits).reshape(-1).double().numpy()
                tuples, probs = S.joint_probabilities(logits, sup, 1.0)
                order = S.candidate_order(tuples, E.pack_tuple(*out[0]), 4)
                with np.errstate(divide="ignore"):
                    lps = [float(np.log(probs[i])) for i in order]
                rows.append((cls, len(tuples), lps, [S.action_label(E.unpack_tuple(tuples[i])) for i in order],
                             float(lg.min()), float(lg.max())))
        return out

T.MaskedPolicySeat = Probe
for seed in (29920000, 29920001, 29920002):
    T.play_match(p55, p37, seed, masks=(("m1",), None))
alt = [lp for r in rows for lp in r[2][1:]]
alt = np.array(alt)
print("searched decisions", len(rows), "alternative candidates", alt.size)
for thr in (-7, -20, -50, -100, -300, -700):
    print(f"  alternatives with log p < {thr}: {(alt < thr).sum()} ({100*(alt<thr).mean():.1f}%)")
print("  -inf:", np.isinf(alt).sum(), " min finite:", alt[np.isfinite(alt)].min())
print("logit range seen: min", min(r[4] for r in rows), "max", max(r[5] for r in rows))
worst = sorted(rows, key=lambda r: min(r[2][1:]))[:8]
for cls, n, lps, labels, lo, hi in worst:
    print(cls, "support", n, [f"{l}:{v:.0f}" for l, v in zip(labels, lps)], f"logits [{lo:.0f}, {hi:.0f}]")
by = collections.Counter(len(r[2]) for r in rows); print("candidates per decision", dict(by))
