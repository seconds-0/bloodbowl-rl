# Model-facing harness audit — September 4, 2026

The current interface is not yet complete enough to call rule-faithful. Broad
legal-action round trips pass, but the engine still replaces several optional
coach decisions with fixed heuristics. Some observations also collapse states
with different legal-game consequences. More reward tuning cannot recover
choices that never reach the policy.

The review has also found missing mechanics before the decision-window layer:
Chomp and Throw Bomb have no activation declarations, despite their skills
appearing in generated inputs. Bloodlust's source explicitly omits biting and
automatically changes a failed activation to Move. Punt and On the Ball also
lack their required runtime paths. All 108 generated skill/trait IDs now have a source/rules review entry;
this is not equivalent to executable conformance coverage. An earlier sub-audit's claim of no further missing choices was too
broad and is not accepted. Full-roster simulator scores cannot yet be treated
as rule-conformant BB2025 strength evidence.

This report is updated during repair. It distinguishes existing tests and source
inspection from freshly executed witnesses. The current source tree is
`/Users/alexanderhuth/Code/bb-improvement-20260904`; production viewers and
historical checkpoints are untouched.

## What was traced

The audit follows rule trigger → procedure/decision owner → engine legal list
→ three-head projection → packed exact support → conditional sampling → stored
action, mask and log probability → apply/decode → reward and next observation.
The action heads have sizes 30, 33 and 391. The integrated obs-v7 runtime has 2,851 inputs and now passes its own fp32
GPU qualification, including the unchanged eight-bank ratio tolerance. Its
separate CPU viewer completes six natural matches. These are scoped runtime
checks; the complete rules inventory still contains unrepaired mechanics.

Over 100 complete audit games, 14,115,881 enumerated actions passed exact
projection/decode checks across 26,038 decision windows. This is strong evidence
that those enumerated alternatives survive the interface. It says nothing
about a rule choice that never opens a decision window. A separate source audit
and focused CPU tests checked conditional support, physical row permutation,
stored masks/action/log probabilities, and frozen-row exclusion. Actual native
qualification additionally checks recomputed probabilities and state layout.

## Confirmed findings and repair status

| Finding | Why learning is affected | Current status |
|---|---|---|
| Sole eligible interceptor auto-used | Defending coach cannot decline | Explicit candidate/decline source repair; both orientations and pre-choice RNG checks pass. The final combined normal and sanitizer suites pass 616 cases plus writer. |
| Viewer independently selects action heads | Individually legal fields can form an illegal joint action | Exact-support and batch-construction fixes pass seven actual viewer tests. The integrated obs-v7 CPU Match completes six natural kickoff games, 6,550 support checks and all 11 required named integrity counters zero. Native PPO uses a different path. |
| Trickster chooses a destination and cancels the block | Coach cannot decide; destination geometry and continuation also violate current rules | General targeted-action wrapper integrated with owner use/decline, destinations, optional pickup, Rooted/No Ball handling and delayed TD tests. |
| Dump-off selects a teammate and resolves a shortcut | Coach cannot decline/target; normal pass, interception and catch procedures are bypassed | Ordinary pass/interception/catch chain integrated, with use/decline and full Quick Pass targets, durable no-turnover scope, My Ball exclusion and normal immediate TD. |
| Bonus rerolls indistinguishable from ordinary stock | Equal total resources can expire differently at drive end | Engine-valid alias reproduced; real Brilliant Coaching creation/consumption/expiry traced. Drive bonus reroll fields implemented in obs-v7. |
| Loner/Bloodlust target numbers omitted | Equal observed skills can have different success probabilities | Engine-valid aliases reproduced. Generated rosters and both construction paths contain Loner 3+/4+ and Bloodlust 2+/3+. Effective egocentric parameters implemented in obs-v7. |
| Player-specific Forego absent | Coach cannot consume one eligible player's activation while continuing the turn, including its Stalling consequence | Current primary rule and executable legal-list witness confirm the gap; not repaired yet. |
| Scan versus rollout numerical drift | PPO recomputes different action probabilities despite unchanged weights | Same-input attribution and replacement CUDA forward/backward pass fixed tolerances. The combined obs-v7 runtime passes eight-bank qualification with maximum ratio error 9.54e-6 below the unchanged 2e-5 limit. |

Additional rule-confirmed choice gaps are Kick nomination and pre-roll D3/D6
selection; Bribe use after Argue the Call; Brawler die/decline and activation
limits; Diving Tackle and Shadowing user/decline/timing; Lone Fouler
eligibility and reroll/decline; Mighty Blow and Dirty Player allocation;
individual offensive Foul-assist selection; and adjacent Diving Catch attempts.
They remain explicit repair work. The detailed matrix identifies where the
problem also changes timing, eligibility, geometry or dice semantics.

An `ACTIVE` skill label alone does not establish a missing choice. Tackle,
Defensive, ordinary Block assists and defensive Foul assists use compulsory
operative wording. The audit does not propose artificial decline windows for
them. Automatic resolution after a parent already selected a target is also
different from omitting that selection entirely.

## Additional legal-trajectory verification

A subsequent audit entered the implemented targeted windows through ordinary
TEAM_TURN declarations instead of manually pushing their procedure frames.
It found a missing `BB_TA_FROM_BLITZ` context flag for Stab when a declared
Blitz did not require a Rush; the Rush path already set the flag. Root
independently reproduced failures on both orientations and integrated the
minimal context correction. A durable observation regression and the renewed
compiled-runtime gates are in progress. Prior runtime results retain their
pre-correction identity.

The corrected private 15-test matrix covers Block, Blitz, Frenzy second Block,
the five implemented directly targeted Specials, both skill orderings, nested
pickup/Catch/Pass rerolls, genuine inaccurate flight, interception, immediate
Dump-off and delayed Trickster touchdowns, and destination decode/mirroring.
Root independently repeats the normal and sanitizer builds. These are selected
legal trajectories, not exhaustive rules conformance or all possible interactions.
Earlier fixture claims are narrowed: die2 with a tackle-zone penalty was a
fumble rather than inaccurate flight; post-entry skill additions did not prove
a full legal trajectory. The corrected matrix initializes all skills before
play and preserves the rejected/narrower artifacts separately.

## Observation compatibility

The integrated obs-v7 has 2,851 inputs. Existing occupied feature meanings and
offsets stay fixed. Two previously zero scalar slots, columns 814/815, expose
own/opponent drive bonus rerolls; 64 appended columns expose Loner and
Bloodlust parameters in the existing egocentric player-row order. Ordinary
skill identifiers are unchanged. Five further public context bytes describe
the pending targeted action, its flags, material choice state, actor and target.
The wrapper's actor/target use separate bytes so a nested TEST retains its own
tested player's identity in the existing context. The earlier private 2,846-
and 2,849-byte prototypes were superseded before a runtime build or migration
of any historical checkpoint. All new fields must remain visible through
nested procedures without replacing the child procedure's context.

A checkpoint bridge must copy old weights exactly, zero the two repurposed
columns and all appended encoder columns, and record source/destination hashes
and explicit semantic versions. This preserves the old mathematical function
on valid v6 states; changing a GEMM dimension may still alter floating-point
reduction details, so actual forward parity must be measured. The migration is
not permission to silently relabel old checkpoints or rewrite their sidecars.

Old BBP-v4 pairs lack these hidden facts. Padding them with zeros would assert
false game state. Keep them explicitly v6-only, or re-extract from raw replay
commands through the corrected v7 engine and a new header/version. This task
has not reprocessed or mixed the corpus.

## Curriculum coverage is narrower than match coverage

The current state-bank validator requires a decision owned by the active coach
and exact lower MATCH/TEAM_TURN frames. It admits a fresh team-turn boundary or
one tightly constrained failed first-step, non-carrier Dodge reroll. It does
not admit arbitrary paused procedures.

Consequently, almost all optional mid-procedure windows have no direct reset
coverage. They may still occur after legal play from a supported boundary.
This is a curriculum limitation, not proof of corrupt state restoration.
Extending it requires individually typed resumable shapes and adversarial
rejection tests; broadly accepting arbitrary stacks would remove useful
integrity guarantees.

## Acceptance standard for each decision window

1. Check the operative BB2025 trigger and its non-trigger cases against the
   current local rulebook and May 2026 FAQ.
2. Verify that the skill/resource owner receives the choice on both sides,
   including when that coach is inactive.
3. Enumerate decline and every legal player, die, square or subset; prove exact
   projection/decode and reject distinct actions that collide.
4. Execute alternatives with injected dice and verify consequences, resource
   consumption, RNG timing, and exactly-once continuation of the interrupted
   action.
5. Expose the context needed to value the choice, including parameters and
   temporary resources; test egocentric symmetry and stale-context clearing.
6. Reach the window through a legal trajectory from a supported start. Add a
   narrow validated direct-reset shape only if the curriculum needs it.

Passing all currently reachable masks is not completion of this checklist.
Neither a source fix nor a short numerical check establishes a stronger neural
policy. Training/evaluation memory-boundary semantics, held-out match strength,
full-game completion and roster coverage remain separate gates.

## Evidence

- `audit-artifacts/model-facing-audit-20260904/actions/`: round trips and
  omitted-choice witnesses.
- `audit-artifacts/model-facing-audit-20260904/observations/`: alias witnesses
  and initial migration analysis.
- `audit-artifacts/model-facing-audit-20260904/policy/`: source trace and viewer
  witness.
- `audit-artifacts/model-facing-audit-20260904/rules/`: exact optional-rule
  matrix and root native/sanitizer logs.
- `audit-artifacts/model-facing-audit-20260904/final-review/`: hashed coverage
  matrix, Forego witness, roster probe and ABI-consumer inventory.
- `audit-artifacts/rig-stage-4/` and `rig-stage-5/`: same-input numerical
  attribution, raw native derivatives, eight-bank and generic qualification.
- `audit-artifacts/viewer-runtime-smoke-v2-20260904/`: actual Match execution,
  effective config and named native integrity proof; v1 is retained separately.
- `audit-artifacts/model-facing-audit-20260904/integration-v7/`: exact input patches, deeper skill reviews, rejected first runs and combined verification.
- `DECISIONS.md` D298–D305: accepted scoped findings.

## Combined source verification and remaining rule priorities

The integrated source passes 616 native cases (492 engine, 64 reward, 5 contact,
22 state-bank, 33 observation) plus the BBP-v5 writer/diagnostic regression,
both normally and under ASan/UBSan. A separate random-policy standalone
self-test completes 100 episodes with zero self-test failures. These are
correctness checks of the represented rules, not full-BB2025 or strength proof.
The wrapper's Ball & Chain exclusion predicate is tested synthetically; no
real Ball & Chain action exists to exercise it. Chomped clearing also awaits
an actual Chomp condition. Some focused interruption tests start at a manually
constructed wrapper, so complete legal-trajectory coverage remains work.

The deeper source audit identifies a common high-leverage repair family:
Team/skill reroll decisions are missing for Throw/Kick Team-mate and several
direct special-action dice; Pro cannot select an eligible Block die. Correcting
that shared decision flow is more useful than adding a new reward to encourage
those actions. Other common defects include Catch/Sure Hands usage caps,
Leader resource lifetime, forced Juggernaut/Saboteur/Pick-me-up choices,
Secret Weapon send-offs, Animosity timing/keyword handling, and Grab geometry.
These findings have source/rules evidence; most still need failing executable
witnesses before a code change is accepted. The three deeper reports preserve
that distinction. Their listed implemented clauses are bounded inspections,
not exhaustive interaction tests.

Checkpoint migration now rejects a same-sized reordering of action heads and
has a cross-module architecture invariant. The converter test functions are
registered with unittest discovery so importing the module cannot masquerade
as having executed them. Seven converter tests actually execute and pass;
older aggregate logs that imported this module did not run its six function
tests and must not be read as converter evidence.


The later ancillary consumer audit removes four remaining active old-size
launch/pool defaults and adds a shared-default invariant (23 tests pass).
The GPU qualification uses the earlier immutable source snapshot2e08979a…;
that result will not be relabeled as a build of later runner-only edits.
Fresh current-source action statistics cover84,407 windows in100 standalone
episodes: zero distinct-action projection collisions, with548 identical raw
Jump entries. This is enumeration evidence, not evidence that all required
rule alternatives exist or that every episode is a natural complete match.


## Replay extraction is a separate integration gate

The BBP-v5 writer and generic C lockstep action executor can represent the new
choices. The FUMBBL-to-engine mapper currently cannot reconstruct their order:
Dump-off/Trickster skill reports fall through to an unmapped-skill skip, and
pass/pickup handlers cannot open the wrapper's preceding choice windows.
A skip does not advance the engine, so later actions can diverge. The normalizer
also drops dialog records that might carry required choice evidence.

Therefore the writer is format-qualified, but targeted-action replay
extraction is unqualified. Do not infer decline, force a fallback, or relabel
old pairs. First locate actual BB2025 raw examples for every branch, preserve
needed typed dialog fields, implement the mapper's pending-action state and
then test mapper → engine → writer end to end with zero skips and dice drift.
The source-only audit is preserved as
`integration-v7/bb-obs7-replay-adapter-audit-20260904.md` under the audit root.
No corpus re-extraction or new BC training has been performed.
