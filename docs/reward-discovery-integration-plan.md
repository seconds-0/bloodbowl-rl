# Reward-Discovery Integration Plan v3 (dual-reviewed, 2026-06-20)

Final synthesis. v1 (Claude) → v2 (+ Codex integration approach) → **v3 (+ Codex v2-review +
adversarial-Claude review)**. The two v2 reviews are in `.codex-reviews/plan-v2-codex-review.md` and
returned by the adversarial agent. Their load-bearing corrections are folded in and marked **[adv]** /
**[codex]**. Invariants kept: decision-time-EV pricing (D147); win-rate/Elo-vs-frozen-anchors as the
only ground truth; never-destroy-cloud-resources; back caps up to Mac on every cap (D160 lesson).

## The headline reorder the reviews forced (READ THIS FIRST)
**[adv HIGH-3] Validate the netblock finding from scratch BEFORE building any automation on it.** Every
result so far is a single warm-start arm, one seed, no cold/BC-init control, one lineage — the exact
profile D04 calls a likely lineage artifact, and the ledger has a *documented walk-back* (D34→D34-AMENDED
retracted a from-scratch claim after a matched cold control). Automating a knob search whose objective is
read off lineage-contaminated probes is "finding biased rewards faster." So **item #1 is: reproduce the
net-EV turnover finding (2d-red↓ with scoring held) from a BC-init / cold start, ≥2 seeds, fixed budget,
with CIs.** If it doesn't reproduce cold, the whole turnover economy — and any sweep that optimizes
toward it — is suspect. Nothing in Tier 2 starts until this passes.

## Corrections folded into v3
- **[adv HIGH-2] "#58 is a blocker" is FALSE.** The match-mode sweep fix is already landed locally
  (D131: `2a78df5`/`ac155a3`/`473752e`) and a 16-trial sweep already ran (task #57). #58 is only the
  upstream-PR courtesy. **Protein can run today on the local tree** — remove all "land #58 first" gating.
- **[adv HIGH-1] The metric split is CODE, not read-only analysis.** "Low-value vs carrier-pressure
  2d-red" is NOT measurable today: `block_2dred_frac` is a pure dice-tier histogram; carrier telemetry
  isn't crossed with dice tier. Needs a new **`block_tier × target_value` 2-D telemetry crossing** (C +
  binding + rebuild + resync). This is the first CODE task and it gates the metric the optimizer uses.
- **[adv MEDIUM-4 — cardinal-rule extension] The composite outer objective must use PRE-DICE features
  only.** The validated stat vector (bloodbowl.h:361) includes realized post-dice outcomes
  (pickup/pass/GFI success, tds). Tuning knobs to match the agent's realized *success rates* to humans
  launders outcome-matching up into the outer objective. **Restrict the optimization TARGET to pre-dice
  / decision-mix features** (block-tier mix, declaration rates, positional/EV); keep realized-roll
  successes + outcome counts as DIAGNOSTICS only.
- **[adv MEDIUM-3] Elo-vs-anchors is a TRIPWIRE, not a maximization term.** If it's in the sweep score,
  Protein hammering it rots the finite frozen anchor pool. Optimize human-stat-distance; use
  Elo-vs-anchors only as an EvalStop constraint. Rotate/refresh the FINAL anchor set after any sweep.
- **[codex M1] Soften PBRS language.** Even `dist_ball`/`dist_endzone` emit `Φ(s')−Φ(s)` (not
  `γΦ(s')−Φ(s)`; γ=0.995) → "delta-potential scaffold / anneal-to-zero," not theorem-level "PBRS-safe."
  `possession`/k-terms/k_turnover are optimum-moving.
- **[codex M3] "frozen TRAIN opponent" = the frozen-bank / league-preseed selfplay pool**, NOT a
  scripted opponent (native rejects scripted-opponent-with-learning, pufferl.py:191; use selfplay.py:120).
- **[codex M2] Protein needs a real wrapper.** Current sweep observes training metrics or final
  match_score, not a composite kickoff-stat-residual + anchor-Elo. → write an external resumable sweep
  driver (or modify pufferl.py) that computes/logs the composite; decide whether early-stop uses a proxy
  or waits for final eval.
- **[codex L4] Force `reward_statmatch_scale=0`; never a sweep knob** (the in-env statmatch path still
  exists, default 0 — keep it off and out of the search).
- **[codex L5] Header struct comment fixed** (bloodbowl.h:309 said p_own_to; now ev.p_turnover per F2).
- **[adv MEDIUM-2 / codex M2] Native BC-CE gated behind a CHEAP precursor** (below).

## TIER 0 — now (free + protect)
0. **Back caps off the credit-fragile box** (DONE: `runs/caps/{netblock,violence}_cap.bin` on Mac).
   Standing: cap → back up immediately.
1. **Potential-shaping audit (corrected language).** `dist_ball`/`dist_endzone` = delta-potential
   scaffold (anneal-to-zero candidates, NOT theorem-PBRS given γ mismatch). `possession`, `k_kd/k_value/
   k_ball`, `k_turnover`, `rush_cost` = optimum-moving (the hacking risk surface). Table → DECISIONS.

## TIER 1 — first CODE + make the read trustworthy (days)
2. **[adv HIGH-1, first code task] Build the `block_tier × target_value` telemetry crossing** (low-value
   vs carrier/high-value 2d-red). Gates the next metric. C + binding + rebuild + resync.
3. **[adv HIGH-3, item #1 experiment] From-scratch/BC-init reproduction of the netblock turnover finding**
   (≥2 seeds, CIs) — BEFORE any automation. Uses the live box.
4. **Composite probe score** (orchestration, outside the env): **pre-dice features only** [adv M4],
   kickoff-start eval, as the GERS upper-level objective. Elo-vs-anchors = separate tripwire [adv M3].
5. **Sign-pair logging** (orchestration): per eval, per anchor-archetype, (Δcomposite, ΔElo-vs-anchors);
   flag the hacking quadrant.
6. **EvalStop** (orchestration, NOT the kernel): stop+keep-best on k=2 consecutive Elo-vs-anchor declines.
7. **Opponent separation [codex M3]:** frozen TRAIN bank (selfplay pool, stationarity) / EVAL anchor
   (sweep tripwire) / quarantined FINAL anchor set (promotion only; rotate after sweeps [adv M3]).
8. **Cross-ancestor warm-start probe** for finalists only.
9. **[adv MEDIUM-5] Re-express k_value (and k_kd where feasible) as a telescoping team-value/EV
   potential**; validate optimum-invariance via shaping-anneal-to-zero (§04 #7). The highest-leverage
   safety lever — schedule it, don't footnote it.

## TIER 2 — automate the outer loop (only after #3 passes; weeks)
10. **Resumable Protein/GERS knob sweep** around the (validated) netblock economy. `search_center` =
    current knobs; `score` = pre-dice composite; Elo = tripwire. **[codex M2/adv M1] Build the durable
    `observe()`-replay wrapper as a TESTED precondition** (kill -9 mid-trial, restart, confirm GP state
    identical) + per-trial JSON mirrored to Mac. **[adv L3] Cost-model first** (probe-len × arms × SPS →
    wall-clock → $) with the balance-guard ladder as a hard stop — a serial single-GPU sweep is days of
    wall-clock per iteration on the box that just credit-died. NO #58 dependency [adv H2].
11. **EA-SEED LLM-controller — after #10 has structured trial data.** Propose-and-EXPLAIN (logged to
    DECISIONS), gated through Tier-1 trust; NOT a silent optimizer. **[adv L1] Marginal value over
    Protein for 8 numeric knobs is thin — keep deferred; value is the explanation artifact.**

## TIER 3 — native trainer features + learn-the-reward (research; gated behind precursors)
12. **[adv M2] Native BC-CE — only after a cheap precursor proves it helps:** (a) offline-correlation
    "which reward feature tracks human residuals" report, AND (b) a TORCH-backend BC-CE A/B at reduced
    SPS showing it moves block-selection toward human AT ALL. Only then spend weeks of native CUDA work
    (load `.bbp` to GPU, masked 3-head CE in the optimizer step, **[codex L6] reproduce the iid /
    zero-recurrent-state limitation first** before sequence-BC, **[codex] upweight DECLARE/BLOCK_TARGET/
    CHOOSE_DIE** per D33). COMPLEMENT not replace EV shaping; anneal to a small floor.
13. True on-policy KL-to-BC in native (frozen teacher resident) — research; defer.
14. f-IRL knob calibration — research; the offline-correlation report (#12a) is the cheap precursor.
15. **[adv L2] MAP-Elites atlas — gated on a DEFINED stall:** Protein best-composite plateaus N trials
    while ≥2 stat residuals stay anti-correlated. `pyribs`. Defer until then.

## From-scratch gate (tiered) + KL-complement — unchanged from v2, both reviews concur
Warm-start probe per candidate; cross-ancestor per finalist; **from-scratch ≥2-seed+CIs per new default /
paper claim / economy change** (this is why #3 is item #1); from-scratch + tournament + behavior-stat at
lock-in. KL-to-BC COMPLEMENTS decision-time-EV shaping (policy prior vs credit assignment), never replaces.

## DO NOT
Online GAIL/AIRL in self-play; meta-gradient through the C engine; full online PBT; tune knobs to
maximize anchor-Elo (rots ground truth — Elo is a tripwire); human-stat-matching OR realized-outcome
stats in the env reward (D147) or in the sweep OPTIMIZATION target (keep outcomes as diagnostics);
`reward_statmatch_scale` ≠ 0 in any sweep; fake KL-to-BC in the env/Python layer for native runs.

## First concrete moves (box live)
Tier 0 #1 audit (free, now) → Tier 1 #2 build the tier×target-value telemetry (first code) + #3
from-scratch-reproduce netblock (first experiment, gates automation) → Tier 1 orchestration guardrails
(#4–8) → only then Tier 2 #10 Protein. netblock2 (k_turnover 0.30, running) finishes the cheap
higher-k read in parallel but is itself warm-started, so it does NOT substitute for #3.

## Verdicts
- **[codex] v2 incorporated the four major corrections correctly; tier ordering sound for native+1GPU.**
- **[adv] NOT sound as-written but close: start Tier-1 guardrails; MANDATORY before automation — (HIGH-3)
  from-scratch-reproduce netblock, (HIGH-1) build the tier×target-value telemetry, (HIGH-2) drop the
  fictional #58 blocker, (M3/M4) anchor-Elo as tripwire + composite = pre-dice features only.** All folded
  into v3 above.
