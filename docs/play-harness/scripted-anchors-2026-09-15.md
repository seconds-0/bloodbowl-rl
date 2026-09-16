# Scripted bots as tournament anchors, 2026-09-15

**Question.** D399 made the gate two-part: the bot exam, plus a tournament
against a fixed anchor panel. Every current rung trained against the contact
bot as a frozen-pool seat, and none trained against the offense bot, so the
offense bot is the first held-out anchor. Can the play harness seat the engine's
scripted bots as tournament players, and does a harness bench reproduce the rig
exam's cells?

**Answer.**

1. **Yes, the harness seats both bots.** `--bot NAME=contact|offense` makes a
   bot a tournament player. On the bot's turn the shim runs the engine's own
   pick function through `c_step`'s scripted branch, and the manifest records
   the bot kind and the sha256 of its source files.
2. **Champion TD per game, which is what the gate scores, matches the rig exam
   in every cell.** Averaged over exam seeds 42 and 43, chain 30's bench reads
   are:
   - contact AWAY: +0.027 against the exam;
   - contact HOME: -0.006;
   - offense AWAY (the veto cell): -0.001.
   Per seed, 5 of 6 champion cells agree within noise. Contact AWAY seed 42 is
   the exception: +0.047, z +2.08.
3. **The offense bot scores fewer touchdowns on the bench than on the rig.**
   Its TDs per game against chain 30 are 0.309 on the bench against 0.342 on the
   rig: lower on both seeds (-0.022 and -0.043), z -2.73 pooled. That z is
   overstated because the rig's two exam seeds share env seeds, so their mean is
   not two independent draws. The gap is not an artifact of the game selection:
   seed 43 reads 0.297 on counted games, 0.300 over all finished games and 0.280
   over first games. Both contact-bot conceded cells agree (-0.008, -0.004).
   A CPU-versus-CUDA difference in how the champion defends against this one bot
   is not ruled out. Conceded cells are not scored by the gate (D268).

## What was built

| piece | file | commit |
|---|---|---|
| `bbp_step_scripted` / `bbp_scripted_bot_index`: the bot decides through c_step's own `scripted_opponent` branch | `play_harness/native/bbplay.c`, `play_harness/engine.py` | d712f2a |
| `--bot NAME=contact\|offense` players, `ScriptedBot` / `BotSeat`, bot identity in the manifest | `play_harness/tournament.py` | 2bc126b |
| sharpness leaves out scripted seats | `play_harness/tournament_stats.py` | fa3e4c4 |
| bot exam bench with the exam's game selection | `play_harness/bot_exam.py` | 6e473b4 |
| warning and test: consecutive exam seeds share env seeds | `play_harness/bot_exam.py` | 39dda5f |
| tests honour `OMP_NUM_THREADS` | `play_harness/tests/conftest.py` | b85f77a |

Tests: `play_harness/tests/test_scripted_bots.py` (43 tests). The whole harness
suite at 4759920 reads 187 passed, 8 skipped, 0 failed. The skips are the
server and lobby tests that need `.play-artifacts/checkpoints/chain25` inside
the checkout, and the rig parity fixture.

Two websocket tests in `test_review_fixes.py` failed in this worktree before any
change here, at 2f99400 too: `new_game` resolves the default checkpoint under
the checkout's own `.play-artifacts`, the server answers `unknown_checkpoint`,
and the tests waited 120 s for a `state` that never came. They now skip without
that checkpoint, as the protocol tests already did (4759920). Run the suite with
`BBPLAY_CHECKPOINT` pointing at chain 25: with the random fallback policy,
`test_joined_views_mark_argmax_only_when_both_decisions_were_argmax` finds too
few joined declarations and fails its `checked > 20` floor.

### The bot is the engine's code

No bot logic lives in Python. On the bot's turn `Engine.step_scripted(type,
team)` sets the env's `scripted_opponent = 1`, `scripted_opponent_type` and
`scripted_opponent_team` for one `c_step`, with both action rows at the NONE
tuple, then restores the `bbp_create` values. `c_step` then calls
`bbe_contact_bot_pick` (type 0) or `bbe_offense_bot_pick` (type 1) on the live
match, the same dispatch the rig exam runs. The shim ABI is now 4.

Tests pin this down:

- Whole bot-vs-bot games through `step_scripted` equal twin sessions that
  submit the picked action's tuple: same digest at every step, same rewards,
  final match bytes, counters and Stalling tallies, for both bots and two seeds.
- After a scripted step the env decodes submitted tuples again (a random coach
  that departs from the bot keeps both sessions identical).
- Wrong type or wrong team is refused with the state untouched.
- The env's own dispatch line in `bloodbowl.h` and the ini's type table are
  asserted verbatim, so a renumbering fails the tests.

### Tournament players

A bot is a player like a checkpoint. It can appear in `--pair`, the round robin
or both legs of a pair:

```bash
OMP_NUM_THREADS=1 .venv/bin/python -m play_harness.tournament \
    --checkpoint chain30=.play-artifacts/checkpoints/chain30/0000002999975936.bin \
    --bot offense=offense --bot contact=contact \
    --pair chain30,offense,400 --pair chain30,contact,400 \
    --workers 4 --out-dir .play-artifacts/tournaments/<stamp>
```

- A bot seat (`BotSeat`) is stepped on every c_step like a policy seat, so the
  one-step-per-seat contract and `check_record` hold unchanged. It holds no
  state, draws no random numbers and never computes an observation.
- `--player-mode` and `--temperature` for a bot are refused, as is a name used
  by both a checkpoint and a bot.
- Game records carry `bots` (per side: `contact`, `offense` or null), with
  `modes` `"scripted"` and temperature null on the bot's side, and
  `logprob_sum` 0 there. `tournament_stats.sharpness` skips scripted seats.
- The manifest gains `bots`: per bot `kind`, `scripted_opponent_type`,
  `pick_function` and `source_sha256` of `puffer/bloodbowl/contact_bot.h`,
  `puffer/bloodbowl/offense_bot.h` and `play_harness/native/bbplay.c`. A resume
  refuses a changed bot or bot source. `bot_library_sha256` records the built
  shim, which also covers the engine helpers the bots call (reachability, block
  EV). Checkpoint-only manifests without `bots` still resume.
- Bot-vs-bot runs need no checkpoint.

## Validation against the rig exam

### How the exam selects games

The exam (`tools/eval_vs_contact_bot.sh`, `NATIVE=1`, 12M steps, cells logged
as `vs scripted bot type=T team=S`) is a frozen native eval: 2048 agent rows =
1024 envs on seeds `SEED + i`, the bot on side `S` of every env, kickoff starts
(`demo_reset_pct 0`), procgen rosters at the ini skill-up settings 4/2/0.0,
`max_decisions` 4096, horizon 64. A cell name is the bot's side: contact AWAY
is the bot AWAY and the champion HOME.

The selection matters as much as the matchup:

- The train phase is 12M // (2048 x 64) = 91 epochs. At the eval boundary
  `set_evaluation_mode` calls `static_vec_reset`, so every env starts a fresh
  game, and recurrent state is zeroed
  (`training/puffer_recurrent_eval_state.patch`).
- `static_vec_eval_log` does not reset the env logs, so `env/n` is cumulative,
  and pufferl reads it after every 64-step epoch and stops at the first epoch
  with `env/n >= eval_episodes` (`training/pufferl_eval_episode_gate.patch`).
- A cell is therefore every game that **finished** by that epoch: a bit over
  two games per env, weighted toward short games. Games still running are never
  counted. A game the env ends at `max_decisions` is counted with its score.
- Champion score is `slot_{champion}_score`, win 1, draw 0.5.

### Bench

`play_harness.bot_exam` plays the same matchup through the harness and applies
that selection exactly. Env `i` plays consecutive games on engine seed
`exam_seed + i`, episodes 0, 1, 2 and so on, so game `k` ends at step
`L_0 + ... + L_k`. The stop step is the first multiple of 64 at which at least
`eval_episodes` games have ended, and the cell is every game ended by then.

The driver plays only what it needs. From the games known so far it computes an
upper bound on the stop step. It extends any env that could still finish a game
by that bound, cutting a game off once it runs past the bound. It repeats until
no env can, at which point the bound is exact. A test checks the selected set
against a brute-force lockstep simulation of the pufferl loop, including games
that end exactly on epoch boundaries. Intervals are 95%, with an env-clustered
(ratio estimator) SE, because one env's games are selected jointly.

"Agree within noise" means |bench - exam| <= 1.96 x SE of the difference. The
exam log carries no per-game spread, so the exam's SE is the bench SE scaled to
the exam's ~2025 games.

**Seed overlap.** Env `i` on exam seed 43 is env `i + 1` on seed 42. On the rig
the training phase shifts each env's episode index and curand stream, so the two
exam seeds are different draws. In the bench nothing does: the first seed 43 run
at `--episode-offset 0` repeated 2095 of seed 42's 2097 finished offense games
exactly, and the same held for the contact cells. Those runs are kept under
`.play-artifacts/bot-exam/chain30-*-s43` as evidence and not reported. The
reported seed 43 cells use `--episode-offset 1000`, which gives different
rosters, dice and sampling seeds (39dda5f pins this with a test).

**Selection effect.** It is real but small for chain 30. In offense AWAY seed
42, counted games average 1153 c_steps against 1169 for first games. Champion
TD per game is 0.571 on the exam selection, 0.572 over all finished games and
0.562 over first games only, all well inside the interval.

**Chain 30 (sha 41ecd998) against the rig exam.** Values are TDs per game with
95% intervals. The diff is bench minus exam, and the verdict is "agree" when
|diff| <= 1.96 SE. Every bench cell played all 1024 envs with zero integrity
counters and no game cut off at the decision cap. Seed 42 uses episode offset
0 and seed 43 uses 1000.

| cell | seed | bench games | champion TD, bench | rig | diff, z, verdict | bot TD, bench | rig | diff, z, verdict |
|---|---|---|---|---|---|---|---|---|
| contact AWAY | 42 | 2053 | 0.611 [0.580, 0.642] | 0.564 | +0.047, +2.08, **disagree** | 0.392 [0.365, 0.420] | 0.398 | -0.006, -0.30, agree |
| contact AWAY | 43 | 2057 | 0.583 [0.554, 0.613] | 0.577 | +0.006, +0.30, agree | 0.370 [0.344, 0.396] | 0.381 | -0.011, -0.56, agree |
| contact HOME | 42 | 2047 | 0.532 [0.503, 0.560] | 0.538 | -0.006, -0.32, agree | 0.402 [0.374, 0.430] | 0.378 | +0.024, +1.18, agree |
| contact HOME | 43 | 2048 | 0.517 [0.489, 0.544] | 0.523 | -0.006, -0.32, agree | 0.357 [0.331, 0.384] | 0.390 | -0.033, -1.69, agree |
| offense AWAY | 42 | 2021 | 0.571 [0.546, 0.597] | 0.581 | -0.010, -0.51, agree | 0.322 [0.298, 0.346] | 0.344 | -0.022, -1.30, agree |
| offense AWAY | 43 | 2028 | 0.598 [0.572, 0.624] | 0.591 | +0.007, +0.38, agree | 0.297 [0.275, 0.320] | 0.340 | -0.043, -2.59, **disagree** |

Both exam seeds averaged:

| cell | champion TD, bench | rig | diff, z, verdict | bot TD, bench | rig | diff, z, verdict |
|---|---|---|---|---|---|---|
| contact AWAY | 0.597 [0.576, 0.619] | 0.5705 | +0.027, +1.71, agree | 0.381 [0.362, 0.400] | 0.3895 | -0.008, -0.60, agree |
| contact HOME | 0.524 [0.504, 0.544] | 0.5305 | -0.006, -0.45, agree | 0.380 [0.360, 0.399] | 0.3840 | -0.004, -0.30, agree |
| offense AWAY | 0.585 [0.567, 0.603] | 0.5860 | -0.001, -0.09, agree | 0.309 [0.293, 0.326] | 0.3420 | -0.033, -2.73, **disagree** |

The one exam score in the brief, offense AWAY seed 42, also agrees:

- **champion score:** bench 0.625 [0.609, 0.641] against 0.614, +0.011, z +0.93;
- **draw rate:** bench 0.415 [0.393, 0.437] against 0.417, -0.002, z -0.12.

Descriptive bench results per cell:

| cell | seed | W / D / L | champion score | draw rate | stop epoch (step) | games played |
|---|---|---|---|---|---|---|
| contact AWAY | 42 | 767 / 880 / 406 | 0.588 | 0.429 | 33 (2112) | 3076 |
| contact AWAY | 43 | 761 / 894 / 402 | 0.587 | 0.435 | 33 (2112) | 3102 |
| contact HOME | 42 | 676 / 935 / 436 | 0.559 | 0.457 | 33 (2112) | 3089 |
| contact HOME | 43 | 688 / 959 / 401 | 0.570 | 0.468 | 33 (2112) | 3094 |
| offense AWAY | 42 | 843 / 839 / 339 | 0.625 | 0.415 | 44 (2816) | 3058 |
| offense AWAY | 43 | 876 / 851 / 301 | 0.642 | 0.420 | 44 (2816) | 3067 |

"Games played" includes games cut off at the stop step. Twelve comparisons at
5% should give about 0.6 disagreements by chance. Two came out, which is not
alarming on its own (binomial p about 0.12). The offense bot-TD gap, however,
has the same sign on both seeds.

Artifacts: `.play-artifacts/bot-exam/chain30-{offense-away,contact-away,contact-home}-s42`
and `...-s43-ep1000`, plus the discarded overlapping runs in `...-s43`. The
manifests record harness heads 6e473b4 (seed 42 cells and offense seed 43) and
4759920 (contact seed 43 cells). The commits between them touch only a
docstring, the CLI help text and tests. The shim library sha (eb17280f) is
identical in every manifest.

### Conditions that could not be matched

- **Roster and dice draws.** The exam's eval games start after the training
  phase, so each env's episode index, and with it the procgen roster and dice
  seed, depends on training-phase game lengths. The bench uses episodes 0, 1, 2,
  ... on the same seeds: the same distribution, different draws.
- **Champion sampling.** The harness samples with torch on CPU; the exam samples
  with curand on the GPU. Only distributions can agree, not games.
- **eval_episodes.** `rig_exam.sh` lives on the rig and is not in the repo, and
  no local record gives its `EVAL_EPISODES`. The bench uses 2000, inferred from
  the exam's cell sizes (for example 2058 / 2041 / 2027 in D262): every cell is
  above 2000 by less than one epoch's completions (about 60), and 2027 rules
  out 2048. The Puffer default is 10000.
- **Float kernels.** The harness runs the native gate formulas in torch on
  arm64; the exam runs the CUDA kernels. D399's refuters found the two agree
  (bias-free layers, kernel formulas matched, observation bytes identical).

## Reproduce

```bash
git worktree add ~/Code/bb-harness-anchors feat/harness-scripted-anchors-20260915
cd ~/Code/bb-harness-anchors
CKPT=.play-artifacts/checkpoints/chain30/0000002999975936.bin
for cell in "offense away 42 0" "contact away 42 0" "contact home 42 0" \
            "offense away 43 1000" "contact away 43 1000" "contact home 43 1000"; do
  set -- $cell
  OMP_NUM_THREADS=1 .venv/bin/python -m play_harness.bot_exam --checkpoint "$CKPT" \
      --bot $1 --bot-side $2 --exam-seed $3 --episode-offset $4 --workers 4 \
      --out-dir .play-artifacts/bot-exam/chain30-$1-$2-s$3-ep$4
done
OMP_NUM_THREADS=1 .venv/bin/python -m pytest play_harness/tests
```

Each run writes `manifest.json` (checkpoint sha, bot identity and source
hashes, shim sha, settings, harness head), `games.jsonl` (every game played,
including cut-off games as `in_progress_after`), `selected.jsonl` (start and end
step and counted flag per finished game) and `summary.json`. A rerun resumes
from `games.jsonl` and refuses a changed setting.
