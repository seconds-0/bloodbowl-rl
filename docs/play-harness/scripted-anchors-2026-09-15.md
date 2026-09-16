# Scripted bots as tournament anchors, 2026-09-15

**Question.** D399 made the gate two-part: the bot exam, plus a tournament
against a fixed anchor panel. Every current rung trained against the contact
bot as a frozen-pool seat, and none trained against the offense bot, so the
offense bot is the first held-out anchor. Can the play harness seat the engine's
scripted bots as tournament players, and how does a harness bench compare with
the rig exam's cells?

**Answer.**

1. **Yes, the harness seats both bots.** `--bot NAME=contact|offense` makes a
   bot a tournament player. On the bot's turn the shim runs the engine's own
   pick function through `c_step`'s scripted branch. The manifest records the
   bot kind, the sha256 of its source files and the compiled shim, and a resume
   on a different compiled engine is refused.
2. **The offense bot scores fewer touchdowns on the bench than on the rig.**
   Against chain 30 it reads 0.309 TD per game on the bench against 0.342 on
   the rig. The difference is -0.033, interval [-0.056, -0.009], lower on both
   exam seeds (-0.022 and -0.043).
   - The z of -2.73 is somewhat overstated: the rig's two exam seeds share env
     seeds, so their mean is not two independent draws.
   - The gap is not an artifact of the game selection: seed 43 reads 0.297 on
     counted games, 0.300 over all finished games and 0.280 over first games.
   - A CPU-versus-CUDA difference in how the champion defends against this one
     bot is not ruled out.
3. **No champion difference was detected, under the stated variance
   approximation.** Averaged over exam seeds 42 and 43, bench minus exam is:
   - contact AWAY: +0.027, interval [-0.004, +0.057];
   - contact HOME: -0.006, interval [-0.035, +0.022];
   - offense AWAY (the veto cell): -0.001, interval [-0.027, +0.024].
   **This is not an equivalence test.** "No difference detected" only means the
   interval covers 0. The intervals still allow systematic offsets of about
   0.02-0.06 TD per game, as large as the gate's 0.02 champion floor or larger.
   The exam's SE is approximated from the bench (see "Bench"). Per seed, the
   contact AWAY seed 42 champion difference is detected: +0.047, interval
   [+0.003, +0.091].
   Contact-bot conceded cells show no detected difference either (-0.008 and
   -0.004). Conceded cells are not scored by the gate (D268).

## What was built

| piece | file | commit |
|---|---|---|
| `bbp_step_scripted` / `bbp_scripted_bot_index`: the bot decides through c_step's own `scripted_opponent` branch | `play_harness/native/bbplay.c`, `play_harness/engine.py` | d712f2a |
| `--bot NAME=contact\|offense` players, `ScriptedBot` / `BotSeat`, bot identity in the manifest | `play_harness/tournament.py` | 2bc126b |
| sharpness leaves out scripted seats | `play_harness/tournament_stats.py` | fa3e4c4 |
| bot exam bench with the exam's game selection | `play_harness/bot_exam.py` | 6e473b4 |
| warning and test: consecutive exam seeds share env seeds | `play_harness/bot_exam.py` | 39dda5f |
| tests honour `OMP_NUM_THREADS` | `play_harness/tests/conftest.py` | b85f77a |
| resume refuses a different compiled engine, in both runners | `play_harness/tournament.py`, `play_harness/bot_exam.py` | 2139dab |
| bench-versus-exam differences reported as intervals, not as agreement | `play_harness/bot_exam.py` | 80a9c21 |
| websocket review tests run on a synthetic checkpoint catalog | `play_harness/tests/test_review_fixes.py` | 6345c5d, 28aa03f |

Tests: `play_harness/tests/test_scripted_bots.py`.

- **Full suite.** With `BBPLAY_CHECKPOINT` at chain 25 the whole harness suite
  reads 194 passed, 6 skipped, 0 failed. The skips are the server and lobby
  tests that need `.play-artifacts/checkpoints/chain25` inside the checkout, and
  the rig parity fixture.
- **No checkpoint.** With `BBPLAY_CHECKPOINT` unset and no checkpoint catalog,
  `test_review_fixes.py` reads 7 passed, 1 skipped.
  - The stale-game and publication-order websocket tests run on a synthetic
    checkpoint catalog (6345c5d). `new_game` checks the requested checkpoint
    against the server catalog before the injected policy loader runs, and
    these tests need a catalog entry, not weights.
  - Only the joined-view test skips (28aa03f). A random fallback policy produces
    no joined ACTIVATE/DECLARE views, so it fails its floor at 2f99400 too.

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
  `puffer/bloodbowl/offense_bot.h` and `play_harness/native/bbplay.c`, plus
  `bot_library_sha256`, the built shim.
- **Resume identity.** The source hashes do not cover `bloodbowl.h`, the engine
  helpers the bots call, or compiler flags, so the resume check also compares
  `bot_library_sha256`. A resume on a different compiled engine is refused
  before any record is reused or the manifest is rewritten.
  - A checkpoint-only run records `bot_library_sha256: null`.
  - Manifests written before bots existed (the c32 shape, with players and
    pairs, and the older rr6 shape) resume as before.
  - `bot_exam` compares `library_sha256` the same way (`RESUME_KEYS`).
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
that end exactly on epoch boundaries. Bench intervals are 95%, with an
env-clustered (ratio estimator) SE, because one env's games are selected
jointly.

**How the comparison is computed.** `agreement()` gives bench minus exam, an
approximate 95% interval and z. The exam log carries no per-game spread, so the
exam's SE is approximated as the bench SE scaled to the exam's ~2025 games,
ignoring the exam's cross-seed covariance. "Detected" means the interval
excludes 0. It is a difference test, not an equivalence test: "not detected"
does not show the two are close, and the interval gives the offsets still
compatible with the data. A reproduction acceptance criterion would need a
pre-set equivalence tolerance and the exam's own per-game spread, which the
rig's cell logs do not carry.

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

**Chain 30 (sha 41ecd998) against the rig exam.** The bench column holds TDs
per game with the bench's 95% interval. The difference column is bench minus
exam with its approximate 95% interval, z, and whether a difference was
detected. Every bench cell played all 1024 envs with zero integrity counters
and no game cut off at the decision cap. Seed 42 uses episode offset 0 and seed
43 uses 1000.

| cell | seed | bench games | champion TD, bench | rig | difference [95%], z | bot TD, bench | rig | difference [95%], z |
|---|---|---|---|---|---|---|---|---|
| contact AWAY | 42 | 2053 | 0.611 [0.580, 0.642] | 0.564 | +0.047 [+0.003, +0.091], +2.08, **detected** | 0.392 [0.365, 0.420] | 0.398 | -0.006 [-0.045, +0.033], -0.30, not detected |
| contact AWAY | 43 | 2057 | 0.583 [0.554, 0.613] | 0.577 | +0.006 [-0.036, +0.049], +0.30, not detected | 0.370 [0.344, 0.396] | 0.381 | -0.011 [-0.048, +0.026], -0.56, not detected |
| contact HOME | 42 | 2047 | 0.532 [0.503, 0.560] | 0.538 | -0.006 [-0.047, +0.034], -0.32, not detected | 0.402 [0.374, 0.430] | 0.378 | +0.024 [-0.016, +0.064], +1.18, not detected |
| contact HOME | 43 | 2048 | 0.517 [0.489, 0.544] | 0.523 | -0.006 [-0.046, +0.033], -0.32, not detected | 0.357 [0.331, 0.384] | 0.390 | -0.033 [-0.070, +0.005], -1.69, not detected |
| offense AWAY | 42 | 2021 | 0.571 [0.546, 0.597] | 0.581 | -0.010 [-0.046, +0.027], -0.51, not detected | 0.322 [0.298, 0.346] | 0.344 | -0.022 [-0.056, +0.011], -1.30, not detected |
| offense AWAY | 43 | 2028 | 0.598 [0.572, 0.624] | 0.591 | +0.007 [-0.029, +0.043], +0.38, not detected | 0.297 [0.275, 0.320] | 0.340 | -0.043 [-0.075, -0.010], -2.59, **detected** |

Both exam seeds averaged:

| cell | champion TD, bench | rig | difference [95%], z | bot TD, bench | rig | difference [95%], z |
|---|---|---|---|---|---|---|
| contact AWAY | 0.597 [0.576, 0.619] | 0.5705 | +0.027 [-0.004, +0.057], +1.71, not detected | 0.381 [0.362, 0.400] | 0.3895 | -0.008 [-0.035, +0.019], -0.60, not detected |
| contact HOME | 0.524 [0.504, 0.544] | 0.5305 | -0.006 [-0.035, +0.022], -0.45, not detected | 0.380 [0.360, 0.399] | 0.3840 | -0.004 [-0.032, +0.023], -0.30, not detected |
| offense AWAY | 0.585 [0.567, 0.603] | 0.5860 | -0.001 [-0.027, +0.024], -0.09, not detected | 0.309 [0.293, 0.326] | 0.3420 | **-0.033 [-0.056, -0.009], -2.73, detected** |

The one exam score in the brief, offense AWAY seed 42, shows no detected
difference:

- **champion score:** bench 0.625 [0.609, 0.641] against 0.614, difference
  +0.011 [-0.012, +0.033];
- **draw rate:** bench 0.415 [0.393, 0.437] against 0.417, difference -0.002
  [-0.033, +0.029].

Descriptive bench results per cell:

| cell | seed | W / D / L | champion score | draw rate | stop epoch (step) | games played |
|---|---|---|---|---|---|---|
| contact AWAY | 42 | 767 / 880 / 406 | 0.588 | 0.429 | 33 (2112) | 3076 |
| contact AWAY | 43 | 761 / 894 / 402 | 0.587 | 0.435 | 33 (2112) | 3102 |
| contact HOME | 42 | 676 / 935 / 436 | 0.559 | 0.457 | 33 (2112) | 3089 |
| contact HOME | 43 | 688 / 959 / 401 | 0.570 | 0.468 | 33 (2112) | 3094 |
| offense AWAY | 42 | 843 / 839 / 339 | 0.625 | 0.415 | 44 (2816) | 3058 |
| offense AWAY | 43 | 876 / 851 / 301 | 0.642 | 0.420 | 44 (2816) | 3067 |

"Games played" includes games cut off at the stop step. Twelve per-seed tests at
5% should detect about 0.6 differences by chance. Two were detected, which is
not alarming on its own (binomial p about 0.12). The offense bot-TD gap,
however, has the same sign on both seeds.

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
  with curand on the GPU. Only distributions can be compared, not games.
- **eval_episodes.** `rig_exam.sh` lives on the rig and is not in the repo, and
  no local record gives its `EVAL_EPISODES`. The bench uses 2000, inferred from
  the exam's cell sizes (for example 2058 / 2041 / 2027 in D262): every cell is
  above 2000 by less than one epoch's completions (about 60), and 2027 rules
  out 2048. The Puffer default is 10000.
- **Exam spread.** The exam log gives cell means only, so the exam's SE and
  cross-seed covariance are approximated, not measured.
- **Float kernels.** The harness runs the native gate formulas in torch on
  arm64; the exam runs the CUDA kernels. D399's refuters found the formulas and
  observation bytes match, but that does not rule out a behavioural difference
  such as the offense-bot gap.

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
OMP_NUM_THREADS=1 BBPLAY_CHECKPOINT=<chain25 blob> .venv/bin/python -m pytest play_harness/tests
```

Each run writes `manifest.json` (checkpoint sha, bot identity and source
hashes, shim sha, settings, harness head), `games.jsonl` (every game played,
including cut-off games as `in_progress_after`), `selected.jsonl` (start and end
step and counted flag per finished game) and `summary.json`. A rerun resumes
from `games.jsonl`, and refuses a changed setting or a different compiled
engine.
