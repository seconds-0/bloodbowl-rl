# RTX 2070 exact-action 50M canary execution checklist

Status: prepared for execution only after exact recovery preservation and an
independently accepted recurrent-CUDA qualification. This checklist does not
authorize a canary from a failed, incomplete, stale, or merely self-reported
qualification.

## Fixed scope

- Candidate source: `a52fc6e2f4ece5a7ff16bb4791e3aca4dd72f2e3`
- Candidate Git tree: `57731b2af496a4e382d263bbfe123bc219f6bd51`
- Control runner: `9274f45480d5bfff7943d3ce80fbc15c96760665`
- Runner Git tree: `30cf4d146be5e31ce450adec47e693a40c732b82`
- Runner file SHA-256:
  `c1d9ad45884754f307e58272a8d43a399ab4320a3906972f001edfc75839b740`
- Stopped analyzer SHA-256:
  `6e8fc25fe954da206a90e0cb0d1a2cff0db268f5c29b16bbad28db3c37445fb6`
- Stopped complete-log guard SHA-256:
  `e9c957ae37671bc6bfd6d09c7ef2d956736a5ead7242395f2357006bfc571ff1`
- PufferLib base: `9836f0d2e78889c1aaf189c04d161b6fc61a9386`
- Candidate root:
  `/home/rache/bloodbowl-rl-qualification-candidate-a52fc6e`
- Control root:
  `/home/rache/bloodbowl-rl-qualification-control-20260722`
- Qualification root:
  `/home/rache/bloodbowl-rl-qualification-artifacts-20260722/candidate-qualification`
- Canary output:
  `/home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-50m-s42-v1`
- Stopped-validation output:
  `/home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-50m-s42-v1-validation`
- Unit name: `bloodbowl-exact-action-canary-50m-s42-v1.service`
- Requested agent steps: exactly `50000000`
- Rollout quantum: exactly `131072` (`2048 * 64`)
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
`6e8fc25fe954da206a90e0cb0d1a2cff0db268f5c29b16bbad28db3c37445fb6`.
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
   commit `9274f45`.
4. The qualification directory is closed and its exact relative file set,
   modes, sizes, and SHA-256 inventory are fixed.
5. Candidate source, Puffer source, venv package inventory, installed Blood Bowl
   source, compiled module/backend, CUDA libraries, and build-identity artifact
   still match the accepted qualification.
6. No recovery trainer, qualification cell, evaluator, or other GPU compute
   process remains. BBTV follower state and public HTTP health are recorded.
7. The canary output path and unit name do not exist.

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
  PREFIX=exact-action-canary-50m-s42-v1 \
  OUT_DIR=/home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-50m-s42-v1 \
  POLL_SECONDS=30 PLAN_ONLY=1 ARM_DETACH=0 \
  /usr/bin/bash /home/rache/bloodbowl-rl-qualification-candidate-a52fc6e/tools/run_reward_screen.sh
```

Require exit zero and a new `SCREEN_MANIFEST.json`, but no trainer, log, run
directory, result, or completion artifact. Independently validate the manifest
contract:

- one arm `both`, one seed `42`, exact 50M steps;
- fresh-v5 qualification, `qualification_only=true`;
- no warm path, pool path, pool identity, or frozen bank;
- exact candidate module/backend/environment and complete patch bundle;
- exact fp32 policy shape 512 x 3 with expansion factor 1;
- the exact immutable candidate manifest's original ordered 11-key live
  registry including `illegal_frac`, contamination budget zero, poll interval
  30 seconds, and maximum silence 180 seconds; the later stopped control
  verdict separately requires all 16 emitted counters;
- `arm_detach=0` and exact external output path.

Hash the manifest and every plan-only stdout/stderr/command artifact. A
plan-only rejection, unexpected file, or manifest mismatch blocks the canary.

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
- canary `SCREEN_MANIFEST.json` and output path;
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
ExecStartPre=/home/rache/bloodbowl-rl-qualification-candidate-a52fc6e/vendor/PufferLib/.venv/bin/python /home/rache/bloodbowl-rl-qualification-control-20260722/tools/qualify_recurrent_cuda.py validate /home/rache/bloodbowl-rl-qualification-artifacts-20260722/candidate-qualification/QUALIFICATION.json
ExecStartPre=/usr/bin/bash -c 'set -euo pipefail; out="$(/usr/local/bin/nvidia-smi --query-compute-apps=pid --format=csv,noheader,nounits)"; stripped="$(/usr/bin/printf "%s" "$out" | /usr/bin/tr -d "[:space:]")"; test -z "$stripped"'
ExecStart=/usr/bin/env -u WARM -u POOL PATH=/home/rache/bloodbowl-rl-qualification-candidate-a52fc6e/vendor/PufferLib/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin CUDA_VISIBLE_DEVICES=0 OMP_NUM_THREADS=16 OPENBLAS_NUM_THREADS=16 MKL_NUM_THREADS=16 NUMEXPR_NUM_THREADS=16 STEPS=50000000 SCREEN_PROFILE=exact-action-canary PREFIX=exact-action-canary-50m-s42-v1 OUT_DIR=/home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-50m-s42-v1 POLL_SECONDS=30 PLAN_ONLY=0 ARM_DETACH=0 /usr/bin/bash /home/rache/bloodbowl-rl-qualification-candidate-a52fc6e/tools/run_reward_screen.sh
Restart=no
KillMode=control-group
TimeoutStartSec=7200
TimeoutStopSec=60
SendSIGKILL=yes
UMask=0022

[Install]
WantedBy=default.target
```

Before start, require `systemd-analyze --user verify` success, exact installed
unit-byte equality with Gate 3, `systemctl --user is-enabled` reporting disabled,
and `NRestarts=0`. Do not enable the unit and do not use a restart policy.

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
stopped checks below. Run them from exact control commit `9274f45` with the
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
   fixed 2,048 x 64 rollout contract, final step 49,938,432, checkpoint bytes
   16,066,560, policy shape 512 x 3 x 1, fresh null warm/pool/banks, exact
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
