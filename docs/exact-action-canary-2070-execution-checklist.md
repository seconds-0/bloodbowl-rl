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
- Fresh v3 execution-evidence root:
  `/home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-v3-execution`
- Fresh v3 authorization destination:
  `/home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-v3-execution/CANARY_AUTHORIZATION.json`
- Canonical v3 unit source:
  `/home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-v3-execution/bloodbowl-exact-action-canary-50m-s42-v3.service`
- Unit name: `bloodbowl-exact-action-canary-50m-s42-v3.service`
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

The first v2 Gate 3 authorization and unit bytes are also immutable rejection
evidence. The plan-only output itself remains accepted and unchanged, but the
first synthetic empty-output unit exposed that systemd expands `%s` to the user
shell before Bash. Its journal recorded a `printf` excess-argument warning and
status 1. The cleanup trap removed all three disposable probe units; the real
v2 unit was never installed or started, GPU compute remained empty, and BBTV
remained active. Preserve but never install/reuse:

| Rejected artifact | Absolute path | SHA-256 |
|---|---|---|
| Gate 3 authorization | `/home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-v2-execution/CANARY_AUTHORIZATION.json` | `3af34715cfa0cc848c0c8ba2effa48a2916f0c1059d0760dcef3a97fb1030d91` |
| v2 unit bytes | `/home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-v2-execution/bloodbowl-exact-action-canary-50m-s42-v2.service` | `00e9c32cde253d8f3639c13985d3e30d181e40735cd027678afd9399e46e274a` |
| Probe runner | `/home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-v2-execution/gate4-synthetic-probes.sh` | `134f4cb066d43dd6e30e910b07e2da30308ffd89a8dbf8fd6939ecd1d1b2e5c9` |
| Empty-probe journal | `/home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-v2-execution/gate4-attempt1-empty-journal.txt` | `20f306a4c042e7fea8ed1fec3107eeb048ecf6ace212a1c82172f42cd32de9ed` |
| Post-cleanup proof | `/home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-v2-execution/gate4-attempt1-post-cleanup.txt` | `9f019876e51a9810c2ddcafa72afbbe96b623c9fc9c970c46a0c73f192f8bf42` |
| Rejection record | `/home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-v2-execution/gate4-attempt1-rejection.txt` | `0592a95210e094c7942ffaa9af53a10d8e274991553e47e2366a5fa714902b0e` |

Only a newly hash-bound authorization and the fresh v3 unit identity above may
proceed. The corrected unit writes `%%s`, which systemd reduces to literal `%s`
for Bash. This changes only external unit authority; it does not alter or
rematerialize the accepted v2 plan manifest, candidate runtime, or launcher.
The entire rejected v2 execution root is immutable. Every newly created
prelaunch v3 validator capture, canonical unit/probe copy, authorization,
inventory, status, and journal must be preserved under the fixed, initially
absent v3 execution-evidence root. Transient systemd-manager unit files must
live in the manager's required unit-file directory and be removed when the
checklist requires; Gate 6 artifacts must be written only to the separately
authorized stopped-validation output; launcher-owned live artifacts remain in
the accepted canary output. No new evidence may be appended to the v2 execution
root.

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

Re-hash all six before Gate 2 revalidation and again immediately before unit
installation. Any mismatch rejects the canary.

## Gate 1: accepted prerequisites

All of the following must be captured and hash-bound before Gate 2
revalidation:

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
7. The accepted v2 canary output exists as exactly the unchanged regular
   `SCREEN_MANIFEST.json` and zero-byte released `.screen.lock` described in
   Gate 2. The fresh v3 execution-evidence root and exact v3 unit name do not
   exist. The exact superseded v1 unit identity named above is also absent from
   the user systemd manager and its unit-file directory, and the original
   pre-rejection v1 output path
   `/home/rache/bloodbowl-rl-qualification-artifacts-20260722/exact-action-canary-50m-s42-v1`
   is absent rather than copied alongside its renamed rejection directory.
8. Recompute the five rejection-only evidence hashes and both canonical
   inventories above from their exact paths; every value must still match.
9. Recompute the rejected Gate 3/unit/probe hashes in the second table. Require
   the superseded v2 unit identity absent from the manager and unit-file
   directory, and require the accepted v2 plan-only manifest, lock, and exact
   two-file inventories unchanged. Require the fixed stopped-validation output
   to exist as an empty directory and bind that empty state before launch; do
   not delete or recreate it merely to satisfy this check.

Any mismatch stops deployment. Do not delete or overwrite an existing output
to make the precondition true.

## Gate 2: revalidate the accepted plan-only positive launch proof

Do not rerun the launcher and do not rematerialize its output. The accepted
plan-only invocation was run once from the exact candidate root with its venv
first on `PATH`, `PLAN_ONLY=1`, `ARM_DETACH=0`, and an explicitly empty inherited
warm and pool environment. Its frozen command was:

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

Recompute the preserved command/stdout/stderr/status hashes and require the
recorded exit zero. Require exactly two regular files directly under the
accepted output:
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
inventory, and every preserved plan-only stdout/stderr/command artifact. Run
the independent manifest validator twice again from fresh candidate-interpreter
processes and require byte-identical accepted output. Only after all preceding
read-only checks accept, atomically create the exact previously absent v3
execution-evidence root. Persist each fresh validator's stdout, stderr, and
status separately under that root as
`gate2-validator-{1,2}.{stdout,stderr,status}`; require both status files encode
zero, both stderr files are empty, and both stdout files are byte-identical.
Close and hash the resulting six-file relative-name/type/mode/size/digest set
before Gate 3. A changed plan-only artifact, missing/held/nonempty lock,
unexpected file or directory, validator disagreement, or manifest mismatch
blocks the canary. Rerunning the launcher,
deleting the lock, or rewriting the manifest is forbidden.

## Gate 3: hash-bound authorization record

First require the exact v3 execution-evidence root to contain only Gate 2's
closed six-file validator set, and require both the canonical v3 unit source and
authorization destination from Fixed scope absent. Atomically write the exact
unit bytes shown in Gate 4 to the canonical v3 unit source, then create one
canonical JSON authorization at the exact fixed v3 destination outside the
source checkout. It must bind, by absolute path plus SHA-256 where applicable:

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
- exact unit name `bloodbowl-exact-action-canary-50m-s42-v3.service`, exact unit
  bytes, and unit SHA-256;
- exact canary command and environment;
- `Restart=no`, `KillMode=control-group`, `ARM_DETACH=0`, and the two-hour
  service ceiling;
- an explicit statement that qualification and canary outputs are
  qualification-only, ancestry-ineligible, and reward-evidence-ineligible.

Write the unit and authorization atomically at their fixed v3 destinations,
hash them, copy the authorization off-box, and independently recompute it before
installing the unit. Bind the
v3 execution-evidence root's exact relative file set, modes, sizes, and
digests after each gate. Presence without exact content, a different unit name,
or any new artifact under the rejected v2 execution root does not authorize
launch.

## Gate 4: exact one-shot user unit

Install only the already hash-bound canonical unit bytes below as
`bloodbowl-exact-action-canary-50m-s42-v3.service` after Gate 3 accepts.
Substitute no path or unit name and add no environment variable after hashing:

```ini
[Unit]
Description=Blood Bowl exact-action fresh 50M seed-42 qualification canary
After=default.target

[Service]
Type=oneshot
WorkingDirectory=/home/rache/bloodbowl-rl-qualification-candidate-a52fc6e
ExecStartPre=/home/rache/bloodbowl-rl-qualification-candidate-a52fc6e/vendor/PufferLib/.venv/bin/python /home/rache/bloodbowl-rl-qualification-control-20260722-v4/tools/qualify_recurrent_cuda.py validate /home/rache/bloodbowl-rl-qualification-artifacts-20260722/candidate-qualification/QUALIFICATION.json
ExecStartPre=/usr/bin/bash -c 'set -euo pipefail; out="$$(/usr/local/bin/nvidia-smi --query-compute-apps=pid --format=csv,noheader,nounits)"; stripped="$$(/usr/bin/printf "%%s" "$${out}" | /usr/bin/tr -d "[:space:]")"; test -z "$${stripped}"'
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
expansion rules. The doubled percent in `%%s` is independently mandatory:
systemd reduces `%%` to one literal `%`, while bare `%s` is its user-shell
specifier and must never appear in an operative `ExecStartPre` format string.

Before installing the real unit, construct three separately named disposable,
non-training canonical probe units under the v3 execution-evidence root using
the same `$$` command-substitution, `$${name}` shell-local syntax, and `%%s`
format escape. Install transient copies only in the systemd user manager's
required unit-file directory; never place them in a source, canary-output, or
stopped-validation root.
Reject any probe bytes containing bare `printf "%s"`. Replace only the probe
body: the empty-output unit must exit zero; the fixed `123` output unit must
fail; and the probe-command-nonzero unit must independently fail. Require
`systemd-analyze --user verify` on all three unit files, capture each unit's
exact bytes/status/journal separately, then remove all three and require every
unit name absent. This synthetic proof must run only after the recovery boundary
and off-box preservation; it launches no GPU process.

Then require `systemd-analyze --user verify` success for the exact canonical
real unit, copy it to the manager without changing a byte,
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
