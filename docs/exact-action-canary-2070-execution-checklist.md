# RTX 2070 exact-action 50M canary execution checklist

Status: prepared for execution only after exact recovery preservation and an
independently accepted recurrent-CUDA qualification. This checklist does not
authorize a canary from a failed, incomplete, stale, or merely self-reported
qualification.

## Fixed scope

- Candidate source: `a52fc6e2f4ece5a7ff16bb4791e3aca4dd72f2e3`
- Candidate Git tree: `57731b2af496a4e382d263bbfe123bc219f6bd51`
- Control runner: `cf13fe5e22b95da0afac033188dcea96432d6909`
- Runner Git tree: `82c184a5983a4add2278237d121604ac3833c263`
- Runner file SHA-256:
  `916fa6efa851c3d966658de8635dade2da61646945dabbf930774389659c140e`
- Stopped analyzer SHA-256:
  `3ea835d5f7c893571e3a885c4d5ad8a7cd61e16fdd372e968b5d11b955b5d3fd`
- Stopped complete-log guard SHA-256:
  `e9c957ae37671bc6bfd6d09c7ef2d956736a5ead7242395f2357006bfc571ff1`
- PufferLib base: `9836f0d2e78889c1aaf189c04d161b6fc61a9386`
- Candidate root:
  `/home/rache/bloodbowl-rl-qualification-candidate-a52fc6e`
- Control root:
  `/home/rache/bloodbowl-rl-qualification-control-20260722-v4`
- Qualification root:
  `/home/rache/bloodbowl-rl-qualification-artifacts-20260722/candidate-qualification`
- Canary output:
  `/home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-50m-s42-v2`
- Stopped-validation output:
  `/home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-50m-s42-v2-validation`
- Unit name: `bloodbowl-exact-action-canary-50m-s42-v2.service`
- Requested agent steps: exactly `50000000`
- Rollout quantum: exactly `131072` (`2048 * 64`)
- Minibatch size: exactly `16384`
- CUDA graph capture epoch: exactly `10`
- Executed/final agent steps: exactly `49938432` (381 complete rollouts)
- Learner/environment/self-play seed: exactly `42`
- Reward profile: frozen R0 `both`
- Precision: fp32
- ABI: `obs-v5` / version 5 / `exact-joint-v1`
- Initialization: fresh
- Warm checkpoint, league pool, and frozen banks: absent
- Qualification and canary ancestry eligibility: permanently false
- Hard-integrity contamination budget: literal zero
- Live detection interval: at most 30 seconds plus one dashboard emission

The superseded v1 plan-only attempt is immutable rejection evidence, not launch
authority. The frozen launcher exited zero and wrote its valid manifest, but it
also intentionally created the persistent zero-byte `.screen.lock` used by the
one-screen ownership contract. The earlier checklist allowed only the manifest,
so v1 was rejected before training. Its final preserved location is
`/home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-50m-s42-v1-plan-rejected-unaccounted-lock`.
The exact rejection-only evidence is:

| Artifact | Absolute path | SHA-256 |
|---|---|---|
| Manifest | `/home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-50m-s42-v1-plan-rejected-unaccounted-lock/SCREEN_MANIFEST.json` | `15271d946e404ddcd26e9fc075d44b9dbeaa268b6e5e9ffecf536abfd212a331` |
| Zero-byte lock | `/home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-50m-s42-v1-plan-rejected-unaccounted-lock/.screen.lock` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| Mode/size inventory | `/home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-50m-s42-v1-plan-rejected-files.tsv` | `6d69a4deb85698279f100079ee6bb3b785af9b36d97cefeb7cc4f11389ce35f7` |
| Closed content inventory | `/home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-50m-s42-v1-plan-rejected-inventory.sha256` | `2756134a67dfc8010c13d16eb30533b82671580e6e5eb049f430f813ef7482e4` |
| Rejection record | `/home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-50m-s42-v1-plan-rejection.txt` | `68d92db88481fb9aaa06b0e31e80429f5da9904b20ef39e6ed15dcad3f551618` |

The mode/size inventory is the two headerless, bytewise-sorted TSV rows
`mode<TAB>bytes<TAB>relative-path`, where mode is exactly three octal permission
digits from GNU `find -printf '%m'` with no prefix. The closed content inventory
is the two bytewise-sorted `sha256<TWO-SPACES>relative-path` rows. Recompute both
from the preserved output while excluding the external evidence files
themselves. The rejected, never-installed unit identity was
`bloodbowl-exact-action-canary-50m-s42-v1.service`; Gate 1 must prove both that
unit and its unit file absent.
No trainer, log, checkpoint, run directory, completion artifact, or GPU compute
process was created. Do not delete, relabel, launch, or reuse the v1 output or
unit identity. Only the fresh v2 paths above may proceed under this corrected
authority.

Candidate launch-source SHA-256 identities are:

| File | SHA-256 |
|---|---|
| `tools/run_reward_screen.sh` | `b4ffe9cd6652a0b5f003956015797c458863a8152adcc278b323ba0a329adda8` |
| `tools/run_reward_ablation.sh` | `9ec91be0203fba670a0e61e3da5a1011fe976294bb552d78e482ef70c9c32e43` |
| `tools/live_integrity_guard.py` | `e182ced506ccb8b8d802f660d64fb13a3ca438c18487104a6c97cb1f07426b0b` |
| `tools/checkpoint_lineage.py` | `c2fd719bd8a24aa6d759e83ab1cc8bdd99608ee343f3d559abfb14a6b21dacb5` |
| `tools/game_stats.py` | `fb8c1f4a2de137b8102aaff5871fdfa32dafc77ebdf3c506e7aed3ceb001b957` |
| `puffer/config/rewards/r0_full.json` | `eb9ddfe506c6222df4439150b3f4009577aa117a1afa1e792ed6ee380372b88b` |

The independent stopped analyzer is executed only from the exact control
runner, not from candidate `a52fc6e`. Re-hash
`tools/analyze_reward_screen.py` in that control root and require exact SHA-256
`3ea835d5f7c893571e3a885c4d5ad8a7cd61e16fdd372e968b5d11b955b5d3fd`.
Re-hash `tools/live_integrity_guard.py` in the same control root and require
exact SHA-256
`e9c957ae37671bc6bfd6d09c7ef2d956736a5ead7242395f2357006bfc571ff1`.

Re-hash all six before plan-only materialization and again immediately before
unit installation. Any mismatch rejects the canary.

## Gate 1: accepted prerequisites

All of the following must be captured and hash-bound before plan-only canary
materialization:

1. The recovery preservation verifier accepted the off-box copy, and the local
   recovery manifest file SHA-256 and inventory SHA-256 are fixed.
2. The predecessor throughput control exists, validates, and binds exact
   predecessor source/module/backend/environment identities.
3. Candidate `QUALIFICATION.json` exists in the fixed qualification root,
   states `qualification_only=true` and `accepted=true`, and is independently
   accepted twice from fresh candidate-interpreter processes using exact runner
   commit `cf13fe5`.
4. The qualification directory is closed and its exact relative file set,
   modes, sizes, and SHA-256 inventory are fixed.
5. Candidate source, Puffer source, venv package inventory, installed Blood Bowl
   source, compiled module/backend, CUDA libraries, and build-identity artifact
   still match the accepted qualification.
6. No recovery trainer, qualification cell, evaluator, or other GPU compute
   process remains. BBTV follower state and public HTTP health are recorded.
7. The canary output path and unit name do not exist. The exact superseded v1
   unit identity named above is also absent from the user systemd manager and
   its unit-file directory, and the original pre-rejection v1 output path
   `/home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-50m-s42-v1`
   is absent rather than copied alongside its renamed rejection directory.
8. Recompute the five rejection-only evidence hashes and both canonical
   inventories above from their exact paths; every value must still match.

Any mismatch stops deployment. Do not delete or overwrite an existing output
to make the precondition true.

## Gate 2: plan-only positive launch proof

From the exact candidate root, with its venv first on `PATH`, run the launcher
once with `PLAN_ONLY=1`, `ARM_DETACH=0`, and an explicitly empty inherited warm
and pool environment:

```text
/usr/bin/env -u WARM -u POOL \
  PATH=/home/rache/bloodbowl-rl-qualification-candidate-a52fc6e/vendor/PufferLib/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  CUDA_VISIBLE_DEVICES=0 \
  OMP_NUM_THREADS=16 OPENBLAS_NUM_THREADS=16 MKL_NUM_THREADS=16 NUMEXPR_NUM_THREADS=16 \
  STEPS=50000000 \
  SCREEN_PROFILE=exact-action-canary \
  PREFIX=exact-action-canary-50m-s42-v2 \
  OUT_DIR=/home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-50m-s42-v2 \
  POLL_SECONDS=30 PLAN_ONLY=1 ARM_DETACH=0 \
  /usr/bin/bash /home/rache/bloodbowl-rl-qualification-candidate-a52fc6e/tools/run_reward_screen.sh
```

Require exit zero and exactly two regular files directly under the new output:
`SCREEN_MANIFEST.json` plus `.screen.lock`, with no directory or other entry.
Complete and accept this regular-file/type inventory before opening the lock;
never run the probe against a symlink, FIFO, device, directory, or an
uninventoried path.
The lock must have zero bytes, the empty-file SHA-256, and a successful
post-process, non-creating proof that no process retains it:

```text
( exec 9</home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-50m-s42-v2/.screen.lock; flock -n 9 )
```

The empty-file SHA-256 must be exactly
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
Open the already inventoried absolute path read-only as shown; a pathname-form `flock`
probe is forbidden because it could create a missing lock and conceal a failed
inventory. The subshell is mandatory: it closes FD 9 and releases the proof's
lock before the command returns. Name the first capture the pre-proof inventory.
Recompute the exact two-file names, regular-file types, modes, sizes, and
digests as the post-proof inventory and require it to be byte-identical to the
pre-proof inventory. This
file is an intentional ownership-control artifact created before manifest
freezing; deleting it would weaken the launcher's one-screen contract and is
forbidden. Require no trainer, log, run directory, result, checkpoint, or
completion artifact. Independently validate the manifest contract:

- one arm `both`, one seed `42`, exact 50M steps;
- fresh-v5 qualification, `qualification_only=true`;
- no warm path, pool path, pool identity, or frozen bank;
- exact candidate module/backend/environment and complete patch bundle;
- exact fp32 policy shape 512 x 3 with expansion factor 1;
- exact 2,048 x 64 rollout contract and minibatch size 16,384;
- no cudagraph override and exact pinned Puffer default capture epoch 10;
- the exact immutable candidate manifest's original ordered 11-key live
  registry including `illegal_frac`, contamination budget zero, poll interval
  30 seconds, and maximum silence 180 seconds; the later stopped control
  verdict separately requires all 16 emitted counters;
- `arm_detach=0` and exact external output path.

Hash the manifest, the zero-byte released lock, the exact two-file mode/size
inventory, and every plan-only stdout/stderr/command artifact. A plan-only
rejection, missing/held/nonempty lock, unexpected file or directory, or
manifest mismatch blocks the canary.

## Gate 3: hash-bound authorization record

Create one canonical JSON authorization outside the source checkout. It must
bind, by absolute path plus SHA-256 where applicable:

- accepted off-box recovery preservation manifest and inventory identity;
- predecessor throughput baseline and its complete artifact inventory;
- candidate qualification and its complete artifact inventory;
- both independent validation outputs;
- runner, predecessor, candidate, Puffer, Python, package, module, backend,
  environment, patch, CUDA-library, driver, compiler, CPU, and GPU identities;
- exact stopped-analyzer path/hash and the separate new/empty stopped-validation
  output directory;
- canary `SCREEN_MANIFEST.json`, zero-byte released `.screen.lock`, exact
  two-file plan-only inventory, and output path;
- exact unit bytes and unit SHA-256;
- exact canary command and environment;
- `Restart=no`, `KillMode=control-group`, `ARM_DETACH=0`, and the two-hour
  service ceiling;
- an explicit statement that qualification and canary outputs are
  qualification-only, ancestry-ineligible, and reward-evidence-ineligible.

Write the authorization atomically, hash it, copy it off-box, and independently
recompute it before installing the unit. Presence without exact content does
not authorize launch.

## Gate 4: exact one-shot user unit

Materialize these semantics only after Gate 3 accepts. Substitute no path and
add no environment variable after hashing:

```ini
[Unit]
Description=Blood Bowl exact-action fresh 50M seed-42 qualification canary
After=default.target

[Service]
Type=oneshot
WorkingDirectory=/home/rache/bloodbowl-rl-qualification-candidate-a52fc6e
ExecStartPre=/home/rache/bloodbowl-rl-qualification-candidate-a52fc6e/vendor/PufferLib/.venv/bin/python /home/rache/bloodbowl-rl-qualification-control-20260722-v4/tools/qualify_recurrent_cuda.py validate /home/rache/bloodbowl-rl-qualification-artifacts-20260722/candidate-qualification/QUALIFICATION.json
ExecStartPre=/usr/bin/bash -c 'set -euo pipefail; out="$$(/usr/local/bin/nvidia-smi --query-compute-apps=pid --format=csv,noheader,nounits)"; stripped="$$(/usr/bin/printf "%s" "$${out}" | /usr/bin/tr -d "[:space:]")"; test -z "$${stripped}"'
ExecStart=/usr/bin/env -u WARM -u POOL PATH=/home/rache/bloodbowl-rl-qualification-candidate-a52fc6e/vendor/PufferLib/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin CUDA_VISIBLE_DEVICES=0 OMP_NUM_THREADS=16 OPENBLAS_NUM_THREADS=16 MKL_NUM_THREADS=16 NUMEXPR_NUM_THREADS=16 STEPS=50000000 SCREEN_PROFILE=exact-action-canary PREFIX=exact-action-canary-50m-s42-v2 OUT_DIR=/home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-50m-s42-v2 POLL_SECONDS=30 PLAN_ONLY=0 ARM_DETACH=0 /usr/bin/bash /home/rache/bloodbowl-rl-qualification-candidate-a52fc6e/tools/run_reward_screen.sh
Restart=no
KillMode=control-group
TimeoutStartSec=7200
TimeoutStopSec=60
SendSIGKILL=yes
UMask=0022

[Install]
WantedBy=default.target
```

The doubled dollars above are mandatory for this frozen contract: each `$$`
becomes one literal `$` in the Bash command. This unambiguously passes every
dollar to Bash and does not depend on systemd's positional environment-variable
expansion rules.

Before installing the real unit, construct three separately named disposable,
non-training user units outside every source/output root using the same `$$`
command-substitution and `$${name}` shell-local syntax. Replace only the probe
body: the empty-output unit must exit zero; the fixed `123` output unit must
fail; and the probe-command-nonzero unit must independently fail. Require
`systemd-analyze --user verify` on all three unit files, capture each unit's
exact bytes/status/journal separately, then remove all three and require every
unit name absent. This synthetic proof must run only after the recovery boundary
and off-box preservation; it launches no GPU process.

Then require `systemd-analyze --user verify` success for the exact real unit,
exact installed unit-byte equality with Gate 3, `systemctl --user is-enabled`
reporting disabled, and `NRestarts=0`. Do not enable the unit and do not use a
restart policy. Immediately before the one allowed start, repeat the Gate 2
exact two-regular-file inventory, size/digest checks, subshell-scoped released-
lock proof, and post-proof re-inventory; require exact equality with Gate 3 and
no third entry. Require the current manifest SHA-256 to equal the Gate 3
identity. The real launcher intentionally reuses the plan-only output: when
`SCREEN_MANIFEST.json` already exists it checks schema version 1, recomputes and
deep-compares the complete nested `contract` object, rejects any drift, and
does not rewrite it. It leaves the manifest byte-identical. Capture the
manifest SHA-256 again at the first live poll
and require exact equality with Gate 3. Any byte change or contract mismatch
rejects the canary and requires stopping the unit.

## Gate 5: launch and live monitoring

Start the exact unit once. Record start time, service properties, process group,
GPU process identity, screen status, manifest hash, log inode/size/mtime, and
BBTV health. The launcher and redundant durable live guard must enforce every
hard-integrity field at literal zero, including `illegal_frac`.

Poll without modifying the output. Fail the canary on any of:

- missing, malformed, non-finite, or nonzero hard-integrity field;
- sampled/executed exact-action disagreement or native first-transition abort;
- log truncation/replacement, stale telemetry beyond 180 seconds, unexpected
  process exit, PID/process-group drift, GPU disappearance, or a second GPU
  compute process;
- source, module, backend, environment, manifest, qualification, authorization,
  or unit drift;
- requested-step, profile, seed, optimizer, reward, precision, ABI, warm/pool,
  bank, or output-path mismatch.

On failure, preserve the atomic reason and all partial evidence. Allow the unit
and launcher's own containment path to stop the complete control group; verify
no child or GPU process remains. Do not restart, resume, repair in place, or
reuse partial checkpoints.

## Gate 6: stopped canary acceptance

After the unit exits, require inactive `Result=success`, `ExecMainStatus=0`,
`NRestarts=0`, no compute PID, and exact source/unit/authorization identity.
Require the screen's own complete validation plus all three fresh independent
stopped checks below. Run them from exact control commit `cf13fe5` with the
candidate interpreter, writing only under the separately new/empty
stopped-validation output directory:

1. Run `live_integrity_guard.py --complete-log` on the sole canary trainer log
   with new external state/failure paths. This independently rescans every
   complete schema-2 panel and requires the exact ordered 16-key control hard
   registry at literal zero without applying a stopped-log liveness deadline.
2. Run `analyze_reward_screen.py <canary-output> --json
   --expected-screen-sha <Gate-2-manifest-sha>` and atomically preserve stdout,
   stderr, and exit status. Require analysis
   `exact_action_canary_qualification`, exact one-arm seed-42 schedule, the
   fixed 2,048 x 64 rollout contract and 16,384 minibatch, final step
   49,938,432, checkpoint bytes 16,066,560, policy shape 512 x 3 x 1, fresh
   null warm/pool/banks, exact
   fp32 obs-v5/exact-joint provenance, an exactly empty failure list, both
   train/eval game floors, all 16 control hard fields at zero despite the
   immutable manifest's narrower 11-key live registry, lineage digest binding,
   and atomic completion.
3. Independently validate the final checkpoint and adjacent lineage with the
   frozen candidate CLI's actual interface:

   ```text
   checkpoint_lineage.py validate
   --checkpoint <final-checkpoint>
   --lineage <adjacent-lineage-json>
   --allow-qualification
   --expect source_sha256=<authorized-source-sha256>
   --expect compiled_module_sha256=<authorized-module-sha256>
   --expect puffer_patch_bundle_sha256=<authorized-patch-bundle-sha256>
   ```

   The three repeated `--expect` values come from the already authorized
   manifest; the frozen CLI has no expected-identity-JSON option. Require
   `qualification_only=true`, `eligible=false`, fresh initialization, and empty
   warm/pool ancestry.

Together these stopped checks must establish:

- exactly one accepted seed-42 `both` result;
- requested steps exactly 50M and executed/final steps exactly 49,938,432;
- train and cumulative final evaluation evidence present with at least 10,000
  completed evaluation games;
- every hard-integrity value exactly zero in all populated schema-2 panels;
- exact final checkpoint byte count and hash;
- fresh, pool-free, warm-free obs-v5/exact-joint run manifest;
- lineage sidecar `qualification_only=true`, `eligible=false`, initialization
  `fresh`, and empty warm/pool ancestry;
- complete output relative file set, modes, sizes, and SHA-256 inventory copied
  and verified off-box.

The accepted canary proves only that this repaired runtime can execute the
bounded fresh 50M qualification workload under the zero error budget. Its
checkpoint may not seed a long run, league, BC job, reward comparison, causal
screen, promotion decision, or BBTV production follower. Any later scientific
training requires separately created eligible obs-v5 ancestry and pool
authority.
