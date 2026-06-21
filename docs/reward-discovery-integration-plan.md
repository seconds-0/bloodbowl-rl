# Reward-Discovery Integration Plan (Claude draft v1, 2026-06-20)

Maps the 2024–2026 SOTA (see `analysis/reward-discovery/01..04` + `papers/key-paper-extracts.md`)
onto our concrete repo. Sequenced by effort × value × dependency. Guiding invariants we KEEP:
decision-time-EV pricing (D147); win-rate/Elo-vs-frozen-anchors as the only ground truth; DECISIONS.md
ledger; never-destroy-cloud-resources.

## Guiding reframe (the meta-point that organizes everything)
We are doing **manual evolutionary bilevel reward shaping** (GERS framing): outer loop = us choosing
knobs, inner loop = warm-started probe, objective = human-stat distance + Elo. Every item below either
(a) makes the outer loop automatic/cheaper, (b) makes the inner read trustworthy, or (c) replaces hand
weights with corpus-learned ones. Adopt in that priority order — trust before automation before learning.

## TIER 0 — Free, no compute, do first (this session / next)
1. **Potential-shaping knob audit.** Classify each of the 8 EV knobs as PBRS-potential `γΦ(s')−Φ(s)`
   (provably optimum-invariant → hack-immune) vs raw event-bonus (optimum-mover → risk surface).
   Expected: possession annuity + dist-ball + dist-endzone are telescoping potentials (safe);
   k_kd/k_value/k_ball + the new k_turnover + rush-cost are raw bonuses (the surface to scrutinize).
   Deliverable: a table in DECISIONS.md + flag which raw bonuses could be re-expressed as Φ-differences
   (e.g., k_value removal-EV → a "team-value-on-pitch" potential). COST: read-only analysis. RISK: none.
2. **Success-metric reframe.** Stop reading aggregate 2d-red; read **low-value-target 2d-red** + the
   carrier telemetry (blocks_vs_carrier, carrier_knockdowns) so "smart carrier-pressure 2d-red" is not
   scored as failure (review F7). COST: a stats rollup. RISK: none.

## TIER 1 — Cheap, high-value: make the probe loop trustworthy + the human anchor (days)
3. **Sign-pair logging in the probe workflow.** Per eval, per anchor-archetype, log
   (Δshaped_reward, ΔElo-vs-FROZEN-anchors). Flag the reward-hacking quadrant (Δproxy>0, Δtrue<0) and
   proxy-under-alignment (drop that knob). Requires a small frozen archetype-diverse anchor set
   (we already keep anchors) scored each eval. COST: eval harness + a log field. RISK: low.
4. **EvalStop monitor.** Stop-and-keep-best on k=2 consecutive Elo-vs-anchor declines even while shaped
   reward climbs — catches the reward-overoptimization inverted-U. ~20-line addition to the fleet
   monitor we already run. COST: tiny. RISK: low (just a stop rule). DEPENDS: 3 (needs the anchor-Elo
   signal).
5. **From-scratch reproduction as the graduation gate (addresses warm-start bias directly).** A reward
   isn't "discovered" until a short **BC-init / cold** replicate (≥2 seeds) moves toward the target.
   Formalize as the D46 graduation criterion. The netblock turnover finding is the first candidate to
   put through this gate. COST: one extra short run per graduated reward. RISK: compute; this is the
   "real cost" item the agent flagged for Codex-review-before-adopting.
6. **Cross-ancestor warm-start probe.** Re-read a candidate reward warm-started from 2 DIFFERENT
   lineages (e.g., a bash-leaning cap + an agile-leaning cap). Behavior depends on ancestor ⇒ we were
   reading the policy not the reward. (We're 4 economies deep on ONE chain — real exposure.) COST: one
   extra probe per important verdict. RISK: low.
7. **KL-to-BC anchor during RL (AlphaStar/piKL).** Cheapest human-likeness lever; add a decaying
   KL(π_RL‖π_BC) term using the existing bc_v4 BC policy. Does NOT touch the reward (policy
   regularizer → no variance-laundering). ~1-day build (it's an aux-loss term in the trainer, similar
   to the BC-coef we've used). RISK: low–medium (a training-loop change → needs the native build +
   NaN-stability recheck). High value for the "play like humans" objective.

## TIER 2 — Automate the outer loop (1–2 weeks)
8. **Protein sweep (the tool we already own).** Cost-aware BO over the knobs, `search_center` seeded at
   the current economy, `score = −human-stat-distance`, `cost = wallclock`, built-in early-stop.
   Replaces one-knob-at-a-time manual sweeps with joint cost-aware search. DEPENDS: land the match-mode
   sweep PR (task #58) first. COST: PR + sweep config. RISK: medium (Protein is Python; verify it
   drives the native arms correctly). Start with a 3–4-knob sweep around the netblock economy.
9. **EA-SEED LLM-in-the-loop controller (formalize D113-A).** After each probe cap, emit a structured
   report {per-stat observed, human-ref, delta} + {per-knob mean contribution} (Eureka "reward
   reflection") → an LLM returns the next knob vector as JSON + rationale logged to DECISIONS.md →
   launch the warm-started arm → repeat. COST: a launcher wrapper + a metric-report emitter. RISK:
   medium (LLM-proposed knobs must pass the Tier-1 guardrails before a full arm). This is the
   "automate what we do by hand" centerpiece — and the paper-worthy bit.
10. **CARD/TPE pre-filter.** Before spending a full probe arm, rank an LLM/Protein-proposed knob vector
    against a cached self-play trajectory bank (we keep banks) as a cheap proxy; only train the top
    1–2. Direct multiplier on iteration throughput. DEPENDS: 9. RISK: low.

## TIER 3 — Learn the reward from the corpus (2–4 weeks, research-grade)
11. **f-IRL / moment-matching knob calibration.** Fit the WEIGHTS of a linear-in-φ reward over our
    existing human-stat features so a policy optimizing it reproduces human moments — offline on the
    frozen 12,722-game corpus, freeze, anneal in. Auto-calibrates the 8 knobs instead of hand-tuning;
    keeps interpretability + decision-time-EV (φ over pre-dice features). COST: an offline fitter on
    the 2.1M pairs. RISK: medium-high (research-grade; validate it beats hand-tuning before trusting).
12. **MAP-Elites / CMA-MAE behavioral atlas (when one policy can't hit all targets).** QD over reward
    space with human stats as behavior descriptors → a map of which reward economy buys which
    behavioral profile. Use `pyribs`. COST: QD harness + many short probes (our throughput affords it).
    RISK: medium. Adopt only if the multi-target tension (block-mix vs advancement vs TDs) proves
    irreducible under scalar optimization (it likely will — fixed linear scalarization provably can't
    reach non-convex Pareto regions).

## DO NOT
- Online adversarial IRL (GAIL/AIRL) in the self-play loop — stacks two non-stationarities + rewards
  post-dice realized outcomes = violates decision-time-EV.
- Meta-gradient bilevel — no clean gradients through the discrete C engine; use derivative-free
  (Protein/CMA-ES).
- Full online PBT — our loop is fixed-knob short-read, not online-schedule (unless we decide knobs
  should anneal across the curriculum).
- Tune knobs to directly maximize anchor-Elo (rots the held-out ground truth).

## Sequencing / dependencies
Tier 0 (now) → Tier 1 guardrails 3,4,6 (make every future read trustworthy) → 5 from-scratch gate
(Codex-review first, it has real compute cost) + 7 KL-to-BC (parallel, independent build) → Tier 2
automation (8 needs #58; 9–10 build on the guardrails) → Tier 3 (11–12, opportunistic / paper).
First concrete moves with the box live: Tier 0 audit (free) + 7 KL-to-BC (next build) + 8 Protein
(after #58). The netblock turnover finding is the first reward to run through the 5/6 trust gates.

## Open question for the integration review
Is the from-scratch graduation gate (item 5) worth its compute cost as a STANDING rule, or only at
final lock-in? And: should KL-to-BC (7) replace or complement the decision-time-EV shaping for
human-likeness? These are the two judgment calls for Codex + the adversarial review.
