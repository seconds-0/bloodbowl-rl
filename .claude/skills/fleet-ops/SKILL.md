---
name: fleet-ops
description: Operate Blood Bowl RL compute safely across the local Mac, the Tailscale RTX 2070 WSL host, and any deliberately reactivated Vast.ai instances. Use for host discovery, SSH, isolated checkout selection, process/disk/GPU preflight, source sync, Puffer rebuilds, reward-screen launch or monitoring, checkpoint/artifact transfer, hibernation, recovery, or production-process safety.
---

# Blood Bowl RL compute operations

Read `AGENTS.md`, the tail of `DECISIONS.md`, and the experiment-specific skill
before touching remote state. External inventory is live state; old host IDs,
ports, paths, roles, and process claims in the ledger are historical snapshots.

## Current topology

The paid four-box Vast fleet documented in June was stopped after D176. Do not
restart or destroy those historical instance IDs from documentation.

The current lightweight target is the Tailscale host `wsl-ubuntu` (RTX 2070).
July audit work used:

- isolated experiment checkout: `/home/rache/bloodbowl-rl-audit`;
- production/evaluator checkout: `/home/rache/bloodbowl-rl`.

Treat the production checkout and any `server.py`/stream/evaluator process as
out of scope unless the user explicitly authorizes changing it. Training access
does not imply permission to kill, rebuild, replace checkpoints for, or deploy to
the production service.

When the user explicitly authorizes BBTV to follow a reward-screen experiment,
use `stream_backend/run_follow_latest.sh` and the isolation contract in
`docs/bbtv-latest-checkpoint.md`. Never point the production stream at a native
checkpoint directly or build its float viewer module in the trainer's vendored
Puffer tree. Deploy through the reversible `bbstream.service` override, verify
the imported viewer `_C` path/hash, and preserve the static launcher as fallback.
If a delayed queue requires an empty GPU compute-PID list, build BBTV's match
viewer separately with `bloodbowl --cpu`, verify `env_name=bloodbowl`, `gpu=0`,
fp32, a real spare-port WebSocket cycle, and absence from the exact gate parser.
Hiding CUDA from a GPU-built `_C` causes the viewer to fail and is not a handoff
solution (D189).

## Discover before acting

From the Mac:

```bash
tailscale status
ssh -n -o ConnectTimeout=10 rache@wsl-ubuntu \
  'hostname; pwd; nvidia-smi; df -h /; pgrep -af "puffer|server.py" || true'
```

Before every run, record:

- exact host, user, checkout path, branch/commit, and dirty state;
- live `puffer`, Python, evaluator, stream, and watcher processes;
- GPU, driver, CUDA, OS/WSL, compiler, Python, and Torch versions;
- free disk and inode capacity;
- installed Puffer source/config hash;
- imported `_C.__file__`, `_C.env_name`, GPU flag, precision bytes, and SHA-256;
- warm checkpoint format, size, architecture, SHA-256, and conversion route;
- opponent/data/reward/plan hashes.

If the intended checkout or process ownership is ambiguous, stop before mutating
anything. Never infer that an idle-looking GPU means an existing service is safe
to replace.

## Isolated-checkout rule

Run experiments in `/home/rache/bloodbowl-rl-audit`. Keep production in
`/home/rache/bloodbowl-rl` untouched. Confirm the path in every SSH command rather
than relying on the remote shell's current directory.

Do not sync these from the Mac as generic source payloads:

- `.git/`, local virtual environments, build outputs, caches, or device binaries;
- `runs/` except intentionally selected manifests/results;
- production checkpoints, service files, secrets, or runtime logs;
- the remote replay cache unless performing a deliberate verified data transfer.

Preserve remote-only anchors and checkpoints. Use checksums before and after any
copy. Never use a destructive rsync option on a directory containing unknown
remote artifacts.

## Build and installed-snapshot discipline

`puffer/bloodbowl/` is the repository source. Puffer builds the installed snapshot
under the vendored Puffer tree, not the source directory directly.

After any environment, engine, config, or relevant Puffer-patch change:

```bash
cd /home/rache/bloodbowl-rl-audit
bash tools/install_puffer_env.sh
bash tools/install_puffer_env.sh --check
cd vendor/PufferLib
rm -rf build
./build.sh bloodbowl --float
```

Use plain `./build.sh bloodbowl` only when the experiment explicitly requires the
native bf16 CUDA backend. `--float` is required for Torch/`--slowly`. One vendored
tree holds one active `_C` build; rebuilding changes what future processes import.
Never rebuild a tree used by a live process.

After building, verify the imported extension from the exact run environment:

```bash
python - <<'PY'
from pathlib import Path
from pufferlib import _C
import hashlib
p = Path(_C.__file__).resolve()
print(p)
print('env_name', _C.env_name)
print('gpu', _C.gpu)
print('precision_bytes', _C.precision_bytes)
print('sha256', hashlib.sha256(p.read_bytes()).hexdigest())
PY
```

Do not accept a source hash as proof that Python imported the intended extension.

## Reward-screen launch contract

Use `.claude/skills/training-experiments/SKILL.md`. New reward experiments use:

- complete JSON manifests under `puffer/config/rewards/`;
- `tools/reward_manifest.py`;
- `tools/run_reward_screen.sh` and the per-arm audited launcher;
- immutable plan, status, result, checkpoint, and completion records;
- `tools/analyze_reward_screen.py` or `tools/analyze_reward_transfer.py`.

Do not use bare `tools/run_synthesis_c.sh` for a new reward arm. It contains
historical inherited reward defaults, including a legacy ball-loss penalty.
Omitted reward fields are not equivalent to explicit zeroes.

Before launch, prove:

1. no conflicting trainer is live in the isolated checkout;
2. production evaluator/stream processes will remain untouched;
3. disk can hold checkpoints, logs, and final copied artifacts;
4. install drift check passes and the imported module matches the plan;
5. the warm checkpoint and pool hashes match;
6. reward manifests are complete, canonical, and correctly assigned to arms;
7. seed/order/eval targets and integrity rejection gates are frozen;
8. `demo_reset_pct=0` for full-game final evaluation.

## Monitoring

Use `ssh -n` and an explicit connection timeout in every loop. Avoid
`pkill -f` patterns that can match the watcher itself; inspect exact PIDs and
command lines first.

Monitor all of:

- process existence and command line;
- fresh log/status mtime;
- exact native step and checkpoint cadence;
- disk usage and inode pressure;
- GPU memory/utilization and host memory;
- train/eval phase;
- completed full eval games;
- reward clip/non-finite counters;
- engine error, demo, and fallback counters;
- immutable result/checkpoint hashes.

A final training Steps line is not completion. The audited evaluator may continue
until the completed-game gate is satisfied. Do not kill it merely because the
dashboard is no longer advancing training steps. Acceptance requires the explicit
final phase/status reprint, target games, final checkpoint, and zero integrity
counters.

For a long-running user-directed goal, send a concise progress update about every
30 minutes, including active arm, steps/games, integrity state, disk, ETA, and any
decision needed. Monitoring does not authorize modifying production.

For a multi-day unattended queue, use the tracked
`training/systemd/experiment-queue@.service` in the lingering user manager.
Freeze the plan before service start and retain its SHA in atomic queue state.
Require disk, job-runtime, progress, sustained-temperature, and output-validator
guards. Use typed command/validator/environment values, recursive tree pins for
directory inputs, and explicit mutable/predecessor-artifact paths; recheck every
declared pin and use the allowlisted plan environment. Every invocation is a
pinned executable plus pinned runner; literal values are only numbers,
lowercase SHA-256 digests, or long flags. Test interruption
recovery, completed-artifact drift, and fail-closed suppression of later jobs
before handoff. `Restart=on-failure` recovers a runner crash; a deliberate
queue halt must exit normally and remain stopped for inspection. Recheck linger,
Tailscale online/key-expiry state, enabled BBTV services, disk/inodes, journal
size, and GPU thresholds immediately before departure.

Freeze the concrete July queue with `tools/freeze_vacation_queue.py`; do not
write a substitute plan on-box. The audit host's experiment tree can be an
artifact-preserving source snapshot without `.git`. Deploy a merged source
archive without deleting `runs/`, checkpoints, or vendor artifacts, verify all
tracked archive paths by checksum, and record `.deployed-source.json`. Do not
report that tree as an exact Git checkout merely because its tracked bytes match.
The frozen plan marks PPO screen jobs non-resume-safe and only atomic,
restart-validating transfer/gate jobs resume-safe. Queue-owned reward screens
must set `ARM_DETACH=0`: the queue creates a new process group for each job, and
an inner `setsid`, daemonizer, or supervisor would evade per-job runtime,
thermal, progress, and capacity termination even if a later systemd service stop
could still clean the cgroup.

The primary freezer has exactly three reviewed evidence routes. An accepted
simplification produces the six-job candidate route. A decomposition result
that recommends `both` and records an empty eligible-candidate list produces
only the two-job R0 control route: `control-final`, `12B x seeds 42/43/44`, once
per ancestry. That fallback has no candidate-transfer input, learned-transfer
input, or gate; both PPO jobs remain non-resume-safe. Its source decomposition
screen must carry the same recursive config-tree, default-config, and exact
nine-file runtime identity as every other freezer input. Never accept a legacy
partial-provenance screen or partial transfer matrix: reference must be `both`
and candidates must be exactly `possession_only`, `gain_only`, and `neither`.
Never hand-edit the frozen plan or substitute a rejected reward candidate.

The third primary route, `confirmation-rejected-baseline`, applies only when the
already-selected candidate fails its unchanged paired confirmation and emits
the same two R0 jobs after independently reproducing that failure. If measured
throughput leaves time after the exact primary queue completes, D186 permits a
separate additive-only overflow built by `tools/freeze_vacation_overflow.py`:
one unchanged `control-final` screen from the exact netblock pool-bank ancestry.
Arm its tracked watcher timer only after negative and success smokes. It must
require primary-service inactivity, the exact primary plan/state/artifacts and
validators, unchanged overflow pins, no prior overflow state, and an idle GPU.
Never modify a file pinned by the live primary queue, start concurrent training,
or allow the timer to relaunch existing state.

A persisted queue halt is terminal across restart and reboot. Do not edit its
state to resume it. Preserve the evidence and deploy a new reviewed queue
ID/plan/state after diagnosis if the user-authorized experiment should continue.

For D215/D216 overflow recovery, never deploy into or write under
`/home/rache/bloodbowl-rl-audit`. Use the exact merged source in the isolated
`/home/rache/bloodbowl-rl-recovery-20260719` root and the queue ID
`vacation-r0-overflow-recovery-20260719-v1`. Freeze and record a new plan hash;
the first queue job must validate the old terminal evidence before the fresh
three-seed trainer starts. Prove old hashes unchanged before and after setup,
require the exact reviewed recovery root, and keep BBTV CPU-only and
observational. The frozen preflight must use its exact pinned `nvidia-smi` and
revalidate an empty compute-process list immediately before advancing to PPO;
the complete seven-file Puffer patch bundle must be pinned too. Never copy old
mutable state into the recovery root, reuse the old rejected checkpoint as
output, or run old and new trainers concurrently.
Install the separately rooted `experiment-recovery-queue@.service`; the existing
`experiment-queue@.service` is audit-root-only. Configure the CPU BBTV follower
to search both checkpoint roots while writing its state/cache under the recovery
root. Execute the launcher and follower from the exact merged recovery checkout
and set `BBTV_ROOT=/home/rache/bloodbowl-rl` only for unchanged production
runtime assets. Verify the live command includes both checkpoint roots and the
recovery state dir, and that it keeps the last complete old matchup until a
newer complete recovery checkpoint is available.
Use `docs/vacation-operator-runbook.md` for the exact read-only snapshot,
state-to-action matrix, overflow watcher grace period, BBTV fault isolation,
and return-day sequence. It is deliberately non-authorizing: do not improvise
an in-place PPO restart, manual overflow start, evidence cleanup, or concurrent
evaluation.

For the active July vacation preparation/run, append an operational handoff to
`docs/vacation-progress.md` at least hourly: timestamp, live service/job state,
completed work, blockers, and exact next steps. This journal never substitutes
for immutable experiment manifests, result files, or completion proofs.

## Checkpoints and transfer

Select checkpoints by embedded step plus manifest/hash, not newest mtime. Verify
observation lineage, source/module identity, size, and architecture before
loading. Current source uses obs-v5 at 2782 bytes. Obs-v4 is also 2782 bytes but
semantically incompatible; active historical/live v4 runs remain valid only in
their deliberately pinned v4 runtime. Flat checkpoint shape cannot distinguish
v4 from v5. Older obs-v3 is shape-incompatible unless deliberately converted
with the correct `--obs-size 1612`.

Native↔Torch conversion is lossy with respect to biases: native-to-Torch
zero-fills them and Torch-to-native drops them. Apply conversions symmetrically,
record both hashes, and do not call a converted policy bit-identical unless the
round trip was actually verified.

Pull compact artifacts to the Mac after acceptance:

- plan/completion proof;
- result or analysis JSON;
- final logs needed for audit;
- selected final checkpoints;
- hashes and environment metadata.

Do not pull entire checkpoint trees by default. Verify local hashes against the
remote manifest before freeing space. Keep remote disk below the experiment's
80% guardrail.

## Vast.ai fallback

Only use Vast when the user asks or the experiment plan explicitly authorizes paid
capacity. Discover with current CLI state:

```bash
vastai show instances --raw
vastai show user --raw
```

Do not trust June labels, IDs, ports, balances, or roles. Stopped instances can be
reclaimed. `destroy` is irreversible and requires explicit user authorization.
Before stopping any instance, copy/hash irreplaceable checkpoints and replay data.
Before provisioning, establish a spend cap, teardown condition, and idle guard.

If a new Vast instance is intentionally created, run `tools/fleet.sh setup`, then
verify what its excludes did not transfer. Anchors, checkpoints, caches, virtual
environments, and builds are often remote-only and must be handled deliberately.

## Recovery and handoff

When a run dies:

1. preserve the log, status/result JSON, command line, core dump, and last
   checkpoint before relaunching;
2. classify clean cap, evaluator still running, out-of-disk, OOM, source drift,
   integrity rejection, or actual crash;
3. do not relaunch from a different config or checkpoint under the same arm ID;
4. use the immutable resume mechanism, if supported, and record the new process;
5. re-run acceptance analysis from artifacts rather than eyeballing the dashboard.

At handoff, state exact paths/hashes, what remains live, what was copied, tests and
acceptance gates passed, limitations, and whether anything was committed, deployed,
promoted, stopped, or destroyed.
