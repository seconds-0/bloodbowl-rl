---
name: puffer-env-dev
description: Develop and audit the Blood Bowl PufferLib 4.0 environment — binding macros, buffers, action masks, exact joint sampling, self-play routing, builds, the config surface, the local patch stack and its order, log/telemetry contract, train/eval/match CLI, and checkpoint conversion. Use for native C binding work or any Puffer training/evaluation correctness question.
---

# PufferLib 4.0 Native C Env Development

We target the **4.0 macro ABI in `vendor/PufferLib/src/vecenv.h`**. Almost every online
tutorial describes the old 3.0 pattern (`env_binding.h`, Gymnasium emulation,
`pufferlib.vector.make`, Python env classes) — **none of that exists anymore**. See
"4.0 vs 3.0" at the bottom before trusting any external article.

Primary template: `vendor/PufferLib/ocean/chess/` (2-player board game, action masking,
self-play perm, FEN curriculum — structurally closest to Blood Bowl).
Minimal: `ocean/squared/`. MultiDiscrete: `ocean/drive/`.
Cached upstream docs: `docs/vendor/pufferlib/docs.html`.

For observation work also read `docs/obs-v6-spec.md` (and `docs/obs-v5-spec.md` for the
v4→v5 delta it builds on). Obs-v6 keeps the same 2,782-byte shape and spends the scalar
bytes v5 left zero, so **blob size cannot distinguish any of v4/v5/v6** — require exact
source/module identity plus `BBE_OBS_VERSION`, and never treat a shape-loadable v4 or v5
checkpoint or pair shard as v6.

## 1. The binding ABI

A 4.0 env = `ocean/<name>/<name>.h` (all game logic) + `ocean/<name>/binding.c` (macros +
glue) + `config/<name>.ini`. `binding.c` defines macros **then** includes `vecenv.h`, whose
implementation only compiles `#ifdef OBS_SIZE` (vecenv.h:164).

```c
#include "bloodbowl.h"
#define OBS_SIZE 167          // flat obs length per agent slot
#define NUM_ATNS 1            // number of action heads (MultiDiscrete dims)
#define ACT_SIZES {97}        // logits per head; brace list, len == NUM_ATNS
#define OBS_TENSOR_T ByteTensor  // ByteTensor|FloatTensor|IntTensor|LongTensor (src/tensor.h)
                              // MUST be a literal "#define OBS_TENSOR_T X" line in binding.c —
                              // build.sh:273 awk-greps it out of binding.c (won't see a .h)
#define MY_ACTION_MASK 97     // optional: mask bytes per slot == sum(ACT_SIZES)
#define MY_VEC_INIT           // optional: you provide my_vec_init (else default, vecenv.h:350)
#define MY_VEC_CLOSE          // optional: you provide my_vec_close
#define MY_USES_PERM          // optional: self-play pool routing (you provide my_setup_perm)
#define MY_USES_TAGS          // optional: env has `int tag; int boundary_reached;`
#define Env BloodBowl         // your env struct name
#include "vecenv.h"

void my_init(Env* env, Dict* kwargs) { /* read [env] ini keys via dict_get */ }
void my_log(Log* log, Dict* out)     { dict_set(out, "perf", log->perf); /* ... */ }
```

Required Env fields (see `ocean/squared/squared.h:32`): `Log log;` (first is conventional),
`observations` (pointer of your obs dtype), `float* actions; float* rewards; float*
terminals;`, `int num_agents;`, `unsigned int rng;` — plus `unsigned char* action_mask;` if
MY_ACTION_MASK and `int tag; int boundary_reached;` if MY_USES_TAGS.

Required functions in your `.h`: `c_reset`, `c_step`, `c_render`, `c_close`. `c_close` must
NOT free observations/actions/rewards/terminals — the vec owns them (vecenv.h:422-440).

Dict kwargs gotchas: `dict_get` **asserts** the key exists (vecenv.h:47-52), so every key
your `my_init`/`my_vec_init` reads must be in the ini `[env]` section. `dict_set` stores the
key **pointer**, not a copy (vecenv.h:61) — keys must be string literals
(`ocean/chess/binding.c:193-196`).

## 2. Buffer layout / stepping contract

`create_static_vec` (vecenv.h:402) allocates one contiguous buffer per stream across all
`total_agents` slots, then hands each env base+stride pointers (vecenv.h:466-491):

| buffer       | per-slot stride                | dtype                  |
|--------------|--------------------------------|------------------------|
| observations | `OBS_SIZE * sizeof(obs elem)`  | your OBS_TENSOR_T      |
| actions      | `NUM_ATNS` floats              | **always float** — cast `(int)env->actions[h]` |
| rewards      | 1 float                        | float                  |
| terminals    | 1 float (0.0/1.0)              | float                  |
| action_mask  | `MY_ACTION_MASK` uchars        | unsigned char, 1=legal |

A multi-agent env owns `num_agents` **consecutive** slots from its base pointer (unless perm
is active, §4). An env may only touch its own slots — envs run under `#pragma omp parallel
for` (vecenv.h:291, 745), so cross-env writes are a data race.

Per step the harness zeroes rewards+terminals (vecenv.h:288-289 / :742-743), runs `c_step`
on every env in parallel, then uploads obs/rewards/terminals/mask to GPU. **Observations are
never zeroed for you** — memset your own obs (chess `populate_observations`, chess.h:1587).

**Auto-reset is the env's job, inside `c_step`**: on episode end set `terminals[s]=1`, set
final rewards, accumulate the Log, then call `c_reset(env)` before returning
(`ocean/squared/squared.h:94-107`). The trainer only calls `c_reset` once at startup. If all
episodes have identical length, stagger initial states or the rollout buffers sync up.

## 3. Log struct rules

`Log` is **floats only**, with `float n;` REQUIRED as the last conceptual counter
(squared.h:21-29). Aggregation (vecenv.h:665-686) reinterprets the struct as
`float[sizeof(Log)/sizeof(float)]`, sums element-wise across envs, divides **every** field
by summed `n`, then memsets all env logs to zero. So: store **sums**, bump `env->log.n++`
once per episode, never put ints or pointers in Log. Export fields in `my_log` via
`dict_set` — these become `env/<key>` in the dashboard, wandb, and selfplay.py.

Blood Bowl's reward-integrity ratios deliberately combine fields *after* aggregation: `Log`
stores raw emission counters, aggregation divides every counter by the same episode count,
and `my_log` forms the ratios afterwards, so the common divisor cancels and emission
weighting survives across short and long episodes. `reward_episode_abs_max_mean` is the mean
of episode maxima, not a run-wide maximum.

**HARD KEY LIMIT (bit us 2026-06-05):** `vec_log` in `src/bindings_cpu.cpp` AND
`src/bindings.cu` allocates the output dict with a FIXED capacity (upstream 32; ours 160)
and appends `"n"` after `my_log` returns. `dict_set`'s capacity check is a bare `assert`
upstream — **compiles out under NDEBUG** — so exceeding capacity is a silent
24-bytes-per-key heap overrun that surfaces as `free(): corrupted unsorted chunks` at the
FIRST aggregation with completed episodes (~epoch 3 / ~786K steps; `n==0` early-returns
before that). It reproduces at any thread count / cwd / config — don't chase those. Our
vendored `dict_set` now aborts loudly with the key name. Blood Bowl currently emits 123 keys
plus `"n"`. When adding Log keys, recount `dict_set` calls in `my_log` (+1 for `"n"`)
against the `create_dict` capacity at **both** vec_log call sites.

## 4. Two-player self-play (the chess pattern)

One `c_step` = one ply. Layout: `num_agents = 2`, both slots belong to one env.

- **Per-slot pointer arrays** instead of raw base+stride: chess.h:436-440 declares
  `obs_ptr[2] / action_mask_ptr[2] / action_ptr[2] / reward_ptr[2] / terminal_ptr[2]`,
  populated by `my_setup_perm` (`ocean/chess/binding.c:17-27`), which maps slot → physical
  row via `vec->agent_perm` (NULL = identity). All env-body access goes through these
  arrays — that is what makes frozen-bank routing work.
- **Who acts**: read only the side-to-move's action,
  `*env->action_ptr[env->slot_for_color[mover]]` (chess.h:2410-2412); write fresh obs +
  masks for **both** slots every step.
- **Slot↔color randomized per env** at init (`(i & 1)` flip, binding.c:126-132) so a policy
  in a fixed slot sees both colors; kills first-player bias in logs.
- **Egocentric obs**: each slot sees the board from its own perspective (chess flips via
  `sq ^ 56`; BB mirrors the pitch for the away team).
- **Tags for the pool** (MY_USES_TAGS): set `env->boundary_reached = 1` at game end;
  accumulate `log.hist_score_bank[b]`/`hist_n_bank[b]` when `tag == b+1` (tag 0 = pure
  self-play). Export them as literal `hist_score_bank_0`..`_7` — `selfplay.py:224-225` reads
  exactly those names, multiplied back by `env/n`.

## 5. Action masking and exact joint sampling

`#define MY_ACTION_MASK N` where `N == sum(ACT_SIZES)`. The vec allocates
`total_agents * N` uchars (vecenv.h:448-459); write 1 for each legal action of the **next**
decision when you write that slot's obs. The mask is consumed by both native and Torch
backends during rollout and PPO recomputation — native kernels skip unsupported logits in
normalization, sampling, entropy, and gradients; Torch uses `masked_fill(-inf)`. The policy
never *sees* the mask as input, so chess additionally encodes legality into obs features
(`O_VALID_FROM`/`O_VALID_TO`) so the net can learn it. Every head must have at least one
enabled value.

**Blood Bowl uses exact joint sampling in BOTH backends** (D218). Keep the semantic
`{type,arg,square}` logits, but transport the current ragged packed joint support through
`MY_JOINT_ACTION_MAX`. Rollout samples type, then `arg|type`, then `square|type,arg`, and
overwrites the ordinary 454-wide rollout mask with the selected conditional masks. PPO
recompute reuses those stored masks, so ratio and entropy are distribution-identical without
storing ragged support for the whole horizon. Inactive heads are singleton sentinels
(`arg=32`, `square=390`) contributing zero log-probability and entropy. `bbe_decode` fails
closed on a tuple outside support — it never snaps to a neighbor. Torch frozen rows must
store their own action, logprob, and selected mask together. Run
`training/test_exact_joint_actions.py`, the installed-snapshot check, and native/Torch
ratio-one checks after any sampler change.

## 6. MultiDiscrete actions

`#define NUM_ATNS 2` + `#define ACT_SIZES {7, 13}` (`ocean/drive/binding.c:2-3`). The action
slot holds NUM_ATNS floats; read head h as `(int)env->actions[h]`. The sampler walks heads
with a running `logits_offset` (pufferlib.cu:500-553), so a mask covers the concatenated
heads: `MY_ACTION_MASK = 7+13 = 20`, head h's bits at `sum(ACT_SIZES[:h])`. NOTE:
`ocean/convert/binding.c` uses stale `OBS_TYPE/ACT_TYPE` macros and predates the current
ABI — use **drive** as the MultiDiscrete reference.

## 7. Build and run, end-to-end

build.sh only looks inside its own tree (`[ -d "ocean/$ENV" ]`, build.sh:135), and one env is
**statically linked** into `pufferlib/_C.so` per build (`m.attr("env_name")`,
src/bindings.cu:510; `_resolve_backend` asserts it matches, pufferl.py:172-174).

```bash
# 1. "Register" = install the snapshot. NEVER symlink or hand-copy — use the installer:
bash tools/install_puffer_env.sh           # cp -RL puffer/bloodbowl -> ocean/bloodbowl
                                           # (+ puffer/config/bloodbowl.ini + demo state
                                           # bank), applies the patch stack, writes
                                           # .content_hash
bash tools/install_puffer_env.sh --check    # drift guard: ALL builds (incl. --fast/--local)
                                            # compile the installed SNAPSHOT, never puffer/
                                            # or engine/src — exit 1 = re-install
cd vendor/PufferLib
# config discovery: load_config scans config/**/*.ini for env_name in [base] (pufferl.py:620)

# 2. Iterate in pure C first (fastest builds, ASan on Linux):
./build.sh bloodbowl --local     # debug standalone from ocean/bloodbowl/bloodbowl.c
./build.sh bloodbowl --fast      # optimized standalone

# 3. After ANY env code change, the full liturgy from repo root:
#    bash tools/install_puffer_env.sh \
#      && cd vendor/PufferLib && rm -rf build && ./build.sh bloodbowl --float
#    NEVER skip the install, NEVER skip `rm -rf build` (stale objects survive).
./build.sh bloodbowl             # CUDA backend (Linux + nvcc), bf16 by default
./build.sh bloodbowl --float     # fp32 — REQUIRED for the torch backend and for the
                                 # recurrent CUDA qualification. Verify:
                                 # python -c 'from pufferlib import _C;
                                 # assert _C.precision_bytes==4'
./build.sh bloodbowl --debug     # -O0 -g
./build.sh bloodbowl --cpu       # Mac/CPU Torch backend (<200k sps; exact masks work)

# 4. Train / eval / match (CLI == python -m pufferlib.pufferl):
puffer train bloodbowl --train.learning-rate 0.001 --env.some-key 3 --vec.num-threads 4
puffer train bloodbowl --wandb --tag exp1
puffer eval  bloodbowl --load-model-path latest
puffer sweep bloodbowl --sweep.gpus 8
puffer match bloodbowl --load-model-path A.bin --load-enemy-model-path B.bin --num-games 4096
puffer train bloodbowl --slowly   # REQUIRED with --cpu builds (torch backend)
```

The standalone `.c` demo is also how you do C-side inference with trained weights:
`load_weights` + `make_puffernet` + `forward_puffernet` from `src/puffernet.h`.

**Config surface.** `validate_config` (pufferl.py:162) enforces `minibatch_size % horizon
== 0`, `minibatch_size <= horizon * total_agents`, and `total_agents % num_buffers == 0`.
Sections: `[base]` (env_name, checkpoint_dir…), `[vec]`, `[env]` (your kwargs — every key
must be readable by my_init), `[policy]` (hidden_size, num_layers), `[train]`, `[selfplay]`,
`[sweep]`. Defaults merge from `config/default.ini`; ours is
`puffer/config/bloodbowl.ini`, installed into vendor by the installer.

**macOS**: build.sh hardcodes `-mavx2 -mfma` (x86-only), has empty `SANITIZE_FLAGS` on
Darwin, and the default CUDA mode needs nvcc. On the Mac only `--local/--fast` standalones
and `--cpu` are viable; real training happens on the Linux GPU box. Exact-mask semantics can
be exercised locally on Torch/CPU; CUDA graph capture and native-kernel behavior cannot.

**Mac practice runs — verified recipe (2026-06)**: use `tools/mac_practice_build.sh`, NOT
`./build.sh --cpu`. Three walls:
1. `-mavx2` hard-errors on arm64 → guard SIMD_FLAGS (local vendored patch).
2. Apple clang lacks `-fopenmp`; brew LLVM + `-lomp` links homebrew libomp while torch loads
   its OWN libomp → two OpenMP runtimes in-process → SIGSEGV in
   `__kmp_suspend_initialize_thread` during the first rollout. `KMP_DUPLICATE_LIB_OK=TRUE`
   does NOT save you. Fix: compile `_C` with NO `-fopenmp` at all (vecenv/bindings_cpu use
   only `#pragma omp`, zero `omp_*` API calls — pragmas degrade to single-threaded). Keep
   `-I/opt/homebrew/opt/libomp/include` so `#include <omp.h>` resolves.
3. `selfplay.setup` raises RuntimeError on non-CUDA backends and pufferl catches it, prints
   one WARNING and exits 0 having trained NOTHING (looks like success!) → always pass
   `--selfplay.enabled 0` with `--slowly`.

venv: `uv venv .venv --python 3.12 && uv pip install -e .` in vendor/PufferLib. Observed:
MinGRU 2.9M params, ~15K SPS single-thread torch CPU. Good enough to shake out
binding/policy/config before touching the GPU. For lldb on a venv'd python, use
`readlink -f .venv/bin/python` as the target and
`settings set target.process.stop-on-exec false`.

## 8. The local patch stack and its order

`vendor/*/` is gitignored, so **every patch is lost on a re-clone**. All of them live in
`training/*.patch` and `tools/install_puffer_env.sh` applies them in one ordered pass. The
order matters because later patches' context lines come from earlier ones — this stack
interleaves C-side (`src/*.cu`, `src/bindings*.cpp`) and Python-side
(`pufferlib/pufferl.py`, `torch_pufferl.py`, `selfplay.py`, `sweep.py`) edits, which is why
it used to be applied by hand and got out of sync. Do not hand-apply a subset and compare
the result to an accepted arm; `tools/run_reward_screen.sh` hashes the whole ordered bundle.

Installer order:

1. snapshot copy (`cp -RL puffer/bloodbowl` → `ocean/bloodbowl`), ini, demo state bank,
   generated exact-action header, `.content_hash`;
2. **dict capacity** — bumped in place with perl in `src/bindings.cu`,
   `src/bindings_cpu.cpp`, `src/pufferlib.cu` to `create_dict(160)`.
   `training/puffer_dict_capacity.patch` is the *record* of that change, not what gets
   applied (see §3 for why the capacity is load-bearing);
3. `sweep_match_mode_exclusion.patch` → `pufferlib/sweep.py` (upstream omits `match_*` from
   `_params_from_puffer_sweep`'s skip-list, so a match-mode sweep crashes; also clears the
   stale `__pycache__` that would shadow it);
4. `pufferl_env_dashboard_limit.patch` (stock dashboard truncates env metrics at 30 keys;
   we emit 123);
5. `pufferl_env_json.patch`, then `pufferl_env_json_metadata_upgrade.patch`;
6. `pufferl_env_phase_contract.patch` (explicit train vs final-eval phase);
7. `pufferl_eval_episode_gate.patch` (accumulates completed games across intervals and
   scales the eval budget to the requested target);
8. `pufferl_metrics_keyerror.patch` (keeps `metrics.setdefault` for dynamic keys);
9. `torch_pufferl_trusted_load.patch` (PyTorch 2.6 flipped `torch.load` to
   `weights_only=True`; our checkpoints are trusted local full-pickle state dicts);
10. `pufferl_scripted_training_guard.patch` and `pufferl_warm_start.patch` — the two edits
    that existed only as untracked local edits in individual box checkouts until they were
    captured. Their absence is why the obs-v5 checkout could not warm-start;
11. `selfplay_league.patch` → `pufferlib/selfplay.py` (§10);
12. `puffer_exact_joint_actions.patch` — C-side + Torch: extends the vec interface with the
    transient ragged joint-support buffer (§5);
13. `puffer_recurrent_eval_state.patch` — after exact actions, because both extend the same
    native and Torch rollout paths;
14. `puffer_frozen_prio_mask.patch` — frozen PPO rows must be mathematically ineligible for
    priority sampling; zero advantage is not exclusion at `alpha=0` because `pow(0,0) == 1`;
15. `puffer_recurrent_cuda_qualification.patch` — last: it inspects the tensors produced by
    the preceding patches, so it belongs to the same compiled backend identity.

`--check` reverse-verifies the qualification, frozen-prio, trusted-load, and selfplay-league
patches, so a stale vendored tree fails before a build rather than after a run.

`training/torch_pufferl_bcreg.patch` is **not** in the stack (§11).

### Warm start

**`puffer train` has NO upstream warm-start** — `load_model_path` is only read by
`eval()`/`match()`. `pufferl_warm_start.patch` adds it to `_train` right after
`create_pufferl`, resolves `'latest'` like eval does, and calls `backend.load_weights`. Used
for curriculum chaining and BC warm starts. The CUDA backend loads its own flat-fp32 `.bin`
directly; state_dict-style `.bin`s (BC pretrain output) need the converter noted in
`training/bc_pretrain.py` first.

### Recurrent evaluation state

`puffer_recurrent_eval_state.patch` defines the boundary contract: CUDA graph warmup must
restore primary and every frozen-bank recurrent buffer to exact zero; training is valid only
with `reset_state=True` and evaluation mode off (PPO does not retain each segment's initial
recurrent state); evaluation starts from fresh games, preserves state across nonterminal
rollout calls, and clears a terminal row before forwarding the next game's observation. Keep
the captured device-gated reset launch proportional to **active rows**, not
layers × rows × hidden. Graph-enabled qualification cells use `cudagraphs=10`, matching the
Puffer/canary warmup boundary — `0` captures the first execution before CUDA lazy init, and
`-1` is the deliberate graph-off parity cell.

Source tests are not CUDA acceptance. Before a long run, measure on the target GPU:
graph-on/off deterministic parity and throughput, primary/frozen post-terminal parity,
construction checksums, and zero-update ratios. `tools/qualify_recurrent_cuda.py` does this
in an isolated **fp32** checkout (BF16 rounds the stored behavior log-probability before PPO
recomputation, so it cannot satisfy the near-unity ratio contract). It uses fresh
subprocesses and a bounded raw snapshot, and rejects: a candidate module/backend/environment
that differs from what was declared, missing banks or buffers, incomplete sampled ratio-row
coverage, changed weights at learning rate zero, any nonzero or non-finite value across the
16-key hard-integrity registry in a transition-executing cell, any selected frozen row, and
a missing or identity-mismatched same-host predecessor throughput report. Qualification
outputs and their checkpoints are never eligible warm starts or pool ancestry.

Both the qualification worker and the real trainer must enter through
`tools/puffer_cuda_runtime.py` (D225): in a fresh WSL process, importing `_C` before the
first CUDART call leaves it reporting `cudaErrorNoDevice`. Require `cudaSuccess` with a
positive device count before the import, keep the exact resolved `libcudart.so.12` handle,
import, then require the same count; record CUDART path/hash and `CUDA_VISIBLE_DEVICES`. An
out-of-process `nvidia-smi`, Torch, or CUDART probe is not evidence for this worker.

## 9. Observation lineage and checkpoint conversion

**Every obs bump is a LINEAGE BREAK. Current runtime: obs-v6, `BBE_OBS_SIZE = 2782.**
History: v2 832 → v3 1612 → v4 2782 → v5 2782 → v6 2782. THREE consecutive revisions at the
same size make blob size worthless — never warm-start a v6 runtime from a v4 or v5
checkpoint. `tools/checkpoint_lineage.py` refuses a mismatched `observation_version` as its
first check, because nothing else can see the difference.

The three OBS_SIZE sync points (`bloodbowl.h`, `binding.c`, `convert_checkpoint.py`) and the
`--obs-size` rules for older lineages are in `training-experiments` §3. The build-side half
matters here: the `_Static_assert` between `BBE_OBS_SIZE` and `binding.c`'s literal is what
caught the stale 1612 (D54); nothing guards the converter default.

**BBP shard versions** (header `"BBP1"`, u32 version, obs_size, mask_size — written by
`tools/bb_lockstep.c`, read by `training/bc_pretrain.py` and `validation/extract_pairs.py`):

| version | means |
|---|---|
| v1 | obs-v2, 832 bytes |
| v2 | historical marginal-mask era; spans obs-v3 (1612) **and** obs-v4 (2782) |
| v3 | obs-v5's semantic ABI at 2782, still pre-exact-action |
| v4 | **current** — exact sequential action semantics and canonical inactive-head sentinels, 2782 |

**Known gap:** the BBP header does not record the observation revision, so a v4 shard
written under obs-v5 and one written under obs-v6 are indistinguishable by header. obs-v6
deliberately did not touch BBP; keep v5 and v6 pair stores separate by provenance.

The writer emits v4, and `bc_pretrain.py` rejects anything but v4 unless `--allow-legacy` is
passed. v2/2782, v3/2782, and v4/2782 must never mix despite identical physical shape, and
an index rejects mixed header versions outright. The historical pair store is 2,085,330
obs-v4 records across 12,304 BBP-v2 shards — **not** current training data. The strict
embedded-`rulesVersion` BB2025 surface is 9,118 non-empty replay IDs / 1,622,231 joined
records (`runs/replay-audit-20260713/`). Never call shard count replay count, and never mix
BB2020 into BC.

Historical anchor: **bc_v4** (val exact 0.508) is not valid for obs-v6 warm-start and lives
only on the training boxes; local `training/` holds ≤ bc_v3b.

Warm relaunch: checkpoints land under `vendor/PufferLib/checkpoints/` (`[base]
checkpoint_dir`) per run dir; pick the anchor by the STEP NUMBER in the filename (e.g.
`0000014942470144.bin`) — **newest mtime ≠ highest step across run dirs**.

## 10. Self-play pool and league seeding

Built-in pool (`pufferlib/selfplay.py`): a fraction of envs play primary-vs-frozen-snapshot,
the rest pure self-play. Gated on `[selfplay] enabled = 1`; requires the native CUDA backend
plus an env implementing MY_USES_PERM, MY_USES_TAGS, and the
`hist_score_bank_<b>/hist_n_bank_<b>` log fields.

Knobs (`config/default.ini` `[selfplay]`; chess.ini has tuned values):
- `swap_winrate` (chess 0.6) + `min_games` (chess 4096): advance to a new opponent once
  primary's winrate vs the current frozen opponent clears the threshold over ≥ min_games.
- `snapshot_interval` (chess 1e9 steps): unconditional pool snapshot cadence.
- `opp_timeout_steps` (chess 4e9): force-swap a stalemated opponent.
- `max_size`: pool cap; eviction drops every other entry from the oldest half
  (`evict`, selfplay.py:41) to preserve temporal coverage.
- `elo_init`/`elo_k`: per-snapshot Elo, updated each rollout window.
- `[vec] frozen_bank_pct` (chess 0.1): fraction of each buffer's slots per frozen bank;
  `[vec] num_frozen_banks` (1-8).
- Opponent sampling: sqrt-rank weights, newest 5 excluded once the pool reaches 6.

A pending swap waits until every historical env of that bank has finished a game
(`count_aligned >= num_hist_envs`, selfplay.py:268) — that is what `boundary_reached` is
for. Row routing is built by `build_perm_tags` (selfplay.py:50) and pushed via
`_C.set_agent_perm` / `_C.set_env_tags`; full layout in `reference/vecenv-internals.md`.

**League preseed (`selfplay_league.patch`).** Stock `selfplay.setup()` keeps pool state in
memory and UNCONDITIONALLY bootstraps: it saves the learner's current weights as
`<ckpt>/<env>/<run_id>/pool/{global_step:016d}.bin` and loads that one file into every
frozen bank (selfplay.py:169-175). The patch adds `[selfplay] league_preseed`: when it names
a pool dir built by `tools/build_league.py` (`league_seeds.json` + one flat-fp32
`{bank:016d}.bin` per bank), bank b loads seed b, the opponent pool starts as the ordered
seed set, that dir becomes the run's pool_dir, and the bootstrap save is skipped. Empty key
= upstream behavior. Seed sizes are hard-verified in Python because the C loader
(`pufferl_load_frozen_bank`, pufferlib.cu:1830) only fprintf-warns on a size mismatch and
silently keeps the bank's old weights.

Validate with `python3 training/test_selfplay_league.py` (stubbed-backend proof that setup()
loads each seed into its bank, plus bootstrap-path upstream-equivalence).
`tools/run_league.sh` is the launch recipe: native CUDA backend, 5 banks, warm start from the
graduate, `--vec.num-frozen-banks 5 --vec.frozen-bank-pct 0.08` (163 rows/bank, 815 total <
apb/2 = 1024; the min_games math is derived in the script header), snapshot_interval 500M.
Seed paths resolve from PROFILE markers with `LEAGUE_SEED_*` env overrides.

## 11. Telemetry and eval contract

- **Do not kill the post-training eval because the `Steps` line stopped.**
  `pufferl_eval_episode_gate.patch` accumulates completed games across intervals and scales
  the eval budget to the requested target. An arm is accepted only after the requested full
  games, the explicit final phase/status reprint, the checkpoint hash, and zero integrity
  counters. The acceptance floor equals the request — an exact count is complete and must not
  require an incidental vectorized overshoot. A frozen dashboard line proves neither a hang
  nor completion.
- Record the actual imported `_C.__file__`, `_C.env_name`, `_C.gpu`, `_C.precision_bytes`,
  and module SHA. A source checkout or content hash does not prove which extension Python
  loaded.
- Env telemetry must distinguish train from final eval, clear sticky metadata, expose reward
  clip / non-finite / error / demo / fallback counts, and print the final cumulative record.
- Reward telemetry splits clipped samples into terminal and non-terminal contexts. On an
  episode-ending step, keep the explicit current-step objective reward plus result utility;
  incidental action/board shaping must not co-stack with the result, and deliberately
  terminal terms stay separately clip-visible.

## 12. Historical BC-regularized PPO (rejected for new runs)

With `[train] bc_coef > 0`, every PPO minibatch in the TORCH backend (`--slowly`) also pays
`bc_coef *` masked 3-head CE on `bc_batch` human pairs from the `.bbp` shards in
`bc_pairs_dir` (keys `loss/bc_loss`, `loss/bc_acc`, `loss/bc_coef`; the native CUDA trainer
ignores `bc_*`). **D176 rejected the mechanism:** coefficient-1 iid CE collapsed offense to
zero while the no-anchor control stayed functional. The patch also eagerly preloads every
shard with no replay-ID/edition allowlist, so the legacy `validation/pairs` path can mix
editions. Keep `bc_coef=0`; reconsidering needs bounded streaming, a BB2025-exact allowlist,
and a new hypothesis. `training/torch_pufferl_bcreg.patch` is applied only by
`tools/run_bcreg.sh` and validated by `training/test_bcreg_torch_pufferl.py`; its hardcoded
`training/bc_v1.bin` is dead obs-v2 lineage, so never run the historical recipe against the
v5 runtime even with a shape-loadable checkpoint.

## 13. Footguns beyond §1–§6

The section rules above are the footgun list for obs zeroing, auto-reset, Log layout,
OBS_TENSOR_T, dict keys, stride isolation, float actions, and mask width. Additionally:

1. **One env per `_C` build** — "build.sh was run for X, not Y" means rebuild.
2. **Obs/reward scale** in [-1, 1]-ish; a stray magnitude-1000 feature stalls training.
3. **raylib is always linked** — `c_render` may be a stub but must exist; keep rendering out
   of the training hot path.
4. **Hash the env before and after every change.** The standalone's FNV mode folds obs,
   action masks, legal-action buffers (`legal_arg`/`legal_sq`/`n_legal`/`illegal`), and
   sampled actions into one FNV-1a hash:
   ```bash
   bash tools/install_puffer_env.sh && cd vendor/PufferLib \
     && ./build.sh bloodbowl --fast && ./bloodbowl --fnv --seed 42 100
   ```
   The install step is NOT optional (build.sh compiles the installed snapshot, so skipping it
   hashes STALE code and a real change reads as "no-op"). Run the binary FROM vendor/PufferLib
   both times — the state bank resolves via the cwd-relative
   `resources/bloodbowl/state_bank.bbs`, and a missing bank is SILENT (procgen-only episodes)
   and changes the hash. Same seed/episodes/cwd: intended-no-op refactor ⇒ identical hash;
   intended obs/mask change ⇒ hash changes and NOTHING else does.

## 14. Where 4.0 differs from 3.0 articles online

| 3.0 (most blog posts / old docs)             | 4.0 (this vendored tree)                          |
|----------------------------------------------|---------------------------------------------------|
| `env_binding.h`, per-env shared lib          | `src/vecenv.h` macro include, static-linked `_C`  |
| Python env classes, Gymnasium/PettingZoo emulation | No Python env layer at all; pure C ABI       |
| `pufferlib.vector.make(...)`, Serial/Multiprocessing | `StaticVec` in C; buffers + OMP + CUDA streams |
| Python PPO (CleanRL-derived `pufferl.py`)    | ~5k lines CUDA (`src/*.cu`); pufferl.py is a CLI shim |
| obs/action spaces objects                    | `OBS_SIZE` flat + `OBS_TENSOR_T`; actions always float |
| no native masking/self-play                  | `MY_ACTION_MASK`, `MY_USES_PERM/TAGS`, `selfplay.py`, `puffer match` |
| `pip install pufferlib[...]`                 | build from source: `./build.sh <env>` then `puffer train <env>` |
| LSTM default policy                          | MinGRU + highway-net "PufferNet"; Muon optimizer, GAE+VTrace hybrid, prioritized replay |

Deep internals (StaticVec walkthrough, threading, perm row layout, pybind export surface,
match() mechanics): `reference/vecenv-internals.md`.
