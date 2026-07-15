# bloodbowl-rl agent guide

This repository trains a non-LLM agent for Blood Bowl Third Season Edition
(BB2025) with a deterministic C engine, a PufferLib environment, PPO/self-play,
and behavioral cloning from FUMBBL replays.

## Read this first

1. Read the tail of `DECISIONS.md`. It is the chronological program ledger;
   later entries amend earlier ones without deleting history.
2. For reward, replay, or training work, read
   `docs/reward-and-replay-audit-2026-07-09.md`. D177–D186 summarize its durable
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
file, and require an exclusive idle GPU; the evaluator must remain pending
rather than stopping a training or BBTV process. Keep static-pool dashboard
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
- Split by replay ID, never by record. Prevent actions from one match appearing
  in both train and validation.
- Use the bounded streaming loader in `training/bc_pretrain.py`; do not restore
  the all-in-memory loader. Preserve header/ID validation, memory-map LRU,
  owning minibatches, and batchwise evaluation.
- Replay-first sampling is the current default because it removes long-shard
  dominance. It does not repair opening censorship. The next sampler should
  stratify replay, roster/matchup, turn or drive depth, and action family, with
  explicit setup/opening caps and grouped metrics.
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
- Reward declarations or settled state, not realized dice luck, except for true
  terminal/objective outcomes. Expected-value shaping can still redefine the
  objective, so it also requires held-out match validation.
- "Secure the ball," "safe actions first," blocking, screening, and forward
  movement are contextual strategies. Do not turn them into unconditional event
  coupons.
- BB2025 Stalling is real: crowd-action probability declines by turn and reaches
  zero on turns 7–8. Possession is not automatically valuable independent of
  score and clock.
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
  build, and retain the static stream as a reversible fallback.

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
