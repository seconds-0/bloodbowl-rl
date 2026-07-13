# Threat Annuity — design spec (FOR REVIEW, pre-build)

> **Historical proposal; not an approved reward term or current experiment.** The
> July audit found distance learnability but no production-promotable reward and
> queued possession/gain decomposition first. Any revival must use exact PBRS
> where claimed and pass the immutable held-out transfer gates in `AGENTS.md` and
> `.claude/skills/training-experiments/SKILL.md`.

Alex's design (2026-06-18), after D147 (cardinal rule) + D148 (injury-outcome dead end).
The EV-weighted, zero-sum, decision-time **dual of the possession annuity**: prices the
contest for the ball as a continuous threat field, so the defense is paid for getting in
position to take the ball and the offense is paid for neutralizing those threats.

## The term

At each settled **own-turn-end** (same hook as the possession annuity / R6, gated on
`pre_in_team_turn`), compute the total **blitz-threat on the current ball carrier**:

```
carrier_threat = Σ over enemy players e of:  P_reach(e → carrier) · P_kd(e blitzes carrier)
```

- `P_reach(e → carrier)` = probability `e` can reach a square adjacent to the carrier this
  turn, compounding the per-roll odds along the cheapest path (dodges at e's AG ± Dodge/
  Tackle, GFIs at 2+, accounting for tackle zones). The reachability engine
  (`bb_reach_field_compute`, used by R6/R12) already yields the `(dodges, gfis)` cost to
  every square; convert that cost to a success probability. A **prone/stunned** enemy
  contributes 0 (it cannot blitz; it must spend its activation standing). A **marked**
  enemy has higher dodge cost to leave → lower `P_reach` automatically.
- `P_kd(e blitzes carrier)` = `bb_block_ev` for e's block on the carrier from the adjacent
  square (real block dice from ST + assists at that hypothetical position + skills) →
  `p_def_down`. (Assist geometry: price from current standing pieces; do NOT enumerate
  hypothetical repositioning of e's teammates — keep it O(enemies), per the R6v2a
  fragility discipline.)

**Charge:** `−threat_scale · carrier_threat` to the ball-holding team,
`+threat_scale · carrier_threat` to the defending team. Zero-sum, one measurement per
own-turn-end (≤16/side/game) → unfarmable, exactly like the possession annuity.

## Why this is the right object

1. **Decision-time / cardinal-rule compliant (D147):** every factor is an EV / settled-
   state quantity computed BEFORE any dice — `P_reach` and `P_kd` are probabilities, not
   realized results. No outcome shaping.
2. **Prices knockdown VALUE endogenously (Alex's Q1):** a flat `k_kd 0.03` pays the same
   for decking a backfield lineman and a Gutter Runner one dodge from the carrier. Here,
   knocking a high-threat enemy prone zeroes its `P_reach` term → the offense is rewarded
   by *exactly the threat removed*. The knockdown's value = the threat it eliminated. No
   separate knob, no double-count.
3. **Rewards defensive positioning — the agents' biggest gap:** the defense earns
   `+threat` for every actionable blitz-threat it puts on the carrier (move into blitz
   range, screen lanes). This directly attacks "they don't play defense."
4. **Rewards offensive protection:** the ball-holder earns by reducing `carrier_threat` —
   caging (no adjacent-reachable squares), marking threats (raises their dodge cost →
   lower `P_reach`), or knocking them down. "Interpose / add tackle zones" falls out for
   free because the reachability engine already prices tackle zones.
5. **Reuses existing engines:** `bb_reach_field_compute` (R6/R12) + `bb_block_ev`. O(enemies)
   per turn-end, same budget class as R6/R12.

## Relationship to existing terms

- **SUBSUMES R6 carrier-exposure** (tiered free/1-roll/safe → continuous EV-weighted, and
  symmetric rather than offense-only-penalty). Build = REPLACE `reward_carrier_exposure`
  with this; do not stack (double-count).
- **Distinct from R12 def-threat** (that prices downfield SCORING reach to our endzone, a
  different object — keep separate or revisit later).
- **Complements the possession annuity** (possession = "do I hold it at turn-end"; threat
  = "how contested is it"). Both zero-sum turn-boundary, both objective-class.

## The one caution (D67–69)

Positive reward to the defense risks subsidizing turtling. Mitigation baked into the
formula: it pays only **actionable** threat (`P_reach > 0` means the enemy can *actually*
blitz the carrier this turn) — standing safely far away earns nothing. This is the
opposite of turtling (it rewards aggressive ball-pressure), distinct from the D67–69
"never reward being safe" warning. The canary: contact/blitz rate up, sack rate up, AND
strength up on the ladder — not turtle-draws.

## Open design questions (for the reviewers)

1. **`P_reach` → probability conversion:** the reach engine gives `(dodges, gfis)` cost.
   Compound as `Π P(dodge_i) · Π P(gfi_j)` with skill-adjusted per-roll odds? Cap path
   length at MA + max-rush. Confirm the cheapest-path cost is the right summary (vs
   best-of-several-paths).
2. **Scale + interaction with the clamp:** `carrier_threat` can sum across ~11 enemies;
   bound the charged value (cap like R12's `min(n,4)`) so the zero-sum transfer can't blow
   the [−1,1] per-step clamp when it lands with the terminal/possession rewards.
3. **Carrier-less turns:** if no one holds the ball at turn-end (loose ball), threat = 0
   (or price threat on the loose ball's square?). Default 0 for v1.
4. **Self-play symmetry:** zero-sum per possession means the holder pays and the defender
   earns for the SAME carrier; both teams see both roles as possession alternates. Confirm
   it nets to a real gradient (teaches mark-when-holding / pressure-when-not), not a wash.
5. **Does it replace or coexist with the k-knobs?** The k-knobs price the EV of a SPECIFIC
   declared block; the threat annuity prices the POSITIONAL threat field. Likely
   complementary (k-knobs drive the individual favorable block; threat annuity drives
   getting into position). Confirm no double-count on the carrier-block specifically.
6. **Knockdown value vs `k_kd`:** with the threat annuity pricing knockdown-of-threats
   endogenously, is `k_kd` now redundant / should it shrink? (The threat annuity only
   prices knockdowns of carrier-threats; `k_kd` prices all knockdowns. Decide the split.)

## Build plan (gated on review)

1. `bb_carrier_threat_eval(m, team)` in `bb_reachability.c` (reuse reach + block-EV),
   returning the zero-sum threat value, O(enemies), no RNG.
2. Reward hook in `bloodbowl.h` at the settled own-turn-end (replace the R6 block), capped,
   zero-sum, `reward_carrier_threat` knob (default 0 inert) + telemetry.
3. Tests: prone/marked enemy contributes 0; a 1-dodge fast threat > a 3-dodge slow one;
   zero-sum charge; cap; default-0 inert.
4. Adversarial Opus + Codex review of the design + implementation BEFORE a live arm
   (Alex's standing pattern for reward-economy changes).
5. A/B arm: warm from league9_cap, threat annuity replacing R6, watch contact/sack/
   strength canaries. Build the box with the D146 blitz fix + D147 EV conversions folded
   in (the next build should also drop injury-outcome and price removal-EV in k_value).

---

## FINAL DESIGN (v2, LOCKED 2026-06-18 — supersedes the draft above)

Refined live with Alex. The earlier "Σ over all enemies" was wrong; corrected below.

### The metric — per-enemy threat, EXCESS over the cage-dive baseline

For each enemy `e` vs the current ball carrier:
```
P_reach(e) = compounded P(reach a carrier-adjacent square this turn) along the cheapest
             dodge/GFI path (skill-adjusted per-roll odds, tackle-zone aware via the reach
             engine); = 1.0 if e is ALREADY adjacent (free block, no movement); = 0 if
             prone/stunned/off-pitch (can't act).
P_kd(e)    = bb_block_ev p_def_down for e's block on the carrier from the adjacent square
             (ST + CURRENT standing assists + skills; no hypothetical repositioning).
threat(e)        = P_reach(e) * P_kd(e)
threat_excess(e) = max(0, threat(e) - P_BASELINE)
```
`P_BASELINE` = the "anyone can always do this" cage-dive, computed by the engine with the
SAME functions: a ST3 mover, ONE dodge through 3 tackle zones, then a 2d-red block →
`P(that dodge) * P(2d-red p_def_down)` ≈ 0.15. **Its low value comes from the movement
(dodge) factor** — so a *free block* (P_reach=1, no movement) at the same 2d-red is ~0.30,
i.e. ABOVE baseline. That is correct: any standing enemy adjacent to your carrier is worse
than the unavoidable baseline and must be penalized (you cage so none are adjacent).

### Pooling — rules-correct (one blitz/turn, many blocks/turn)

```
carrier_threat T = Σ over ADJACENT standing enemies of threat_excess(e)   [free blocks, P_reach=1]
                 + MAX over MOVEMENT-reachable enemies of threat_excess(e) [the single blitz]
```
Cap `T` at `T_max` (e.g. 4× a "bad" single-threat unit, sized so the charged transfer can't
blow the [-1,1] per-step clamp alongside terminal/possession rewards).

### The charge — SYMMETRIC positive-positive annuity (Alex), at settled own-turn-end

Mirrors the possession annuity: BOTH sides get a positive for doing their job.
```
T_c = min(T, T_max)
defending team (no ball)  earns:  + k * T_c              # rewarded for projecting threat
ball-holding team         earns:  + k * (T_max - T_c)    # "secured carrier" annuity; full when caged, eroded by exposure
```
Sum = `k*T_max` (constant/turn) → near-zero-sum, unfarmable, like possession. Fires ONCE
per own-turn-end (gated `pre_in_team_turn`), only when a team holds the ball. Offense bonus
is earned only WHILE holding → positively reinforces get-it/cage-it/protect-it.

### The balance — the camping risk + how it's controlled

A too-large `k` rewards never advancing (camp a deep cage, collect the safety bonus). DEFUSED
by the baseline-excess design: a PROPER cage keeps `T≈0` ANYWHERE on the field, so
advancing-in-a-cage keeps (most of) the safety bonus AND gains `dist_endzone` → "caged
advance" dominates camping (same safety, more progress). Residual risk: a midfield cage is
leakier than a backfield one, so advancing into the teeth raises `T` a little. Control:
- `k * T_max` at **possession-annuity scale (~0.03–0.05)** — far below `dist_endzone` (0.2/sq)
  and TD (1.0), so progress always beats camping.
- **`k` is a SWEPT hyperparameter**, not a guess. Start ~0.03.
- **Camping canary (hard gate):** tds must NOT drop; carrier dist-to-endzone must keep
  DECREASING over drives; possession_rate must NOT spike into turtle-draws. If camping
  emerges, halve `k`.

### Build = REPLACE R6 carrier-exposure (do not stack — double-count). Knob `reward_carrier_threat` default 0 inert.
