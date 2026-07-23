---
name: puffer-env-dev
description: Develop and audit the Blood Bowl PufferLib 4.0 environment, including binding macros, buffers, action masks, self-play routing, builds, configs, local patch stack, phase/provenance telemetry, eval game gates, reward integrity, train/eval/match, and checkpoint conversion. Use for native C binding work or any Puffer training/evaluation correctness question.
---

# PufferLib 4.0 Native C Env Development

We target the **4.0 macro ABI in `vendor/PufferLib/src/vecenv.h`**. Almost every online
tutorial/blog describes the old 3.0 pattern (`env_binding.h`, Gymnasium emulation,
`pufferlib.vector.make`, Python env classes) — **none of that exists anymore**. See
"4.0 vs 3.0" at the bottom before trusting any external article.

Primary template: `vendor/PufferLib/ocean/chess/` (2-player board game, action masking,
self-play perm, FEN curriculum — structurally closest to Blood Bowl).
Minimal template: `vendor/PufferLib/ocean/squared/`. MultiDiscrete: `vendor/PufferLib/ocean/drive/`.
Cached upstream docs: `docs/vendor/pufferlib/docs.html` (env-author checklist + CLI cheatsheet).

For current Blood Bowl experiment acceptance, also read `AGENTS.md`, D177–D186,
and `docs/reward-and-replay-audit-2026-07-09.md`. Upstream success/exit status is
not sufficient: the audited path requires explicit phase, provenance, completed
games, final cumulative reprint, and reward-integrity telemetry.

For observation work, also read D217 and `docs/obs-v5-spec.md`. Obs-v5 retains
obs-v4's 2,782-byte tensor shape but changes reserved-byte semantics and
Touchback projection. Blob size cannot distinguish those lineages: require the
exact source/module identity, and never treat a shape-loadable v4 checkpoint or
pair shard as semantically v5 without a separately reviewed bridge.

## 1. The binding ABI

A 4.0 env = `ocean/<name>/<name>.h` (all game logic) + `ocean/<name>/binding.c` (macros +
glue) + `config/<name>.ini`. `binding.c` defines macros **then** includes `vecenv.h`,
whose implementation only compiles `#ifdef OBS_SIZE` (vecenv.h:164).

Annotated minimal binding (pattern from `ocean/squared/binding.c` + chess):

```c
#include "bloodbowl.h"
#define OBS_SIZE 167          // flat obs length per agent slot
#define NUM_ATNS 1            // number of action heads (MultiDiscrete dims)
#define ACT_SIZES {97}        // logits per head; brace list, len == NUM_ATNS
#define OBS_TENSOR_T ByteTensor  // obs dtype: ByteTensor|FloatTensor|IntTensor|LongTensor (src/tensor.h)
                              // MUST be a literal "#define OBS_TENSOR_T X" line in binding.c —
                              // build.sh:273 awk-greps it out of binding.c (won't see a .h)
#define MY_ACTION_MASK 97     // optional: mask bytes per slot == sum(ACT_SIZES)
#define MY_VEC_INIT           // optional: you provide my_vec_init (else default, vecenv.h:350)
#define MY_VEC_CLOSE          // optional: you provide my_vec_close
#define MY_USES_PERM          // optional: self-play pool routing (you provide my_setup_perm)
#define MY_USES_TAGS          // optional: env has `int tag; int boundary_reached;` fields
#define Env BloodBowl         // your env struct name
#include "vecenv.h"

void my_init(Env* env, Dict* kwargs) { /* read [env] ini keys via dict_get */ }
void my_log(Log* log, Dict* out)     { dict_set(out, "perf", log->perf); /* ... */ }
```

Required fields on your Env struct (see `ocean/squared/squared.h:32`):
`Log log;` (first is conventional), `observations` (pointer of your obs dtype),
`float* actions; float* rewards; float* terminals;`, `int num_agents;`,
`unsigned int rng;` — plus `unsigned char* action_mask;` if MY_ACTION_MASK, and
`int tag; int boundary_reached;` if MY_USES_TAGS.

Required functions in your `.h`: `c_reset(Env*)`, `c_step(Env*)`, `c_render(Env*)`,
`c_close(Env*)`. `c_close` must NOT free observations/actions/rewards/terminals — the
vec owns them (vecenv.h:422-440 cudaHostAlloc / calloc).

Dict kwargs gotchas: `dict_get` **asserts** the key exists (vecenv.h:47-52) — every key
your `my_init`/`my_vec_init` reads must be in the ini `[env]` section. `dict_set` stores
the key **pointer**, not a copy (vecenv.h:61) — keys must be string literals
(see the hard-won comment at `ocean/chess/binding.c:193-196`).

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

A multi-agent env owns `num_agents` **consecutive** slots starting at its base pointer
(unless perm is active, §4). An env may only touch its own slots — envs in a buffer run
under `#pragma omp parallel for` (vecenv.h:291, 745); cross-env writes are a data race.

Per step the harness: zeroes rewards+terminals (vecenv.h:288-289 threaded path,
:742-743 sync path), runs `c_step` on every env in parallel, then uploads
obs/rewards/terminals/mask to GPU. **Observations are never zeroed for you** — memset
your own obs (chess `populate_observations` memsets first, chess.h:1587).

**Auto-reset is the env's job, inside `c_step`**: on episode end set `terminals[s]=1`,
set final rewards, accumulate the Log, then call `c_reset(env)` before returning
(`ocean/squared/squared.h:94-107`). The trainer only calls `c_reset` once at startup.
If all episodes have identical length, stagger initial states or the rollout buffers sync up.

## 3. Log struct rules

`Log` is **floats only**, with `float n;` REQUIRED as the last conceptual counter
(squared.h:21-29). Aggregation (vecenv.h:665-686) reinterprets the struct as
`float[sizeof(Log)/sizeof(float)]`, sums element-wise across envs, divides **every**
field by summed `n`, then memsets all env logs to zero. So: store **sums**, bump
`env->log.n++` once per episode, never put ints/pointers in Log. Export fields in
`my_log` via `dict_set` — these become `env/<key>` in the dashboard, wandb, and
selfplay.py.

Blood Bowl's reward-integrity ratios deliberately combine fields after this
aggregation: `Log` stores raw emission counters, vec aggregation divides every
counter by the same episode count, and `my_log` forms the ratios afterward.
The common divisor cancels, preserving emission weighting across short and
long episodes. `reward_episode_abs_max_mean` is the mean of episode maxima;
it is not a run-wide maximum.

**HARD KEY LIMIT (bit us 2026-06-05):** `vec_log` in `src/bindings_cpu.cpp` AND
`src/bindings.cu` allocates the output dict with a FIXED capacity (upstream: 32;
ours: 160 via `training/puffer_dict_capacity.patch`) and appends `"n"` after
`my_log` returns. `dict_set`'s capacity check is a bare `assert` upstream —
**compiles out under NDEBUG**, so exceeding capacity is a silent 24-bytes-per-key
heap overrun that surfaces as `free(): corrupted unsorted chunks` at the FIRST
log aggregation with completed episodes (~epoch 3 / ~786K steps, `n==0`
early-returns before that). It reproduces at any thread count / cwd / config —
do not chase those. Our vendored `dict_set` now aborts loudly with the key name.
Blood Bowl currently emits 123 keys plus `"n"`. When adding Log keys, recount
`dict_set` calls in `my_log` (+1 for `"n"`) against the `create_dict` capacity
at both vec_log call sites and update the installer/dashboard guidance.

## 4. Two-player self-play (the chess pattern)

One `c_step` = one ply. Layout: `num_agents = 2`, both slots belong to one env.

- **Per-slot pointer arrays** instead of raw base+stride: chess.h:436-440 declares
  `obs_ptr[2] / action_mask_ptr[2] / action_ptr[2] / reward_ptr[2] / terminal_ptr[2]`,
  populated by `my_setup_perm` (`ocean/chess/binding.c:17-27`), which maps slot →
  physical row via `vec->agent_perm` (NULL = identity). All env-body reads/writes go
  through these arrays — that's what makes the frozen-bank routing work later.
- **Who acts**: read only the side-to-move's action:
  `*env->action_ptr[env->slot_for_color[mover]]` (chess.h:2410-2412); write fresh obs +
  masks for **both** slots every step (`populate_observations`, chess.h:1577).
- **Slot↔color randomized per env** at init (`(i & 1)` flip in binding.c:126-132) so a
  policy in a fixed slot sees both colors; kills first-player bias in logs.
- **Egocentric obs**: each slot sees the board from its own perspective (chess flips
  via `sq ^ 56`). Do the same for BB (flip pitch for the away team).
- **Tags for the pool** (MY_USES_TAGS): set `env->boundary_reached = 1` at game end
  (chess.h:2668); accumulate `log.hist_score_bank[b]`/`hist_n_bank[b]` when
  `tag == b+1` (env is playing frozen bank b; tag 0 = pure self-play). Export them as
  `hist_score_bank_0`..`_7` literals in `my_log` — `selfplay.py:224-225` reads exactly
  those names, multiplied back by `env/n`.

## 5. Action masking

`#define MY_ACTION_MASK N` where `N == sum(ACT_SIZES)` (total flattened logits). The vec
allocates `total_agents * N` uchars (vecenv.h:448-459); write 1 for each legal action of
the **next** decision when you write that slot's obs (chess memsets the mask then sets
legal bits). The mask is consumed by both native and Torch backends during rollout and
PPO recomputation. Native kernels explicitly skip unsupported logits in normalization,
sampling, entropy, and gradient loops; Torch uses `masked_fill(-inf)`. The policy never
*sees* the mask as input — chess additionally encodes legality into obs features
(`O_VALID_FROM`/`O_VALID_TO` square lists) so the net can learn it. Every head must have
at least one enabled value. Blood Bowl's exact-support path asserts/fails closed on an
empty conditional slice rather than treating it as a usable distribution.

**Blood Bowl uses exact joint sampling in BOTH backends** (D218). Keep the
semantic `{type,arg,square}` logits, but transport the current ragged packed
joint support through `MY_JOINT_ACTION_MAX`. Rollout samples type, then
`arg|type`, then `square|type,arg`; it overwrites the ordinary 454-wide rollout
mask with the selected conditional masks. PPO recompute continues using those
stored masks, so ratio and entropy are distribution-identical without storing
ragged support for the whole horizon. Inactive heads must be singleton arg=32
or square=390. `bbe_decode` fails closed on a tuple outside support; it never
snaps to a neighbor. Torch frozen rows must store their own action, logprob, and
selected mask together. New BC pairs are BBP v4 with the same conditional-mask
meaning. Run `training/test_exact_joint_actions.py`, the installed-snapshot
check, and native/Torch ratio-one checks after any sampler change.

## 6. MultiDiscrete actions

`#define NUM_ATNS 2` + `#define ACT_SIZES {7, 13}` (`ocean/drive/binding.c:2-3`). The
agent's action slot holds NUM_ATNS floats; read head h as `(int)env->actions[h]`. The
sampler walks heads with a running `logits_offset` (pufferlib.cu:500-553), so a mask
covers the heads concatenated: `MY_ACTION_MASK = 7+13 = 20`, head h's bits at offset
`sum(ACT_SIZES[:h])`. NOTE: `ocean/convert/binding.c` uses stale `OBS_TYPE/ACT_TYPE`
macros and no `OBS_TENSOR_T` — it predates the current ABI; use **drive** as the
MultiDiscrete reference, not convert.

## 7. Adding + building + training a new env, end-to-end

build.sh only looks inside its own tree (`[ -d "ocean/$ENV" ]`, build.sh:135), and one
env is **statically linked** into `pufferlib/_C.so` per build (`m.attr("env_name")`,
src/bindings.cu:510; `_resolve_backend` asserts it matches, pufferl.py:172-174).

```bash
# (paths below are repo-root-relative; run the installer from repo root)
# 1. "Register" = install the snapshot. NEVER symlink or hand-copy — use the installer:
bash tools/install_puffer_env.sh           # cp -RL puffer/bloodbowl -> ocean/bloodbowl
                                           # (+ puffer/config/bloodbowl.ini + stages the
                                           # demo state bank), writes .content_hash
bash tools/install_puffer_env.sh --check   # drift guard: ALL builds (incl. --fast/--local
                                           # standalones) compile the installed SNAPSHOT,
                                           # never puffer/ or engine/src — exit 1 = re-install
cd vendor/PufferLib
# config discovery: load_config scans config/**/*.ini for env_name in [base] (pufferl.py:620-625)

# 2. Iterate in pure C first (fastest builds, ASan on Linux):
./build.sh bloodbowl --local     # debug standalone from ocean/bloodbowl/bloodbowl.c (needs a main())
./build.sh bloodbowl --fast      # optimized standalone

# 3. Training backend. After ANY env code change the full liturgy (from repo root) is:
#    bash tools/install_puffer_env.sh \
#      && cd vendor/PufferLib && rm -rf build && ./build.sh bloodbowl --float
#    NEVER skip the install (builds compile the snapshot, not puffer/) and NEVER
#    skip `rm -rf build` — stale objects survive a plain rebuild and bite.
./build.sh bloodbowl             # CUDA backend (Linux + nvcc), bf16 by default
./build.sh bloodbowl --float     # fp32 — REQUIRED for the torch backend (bf16 build refuses
                                 # to import; verify: python -c 'from pufferlib import _C;
                                 # assert _C.precision_bytes==4')
./build.sh bloodbowl --debug     # -O0 -g
./build.sh bloodbowl --cpu       # Mac/CPU: Torch backend (<200k sps; exact masks supported)

# 4. Train / eval / match (CLI == python -m pufferlib.pufferl):
puffer train bloodbowl --train.learning-rate 0.001 --env.some-key 3 --vec.num-threads 4
puffer train bloodbowl --wandb --tag exp1
puffer eval  bloodbowl --load-model-path latest
puffer sweep bloodbowl --sweep.gpus 8
puffer match bloodbowl --load-model-path A.bin --load-enemy-model-path B.bin --num-games 4096
puffer train bloodbowl --slowly   # REQUIRED with --cpu builds (torch backend)
```

The standalone `.c` demo (squared.c) is also how you do C-side inference with trained
weights: `load_weights` + `make_puffernet` + `forward_puffernet` from `src/puffernet.h`.

Config sanity enforced by `validate_config` (pufferl.py:162): `minibatch_size % horizon
== 0` and `minibatch_size <= horizon * total_agents`. Also `total_agents % num_buffers
== 0`. Sections: `[base]` (env_name, checkpoint_dir...), `[vec]`, `[env]` (your kwargs —
every key must be readable by my_init), `[policy]` (hidden_size, num_layers), `[train]`,
`[selfplay]`, `[sweep]`. Defaults merge from `config/default.ini`.

**macOS (this machine)**: build.sh hardcodes `-mavx2 -mfma` (build.sh:144-146, x86-only —
strip for Apple Silicon), has empty `SANITIZE_FLAGS` on Darwin, and the default CUDA mode
needs nvcc. On the Mac, only `--local/--fast` standalones and `--cpu` are viable; real
training happens on a Linux GPU box. Exact-mask semantics can be exercised locally on
Torch/CPU; CUDA graph capture and native-kernel behavior still require a CUDA runner.

**Mac practice runs — verified working recipe (2026-06, bloodbowl)**:
- `tools/mac_practice_build.sh` in bloodbowl-rl, NOT `./build.sh --cpu`. Three walls:
  1. `-mavx2` hard-errors on arm64 → guard SIMD_FLAGS (local vendored patch).
  2. Apple clang lacks `-fopenmp`; using brew LLVM + `-lomp` links homebrew libomp while
     torch loads its OWN libomp → 2 OpenMP runtimes in-process → SIGSEGV in
     `__kmp_suspend_initialize_thread` during the first rollout. `KMP_DUPLICATE_LIB_OK=TRUE`
     does NOT save you. Fix: compile _C with NO `-fopenmp` at all (vecenv/bindings_cpu use
     only `#pragma omp`, zero `omp_*` API calls — pragmas degrade to single-threaded).
     Keep `-I/opt/homebrew/opt/libomp/include` so `#include <omp.h>` resolves.
  3. `selfplay.setup` raises RuntimeError on non-CUDA backends and pufferl catches it,
     prints one WARNING and exits 0 having trained NOTHING (looks like success!) →
     always pass `--selfplay.enabled 0` with `--slowly`.
- venv: `uv venv .venv --python 3.12 && uv pip install -e .` in vendor/PufferLib.
- Observed: MinGRU 2.9M params, ~15K SPS single-thread torch CPU, env stats on the
  dashboard. Good enough to shake out binding/policy/config before renting the GPU.
- lldb on a venv'd python: use `readlink -f .venv/bin/python` as the target, set
  `settings set target.process.stop-on-exec false`, pass PYTHONPATH=repo:site-packages.

## 8. Self-play pool (pufferlib/selfplay.py) — we will use this

Built-in pool: a fraction of envs play primary-vs-frozen-snapshot, rest pure self-play.
Gated on `[selfplay] enabled = 1`; requires native CUDA backend + an env implementing
MY_USES_PERM, MY_USES_TAGS, and the `hist_score_bank_<b>/hist_n_bank_<b>` log fields.

Knobs (`config/default.ini` `[selfplay]` + chess.ini for tuned values):
- `swap_winrate` (chess: 0.6) + `min_games` (chess: 4096): advance to a new opponent once
  primary's winrate vs current frozen opp ≥ threshold over ≥ min_games.
- `snapshot_interval` (chess: 1e9 steps): unconditional pool snapshot cadence.
- `opp_timeout_steps` (chess: 4e9): force-swap a stalemated opponent (no snapshot).
- `max_size`: pool cap; eviction drops every other entry from the oldest half
  (`evict`, selfplay.py:41) to preserve temporal coverage.
- `elo_init`/`elo_k`: per-snapshot Elo, updated each rollout window (`update_elo`).
- `[vec] frozen_bank_pct` (chess: 0.1): fraction of each buffer's agent slots given to
  each frozen bank; `[vec] num_frozen_banks` (1-8): independent opponent banks.
- Opponent sampling: sqrt-rank weights, newest 5 excluded once pool ≥ 6
  (`sample_opponent`, selfplay.py:27).

Swap protocol detail: a pending swap waits until every historical env of that bank has
finished a game (`count_aligned` ≥ num_hist_envs, selfplay.py:268) — that's what
`boundary_reached` is for. Row routing built by `build_perm_tags` (selfplay.py:50) and
pushed via `_C.set_agent_perm` / `_C.set_env_tags`; full layout diagram in
`reference/vecenv-internals.md`.

## 9. Footgun checklist (each has bitten someone)

1. **Obs buffers are not zeroed** between steps — memset your slot's obs every time.
2. **Auto-reset inside c_step** — set terminal, log, `c_reset`; never wait for the harness.
3. **Rewards/terminals**: harness zeroes them pre-step in 4.0, but only write them when
   nonzero and never *accumulate* across steps assuming persistence.
4. **Log = floats only, sums only, `n` last**; everything is divided by aggregated `n`.
5. **OBS_TENSOR_T literally in binding.c** — build.sh awk hack; obs dtype mismatch with
   what your C writes = silent garbage → NaN losses after ~1 epoch (= memory corruption,
   per docs.html checklist).
6. **dict_set keys must be string literals** (pointer stored, not copied).
7. **dict_get asserts** — ini `[env]` keys and my_init reads must match exactly.
8. **Stride isolation** — OMP runs envs concurrently; only touch your own slots.
9. **Actions arrive as floats** — cast per head; range-check defensively (torch backend
   samples without masks; eval paths can write -1).
10. **One env per _C build** — "build.sh was run for X, not Y" means rebuild.
11. **Obs/reward scale** in [-1, 1]-ish; a stray magnitude-1000 feature stalls training.
12. **MY_ACTION_MASK must equal sum(ACT_SIZES)** — it's indexed by flattened logit offset.
13. **raylib is always linked** — `c_render` may be a stub but must exist; keep
    rendering out of the training hot path (`client == NULL` until first render, chess).
14. **Hash the env before/after every change** — the standalone has an FNV mode
    (`puffer/bloodbowl/bloodbowl.c`) folding obs, action masks, legal-action
    buffers (`legal_arg`/`legal_sq`/`n_legal`/`illegal`), and sampled actions
    into one FNV-1a hash. Procedure (the install step is NOT optional — build.sh
    compiles the installed snapshot, so skipping it hashes STALE code and a real
    change reads as "no-op"):
      bash tools/install_puffer_env.sh && cd vendor/PufferLib \
        && ./build.sh bloodbowl --fast && ./bloodbowl --fnv --seed 42 100
    The binary is `./bloodbowl` in vendor/PufferLib; run it FROM vendor/PufferLib
    both times — the state bank resolves via the cwd-relative
    `resources/bloodbowl/state_bank.bbs` and a missing bank is SILENT
    (procgen-only episodes) and changes the hash. Same seed/episodes/cwd
    before and after: intended-no-op refactor ⇒ identical hash; intended
    obs/mask change ⇒ hash changes and NOTHING else does.

## 10. Where 4.0 differs from 3.0 articles online

| 3.0 (most blog posts / old docs)             | 4.0 (this vendored tree)                          |
|----------------------------------------------|---------------------------------------------------|
| `env_binding.h`, per-env shared lib          | `src/vecenv.h` macro include, static-linked `_C`  |
| Python env classes, Gymnasium/PettingZoo emulation | No Python env layer at all; pure C ABI       |
| `pufferlib.vector.make(...)`, Serial/Multiprocessing backends | `StaticVec` in C; buffers + OMP + CUDA streams |
| Python PPO (CleanRL-derived `pufferl.py`)    | ~5k lines CUDA (`src/*.cu`, core in `pufferlib.cu`); pufferl.py is a CLI shim |
| obs/action spaces objects                    | `OBS_SIZE` flat + `OBS_TENSOR_T`; actions always float buffer |
| no native masking/self-play                  | `MY_ACTION_MASK`, `MY_USES_PERM/TAGS`, `pufferlib/selfplay.py`, `puffer match` |
| `pip install pufferlib[...]`                 | build from source: `./build.sh <env>` then `puffer train <env>` |
| LSTM default policy                          | MinGRU + highway-net "PufferNet"; Muon optimizer, GAE+VTrace hybrid, prioritized replay |

Deep internals (StaticVec walkthrough, threading, perm row layout, pybind export
surface, match() mechanics): `reference/vecenv-internals.md`.

## Operational and experiment-integrity contract

- **Do not kill the post-training eval because the Steps line stopped.** The
  audited `training/pufferl_eval_episode_gate.patch` accumulates completed games
  across intervals and scales the eval budget to the requested target. An arm is
  accepted only after the requested full games, explicit final phase/status
  reprint, checkpoint hash, and zero integrity counters. Set the acceptance
  floor to that same request: an exact count is complete and must not require an
  incidental vectorized overshoot. A frozen dashboard line alone proves neither
  a hang nor completion.
- `tools/install_puffer_env.sh` applies the audited Puffer stack in this order:
  dashboard limit, env JSON, JSON metadata upgrade, phase contract, eval episode
  gate, dynamic metrics-key fix, and trusted Torch load. `tools/run_reward_screen.sh`
  hashes the same ordered bundle. Do not hand-apply a subset and compare it to an
  accepted arm.
- Record the actual imported `_C.__file__`, `_C.env_name`, GPU flag, precision,
  and module SHA. A source checkout or installed-content hash does not prove which
  extension Python loaded.
- Env telemetry must distinguish train from final eval, clear sticky metadata,
  expose reward clip/non-finite/error/demo/fallback counts, and print the final
  cumulative record. Keep `metrics.setdefault` behavior for dynamic keys.
- Reward telemetry splits clipped samples into terminal and non-terminal
  contexts. On an episode-ending step, preserve explicit current-step objective
  reward plus result utility; incidental action/board shaping must not co-stack
  with the result. Keep deliberately terminal terms separately clip-visible.
- **`puffer train` has NO upstream warm-start.** load_model_path is only
  read by eval()/match(). We patch _train in the VENDORED pufferl.py
  (gitignored — re-apply after any re-clone; patch lives right after
  create_pufferl, resolves 'latest' like eval does, calls
  backend.load_weights). Used for curriculum chaining (bootstrap → anneal)
  and BC warm starts. CUDA backend loads its OWN flat-fp32 .bin fine;
  state_dict-style .bins (BC pretrain output) need the converter noted in
  training/bc_pretrain.py before GPU warm-start.
- **Every obs bump = LINEAGE BREAK. Current runtime: obs-v5, `BBE_OBS_SIZE` =
  2782** (obs-v4's three probability planes plus decision-window truth; spec
  `docs/obs-v5-spec.md`). Lineage history: v2 832 → v3 1612 → v4 2782 → v5
  2782. The equal v4/v5 shape makes size insufficient: never warm-start a v5
  runtime from a v4 checkpoint. BBP v3 identifies newly extracted obs-v5
  shards; historical BBP v2/2782 identifies obs-v4, and the BC loader rejects
  mixed versions. THREE OBS_SIZE sync points must still agree
  (static asserts catch 2 of 3): `BBE_OBS_SIZE` in `bloodbowl.h`,
  `#define OBS_SIZE` in `binding.c`, and `training/convert_checkpoint.py`
  (`DEFAULT_OBS_SIZE = 2782`; converting an older artifact needs an
  explicit `--obs-size 1612` for v3 / `--obs-size 832` for v2 — binding.c's
  literal once lagged at 1612 and the `_Static_assert` caught it exactly as
  designed, D54). The current historical pair store remains 2,085,330 obs-v4
  records across 12,304 BBP-v2 shards; it is not current obs-v5 training data.
  The
  strict embedded-rulesVersion BB2025 surface is 9,118 non-empty replay IDs and
  1,622,231 joined records (`runs/replay-audit-20260713/`). Never call shard count
  replay count or mix BB2020 into BC. Historical anchor lineage:
  **bc_v4** (not valid for obs-v5 warm-start; val exact 0.508; lives on the
  training boxes — local `training/` only holds ≤ bc_v3b).

### Recurrent evaluation state

The current installed Puffer stack applies
`training/puffer_recurrent_eval_state.patch` after exact joint actions. CUDA
graph warmup must restore primary and every frozen-bank recurrent buffer to
exact zero. Training is valid only with `reset_state=True` and evaluation mode
off because PPO does not retain each segment's initial recurrent state.
Evaluation starts from fresh games, preserves state across nonterminal rollout
calls, and clears a terminal row before forwarding the next game's observation.
Keep the captured device-gated reset launch proportional to active rows, not
layers × rows × hidden size. Graph-enabled qualification cells must use
`cudagraphs=10`, matching the frozen Puffer/canary warmup boundary. Reject `0`
because it captures the first execution before CUDA lazy initialization, and
reserve `-1` for the explicit graph-off parity cell. Source tests are not CUDA
acceptance: before a run,
measure graph-on/off deterministic parity and throughput, primary/frozen
post-terminal parity, construction checksums, and zero-update ratios on the
target GPU.

Install `training/puffer_frozen_prio_mask.patch` after the recurrent patch, then
install `training/puffer_recurrent_cuda_qualification.patch` last and use
`tools/qualify_recurrent_cuda.py` for target-GPU evidence. Frozen sampling must
be explicitly masked: zero advantage is not exclusion when `prio_alpha=0`
because `0^0` produces unit weight.
Build this qualification in fp32. BF16 rounds the stored behavior log
probability before PPO recomputation and is deliberately rejected rather than
given a misleading near-unity ratio tolerance.
The runner uses fresh subprocesses and a bounded raw snapshot; it rejects
an observed candidate that differs from its predeclared clean source commit or
candidate module/backend/environment hashes,
missing banks/buffers, incomplete sampled ratio-row coverage, changed weights,
non-finite or nonzero values across the 16-key control hard-integrity registry
in every transition-executing cell (the construction-only cell emits no episode
telemetry), any selected frozen row, and an
absent, loosely shaped, unhashed, or identity-mismatched
same-host predecessor throughput report. The predecessor module/backend/
runtime/environment hashes must be declared both when captured and when
consumed. Its
runtime must be built after the immutable recovery boundary in a fresh isolated
fp32 checkout at exact commit `afc8008933548438ca93c41341f5f08fdd294386`.
Require obs-v5, exact-joint-v1, matching compiled hashes, and no qualification
surface. The former exact candidate
`a52fc6e2f4ece5a7ff16bb4791e3aca4dd72f2e3` used a different isolated source
checkout and Puffer tree but is permanently rejected under D223. A clean
merged schema-3 control-runner checkout must record and revalidate both full commits,
source-local Puffer paths, installer checks, and runtime hashes. The occupied
recovery runtime is marginal-action historical evidence, not a predecessor;
never modify or reuse the recovery Puffer tree.
The first schema-3 predecessor capture is rejected and must not be retried in
place: its runner compared the immutable predecessor's historical compiled
digest with the expanded registry. D224 requires a role-correct
compiled-source digest plus a separate complete runtime-source digest. Always
include `pufferlib/selfplay.py` in the latter for both roles and revalidate both
digests from disk; separately predeclare the predecessor runtime digest. Keep
its historical upstream/unpatched self-play file, and apply the league patch
only to the current candidate. Do not rebuild the predecessor to change its compiled
identity; use a fresh capture output and newly merged control/candidate root.
The D224-era `predecessor-throughput-v2` and `predecessor-throughput-v3`
captures are also rejected and non-retryable: loading `_C` before the process's
first CUDART call left the WSL worker reporting `cudaErrorNoDevice`. An
out-of-process `nvidia-smi`, Torch, or CUDART probe is not evidence for that
worker. Use the source-bound `tools/puffer_cuda_runtime.py` boundary in every
qualification worker and the real trainer process. It must load and retain the
exact resolved `libcudart.so.12`, require `cudaSuccess` with a positive device
count before `_C` import, repeat the call after import, require the unchanged
positive count, and record the CUDART path/hash plus `CUDA_VISIBLE_DEVICES`.
Predecessor and candidate throughput must agree on the runtime hash and count.
Never repair a failed process or run a third unchanged capture. The candidate
native binding must check the `cudaGetDeviceCount` return code and raise a
Python-visible error containing CUDA name/string rather than assert only on the
count. Before any new timed capture, merge/review this contract, use fresh clean
control/candidate roots, and pass one construction-only target integration.
The D225 `ee7ace4` screen launcher remains historical and unauthorized. D226's
replacement launcher is launch-inert until the exact final merged authorization
commit receives a fresh schema-3 qualification: the earlier accepted D225
qualification is a prerequisite, never authority for changed launcher bytes.
After that fresh qualification accepts, freeze a plan authorization before the
two-file plan-only output and a separate launch authorization afterward. The
launch authority binds the released zero-byte lock, immutable screen manifest,
canonical disabled one-shot unit, and initially empty stopped-validation root.
Treat the construction artifact as a required executable input: both
`capture-throughput` and full `run` must receive the same
`--construction-gate`, revalidate its current module/backend/environment/CUDART
identity before output or worker dispatch, and bind its path/hash in their
artifacts.
For predecessor timing, pass the complete frozen predecessor identity into the
same worker process. Validate it immediately after `_C` import and before
`create_pufferl`, warmup, or rollout; a parent-only post-timing rejection is a
wasted, non-retryable capture under the exact-zero budget.
The trainer wrapper explicitly imports `_C` and atomically publishes
its own complete pre/post evidence into the pending run manifest before
optimization; the earlier launcher probe is only a separately labeled
expectation and must match. Preserve the hash-bound evidence with checkpoints.
The archived `a52fc6e2` canary manifest keeps its original 11-key live fail-fast
registry. Never dirty or relabel that rejected checkout to widen its manifest.
The replacement v4 manifest instead freezes the complete 16-key control registry
live and at stopped validation: the former 11 plus signed clamp delta, clipped
samples, terminal/non-terminal clipped samples, and non-finite samples per
episode. Any missing, non-finite, nonzero, or internally inconsistent value
invalidates the run. Only the exact D226 plan and launch authorization artifacts
may admit `exact-action-canary-50m-s42-v4`; absent, relative, stale, mismatched,
or reused authority must reject before output mutation or optimization. Never
invoke v1/v2/v3 or analyze them as replacement evidence.
The sole `a52fc6e2` canary start is rejected and permanently non-retryable: its
last preflight found `training/selfplay_league.patch` unapplied before GPU use.
Qualification schema 3 requires that the replacement candidate and control
runner use the same operator-predeclared merged commit in different isolated
source checkouts and rejects a value unequal to the control runner's clean `HEAD`. The
installer applies or fully
reverse-verifies that patch, `pufferlib/selfplay.py` participates in backend
identity, and qualification provenance binds the patch file. Recapture the
fixed predecessor from `afc8008933548438ca93c41341f5f08fdd294386` with the
schema-3 runner, use fresh runtime/qualification/canary identities, and never
modify or reuse the recovery Puffer tree. The qualified CUDART path, SHA-256,
device count, and `CUDA_VISIBLE_DEVICES=0` must flow through the plan, screen,
launch record, per-run manifest, and trainer environment. The same-process
trainer pre/post evidence must match that declaration before optimization; an
external launcher probe alone is not authority. Keep qualification and canary
checkpoints permanently ancestry-, reward-, promotion-, and BBTV-ineligible.
The explicit recurrent-state clear is
only the paired post-terminal control and must never be used to alter ordinary
training/evaluation behavior. Qualification outputs and checkpoints are never
eligible ancestry.

## Historical BC-regularized PPO patch (rejected for new runs)

The AlphaStar-style human anchor was tested after D27. When `[train] bc_coef > 0`,
every PPO minibatch in the TORCH
backend (`--slowly`) also pays `bc_coef *` masked 3-head CE on `bc_batch`
human pairs sampled from the `.bbp` shards in `bc_pairs_dir`, zero recurrent
state (= bc_pretrain v0). `bc_coef_anneal=1` cosine-decays bc_coef to 10%
over total_timesteps. Dashboard/wandb keys: `loss/bc_loss`, `loss/bc_acc`,
`loss/bc_coef`. TORCH BACKEND ONLY — the native CUDA trainer ignores bc_*.

**D176 rejected this mechanism for new runs:** coefficient-1 iid CE collapsed
offense to zero while the no-anchor control stayed functional. The patch also
eagerly preloads every shard and has no replay-ID/edition allowlist, so the
legacy `validation/pairs` path can mix rules editions. Keep `bc_coef=0`; any
reconsideration needs bounded streaming, a BB2025-exact allowlist, and a new
controlled hypothesis. Masked sampling and asymmetric training are separate
facilities in the installed patch stack; they are not supplied by this BC patch.

- Config keys live in `puffer/config/bloodbowl.ini` `[train]` (bc_coef
  default 0.0 = off and bit-identical to unpatched; bc_pairs_dir; bc_batch;
  bc_coef_anneal) and reach vendor via `tools/install_puffer_env.sh`.
- **Reapply after any vendor re-clone** (vendor/*/ is gitignored):
  `cd vendor/PufferLib && git apply ../../training/torch_pufferl_bcreg.patch`
  then re-validate with
  `vendor/PufferLib/.venv/bin/python training/test_bcreg_torch_pufferl.py`
  (proves off-mode bit-identity vs pristine HEAD + on-mode bc_loss decrease).
  `tools/run_bcreg.sh` auto-applies the patch if the marker is missing.
- Historical reproduction recipe only: `tools/run_bcreg.sh` — torch backend
  on the CUDA box
  (`rm -rf build && ./build.sh bloodbowl --float`; bf16 default build refuses
  to import), `--selfplay.enabled 0` (pool is native-only), warm start from a
  v4 anchor under a pinned v4 runtime (state_dict loads directly in the torch
  backend — no converter; the script's hardcoded training/bc_v1.bin is dead
  obs-v2 lineage). Never run this historical recipe against the current v5
  runtime, even with a shape-loadable bc_v4 checkpoint. B-profile reward knobs,
  bc_coef 1.0 annealed.
- Current arms launch via `tools/run_synthesis_c.sh`, run ON the box from the
  repo root. Contract: `ANCHOR=<path>` `STEPS=<n>` env vars + extra
  `--env.*` / `--train.frozen-enemy-path <ckpt>` args forwarded via `"$@"`.
  **In the v4 era ANCHOR is effectively MANDATORY**: the script's default
  (training/bc_v3b.bin) is dead obs-v3 lineage, and its size guard
  (`> 13 MB`, run_synthesis_c.sh:31) only rejects the obs-832 era — a
  13.68 MB v3 state_dict passes the guard and then fails against the
  2782-input net. The script also refuses to double-launch, hard-fails on a
  missing/small demo bank, and prints LIVE / TRAINER DIED at ~40s — always
  read that line.
- Warm relaunch: checkpoints land under `vendor/PufferLib/checkpoints/`
  (`[base] checkpoint_dir` in config/default.ini) per run dir; pick the
  anchor by the STEP NUMBER in the filename (e.g. 0000014942470144.bin) —
  **newest mtime ≠ highest step across run dirs.**

## Heterogeneous league seeding (local selfplay.py patch)

Stock `selfplay.setup()` keeps pool state in memory only and UNCONDITIONALLY
bootstraps: it saves the learner's current weights as
`<ckpt>/<env>/<run_id>/pool/{global_step:016d}.bin` and loads that one file
into every frozen bank (selfplay.py:169-175 at the 4.0 pin). The league
patch adds a `[selfplay] league_preseed` key: when it names a pool dir built
by `tools/build_league.py` (`league_seeds.json` manifest + one flat-fp32
`.bin` per bank, named `{bank:016d}.bin`), each bank b loads seed b instead,
the opponent pool starts as the ordered seed set, that dir becomes the run's
pool_dir (snapshots accumulate next to the seeds), and the bootstrap save is
skipped. Empty key = upstream behavior (the bootstrap case dedupes back to a
single pool entry). Seed sizes are hard-verified in Python because the C
loader (`pufferl_load_frozen_bank`, pufferlib.cu:1830) only fprintf-warns on
size mismatch and silently keeps the bank's old weights.

- **Reapply after any vendor re-clone** (vendor/*/ is gitignored):
  `cd vendor/PufferLib && git apply ../../training/selfplay_league.patch`
  then re-validate with `python3 training/test_selfplay_league.py`
  (stubbed-backend proof that setup() loads each seed into its bank, plus
  bootstrap-path upstream-equivalence). `tools/run_league.sh` auto-applies
  the patch if the `league_preseed` marker is missing from selfplay.py.
- Config key lives in `puffer/config/bloodbowl.ini` `[selfplay]`
  (`league_preseed =`, empty default) and reaches vendor via
  `tools/install_puffer_env.sh` — note the `--check` hash covers ocean/ only,
  not the ini, so run_league.sh refreshes the ini itself when the key is
  missing.
- Launch recipe: `tools/run_league.sh` — native CUDA backend (pool/banks are
  CUDA-only), 5 banks (profile-A final / profile-D final / BC-init / anneal
  stage-1 / anneal graduate), warm start from the graduate,
  `--vec.num-frozen-banks 5 --vec.frozen-bank-pct 0.08` (163 rows/bank, 815
  total < apb/2 = 1024; 326 hist envs/bank arms min_games=2048 in ~105M
  steps worst-case vs the 500M timeout — math derivation in the script
  header), B-profile reward knobs, snapshot_interval 500M, tag
  profile-league. Seed paths resolve from PROFILE markers with
  `LEAGUE_SEED_*` env overrides.
