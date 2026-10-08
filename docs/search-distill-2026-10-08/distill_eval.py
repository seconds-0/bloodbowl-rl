#!/usr/bin/env python3
"""Search distillation: the fit check, the choice of the registered arm, and the held-out numbers.

select   Reads the fine-tune's blobs, the training file and the validation file.
         For every arm it checks the blob (size, sidecar and blob hashes as the
         fine-tune recorded them, a difference from the original only in the
         decoder's policy rows, the harness loads it, its float32 logits agree
         with this tool's arithmetic), then recomputes from the blob:
           fit        weighted mean probability of the label on training
                      deviation roots, and the change at the other training
                      loss decisions;
           J          q * M * g - price * U on the validation games (PLAN.md
                      section 3). No rollouts.
         Reading 1: FIT when the fit arm's training label probability is at
         least the plan's threshold; NOT FIT stops the plan. The registered arm
         is the eligible arm with the highest J; ties go to the smaller lambda;
         an arm whose J is not finite or whose blob fails a check is not
         eligible; with no eligible arm there is none. Writes SELECTION.json,
         which binds the blob and sidecar hashes of every arm, and
         REPORT.select.txt.

heldout  Needs SELECTION.json and its sha256. Opens the locked test split, once
         (it leaves locked/OPENED.json and refuses another selection). For
         every arm: the probability it gives the label at test deviation roots
         (all, new labels only, confirmed labels only, by class, without
         kick-off turn roots), and the total variation and the share of
         decisions whose most probable action changed at the other test loss
         decisions (screened roots and out-of-scope decisions separately, and
         among those the original policy was sure of). Intervals are 95%
         percentile bootstraps over games. These are reported numbers. No
         threshold is applied to them and no rule reads them.

  distill_eval.py select  --harness EXPORT --plan PLAN.json --expect-sha256 H \\
      --checkpoint BLOB --dataset DIR --finetune DIR
  distill_eval.py heldout --harness EXPORT --plan PLAN.json --expect-sha256 H \\
      --checkpoint BLOB --dataset DIR --finetune DIR \\
      --expect-selection-sha256 S
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import distill_common as C  # noqa: E402
import distill_finetune as F  # noqa: E402

SCHEMA_SELECTION = "search-distill-selection-v1"
SCHEMA_HELDOUT = "search-distill-heldout-v1"
LOGIT_TOLERANCE = 0.01      # float32 harness logits against float64 arithmetic, at logits near 1,000
LOGIT_CHECK_DECISIONS = 1000
NEW_LABEL = 0.01            # a "new" label: the original gave it less than this


def setup(args):
    plan, plan_sha = C.load_plan(args.plan, args.expect_sha256)
    hx = C.Harness(args.harness)
    if hx.commit != plan["harness_commit"]:
        raise SystemExit(f"the harness export is at {hx.commit}, the plan pins "
                         f"{plan['harness_commit']}")
    if C.sha256_file(args.checkpoint) != plan["checkpoint"]["sha256"]:
        raise SystemExit(f"{args.checkpoint} is not the plan's checkpoint")
    with open(os.path.join(args.dataset, "DATASET.json")) as f:
        dataset = json.load(f)
    with open(os.path.join(args.finetune, "FINETUNE.json")) as f:
        finetune = json.load(f)
    if dataset["plan_sha256"] != plan_sha or finetune["plan_sha256"] != plan_sha:
        raise SystemExit("the dataset or the fine-tune was made under another plan")
    policy, _ = hx.load_policy(args.checkpoint)
    w0 = policy.decoder.decoder.weight.detach().clone()
    return plan, plan_sha, hx, dataset, finetune, w0


def open_dataset(args, dataset, split):
    path = os.path.join(args.dataset, dataset["files"][split]["path"])
    if C.sha256_file(path) != dataset["files"][split]["sha256"]:
        raise SystemExit(f"{path} is not the file DATASET.json recorded")
    return C.open_split(path, split)


def blob_problems(hx, args, arm, record, w0, sample):
    """Why an arm's blob is not acceptable (an empty list when it is), and its weight."""
    import torch
    problems = []
    path = os.path.join(args.finetune, record["blob"])
    sidecar = path + ".lineage.json"
    if not os.path.isfile(path) or not os.path.isfile(sidecar):
        return [f"{arm}: the blob or its sidecar is missing"], None
    if C.sha256_file(path) != record["blob_sha256"]:
        problems.append(f"{arm}: the blob is not the one the fine-tune recorded")
    if C.sha256_file(sidecar) != record["sidecar_sha256"]:
        problems.append(f"{arm}: the sidecar is not the one the fine-tune recorded")
    base = np.fromfile(args.checkpoint, dtype="<f4")
    if os.path.getsize(path) != base.size * 4:
        return problems + [f"{arm}: the blob is not the original's size"], None
    blob = np.fromfile(path, dtype="<f4")
    (first, last), _ = F.decoder_span(hx)
    differ = np.flatnonzero(blob != base)
    if differ.size and (differ.min() < first or differ.max() > last):
        problems.append(f"{arm}: the blob differs from the original outside the decoder's "
                        "policy rows")
    with open(sidecar) as f:
        side = json.load(f)
    producer = side.get("producer") or {}
    if producer.get("arm") != arm or producer.get("lambda") != record["lambda"] or \
            (side.get("checkpoint") or {}).get("sha256") != record["blob_sha256"] or \
            (side.get("ancestry") or {}).get("eligible") is not False:
        problems.append(f"{arm}: the sidecar does not describe this arm")
    try:
        policy, _ = hx.load_policy(path)
    except Exception as exc:                      # the harness's own refusal, whatever it is
        return problems + [f"{arm}: the harness does not load the blob: {exc}"], None
    w = policy.decoder.decoder.weight.detach().clone()
    h = sample["h"][:LOGIT_CHECK_DECISIONS]
    with torch.no_grad():
        played = policy.decoder.decoder(h)               # float32, as the harness computes it
        mine = h.double() @ w.double().T
    worst = float((played.double() - mine).abs().max()) if len(h) else 0.0
    if not math.isfinite(worst) or worst > LOGIT_TOLERANCE:
        problems.append(f"{arm}: harness logits differ from this tool's by {worst}")
    if not bool(torch.isfinite(w).all()):
        problems.append(f"{arm}: a weight is not finite")
    return problems, w


def cmd_select(args):
    plan, plan_sha, hx, dataset, finetune, w0 = setup(args)
    ft = plan["finetune"]
    out_path = os.path.join(args.finetune, "SELECTION.json")
    if os.path.exists(out_path):
        raise SystemExit(f"{out_path} exists; a selection is made once")
    train, validation = open_dataset(args, dataset, "train"), \
        open_dataset(args, dataset, "validation")
    missing = sorted(set(ft["arms"]) - set(finetune["arms"]))
    arms, lines = {}, []
    for arm in sorted(ft["arms"], key=lambda name: ft["arms"][name]):
        if arm in missing:
            arms[arm] = {"lambda": ft["arms"][arm], "eligible": False,
                         "problems": [f"{arm}: not trained"]}
            continue
        record = finetune["arms"][arm]
        problems, w = blob_problems(hx, args, arm, record, w0, validation)
        entry = {"lambda": record["lambda"], "blob": record["blob"],
                 "blob_sha256": record["blob_sha256"],
                 "sidecar_sha256": record["sidecar_sha256"], "problems": problems}
        if w is not None:
            entry["train"] = F.stats(train, C.score(train, w0, w))
            scored = C.score(validation, w0, w)
            entry["validation"] = F.stats(validation, scored)
            entry["selection"] = C.selection_score(validation, scored, ft["selection"]["price"])
            if not math.isfinite(entry["selection"]["J"]):
                problems.append(f"{arm}: J is not finite")
        entry["eligible"] = not problems
        arms[arm] = entry
    fit_arm = ft["fit"]["arm"]
    fit_value = (arms[fit_arm].get("train") or {}).get("label_probability")
    if fit_value is None or not math.isfinite(fit_value):
        fit = "UNREAD"
    else:
        fit = "FIT" if fit_value >= ft["fit"]["threshold"] else "NOT FIT"
    eligible = [a for a in arms if arms[a]["eligible"]]
    registered = None
    if fit == "FIT" and eligible:
        registered = max(eligible, key=lambda a: (arms[a]["selection"]["J"], -arms[a]["lambda"]))
    selection = {
        "schema": SCHEMA_SELECTION, "plan_sha256": plan_sha, "plan_name": plan["name"],
        "purpose": plan["purpose"], "base_checkpoint_sha256": plan["checkpoint"]["sha256"],
        "dataset_files": dataset["files"], "fit": {
            "arm": fit_arm, "threshold": ft["fit"]["threshold"], "value": fit_value,
            "reading": fit},
        "rule": ft["selection"]["rule"], "price": ft["selection"]["price"],
        "arms": arms, "eligible_arms": eligible, "registered_arm": registered,
        "status": ("the plan stops: " + fit) if fit != "FIT" else
                  ("no eligible arm: no registered arm, the gate is not played"
                   if registered is None else "selected"),
        **hx.versions()}
    with open(out_path, "w") as f:
        json.dump(selection, f, indent=1)
    sha = C.sha256_file(out_path)
    lines.append(f"plan {plan['name']} ({plan['purpose']}), sha256 {plan_sha}")
    lines.append(f"READING 1, fit: {fit}. Arm {fit_arm}: weighted mean probability of the "
                 f"label on training deviation roots {fit_value}, threshold "
                 f"{ft['fit']['threshold']}")
    lines.append("arm        lambda  train: label p  p>=.5   change elsewhere (TV, top) | "
                 "validation: M      U        g       q        J          eligible")
    for arm, e in arms.items():
        if "train" not in e:
            lines.append(f"{arm:<10} {e['lambda']:<6} not scored: {'; '.join(e['problems'])}")
            continue
        t, s = e["train"], e["selection"]
        lines.append(
            f"{arm:<10} {e['lambda']:<6}        {t['label_probability']:.4f}   "
            f"{t['label_probability_ge_half']:.3f}   {t['tv_other']:.5f} "
            f"{t['top_changed_other']:.5f}            | {s['M']:.4f} {s['U']:.5f} "
            f"{s['g']:.4f} {s['q']:.5f} {s['J']:+.3e}  "
            f"{'yes' if e['eligible'] else 'NO: ' + '; '.join(e['problems'])}")
    lines.append(f"REGISTERED ARM: {registered} ({selection['status']}); rule: the eligible "
                 "arm with the highest J, ties to the smaller lambda")
    lines.append(f"SELECTION.json sha256 {sha}")
    with open(os.path.join(args.finetune, "REPORT.select.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if fit == "FIT" and registered else 3


def cluster_interval(game, numerator, denominator, reps, seed):
    """(point, [lo, hi]) of sum(numerator) / sum(denominator), games resampled."""
    total = denominator.sum()
    if not total > 0:
        return float("nan"), [float("nan"), float("nan")]
    games, where = np.unique(game, return_inverse=True)
    num = np.zeros(games.size)
    den = np.zeros(games.size)
    np.add.at(num, where, numerator)
    np.add.at(den, where, denominator)
    rng = np.random.default_rng(int(seed))
    values = np.empty(int(reps))
    for r in range(int(reps)):
        draw = rng.integers(0, games.size, size=games.size)
        d = den[draw].sum()
        values[r] = num[draw].sum() / d if d > 0 else np.nan
    lo, hi = np.nanpercentile(values, [2.5, 97.5])
    return float(numerator.sum() / total), [float(lo), float(hi)]


def heldout_rows(data, scored, reps, seed):
    """The reported numbers of one arm on one dataset file."""
    w, game = data["weight"], data["game"]
    dev = data["label"] >= 0
    root, sure = data["kind"] == 0, scored["p0_top"] >= C.SURE
    rows = {}

    def mean(name, mask, values):
        point, interval = cluster_interval(game[mask], (w * values)[mask], w[mask], reps, seed)
        rows[name] = {"n": int(mask.sum()), "value": point, "interval": interval}

    p = np.nan_to_num(scored["p_label"], nan=0.0)
    new = dev & (scored["p0_label"] < NEW_LABEL)
    for name, mask in (
            ("label probability, all labels", dev),
            ("label probability, new labels (original below 0.01)", new),
            ("label probability, confirmed labels", dev & data["confirmed"]),
            ("label probability, class turn", dev & (data["cls"] == 0)),
            ("label probability, class after_declare", dev & (data["cls"] == 1)),
            ("label probability, without kick-off turn roots", dev & ~data["kickoff"])):
        mean(name, mask, p)
    mean("share of labels at 0.5 or more", dev, (p >= 0.5).astype(float))
    for where, mask in (("screened roots", ~dev & root), ("out-of-scope decisions", ~dev & ~root),
                        ("screened roots the original was sure of", ~dev & root & sure),
                        ("out-of-scope decisions the original was sure of",
                         ~dev & ~root & sure)):
        mean(f"total variation, {where}", mask, scored["tv"])
        mean(f"top action changed, {where}", mask, scored["changed"].astype(float))
    rows["counts"] = {"labels": int(dev.sum()), "false_labels": int((dev & data["false"]).sum()),
                      "confirmed_labels": int((dev & data["confirmed"]).sum()),
                      "unjudged_labels": int((dev & ~data["judged"]).sum()),
                      "kickoff_turn_labels": int((dev & data["kickoff"]).sum()),
                      "games": int(np.unique(game).size)}
    return rows


def cmd_heldout(args):
    plan, plan_sha, hx, dataset, finetune, w0 = setup(args)
    selection_path = os.path.join(args.finetune, "SELECTION.json")
    got = C.sha256_file(selection_path)
    if got != args.expect_selection_sha256.strip().lower():
        raise SystemExit(f"{selection_path} hashes to {got}, not to --expect-selection-sha256; "
                         "the test split stays closed")
    with open(selection_path) as f:
        selection = json.load(f)
    if selection["plan_sha256"] != plan_sha or selection["fit"]["reading"] != "FIT":
        raise SystemExit("the selection is of another plan, or its fit reading is not FIT; "
                         "the test split stays closed")
    marker = os.path.join(args.dataset, "locked", "OPENED.json")
    if os.path.exists(marker):
        with open(marker) as f:
            opened = json.load(f)
        if opened["selection_sha256"] != got:
            raise SystemExit(f"the test split was opened at {opened['at']} for another "
                             "selection; it is opened once")
        print(f"note: the test split was already opened at {opened['at']} for this selection")
    else:
        with open(marker, "w") as f:
            json.dump({"selection_sha256": got, "plan_sha256": plan_sha,
                       "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, f)
    test = open_dataset(args, dataset, "test")
    boot = plan["bootstrap"]
    out = {"schema": SCHEMA_HELDOUT, "plan_sha256": plan_sha, "plan_name": plan["name"],
           "purpose": plan["purpose"], "selection_sha256": got,
           "registered_arm": selection["registered_arm"], "bootstrap": boot, "arms": {},
           "note": "reported numbers; no threshold is applied and no rule reads them"}
    lines = [f"plan {plan['name']} ({plan['purpose']}), sha256 {plan_sha}",
             f"selection sha256 {got}; registered arm {selection['registered_arm']}",
             "HELD-OUT NUMBERS on the test games. Reported only: no threshold, no rule. "
             f"95% intervals resample games ({boot['replicates']} replicates, generator seed "
             f"{boot['generator_seed']})."]
    for arm, entry in selection["arms"].items():
        if not entry.get("eligible"):
            lines.append(f"{arm}: not eligible, not scored")
            continue
        problems, w = blob_problems(hx, args, arm, finetune["arms"][arm], w0, test)
        if problems or entry["blob_sha256"] != finetune["arms"][arm]["blob_sha256"]:
            raise SystemExit(f"{arm}: the blob is not the selection's: {problems}")
        rows = heldout_rows(test, C.score(test, w0, w), boot["replicates"],
                            boot["generator_seed"])
        out["arms"][arm] = rows
        mark = " (the registered arm)" if arm == selection["registered_arm"] else ""
        c = rows["counts"]
        lines.append(f"-- {arm}, lambda {entry['lambda']}{mark}: {c['games']} test games, "
                     f"{c['labels']} labels ({c['false_labels']} false, "
                     f"{c['confirmed_labels']} confirmed, {c['unjudged_labels']} unjudged, "
                     f"{c['kickoff_turn_labels']} in a kick-off turn)")
        for name, row in rows.items():
            if name == "counts":
                continue
            lo, hi = row["interval"]
            lines.append(f"   {name:<62} {row['value']:.5f} [{lo:.5f}, {hi:.5f}]  n {row['n']}")
    with open(os.path.join(args.finetune, "HELDOUT.json"), "w") as f:
        json.dump(out, f, indent=1)
    with open(os.path.join(args.finetune, "REPORT.heldout.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    for name, func in (("select", cmd_select), ("heldout", cmd_heldout)):
        sp = sub.add_parser(name)
        sp.add_argument("--harness", required=True)
        sp.add_argument("--plan", required=True)
        sp.add_argument("--expect-sha256", required=True)
        sp.add_argument("--checkpoint", required=True, help="the plan's original checkpoint blob")
        sp.add_argument("--dataset", required=True)
        sp.add_argument("--finetune", required=True, help="the fine-tune's output directory")
        if name == "heldout":
            sp.add_argument("--expect-selection-sha256", required=True)
        sp.set_defaults(func=func)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
