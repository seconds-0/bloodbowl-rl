# Agent 2 — Automated SEARCH / Optimization over Reward-Knob Values (2024–2026)

Our setup is near-ideal for almost every method here: a **deterministic fast sim, cheap warm-started few-B-step probe reads, a scalar score (human-stat distance), and huge parallel throughput** — exactly what successive-halving and population/BO methods exploit.

## 0. The headline: we already own the best-fit tool (PufferLib Protein)

**Protein** is PufferLib's native hyperparameter+reward tuner, purpose-built for our regime. GP over (params→score) + a second GP over (params→log_cost), combined with genetic search over the **cost/score Pareto frontier** — it natively reasons about "cheap short probe that scores well" vs "expensive run," precisely our warm-start-probe economy. A "heavily modified, simpler-but-more-robust CARBS" (Imbue's cost-aware BO); robust to lucky single runs.

Mechanics (from `pufferlib/sweep.py`):
- Each knob declared with `distribution` (`uniform`, `int_uniform`, `uniform_pow2`, `log_normal`, `logit_normal`), `min`, `max`, `scale` (`'auto'`=0.5), `search_center`. **Seed `search_center` at current hand-tuned values** so the GP starts at the known-good economy and explores locally. `log_normal` for positive multiplicative weights (k_kd, k_value, k_ball, possession annuity); `logit_normal` for bounded fractions (turnover-cost).
- **Early phase = Sobol quasirandom** then **GP phase** filters by max-cost budget and weights by a target cost ratio — tell it "spend most trials at the cheap probe length."
- Built-in **early stopping** via `RobustLogCostModel` (`Score ~ A + B·log(Cost)` quantile regression) — kills runs that cost too much for their score trajectory. Successive-halving-in-spirit, already wired in.

**How to run:** `puffer sweep bloodbowl --sweep.gpus N`. Define the 8 EV knobs in `[sweep]` with `search_center` = current values; probe = few-B-step warm-start budget; return **human-stat-distance as `score`** (negated), wall-clock as `cost`. Zero glue. **Caveat (tasks #55/#58): Protein is still Python (not CUDA C); the match-mode sweep fix PR (#58) is the enabling patch — land it first.**
- Sources: production-grade, ships in PufferLib (puffer.ai/docs.html, github.com/pufferai/pufferlib). CARBS lineage: Imbue 2023. Worked ref: github.com/kywch/puffer-phc.

## 1. PBT and successors (online, schedule-aware)
- **PB2 / PB2-Mix** (Parker-Holder, NeurIPS 2020; arXiv 2002.02518, 2106.15883): replaces PBT random mutation with a **time-varying GP bandit** — PBT quality with far smaller populations + regret bounds. PB2-Mix handles mixed categorical/continuous.
- **GPBT + Pairwise Learning** (IEEE TETCI Apr 2024, 2404.08233); **FIRE-PBT** (2021); **AdaQN** (2025); **Multiple-Frequencies PBT** (2506.03225); **Multi-Objective PBT** (2306.01436).
- **Honest assessment:** PBT mutates knobs mid-run + copies network weights between members — heavier to wire, and our loop is fundamentally **fixed-knob short-read** (BO/successive-halving regime), not online-schedule. **Use PB2's idea (GP-bandit over knobs) — which Protein already embodies — rather than standing up full PBT.** Reach for true PBT only if reward weights should ANNEAL across the curriculum.

## 2. Evolutionary / quality-diversity over reward space
- **CMA-ES** as outer reward-weight optimizer — single best fit for "fast sim + parallel probes + scalar score." Derivative-free, handles ~8-dim continuous knob vector trivially, self-adapts covariance, parallelizes as population-per-generation (each individual = one warm-start probe). What GERS (§4) uses.
- **MAP-Elites / CMA-MAE** (QD): fill an **archive** binned by *behavior descriptors* — for us, bin by (block-mix ratio, advancement rate, TD rate), keep highest-scoring per cell. **CMA-MAE** (Fontaine & Nikolaidis) fixes CMA-ME's stalls. Mature QD-RL: QDAC (2403.09930), PG-QD (2501.18723), MO-QD (2411.12433).
- **How WE use it (sleeper pick):** our stat-matching objective is multi-target and knobs trade off (block-mix vs advancement vs TDs). **MAP-Elites over reward space, human stats as behavior descriptors, stat-distance as fitness, turns "can't hit all targets at once" into a map of which reward economy buys which behavioral profile.** 860K SPS affords the thousands of short probes QD wants. Use `pyribs`. Best exploits cheap-fast-probe alongside Protein; gives the **behavioral atlas**, not just argmax.

## 3. Multi-objective reward optimization
- **Key 2024-25 result:** fixed linear scalarization **provably cannot reach non-convex Pareto regions** (supporting-hyperplane theorem). Our hand-tuned weighted-sum reward is a fixed scalarization — there may be human-matching profiles it literally cannot represent at any weights.
- **C-MORL** (2410.02236, ICLR 2025): efficient Pareto-front discovery. **Dynamic Reward Weighting** (2509.11452, Sep 2025): adjusts objective weights *during* training via hypervolume/gradient-interaction — reweight toward whichever human-stat is currently furthest. **Constrained MORL / max-min** (2605.31388, 2026): "match block-mix *subject to* TD-rate within tolerance."
- **How WE use it:** (a) reformulate probe score as vector-valued (one residual per human stat), let Protein/CMA-ES optimize a *rotating* scalarization (dynamic weighting); (b) if single-policy matching fights itself, go **constrained** (primary = win-rate/TD-rate, others = tolerance bands). MORL is the right *framing* even if the optimizer stays Protein/CMA-ES.

## 4. Bilevel optimization of reward (outer reward → inner policy → TRUE objective)
- **GERS — Evolutionary Bilevel Reward Shaping** (PPSN 2026, 2606.16236): the closest paper. Inner = RL on shaped reward; **outer = CMA-ES over reward-shaping params**, optimizing **cumulative *unshaped* reward on held-out validation using only scalar feedback**. Swap "validation envs"→"human-replay stat aggregate", "unshaped reward"→"stat-distance" and this **is** our harness, CMA-ES as the named outer optimizer.
- **Meta-gradient / hyper-gradient bilevel** (2405.19697, 2402.06886, 2510.07624): differentiate the true objective through inner training. More sample-efficient in principle but requires differentiating through PPO — heavy, brittle, **and our reward is read by a discrete C engine, so gradients don't flow.**
- **How WE run it:** adopt **GERS framing + derivative-free outer (CMA-ES/Protein); do NOT attempt meta-gradients through the C engine.** Our warm-started probe = the inner solve; CMA-ES proposing knobs + reading stat-distance = the outer solve. One config away from a textbook evolutionary-bilevel reward-shaping loop. Most accurate description of what to build; coincides with §2.

## 5. Bandit / budget allocation (successive halving, Hyperband, ASHA)
- **Successive Halving / Hyperband**: many knob-vectors at tiny budget, keep top 1/η, multiply survivors' budget by η.
- **ASHA**: asynchronous — promotes the instant a trial is top-1/η of its rung, never blocks on stragglers. **Right primitive for our fleet** (parallel boxes, no sync barriers).
- 2024: HPO surveys (2410.22854); **ULTHO** (2503.06101, ultra-lightweight bandit HPO for deep RL).
- **How WE run it:** (a) free — Protein already does cost-aware early stopping (`RobustLogCostModel`); (b) explicit — wrap probe reads in **Ray Tune ASHA** (rungs 0.5B/1B/2B/4B, η=3), prune bottom two-thirds by stat-distance. Clears hundreds of candidates/day. **ASHA = budget controller; Protein/CMA-ES/QD = candidate sampler — they compose.**

## Recommended stack
1. **Sampler: Protein** (zero-glue, cost-aware; seed search_center at current economy). Land #58 first.
2. **Framing: evolutionary bilevel reward shaping (GERS-style)** — outer CMA-ES, inner warm-start probe, objective = human-stat-distance. Derivative-free only.
3. **When one-policy matching fights itself: MAP-Elites/CMA-MAE over reward space** (behavioral atlas) + **MORL framing** (vector score + dynamic weighting/constraints; fixed linear scalarization provably can't reach non-convex Pareto).
4. **Budget controller: ASHA** (Ray Tune) — or lean on Protein's built-in early stopping.
- **Don't:** full online PBT (our loop is fixed-knob short-read); meta-gradient bilevel (no clean gradients through the C sim).

## Sources
Protein (puffer.ai/docs.html, pufferai/pufferlib, kywch/puffer-phc); PB2 2002.02518; GPBT 2404.08233; MO-PBT 2306.01436; QDAC 2403.09930; PG-QD 2501.18723; MO-QD 2411.12433; C-MORL 2410.02236; Dynamic Reward Weighting 2509.11452; Constrained max-min MORL 2605.31388; **GERS 2606.16236**; hyper-gradient bilevel 2405.19697; ULTHO 2503.06101.
