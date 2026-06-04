# Reward audit: decision-time pricing, never outcome pricing

Directive (Alex, 2026-06-03): rewards and penalties are evaluated at the
DECISION, never at the dice result, everywhere. This audit classifies every
existing and planned knob against that principle and defines the v2
("exposure-EV") shaped profile.

## The one refinement the audit forced

Charging decision-time EV on **your own dice actions** (pickups, dodges,
passes) creates a passivity bias: the downside EV is charged immediately at
the attempt, but the upside (field position, the eventual TD) is realized
later through the objective. Pricing one leg of the bet and not the other
makes every voluntary roll look bad, even +EV ones. Blood Bowl IS dice; a
policy taxed per roll learns to stop playing.

The resolution: **shaping prices what you LET THE OPPONENT DO TO YOU
(exposure); the critic prices your own gambles.** Your own risky roll already
has a clean consequence channel — failed pickup → drive stalls → no TD — and
the value function propagates that in expectation, which IS decision-time
pricing, learned rather than hand-coded. Exposure has no such offset: the
"upside" of standing somewhere is strategic and flows through the objective
regardless. So exposure is where explicit decision-time charges belong.

This matches every motivating example: basing up = exposure; carrier within
blitz range = exposure; standing in surf range = exposure; feeding the
Wardancer to the MB blitzer = exposure.

## Audit table

| Knob | Class | Verdict |
|---|---|---|
| win +3 / loss −3 / draw −0.5 | objective | EXEMPT — this is the thing being optimized, not shaping |
| TD ±1 | objective (score currency) | EXEMPT — quasi-objective; realized by definition |
| setup done/autofix ±0.25 | deterministic decision (no dice between choice and effect) | COMPLIANT — keep |
| surf taken/inflicted ±0.1 (planned) | deterministic: the push-square CHOICE is the surf; no dice intervene | COMPLIANT — charge at the push choice; the crowd-injury dice afterwards carry no shaping |
| ball gain +0.1 / loss −0.5 | OUTCOME-PRICED — a failed pickup charges the dice result | v2: REMOVE. Opponent-caused ball risk moves into the exposure charge (below); self-caused drops are the critic's job |
| injury inflicted/taken ±0.15 | OUTCOME-PRICED — rewards/charges the armour+injury dice | v2: REPLACE with exposure-EV (below) |
| value-scaled injuries (planned) | outcome-priced | v2: the value multiplier moves into the exposure-EV term |

## The v2 exposure-EV charge

Fires when an opponent DECLARES a block/blitz/foul against your player
(before any dice). Zero-sum transfer (collusion-proof in selfplay):

    exposure = k_kd    * P(knockdown      | matchup, skills)
             + k_value * P(removal        | matchup, skills) * (victim_cost_k / 100)
             + k_ball  * P(ball_dislodged | matchup, skills) * [victim is carrying]

    P(ball_dislodged) is its OWN probability over the skill-transformed block
    tree, NOT a rider on P(knockdown) (Alex, 2026-06-04): Strip Ball makes
    plain PUSHES dislodge (the most common faces — roughly triples dislodge
    odds vs a carrier with no knockdown required); Wrestle converts Both-Down
    into a no-armour mutual takedown (ball out, minimal self-risk); Frenzy's
    mandatory second block (engine: M6) compounds knockdown odds on any push;
    Tackle/Juggernaut/Side Step/Stand Firm transform the tree from both sides.
    The probability engine therefore evaluates the full face-distribution ->
    skill-transform -> outcome-event tree — resolving CHOICE nodes (Wrestle
    use/decline per D29, die picks, follow-ups) owner-optimally, not by
    fixed rule — and emits all three probabilities,
    unit-tested against the ActionCalculator's 281 skill-interaction rows
    (validation layer 2 oracle) before pricing any reward.

    (Alex, 2026-06-04: the knockdown itself is the tactical product — lost
    TZs, a wasted enemy activation, opened lanes — independent of the injury
    lottery. The k_kd term makes a well-chosen safe block positive EV at
    declaration, directly curing the observed never-blocking meta, and
    teaches target selection from both sides of the zero-sum transfer.)

    receiver: -exposure      attacker: +exposure

- P(knockdown), P(removal): closed-form from dice count (ST + assists),
  face-pick rights, Block/Wrestle/Dodge/Tackle interactions, armour with
  MB/Claws, injury bands with Thick Skull/Stunty. Unit-tested against the
  Phase-4 ActionCalculator conformance odds before it ever shapes a reward.
- Carrier term: getting hit while holding the ball is priced by P(knockdown)
  (a knockdown strips the ball even when it doesn't injure), scaled by
  k_ball. "Getting hit with the ball is a double punishment" emerges from
  the two additive terms.
- Suggested scales: k_kd = 0.06 (routine 2d+Block block ≈ +0.03), k_value =
  0.5 (Wardancer-vs-MB-blitzer ≈ −0.08/block), k_ball = 0.3. Per-step sums
  stay far inside the [-1,1] trainer clamp; per-game accumulation is zero-sum
  so it cannot inflate either side's return systematically.
- Dice outcomes carry ZERO shaping weight anywhere in v2: luck is priced at
  exposure time only. "Right play, bad result" costs the right-play price.

## Experiment grid

- Profile A — pure: win/draw/TD only.
- Profile B — event-realized (v1 knobs): ball/injury/surf/setup/draw.
- Profile C — exposure-EV (v2): setup/surf/draw + exposure charge; no
  realized ball/injury shaping.
- Arbitration: `puffer match` round-robin between best checkpoints of each,
  plus spectator review. Whatever wins, wins.
- Orthogonal axis — GAMMA (discount horizon): 0.995 (~200-decision lookahead)
  vs 0.998 vs 0.9992 (~1250), run on the A-vs-B winner. Hypothesis (Alex):
  clock-aware multi-turn setup play (slow team, deep reception, turns 12-16)
  sits at the edge of the 0.995 horizon. Primary metric: TD-by-turn histogram
  split by team speed (dwarf-class late-half scoring rate), secondary: perf/
  Elo. `[sweep.train.gamma]` in config/bloodbowl.ini for Protein sweeps;
  manual grid via tools/train_profile.sh <P> --train.gamma 0.998.
  Extended ladder (Alex): 0.99975 ~= whole-game lookahead; gamma=1 is
  legitimate for episodic tasks — the undiscounted objective IS the true
  one; discounting is a variance-control corruption of it. Known-best
  practice at this scale (OpenAI Five, AlphaStar): ANNEAL gamma upward over
  training — learn local causality under tight credit first, extend the
  horizon as the noise floor drops. Our chained-checkpoint runs fake the
  schedule cheaply: 0.995 -> 0.999 -> 0.99975, each stage loading the
  previous stage's checkpoint.

## Addendum (same session): the sequencing charge

Turn-ordering doctrine ("all safe plays first; risky rolls last; carrier
blocks dead last") is ALSO an exposure — of your own unbanked turn. A
turnover destroys every unspent activation, so a risky roll taken early
exposes the remainder of the turn to your own dice:

    sequencing_charge = P(turnover of this roll) * pending_safe_activations * k_seq

- Charged at declaration; dice-free; zero for risk taken last → no passivity
  bias. Prices mis-ordering, never risk itself.
- pending_safe_activations: unactivated players with a zero-roll action
  available (the R1 predicate, evaluated at the declaration).
- P(turnover): from the declared test's target + reroll availability; block
  pools from the shared probability engine.
- Subsumes memo R1 (its turnover-triggered form violated decision-time
  pricing; this is the compliant version).

Attacker-side target selection (Claws->high AV, MB->high value, blitz
allocation) needs no separate knob: it is the +EV side of the zero-sum
block-exposure transfer.

Profile C (final): setup + surf + draw + block-exposure transfer (zero-sum)
+ sequencing charge. One shared closed-form probability engine, unit-tested
against the ActionCalculator conformance odds.

## Addendum 2: desperation plays (late-half / late-game low-percentage play)

Three layers, no special-case "desperation reward":

1. Sequencing-charge exemption: k_seq = 0 when the team has no further turns
   this half (team-relative counter, not literal turn 8 — kickoff events can
   move it). A last-turn turnover destroys nothing that the whistle wasn't
   about to. Covers one-turn scores / TTM hail-marys.
2. The outcome spread already funds desperation: win +3 / draw -0.5 / loss -3
   means down-late, certain-safe play locks in -3 while any nonzero-chance
   play beats it; tied-late, the +3/-0.5 gap funds going for the win. The
   critic's job is to internalize this arithmetic as state-value curvature.
   Expect late-game risk-taking to emerge even in profile A.
3. Formal/eventual: memo R11 — potential shaping on a FUMBBL-fitted
   win-probability surface. Policy-invariant (Ng et al.); desperation falls
   out of the curvature (P(win) ~= 0 when behind-late, so turnovers cost no
   potential while TDs spike it). Gated on the Phase-4 replay corpus.
