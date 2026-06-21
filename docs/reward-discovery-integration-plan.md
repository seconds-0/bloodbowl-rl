# Reward-Discovery Integration Plan v2 (Claude + Codex synthesis, 2026-06-20)

Supersedes v1. Synthesizes Claude's draft (`analysis/reward-discovery/01..04` SOTA) with Codex's
independent integration review (`.codex-reviews/reward-integration-codex.md`). Codex corrected several
v1 errors — incorporated below, marked **[Codex]**. Invariants kept: decision-time-EV pricing (D147);
win-rate/Elo-vs-frozen-anchors as the only ground truth; never-destroy-cloud-resources.

## What changed v1 → v2 (the corrections that matter)
1. **[Codex] KL-to-BC is NOT a ~1-day job.** The native CUDA backend (the production path; PPO
   loss/optimizer are kernels in `vendor/PufferLib/src/pufferlib.cu` + `muon.cu`) **ignores** the torch
   `bc_coef`/BC-CE patch in `torch_pufferl.py`. So: native **BC-pair CE** (load `.bbp` human pairs to
   GPU, add masked 3-head CE to the optimizer step) = weeks of CUDA work; true on-policy KL-to-BC
   (frozen teacher resident in native trainer) = a research project. Moved from Tier 1 → Tier 3.
2. **[Codex] Human-stat-matching belongs in the OUTER objective, not an in-env reward.** Under D147 it
   can't be episode-end reward shaping (the old D113-A statmatch term). It's the GERS upper-level
   validation objective / sweep score — never a per-step or per-episode reward.
3. **[Codex] Protein/GERS sweep BEFORE EA-SEED LLM-controller.** 8 numeric runtime-configured knobs =
   tiny search space → cost-aware BO is the better first automation. EA-SEED only after structured trial
   data exists, and as a propose-and-EXPLAIN step, never a silent optimizer.
4. **[Codex] `reward_possession` is NOT PBRS-safe** (turn-end annuity stream, not optimum-invariant by
   theorem) — v1 wrongly lumped it with the safe potentials. Only `reward_dist_ball`/`reward_dist_endzone`
   are genuine delta-potentials; possession, the k-block-EV terms, and `reward_k_turnover` are
   optimum-moving (D147-clean, but NOT hack-immune by construction). Audit corrected.
5. **[Codex] Resumability + opponent separation** added (lessons from the credit-stop we just hit).

## Guiding reframe
We are doing **manual evolutionary bilevel reward shaping** (GERS): outer = us choosing knobs, inner =
warm-started probe, objective = human-stat distance + Elo. Adopt in priority order: **trust the read →
cheap automation (Protein) → richer feedback (LLM propose-explain) → learn-the-reward (research).**

## TIER 0 — Free / now (protect + cheap analysis)
0. **[Codex #1] Protect netblock artifacts** — back the caps off the single credit-fragile box (DONE
   this session: rsync to `runs/caps/`). Standing rule: cap → back up to Mac immediately.
1. **Potential-shaping knob audit (corrected).** `dist_ball`/`dist_endzone` = delta-potentials
   (scaffold-like, optimum-invariant-ish). `possession`, `k_kd/k_value/k_ball`, `k_turnover`, `rush_cost`
   = optimum-MOVING (the hacking risk surface). Deliverable: the table in DECISIONS + note which raw
   bonuses could be re-expressed as Φ-differences (e.g., k_value removal-EV → a team-value-on-pitch
   potential). Read-only.
2. **[Codex, loud] The metric fix: split low-value-target vs carrier-pressure 2d-red.** Aggregate
   2d-red is the WRONG target — the netblock arc proves the next metric must distinguish low-value slop
   (bad, suppress) from carrier-pressure desperation (often correct, keep). Without this the optimizer
   removes correct violence. Use the carrier telemetry (blocks_vs_carrier, carrier_knockdowns, #64) +
   a target-value split. **This gates everything downstream.**

## TIER 1 — Make the read trustworthy + the outer objective honest (days, mostly orchestration)
3. **[Codex] Composite probe score + kickoff-only stat scoring**, computed OUTSIDE the env (launcher/
   tooling), as the GERS upper-level objective = weighted human-stat distance (kickoff-start eval, not
   curriculum) + Elo-vs-anchors. Never an in-env reward.
4. **Sign-pair logging** (orchestration, not the kernel): per eval, per anchor-archetype,
   (Δcomposite-proxy, ΔElo-vs-FROZEN-anchors); flag the hacking quadrant.
5. **EvalStop** (orchestration, NOT the PPO kernel): stop-and-keep-best on k=2 consecutive
   Elo-vs-anchor declines even while shaped reward climbs.
6. **[Codex] Sharp opponent separation:** one frozen TRAIN opponent (stationarity), a separate EVAL
   anchor (sweep score), a quarantined FINAL anchor set (promotion only, never trained/tuned against).
7. **Cross-ancestor warm-start probe** for FINALISTS only (not every candidate): re-read from 2
   different lineages; ancestor-dependent behavior ⇒ reading the policy, not the reward.

## TIER 2 — Automate the outer loop (1–2 weeks)
8. **[Codex, FIRST automation] Constrained, RESUMABLE Protein/GERS reward-knob sweep** centered on the
   netblock economy. `search_center` = current knobs; `score` = composite (Tier-1 #3); `cost` =
   wallclock; built-in early-stop. **[Codex] Protein's GP state is in-memory → write every trial
   observation to durable JSON + be able to replay `observe()` after an interruption** (the credit-stop
   lesson). DEPENDS: land the match-mode sweep PR (#58). Protein DOES drive native arms (`pufferl.py`
   dispatches `_C` by default). Start 3–4 knobs around netblock.
9. **EA-SEED LLM-controller — AFTER #8 has structured trial data.** Emit {per-stat observed, human-ref,
   delta} + {per-knob contribution} (Eureka reflection) → LLM PROPOSES next knob vector + explains
   (logged to DECISIONS) → gate through Tier-1 trust before a full arm. **[Codex] propose-and-explain,
   not a silent optimizer.**

## TIER 3 — Native trainer features + learn-the-reward (weeks → research)
10. **[Codex] Native BC-pair CE regularizer** (the realistic "human prior" path; KL-to-BC's tractable
    form): load `.bbp` pairs to GPU buffers, sample a BC minibatch per PPO update, add masked 3-head CE
    to the optimizer step in the native trainer. **[Codex] upweight DECLARE/BLOCK_TARGET/CHOOSE_DIE
    pairs** (D33: state-averaged BC keeps aggregate acc but misses block behavior). Anneal to a small
    floor (a strong KL floor can freeze the policy at bc_v4's ceiling). CUDA work + NaN/SPS checks.
    **[Codex] COMPLEMENT, not replace, the EV shaping** (policy prior vs credit assignment — different
    problems; let frozen-anchor Elo decide if divergence from BC is good).
11. **True on-policy KL-to-BC in native** — research project (frozen teacher resident in native
    trainer). Defer.
12. **f-IRL / moment-matching knob calibration** — conceptually aligned (auto-calibrate knob weights to
    human moments, offline on the frozen corpus, stationary reward, φ over pre-dice features) but honest
    f-IRL through PPO/self-play is NOT a quick patch [Codex]. Research-grade; a simple
    offline-correlation "which reward feature tracks human residuals" report is the cheap precursor.
13. **MAP-Elites / CMA-MAE behavioral atlas** — only if scalar Protein search STALLS on the multi-target
    tension (it may; fixed scalarization provably can't reach non-convex Pareto). `pyribs`. Defer.

## From-scratch reproduction gate — TIERED (Codex's rule, resolves open Q-a)
NOT a standing per-candidate filter (would kill search velocity on one GPU + bias toward conservative
changes). Instead:
- Every sweep candidate: warm-start probe + kickoff eval.
- Every finalist: cross-ancestor warm-start probe.
- **Every new default / paper claim / reward-economy change: from-scratch or BC-init, ≥2 seeds, fixed
  budget, with CIs.**
- Every lock-in: from-scratch/BC-init + frozen-anchor tournament + behavior-stat read.
- Any suspicious "warm-start did exactly what the ancestor already did" result: trigger from-scratch early.

## KL-to-BC: COMPLEMENT, not replace (resolves open Q-b) [Codex]
Policy prior (KL/BC) and credit-assignment (EV shaping) solve different problems. The corpus is human,
not oracle (D46); BC is weakest exactly where sparse tactical credit matters (rare blocks, carrier
pressure, multi-turn drives); a strong KL floor can prevent improvement past bc_v4. Use: BC warm-start →
decaying native BC-CE/KL regularizer (decision-type-weighted) → EV shaping remains the credit mechanism
→ frozen-anchor Elo decides whether divergence from BC is good.

## DO NOT
Online adversarial IRL (GAIL/AIRL) in self-play (post-dice + double non-stationarity); meta-gradient
bilevel (no gradients through the C engine); full online PBT (we're fixed-knob short-read); tune knobs
to directly maximize anchor-Elo (rots ground truth); put human-stat-matching in the env reward (D147);
fake KL-to-BC in the env/Python layer for native runs (wrong layer, murders SPS) [Codex].

## First concrete moves (box live, netblock2 running)
Tier 0 #1 audit (free) + #2 the low-value/carrier 2d-red metric split (gates everything) → Tier 1
orchestration guardrails (#3-6) → land #58 → Tier 2 #8 resumable Protein sweep around netblock. The
netblock turnover finding is the first reward to run the new-default from-scratch gate before it becomes
the standing economy.

## Code-doc fix applied this session
Tightened the `reward_k_turnover` comment in `bloodbowl.ini` (it claimed "including the blitz Rush gate"
but the impl uses `ev.p_turnover` not `p_own_to` per D159 F2 — a future agent could have reverted it).
