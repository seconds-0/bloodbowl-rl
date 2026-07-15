# RTX 2070 vacation autonomy plan — July 2026

## Objective and boundary

Use the otherwise-idle RTX 2070 for six days of decision-relevant Blood Bowl
reward research without allowing an unattended process to invent experiments,
change production defaults, or continue after ambiguous evidence. BBTV remains
the visual progress surface and follows only complete manifested checkpoints.

This is an experiment queue, not autonomous reward promotion. Every command,
input, output, time bound, success validator, and recovery policy is frozen in
`QUEUE_PLAN.json`; its SHA-256 is copied into `QUEUE_STATE.json`. Changing the
plan after first start halts the queue. A failed job prevents every later job
from running.

For the concise live state/action matrix and return-day commands, use
`docs/vacation-operator-runbook.md`. It narrows operational ambiguity but does
not add recovery or experiment authority.

## The 24 hours before departure

1. Finish and atomically analyze the active `500M x 2` possession/gain screen.
2. Run all four arms through the 32-cell scripted-opponent transfer matrix:
   two training seeds, both available scripted styles, and both team sides.
3. Select at most one simplification candidate for confirmation. This is only
   a routing decision; scripted bots cannot promote a reward.
4. If a candidate is selected, freeze it and run the longer paired `1B x 2`
   confirmation against R0. The preceding four-arm factorial remains the
   interaction evidence; the confirmation spends compute only on the declared
   reference and candidate.
5. Evaluate a candidate confirmation against exactly four frozen learned anchors, with
   the focal policy loaded in both native backend roles. The learned matrix uses
   exactly `4096` games per cell and a separately pinned gate configuration. It
   is a deterministic fixed-stratum gate over the overall mean, each training
   seed, each anchor, each backend orientation, and the worst cell. These are
   repeated strata, not independent replicates: no confidence interval or
   reward-promotion claim is made.
6. Freeze the candidate queue only after self-play, scripted transfer, and
   learned transfer decide its literal checkpoint/reward hashes. If no candidate
   is eligible, freeze the control route only from the exact rejected-candidate
   evidence below. Review, merge, deploy, start, interrupt, and smoke the
   service before departure; only restart-validating jobs are resume-smoked.

If the pre-departure evidence is incomplete or inconsistent, no queue is
started. If the exact decomposition transfer instead recommends `both` and
records an empty eligible-candidate list, the only reviewed fallback retains R0
as the experimental control: the freeze spec uses `candidate_arm=both`, null
learned-transfer inputs, and `final_steps=12B`, and emits exactly two R0-only
`control-final` jobs (`seeds 42,43,44`) from the two frozen ancestries. That is
still `72B` requested learner steps. It does not guess or train a rejected
candidate. The rejecting decomposition screen must carry the complete current
recursive config-tree hash, explicit `default.ini` hash, and exact nine-file
runtime identity. A legacy screen missing those fields cannot authorize the
fallback and must be rerun under the complete contract.

If the decomposition selects one simplification but that exact candidate later
fails the frozen `1B x 2` paired self-play gate, it remains rejected and no
other candidate may be substituted. A separately labeled
`confirmation-rejected-baseline` route may still characterize R0: the freezer
independently regenerates the paired analysis, reapplies the unchanged mean,
per-seed, and TD thresholds, and requires at least one literal failure. It also
requires the confirmation manifest's embedded selection-transfer evidence to
equal the separately validated transfer record. Passing, malformed, wrong-arm,
wrong-budget, or differently selected evidence fails closed. The route writes
a pinned `BASELINE_AUTHORIZATION.json` and emits the same two R0-only
`control-final` jobs at `12B x seeds 42,43,44` from the two frozen ancestries.
It measures long-horizon seed/ancestry variation and creates reusable R0
learning curves/checkpoints; it cannot confirm another candidate, pass a reward
gate, or change production.

## Six-day queue order

When a simplification candidate is accepted, the frozen queue uses the July
audit's priority order:

1. Reproduce the paired `1B x 2` confirmation from the frozen `league9` second
   ancestry.
2. Run the full scripted transfer matrix for the second ancestry.
3. Evaluate both policies against frozen learned anchors in both native backend
   roles, using equal cell weights. Scripted-bot results remain a separate
   stratum.
4. Run a predeclared two-lineage gate job. It succeeds only if both lineages pass the
   non-inferiority and integrity contract; on rejection it halts the literal
   queue for inspection. Only success unlocks the already-declared matched long
   reproduction. There is no dynamic “otherwise” branch.
5. Run `6B` per arm for `{R0, candidate} x {seeds 42,43,44}` from the main
   ancestry, then the identical six-arm screen from `league9`. The third seed
   buys replication rather than spending the same compute only extending two
   trajectories. Together the two final screens contain `72B` requested learner
   steps. At the measured approximately `190K` learner steps/second, the `72B`
   final steps take about 105 hours and the second confirmation about 6 hours,
   before evaluation/transfer/orchestration overhead. This is an expected
   roughly five-day workload, not a hard six-day deadline.
6. Stop cleanly when the declared jobs finish. Unused GPU time is preferable to
   an unreviewed objective, backend, opponent, roster, or replay-distribution
   change.

When every simplification is rejected, the alternate order is exactly two
jobs: main-ancestry `control-final`, then `league9` `control-final`. Each job
trains R0 for `12B x seeds 42,43,44`; there is no second-ancestry candidate
confirmation, transfer, or gate.

When the selected candidate instead fails paired confirmation, the baseline-
characterization order is deliberately identical: main-ancestry
`control-final`, then `league9` `control-final`, each R0 at
`12B x seeds 42,43,44`. The authorization differs, is recorded explicitly, and
must not be described as an all-candidates-rejected result.

Live primary throughput measured about `187K` learner steps/second. Because the
two primary screens may therefore finish before the user's return, one separately
reviewed overflow queue may follow only after the exact primary plan reaches
terminal `complete` and both original screen artifacts still pass their recorded
hashes and validators. The overflow reuses `control-final` byte-for-byte at
`12B x seeds 42,43,44`; its only changed factor is the exact `netblock` warm
checkpoint already present as static-pool bank 2, SHA-256
`9964cf4d4c9c2654157e898ff17327732e73c4c85a5883e7d311d8d3baade05e`.
This adds `36B` and a third ancestry, not another reward candidate. Together the
primary and overflow request `108B`, approximately 159 training hours at the
measured rate before evaluation overhead.

`tools/freeze_vacation_overflow.py` is the only reviewed builder for that queue.
It binds to the exact primary queue ID and plan SHA, its pinned schema-2 spec and
`BASELINE_AUTHORIZATION.json`, the unchanged two R0 configs, the same pool, and
the reviewed netblock bank. Its first job uses
`tools/validate_primary_queue_completion.py` to revalidate the primary plan,
state, pins, job order, success hashes, and original success validators and to
require an empty GPU compute-process list. Only its atomic proof unlocks one
non-resume-safe PPO screen.

The exact queue may be shorter if the repository lacks a verified launcher for
a proposed cell. A new launcher is deployed only after focused tests and a
local/remote smoke; it is never improvised by the running service.

The per-job safety maxima intentionally sum to more than six days: they are
fault guards, not a return-home cutoff. Because the RTX 2070 is reserved and
the user authorized multi-day use, a slowed but healthy declared job may finish
after the nominal vacation window rather than being killed mid-trajectory. The
queue still cannot start undeclared work after its six candidate-route jobs or
two control-route jobs finish.

The second ancestry is the exact `league9_cap.bin` artifact with SHA-256
`359d14caa08f12362f799c4cab4f33301fc9ce2ba3dec85922abe9622670d5f5`;
the freezer rejects a path label or same-size substitute.

## Runtime safety and recovery

`tools/experiment_queue.py` enforces:

- a singleton file lock, immutable plan SHA-256, and a closed schema that
  rejects unknown or misspelled guard fields;
- mutable working/log/status/artifact paths constrained to the audit root;
- an allowlisted minimal base environment and typed command, validator, and job
  environment values: literals are restricted to numbers, lowercase SHA-256
  digests, and long flags; all other strings live in a pinned runner/config;
  immutable paths must be
  declared pins, mutable paths must be declared under the audit root, and a
  generated input must name an earlier job's exact success artifact;
- every invocation has a pinned executable followed by a pinned runner file;
  inline code/evaluator modes and relative filesystem literals are impossible
  regardless of executable name or whether the path exists at plan freeze;
- size/SHA-256 records for every declared executable, script, checkpoint,
  config, manifest, and validator, plus recursive file-count/byte/tree hashes
  for directory inputs such as the replay pool, rechecked before and after every
  job;
- minimum free bytes and inodes before and during every job, checked on every
  distinct filesystem used by its mutable paths;
- a mandatory maximum runtime for every job;
- mandatory progress-file staleness for jobs longer than 30 minutes, including
  a file that never appears, or an explicit reason why a job bounded to at most
  30 minutes needs no progress file;
- a mandatory GPU temperature ceiling and three consecutive over-temperature
  polls before terminating a process group;
- vacation screen arms run with `ARM_DETACH=0`, so the Puffer trainer remains
  inside the queue job's `start_new_session` process group; runtime, progress,
  capacity, thermal, and service-stop cleanup therefore reach the trainer and
  its descendants rather than only the screen wrapper;
- a mandatory bounded validator for every success artifact, plus an expected
  artifact SHA-256 when it can be known before execution;
- validator process-group cleanup, thermal/capacity supervision, and a 10 MiB
  output cap written on the monitored queue filesystem;
- atomic queue state and per-job logs; and
- retry after interruption only when that job is explicitly `resume_safe`.

The concrete builder is `tools/freeze_vacation_queue.py`. It refuses to select a
candidate. The accepted-candidate route requires already-complete main-lineage
self-play/scripted/learned evidence, writes three hash-pinned screen configs plus
the two-lineage gate config, and validates the resulting six-job typed plan
before publication. The all-candidates-rejected route requires the exact
scripted recommendation described above, writes two hash-pinned `control-final`
configs, and validates a two-job typed plan with no learned transfer or gate.
The confirmation-rejected baseline route requires an exact failed paired
confirmation bound to its original selection transfer, independently
recomputes the fixed self-play gate, writes a pinned authorization report, and
reuses the same two-job R0 execution path. All routes are explicit in the spec;
none is inferred by overloading `candidate_arm`. They apply the same full
source-screen provenance closure, with no legacy exception.
`tools/run_frozen_reward_screen.py` is the categorical/path bridge into the
existing environment-variable launcher. `tools/run_reward_learned_transfer.py`
creates atomic per-cell learned-anchor results in both backend roles.
`tools/vacation_reward_gate.py` is the only path to `GATE_COMPLETE.json`.

Training screens are deliberately **not** `resume_safe`: restarting a partially
optimized PPO trajectory would change the experiment. Scripted transfer is
resume-safe because a cell is exposed at its final name only after validation;
interrupted stdout is content-addressed under `interrupted/`. Learned transfer
writes each cell atomically. Validation-only gate jobs are also resume-safe.
The ordinary interactive reward launcher still defaults to detached arms;
`run_frozen_reward_screen.py` is the reviewed bridge that disables detachment
for queue-owned vacation screens.

A completed job whose recorded success artifact is later missing, changed, or
invalid halts permanently; it is never silently rerun. `pinned_inputs` is also
the explicit transitive dependency declaration reviewed with the plan. The
typed interface blocks ordinary undeclared path arguments and environment
inputs, while each approved Blood Bowl runner's own frozen manifest validates
the files it discovers internally.

The user service uses `KillMode=control-group`, so a service stop cannot leave a
trainer child behind. `Restart=on-failure` covers a runner crash; a deliberate
fail-closed queue halt exits normally and is terminal across service restarts
and reboots. There is intentionally no in-place “acknowledge and continue”
switch. After diagnosis, recovery requires a newly reviewed queue ID/plan/state;
the halted evidence remains immutable.

The optional overflow uses the same queue service plus the tracked
`vacation-overflow-watch@.service/.timer`. The timer is an outer readiness gate,
not an authority to recover: it starts nothing while the primary service is
active, when the primary is not exactly complete, when any primary evidence or
overflow pin drifted, when a GPU compute PID exists, or once any overflow state
exists. A halted, failed, interrupted, or previously started overflow is never
timer-relaunched. Even an accidental manual service start must pass the same
completion proof as the overflow queue's first job before PPO can begin.

The RTX host currently has systemd user lingering enabled, Tailscale running
without key expiry, and the BBTV services enabled. These are host facts to
recheck immediately before departure, not assumptions embedded in the queue.

## Departure gate

Do not leave the queue unattended until all of the following are true:

- repository PR merged and the audit source snapshot is byte-identical to the
  merged commit. The current audit tree intentionally preserves run/vendor
  artifacts and may have no `.git`; verify every tracked archive path by
  checksum and retain `.deployed-source.json` rather than claiming it is a Git
  checkout;
- local CI and focused queue/transfer tests pass;
- remote installed-source check passes and GPU identity is recorded;
- the plan, every referenced input, and every validator are hash-recorded;
- a deliberate interruption demonstrates process-group cleanup and terminal
  halt for a non-resume-safe job; a separate synthetic resume-safe job
  demonstrates validated artifact recovery;
- a synthetic failure demonstrates that later jobs do not start;
- disk/inode use, journal size, Tailscale, linger, BBTV, and GPU temperature are
  healthy;
- BBTV visibly advances to a newly completed manifested checkpoint;
- the exact pinned overflow GPU parser excludes BBTV because its match server
  loaded the isolated CPU/fp32 `_C` from the expected viewer root;
- no production reward or production trainer/evaluator was changed; and
- if the optional overflow is armed, its timer failure/success smokes pass, a
  primary-running poll is a proven no-op, every primary pinned byte remains
  identical across additive deployment, and existing overflow state cannot be
  timer-relaunched.

Freeze and validate only after the main evidence paths are literal:

```bash
vendor/PufferLib/.venv/bin/python tools/freeze_vacation_queue.py \
  runs/<queue-id>/VACATION_SPEC.json
systemctl --user start experiment-queue@<queue-id>.service
```

All three schema-2 spec routes name `route` explicitly and fix
`second_steps=1000000000`, both warm checkpoint paths, the
static pool, the exact main screen and scripted-transfer proofs, free-space/
inode floors, and the thermal ceiling. The candidate mode additionally fixes
`final_steps=6000000000`, the anchor config, and the main learned-transfer proof.
Both R0-only modes instead fix `final_steps=12000000000` and require null anchor
and learned-transfer fields. `all-candidates-rejected-control` requires the full
three-candidate rejection matrix from a provenance-complete decomposition
screen; `confirmation-rejected-baseline` requires the exact rejected paired
screen and its embedded selection proof. Editing any config, pin, or plan after
first start is a terminal halt.

## Monitoring readout

Each status update reports the current job/arm, completed and requested steps,
train or eval phase, completed full games, integrity counters, GPU memory/load/
temperature, free disk, BBTV selection, and estimated completion. Evidence is
read from the queue state and immutable per-run artifacts; a process name or a
stale final dashboard line is never treated as proof of liveness or success.
