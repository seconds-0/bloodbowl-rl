#!/usr/bin/env python3
"""Search distillation: the fit check, the selection file, and the held-out numbers.

Every number here is computed from float32 logits as the harness computes them
at play (the blob's float32 policy rows on the stored float32 features), with
the joint distribution then formed in float64. Training is float64; the fit
value is printed once in that arithmetic too, beside the one that is read.

fit      Reading 1 and the validation numbers, for a dataset of any size.
         Milestone 1 uses only this. It writes REPORT.fit.txt and FIT.json and
         never a selection file, so it cannot open the test games.

select   The same checks and numbers on the complete dataset, then the
         selection file. It refuses, writing nothing, when the dataset does not
         hold every shard of the plan (by the shard names the dataset and the
         fine-tune recorded, and by the games the training and validation
         files themselves hold: exactly the plan's games of each split), or
         when its files are not the ones the fine-tune recorded. SELECTION.json is written only when all three
         arms' blobs pass acceptance and Reading 1 is FIT. The registered arm
         is the one the plan names; no rule chooses it. If any arm's blob
         fails acceptance the plan stops unread at the selection: no file, no
         held-out look, no gate.

heldout  Needs SELECTION.json and its sha256, a registered arm in it whose
         blob passed acceptance, the dataset's files to be the ones the
         selection recorded, and every arm's blob and sidecar to hash to the
         selection's values. Then it opens the locked test split, once (it
         leaves locked/OPENED.json and refuses another selection), and prints,
         for every arm: the probability it gives the label at test deviation
         roots (all, new labels only, confirmed labels only, by class, without
         kick-off turn roots), and the total variation and the share of
         decisions whose most probable action changed at the other test loss
         decisions (screened roots and out-of-scope decisions separately, and
         among those the original policy was sure of). Intervals are 95%
         percentile bootstraps over games. Reported numbers: no threshold is
         applied to them and no rule reads them.

Blob acceptance (one arm): the blob and its sidecar hash to what the fine-tune
recorded; the blob has the original's size and differs from it only in the
decoder's policy rows; the sidecar describes this arm and says it is not
eligible ancestry; the harness loads the blob; the logits this tool computes
are the harness's own decoder's on the same features; every weight is finite.
It is decided before anything is scored and apart from everything else: an arm
whose blob fails is not scored at all.

Reading 1, first match: Unread (the fit arm was not trained, its blob fails
acceptance, or its fit value is not a finite number); NOT FIT (the fit value
is below the plan's threshold); FIT.

J = q * M * g - price * U on the validation games is printed for every arm as
a diagnostic. It decides nothing.

  distill_eval.py fit     --harness EXPORT --plan PLAN.json --expect-sha256 H \\
      --checkpoint BLOB --dataset DIR --finetune DIR
  distill_eval.py select  (the same arguments)
  distill_eval.py heldout (the same arguments) --expect-selection-sha256 S
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

SCHEMA_SELECTION = "search-distill-selection-v2"
SCHEMA_FIT = "search-distill-fit-v1"
SCHEMA_HELDOUT = "search-distill-heldout-v2"
LOGIT_TOLERANCE = 0.01      # float32 play logits against float64 arithmetic, at logits near 1,000
NEW_LABEL = 0.01            # a "new" label: the original gave it less than this
READINGS = ("Unread", "NOT FIT", "FIT")


def setup(args):
    plan, plan_sha = C.load_plan(args.plan, args.expect_sha256)
    hx = C.Harness(args.harness)
    if hx.commit != plan["harness_commit"]:
        raise SystemExit(f"the harness export is at {hx.commit}, the plan pins "
                         f"{plan['harness_commit']}")
    if C.sha256_file(args.checkpoint) != plan["checkpoint"]["sha256"]:
        raise SystemExit(f"{args.checkpoint} is not the plan's checkpoint")
    dataset = C.dataset_meta(args.dataset)
    with open(os.path.join(args.finetune, "FINETUNE.json")) as f:
        finetune = json.load(f)
    if dataset["plan_sha256"] != plan_sha or finetune["plan_sha256"] != plan_sha:
        raise SystemExit("the dataset or the fine-tune was made under another plan")
    # The plan's hash is the same at every milestone, so it does not say which
    # dataset a fine-tune saw. The files' hashes do.
    if finetune.get("dataset") != dataset["files"]:
        raise SystemExit("the dataset's files are not the ones the fine-tune recorded "
                         "(FINETUNE.json 'dataset'); nothing was scored")
    policy, _ = hx.load_policy(args.checkpoint)
    w0 = policy.decoder.decoder.weight.detach().clone()
    return plan, plan_sha, hx, dataset, finetune, w0


def blob_problems(hx, args, arm, record, sample):
    """(problems, weight) for one arm's blob: an empty list is acceptance. The
    weight is handed back only with an empty list."""
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
    try:
        with open(sidecar) as f:
            side = json.load(f)
    except ValueError:
        return problems + [f"{arm}: the sidecar is not JSON"], None
    producer = side.get("producer") or {}
    if producer.get("arm") != arm or producer.get("lambda") != record["lambda"] or \
            (side.get("checkpoint") or {}).get("sha256") != record["blob_sha256"] or \
            (side.get("ancestry") or {}).get("eligible") is not False:
        problems.append(f"{arm}: the sidecar does not describe this arm")
    try:
        policy, _ = hx.load_policy(path)
    except (Exception, SystemExit) as exc:        # the harness's own refusal, whatever it is
        return problems + [f"{arm}: the harness does not load the blob: {exc}"], None
    w = policy.decoder.decoder.weight.detach().clone()
    h = sample["h"]
    with torch.no_grad():
        played = policy.decoder.decoder(h)               # float32, as the harness computes it
        mine = torch.nn.functional.linear(h.float(), w.float(), torch.zeros(w.shape[0]))
        wide = h.double() @ w.double().T
    if len(h) and not bool(torch.equal(played, mine)):
        problems.append(f"{arm}: this tool's float32 logits are not the harness decoder's")
    worst = float((played.double() - wide).abs().max()) if len(h) else 0.0
    if not math.isfinite(worst) or worst > LOGIT_TOLERANCE:
        problems.append(f"{arm}: float32 and float64 logits differ by {worst}")
    if not bool(torch.isfinite(w).all()):
        problems.append(f"{arm}: a weight is not finite")
    return problems, (w if not problems else None)


def coverage_problem(plan, data, split):
    """Why a dataset file does not hold exactly the plan's games of its split,
    or None. Decided from the engine seeds stored in the file itself, which the
    hash DATASET.json records binds and the fine-tune recorded. The shard names
    in DATASET.json are a label; they are not what this rests on."""
    seed0 = int(plan["label"]["seed0"])
    want = {seed0 + i for i in range(int(plan["games"]))
            if C.split_of(seed0 + i, seed0) == split}
    got = {int(s) for s in np.unique(np.asarray(data["engine_seed"]))}
    if got == want:
        return None
    return (f"the {split} file holds {len(got)} games, the plan's {split} games are "
            f"{len(want)} ({len(want - got)} missing, {len(got - want)} that are not the plan's)")


def score_arms(args, plan, hx, finetune, w0, train, validation):
    """Blob acceptance, then the fit and validation numbers of every accepted arm."""
    ft = plan["finetune"]
    arms = {}
    for arm in sorted(ft["arms"], key=lambda name: ft["arms"][name]):
        record = finetune["arms"].get(arm)
        if record is None:
            arms[arm] = {"lambda": ft["arms"][arm], "trained": False, "blob_accepted": False,
                         "blob_problems": [f"{arm}: not trained"]}
            continue
        problems, w = blob_problems(hx, args, arm, record, validation)
        entry = {"lambda": record["lambda"], "trained": True, "blob": record["blob"],
                 "blob_sha256": record["blob_sha256"],
                 "sidecar_sha256": record["sidecar_sha256"],
                 "blob_accepted": not problems, "blob_problems": problems}
        if w is not None:
            entry["train"] = F.stats(train, C.score(train, w0, w))
            scored = C.score(validation, w0, w)
            entry["validation"] = F.stats(validation, scored)
            entry["diagnostic_J"] = C.selection_score(validation, scored,
                                                      ft["diagnostic"]["price"])
            if arm == ft["fit"]["arm"]:
                entry["train_float64"] = F.stats(train, C.score(train, w0, w,
                                                                precision="float64"))
        arms[arm] = entry
    fit_arm = arms[ft["fit"]["arm"]]
    value = (fit_arm.get("train") or {}).get("label_probability")
    if not fit_arm["blob_accepted"] or value is None or not math.isfinite(value):
        reading = "Unread"
    else:
        reading = "FIT" if value >= ft["fit"]["threshold"] else "NOT FIT"
    fit = {"arm": ft["fit"]["arm"], "threshold": ft["fit"]["threshold"], "value": value,
           "value_float64": (fit_arm.get("train_float64") or {}).get("label_probability"),
           "reading": reading}
    return arms, fit


def report_lines(plan, plan_sha, dataset, arms, fit):
    lines = [f"plan {plan['name']} ({plan['purpose']}), sha256 {plan_sha}",
             f"dataset: shards {', '.join(sorted(dataset['shards']))} "
             f"({len(dataset['shards'])} of the plan's {len(plan['shards'])})",
             f"READING 1, fit: {fit['reading']}. Arm {fit['arm']}: weighted mean probability of "
             f"the label on training deviation roots {fit['value']} from float32 logits "
             f"({fit['value_float64']} in the float64 training arithmetic), threshold "
             f"{fit['threshold']}",
             "arm        lambda  blob      train: label p  p>=.5   change elsewhere (TV, top) | "
             "validation: M      U        g       q        J (diagnostic)"]
    for arm, e in arms.items():
        if "train" not in e:
            lines.append(f"{arm:<10} {e['lambda']:<6}  REJECTED  not scored: "
                         f"{'; '.join(e['blob_problems'])}")
            continue
        t, s = e["train"], e["diagnostic_J"]
        lines.append(
            f"{arm:<10} {e['lambda']:<6}  accepted        {t['label_probability']:.4f}   "
            f"{t['label_probability_ge_half']:.3f}   {t['tv_other']:.5f} "
            f"{t['top_changed_other']:.5f}            | {s['M']:.4f} {s['U']:.5f} "
            f"{s['g']:.4f} {s['q']:.5f} {s['J']:+.3e}")
    return lines


def cmd_fit(args):
    plan, plan_sha, hx, dataset, finetune, w0 = setup(args)
    out_path = os.path.join(args.finetune, "FIT.json")
    if os.path.exists(out_path):
        raise SystemExit(f"{out_path} exists; a fit reading is written once per fine-tune")
    train = C.open_split(args.dataset, "train", dataset)
    validation = C.open_split(args.dataset, "validation", dataset)
    arms, fit = score_arms(args, plan, hx, finetune, w0, train, validation)
    lines = report_lines(plan, plan_sha, dataset, arms, fit)
    lines.append("This is the fit reading only. No selection file is written and the test "
                 "split stays closed.")
    with open(out_path, "w") as f:
        json.dump({"schema": SCHEMA_FIT, "plan_sha256": plan_sha, "plan_name": plan["name"],
                   "dataset_files": dataset["files"], "dataset_shards": sorted(dataset["shards"]),
                   "fit": fit, "arms": arms, **hx.versions()}, f, indent=1)
    with open(os.path.join(args.finetune, "REPORT.fit.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if fit["reading"] == "FIT" else 3


def cmd_select(args):
    plan, plan_sha, hx, dataset, finetune, w0 = setup(args)
    ft = plan["finetune"]
    out_path = os.path.join(args.finetune, "SELECTION.json")
    if os.path.exists(out_path):
        raise SystemExit(f"{out_path} exists; a selection is made once")
    want = sorted(s["name"] for s in plan["shards"])
    if sorted(dataset["shards"]) != want:
        missing = sorted(set(want) - set(dataset["shards"]))
        raise SystemExit(f"the dataset does not hold every shard of the plan (missing "
                         f"{missing}); a selection is made on the whole plan only. Use `fit` "
                         "for a milestone's fit reading. Nothing was written")
    if sorted(finetune.get("dataset_shards") or []) != want:
        raise SystemExit("the fine-tune did not record every shard of the plan "
                         f"(FINETUNE.json 'dataset_shards': {finetune.get('dataset_shards')}); "
                         "nothing was written")
    # The shard names above are labels in two JSON files. What the selection
    # rests on is the games the hash-bound files themselves hold.
    train = C.open_split(args.dataset, "train", dataset)
    validation = C.open_split(args.dataset, "validation", dataset)
    for split, data in (("train", train), ("validation", validation)):
        problem = coverage_problem(plan, data, split)
        if problem:
            raise SystemExit(f"the dataset is not the whole plan: {problem}; a selection is "
                             "made on the whole plan only. Nothing was scored or written")
    registered = ft["registered_arm"]
    arms, fit = score_arms(args, plan, hx, finetune, w0, train, validation)
    rejected = [a for a in arms if not arms[a]["blob_accepted"]]
    if rejected:
        status = (f"the plan stops unread at the selection: blob acceptance failed for "
                  f"{rejected}; no selection file, no held-out look, no gate")
    elif fit["reading"] != "FIT":
        status = f"the plan stops: Reading 1 is {fit['reading']}; no selection file, no gate"
    else:
        status = "selected"
    lines = report_lines(plan, plan_sha, dataset, arms, fit)
    lines.append(f"REGISTERED ARM (named in the plan, chosen by no rule): {registered}")
    lines.append(f"STATUS: {status}")
    code = 3
    if status == "selected":
        selection = {
            "schema": SCHEMA_SELECTION, "plan_sha256": plan_sha, "plan_name": plan["name"],
            "purpose": plan["purpose"],
            "base_checkpoint_sha256": plan["checkpoint"]["sha256"],
            "dataset_files": dataset["files"], "dataset_shards": sorted(dataset["shards"]),
            "fit": fit, "registered_arm": registered,
            "rule": "the registered arm is the arm the plan names; this file exists only "
                    "because all three arms' blobs passed acceptance and Reading 1 is FIT; J "
                    "is a diagnostic",
            "arms": arms, "status": status, **hx.versions()}
        with open(out_path, "w") as f:
            json.dump(selection, f, indent=1)
        lines.append(f"SELECTION.json sha256 {C.sha256_file(out_path)}")
        code = 0
    with open(os.path.join(args.finetune, "REPORT.select.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return code


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
    closed = "; the test split stays closed"
    if not os.path.isfile(selection_path):
        raise SystemExit(f"{selection_path} does not exist{closed}")
    got = C.sha256_file(selection_path)
    if got != args.expect_selection_sha256.strip().lower():
        raise SystemExit(f"{selection_path} hashes to {got}, not to "
                         f"--expect-selection-sha256{closed}")
    with open(selection_path) as f:
        selection = json.load(f)
    if selection.get("plan_sha256") != plan_sha or \
            (selection.get("fit") or {}).get("reading") != "FIT":
        raise SystemExit(f"the selection is of another plan, or its fit reading is not FIT"
                         f"{closed}")
    arms = selection.get("arms") or {}
    registered = selection.get("registered_arm")
    if not registered or registered != plan["finetune"]["registered_arm"] or \
            registered not in arms or arms[registered].get("blob_accepted") is not True:
        raise SystemExit(f"the selection names no registered arm whose blob passed acceptance"
                         f"{closed}")
    if any(e.get("blob_accepted") is not True for e in arms.values()) or \
            sorted(arms) != sorted(plan["finetune"]["arms"]):
        raise SystemExit(f"the selection does not hold all the plan's arms with accepted blobs"
                         f"{closed}")
    if selection.get("dataset_files") != dataset["files"]:
        raise SystemExit(f"the dataset's files are not the ones the selection recorded{closed}")
    for arm, entry in arms.items():
        record = finetune["arms"].get(arm) or {}
        path = os.path.join(args.finetune, entry["blob"])
        if record.get("blob_sha256") != entry["blob_sha256"] or \
                record.get("sidecar_sha256") != entry["sidecar_sha256"] or \
                not os.path.isfile(path) or C.sha256_file(path) != entry["blob_sha256"] or \
                C.sha256_file(path + ".lineage.json") != entry["sidecar_sha256"]:
            raise SystemExit(f"{arm}: the blob or its sidecar is not the selection's{closed}")
    marker = os.path.join(args.dataset, C.LOCKED_DIR, "OPENED.json")
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
    test = C.open_split(args.dataset, "test", dataset, unlock_test=True)
    problem = coverage_problem(plan, test, "test")
    if problem:
        raise SystemExit(f"the dataset is not the whole plan: {problem}; no held-out number "
                         "was computed")
    boot = plan["bootstrap"]
    out = {"schema": SCHEMA_HELDOUT, "plan_sha256": plan_sha, "plan_name": plan["name"],
           "purpose": plan["purpose"], "selection_sha256": got,
           "registered_arm": registered, "bootstrap": boot, "arms": {},
           "note": "reported numbers; no threshold is applied and no rule reads them"}
    lines = [f"plan {plan['name']} ({plan['purpose']}), sha256 {plan_sha}",
             f"selection sha256 {got}; registered arm {registered}",
             "HELD-OUT NUMBERS on the test games. Reported only: no threshold, no rule. "
             f"95% intervals resample games ({boot['replicates']} replicates, generator seed "
             f"{boot['generator_seed']})."]
    for arm, entry in arms.items():
        problems, w = blob_problems(hx, args, arm, finetune["arms"][arm], test)
        if problems:
            raise SystemExit(f"{arm}: the blob fails acceptance now: {problems}")
        rows = heldout_rows(test, C.score(test, w0, w), boot["replicates"],
                            boot["generator_seed"])
        out["arms"][arm] = rows
        mark = " (the registered arm)" if arm == registered else ""
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
    for name, func in (("fit", cmd_fit), ("select", cmd_select), ("heldout", cmd_heldout)):
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
