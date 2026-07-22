# RTX 2070 recurrent-CUDA qualification execution checklist

Status: prepared 2026-07-21 for execution only after the recovery queue's
atomic completion and off-box preservation. This checklist does not authorize
an early build, service change, trainer launch, checkpoint promotion, or use of
qualification/canary output as training ancestry.

## Frozen identities

| Role | Exact identity |
|---|---|
| Control runner | `286fec05d8793e9ee06228390d1fc972e81d8624` |
| Predecessor | `afc8008933548438ca93c41341f5f08fdd294386` |
| Candidate | `a52fc6e2f4ece5a7ff16bb4791e3aca4dd72f2e3` |
| PufferLib base | `9836f0d2e78889c1aaf189c04d161b6fc61a9386` |
| Python | `3.11.15` |
| Portable requirements | `7914e9637f419c1b3ff32cd9331c19b2e7ce30ab123db816fe48d50c4c3f2d7b` |
| Precision | fp32 (`precision_bytes == 4`) |
| Observation/action ABI | `obs-v5` / `exact-joint-v1` |

Target roots are pairwise distinct and outside the protected recovery tree:

```text
/home/rache/bloodbowl-rl-qualification-control-20260722
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
5. Require the portable sorted freeze with the one editable line excluded to
   equal the requirements file byte-for-byte. Also record a full sorted freeze
   after replacing the one checkout-specific editable path with a common
   `<PUFFER_ROOT>` sentinel. Predecessor and candidate normalized freezes must
   be byte-identical.
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
identity, expected predecessor identity, zero hard-integrity counters, and
positive internally consistent timing. Preserve the complete output and hashes
before constructing the candidate runtime.

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
--throughput-agents 2048
--throughput-buffers 2
--throughput-threads 16
--throughput-horizon 64
--throughput-hidden 512
--throughput-layers 3
--throughput-warmup-rollouts 2
--throughput-timed-rollouts 8
```

The runner itself rejects any regression-budget value other than 0.10. A
missing, malformed, non-finite, incomplete, nonzero-integrity, identity-drifted,
parity-failed, ratio-coverage-failed, frozen-row-selected, weight-mutated, or
throughput-regressed gate rejects qualification.

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
- the new empty canary output directory;
- exact systemd unit bytes/hash and command;
- `Restart=no`, `KillMode=control-group`, no reboot enablement;
- an `ExecStartPre` qualification revalidation and empty-GPU-process check;
- `env -u WARM -u POOL` around the exact one-seed 50M canary launcher.

The canary is fresh obs-v5, fp32, exact-joint, pool-free, warm-free, has zero
frozen banks, and has a literal zero hard-integrity budget. Qualification
artifacts remain permanently `qualification_only: true`; canary checkpoint
lineage remains `qualification_only: true`, `eligible: false`. Both are
excluded from warm starts, pools, reward evidence, and promotion decisions.
