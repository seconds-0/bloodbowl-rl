# RTX 2070 recurrent-CUDA qualification execution checklist

Status: recovery boundary complete and preserved; schema-3 recapture pending a
merged D224 control/candidate commit. This checklist does not authorize a
trainer launch, checkpoint promotion, or use of qualification/canary output as
training ancestry. Any older literal runner/candidate identity below is a
historical rejection record, not current execution authority.

The first schema-3 predecessor capture failed before timing or GPU work because
the immutable predecessor's compiled attribute used its historical backend
registry while the runner recomputed the expanded registry containing
`pufferlib/selfplay.py`. Preserve its empty output and rejection record; never
retry, overwrite, or reuse that directory. Schema 3 now requires both a
role-correct compiled-source digest and a complete runtime-source digest. The
runtime digest always includes `selfplay.py` for predecessor and candidate and
is independently revalidated from disk.
The rejected schema-3 target is
`/home/rache/bloodbowl-rl-qualification-artifacts-20260722-schema3/predecessor-throughput`;
its rejection record is
`predecessor-throughput-attempt1-rejection.txt` in that artifact root with
SHA-256 `efc013889b4e2eab008210f9b0b7387728bab82349515bce7d93b4e33238d26f`.
Neither path is an input or retry target.

## Frozen identities

| Role | Exact identity |
|---|---|
| Control runner | `<newly merged clean D224 commit>` |
| Predecessor | `afc8008933548438ca93c41341f5f08fdd294386` |
| Candidate | same full commit as control runner, in a separate clean checkout |
| PufferLib base | `9836f0d2e78889c1aaf189c04d161b6fc61a9386` |
| Python | `3.11.15` |
| Portable requirements | `7914e9637f419c1b3ff32cd9331c19b2e7ce30ab123db816fe48d50c4c3f2d7b` |
| Precision | fp32 (`precision_bytes == 4`) |
| Observation/action ABI | `obs-v5` / `exact-joint-v1` |
| CUDA graph warmup | exactly 10 epochs before capture |

Freeze the newly merged control/candidate commit, tree, runner SHA-256, and all
source identities before creating new remote roots. The runner rejects an
operator-supplied candidate commit unless it equals its own clean `HEAD` and
the separate clean candidate checkout. Record the predecessor's existing
historical compiled-source digest and the complete runtime-source digest; do
not rebuild it merely to change the compiled attribute.

The earlier control roots are retained as immutable rejection evidence. The
first root, at commit `9274f45480d5bfff7943d3ce80fbc15c96760665`, proved
that the old runner dereferenced the explicitly supplied venv Python symlink
and therefore launched the managed base interpreter without the venv's
packages. Its rejected empty output is preserved only at
`/home/rache/bloodbowl-rl-qualification-artifacts-20260722/predecessor-throughput-attempt1-rejected-python-resolve`. The
second root, at commit `ffa49adfd71644fe3ffa10106df1fcdc7421b0c7`, fixed
that interpreter defect but attempted the complete 131,072-transition rollout
as one learner minibatch, rather than matching the canary's fixed 16,384
minibatch, and failed before any transition with a CUDA allocation error. Its
rejected output is preserved only at
`/home/rache/bloodbowl-rl-qualification-artifacts-20260722/predecessor-throughput-attempt2-rejected-cuda-oom`. A third root,
at commit `2261cd4c707733679b9482d2ab52eca3088afd54`, fixed the
allocation mismatch but treated Puffer's `cudagraphs` warmup-epoch count as a
boolean and requested capture at epoch zero. First-use CUDA library allocation
therefore invalidated the capture before any timing evidence; its rejected
output is preserved only at
`/home/rache/bloodbowl-rl-qualification-artifacts-20260722/predecessor-throughput-attempt3-rejected-cuda-graph-capture`.
The authorized `<artifacts>/predecessor-throughput-v2` target must remain absent
before the corrected capture. None of the old runners is an executable
qualification authority. Only the merged runner identity above may create new
throughput or qualification evidence.

The predecessor installer SHA-256 is
`577434b35c785cdb271647434ad974f1cb57f3a6dde3620d8f176d3aaa5be119`.
The pre-merge candidate installer SHA-256 is
`aeafca4e191bb88d97fd7aa4b1664d42ad1ee560467d240608975804e67a5094`;
rehash it from the final merged commit before deployment and reject any
unexpected difference. Both commits carry identical `tools/cpu_cap.sh` bytes
with SHA-256
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

The predecessor source commit contains the league patch file, but its
historical installer does not apply it; its Puffer runtime must retain the
upstream/unpatched `selfplay.py`. It also lacks the two qualification-era patch
files. The current candidate must apply and prove full reverse applicability
for all three patches below; freeze their order from the merged installer's
emitted manifest:

| Order | Patch | SHA-256 |
|---:|---|---|
| current | `training/selfplay_league.patch` | `ffaad9b6ea7f5d1dd9436783ad1b6b0d958482c5c108bd662c028a17ff2a39a5` |
| current | `training/puffer_frozen_prio_mask.patch` | `602b719cbfbb76c4ac27d2f5227ff00ee22c8b5d9ab4ea9b90767b29ea87ee67` |
| current | `training/puffer_recurrent_cuda_qualification.patch` | `5bc310ce914d5167eb69d6b62e772d9bfbedf95cbf1cf283bd3f1be2b989976f` |

Re-hash these files from each detached outer checkout before installation and
record the exact ordered inventory in each external build-identity record.
Any absence, addition, reordering, or digest mismatch rejects that runtime.

Target roots are pairwise distinct and outside the protected recovery tree:

```text
/home/rache/bloodbowl-rl-qualification-control-20260722-v6
/home/rache/bloodbowl-rl-qualification-predecessor-afc8008-schema3
/home/rache/bloodbowl-rl-qualification-candidate-<merged-D224-short-sha>
/home/rache/bloodbowl-rl-qualification-artifacts-20260722-schema3-v2
```

The control runner remains clean and unchanged. Predecessor and candidate each
own a separate ignored `vendor/PufferLib` checkout and `.venv`. Output
directories are external, new, and empty.
The listed predecessor root is the existing already-built, exact, clean-checked
schema-3 predecessor and is reused read-only for the corrected capture. Do not
recreate, reinstall, or rebuild it under D224. If it is absent or any identity
or installer check drifts, stop for separate review. Only the v6 control root,
new merged-commit candidate root, and schema3-v2 artifact root are newly
created.

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
   candidate must additionally apply the self-play league patch,
   frozen-priority masking, and then the qualification patch. Record ordered
   patch names and SHA-256 values.
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
complete runtime-source hash, environment/installed-snapshot hash, ABIs,
precision, qualification-surface role, resolved CUDA-library hashes, CPU
model/quota/affinity/thread variables,
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
--output <artifacts>/predecessor-throughput-v2
--predecessor-source-root <predecessor>
--expected-predecessor-source-commit afc8008933548438ca93c41341f5f08fdd294386
--expected-predecessor-module-sha256 <frozen predecessor module SHA-256>
--expected-predecessor-backend-sha256 <frozen predecessor backend SHA-256>
--expected-predecessor-runtime-sha256 0bf5c09cdc5507bbdf28b3c4c470349c1fecca6b742d2252c27416f7250d14c8
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
--throughput-minibatch-size 16384
--throughput-warmup-rollouts 2
--throughput-timed-rollouts 8
```

Require `THROUGHPUT_BASELINE.json`, its confined cell record, exact runner
identity, expected predecessor identity, literal zero for the exact ordered
16-key control hard-integrity registry, and positive internally consistent
timing. The runner itself rejects any operator-supplied throughput minibatch
other than 16,384. Require the emitted configuration to bind that exact value,
exactly 10 uncaptured graph-warmup epochs before capture, and a canonical
configuration hash for equality with the candidate throughput cell. A zero
warmup or graph-disabled timing record is invalid even if internally
self-consistent. Preserve the complete output and hashes before constructing
the candidate runtime.

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
--baseline-throughput <artifacts>/predecessor-throughput-v2/THROUGHPUT_BASELINE.json
--candidate-source-root <candidate>
--predecessor-source-root <predecessor>
--expected-source-commit <newly merged clean D224 control/candidate commit>
--expected-candidate-module-sha256 <frozen candidate module SHA-256>
--expected-candidate-backend-sha256 <frozen candidate backend SHA-256>
--expected-environment-sha256 <same frozen installed environment SHA-256>
--expected-predecessor-source-commit afc8008933548438ca93c41341f5f08fdd294386
--expected-predecessor-module-sha256 <same predecessor module SHA-256>
--expected-predecessor-backend-sha256 <same predecessor backend SHA-256>
--expected-predecessor-runtime-sha256 0bf5c09cdc5507bbdf28b3c4c470349c1fecca6b742d2252c27416f7250d14c8
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
--throughput-minibatch-size 16384
--throughput-warmup-rollouts 2
--throughput-timed-rollouts 8
```

The runner itself rejects any regression-budget value other than 0.10 and any
operator-supplied throughput minibatch other than 16,384. The predecessor and
candidate throughput configurations and configuration hashes must be exactly
equal and must bind `cudagraphs=10`. Only the explicit graph-off correctness
cell may bind `-1`; zero is rejected before backend load. Every
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
  limited to exactly two regular files: `SCREEN_MANIFEST.json` and the
  launcher's zero-byte, released, hash-bound `.screen.lock`; captured plan-only
  command/stdout/stderr evidence is external, and no trainer log, result,
  checkpoint, run directory, or completion artifact exists;
- exact systemd unit bytes/hash and command;
- `Restart=no`, `KillMode=control-group`, no reboot enablement;
- an `ExecStartPre` qualification revalidation and empty-GPU-process check;
- `env -u WARM -u POOL` around the exact one-seed 50M canary launcher.

Any Bash command embedded in a systemd unit must escape both parsers: use `$$`
where Bash must receive literal `$`, and use `%%` where Bash must receive
literal `%`. In particular, an empty-GPU `printf` format is `"%%s"` in unit
bytes; bare `"%s"` is invalid because systemd expands `%s` to the user shell.
Require the synthetic empty/fixed/command-failure probes to prove these exact
bytes before installing the real unit.

The real launch must reuse the plan-only output without rewriting its manifest:
the frozen launcher checks schema version 1, recomputes and deep-compares the
complete nested stored `contract` object, rejects any drift, and leaves
`SCREEN_MANIFEST.json` byte-identical. Immediately before unit start, repeat
the exact two-regular-file inventory and released-lock proof and require it to
match the authorization. Require the manifest hash to match immediately before
unit start and at the first live poll.

The canary is fresh obs-v5, fp32, exact-joint, pool-free, warm-free, has zero
frozen banks, and has a literal zero hard-integrity budget. Qualification
artifacts remain permanently `qualification_only: true`; canary checkpoint
lineage remains `qualification_only: true`, `eligible: false`. Both are
excluded from warm starts, pools, reward evidence, and promotion decisions.
