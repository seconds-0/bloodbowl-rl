# Decision-Time Reward Discovery against Human Behavioral Distributions in a Fast, Deterministic Blood Bowl Simulator

*Working preprint draft. v1, 2026-06-20.*

---

## Abstract

Reward shaping for competitive board games is hard precisely where it matters most: the
reward must be dense enough to drive learning through a sparse, rare scoring signal, yet it
must not teach the agent to chase variance or to optimize a proxy that diverges from
winning. We study this problem in **Blood Bowl Third Season Edition (BB2025)** — a
fully-observable but heavily stochastic, turnover-driven tabletop game with an enormous
turn-wise branching factor that, in its full 11-a-side form, no published pure-RL agent has
solved. We make three contributions. **(1) A system:** a deterministic, injectable-dice C11
rules engine for BB2025 bound to PufferLib as a native vectorized environment that sustains
~860K agent-environment steps/second on a single GPU, trained with PPO, exhaustive
per-decision action masking, and a self-play league, warm-started from behavioral cloning on
a curated corpus of 12,722 human FUMBBL replays. **(2) A methodology:** *decision-time
expected-value (EV) reward shaping*, discovered by warm-started "probe" training arms whose
emergent aggregate behavior is read against a human-replay statistical target. We formalize a
design constraint we call the **cardinal rule** — every shaping term must be priced from the
*expected value of the chosen action at the moment it is declared*, computed by a pure,
RNG-free EV oracle (`bb_block_ev`) *before* the dice are rolled, and never from the realized
post-dice outcome — and argue that violating it launders variance into the reward and teaches
dice-superstition. **(3) An empirical finding about the structure of reward shaping itself:**
in a controlled progression of single-lineage probe arms, scaling the *magnitude* of
upside-only block-reward knobs is approximately **scale-invariant on the action mix** — it
buys more blocks of *every* kind, including unfavorable ones, without shifting *selectivity*
toward the human distribution (raising and then doubling the aggression knobs increased block
volume 5→15.7→21.1 per episode while the unfavorable "2-dice-red" fraction stayed high or
worsened, 0.10→0.11→0.13). What finally moved the mix toward human play was pricing the
**downside** — a net-EV term that charges the declaration-time turnover probability against the
takedown value — which more than halved the unfavorable-block fraction (0.12→0.056) while
scoring and ball advancement held or rose. We
position these findings honestly against the LLM-reward-design (Eureka, EA-SEED),
reward-from-demonstrations (f-IRL, AlphaStar/piKL), potential-based shaping (Ng–Harada–Russell),
and reward-hacking/Goodhart literatures, and we are explicit about what we have *not* yet
done: these are **behavioral and methodological** results from single-seed, single-lineage,
warm-started reads — single-lineage evidence for a mechanistically-interpretable design
principle, not a controlled multi-seed demonstration. We have not run the from-scratch
reproduction gate or a tournament-confirmed strength result, so we make no claim of a
superhuman or even tournament-validated agent.

---

## 1. Introduction

Blood Bowl is a fantasy-football board game in which two teams of 11 take turns moving,
blocking, and passing on a 26×15 grid. Almost every meaningful action is resolved by dice:
blocks roll custom block dice, movement past opponents requires dodge rolls, running beyond a
player's allowance requires "Go For It" (Rush) rolls, and picking up or passing the ball can
fail. Crucially, the game has a **turnover** mechanic: a single failed roll (a fumbled pickup,
a failed dodge, an attacker knocked over on a block) ends the active team's entire turn on the
spot. Scoring — carrying the ball into the opponent's end zone for a touchdown — is rare
(humans average ~2.2 touchdowns per game over a corpus of 12,722 replays) and is separated
from any single decision by a long, fragile chain of dice. This combination — a vast branching
factor, pervasive stochasticity, an unforgiving turnover rule, and a sparse terminal reward —
is exactly what makes the game a recognized AI challenge [Justesen et al., 2019] and exactly
what makes reward shaping both necessary and dangerous.

It is *necessary* because a pure terminal (win/touchdown) reward is too sparse to bootstrap:
the Bot Bowl line of work established that naive RL on the full game fails to consistently beat
even a random agent, and the strongest learned agent to date (MimicBot, the Bot Bowl III
winner) succeeded only by combining imitation learning with RL [Pezzotti, 2021]. It is
*dangerous* because the obvious dense signals — "reward an injury inflicted," "reward a
successful pickup" — pay for *dice outcomes*. A reward that pays for the injury that landed
rewards the lucky roll, not the good decision, and across a self-play population it teaches the
agent to value variance.

This paper is about how to shape such a reward *well*, and about a methodology for
*discovering* the right shape empirically. Our objective is deliberately not "win at any cost":
because human Blood Bowl play is a large, strategically meaningful behavioral reference (not an
optimality certificate — the corpus is not skill-filtered) and because we want behavior that is
legible and human-like, our target is to **reproduce the aggregate behavioral distribution** of a
large human-replay corpus — block-dice selectivity, ball-advancement rate,
touchdown rate — rather than to copy human actions or to maximize an unconstrained win-rate.
This reframing turns reward design into a *behavioral distribution-matching* problem and turns
reward *discovery* into a search over reward economies read against a human statistical target.

We pursue this in a system built for it: a deterministic C engine fast enough (~860K
environment steps/second) that a candidate reward economy can be evaluated by a short,
warm-started "probe" training arm in hours, not days. The speed is load-bearing — it is the
same property that makes the LLM-reward-design literature (born on fast GPU robotics
simulators) work, and it is rare in game RL.

### Contributions

1. **System (§4).** A deterministic, injectable-dice C11 BB2025 engine with a closed-form,
   RNG-free EV oracle for blocks; a PufferLib native binding running at ~860K SPS with full
   per-decision action masking; an obs encoding that gives the policy the same pre-decision
   probability information a human reads off the UI; and a 7-layer validation architecture
   anchored on a 12,722-game human replay corpus. We also report a non-trivial native-CUDA
   numerical-stability engineering result (§6.3).

2. **Methodology (§5).** *Decision-time EV reward shaping*, and the **cardinal rule** that
   formalizes it: price the declared action's pre-dice EV, never the realized post-dice
   outcome. We give the classification procedure we use to audit every reward term, the
   probe-arm discovery loop, and the human-statistic targets.

3. **Empirical finding (§6).** The **dice-mix result**: mechanistically-interpretable
   single-lineage evidence that *upside-only magnitude scaling is scale-invariant on action
   selectivity* and that *pricing the downside (net-EV)* is what shifts the mix toward the human
   distribution. We argue this *suggests a general design principle* for reward shaping, while
   being explicit that the empirical base is one warm-started lineage (§7), not a multi-seed or
   from-scratch validation.

We are explicit throughout about limitations (§7): every result here is read from a
single-seed, single-lineage, warm-started probe; we have not yet executed the from-scratch
reproduction gate or a tournament-grounded strength confirmation. The contribution is the
engine, the methodology, and the behavioral finding — not a validated strong agent.

---

## 2. Background: Blood Bowl as an RL problem

**The game.** BB2025 is fully observable and turn-based. On its turn a team activates players
one at a time; each activation can move, block an adjacent opponent, blitz (move-then-block),
foul, pass, or hand off. The action space is large and *uneven* — the number of legal actions
varies enormously by game state — which historically defeated flat-action RL agents
[Justesen et al., 2019; Pezzotti, 2021]. We expose it as a factored discrete action space with
spatial heads (e.g., a 391-wide square-selection head for kick placement and movement targets)
and exhaustive action masking.

**Dice and turnovers.** Blocks are resolved with block dice whose face distribution depends on
the strength differential and assists (the familiar "2-dice", "3-dice", "1-dice", and "2-dice
against" regimes; we write the unfavorable "2-dice against" case as **2d-red** throughout, and the
favorable "2-dice for" case as **2d**). A block can knock down the defender, the attacker, both, or neither;
an attacker knocked down on their own block is a **turnover** that ends the team's turn.
Movement past tackle zones requires dodges; movement beyond a player's allowance requires
Rushes; all can turn the ball over. This is the structural reason a naive outcome reward is
toxic: the *same decision* (declare a 2-dice block) yields wildly different realized injury and
turnover outcomes depending on dice the agent does not control.

**The human reference.** We measured a corpus of 12,722 FUMBBL replays (453,617 team-turns):
~2.22 touchdowns/game, ~88.8 block rolls/game, and a block-dice *mix* of 2-dice 0.775,
3-dice 0.085, 1-dice 0.124, and 2-dice-red **0.017** (i.e. humans throw favorable-to-unfavorable
2-dice blocks at roughly 46:1). A separate recorded-trajectory parser over 401 fully-normalized
games gives a ball-advancement reference of ~6.0 forward squares per possession (~1.36 per
team-turn). We treat these as a **large, strategically meaningful behavioral reference, not an optimality
certificate and not a ceiling** (the corpus is not skill/division-filtered) — a genuinely
superhuman policy could legitimately diverge (fewer, better blocks; more ball security) — and so
we use them as *targets to move toward and diagnostics to reconcile against*, never as the sole
graduation criterion.

---

## 3. Related work

**Blood Bowl / Bot Bowl.** Justesen et al. [2019] introduced Blood Bowl as an AI challenge with
the FFAI/botbowl framework, OpenAI-Gym environments (including scaled-down boards), a scripted
bot (GrodBot), and the Bot Bowl competition; they report that the full game's branching factor
and rare reward defeat both search heuristics and naive RL, with curriculum learning failing to
consistently beat a random agent on the full board. Justesen et al. [2018, "Rewarding
Temporally Rare Events", arXiv:1803.07131] used event-rarity as an automatic curriculum on
scaled Blood Bowl variants. MimicBot [Pezzotti, 2021, arXiv:2108.09478] won Bot Bowl III by
combining imitation learning (behavioral cloning of human/scripted play) with RL and a hybrid
decision process — the first learned agent to consistently beat the scripted bots — and remains
the strongest published learned result. Our work differs along three axes: (i) we target the
*current* edition (BB2025, with its updated skills, teams, and errata), (ii) our engine is a
deterministic native-C simulator at ~860K SPS rather than a Python framework, enabling the
short-probe reward-discovery loop, and (iii) **our research question is different** — we study
reward *discovery against a behavioral distribution*, not maximal competitive strength. We
share MimicBot's core insight that human imitation is essential to bootstrap (we BC-warm-start
from the replay corpus), and we do **not** claim to beat MimicBot or any human; we have not run
a cross-agent tournament.

**LLM-driven and automated reward design.** Eureka [Ma et al., 2023, arXiv:2310.12931] has GPT-4
write reward *code* from environment source, evolves it, and "reflects" on training telemetry,
beating human-engineered rewards on 83% of 29 robotics tasks — explicitly leveraging fast GPU
simulators to evaluate many candidates. EA-SEED's *Self-Correcting Reward Shaping* [Afonso et
al., 2025, arXiv:2506.23626] is the closest published analog to our manual loop: a language
model proposes updated reward *weights* each iteration from a natural-language behavioral goal
plus a summary of training statistics, in PPO, on a game. **Our manual probe-arm loop is
precisely this loop run by a human** — our EV knobs are its "weights", our human-corpus
aggregate statistics are its "performance summary", and our goal ("match the human
distribution") is its behavioral goal. The gap we occupy: this literature is overwhelmingly
*single-agent* (robotics, single-agent racing); none target a *competitive self-play league*
against a *human behavioral-distribution* target. PufferLib's Protein tuner (cost-aware Bayesian
optimization, CARBS lineage) and evolutionary bilevel reward shaping [GERS, Usaratniwart et al.,
2026, arXiv:2606.16236] are the natural tools to *automate* our hand loop (§8).

**Learning a reward from human data.** The classical framing closest to our objective is
**feature-expectation matching**: apprenticeship learning [Abbeel & Ng, 2004] learns a reward as
a linear combination of features such that a policy optimizing it matches the expert's *feature
expectations* — precisely "reproduce aggregate human statistics without copying actions", which
is our goal stated in the IRL vocabulary. f-IRL [Ni et al., 2020, arXiv:2011.04709] is its modern
density-matching successor: it recovers a *stationary* reward by gradient descent on an
f-divergence between agent and expert *state-marginal* densities — conceptually our best fit for
"auto-calibrate the knob weights so the policy reproduces human moments", run offline on the
frozen corpus. Related occupancy/moment-matching methods (SMM, GMMIL, and the stable
inverse-soft-Q family IQ-Learn and CSIL/ValueDICE) are the natural alternatives if a non-linear
learned reward is wanted; we leave these to future work (§8). Adversarial IRL — GAIL [Ho & Ermon,
2016, arXiv:1606.03476] and AIRL [Fu et al., 2017, arXiv:1710.11248] — is the wrong tool here: a
discriminator scores *realized* transitions (violating our decision-time constraint) and stacks a
second non-stationarity onto self-play. The
game-AI precedent we lean on is **human-KL regularization**: AlphaStar [Vinyals et al., 2019]
trains via supervised learning from human replays then holds a KL penalty toward the
supervised policy throughout RL; piKL [Jacob et al., 2022, arXiv:2112.07544] regularizes search
toward a human imitation policy to get *strong yet human-like* play. Our BC warm-start is the
cheap half of this; a decaying KL-to-BC term is our most natural next human-likeness lever.

**Potential-based shaping and reward hacking.** Ng, Harada & Russell [1999] prove that a
shaping term of the form F(s,s') = γΦ(s') − Φ(s), for *any* potential Φ, leaves the set of
optimal policies *exactly unchanged* — it can only change learning *speed* (Wiewiora [2003]
shows it is equivalent to Q-value initialization), and the multi-agent generalization [Devlin &
Kudenko, 2011] preserves Nash equilibria under per-player PBRS — directly relevant to a two-player
game. This is the formal version of our stated goal — "bias learning speed, not the
optimum" — and it gives a sharp test: knobs expressible as a potential difference are
hack-immune by construction; knobs that are *raw per-event bonuses* (our k-knobs, the turnover
charge) can move the optimum and must be scrutinized. The reward-hacking literature names the
failure modes we guard against: Goodhart's four variants [Manheim & Garrabrant, 2018,
arXiv:1803.04585] (regressional, extremal, causal, adversarial), and reward-model
over-optimization scaling [Gao et al., 2022, arXiv:2210.10760], where the true objective rises
then falls (an inverted-U) as one optimizes the proxy harder — directly relevant to our
observation that cranking a magnitude knob eventually buys only unfavorable blocks. Finally,
**self-play evaluation in non-transitive games** is itself a known hazard: Blood Bowl has
rock-paper-scissors matchups (bash beats agile beats ball-control beats bash), so a "win-rate vs
the current opponent" signal can look healthy while the population cycles. This is part of why we
treat the *absence* of a tournament-vs-frozen-anchors strength number (§6.4) as a real gap, not a
formality, and why the standard self-play remedy is a frozen, archetype-diverse anchor pool
(PSRO/league methods, AlphaStar).

---

## 4. System

### 4.1 Deterministic injectable-dice C11 engine

The engine is a substantial (~20K-line) C11 implementation of BB2025 (30 teams, the skill/trait
catalogue, the May-2026 FAQ/errata) with injectable dice and a replay-differential validation
layer under active use. It is not claimed bug-free or fully rules-complete: some rule windows
remain approximated, and the decision log records recently-found legality bugs (e.g., a BB2025
Blitz-declaration reachability gate that the validation layers initially missed). Two properties
are foundational:

- **Determinism with injectable dice.** Every random draw flows through a single RNG abstraction
  (`bb_rng`) that is either a seeded PCG-64 stream or a *scripted* sequence injected by a test or
  replay. The same state plus the same dice always produces the same transition. This is what
  makes the 7-layer validation (§4.4) and the closed-form EV oracle possible, and it is what lets
  us replay human FUMBBL games through the engine and diff the engine's decisions against the
  recorded ones (the replay-differential layer).

- **A pure, closed-form EV oracle.** `bb_block_ev` computes, with *no RNG*, the exact outcome
  distribution of any block at *declaration* time: `p_def_down`, `p_def_removed`, `p_att_down`,
  `p_att_removed`, `p_ball_out`, and `p_turnover`, with full skill handling (Block, Wrestle,
  Tackle, Dodge, Mighty Blow, Claws, Dauntless, Fend, owner-optimal die choice). It is validated
  against Monte-Carlo (25-matchup MC panel) and is the canonical pre-dice EV used both by the
  reward and by the observation encoder. The existence of this oracle is what makes the cardinal
  rule (§5.1) *implementable*: "price the decision, not the outcome" requires a way to compute
  the decision's value before the dice are rolled.

### 4.2 PufferLib native binding (~860K SPS)

The engine is bound to PufferLib [Suárez, 2024, arXiv:2406.12905] as a native vectorized
environment via its C macros, training with PPO. Self-play is implemented by stepping both
teams through the same env with perspective-swapped observations and per-team reward routing.
On a single modern GPU the native CUDA backend sustains on the order of **860K
agent-environment steps/second** (config- and box-dependent; the native backend is ~3× the
PyTorch backend, and we have measured violence-arm throughput at ~850–862K SPS). The point of
the speed is economic: it makes a *candidate reward economy* cheap to evaluate. A short
warm-started "probe" arm of a few billion environment steps caps in hours, which is what makes a
human-in-the-loop reward-discovery loop (§5.3) practical at all.

### 4.3 Observation: decision-support parity with the human UI (obs-v4)

A central early finding was that the agent's block-dice mix was wildly inhuman and *flat across
training*. The hypothesis (validated by the obs-v4 redesign) was an *information-parity* gap: the
FUMBBL UI shows a human the block-dice count and the dodge/Rush/pickup target numbers *before*
they commit, so the human corpus encodes decisions made *with* that information, while the raw
observation forced the network to re-derive three-way relational arithmetic (strength compare +
assist count + marking) implicitly. Obs-v4 (2782 bytes) appends three probability planes computed
by the same EV machinery: A1 = P(defender knocked down) and A2 = P(attacker knocked down) per
candidate block target (both, because a Blockless 2-dice block can be high on *both*), and B =
P(success) per legal move destination (compounding dodge × Rush × pickup). This is
*decision-support*, not strategy injection: every value is public information a competent human
computes before every roll. Notably the planes carry *probabilities only*, never *values* —
weighting outcomes is the policy's job.

### 4.4 Validation and the human corpus

Engine correctness is exercised by a 7-layer architecture under active use: (1) spec/unit tests,
(2) dice chi-square tests, (3) property/invariant tests, (4) fuzzing, (5) golden traces, (6) a
coverage gate, and (7) a **replay-differential** layer that re-simulates recorded human FUMBBL
games through the deterministic engine and diffs decisions/odds against the recording. We describe
this as a validation *architecture in active use*, not a completed certification: the Blitz-gate
bug above is exactly the class of legality miss the replay-differential layer is meant to catch,
and remaining rule-window approximations are tracked in the decision log. A per-layer
pass/fail/coverage report is future work (§8). The human
behavioral targets come from the same corpus: 12,722 replays for rate/mix statistics and 401
fully-normalized games for ball-trajectory statistics (§2). Importantly, the *training
dashboard* statistics are measured from *curriculum starts* and are **not** directly comparable
to the from-kickoff human numbers; fair comparison requires a full-game agent evaluation in the
same units. Where we report agent-vs-human comparisons of fractions (e.g., the block-dice mix),
those fractions are curriculum-robust; absolute per-game rates are reported with this caveat.

---

## 5. Method: decision-time reward discovery

### 5.1 The cardinal rule

> **Cardinal rule.** Every *shaping* term must be priced from the expected value (or settled
> state) of the chosen action *at the moment it is declared*, before the dice are rolled. The
> only legitimate *outcome* rewards are the objective/terminal ones — win, loss, draw, touchdown,
> and the possession annuity (a zero-sum turn-boundary mini-terminal). Rewarding a realized
> dice result as *shaping* is forbidden.

The justification is direct. Consider two identical declarations of a 2-dice block. Their
realized injury outcomes differ only by the injury dice — variance the agent cannot influence.
A shaping term that reads the realized KO/casualty box therefore pays *different rewards for the
same decision*, which (a) is a high-variance, low-information learning signal and (b) assigns credit to
uncontrollable outcome variance, which can make the policy favor high-variance actions for the
wrong reason. The correct signal is the *EV at
declaration*: `bb_block_ev` already exposes `p_def_removed`, so the *expected* removal value is
available with zero RNG. We classify every reward term by a single question — **does it fire from
EV/settled-state pre-dice (legitimate shaping) or read a realized result post-dice (forbidden as
shaping)?** Potential-based telescoping terms over settled state (distance-to-ball,
distance-to-endzone) and pure reachability geometry are decision-time-legitimate by construction.

This rule is not free philosophy: it was learned from a costly empirical failure. An
"attrition" probe that *restored* a realized-injury reward (`injury_inflicted` read post-dice)
to drive contact moved block volume only 6.8→7.8 per episode and tied the prior champion — a
sparse, rare, variance-dominated signal cannot drive a dense decision. The dense pre-dice EV
knobs are the lever. A subsequent audit found four hard violators
(`injury_inflicted/taken`, `send_off`, `kickoff_touchback`, `ball_gain/ball_loss`) plus one
qualified episode-end regularizer (`statmatch_scale`, mostly attempt-counts, left in place), and
specified the EV conversion for each hard violator (e.g., price `P(send-off)` from the
doubles/bribe/argue probabilities at foul *declaration*; price `P(touchback)` by convolving the
scatter distribution over the aim square at *placement*). We note that one of these,
`ball_gain`, was nonetheless held *active* across the §6 experiment arms (§5.2, §6) — a disclosed
confound, not a clean economy.

### 5.2 The reward economy

The settled economy is a weighted sum of decision-time-legitimate terms (representative values;
these are the knobs the probe loop searches):

| Term | Form | Class | Role |
|---|---|---|---|
| `win` / `draw` / `td` | terminal | objective | the goal |
| `possession` annuity (0.03) | zero-sum turn-boundary | objective | reward holding the ball at own-turn-end |
| `dist_ball` (0.05), `dist_endzone` (0.2) | potential-like difference ≈ γΦ(s')−Φ(s) | potential-like | advance toward ball / end zone |
| block `k_kd` / `k_value` / `k_ball` | pre-dice block EV (`bb_block_ev`) | raw event bonus | reward the favorable block's upside |
| `k_seq` | pre-dice own-turnover risk × unbanked activations | raw event bonus | sequencing discipline |
| `k_turnover` (net-EV charge) | −`k_turnover`·`p_turnover` at declaration | raw event bonus | **price the downside (§6)** |
| `rush_cost` (0.015) | declaration tax | raw event bonus | anti-degeneracy scaffolding |
| `ball_gain` (0.05) | realized possession transition (post-dice) | **outcome (cardinal-rule violator)** | held active across §6 arms — see note |

The economy is *predominantly*, but not *fully*, cardinal-rule clean. The audit (above)
classifies `ball_gain` as an outcome-based shaping violator (it pays on the realized pickup/strip
/scatter result), and it was held active at 0.05 across the §6 arms rather than zeroed or
converted to a declaration-time `k·P(pickup success)`. Because it was held *constant* across
violence, violence2, and netblock, it is unlikely to explain the block-dice-mix deltas, but a
fully cardinal-rule-clean replication should set `ball_gain=0` or price pickup/pass EV at
declaration. We flag this confound explicitly in §6.

The block reward is the load-bearing object. In code it is (per declared block, zero-sum
attacker/defender, scaled by the rush-delivery probability `p_deliver` for no-movement blitzes):

```
exposure       = p_deliver · ( k_kd·p_def_down + k_value·p_def_removed·value(def) + k_ball·p_ball_out )
turnover_cost  = k_turnover · p_turnover                    # net-EV downside (D158/D159)
block_reward   = exposure − turnover_cost
```

Every factor (`p_def_down`, `p_def_removed`, `p_ball_out`, `p_turnover`) comes from
`bb_block_ev` at declaration — pre-dice, cardinal-rule clean. We flag, with the PBRS literature
(§3), that the distance terms (dist_ball, dist_endzone) are *intended as* potential-like shaping:
the Ng–Harada–Russell optimum-invariance guarantee applies only where the implementation exactly
matches γΦ(s')−Φ(s) and is not altered by the [−1,1] reward clipping or by interaction with the
non-potential raw bonuses, so we claim a potential-*like* design intent, not a verified
invariance. The possession annuity is a zero-sum turn-boundary objective-class term, *not* a
potential difference, and we do not ascribe the PBRS guarantee to it. The block k-knobs and the
turnover charge are *raw event bonuses* that can move the optimum and are therefore the real
hacking surface — an audit we report but have not yet discharged with a potential-shaping rewrite
or an anneal-to-zero lock-in (§8).

### 5.3 The probe-arm discovery loop

A reward "discovery" iteration is: (1) propose a knob change motivated by a behavioral gap
(observed-vs-human on a target statistic); (2) launch a *warm-started* probe arm — a few-billion
-step self-play continuation from a recent checkpoint, with the new economy, on the fast native
backend; (3) read the emergent aggregate statistics (block-dice mix, ball-advancement,
touchdowns, contact volume) against the human reference; (4) keep, revise, or revert. The
warm-start is what makes each read cheap (hours), and the fast engine is what makes the loop
tractable. This is the EA-SEED loop with a human in the LLM's seat (§3). We log every iteration
in a numbered decision ledger that doubles as the persistent memory of "knob → values tried →
resulting stat-deltas" — the role HROSE's State Execution Table plays in the automated version.

The methodology's principal hazard is **warm-start bias** (read off the lineage's
state-visitation distribution rather than implied by the reward) and the related single-seed/
single-lineage fragility. We discuss these as live limitations in §7 and the planned guards
(from-scratch reproduction gate, cross-ancestor warm-start, anneal-to-zero lock-in) in §8; the
results below are reported under exactly these caveats.

---

## 6. Experiments

All arms in this section are **single-seed, single-lineage, warm-started** probes on the native
bf16 CUDA backend, sharing the settled v4 economy except where a knob is named (and including the
`ball_gain=0.05` confound noted in §5.2, held constant across all arms). They are read on
training-dashboard aggregate statistics; block-dice *fractions* are curriculum-robust, absolute
per-game rates carry the curriculum-start caveat (§4.4). We frame all results as **behavioral**,
not as strength claims (no tournament confirmation; see §6.4, §7).

*Units.* A **curriculum episode** ("ep") is one training episode that begins from a *curriculum
start state* (a sampled mid-game position from the demo bank), not from the opening kickoff;
"blocks/ep" therefore is **not** the same unit as the human "blocks/game" (from kickoff). We
report per-ep agent metrics for relative comparisons across arms (same units) and mark human
per-game rates as orientation-only where they appear; only block-dice **fractions** are directly
agent-vs-human comparable. We report point estimates from the late-training dashboard window;
these arms are single runs without seed replicates, so we do not report confidence intervals —
the absence of multi-seed uncertainty quantification is itself a stated limitation (§7).

### 6.1 The dice-mix result: magnitude scaling is scale-invariant on selectivity

The agent's standing block-dice profile was *both* under-volume (~5 blocks/curriculum-episode
vs ~89/game human) *and* mis-selected: block_2d_frac ~0.45 (human 0.77) and block_2dred_frac
~0.10 (human 0.017 — roughly 6× too many unfavorable blocks). The natural hypothesis is that
the economy under-priced contact, so we scaled the upside knobs.

**Table 1 — Run provenance and per-ep agent metrics (same units; relative comparison only).**
Each arm is one single-seed warm-started run; the warm-start chain is
threat→violence→violence2→netblock (each from the prior's cap). "Steps" is the run's
environment-step budget. Per-ep metrics are training-dashboard reads from curriculum starts and
are **not** human-comparable in absolute terms.

| Arm | warm-from | steps | k_kd | k_value | k_turnover | blocks/ep | knockdowns/ep | tds/ep | fwd_adv (sq/poss) |
|---|---|---|---|---|---|---|---|---|---|
| baseline (threat-arm end) | league9_cap | ~4B | 0.03 | 0.25 | 0 | ~5 | ~2 | 0.35 | ~3.7–4 |
| **violence** | threat cap | 28B | 0.10 | 0.50 | 0 | 15.7 | 7.2 | 1.43 | 6.97 |
| **violence2** | violence cap | 12B | 0.20 | 1.00 | 0 | 21.1 | 9.7 | — | — |
| **netblock** | violence cap | ~14B | 0.10 | 0.50 | **0.15** | ~14 | — | 1.46 | ~6.9 |

*The block-volume and contact columns for the baseline row are measured at the violence-arm
launch (the standing pre-violence policy); its tds/fwd_adv are the immediately-preceding
threat-annuity arm's end-of-run values, which violence warm-started from. violence2's
tds/fwd_adv were not separately logged. netblock warm-starts from the **violence** cap (not
violence2), so its k-values match violence's. All values are single-run dashboard reads without
seed replicates or confidence intervals (§7).*

**Table 2 — Block-dice mix (fractions; directly agent-vs-human comparable).** These fractions
are curriculum-robust (§4.4). The denominator is the count of standing block declarations in the
measurement window.

| Arm | k_kd | k_value | k_turnover | **block_2d_frac** (→0.77) | **block_2dred_frac** (→0.017) |
|---|---|---|---|---|---|
| baseline (pre-violence) | 0.03 | 0.25 | 0 | 0.45 | 0.10 |
| **violence** | 0.10 | 0.50 | 0 | 0.49 | **0.11** |
| **violence2** | 0.20 | 1.00 | 0 | 0.47 | **0.13** |
| **netblock** | 0.10 | 0.50 | **0.15** | **0.543** | **0.056** |
| *human reference* | — | — | — | **0.77** | **0.017** |

*Human absolute rates (for orientation only, not in the comparison tables above): ~88.8 block
rolls/game and ~2.22 touchdowns/game from kickoff over the 12,722-game corpus; ~6.0 forward
squares/possession over the 401-game trajectory corpus. These are from-kickoff full-game units
and are not directly comparable to the per-ep agent dashboard rates in Table 1.*

Reading the table:

- **violence (k_kd 0.03→0.10, k_value 0.25→0.50).** Tripled block volume (5→15.7), tripled
  knockdowns, **quadrupled touchdowns** (0.35→1.43), and brought ball advancement up to the human
  ~6-7 sq/possession reference — refuting an a-priori worry that more contact would mean less
  ball progress ("violence makes lanes"). **But the dice mix barely moved**: 2d 0.45→0.49,
  2d-red 0.10→**0.11**.

- **violence2 (doubled again to k_kd 0.20, k_value 1.00).** Bought ~35% more blocks of *every
  kind* (15.7→21.1) and made the mix *worse* (2d-red 0.11→**0.13**, 2d flat at 0.47).

The mechanism is simple and general. The block reward is `k·p_def_down` (plus value/ball terms);
multiplying `k` scales the reward of *every* block — favorable and unfavorable — by the same
factor. The *ratio* between a 2-dice reward and a 2-dice-red reward is **scale-invariant in k**.
So raising `k` raises the *volume* of blocking (more blocks clear the action-value bar) but
cannot change *which* blocks are preferred. **Upside-only magnitude scaling changes volume, not
selectivity.** This is the inverted-U of reward over-optimization [Gao et al., 2022] seen through
a behavioral lens: pushing the proxy knob harder eventually buys only *more unfavorable-dice
blocks* — many, though not all, of which are bad. (A 2-dice-red is not always a mistake: blitzing
the ball carrier on a 2-dice-red to force a turnover is often correct. The aggregate 2d-red
fraction is therefore an imperfect proxy for "discipline" until it is stratified by target value
/ carrier status — see §6.2.)

### 6.2 Pricing the downside (net-EV) shifts the mix

To move selectivity we must break the scale-invariance — make a 2-dice-red *net-negative* where a
2-dice is net-positive. The lever is the **downside**: a 2-dice-red block has a high attacker-down
probability and therefore a high *turnover* probability (`p_turnover` ≈ 0.30 for 2d-red vs ≈ 0.03
for 2d — about 10×), which the upside-only economy never charged. The fix (the **net-EV** block
reward) charges the declaration-time turnover probability against the takedown value:

```
block_reward = ( k_kd·p_def_down + k_value·p_def_removed·value + k_ball·p_ball_out ) − k_turnover·p_turnover
```

This is cardinal-rule clean — `p_turnover` is a pre-dice EV from `bb_block_ev` — and it is
*selective by construction*: because the turnover term scales with `p_turnover`, it penalizes a
2-dice-red against a backfield lineman (high turnover, low removal value → net-negative) but
*can leave a 2-dice-red against the ball carrier or a star +EV* (where the removal/ball-out value
dominates the turnover cost). It does not *ban* the unfavorable block; it self-sorts by target
value. We note this self-sorting is an analytic property of the term, confirmed at the aggregate
level (the fraction dropped) but **not yet** confirmed at the stratified level — we did not read
the per-target (carrier-vs-lineman) telemetry that would show *which* residual 2d-reds survived.

The **netblock** arm (warm-started from the converged violence policy; k_kd 0.10, k_value 0.50,
k_turnover 0.15, with the confounding `k_seq` term zeroed for a clean read) **more than halved
the unfavorable-block fraction the magnitude sweep could not move**: block_2dred_frac
0.12→**0.056**, with block_2d_frac rising 0.49→**0.543** and — critically — **scoring and
advancement held or rose** (tds 1.43→1.46, fwd_adv ~6.9 held). The mix moved without
over-caution: better blocks, not fewer.

The headline lesson, which we offer as a *general design principle suggested by* (not proven by)
this single lineage: **to change an action *mix* (selectivity), shape the *downside* of the bad
action, not the *upside* of the good one.** Upside-only multiplicative shaping is scale-invariant
on selectivity and only inflates volume; pricing the asymmetric downside is what reweights the
choice. The analytic argument (scale-invariance of a multiplicative knob's reward *ratio*) is
clean; the empirical support is one warm-started lineage with the §7 caveats. We note honestly
that the netblock fraction (0.056) is still well
above human (0.017): the trajectory had not floored, k_turnover=0.15 was a first guess (a sweep
candidate), and we cannot yet distinguish "residual sloppiness" from "correct aggressive
carrier-pressure" without per-target telemetry (which ships in the same build but was not yet
read at the credit-stop that ended the arm).

### 6.3 Engineering result: a latent native-CUDA NaN

A reward-economy paper would be incomplete without the stability work that let it run. The
threat-annuity arm and a matched no-threat control died with `policy → inf → NaN` at 600M–700M
steps, exposing the bug. The diagnosis took five iterations and is itself instructive: the first
three fixes patched the *Python* PPO loop (`torch_pufferl.py`), which **native bf16 runs never
execute** — `pufferl.py` selects the native `_C` backend unless `--slowly` is passed, and the
loss math lives in the CUDA kernels (`pufferlib.cu`/`muon.cu`). A fourth diagnosis wrongly
concluded the fault was upstream of the ratio; the fifth and correct diagnosis (Codex-assisted)
identified the native backend and the true cause: an *unclamped* `__expf(logratio)` in the native
PPO kernel. A chronic rollout-vs-train log-probability mismatch (the native bf16 rollout and the
fp32 train-time recompute disagree on a few masked-action log-probs, driving the approximate KL
to ~110–190) occasionally produced `logratio > 88`, overflowing `exp()` to `+inf`, NaN-ing every
weight. The fix clamps the ratio input to [−10, 10] *before* `__expf` (keeping the *raw* logratio
for the KL diagnostics so the heavy-tail canary stays visible) and guards non-finite gradients in
the optimizer. The later violence (28B), violence2 (12B), and netblock (~14B) arms then ran with
zero NaN/inf — evidence that the native-CUDA fix held end-to-end (the first 28B clean native run
post-fix). The durable fix (bf16/fp32 log-probability parity) remains open and is a candidate
upstream PufferLib contribution. The transferable lesson: **for a native-backend numerics bug,
confirm which backend actually executes the patched path before diagnosing** — we spent three
wrong root-cause iterations patching dead code (and a fourth misattributing the layer).

### 6.4 What we did *not* measure

We attempted tournament confirmation (the project's standard strength gate) but the checkpoint
converter cannot currently load native bf16 pool snapshots into the match harness, so the
violence/netblock arms have **no head-to-head strength number**. The behavioral deltas
(4× touchdowns, advancement to the human reference, the halved unfavorable-block fraction) are
strong enough to motivate the next arm — but **not** to conclude improved *play*: they are
*behavioral*, not *strength*, results. We have also not run the from-scratch reproduction gate
(§7).

---

## 7. Discussion and limitations

We state the limitations plainly because they bound every claim above.

1. **No from-scratch validation.** Every result is read from a *warm-started* probe. A behavior
   read off a warm-started arm can be inherited from the lineage's state-visitation distribution
   rather than implied by the reward — the **warm-start bias** the IRL/Goodhart literature warns
   of (a restricted-coverage *extremal Goodhart*). The discipline this project commits to — but
   has **not yet executed** for the dice-mix result — is a *from-scratch reproduction gate*: a
   reward is not "discovered" until a cold/BC-init replicate (≥2 seeds) moves toward the target.
   Until then, the dice-mix finding is a strong, mechanistically-explained *single-lineage* read,
   not a validated invariant.

2. **Single seed, single lineage.** RL is seed- and init-sensitive; a single warm-started read
   is statistically weak. The violence→violence2→netblock arms are *one chain* (each warm-started
   from the last), so they share a common ancestor's biases. The *mechanism* (scale-invariance of
   a multiplicative knob; selectivity from an asymmetric downside) is analytically clean and we
   believe it generalizes, but the *empirical* support is a single lineage with no seed replicates
   and no cross-ancestor warm-start.

3. **No strength claim.** We have no tournament-confirmed strength result for any arm in §6
   (§6.4). We do **not** claim a superhuman, MimicBot-beating, or even tournament-validated agent.
   The human statistics are a behavioral *reference*, not a ceiling, and matching them is *not*
   the same as winning.

4. **Manual loop.** The discovery loop is human-driven; it is slow, subjective in its proposal
   step, and unaudited for confirmation bias beyond the decision ledger. It is exactly the loop
   EA-SEED automates.

5. **Un-discharged hacking audit.** The block k-knobs and the turnover charge are raw event
   bonuses (not potential differences) and can, in principle, move the optimum. We have *named*
   this surface but not discharged it with a potential-shaping rewrite or an anneal-to-zero
   lock-in test.

6. **Comparability caveats.** Training-dashboard rates use curriculum starts and are not directly
   comparable to from-kickoff human numbers; we lean on curriculum-robust *fractions* for the
   central claim and flag absolute rates accordingly.

7. **A disclosed cardinal-rule confound in the experiments.** Despite the rule, the §6 arms held
   `ball_gain=0.05` (a D147 outcome-based violator) active rather than zeroing it or converting it
   to a declaration-time pickup/pass EV. It was *constant* across all four arms, so it is unlikely
   to drive the *relative* dice-mix deltas, but the economy tested is not the fully clean economy
   the methodology prescribes, and a clean replication is owed.

What survives these caveats is, we think, still worth reporting: a fast deterministic engine and
EV oracle that make decision-time reward shaping *implementable*; a clean formal statement of the
cardinal rule with an empirical demonstration that violating it (realized-injury shaping) fails;
and a mechanistically-explained behavioral finding — upside scaling is scale-invariant on
selectivity, downside pricing is what reweights the mix — that is general to reward shaping.

---

## 8. Future work

- **From-scratch reproduction gate.** Make cold/BC-init reproduction (≥2 seeds) the graduation
  criterion for any discovered reward, per the warm-start-bias guard. This is the single most
  important missing experiment.

- **Automate the loop.** Replace the human proposer with EA-SEED-style LLM weight proposal over a
  structured {observed, human-ref, delta} + per-knob-contribution report, gated by a
  cost-aware sampler (PufferLib Protein) or evolutionary bilevel reward shaping (GERS, CMA-ES
  outer / warm-probe inner, human-stat distance as the scalar objective). Derivative-free only —
  no gradients flow through the discrete C engine.

- **f-IRL knob calibration.** Fit a linear-in-φ reward over the existing pre-dice EV features so a
  policy reproduces human moments, offline on the frozen corpus, then anneal in — replacing hand
  -tuning of *weights* while keeping the decision-time-EV structure and interpretability.

- **Potential-shaping audit and anneal-to-zero lock-in.** Re-express raw-bonus knobs as potential
  differences where feasible (free optimum-invariance), and decay shaped weights to zero over the
  final curriculum, requiring strength-vs-frozen-anchors to hold — the cleanest single lock-in
  validation.

- **Human-likeness regularizer.** Add a decaying KL-to-BC term (AlphaStar/piKL) as a policy
  regularizer (no reward-laundering risk) to pull play toward the human prior without touching
  the EV reward.

- **Strength grounding.** Fix the native-checkpoint match path and run from-kickoff tournaments
  against frozen archetype-diverse anchors (and ideally a scripted reference bot) so behavioral
  reads can be reconciled against an absolute strength signal — and add the EvalStop /
  sign-pair-logging Goodhart guards to every arm.

---

## 9. Conclusion

We presented a system and a methodology for *reward discovery against a human behavioral
distribution* in a fast, deterministic Blood Bowl simulator. The system — a deterministic
injectable-dice C11 BB2025 engine with a closed-form EV oracle, a ~860K-SPS PufferLib native
binding, information-parity observations, and a replay-anchored 7-layer validation — makes
decision-time reward shaping implementable and makes a short-probe discovery loop tractable. The
methodology centers on a single design constraint, the **cardinal rule**: price the declared
action's pre-dice expected value, never the realized post-dice outcome. And the central empirical
finding is a clean, mechanistically-explained lesson about the *structure* of reward shaping:
scaling the magnitude of an upside-only knob is scale-invariant on action selectivity (it inflates
volume, including bad actions), whereas pricing the asymmetric *downside* (a net-EV turnover
charge) is what shifts the action mix toward the human distribution — more than halving the
unfavorable-block fraction while scoring and advancement held. The finding *suggests a general
design principle* — change a mix by pricing the bad action's downside, not the good action's
upside — supported here by mechanistically-interpretable single-lineage evidence rather than a
controlled multi-seed study. We are deliberately conservative about scope: these are behavioral
and methodological results from single-seed, single-lineage, warm-started reads, with one
disclosed cardinal-rule confound (`ball_gain`) held constant across arms, and without
from-scratch validation or a tournament-confirmed strength claim. The contribution is the engine,
the cardinal-rule methodology, and the dice-mix finding — and a clear, honest map of the
validation work that remains.

---

## References

- Abbeel, P., Ng, A. Y. (2004). *Apprenticeship Learning via Inverse Reinforcement Learning.*
  ICML 2004.
- Afonso, A., Leite, I., Sestini, A., Fuchs, F., Tollmar, K., Gisslén, L. (2025). *Self-correcting
  Reward Shaping via Language Models for Reinforcement Learning Agents in Games.* arXiv:2506.23626.
- Devlin, S., Kudenko, D. (2011). *Theoretical Considerations of Potential-Based Reward Shaping
  for Multi-Agent Systems.* AAMAS 2011 (arXiv:1401.3907).
- Fu, J., Luo, K., Levine, S. (2017). *Learning Robust Rewards with Adversarial Inverse
  Reinforcement Learning* (AIRL). arXiv:1710.11248.
- Gao, L., Schulman, J., Hilton, J. (2022/2023). *Scaling Laws for Reward Model Overoptimization.*
  arXiv:2210.10760 (ICML 2023).
- Ho, J., Ermon, S. (2016). *Generative Adversarial Imitation Learning* (GAIL). arXiv:1606.03476
  (NeurIPS 2016).
- Jacob, A. P., Wu, D. J., Farina, G., Lerer, A., Hu, H., Bakhtin, A., Andreas, J., Brown, N.
  (2022). *Modeling Strong and Human-Like Gameplay with KL-Regularized Search* (piKL).
  arXiv:2112.07544.
- Justesen, N., et al. (2018). *Automated Curriculum Learning by Rewarding Temporally Rare
  Events.* arXiv:1803.07131.
- Justesen, N., Uth, L. M., Jakobsen, C., Moore, P. D., Togelius, J., Risi, S. (2019). *Blood
  Bowl: A New Board Game Challenge and Competition for AI.* IEEE Conference on Games (CoG).
- Ma, Y. J., Liang, W., Wang, G., Huang, D.-A., Bastani, O., Jayaraman, D., Zhu, Y., Fan, L.,
  Anandkumar, A. (2023). *Eureka: Human-Level Reward Design via Coding Large Language Models.*
  arXiv:2310.12931 (ICLR 2024).
- Manheim, D., Garrabrant, S. (2018). *Categorizing Variants of Goodhart's Law.* arXiv:1803.04585.
- Ng, A. Y., Harada, D., Russell, S. (1999). *Policy Invariance Under Reward Transformations:
  Theory and Application to Reward Shaping.* ICML 1999, 278–287.
- Ni, T., Sikchi, H., Wang, Y., Gupta, T., Lee, L., Eysenbach, B. (2020). *f-IRL: Inverse
  Reinforcement Learning via State Marginal Matching.* arXiv:2011.04709 (CoRL 2020).
- Pezzotti, N. (2021). *MimicBot: Combining Imitation and Reinforcement Learning to win in Bot
  Bowl.* arXiv:2108.09478.
- Suárez, J. (2024). *PufferLib: Making Reinforcement Learning Libraries and Environments Play
  Nice.* arXiv:2406.12905.
- Usaratniwart, E., Gao, X., Ong, M., Akimoto, Y. (2026). *Evolutionary Bilevel Reward Shaping for
  Generalization in Reinforcement Learning* (GERS). arXiv:2606.16236 (PPSN 2026).
- Vinyals, O., et al. (2019). *Grandmaster level in StarCraft II using multi-agent reinforcement
  learning* (AlphaStar). Nature 575, 350–354.
- Wiewiora, E. (2003). *Potential-Based Shaping and Q-Value Initialization are Equivalent.* JAIR
  19, 205–208 (arXiv:1106.5267).

---

## Appendix A — Claim → evidence map

Each central claim is traceable to a numbered entry in the project's decision ledger
(`DECISIONS.md`), which is the primary empirical record. This map is intended to make
overclaiming detectable.

| Claim (paper §) | Evidence (ledger) | Status |
|---|---|---|
| Cardinal rule; realized-injury shaping fails (§5.1) | D147 (audit, 5 terms), D148 (attrition A/B: blocks 6.8→7.8, tie) | refuted hypothesis → rule codified |
| `ball_gain` held active across §6 arms (§5.2, §6) | D147 (classifies violator), D156 (violence keeps ball_gain 0.05), D159 (netblock zeroed only k_seq) | disclosed confound |
| violence: volume/tds/advancement up, mix flat (§6.1) | D157 (blocks 5→15.7, tds 0.35→1.43, fwd_adv→6.97; 2d 0.45→0.49, 2d-red 0.10→0.11) | single-lineage read |
| violence2: doubling → more volume, worse mix (§6.1) | D158 (blocks 15.7→21.1, 2d-red 0.11→0.13) | single-lineage read |
| netblock: net-EV halves 2d-red, scoring holds (§6.2) | D159 (early 0.12→0.07-0.08), D160 (cap 0.12→0.056, 2d→0.543, tds 1.43→1.46) | single-lineage read |
| Native-CUDA NaN: 5-iteration diagnosis, fix held (§6.3) | D151/D152 (wrong-path/wrong-layer), D153 (native `_C` identified), D154 (pufferlib.cu/muon.cu fix, fork f14b71c), D156-D160 (clean runs) | resolved |
| obs-v4 information-parity rationale (§4.3) | D46/D52 chain; obs-v4 spec (2782 B, planes A1/A2/B) | design, partially validated |
| Human block-mix 2d:2d-red ≈ 46:1 (§2) | human-baseline.json (0.7745/0.0169 = 45.8) | measured |
| No from-scratch / no tournament strength (§6.4, §7) | D157/D160 (tournament deferred: native-bf16 convert path broken); no cold-init gate run | **acknowledged gap** |

## Appendix B — Codex review and resolutions

This draft was reviewed by Codex (GPT-5.5, high reasoning effort) against `DECISIONS.md`. The
review and the resolutions (all incorporated into the body above):

1. **`ball_gain` confound not disclosed.** The experiment economy was framed as cardinal-rule
   clean, but `ball_gain=0.05` (a D147 outcome-based violator) was held active across the §6
   arms. → Added to the §5.2 economy table as an explicit violator, disclosed in §5.1 and §6, and
   added to the Appendix A claim map and the limitations.
2. **Abstract "doubling 5→21" was imprecise.** The 5→15.7 jump came from the *first* violence
   change, not the doubling. → Corrected to "5→15.7→21.1" in the abstract.
3. **"Clean, controlled demonstration" / "generalizes" overclaimed for one lineage.** → Recast
   throughout as "mechanistically-interpretable single-lineage evidence" / "suggests a general
   design principle" (abstract, contributions §1, §6.1, §6.2, conclusion).
4. **"Bad blocks" ignored the carrier-pressure caveat.** A 2d-red on the carrier is often correct.
   → Changed to "unfavorable-dice blocks" and added the stratification caveat (§6.1, §6.2).
5. **PBRS / hack-immunity overclaimed, especially for possession.** Possession is an annuity, not
   a potential difference; clipping can break telescoping invariance. → Removed possession from
   the PBRS guarantee, weakened distance terms to "potential-*like* (intended)", dropped
   "hack-immune by construction" (§5.2).
6. **NaN chronology garbled.** The threat arm + control exposed the bug; violence/netblock
   *validated* the fix; the diagnosis was 5 iterations (3 wrong path + 1 wrong layer). → Rewrote
   §6.3 with exact chronology and per-arm step budgets.
7. **System-validation language too final.** "Implements the ruleset" / "gated" overstated given
   the D146 Blitz-legality bug validation missed. → Softened §4.1 and §4.4 to "substantial
   implementation … under active use"; noted the Blitz bug; flagged a per-layer report as future
   work.
8. **Statistics lacked provenance/uncertainty.** → Split §6.1 into Table 1 (provenance + per-ep
   metrics, same units) and Table 2 (comparable fractions); added warm-from, step budgets,
   denominator, and an explicit "no seed replicates → no CIs" statement; defined "curriculum
   episode".
9. **Table invited invalid agent-vs-human comparisons.** → Moved human absolute per-game rates to
   an orientation-only footnote; kept human only beside the comparable fractions.
10. **"Plausibly-near-optimal" unjustified.** The corpus is not skill-filtered. → Changed to
    "large, strategically meaningful behavioral reference, not an optimality certificate" (§1, §2).
- **Related-work gaps.** → Added Abbeel & Ng (feature-expectation matching), GAIL (Ho & Ermon) and
  AIRL (Fu et al.) citations, an occupancy/moment-matching sentence (SMM/GMMIL/IQ-Learn/CSIL),
  multi-agent PBRS (Devlin & Kudenko), and a self-play non-transitivity / evaluation nod.
- **Clarity.** → Fixed "five terms" → "four hard violators plus one qualified regularizer",
  de-anthropomorphized "dice-superstition", standardized "2d-red" notation (defined in §2),
  changed "leaves +EV" → "can leave +EV", and added "not to conclude improved play" in §6.4.

Codex's "claims to keep" — the no-strength-claim language, the central D156–D160 story recast as
single-lineage-plus-mechanism, and the native-CUDA lesson — are retained as written.
</content>
