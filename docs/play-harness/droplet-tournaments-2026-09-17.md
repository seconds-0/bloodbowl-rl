# Tournaments on a throwaway droplet, 2026-09-17

**Question.** Can play-harness tournaments run on a disposable DigitalOcean
droplet instead of the Mac, which reached load 47 on 14 cores during the chain 34
gate run?

**Answer.** Yes, and the runner is proven end to end, but one droplet is slow.

1. `tools/droplet_tournament.py run` creates one tagged droplet, installs CPU-only
   torch, syncs a pinned commit and only the named checkpoints, builds the shim,
   runs the tournament and the stats under nohup, copies the results back,
   verifies them by sha256 and against the manifest, destroys the droplet and
   prints the cost. It ran seven times today. Success, a failing job and a Ctrl-C
   in the middle of the install all ended with the droplet and its ssh key
   verified gone.
2. **The account cannot create a 16 to 32 vCPU CPU-optimized droplet.** The
   largest CPU-optimized size it offers is `c-4`. The largest non-GPU size is
   `s-8vcpu-16gb-amd`: 8 shared vCPUs, 16 GB, $0.16667 per hour. That is the
   default size.
3. **A droplet core plays about one fifth as fast as a Mac core.** One droplet
   plays 1.28 games/s on checkpoint pairs and 1.81 games/s on bot pairs with 8
   workers. The Mac plays 4.4 games/s with 4 workers.
4. **A 22,400 game tournament takes about 4.4 hours on one droplet ($0.73), or
   about 77 minutes split by pair over four droplets ($0.77).** The split is
   sound and has a verified `merge` step. Both commands for the chain 35 gate
   are at the end.
5. **Cross-machine runs agree in distribution, not always game by game.** The 200
   game slice of the chain 34 reference matched the Mac in every game. Over
   2,400 games, 2,399 matched and one took different actions.

## Size and price

| size | vCPU | kind | $/hour | result |
|---|---|---|---|---|
| `s-8vcpu-16gb-amd` | 8 | shared, DO-Premium-AMD | 0.16667 | **chosen**: most cores on offer, flat scaling to 8 workers, steal under 0.2% |
| `c-4` | 4 | dedicated, Xeon Platinum 8280 | 0.12500 | slower per core and worse under load (table below) |
| `c-16`, `c-32` and every other 16+ vCPU CPU size | | | | not offered to this account on 2026-09-17 |

The size list came from `GET /v2/sizes` with the account's token. `run` checks the
size, region and live price before it creates anything, refuses a size above
`--max-hourly` (default $1.00), and stops with a `BLOCKER` message when the
account has no free droplet slot (limit 10, shared with other projects). Pass
`--size c-32` if the account tier is ever raised; nothing else changes.

## Why a droplet core is slow

The policy forward runs at batch size 1. Each forward reads about 16 MB of
weights (encoder 2782 x 512, three 512 x 1536 layers, the decoder), and a game
alternates two checkpoints, so the weights never stay in cache. The forward is
bound by memory bandwidth per core, which is where Apple silicon is far ahead of a
cloud vCPU.

Measured on a kept droplet, chain 34 against chain 30, per-game `seconds` from
`games.jsonl`:

| machine | workers | ms per engine step | games/s (steady) |
|---|---|---|---|
| Mac (reference run, loaded) | 4 | 1.41 | 4.4 |
| `s-8vcpu-16gb-amd` | 1 | 6.98 | 0.24 |
| `s-8vcpu-16gb-amd` | 4 | 7.47 | 0.83 |
| `s-8vcpu-16gb-amd` | 8 | 7.61 | 1.65 |
| `c-4` | 1 | 8.71 | 0.19 |
| `c-4` | 4 | 12.17 | 0.51 |

Checked and ruled out: thread oversubscription (torch reports 1 thread, and one
worker alone on an idle box is just as slow), denormal floats (none in the
recurrent state, and flush-to-zero changes nothing), CPU steal (0.02% to 0.11%).
A single forward takes 3.0 ms on the droplet, 1.7 ms of it in `linear` calls.
Inside the forward those calls move 2.4 million weights per ms; the encoder
layer timed alone, with its weights in cache, moves 9.2 million.

More cores on one box would help only in proportion. The real fix is batching
several games per forward inside a worker. That changes float rounding and the
harness design, so it is out of scope here.

## Throughput and the 22,400 game estimate

Two droplets ran at the same time, 8 workers each, seed block 20600000:

| run | pairs | games | games/s wall | wall | stats (2,000 reps) | droplet lifetime | cost |
|---|---|---|---|---|---|---|---|
| `c34-tp-ckpt` | chain34 v chain30, chain34 v chain27 | 1,200 | 1.284 | 934.7 s | 9 s | 19.9 min | $0.055 |
| `c34-tp-bot` | chain34 v offense | 1,200 | 1.806 | 664.5 s | 3 s | 14.5 min | $0.040 |

Fixed overhead per droplet is about 5 minutes: 150 to 170 s from create to
installed, 20 to 45 s for the sync and shim build, under a minute to copy back,
verify and destroy.

The chain 35 gate is 7 pairs x 3,200 = 22,400 games: 12,800 checkpoint games and
9,600 bot games.

| plan | droplets | wall time | cost |
|---|---|---|---|
| one droplet | 1 | 12,800 / 1.284 + 9,600 / 1.806 = 15,285 s, plus overhead: **about 4.4 h** | **about $0.73** |
| split by pair | 4 | slowest shard 3,200 / 1.284 + 3,200 / 1.806 = 71 min, plus overhead: **about 77 min** | **about $0.77** |
| the Mac, for scale | 0 | 22,400 / 4.4 = 85 min at load 47 | $0 |

Shared hosts vary. The kept benchmark droplet played checkpoint games at 1.65
games/s and the throughput droplet at 1.28, so read these estimates as plus or
minus 25%. Cost is the droplet lifetime prorated from the listed hourly price;
the invoice is the authority.

## Determinism

The slice replayed the chain 34 reference (`c34-gate-20260916`, played on the
Mac): same five checkpoints and offense bot, same five pairs, seed0 20600000, 40
games per pair. The droplet was x86-64, gcc 13.3, torch 2.14.0+cpu, python 3.12.3;
the Mac is arm64, clang, torch 2.14.0. Games are matched on (pair, game index,
leg).

| run | games | same `action_trail_sha256` | same `final_digest` | same score | integrity counters |
|---|---|---|---|---|---|
| slice, AMD droplet | 200 | 200 | 200 | 200 | all zero |
| 16 games, Intel `c-4` | 16 | 16 | 16 | 16 | all zero |
| throughput runs, merged | 2,400 | **2,399** | 2,400 | 2,400 | all zero |

- The one game that differs is chain34 v chain30, game index 20, leg `A_home`
  (engine seed 20600020). It ran 476 engine steps on the droplet and 494 on the
  Mac, and ended 0-0 on both.
- The cause is float rounding. `logprob_sum` (rounded to 4 places) differs from
  the Mac in 1,797 of the 2,400 games even when every action is the same, by at
  most 0.0014. Now and then that difference crosses a sampling boundary and a
  game takes another path.
- `final_digest` matched in the diverged game too, so it is a weak test. Use
  `action_trail_sha256`.
- Outcome distributions agree. Against the reference's full 3,200 games per
  pair, the score-rate z values are -0.07 (chain27), -0.61 (chain30) and -0.37
  (offense).

**Cross-machine runs agree in distribution, not game by game.** Expect about 1
game in 2,000 to differ between the Mac and a droplet. Nothing here tries to
force bit equality. Whether two droplets of the same CPU model match each other
in every game was not tested.

Every droplet built a byte-identical shim from the pinned commit (sha256
`f22b4b6211e1...`, AMD and Intel alike), which is what lets `merge` require one
shim hash across shards. The Mac's shim hash differs, so a run cannot move between
the Mac and a droplet. The runner does not resume; a failed run starts over.

## How to run

Run from a checkout of this branch. The droplet gets `git archive` of `HEAD`
(`play_harness`, `engine`, `puffer`, `training/convert_checkpoint.py`), so
commit first; `run` refuses uncommitted changes under those paths.

```bash
tools/droplet_tournament.py run --name NAME \
    --checkpoint PLAYER=LOCAL_BLOB ... --bot offense=offense \
    --pair A,B,N ... --seed0 S [--out-root DIR] [--max-hours 4] [--keep]
tools/droplet_tournament.py status                  # leak check
tools/droplet_tournament.py destroy --name NAME     # or --id ID when state is lost
tools/droplet_tournament.py compare --run-dir NEW/main --ref-dir OLD/main
tools/droplet_tournament.py merge --out ALL/main --shard S1/main --shard S2/main
```

- **Token.** Read at run time from `DIGITALOCEAN_TOKEN` or
  `~/code/killteam-3d/.env`. It is never written to disk, a log or the droplet.
- **Workers.** Default is the size's vCPU count. `play_harness.tournament` keeps
  its cap of 4 workers on a workstation; the droplet job raises it with
  `BBPLAY_MAX_WORKERS`. Worker count never changes a game.
- **Torch.** `torch==2.14.0` from the CPU wheel index and `numpy==2.5.3`, the Mac
  venv's versions, on Ubuntu 24.04 (python 3.12.3). The install asserts the
  version and that CUDA is absent.
- **Results.** `OUT_ROOT/NAME/main` holds `games.jsonl`, `manifest.json`,
  `COMPLETE.json`, `report.json`, `report.txt`, `machine.json`, `SHA256SUMS`,
  `tournament.log` and `droplet_run.json` (size, price, timings, steal, cost).
  The manifest's `harness_git_head` is the pinned commit, read on the droplet
  from a `SOURCE_COMMIT` file.
- **Verification.** Every copied file must match the droplet's `SHA256SUMS`. The
  manifest must name the pinned commit, the local checkpoint hashes, the seed
  block, the pairs and the task count. `COMPLETE.json` must say complete, the game
  count must equal the request, and every integrity counter must be zero. The
  results move from `main.partial` to `main` only after all of that passes.
- **Teardown.** A `finally` block plus SIGINT, SIGTERM and SIGHUP handlers
  destroy the droplet and the key on every exit path and wait for HTTP 404 on
  both. Signals are ignored during teardown. A failed run first copies whatever
  logs it can reach into `main.failed`.
- **Spend guards.** `--max-hours` (default 4) gives up and destroys the droplet.
  A tournament log silent for `--stale-seconds` (default 900) with no exit file
  is a failure. Liveness is the log's age, not its text.
- **`--keep`** leaves the droplet up for debugging and prints the ssh and destroy
  commands. It keeps billing until `destroy`.
- **Destroy guards.** A droplet is deleted only if it carries the
  `bb-harness-tournament` tag, is named `bb-harness-*`, and (with `--name`) is the
  id recorded in `~/.cache/bb-droplet-tournament/NAME/` at creation. Other
  projects' droplets on the account are never touched.

Keep the Mac awake for the run (`caffeinate -i`). If the runner process is killed
with SIGKILL, or the Mac dies, the droplet survives and keeps billing: that is
what the leak check is for.

## Leak check

`status` lists every droplet carrying the tag with its age and accrued cost, every
`bb-harness-*` ssh key, and every local state directory that still records a
droplet id. Run it after every session. A clean account prints:

```
droplets tagged bb-harness-tournament: 0
ssh keys named bb-harness-*: 0
local state with a live droplet id: 0
```

`run` prints the same block after its own teardown. During today's parallel runs
it correctly showed the sibling droplet that was still working.

## Spend on 2026-09-17

| run | purpose | cost |
|---|---|---|
| `c34-slice-a` | determinism slice, first full lifecycle | $0.015 |
| `bench-c4`, `bench-s8` | kept boxes for the worker-scaling benchmark, then `destroy` | $0.021, $0.028 |
| `c34-tp-ckpt`, `c34-tp-bot` | throughput, two droplets at once, then `merge` | $0.055, $0.040 |
| `trap-fail`, `trap-sigint` | failing job and Ctrl-C teardown | $0.010, $0.010 |
| **total** | | **$0.18** |

## Chain 35 gate tournament

Set the blob path first. Its `.lineage.json` sidecar must sit beside it.

```bash
cd ~/Code/bb-harness-droplet
CHAIN35_BLOB=FILL_IN_THE_CHAIN35_CHECKPOINT_PATH   # .../chain35/0000002999975936.bin
CK=~/Code/bb-play-harness/.play-artifacts/checkpoints
B=0000002999975936.bin
OUT=~/Code/bb-play-harness/.play-artifacts/tournaments
```

### Option A: four droplets, about 77 minutes, about $0.77 (recommended)

Needs four free droplet slots; `run` stops with a `BLOCKER` line if there is none.
Each shard is its own process with its own teardown. Save as a file and run it
with `bash`.

```bash
run() { name=$1; shift
  caffeinate -i tools/droplet_tournament.py run --name "$name" --seed0 20700000 \
      --out-root "$OUT" --max-hours 3 "$@" > "/tmp/$name.log" 2>&1 & }
run c35-gate-20260917-s1 --checkpoint chain35=$CHAIN35_BLOB --checkpoint chain30=$CK/chain30/$B \
    --bot offense=offense --pair chain35,chain30,3200 --pair chain30,offense,3200
run c35-gate-20260917-s2 --checkpoint chain35=$CHAIN35_BLOB --checkpoint chain34=$CK/chain34/$B \
    --bot offense=offense --pair chain35,chain34,3200 --pair chain34,offense,3200
run c35-gate-20260917-s3 --checkpoint chain35=$CHAIN35_BLOB --checkpoint chain27=$CK/chain27/$B \
    --bot offense=offense --pair chain35,chain27,3200 --pair chain35,offense,3200
run c35-gate-20260917-s4 --checkpoint chain35=$CHAIN35_BLOB --checkpoint chain32=$CK/chain32/$B \
    --pair chain35,chain32,3200
wait
tools/droplet_tournament.py merge --out $OUT/c35-gate-20260917/main \
    --shard $OUT/c35-gate-20260917-s1/main --shard $OUT/c35-gate-20260917-s2/main \
    --shard $OUT/c35-gate-20260917-s3/main --shard $OUT/c35-gate-20260917-s4/main
OMP_NUM_THREADS=1 ~/Code/bb-play-harness/.venv/bin/python -m play_harness.tournament_stats \
    --run-dir $OUT/c35-gate-20260917/main --json $OUT/c35-gate-20260917/main/report.json
tools/droplet_tournament.py status
```

`merge` refuses shards that differ in commit, seed block, settings, torch or
compiled shim, that give a shared player a different checkpoint, or that overlap
in pairs. The final stats pass is one process on the Mac (2.6 s for 2,400 games
today). Each shard also carries its own `report.json` for its pairs.

### Option B: one droplet, about 4.4 hours, about $0.73

```bash
caffeinate -i tools/droplet_tournament.py run --name c35-gate-20260917 \
    --checkpoint chain35=$CHAIN35_BLOB \
    --checkpoint chain30=$CK/chain30/$B --checkpoint chain34=$CK/chain34/$B \
    --checkpoint chain27=$CK/chain27/$B --checkpoint chain32=$CK/chain32/$B \
    --bot offense=offense \
    --pair chain35,chain30,3200 --pair chain35,chain34,3200 --pair chain35,chain27,3200 \
    --pair chain35,chain32,3200 --pair chain35,offense,3200 \
    --pair chain34,offense,3200 --pair chain30,offense,3200 \
    --seed0 20700000 --out-root $OUT --max-hours 6
```

`--max-hours 6` matters: the default of 4 would stop this run before it ends.

## Tests

`play_harness/tests/test_droplet_tournament.py`, 60 tests, 0.1 s. A fixture makes
any `urlopen` or `subprocess.run` call fail the test, so nothing can reach the
network. They cover argument building (including a parse by the real tournament
CLI), the droplet-side scripts, size and price checks, cost and estimate math,
sha256 and manifest verification, the run comparison, the merge refusals, the
destroy guards and the droplet-limit blocker.

## Limits

- The 16 to 32 dedicated vCPU size in the brief does not exist on this account.
  The numbers above are for 8 shared vCPUs.
- One droplet is slower than the Mac. Only the split across droplets gets close
  to the Mac's wall time.
- Throughput was measured on chain 34 pairs. Chain 35 games may run longer or
  shorter.
- Option A was proven with two concurrent shards and a merge, not with four.
