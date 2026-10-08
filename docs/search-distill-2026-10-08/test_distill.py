#!/usr/bin/env python3
"""Tests of the search-distillation tools that must pass before any registered run.

Run on one machine, one process, against an export of the pinned harness. It
makes its own small plan and records in a fresh scratch directory and changes
nothing else.

  test_distill.py --harness EXPORT --checkpoint BLOB --scratch DIR [--only NAME[,NAME]]
                  [--seat-games SEED:SIDE[,SEED:SIDE]]

The tests, by name:

  rule       distill_accept.deviation is play_harness.search.deviation, float for
             float, on random returns and at knife-edge values; the acceptance
             tool's match-over status is the engine's.
  seat       THE LABEL IS THE SEAT'S. A real play_harness.search.SearchSeat at
             the registered setting plays whole searched games. (a) At every
             decision the seat searches, before and after its deviations, the
             label tool's screen is run on a clone of the seat's own root
             (engine, both recurrent states, logits, masked support, a0, step,
             flags): its candidates, its 4 x 16 returns and its decision must
             equal the seat's exactly. That is teacher parity on identical
             roots, which holds after the game has left the plain one. (b) The
             label tool's own plain game on the same seeds is screened at every
             in-scope decision up to the seat's first deviation: same steps,
             same candidates, same returns, and its first deviation is the
             seat's, with the seat's action. That is integration: seeds, step
             index, states and flags of the tool's game loop are the seat's.
  blitz      THE LONGER HORIZON AT A KICK-OFF BLITZ TURN ROOT, directly. From a
             root flagged kickoff_turn, every rollout that stops on a turn end
             has passed the end of the free turn and a whole opponent team turn
             (the trail holds an opponent ACTIVATE) and ends with the searcher's
             completed-turn counter one higher; from an ordinary turn-level root
             of the same game no rollout that stops on a turn end holds one.
             The seat test also counts the kick-off turn decisions it compared.
  chain      Two 20-game shards at reduced rollouts through the label tool, the
             acceptance, the dataset tool, the fine-tune, the fit reading and
             the selection. The later tests use its records.
  replay     Every game's stored trail regenerates its final digest, its score
             and both observation hashes.
  loss       THE LOSS IS THE SAMPLER'S. The training arithmetic's joint
             log-probabilities equal play_harness.search.joint_log_probabilities
             to 1e-9 on every stored decision, the largest support included, and
             the log-probability policy.select_joint returns for a sampled
             action; the joint KL by enumeration equals the p0-weighted
             conditional form. And the step is the declared loss's (B5): over
             chunks of unequal weight the mean chunk loss equals the loss of
             the whole training set.
  blob       Zero training steps write chain 55's blob back byte for byte; a
             trained arm differs from it only in the decoder's policy rows; a
             second run of the same training gives the same bytes; the harness
             refuses the blob without its sidecar; the trainer's lineage tool
             refuses the sidecar.
  locks      The reader refuses the test split without the unlock, the reserve
             split always, and a DATASET.json that names the locked file as
             another split, each BEFORE anything is deserialised (the test
             counts the loads); the dataset tool has no path for the reserve
             split; the evaluation tool refuses the test split without the
             selection's hash. The test never deserialises the test file.
  accept     Records corrupted on a copy whose file hashes are kept consistent,
             so that only the acceptance's own reading can refuse them: a
             judgment cell that is infinity or NaN, a null cell without a cap
             stop, stop counts that are incomplete, negative or do not sum
             (B1); an other decision repeated, on a root's step, or with a
             changed weight or seed (B2); a candidate outside the recorded
             support or listed twice (B3); a shard with no library hash. And a
             legal action omitted from a root's support, which acceptance
             cannot see, is refused by the dataset tool's replay (B3).
  milestone  B4. A dataset of one shard of two: `fit` reads it and writes no
             selection; `select` refuses it; `heldout` finds no selection.
             `select` refuses a dataset that is not the one the fine-tune saw.
             `heldout` refuses selections with no registered arm, an arm whose
             blob did not pass, other dataset files, or another sidecar hash.
             The test split is never opened.
  fitblob    B6. The fit arm's blob changed outside the decoder's policy rows:
             Reading 1 is Unread and the arm is not scored. Another arm's
             sidecar changed by one byte: no selection file.
  gate       gate/score_from_plan.py on scratch files: a shard manifest with
             another producer, blob hash or compatibility block (B7); a
             scratch git repository that is dirty, has an untracked file or
             has moved (B8), by the function and by the script itself;
             malformed intervals; a rejected run's reading.json (Unread).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import distill_accept as A  # noqa: E402
import distill_common as C  # noqa: E402
import distill_dataset as D  # noqa: E402
import distill_finetune as F  # noqa: E402
import distill_screen as DS  # noqa: E402
import make_plan as MP  # noqa: E402

# Seeds outside every block in use (the rehearsal range). 29980730 has a kick-off
# Blitz turn at the opening kick-off (in-scope decisions at engine steps 26 to 39).
SEAT_GAMES = ((29980730, 0), (29980707, 1), (29980702, 0))
BLITZ_GAME = (29980730, 0, 26)          # engine seed, seat A's side, a kick-off turn root
CHAIN_GAMES = 40                        # two shards of 20: each holds every split group
TRAINER_LINEAGE_TOOL = os.path.join(os.path.dirname(os.path.dirname(HERE)), "tools")
RESULTS = []


def check(name, condition, detail):
    RESULTS.append((name, bool(condition), detail))
    print(f"{'PASS' if condition else 'FAIL'} {name}: {detail}", flush=True)
    return bool(condition)


def registered_settings():
    return {"seed0": 0, **MP.LABEL}


# ---- rule ------------------------------------------------------------------------------
def test_rule(ctx):
    S, E = ctx["lab"].S, ctx["lab"].E
    rng = np.random.default_rng(0)
    cases, same = 0, 0
    for k in (2, 3, 4):
        for n in (2, 4, 16, 128):
            for scale in (0.02, 0.2):
                for _ in range(40):
                    r = rng.normal(0.0, scale, size=(k, n))
                    r[1] += rng.choice([0.0, 0.05, 0.10, 0.1000001, 0.3])
                    cases += 1
                    same += A.deviation(r, 0.10) == S.deviation(r, 0.10)
    flat = np.zeros((3, 16))
    flat[1] += 0.2                                      # a constant difference: the floor decides
    cases += 1
    same += A.deviation(flat, 0.10) == S.deviation(flat, 0.10)
    packs = all(A.pack_tuple(t) == E.pack_tuple(*t)
                for t in ((0, 0, 0), (3, 7, 122), (29, 32, 390), (1, E.ARG_NONE, E.SQ_NONE)))
    check("rule", same == cases and A.STATUS_MATCH_OVER == E.STATUS_MATCH_OVER
          and tuple(A.STOPS) == tuple(S.STOPS) and packs,
          f"{same} of {cases} random and knife-edge return tables give the harness's "
          f"(deviate, best, gain, se) exactly; match-over status {A.STATUS_MATCH_OVER}, the "
          "kinds of stop and the tuple packing are the harness's")


# ---- seat ------------------------------------------------------------------------------
def seat_game(lab, engine_seed, a):
    """One whole searched game by the real SearchSeat, with the label tool's
    screen run on a clone of the seat's root at every decision it searches."""
    E, S, T, P = lab.E, lab.S, lab.T, lab.hx.P
    setting = S.search_setting()
    masks = (("m1",), ("m1",))
    offsets, search = [0, 0], [None, None]
    offsets[1 - a], search[a] = 1, setting
    match = T.Match(lab.policy, lab.policy, engine_seed, masks=masks, seed_offsets=offsets,
                    search=search)
    seat = match.seats[a]
    stash, calls, mismatches = {}, [], []
    original_decide, original_evaluate = seat.decide, seat.rollouts.evaluate

    def decide(logits, support, deciding):
        if deciding:
            declared = seat._after_declare
            kept, _ = P.restrict_support(support, seat.masks, declared)
            stash.update(logits=np.asarray(logits, dtype=np.float32).copy(),
                         support=np.asarray(kept).copy())
        return original_decide(logits, support, deciding)

    def evaluate(root, own_state, opp_state, candidates, rollouts, sampling_seed, step_index,
                 after_declare=(False, False), record=False, first_index=0):
        batch = original_evaluate(root, own_state, opp_state, candidates, rollouts,
                                  sampling_seed, step_index, after_declare=after_declare,
                                  record=record, first_index=first_index)
        tool_root = {"clone": root.clone_for_search(0, S.SEARCH_DICE_STREAM),
                     "own": own_state.clone(), "opp": opp_state.clone(),
                     "logits": stash["logits"], "support": stash["support"],
                     "a0": tuple(int(v) for v in candidates[0]), "step": int(step_index),
                     "flags": (bool(after_declare[0]), bool(after_declare[1]))}
        try:
            rec = lab.screen(tool_root, a, sampling_seed, f"seed {engine_seed} step {step_index}")
        finally:
            tool_root["clone"].close()
        call = {"step": int(step_index), "a0": tool_root["a0"],
                "candidates": [list(map(int, c)) for c in candidates],
                "returns": batch.returns.copy(), "tool": rec,
                "kickoff": C.in_kickoff_turn(E, root.match()),
                "capped": batch.count(S.STOP_CAP) > 0}
        if rec["tuples"] != call["candidates"]:
            mismatches.append(f"step {step_index}: candidates differ")
        if not call["capped"] and not np.array_equal(np.asarray(rec["returns"]), batch.returns):
            mismatches.append(f"step {step_index}: returns differ")
        if call["capped"] != rec["cap_rejected"]:
            mismatches.append(f"step {step_index}: cap rejection differs")
        calls.append(call)
        return batch

    seat.decide, seat.rollouts.evaluate = decide, evaluate
    played = {}
    try:
        while True:
            team = match.observe()
            before = len(calls)
            outs = [match.seats[s].step(*match.seat_inputs(s), s == team) for s in (0, 1)]
            if team == a and len(calls) > before:
                call = calls[-1]
                action = tuple(int(v) for v in outs[a]["tuple"])
                call["played"] = action
                want = tuple(call["tool"]["label"]) if call["tool"]["deviate"] else call["a0"]
                if action != want:
                    mismatches.append(f"step {call['step']}: the seat played {action}, the "
                                      f"tool's screen says {want}")
                played[call["step"]] = action
            if match.apply(team, outs):
                break
            match.check_step_budget()
        record = match.record()
    finally:
        match.close()
    stats = record["search_stats"][a]
    deviations = [c for c in calls if c["played"] != c["a0"]]
    if sum(stats["deviations"].values()) != len(deviations) or \
            sum(stats["searched"].values()) != len(calls):
        mismatches.append("the seat's own counts are not the calls seen")
    return calls, deviations, mismatches


def test_seat(ctx):
    lab = ctx["lab"]
    S = lab.S
    total = {"decisions": 0, "deviations": 0, "after_first": 0, "kickoff": 0, "prefix": 0}
    problems, t0 = [], time.time()
    for engine_seed, a in ctx["seat_games"]:
        t1 = time.time()
        calls, deviations, mismatches = seat_game(lab, engine_seed, a)
        problems += [f"seed {engine_seed}: {m}" for m in mismatches]
        first = deviations[0]["step"] if deviations else None
        total["decisions"] += len(calls)
        total["deviations"] += len(deviations)
        total["kickoff"] += sum(c["kickoff"] for c in calls)
        total["after_first"] += sum(1 for c in calls if first is not None and c["step"] > first)
        # (b) the tool's own plain game, up to the seat's first deviation
        until = (first + 1) if first is not None else None
        g = lab.play_game(engine_seed, a, select="all", until_step=until)
        roots = sorted((r for cls in C.SCOPE for r in g["kept"][cls]), key=lambda r: r["step"])
        seat_calls = [c for c in calls if first is None or c["step"] <= first]
        try:
            if [r["step"] for r in roots] != [c["step"] for c in seat_calls]:
                problems.append(f"seed {engine_seed}: the tool's in-scope steps up to the first "
                                "deviation are not the seat's searched steps")
            else:
                for root, call in zip(roots, seat_calls):
                    rec = lab.screen(root, a, g["seed"], f"seed {engine_seed} step {root['step']}")
                    total["prefix"] += 1
                    if root["a0"] != call["a0"] or rec["tuples"] != call["candidates"] or \
                            (not call["capped"] and not np.array_equal(
                                np.asarray(rec["returns"]), call["returns"])):
                        problems.append(f"seed {engine_seed} step {root['step']}: the tool's "
                                        "own game does not give the seat's screen")
                    if root["kickoff_turn"] != call["kickoff"]:
                        problems.append(f"seed {engine_seed} step {root['step']}: kick-off "
                                        "turn flag differs")
                    last = root["step"] == first
                    if rec["deviate"] != last or (last and tuple(rec["label"]) != call["played"]):
                        problems.append(f"seed {engine_seed} step {root['step']}: the tool's "
                                        "first deviation is not the seat's")
        finally:
            for root in roots:
                root["clone"].close()
        print(f"  seat game seed {engine_seed} side {a}: {len(calls)} searched decisions, "
              f"{len(deviations)} deviations, first at step {first}, "
              f"{time.time() - t1:.0f} s", flush=True)
    setting = S.search_setting()
    check("seat", not problems and total["deviations"] > 0 and total["after_first"] > 0,
          f"{len(ctx['seat_games'])} searched games at k {setting['k']}, n {setting['n']}, delta "
          f"{setting['delta']}: {total['decisions']} searched decisions screened by the tool on "
          f"a clone of the seat's root, {total['after_first']} of them after the game's first "
          f"deviation, {total['deviations']} deviations, {total['kickoff']} inside a kick-off "
          f"turn; {total['prefix']} decisions of the tool's own plain game equal to the seat's "
          f"up to the first deviation; {len(problems)} mismatches"
          + (": " + "; ".join(problems[:5]) if problems else "")
          + f"; {time.time() - t0:.0f} s")


# ---- blitz -----------------------------------------------------------------------------
def test_blitz(ctx):
    lab = ctx["lab"]
    E, S = lab.E, lab.S
    engine_seed, a, step = BLITZ_GAME
    g = lab.play_game(engine_seed, a, select="all")
    roots = [r for cls in C.SCOPE for r in g["kept"][cls]]
    try:
        blitz = next(r for r in roots if r["step"] == step)
        ordinary = next(r for r in roots if r["class"] == "turn" and not r["kickoff_turn"])
        out = {}
        for name, root in (("blitz", blitz), ("ordinary", ordinary)):
            cands, _, _, _ = lab.candidates(root)
            before = root["clone"].turns_completed()[a]
            batch = lab.rollouts[a].evaluate(root["clone"], root["own"], root["opp"], cands, 16,
                                             g["seed"], root["step"], after_declare=root["flags"],
                                             record=True)
            turn_stops = [b for b, s in enumerate(batch.stops) if s == S.STOP_TURN]
            with_opponent_turn = sum(
                any(team != a and tup[0] == E.A["ACTIVATE"] for team, tup, _ in batch.trails[b])
                for b in turn_stops)
            # the rollout's own clones still hold their end state
            after = [lab.rollouts[a]._pool[b].turns_completed()[a] for b in turn_stops]
            out[name] = {"flag": root["kickoff_turn"], "rollouts": len(batch.stops),
                         "turn_stops": len(turn_stops), "with_opponent_turn": with_opponent_turn,
                         "counter_plus_one": sum(v == before + 1 for v in after),
                         "mean_steps": float(batch.steps.mean()),
                         "stops": {s: batch.count(s) for s in S.STOPS}}
    finally:
        for r in roots:
            r["clone"].close()
    b, o = out["blitz"], out["ordinary"]
    ok = (b["flag"] and not o["flag"] and b["turn_stops"] > 0 and o["turn_stops"] > 0
          and b["with_opponent_turn"] == b["turn_stops"] and o["with_opponent_turn"] == 0
          and b["counter_plus_one"] == b["turn_stops"]
          and o["counter_plus_one"] == o["turn_stops"])
    check("blitz", ok,
          f"seed {engine_seed}: from the kick-off turn root at step {step}, "
          f"{b['with_opponent_turn']} of {b['turn_stops']} rollouts that stop on a turn end hold "
          f"a whole opponent team turn and all end with the completed-turn counter one higher "
          f"(mean {b['mean_steps']:.0f} engine steps, stops {b['stops']}); from the ordinary "
          f"turn-level root at step {ordinary['step']}, {o['with_opponent_turn']} of "
          f"{o['turn_stops']} do (mean {o['mean_steps']:.0f} engine steps)")


# ---- chain -----------------------------------------------------------------------------
def run_tool(argv, env=None):
    r = subprocess.run([sys.executable] + argv, capture_output=True, text=True,
                       env={**os.environ, "OMP_NUM_THREADS": "1", "PYTHONDONTWRITEBYTECODE": "1",
                            **(env or {})})
    return r.returncode, r.stdout + r.stderr


def tool(ctx, name, *extra, **paths):
    """Run one of the plan-bound tools with the chain's plan and checkpoint."""
    argv = [os.path.join(HERE, name)] + list(extra)
    if name != "distill_accept.py":
        argv += ["--harness", ctx["harness"], "--checkpoint", ctx["checkpoint"]]
    argv += ["--plan", ctx["plan"], "--expect-sha256", ctx["plan_sha"]]
    for key, value in paths.items():
        argv += ["--" + key.replace("_", "-"), value]
    return run_tool(argv)


def last_line(text):
    lines = text.strip().splitlines()
    return lines[-1] if lines else ""


def test_chain(ctx):
    """Two shards of 20 games at reduced rollouts through every tool, as the
    registered run would go: label, accept, dataset over both shards, the three
    fits, the fit reading, the selection."""
    scratch, harness, ckpt = ctx["scratch"], ctx["harness"], ctx["checkpoint"]
    plan = os.path.join(scratch, "PLAN.dev.json")
    t0 = time.time()
    code, text = run_tool([os.path.join(HERE, "make_plan.py"), "--harness", harness, "--kind",
                           "dev", "--games", str(CHAIN_GAMES), "--dev-shards", "2",
                           "--out", plan])
    sha = last_line(text).split()[-1] if code == 0 else None
    ctx.update(plan=plan, plan_sha=sha, chain_ok=False)
    s1, s2 = os.path.join(scratch, "shard1"), os.path.join(scratch, "shard2")
    dataset, finetune = os.path.join(scratch, "dataset"), os.path.join(scratch, "finetune")
    both = ["--shard-dir", "dev-s1=" + s1, "--shard-dir", "dev-s2=" + s2]
    failed = None if sha else "make_plan: " + last_line(text)
    steps = (("label 1", "distill_screen.py", ["run", "--shard", "dev-s1", "--checkpoint", ckpt,
                                               "--harness", harness, "--out-dir", s1]),
             ("label 2", "distill_screen.py", ["run", "--shard", "dev-s2", "--checkpoint", ckpt,
                                               "--harness", harness, "--out-dir", s2]),
             ("accept", "distill_accept.py", both),
             ("dataset", "distill_dataset.py", ["--harness", harness, "--checkpoint", ckpt]
              + both + ["--out-dir", dataset]),
             ("finetune", "distill_finetune.py", ["--harness", harness, "--checkpoint", ckpt,
                                                  "--dataset", dataset, "--out-dir", finetune]),
             ("fit", "distill_eval.py", ["fit", "--harness", harness, "--checkpoint", ckpt,
                                         "--dataset", dataset, "--finetune", finetune]),
             ("select", "distill_eval.py", ["select", "--harness", harness, "--checkpoint", ckpt,
                                            "--dataset", dataset, "--finetune", finetune]))
    accepted = ""
    for name, script, argv in steps:
        if failed:
            break
        code, text = run_tool([os.path.join(HERE, script)] + argv
                              + ["--plan", plan, "--expect-sha256", sha])
        # fit and select exit 3 when the fit check stops the plan; they still ran
        if code != 0 and not (name in ("fit", "select") and code == 3):
            failed = f"{name} exit {code}: {last_line(text)}"
        if name == "accept":
            accepted = " | ".join(text.strip().splitlines()[:2])
    ctx.update(shards={"dev-s1": s1, "dev-s2": s2}, dataset=dataset, finetune=finetune,
               chain_ok=failed is None)
    selected = os.path.isfile(os.path.join(finetune, "SELECTION.json"))
    fit = {}
    if not failed:
        with open(os.path.join(finetune, "FIT.json")) as f:
            fit = json.load(f)["fit"]
    check("chain", failed is None and os.path.isfile(os.path.join(finetune, "REPORT.fit.txt")),
          (f"{CHAIN_GAMES} games in two shards through label, acceptance, dataset, fine-tune, "
           f"fit and select; {accepted}; Reading 1 {fit.get('reading')} at "
           f"{fit.get('value')} (float64 {fit.get('value_float64')}); selection written: "
           f"{selected}; {time.time() - t0:.0f} s") if not failed else failed)


def need_chain(ctx, name):
    if not ctx.get("chain_ok"):
        check(name, False, "needs the chain test's records (run without --only, or with chain)")
        return False
    return True


# ---- replay ----------------------------------------------------------------------------
def test_replay(ctx):
    if not need_chain(ctx, "replay"):
        return
    hx = ctx["lab"].hx
    games = [g for d in ctx["shards"].values() for g in A.read_jsonl(os.path.join(d, "games.jsonl"))]
    same, t0 = 0, time.time()
    for g in games:
        end = C.drain(C.replay(hx, g))
        same += all(end[key] == g[key] for key in ("obs_sha256", "final_digest", "score"))
    check("replay", same == len(games),
          f"{same} of {len(games)} stored trails regenerate the final digest, the score and "
          f"both observation hashes; {time.time() - t0:.1f} s")


# ---- loss ------------------------------------------------------------------------------
def test_loss(ctx):
    if not need_chain(ctx, "loss"):
        return
    lab = ctx["lab"]
    S, P, E, torch = lab.S, lab.hx.P, lab.E, lab.torch
    data = C.open_split(ctx["dataset"], "train")
    w0 = lab.policy.decoder.decoder.weight.detach()
    n = len(data["a0"])
    supports = C.supports_of(data)
    joint = C.Joint(supports)
    with torch.no_grad():
        logits32 = lab.policy.decoder.decoder(data["h"])             # as the harness computes them
        mine = joint.logp(logits32.double())
    worst, worst_select, largest = 0.0, 0.0, 0
    generator = torch.Generator().manual_seed(0)
    for i in range(n):
        tuples, logps = S.joint_log_probabilities(logits32[i], supports[i], 1.0)
        a, b = int(joint.first[i]), int(joint.first[i + 1])
        order = np.argsort(np.asarray(tuples, dtype=np.int64))
        worst = max(worst, float(np.abs(mine.numpy()[a:b] - np.asarray(logps)[order]).max()))
        largest = max(largest, b - a)
        if i % 4 == 0:
            action, logprob, _ = P.select_joint(logits32[i], supports[i], "sample", generator)
            at = a + int(np.searchsorted(joint.packed[a:b], E.pack_tuple(*action)))
            worst_select = max(worst_select, abs(float(mine[at]) - logprob))
    rng = torch.Generator().manual_seed(1)
    w = w0.double() + 0.05 * torch.randn(w0.shape, generator=rng, dtype=torch.float64)
    z0, z = data["h"].double() @ w0.double().T, data["h"].double() @ w.T
    lp0, lp = joint.logp(z0), joint.logp(z)
    by_tuples = joint.per_decision_sum(torch.exp(lp0) * (lp0 - lp))
    by_chain = joint.conditional_kl(z0, z)
    kl_gap = float((by_tuples - by_chain).abs().max())
    # The step is the declared loss's gradient in expectation: the mean over the
    # chunks of a chunk's loss equals the loss of the whole training set as one
    # chunk, though the chunks' weights differ. (A loss is linear in its
    # numerator, so equal losses at any w are equal gradients.)
    total = float(data["weight"].sum())
    whole = F.build_chunk(data, np.arange(n), w0.double())
    full = float(F.chunk_loss(whole, w, 4.0, total))
    parts, _ = F.partition(n, 300, 0)
    chunks = [F.build_chunk(data, index, w0.double()) for index in parts]
    mean_new = float(np.mean([float(F.chunk_loss(c, w, 4.0, total / len(parts))) for c in chunks]))
    mean_old = float(np.mean([float(F.chunk_loss(c, w, 4.0, float(c["w"].sum()))) for c in chunks]))
    weights = [float(c["w"].sum()) for c in chunks]
    declared = abs(mean_new - full) <= 1e-12 * max(1.0, abs(full))
    # select_joint's value is a sum of float32 log-softmaxes: it agrees to float32 rounding
    check("loss", worst < 1e-9 and worst_select < 2e-3 and kl_gap < 1e-9 and largest >= 100
          and declared and max(weights) > min(weights),
          f"{n} stored decisions (largest support {largest} tuples): joint log-probabilities "
          f"within {worst:.1e} of the harness's joint_log_probabilities; within "
          f"{worst_select:.1e} of select_joint's float32 log-probability on {(n + 3) // 4} "
          f"sampled actions; joint KL by enumeration and by the p0-weighted conditional form "
          f"within {kl_gap:.1e}; over {len(parts)} chunks of unequal weight ({min(weights):.0f} "
          f"to {max(weights):.0f}) the mean chunk loss is the whole set's loss to "
          f"{abs(mean_new - full):.1e} (dividing each chunk by its own weight would be off by "
          f"{abs(mean_old - full):.1e})")


# ---- blob ------------------------------------------------------------------------------
def test_blob(ctx):
    if not need_chain(ctx, "blob"):
        return
    lab = ctx["lab"]
    hx, torch = lab.hx, lab.torch
    data = C.open_split(ctx["dataset"], "train")
    w0 = lab.policy.decoder.decoder.weight.detach().clone()
    side = {"ancestry": {"initialization": "offline-distill", "eligible": False,
                         "qualification_only": True},
            "producer": {"test": "blob identity"}}
    zero, _, _ = F.train(data, w0, 4.0, 0, 0.001, 8192, 0)
    path0, sha0, _, changed0 = F.write_blob(hx, ctx["checkpoint"], zero,
                                            os.path.join(ctx["scratch"], "blob-zero"), side)
    identical = open(path0, "rb").read() == open(ctx["checkpoint"], "rb").read()
    first, _, _ = F.train(data, w0, 4.0, 40, 0.001, 8192, 0)
    second, _, _ = F.train(data, w0, 4.0, 40, 0.001, 8192, 0)
    path1, sha1, _, changed1 = F.write_blob(hx, ctx["checkpoint"], first,
                                            os.path.join(ctx["scratch"], "blob-a"), side)
    _, sha2, _, _ = F.write_blob(hx, ctx["checkpoint"], second,
                                 os.path.join(ctx["scratch"], "blob-b"), side)
    (lo, hi), (v_lo, v_hi) = F.decoder_span(hx)
    base = np.fromfile(ctx["checkpoint"], dtype="<f4")
    blob = np.fromfile(path1, dtype="<f4")
    differ = np.flatnonzero(blob != base)
    inside = differ.size > 0 and differ.min() >= lo and differ.max() <= hi
    value_same = np.array_equal(blob[v_lo:v_hi + 1], base[v_lo:v_hi + 1])
    bare = os.path.join(ctx["scratch"], "blob-bare")
    os.makedirs(bare, exist_ok=True)
    with open(path1, "rb") as src, open(os.path.join(bare, C.BLOB), "wb") as dst:
        dst.write(src.read())
    try:
        hx.load_policy(os.path.join(bare, C.BLOB))
        refused = False
    except Exception:
        refused = True
    trainer = "not checked"
    try:
        sys.path.insert(0, TRAINER_LINEAGE_TOOL)
        import checkpoint_lineage as CL
        raw = json.load(open(path1 + ".lineage.json"))
        strict = os.path.join(ctx["scratch"], "blob-a-trainer-format")
        os.makedirs(strict, exist_ok=True)
        with open(path1, "rb") as src, open(os.path.join(strict, C.BLOB), "wb") as dst:
            dst.write(src.read())
        with open(os.path.join(strict, C.BLOB) + ".lineage.json", "wb") as f:
            f.write(CL.canonical_bytes(raw))                 # the trainer tool's own byte format
        try:
            CL.validate_lineage(os.path.join(strict, C.BLOB), require_eligible=False)
            trainer = "ACCEPTED"
        except CL.LineageError as exc:
            trainer = f"refused ({exc})"
    except ImportError as exc:
        trainer = f"not checked ({exc})"
    check("blob", identical and changed0 == 0 and inside and value_same and sha1 == sha2
          and refused and trainer.startswith("refused") and bool(torch.equal(first, second)),
          f"zero steps: byte-identical to chain 55 ({sha0[:12]}), 0 floats changed; 40 steps: "
          f"{changed1} floats changed, all inside the decoder's policy rows {lo} to {hi}, the "
          f"value row unchanged; a second run gives the same sha256 ({sha1[:12]}); the harness "
          f"refuses the blob without a sidecar; the trainer's lineage tool: {trainer}")


# ---- locks -----------------------------------------------------------------------------
def test_locks(ctx):
    """The split locks, without ever deserialising the test file: the reader
    refuses by the path DATASET.json records, before it loads anything."""
    if not need_chain(ctx, "locks"):
        return
    torch = ctx["lab"].torch
    dataset = ctx["dataset"]
    loads, real_load = [], torch.load
    torch.load = lambda *a, **k: loads.append(a[0]) or real_load(*a, **k)
    try:
        refusals = []
        for split, kwargs in (("test", {}), ("reserve", {}), ("validation", {"meta": "doctored"}),
                              ("train", {"meta": "doctored"})):
            meta = None
            if kwargs.get("meta"):
                # a DATASET.json that names the locked file as the training or validation file
                meta = C.dataset_meta(dataset)
                meta["files"][split] = dict(meta["files"]["test"])
            try:
                C.open_split(dataset, split, meta)
                refusals.append("opened")
            except SystemExit as exc:
                refusals.append(str(exc))
        loaded_for_refusals = list(loads)
        train = C.open_split(dataset, "train")
        validation = C.open_split(dataset, "validation")
    finally:
        torch.load = real_load
    refused = [("stays closed" in refusals[0]), ("never written" in refusals[1]),
               ("nothing was read" in refusals[2]), ("nothing was read" in refusals[3])]
    try:
        D.split_path(dataset, "reserve")
        no_reserve_path = False
    except SystemExit:
        no_reserve_path = True
    plan = json.load(open(ctx["plan"]))
    seed0 = plan["label"]["seed0"]
    wrong = sum(C.split_of(int(s), seed0) != split
                for split, data in (("train", train), ("validation", validation))
                for s in data["engine_seed"])
    meta = C.dataset_meta(dataset)
    reserve_files = [n for n in os.listdir(dataset) + os.listdir(os.path.join(dataset, "locked"))
                     if "reserve" in n]
    no_reserve_labels = "deviation_roots" not in meta["counts"]["reserve"]
    code, text = tool(ctx, "distill_eval.py", "heldout", dataset=dataset,
                      finetune=ctx["finetune"], expect_selection_sha256="0" * 64)
    closed = code != 0 and "stays closed" in text and \
        not os.path.exists(os.path.join(dataset, "locked", "OPENED.json"))
    check("locks", all(refused) and not loaded_for_refusals and no_reserve_path and wrong == 0
          and not reserve_files and no_reserve_labels and closed,
          f"the reader refuses the test split without the unlock, the reserve split always, and "
          f"a DATASET.json that names the locked file as the training or the validation file "
          f"({sum(refused)} of 4), each before anything is deserialised ({len(loaded_for_refusals)} "
          f"loads); the dataset tool has no path for the reserve split, no reserve file exists, "
          f"DATASET.json counts no reserve label, and {wrong} games sit in a file of another "
          f"split; the evaluation tool refuses the test split without the selection's hash and "
          f"leaves it unopened: {closed}")


# ---- records corrupted on a copy -------------------------------------------------------
RECORD_FILES = ("games", "roots", "other")


def corrupt_shard(src, dst, mutate):
    """A copy of a shard directory with its records changed by `mutate(roots,
    games, other, complete)` and every hash that covers them rewritten, so that
    only the acceptance's own reading of the records can refuse it."""
    os.makedirs(dst)
    rows = {k: A.read_jsonl(os.path.join(src, f"{k}.jsonl")) for k in RECORD_FILES}
    with open(os.path.join(src, "COMPLETE.json")) as f:
        complete = json.load(f)
    mutate(rows["roots"], rows["games"], rows["other"], complete)
    for kind in RECORD_FILES:
        with open(os.path.join(dst, f"{kind}.jsonl"), "w") as f:
            f.writelines(json.dumps(r) + "\n" for r in rows[kind])
        complete[f"{kind}_sha256"] = C.sha256_file(os.path.join(dst, f"{kind}.jsonl"))
    with open(os.path.join(dst, "COMPLETE.json"), "w") as f:
        json.dump(complete, f, indent=1)
    with open(os.path.join(src, "plan.json"), "rb") as a, \
            open(os.path.join(dst, "plan.json"), "wb") as b:
        b.write(a.read())
    names = ("roots.jsonl", "games.jsonl", "other.jsonl", "COMPLETE.json", "plan.json")
    with open(os.path.join(dst, "SHA256SUMS"), "w") as f:
        for name in names:
            f.write(f"{C.sha256_file(os.path.join(dst, name))}  {name}\n")
    return dst


def rejudge(j, min_pairs):
    """Recompute a judgment's derived fields from its cells the way a tool that
    silently dropped a pair would: cap counts untouched."""
    a0, alt = (np.array([np.nan if v is None else v for v in row], dtype=float)
               for row in j["returns"])
    valid = np.isfinite(a0) & np.isfinite(alt)
    kept = int(valid.sum())
    d = alt[valid] - a0[valid]
    fresh = float(d.mean())
    se = float(d.std(ddof=1) / np.sqrt(kept))
    judged = kept >= min_pairs
    j.update(kept_pairs=kept, dropped_pairs=j["pairs"] - kept, fresh_gain=fresh, fresh_se=se,
             judged=bool(judged), false=bool(judged and fresh <= 0.0),
             confirmed=bool(judged and fresh > 2.0 * se))


def test_accept(ctx):
    """B1, B2, B3 and the library hash: each corruption is made on a copy whose
    file hashes are consistent, and shard acceptance must refuse it."""
    if not need_chain(ctx, "accept"):
        return
    with open(ctx["plan"]) as f:
        plan = json.load(f)
    src = ctx["shards"]["dev-s1"]
    min_pairs = plan["label"]["judge_min_pairs"]
    base = os.path.join(ctx["scratch"], "corrupt")
    os.makedirs(base)

    def first_label(roots):
        return next(r for r in roots if r["deviate"])

    def big_root(roots):
        # in a game the dataset tool replays (the reserve group's games are not replayed)
        seed0 = plan["label"]["seed0"]
        return next(r for r in roots if not r["cap_rejected"]
                    and r["support_size"] > len(r["tuples"]) + 1
                    and C.split_of(r["engine_seed"], seed0) != "reserve")

    def inf_cell(roots, games, other, complete):
        j = first_label(roots)["judgment"]
        j["returns"][1][0] = float("inf")
        rejudge(j, min_pairs)
        complete["dropped_judgment_pairs"] = sum((r.get("judgment") or {}).get("dropped_pairs", 0)
                                                 for r in roots)

    def nan_cell(roots, games, other, complete):
        j = first_label(roots)["judgment"]
        j["returns"][0][1] = float("nan")
        rejudge(j, min_pairs)
        complete["dropped_judgment_pairs"] = sum((r.get("judgment") or {}).get("dropped_pairs", 0)
                                                 for r in roots)

    def null_without_cap(roots, games, other, complete):
        j = first_label(roots)["judgment"]
        j["returns"][1][2] = None
        rejudge(j, min_pairs)
        complete["dropped_judgment_pairs"] = sum((r.get("judgment") or {}).get("dropped_pairs", 0)
                                                 for r in roots)

    def judgment_stops_short(roots, games, other, complete):
        first_label(roots)["judgment"]["stops"]["turn"] -= 1

    def judgment_stops_missing(roots, games, other, complete):
        del first_label(roots)["judgment"]["stops"]["cutoff"]

    def screen_stops_negative(roots, games, other, complete):
        r = roots[0]
        r["stops"]["turn"] += 1
        r["stops"]["cutoff"] -= 1

    def other_duplicated(roots, games, other, complete):
        game = other[0]["game"]
        mine = [o for o in other if o["game"] == game]
        mine[1].update(step=mine[0]["step"])              # the count stays, a step repeats

    def other_weight(roots, games, other, complete):
        other[0]["searchable"] += 7

    def other_seed(roots, games, other, complete):
        other[0]["engine_seed"] += 1

    def other_on_a_root(roots, games, other, complete):
        o = next(o for o in other if o["game"] == roots[0]["game"])
        o["step"] = roots[0]["step"]

    def candidate_outside_support(roots, games, other, complete):
        r = roots[0]
        r["tuples"][-1] = [29, 32, 390]                   # no support holds it

    def candidate_twice(roots, games, other, complete):
        r = next(r for r in roots if len(r["tuples"]) >= 3 and not r["deviate"])
        r["tuples"][2] = list(r["tuples"][1])

    def no_library(roots, games, other, complete):
        complete["library_sha256"] = None

    def omitted_support(roots, games, other, complete):
        # A legal action that is no candidate is left out of a root's recorded
        # support. Nothing in the records contradicts it.
        r = big_root(roots)
        packed = {A.pack_tuple(t) for t in r["tuples"]}
        drop = next(t for t in r["support"] if t not in packed)
        r["support"] = [t for t in r["support"] if t != drop]
        r["support_size"] -= 1

    cases = (
        ("B1 a judgment cell is infinity, its pair dropped and the fields recomputed, no cap stop",
         inf_cell, "neither a finite number nor null"),
        ("B1 a judgment cell is NaN", nan_cell, "neither a finite number nor null"),
        ("B1 a judgment cell is null with no cap stop counted", null_without_cap,
         "null judgment returns against"),
        ("B1 judgment stop counts do not sum to the rollouts", judgment_stops_short,
         "stop counts sum to"),
        ("B1 judgment stop counts lack a kind of stop", judgment_stops_missing,
         "do not name exactly"),
        ("B1 a screening stop count is negative", screen_stops_negative,
         "not a non-negative integer"),
        ("B2 an other decision repeated in place of another", other_duplicated,
         "already holds a record"),
        ("B2 an other decision on a root's step", other_on_a_root, "already holds a record"),
        ("B2 an other decision's searchable count changed", other_weight,
         "is not its game record's"),
        ("B2 an other decision's engine seed changed", other_seed, "is not its game record's"),
        ("B3 a candidate outside the recorded support", candidate_outside_support,
         "not distinct tuples of the recorded support"),
        ("B3 a candidate listed twice", candidate_twice,
         "not distinct tuples of the recorded support"),
        ("a shard that names no engine library", no_library, "names no sha256 of the engine"),
    )
    control = corrupt_shard(src, os.path.join(base, "control"), lambda *a: None)
    problems, _ = A.shard_problems(control, "dev-s1", plan, ctx["plan_sha"])
    results = [("the unchanged copy is accepted", not problems, str(problems[:1]))]
    for i, (name, mutate, phrase) in enumerate(cases):
        copy = corrupt_shard(src, os.path.join(base, f"case{i}"), mutate)
        problems, _ = A.shard_problems(copy, "dev-s1", plan, ctx["plan_sha"])
        results.append((name, any(phrase in p for p in problems), str(problems[:1])))
    # B3, the part acceptance cannot see: the dataset tool rebuilds the support on replay.
    copy = corrupt_shard(src, os.path.join(base, "omitted"), omitted_support)
    problems, _ = A.shard_problems(copy, "dev-s1", plan, ctx["plan_sha"])
    code, text = tool(ctx, "distill_dataset.py", shard_dir="dev-s1=" + copy,
                      out_dir=os.path.join(base, "omitted-dataset"))
    results.append(("B3 a legal action omitted from a root's support passes acceptance (the "
                    "records agree) and is refused by the dataset tool's replay",
                    not problems and code != 0 and "masked support is not the one the replayed "
                    "engine gives" in text, last_line(text)[:120]))
    for name, ok, detail in results:
        if not ok:
            print(f"    not refused: {name}: {detail}", flush=True)
    check("accept", all(ok for _, ok, _ in results),
          f"{sum(ok for _, ok, _ in results)} of {len(results)}: the unchanged copy is accepted; "
          f"refused on copies with consistent hashes: " + "; ".join(n for n, _, _ in results[1:]))


# ---- milestones and binding ------------------------------------------------------------
def linked_finetune(ctx, name, copy_arm=None, source=None):
    """A scratch fine-tune directory: FINETUNE.json copied, the arms' checkpoint
    directories linked, except `copy_arm`, whose two files are copied so that a
    test can change them."""
    source = source or ctx["finetune"]
    out = os.path.join(ctx["scratch"], name)
    os.makedirs(os.path.join(out, "checkpoints"))
    with open(os.path.join(source, "FINETUNE.json")) as f:
        finetune = json.load(f)
    with open(os.path.join(out, "FINETUNE.json"), "w") as f:
        json.dump(finetune, f, indent=1)
    for arm in finetune["arms"]:
        src = os.path.join(source, "checkpoints", arm)
        dst = os.path.join(out, "checkpoints", arm)
        if arm != copy_arm:
            os.symlink(src, dst)
            continue
        os.makedirs(dst)
        for fname in (C.BLOB, C.BLOB + ".lineage.json"):
            with open(os.path.join(src, fname), "rb") as a, \
                    open(os.path.join(dst, fname), "wb") as b:
                b.write(a.read())
    return out, finetune


def test_milestone(ctx):
    """B4: a milestone's dataset cannot produce a selection or open the test
    split; a selection is bound to its dataset's files, to a registered arm
    whose blob passed, and to every arm's sidecar."""
    if not need_chain(ctx, "milestone"):
        return
    scratch = ctx["scratch"]
    partial, ft_partial = os.path.join(scratch, "dataset-m1"), os.path.join(scratch, "finetune-m1")
    out = []
    code, text = tool(ctx, "distill_dataset.py", shard_dir="dev-s1=" + ctx["shards"]["dev-s1"],
                      out_dir=partial)
    out.append(("a dataset of one shard of two is built and says so",
                code == 0 and C.dataset_meta(partial)["complete"] is False
                and "holds 1 of the plan's 2 shards" in text, last_line(text)[-60:]))
    code, text = tool(ctx, "distill_finetune.py", dataset=partial, out_dir=ft_partial)
    out.append(("the three arms train on it", code == 0, last_line(text)[:80]))
    code, text = tool(ctx, "distill_eval.py", "fit", dataset=partial, finetune=ft_partial)
    out.append(("fit gives Reading 1 on it and writes no selection file",
                code in (0, 3) and "READING 1, fit:" in text
                and os.path.isfile(os.path.join(ft_partial, "REPORT.fit.txt"))
                and not os.path.exists(os.path.join(ft_partial, "SELECTION.json")),
                last_line(text)[:80]))
    code, text = tool(ctx, "distill_eval.py", "select", dataset=partial, finetune=ft_partial)
    out.append(("select refuses the one-shard dataset and writes nothing",
                code != 0 and "does not hold every shard of the plan" in text
                and not os.path.exists(os.path.join(ft_partial, "SELECTION.json"))
                and not os.path.exists(os.path.join(ft_partial, "REPORT.select.txt")),
                last_line(text)[:80]))
    code, text = tool(ctx, "distill_eval.py", "heldout", dataset=partial, finetune=ft_partial,
                      expect_selection_sha256="0" * 64)
    out.append(("heldout on it finds no selection and leaves the test split closed",
                code != 0 and "stays closed" in text
                and not os.path.exists(os.path.join(partial, "locked", "OPENED.json")),
                last_line(text)[:80]))
    # The same one-shard dataset and fine-tune with both JSON files relabelled to
    # name every shard of the plan; no tensor and no file hash changes. Only the
    # games the files hold can refuse it.
    with open(ctx["plan"]) as f:
        every = sorted(s["name"] for s in json.load(f)["shards"])
    meta_path = os.path.join(partial, "DATASET.json")
    meta = C.dataset_meta(partial)
    meta["shards"] = {name: dict(next(iter(meta["shards"].values()))) for name in every}
    meta["complete"] = True
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=1)
    ft_path = os.path.join(ft_partial, "FINETUNE.json")
    with open(ft_path) as f:
        relabelled = json.load(f)
    relabelled["dataset_shards"] = every
    with open(ft_path, "w") as f:
        json.dump(relabelled, f, indent=1)
    code, text = tool(ctx, "distill_eval.py", "select", dataset=partial, finetune=ft_partial)
    out.append(("select refuses the one-shard dataset relabelled as every shard, by the games "
                "its files hold, and writes nothing",
                code != 0 and "the dataset is not the whole plan" in text
                and not os.path.exists(os.path.join(ft_partial, "SELECTION.json"))
                and not os.path.exists(os.path.join(ft_partial, "REPORT.select.txt")),
                last_line(text)[:110]))
    relabelled["dataset_shards"] = every[:1]
    with open(ft_path, "w") as f:
        json.dump(relabelled, f, indent=1)
    code, text = tool(ctx, "distill_eval.py", "select", dataset=partial, finetune=ft_partial)
    out.append(("select refuses when only the dataset is relabelled and the fine-tune recorded "
                "one shard",
                code != 0 and "the fine-tune did not record every shard of the plan" in text
                and not os.path.exists(os.path.join(ft_partial, "SELECTION.json")),
                last_line(text)[:110]))
    code, text = tool(ctx, "distill_eval.py", "select", dataset=ctx["dataset"], finetune=ft_partial)
    out.append(("select refuses a dataset whose files are not the ones the fine-tune recorded",
                code != 0 and "not the ones the fine-tune recorded" in text
                and not os.path.exists(os.path.join(ft_partial, "SELECTION.json")),
                last_line(text)[:80]))
    # Selections that must not open the test split. Built on the whole dataset's fit.
    with open(os.path.join(ctx["finetune"], "FIT.json")) as f:
        fit = json.load(f)
    with open(ctx["plan"]) as f:
        plan = json.load(f)
    registered = plan["finetune"]["registered_arm"]
    good = {"schema": "search-distill-selection-v2", "plan_sha256": ctx["plan_sha"],
            "fit": dict(fit["fit"], reading="FIT"), "registered_arm": registered,
            "dataset_files": fit["dataset_files"],
            "arms": {a: dict(e, blob_accepted=True) for a, e in fit["arms"].items()}}

    def changed(**over):
        selection = json.loads(json.dumps(good))
        for key, value in over.items():
            if key == "arm":
                arm, field, new = value
                selection["arms"][arm][field] = new
            else:
                selection[key] = value
        return selection

    wrong_files = json.loads(json.dumps(fit["dataset_files"]))
    wrong_files["validation"]["sha256"] = "0" * 64
    for i, (name, selection, phrase) in enumerate((
            ("a selection with no registered arm", changed(registered_arm=None),
             "names no registered arm whose blob passed acceptance"),
            ("a selection whose registered arm's blob did not pass",
             changed(arm=(registered, "blob_accepted", False)),
             "names no registered arm whose blob passed acceptance"),
            ("a selection that registers another arm than the plan's",
             changed(registered_arm=next(a for a in good["arms"] if a != registered)),
             "names no registered arm whose blob passed acceptance"),
            ("a selection with another arm's blob rejected",
             changed(arm=(next(a for a in good["arms"] if a != registered), "blob_accepted",
                          False)), "does not hold all the plan's arms with accepted blobs"),
            ("a selection made on other dataset files", changed(dataset_files=wrong_files),
             "not the ones the selection recorded"),
            ("a selection that binds another sidecar hash",
             changed(arm=(registered, "sidecar_sha256", "0" * 64)),
             "the blob or its sidecar is not the selection's"),
            ("a selection whose fit reading is not FIT",
             changed(fit=dict(good["fit"], reading="NOT FIT")), "its fit reading is not FIT"))):
        directory, _ = linked_finetune(ctx, f"selection{i}")
        path = os.path.join(directory, "SELECTION.json")
        with open(path, "w") as f:
            json.dump(selection, f, indent=1)
        code, text = tool(ctx, "distill_eval.py", "heldout", dataset=ctx["dataset"],
                          finetune=directory, expect_selection_sha256=C.sha256_file(path))
        out.append((f"heldout refuses {name}",
                    code != 0 and phrase in text and "stays closed" in text
                    and not os.path.exists(os.path.join(ctx["dataset"], "locked", "OPENED.json")),
                    last_line(text)[:90]))
    for name, ok, detail in out:
        if not ok:
            print(f"    failed: {name}: {detail}", flush=True)
    check("milestone", all(ok for _, ok, _ in out),
          f"{sum(ok for _, ok, _ in out)} of {len(out)}: " + "; ".join(n for n, _, _ in out)
          + "; the test split was never opened")


# ---- blob acceptance and Reading 1 -----------------------------------------------------
def test_fitblob(ctx):
    """B6: an arm whose blob fails acceptance is not scored. The fit arm's makes
    Reading 1 Unread; any arm's stops the plan at the selection."""
    if not need_chain(ctx, "fitblob"):
        return
    with open(ctx["plan"]) as f:
        plan = json.load(f)
    fit_arm = plan["finetune"]["fit"]["arm"]
    other_arm = next(a for a in plan["finetune"]["arms"] if a != fit_arm)
    out = []
    # the fit arm's blob with one float changed outside the decoder's policy rows
    directory, _ = linked_finetune(ctx, "fitblob-value-row", copy_arm=fit_arm)
    blob_path = os.path.join(directory, "checkpoints", fit_arm, C.BLOB)
    (_, _), (v_lo, _) = F.decoder_span(ctx["lab"].hx)
    blob = np.fromfile(blob_path, dtype="<f4")
    blob[v_lo] += 1.0
    blob.tofile(blob_path)
    for command in ("fit", "select"):
        code, text = tool(ctx, "distill_eval.py", command, dataset=ctx["dataset"],
                          finetune=directory)
        out.append((f"{command}: the fit arm's blob changed in the value row gives Reading 1 "
                    "Unread, the arm is not scored, and no selection is written",
                    code == 3 and "READING 1, fit: Unread" in text
                    and f"{fit_arm}" in text and "REJECTED  not scored" in text
                    and not os.path.exists(os.path.join(directory, "SELECTION.json")),
                    last_line(text)[:100]))
    with open(os.path.join(directory, "FIT.json")) as f:
        entry = json.load(f)["arms"][fit_arm]
    out.append(("the rejected arm carries no fit number at all",
                entry["blob_accepted"] is False and "train" not in entry, str(sorted(entry))))
    # The same change with every recorded hash brought up to date (the blob's
    # hash in the sidecar and in FINETUNE.json, the sidecar's hash in
    # FINETUNE.json): now only the check that the blob differs from the original
    # inside the decoder's policy rows alone can refuse it.
    directory, finetune = linked_finetune(ctx, "fitblob-value-row-rehashed", copy_arm=fit_arm)
    blob_path = os.path.join(directory, "checkpoints", fit_arm, C.BLOB)
    blob = np.fromfile(blob_path, dtype="<f4")
    blob[v_lo] += 1.0
    blob.tofile(blob_path)
    with open(blob_path + ".lineage.json") as f:
        side = json.load(f)
    side["checkpoint"]["sha256"] = C.sha256_file(blob_path)
    with open(blob_path + ".lineage.json", "w") as f:
        json.dump(side, f, indent=1)
    finetune["arms"][fit_arm]["blob_sha256"] = C.sha256_file(blob_path)
    finetune["arms"][fit_arm]["sidecar_sha256"] = C.sha256_file(blob_path + ".lineage.json")
    with open(os.path.join(directory, "FINETUNE.json"), "w") as f:
        json.dump(finetune, f, indent=1)
    code, text = tool(ctx, "distill_eval.py", "fit", dataset=ctx["dataset"], finetune=directory)
    with open(os.path.join(directory, "FIT.json")) as f:
        said = json.load(f)["arms"][fit_arm]["blob_problems"]
    out.append(("fit: the same change with every hash rehashed is refused by the span check "
                "alone, and Reading 1 is Unread",
                code == 3 and "READING 1, fit: Unread" in text and len(said) == 1
                and "outside the decoder's policy rows" in said[0], str(said)[:120]))
    # another arm's sidecar changed by one byte: Reading 1 is still read, the plan stops
    directory, _ = linked_finetune(ctx, "fitblob-sidecar", copy_arm=other_arm)
    with open(os.path.join(directory, "checkpoints", other_arm, C.BLOB + ".lineage.json"), "a") as f:
        f.write(" ")
    code, text = tool(ctx, "distill_eval.py", "select", dataset=ctx["dataset"], finetune=directory)
    with open(os.path.join(ctx["finetune"], "FIT.json")) as f:
        reading = json.load(f)["fit"]["reading"]
    out.append(("select: another arm's sidecar changed by one byte leaves Reading 1 as it was "
                "and stops the plan unread at the selection, with no selection file",
                code == 3 and f"READING 1, fit: {reading}" in text
                and "the plan stops unread at the selection" in text
                and not os.path.exists(os.path.join(directory, "SELECTION.json")),
                last_line(text)[:100]))
    for name, ok, detail in out:
        if not ok:
            print(f"    failed: {name}: {detail}", flush=True)
    check("fitblob", all(ok for _, ok, _ in out),
          f"{sum(ok for _, ok, _ in out)} of {len(out)}: " + "; ".join(n for n, _, _ in out))


# ---- the gate's scorer -----------------------------------------------------------------
def load_scorer():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "distill_gate_scorer", os.path.join(HERE, "gate", "score_from_plan.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(root, *args):
    return subprocess.run(["git", "-C", root, "-c", "user.name=test", "-c",
                           "user.email=test@example.invalid", "-c", "commit.gpgsign=false", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def test_gate(ctx):
    """B7, B8 and the Unread outputs of gate/score_from_plan.py, on scratch
    files: a shard manifest with another producer, a harness worktree that is
    dirty or has moved, malformed intervals, and a rejected run's reading.json."""
    if not need_chain(ctx, "gate"):
        return
    G = load_scorer()
    scratch = os.path.join(ctx["scratch"], "gate")
    os.makedirs(scratch)
    out = []
    # B8: a scratch git repository standing in for the harness worktree
    repo = os.path.join(scratch, "worktree")
    os.makedirs(repo)
    git(repo, "init", "-q")
    with open(os.path.join(repo, "tournament_stats.py"), "w") as f:
        f.write("VALUE = 1\n")
    git(repo, "add", "tournament_stats.py")
    git(repo, "commit", "-q", "-m", "the registered commit")
    head = git(repo, "rev-parse", "HEAD")
    out.append(("B8 a clean worktree at the plan's commit is accepted",
                G.worktree_problem(repo, head) is None, ""))
    with open(os.path.join(repo, "tournament_stats.py"), "w") as f:
        f.write("VALUE = 2\n")
    out.append(("B8 a tracked file changed after play is refused",
                "not clean" in (G.worktree_problem(repo, head) or ""), ""))
    git(repo, "checkout", "-q", "--", "tournament_stats.py")
    with open(os.path.join(repo, "extra.py"), "w") as f:
        f.write("pass\n")
    out.append(("B8 an untracked file is refused",
                "not clean" in (G.worktree_problem(repo, head) or ""), ""))
    git(repo, "add", "extra.py")
    git(repo, "commit", "-q", "-m", "a later commit")
    out.append(("B8 a worktree that has moved to another commit is refused",
                "the plan's harness commit is" in (G.worktree_problem(repo, head) or ""), ""))
    out.append(("B8 a directory that is no git worktree is refused",
                "not a readable git worktree" in (G.worktree_problem(scratch + "/none", head) or ""),
                ""))
    # B7: a plan of two players on the chain's own arms, and manifests as a tournament writes them
    with open(os.path.join(ctx["finetune"], "FINETUNE.json")) as f:
        arms = json.load(f)["arms"]
    names = sorted(arms)[:2]
    paths = {a: os.path.join(ctx["finetune"], arms[a]["blob"]) for a in names}
    plan = {"players": {a: {"checkpoint": a, "masks": ["m1"]} for a in names},
            "checkpoint_paths": paths,
            "checkpoints_sha256": {a: arms[a]["blob_sha256"] for a in names},
            "sidecars_sha256": {a: arms[a]["sidecar_sha256"] for a in names}}
    sidecars = G.registered_sidecars(plan)

    def manifest(tag, change=None):
        m = {"checkpoints": {a: {"path": "/srv/bb/checkpoints/" + a,
                                 "sha256": arms[a]["blob_sha256"],
                                 "producer": json.loads(json.dumps(sidecars[a]["producer"])),
                                 "compatibility": dict(sidecars[a]["compatibility"])}
                             for a in names}}
        if change:
            change(m["checkpoints"])
        path = os.path.join(scratch, f"manifest.{tag}.json")
        with open(path, "w") as f:
            json.dump(m, f)
        return path

    def problems(tag, change=None):
        return G.manifest_problems(manifest(tag, change), plan, sidecars, "shard " + tag)

    out.append(("B7 a shard manifest with the registered blobs and producers is accepted",
                problems("good") == [], ""))
    found = problems("producer", lambda c: c[names[1]]["producer"].update({"lambda": 99.0}))
    out.append(("B7 a shard manifest whose second player has another producer is refused",
                len(found) == 1 and "producer or compatibility block is not the registered" in
                found[0] and names[1] in found[0], str(found)[:100]))
    found = problems("blob", lambda c: c[names[0]].update({"sha256": "0" * 64}))
    out.append(("B7 a shard manifest with another blob hash is refused",
                any("played a blob that is not the registered" in p for p in found), ""))
    found = problems("compat", lambda c: c[names[0]]["compatibility"].update(
        {"observation_version": 5}))
    out.append(("B7 a shard manifest with another compatibility block is refused",
                any("producer or compatibility" in p for p in found), ""))
    found = problems("stranger", lambda c: c.update({"intruder": dict(c[names[0]])}))
    out.append(("B7 a shard manifest that lists an unregistered player is refused",
                any("not a registered checkpoint player" in p for p in found), ""))
    found = problems("absent-entry", lambda c: c.pop(names[1]))
    out.append(("B7 a shard manifest with no entry for a registered player is refused",
                len(found) == 1 and "has no checkpoint entry for" in found[0]
                and names[1] in found[0], str(found)[:100]))
    out.append(("B7 a missing shard manifest is refused",
                any("no readable manifest" in p for p in G.manifest_problems(
                    os.path.join(scratch, "absent.json"), plan, sidecars, "shard absent")), ""))
    bad_plan = dict(plan, sidecars_sha256={a: "0" * 64 for a in names})
    try:
        G.registered_sidecars(bad_plan)
        refused = False
    except SystemExit:
        refused = True
    out.append(("B7 a local sidecar that is not the registered file is refused", refused, ""))
    # Unread: malformed and missing intervals, and the reading's order
    rule = {"positive_point": 15.0, "flat_bound": 15.0}

    def row(tag, content):
        path = os.path.join(scratch, f"contrast.{tag}.json")
        if content is not None:
            with open(path, "w") as f:
                f.write(content)
        return G.interval_row(path)

    good_row = row("good", json.dumps({"decisive_elo_diff": 20.0,
                                       "decisive_elo_diff_ci95": [5.0, 35.0]}))
    bad_rows = [row("three", json.dumps({"decisive_elo_diff": 20.0,
                                         "decisive_elo_diff_ci95": [5.0, 20.0, 35.0]})),
                row("one", json.dumps({"decisive_elo_diff": 20.0, "decisive_elo_diff_ci95": [5.0]})),
                row("text", json.dumps({"decisive_elo_diff": "20", "decisive_elo_diff_ci95": [5, 35]})),
                row("nokey", json.dumps({"decisive_elo_diff": 20.0})),
                row("notjson", "{"), row("missing", None)]
    out.append(("Unread: an interval of three ends, of one end, a text value, a missing key, a "
                "file that is not JSON and a missing file all give no row",
                good_row == (20.0, 5.0, 35.0) and all(r == (None, None, None) for r in bad_rows),
                str(bad_rows)))
    nan, inf = float("nan"), float("inf")
    table = (([good_row, good_row], "Positive"), ([good_row, bad_rows[0]], "Unread"),
             ([good_row], "Unread"), ([(20.0, nan, 35.0), good_row], "Unread"),
             ([(20.0, 5.0, inf), good_row], "Unread"), ([(20.0, 35.0, 5.0), good_row], "Unread"),
             ([(-20.0, -35.0, -5.0), good_row], "Negative"),
             ([(14.9, 5.0, 25.0), good_row], "Inconclusive"),
             ([(0.0, -15.0, 15.0), (1.0, -10.0, 12.0)], "Flat"),
             ([(0.0, -15.1, 15.0), (1.0, -10.0, 12.0)], "Inconclusive"),
             ([(15.0, 0.0, 30.0), good_row], "Inconclusive"),
             ([(15.0, 0.1, 30.0), good_row], "Positive"))
    got = [G.reading(c, rule) for c, _ in table]
    out.append(("the reading's order and edges (Unread, Negative, Positive, Flat, Inconclusive)",
                got == [want for _, want in table], str(got)))
    here, run = os.path.join(scratch, "here"), os.path.join(scratch, "run")
    os.makedirs(here)
    message = G.write_unread(run, here, {"reading": rule}, "the merged run is not accepted")
    with open(os.path.join(here, "reading.json")) as f:
        beside = json.load(f)
    os.makedirs(run)
    G.write_unread(run, here, {"reading": rule}, "the merge of the shards failed")
    with open(os.path.join(run, "reading.json")) as f:
        inside = json.load(f)
    out.append(("a rejected run leaves reading.json with Unread and the reason, beside the "
                "script before a run directory exists and in it afterwards",
                beside["reading"] == "Unread" and inside["reading"] == "Unread"
                and "not accepted" in beside["reason"] and "READING: Unread" in message, ""))
    # The whole script, on a scratch gate directory. First with a worktree changed after
    # "play": a refusal, exit not zero, no reading written, nothing of the harness run. Then
    # with the worktree restored and a run whose manifest has another producer: the run is
    # rejected and reading.json says Unread.
    gate_dir = os.path.join(scratch, "gatedir")
    os.makedirs(gate_dir)
    scripts = ("score_from_plan.py", "launch_from_plan.py", "play_local_from_plan.py",
               "accept_from_plan.py", "paired_contrasts.py", "gate_diagnostics.py")
    for name in scripts:
        with open(os.path.join(HERE, "gate", name), "rb") as a, \
                open(os.path.join(gate_dir, name), "wb") as b:
            b.write(a.read())
    sha = lambda name: C.sha256_file(os.path.join(gate_dir, name))  # noqa: E731
    now = git(repo, "rev-parse", "HEAD")
    with open(os.path.join(repo, "tournament_stats.py"), "w") as f:
        f.write("VALUE = 3\n")                                    # changed after "play"
    script_plan = dict(
        plan, gate="distill-mac-scratch-test", local_rehearsal=True, harness_commit=now,
        harness_worktree=repo, main_checkout=os.path.expanduser("~/Code/bb-play-harness"),
        out_root=os.path.join(scratch, "out"), run_dir=os.path.join(scratch, "out", "main"),
        shards={}, reading=rule,
        scoring={"script": "score_from_plan.py", "script_sha256": sha("score_from_plan.py")},
        launch={"script": "launch_from_plan.py", "script_sha256": sha("launch_from_plan.py"),
                "local_script": "play_local_from_plan.py",
                "local_script_sha256": sha("play_local_from_plan.py")},
        acceptance={"script": "accept_from_plan.py", "script_sha256": sha("accept_from_plan.py")},
        contrasts={"script": "paired_contrasts.py", "script_sha256": sha("paired_contrasts.py"),
                   "sets": []},
        diagnostics={"script": "gate_diagnostics.py", "script_sha256": sha("gate_diagnostics.py")})
    with open(os.path.join(gate_dir, "PLAN.json"), "w") as f:
        json.dump(script_plan, f, indent=1)
    code, text = run_tool([os.path.join(gate_dir, "score_from_plan.py"), "--expect-sha256",
                           C.sha256_file(os.path.join(gate_dir, "PLAN.json"))])
    run_dir = script_plan["run_dir"]
    wrote = [p for p in (os.path.join(gate_dir, "reading.json"),
                         os.path.join(run_dir, "reading.json")) if os.path.isfile(p)]
    out.append(("B8 the scorer itself, run on a scratch gate whose worktree changed after play: "
                "a refusal, exit not zero, no reading written, nothing of the harness was run",
                code != 0 and wrote == [] and "is not clean" in text and "REFUSED, no reading"
                in text and "MANIFESTS-CHECKED" not in text and "+ " not in text,
                last_line(text)[:110]))
    git(repo, "checkout", "-q", "--", "tournament_stats.py")
    os.makedirs(run_dir)
    code, text = run_tool([os.path.join(gate_dir, "score_from_plan.py"), "--expect-sha256",
                           C.sha256_file(os.path.join(gate_dir, "PLAN.json"))])
    wrote = [p for p in (os.path.join(gate_dir, "reading.json"),
                         os.path.join(run_dir, "reading.json")) if os.path.isfile(p)]
    out.append(("the scorer itself on a run whose manifest does not exist yet: a refusal (the "
                "run is not complete), exit not zero, no reading written",
                code != 0 and wrote == [] and "REFUSED, no reading: the run is not complete"
                in text and "READING:" not in text and "MANIFESTS-CHECKED" not in text,
                last_line(text)[:110]))
    with open(manifest("run", lambda c: c[names[1]]["producer"].update({"lambda": 99.0})), "rb") \
            as a, open(os.path.join(run_dir, "manifest.json"), "wb") as b:
        b.write(a.read())
    code, text = run_tool([os.path.join(gate_dir, "score_from_plan.py"), "--expect-sha256",
                           C.sha256_file(os.path.join(gate_dir, "PLAN.json"))])
    written = os.path.join(run_dir, "reading.json")
    left = json.load(open(written)) if os.path.isfile(written) else {}
    out.append(("B7 the scorer itself, with the worktree restored and a run whose manifest has "
                "another producer: exit not zero, reading.json in the run directory says Unread "
                "with the reason, nothing of the harness was run",
                code != 0 and left.get("reading") == "Unread" and "manifest" in
                left.get("reason", "") and "READING: Unread" in text
                and "MANIFESTS-CHECKED" not in text and "+ " not in text, last_line(text)[:110]))
    for name, ok, detail in out:
        if not ok:
            print(f"    failed: {name}: {detail}", flush=True)
    check("gate", all(ok for _, ok, _ in out),
          f"{sum(ok for _, ok, _ in out)} of {len(out)}: " + "; ".join(n for n, _, _ in out))


TESTS = (("rule", test_rule), ("seat", test_seat), ("blitz", test_blitz), ("chain", test_chain),
         ("replay", test_replay), ("loss", test_loss), ("blob", test_blob),
         ("locks", test_locks), ("accept", test_accept), ("milestone", test_milestone),
         ("fitblob", test_fitblob), ("gate", test_gate))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--harness", required=True)
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--scratch", required=True, help="a directory that does not exist yet")
    ap.add_argument("--only", default=None, help="comma-separated test names")
    ap.add_argument("--seat-games", default=None, metavar="SEED:SIDE[,SEED:SIDE]")
    args = ap.parse_args(argv)
    only = set(args.only.split(",")) if args.only else {name for name, _ in TESTS}
    unknown = only - {name for name, _ in TESTS}
    if unknown:
        raise SystemExit(f"unknown tests {sorted(unknown)}")
    if os.path.exists(args.scratch):
        raise SystemExit(f"{args.scratch} exists; choose a fresh --scratch")
    os.makedirs(args.scratch)
    seat_games = SEAT_GAMES
    if args.seat_games:
        seat_games = tuple(tuple(int(v) for v in item.split(":"))
                           for item in args.seat_games.split(","))
    ctx = {"harness": os.path.abspath(args.harness),
           "checkpoint": os.path.abspath(args.checkpoint),
           "scratch": os.path.abspath(args.scratch), "seat_games": seat_games,
           "lab": DS.Labeler(args.harness, args.checkpoint, registered_settings())}
    started = time.time()
    for name, func in TESTS:
        if name in only:
            t0 = time.time()
            func(ctx)
            print(f"  ({name}: {time.time() - t0:.0f} s)", flush=True)
    passed = sum(ok for _, ok, _ in RESULTS)
    print(f"{passed} of {len(RESULTS)} tests passed; {time.time() - started:.0f} s; harness "
          f"{ctx['lab'].hx.commit[:7]}, library {ctx['lab'].hx.library_sha256[:12]}")
    with open(os.path.join(args.scratch, "RESULTS.json"), "w") as f:
        json.dump([{"test": n, "passed": ok, "detail": d} for n, ok, d in RESULTS], f, indent=1)
    return 0 if passed == len(RESULTS) and RESULTS else 1


if __name__ == "__main__":
    raise SystemExit(main())
