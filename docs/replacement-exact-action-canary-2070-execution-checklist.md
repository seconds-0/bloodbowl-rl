# RTX 2070 replacement exact-action 50M canary checklist

Status: reviewed procedure only. This file does not authorize plan creation or
training by itself. Authority exists only when the exact merged authorization
commit is rebuilt, requalified, independently accepted, and represented by the
two immutable authority artifacts below.

The rejected `a52fc6e2` candidate and its v1/v2/v3 outputs, units, probes,
authorization records, and stopped evidence remain immutable rejection
evidence. Never delete, modify, copy forward, relabel, retry, or use them as an
input to this replacement.

## Fixed replacement contract

- Profile: `exact-action-canary`
- Prefix: `exact-action-canary-50m-s42-v4`
- Unit: `bloodbowl-exact-action-canary-50m-s42-v4.service`
- Requested agent steps: `50000000`
- Rollout quantum: `131072` (`2048 * 64`)
- Final complete-rollout steps: `49938432`
- Learner/environment/self-play seed: `42`
- Reward arm: R0 `both`
- Precision: fp32
- ABI: obs-v5 / version 5 / exact-joint-v1
- Initialization: fresh
- Warm checkpoint: absent
- League pool: absent
- Frozen banks: zero
- Minibatch size: `16384`
- CUDA graph capture epoch: `10`
- Monitor poll: `30` seconds
- Maximum integrity-panel silence: `180` seconds
- Contamination budget: literal zero for all 16 hard-integrity fields
- Unit: `Type=oneshot`, `Restart=no`, `KillMode=control-group`,
  `TimeoutStartSec=7200`, `TimeoutStopSec=60`, disabled and never enabled
- Qualification and canary artifacts: permanently ancestry-ineligible and
  reward-evidence-ineligible
- Maximum start count: one; never restart, resume, or repair in place

The exact merged authorization commit is not known until the PR merges. Record
its full 40-character commit and tree in the external execution evidence before
creating remote roots; requalify the exact merged authorization commit. The
earlier accepted D225 `ee7ace4` qualification is a prerequisite and regression
reference, not evidence for changed launcher bytes.

Create entirely fresh paths derived from that merged commit. The concrete paths
must be copied into the immutable execution record before use:

- clean control root;
- separate clean candidate root;
- candidate-local Puffer checkout and venv;
- construction output;
- predecessor capture/consumption output;
- qualification output;
- plan-only output;
- stopped-validation output;
- authority/evidence root;
- `CANARY_PLAN_AUTHORIZATION.json` and its `.sha256` sidecar;
- `CANARY_LAUNCH_AUTHORIZATION.json` and its `.sha256` sidecar;
- canonical v4 unit file;
- off-box preservation destination.

No path may be inside the production checkout, recovery root, a rejected
canary root, a prior qualification root, or a source checkout.

## Gate 0: immutable boundary and host discovery

Before any write or GPU cell:

1. Revalidate the completed recovery queue and screen evidence and the accepted
   off-box preservation inventory. Copy exact byte-identical instances of the
   preserved `gate6-verifier.stdout` and `recovery-inventory.json` into the new
   evidence root. The authority requires their frozen SHA-256 values, validates
   the full inventory schema and three result bindings, and reconciles the
   accepted file count, byte total, and inventory digest between them. These are
   authorization inputs, not replacements for the off-box files.
2. Revalidate the untouched schema-3 predecessor throughput artifact and its
   full closed inventory.
3. Confirm `wsl-ubuntu` resolves to the intended RTX 2070 host and record host,
   driver, GPU, compiler, Python, Torch, disk, RAM, and current CUDART identity.
4. Confirm the recovery queue is inactive/successful, no recovery or
   qualification process is live, and no GPU compute PID exists.
5. Record `bbstream.service`, `bbtv-tunnel.service`, BBTV follower state, and a
   public HTTP health result. Do not change the tunnel.
6. Require the old v1/v2/v3 unit names absent and all rejected evidence roots
   unchanged. Do not remove an old artifact to satisfy a precondition.

Any mismatch stops the procedure. Preserve one rejection record and do not
repeat the same failed boundary.

## Gate 1: merge, deploy, and fresh final-commit qualification

1. Require all local suites, sanitizer coverage, independent code/test review,
   and required GitHub checks green before merge.
2. Record the exact squash-merged commit and tree. Build clean control and
   candidate checkouts at that same commit in separate fresh roots.
3. Install the exact pinned Puffer base and all patches, including the complete
   self-play patch, into only the candidate-local Puffer tree. Require installer
   `--check`, complete reverse patch applicability, exact normalized package
   inventory, and a fresh fp32 module.
4. Keep the historical predecessor source/module/runtime untouched. Consume its
   exact accepted schema-3 throughput control under the new runner; never rebuild
   it to match the candidate.
5. Run one construction gate, one predecessor control consumption/capture as
   required by the merged runner, and one full qualification. Do not retry a
   failed output identity.
6. Require all five mandatory qualification gates accepted, graph/reset maxima
   exactly zero within their frozen tolerances, full primary-row ratio coverage,
   no frozen-row selection, byte-identical zero-update weights, throughput
   within the ten-percent predecessor budget, and all 16 hard-integrity fields
   exactly zero in every transition-executing cell.
7. Run the validator twice from fresh candidate-Python processes with `-B`,
   `PYTHONDONTWRITEBYTECODE=1`, and `CUDA_VISIBLE_DEVICES=0`. Require exit zero,
   empty stderr, byte-identical validation output, unchanged qualification
   inventory, and clean control/candidate roots.
8. Copy the complete closed evidence off-box, verify every hash and exact file
   coverage, then obtain a separate read-only APPROVE verdict with no P0–P3.

Do not proceed from a qualification that covers a parent commit, a locally
modified checkout, a different module, or a self-reported result.

## Gate 2: freeze plan authority

The plan authority is created only after Gate 1. It binds the accepted recovery
reference, predecessor inventory, full qualification inventory, clean source
commit/tree, candidate/module/backend/environment identities, shared CUDART
path/hash/device count, the complete 16-key registry, and the exact absent
plan-output destination.

Invoke the merged candidate tool from its candidate venv with absolute paths:

```text
<candidate-python> -B <candidate-root>/tools/exact_action_canary_authority.py \
  freeze-plan \
  --destination <authority-root>/CANARY_PLAN_AUTHORIZATION.json \
  --qualification <qualification-root>/QUALIFICATION.json \
  --source-root <candidate-root> \
  --qualification-runner-root <control-runner-root> \
  --screen-output <fresh-plan-output> \
  --recovery-verification <exact-gate6-verifier.stdout> \
  --recovery-inventory <accepted-recovery-inventory> \
  --predecessor-root <accepted-predecessor-output-root>
```

Require the destination, digest sidecar, and plan output absent before the
command. The authority tool creates the JSON and `.sha256` sidecar exclusively;
presence, relative paths, symlinks, malformed evidence, source drift, or an
existing output rejects the operation. Copy both files off-box and independently
run `validate-plan --require-output-absent` before Gate 3.

## Gate 3: exactly one plan-only materialization

Invoke the exact candidate launcher once:

```text
/usr/bin/env -u WARM -u POOL \
  PATH=<candidate-venv-bin>:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  CUDA_VISIBLE_DEVICES=0 \
  OMP_NUM_THREADS=16 OPENBLAS_NUM_THREADS=16 MKL_NUM_THREADS=16 NUMEXPR_NUM_THREADS=16 \
  STEPS=50000000 SCREEN_PROFILE=exact-action-canary \
  PREFIX=exact-action-canary-50m-s42-v4 \
  OUT_DIR=<fresh-plan-output> POLL_SECONDS=30 PLAN_ONLY=1 ARM_DETACH=0 \
  CANARY_PLAN_AUTHORIZATION=<authority-root>/CANARY_PLAN_AUTHORIZATION.json \
  CANARY_PLAN_AUTHORIZATION_SHA256_FILE=<authority-root>/CANARY_PLAN_AUTHORIZATION.sha256 \
  /usr/bin/bash <candidate-root>/tools/run_reward_screen.sh
```

Require exit zero. The output must contain exactly two regular files:
`SCREEN_MANIFEST.json` and a zero-byte `.screen.lock`. Require the empty-file
SHA-256, exact modes/sizes/digests, and a non-creating, read-only, subshell-scoped
released-lock proof. Recompute the inventory afterward and require it
byte-identical. Require no trainer log, run directory, checkpoint, status,
result, completion record, launch record, or GPU process.

If anything else exists, preserve and reject that plan identity. Never delete a
lock or extra entry, rewrite the manifest, or rerun the launcher into that path.

## Gate 4: canonical unit and launch authority

Create the separately new/empty stopped-validation directory. Render the unit
once with `render-unit`, supplying the fixed candidate source, separate clean
control/qualification-runner source, qualification, plan output, future
launch-authorization destination, and future digest-sidecar path. Require
the unit name `bloodbowl-exact-action-canary-50m-s42-v4.service`.

```text
<candidate-python> -B <candidate-root>/tools/exact_action_canary_authority.py \
  render-unit \
  --destination <authority-root>/bloodbowl-exact-action-canary-50m-s42-v4.service \
  --source-root <candidate-root> \
  --qualification-runner-root <control-runner-root> \
  --qualification <qualification-root>/QUALIFICATION.json \
  --screen-output <fresh-plan-output> \
  --launch-authorization <authority-root>/CANARY_LAUNCH_AUTHORIZATION.json \
  --launch-authorization-sha256-file <authority-root>/CANARY_LAUNCH_AUTHORIZATION.sha256
```

Then freeze the launch authority:

```text
<candidate-python> -B <candidate-root>/tools/exact_action_canary_authority.py \
  freeze-launch \
  --destination <authority-root>/CANARY_LAUNCH_AUTHORIZATION.json \
  --plan-authorization <authority-root>/CANARY_PLAN_AUTHORIZATION.json \
  --plan-sha256-file <authority-root>/CANARY_PLAN_AUTHORIZATION.sha256 \
  --source-root <candidate-root> \
  --unit <authority-root>/bloodbowl-exact-action-canary-50m-s42-v4.service \
  --stopped-validation-output <empty-stopped-validation-output>
```

Require exclusive creation of the JSON and sidecar. The launch authority must
bind the exact plan inventory/manifest, source and qualification, shared CUDART,
canonical unit bytes/hash, empty stopped output, fixed command/environment,
one-start ceiling, the initially absent canonical sibling
`CANARY_LAUNCH_CONSUMPTION.json` and digest sidecar, exact-zero budget, and all
eligibility exclusions. Consumption authentication before publication is
strictly limited to those frozen launch bytes; do not move fallible plan,
qualification, source, unit, or GPU revalidation ahead of the publication.

Copy the unit, both authorities, both sidecars, and closed evidence inventory
off-box. Obtain an independent read-only review before installing anything.

## Gate 5: systemd escape probes and disabled installation

Before the real unit, run three disposable non-training user units using the
same `$$`, `$${name}`, and `%%s` escape pattern as the canonical empty-GPU
probe:

- empty output must exit zero;
- fixed `123` output must fail;
- a failing producer command must independently fail.

Run `systemd-analyze --user verify` on all probe units and the canonical unit.
Capture exact unit bytes, statuses, and journals. Remove the disposable units
and require them absent. Reject any operative bare `printf "%s"` or single `$`
where Bash requires expansion.

Copy the canonical unit byte-for-byte into the user manager's required unit
directory, daemon-reload, and require:

- installed bytes equal the authorized unit;
- disabled/not enabled;
- inactive before start;
- `NRestarts=0`;
- `Restart=no` and `KillMode=control-group`;
- the exact first `consume-launch` prestart, separate-runner qualification
  validator, and empty-GPU probe in that order;
- the exact `/usr/bin/env -u WARM -u POOL` 50M command.

Do not enable the unit.

## Gate 6: final prestart and one allowed start

Immediately before start:

1. Revalidate both authorities, sidecars, source, qualification, predecessor,
   recovery reference, plan output, released lock, canonical/installed unit,
   empty stopped output, and complete inventories.
2. Require three idle GPU samples at the fleet-skill interval: utilization zero,
   temperature at most 55 C, and an empty exact compute-process list.
3. Record BBTV public health and selection. Stop only `bbstream.service` for the
   bounded GPU workload; keep `bbtv-tunnel.service` active. Install a shell trap
   that restores BBTV and records its state regardless of success or failure.
4. Recheck empty GPU, unit disabled/inactive, no trainer, no old canary unit, and
   no held screen lock.

Start the exact unit once. Its first prestart must exclusively publish
`CANARY_LAUNCH_CONSUMPTION.json` and its digest sidecar before qualification or
GPU checks; require both to bind the exact launch authorization, plan output,
attempt `1`, and maximum starts `1`. Record the start timestamp, unit properties,
main PID, process group, GPU PID, command line, consumption hash,
manifest hash, launch-record hash, log inode/size/mtime,
source/module/CUDART identities, and BBTV tunnel health.

Before the installer or any training setup, require the launcher to exclusively
publish `$OUT_DIR/CANARY_LIVE_INVOCATION.json`, binding the exact authorization,
consumption hash, output, attempt `1`, and maximum starts `1`. Preserve its hash.
An existing, malformed, or drifted claim rejects; never remove it to retry.

No second `systemctl start`, `restart`, reset-failed-and-retry, manual trainer,
or alternate command is permitted. The immutable consumption blocks a second
unit start, while the live-invocation claim independently blocks direct
`ExecStart` replay even if the first attempt fails before trainer launch.

## Gate 7: live monitoring and zero error budget

Poll read-only at no more than 30-second intervals plus dashboard emission.
Require one unit/process group, one GPU compute process, unchanged source/unit/
authority/manifest hashes, advancing log/progress, and complete schema-2
integrity panels.

Fail immediately on any missing, malformed, non-finite, or nonzero hard field;
sampled/executed action disagreement; native first-transition abort; log
replacement/truncation; more than 180 seconds without an integrity panel;
unexpected exit; PID/process-group drift; GPU disappearance or an additional
compute PID; or any source/module/backend/environment/CUDART/command drift.

Let the unit and live guard terminate the entire control group. Preserve the
atomic failure record and partial evidence, verify no child or compute PID
remains, restore BBTV, and stop. Never restart, resume, splice, or repair the
partial canary.

## Gate 8: stopped acceptance and preservation

After the sole unit exits, require inactive `Result=success`,
`ExecMainStatus=0`, `NRestarts=0`, no compute PID, unchanged authorities/unit,
and restored healthy BBTV.

Write Gate 8 outputs only into the separately authorized stopped-validation
directory:

1. Run `live_integrity_guard.py --complete-log` from the exact merged control
   checkout against the sole trainer log and require all 16 hard-integrity
   fields literally zero in every complete panel.
2. Run `analyze_reward_screen.py <canary-output> --json
   --expected-screen-sha <authorized-manifest-sha>`. Require the exact v4
   authority/launch record, one seed-42 `both` result, final step `49938432`,
   checkpoint bytes `16066560`, policy shape 512 x 3 x 1, fresh/no warm/no pool,
   at least 10,000 completed evaluation games, empty failure list, all 16
   counters zero, exact CUDA/qualification bindings, and atomic completion.
3. Run `checkpoint_lineage.py validate` on the final checkpoint and adjacent
   lineage with the authorized source/module/Puffer expectations. Require
   `qualification_only=true`, `eligible=false`, initialization `fresh`, and
   empty warm/pool ancestry.

Close the complete output, unit/journal, stopped-validation, and authorization
inventories; copy them off-box; verify exact coverage and every SHA-256; and get
an independent read-only acceptance review.

An accepted canary proves only bounded execution of the repaired runtime. Its
checkpoint and metrics remain ancestry-ineligible and reward-evidence-ineligible
and cannot seed BBTV, a pool, BC, a reward comparison, a promotion decision, a
causal screen, or a long run. Scientific training requires separate eligible
fresh ancestry and separately reviewed authority.
