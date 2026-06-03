# bloodbowl-rl

Training harness for a non-LLM RL agent that plays **Blood Bowl — Third Season Edition (BB2025)**.

Deterministic C11 rules engine (no graphics in the hot loop) bound to [PufferLib](https://github.com/PufferAI/PufferLib) as a native vectorized environment; PPO + hard action masking + autoregressive action heads + self-play league; behavioral-cloning warm-start from curated FUMBBL human replays. Replays render after the fact via a raylib viewer.

## Principles

1. **Full ruleset before training** — every skill, table, and procedure implemented and validated before a single RL step.
2. **Determinism + injectable dice** — every roll goes through `bb_rng`: seeded PCG-64 *or* a recorded dice script. This is what makes replay-differential testing, golden traces, and exact reproduction possible.
3. **Validation is the product** of the engine phase: 7 automated layers (rulebook unit tests, statistical dice conformance, property invariants, fuzzing+sanitizers, golden traces, rule-coverage gate, FUMBBL/FFB replay differential).
4. **Generalization over memorization** — procedural roster/skill/injury randomization at reset; learned skill embeddings; the agent must read the team, not memorize it.

## Layout

```
engine/       Pure C11 rules engine (zero Python deps) + tests
validation/   Oracle harnesses: FUMBBL replay differential, FFB headless, calculator conformance
puffer/       PufferLib binding (ocean/bloodbowl pattern)
training/     BC pipeline, PPO configs, self-play league, eval
render/       raylib replay viewer
tools/        Roster codegen (YAML → C tables), replay fetcher, coverage reports
docs/vendor/  Cached external docs/specs/papers (gitignored)
vendor/       Pinned reference clones (gitignored; see vendor/PINS.md)
```

## Status

Phase 0 — scaffolding, doc cache, project skills. See `~/.claude/plans/i-need-you-to-merry-naur.md` for the full plan.

## Note on IP

Blood Bowl is a Games Workshop game. This repo contains no rulebook text, GW artwork, or other GW assets — engine code and data tables are original work. Private research project.
