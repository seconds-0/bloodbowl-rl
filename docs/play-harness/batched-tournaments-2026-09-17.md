# Batched tournaments, 2026-09-17

**Question.** Can a tournament worker play several games at once and share one
policy forward between them, and what does that do to speed and to the games?

**Answer.** Yes. `python -m play_harness.tournament --games-per-worker N` is on the
branch `feat/harness-batched-forward-20260917`. The default is 1, which is the old
code path with the old results.

1. **One 8 vCPU droplet plays 5.0 times as fast at N = 32** on checkpoint pairs
   (1.54 to 7.74 games/s) and 4.7 times as fast on a bot pair (1.83 to 8.68).
   Throughput flattens after that: N = 64 adds 12 to 15%, N = 128 another 6%.
2. **The games barely change.** Against N = 1 on the same droplet, with the same
   seeds, 1,200 of 1,200 bot-pair games took identical actions at every N from 2
   to 64. On the checkpoint pairs 1,200 of 1,200 matched at N = 2, 4 and 8, and
   1,199 of 1,200 at N = 16, 32, 64 and 128. W/D/L, TD means and every score were
   identical in every run. Every integrity counter was zero in every run.
3. **The one game that differs is the same game every time**: engine seed
   20600020, chain34 v chain30, leg `A_home`. It is also the single game that
   differed between the Mac and a droplet in the cross-machine check. One of its
   sampling draws lands inside a probability gap of 5 in a million, so any change
   in float rounding flips it. It was traced; see "The game that flips".
4. **A 22,400 game gate would take about 48 minutes on one droplet (about
   $0.13)** at N = 32, against 4.4 hours and $0.73 unbatched, or
   about 17 minutes on four droplets (about $0.17).
5. **Registered gates stay at N = 1.** Nothing in any gate procedure changed.
   Adopting N > 1 for gates is a separate decision for the project journal.

## Design

At N = 1 a worker plays one game at a time. Every engine step runs a batch-1
forward for each seat, about 840 forwards per game. Each forward reads all 16 MB
of weights, and a game alternates two checkpoints, so on a cloud vCPU the forward
is limited by memory bandwidth, not arithmetic.

With `--games-per-worker N` a worker holds N games (`BatchedGames` in
`play_harness/tournament.py`). One step of the worker:

1. Every game in flight reports its deciding team and both seats' observation and
   exact joint support.
2. The policy seats are grouped by policy object. Each group gets ONE forward
   (`policy.batched_forward`): observations stacked to `[B, 2782]`, recurrent states
   concatenated to `[3, B, 512]`. A pair of two checkpoints costs two forwards per
   step however many games are in flight. A bot seat costs none. One checkpoint
   on both seats is one group.
3. Every seat selects from its own logits row with `PolicySeat.decide`, which is
   the second half of the old `PolicySeat.step`: the same `select_joint`
   (exact-joint-v1: type, then arg given type, then square given both), the
   seat's own `torch.Generator`, its own mode and temperature.
4. Every game applies its action through `Match.apply`, the same checks
   `play_match` uses: one forward per seat per engine step, the waiting seat
   emits NONE, the tuple is inside the exact support, the engine accepts it.

A finished game leaves its slot, its record is returned, and the worker takes the
next task from the queue before the next step. There is no batch-shaped state
buffer. A seat owns its `(3, 1, 512)` state and its generator, the `Match` owns
its seats, and a new game builds a new `Match`. So "reset the rows of a finished
game" holds by construction: nothing of the old game is left to reset.

Worker processes (`_batched_worker`) read a task queue and write a result queue.
The parent hands out tasks in a window of twice what the workers hold in flight
and tops it up as results return. It aborts the run, as before, on the first
contract violation, and also when a worker dies without a report, when a game is
reported twice, or when the workers finish with games unplayed.

`play_match` was refactored onto the same `Match` object so both paths share one
copy of the contract checks and the record. Its behavior is unchanged: the
refactored N = 1 path reproduces records of the chain 34 reference run (played
2026-09-16, before this work) field for field, and a standing test checks that on
the Mac.

## Determinism contract

- A game's engine seed is `seed0 + index`. Its sampling seeds are functions of
  (engine seed, side, episode). Both are unchanged, and both are recorded per game.
- A seat's generator is consumed exactly as at N = 1: three `multinomial` calls per
  sampled decision, none on a waiting step, none in argmax mode. The number of
  draws does not depend on the logits.
- No value flows between rows of a batch. Every operation in `forward_eval` is
  row-wise, and the state each seat gets back is a copy of its own row.
- So a game depends on its batch in one way only: **a batched matrix product may
  round differently from a batch-1 product**, by about 1 part in a million of the
  logits. A sampled action changes only when a draw falls inside the sliver of
  probability that the rounding moved.
- Therefore N = 1 and N > 1 agree in distribution and in nearly every game, but
  not by guarantee in every game. This is the same kind of difference as running
  on another machine, and about the same size (1 game in 2,400 there).
- The manifest records `games_per_worker`. A resume refuses a run whose value
  differs, the same way it refuses a changed compiled library, because the two
  settings are slightly different samplers. A manifest without the key was played
  unbatched and counts as 1. `droplet_tournament.py merge` refuses shards that
  differ, and `run` checks the manifest value against the request.
- Worker count and batch composition are not recorded per game. At N > 1 the
  games that share a batch depend on finish order, so two runs at the same N can
  in principle differ in a knife-edge game. None did here.

## Measured agreement (droplet, same machine, same seeds)

`s-8vcpu-16gb-amd`, 8 workers, torch 2.14.0+cpu, seed0 20600000. The N = 1 runs
went through the full runner (`bf-ckpt-n1`, `bf-bot-n1`). The other N ran on the
same two droplets afterwards. Every run passed the runner's schedule check (each
scheduled game exactly once, on the right engine seed).

Checkpoint pairs: chain34 v chain30 and chain34 v chain27, 600 games each.

| N | same `action_trail_sha256` | same score | chain34 v chain30 W/D/L, TD | chain34 v chain27 W/D/L, TD | integrity counters |
|---|---|---|---|---|---|
| 1 | reference | | 219/209/172, 1.2867-1.1400 | 227/217/156, 1.0367-0.8633 | all zero |
| 2 | 1,200 / 1,200 | 1,200 | identical | identical | all zero |
| 4 | 1,200 / 1,200 | 1,200 | identical | identical | all zero |
| 8 | 1,200 / 1,200 | 1,200 | identical | identical | all zero |
| 16 | 1,199 / 1,200 | 1,200 | identical | identical | all zero |
| 32 | 1,199 / 1,200 | 1,200 | identical | identical | all zero |
| 64 | 1,199 / 1,200 | 1,200 | identical | identical | all zero |
| 128 | 1,199 / 1,200 | 1,200 | identical | identical | all zero |

Bot pair: chain34 v the offense bot, 1,200 games. N = 1 gave W/D/L 337/670/193
and TD 0.3850-0.2708. N = 2, 4, 8, 16, 32 and 64 each matched it in 1,200 of 1,200
action trails, with identical W/D/L and TD and all integrity counters zero.

The integrity counters are `illegal`, `projection_collision`, `error_episodes`,
`rejected_submissions`, `precheck_collisions`, plus the runner's `unnatural` and
`forward_mismatch` counts. `logprob_sum` (rounded to 4 places) drifts by at most
0.0032 (checkpoint pairs) and 0.0012 (bot pair) between N = 1 and N > 1 over games
with identical actions, which is the rounding made visible.

**A full runner lifecycle at N = 32** (`bf-mixed-n32`: `run --games-per-worker 32`,
chain34 v chain30 and chain34 v offense, 1,600 games each, a fresh droplet, all of
the runner's verification, then teardown) was compared with the chain 34 reference
run, which the Mac played unbatched on 2026-09-16:

| compared with | games | same `action_trail_sha256` | same score | W/D/L and TD | integrity counters |
|---|---|---|---|---|---|
| Mac reference, N = 1 (`compare`) | 3,200 | **3,200** | 3,200 | identical: 606/540/454, 1.29-1.13 and 451/891/258, 0.39-0.28 | all zero |
| droplet N = 1, checkpoint games in common | 600 | 599 | 600 | identical | all zero |
| droplet N = 1, bot games in common | 1,200 | 1,200 | 1,200 | identical | all zero |

The 599 is seed 20600020 again: at N = 32 the droplet plays it the way the Mac
does at N = 1.

### The game that flips

Engine seed 20600020, chain34 v chain30, `A_home`, was replayed on the Mac alone
and inside a batch of 8 with a seat that logs every decision. The first decision
that differs is the AWAY seat's 31st. At that decision the generator state and the
support are identical in both runs. The logits differ by at most 4.6e-4 on a
largest logit of 440 (1 part in a million) and by 1.5e-5 on the two candidates.
The arg head's probabilities are 0.617702 / 0.382288 alone and 0.617696 / 0.382293
in the batch. The draw falls in the 5.4e-6 gap between them, so the seat picks
arg 4 alone and arg 0 in the batch. The logit difference does not grow over the
30 decisions before it (2.7e-5 to 1.0e-3, no trend), so rounding does not build
up in the recurrent state.

This game has two outcomes and rounding picks one: 494 engine steps (Mac N = 1,
droplet N >= 16) or 476 (droplet N = 1, Mac N = 8 and 16). Both end 0-0.

## Throughput

Games per second of wall time for the whole 1,200 game run, worker start and the
drain at the end included. 8 workers, one game per task.

| N | checkpoint pairs | speedup | bot pair | speedup |
|---|---|---|---|---|
| 1 | 1.54 | 1.0 | 1.83 | 1.0 |
| 2 | 2.01 | 1.3 | 2.48 | 1.4 |
| 4 | 2.88 | 1.9 | 3.91 | 2.1 |
| 8 | 4.30 | 2.8 | 5.77 | 3.2 |
| 16 | 6.02 | 3.9 | 7.41 | 4.1 |
| **32** | **7.74** | **5.0** | **8.68** | **4.7** |
| 64 | 8.70 | 5.6 | 9.96 | 5.4 |
| 128 | 9.20 | 6.0 | not run | |

The full-lifecycle run at N = 32 played its 3,200 mixed games (half checkpoint
pair, half bot pair, interleaved, so each worker made two checkpoint forwards per
step) at **8.73 games/s** in 367 s. It is longer than the sweep runs, so the drain
weighs less. The droplet lived 9.9 minutes and cost $0.027.

- **Where it stops.** Each doubling up to 16 adds 28 to 57%. 16 to 32 adds 29%
  (checkpoints) and 17% (bot), 32 to 64 adds 12% and 15%, 64 to 128 adds 6%. With 8N games in flight, the drain at the end of a run
  also grows with N: at N = 128 a 1,200 game run is almost all drain, so the
  large-N numbers understate a long run and overstate nothing.
- **Memory.** Flat in N: about 2.8 GB summed over the parent and 8 workers on the
  checkpoint runs (320 MB for the largest process), 2.3 GB on the bot run. The
  torch runtime and the weights dominate. An engine and a seat are small. The
  droplet has 16 GB.
- **CPU steal** stayed between 0.02% and 0.04%.
- **What the time is now.** A profile of one worker at N = 32 (chain34 v chain30):
  33% in the matrix products (0.2 ms per seat-row, against 3.0 ms per batch-1
  forward), 31% in `select_joint` (a third of that in the three `multinomial`
  calls), about 20% in the gate arithmetic (`exp`, `where`, the native fast
  sigmoid), the rest in the engine calls and bookkeeping. The sampler and the gate
  arithmetic are fixed by the parity contract with the native rollout, so they
  were left alone. Going past about 10 games/s per droplet means changing one of
  them, and that needs its own parity decision.

### Mac spot check

One measurement, at the owner's request for low load: 2 workers, `nice 20`, 69 s in
total, chain34 v chain30, with the machine at load 8.

| N | games | games/s wall | same action trail as the Mac reference run |
|---|---|---|---|
| 1 | 80 | 2.87 | 80 / 80 |
| 8 | 120 | 5.18 | 119 / 120 |
| 16 | 120 | 7.86 | 119 / 120 |

These runs are short, so worker start (about 3 s) weighs on all three. Apple
silicon is not memory-bound at batch 1 (its `linear` costs the same per row at
batch 1 and batch 8), so the Mac gains less than a droplet: about 2.7 times at
N = 16. The differing game is seed 20600020 again.

## Recommended N

| machine | N | why |
|---|---|---|
| DigitalOcean `s-8vcpu-16gb-amd`, 8 workers | **32** | 5 times the unbatched rate. 256 games in flight is under a tenth of a 3,200 game shard, so the drain stays small. |
| the same, one droplet playing 10,000 games or more | 64 | 12 to 15% more, and the drain no longer matters. |
| Mac, 2 to 4 workers | 16 | 2.7 times in the spot check. Not tuned further because the Mac was in use. |
| any registered gate | **1** | The gate procedure is unchanged until the journal says otherwise. |

## What it means for a 22,400 game gate

The chain 35 gate shape: 7 pairs x 3,200 = 12,800 checkpoint games and 9,600 bot
games. Droplet price $0.16667 per hour, about 5 minutes of fixed overhead per
droplet (create, install, sync, copy back, destroy).

| plan | N | wall time | cost |
|---|---|---|---|
| one droplet, unbatched (measured earlier today) | 1 | about 4.4 h | about $0.73 |
| one droplet | 32 | 22,400 / 8.73 = 43 min, plus overhead: **about 48 min** | **about $0.13** |
| four droplets, split by pair | 1 | about 77 min | about $0.77 |
| four droplets, split by pair | 32 | slowest shard 6,400 / 8.73 = 12 min, plus overhead: **about 17 min** | **about $0.17** |
| the Mac, 4 workers, unbatched, at load 47 | 1 | about 85 min | $0 |

The N = 32 rows use the 8.73 games/s of the mixed full-lifecycle run, the longest
batched run here and the closest in shape to a gate shard. The sweep's 1,200 game
rates (7.74 and 8.68) give 51 minutes for one droplet. Shared hosts vary by about
25% from droplet to droplet, so read all of these the same way. At N = 32 one droplet beats the four-droplet unbatched plan on wall time and
costs a fifth as much, which also leaves the account's droplet slots free.

## How to run

```bash
# local
OMP_NUM_THREADS=1 .venv/bin/python -m play_harness.tournament \
    --games-per-worker 16 --workers 4 --pair A,B,400 --out-dir DIR
# BBPLAY_GAMES_PER_WORKER is the fallback when the flag is absent

# droplet
tools/droplet_tournament.py run --name NAME --games-per-worker 32 \
    --checkpoint ... --pair ... --seed0 S
```

The runner refuses a value outside 1 to 256 before it creates anything, forwards
the flag, checks the copied manifest against it, and writes it to
`droplet_run.json`. At the default of 1 the droplet command line is unchanged.

## Tests

`play_harness/tests/test_batched_tournament.py`, 25 tests, about 50 s. No
network, and only the CLI checkpoint test and the reference-run test need local
artifacts (they skip without them).

- **Structural, exact.** `RowwisePolicy` computes each batch row with its own
  batch-1 forward, which removes rounding and nothing else. With it a batched game
  must equal its unbatched game in every record field, and does: at N = 2 and
  N = 8 over ten games (checkpoint-style pairs, policy v bot both ways, bot v
  bot); for one game played in two different batches, in a different row, beside
  different games; for games that enter a slot another game just left (every
  seat's first forward sees an all-zero state, and every seat has its own
  generator); with argmax on one seat and temperature 0.5 on the other; and with
  one policy object on both seats sharing one forward.
- **Numeric.** The real batched forward is compared with batch-1 forwards of the
  same inputs at every step of the same ten games. Largest relative difference:
  3.0e-5 in the logits on the Mac, 1.4e-5 on the droplet (the random test policies
  have activations in the thousands). 10 of 10 action trails matched at N = 2 and
  N = 8 on both machines. The test allows one miss, for the reason this document
  exists.
- **Forward accounting.** A bot seat adds no forward row, and a step makes at most
  one forward per policy.
- **Contract.** An out-of-support tuple and a skipped waiting-step forward abort
  the batch and name the game. A full runner and a repeated task are refused.
- **CLI.** The default and `--games-per-worker 1` never reach the batched workers
  and write identical games and manifests. N = 3 with two worker processes plays
  a partial run, resumes it, and ends with every game exactly once, equal to the
  N = 1 run (bot games carry no floats). A resume at another N is refused, through
  the flag and through the environment variable, and a manifest without the key
  resumes only at 1.
- **Worker failures.** A worker that cannot load its checkpoint reports and stops
  the run. A worker killed without a report stops the run. The schedule is fed in
  a window (5,000 tasks through queues that hold 18). A worker that fails to start
  leaves no process or queue behind.
- `test_droplet_tournament.py` gained 6 tests (81 in all): the flag in the
  droplet command line, the manifest check, the range refusal before any API
  call, and the merge refusal.
- The full `play_harness/tests` suite passes on the Mac. The batched and tournament
  tests also pass on the droplet (x86-64, torch 2.14.0+cpu).

An independent review (Codex, 2026-09-17) found no cross-game leakage, no RNG
coupling and no change in the N = 1 path. It did find that the first version
queued the whole schedule before reading any result, which can block for good on
a bounded OS queue, that a failed worker start skipped cleanup, and that the
runner accepted a bad N until after it had built a droplet. All three are fixed
and tested.

## Limits

- Agreement was measured on chain 34, 30 and 27 and the offense bot, at
  temperature 1 in sample mode, on one CPU model. Another checkpoint will have
  its own knife-edge games. Expect about one game in a thousand, not zero.
- Throughput was measured on 1,200 game runs with one or two pairs per droplet.
  A worker that holds many pairs at once makes one forward per distinct
  checkpoint per step, so a full round robin on one droplet batches less well
  than a shard of one or two pairs.
- The Mac number is one short, niced measurement on a busy machine.
- Two runs at the same N > 1 are not guaranteed identical in a knife-edge game,
  because batch composition follows finish order. A gate that needs replayable
  games should stay at N = 1 or accept that.
- Spend on this work: $0.34 (`bf-bot-n1` $0.151 and `bf-ckpt-n1` $0.161, each kept about 55 minutes for the sweep, and `bf-mixed-n32` $0.027; the leak check was clean afterwards).
