# R0 long-horizon milestone evaluation

Status: predeclared post-run research protocol. This document does not alter
the active vacation queues, choose a checkpoint from live metrics, or authorize
a reward/default promotion.

## Question

The vacation queues train unchanged R0 for 12B steps at seeds 42, 43, and 44
from the turnover3, league9, and (conditionally) netblock ancestries. Their
purpose is long-horizon seed/ancestry characterization after the `neither`
simplification failed its frozen confirmation gate. They are not a reward A/B.

The first main-arm trajectory improved against all four static training banks
through 6B, but touchdowns and ball progress were non-monotonic. The post-run
question is therefore:

> Does R0's strength against fixed opponents continue improving from 0--12B,
> plateau, or regress, and is the trajectory consistent across seeds and
> ancestries?

Training dashboards, BBTV games, human-stat proximity, and a single newest
checkpoint cannot answer this question.

## Evidence partitions

Keep the following names exact in every artifact and report.

1. **Training-pool evidence.** The learner was trained with the static
   `league9`, `violence`, `netblock`, and `turnover3` banks. Dashboard
   `historical_winrate` and any new matches against these four checkpoints are
   in-pool measurements. They diagnose optimization but are not transfer.
2. **Unseen-exact-checkpoint transfer.** Historical checkpoints such as
   `statmatch1`, `league7b`, `exploiter1`, and `gen1` were not exact members of
   the vacation static pool. They provide a fixed strength/style spread, but
   the population is lineage-connected: several are ancestors of, or prior
   opponents used to produce, later policies. Call them unseen exact
   checkpoints, not independent held-out lineages.
3. **Scripted transfer.** The contact and cage-advance bots are distinct fixed
   policies and must be evaluated with both bot sides. Their deterministic
   weaknesses make them functional probes, not a complete external standard.
4. **Roster stratification.** Training procgen sampled all BB2025 roster IDs.
   The forced matchup grid is an equal-weight stratified test of archetype and
   matchup robustness, not unseen-roster generalization.

In-sample, unseen-checkpoint, scripted, and roster-stratified results must be
reported separately. No pooled headline may erase these partitions.

## Frozen checkpoints

For every accepted seed run, preserve the exact native checkpoint at or
immediately before each target:

```text
0B warm, 1B, 2B, 4B, 6B, 8B, 10B, exact final 12B
```

For non-final targets, choose the greatest embedded checkpoint step not above
the target. Require the gap to be no larger than one frozen checkpoint
interval. The 12B point is the exact final checkpoint named by the accepted
arm result. Record target step, embedded step, byte size, SHA-256, source run
manifest, source result, screen completion, lineage, and training seed. Never
select by modification time.

The warm checkpoint is one shared baseline per ancestry, not three independent
seed observations. Do not triple-count it in uncertainty estimates.

## Stage A: fixed trajectory matrix

Use the four unseen-exact-checkpoint anchors below after verifying their current
native files, architecture, provenance, and SHA-256 on the evaluation host:

| Anchor | Current RTX SHA-256 | Role |
|---|---|---|
| `statmatch1` | `85315d26a40f26a387ef28742b7f3306583ca73b488aae01e06c72566f5ab435` | historically strongest, distinct reward/style probe |
| `league7b` | `2bf0815f506ac98e4972744903164673d40bee27b0b0c9197268b4c094fcdec1` | strong hard-pool policy and league-family reference |
| `exploiter1` | `6373cfa349bab8eee133933d42b353e796d2693e4e85b5a285c999647b11771a` | deliberately non-transitive attack style |
| `gen1` | `62f6fcbc111e3b319ac0158358f0211e8aaf460c88f49eee86ff4639a148945a` | stable non-degenerate floor |

All four files were 16,066,560 bytes on the RTX host on 2026-07-14. The
evaluator must re-hash them at freeze and before every cell; this table is
provenance, not permission to ignore later drift.

For every lineage, seed, and frozen milestone:

- play 2,048 complete kickoff games per anchor and backend role;
- load the focal checkpoint once as policy A and once as policy B;
- use identical match seeds for all milestones within a
  `(seed, anchor, backend role)` stratum;
- keep `demo_reset_pct=0`, macro moves off, scripted opponent off, and procgen
  roster settings unchanged;
- require the native BB2025 GPU-fp32 module, observation size 2782, exact
  implementation/config hashes, and zero clip, non-finite, error, demo, and
  fallback counters;
- store W/D/L-equivalent match score, draw rate, TD for/against, games, all
  integrity fields, raw environment metrics, and immutable cell hashes;
- reject a cell that omits or contains invalid values for the fixed behavior
  panel: illegal repairs, block volume and dice tiers, carrier targeting,
  possession, ball movement, dodge/Rush/pickup/pass/handoff attempts, and
  knockdown outcomes; and
- report focal and opponent block volume from the existing per-team counters.
  The other behavior metrics are currently match-level aggregates over both
  policies. Keep them labelled `joint_behavior`: they diagnose trajectory drift
  under fixed opponents but cannot be attributed to the focal policy alone.

At eight checkpoints, three seeds, four anchors, two backend roles, and 2,048
games, Stage A is 393,216 games per ancestry. This is descriptive trajectory
evidence. One 2,048-game cell is not decision-grade inside a narrow Elo band.

### Fixed summaries

For each milestone report:

- equal-anchor/equal-role macro mean and per-seed values;
- per-anchor and per-backend-role means;
- score, TD-for, and TD-against change from the ancestry warm checkpoint;
- change from the preceding frozen milestone;
- validated joint-behavior means and warm deltas, plus focal/opponent block
  volume; and
- in-pool dashboard trajectory beside, never merged with, transfer results.

Treat seeds, anchors, roles, and checkpoints as repeated strata rather than
independent games. Report the raw paired strata and a seed-clustered bootstrap;
do not use a naive per-game binomial interval as the only uncertainty estimate.

## Fixed plateau rule

Stage A may nominate exactly two policies per seed/ancestry for Stage B:

1. the exact 12B terminal checkpoint; and
2. the earliest nonterminal milestone whose equal-anchor macro score is within
   0.01 of the maximum Stage-A milestone and for which two later milestones
   exist and neither is more than 0.02 better.

If no milestone satisfies the second rule, use the highest-scoring nonterminal
milestone and label the choice exploratory. This keeps the Stage-B comparator
distinct from the terminal instead of allowing a vacuous terminal-vs-terminal
comparison. If the nominated point differs across seeds, preserve each seed's
own nomination; never swap seed identities or choose one seed's visually best
checkpoint for all seeds. This rule is a compression rule for additional
evaluation, not a production-selection gate.

## Stage B: transfer confirmation

Evaluate the terminal and fixed-rule plateau nominees without changing them.

### Scripted bots

For both contact and cage-advance bots and both bot sides, run 4,096 full
kickoff games per nominated checkpoint. Apply native-to-Torch conversion
symmetrically where the scripted evaluator requires Torch, record input/output
hashes, and remember that conversion zero-fills native biases. Use common eval
seeds for terminal/plateau pairs.

### Forced roster grid

Use the audit's six fixed pairs in both home/away orders:

| Pair | Team IDs |
|---|---:|
| Orc / Dwarf | 22 / 7 |
| Orc / Wood Elf | 22 / 29 |
| Skaven / Dark Elf | 24 / 6 |
| Human / Necromantic Horror | 13 / 17 |
| Goblin / Orc | 10 / 22 |
| Tomb Kings / Wood Elf | 26 / 29 |

Run each focal checkpoint against at least two fixed unseen-checkpoint anchors,
in both backend roles, for 512 complete games per ordered matchup. Macro-average
all ordered roster cells equally; do not allow common or high-throughput
rosters to dominate. Report every critical cell, especially stunty/strength and
slow/fast extremes.

### Stage-B interpretation

A terminal checkpoint is a long-horizon keeper only if its paired macro score
is non-inferior to the plateau nominee, no critical roster cell has a material
drop, and TD-against does not show a compensating defensive regression. A
plateau nomination that wins Stage B can support an early-stopping hypothesis
for a future matched run; it does not retroactively make the completed 12B
training invalid and does not promote R0.

## Immutable runner contract

The milestone evaluator must be a separate post-run tool and artifact tree. It
must not modify or become an input to the active primary or overflow queues.
The four learned anchors are ordered exactly as declared in the protocol; that
order is part of the common-match-seed assignment and may not be permuted.

The runner must:

1. require an accepted `control-final` `SCREEN_COMPLETE.json` and re-run the
   existing analyzer/validator before discovering checkpoint directories;
2. require a complete, absolute-path spec whose bytes are hashed before any
   cell starts;
3. resolve target steps once, hash every selected checkpoint, then freeze a
   manifest that cannot be overwritten with different inputs;
4. freeze the imported module, complete config tree, Puffer sources, runner,
   analyzer, warm/result/run-manifest/screen-completion files, anchors,
   checkpoint sizes/hashes, seeds, targets, match seeds, roster settings,
   games, and integrity requirements;
5. use one restart-validating atomic result per cell and reject an existing
   cell whose identity, implementation, checkpoint, game count, or integrity
   fields differ;
6. hold the shared reward/evaluation GPU lock, bound each cell runtime, publish
   atomic progress, and require an exclusive evaluation GPU gate. The BBTV
   follower must be explicitly quiesced first so it cannot start a new match
   after an idle-PID check. If a training queue, other compute process, or BBTV
   follower remains active, stay pending and do not stop it implicitly;
7. write an analysis plus completion proof chaining the manifest and every
   cell SHA-256;
8. make no automatic reward, checkpoint, production, or queue change.

The primary and optional overflow training queues remain the only unattended
GPU work during the vacation. The evaluator may be merged and tested while
training runs, but it should not be deployed into the pinned audit snapshot or
started until the relevant source screen has completed and the GPU is idle.

The per-lineage spec has this exact shape; replace only the output/source paths,
completion hash, and matrix ID after the accepted screen exists:

```json
{
  "schema_version": 1,
  "matrix_id": "vacation-r0-main-milestones-v1",
  "root": "/home/rache/bloodbowl-rl-audit",
  "out_dir": "/home/rache/bloodbowl-rl-audit/runs/vacation-r0-main-milestones-v1",
  "screen_complete": "/absolute/path/to/SCREEN_COMPLETE.json",
  "screen_complete_sha256": "<lowercase SHA-256>",
  "target_steps": [0, 1000000000, 2000000000, 4000000000, 6000000000, 8000000000, 10000000000, 12000000000],
  "max_target_gap_steps": 50000000,
  "games_per_cell": 2048,
  "anchors": [
    {"name": "statmatch1", "path": "/home/rache/bloodbowl-rl-audit/training/statmatch1_cap.bin", "bytes": 16066560, "sha256": "85315d26a40f26a387ef28742b7f3306583ca73b488aae01e06c72566f5ab435"},
    {"name": "league7b", "path": "/home/rache/bloodbowl-rl-audit/training/league7b_cap.bin", "bytes": 16066560, "sha256": "2bf0815f506ac98e4972744903164673d40bee27b0b0c9197268b4c094fcdec1"},
    {"name": "exploiter1", "path": "/home/rache/bloodbowl-rl-audit/training/v4_exploiter1_cap.bin", "bytes": 16066560, "sha256": "6373cfa349bab8eee133933d42b353e796d2693e4e85b5a285c999647b11771a"},
    {"name": "gen1", "path": "/home/rache/bloodbowl-rl-audit/training/v4_contested_cap.bin", "bytes": 16066560, "sha256": "62f6fcbc111e3b319ac0158358f0211e8aaf460c88f49eee86ff4639a148945a"}
  ],
  "orientations": [0, 1]
}
```

After review and an exclusive-GPU gate, first freeze without running cells:

```bash
python tools/run_checkpoint_milestone_eval.py --spec /absolute/spec.json --plan-only
```

The same command without `--plan-only` runs or restart-validates the matrix.
Validation later uses `--validate-complete` plus the recorded completion SHA.

## Promotion boundary

This protocol characterizes R0 optimization length and ancestry sensitivity.
It cannot settle the reward because every vacation arm uses the same reward.
Any next reward change remains a matched causal experiment and must satisfy the
July audit's learned-opponent, scripted, roster-grid, seed, ancestry, integrity,
and production-review gates. BBTV remains qualitative throughout.
