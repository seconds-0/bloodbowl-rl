# Isolated vacation R0 overflow recovery

## Purpose

Recover useful RTX 2070 time after `vacation-r0-overflow-20260714-v1`
terminally halted at seed 42. The old run completed all 11,999,903,744
rollout-aligned training steps and exactly 10,000 final-policy games with clean
integrity telemetry, but its immutable screen required 10,001 games. D215 fixes
future screens; it does not change the old result.

The recovery is a full rerun, not a continuation. It uses a new root, queue ID,
plan, state, logs, screen manifest, results, and checkpoints. The old audit root
is read-only evidence.

## Frozen shape

- Recovery root: `/home/rache/bloodbowl-rl-recovery-20260719`.
- Queue ID: `vacation-r0-overflow-recovery-20260719-v1`.
- Job 1, `terminal-evidence-preflight`: bounded and restart-safe. Recompute a
  compact authorization proof from the exact old plan/state/manifest/status/
  result/checkpoint and current corrected launcher/helper.
- Job 2, `full-control-rerun`: non-resume-safe ordinary `control-final`, R0
  `both`, netblock warm ancestry, 12B requested steps, learner seeds 42/43/44,
  10,000 final-policy games per seed.
- Runtime: 72-hour job ceiling, 10-minute progress freshness, 30-second queue
  polling, frozen disk/inode/thermal limits, queue-owned process group.
- Service: separately rooted `experiment-recovery-queue@.service`; never the
  audit-root `experiment-queue@.service`.
- BBTV: CPU-only, newest complete manifested checkpoint across the old and
  recovery checkpoint roots, mutable selection/cache in the recovery root,
  observational only. It keeps showing the old final seed-42 matchup until a
  newer complete recovery checkpoint exists.

## Preflight acceptance

`tools/validate_vacation_overflow_recovery.py` accepts only the reviewed old
artifacts and exact semantics:

- old plan SHA-256
  `d90ee01c8c459f599c8601934f545ccb7783261edae3bcb6e9e3878036d37d3e`;
- terminal queue state `halted`, final job failed with exit 1;
- failed screen status at arm `both`, seed 42, zero completed arms;
- exact `control-final` schedule for seeds 42/43/44 and old
  `eval_episodes=10000`, `min_eval_games=10001` contract;
- seed 42 trainer complete, acceptance false, and the only failure exactly
  `insufficient_games` with observed 10,000 and old minimum 10,001;
- all declared train/eval integrity metrics zero;
- exact final checkpoint size/hash and exact screen-manifest linkage;
- no old `SCREEN_COMPLETE.json` and no seed-43/44 result; and
- current launcher/helper still implement the inclusive 10,000-game boundary.

The validator writes a deterministic proof and its success validator recomputes
the same live facts. Any mismatch stops before GPU work.

## Non-authority

The recovery proof does not:

- accept, aggregate, or promote the old rejected result;
- use the old seed-42 checkpoint as a recovery result or warm start;
- edit or restart the old queue;
- select or change a reward, optimizer, pool, environment, roster, or backend;
- authorize milestone evaluation or a production-default change; or
- give BBTV permission to affect training.

## Review, deployment, and start gate

1. Run focused recovery, frozen-screen, launcher, artifact, queue, and contract
   tests plus the full repository suite.
2. Obtain fresh exact-head reviews and green hosted checks; merge before any
   host deployment.
3. Create the separate host root from the exact merged revision. Build/check
   its Puffer environment and copy the exact static pool without touching the
   old audit tree.
4. Write the closed recovery spec, freeze the plan once, record its SHA-256,
   and revalidate every pin.
5. Prove the old audit identities are unchanged, the old/new roots are
   distinct, no trainer or GPU compute PID exists, capacity/thermal status is
   healthy, and BBTV's CPU-only public path is healthy.
6. Install/start only
   `experiment-recovery-queue@vacation-r0-overflow-recovery-20260719-v1.service`.
   Confirm the preflight proof completes before the first trainer appears.
7. Monitor queue state, screen status, current seed/steps, integrity telemetry,
   newest complete checkpoint, GPU health, disk/inodes, and BBTV; append the
   durable progress journal at least hourly.

Any non-resume-safe interruption remains terminal and requires a new human
decision and separately reviewed plan.
