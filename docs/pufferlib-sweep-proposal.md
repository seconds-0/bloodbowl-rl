# PufferLib hyperparameter sweep: research + proposal for bloodbowl-rl

Joseph Suarez (PufferLib founder) suggested running a hyperparameter sweep. This doc
(1) documents how PufferLib 4.0's sweep tooling (`Protein`, CARBS-derived) actually
works, grounded in the vendored source at the pinned commit
(`vendor/PufferLib` @ `9836f0d2e` per `vendor/PINS.md`), and (2) proposes a concrete,
de-risked sweep plan for this repo's bloodbowl env.

**Headline finding (read this first):** a plain `puffer sweep bloodbowl` will
**deadlock/crash** as shipped, because the non-match-mode result path hardcodes a
`env/score` key that the bloodbowl binding never emits (§1.6). The proposal below
works around this by using PufferLib's **match-mode** sweep scoring (the same
machinery `config/chess.ini` already uses), which both sidesteps the bug and gives
us a metric we actually trust for self-play. See §2.2/§2.5.

---

## Part 1 — Research

### 1.1 Where the sweep code lives

- **`vendor/PufferLib/pufferlib/sweep.py`** (977 lines) — the entire optimizer stack:
  normalization `Space` classes (`Linear`, `Pow2`, `Log`, `Logit`, L46–140), config
  parsing (`_params_from_puffer_sweep`, L141–182; `Hyperparameters`, L184–254), Pareto
  utilities (`pareto_points` L256–276, `prune_pareto_front` L278–306), and three
  optimizer classes: `Random` (L309–339), `ParetoGenetic` (L342–396), and **`Protein`**
  (L522–977, the default and the one we'll use).
- **`vendor/PufferLib/pufferlib/pufferl.py`** — the CLI entrypoint and training loop:
  - `_train()` (L190–389): single-trial worker; computes `target_key =
    f'env/{args["sweep"]["metric"]}'` (L204), optional match-mode scoring (L208–211,
    L319–336), and reports back via `result_queue` (L383–389).
  - `train()` (L391–416), `sweep()` (L418–478): the sweep driver loop.
  - `load_config()` (L597–671): turns `config/*.ini` + CLI flags into the nested
    `args` dict that everything else consumes.
  - `main()` (L673+): `puffer [train|eval|sweep|paretosweep|match] <env> ...`
    dispatch; `sweep` → `sweep(env_name, args, pareto='pareto' in mode)` (L686–687).
- **Config**: `vendor/PufferLib/config/default.ini` `[sweep]` (L91–110) +
  `[sweep.train.*]`/`[sweep.policy.*]`/`[sweep.vec.*]` blocks (L111–252);
  `vendor/PufferLib/config/chess.ini` `[sweep]` (L68–98) — the **match-mode**
  reference implementation (chess is PINS.md's "best template" for our env); our own
  `puffer/config/bloodbowl.ini` `[sweep]` (L215–227) already has a one-param stub.

No `carbs` import anywhere — Protein is a from-scratch reimplementation, not a CARBS
dependency (consistent with the blog post, §1.3).

### 1.2 The optimization algorithm: Protein (CARBS-derived)

**Search space normalization.** Every swept hyperparameter is wrapped in a `Space`
subclass that maps `[min, max]` → `[-1, 1]` (`sweep.py` L46–140):

| `distribution` | Class | Behavior |
|---|---|---|
| `uniform` | `Linear` (L57) | linear map |
| `int_uniform` | `Linear(is_integer=True)` | linear map, rounded |
| `uniform_pow2` | `Pow2` (L76) | log2-spaced, rounds to nearest power of 2 |
| `log_normal` | `Log` (L96, base 10) | log-spaced; `scale='time'` sets `scale = 1/(log2(max)-log2(min))` |
| `logit_normal` | `Logit` (L122, base 10) | logit-spaced, for values bounded in (0,1) like `gamma`/`gae_lambda` |

`scale` controls the per-dimension jitter radius used when sampling around a search
center; `scale='auto'` → `0.5` for all four classes. `Hyperparameters.search_centers`
(L195–196) defaults every dimension to its **normalized midpoint** (`norm_mean = 0`)
— i.e., the first suggestion (`suggestion_idx == 1`, before the Sobol phase even
starts — actually the very first point comes from the **training run's own
config values**, since `sweep()` only calls `sweep_obj.suggest()` when `idx > 1`,
L465: *"First experiment uses defaults"*).

**Two Gaussian Processes** (L399–446, `gpytorch`): `gp_score` and `gp_cost`, each an
`ExactGPModel` with a `ConstantMean` + `ScaleKernel(AdditiveKernel(PolynomialKernel(power=1), MaternKernel(nu=1.5)))`
— i.e. Matérn-3/2 (CARBS's choice too) plus a linear term, trained with Adam
(`gp_learning_rate=0.001`, `gp_training_iter=50` steps per suggestion, L425–446).
`GaussianLikelihood` uses a `LogNormalPrior(log(1e-2), 0.5)` noise prior — "Params
taken from HEBO" (sweep.py L597, citing arXiv:2012.03826).

**The suggestion loop** (`Protein.suggest`, L750–900):
1. **Suggestions 1–10** (`num_random_samples=10`, default): drawn from a **scrambled
   Sobol sequence** over the normalized `[-1,1]^d` cube (L763–771) — structured
   low-discrepancy exploration, not pure random. This is how Protein bootstraps an
   initial Pareto set without any GP.
2. **After that**, retrain both GPs on up to `gp_max_obs=750` observations
   (deduplicated via a `KDTree`, L632–647; sampled with `recent_ratio=0.5` so half
   the training set is always the most recent runs, L649–690).
3. Compute the **Pareto front of (score, cost)** via `pareto_points` (L256–276: sort
   by cost, keep points that improve on the best-score-so-far) and prune the
   inefficient high-cost tail via `prune_pareto_front` (L278–306, `efficiency_threshold=0.5`).
4. Sample `suggestions_per_pareto=256` candidates per Pareto point (plus the
   top-5 observations by score, `_get_top_obs_params`, L723–741, for diversity) via
   per-dimension jitter (`Hyperparameters.sample`, L213–224).
5. **Predict score & cost for every candidate** with the two GPs (batched,
   `infer_batch_size=4096`, L817–854).
6. **Acquisition function** (L857–864):
   ```
   suggestion_score = optimize_direction * gp_y_norm
                     * [gp_c < max_suggestion_cost]
                     * (1 - |target_cost_ratio - gp_log_c_norm|)
   ```
   `target_cost_ratio = (1 + expansion_rate) * ratio`, `expansion_rate=0.1`, where
   `ratio` is drawn from a shuffled bag `{0.16, 0.32, 0.48, 0.64, 0.8, 1.0}` jittered
   by `N(0, 0.1)` (`_sample_target_cost_ratio`, L743–748). This is the blog's
   `GP_y(x) · (1 - |αU − GP_c(x)|)` acquisition (α here ≈ 1.1, applied to a
   *discrete* set of target cost fractions rather than one continuous `U`) — **it
   explicitly samples across the cost axis** so a fixed fraction of trials always
   targets cheaper/more-expensive regions, which is how Protein "explores the
   Pareto frontier" without an explicit Pareto-frontier *model* (CARBS's failure
   mode, per the blog).
7. Argmax → unnormalize → return as a hyperparameter dict.

**Early stopping** (`should_stop`/`early_stop`, L948–976, wired in at `pufferl.py`
L298–301): a `RobustLogCostModel` (L449–518) fits **quantile regression**
(`early_stop_quantile=0.3`, i.e. 30th percentile) of `score ~ A + B·log(cost)` via
Nelder-Mead pinball loss, needs `min_num_samples=30` to activate, and kills a trial
whose running-mean metric falls below the 30th-percentile curve for its current
cost. Gated by `pufferl.py` L299: a trial is only eligible for the chop after
`global_step > min(0.20 * total_timesteps, 100_000_000)`.

**Failure handling**: NaN losses, non-finite scores, or `validate_config` exceptions
(L470–473) are recorded as `is_failure=True` observations (score = current
`min_score`, L920–923/665–672) — these get blended into early GP fits (when <100
successes exist) to steer the GP away from broken regions, without being part of the
Pareto front.

### 1.3 How many trials, and the speed-vs-score tradeoff

- `default.ini` ships `max_runs = 1200` (L97) — Protein is designed for **large**
  sweeps. The Sobol phase (10 trials) + `optimizer_reset_frequency=50` (periodic GP
  optimizer resets, L782–785) + `gp_max_obs=750` all imply it's tuned for
  hundreds-of-trials regimes.
- From the blog ("Stronger Hyperparameters with Protein", fetched via
  `puffer.ai/blog.html`): Protein's core logic is **<100 lines** vs CARBS's 2500+; it
  fixes CARBS's instability on small Pareto sets (CARBS needed ~20% resampling
  overhead to compensate for "lucky seed" Pareto points). On Breakout, a single
  sweep's hyperparameters transferred to "nearly all Ocean environments", eliminating
  the prior ~200-experiments-per-env practice — i.e. **Suarez's own usage pattern is
  "one moderately-sized sweep on a cheap proxy, then reuse the result broadly"**,
  exactly the shape we want for a 4090-hour-constrained project.
- For a **small** sweep (20–50 trials, our budget — see §2.4), expect: 10 Sobol
  points + a handful of GP-guided refinements. Treat the output as a **ranked
  shortlist of 3–5 promising configs**, not a converged global optimum — `gp_max_obs`
  and `optimizer_reset_frequency` never even trigger at this scale.
- **Pareto / speed-vs-score**: by default `cost_param = "train/total_timesteps"`
  (Protein `__init__` kwarg, L538) — if `[sweep.train.total_timesteps]` is swept
  (as in `default.ini` L111–115 and `chess.ini` L77–83), Protein treats "how long to
  train" as itself a tunable axis and jointly searches the score-vs-steps Pareto
  frontier. If `total_timesteps` is **not** swept (our plan, §2.5), `cost_param_idx`
  is `None` (L575–580) — Protein still fits `gp_cost` against real wall-clock
  `cost` (the `uptime` log field, see `pufferl.py` L386–389) and still applies the
  cost-aware acquisition weighting (step 6 above doesn't require `cost_param_idx`),
  it just can't *directly dial* `total_timesteps` per-suggestion. This is fine for
  us: at fixed `total_timesteps`, "cost" still varies with `minibatch_size`/
  `horizon`/`update_epochs` (throughput), so the cost-GP remains meaningful.

### 1.4 `puffer sweep` CLI usage

From `pufferl.py` `main()` (L673–687) and `load_config()` (L597–671):

```
puffer sweep <env_name> [--<section>.<key> <value> ...]
puffer paretosweep <env_name> [...]      # pareto='pareto' in mode → geomspaces
                                          # total_timesteps across sweep_gpus
```

- `load_config()` builds an `argparse` parser from **every** key in
  `config/default.ini` + `config/<env>.ini` (merged via `configparser`, L629–637),
  so **every** `[section].key` (including all of `[sweep.*]`) is overridable from
  the CLI as `--section.key value` (underscores → dashes, L650).
- `sweep()` (L418–478):
  - `sweep_gpus = args['sweep']['gpus'] or len(os.listdir('/proc/driver/nvidia/gpus'))`
    (L422) — `0` (the `default.ini` value, L98) means **auto-detect GPU count** from
    `/proc/driver/nvidia/gpus`. On a single-GPU Vast box this should resolve to `1`,
    but pass `--sweep.gpus 1` explicitly to avoid depending on that path existing in
    the container.
  - `args['vec']['num_threads'] //= (sweep_gpus // exp_gpus)` (L423) — on a 1-GPU box
    with `train.gpus=1`, this is `//1`, a no-op.
  - `method = sweep_config.pop('method')` (L427) then `getattr(pufferlib.sweep,
    method)` (L430) — so `[sweep] method = Protein` (the `default.ini` default,
    L92) selects the `Protein` class. `Random` and `ParetoGenetic` (sweep.py
    L309/342) are the only other valid values.
  - Main loop (L444–478): while `completed < max_runs`, pulls finished trials off
    `result_queue`, calls `sweep_obj.observe(...)`, then `sweep_obj.suggest(args,
    fixed_total_timesteps=...)` to mutate `args` in place for the next trial, then
    spawns `train(env_name, exp_args, range(gpu_id, gpu_id+exp_gpus), sweep_obj=...,
    result_queue=...)`.
  - **Single-GPU boxes run trials strictly sequentially** — `sweep_gpus //
    exp_gpus == 1` means only one trial is ever "active" at a time (L445).

### 1.5 wandb integration

- `_train()` L195–203: if `args['wandb']`, each trial calls `wandb.init(id=run_id,
  config=args, project=args['wandb_project'], group=args['wandb_group'],
  tags=[args['tag']])` — **one wandb run per trial**, grouped by `wandb_group`.
- L292–293 / L335–336: `wandb.log(flat_logs, step=agent_steps)` every ~0.6s-throttled
  epoch, plus `env/match_score` in match-mode.
- L376–379: model-artifact upload (`wandb.Artifact(run_id, type='model')`) only fires
  when `sweep_obj is None` — **sweep trials never upload model artifacts** (also
  `sweep()` sets `args['no_model_upload'] = True` at L424, belt-and-suspenders).
- **No resume support for Protein's own state.** `sweep_obj` (the `Protein`
  instance, with its GPs and `success_observations`/`failure_observations` history)
  lives only in the `sweep()` process's memory for the duration of the `while
  completed < num_experiments` loop (L444–478) — there is no `save`/`load` method on
  `Protein` (grep confirms none). Each trial's downsampled metrics + full config ARE
  persisted as JSON (`pufferl.py` L370–373, `experiments/<env>/<run_id>.json`) and to
  wandb, so **post-hoc analysis of individual trials survives a crash**, but
  re-seeding a fresh `Protein` from those JSONs to "resume" a killed sweep is **not
  built in** — you'd lose the GP state and have to either re-run or write custom
  glue to call `sweep_obj.observe()` for each old trial before resuming `suggest()`
  calls. Given D65's "box keeps billing after the run completes/dies" footgun, this
  argues for a sweep short enough to babysit in one sitting (§2.4/§2.6).

### 1.6 Critical compatibility finding: `env/score` doesn't exist for bloodbowl

`_train()`'s non-match-mode result path (`pufferl.py` L388–389):
```python
result_queue.put((args['gpu_id'], metrics['env/score'], metrics['uptime'], metrics['agent_steps']))
```
`metrics` is built from `unroll_nested_dict(logs)` where `logs` comes from
`backend.log()`/`backend.eval_log()`, which for bloodbowl is populated entirely by
`my_log()` in `puffer/bloodbowl/binding.c` (L203–265). That function emits exactly
38 keys (`perf`, `score_diff`, `tds`, `episode_return`, ..., `slot_0_score`,
`slot_1_score`, `draw_rate`) — **there is no `"score"` key**. (Compare: chess and
most Ocean envs DO emit a generic `score`.)

Consequence: if `target_key = f'env/{metric}'` (e.g. `env/perf`, the current
`bloodbowl.ini` L216 default, or `env/tds`) **is present** in `flat_logs` (likely,
since `perf`/`tds` are always logged), execution reaches L389 and
`metrics['env/score']` raises `KeyError` **inside the spawned trial subprocess**
(`pufferl.py` L415, `ctx.Process(target=_train, ...)`). The parent `sweep()` loop is
then blocked forever on `result_queue.get()` (L446) — **a silent deadlock**, not a
clean crash. (If `target_key` is *absent* instead, L314–317 returns `(gpu_id, None,
None, None)` cleanly and the trial is recorded as a failure — that path is fine.)

**This only matters in non-match-mode.** When `match_enemy_model_path` is set,
`match_mode=True` (L210–211) and the L383–387 branch is taken instead — it builds
the result tuple from `match_score` and never touches `metrics['env/score']`. **§2.2
therefore makes match-mode mandatory for any bloodbowl sweep**, which is good news:
it's also the metric we want (see §2.2's justification) and it's exactly the
pattern `config/chess.ini` already proves out (L68–76). (A one-line local patch —
`metrics['env/score']` → `metrics[target_key]` at L389 — would fix the
non-match-mode path too, mirroring this repo's existing `training/*.patch`
convention, but is not required for the recommended plan.)

### 1.7 Default hyperparameter coverage (`config/default.ini` `[sweep.*]`, L111–252)

| Param | Distribution | Range | Notes |
|---|---|---|---|
| `train.total_timesteps` | log_normal, scale=`time` | 3e7 – 1e11 | cost axis |
| `policy.hidden_size` | uniform_pow2 | 32 – 1024 | |
| `policy.num_layers` | uniform | 1 – 8 | |
| `vec.num_buffers` | uniform | 1 – 8 | |
| `train.horizon` | uniform_pow2 | 8 – 1024 | (= bptt horizon) |
| `train.learning_rate` | log_normal, scale=0.5 | 1e-5 – 0.1 | very wide |
| `train.ent_coef` | log_normal | 1e-5 – 0.2 | |
| `train.gamma` | logit_normal | 0.8 – 0.9999 | |
| `train.gae_lambda` | logit_normal | 0.2 – 0.995 | |
| `train.vtrace_rho_clip` | uniform | 0.1 – 5.0 | (torch backend only) |
| `train.vtrace_c_clip` | uniform | ~0.1 – ~5 | (torch backend only) |
| `train.replay_ratio` | uniform | (commented context) | |
| `train.clip_coef` | uniform | 0.01 – 1.0 | |
| `train.vf_clip_coef` | uniform | 0.01 – 5.0 | |
| `train.vf_coef` | uniform | 0.1 – 5.0 | |
| `train.max_grad_norm` | uniform | 0.1 – 5.0 | |
| `train.beta1` | logit_normal | 0.5 – 0.999 | Adam β1 |
| `train.beta2` | logit_normal | 0.9 – 0.99999 | Adam β2 |
| `train.eps` | log_normal | 1e-14 – 1e-4 | Adam ε |
| `train.prio_alpha` | uniform | 0 – 1 | prioritized replay |
| `train.prio_beta0` | uniform | 0 – 1 | prioritized replay |
| `[sweep.policy.hidden_size]`/`num_layers` | — | — | commented `[sweep.vec.total_agents]` and `[sweep.train.minibatch_size]` are present but disabled |

`config/chess.ini` `[sweep]` (L68–98) is the **match-mode + self-play** template:
```ini
[sweep]
match_enemy_model_path = 'resources/chess/10b_weights.bin'
match_num_games = 4096
match_enemy_hidden_size = 512
match_enemy_num_layers = 3

[sweep.train.total_timesteps]   # log_normal, 7e9–15e9, mean=10e9, scale=time
[sweep.selfplay.swap_winrate]   # uniform, 0.55–0.90
[sweep.vec.num_buffers]         # uniform_pow2, 1–8
[sweep.vec.frozen_bank_pct]     # uniform, 0.05–0.5
```
Our own `puffer/config/bloodbowl.ini` `[sweep]` (L215–227) currently has just:
```ini
[sweep]
metric = perf

[sweep.train.gamma]
distribution = uniform
min = 0.995
max = 0.99975
```
— a stub for a previously-discussed discount-horizon sweep (the comment cites the
"~200-decision effective lookahead" rationale), never run. `method`,
`metric_distribution`, `goal`, `max_runs`, etc. all fall back to `default.ini`'s
values (`Protein`, `linear`, `maximize`, `1200`, ...) since `load_config` merges
`default.ini` then the env `.ini` (L633–634).

---

## Part 2 — Proposal for bloodbowl-rl

### 2.1 Current config (`puffer/config/bloodbowl.ini`)

| Knob | Value | Line |
|---|---|---|
| `learning_rate` | 0.0006 | L178 |
| `anneal_lr` / `min_lr_ratio` | 1 / 0.1 | L179–180 |
| `gamma` | 0.995 | L181 |
| `gae_lambda` | 0.85 | L182 |
| `replay_ratio` | 0.25 | L183 |
| `clip_coef` | 0.2 | L184 |
| `vf_coef` | 1.0 | L185 |
| `vf_clip_coef` | 0.5 | L186 |
| `max_grad_norm` | 1.5 | L187 |
| `ent_coef` (+anneal to 10%) | 0.02 | L189–191 |
| `minibatch_size` | 16384 | L192 |
| `horizon` (bptt) | 64 | L193 |
| `update_epochs` | 1 | L194 |
| `total_agents` (≈ num_envs) | 4096 | L25 |
| `num_buffers` / `num_threads` | 2 / 20 | L28–29 |
| `policy.hidden_size` / `num_layers` / `expansion_factor` | 512 / 3 / 1 | L170–172 |
| `total_timesteps` | 2,000,000,000 | L177 |

batch_size = `total_agents * horizon` = 4096 × 64 = **262,144**; minibatch_size
16,384 → **16 minibatches/epoch**, `update_epochs=1` → 1 PPO pass over each rollout.

### 2.2 The hard part: what objective does Protein optimize?

The three candidates from the prompt, evaluated:

1. **Raw SPS** — purely a throughput/infra metric (vec/buffer/thread tuning,
   `docs/sps-optimization-plan.md` territory). It's orthogonal to the *learning*
   hyperparameters (lr, ent_coef, gae_lambda, clip, vf_coef, ...) we actually want
   Protein for — a config that trains badly but fast would "win". **Rejected as the
   primary metric**, though it's a fine secondary readout to sanity-check (no config
   should tank SPS by >2x).

2. **Sample-efficiency to a fixed curriculum `tds`** — `env/tds` is real and always
   logged (binding.c L216), so `metric = tds` is a safe `target_key` (no §1.6
   KeyError on the *gating* path). But raw `tds` is logged from **self-play**
   training by default: the opponent is the evolving snapshot pool
   (`[selfplay]`, `bloodbowl.ini` L8–21), so trial A's `tds` and trial B's `tds` are
   each measured against a *different, drifting* opponent population that itself
   depends on trial A/B's own learning trajectory — exactly the non-stationarity
   the prompt worries about. Two configs could rank differently purely because one
   "got lucky" with an easier opponent pool early on.

3. **Score-at-fixed-wall-clock vs. a FROZEN opponent** — this is what `chess.ini`'s
   `match_enemy_model_path`/`match_num_games` (L72–73) machinery does: train for a
   fixed budget, then run `match()` (a real 2-policy match, using the same
   `slot_0_score`/`slot_1_score`/`draw_rate` fields bloodbowl already emits —
   binding.c L259–261) against a **fixed** checkpoint, and use that win-rate as the
   Protein score.

**Recommendation: a hybrid of (2) and (3), with the opponent frozen on *both* sides
of training.**

- **Train each trial asymmetrically** (`train.frozen_enemy_path` = a fixed anchor
  checkpoint, e.g. `bc_v4.bin` — the existing D43-follow-up asymmetric mode) for a
  **short, fixed** `total_timesteps` (not swept), on a curriculum stage with dense
  scoring (`env.demo_endzone_maxdist = 6`, the first rung of the curriculum ladder)
  so a few hundred million steps produces a non-degenerate `tds`/win signal. Every
  trial warm-starts from the **same** checkpoint (`--load-model-path`) and faces the
  **same** frozen opponent for the **same** number of steps — this removes
  self-play co-evolution as a confound entirely. `metric = tds` serves as the
  `target_key` for early-stop gating (§1.6) — it's measured against a stationary
  opponent now, so it's also a meaningful number on its own.
- **Score each trial by match-mode win-rate vs. a *different* frozen reference**
  (`sweep.match_enemy_model_path` = e.g. a mid-tier league anchor like
  `league6b`'s converted checkpoint, NOT the same file as `frozen_enemy_path`).
  Using a different eval-opponent than the train-opponent guards against a config
  "winning" by specializing against `bc_v4`'s specific weaknesses in just a few
  hundred million steps (a real but second-order risk at this timescale — see §2.6
  risk 3). `match_num_games = 1024` (vs chess's 4096 — our games are cheap and we
  just need a stable win-rate estimate, not a tournament-grade one).
- This is **fully stationary** (both opponents fixed for the whole sweep),
  **cheap** (§2.4), **directly aligned with what we care about** (beats a real
  reference team), and **reuses existing, proven plumbing** (chess.ini's pattern;
  bloodbowl's `eval_log` already emits `slot_0_score`/`slot_1_score`/`draw_rate`).
  It also **sidesteps §1.6's KeyError/deadlock entirely**, since match-mode never
  reaches the `metrics['env/score']` line.

### 2.3 Which hyperparameters to sweep, and ranges

Scope: **PPO optimization hyperparameters only** — not reward-economy knobs (those
go through the existing A/B ladder per the `training-experiments` skill, they're
experiment-design choices, not generic RL hyperparameters) and not policy
architecture (`hidden_size`/`num_layers` — changing these breaks checkpoint
compatibility with every warm-start/convert/tournament script on the fleet; worth a
*separate*, narrowly-scoped sweep later if this one's results justify it).

| Param | Current | Distribution | Range | Why |
|---|---|---|---|---|
| `train.learning_rate` | 0.0006 | log_normal, scale=0.5 | 1e-4 – 3e-3 | `default.ini`'s 1e-5–0.1 is absurdly wide for a 4M-param recurrent net; bracket the current value by ~5x each way |
| `train.ent_coef` | 0.02 | log_normal, scale=auto | 0.005 – 0.08 | masked 454-way factored action space needs real exploration pressure (per `bloodbowl.ini` L188 comment); don't let it collapse toward 0 |
| `train.gae_lambda` | 0.85 | uniform, scale=auto | 0.75 – 0.97 | bias/variance tradeoff for the multi-turn credit horizon |
| `train.gamma` | 0.995 | **keep existing** `[sweep.train.gamma]` (uniform, 0.995–0.99975) | — | already scaffolded in `bloodbowl.ini` L223–227 with a documented rationale (200-decision lookahead); reuse rather than re-litigate |
| `train.clip_coef` | 0.2 | uniform, scale=auto | 0.1 – 0.3 | `default.ini`'s 0.01–1.0 is too wide; bracket current |
| `train.vf_coef` | 1.0 | log_normal, scale=auto | 0.25 – 2.0 | value head shares the trunk with 3 action heads — worth checking if it's under/over-weighted |
| `train.max_grad_norm` | 1.5 | uniform, scale=auto | 0.5 – 3.0 | |
| `train.minibatch_size` | 16384 | uniform_pow2, scale=auto | 8192 – 32768 | must satisfy `validate_config` (`% horizon==0` and `<= horizon*total_agents`; both bounds OK at horizon=64, total_agents=4096 — `Protein` routes violations to `is_failure` via `sweep()` L470–473, not a crash) |
| `train.update_epochs` | 1 | int_uniform, scale=auto | 1 – 3 | currently unswept; with `replay_ratio=0.25` there's headroom to reuse rollouts more |

9 dims total (including the existing `gamma` stub). `Hyperparameters.num = 9` →
Sobol `d=9` for the first 10 suggestions.

**Held fixed**: `horizon=64`, `total_agents=4096`, `num_buffers=2`, `num_threads=20`,
`anneal_lr`/`anneal_ent_coef` schedules, `replay_ratio=0.25`, `bc_coef=0` (no BC
anchor during the short sweep-training phase — keep the signal about PPO dynamics,
not BC interaction; BC-anchor strength is its own sweep if this one's promising),
policy arch (512/3/1).

### 2.4 Exact sweep config

Add to `puffer/config/bloodbowl.ini` (extends the existing `[sweep]`/`[sweep.train.gamma]`
at L215–227 — keep `[sweep.train.gamma]` as-is):

```ini
[sweep]
method = Protein
metric = tds
metric_distribution = linear
goal = maximize
max_runs = 32
gpus = 1
downsample = 5
use_gpu = True
prune_pareto = True
early_stop_quantile = 0.3
# Match-mode scoring (chess.ini pattern): score each trial by win-rate vs a FIXED
# reference checkpoint, deliberately DIFFERENT from train.frozen_enemy_path (see
# docs/pufferlib-sweep-proposal.md S2.2). 0/0 below -> match enemy uses our own
# policy.hidden_size/num_layers (512/3), matching any v4-lineage .bin.
match_enemy_model_path = 'training/league6b_cuda.bin'
match_num_games = 1024
match_enemy_hidden_size = 0
match_enemy_num_layers = 0

[sweep.train.learning_rate]
distribution = log_normal
min = 0.0001
max = 0.003
scale = 0.5

[sweep.train.ent_coef]
distribution = log_normal
min = 0.005
max = 0.08
scale = auto

[sweep.train.gae_lambda]
distribution = uniform
min = 0.75
max = 0.97
scale = auto

[sweep.train.clip_coef]
distribution = uniform
min = 0.1
max = 0.3
scale = auto

[sweep.train.vf_coef]
distribution = log_normal
min = 0.25
max = 2.0
scale = auto

[sweep.train.max_grad_norm]
distribution = uniform
min = 0.5
max = 3.0
scale = auto

[sweep.train.minibatch_size]
distribution = uniform_pow2
min = 8192
max = 32768
scale = auto

[sweep.train.update_epochs]
distribution = int_uniform
min = 1
max = 3
scale = auto

# --- existing, unchanged ---
[sweep.train.gamma]
distribution = uniform
min = 0.995
max = 0.99975
```

**Launch** (on a box, from `/root/bloodbowl-rl`, matching the `run_synthesis_c.sh`
launch-contract conventions — full override of the settled v4 economy, asymmetric
mode for the train-time opponent):

```bash
. tools/cpu_cap.sh   # D59 CPU-cap, mandatory before any puffer invocation

puffer sweep bloodbowl \
  --load-model-path training/<warm_start_anchor>.bin \
  --train.total-timesteps 400_000_000 \
  --train.frozen-enemy-path training/bc_v4.bin \
  --env.demo-endzone-maxdist 6 --env.demo-reset-pct 0.5 \
  --env.reward-ball-gain 0.05 --env.reward-dist-ball 0.05 --env.reward-dist-endzone 0.2 \
  --env.reward-k-kd 0.03 --env.reward-k-value 0.25 --env.reward-k-ball 0.15 --env.reward-k-seq 0.01 \
  --sweep.gpus 1 --sweep.max-runs 32 \
  --tag sweep-ppo-v1 \
  --wandb --wandb-project puffer4 --wandb-group bb-sweep-ppo-v1
```

Notes:
- `--load-model-path` (the local warm-start patch, `pufferl.py` L227–237) makes
  **every** trial start from identical weights — same rationale as the frozen
  opponent: remove init-variance as a confound.
- `--env.reward-*` block is the settled v4 economy from the fleet-ops launch
  contract (`reward_ball_loss`/`reward_possession`/`reward_rush_cost` intentionally
  omitted/0, matching the current live-arm convention — **diff this block against a
  live twin's command line before launch**, per CLAUDE.md footgun #6).
- `[sweep] metric = tds` overrides `bloodbowl.ini`'s current `metric = perf` (L216)
  — only for this sweep's gating; doesn't affect normal `puffer train` runs (the
  `[sweep]` block is inert outside `sweep()`/`paretosweep()`).
- `training/league6b_cuda.bin` and `training/bc_v4.bin` are placeholders for
  whatever frozen anchors are actually staged on the chosen box — **ship/convert
  them there first** (`convert_checkpoint.py --to-cuda ... --obs-size 2782`) and
  update the paths. Pick two *different* checkpoints (§2.2).

### 2.5 Trials, box, wall-clock, cost

- Per trial: 400M steps. At native-CUDA SPS of ~1–2M (D57), training takes **~3.5–7
  min**. Match phase: 1024 games at presumably similar per-step throughput to the
  chess match (4096 games) — expect **~1–2 min**. Call it **~5–8 min/trial**.
- `max_runs = 32` → **~3–4 hours** total, sequential (single GPU, §1.4).
- **Box**: don't contend with the four live flagship arms (japan-native,
  taiwan-anchor, ballhawk, possession — all 24/7 per `CLAUDE.md`). Spin up a **5th,
  short-lived Vast RTX 4090 instance** dedicated to the sweep (or use a quiet window
  on box-1's judge GPU if one exists — verify with `vastai show instances --raw`
  before assuming). RTX 4090 spot pricing on Vast is roughly **$0.30–0.50/hr** —
  check current pricing/balance before launching (`vastai show instances`/
  `vastai search offers`), but a 3–4 hour run should land around **$1–2 total**.
  Cheap enough that the dominant cost is *attention*, not money — see §2.6 on
  babysitting given §1.5's no-resume limitation.
- Checkpoint disk: each trial saves one final `.bin` for the match phase (4M params
  × 4B ≈ 16MB) → 32 trials ≈ **~512MB** under `experiments/bloodbowl/<run_id>/`.
  Clean up after reading results.

### 2.6 Risks, and the recommended *first* (de-risked) sweep

1. **§1.6's `env/score` KeyError/deadlock** — avoided by match-mode (mandatory, not
   optional, for this env).
2. **400M-step ranking may not transfer to 8–30B full runs.** LR schedules
   (`anneal_lr`) and entropy annealing interact with `total_timesteps`; a config
   that "wins" a short race by converging fast could plateau lower over 30B steps.
   **Mitigation**: never adopt the sweep's #1 config directly — take the **top 3**,
   run each at the standard A/B scale (a few B steps) with the existing tournament
   procedure (D45/D50/D56) before any fleet-wide change.
3. **Single fixed train-opponent (`bc_v4`) risks "beat bc_v4 specifically" configs.**
   Mitigated by using a *different* checkpoint for `sweep.match_enemy_model_path`
   (§2.4), but the residual risk remains that both are "old" checkpoints the current
   policy already dominates — pick anchors the *current* flagship still has a
   non-trivial loss-rate against (check recent tournament logs), or the win-rate
   metric saturates near 1.0 for every config and Protein can't discriminate.
4. **`demo_endzone_maxdist=6` is mid-curriculum**; per D50/D56, mid-curriculum
   metrics aren't the graduation criterion. A config tuned here might not be best
   for kickoff-start play. **Mitigation**: same as #2 — the A/B validation pass
   should include a kickoff-start tournament leg.
5. **Thin-data GP** — 32 trials over 9 dims is well below where Protein's GP-guided
   phase is designed to shine (`gp_max_obs=750`, `optimizer_reset_frequency=50`).
   Treat output as a **prior/shortlist**, not a final answer (§1.3).
6. **No resume (§1.5)** — run in `tmux`/`nohup`, budget to finish in one ~4hr
   sitting, and don't rely on resuming a killed sweep. Gate liveness the same way as
   training arms (D65: log-mtime, not log-content).
7. **`/proc/driver/nvidia/gpus` autodetect** (`pufferl.py` L422) — pass
   `--sweep.gpus 1` explicitly; don't rely on the container exposing that path.

**Recommended first sweep (smaller than §2.4, run this before the full 32-trial
version)**: `max_runs = 16`, drop to the **4 highest-leverage** dims
(`learning_rate`, `ent_coef`, `gae_lambda`, `gamma`), `train.total_timesteps =
200_000_000` (~2–4 min/trial + match ≈ **~1–1.5 hours total, <$1**). This validates
the whole pipeline (match-mode scoring works for bloodbowl, `tds` gating fires
correctly, checkpoints convert/match cleanly, wandb grouping looks right) at minimal
cost before committing to the full 9-dim/32-trial/$1-2 run. If the small sweep's
top-3 configs look sane (no `is_loss_nan`, win-rates spread meaningfully rather than
all saturating at 0 or 1 vs the reference), proceed to §2.4's full sweep; otherwise
fix the reference-checkpoint choice or curriculum stage first.

---

## Sources

- `vendor/PufferLib/pufferlib/sweep.py`, `pufferl.py` (pinned commit `9836f0d2e7`,
  `vendor/PINS.md`)
- `vendor/PufferLib/config/default.ini`, `config/chess.ini`
- `puffer/config/bloodbowl.ini`, `puffer/bloodbowl/binding.c`
- [puffer.ai/blog.html](https://puffer.ai/blog.html) — "Stronger Hyperparameters with
  Protein"
- [puffer.ai/docs.html](https://puffer.ai/docs.html) — `puffer sweep` CLI reference
  (minimal; config format not documented there, hence source-grounding above)
- [x.com/jsuarez5341/status/1938287195305005500](https://x.com/jsuarez5341/status/1938287195305005500) — Protein announcement
