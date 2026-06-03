# vecenv.h / backend internals (PufferLib 4.0, vendored at vendor/PufferLib)

Line numbers refer to the vendored tree. Read alongside `vendor/PufferLib/src/vecenv.h`.

## StaticVec (vecenv.h:73-100)

```c
typedef struct StaticVec {
    void* envs;                  // Env[size], allocated by my_vec_init
    int size;                    // number of env instances
    int total_agents;            // == [vec] total_agents
    int buffers;                 // == [vec] num_buffers
    int agents_per_buffer;       // total_agents / buffers
    int* buffer_env_starts;      // env index where buffer b starts
    int* buffer_env_counts;      // envs in buffer b
    void* observations;          // host (pinned when gpu=1): total_agents * OBS_SIZE * elem
    float* actions;              // total_agents * NUM_ATNS
    float* rewards;              // total_agents
    float* terminals;            // total_agents
    unsigned char* action_mask;  // total_agents * MY_ACTION_MASK, NULL unless opted in
    void* gpu_observations; ...  // device mirrors; on CPU builds they ALIAS the host ptrs (vecenv.h:441-445)
    int* agent_perm;             // perm[slot] = physical row; NULL = identity (MY_USES_PERM only)
} StaticVec;
```

## Env creation flow

`create_static_vec` (vecenv.h:402) → `my_vec_init` (yours, or default at vecenv.h:350).

Default `my_vec_init`: loops `my_init(&envs[i], env_kwargs)` until `sum(num_agents) ==
total_agents`, sets `envs[i].rng = i`, then chunks envs into buffers greedily
(`buf_agents >= agents_per_buffer` rolls to next buffer). Custom `my_vec_init`
(MY_VEC_INIT) must fill `buffer_env_starts/counts` itself — copy the loop from
`ocean/chess/binding.c:138-151`. Process-wide shared state (curricula, tables) is loaded
once in `my_vec_init` into file-static globals and freed in `my_vec_close`
(SHARED_FEN_CURRICULUM pattern, chess binding.c:32-70 + 157-166).

After my_vec_init, the vec assigns per-slot pointers (vecenv.h:466-491). Under
MY_USES_PERM it additionally calls `my_setup_perm(vec, env, slot_base)` per env — both
at init (identity) and again on every `static_vec_set_perm` (vecenv.h:496-521).

## Threading / stepping (vecenv.h:239-342)

- One pthread per buffer (`static_omp_threadmanager`), spun up by
  `create_static_threads`; each owns a CUDA stream created by `pufferlib.cu`
  (PyTorch-managed; vecenv.h:595 comment).
- Per horizon step `t`: `net_callback` (GPU forward) → async D2H actions → memset
  rewards/terminals (lines 288-289) → `#pragma omp parallel for` over the buffer's envs
  calling `c_step` (num_workers = num_threads / buffers) → async H2D obs/rew/term/mask.
- Sync single-step path for eval/torch backend: `static_vec_step` → `cpu_vec_step` /
  `gpu_vec_step` (vecenv.h:751-774; asserts `buffers == 1`).
- Profiling: `static_vec_read_profile` returns ms split between EVAL_GPU and
  EVAL_ENV_STEP — the "Evaluate / GPU / Env" rows in the dashboard.

## Log aggregation (vecenv.h:665-710)

`static_vec_aggregate_logs` treats Log as a float array (`sizeof(Log)/sizeof(float)`
keys), sums envs with `log.n != 0`, divides every field by total n. `static_vec_log`
(training) zeroes all env logs after reading; `static_vec_eval_log` does NOT zero
(used by eval/match to accumulate across rollouts until `env/n >= num_games`).

## Pybind export surface

CUDA backend (`src/bindings.cu:509-620`, module `pufferlib._C`):
`env_name`, `gpu=1`, `precision_bytes`, `create_pufferl`, `rollouts`, `train`, `log`,
`eval_log`, `render`, `close`, `save_weights`, `load_weights`, `add_frozen_bank`,
`load_frozen_bank`, `set_agent_perm`, `set_env_tags`, `count_aligned`, `num_envs`,
`create_vec`, `get_nccl_id`, `get_utilization`, `puff_advantage`.

CPU backend (`src/bindings_cpu.cpp:160-186`): only `env_name`, `gpu=0`,
`puff_advantage_cpu`, `create_vec` and a `VecEnv` class with
`reset/cpu_step/render/log/close`. **No create_pufferl, no perm/tags/banks** → on a
`--cpu` build you must train with `--slowly` (torch backend drives `_C.create_vec` +
`cpu_step`, see `pufferlib/torch_pufferl.py:418, :241`), and self-play pool + action
masks are unavailable.

`_resolve_backend` (pufferl.py:171-178): asserts `_C.env_name == args['env_name']`,
returns `torch_pufferl.PuffeRL` iff `--slowly` else `_C`.

## Action-mask plumbing (CUDA backend)

- `pufferlib.cu:238-255`: vec's mask becomes a `ByteTensor (total_agents, mask_size)`;
  `mask_size = vec->action_mask_size` (0 = disabled, all code paths null-safe).
- Rollout storage `(horizon, agents, mask_size)` (pufferlib.cu:60, 87) so the train
  pass replays the same mask per timestep; minibatch view at :106-136.
- Sampling: `masked_logit` (pufferlib.cu:430-439) → masked logits = -1e4.
  `sample_logits` walks heads via `act_sizes` with running `logits_offset`
  (:500-553); cumsum-rounding fallback scans backwards for the last *legal* action
  (:536-549). Same masking used when recomputing logprobs/entropy in training (:838+).

## Self-play pool row layout (selfplay.py:50-116)

Per buffer (apb = agents_per_buffer, F = sum of per-bank frozen sizes):

```
rows [0,        apb - 2F)   primary — pure selfplay envs (both teams), tag 0
rows [apb - 2F, apb - F )   primary — historical envs' team A
rows [apb - F + sum(fs[:b]), apb - F + sum(fs[:b+1]))  bank b — historical envs' team B, tag b+1
```

`build_perm_tags` produces `perm` (env-slot → physical row; my_setup_perm consumes it)
and per-env `tags` (set via `static_vec_set_env_tags`, requires MY_USES_TAGS). Env order
in a buffer: selfplay envs first, then historical envs in bank-block order. The C-side
frozen banks are separate policy weights laid out after primary (pufferlib.cu ~:1798,
:2069 per comments in selfplay.py); `frozen_bank_pct` is **per bank**.

Swap handshake: when a bank's winrate ≥ swap_winrate over ≥ min_games (or
opp_timeout_steps elapsed), `pending_opp_path` is armed; the actual
`load_frozen_bank` only fires once `count_aligned(tag, 0) >= num_hist_envs`
(every historical env finished ≥1 game since arming — that's `boundary_reached`,
reset by `count_aligned(tag, 1)`). Stats `hist_score/hist_n` reset on swap so winrate
is per-opponent. `static_vec_count_aligned` is in vecenv.h:532-552.

Winrate signal path: env C code accumulates `log.hist_score_bank[b]` (1 win / 0.5 draw /
0 loss for PRIMARY) and `log.hist_n_bank[b]` on envs with `tag == b+1` →
`my_log` exports `hist_score_bank_<b>` → log aggregation divides by n →
`selfplay.step` re-multiplies by `env/n` (selfplay.py:224-225) to recover sums.

## puffer match (pufferl.py:497-583)

Head-to-head eval of two checkpoints: pins `num_buffers=2, total_agents=8192`,
`num_frozen_banks=1, frozen_bank_pct=0.5`, builds a perm putting each env's slot 0 in
primary's half and slot 1 in the frozen half, loads A into primary and B into the bank,
then loops `rollouts` + `eval_log` until `env/n >= num_games`. Reads
`env/slot_0_score` / `env/slot_1_score` / `env/draw_rate` — so a 2-player env should
maintain those Log fields (chess.h Log:385-386). Enemy arch can differ via
`--enemy-hidden-size/--enemy-num-layers` (→ `frozen_bank_hidden_size/num_layers`).
Sweeps can score trials by match winrate instead of training score via
`[sweep] match_enemy_model_path` (see config/chess.ini).

## Misc facts worth knowing

- `default.ini` keys not in your env's ini still apply (configparser reads
  `[puffer_default_config, path]`), e.g. `cudagraphs = 10` (capture epoch),
  `reset_state`, `checkpoint_interval = 500`.
- Checkpoints: `checkpoints/<env>/<run_id>/<global_step:016d>.bin`;
  `--load-model-path latest` = newest .bin by ctime under `checkpoints/<env>/**`.
- bf16 is the default precision; torch backend refuses it (`torch_pufferl.py:21`) —
  build `--float` (or `--cpu`, which implies it) for `--slowly`.
- `MY_SHARED/MY_GET/MY_PUT` optional hooks exist (vecenv.h:776-797) for shared state /
  Python-side state injection; defaults are no-ops, no ocean env in this tree uses
  them prominently.
- Scale sanity anchor: chess trains at high SPS with 8192 agents, 167-byte obs,
  a 97-way masked single head, and a ~3.2k-line .h.
