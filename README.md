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

Active reward/replay research. The repaired reward 2×2 and R0/R2 scripted
transfer are complete; R0 remains an experimental baseline and no production
reward has been promoted. See `STATUS.md`, D177–D180 in `DECISIONS.md`, and
`docs/reward-and-replay-audit-2026-07-09.md` for the current verdict and next
experiment. Agent workflows start at `AGENTS.md`.

## Play against a trained policy

The play harness runs a local web game where you coach one team and a trained
checkpoint coaches the other. It binds 127.0.0.1 only.

```bash
play_harness/run.sh            # builds the engine shim when needed, then serves
# open http://127.0.0.1:8790/
```

In the lobby, pick the checkpoint (chain 25 is the default), how rosters are
chosen, your side, sampling or argmax, the bot's move delay, the turn clock and
the seed. The seed is shown so you can replay a game. Checkpoints are listed
from `.play-artifacts/checkpoints/` when they carry a `.lineage.json` sidecar;
add another directory with `--checkpoint-dir DIR`, or change the port with
`--port`.

Game records, flagged bot moves and survey answers land in
`.play-artifacts/games/<stamp>-<teams>-<seed>/game.json` (gitignored).
Design and interaction spec: `docs/play-harness/design-2026-09-13.md`.
Backend tests: `.venv/bin/python -m pytest play_harness/tests`. Browser suite:
`play_harness/web/e2e` (Playwright; run it on a throwaway box, not the Mac).

## Note on IP

Blood Bowl is a Games Workshop game. This repo contains no rulebook text, GW artwork, or other GW assets — engine code and data tables are original work. Private research project.
