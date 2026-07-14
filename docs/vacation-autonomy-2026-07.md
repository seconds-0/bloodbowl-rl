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

## The 24 hours before departure

1. Finish and atomically analyze the active `500M x 2` possession/gain screen.
2. Run all four arms through the 32-cell scripted-opponent transfer matrix:
   two training seeds, both available scripted styles, and both team sides.
3. Select at most one simplification candidate for confirmation. This is only
   a routing decision; scripted bots cannot promote a reward.
4. Freeze the selected candidate and run the longer paired `1B x 2`
   confirmation against R0. The preceding four-arm factorial remains the
   interaction evidence; the confirmation spends compute only on the declared
   reference and candidate.
5. Evaluate that confirmation against exactly four frozen learned anchors, with
   the focal policy loaded in both native backend roles. The learned matrix uses
   exactly `4096` games per cell and a separately pinned gate configuration. It
   is a deterministic fixed-stratum gate over the overall mean, each training
   seed, each anchor, each backend orientation, and the worst cell. These are
   repeated strata, not independent replicates: no confidence interval or
   reward-promotion claim is made.
6. Freeze the six-day queue only after self-play, scripted transfer, and learned
   transfer decide its literal checkpoint/reward hashes. Review, merge, deploy,
   start, interrupt, and resume-smoke the service before departure.

If the pre-departure evidence is incomplete, inconsistent, or rejects every
simplification, the vacation queue retains R0 as the experimental control. It
does not guess a candidate.

## Six-day queue order

The frozen queue uses the July audit's priority order:

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

The exact queue may be shorter if the repository lacks a verified launcher for
a proposed cell. A new launcher is deployed only after focused tests and a
local/remote smoke; it is never improvised by the running service.

The per-job safety maxima intentionally sum to more than six days: they are
fault guards, not a return-home cutoff. Because the RTX 2070 is reserved and
the user authorized multi-day use, a slowed but healthy declared job may finish
after the nominal vacation window rather than being killed mid-trajectory. The
queue still cannot start undeclared work after its six literal jobs finish.

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
candidate, requires already-complete main-lineage self-play/scripted/learned
evidence, writes three hash-pinned screen configs plus the two-lineage gate
config, and validates the resulting six-job typed plan before publication.
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
- BBTV visibly advances to a newly completed manifested checkpoint; and
- no production reward or production trainer/evaluator was changed.

Freeze and validate only after the main evidence paths are literal:

```bash
vendor/PufferLib/.venv/bin/python tools/freeze_vacation_queue.py \
  runs/<queue-id>/VACATION_SPEC.json
systemctl --user start experiment-queue@<queue-id>.service
```

The spec fixes `second_steps=1000000000`, `final_steps=6000000000`, both warm
checkpoint paths, the static pool, anchor config, three main-lineage completion
proofs, free-space/inode floors, and the thermal ceiling. Editing any config,
pin, or plan after first start is a terminal halt.

## Monitoring readout

Each status update reports the current job/arm, completed and requested steps,
train or eval phase, completed full games, integrity counters, GPU memory/load/
temperature, free disk, BBTV selection, and estimated completion. Evidence is
read from the queue state and immutable per-run artifacts; a process name or a
stale final dashboard line is never treated as proof of liveness or success.
