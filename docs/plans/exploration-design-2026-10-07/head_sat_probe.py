"""Which head is saturated, and how saturated are END_TURN and END_ACTIVATION?
Plain self-play, every own decision of side 0 with two or more legal joint actions.
Read-only use of the harness; output goes to stdout."""
import sys, os, collections, json
import numpy as np, torch
sys.path.insert(0, "/Users/alexanderhuth/Code/bb-harness-search")
from play_harness import engine as E, search as S, tournament as T
from play_harness.policy import PolicySeat, load_checkpoint

STORE = "/Users/alexanderhuth/Code/bb-play-harness/.play-artifacts/checkpoints/%s/0000002999975936.bin"
OFF = S._HEAD_OFFSETS
rows = []

def head_stats(lg, packed):
    """Per head, on the path of the most probable joint action: number of legal
    values, top conditional probability, log-prob of the second value, legal logit range."""
    out = []
    keep = np.ones(packed.size, bool)
    for h in range(3):
        vals = (packed >> (10 * h)) & 1023
        legal = np.unique(vals[keep])
        l = lg[OFF[h] + legal]
        top = l.max()
        lp = l - top - np.log(np.exp(l - top).sum())
        srt = np.sort(lp)[::-1]
        best = legal[int(np.argmax(l))]
        out.append((len(legal), float(np.exp(srt[0])), float(srt[1]) if len(srt) > 1 else float("nan"),
                    float(l.max() - l.min())))
        keep &= vals == best
    return out

class Probe(PolicySeat):
    prev_declare = False
    def decide(self, logits, support, deciding):
        out = super().decide(logits, support, deciding)
        if deciding and self.seat == 0:
            lg = torch.as_tensor(logits).reshape(-1).double().numpy()
            tuples, logp = S.joint_log_probabilities(logits, support, 1.0)
            types = np.array([int(t) & 1023 for t in tuples])
            tset = set(types.tolist())
            cls = S.decision_class(tset, self.prev_declare)
            if len(tuples) >= 2:
                p = np.exp(logp)
                def mass(name):
                    m = types == E.A[name]
                    return float(p[m].sum()) if m.any() else None
                rows.append(dict(cls=cls, n=len(tuples), top=float(p[0]), lp2=float(logp[1]),
                                 top_type=E.ACTION_TYPES[types[0]], second_type=E.ACTION_TYPES[types[1]],
                                 played=E.ACTION_TYPES[out[0][0]], heads=head_stats(lg, np.asarray(tuples, dtype=np.int64)),
                                 legal_gap=float(logp[0] - logp[-1]),
                                 maxabs_all=float(np.abs(lg).max()),
                                 p_end_turn=mass("END_TURN"), has_activate=E.A["ACTIVATE"] in tset,
                                 p_end_act=mass("END_ACTIVATION"), has_block=E.A["BLOCK_TARGET"] in tset,
                                 p_block=mass("BLOCK_TARGET")))
            self.prev_declare = (out[0][0] == E.A["DECLARE"])
        return out

def pct(x): return f"{100*x:.0f}%"
for name in sys.argv[1:]:
    pol, _ = load_checkpoint(STORE % name)
    rows.clear()
    for seed in range(29930000, 29930006):
        T.play_match(pol, pol, seed, seat_factory=Probe)
    R = rows
    top = np.array([r["top"] for r in R])
    print(f"== {name}: {len(R)} decisions with a choice; top > 0.999999: {pct((top>0.999999).mean())}; top > 0.99: {pct((top>0.99).mean())}")
    print(f"   largest |logit| over all 454 outputs, median {np.median([r['maxabs_all'] for r in R]):.0f}; "
          f"log-prob gap between most and least probable LEGAL joint action, median {np.median([r['legal_gap'] for r in R]):.0f}, p90 {np.percentile([r['legal_gap'] for r in R],90):.0f}")
    for h, hn in enumerate(("type", "arg | type", "square | type,arg")):
        live = [r["heads"][h] for r in R if r["heads"][h][0] >= 2]
        if not live: continue
        tp = np.array([x[1] for x in live]); l2 = np.array([x[2] for x in live]); rg = np.array([x[3] for x in live])
        print(f"   head {h} ({hn}): has a choice at {pct(len(live)/len(R))} of decisions; of those top > 0.999999: {pct((tp>0.999999).mean())}, "
              f"top > 0.99: {pct((tp>0.99).mean())}; second value log-prob median {np.median(l2):.0f}; legal logit range median {np.median(rg):.0f}, p90 {np.percentile(rg,90):.0f}")
    print("   by class:")
    for cls in ("turn", "declare", "after_declare", None):
        rr = [r for r in R if r["cls"] == cls]
        if rr:
            t = np.array([r["top"] for r in rr])
            print(f"     {str(cls):14s} n={len(rr):4d} top>0.999999 {pct((t>0.999999).mean())}  top>0.99 {pct((t>0.99).mean())}")
    et = [r for r in R if r["p_end_turn"] is not None and r["has_activate"]]
    pe = np.array([r["p_end_turn"] for r in et])
    played_end = np.array([r["played"] == "END_TURN" for r in et])
    print(f"   turn-level decisions with END_TURN and an ACTIVATE both legal: {len(et)}; END_TURN played at {pct(played_end.mean())}")
    print(f"     P(END_TURN) >= 0.999999: {pct((pe>=0.999999).mean())}; 0.99 to 0.999999: {pct(((pe>=0.99)&(pe<0.999999)).mean())}; "
          f"0.01 to 0.99: {pct(((pe>=0.01)&(pe<0.99)).mean())}; 1e-6 to 0.01: {pct(((pe>=1e-6)&(pe<0.01)).mean())}; below 1e-6: {pct((pe<1e-6).mean())}")
    if played_end.any():
        q = pe[played_end]
        print(f"     where END_TURN was played ({played_end.sum()}): P(END_TURN) >= 0.999999 at {pct((q>=0.999999).mean())}, >= 0.99 at {pct((q>=0.99).mean())}")
    eb = [r for r in R if r["p_end_act"] is not None and r["has_block"]]
    if eb:
        pa = np.array([r["p_end_act"] for r in eb]); pb = np.array([r["p_block"] for r in eb])
        print(f"   decisions with END_ACTIVATION and a BLOCK_TARGET both legal: {len(eb)}; "
              f"P(END_ACTIVATION) >= 0.999999: {pct((pa>=0.999999).mean())}; P(block) >= 0.999999: {pct((pb>=0.999999).mean())}; "
              f"both below 0.99: {pct(((pa<0.99)&(pb<0.99)).mean())}; P(block) below 1e-6: {pct((pb<1e-6).mean())}")
    c = collections.Counter((r["cls"], r["top_type"]) for r in R if r["top"] > 0.999999)
    print("   saturated decisions by (class, top type):", c.most_common(8))
    sys.stdout.flush()
