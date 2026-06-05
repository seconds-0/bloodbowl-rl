---
name: puffer-env-dev
description: Use when writing or debugging the native C env binding for PufferLib 4.0 (vendor/PufferLib) — binding.c macros, Env struct, action masks, two-player self-play perm/tags, build.sh, config .ini, puffer train/eval/match, or any "how do I hook the BB engine into Puffer" question.
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
legal bits). The mask is consumed GPU-side: `masked_logit` in `src/pufferlib.cu:430-439`
sets masked logits to `-1e4` during sampling and the same masking applies in the train
pass. The policy never *sees* the mask as input — chess additionally encodes legality
into obs features (`O_VALID_FROM`/`O_VALID_TO` square lists) so the net can learn it.
All-zero mask doesn't crash (uniform over -1e4 logits) but samples garbage — always
leave ≥1 bit set (give BB an explicit end-turn/no-op action that is always legal).

**Masks exist only in the native CUDA backend.** `pufferlib/torch_pufferl.py` (the
`--slowly` / `--cpu` path) has zero mask plumbing — invalid actions WILL be sampled
there, so `c_step` must tolerate any in-range action value (chess answers invalid picks
with `reward_invalid_*` penalties, binding.c kwargs).

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
cd vendor/PufferLib
# 1. "Register" = create the directory + config. For our env, symlink out of the repo:
ln -s ../../../engine ocean/bloodbowl        # or a puffer/bloodbowl dir holding binding.c + bloodbowl.h
cp config/squared.ini config/bloodbowl.ini   # set [base] env_name = bloodbowl; add [env] keys
# config discovery: load_config scans config/**/*.ini for env_name in [base] (pufferl.py:620-625)

# 2. Iterate in pure C first (fastest builds, ASan on Linux):
./build.sh bloodbowl --local     # debug standalone from ocean/bloodbowl/bloodbowl.c (needs a main())
./build.sh bloodbowl --fast      # optimized standalone

# 3. Training backend:
./build.sh bloodbowl             # CUDA backend (Linux + nvcc), bf16 by default
./build.sh bloodbowl --float     # fp32 precision
./build.sh bloodbowl --debug     # -O0 -g
./build.sh bloodbowl --cpu       # Mac/CPU: torch-only backend (<200k sps, no masks)

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
training (and anything mask-dependent) happens on a Linux GPU box.

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

## Operational gotchas discovered in production (2026-06-04)

- **The post-training eval tail HANGS for long-episode envs.** After
  total_timesteps, _train runs eval epochs until `env/n > eval_episodes`
  (10000 default). Our episodes are 300-900 decisions, so this is hours —
  and it pins the box silently at the final Steps count (log mtime frozen,
  0% CPU pattern). Fix per run: `--eval-episodes 100`-ish, or just pkill
  after the final checkpoint lands (checkpoints save during training; the
  eval tail adds nothing we use).
- **`puffer train` has NO upstream warm-start.** load_model_path is only
  read by eval()/match(). We patch _train in the VENDORED pufferl.py
  (gitignored — re-apply after any re-clone; patch lives right after
  create_pufferl, resolves 'latest' like eval does, calls
  backend.load_weights). Used for curriculum chaining (bootstrap → anneal)
  and BC warm starts. CUDA backend loads its OWN flat-fp32 .bin fine;
  state_dict-style .bins (BC pretrain output) need the converter noted in
  training/bc_pretrain.py before GPU warm-start.
- **obs v3 = LINEAGE BREAK (cycle-2 integration, 2026-06-04).**
  `BBE_OBS_SIZE` went 832 → 1612 (two 390-byte tackle-zone planes appended
  after the unchanged 832 layout; offsets documented in
  `puffer/bloodbowl/bloodbowl.h`). The encoder input dim is part of the
  parameter count, so EVERY pre-cycle-2 checkpoint (CUDA flat blob
  12,072,960 B; torch state_dicts incl. training/bc_v1.bin / bc_v15.bin) is
  incompatible with the obs-v3 binding — they are archived in
  `checkpoints-backup/`, never warm-start from them. The obs-v3 blob is
  13,670,400 B (3,417,600 fp32); `training/convert_checkpoint.py` and
  `tools/build_league.py` default to it, and converting an archived 832
  artifact stays possible with an explicit `--obs-size 832` /
  `--expect-bytes 12072960`. BC pairs must be .bbp v2 (re-extracted;
  obs lineages never mix in one corpus) — current anchor checkpoint:
  training/bc_v2.bin.

## BC-regularized PPO (local torch_pufferl.py patch)

The AlphaStar-style human anchor (DECISIONS.md D27: selfplay PPO erodes the
BC prior): when `[train] bc_coef > 0`, every PPO minibatch in the TORCH
backend (`--slowly`) also pays `bc_coef *` masked 3-head CE on `bc_batch`
human pairs sampled from the `.bbp` shards in `bc_pairs_dir`, zero recurrent
state (= bc_pretrain v0). `bc_coef_anneal=1` cosine-decays bc_coef to 10%
over total_timesteps. Dashboard/wandb keys: `loss/bc_loss`, `loss/bc_acc`,
`loss/bc_coef`. TORCH BACKEND ONLY — the native CUDA trainer ignores bc_*.

- Config keys live in `puffer/config/bloodbowl.ini` `[train]` (bc_coef
  default 0.0 = off and bit-identical to unpatched; bc_pairs_dir; bc_batch;
  bc_coef_anneal) and reach vendor via `tools/install_puffer_env.sh`.
- **Reapply after any vendor re-clone** (vendor/*/ is gitignored):
  `cd vendor/PufferLib && git apply ../../training/torch_pufferl_bcreg.patch`
  then re-validate with
  `vendor/PufferLib/.venv/bin/python training/test_bcreg_torch_pufferl.py`
  (proves off-mode bit-identity vs pristine HEAD + on-mode bc_loss decrease).
  `tools/run_bcreg.sh` auto-applies the patch if the marker is missing.
- Launch recipe: `tools/run_bcreg.sh` — torch backend on the CUDA box
  (`./build.sh bloodbowl --float`; bf16 default build refuses to import),
  `--selfplay.enabled 0` (pool is native-only), warm start from
  training/bc_v1.bin (state_dict loads directly in the torch backend — no
  converter), B-profile reward knobs, bc_coef 1.0 annealed.

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
