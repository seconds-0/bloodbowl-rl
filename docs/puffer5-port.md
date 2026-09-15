# PufferLib 5.0 port, milestone 1 (2026-09-15)

Branch `feat/puffer5-port-20260915`. PufferLib 5.0 is pinned at `6ffa5b1`
(branch 5.0, "5.0 Experiments"). This milestone is a benchmark-capable port
that trains the chain 30 algorithm on 5.0's C/CUDA trainer. It is not a
ladder-capable replacement for the 4.0 fork: see "Milestone 2".

## Layout

| Path | Purpose |
|---|---|
| `training/puffer5/adapter/bloodbowl.h` | 5.0 `ENV_HEADER` (C and C++): `pufferenv.h` ABI, `my_vec_init`, seat routing, joint-support hook |
| `training/puffer5/adapter/bloodbowl5_env.c` | C translation unit that compiles the unmodified 4.0 `binding.c` and exports `bbe5_*` |
| `training/puffer5/adapter/shim/vecenv.h` | 4.0 `vecenv.h` API shim used only by that translation unit |
| `training/puffer5/bloodbowl.ini` | chain 30 recipe and layout as 5.0 config |
| `training/puffer5/patches/0001..0008` | trainer patch series, applied in order |
| `tools/install_puffer5_env.sh` | pins `6ffa5b1`, applies the series, installs env + adapter + config, drift check |
| `tests/puffer5/env_parity/` | 4.0 vecenv vs 5.0 adapter byte parity drivers |
| `tests/puffer5/test_trainer_helpers.cpp` | host tests for the patch helpers |
| `tests/puffer5/logit_parity/` | 5.0 CPU forward vs play harness on chain 30's checkpoint |
| `tools/puffer5/bench_queue.sh`, `bench_probe.py`, `ref40_launch.py` | queued GPU benchmark |

`puffer/bloodbowl/` is untouched and still hashes to `3ed6899e` with the
installer's hash. The installer copies it to `ocean/bloodbowl/env/`. Nothing
in `puffer/bloodbowl/` compiles into the C++ trainer: the engine is C11 and not
C++ clean, so it is linked as a separate object built with the 4.0
static-library flags (`-O2 -DNDEBUG -mavx2 -mfma`).

Build on the rig:

```bash
bash tools/install_puffer5_env.sh /home/rache/bbpuffer5/PufferLib5
cd /home/rache/bbpuffer5/PufferLib5
PATH=<venv with nvidia-nccl>/bin:$PATH NVCC_THREADS=4 NVCC_ARCH=sm_75 \
    nice -n 19 ./build.sh bloodbowl --float
LD_LIBRARY_PATH=<nccl lib> ./puffer train --base.load_model_path=... \
    --selfplay.league_preseed=<pool dir>
```

## Patch series

| Patch | 4.0 behaviour ported | Test evidence |
|---|---|---|
| 0001 build | env object compiled with 4.0 flags and linked; `NVCC_THREADS` caps nvcc | rig `nvcc` build |
| 0002 exact joint | env packs legal joint support after every step; sampler samples type, then arg given type, then square given both, and writes the three conditional masks into the rollout mask row that PPO reuses (exact-joint-v1) | `test_trainer_helpers` masks match an independent prefix filter for every tuple; env support packing is the 4.0 `my_pack_joint_actions` itself, and env parity checks it byte for byte |
| 0003 frozen rows | only policy 0's rows are gathered into the training buffer, so frozen-bank and bot rows never reach advantages, value loss or policy gradient | `test_trainer_helpers`: chain 30 layout, 12 epochs at rr 1.0 and 0.25, zero frozen visits, every learner row visited, every minibatch slice in bounds |
| 0004 clamp | reward clamp `[-8, 8]` (D234) | code inspection |
| 0005 NaN guard | ratio from `clamp(logratio, -10, 10)`, raw logratio kept for KL; any non-finite PPO element gets zero gradient and loss; Muon skips momentum and weight update on a non-finite global norm (4.0 `f14b71c`) | `test_trainer_helpers` guard predicates |
| 0006 scripted bank | skips the forward for the frozen policy whose seats the env plays with the contact bot; refuses learning runs whose scripted opponent would sit on learner rows | `test_trainer_helpers` keying cases |
| 0007 warm start and league | `base.load_model_path` seeds the learner; `selfplay.league_preseed` loads bank b from `<pool>/%016d.bin` and disables resampling; weight files must match the policy size exactly | exercised by the benchmark probes |
| 0008 metrics | `PUFFER5_METRICS_JSONL` appends each trainer log as one JSON line | exercised by the benchmark probes |
| 0009 masked categories | disabled categories are excluded from the log-normalizer, sampling, entropy and gradient, as in the 4.0 exact-action patch (upstream substituted a -1e4 logit, which leaks probability once legal logits approach -1e4) | `test_trainer_helpers`: the review counterexample (singleton support at logit -1e4 now gives log-probability 0, zero entropy, zero disabled gradient) plus 200 random 391-way heads against a float64 masked log-softmax |
| 0010 padding | pad rows sized to the furthest reachable minibatch slice; refuses gathers beyond int indexing | `test_trainer_helpers`: pad 208 at rr 1.0 and 0 at rr 0.25 for chain 30, 128 for a 1920-row layout |

A Codex review (gpt-6-astra, `.codex-reviews/puffer5-port-review.md`, not
committed) reconstructed the series byte for byte from `6ffa5b1`. It found no
graph-capture race, no frozen-row leakage and no defect in the NaN-guard control
flow, seat routing or Log move. It reported four P2 defects, all fixed:
0009, 0010 (padding and int overflow), idempotent reinstall, and bytecode or
path writes from the 4.0 probe. It also corrected this document's description
of 4.0 advantages.

Recurrent evaluation state (task item e) needs no patch. 5.0's `zero_term_state`
zeroes each policy's state for terminal rows before the next observation is
encoded, in training and in evaluation, and `eval_make` builds a fresh trainer
whose `env_restart` resets every env and zeroes all policy states. Evaluation
forces `reset_every_horizon=0`, so state persists across rollout calls. That is
the 4.0 evaluation contract. For training, `bloodbowl.ini` sets
`reset_every_horizon=1` to match 4.0's `reset_state=True`.

## Seat routing (4.0 league layout in 5.0)

4.0 `selfplay.py` routes per buffer: selfplay envs first, then historical envs
in bank block order, with bank b's rows at `apb - F + b*int(apb*p)`. 5.0's
`env_setup` gives the trailing `hist_policy_percent` of each buffer's envs to
frozen policies and lays rows out by policy index. The adapter gives seat 1 of
those envs policy `1 + bank` in block order, so the physical rows match 4.0
exactly:

- `vec.num_policies = 1 + num_frozen_banks`
- `vec.hist_policy_percent = num_frozen_banks * int(apb * frozen_bank_pct) / envs_per_buffer`

Chain 30 (4 banks x 0.12, apb 1024, 512 envs per buffer): 122 rows per bank,
488 historical envs, `hist_policy_percent = 0.953125`, and 536 learner rows per
buffer (1072 of 2048). 5.0 tags an env with its largest seat policy index, which
equals the 4.0 tag (bank b is tag b+1), so `env.scripted_bank_tag=4` still puts
the contact bot on bank 3's seats.

## replay_ratio mapping

Both trainers take `replay_ratio * total_agents * horizon / minibatch_size`
gradient steps per epoch, each over `minibatch_size / horizon` learner rows:

| replay_ratio | Muon steps per epoch (2048 agents, H64, mb 16384) | rows per step |
|---|---|---|
| 1.0 | 8 | 256 |
| 0.25 | 2 | 256 |

So 5.0 `train.replay_ratio` takes the 4.0 value unchanged. What differs is
which rows a step sees:

- **4.0:** prioritized sampling with replacement over learner rows
  (`prio_alpha=0.8`, `prio_beta0=0.2` annealed, importance-weighted).
- **5.0 port:** contiguous learner-row slices in a rotated order, so coverage is
  deterministic and uniform. At rr 1.0 that is 1.91 passes per epoch over the
  1072 learner rows. Upstream 5.0 always trained rows `[0, rr*total)` and never
  the rest; patch 0003 rotates the start row every epoch.

## Algorithm differences that remain (upstream 5.0 design, not ported)

1. **Minibatch selection.** No prioritized replay and no importance weights.
2. **Advantages.** 4.0 recomputes GAE over the whole rollout buffer before every
   minibatch (with the stored ratio and values it writes back after each step),
   zeroes frozen rows, samples by priority, and normalizes advantages. 5.0
   computes GAE only over the minibatch's own rows, from the current network's
   values, and uses unnormalized advantages.
3. **Value clip gradient.** When the clipped term wins, 5.0 gives zero value
   gradient; 4.0 kept `v_clipped - ret` inside the clip range.
4. **Training-time terminal reset.** 5.0 zeroes recurrent state at terminal rows
   during training rollouts and in the train scan. 4.0 training carried state
   through a terminal until the next horizon reset.
5. **MinGRU candidate.** 5.0 uses the exact sigmoid for negative candidates;
   4.0's CUDA kernel used a fast-tanh approximation. On chain 30's checkpoint the
   two differ by at most 6.1e-5 in logits.
6. **Stale async actor.** On by default upstream; the port config sets
   `base.async=0`, and the benchmark measures both.
7. **Muon.** The code path is 5.0's (fused clip and Nesterov, per-parameter
   Newton-Schulz). Same algorithm and momentum 0.95, but not numerically
   compared with 4.0.

Items 1 to 3 change the learning dynamics, not just the plumbing. Before any
5.0 arm is compared with a 4.0 arm, either port prioritized replay and advantage
normalization or pre-register the port as a different trainer and run a bridge
screen.

## Milestone 2: what a ladder-capable port still needs

- **League and scripted bank parity.** League rotation and pool building
  (`tools/build_league.py` rotation, swap rules, snapshots, per-bank lineage
  checks), bank-boundary-aligned swaps, eval and match layouts, and a GPU
  qualification that bank rows never enter PPO: the 4.0
  `qualify_recurrent_cuda.py` checks, adapted.
- **Telemetry.** The `PUFFER_ENV_JSON` schema 2 panels, explicit train/eval phase
  and final cumulative reprint, completed-game gates, and the 16 hard integrity
  counters wired into `tools/live_integrity_guard.py`. The env already emits the
  keys through `my_log`; the trainer side is missing.
- **Python tooling replacements.** `tools/puffer_cuda_runtime.py` (CUDA init
  evidence for a C binary), `run_reward_screen.sh`/`ladder_stage.sh` launch
  contracts and manifests, the exam path (`eval_vs_contact_bot.sh` and match on
  the 5.0 CLI with exact joint sampling), module and patch-bundle provenance, and
  the queue validators.
- **Lineage graft or rehost.** 5.0 checkpoints are flat fp32 blobs with 4.0's
  registration order and shapes (chain 30's 16,066,560-byte blob loads by size).
  `checkpoint_lineage.py` needs a 5.0 producer (source hash, patch bundle, binary
  hash), and a bridge eval of the same checkpoint under both trainers must pass
  before any 5.0 curve is compared with a 4.0 one.
- **CPU play/eval binary.** `puffercpu.c` still samples heads independently from
  the marginal mask, which the env rejects; it needs the exact-joint sampler.
- **Unverified GPU paths.** Graph-on/off parity, captured-graph replay of the
  joint-support uploads, the row gather under `async=1`, and 5.0 CUDA logits
  against the CPU forward.

## Results (CPU side, 2026-09-15)

**Env parity** (`tests/puffer5/env_parity/run_parity.sh`, rig, clang 21,
4.0 flags). The 4.0 reference is the unmodified `binding.c` against the live
tree's patched `vecenv.h` (sha `ae19489b`) via `create_static_vec` and
`cpu_vec_step`. The 5.0 side is the installed adapter and env object. Each trace
records obs bytes, packed joint support per row, rewards, terminals, and the
summed Log at the end.

| Case | Result |
|---|---|
| 16 agents, 200 steps, seed 42 | byte-identical (11,644,240 bytes) |
| 16 agents, 200 steps, seed 7 | byte-identical |
| 16 agents, 200 steps, seed 42, `max_decisions=64` (24 episodes) | byte-identical |
| 64 agents, 5000 steps, seed 42 (179 episodes) | byte-identical (1.03 GB) |

**Logit parity** (`tests/puffer5/logit_parity`, Mac). 5.0's CPU network
(`src/puffercpu.c`) loads chain 30's final checkpoint (sha `41ecd998`) by size,
4,016,640 floats consumed. It is compared with the play harness torch path on
two 400-step single-env traces that include terminal resets.

| Metric | Default budget | `max_decisions=150` |
|---|---|---|
| Logits, step 0 | 1.1e-5 | 1.1e-5 |
| Logits, all steps | 1.6e-3 | 3.5e-3 |
| Per-head probability | 2.6e-5 | 3.2e-5 |
| Value | 1.7e-6 | 2.0e-6 |
| Per-head argmax agreement | 1.0 | 1.0 |

An absolute 1e-4 bound on raw logits holds for the first 11 steps and then
fails. Logits reach |1488|, where one float32 step is 1.2e-4. The recurrent
state carries rounding forward, and both float32 implementations sit 5e-3 to
1.5e-2 from a float64 reference built from the same blob. The play harness's
native (4.0 fast-sigmoid) kernel and its torch kernel differ from each other by
6.1e-5.

**Seat routing** (`tests/puffer5/seat_routing`). The adapter's routing, fed
through a verbatim copy of 5.0 `env_setup`'s layout loop, is compared with the
unmodified 4.0 `build_perm_tags` from the live `selfplay.py` (sha `69cd7fe6`).
Every env's tag and seat rows agree, and the bot seats exactly fill the skipped
policy's slice:

| Config | Result |
|---|---|
| 4 banks x 0.12, bot tag 4 (chain 30) | layout `[0, 536, 658, 780, 902, 1024]`, 244 bot seats, 0 failures |
| 8 banks x 0.06, bot tag 8 | 0 failures |
| 1 bank x 0.10 | 0 failures |

**Build.** `nvcc` 12.4, `-arch=sm_75`, `--float`, 4 threads: the trainer builds
and links, and the `--cpu` binary builds. Neither has run on the GPU yet.
