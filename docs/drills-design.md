# Football Practice: the Drill Framework

*Design doc, 2026-06-09. Status: approved concept (Alex: "we should literally run
football practice. Pre set up scenarios/drills"), phase 1 in progress.*

## Why

Every skill this project has actually created came from a **start-state
distribution**, not a reward signal:

- Backplay (D47/D50) taught *finishing* — near-endzone starts → tds.
- Pickup curriculum (D64) is teaching *scooping* — loose-ball starts.
- Ballhawk-as-rewards (pre-D42) taught nothing — reward bribes produced scrum
  standoffs, not skills.

Generalization: **drills**. A drill is what a real coach runs — a pre-set
scenario practiced densely until the skill exists, then mixed into scrimmage.

## Definitions

**Drill** = (start-state distribution, success metric, graduation rule)

Two state-source types:

1. **Predicate drill** — rejection-sample the FUMBBL demo bank at env reset.
   Proven pattern (`demo_endzone_maxdist`, `demo_pickup_maxdist` in
   `puffer/bloodbowl/bloodbowl.h` reset logic). Cost: ~30 lines of C per
   predicate + 1 ini/binding knob. Limited to states that occur in human play.

2. **Authored drill** — *synthesized* scenario. Humans rarely leave the exact
   teaching positions we want (e.g. open-receiver geometries decay before they
   hit the bank). Build them instead.

## The drill compiler (phase 1 core)

No state surgery. The engine is deterministic with **injectable dice and
scripted actions** — the same machinery `tools/bb_lockstep.c` uses to replay
FUMBBL games. The compiler:

1. Takes a drill spec (placements, ball state, turn/half, active team, roster
   constraints, parameter ranges for variety).
2. Drives the engine from `bb_match_init_random`/`init_forced` through a
   scripted setup phase (kickoff + scripted moves with scripted dice) to the
   target position. The engine itself guarantees reachability + legality —
   a state you cannot script your way into is a state that cannot occur.
3. Dumps states through the existing `sd_commit` path into standard **BBS1**
   bank format (16B header incl. `bbe_state_fingerprint()`, 12B record meta +
   raw `bb_match`). Validated by the same loader checks as the FUMBBL bank.
4. Emits N parameterized variants per drill (positions jittered, rosters
   procgen'd) so the policy can't memorize a single layout.

**Drills compile to banks; the env needs zero new code** beyond what the
pickup knob already established. Each drill bank ships to
`vendor/PufferLib/resources/bloodbowl/` and an arm points at it.

Bank-path note: `bbe_state_bank_path` is currently a hardcoded single path.
Phase 1 keeps one-drill-per-arm (matches the fleet pattern — each box runs one
stage). A `demo_bank_path` knob or tagged multi-drill banks + mixture weights
is phase 2.

## Drill library v1 (ranked by measured gap, D61/D63 human baseline)

| # | drill | gap (agent vs human) | source | success metric |
|---|-------|----------------------|--------|----------------|
| 1 | Scoop (pickup) | pickup_success 0.30 vs 4.88 | predicate — **LIVE** (D64) | pickup_success |
| 2 | **Passing** | pass 0.00 vs 1.97 — never passes | authored: carrier + open receiver downfield, turn-8 clock pressure variants | pass_attempts, completions |
| 3 | Cage-crack / sack | no strip game; 2dred gauge can't see skill-package EV | authored: opponent cage at midfield, our blitzer (Wrestle/Tackle/Strip Ball variants) adjacent | opponent carrier drops ball |
| 4 | Two-turn scoring | tds 0.10 vs 2.22 from kickoff | predicate: backplay filter + turn counter near half-end | tds |
| 5 | Sideline surf | surf rewards exist, behavior rare | authored: opponent on sideline lane, our players in push position | surfs_inflicted |
| 6 | Screen / cage formation | carrier exposed on offense | authored: our carrier midfield, defenders incoming; success = carrier safe N turns | possession retained N turns |

## ⚠️ The mix-ratio doctrine (D67 — learned the hard way)

**Drills must be mixed with scrimmage.** The pickup drill at `demo-reset-pct
0.9` (90% drill episodes) produced a drill-locked skill that NEVER deployed
from kickoff, and from-kickoff play regressed on every axis (pickup_attempts
0.714 → 0.000 vs ancestor, equal-treatment eval) — catastrophic forgetting of
game-context behavior. Meanwhile the flagship ladder (backplay → uniform →
kickoff) taught scooping in-context (0.532/game) with no dedicated drill.
Real football practice is ~30% drills / ~70% integrated play for exactly this
reason. Rules:

- **Never run a drill above ~0.5 episode share**; fix-test pickup-s3mix
  (demo-reset-pct 0.5) measures whether 50/50 transfers.
- **Every drill lineage must graduate back to full games** before its skill
  is assessed — drill-context metrics do NOT measure transfer (pickup-s2
  scored ~0.6 attempts/ep in drills while scoring 0.000 from kickoff).
- **Assess transfer ONLY via from-kickoff eval** (eval_game_stats.sh) against
  the lineage ancestor with equal checkpoint treatment (bias round-trip both
  sides; stripping measured harmless, D67).

## Practice schedule (phase 2)

Mixture over drills per episode draw, weights annealed by per-drill success
(struggling drill → more reps, plateaued drill → fewer). Per-drill success
rates in the Log = the **report card**. Manual stage advancement first (the
backplay ladder discipline, D50/D51: small steps, warm-start each stage),
automation only after the manual ladder is understood.

## Relation to obs work

Drills create *experience*; the obs side gives *eyes*. The cage-crack drill
pairs with the proposed P(ball removal | block) plane (obs-v5 candidate:
extend bb_blockev with Strip Ball/Wrestle/Tackle → ball-consequence modeling)
— see the 2026-06-09 discussion: a wrestle-tackle-stripball cage dive into
2-red is HIGH-EV ball removal that knockdown-only planes (A1/A2) cannot
represent. Also split the block_2dred_frac gauge: EV-justified red blocks vs
naive ones.

## Phase 1 deliverables

1. Drill compiler: `tools/drill_compiler.py` (spec → setup script) driving a
   `bb_lockstep --dump-states`-style path, or a dedicated small C tool reusing
   the sd_* machinery. Output: `validation/drills/<name>.bbs`.
2. Passing drill bank (#2) + arm launch when a box frees.
3. Per-drill success metrics already exist in the Log for pass/pickup/surf;
   add "opponent carrier dropped ball by our action" event counter for #3.

## Anti-goals

- No reward for pre-roll EV of removal (double-pays expectation, farmable —
  RL already optimizes EV through outcomes; 2026-06-09 discussion).
- No drill states via direct struct editing (stack/legality risk) — always
  through the engine.
- No automated mixture until the manual ladder is proven (D28: gradual,
  never cold-off; D51: small steps).
