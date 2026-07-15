# July vacation operator runbook

This is the short operational companion to
`docs/vacation-autonomy-2026-07.md`. It does not grant authority to change a
reward, plan, state file, checkpoint, queue order, or promotion decision. Its
purpose is to make the safe response to each observable state unambiguous while
the user is away and on the return day.

Current frozen identities:

- primary queue: `vacation-r0-baseline-20260714-v1`, plan SHA-256
  `4ee72e3c58f09786cdd3bbf78a772e8de2d9a93e21a8b065cf0c5976ecced270`;
- optional overflow: `vacation-r0-overflow-20260714-v1`, plan SHA-256
  `d90ee01c8c459f599c8601934f545ccb7783261edae3bcb6e9e3878036d37d3e`;
- audit root: `/home/rache/bloodbowl-rl-audit`;
- production/BBTV root: `/home/rache/bloodbowl-rl`;
- public viewer: <https://bbtv.seconds0.com/>; and
- durable human journal: `docs/vacation-progress.md` on
  `codex/vacation-live-monitoring`.

Later ledger entries supersede this snapshot. Never copy these identifiers into
a new queue without a fresh freeze/review.

## Read-only status snapshot

Run through Tailscale from the Mac. Every SSH command is noninteractive so a
lost route fails instead of hanging:

```bash
ssh -n -o BatchMode=yes -o ConnectTimeout=10 rache@100.97.209.46 '
  date
  systemctl --user show \
    experiment-queue@vacation-r0-baseline-20260714-v1.service \
    experiment-queue@vacation-r0-overflow-20260714-v1.service \
    bbstream.service bbweb.service bbtv-tunnel.service \
    -p Id -p ActiveState -p SubState -p MainPID -p NRestarts --no-pager
  systemctl --user list-timers --all --no-pager | grep vacation-overflow
  /usr/lib/wsl/lib/nvidia-smi \
    --query-gpu=temperature.gpu,fan.speed,utilization.gpu,memory.used,memory.total,power.draw,clocks_throttle_reasons.sw_thermal_slowdown,clocks_throttle_reasons.hw_slowdown \
    --format=csv,noheader,nounits
  /usr/lib/wsl/lib/nvidia-smi \
    --query-compute-apps=pid --format=csv,noheader,nounits
  df -h /; df -i /; free -h
'
```

Then validate the exact plans and report the queue states without writing them:

```bash
ssh -n -o BatchMode=yes -o ConnectTimeout=10 rache@100.97.209.46 '
  cd /home/rache/bloodbowl-rl-audit
  vendor/PufferLib/.venv/bin/python - <<"PY"
import hashlib
import json
from pathlib import Path
import sys

queue_ids = (
    "vacation-r0-baseline-20260714-v1",
    "vacation-r0-overflow-20260714-v1",
)
plans = {}
for queue_id in queue_ids:
    plan_path = Path("runs") / queue_id / "QUEUE_PLAN.json"
    plans[queue_id] = json.loads(plan_path.read_text())

def file_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

# These imports/functions are read-only at the frozen hashes. Prove the exact
# module bytes from the plans with the standard library before importing them.
for relative in (
    "tools/experiment_queue.py",
    "tools/validate_primary_queue_completion.py",
):
    path = Path(relative).resolve()
    declared = {
        item["sha256"]
        for plan in plans.values()
        for item in plan["pinned_files"]
        if Path(item["path"]).resolve() == path
    }
    if len(declared) != 1 or file_sha256(path) not in declared:
        raise SystemExit(f"refusing unpinned monitoring import: {path}")

sys.path.insert(0, "tools")
import experiment_queue
import validate_primary_queue_completion

for queue_id in queue_ids:
    plan_path = Path("runs") / queue_id / "QUEUE_PLAN.json"
    plan = plans[queue_id]
    state_path = plan_path.with_name("QUEUE_STATE.json")
    print(queue_id)
    print(" plan_sha256", experiment_queue.sha256(plan_path))
    print(" pinned_files", len(plan["pinned_files"]))
    print(" pin_error", experiment_queue.pinned_files_error(plan))
    print(
        " state",
        state_path.read_text().strip() if state_path.exists() else "ABSENT",
    )

config = validate_primary_queue_completion.validate_config(
    Path(
        "runs/vacation-r0-overflow-20260714-v1/configs/"
        "PRIMARY_COMPLETION_CONFIG.json"
    )
)
print(
    " exact_gate_pids",
    validate_primary_queue_completion.gpu_compute_pids(
        config["nvidia_smi_path"]
    ),
)
PY
'
```

Also inspect the current trainer log's last complete `PUFFER_ENV_JSON`, newest
complete checkpoint, `runs/bbtv-follow/selection.json`, overflow watcher
journal, and public HTTP/WebSocket. A dashboard line is a sample, not a
completion artifact.

## State-to-action table

| Observed state | Safe response |
|---|---|
| Primary service active; primary state `running`; current job `running`; progress fresh; all pins valid | Observe and journal. Do not restart or edit anything. |
| Primary screen changes seed, enters final evaluation, or briefly has no `puffer train` child while the queue job remains healthy | Read the queue-owned log/status and validator phase. Do not infer failure from one process-name snapshot. |
| One temperature sample is high but below the frozen guard condition | Observe the next polls. The queue alone owns termination. The current implementation requires three consecutive polls above each plan's `max_gpu_temperature_c` (currently 88 C at a 30-second plan poll); re-read the pinned values rather than copying these numbers to a future queue. |
| Three over-ceiling polls, stale/absent progress, runtime breach, low disk/inodes, invalid output, or pin drift | Let the queue halt and clean its process group. Preserve state/logs/artifacts. Never restart the same non-resume-safe PPO job or edit state to continue. |
| Primary service inactive and primary state `complete`; overflow state absent | Allow at least two scheduled watcher intervals (currently about 11 minutes each; verify the live timer). Inspect the watcher journal, completion proof, GPU PIDs, and pins. Do not manually start overflow. |
| Overflow remains armed/state-absent after that grace period | During the vacation, diagnose and leave the reviewed timer/gate authoritative; do not evaluate. On return, only the user may choose to keep waiting or explicitly cancel the never-started overflow. A cancellation must disable the timer, record the live state/hashes and decision, and be proved before evaluation; it is not queue completion. |
| Overflow service/state `running` with fresh progress and valid pins | Observe and journal exactly like primary. Do not start milestone evaluation. |
| Overflow state exists as `halted`, `failed`, or `interrupted` | Terminal evidence. The timer must not relaunch it. Preserve it and require a new reviewed queue ID for any authorized replacement. |
| Primary or overflow state `complete`, but its recorded success artifact is missing, changed, or fails its validator | Treat as failed evidence. Do not rerun or evaluate it. |
| An unexpected GPU compute PID appears | Identify it from `/proc/<pid>` and its systemd cgroup. Do not kill an unknown process merely to satisfy the gate. BBTV must remain CPU-only under D189. |
| BBTV briefly reconnects at a checkpoint/match boundary | Observational only; wait for its bounded follower recovery. Never touch training. |
| BBTV remains down while training is healthy | Inspect `bbstream.log`, its CPU-viewer preflight, service state, and `.deployed-bbtv-source.json`. A viewer failure is not permission to change a queue. Never partially pair the CUDA-hiding follower with the old GPU viewer; the reviewed rollback is whole-override removal. |
| Tailscale/SSH is temporarily unreachable | The lingering user manager and queues continue independently. Retry read-only access; do not infer that training stopped. |
| Disk guard approaches its floor | Do not delete checkpoints, logs, manifests, state, pins, or provenance. Any cleanup requires a reviewed list outside experiment evidence. |

`Restart=on-failure` handles an ordinary queue-runner crash. A deliberate
fail-closed halt exits normally and remains stopped. A host reboot can interrupt
a non-resume-safe PPO trajectory; the correct result is preserved terminal
evidence, not an in-place continuation.

## Monitoring cadence and journal entry

During the active goal:

- send the user a concise progress update about every 30 minutes;
- append and push one full `docs/vacation-progress.md` entry at least hourly;
- record active job/seed, exact step or completed games, integrity totals,
  newest checkpoint, SPS/ETA, service/PID/restart state, both plan hashes and pin
  results, overflow state/watcher result, GPU/thermal trend, disk/inodes/memory,
  BBTV selection and public transport, completed work, blockers, and next steps;
- label BBTV and live curves observational, never promotion evidence; and
- report command/probe mistakes explicitly and rerun with the correct
  environment rather than silently omitting the check.

The hourly journal does not replace queue state, manifests, validators, or
content hashes. If monitoring loses access, record the gap and the first
authoritative state recovered afterward.

## Return-day checklist

1. Capture the complete read-only snapshot above before changing any service.
2. Hash and archive primary/overflow plan, state, logs, status files, manifests,
   success artifacts, checkpoint registries, BBTV selection/provenance, and the
   monitoring journal. Re-run both pin validators.
3. Classify every queue as `running`, accepted `complete`, terminal failure, or
   unresolved armed/state-absent overflow. If either queue is pending/running or
   overflow is unresolved, leave evaluation pending.
4. If primary is accepted complete and overflow state is still absent, allow
   the watcher grace period and diagnose its exact completion proof. The
   returning user must explicitly choose continued waiting or recorded
   cancellation/disarm; never bypass the gate with a manual start.
5. Only after primary and overflow are both terminal—or the returning user has
   explicitly cancelled a never-started overflow and the timer is proved
   disabled—require accepted `control-final` completion artifacts for each
   ancestry being characterized. A halt/failure/cancellation is not an
   evaluable completion for that ancestry.
6. Before milestone evaluation, prove the overflow watcher cannot start work
   during the idle window: its queue has terminal state or its never-started
   timer was explicitly disarmed above. Stop only `bbstream`, prove the exact
   GPU compute-PID list is empty, and freeze the predeclared evaluation
   manifest. Run the merged `tools/run_checkpoint_milestone_eval.py` from a
   separate evaluation checkout while its spec references the audit artifacts;
   never deploy the evaluator into the pinned audit snapshot. Follow
   `docs/plans/r0-milestone-evaluation.md`, and do not stop training to make
   this condition true.
7. Validate Stage A before considering Stage B. Preserve common seeds, both
   native roles, raw seed strata, fixed milestone points, and all hashes.
8. Restore `bbstream` after the evaluator releases the GPU; recheck public HTTP
   and WebSocket plus the CPU-only module/provenance contract.
9. Write the result to `DECISIONS.md` only after immutable analysis. The fixed
   milestone protocol characterizes learning and plateau behavior; it cannot
   promote a reward, mutate a queue, or change a production default.

## Actions this runbook never authorizes

- editing `QUEUE_PLAN.json`, `QUEUE_STATE.json`, a success artifact, or any pin;
- restarting a halted/interrupted PPO screen in place;
- starting overflow early or manually bypassing its watcher/completion gate;
- cancelling/disarming an absent overflow during the vacation or without the
  returning user's explicit decision and durable record;
- running evaluation while primary or overflow is pending/running;
- killing an unknown GPU process to make a validator pass;
- deleting experiment evidence to recover space;
- selecting a newest checkpoint, BBTV matchup, or attractive dashboard panel;
- generating another reward candidate during the vacation; or
- promoting R0 or any reward without the declared post-run human review.
