# bloodbowl-rl agent guide

This repository trains a non-LLM agent for Blood Bowl Third Season Edition
(BB2025) with a deterministic C engine, a PufferLib environment, PPO/self-play,
and behavioral cloning from FUMBBL replays.

## Read this first

1. Read the tail of `DECISIONS.md`. It is the chronological program ledger;
   later entries amend earlier ones without deleting history.
2. For reward, replay, or training work, read
   `docs/reward-and-replay-audit-2026-07-09.md`. D177–D192 summarize its durable
   conclusions and the subsequent vacation-training decisions.
3. Load the relevant project skill under `.claude/skills/`:
   - `training-experiments` for any run, A/B, checkpoint, metric, or promotion;
   - `fumbbl-data` for replay download, filtering, conversion, or BC sampling;
   - `bb-rules` for any rule or strategy claim;
   - `puffer-env-dev` for the native binding, Puffer patches, eval, or builds;
   - `bb-validation` for engine/rule verification;
   - `fleet-ops` for Tailscale/Vast host discovery, isolated checkouts, process
     safety, builds, launches, monitoring, and artifact transfer. Live hosts and
     routes must be rediscovered; the old four-box table is historical.
4. Treat `CLAUDE.md` as a compact map of hard-won facts, not a substitute for
   the ledger or the July audit.

When sources disagree, use the current user request first, then this file's
safety/verification rules, then the newest applicable `DECISIONS.md` entry and
its immutable artifacts. Older prose is historical evidence, not a current
default.

## Current reward verdict

- No reward configuration is production-promoted by the July audit.
- R0 is the next-stage experimental baseline, not a final reward:
  `puffer/config/rewards/r0_full.json`.
- Distance shaping currently supplies nearly all scoring learnability. Removing
  it collapses TD and match-score progress, but raw `Phi(s') - Phi(s)` is not
  exact potential-based shaping at `gamma=0.995` and increases some adverse-die
  blocking. Keep it only as a scaffold to be made exact or annealed away.
- Removing the combined possession-annuity/ball-gain family (R2) made match
  score worse in all eight paired transfer cells and increased losses and
  opponent TDs in all eight. Do not replace R0 with R2.
- The next causal experiment must decompose the bundle while distance remains
  on: both, possession-only, gain-only, neither; `500M x 2 seeds`.
- The July 13–14 decomposition attempt is rejected under D182: one training
  emission crossed PPO's clamp by exactly `0.015`; the old telemetry cannot
  classify its sign or terminal context. The audit separately confirmed an
  unsafe terminal result-plus-shaping path. Do not analyze or transfer from
  that screen. Correct terminal composition and add phase-split clip telemetry,
  then rerun all arms.
- Do not change production defaults until the survivor passes learned-opponent,
  roster-grid, longer-horizon, multi-seed, and second-ancestry confirmation.
- The corrected `neither` confirmation later failed the frozen mean-performance
  gate (D185). The active vacation queue therefore characterizes R0 only; do not
  switch candidates or describe R0 as promoted. D186 permits one separately
  frozen third-ancestry R0 overflow only after exact primary completion.
- The frozen seed-42 6B curve improves against all four static training banks
  but is non-monotonic and in-pool (D187, with corrected endpoints in D188).
  Select no live/newest checkpoint from
  it. Use the fixed post-run milestone matrix. Near-absent pass/handoff coverage
  remains a future-research requirement. D190 adds per-component emitted-reward
  attribution for future builds, but it is not retroactive: the pinned vacation
  queues predate the ledger and must not be rebuilt or reinterpreted as though
  they emitted it.
- Human-looking block, rush, possession, or action rates are diagnostics, not
  optimization objectives. Tournament/match utility and held-out transfer are
  the decision criteria.

Canonical evidence:

- Screen: `runs/reward-screens/reward-screen-20260709-v1/SCREEN_COMPLETE.json`
- Transfer: `runs/reward-transfer-20260713-v1/ANALYSIS.json`
- Full interpretation: `docs/reward-and-replay-audit-2026-07-09.md`

## Experimental contract

For any causal comparison:

- Change one declared factor. Freeze source, installed environment, Puffer
  patches, config, warm checkpoint, pool, backend, optimizer, seeds, run order,
  and evaluation policy unless the factor explicitly includes one of them.
- Use a complete canonical reward manifest. Never rely on launcher inheritance
  or omission semantics; explicit zero and missing are different.
- Record hashes for source/config/module/Puffer patches, warm checkpoint,
  opponent pool, reward manifest, plan, result, and final checkpoint.
- Require explicit train/eval phase telemetry, enough completed full games, a
  final cumulative reprint, and zero clip, non-finite, engine-error, demo, and
  fallback counters. Reject an arm that fails integrity; do not average it in.
- On an episode-ending step, preserve explicit objective reward (TD) and result
  utility, but do not let incidental action/board shaping co-stack with the
  terminal result. Keep deliberately episode-terminal terms separately visible
  to clip telemetry.
- Reward-component reports use the team-0/home learner perspective, not the sum
  of both agents (zero-sum terms would cancel). Reconcile raw component sum plus
  residual to raw `episode_return`, then reconcile `episode_return` minus signed
  clamp delta to post-clamp return, within float tolerance. A nonzero clamp
  delta is independently an integrity failure even when those identities hold;
  so is any mismatch or non-finite component counter. The ledger diagnoses
  emitted reward; it does not validate a component or authorize promotion.
- Evaluate kickoff starts with `demo_reset_pct=0`, both sides/orientations, W/D/L,
  TD for/against, common-seed paired differences, and held-out opponents.
- Two seeds and scripted bots are descriptive screening evidence, not a
  confidence interval, learned-opponent result, or production promotion.
- Do not compare historical curves numerically across reward-semantic, counter,
  observation, backend, or replay-distribution fixes without a bridge eval.
- Write each accepted finding as one atomic `DECISIONS.md` entry before changing
  a default. Append amendments; never rewrite old entries.

Use `tools/run_reward_screen.sh`, `tools/reward_manifest.py`,
`tools/analyze_reward_screen.py`, `tools/run_reward_candidate_transfer.py`, and
`tools/run_reward_learned_transfer.py` for the audited path. Preserve immutable
manifests and completion records. A long final confirmation uses the explicit
`paired-final` profile: reference/candidate at seeds 42, 43, and 44; it still
requires prior candidate-transfer evidence and is never an adaptive selection.

For unattended multi-day work, use `tools/experiment_queue.py` and the tracked
`experiment-queue@.service` template. Freeze a literal JSON command queue after
the preceding evidence chooses its inputs; do not let a running process invent
branches or promote a reward. Require plan hashes, bounded runtimes, disk,
progress, thermal, artifact, and validator gates. Mark a job `resume_safe` only
when its own immutable runner validates partial/completed artifacts. A halted
job must leave every later job pending. See
`docs/vacation-autonomy-2026-07.md` for the first deployed contract.
Queue commands and environments use typed values: pin immutable files and
directory trees, declare audit-root output paths mutable, and link generated
inputs to an earlier job's recorded success artifact. Long jobs always expose a
progress file; completed evidence drift halts rather than rerunning training.
Every invocation uses a pinned executable followed by a pinned runner; literals
are restricted to numbers, lowercase SHA-256 digests, and long flags.
Build the concrete candidate six-job plan with `tools/freeze_vacation_queue.py`
only after the main paired screen plus scripted and learned transfer all
complete. If the decomposition transfer instead recommends `both` and records
an empty eligible-candidate list, the same freezer's only alternate mode is a
two-job R0 control replication: `control-final` at `12B x seeds 42/43/44` from
each of the two ancestries. It requires `candidate_arm=both`, null learned
inputs, exact rejection evidence, and a source decomposition screen carrying
the complete current config-tree/default-config/nine-file runtime identity.
The transfer must use `both` as reference and evaluate exactly all three
simplifications (`possession_only`, `gain_only`, `neither`). Legacy partial
provenance or a partial candidate matrix cannot authorize the fallback; never
substitute a rejected candidate.
If the already-selected candidate instead completes its paired `1B x 2`
confirmation and fails the unchanged self-play gate, the explicit
`confirmation-rejected-baseline` route may emit the same two R0-only jobs. It
must independently regenerate the failure, match the confirmation's embedded
selection evidence exactly, write a pinned `BASELINE_AUTHORIZATION.json`, and
keep learned inputs null. This is baseline characterization, not
all-candidates-rejected evidence, a candidate switch, or reward promotion.
Every vacation spec names its route explicitly; never infer the route from
`candidate_arm`.
On the candidate route, `tools/vacation_reward_gate.py` must pass both
ancestries before either long final screen can start. The control route has no
candidate gate. PPO screens are not resume-safe; atomic/restart-validating
transfer and validation jobs may be.
Queue-owned reward screens use the frozen wrapper's `ARM_DETACH=0` contract;
never add nested `setsid`/daemonization that could let the trainer escape the
queue job process group and its guards.
During the active vacation preparation and unattended run, append a timestamped
status/finished-work/blockers/next-steps entry to `docs/vacation-progress.md` at
least once per hour. The journal is an operational handoff, never scientific
evidence in place of immutable manifests and completion artifacts.
Use `docs/vacation-operator-runbook.md` for the read-only snapshot,
state-to-action matrix, terminal-halt response, and return-day checklist. It
never authorizes an in-place PPO restart, manual overflow start, or concurrent
evaluation.
If measured throughput leaves the GPU idle before return, the only reviewed
extension is `tools/freeze_vacation_overflow.py`: one unchanged `control-final`
R0 screen from the exact netblock pool-bank ancestry at `12B x seeds 42/43/44`.
It is a separate queue gated on exact successful completion of the immutable
primary plan, both original validators, primary-service inactivity, unchanged
pins, and an idle GPU. Never append the active plan, deploy over one of its
pinned files, start the overflow early, or timer-relaunch existing state.

After an accepted R0 `control-final` screen, use
`tools/run_checkpoint_milestone_eval.py` and
`docs/plans/r0-milestone-evaluation.md` for the predeclared 0/1/2/4/6/8/10/12B
trajectory. Resolve checkpoints by embedded step, hash every selected native
file, and require an exclusive idle GPU with the BBTV follower explicitly
quiesced; the evaluator must remain pending rather than stopping a training or
BBTV process. Keep static-pool dashboard
scores labeled in-pool, historical anchors labeled unseen exact checkpoints
but lineage-connected, scripted bots separate, and the forced roster grid
labeled stratification rather than unseen-roster transfer. The fixed plateau
rule only nominates terminal/plateau policies for more evaluation. It never
changes a reward, active queue, production default, or promotion verdict.

## Replay and BC contract

- Filter by the embedded replay `rulesVersion`; filenames, directory names, and
  pair-shard presence are not edition proof.
- Current exact inventory: 15,347 raw replays; 11,580 BB2025 and 3,767 BB2020.
  The strict non-empty BB2025 allowlist has 9,118 replay IDs and 1,622,231
  joined records. See `runs/replay-audit-20260713/`.
- Never mix BB2020 records into BB2025 training or evaluation.
- A BBS1 match-size/fingerprint match proves build compatibility, not record
  integrity. Preserve the engine-owned validator split: scenario scanners and
  fresh-turn writers call `bb_state_bank_boundary_valid`, while production
  reset admission and continuation canaries call
  `bb_state_bank_resumable_valid`. The latter currently admits only the exact
  fresh-team-turn shape plus the exact five-frame failed non-Rush Dodge TEST
  reroll window described below. Its pending MOVE destination must be exposed
  egocentrically in observation context bytes 9/12 because a reset has no
  preceding STEP history and reroll masks are nonspatial. Before either shape
  enters reset selection it
  must have bounded procedure/team/enum/skill indices, bidirectionally
  consistent grid/player coordinates, and a valid ball state. New bank writers
  and readers must fail closed on malformed raw snapshots. Authored records
  must additionally pass `ad_verify_one_action_continuation` after loading;
  this canonical-action canary proves resumability, not action quality.
- The historical BBS state bank is mixed by source replay: 123 of 15,471
  records come from 42 BB2020 replay IDs. Before any future replay-state
  scenario/curriculum, run `tools/filter_state_bank.py` with the pinned mixed-
  bank and strict-allowlist hashes. Preserve its manifest and selected-ID list;
  do not treat loader compatibility as edition proof. The strict subset is
  still entirely half one and opening-censored, so it cannot supply passing,
  late-game, Stalling, comeback, or reroll-budget coverage by itself.
- Split by replay ID, never by record. Prevent actions from one match appearing
  in both train and validation.
- Use the bounded streaming loader in `training/bc_pretrain.py`; do not restore
  the all-in-memory loader. Preserve header/ID validation, memory-map LRU,
  owning minibatches, and batchwise evaluation.
- Replay-first sampling is the current default because it removes long-shard
  dominance. It does not repair opening censorship. The next sampler should
  stratify replay, roster/matchup, turn or drive depth, and action family, with
  explicit setup/opening caps and grouped metrics.
- Strict-bank S1–S6 outputs are descriptive, overlapping opportunity
  predicates. `S2` is contained in `S1`; `S4` and `S5` are disjoint carrier
  perspectives; `S3` is ordering pressure rather than ordering quality; and
  `S6` is fixed direct-block diversity plus one-move zero-roll assist
  sensitivity. Keep record, distinct-replay, and three-per-replay-capped
  denominators together. Never use replay outcomes as action-quality labels,
  infer unseen continuation quality from a turn-start snapshot, or turn the
  coverage report into a sampler/training input without a separate reviewed
  contract.
- Authored drill states must follow
  `docs/plans/authored-drill-state-bank.md`: initialize a real match, reach
  every capture through legal engine actions, record all actions/dice, then
  reinitialize and reproduce the raw state byte-for-byte with scripted RNG.
  Before serialization, the writer must independently rerun discovery from the
  recipe's configuration-only fields and require full recipe byte identity;
  exact replay of a caller-supplied transcript alone does not prove that its
  declared procgen and game seeds, plus every controller seed actually used by
  that recipe kind, generated the transcript. Unused controller fields must be
  canonical zeroes so inert caller values cannot masquerade as provenance.
  Direct match/grid/ball/score/turn/procedure surgery is forbidden. Group
  train/dev/test by recipe template, keep paired rollout/regret diagnostics out
  of BBS/observations/rewards/BC labels, and require deterministic manifest-last
  publication plus loader and one-action continuation validation.
  The shared BBS1 reset gate admits only the exact `MATCH -> TEAM_TURN`
  boundary and one procedure-specific nested shape:
  `MATCH -> TEAM_TURN -> ACTIVATION(Move) -> MOVE -> TEST(Dodge)` at a failed
  first-step, non-Rush reroll decision. The nested validator recomputes the
  Dodge target, requires real Use/Decline actions and remaining ordinary MA,
  and rejects Rooted or activation-cleared Distracted/Eye Gouged movers, every
  other TEST kind, parent shape, malformed skill bit, or continuation field.
  A legally resolved Rush retains its result in `match.ret` and remains
  deliberately outside this first shape. Tackle suppresses only the Dodge
  skill reroll at the origin; Team Re-roll and Pro availability are independent.
  Scenario scanners must remain on the fresh-turn-only validator. The authored
  writer may use the resumable validator only for the exact F4 pending-Dodge
  recipe kind; F1/F2/F3/F5 remain fresh-turn-only. Do not widen either gate to
  arbitrary decision states. Any later target or
  reroll shape needs its own complete lower-frame validator first. The F1
  proof keeps that boundary: a non-dash-PA, non-No-Ball carrier's private copy
  must reach a standing, tackle-zone-capable, non-No-Ball teammate target
  through legal activation and Pass declaration with zero dice. The ordinary
  raw match still contains its ball carrier; no separate carrier/action/target
  metadata, nested frame, chosen action, or target is serialized or used as a
  label. The F2 proof uses the same boundary and zero-die private activation /
  declaration pattern for Hand-off, but requires at least one adjacent
  catch-capable teammate. A Standing No Ball teammate may remain a rules-legal
  Hand-off target and auto-fail the Catch; a No-Ball-only target set therefore
  does not satisfy the authored F2 opportunity predicate.
  The F5 proof also keeps the shared fresh-team-turn boundary. It requires the
  active carrier to satisfy the engine's exact no-Dodge/no-Rush/no-gate scoring
  predicate, then privately verifies a zero-die activation and Move declaration
  with End Activation still legal. The probe establishes that scoring and
  Stalling are both available; it does not say which is strategically correct,
  apply the Stalling choice, or serialize a path, action, or preference.
  The fixed F4 proof legally reaches the exact nested pending-Dodge window with
  controller seed 1 after 384 decisions and 110 dice. Capture occurs before
  choosing Team Re-roll, Dodge, or Decline: the final recorded action is the
  failed Step, so no pending action or outcome becomes a label. Require full
  rediscovery/replay identity, deterministic writer bytes, mixed-batch
  fail-before-header behavior, production-loader byte identity/masks, and the
  continuation canary. This is one opportunity template, not F4 axis coverage,
  quotas, counterfactual authorization, publication, training, or deployment.
  The first F3 axis expands only the fresh-boundary half-two turn/orientation
  contract: exactly one recipe for each active-side orientation (Home and Away)
  at turns 1 through 8, for 16 cells total. Store the requested turn and active
  side inside the recipe so independent rediscovery binds the cell; reject
  those fields on every non-axis recipe. Do not confuse `BB_TEAM_COUNT`'s 30
  roster catalogue entries with the two active-side orientations. The quota
  validator proves structural coverage only; writer preflight remains the
  seed/transcript/provenance, exact-replay, boundary, and continuation gate.
  The 16 fixed proofs use distinct controller seeds 1000-1015 and pass exact
  writer/reload identity. A 256-seed x 16-cell optimized/sanitized sweep agrees
  on 4,088 captures, 8 clean match ends, and zero unexpected failures. This
  does not cover score, possession, receiving history, material, reroll budget,
  roster, race pair, or tactical quality, and it does not authorize a bank,
  sidecar, manifest, training input, reward change, evaluation, or deployment.
  The first F2 axis likewise stays at the fresh-turn boundary and crosses the
  two active-side orientations with exactly one versus two-or-more legal
  catch-capable Hand-off targets, for four cells total. The shared pure counter
  privately follows the carrier's zero-die legal activation and Hand-off
  declaration after complete raw-boundary validation; it counts catch-capable
  target actions, not rules-legal No Ball auto-failure targets. Store side and
  bucket in the recipe, reject the bucket on every other recipe kind, and keep
  two-or-more explicitly non-exact. The fixed cells use controller seeds 4/2
  for Home one/multiple and 8/13 for Away one/multiple. Matching optimized and
  sanitized 4,096-seed x four-cell sweeps yield 1,246/994/1,189/1,291 captures,
  the complementary attempts end cleanly, and none fail unexpectedly. This is
  opportunity structure, never evidence that Hand-off or any target is the
  right action; marking, receiver identity, score/clock, roster/race, tactical
  quality, publication, training, rewards, evaluation, and deployment remain
  separate contracts.
  The first F1 axis also stays at the fresh-turn boundary and crosses the two
  active-side orientations with an open versus marked ball carrier, for four
  cells total. Classify pressure only after the complete F1 Pass-opportunity
  predicate succeeds, then use `bb_is_marked` on the validated carrier; do not
  replace engine Tackle-Zone semantics with geometric adjacency. Store side and
  pressure inside the recipe, reject the pressure field on every other recipe
  kind, and independently rediscover both. This axis says only that a real Pass
  opportunity exists under two carrier-pressure contexts. It does not choose
  Pass, a receiver, or a target, and it does not establish tactical quality.
  The 4,096-seed-per-cell optimized endpoint sweep yields Home/open 1,323,
  Home/marked 948, Away/open 1,464, and Away/marked 996 exact captures; all
  complementary attempts end cleanly and none fail unexpectedly. The
  ASan/UBSan sweep matches every count with no sanitizer finding.
  Receiver identity/marking, Pass range, interception, score/clock, roster/race,
  publication, training, rewards, evaluation, deployment, BBTV, and the frozen
  vacation queues remain separate contracts.
  The current cross-family composition gate accepts exactly one 26-record proof
  bundle: F1 4, F2 4, F3 16, F4 1, and F5 1. It is order-independent, assigns
  primary family only by exact recipe kind, and reuses the complete F1/F2/F3
  quota validators plus exact F4/F5 predicates. Never call this 4/4/16/1/1
  object balanced, canonical, published, or training-ready. The unchanged
  writer must still rediscover, exact-replay, admit, and continue every record;
  the bundle gate is only structural composition. Metadata sidecars,
  train/dev/test grouping, reports, manifest-last publication, staging, and
  training require separate reviewed contracts.
- The corpus is sharply prefix-censored: it is not sufficient by itself for
  second halves, late drives, stalling, comeback play, or rare actions.
- Correct BB2025 human possession is about `0.474` on genuine team-turn
  boundaries after excluding synthetic observations. Treat it as a diagnostic,
  not a reward target.

## Rules and reward semantics

- Implement BB2025 only. Read the local current rule mirror and May 2026 FAQ via
  `.claude/skills/bb-rules/SKILL.md`; never fill gaps from BB2016/BB2020 memory.
- Every rulebook "may" is policy surface. Do not auto-resolve an optional choice.
- Route every die through `bb_rng`; preserve determinism and injectable scripts.
- A player with PA `-` cannot declare a Pass Action but may still Hand-off.
  `No Ball` players cannot catch, intercept, or receive a Touchback. They remain
  legal Hand-off targets when Standing with a Tackle Zone, but automatically
  fail the required Catch without a catch die; an ordinary Pass may also target
  their square and then Bounce. Keep these rules in the engine, not a reward.
- Reward declarations or settled state, not realized dice luck, except for true
  terminal/objective outcomes. Expected-value shaping can still redefine the
  objective, so it also requires held-out match validation.
- "Secure the ball," "safe actions first," blocking, screening, and forward
  movement are contextual strategies. Do not turn them into unconditional event
  coupons.
- BB2025 Stalling is real. Snapshot eligibility when the carrier is activated:
  they must then hold the ball and have a scoring path requiring no Dodge,
  Rush, Block, activation gate/Trait, or other die. If they finish still
  carrying, or voluntarily end the team turn before activating them, roll the
  non-rerollable crowd D6 through `bb_rng`; `D6 >= current turn` uses the
  ordinary knockdown chain. The finer rulebook choice to forego only that
  player and continue the turn is not yet a distinct action-space surface.
  A prior Turnover and a completed Pass/Hand-off that transfers possession are
  exemptions. The roll is still consumed on turns 7–8 even though the crowd
  cannot act. Possession is not automatically valuable independent of score
  and clock.
- Prefer terminal match utility, exact discounted PBRS where needed, auxiliary
  learning targets, temporary small scaffolds, and diverse opponents—in that
  order of authority.

## Source, build, and Puffer discipline

- `puffer/bloodbowl/` is source; the installed snapshot under
  `vendor/PufferLib/.../ocean/bloodbowl/` is what the build compiles.
- After an environment change, run:

  ```bash
  bash tools/install_puffer_env.sh
  bash tools/install_puffer_env.sh --check
  cd vendor/PufferLib
  rm -rf build
  ./build.sh bloodbowl --float
  ```

- Keep the current observation size synchronized in `bloodbowl.h`, `binding.c`,
  and `training/convert_checkpoint.py`. Checkpoint lineages with different input
  sizes are incompatible.
- Apply the audited Puffer patches in repository order and test them. Important
  patches include the env phase contract, eval episode gate, dynamic metrics-key
  fix, trusted Torch load, and BC/masking changes.
- Record `_C.__file__`, `_C.env_name`, GPU flag, precision bytes, and the imported
  module hash. A source-tree hash alone does not prove which extension ran.
- Never assume the final dashboard line means evaluation completed. Require the
  explicit final phase/status reprint and minimum completed-game gate.
- Do not touch a production evaluator/stream process, production reward default,
  or unrelated service unless the user explicitly places it in scope.
- If BBTV is explicitly placed in scope, follow
  `docs/bbtv-latest-checkpoint.md`: consume only complete manifested
  checkpoints, convert outside the trainer tree, use the isolated float viewer
  build, and retain the static stream as a reversible fallback. During an
  armed vacation overflow handoff, the match server must load the separately
  proven CPU/fp32 `_C`, hide CUDA, and be absent from the exact pinned GPU PID
  parser; hiding CUDA from a GPU-built `_C` only crashes the viewer (D189).

## Verification and working-tree safety

- Preserve user changes in this dirty working tree. Do not reset, discard,
  commit, push, or deploy unless asked.
- Use `make test` for the normal engine/environment suite and `make asan` for
  sanitizer coverage after rule/reward changes. Add focused regressions for every
  confirmed semantic defect.
- Run the relevant Python unittest suites for reward manifests/analyzers, replay
  audit/loader, checkpoint conversion, league, and BC behavior.
- Rules changes may intentionally alter goldens; regenerate them only after the
  semantic change is reviewed and understood.
- Report what changed, exact verification performed, remaining limitations, and
  whether anything was committed, deployed, or promoted.
