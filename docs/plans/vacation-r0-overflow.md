# Fail-closed vacation R0 overflow tranche

## Selected tranche and why now

Add one separately frozen, non-promotion overflow queue that can run a single
third-ancestry R0 `control-final` screen at `12B x seeds 42/43/44`, but only
after the already-running primary vacation queue has completed both of its
declared jobs and all of their success artifacts still pass the original
validators.

The primary `72B` queue is healthy and must not be changed. Its first live
129,892,352 learner steps measured about 187K steps/second, making the training
portion roughly 107 hours. Because it started about 24 hours before the user's
six-day absence, it can leave about two days of the full departure/return
horizon unused. One additional `36B` three-seed screen adds about 53 training
hours. Its warm start is the exact `netblock` checkpoint already frozen as bank
2 of the primary static pool, SHA-256
`9964cf4d4c9c2654157e898ff17327732e73c4c85a5883e7d311d8d3baade05e`.
This buys a third ancestry with the unchanged R0 recipe without selecting a new
reward or training a candidate that failed its gate.

## Success criteria

- The running primary plan, state, outputs, service, and process group are never
  edited, stopped, or restarted by this tranche.
- The overflow freezer accepts only the exact
  `confirmation-rejected-baseline` primary plan, its reviewed plan SHA-256,
  main warm, static pool, confirmation rejection, and R0 reward contract.
- The overflow plan contains a validation-only primary-completion gate followed
  by exactly one non-resume-safe `control-final` screen: R0, exact `netblock`
  ancestry, `12B x seeds 42/43/44`, no candidate, transfer, learned anchor,
  reward gate,
  or production mutation.
- The primary-completion gate independently validates the primary plan hash,
  queue ID, terminal `complete` state, exact job order, recorded success hashes,
  and both original success validators. It writes an atomic proof whose own
  validator recomputes the same facts.
- A delayed starter is idempotent and starts the overflow service only when the
  primary service is inactive, its exact completion gate passes, the overflow
  has not already started or terminated, and no GPU compute process is present.
- Premature start, primary failure/halt/drift, wrong plan, missing artifact,
  active primary service, active GPU process, overflow plan drift, or malformed
  state fails closed and cannot reach the PPO screen.
- The overflow queue retains the primary queue's typed commands, file/tree pins,
  capacity floors, progress freshness, runtime bound, sustained thermal guard,
  process-group cleanup, result validator, and BBTV manifested-checkpoint path.

## Implementation slices

1. Reuse the existing, unchanged `control-final` profile and its learner seeds
   42/43/44. Freeze the exact `netblock` pool bank as the only changed factor;
   keep optimizer, pool, environment, reward, evaluation, and integrity settings
   identical to the primary R0 screens.
2. Add a primary-queue completion validator with `--check`, `--write-proof`, and
   `--validate-proof` modes. Reuse `experiment_queue` plan and completed-evidence
   validation instead of duplicating artifact semantics.
3. Add a closed-schema overflow freezer that revalidates the original rejected
   confirmation authorization, pins the primary plan and all runtime inputs,
   and emits exactly the two-job queue.
4. Add an idempotent delayed starter plus tracked systemd oneshot/timer templates.
   The starter is an extra outer gate; the queue's first job remains authoritative
   if the timer or service is invoked manually.
5. Update the vacation autonomy contract, decision ledger, AGENTS/CLAUDE and the
   relevant local training/fleet skill guidance, without weakening the primary
   queue contract.

All implementation and deployment files are additive. No file pinned by the
active primary plan may change in the audit tree before that plan completes.

## Test plan

Add tests before or with each behavior:

- `tools/test_validate_primary_queue_completion.py`: success, running/halted
  primary, wrong plan SHA/queue/job order, missing or drifted result, recorded
  success hash mismatch, proof drift, and validator failure.
- `tools/test_freeze_vacation_overflow.py`: closed schema, exact source route,
  wrong primary hash/evidence/warm/pool/budget, preexisting state/artifact,
  exact two-job output, non-resume-safe PPO, pins, and plan validation.
- `tools/test_start_vacation_overflow.py`: primary active, completion failure,
  GPU busy, overflow already active/running/complete/halted, plan drift, start
  failure, and one successful idempotent start.
- Synthetic end-to-end queue tests: premature invocation halts before PPO;
  exact completed primary produces a validated proof and unlocks only the
  declared screen; interruption of the PPO screen is terminal; later timer
  polls never relaunch it.

Run at minimum:

```text
vendor/PufferLib/.venv/bin/python -m unittest \
  tools.test_validate_primary_queue_completion \
  tools.test_freeze_vacation_overflow \
  tools.test_start_vacation_overflow \
  tools.test_experiment_queue \
  tools.test_experiment_contracts
vendor/PufferLib/.venv/bin/python -m unittest discover -s tools -p 'test_*.py'
bash -n tools/run_reward_screen.sh
git diff --check
```

Also rerun the existing frozen-screen/launcher tests to prove their bytes and
behavior remain untouched, plus the repository's generated/config manifest checks,
engine tests, and
hosted CI. On the RTX host, freeze from the real primary evidence, validate the
exact plan, run synthetic delayed-start failure/success smokes with bounded
dummy jobs, and compare deployed tracked bytes to the merged archive.

## Rollout and validation

Ship through a reviewed PR with fully green CI, merge to `main`, and deploy only
the additive tracked files from the exact merged archive into the artifact-
preserving audit tree. Prove that every file pinned by the active primary plan
is byte-identical before and after deployment. Do not restart the active primary
queue or BBTV. Freeze the real overflow queue only after deployment so every
installed source/config identity is exact.

Install and enable the delayed-start timer only after its tracked template,
watcher config, primary/overflow plan hashes, negative smokes, and singleton
checks are verified. A timer poll while the primary is running must be a no-op.
The first real overflow checkpoint must appear only after primary completion;
BBTV may then follow it observationally at a matchup boundary.

BBTV's match server must use the separately verified CPU/fp32 viewer and be
absent from the exact pinned `nvidia-smi` compute-PID parser. Hiding CUDA from a
GPU-built `_C` is invalid because PuffeRL will fail while moving the policy;
prove the imported module path, `gpu=0`, and a real spare-port WebSocket cycle
before restarting only the BBTV service.

## Risks and simplification opportunities

- Concurrent trainers: require primary service inactivity, exact primary
  completion, no GPU compute PID, and retain a second in-queue completion gate.
- Cross-queue mutable evidence: pin the immutable primary plan and record its
  expected hash; validate mutable state and artifacts semantically at launch
  and again in the queue job rather than pretending they are immutable now.
- Timer retry races: make all non-ready states no-ops, all contradictory states
  terminal errors, and starting/already-started states idempotent.
- Duplicate queue semantics: call `experiment_queue.validate_plan` and its
  completed-evidence validator; do not reimplement path, pin, or success rules.
- Profile sprawl and active pin drift: reuse `control-final` byte-for-byte. The
  third warm ancestry is the single declared experimental factor.
- Statistical interpretation: the new seeds improve replication only. They do
  not rescue the rejected candidate or authorize reward promotion.

## Explicitly out of scope

- Editing, appending, replacing, pausing, or restarting the active primary
  queue.
- Selecting another decomposition candidate or relaxing any threshold.
- Changing R0, optimizer settings, replay/static pool, evaluation target,
  roster, environment, backend, or production defaults. The predeclared third
  warm ancestry is the tranche's only experimental difference.
- Automatically interpreting or promoting the overflow results.
- Running the overflow concurrently with any trainer or after a primary halt,
  failure, interruption, or evidence drift.
