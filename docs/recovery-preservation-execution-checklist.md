# Recovery evidence preservation execution checklist

This checklist applies only to the stopped recovery queue
`vacation-r0-overflow-recovery-20260719-v1`. It does not authorize an early
stop, a live-log scan, a trainer restart, a reward decision, or training from
any copied artifact.

## Frozen identities

- Recovery root:
  `/home/rache/bloodbowl-rl-recovery-20260719`
- Queue root:
  `/home/rache/bloodbowl-rl-recovery-20260719/runs/vacation-r0-overflow-recovery-20260719-v1`
- Queue-plan SHA-256:
  `822bb912dbf3992c5fa6f04ddcaa5354897db10d03f2e66934b846c198b6a111`
- Pinned Python SHA-256:
  `2c676ebca162bd6ead9ca5319723f2e89a1110b327db51fb0e07f2f1c49f162a`
- Frozen `validate_vacation_artifact.py` SHA-256:
  `328a45ff3d21e9398a651b15d9e52f0217aeaa8698d7dddfa2189fd256a84ca9`
- Frozen screen-config SHA-256:
  `0081e295cdda5158f177d9c509072ad136a6c5d09869c6812b96efa7e97e778d`
- Post-stop tools merge commit:
  `c1600adadf416063020bff0e35e3633835f2b8a5`
- `audit_recovery_complete_logs.py` SHA-256 at that commit:
  `96657dba08ab2be243ff4e8c703b3b7f9fdb0e75b1540af34ba5224c894db2f8`
- `recovery_preservation.py` SHA-256 at that commit:
  `9b8f767e461234733c27dd030b8be7da3f52b224c3b765bacdc9b5e59a4b0402`
- Local evidence destination:
  `/Users/alexanderhuth/BloodBowlRLArtifacts/recovery-preservation-20260719-c1600`
- Remote external tools directory:
  `/home/rache/bloodbowl-rl-poststop-tools-c1600`
- Local detached tools checkout:
  `/Users/alexanderhuth/Code/bloodbowl-rl-poststop-tools-c1600`

The local filesystem had 56 GiB free at the 2026-07-21 20:25 PDT preflight.
The stopped copy is expected to be well below that, but capacity must be
rechecked before transfer. The local `/usr/bin/rsync` is openrsync protocol 29
and lacks `--from0`; the remote rsync is 3.4.1. The validated manifest forbids
newlines and carriage returns in paths, so the emitted NUL list may be converted
to a newline list locally before passing it to `--files-from`.

## Gate 1: establish the external atomic boundary

Do not proceed until all of these are simultaneously true:

1. `QUEUE_STATE.json` has schema 1, `state=complete`, `current_job=null`, exact
   message `all queued jobs completed and validated`, exact queue and plan
   identity, and exactly the two completed jobs with exit code zero and success
   digests.
2. User service
   `experiment-recovery-queue@vacation-r0-overflow-recovery-20260719-v1.service`
   is inactive with `Result=success`, `ExecMainStatus=0`, and `NRestarts=0`.
3. `work/full-control/SCREEN_COMPLETE.json` exists as a regular file.
4. Trainer PID 653090 is absent and `nvidia-smi` reports no compute process.
5. The original queue, trainer, BBTV, web, and tunnel PID/restart history is
   captured locally before any post-stop service action.

Capture the queue state, relevant `systemctl --user show` output, process list,
GPU process list, completion artifact identity, BBTV selection, disk/RAM state,
and UTC/local timestamps directly into the new local evidence directory. If
any predicate differs, stop. Do not repair or reinterpret the recovery tree.

## Gate 2: run the exact frozen screen validator

Re-hash the pinned Python, frozen validator, frozen screen config, and queue
plan and require exact equality with the identities above. Then run exactly:

```text
/home/rache/.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/bin/python3.11 \
  /home/rache/bloodbowl-rl-recovery-20260719/tools/validate_vacation_artifact.py \
  --screen \
  /home/rache/bloodbowl-rl-recovery-20260719/runs/vacation-r0-overflow-recovery-20260719-v1/configs/FULL_CONTROL_SCREEN_CONFIG.json \
  /home/rache/bloodbowl-rl-recovery-20260719/runs/vacation-r0-overflow-recovery-20260719-v1/work/full-control/SCREEN_COMPLETE.json
```

Capture stdout, stderr, exit code, command, and hashes locally. Any nonzero
exit or identity mismatch rejects the boundary.

## Gate 3: independently audit all stopped logs

Only after Gate 2 passes, place the two post-stop tools in a new directory
outside the recovery root. Source them from a clean detached checkout of exact
commit `c1600ada`, copy no dependency tree, and require the two exact hashes
above on both machines.

Run the independent auditor with the pinned Python, the explicit three logs,
the explicit count, and the inclusive 10,000-game floor:

```text
/home/rache/.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/bin/python3.11 \
  /home/rache/bloodbowl-rl-poststop-tools-c1600/tools/audit_recovery_complete_logs.py \
  --expected-count 3 \
  --min-eval-games 10000 \
  ...full-control-both-s42.log \
  ...full-control-both-s43.log \
  ...full-control-both-s44.log
```

Use full absolute log paths in the real command. Capture stdout, stderr, exit
code, exact command, and the auditor hash locally. Require `accepted=true`,
exactly three distinct scanned logs, at least 10,000 completed evaluation games
per log, and exact zero for all 15 hard-integrity fields. `illegal_frac` remains
reported historical diagnostic data and is not silently promoted into a gate
for this pre-exact-action lineage. Any scan instability or nonzero exit rejects
the boundary.

## Gate 4: build the source inventory

With Gates 1--3 still accepted, run the merged planner from the external tools
directory using the pinned Python:

```text
/home/rache/.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/bin/python3.11 \
  /home/rache/bloodbowl-rl-poststop-tools-c1600/tools/recovery_preservation.py plan \
  --recovery-root /home/rache/bloodbowl-rl-recovery-20260719 \
  --queue-dir /home/rache/bloodbowl-rl-recovery-20260719/runs/vacation-r0-overflow-recovery-20260719-v1 \
  --bbtv-selection /home/rache/bloodbowl-rl-recovery-20260719/runs/bbtv-follow/selection.json \
  --output /home/rache/bloodbowl-rl-poststop-evidence-c1600/recovery-inventory.json
```

The output directory must be new and outside the recovery root. Capture the
planner's JSON stdout locally. Require `accepted=true`; record its manifest-file
SHA-256, inventory SHA-256, file count, and byte count. Copy the manifest alone
to the new local evidence envelope and require its local SHA-256 to equal the
planner's recorded output SHA-256 before using it.

## Gate 5: transfer exactly the inventory

Using exact commit `c1600ada` locally:

1. Run `recovery_preservation.py emit-files` into `files.nul`.
2. Convert NUL separators to newlines into `files.txt`. This is lossless because
   the manifest validator rejects newline, carriage-return, and NUL path bytes.
3. Run local `/usr/bin/rsync -a --files-from=files.txt` with the remote recovery
   root as source and a new empty `copy/` directory as destination.
4. Capture rsync command, stdout, stderr, exit code, source/destination free
   space, and the manifest/list hashes locally.

Do not add `--ignore-errors`, `--ignore-missing-args`, an exclude, a newest-file
heuristic, or a second source root. A transfer error rejects the copy.

## Gate 6: verify the off-box copy

Run exact `c1600ada` locally:

```text
/opt/homebrew/bin/python3.11 \
  /Users/alexanderhuth/Code/bloodbowl-rl-poststop-tools-c1600/tools/recovery_preservation.py verify \
  recovery-inventory.json \
  --copy-root copy
```

Require exit zero, `accepted=true`, and exact equality of file count, total
bytes, and inventory SHA-256 with Gate 4. The verifier requires the exact file
set, regular non-symlink files, modes, sizes, and content hashes, then repeats
the file-set and identity checks after hashing. Preserve the verifier output
and a SHA-256 index of every envelope file locally.

Only after Gate 6 passes is recovery evidence preservation complete. The source
recovery tree remains read-only and retained. The copied recovery checkpoints
remain evidence only: they are not qualification inputs, canary ancestry, or
reward-promotion authority.

## After preservation

Reconfirm all evidence hashes and journal the exact accepted identities. Only
then may `bbstream.service` be briefly stopped to remove its CPU match-server
load from the frozen predecessor/candidate throughput comparison. Keep BBTV web
and tunnel services intact; restart and verify the follower and public viewer
after independent CUDA qualification validation.
