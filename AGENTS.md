# bloodbowl-rl agent guide

This repository trains a non-LLM agent for Blood Bowl Third Season Edition
(BB2025) with a deterministic C engine, a PufferLib environment, PPO/self-play,
and behavioral cloning from FUMBBL replays.

`CLAUDE.md` holds the current program state, the verified hard-won facts, and the
footgun list — read it, and don't duplicate it here. This file holds the durable
contracts: how a causal experiment must be run, what the rules and reward
semantics are, how to build, and how to verify.

## Read this first

1. The tail of `DECISIONS.md` — the chronological program ledger. Later entries
   amend earlier ones without deleting history.
2. For reward, replay, or training work,
   `docs/reward-and-replay-audit-2026-07-09.md` (D177–D192 summarize its durable
   conclusions).
3. The relevant project skill under `.claude/skills/`: `training-experiments`
   (runs, A/Bs, checkpoints, metrics), `fumbbl-data` (replays), `bb-rules` (any
   rule or strategy claim), `puffer-env-dev` (binding, patches, builds),
   `bb-validation` (engine verification), `fleet-ops` (host discovery, isolated
   checkouts, process safety, launches, artifacts — live hosts must be
   rediscovered; the old four-box table is historical).

When sources disagree: the current user request, then this file's verification
rules, then the newest applicable `DECISIONS.md` entry. Older prose is historical
evidence, not a current default. No reward configuration is production-promoted;
R0 (`puffer/config/rewards/r0_full.json`) is the next-stage experimental baseline.

## Experimental contract

For any causal comparison:

- **Change one declared factor.** Freeze source, installed environment, Puffer
  patches, config, warm checkpoint, pool, backend, optimizer, seeds, run order,
  and evaluation policy unless the factor explicitly includes one of them.
- **Pair the seeds.** Two seeds and scripted bots are descriptive screening
  evidence, not a confidence interval, a learned-opponent result, or grounds for
  promotion.
- **Use a complete canonical reward manifest** and validate its hash. Never rely
  on launcher inheritance or omission semantics: an omitted field and an explicit
  zero are different rewards.
- **Record hashes** for source/config/module/Puffer patches, warm checkpoint,
  opponent pool, reward manifest, plan, result, and final checkpoint.
- **Require real completion, not a final Steps line:** explicit train/eval phase
  telemetry, the requested number of completed full games, a final cumulative
  reprint, and zero clip, non-finite, engine-error, demo, and fallback counters.
  The acceptance floor equals the explicit request and must not depend on
  vectorized overshoot. Reject an arm that fails integrity; do not average it in.
- **Detection is fail-fast and live**, not an end-of-run audit: the engine aborts
  on the first support/decode defect and `tools/live_integrity_guard.py` kills the
  trainer on the first bad hard-integrity panel (details in `CLAUDE.md`). A
  repaired runtime gets a disposable 50M-step canary before a long causal budget;
  never use that canary as a warm start or an accepted result.
- **Terminal steps:** preserve explicit objective reward (TD) and result utility,
  but do not let incidental action/board shaping co-stack with the terminal
  result. Keep deliberately episode-terminal terms separately visible to clip
  telemetry.
- **Reward-component reports** use the team-0/home learner perspective, not the
  sum of both agents (zero-sum terms would cancel), and must reconcile against
  raw and post-clamp `episode_return`. The ledger diagnoses emitted reward; it
  does not validate a component or authorize promotion.
- **Evaluate kickoff starts** with `demo_reset_pct=0`, both sides/orientations,
  W/D/L, TD for/against, common-seed paired differences, and held-out opponents.
- **Do not compare historical curves numerically** across reward-semantic,
  counter, observation, backend, or replay-distribution fixes without a bridge
  eval.
- **Write each accepted finding as one atomic `DECISIONS.md` entry** before
  changing a default. Append amendments; never rewrite old entries.

Audited path: `tools/run_reward_screen.sh`, `tools/reward_manifest.py`,
`tools/analyze_reward_screen.py`, `tools/run_reward_candidate_transfer.py`,
`tools/run_reward_learned_transfer.py`. A long final confirmation uses the
`paired-final` profile (reference/candidate at seeds 42, 43, 44) and still
requires prior candidate-transfer evidence. For unattended multi-day work use
`tools/experiment_queue.py` with `training/systemd/experiment-queue@.service`; see
`CLAUDE.md` for its operational rules.

## Replay and BC contract

- Filter by the embedded replay `rulesVersion`. Filenames, directory names, and
  pair-shard presence are not edition proof, and BB2020 records must never enter
  BB2025 training or evaluation. Current inventory and the strict allowlist are in
  `CLAUDE.md` and `runs/replay-audit-20260713/`.
- **Split by replay ID, never by record**, so no match's actions appear in both
  train and validation.
- Use the bounded streaming loader in `training/bc_pretrain.py`; do not restore
  the all-in-memory loader. Preserve header/ID validation, memory-map LRU, owning
  minibatches, and batchwise evaluation.
- Replay-first sampling removes long-shard dominance; it does not repair opening
  censorship. The corpus is sharply prefix-censored and by itself insufficient for
  second halves, late drives, stalling, comeback play, or rare actions. The next
  sampler should stratify replay, roster/matchup, drive depth, and action family
  with explicit setup/opening caps and grouped metrics.
- A BBS1 match-size/fingerprint match proves build compatibility, not record
  integrity. Keep the validator split: scenario scanners and fresh-turn writers
  call `bb_state_bank_boundary_valid`; production reset admission and continuation
  canaries call `bb_state_bank_resumable_valid`. Before either shape enters reset
  selection it must have bounded procedure/team/enum/skill indices,
  bidirectionally consistent grid/player coordinates, and a valid ball state. New
  bank writers and readers fail closed on malformed raw snapshots.
- Never use replay outcomes as action-quality labels, and never infer unseen
  continuation quality from a turn-start snapshot.
- Authored drill states follow `docs/plans/authored-drill-state-bank.md`. Direct
  match/grid/ball/score/turn/procedure surgery is forbidden; group train/dev/test
  by recipe template and keep paired rollout/regret diagnostics out of BBS
  records, observations, rewards, and BC labels.

## Rules and reward semantics

- Implement BB2025 only. Read the local rule mirror and May 2026 FAQ via
  `.claude/skills/bb-rules/SKILL.md`; never fill gaps from BB2016/BB2020 memory.
- Every rulebook "may" is policy surface. Do not auto-resolve an optional choice.
- Route every die through `bb_rng`; preserve determinism and injectable scripts.
- A player with PA `-` cannot declare a Pass Action but may still Hand-off.
  `No Ball` players cannot catch, intercept, or receive a Touchback. They remain
  legal Hand-off targets when Standing with a Tackle Zone, but automatically fail
  the required Catch without a catch die; an ordinary Pass may also target their
  square and then Bounce. Keep these in the engine, never as a reward fine.
- **BB2025 Stalling is real.** Snapshot eligibility when the carrier is activated:
  they must then hold the ball and have a scoring path requiring no Dodge, Rush,
  Block, activation gate/Trait, or other die. If they finish still carrying, or
  you voluntarily end the team turn before activating them, roll the
  non-rerollable crowd D6 through `bb_rng`; `D6 >= current turn` uses the ordinary
  knockdown chain. A prior Turnover and a completed Pass/Hand-off that transfers
  possession are exemptions. The roll is still consumed on turns 7–8 even though
  the crowd cannot act. The finer rulebook choice to forego only that player and
  continue the turn is not yet a distinct action-space surface. Possession is not
  automatically valuable independent of score and clock.
- **Stalling is measured, not inferred.** The engine records every consumed crowd
  D6 — per team, per turn — plus whether the crowd acted and whether it caused a
  Turnover, into a caller-owned `bb_stall_tally` reached through a thread-local
  sink (`engine/include/bb/bb_stall.h`). Never into `bb_match`: the BBS bank
  serializes that struct wholesale. The env attaches its own tally in `c_step`
  and publishes `stall_rolls*`, `stall_crowd_acted`, `stall_turnovers*`,
  `stall_rolls_turnN` and the gate metric `stall_rate_turn1_6*` (stalls per
  completed team turn, turns 1-6) to the machine panel. Do not re-derive stalls
  from distance or end position (footgun 20).
- Reward declarations or settled state, not realized dice luck, except for true
  terminal/objective outcomes. Expected-value shaping can still redefine the
  objective, so it also requires held-out match validation. "Secure the ball,"
  "safe actions first," blocking, screening, and forward movement are contextual
  strategies, not unconditional event coupons. Human-looking block, rush,
  possession, or action rates are diagnostics; tournament/match utility and
  held-out transfer are the decision criteria. Full interpretation in `CLAUDE.md`.
- Order of authority: terminal match utility, then exact discounted PBRS where
  needed, then auxiliary learning targets, then temporary small scaffolds, then
  diverse opponents.

## Source, build, and Puffer discipline

- `puffer/bloodbowl/` is source; the installed snapshot under
  `vendor/PufferLib/.../ocean/bloodbowl/` is what the build compiles. After an
  environment change, run:

  ```bash
  bash tools/install_puffer_env.sh          # also applies the Puffer patch stack
  bash tools/install_puffer_env.sh --check  # drift guard; exit 1 = re-install
  cd vendor/PufferLib
  rm -rf build
  ./build.sh bloodbowl --float
  ```

- The three observation-size sync points, the obs-v4/obs-v5 provenance trap, the
  `.lineage.json` requirement, the `cudagraphs=10` boundary, the fp32-only
  qualification rule, and the D225 CUDA-init-order wrapper
  (`tools/puffer_cuda_runtime.py`, which every CUDA worker and the real trainer
  must enter through) live in `CLAUDE.md`.
- Marginal legality is not sufficient. Rollout must sample only the packed joint
  support and store the selected conditional masks for PPO recompute.
  `illegal_frac` is an integrity counter and must remain exactly zero; decoder
  repair is not an accepted policy path. The environment aborts on the first
  policy tuple outside exact support.
- The installer applies the patch stack in order: exact-action, then
  `puffer_recurrent_eval_state.patch`, then `puffer_frozen_prio_mask.patch`
  (frozen rows need exactly zero priority even at `prio_alpha=0` — zeroed
  advantages alone are insufficient because `0^0 == 1`), then the CUDA
  qualification patch. PPO training requires `reset_state=True` with evaluation
  mode off; persistent-state training is unsupported because recomputation does
  not capture trajectory initial state.
- BBP v4 is the first replay-pair lineage with exact conditional masks and
  canonical inactive-head sentinels (`arg=32`, `square=390`). Do not train a
  current BC/action experiment from v1–v3 pairs, or mix lineages, merely because
  obs/mask dimensions are unchanged.
- Record `_C.__file__`, `_C.env_name`, GPU flag, precision bytes, and the imported
  module hash. A source-tree hash does not prove which extension ran.
- Do not touch a production evaluator/stream process, production reward default,
  or unrelated service unless the user explicitly places it in scope. If BBTV is
  in scope, follow `docs/bbtv-latest-checkpoint.md`.

## Verification and working-tree safety

- Preserve user changes in this dirty working tree. Do not reset, discard,
  commit, push, or deploy unless asked.
- `make test` for the normal engine/environment suite, `make asan` for sanitizer
  coverage after rule/reward changes. Add a focused regression for every confirmed
  semantic defect.
- Run the relevant Python unittest suites for reward manifests/analyzers, replay
  audit/loader, checkpoint conversion, league, and BC behavior.
- Rules changes may intentionally alter goldens; regenerate them only after the
  semantic change is reviewed and understood.
- Report what changed, the exact verification performed, remaining limitations,
  and whether anything was committed, deployed, or promoted.
