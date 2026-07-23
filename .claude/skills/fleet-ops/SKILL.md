---
name: fleet-ops
description: Operate Blood Bowl RL compute on the local Mac and the Tailscale RTX 2070 WSL host (plus optionally reactivated Vast.ai instances). Use for host access, isolated checkout selection, process/disk/GPU preflight, source sync, Puffer rebuilds, run launch and monitoring, liveness checks, checkpoint/artifact transfer, and recovery after a run dies.
---

# Blood Bowl RL compute operations

## The box

There is one GPU: an RTX 2070 in WSL on the Tailscale host `wsl-ubuntu`.

```bash
tailscale status
ssh -n -o ConnectTimeout=10 rache@100.97.209.46 'hostname; nvidia-smi; df -h /'
```

`rache@100.97.209.46` is the working route. The `wsl-ubuntu` name only resolves when
Tailscale DNS is up, so prefer the IP in scripts.

Two checkouts live on it:

- `/home/rache/bloodbowl-rl-audit` — experiments. Use this one.
- `/home/rache/bloodbowl-rl` — may be running the BBTV/eval `server.py`. Leave it alone
  unless the user asks for it. Training access is not permission to kill, rebuild, or
  redeploy that service.

Confirm the checkout path in every SSH command rather than trusting the remote shell's
cwd. An idle-looking GPU does not mean an existing service is safe to replace.

The June four-box paid Vast fleet was stopped after D176; the instance IDs in old ledger
entries are dead. Discover live state instead of restarting anything from documentation.

## Preflight before a run

Record, from the exact host and environment the run will use:

- checkout path, branch/commit, dirty state;
- live `puffer`, Python, evaluator, stream, and watcher processes (with command lines);
- GPU/driver/CUDA, OS/WSL, compiler, Python, Torch versions;
- free disk **and inodes**;
- installed Puffer source/config hash (`tools/install_puffer_env.sh --check`);
- the imported `_C.__file__`, `_C.env_name`, `_C.gpu`, `_C.precision_bytes`, SHA-256;
- warm checkpoint format, size, SHA-256, and its `.lineage.json`;
- reward manifest, opponent, and data hashes.

If checkout or process ownership is ambiguous, stop before mutating anything.

`tools/cpu_cap.sh` fixes the WSL/cgroup thread-thrash footgun (visible CPUs ≫ allowed
CPUs → unpinned BLAS/torch pools cost ~5× SPS, D59). Launch scripts source it; a manual
`puffer train` must `. tools/cpu_cap.sh` first. Verify the live trainer's
`OMP_NUM_THREADS` equals the quota and its thread count is ~150–190, not hundreds.

## Sync and build discipline

`puffer/bloodbowl/` is the source; the build compiles the **installed snapshot** under
the vendored Puffer tree. An edit without a re-install silently trains on stale rules.

```bash
cd /home/rache/bloodbowl-rl-audit
bash tools/install_puffer_env.sh
bash tools/install_puffer_env.sh --check     # drift guard; exit 1 = re-install
cd vendor/PufferLib && rm -rf build && ./build.sh bloodbowl --float
```

`--float` (fp32) is required for the Torch backend and for the recurrent CUDA
qualification; plain `./build.sh bloodbowl` is bf16 native CUDA, which is what
`puffer match` needs. Never skip `rm -rf build` — stale objects survive a plain rebuild.
Sync `engine/` and `puffer/bloodbowl/` **together**; a header without its `binding.c`
builds a stale mixture. After syncing, `grep` the changed symbol on the box to prove the
right code landed, then install + rebuild there.

One vendored tree holds one active `_C`. Never rebuild a tree a live process is using.

Verify what Python actually imported — a source hash proves nothing about the loaded
extension:

```bash
python - <<'PY'
import hashlib
from pathlib import Path
from pufferlib import _C
p = Path(_C.__file__).resolve()
print(p, _C.env_name, _C.gpu, _C.precision_bytes,
      hashlib.sha256(p.read_bytes()).hexdigest())
PY
```

### CUDA init order (D225 — the real WSL trap)

In a fresh WSL process, importing `_C` **before** the first CUDART call leaves that
process reporting `cudaErrorNoDevice`, even though the host GPU is fine. A separate
`nvidia-smi`, Torch, or probe process proves nothing about the worker. Every trainer and
qualification worker must enter through `tools/puffer_cuda_runtime.py`: require
`cudaSuccess` with a positive device count *before* the native import, keep the resolved
CUDART handle, import, then require the same count afterwards. Record the CUDART
path/hash and `CUDA_VISIBLE_DEVICES` with the run. A failed probe should exit the process,
not try to repair it.

## Launch contract

The experiment side lives in `training-experiments`. Before launch, prove on the box: no
conflicting trainer in the isolated checkout; the production evaluator/stream will be
untouched; disk and inodes hold checkpoints + logs + copied artifacts; the install drift
check passes and the imported module matches the plan; warm checkpoint and pool hashes
match; every reward manifest is complete and assigned to the right arm; seeds, order, and
eval targets are fixed; `demo_reset_pct=0` for full-game final evaluation. Never launch a
new reward arm through bare `tools/run_synthesis_c.sh` — it carries a legacy ball-loss
penalty, and an omitted reward field is not an explicit zero.

## Monitoring

Use `ssh -n` and an explicit `ConnectTimeout` in every loop, or it will hang forever.

**Liveness is log MTIME, never log content.** A finished trainer leaves its log frozen at
the final dashboard forever, so any content-grepping monitor reports "running" indefinitely
(two arms idle-billed 8–13h this way, D65). Gate on `stat -c %Y <log>` age (>360s stale =
done or dead) **and** a real process check.

For the process half, use the PID the launcher recorded — `run_reward_ablation.sh` writes
`{"pid":…,"process_group":…}` next to the run — and `kill -0 <pid>`. Do **not** reach for
`pgrep -xc puffer` on a current arm: these runs exec
`python tools/puffer_cuda_runtime.py train bloodbowl …`, so the process is not named
`puffer` and does not contain the string `puffer train`. `pgrep -xc puffer` and
`pgrep -f 'puffer [t]rain'` only match the historical direct-CLI launches.

**Use bracket patterns in pgrep/pkill** whenever you do pattern-match, e.g.
`pkill -f '[r]un_synthesis'` — a bare `pkill -f puffer` matches the watcher's own command
line. One-trainer-per-host is enforced by the launcher's `flock` on
`/tmp/bloodbowl-rl-*.lock`, which (unlike the pgrep guard beside it) still holds for
wrapper-launched trainers.

Watch: process existence and command line; log/status mtime; native step and checkpoint
cadence; disk and inode pressure; GPU memory/utilization and host memory; train vs eval
phase; completed full eval games; reward clip and non-finite counters; engine-error,
demo, and fallback counters; result/checkpoint hashes.

`tools/live_integrity_guard.py` is the kill switch, and it runs twice: from the screen
poll loop and from a watchdog beside the detached trainer, so losing the outer screen
does not remove the bound. It scans each new machine panel, stops the trainer's process
group on any hard-field failure, and writes `LIVE_INTEGRITY_FAILURE.json`. 180 seconds
without an integrity-bearing panel is itself a failure; metadata-only startup panels do
not reset that clock. The two watchers use independent incremental state files and share
the failure artifact. Before treating the GPU as idle, check the wrapper's exit status
and the absence of its trainer child.

**A final training `Steps` line is not completion.** The audited evaluator keeps running
until the completed-game gate is satisfied; do not kill it because the dashboard stopped
advancing. Acceptance needs the explicit final phase/status reprint, the requested games,
the final checkpoint, and zero integrity counters.

For a fresh runtime, run the staged CUDA checks before a long run: exact-zero primary and
frozen-bank recurrent state after graph warmup; deterministic graph-on/off first outputs;
fresh train→eval games; primary/frozen first-post-terminal equivalence to zero state;
Torch/native parity; finite exact zero-update PPO ratios; target-GPU throughput. Training
requires `reset_state=True` with evaluation mode off. Then a disposable 50M-step canary.

When Bash lives inside a systemd unit, remember the second escape layer: `$$` delivers
one literal `$` and `%%` one literal `%`, so an intended `printf "%s"` must be written
`printf "%%s"` in the unit (bare `%s` is systemd's user-shell specifier).

For an unattended multi-day run, use the tracked
`training/systemd/experiment-queue@.service` with `tools/experiment_queue.py`: literal
commands, per-job max runtime, disk/inode, mtime-progress, thermal, and process-group
guards. Queue-owned screens set `ARM_DETACH=0`; never add an inner `setsid`, daemonizer,
or supervisor, which would escape those guards. `Restart=on-failure` recovers a runner
crash. Before departure, recheck linger, Tailscale key expiry, enabled BBTV services,
disk/inodes, journal size, and GPU thresholds.

## BBTV (the stream), when asked

Use `stream_backend/run_follow_latest.sh` and `docs/bbtv-latest-checkpoint.md`. Never
point the production stream at a native checkpoint directly, and never build its float
viewer module inside the trainer's vendored Puffer tree. Deploy through the reversible
`bbstream.service` override, verify the imported viewer `_C` path/hash, and keep the
static launcher as fallback. If the viewer must stay off the GPU, build it with
`build.sh bloodbowl --cpu` and verify `env_name=bloodbowl`, `gpu=0`, fp32, and a real
WebSocket cycle — hiding CUDA from a GPU-built `_C` just makes it fail (D189).

## Checkpoints and transfer

Select a checkpoint by the **step number embedded in its filename** plus its manifest
hash. Newest mtime ≠ highest step across run dirs.

Current source is obs-v5 at 2782 bytes. **Obs-v4 is also 2782 bytes and semantically
incompatible**, so shape proves nothing: require the adjacent `.lineage.json` and
validate it with `tools/checkpoint_lineage.py` before any warm start or pool seed.
Qualification-only checkpoints are never warm starts or pool seeds. Obs-v3 checkpoints
are shape-incompatible and need an explicit `--obs-size 1612` conversion. The
exact-action canary runs with `WARM` and `POOL` unset (`env -u WARM -u POOL`) and zero
frozen banks.

Native↔Torch conversion is lossy for biases (native→Torch zero-fills, Torch→native
drops). Convert both sides symmetrically, record both hashes, and don't call a converted
policy bit-identical unless you verified the round trip.

Pull compact artifacts to the Mac after acceptance: plan/completion record, result or
analysis JSON, the logs needed for audit, selected checkpoints, hashes and environment
metadata. Don't pull whole checkpoint trees. Verify local hashes against the remote
manifest before freeing remote space, and keep remote disk under ~80%.

Do not sync as generic source payloads: `.git/`, venvs, build outputs, caches, device
binaries, `runs/` (except selected manifests/results), production checkpoints, service
files, secrets, or the remote replay cache. Preserve remote-only anchors and checkpoints,
checksum before and after any copy, and never use a destructive rsync flag on a directory
holding unknown remote artifacts. `tools/fleet.sh setup` will clobber a box's demo state
bank with the Mac's, and its `bb-<name>` matching silently no-ops on a typo (D65) —
confirm the rsync actually ran and re-check `Loaded N demo states` afterwards.

## Vast.ai fallback

Only with explicit user request or an experiment plan that authorizes paid capacity.

```bash
vastai show instances --raw
vastai show user --raw
```

Do not trust June labels, IDs, ports, or balances. Stopped instances can be reclaimed
(GPU re-rented) — restart promptly or accept a replacement. `destroy` is irreversible and
needs explicit authorization; copy and hash irreplaceable checkpoints and replay data
first. Set a spend cap and teardown condition before provisioning. `vastai` CLI < 1.0
(brew 0.4) creates zombie instances — check the version. After `tools/fleet.sh setup` on
a new instance, verify what the excludes did not transfer.

## Recovery

When a run dies:

1. preserve the log, status/result JSON, command line, core dump, and last checkpoint
   before relaunching;
2. classify it: clean step cap, evaluator still running, out of disk, OOM, source drift,
   integrity rejection, or a real crash;
3. don't relaunch a different config or checkpoint under the same arm ID;
4. re-run acceptance analysis from artifacts, not by eyeballing the dashboard.

At handoff, state exact paths and hashes, what is still live, what was copied, which gates
passed, the limitations, and whether anything was committed, deployed, or stopped.
