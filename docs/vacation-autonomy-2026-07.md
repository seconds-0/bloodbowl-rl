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
4. Run the longer `1B x 2` confirmation against R0, retaining all four arms if
   schedule time permits so an early transfer choice cannot hide an interaction.
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
4. Only if both lineages pass the predeclared non-inferiority and integrity
   gates, run the matched `4B x 2` final reproduction. Otherwise spend the
   remaining budget on additional control/candidate seeds and held-out anchor
   games, not on a new reward recipe.
5. Stop cleanly when the declared jobs finish. Unused GPU time is preferable to
   an unreviewed objective, backend, opponent, roster, or replay-distribution
   change.

The exact queue may be shorter if the repository lacks a verified launcher for
a proposed cell. A new launcher is deployed only after focused tests and a
local/remote smoke; it is never improvised by the running service.

## Runtime safety and recovery

`tools/experiment_queue.py` enforces:

- a singleton file lock and immutable plan SHA-256;
- absolute paths constrained to the declared audit root;
- minimum free disk before and during every job;
- a maximum job runtime;
- progress-file staleness, including a file that never appears;
- three consecutive over-temperature polls before terminating a process group;
- exact success artifact SHA-256 and/or a declared validator command;
- atomic queue state and per-job logs; and
- retry after interruption only when that job is explicitly `resume_safe`.

The user service uses `KillMode=control-group`, so a service stop cannot leave a
trainer child behind. `Restart=on-failure` covers a runner crash; a deliberate
fail-closed queue halt exits normally and stays stopped for inspection.

The RTX host currently has systemd user lingering enabled, Tailscale running
without key expiry, and the BBTV services enabled. These are host facts to
recheck immediately before departure, not assumptions embedded in the queue.

## Departure gate

Do not leave the queue unattended until all of the following are true:

- repository PR merged and the audit checkout is exactly the merged commit;
- local CI and focused queue/transfer tests pass;
- remote installed-source check passes and GPU identity is recorded;
- the plan, every referenced input, and every validator are hash-recorded;
- a deliberate service interruption demonstrates the advertised recovery path;
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
