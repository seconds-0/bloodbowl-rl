# Reward-Discovery State of the Art (2024–2026) — synthesis for bloodbowl-rl

Research dispatched 2026-06-20 (4 parallel agents, web-search heavy). We are doing **manual reward
discovery** via warm-started probe arms read against human aggregate stats. This maps onto a mature,
fast-moving literature. Below: what to adopt, in what order, and the guardrails our loop is missing.

## TL;DR — the recommended stack (cheapest → deepest)

1. **KL-to-BC anchor during RL** (AlphaStar / piKL, ICML 2022 `2112.07544`). Cheapest human-likeness
   signal, self-play-safe, ~1 day, does NOT touch the reward (it's a policy regularizer, no
   variance-laundering risk). We already train a BC warm-start (bc_v4) — add a decaying
   KL(π_RL‖π_BC) term. **First experiment if "play like humans" is the goal.**

2. **Automate the knob loop = EA-SEED** (`2506.23626`, June 2025) — the near-exact published analog
   of what we do by hand: an LLM proposes new reward *weights* each round from (a) a natural-language
   behavioral goal + (b) a training-stat summary. Our D113-A statmatch arm is this, manually. Wrap the
   probe launcher so an LLM reads a DECISIONS-style {observed, human-ref, delta} report + per-knob
   contribution telemetry (Eureka "reward reflection") and emits the next knob vector as JSON.

3. **Sampler = PufferLib Protein** (we already own it). Cost-aware BO (CARBS lineage): GP over
   (knobs→score) + GP over (knobs→log-cost), genetic search of the cost/score Pareto frontier — built
   for exactly our "cheap short probe vs expensive run" economy, with built-in early-stop
   (`RobustLogCostModel` ≈ ASHA). Seed `search_center` at current knobs; `log_normal` for the positive
   EV weights. **Blocked on the match-mode sweep PR (task #58) — land that first.**

4. **Framing = evolutionary bilevel reward shaping** (GERS, `2606.16236`, the closest paper to our
   problem). Outer **CMA-ES** over the 8 knobs, inner = warm-start probe, objective = human-stat
   distance. Derivative-free ONLY — never meta-gradient through the discrete C engine.

5. **When one policy can't hit all targets at once: MAP-Elites / CMA-MAE over reward space**
   (`pyribs`), with human stats as *behavior descriptors* → a behavioral ATLAS (which reward economy
   buys which profile), not just an argmax. Exploits our cheap-fast-probe advantage best. Also adopt
   **MORL framing**: fixed linear scalarization *provably* can't reach non-convex Pareto regions
   (`2410.02236`), so vector-score + dynamic reweighting (`2509.11452`) or constraints.

6. **Auto-calibrate the 8 knobs from the human corpus = f-IRL / moment-matching** (`2011.04709`,
   CoRL). Fit a linear-in-φ reward over our EXISTING human-stat features so a policy optimizing it
   reproduces human moments. Keeps decision-time-EV + interpretability; run OFFLINE on the frozen
   12.7k-game corpus, freeze, anneal in. This *replaces hand-tuning of weights, not the structure* —
   highest-value "learn the reward" version.

## The single highest-leverage idea: potential-based shaping (provable hack-immunity)

Ng–Harada–Russell 1999: a shaping term `F(s,s') = γΦ(s') − Φ(s)` leaves the **optimal policy exactly
unchanged** for ANY potential Φ — it only changes learning *speed* (Wiewiora 2003: equivalent to
Q-init). The multi-agent generalization preserves Nash equilibria (`1401.3907`). **This is literally
our stated goal — "bias learning speed, not the optimum."**

→ **Audit each of the 8 knobs: potential-difference (provably safe) vs raw event-bonus (hacking-prone).**
- Telescoping potentials (possession annuity, dist-endzone) ARE this form → free guarantee.
- Raw per-event bonuses (k_kd/k_value/k_ball, the new turnover charge, rush-tax) are NOT → they CAN
  move the optimum → that's where hacking/lock-in distortion lives → scrutinize hardest, and
  re-express as Φ-differences where possible.

## Guardrails to add to the probe-arm workflow (directly addresses warm-start bias + Goodhart)

1. **Sign-pair logging:** per segment, per anchor-archetype, record (Δshaped_reward, ΔElo-vs-FROZEN-anchors).
   Reward hacking = Δproxy>0, Δtrue<0. Aggregates hide it — compute per archetype, not pooled (`2606.03238`).
2. **EvalStop** (`2606.04145`): stop-and-keep-best on 2 consecutive Elo-vs-anchor drops even while the
   shaped reward keeps climbing — catches the reward-overoptimization inverted-U (`2210.10760`). ~20-line monitor add.
3. **From-scratch reproduction = the graduation gate** (addresses the warm-start-bias worry directly):
   a reward isn't "discovered" until a cold/BC-init replicate (≥2 seeds) moves toward the target.
   Formalizes D46 discovery-vs-artifact. Warm-start "good" + from-scratch "no move" ⇒ lineage artifact.
4. **Cross-ancestor warm-start test:** warm-start the same candidate reward from 2 DIFFERENT lineages
   (bashy cap + agile cap). Behavior depends on ancestor ⇒ reading the policy, not the reward. (We are
   now 4 economies deep on one chain — this is a real exposure.)
5. **Shaping-anneal at lock-in:** decay shaped weights → 0 over the final curriculum; require
   Elo-vs-anchors to HOLD or rise. A drop ⇒ that knob was load-bearing on the *optimum* (hacking risk) →
   redesign as a potential or drop.
6. **Coverage meter:** state-visitation overlap between probe and parent; low overlap ⇒ untrusted
   off-distribution read.
7. **Transitivity probe (self-play pathology):** score live policy vs OLD league snapshots; require
   monotone improvement. Self-play win≈50% but flat Elo-vs-anchors ⇒ cycling/collusion, not progress.
   Keep anchors FROZEN, archetype-diverse, evaluation-only, never a training opponent.

## What NOT to do
- **Online adversarial IRL (GAIL/AIRL) in the self-play loop:** stacks two non-stationarities AND
  rewards *realized* (post-dice) transitions = violates our decision-time-EV invariant. Multi-agent IRL
  is provably under-determined from equilibrium play (`2411.15046`).
- **Meta-gradient bilevel** (differentiating the true objective through PPO): no clean gradients through
  the discrete C engine. Use derivative-free outer optimization (CMA-ES / Protein).
- **Full online PBT:** our loop is fixed-knob short-read (BO/successive-halving regime), not
  online-schedule. Reach for it only if reward weights should ANNEAL across the curriculum.
- **RLVR/GRPO** (DeepSeek-R1 lineage): for binary-verifiable LLM reasoning, not our rich-telemetry game.

## The gap = the opportunity (paper-worthy)
LLM-driven closed-loop reward design is overwhelmingly single-agent robotics; the only game entries are
single-agent; NONE target competitive self-play leagues. The technique was born from FAST GPU sims
(Eureka/Isaac) — exactly our 860K-SPS regime, which game-RL rarely has. "LLM-driven reward design for
*competitive self-play* against *human behavioral-distribution targets* in a fast simulator" with a
12.7k-game corpus appears unpublished.

## Key sources
EA-SEED `2506.23626` · Eureka `2310.12931` (eureka-research/Eureka) · CARD `2410.14660`
(ShengjieSun419/CARD) · PROF `2511.13765` · HROSE `2504.07596` · RF-Agent `2602.23876`
(deng-ai-lab/RF-Agent) · PufferLib Protein (pufferai/pufferlib, kywch/puffer-phc) · GERS `2606.16236`
· PB2 `2002.02518` · C-MORL `2410.02236` · Dynamic Reward Weighting `2509.11452` · QDAC `2403.09930`
· f-IRL `2011.04709` · CSIL (joemwatson.github.io/csil) · IQ-Learn `2106.12142` · scalable-IRL
`2409.01369` · piKL `2112.07544` · Goodhart variants `1803.04585` · RM overopt scaling `2210.10760`
· When-RLHF-Fails `2606.03238` · Ng-Harada-Russell PBRS (1999) · Wiewiora `1106.5267` · MA-PBRS
`1401.3907` · warm-start gap `2306.11271` · EvalStop `2606.04145` · Constrained-RLHF `2310.04373`
· self-play survey `2408.01072`
