# Frozen recurrent evaluation bridge driver

This report defines the first bounded, read-only inference bridge required by
`docs/recurrent-memory-next-tranche-2026-09-05.md`.  The driver is
`tools/bridge_recurrent_evaluation.py`.  Its final driver completed the local GPU bridge under root supervision; D331 records acceptance.

## Question and acceptance rule

The bridge asks whether the same frozen migrated chain-9 policy produces the
same evaluation trajectory under the historical `tail-bootstrap-v1` runtime
and the corrected `terminal-aware-tbptt-v1` runtime.  Evaluation already
carries recurrent state through a match and clears state at episode terminals,
so an accepted bridge requires matching behavior.  Any trace difference blocks
the subsequent learning comparison; W/D/L equality alone cannot accept it.

For every H=1 native rollout, the driver obtains the actual
`qualification_snapshot`.  It stores SHA-256 digests over the raw contiguous
observation and exact action-mask arrays, direct action/reward/terminal values
plus raw-array digests, and direct fp32 log-probability/value values plus
digests.  Corresponding observations, legal support, action tuples, and
terminals must be exact.  Rewards, log-probabilities, and values must be finite
and equal under the frozen `atol=1e-6`, `rtol=1e-6` rule.  Cell and step keys must
also match exactly.

Each runtime evaluates contact and cage scripted opponents, the learner on
home and away, and two common seeds.  Two complete games are required for each
style/side/seed cell.  This is four games per aggregated style/side cell and 16
games per runtime.  All starts use `demo_reset_pct=0`; each native rollout has
horizon one.  Every cell must report exactly its requested full games and all
16 shared hard-integrity fields at exactly zero.  The driver never calls a
training entry point.  It serializes weights before and after inference and
requires both serializations to be byte-identical to the pinned checkpoint
SHA-256. This also detects a native `load_weights` call that returns without
loading the intended file. The controller separately hashes the input
checkpoint before and after the complete bridge.

## Process and identity isolation

The controller launches two fresh subprocesses.  Each command begins with the
literal shared-venv Python path from the plan.  `PYTHONPATH` is replaced with
exactly `<runtime>/vendor/PufferLib:<runtime>/tools`, user-site imports and
bytecode writes are disabled, and the worker checks its lexical
`sys.executable`. `LD_PRELOAD` is replaced with the explicit shared-venv
`libcudart.so.12`, its bin directory leads `PATH`, and OMP/OpenBLAS threads are
fixed at 16. CUDA runtime
preflight completes before importing the native backend.  The worker then
requires native CUDA, fp32, `bloodbowl`, the arm-specific complete module
SHA-256, and the arm-specific recurrent contract.  There is no generic
validator whose current-contract constant can accidentally reject the old arm
or accept the wrong new arm.

Every cell also emits a canonical SHA-256 over its complete effective native
configuration, including the forced empty `nccl_id`. The controller requires
the ordered old/new config-hash lists to match exactly before comparing traces.

The trace is streamed as JSONL and is capped at 32 MiB before each write.  Its
completion record binds its byte count and SHA-256.  The controller independently
rehashes both traces before comparison.  Large observations and action masks
are retained through their dtype, shape, and raw-byte digest rather than JSON
float expansion.

## Intended remote freeze

The old runtime is
`/home/rache/bloodbowl-rl-improve-20260904/integrated-runtime-obs7-reducer-v1`
with module
`553c70a9bc3ad33da20c34a52bbc7c2dd58c1f286f4e3dcff51c375ca8ba690b`
and contract `tail-bootstrap-v1`.  The new runtime is
`/home/rache/bloodbowl-rl-improve-20260904/integrated-runtime-terminal-aware-v2`
with module
`651ffc40e43e669912803e2f5bb3d3e641c34c0d8b431ab0f38f8393bbc700a3`
and contract `terminal-aware-tbptt-v1`. Both use the same explicitly supplied
shared-venv Python and CUDA runtime library.

The checkpoint is
`qualification/migrated-chain9-obs7-reducer-v2-correct-bundle/0000002999975936.bin`
with expected SHA-256
`452527469879f1cfb489a8799af331f22986728a74431c0eeca488b7edb8a50e`.
It is accepted only with the explicit `qualification_only=true` and
`lineage_promotion=false` plan declarations.  Loading it for inference does not
rewrite lineage or authorize training ancestry.

After the v2 module hash is known, freeze an immutable plan with:

```bash
python tools/bridge_recurrent_evaluation.py freeze \
  --checkpoint /home/rache/bloodbowl-rl-improve-20260904/qualification/migrated-chain9-obs7-reducer-v2-correct-bundle/0000002999975936.bin \
  --checkpoint-sha256 452527469879f1cfb489a8799af331f22986728a74431c0eeca488b7edb8a50e \
  --old-runtime /home/rache/bloodbowl-rl-improve-20260904/integrated-runtime-obs7-reducer-v1 \
  --new-runtime /home/rache/bloodbowl-rl-improve-20260904/integrated-runtime-terminal-aware-v2 \
  --python /home/rache/bloodbowl-rl-improve-20260904/integrated-runtime-obs7-direct-v2/vendor/PufferLib/.venv/bin/python \
  --cudart /home/rache/bloodbowl-rl-improve-20260904/integrated-runtime-obs7-direct-v2/vendor/PufferLib/.venv/lib/python3.11/site-packages/nvidia/cuda_runtime/lib/libcudart.so.12 \
  --old-module-sha256 553c70a9bc3ad33da20c34a52bbc7c2dd58c1f286f4e3dcff51c375ca8ba690b \
  --new-module-sha256 651ffc40e43e669912803e2f5bb3d3e641c34c0d8b431ab0f38f8393bbc700a3 \
  --output BRIDGE_PLAN.json
```

Run the frozen plan only after qualification acceptance:

```bash
python tools/bridge_recurrent_evaluation.py run \
  --plan BRIDGE_PLAN.json \
  --output bridge-recurrent-evaluation-v1
```

An accepted `BRIDGE_COMPLETE.json` establishes stepwise frozen inference parity
for this bounded scripted matrix.  It does not establish a training benefit,
learned-opponent transfer, statistical confidence, checkpoint lineage
eligibility, or production promotion.

## Accepted execution

D331 records16 natural games per runtime and16,913 paired H1 snapshots. All
exact fields match raw-byte hashes; reward, value and log-probability maximum
errors are zero. All16 integrity fields are zero and every serialized weight
file matches the pinned checkpoint. Root replays the copied traces and hashes
in `audit-artifacts/memory-integration-20260905/eval-bridge-v2/`. The first
execution was rejected because the driver required an episode counter before
a game completed; the corrected startup rule preserves strict endpoint gates.
