# RTX 2070 recurrent-CUDA qualification execution checklist

Status: prepared 2026-07-21 for execution only after the recovery queue's
atomic completion and off-box preservation. This checklist does not authorize
an early build, service change, trainer launch, checkpoint promotion, or use of
qualification/canary output as training ancestry.

## Frozen identities

| Role | Exact identity |
|---|---|
| Control runner | `ffa49adfd71644fe3ffa10106df1fcdc7421b0c7` |
| Predecessor | `afc8008933548438ca93c41341f5f08fdd294386` |
| Candidate | `a52fc6e2f4ece5a7ff16bb4791e3aca4dd72f2e3` |
| PufferLib base | `9836f0d2e78889c1aaf189c04d161b6fc61a9386` |
| Python | `3.11.15` |
| Portable requirements | `7914e9637f419c1b3ff32cd9331c19b2e7ce30ab123db816fe48d50c4c3f2d7b` |
| Precision | fp32 (`precision_bytes == 4`) |
| Observation/action ABI | `obs-v5` / `exact-joint-v1` |

The corresponding outer Git tree identities are runner
`dd06117b77a4d15b5deb1770f86a465dc04338d0`, predecessor
`f89318a58c9038a888419f9a0720478c1cf1a325`, and candidate
`57731b2af496a4e382d263bbfe123bc219f6bd51`. The frozen control-runner
`tools/qualify_recurrent_cuda.py` SHA-256 is
`4b8519da01edcff7ee203e8114b3ef4aa8fb673df63cb9ce0b83e34baa6ba646`.

The earlier control root at commit `9274f45480d5bfff7943d3ce80fbc15c96760665`
is retained as immutable rejection evidence. Its first predecessor capture
proved that the old runner dereferenced the explicitly supplied venv Python
symlink and therefore launched the managed base interpreter without the venv's
packages. The rejected empty output is preserved only at
`<artifacts>/predecessor-throughput-attempt1-rejected-python-resolve`; the
authorized `<artifacts>/predecessor-throughput` target must remain absent before
the corrected capture. The old runner is not an executable qualification
authority. Only the merged runner identity above may create new throughput or
qualification evidence.

The predecessor installer SHA-256 is
`577434b35c785cdb271647434ad974f1cb57f3a6dde3620d8f176d3aaa5be119`.
The candidate installer SHA-256 is
`de7bf4769cba18c127cb2278d8bbf9cb2f62508bcdde876341c6fe0f6a20d08f`.
Both commits carry identical `tools/cpu_cap.sh` bytes with SHA-256
`75ec32025777510523dc1e0d160d7a011fb4275792d15f20564afe99fe5e1907`.

The common ordered patch inventory is byte-identical in both roles:

| Order | Patch | SHA-256 |
|---:|---|---|
| 1 | `training/sweep_match_mode_exclusion.patch` | `b1e181201ea4046f60225e8bfcdec9f11b3b86ff4b80d5413cc749e931a15945` |
| 2 | `training/pufferl_env_dashboard_limit.patch` | `02d4d057072c89ad4787d70e875211146ce8994204d29840310000b0d7dfea2f` |
| 3 | `training/pufferl_env_json.patch` | `a739d6e5c4bd44112d1510dc81f8fffd6cddb9ccfdba12811d9e9993653ad936` |
| 4 | `training/pufferl_env_json_metadata_upgrade.patch` | `41aca69045d0105ce4f7f710b6e0934bd2981866cdfa76c60c3a7a60de9faade` |
| 5 | `training/pufferl_env_phase_contract.patch` | `65706562c1c52febac07220fe41860ab4a8669a53e0aeaf87850022c0bc0b674` |
| 6 | `training/pufferl_eval_episode_gate.patch` | `bfadd8623635daad604bc33a4a20c8cb41739b5b062b58dc92745485bf512904` |
| 7 | `training/pufferl_metrics_keyerror.patch` | `05c4b67e7f82618c4ce1acb8a0daefe907e6f55f6dbf017e3cf823ae43d8b57a` |
| 8 | `training/torch_pufferl_trusted_load.patch` | `75a8aa7fad40d91336646e2b71e0bb51fa93251cec3c7683fb6e414cadc17f1e` |
| 9 | `training/puffer_exact_joint_actions.patch` | `d6c32180ee89f75d6cb885fd6aaa4d98c0d5a57e0722637636775565e924e0eb` |
| 10 | `training/puffer_recurrent_eval_state.patch` | `b24ec966dd8d6058067080ff37c3057198bfe8ac1e778999fcd91394fc253b61` |

The predecessor commit contains neither candidate-only patch. The candidate
must then apply, in order:

| Order | Patch | SHA-256 |
|---:|---|---|
| 11 | `training/puffer_frozen_prio_mask.patch` | `602b719cbfbb76c4ac27d2f5227ff00ee22c8b5d9ab4ea9b90767b29ea87ee67` |
| 12 | `training/puffer_recurrent_cuda_qualification.patch` | `5bc310ce914d5167eb69d6b62e772d9bfbedf95cbf1cf283bd3f1be2b989976f` |

Re-hash these files from each detached outer checkout before installation and
record the exact ordered inventory in each external build-identity record.
Any absence, addition, reordering, or digest mismatch rejects that runtime.

Target roots are pairwise distinct and outside the protected recovery tree:

```text
/home/rache/bloodbowl-rl-qualification-control-20260722-v2
/home/rache/bloodbowl-rl-qualification-predecessor-afc8008
/home/rache/bloodbowl-rl-qualification-candidate-a52fc6e
/home/rache/bloodbowl-rl-qualification-artifacts-20260722
```

The control runner remains clean and unchanged. Predecessor and candidate each
own a separate ignored `vendor/PufferLib` checkout and `.venv`. Output
directories are external, new, and empty.

## Boundary gate

Do not create any target root until all of the following are true and recorded:

1. `QUEUE_STATE.json` has `state=complete`, `current_job=null`, exact message
   `all queued jobs completed and validated`, and both jobs complete with
   success SHA-256 values.
2. `experiment-recovery-queue@vacation-r0-overflow-recovery-20260719-v1.service`
   is inactive after successful exit, with no restart or failed result.
3. `work/full-control/SCREEN_COMPLETE.json` exists.
4. The exact pinned Python and recovery checkout's frozen
   `validate_vacation_artifact.py --screen` command accept it.
5. The stopped three-log `audit_recovery_complete_logs.py` scan accepts with
   explicit `--min-eval-games 10000`.
6. The complete queue directory, three result-bound final checkpoints and run
   manifests, final BBTV selection, service/process/GPU snapshot, and journal
   are copied off-box. Remote and local relative file sets and SHA-256
   inventories are exactly equal.

## Reproducible runtime construction

For each outer source checkout:

1. Clone the repository, detach at the exact role commit, and require exact
   `HEAD` plus empty `git status --porcelain --untracked-files=all`.
2. Clone PufferLib only into that checkout's `vendor/PufferLib`, detach at the
   exact Puffer pin, and record its origin URL, `HEAD`, and clean pre-install
   status.
3. Create only that Puffer root's `.venv` using the exact managed Python:

   ```text
   /home/rache/.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/bin/python3.11
   ```

4. Verify the requirements file is 63 lines, sorted, and has the frozen
   portable SHA-256. Sync it with uv 0.11.19 and `--strict --torch-backend
   cu128`, then install only the source-local Puffer tree editable with
   `--no-deps --no-build-isolation` so the already pinned setuptools performs
   the editable install.
5. Preserve the raw sorted freeze first. The cu128 index reports the installed
   Torch build as `torch==2.10.0+cu128`, while the portable input requirements
   intentionally pin `torch==2.10.0`; this single deterministic local-version
   suffix is the only permitted raw difference after excluding the editable
   line. Create and preserve a separate requirements-normalized freeze by
   changing exactly that line to `torch==2.10.0`, then require byte equality
   with the requirements file. Also record a full sorted freeze after replacing
   the one checkout-specific editable path with a common `<PUFFER_ROOT>`
   sentinel. Predecessor and candidate raw-portable hashes,
   requirements-normalized hashes, and full sentinel-normalized hashes must be
   pairwise identical by representation. Any other difference rejects the
   runtime.
6. If wheel libraries lack development links, create only these exact local
   links inside the venv after verifying their targets exist:

   ```text
   libcudnn.so -> libcudnn.so.9
   libnccl.so  -> libnccl.so.2
   ```

   Record resolved target paths, sizes, and SHA-256 values for both runtimes.
7. Put the role venv first on `PATH`, run `hash -r`, source that exact commit's
   byte-verified `tools/cpu_cap.sh`, set `CUDA_VISIBLE_DEVICES=0`, and set
   `CCACHE_DISABLE=1`.
8. Run that exact source's `tools/install_puffer_env.sh` in install mode. The
   predecessor must apply exact actions and recurrent-state hardening only; the
   candidate must additionally apply frozen-priority masking followed by the
   qualification patch. Record ordered patch names and SHA-256 values.
9. From the source-local Puffer root, remove only its `build/` directory and
   run `./build.sh bloodbowl --float`. Do not use the recovery Puffer tree or a
   module from another checkout.
10. Run the same source-local installer with `--check`. Require imported module
    containment in the role's Puffer root, `precision_bytes == 4`, `env_name ==
    bloodbowl`, `obs-v5`, observation version 5, and `exact-joint-v1`.
    Predecessor must lack both qualification calls; candidate must expose both.

Before any behavioral cell, atomically write an external build-identity record
containing outer commit/tree, Puffer pin, ordered patch hashes, normalized
package hashes, Python/uv/Torch/CUDA package versions, driver and compiler
versions, module path/hash, compiled and independently recomputed backend hash,
environment/installed-snapshot hash, ABIs, precision, qualification-surface
role, resolved CUDA-library hashes, CPU model/quota/affinity/thread variables,
GPU name/bus ID, and installer-check stdout/stderr digest.

## Comparable host state

Immediately before each timed phase:

1. Preserve the current BBTV selection and follower service state.
2. Stop only `bbstream.service`; keep the web and tunnel services intact.
3. Require no competing evaluator or trainer and a literally empty
   `nvidia-smi --query-compute-apps=pid` result.
4. Require the same 16-CPU affinity, infinite CPU quota, thread variables all
   equal to 16, `CUDA_VISIBLE_DEVICES=0`, and loader environment.
5. Require three samples ten seconds apart with temperature at or below 55 C,
   utilization exactly 0%, and no compute PID, then record temperature, clocks,
   power, memory, utilization, driver, disk, RAM, and all process identities.
   Do not loosen the threshold for one role.

Restore and verify the BBTV follower and public viewer after each bounded timed
phase unless the next phase is beginning immediately under the same recorded
host condition.

## Predecessor throughput capture

Run the frozen control-runner script under the predecessor interpreter and pass
the predecessor interpreter again through `--python`. The output directory must
not already exist. Pass:

```text
capture-throughput
--puffer-root <predecessor>/vendor/PufferLib
--python <predecessor>/vendor/PufferLib/.venv/bin/python
--output <artifacts>/predecessor-throughput
--predecessor-source-root <predecessor>
--expected-predecessor-source-commit afc8008933548438ca93c41341f5f08fdd294386
--expected-predecessor-module-sha256 <frozen predecessor module SHA-256>
--expected-predecessor-backend-sha256 <frozen predecessor backend SHA-256>
--expected-environment-sha256 <frozen installed environment SHA-256>
--seed 271828
--ratio-call-limit 64
--cell-timeout-seconds 1800
--throughput-agents 2048
--throughput-buffers 2
--throughput-threads 16
--throughput-horizon 64
--throughput-hidden 512
--throughput-layers 3
--throughput-warmup-rollouts 2
--throughput-timed-rollouts 8
```

Require `THROUGHPUT_BASELINE.json`, its confined cell record, exact runner
identity, expected predecessor identity, literal zero for the exact ordered
16-key control hard-integrity registry, and positive internally consistent
timing. Preserve the complete output and hashes before constructing the
candidate runtime.

## Candidate qualification

After building and freezing the candidate identity, reproduce the same BBTV,
GPU, thermal, CPU, and environment preconditions. Run the same unchanged
control-runner script under the candidate interpreter and pass the candidate
interpreter through `--python`. The qualification output directory must not
already exist. Pass:

```text
run
--puffer-root <candidate>/vendor/PufferLib
--python <candidate>/vendor/PufferLib/.venv/bin/python
--output <artifacts>/candidate-qualification
--baseline-throughput <artifacts>/predecessor-throughput/THROUGHPUT_BASELINE.json
--candidate-source-root <candidate>
--predecessor-source-root <predecessor>
--expected-source-commit a52fc6e2f4ece5a7ff16bb4791e3aca4dd72f2e3
--expected-candidate-module-sha256 <frozen candidate module SHA-256>
--expected-candidate-backend-sha256 <frozen candidate backend SHA-256>
--expected-environment-sha256 <same frozen installed environment SHA-256>
--expected-predecessor-source-commit afc8008933548438ca93c41341f5f08fdd294386
--expected-predecessor-module-sha256 <same predecessor module SHA-256>
--expected-predecessor-backend-sha256 <same predecessor backend SHA-256>
--max-regression-fraction 0.10
--seed 271828
--ratio-call-limit 64
--cell-timeout-seconds 1800
--throughput-agents 2048
--throughput-buffers 2
--throughput-threads 16
--throughput-horizon 64
--throughput-hidden 512
--throughput-layers 3
--throughput-warmup-rollouts 2
--throughput-timed-rollouts 8
```

The runner itself rejects any regression-budget value other than 0.10. Every
transition-executing cell—graph off/on, terminal automatic/control, ratio, and
throughput—must bind the exact ordered 16-key control registry at literal zero;
construction is the sole exemption because it performs no transition and emits
no episode telemetry. A missing, malformed, non-finite, incomplete,
nonzero-integrity, identity-drifted, parity-failed, ratio-coverage-failed,
frozen-row-selected, weight-mutated, or throughput-regressed gate rejects
qualification.

## Independent validation and canary boundary

Run `validate <candidate-qualification>/QUALIFICATION.json` from the same clean
control checkout using the candidate interpreter. Capture stdout, stderr, exit
status, and all artifact hashes. Rerun the exact validation once from a fresh
process after hashing the closed artifact directory.

Only an independently recomputed `accepted: true` verdict authorizes creation
of a separate canary authorization record. That record must bind:

- the preserved recovery inventory path and SHA-256;
- the accepted qualification path and SHA-256;
- runner, predecessor, candidate, Puffer, module, backend, environment,
  package, host, and library identities;
- the exact plan-only canary output path, whose already authorized contents are
  limited to `SCREEN_MANIFEST.json` plus captured plan-only command/stdout/
  stderr evidence and contain no trainer log, result, checkpoint, or completion
  artifact;
- exact systemd unit bytes/hash and command;
- `Restart=no`, `KillMode=control-group`, no reboot enablement;
- an `ExecStartPre` qualification revalidation and empty-GPU-process check;
- `env -u WARM -u POOL` around the exact one-seed 50M canary launcher.

The canary is fresh obs-v5, fp32, exact-joint, pool-free, warm-free, has zero
frozen banks, and has a literal zero hard-integrity budget. Qualification
artifacts remain permanently `qualification_only: true`; canary checkpoint
lineage remains `qualification_only: true`, `eligible: false`. Both are
excluded from warm starts, pools, reward evidence, and promotion decisions.
