"""The policy's options at one decision, exactly over the joint support.

The policy selects type, then arg given type, then square given both, each
from a log-softmax restricted to the exact conditional support (select_joint).
The probability of a legal tuple is the product of those three conditionals,
so the options listed here sum to one over the support and match the sampled
log-probability recorded in the trace.
"""
from __future__ import annotations

import numpy as np

from . import engine as E

HEAD_SPLITS = (E.ACT_SIZES[0], E.ACT_SIZES[0] + E.ACT_SIZES[1])


def legal_array(legal):
    """Compact (type, arg, x, y, proj_arg, proj_sq) rows for later labelling."""
    return np.array([(la.type, la.arg, la.x, la.y, la.proj_arg, la.proj_sq) for la in legal],
                    dtype=np.int16).reshape(-1, 6)


def _log_softmax(values):
    v = np.asarray(values, dtype=np.float64)
    m = v.max()
    return v - (m + np.log(np.exp(v - m).sum()))


def joint_logprobs(logits, rows):
    """log p(tuple) for every legal row (rows sharing a tuple share the value)."""
    logits = np.asarray(logits, dtype=np.float64).reshape(-1)
    heads = np.split(logits, HEAD_SPLITS)
    rows = np.asarray(rows).reshape(-1, 6)
    types, args, sqs = rows[:, 0].astype(int), rows[:, 4].astype(int), rows[:, 5].astype(int)
    out = np.zeros(len(rows), dtype=np.float64)
    utypes = np.unique(types)
    lt = dict(zip(utypes.tolist(), _log_softmax(heads[0][utypes]).tolist()))
    for t in utypes.tolist():
        in_t = types == t
        uargs = np.unique(args[in_t])
        la = dict(zip(uargs.tolist(), _log_softmax(heads[1][uargs]).tolist()))
        for a in uargs.tolist():
            in_ta = in_t & (args == a)
            usq = np.unique(sqs[in_ta])
            ls = dict(zip(usq.tolist(), _log_softmax(heads[2][usq]).tolist()))
            idx = np.nonzero(in_ta)[0]
            out[idx] = lt[t] + la[a] + np.array([ls[int(s)] for s in sqs[idx]])
    return out


def ranked(logits, rows):
    """Distinct tuples ranked by probability: list of (row_index, prob)."""
    lp = joint_logprobs(logits, rows)
    seen = {}
    for i, row in enumerate(np.asarray(rows).reshape(-1, 6)):
        key = (int(row[0]), int(row[4]), int(row[5]))
        if key not in seen:
            seen[key] = i
    order = sorted(seen.values(), key=lambda i: -lp[i])
    return [(i, float(np.exp(lp[i]))) for i in order]


def conditional_argmax_row(logits, rows):
    """Row index of the conditional argmax tuple (the argmax play mode)."""
    logits = np.asarray(logits, dtype=np.float64).reshape(-1)
    heads = np.split(logits, HEAD_SPLITS)
    rows = np.asarray(rows).reshape(-1, 6)
    cand = np.arange(len(rows))
    for h, col in ((0, 0), (1, 4), (2, 5)):
        vals = rows[cand, col].astype(int)
        # torch.argmax over the masked head keeps the lowest head index on ties,
        # so rank the distinct head values in index order, not legal-row order.
        uniq = np.unique(vals)
        best = int(uniq[int(np.argmax(heads[h][uniq]))])
        cand = cand[vals == best]
    return int(cand[0])
