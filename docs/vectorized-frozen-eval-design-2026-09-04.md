# Vectorized frozen-policy evaluation design — 2026-09-04

Status: read-only design audit. No implementation or GPU measurement is part
of this note.

## Finding

The current one-environment evaluator is lossless but cannot scale to final
gates. The measured baseline is approximately 2 seconds per completed game.
For four policies and eight fixed cells, serial cost is:

| Games per policy/cell | Total games | Serial time at 2 s/game |
|---:|---:|---:|
| 32 | 1,024 | 2,048 s = 34.1 min |
| 128 | 4,096 | 8,192 s = 136.5 min = 2.28 h |
| 1,000 | 32,000 | 64,000 s = 17.78 h |

The native terminal tensor already identifies rows that ended during a
horizon-one rollout. It cannot identify the completed game's final score or
integrity record. `bbe_finish_episode` folds those values into the individual
environment's cumulative `Log`, sets both terminal rows, and immediately calls
`bbe_reset_match`. `static_vec_eval_log` then aggregates every environment and
exposes only population means. Per-game attribution cannot be reconstructed
from this aggregate when multiple environments finish in one rollout.

`boundary_reached` is also insufficient. It is a one-bit self-play bank-swap
signal, contains no score or seed, and can be cleared by the existing boundary
consumer. The public terminal pointers have the same attribution limitation.

## Smallest lossless extension

Keep the existing evaluation-only Python control path, horizon `1`, terminal
recurrent-state reset, and scripted-opponent mechanism. Add one fixed-size
Blood Bowl completion snapshot to each `Env`, filled inside
`bbe_finish_episode` before `bbe_reset_match` clears episode state:

```c
typedef struct {
    uint64_t sequence;
    uint64_t base_seed;
    uint64_t episode;
    uint64_t game_rng_seed;
    uint64_t procgen_rng_seed;
    uint32_t env_index;
    int32_t home_tds;
    int32_t away_tds;
    int32_t decisions;
    float perf;
    float score_diff;
    float illegal_frac;
    float reward_clip_terminal_samples;
    float reward_clip_nonterminal_samples;
    float reward_clipped_samples;
    float reward_clip_excess;
    float reward_nonfinite_samples;
    float reward_component_nonfinite_samples;
    float error_episodes;
    float demo_episodes;
    float demo_fallbacks;
} BBEvalCompletion;
```

The exact field names may follow existing structs, but each value must come
from the just-finished episode, not by subtracting large cumulative floats.
This matters for the exact-zero contract: a `1e-7` clip excess must remain
observable after a long run. Increment `sequence` once after the snapshot is
fully populated.

Most integrity values already exist as `ep_*` fields at finish time. Derive
`error_episodes` directly from the error/no-legal terminal reason and
`illegal_frac` from the episode's `illegal` and `decisions`. `demo_started` is
already per episode. `demo_fallbacks` is currently incremented during reset in
the cumulative log, so add or latch a per-episode fallback bit; do not copy its
cumulative total into every completion. The drain loop already knows the
environment array index and can attach it without storing another copy in the
environment.

Expose one native method:

```python
records = backend.drain_eval_completions(pufferl)
```

It scans the host `Env[]`, returns every snapshot whose sequence differs from
that environment's consumed sequence, then advances the consumed sequence.
The consumed sequence belongs to the Puffer instance or the environment and
is reset when that instance is created. The method must reject:

- calls outside evaluation mode;
- horizons other than one, because one environment could otherwise complete
  and overwrite more than one game before the drain;
- a sequence jump greater than one, which proves an overwritten completion;
- duplicate `(env_index, sequence)` records;
- unsupported environments at compile time rather than returning partial
  generic records.

The Python runner drains after every `backend.rollouts` call, validates every
record before writing it, normalizes W/D/L from the learner's declared side,
and immediately fsyncs the JSONL and progress marker. It must continue to avoid
`backend.train`, optimizer construction, and the training entrypoint.

## Exact finite seed plan

For a cell requesting `N` games, create exactly `N` environments (`2N` agent
rows) with base environment seeds `cell_seed + env_index`. Accept only episode
1 from each environment and stop after all `N` environment indices have
produced it. Later episodes may run while the slowest first game finishes, but
they are drained and explicitly classified as ignored overshoot; they never
replace or count toward the plan. This gives every policy the same finite list
of common game seeds and avoids a policy-dependent stopping sample.

If `N` exceeds the safe row capacity, split the prospectively frozen seed list
into fixed batches. Each batch manifest records its exact seed interval and is
complete only when every expected `env_index` has one accepted episode-1
record. Do not stop at the first aggregate `N` completions: faster policies or
shorter games would then choose which seeds enter the sample.

The completion record supplies engine seed identity. The manifest supplies
checkpoint, compiled module, config tree, scripted style, scripted team,
learner side, roster constraints, and policy sampling seed. The final trace ID
hashes both sets.

## Required regressions

1. Run at least eight environments with deliberately interleaved game lengths;
   drain after every horizon-one rollout and prove every episode-1 environment
   appears exactly once.
2. Drain twice without another rollout and require an empty second result.
3. Force a completion on consecutive rollouts for one environment and prove
   sequences 1 and 2 are distinct and neither is overwritten.
4. Set every integrity field independently, including clip excess `1e-7`, and
   prove the exact value reaches Python and rejects the run.
5. Prove final HOME/AWAY touchdowns, `perf`, and `score_diff` agree for wins,
   draws, and losses; repeat learner normalization with the bot on both sides.
6. Prove `base_seed`, episode-1 RNG seeds, and environment index match the
   native reset formulas with uint64 wrapping.
7. Reject horizon greater than one and a synthetic sequence jump.
8. Repeat the same checkpoint/cell/common-seed batch twice and require identical
   per-game trace identities and results.
9. Retain the existing recurrent evaluation test: state persists inside a game
   and resets only on the completed environment's terminal rows.
10. Kill the process after several drains and prove JSONL/progress recovery
    contains every acknowledged game and no partial record.

## Evaluation ladder

Use 32 common games per policy/cell for the first exploratory exam. Across
eight cells this is 256 games per policy; it can detect large failures and
side/style asymmetry cheaply, but a 32-game cell has worst-case binomial
standard error about 0.088 and cannot support a narrow promotion margin.

Use 128 games per policy/cell only for survivors or when the 32-game result is
decision-relevant but uncertain. This remains a development screen, with
common-seed paired differences reported per cell.

Reserve approximately 1,000 games per policy/cell for a final scripted stratum
after vectorized throughput is measured. Learned-opponent and roster-grid
transfer are separate final gates: freeze their checkpoints, roster pairs,
sides, and common seeds prospectively, and do not substitute a large scripted
sample for them. Cluster conclusions by training run and seed; game count does
not turn two trained policies into independent training replications.

Before adopting any budget, measure games/second and tail completion time on
the integrated RTX 2070 build at 32, 128, 512, and 1,000 environments. The
design predicts parallelism but makes no unmeasured throughput claim.
