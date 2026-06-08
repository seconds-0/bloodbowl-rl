---
name: fleet-ops
description: >
  Operate the bloodbowl-rl Vast.ai training fleet solo — restart or hibernate boxes,
  warm-relaunch a training arm (full rebuild sequence included), ship checkpoints and
  payloads box-to-box, run a 4096-game tournament, arm monitors and the credit balance
  guard, and avoid every known footgun. Use when the user says "restart the fleet",
  "relaunch training", "warm relaunch", "hibernate the boxes", "ship the checkpoint",
  "run a tournament", "convert checkpoint", "the trainer died", "Vast balance is low",
  "which box is which", "set up a new box", "sync code to the boxes", or anything about
  bb-japan-native, bb-taiwan-anchor, bb-ballhawk, bb-possession, fleet.sh, or
  run_synthesis_c.sh.
---

# Fleet Ops — bloodbowl-rl Vast.ai training fleet

You are operating this fleet alone. Everything below is verified operational fact
(seed 2026-06-08, cross-checked against the repo). Placeholders are written
`<LIKE_THIS>` — substitute before running. Read FOOTGUNS (§8) before touching anything.

## 1. Fleet inventory

4 Vast.ai boxes. **Labels are state** — always check reality first (restarts can also
change ssh host/port, so re-check after any stop/start):

```bash
vastai show instances --raw
```

| Label | SSH | Cores | Role / notes |
|---|---|---|---|
| `bb-japan-native` | `ssh3.vast.ai:12464` | 24c | "box-1": scraper + judge GPU + **replay cache SOLE COPY (~27K files)** — protect above all others |
| `bb-taiwan-anchor` | `ssh2.vast.ai:31946` | 28c | "box-2": running v3_tax completion |
| `bb-ballhawk` | `ssh4.vast.ai:25430` | 64c FAST | running v4_s2 flagship (maxdist 9 from v4_s1_final 15B ckpt) |
| `bb-possession` | `ssh7.vast.ai:30498` | 64c FAST | running v4_s2tax twin (same + `reward_rush_cost 0.015`) |

- SSH key: `~/.ssh/id_ed25519`; repo on every box: `/root/bloodbowl-rl`
- Example: `ssh -i ~/.ssh/id_ed25519 -p 12464 root@ssh3.vast.ai`
- **Checkpoints live under `/root/bloodbowl-rl/vendor/PufferLib/checkpoints/bloodbowl/<run>/`**
  (the trainer runs with cwd `vendor/PufferLib`). There is NO top-level
  `/root/bloodbowl-rl/checkpoints/` — do not look there.
- **Mac → ssh4 can be pathologically slow.** Ship big payloads box-to-box with
  `ssh -A` from a fast box (§4). Never push gigabytes from the Mac directly.

### tools/fleet.sh

Subcommands: `search` / `ls` / `setup` / `launch` / `status` / `collect` / `destroy`.
- `setup` intentionally **excludes** `venv/`, raylib, and `build/` — those rebuild per-box.
- `collect <name>` rsyncs `vendor/PufferLib/checkpoints/bloodbowl/` + `/tmp/*.log` into `runs/<name>/`.
- `destroy <name>` PERMANENTLY destroys the instance (5s Ctrl-C grace). Never aim it
  at bb-japan-native, and never destroy anything to "free up space" — stopping is the
  only sanctioned reaction to money/quota problems.

## 2. Restart / hibernate boxes

**Hibernate (stop)** is reversible (disks persist) but risky: **Vast stopped instances
can be RECLAIMED (GPU re-rented).** Restart promptly or accept that the box may be
replaced. `bb-japan-native` holds the sole replay-cache copy — never leave it stopped
longer than necessary, never sacrifice it.

```bash
vastai show instances --raw           # inspect; instance IDs come from here
vastai stop instance <INSTANCE_ID>
vastai start instance <INSTANCE_ID>
```

After a restart: ssh host/port may have changed (re-run the raw listing), and
**training does NOT auto-resume** — verify, then warm-relaunch per §3 if a run died:

```bash
ssh -n -o ConnectTimeout=10 -i ~/.ssh/id_ed25519 -p <PORT> root@<HOST> \
  'hostname; ls /root/bloodbowl-rl; nvidia-smi -L; pgrep -af "puffer [t]rain" || echo NO-TRAINER'
```

(`ssh -n` + `ConnectTimeout` are mandatory in any loop — footgun #9.)

### Balance guard (the credit ladder)

`/tmp/vast_ladder.sh` runs **on the Mac** (it polls `vastai show user --raw` every
10 min). It is **stop-only and reversible**, hardcodes instance IDs, and stops in
reverse-value order as credit crosses thresholds:

- balance < **$5** → stop box-2 / tax twin (instance 39471946)
- balance < **$3.5** → stop possession box (39790498)
- balance < **$2** → stop box-1 scraper/judge (39322464)
- it **never stops bb-ballhawk** (the flagship survives longest)
- balance > $12 → the ladder **exits** (boxes restart manually, not automatically)

If boxes are mysteriously stopped, check the balance first — the ladder probably
fired. If **bb-ballhawk** is stopped, the ladder did NOT do it (reclaim/host outage —
investigate). Being in `/tmp`, the ladder dies on Mac reboot and on the >$12 exit;
re-arm with:

```bash
nohup /tmp/vast_ladder.sh >> /tmp/vast_ladder.log 2>&1 &
```

## 3. Warm relaunch of a training arm

### 3a. The launch contract — `tools/run_synthesis_c.sh`

Run on the box from `/root/bloodbowl-rl`. Env vars: `ANCHOR=<path>` (warm-start /
anchor checkpoint, default `training/bc_v3b.bin`), `LOG=<path>` (default
`/tmp/synthesis_c.log`), `STEPS=<n>` (default 10B; **asymmetric runs OVERSHOOT ~1.5x
— known, benign**). Extra args pass through to `puffer train` (`--env.*`,
`--train.frozen-enemy-path <CKPT>` for asymmetric frozen-defense runs).

Hard prerequisites the script enforces — know them before you stall on them:

1. **Refuses to double-launch** if any `puffer train` is live. Kill the old trainer
   first: `pkill -f '[p]uffer train'` (bracket pattern, footgun #3).
2. **Dead-lineage guard: anchors ≤13MB are REJECTED.** (Direction matters: healthy
   obs-v3/v4 torch checkpoints are >13MB; the dead 832-obs lineage is ~12MB. Big is
   fine; small is the red flag.)
3. **Demo bank required:** `vendor/PufferLib/resources/bloodbowl/state_bank.bbs`,
   >1MB, or the script aborts (a missing bank would otherwise SILENTLY train
   procgen-only — the guard exists because of that).

**CRITICAL: the script hardcodes the LEGACY synthesis-C reward economy** (ball_gain
0.1, **ball_loss -0.2**, full k values, demo-reset-pct 0.5, no possession annuity).
Your `--env.*` args are appended last and override, but anything you don't pass keeps
the legacy value — in particular the **ball_loss -0.2 poison** survives unless you
explicitly zero it. For any v4-economy arm, pass the FULL knob set in §3e. After
launch, confirm the effective config in the log.

Knob naming: env-internal names use underscores (`reward_possession`); the CLI form is
`--env.` + dashes (`--env.reward-possession`).

### 3b. Picking the warm-start checkpoint

Warm relaunch = `ANCHOR=<newest checkpoint of the lineage you intend to continue>`:

```bash
ls -t /root/bloodbowl-rl/vendor/PufferLib/checkpoints/bloodbowl/*/0*.bin | head -5
```

**CAUTION: newest mtime != highest step across run dirs.** Inspect the step numbers in
the filenames per run dir; each run dir has a `PROFILE` file naming its arm. Old
**obs-v3 lineage checkpoints are input-shape INCOMPATIBLE** with v4 (1612B vs 2782B
obs) — never warm-start a v4 arm from a v3 file.

### 3c. Full rebuild sequence (MANDATORY after ANY env code change)

The GPU build compiles the **installed snapshot** (`vendor/PufferLib/ocean/bloodbowl/`),
NOT `engine/src` or `puffer/bloodbowl/` — an edit without a re-install silently trains
on stale rules.

```bash
cd /root/bloodbowl-rl
bash tools/install_puffer_env.sh          # refresh the snapshot
bash tools/install_puffer_env.sh --check  # drift guard — exit 1 means re-run install
cd vendor/PufferLib && rm -rf build && ./build.sh bloodbowl --float
```

Rules that are not optional:
- `--float` is required for the **torch** backend. A plain build produces **bf16 for
  native CUDA** — wrong artifact for torch runs.
- **Never skip `rm -rf build`** — stale objects bite.
- Sync `engine/` AND `puffer/` **together** (header + binding.c as a unit), then
  verify the change landed in the INSTALLED copy on the box:
  `grep <your change> vendor/PufferLib/ocean/bloodbowl/<file>` (footguns #1, #4).

### 3d. Obs-size sync points (v4 era)

obs-v4 = **2782 bytes** (probability planes A1/A2/B; spec: `docs/obs-v4-spec.md`).
Three places must agree; static asserts catch only **2 of the 3**:

1. `BBE_OBS_SIZE` in `puffer/bloodbowl/bloodbowl.h` (currently line ~96)
2. `#define OBS_SIZE` in `puffer/bloodbowl/binding.c` line 8
3. `--obs-size` in `training/convert_checkpoint.py` — `DEFAULT_OBS_SIZE = 2782`;
   **v3 ckpts need `--obs-size 1612`, obs-v2 legacy 832**

The convert script default is the one the asserts do NOT catch — check it by hand
(note: its `--help` text lags; trust the `DEFAULT_OBS_SIZE` constant).

### 3e. Launch and verify

Reference launch for a v4-economy arm (stage-3 example — adjust maxdist/STEPS):

```bash
cd /root/bloodbowl-rl
pgrep -af 'puffer [t]rain' && pkill -f '[p]uffer train'   # script refuses to double-launch
ANCHOR=vendor/PufferLib/checkpoints/bloodbowl/<S2_RUN>/<HIGHEST_STEP>.bin \
LOG=/tmp/v4_s3.log STEPS=<N> \
bash tools/run_synthesis_c.sh \
  --env.demo-endzone-maxdist 12 \
  --env.reward-possession 0.03 --env.reward-ball-loss 0 \
  --env.reward-ball-gain 0.05 --env.reward-dist-ball 0.05 --env.reward-dist-endzone 0.2 \
  --env.reward-k-kd 0.03 --env.reward-k-value 0.25 --env.reward-k-ball 0.15 --env.reward-k-seq 0.01 \
  [--env.reward-rush-cost 0.015] [--train.frozen-enemy-path <FROZEN_CKPT>]
```

(The four `reward-k-*` values are the "k-half" set — half the script's legacy
defaults; they must be passed explicitly or you get the full legacy values.)

**The script prints `LIVE: pid ...` or `TRAINER DIED` at 40 seconds.** Do not walk
away before you have seen `LIVE`, and check the echoed config lines + `Loaded N demo
states` above it. If it died, read `$LOG` — usual suspects: stale build (redo §3c),
obs-size mismatch (§3d), wrong-lineage anchor (§3b).

### 3f. Current-era reference config (v4, the settled reward economy)

- Anchor: `bc_v4.bin` (val exact 0.508; lives on the boxes, not in the Mac repo);
  2.09M pairs in `validation/pairs_v4` (`pairs` symlink points there on v4 boxes);
  `bc_acc` ceiling ~0.51 for v4.
- `reward_possession 0.03` — zero-sum annuity, paid +/- per own-turn-ended-holding.
  **`ball_loss` MUST be 0 whenever the annuity is on** — the loss-fine is measured
  poison (D42/D43) — and per §3a you must zero it EXPLICITLY at launch.
- `ball_gain 0.05`, `dist_ball 0.05`, `dist_endzone 0.2`; k-half `0.03/0.25/0.15/0.01`
- `reward_rush_cost 0.015` (rush tax; A/B leaning adopt — anti-degeneracy scaffolding
  per D46, never a permanent value statement)
- BC anchor: `bc_coef 1.0` cosine-decayed to 10% (`bc_coef_floor`, default 0.1)

### 3g. Curriculum ladder

`demo_endzone_maxdist 6 -> 9 -> 12 -> uniform(0) -> kickoff` (`demo_reset_pct 0` only
at the kickoff stage), +3 squares per stage, advance when `tds` plateaus, warm-start
each stage from the newest checkpoint of the previous one. Next queued: v4 stage-3
(maxdist 12) when v4_s2 plateaus.

## 4. Shipping payloads box-to-box

Never route big files Mac → ssh4. Hop through a fast box with agent forwarding:

```bash
# From the Mac, land on a fast box with your agent forwarded:
ssh -A -i ~/.ssh/id_ed25519 -p <FAST_BOX_PORT> root@<FAST_BOX_HOST>

# Then box-to-box (agent supplies the key):
scp -P <DEST_PORT> /root/bloodbowl-rl/vendor/PufferLib/checkpoints/bloodbowl/<RUN>/<CKPT>.bin \
    root@<DEST_HOST>:/root/bloodbowl-rl/
```

Small payloads (configs, single scripts) may go direct from the Mac, but code syncs
must still obey footgun #4: ship `engine/` and `puffer/` together, re-run
`install_puffer_env.sh`, and `grep` the installed file on the destination box.

## 5. Tournament procedure

Tournaments run on box-1 (`bb-japan-native`, the judge GPU). `puffer match` runs on
the **native CUDA backend only** — that is why checkpoints must be converted first.

1. **Ship both checkpoints to box-1** (via §4 if large).
2. **Convert each to CUDA format — `-o` is REQUIRED, and mind `--obs-size`:**

```bash
cd /root/bloodbowl-rl
python training/convert_checkpoint.py --to-cuda <A>.bin -o <A>_cuda.bin            # v4 ckpt: default 2782 correct
python training/convert_checkpoint.py --to-cuda <B>.bin -o <B>_cuda.bin --obs-size 1612   # ONLY if B is v3
```

(Arch comes from the run config's `[policy]` section; override with
`--hidden-size`/`--num-layers` if converting a foreign checkpoint.)

3. **Run the match:**

```bash
puffer match bloodbowl \
  --load-model-path <A>_cuda.bin \
  --load-enemy-model-path <B>_cuda.bin \
  --num-games 4096
```

4. **Read the result line** — A/B/draw are FRACTIONS, not counts:
   `games=4096/4096  A=0.412  B=0.396  draw=0.192`

### Interpreting results (D50/D56 graduation rule — do not panic-quit a run)

- Kickoff-start tournament win-rate is the **FINAL exam only**, for the final
  curriculum stage.
- **Mid-curriculum tournaments draw 97–99%. That is EXPECTED, not failure.**
  Calibrations, not verdicts.
- Draw rate RISES with prior strength (96.8% → 98.8% v3→v4): stronger mirror priors
  mean fewer accident-decided games. The bar rises with the player.
- Per-stage progress = tds-at-stage-starts + retention probes of earlier stages,
  not tournaments.

## 6. Monitors and guards

- **Every monitor / SSH loop uses `ssh -n` and `-o ConnectTimeout=<N>`** or it will
  eat stdin / hang forever (footgun #9).
- **`pkill -f` matches its own watcher command lines.** Always use bracket patterns:
  `pkill -f '[r]un_synthesis'` (footgun #3).
- **Balance ladder:** Mac-side `/tmp/vast_ladder.sh` (§2): stop-only, hardcoded IDs,
  thresholds $5/$3.5/$2, never touches ballhawk, exits at >$12, dies on Mac reboot —
  re-arm with the nohup line in §2.
- **Spectating:** `tools/spectate.sh` gates on the Mac display being awake — raylib
  `InitWindow` segfaults when the display is asleep (footgun #8). Do not bypass.
- **Render/feed hooks:** NEVER format strings or do I/O from env-stepping threads.
  Only safe pattern: POD staging slot consumed by the render thread. Two SIGSEGVs
  taught this (footgun #7).
- **Launch verification is itself a monitor:** `run_synthesis_c.sh` prints
  `LIVE`/`TRAINER DIED` at 40s — absence of `LIVE` is a failure.

## 7. Metric semantics (so you don't misread a healthy run as broken)

- `tds` = per-episode touchdowns **from curriculum starts** — NOT comparable across
  maxdist stages.
- `block_2dred_frac`: human reference 0.017; agent ~0.18–0.20; **falling means the
  probability planes are working.** 2d:2dred human ratio 46:1.
- `possession_rate`: raw prior ~0.15; poisoned ~0.05 (poisoned signature = a
  loss-fine snuck in alongside the annuity — check the launch log shows
  `reward-ball-loss 0`, see §3a).
- `gfi`: human ~2–5/ep; agent ~25–35. Artifact **per D46 unless grounded** — the
  verdict belongs to the tournament, not taste. Apply the D46 discriminator
  (survives grounding? profit routed through the objective? human rates are
  evidence, not law).
- `bc_acc` ceiling ~0.51 (v4).

## 8. FOOTGUNS (each cost real hours)

> (1) python str.replace silently no-ops on anchor mismatch — ALWAYS grep the file
> after scripted edits; (2) zsh does NOT word-split unquoted vars (set -- $hp fails);
> (3) pkill -f matches its own watcher commands — use [b]racket patterns; (4) partial
> code syncs (header without binding.c) build stale mixtures — sync engine/ AND
> puffer/ together, reinstall, verify with grep on the box; (5) Vast stopped
> instances can be RECLAIMED (GPU re-rented) — restart promptly or accept
> replacement; (6) balance ladder /tmp/vast_ladder.sh (Mac) stops boxes at credit <
> $5/$3.5/$2 (stop-only, reversible, never ballhawk); (7) render hooks: NEVER format
> strings or do I/O from env-stepping threads — POD staging slot + render-thread
> consumer (two SIGSEGVs); (8) raylib InitWindow segfaults when the Mac display is
> asleep — spectate.sh gates on display-awake; (9) monitor/SSH loops need ssh -n and
> ConnectTimeout.

Additional standing hazards (same severity):
- **Anchor files ≤13MB are REJECTED by the dead-lineage guard** (dead 832-obs lineage
  is ~12MB; healthy anchors are bigger). Large anchors are fine.
- `run_synthesis_c.sh` defaults to the LEGACY reward economy incl. `ball_loss -0.2` —
  v4 arms must pass the full §3e override set.
- Checkpoints are under `vendor/PufferLib/checkpoints/bloodbowl/`, not the repo root.
- v3 checkpoints are input-shape incompatible with v4 (1612 vs 2782) — convert with
  the right `--obs-size` or don't mix lineages at all.
- Asymmetric runs overshoot STEPS by ~1.5x — known, benign; don't kill them for it.
- The GPU build compiles the installed `ocean/bloodbowl` snapshot — run
  `install_puffer_env.sh --check` before any build (drift = silent stale rules).
- Tier-4 box-side OMP/CUDA knob changes must be A/B'd carefully — one config showed
  an **80x regression**.

## 9. What is running / what comes next (state as of 2026-06-08)

Running now:
- `v4_s2` flagship — bb-ballhawk, maxdist 9, warm-started from v4_s1_final 15B ckpt
- `v4_s2tax` twin — bb-possession, same config + `reward_rush_cost 0.015`
- `v3_tax` completion — box-2 (bb-taiwan-anchor)

Next queue (in order):
1. v4 stage-3 (maxdist 12) when s2 plateaus
2. Rush-tax adoption decision (s2 vs s2tax A/B; per D46, if the untaxed twin keeps
   high GFI AND wins, the tax dies)
3. **Native anchor-free experiment** — the 4x SPS lever: native CUDA backend + frozen
   `bc_v4` as selfplay-pool opponent + NO bc aux. D47 proved anchor release safe;
   measure learning parity vs a torch twin.
4. Tier-4 box-side OMP/CUDA knobs (careful A/B — see 80x regression above)
5. bc_v5 with sequence context (D35: sequence context > bigger policy > more data)
6. Windows 2070 onboarding (task 22); wizards/stars/team-comp backlog (tasks 23–24)

## 10. Doctrine quick-reference (when judgment calls arise)

- **D46:** never patch inhuman behavior by aesthetics; ground it in tournament wins.
  Taxes are scaffolding to be annealed away, deployed as A/Bs.
- **D50/D56:** kickoff tournament = final exam only; mid-curriculum 97–99% draws are
  expected.
- **D42/D43:** `|ball_loss| > ball_gain` in coupon configs; in annuity configs the
  loss-fine is deleted entirely. Potentials must be telescoping/unfarmable.
- **D28/D26:** anneal scaffolding gradually (halve per chained stage); cold-off kills
  the behavior.
- **D38:** torch backend must mask per-head actions at sample AND train-time recompute;
  CUDA backend was always masked.
- **D45/D47:** the BC anchor prevents erosion but is not the binding constraint; prior
  quality is the bottleneck.
- **D35:** verify with extended cosine-decay steps before declaring capacity-bound.
- **D6:** `make goldens` is explicit; rules fixes are expected to break goldens.

---

## Revision log (dry-run against the repo, 2026-06-08 — what the previous draft got wrong)

Simulated tasks: (A) warm-relaunch v4 stage-3 after an env change, (B) run+interpret a
tournament, (C) restart after credit-out. Stalls/wrong-guesses found and fixed above:

1. **Guard direction inverted:** doc said ">13MB trips the dead-lineage guard"; the
   script (`run_synthesis_c.sh:30`) REJECTS anchors ≤13MB. Would have caused fear of
   every healthy checkpoint and acceptance of dead ones.
2. **Wrong checkpoint path:** `/root/bloodbowl-rl/checkpoints/...` doesn't exist; real
   path is `vendor/PufferLib/checkpoints/bloodbowl/` (verified `fleet.sh:133`,
   `spectate.sh:45`). Warm-relaunch step would have stalled at an empty glob.
3. **Hidden legacy economy:** the launch script hardcodes `--env.reward-ball-loss -0.2`
   (documented poison), full k values, `demo-reset-pct 0.5`; §3f values are NOT
   defaults. Added the explicit full-override launch command (§3e).
4. **Undocumented launch prerequisites:** double-launch refusal (`pgrep puffer train`)
   and the >1MB `state_bank.bbs` demo bank (`run_synthesis_c.sh:21,36`).
5. **Tournament convert command errored:** `convert_checkpoint.py` has `-o` required
   (`convert_checkpoint.py:227`); doc omitted it. Also stated WHY conversion is needed
   (`match()` requires the native CUDA backend, `pufferl.py:525`) and that the result
   line reports fractions (`pufferl.py:587`).
6. **Ladder underspecified:** runs on the Mac, hardcoded instance IDs, never stops
   bb-ballhawk, exits at >$12 balance, plus the re-arm command (read from
   `/tmp/vast_ladder.sh`).
7. **Grep-verify target wrong:** the GPU build compiles the installed
   `vendor/PufferLib/ocean/bloodbowl/` snapshot, not `puffer/`; added
   `install_puffer_env.sh --check` drift guard (header of that script).
8. **fleet.sh `destroy` subcommand existed undocumented** — added with the
   never-destroy warning.
9. Minor: knob-name mapping (underscore env names vs `--env.` dash CLI form), LOG
   default, "k-half" defined, restart-doesn't-resume-training, ssh host/port can
   change across stop/start.
