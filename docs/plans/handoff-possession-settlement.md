# Handoff Catch-retry possession settlement

Status: complete; implementation, independent reviews, clean checkpoint, and
all post-checkpoint identity gates green

Base: `db03bcfc5a153291264d6f4872bde4da50bd11cd`

## Problem statement

An ordinary successful handoff is atomic from the policy's point of view and
already preserves team possession. Before this item, a failed handoff Catch
with an available Catch-skill or team re-roll was different:

1. removed the carrier flag with `bb_drop_ball()`;
2. moved the ball to the receiver with `bb_ball_to()`, which marked it
   `BB_BALL_ON_GROUND`;
3. pushed the Catch test, which could stop at a policy-visible re-roll
   decision.

At that decision the transfer had not settled, but the public engine state said
that it had become a loose ball. The Puffer adapter consequently:

- ends the handing team's possession at the receiver;
- increments completed-possession telemetry;
- emits `reward_ball_loss`;
- starts the exact-PBRS fetch regime;
- exposes a ground ball in both egocentric observations; and
- if the retry succeeds, starts a second same-team possession and emits
  `reward_ball_gain`.

This is the handoff analogue explicitly deferred by D235. It is not a rules
legality defect, and it does not affect a handoff that fully resolves inside
one environment step.

## Intended contract

The ball has three settlement categories relevant here:

- `HELD`: settled possession by the carrier's team;
- `ON_GROUND`: settled loose ball;
- `IN_AIR`: unresolved ball transfer/flight, with no carrier and no fetch
  potential.

A handoff enters `IN_AIR` after the original carrier releases it and remains
there through every Catch re-roll decision and any nonterminal Bounce,
Throw-in, or subsequent Catch chain caused by that failed Catch. It settles
only when the complete open-play chain becomes `HELD` or comes to rest
`ON_GROUND`. Leaving the pitch during open play does not settle it: repeated
crowd Throw-ins remain part of the same unresolved chain. Drive/match cleanup
is a separate lifecycle boundary.

This deliberately reuses the existing public value as the adapter's established
"unsettled ball" category. It does not add or reorder an enum value, change
`bb_match`, change any tensor field or size, or introduce a handoff-specific
adapter exception. The enum comment and observation documentation must be
widened from pass/kick flight to unresolved pass/kick/handoff transfer.

Turnover is also settlement-based. No retry decision by itself latches a
turnover. The unchanged active team turns over only when the full chain comes
to rest loose or settles in an opponent's hands; a same-team rebound Catch
continues the turn. `decision_team` may temporarily be the opponent for an
out-of-turn Catch retry without changing `active_team`.

## Scope and non-goals

In scope:

- handoff release through Catch/re-roll and its downstream settlement chain;
- engine state, carrier flags, coordinates, turnover outcome, and legal retry
  surface;
- Puffer possession path/counting, gain/loss components, exact PBRS, and both
  egocentric observations;
- replay-pair lineage, because the changed state is policy-visible;
- documentation and a new chronological decision entry.

Out of scope:

- pass or kickoff behavior already fixed by D235;
- fumbles, knockdown drops, ordinary ground-originated bounces/throw-ins, and
  loose-ball catches;
- Catch/Pro/team-re-roll legality changes;
- action or observation shape changes;
- reward coefficients;
- state-bank admission or restored-state PBRS initialization;
- training, corpus relabeling, checkpoint promotion, or a production launch.

## Watched-fail regressions before production edits

Add or revise every behavior and lineage test below first, run the focused
filters against the base implementation, and record the expected failures.
Behavior cases must fail specifically because a policy-visible retry boundary
is `ON_GROUND`; BBP cases must fail because the base still emits/accepts v5 as
current. Only then edit production behavior or version gates.

### Engine tests

1. Catch-skill retry:
   - handoff receiver fails the first Catch and has Catch;
   - retry action is legal and receiver Pro remains illegal outside its own
     activation;
   - at the decision the ball is `IN_AIR` at the receiver, has no carrier, and
     neither player has `HAS_BALL`;
   - successful retry settles `HELD` on the receiver without turnover.

2. Team re-roll retry:
   - the active team has one re-roll and the receiver has no Catch;
   - the handoff failure exposes `USE_REROLL/TEAM`;
   - the unresolved state and coordinates match the skill-retry contract;
   - use consumes exactly one re-roll and success settles on the receiver.

3. Loner branches:
   - choosing the active-team re-roll consumes it before the receiver's Loner
     gate;
   - a failed Loner gate preserves the original failed Catch, continues the
     unresolved Bounce chain, and turns over only if that chain settles loose;
   - a passed Loner gate followed by a successful retry settles `HELD` without
     turnover.

4. Declined and failed retry:
   - the initial Catch failure exposes a retry decision in `IN_AIR`;
   - declining allows the scripted Bounce to finish;
   - the final empty landing is `ON_GROUND` at the expected square and causes
     exactly the existing handoff turnover;
   - using the only retry and failing it follows the same final loose-ball
     contract;
   - no second re-roll of that same Catch die is offered, while a later
     bounced-ball Catch remains a distinct test that may have its own retry.

5. Same-team rebound:
   - the original receiver fails, the Bounce reaches another active-team
     player with Catch, and that player's first bounced-ball Catch fails;
   - at this second decision the ball remains `IN_AIR` at the rebound player,
     `turnover == 0`, `active_team` is unchanged, and the turn has not advanced;
   - Catch is legal, Pro is illegal for the non-activating rebound player, and
     a retry success becomes `HELD` with no turnover.

6. Opponent rebound:
   - the original receiver fails and the Bounce reaches an inactive-team
     player with Catch whose first Catch fails;
   - `decision_team` changes to the opponent while `active_team`, the turn, and
     `turnover == 0` remain unchanged;
   - Catch skill is legal, but opponent team re-roll and Pro are illegal;
   - retry success settles opponent possession and exactly one turnover;
   - retry failure followed by an active-team recovery must not latch a
     premature turnover.

7. Bounce back to the activating carrier:
   - the receiver fails and the Bounce returns to the original carrier;
   - that carrier fails the bounced Catch and still has
     `BB_PF_ACTIVATING`, so Pro is legal;
   - the Pro 3+ gate and its retry settle correctly on success;
   - a failed gate or failed re-roll resumes the unresolved Bounce chain.

8. Throw-in and touchdown unwinding:
   - a failed handoff Catch Bounces off-pitch, the crowd return lands on a
     Catch player, and their failed Catch exposes `IN_AIR`;
   - cover a final catch and a final empty-ground outcome;
   - an opponent Catch in its scoring endzone latches the pending handoff
     turnover before touchdown unwinds the MOVE parent.

9. Resolution invariant and negative controls:
   - every fully resolved handoff returns to MOVE only as `HELD`,
     `ON_GROUND`, or lifecycle `OFF_PITCH`, never still `IN_AIR`;
   - successful one-step handoff still ends held by the receiver;
   - No Ball auto-failure still ends as the same ground Bounce;
   - pass Catch retry remains `IN_AIR`;
   - a ground-originated Catch/Bounce remains ground-originated.

At every retry decision above, pin no carrier, both relevant `HAS_BALL` flags
clear, exact ball coordinates, exact retry actions, `turnover == 0`, unchanged
`active_team`, unchanged turn counters, and the expected `decision_team`.

### Puffer environment tests

Use an Away-team handoff so both physical and mirrored coordinates are pinned.
Initialize a settled Away possession at the original carrier.

1. Successful original-receiver retry:
   - after the handoff target action, `possessor` remains Away;
   - possession path advances carrier-to-receiver exactly once;
   - completed possessions remain zero;
   - gain/loss reward components and total rewards are zero;
   - fetch distance/potential is inactive for both teams;
   - both observations encode `IN_AIR`, the correctly mirrored receiver
     coordinate, and no carrier;
   - retry success becomes `HELD` by the receiver with no new possession;
   - a later unrelated action cannot replay the transfer.

2. Same-team rebound retry:
   - Away remains possessor through both Catch failures;
   - path adds carrier-to-receiver and receiver-to-rebound exactly once;
   - retry success stays one continuous possession, with zero completed
     possessions, zero gain/loss components, and no turnover.

3. Opponent rebound retry:
   - while Home's Catch retry is pending, Away remains possessor, completed
     possessions stay zero, and no gain/loss component fires;
   - Home's Catch skill is the only non-decline retry source;
   - successful retry ends Away's path at the Home catcher, starts Home's path
     there, increments completed possessions exactly once, emits exactly one
     Away loss and one Home gain, and turns over exactly once;
   - a later unrelated Home action cannot replay the transfer.

4. Declined retry/full-chain loose ball:
   - the retry boundary has the same unresolved assertions;
   - the final Bounce ends the original possession once at the final square;
   - path includes carrier-to-receiver and receiver-to-landing exactly once;
   - exactly one Away loss and no gain are emitted;
   - a later action cannot duplicate settlement.

5. Exact PBRS:
   - explicitly zero every unrelated reward coefficient;
   - release into unresolved transfer emits the existing carry-regime exit
     `-Phi(old carrier)`;
   - both fetch and carry potentials are zero throughout every unresolved
     retry decision;
   - successful same-team retry emits `gamma * Phi(actual new carrier)`,
     including the downstream rebound carrier rather than the intended
     receiver;
   - final ground settlement activates fetch for both teams only then and
     emits each exact `gamma * Phi_fetch(team)` from the zero limbo baseline,
     alongside exactly one Away loss;
   - opponent settlement emits Home
     `gamma * Phi_carry(opponent catcher)`, leaves Away carry at zero, and
     co-fires exactly one Away loss/Home gain;
   - no gain/loss component co-fires on a same-team success.

6. Negative control:
   - an atomic handoff with no policy-visible retry remains one continuous
     possession with the same final metrics.

For every Puffer retry boundary, pin both egocentric observations:

- state, mirrored ball square, and carrier byte zero;
- declared action kind `HANDOFF`;
- top TEST/Catch kind, tested player, and target;
- active-team and decision-team scalars;
- exact conditional retry masks.

The continuous Chebyshev path must be asserted at each boundary, including the
zero-distance retry settlement, and every terminal case must take a later legal
action to prove that count, path, reward, and turnover settlement do not replay.

### BBP lineage tests

Add these before changing any current-version constant:

1. writer emits numeric `v6/2782/454`;
2. extractor accepts exact v6 and rejects exact stale v5 plus wrong-observation
   and wrong-mask v6;
3. streaming CLI and reusable `load_shards`/context paths accept exact v6;
4. exact v5 is rejected by default and accepted only under explicit legacy
   reproduction;
5. v5+v6 is rejected even with the override;
6. malformed v6 cannot fall through the override;
7. malformed historical tuples such as `v5/8/454` are rejected even with the
   override;
8. audit readers report both historical v5 and current v6;
9. the archived Torch loader remains exactly `(1,2,3,4)`, rejects both v5 and
   v6 before its shape-only check, and its launcher names current v6.

## Production implementation hypothesis

Keep the change local to `engine/src/proc_ball.c`:

1. release the original carrier as today;
2. move to the receiver square;
3. mark that ball as `BB_BALL_IN_AIR` before pushing Catch.

The D235 `ball_to_preserving_air()` helper then naturally keeps the unresolved
handoff through nonterminal Scatter/Bounce, Throw-in, and Catch chains.
`bb_give_ball()` settles success as held; the existing terminal empty
Scatter/Throw-in calls to `bb_ball_to()` settle failure as ground.

Do not change `bb_ball_to()` globally and do not special-case handoffs inside
Puffer possession or potential code. Those alternatives risk misclassifying
ordinary loose balls or leaving observation and reward semantics inconsistent.

## Observation and data lineage

`BBE_OBS_SIZE`, `BBE_MASK_SIZE`, action encoding, offsets, numeric enum mapping,
and the operative value dictionary remain unchanged. `BBE_OBS_VERSION` remains
6. `IN_AIR` already means carrierless, non-fetch, unsettled limbo to the
adapter; the old enum examples were too narrow. This change adds a handoff edge
to the transition graph rather than repurposing the byte. The declared HANDOFF
action, nested TEST/Catch context, tested player, active/decision teams, and
legal mask already disambiguate the window from pass and kickoff flight.
Source/module hashes protect checkpoint dynamics, while BBP v6 protects
recorded observation/action data. If `IN_AIR` were instead interpreted as a
literal pass/kick-only ABI meaning, this would require obs-v7; that
interpretation is rejected because it conflicts with the existing Puffer
settlement contract and D235.

The correction is nevertheless visible at a policy decision and changes which
records the lockstep writer can emit. Per the D235 standing rule, mint **BBP
v6**:

- writer emits exactly `v6/2782/454`;
- current extraction and both BC entry paths require exactly
  `v6/2782/454`;
- v5 is historical by default even though its shape and exact masks match;
- explicit legacy reproduction may read one homogeneous, known-valid old tuple
  but may not mix lineages;
- malformed v6 headers must not fall through a legacy-shape path;
- training consumers use an explicit known-tuple allowlist:
  `v1/832/454`, `v2/1612/454`, `v2/2782/454`, and
  `v3|v4|v5|v6/2782/454`; fabricated historical shapes are rejected even with
  the legacy override;
- audit readers recognize v1-v6 without treating old versions as current;
- rename/update the writer regression and Makefile target;
- update CLI/context/producer/CI contract tests and lineage documentation;
- do not relabel any shard; current pairs must be re-extracted.

The rejected historical Torch BC-regularizer remains deliberately frozen on
its pre-v5 formats and must reject v5 and v6 before any shape-only comparison.
Its launcher must require an explicitly supplied archived homogeneous v1-v4
pair directory; it must not point at the current `validation/pairs` directory
or tell users to run the v6 extractor. The malformed archived patch is not
repaired or described as a working current consumer in this item.

After implementation, run a residual search for `v5/2782/454`,
`BBP_CURRENT_VERSION 5`, version allowlists, `pairs_v5`, and comments saying
handoffs remain ground-based. Historical occurrences remain only when clearly
labelled. Update the enum/helper/Puffer comments, writer and renamed writer
test, Makefile, producer, both BC paths and tests, both audit paths and tests,
historical launcher contract, `validation/README.md`, both obs specs,
`AGENTS.md`, `CLAUDE.md`, this plan's evidence, and a new D236 entry without
rewriting D235.

## Validation

After the watched failures and minimal implementation:

1. focused engine and Puffer settlement tests;
2. focused BBP producer/loader/context/audit contract tests;
3. `git diff --check`;
4. full `make test`;
5. full `make asan`;
6. the complete CI-equivalent Python BC/lineage and replay-audit suites;
7. clean install into the pinned PufferLib worktree, install check, standalone
   CPU build, import, and advertised metadata/source hashes;
8. deterministic 100-episode seed-42 FNV twice, compared both for repeatability
   and against D235's `4b8c411c07d0e709` base; equality is permitted if that
   controller never reaches a handoff retry, but the coverage reason must be
   recorded;
9. self-review of the complete diff;
10. independent adversarial final review.

The user explicitly waived the unavailable Kimi Code CLI gate for the
remaining program. No Kimi result will be claimed.

## Acceptance criteria

- Every exposed handoff Catch retry is unresolved rather than loose.
- Same-team success preserves one possession, one continuous path, and emits
  no gain/loss transfer.
- A full chain that finally rests loose settles one completed possession, one
  loss, and the existing turnover.
- A same-team rebound Catch remains continuous; an opponent Catch settles one
  loss/gain transfer and one turnover only when the Catch succeeds.
- Fetch PBRS never activates before settlement.
- Active/decision teams, Pro/Catch/team/Loner retry legality, turnover timing,
  and touchdown unwinding agree with the complete branch matrix.
- Carrier flags, coordinates, legal actions, observations, and reward
  components agree at every policy boundary.
- Ordinary loose-ball, fumble, pass, and kickoff behavior is unchanged.
- Current replay data is unambiguously BBP v6; no v5/v6 mixing or fabricated
  legacy tuple is accepted.
- Full native, sanitizer, lineage, install/build, and deterministic gates pass.

## Implementation and evidence

The production change is intentionally one state transition in
`handoff_advance()`: after release and relocation to the receiver,
`m->ball.state` becomes `BB_BALL_IN_AIR` before Catch is pushed. The existing
conditional relocation helper then preserves unresolved state through
Bounce/Throw-in/Catch chains, while `bb_give_ball()` and terminal raw
`bb_ball_to()` calls retain their existing held/ground settlement behavior.
No adapter special case, reward change, struct-layout change, enum renumbering,
action change, or observation-version bump was made.

Adversarial planning first returned REVISE, principally for incomplete branch
coverage and replay-lineage ambiguity. The revised watched-fail matrix was then
approved before production code changed. Against the exact D235 base:

- the final 15-test engine filter produces 14 failures at the expected
  `ON_GROUND (1) != IN_AIR (3)` retry boundary, while the ground-originated
  negative control passes;
- seven Puffer settlement/reward regressions reproduce the premature
  possession, path, observation, loss/gain, and fetch-PBRS effects, while the
  atomic handoff control passes;
- the new writer/producer/current-loader tests reject the base's v5 current
  lineage and require numeric v6;
- a review-added launcher regression fails because a caller-supplied duplicate
  `--train.bc-pairs-dir` can supersede the directory that was preflighted.

All watched failures pass after the implementation. The engine matrix covers
Catch skill, team re-roll, both Loner gates, decline, failed replacement die,
same- and opposing-team rebounds, opposing retry failure followed by active
recovery, activating-player Pro success and failed-gate resumption, opposing
endzone touchdown unwinding, crowd return to a Catch retry, crowd return to
empty ground, and the ground-originated negative control. The eight Puffer
tests pin both egocentric observations, exact conditional masks, active and
decision teams, continuous Chebyshev paths, completed-possession counts,
gain/loss components, exact carry/fetch PBRS, and no settlement replay on a
later action.

BBP v6 is now the current named semantic lineage at the unchanged
`2782/454` shape. The writer and extractor emit/require exact v6; both BC entry
paths require exact v6 by default; a known-tuple allowlist permits only one
homogeneous v1-v5 lineage under the explicit historical override; malformed
current or historical tuples and all mixtures fail. Audit readers recognize
v1-v6 without granting training authority. The rejected Torch loader remains
frozen at v1-v4. Its launcher now requires an explicitly archived directory,
preflights one homogeneous known v1-v4 tuple, rejects pair-directory
overrides, and places the validated directory last so argparse cannot replace
it. No shard was relabelled, and no local v6 corpus is claimed.

Final validation on the review snapshot:

- optimized native: 476 engine, 64 Puffer reward, 2 contact-bot, 12
  state-bank, 26 observation, and numeric BBP-v6 writer tests, all green;
- ASan/UBSan: the same complete matrix, all green;
- CI-equivalent BC/lineage/producer suite: 90 tests green, including every
  known historical tuple and a fabricated tuple for every historical version;
- replay/reward/tool suite while the engine diff was uncommitted: 200 green, 2
  skipped, with only the three scenario-publication tests correctly refusing
  a tracked engine tree that differed from `HEAD`; after local checkpoint
  `8613dba`, all 205 tests complete successfully (203 green, 2 skipped);
- code generation, reward manifests, shell syntax, and `git diff --check`
  green;
- clean install/check in pinned PufferLib commit
  `9836f0d2e78889c1aaf189c04d161b6fc61a9386` advertises environment source
  `6cb120b67d3d738b59193472ff268b9b904db94fcd9aaa4657407b1e62ed06d1`,
  exact-action source
  `1414c9041d1942bdd049eb257338c3a2df3cf72240015e58e5eab095ff691ca7`,
  `obs-v6/6`, `exact-joint-v1`, CPU, and fp32; the imported module SHA-256 is
  `c2b4c64107463814956f44ef89a1f31be4697386c3f14578c5ee985912fa7567`;
- the final standalone SHA-256 is
  `60109e46e492d17942350f66279a0b6a24c889e8389b5da5db22fc4dcab16df8`;
  seed-42/100-episode FNV repeats as `ea1d720e69f5a491` with 26,251 steps,
  zero illegal actions, and unchanged summary counters. Its move from D235's
  `4b8c411c07d0e709` confirms that the deterministic controller reaches a
  policy-visible handoff-retry trace.

Independent review found and closed the missing handoff-to-empty-Throw-in
branch, failed-Pro resumption branch, launcher override, stale operational
lineage guidance, and stale watched-fail comments. Two pre-existing issues are
explicitly not hidden by this item's acceptance: the engine currently treats
Catch as once-per-player rather than reusable across distinct Catch tests, and
the training reader trusts writer-validated per-record action support after
authenticating a BBP header. They require separate test-first correctness and
input-integrity items rather than expansion of this settlement-state change.

Root self-review traced every production transition and inspected the complete
runtime, lineage, launcher, test, and documentation diff. The final holistic
adversarial review returned APPROVE with no P0, P1, or P2 blocker; a second
independent runtime review reran every native executable, reported no P0/P1
production blocker, and identified a P2 shared-oracle concern in several PBRS
assertions. The representative same-team rebound chain now pins independently
derived literal potentials `0.15`, `0.13`, and `0.1287`; its focused regression
and the refreshed clean-build gates pass. Repetitive branch setup remains a
future behavior-preserving test refactor, not an Item 2 correctness gap. The
checkpoint closeout obligation was the documented rerun of the three
source-identity publication tests; all three pass from committed `HEAD`.

The user explicitly waived the unavailable Kimi Code CLI gate for the
remaining program. No Kimi result is claimed.
