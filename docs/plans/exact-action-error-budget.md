# Exact-action fail-fast error budget

Status: implemented and source-verified; live deployment remains gated on the
immutable pre-repair baseline boundary, 2026-07-21

## Selected tranche and why now

D218 makes sampled/executed policy-action identity an exact harness invariant.
The native environment already aborts on the first tuple outside current joint
support, but the long reward-screen wrapper currently evaluates most integrity
counters only after an arm exits and does not include `illegal_frac` in its
zero-budget acceptance set. A scientifically strict final gate is not enough if
a different integrity violation can consume hours before that gate runs.

This tranche separates two meanings of budget:

- **contamination budget:** zero accepted violating transitions or panels;
- **detection/compute budget:** bounded time and agent steps before a violation
  stops the current arm and suppresses every downstream arm.

Zero contamination remains the acceptance rule. The operational error budget
exists to bound wasted compute, not to average rare harness corruption into a
result.

## Error-budget tiers

### Tier 0 — construction and provenance

Before allocating long-run compute, require the installed exact-action source,
generated build header, imported module digest, environment name, GPU flag,
precision, observation ABI, and complete Puffer patch bundle to match the frozen
plan. Budget: zero mismatches; no trainer launch.

### Tier 1 — exact transition invariants

Empty conditional support, support overflow, a sampled tuple outside joint
support, decode rejection, sampled/executed disagreement, malformed head value,
or non-finite behavior probability is a programming error. Budget: zero. The
native/Torch boundary must fail on the first offending transition. A failed
process status prevents result publication and all later arms.

### Tier 2 — live panel integrity

Every complete `PUFFER_ENV_JSON` panel must contain finite zero values for the
frozen hard-integrity keys. A missing, malformed, non-finite, or nonzero field
terminates the active trainer. Metadata-only panels before an episode completes
are consumed but do not reset liveness. The screen and durable watchdog embedded
beside the trainer poll at most every 30 seconds, so the detection budget is one
dashboard-emission interval plus one poll even if the outer screen or SSH session
disappears. Each monitor records its byte offset in an independent state file,
so redundant overlapping polls cannot race; both share one atomic failure
artifact. Truncation or replacement of the log also fails closed.

Initial hard keys:

- `illegal_frac`;
- reward clip/non-finite counters;
- reward-component mismatch/non-finite counters;
- `error_episodes` and `demo_fallbacks`.

These are harness-integrity signals, not noisy gameplay metrics. No statistical
tolerance applies.

### Tier 3 — staged deployment qualification

The repaired runtime does not receive a multi-day budget immediately. At the
post-baseline boundary it must pass, in order:

1. static/install/module provenance with no training;
2. native CUDA construction and graph capture;
3. one-rollout zero-update ratio/log-probability/entropy/gradient smoke;
4. deterministic exact-support full-game smoke;
5. a reward-frozen canary capped at 50M agent steps (about five minutes at the
   current RTX 2070 cadence), with the same live guard and zero hard failures;
6. only then, the paired causal screen.

Failure at any stage preserves its evidence and prevents the next stage. A
canary is disposable qualification evidence, not a warm start or a result cell.
Launch that stage only through the dedicated one-arm profile:

```bash
env -u WARM -u POOL STEPS=50000000 \
  SCREEN_PROFILE=exact-action-canary PREFIX=exact-action-canary-v1 \
  bash tools/run_reward_screen.sh
```

The profile accepts exactly 50M requested steps, freezes R0, seed 42, and one
arm, rejects candidate-selection and legacy warm/pool inputs, uses deterministic
fresh obs-v5 initialization with no frozen banks, and records
`qualification_only: true` in `SCREEN_MANIFEST.json`. Its checkpoint receives a
hash-bound lineage sidecar that makes it permanently ineligible as a warm start
or pool seed.

## Success criteria

1. `illegal_frac` is part of both train/eval acceptance integrity and must equal
   exactly zero.
2. A synthetic nonzero, missing, non-finite, malformed, truncated, or replaced
   live panel fails closed with an atomic reason artifact.
3. The screen monitor stops the current process group on a live failure and
   cannot advance to another arm.
4. Exact-action source failures remain first-transition fatal in native and
   Torch paths.
5. The frozen screen manifest records the guard implementation and zero-budget
   contract, so removing or weakening it changes provenance.
6. Clean historical-format fixture logs used by tests remain readable only when
   explicitly outside the repaired exact-action launch path.
7. A completed arm can be safely reopened after the live silence window: its
   remaining bytes and hard values are revalidated, but a stopped log is not
   misclassified as a silent live trainer.

## Implementation slices

1. Add fail-first parser tests for clean incremental panels and every hard
   failure class.
2. Implement one small incremental log guard with atomic offset/failure state.
3. Invoke it from the reward-screen wait loop and terminate the active arm on
   failure.
4. Add `illegal_frac` and the complete hard-key set to final acceptance.
5. Bind the guard and error-budget declaration into screen provenance.
6. Update D218/agent guidance only after verification establishes the final
   behavior.

## Test and validation plan

```text
python3 -m unittest tools.test_live_integrity_guard
python3 -m unittest tools.test_experiment_contracts
python3 -m unittest discover -s tools -p 'test_*.py'
PYTHONPATH=training python3.11 -m unittest discover -s training -p 'test_*.py'
make test
make asan
bash tools/install_puffer_env.sh
bash tools/install_puffer_env.sh --check
git diff --check
```

Before deployment, run a throwaway process-containment reproduction proving a
guard failure kills the trainer and leaves a nonzero atomic status while the
queue supervisor remains able to record the stopped job.

The source verification completed 2026-07-21: 220 tool tests (2 dependency
skips), 27 training tests (1 dependency skip), the 442-test native suite, and
the ASan/UBSan suite passed. Fable's analyze-only review found no P0-P2 path that
could accept a violation, advance a later arm, or leave trainer compute alive;
it found one fail-closed recovery defect, now fixed by the completed-log mode
regression above. The vendored install/build and live process-containment canary
remain deployment-boundary checks because this worktree does not contain the
vendored Puffer checkout and the current production queue is immutable.

## Risks and simplification review

- Do not introduce a second definition of exact support; the guard consumes
  emitted integrity only.
- Do not use approximate float thresholds for integer-derived hard signals.
- Do not repeatedly parse the whole log; preserve an inode-bound byte offset.
- Do not let a partial final line advance the offset.
- Do not kill an unrelated host process by command-pattern matching; use the
  PID/process group recorded by the launcher.
- Prefer one frozen hard-key registry shared by live and final validation.

## Explicitly out of scope

- Allowing a nonzero exact-action corruption rate.
- Changing rewards, optimizer settings, opponents, or the running pre-repair
  recovery queue.
- Reusing the 50M canary checkpoint as a causal-screen warm start.
- Deploying before the current three-seed baseline reaches its immutable
  boundary.
- Recurrent rollout/recompute state parity, which remains a separate harness
  tranche.
