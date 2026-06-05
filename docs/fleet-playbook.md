# Fleet playbook — the experiment wave

Tooling: `tools/fleet.sh` (state = Vast instance labels `bb-<name>`; no local
manifest). Provisioning policy: **filter on `cpu_cores_effective`, not host
cores** — the container slice is what the env threads actually get (box-2
sits on a 224-core host but is allocated 28). `MIN_CORES=32` default; raise
to 64+ for anchored (torch) runs, which are env-CPU-bound (GPU ~11-16%).

## Current fleet

| label | role | notes |
|---|---|---|
| bb-japan-native | native CUDA runs + pipeline | 24 cores; scraper lives here |
| bb-taiwan-anchor | anchored (torch) flagship | 28 cores; synthesis lineage |

## Gate

The wave launches only after the synthesis+C signal (first ~1B steps show
tds holding AND blocks > 0 — both behaviors coexisting). Replicating a
loser n times teaches ~nothing; the frontier stays sequential, the grid
fans out around confirmed winners.

## Wave 1 (on signal): ~8 boxes, one ~30h cycle, ≈$100

```
tools/fleet.sh search                      # pick cores-heavy 4090 offers
tools/fleet.sh provision seed2 <offer>     # x N, label once running
tools/fleet.sh setup seed2                 # rsync + gpu_box_setup.sh
```

- 3x synthesis+C seeds (`--train.seed 43/44/45`) — first-ever error bars;
  launch via `tools/run_synthesis_c.sh` on each box (NOT fleet.sh launch:
  the anchored run needs the --slowly/bc/demobank flags the script pins)
- 3x k-grid: k_kd/k_value/k_ball at (half, spec, double), same seed
- 2x gamma: 0.998 / 0.99975 on the synthesis lineage
- arbiter: bb-japan-native runs `puffer match` round-robins of everything

Collect: `tools/fleet.sh collect <name>` -> runs/<name>/; arbitrate; destroy
losers same day (a parked 4090 is $16/day).

## Thread-scaling test (FREE 2-4x, run before wave 1)

The 96T/48T "crashes" were the vec_log dict overflow (D36 fix), NOT
threading — never retested. After synthesis+C is stable ~1h on bb-taiwan
(28 effective cores, launched at 20T):

1. note Steps + SPS; kill trainer
2. relaunch `tools/run_synthesis_c.sh` with `--vec.num-threads 28` —
   warm-start resumes from the newest checkpoint automatically
3. stable 15 min? record SPS; optionally probe 40T (oversubscription
   sometimes helps I/O-stalled env threads, sometimes thrashes)
4. crash/stall -> drop back to 20T; either way record in DECISIONS

For wave boxes: set threads ~= cpu_cores_effective at provision time.

## Roles beyond Vast

- **Hetzner dedicated** (account exists; hourly CCX first, auction EPYC if
  it earns it): permanent pipeline/arbiter home — scraper, lockstep, bank
  builds, bc training, tournaments — frees every GPU box for training.
  Trigger: when wave cadence makes bb-japan's GPU too busy for arbitration.
- **Alex's RTX 2070** (task #22): free baseload — eval tournaments, bc
  retrains. Needs the WSL2 + `--float` runbook evening.
