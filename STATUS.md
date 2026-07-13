# Status — 2026-07-13

## Current verdict

The BB2025 rules/reward/replay audit is complete in the working tree. No reward
configuration has been promoted to production and no production default was
changed.

The repaired paired R0–R3 reward screen completed all eight arms at exact
`249,954,304` native steps with two seeds, at least 10,001 final-policy eval
games per arm, frozen provenance, and zero clip/non-finite/error/demo/fallback
telemetry. Distance shaping supplied nearly all present scoring learnability
(`+0.76365 TD/game`, `+0.11130` match score), but also increased block volume
and 2D-red rate. Raw distance delta is a temporary scaffold, not exact PBRS at
`gamma=0.995`.

The R0-versus-R2 held-out scripted transfer completed 16 cells and 16,076 full
games. Removing possession+gain (R2) made match score worse in all eight paired
seed/style/side cells and increased losses plus opponent TDs in all eight. R0
therefore survives as the next experimental baseline, not a production recipe.

The first 500M possession/gain decomposition arm completed cleanly at runtime
but was rejected before acceptance because a partially deployed per-arm
launcher hashed an older five-patch Puffer bundle while the frozen screen
required seven patches. D181 records the failure. No metric from that arm is a
reward verdict. The launcher now enforces the frozen bundle before training;
the screen will restart under a fresh immutable identity after deployment.

## Next experiment

With distance fixed on, decompose the bundled family:

1. possession annuity + ball gain;
2. possession annuity only;
3. ball gain only;
4. neither.

Run `500M × 2 seeds` under the immutable screen contract. Then compare R0 with
the simplest transfer-noninferior survivor using learned opponents, both sides,
roster-grid macro evaluation, longer training, and a second ancestry. Only that
confirmation path can authorize a default change.

## Replay and BC state

- Raw manifest: 15,347 replays = 11,580 BB2025 + 3,767 BB2020 by embedded
  `rulesVersion`.
- Strict non-empty BB2025 allowlist: 9,118 replays / 1,622,231 joined records.
- The corpus is severely opening-censored and almost lacks rare action targets;
  it cannot be the sole source for second halves, late drives, stalling, or
  comeback policy.
- `training/bc_pretrain.py` now uses exact allowlists, replay-disjoint splits,
  bounded memory-mapped streaming, owning minibatches, and batchwise eval.
- Replay-first is the current default. Next sampling work must stratify
  roster/matchup, turn/drive depth, and action family while capping setup mass.

## Canonical evidence

- Full report: `docs/reward-and-replay-audit-2026-07-09.md`
- Screen proof: `runs/reward-screens/reward-screen-20260709-v1/SCREEN_COMPLETE.json`
- Transfer analysis: `runs/reward-transfer-20260713-v1/ANALYSIS.json`
- Replay audit and strict allowlist: `runs/replay-audit-20260713/`
- Durable decisions: D177–D180 in `DECISIONS.md`

## Verification and deployment state

The corrected engine passed 419 normal tests and the same 419 under
sanitizers. This ship cycle also passed 56 tool/analyzer tests, 24
replay/streaming/league tests, 6 BC-context tests, 4 checkpoint-conversion
tests, and the BC regression harness. Core reward/BBTV corrections are merged;
BBTV is deployed and streams the newest complete manifested checkpoint against
its hash-pinned warm baseline. No production reward was promoted. Training
continues only from the isolated RTX 2070 audit checkout; the production viewer
checkout and isolated float viewer build remain separate.
