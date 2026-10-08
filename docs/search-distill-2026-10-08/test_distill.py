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
  chain      A 20-game shard at reduced rollouts through the label tool, the
             acceptance, the dataset tool, the fine-tune and the selection.
             The later tests use its records.
  replay     Every game's stored trail regenerates its final digest, its score
             and both observation hashes.
  loss       THE LOSS IS THE SAMPLER'S. The training arithmetic's joint
             log-probabilities equal play_harness.search.joint_log_probabilities
             to 1e-9 on every stored decision, the largest support included, and
             the log-probability policy.select_joint returns for a sampled
             action; the joint KL by enumeration equals the p0-weighted
             conditional form.
  blob       Zero training steps write chain 55's blob back byte for byte; a
             trained arm differs from it only in the decoder's policy rows; a
             second run of the same training gives the same bytes; the harness
             refuses the blob without its sidecar; the trainer's lineage tool
             refuses the sidecar.
  locks      The training tool's reader refuses the test file; the dataset tool
             has no path for the reserve split and no reserve game is in any
             file; the evaluation tool refuses the test split without the
             selection's hash.
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
CHAIN_GAMES = 20
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
    check("rule", same == cases and A.STATUS_MATCH_OVER == E.STATUS_MATCH_OVER,
          f"{same} of {cases} random and knife-edge return tables give the harness's "
          f"(deviate, best, gain, se) exactly; match-over status {A.STATUS_MATCH_OVER} is the "
          "engine's")


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


def test_chain(ctx):
    scratch, harness, ckpt = ctx["scratch"], ctx["harness"], ctx["checkpoint"]
    plan = os.path.join(scratch, "PLAN.dev.json")
    t0 = time.time()
    code, text = run_tool([os.path.join(HERE, "make_plan.py"), "--harness", harness, "--kind",
                           "dev", "--games", str(CHAIN_GAMES), "--out", plan])
    sha = text.strip().splitlines()[-1].split()[-1] if code == 0 else None
    steps = [("label", ["distill_screen.py", "run", "--harness", harness, "--plan", plan,
                        "--expect-sha256", sha, "--shard", "dev", "--checkpoint", ckpt,
                        "--out-dir", os.path.join(scratch, "shard")]),
             ("accept", ["distill_accept.py", "--plan", plan, "--expect-sha256", sha,
                         "--shard-dir", "dev=" + os.path.join(scratch, "shard")]),
             ("dataset", ["distill_dataset.py", "--harness", harness, "--plan", plan,
                          "--expect-sha256", sha, "--checkpoint", ckpt, "--shard-dir",
                          "dev=" + os.path.join(scratch, "shard"), "--out-dir",
                          os.path.join(scratch, "dataset")]),
             ("finetune", ["distill_finetune.py", "--harness", harness, "--plan", plan,
                           "--expect-sha256", sha, "--checkpoint", ckpt, "--dataset",
                           os.path.join(scratch, "dataset"), "--out-dir",
                           os.path.join(scratch, "finetune")]),
             ("select", ["distill_eval.py", "select", "--harness", harness, "--plan", plan,
                         "--expect-sha256", sha, "--checkpoint", ckpt, "--dataset",
                         os.path.join(scratch, "dataset"), "--finetune",
                         os.path.join(scratch, "finetune")])]
    failed = None if sha else "make_plan"
    for name, argv in steps:
        if failed:
            break
        code, text = run_tool([os.path.join(HERE, argv[0])] + argv[1:])
        # the selection exits 3 when the fit check stops the plan; it still ran
        if code != 0 and not (name == "select" and code == 3):
            failed = f"{name} exit {code}: {text.strip().splitlines()[-1] if text.strip() else ''}"
    ctx.update(plan=plan, plan_sha=sha, chain_ok=failed is None)
    accepted = ""
    if not failed:
        _, accepted = run_tool([os.path.join(HERE, "distill_accept.py"), "--plan", plan,
                                "--expect-sha256", sha, "--shard-dir",
                                "dev=" + os.path.join(scratch, "shard")])
        accepted = accepted.strip().splitlines()[0]
    check("chain", failed is None,
          (f"{CHAIN_GAMES} games through label, acceptance, dataset, fine-tune and selection; "
           f"{accepted}; {time.time() - t0:.0f} s") if not failed else failed)


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
    games = A.read_jsonl(os.path.join(ctx["scratch"], "shard", "games.jsonl"))
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
    data = C.open_split(os.path.join(ctx["scratch"], "dataset", "train.pt"), "train")
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
    # select_joint's value is a sum of float32 log-softmaxes: it agrees to float32 rounding
    check("loss", worst < 1e-9 and worst_select < 2e-3 and kl_gap < 1e-9 and largest >= 100,
          f"{n} stored decisions (largest support {largest} tuples): joint log-probabilities "
          f"within {worst:.1e} of the harness's joint_log_probabilities; within "
          f"{worst_select:.1e} of select_joint's float32 log-probability on {(n + 3) // 4} "
          f"sampled actions; joint KL by enumeration and by the p0-weighted conditional form "
          f"within {kl_gap:.1e} (mean KL {float(by_tuples.mean()):.3f})")


# ---- blob ------------------------------------------------------------------------------
def test_blob(ctx):
    if not need_chain(ctx, "blob"):
        return
    lab = ctx["lab"]
    hx, torch = lab.hx, lab.torch
    data = C.open_split(os.path.join(ctx["scratch"], "dataset", "train.pt"), "train")
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
    if not need_chain(ctx, "locks"):
        return
    scratch = ctx["scratch"]
    test_file = os.path.join(scratch, "dataset", "locked", "test.pt")
    refusals = 0
    for expect in ("train", "validation"):
        try:
            C.open_split(test_file, expect)
        except SystemExit:
            refusals += 1
    try:
        D.split_path(os.path.join(scratch, "dataset"), "reserve")
        no_reserve_path = False
    except SystemExit:
        no_reserve_path = True
    plan = json.load(open(ctx["plan"]))
    seed0 = plan["label"]["seed0"]
    seen = {"train": set(), "validation": set(), "test": set()}
    for split in seen:
        data = C.open_split(D.split_path(os.path.join(scratch, "dataset"), split), split)
        seen[split] = {int(s) for s in data["engine_seed"]}
    wrong = sum(C.split_of(s, seed0) != split for split, seeds in seen.items() for s in seeds)
    reserve_files = [n for n in os.listdir(os.path.join(scratch, "dataset")) if "reserve" in n] \
        + [n for n in os.listdir(os.path.join(scratch, "dataset", "locked")) if "reserve" in n]
    code, text = run_tool([os.path.join(HERE, "distill_eval.py"), "heldout", "--harness",
                           ctx["harness"], "--plan", ctx["plan"], "--expect-sha256",
                           ctx["plan_sha"], "--checkpoint", ctx["checkpoint"], "--dataset",
                           os.path.join(scratch, "dataset"), "--finetune",
                           os.path.join(scratch, "finetune"), "--expect-selection-sha256",
                           "0" * 64])
    closed = code != 0 and "stays closed" in text and \
        not os.path.exists(os.path.join(scratch, "dataset", "locked", "OPENED.json"))
    check("locks", refusals == 2 and no_reserve_path and wrong == 0 and not reserve_files
          and closed,
          f"the training reader refuses the test file as train and as validation ({refusals} "
          f"of 2); the dataset tool has no path for the reserve split; {wrong} games sit in a "
          f"file of another split and no reserve file exists; the evaluation tool refuses the "
          f"test split without the selection's hash and leaves it unopened: {closed}")


TESTS = (("rule", test_rule), ("seat", test_seat), ("blitz", test_blitz), ("chain", test_chain),
         ("replay", test_replay), ("loss", test_loss), ("blob", test_blob),
         ("locks", test_locks))


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
