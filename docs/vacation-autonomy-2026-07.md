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
5. Freeze the six-day queue only after the screen and transfer artifacts decide
   its literal checkpoint/reward hashes. Review, merge, deploy, start, interrupt,
   and resume-smoke the service before departure.

If the pre-departure evidence is incomplete, inconsistent, or rejects every
simplification, the vacation queue retains R0 as the experimental control. It
does not guess a candidate.

## Six-day queue order

The frozen queue uses the July audit's priority order:

1. Complete or validate the `1B x 2` R0-versus-candidate confirmation.
2. Evaluate both policies against frozen learned anchors in both orientations,
   using equal cell weights. Scripted-bot results remain a separate stratum.
3. Reproduce the paired confirmation from the frozen `league9` second ancestry.
4. Run a predeclared gate job. It succeeds only if both lineages pass the
   non-inferiority and integrity contract; on rejection it halts the literal
   queue for inspection. Only success unlocks the already-declared matched
   `4B x 2` final reproduction. There is no dynamic “otherwise” branch.
5. Stop cleanly when the declared jobs finish. Unused GPU time is preferable to
   an unreviewed objective, backend, opponent, roster, or replay-distribution
   change.

The exact queue may be shorter if the repository lacks a verified launcher for
a proposed cell. A new launcher is deployed only after focused tests and a
local/remote smoke; it is never improvised by the running service.

## Runtime safety and recovery

`tools/experiment_queue.py` enforces:

- a singleton file lock, immutable plan SHA-256, and a closed schema that
  rejects unknown or misspelled guard fields;
- mutable working/log/status/artifact paths constrained to the audit root;
- an explicit minimal base environment plus size/SHA-256 records for every
  declared executable, script, checkpoint, config, manifest, and validator,
  rechecked before and after every job;
- minimum free disk before and during every job;
- a mandatory maximum runtime for every job;
- mandatory progress-file staleness for long jobs, including a file that never
  appears, or an explicit reason why a bounded short job needs no progress file;
- three consecutive over-temperature polls before terminating a process group;
- a mandatory bounded validator for every success artifact, plus an expected
  artifact SHA-256 when it can be known before execution;
- atomic queue state and per-job logs; and
- retry after interruption only when that job is explicitly `resume_safe`.

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

- repository PR merged and the audit checkout is exactly the merged commit;
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

## Monitoring readout

Each status update reports the current job/arm, completed and requested steps,
train or eval phase, completed full games, integrity counters, GPU memory/load/
temperature, free disk, BBTV selection, and estimated completion. Evidence is
read from the queue state and immutable per-run artifacts; a process name or a
stale final dashboard line is never treated as proof of liveness or success.
