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

    exposure = P(removal | matchup) * (victim_cost_k / 100) * k_value
             + [victim is carrying] * P(knockdown | matchup) * k_ball

    receiver: -exposure      attacker: +exposure

- P(knockdown), P(removal): closed-form from dice count (ST + assists),
  face-pick rights, Block/Wrestle/Dodge/Tackle interactions, armour with
  MB/Claws, injury bands with Thick Skull/Stunty. Unit-tested against the
  Phase-4 ActionCalculator conformance odds before it ever shapes a reward.
- Carrier term: getting hit while holding the ball is priced by P(knockdown)
  (a knockdown strips the ball even when it doesn't injure), scaled by
  k_ball. "Getting hit with the ball is a double punishment" emerges from
  the two additive terms.
- Suggested scales: k_value = 0.5 (Wardancer-vs-MB-blitzer ≈ −0.08/block),
  k_ball = 0.3.
- Dice outcomes carry ZERO shaping weight anywhere in v2: luck is priced at
  exposure time only. "Right play, bad result" costs the right-play price.

## Experiment grid

- Profile A — pure: win/draw/TD only.
- Profile B — event-realized (v1 knobs): ball/injury/surf/setup/draw.
- Profile C — exposure-EV (v2): setup/surf/draw + exposure charge; no
  realized ball/injury shaping.
- Arbitration: `puffer match` round-robin between best checkpoints of each,
  plus spectator review. Whatever wins, wins.
