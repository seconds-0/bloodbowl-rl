# Agent 4 — Reward Hacking, Shaping Invariance, Validating Discovered Rewards

Our two worries map onto mature literature. (a) "Warm-start bias" = the RL-specific face of **causal/extremal Goodhart** + **warm-starting gap**. (b) "Degenerate optima that look fine on the shaped metric but lose games" = textbook **proxy-true divergence / reward overoptimization**. Clean theoretical lever: **potential-based shaping** makes our stated goal — "bias learning SPEED, not the optimum" — a *provable* property. Plus cheap detection checks to bolt onto the probe-arm workflow.

## 1. Goodhart taxonomies + modern detection
- **Goodhart's four variants** (Manheim & Garrabrant 2018, 1803.04585): *regressional* (optimizing selects noise), *extremal* (proxy↔goal correlation breaks in the tail you optimize into), *causal* (proxy correlates but intervening doesn't move the goal), *adversarial* (policy games the proxy). A stat-matching pseudo-reward that correlates with winning in human replays but is non-causal under our policy = **causal Goodhart**; a knob that helps moderately but degenerates when pushed = **extremal Goodhart**.
- **RM overoptimization scaling laws** (Gao, Schulman, Hilton, ICML 2023, 2210.10760): proxy-vs-gold gap grows *predictably* with optimization strength; gold rises then falls (inverted-U). 2024 direct-alignment extension shows same shape without explicit RM. **More optimization against a shaped knob is not monotonically good.**
- **Directional taxonomy** (When RLHF Fails, 2606.03238, 2026): classify each checkpoint transition by sign-pair (Δproxy, Δtrue): **reward hacking = Δproxy>0, Δtrue<0**; optimization collapse = both down; *proxy under-alignment* = proxy down, true up (drop that knob); evaluator gaming = two true-judges disagree in sign. **Aggregate gains mask matchup-level degradation.** A logistic model on pre-transition features *predicts* imminent hacking (ROC-AUC 0.82).
- **Detectors** (Lilian Weng 2024 survey; TRACE/anomaly-ensemble): trajectory-divergence monitoring (proxy vs true over training); action-distribution distance (KL/Wasserstein vs a trusted policy); feature-imprint analysis; ensemble rewards.
- **Guard for our loop:** every probe logs, per segment, the **(Δshaped, Δtrue) sign-pair** where true = win-rate/Elo vs a *frozen* anchor set (not the self-play opponent). Flag arms in the hacking/under-alignment quadrant. Compute **per anchor archetype** (bashy/agile/balanced), not pooled — D113 statmatch can win the aggregate while losing to one archetype.

## 2. Potential-based shaping — the provable "speed-not-optimum" lever
- **Ng, Harada & Russell 1999:** a shaping term **F(s,s') = γΦ(s') − Φ(s)** for *any* potential Φ leaves the set of optimal policies **exactly unchanged** (necessary-and-sufficient among Markovian state-based shapings). **Wiewiora 2003:** PBRS ≡ Q-value initialization — it only changes where learning starts / how fast it propagates = our goal exactly. Dynamic/value-bootstrapped potentials preserve invariance while adapting. **Multi-agent generalization** (Devlin & Kudenko 2011; 1401.3907): **Nash equilibria unchanged** under per-player PBRS — directly relevant (BB is two-player general-sum-ish). 2024-25: invariance extended to action- and sequence-dependent pseudo-rewards.
- **Sharp implication for our 8 knobs:** any knob expressible as γΦ(s')−Φ(s) **cannot** change which policy wins — only learning speed → **immune to reward hacking by construction.** Any knob NOT of that form (flat per-event bonus like "+r per block", rush-tax, non-telescoping carrier-exposure) **can** move the optimum → that's where hacking lives.
- **Guard:** audit each knob "potential difference or raw event bonus?" Telescoping ones (possession annuity, dist-endzone) → free guarantee. Raw-bonus ones (k_kd/k_value/k_ball, turnover charge) → real risk surface, scrutinize hardest; re-express as Φ-differences where feasible (e.g., Φ = expected territorial/ball-control value → telescoping difference rewards it, same learning bias, zero optimum shift). **Single highest-leverage design change available.**

## 3. Validating a shaped reward generalizes (worry (a))
- **Warm-starting gap** (2306.11271): a *provable* sub-optimality gap from warm-starting, driven by approximation error + coverage of the prior policy; warm-start "improves fast then stagnates." A behavior read off a warm-started probe can be **inherited from the lineage's state-visitation distribution**, not implied by the reward — chained 4-deep economies compound this (each arm only saw on-distribution states its parent reached). **Extremal Goodhart via restricted coverage.**
- **RL is seed/init sensitive** (2110.15572): same algorithm+reward → different policies across seeds/inits; a single warm-started read is statistically weak.
- **Guards + lock-in design (heart of worry (a)):**
  - **From-scratch confirmation gate.** A reward is not "discovered" until ≥2-3-seed **cold/BC-init** replicate reproduces the target within tolerance. Warm-start "good" + from-scratch "no move" ⇒ lineage artifact. Formalizes D46; make *from-scratch reproduction* the graduation criterion, not just warm-start stability.
  - **Lineage-swap / cross-warm-start test.** Warm-start the same candidate reward from **two different ancestors** (bashy cap + agile cap). Behavior depends on ancestor ⇒ reading the policy, not the reward. Agreement ⇒ reward-driven.
  - **Coverage check.** State-visitation overlap probe-vs-parent; never leaves parent's manifold ⇒ untrusted off-distribution read → inject exploration before trusting.
  - **Anneal shaping to zero at lock-in.** PBRS-form knobs are optimum-invariant → decay shaped weights → 0 over the final curriculum, confirm win-rate/Elo holds or rises. A drop ⇒ that knob was load-bearing on the *optimum* (hacking risk) → redesign as a potential or drop. Cleanest single lock-in validation.

## 4. Self-play-specific pathologies
- **Non-transitivity / cyclic dynamics** (self-play survey 2408.01072; PSRO/AlphaStar league): vanilla self-play cycles in non-transitive games. BB has non-transitive matchups (bash beats agile beats elusive-ball-control beats bash) → "win-rate vs current opponent" can look great while the population chases its tail. Mitigation = population/league with fictitious-play or **PSRO best-response to a fixed, diverse pool**. We already run a rotating league + anchored ladder — keep anchors **frozen and archetype-diverse**.
- **Collusion / degenerate equilibria** in symmetric self-play: drift to mutually-low-variance "agreement" (both stall, trade nothing) that maxes a shaped proxy without contesting the win. Shaped rewards paying for *activity* (blocks thrown, yards) rather than *outcome* (TD-differential, win) invite this.
- **Guard:** carry **win-rate/Elo vs frozen anchors as the ONLY ground truth**; never let a shaped proxy alone decide graduation. Self-play win≈50% but Elo-vs-anchors flat/dropping ⇒ cycling/collusion. Periodically score live vs old league snapshots (transitivity probe): healthy ladder beats its ancestors monotonically.

## 5. Goodhart-robust evaluation
- **Constrained / sweet-spot optimization** (Moskovitz et al., Constrained RLHF, 2310.04373): optimize each component only up to a **proxy-identified threshold**, past which it stops helping true reward. Each knob has a sweet spot beyond which it induces extremal Goodhart — the k-knob aggression sweep is literally searching for this. Formalize: "raise k only until Elo-vs-anchors stops improving."
- **World-feedback early stopping** (EvalStop, 2606.04145, 2026): training loss + shaped reward rise monotonically (uninformative); only the held-out **true metric** peaks then falls. Stop on **k consecutive true-metric drops** (k=2), keep best-prior. 98.3% precision, 1.5% FP. ~20-line monitor add.
- **Held-out integrity** (Gao 2023; 2002.08512): the true metric stays honest only if **never optimized against + periodically refreshed**. Tuning knobs to max anchor-Elo directly rots the anchors.
- **Guards:** EvalStop on every arm (stop+keep-best on 2 consecutive anchor-Elo drops even while shaped reward climbs — catches inverted-U); **two independent true-judges** (tournament win-rate vs anchors AND FUMBBL/FFB replay-differential plausibility) — opposite directions ⇒ distrust; **quarantine the anchor pool** (eval-only, never a training opponent, rotate/expand, hold a few out for final lock-in).

## Concrete checklist for the probe-arm workflow
1. **Knob audit:** classify each of 8 knobs PBRS-potential (safe) vs raw-bonus (hacking-prone); rewrite raw bonuses as Φ-differences where possible.
2. **Sign-pair logging:** per segment, per anchor-archetype, (Δshaped, ΔElo-vs-anchors); flag hacking/under-alignment quadrants.
3. **EvalStop:** stop+keep-best on 2 consecutive anchor-Elo drops regardless of shaped reward.
4. **Coverage meter:** state-visitation overlap probe-vs-parent; low ⇒ untrusted.
5. **Cross-ancestor warm-start:** same reward → same behavior from ≥2 lineages before believing it.
6. **From-scratch reproduction gate (graduation):** reward graduates only when a short BC/cold-init arm (≥2 seeds) moves toward the target — direct artifact-vs-discovery test for worry (a).
7. **Shaping-anneal lock-in:** decay shaped weights → 0 over final curriculum; require win-rate/Elo to hold/rise.
8. **Transitivity probe:** live vs old league snapshots; require monotone improvement (rule out cycling/collusion).
9. **Two-judge cross-check:** anchor-Elo vs replay-differential plausibility must not disagree in sign.

**Throughline:** make as many knobs potential-based as possible (free invariance), and make win-rate/Elo-vs-frozen-anchors the single quarantined ground truth every shaped read reconciles against — via from-scratch reproduction + shaping-anneal at lock-in.

## Sources
Goodhart variants 1803.04585; RM overopt scaling 2210.10760 (+ DAA NeurIPS 2024); When-RLHF-Fails 2606.03238; Weng reward-hacking survey 2024; Ng-Harada-Russell PBRS 1999; Wiewiora 1106.5267; MA-PBRS 1401.3907; warm-start gap 2306.11271; self-play survey 2408.01072; Constrained-RLHF 2310.04373; EvalStop 2606.04145; reliance-on-metrics 2002.08512; stochasticity-in-policy-opt 2110.15572.

**Standing-doctrine note (from the agent):** before acting on workflow changes (esp. redefining graduation to require from-scratch reproduction, which has real compute cost), Codex-review the from-scratch-gate + shaping-anneal proposal against the actual DECISIONS.md ledger first.
