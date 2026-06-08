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


---

## 11. Native anchor-free architecture (the 4x path)

The production RL architecture as of D57 (verified live: `profile-v4-native-asym` on
box-1, 2.1M SPS vs torch's 0.6–0.77M). Native CUDA backend, **no BC aux loss**, frozen
`bc_v4` teacher injected through the selfplay league pool and **provably pinned** for
the whole run (Audit 1, 2026-06-08). Read this whole section before launching — the
pinning only works if every knob below is set exactly. The launch script
`tools/run_native_asym.sh` automates almost all of it; prefer the script and read its
output rather than re-deriving the checks by hand.

### When native vs torch

- **Native CUDA backend = ALL RL stages.** Curriculum stages, asymmetric runs,
  frozen-teacher runs, tournaments — everything that is "train the policy with PPO"
  runs native. It is ~4x faster, and the selfplay pool / frozen banks and
  `puffer match` are CUDA-backend-only anyway (selfplay.py raises on any other
  backend).
- **Torch backend = ONLY two jobs:** (1) training new `bc_vN` anchors
  (`training/bc_pretrain.py` is torch-side), and (2) aux-loss research — any
  experiment that needs the BC regularizer or other torch-only loss terms.
- Do not "just use torch because the checkpoint is torch-format" — convert instead
  (see checkpoint formats below).

### Build difference — one backend per box (FOOTGUN)

- **Native build:** `cd vendor/PufferLib && rm -rf build && ./build.sh bloodbowl` —
  **plain, NO `--float`**. Plain = bf16 native CUDA artifact.
- **Torch build:** same but **with `--float`** (§3c; `--float` is required for
  `--slowly`/torch and forfeits the 4x).
- **The two artifacts are MUTUALLY EXCLUSIVE on a box.** Both builds write the SAME
  output files (`pufferlib/_C<EXT_SUFFIX>.so` and `build/bindings.o` — see build.sh):
  rebuilding for one backend silently replaces the other's artifact, and the other
  backend's trainer dies (or worse, misbehaves) at its NEXT launch — possibly days
  later, long after you forgot the rebuild. **Rule: one backend per box.** If a box
  runs native arms, never `--float`-build on it; do torch work (bc_vN training) on a
  designated torch box. If you must flip a box, kill its trainer first, rebuild, and
  treat it as converted — update the box's role in §1.
- Which build is installed (the script checks this for you):
  `cd vendor/PufferLib && python3 -c "from pufferlib import _C; print(_C.precision_bytes)"`
  → `2` = native bf16, `4` = `--float`/torch build, import error = not built.
- The §3c rules still apply unchanged: `install_puffer_env.sh` + `--check` before any
  build, never skip `rm -rf build`.

### Pre-launch: the vendored patches (fresh-re-clone footgun)

`vendor/` is gitignored — a re-clone or vendor refresh silently loses the local
patches this architecture depends on. `run_native_asym.sh` does NOT guard all of
these (run_league.sh does — same machinery); check them yourself after any re-clone,
from `vendor/PufferLib`:

- `grep -q league_preseed pufferlib/selfplay.py` — if missing:
  `git apply ../../training/selfplay_league.patch`.
- `grep -q '^league_preseed' config/bloodbowl.ini` — if missing, refresh:
  `cp ../../puffer/config/bloodbowl.ini config/bloodbowl.ini`. (puffer's
  `load_config` only accepts CLI args for keys present in the ini — without this key
  the `--selfplay.league-preseed` flag itself is rejected.)
- `grep -q 'Warm-started training from' pufferlib/pufferl.py` — the warm-start patch;
  required for `WARM`. Reapply per `.claude/skills/puffer-env-dev/SKILL.md`.

### Launch — `tools/run_native_asym.sh` (the TEACHER/WARM contract)

Run ON the box from `/root/bloodbowl-rl`:

```bash
TAG=<run-tag> TEACHER=training/bc_v4_cuda.bin WARM=<ckpt_cuda.bin> bash tools/run_native_asym.sh [trailing puffer args...]
```

Env-var contract (read the script header for the full text):

- `TAG=<name>` — **REQUIRED.** Also names the default pool dir
  (`training/league_$TAG`) and default log (`/tmp/$TAG.log`).
- `TEACHER=<path>` — the frozen teacher's **CUDA flat blob** (default
  `training/bc_v4_cuda.bin`). The script builds/refreshes the league preseed dir
  around it: copies the blob in, sweeps dead learner snapshots from earlier attempts,
  and writes `league_seeds.json` with `expected_bytes` set to the blob's ACTUAL byte
  size. `expected_bytes` is **mandatory** — it is the Python-side guard against the
  C loader's silent-keep-old-weights failure mode (see TROUBLESHOOTING). bc anchors
  live PER-BOX only (`fleet.sh setup` excludes `training/*.bin`) — ship box-to-box
  via `ssh -A` (§4); if a box only has `bc_v4.bin` (torch), convert:
  `python training/convert_checkpoint.py --to-cuda training/bc_v4.bin -o training/bc_v4_cuda.bin`
  (obs-size default 2782 is correct for v4).
- `WARM=<path>` — optional learner warm-start **CUDA flat blob** (becomes
  `--load-model-path`). Same lineage rules as §3b; v3-lineage blobs are input-shape
  incompatible with v4, and newest mtime ≠ highest step — read the step number in
  the filename.
- `STEPS=` (default 30B) / `LOG=` as in §3a. Asymmetric/frozen-bank runs
  **overshoot STEPS ~1.5x** (30B requested ≈ 45B run) — known, benign, don't kill it.
- `POOL=` (override the pool dir), `EXPECT_BYTES=` (default 16066560 = obs-v4;
  override only for a genuinely new architecture), `SKIP_DRIFT_CHECK=1` (skip the
  `install_puffer_env.sh --check` gate — only for known-cosmetic drift).
- Trailing args pass through to `puffer train` LAST and puffer's CLI is last-wins —
  that is the override mechanism for reward/stage knobs, **and it also means a
  trailing `--selfplay.swap-winrate` / `--selfplay.opp-timeout-steps` /
  `--selfplay.snapshot-interval` would silently UN-PIN the teacher. Never pass the
  pinning knobs as trailing args.**

Both TEACHER and WARM must already be CUDA flat blobs — the script rejects torch
zips (`PK` magic) and wrong sizes (16,066,560 B = current v4; 13,670,400 = v3
lineage; 12,072,960 = dead obs-832 — both incompatible).

The script then runs its own guards (one-trainer-per-box, source drift, native-build
precision check, blob checks, demo bank presence) and at **40s** prints either
`LIVE: pid ...` or `TRAINER DIED` + log tail, and greps the log for
`pufferl_load_frozen_bank` stderr (any hit = the C loader REFUSED the teacher; the
script tells you to kill the run) and for the `Warm-started` line when WARM was set.
**Read that output before walking away.** Then confirm on the dashboard:
`hist_score_bank_0` nonzero and moving = teacher loaded and playing.

Canonical underlying command (verified live on box-1 — if the script ever drifts or
is missing, this is the contract it expands to; note it does NOT build the pool dir,
see the fallback below):

```bash
cd /root/bloodbowl-rl/vendor/PufferLib && puffer train bloodbowl --tag <TAG> \
  --selfplay.enabled 1 \
  --selfplay.league-preseed /root/bloodbowl-rl/training/league_<TAG> \
  --selfplay.swap-winrate 1.1 \
  --selfplay.opp-timeout-steps 100000000000 \
  --selfplay.snapshot-interval 1000000000000 \
  --vec.num-frozen-banks 1 --vec.frozen-bank-pct 0.48 \
  --load-model-path <WARM_CUDA_BLOB> \
  --env.reward-possession 0.03 --env.reward-ball-gain 0.05 --env.reward-ball-loss 0 \
  --env.reward-dist-ball 0.05 --env.reward-dist-endzone 0.2 \
  --env.reward-k-kd 0.03 --env.reward-k-value 0.25 --env.reward-k-ball 0.15 --env.reward-k-seq 0.01 \
  --env.demo-reset-pct 0.9 --env.demo-endzone-maxdist <STAGE> \
  --train.total-timesteps <STEPS>
```

Note what is ABSENT: no `--bc-coef`, no BC aux of any kind, no
`--train.frozen-enemy-path`. The teacher arrives through the league pool, not the
frozen-enemy path. Liveness: `pgrep -af 'puffer [t]rain'` + the echoed config at the
head of `$LOG`. Healthy = zero `pufferl_load_frozen_bank` warnings in the log + a
nonzero `hist_score_bank_0` on the dashboard.

**Fallback — hand-building the 1-seed pool** (only if the script is gone): make the
dir, copy the teacher blob in, and write `<POOL>/league_seeds.json`. The keys
selfplay.py actually consumes are `expected_bytes` (int, the blob's REAL byte size —
never omit) and `seeds`: a list of exactly `num_frozen_banks` entries, each with at
least `"file"` (basename of the blob in the pool dir); `"name"`/`"bank"`/`"sha256"`
are documentation. One bank → one seed entry.

### The pinning knobs — WHY the teacher can never rotate

The selfplay league normally swaps a bank's opponent when the learner beats it. We pin
by making every rotation trigger unsatisfiable (proven against
`vendor/PufferLib/pufferlib/selfplay.py` + `src/pufferlib.cu`, Audit 1; line numbers
are from the patched vendored copy):

- `--selfplay.swap-winrate 1.1` — per-game score is {1.0 win, 0.5 draw, 0.0 loss}
  (bloodbowl.h, episode-end result), so winrate ≤ 1.0 **strictly**. The winrate
  trigger (`selfplay.py:295`, `winrate >= swap_winrate`) requires ≥ 1.1.
  Unsatisfiable. Do NOT "round it down to 1.0" — the comparison is `>=`, so 1.0 is
  reachable and would un-pin the teacher.
- `--selfplay.opp-timeout-steps 100000000000` — the timeout trigger
  (`selfplay.py:298`) needs 1e11 steps on one opponent; the run is ~45B total.
  Unsatisfiable.
- `--selfplay.snapshot-interval 1000000000000` — suppresses interval snapshots
  (gate at `selfplay.py:279`); they are pure dead weight under pinning (ini default
  200M would drop ~150 × 16MB files into the pool dir over 30B). Keep the
  verified-live huge-value convention; don't relitigate it to 0 mid-era.
- With both swap triggers dead, the swap branch (`selfplay.py:315-330`) never arms
  `pending_opp_path`, so `load_frozen_bank` is called exactly ONCE, at setup, with the
  manifest's teacher blob. Eviction, Elo updates, and snapshot saves are all
  bookkeeping-only — none of them touch bank weights. The teacher is immutable for the
  entire run.
- `zero_frozen_advantages_cuda` (pufferlib.cu:1382, called at :1559) zeroes
  advantages on all teacher-controlled rows — the learner never receives policy
  gradient from the teacher's actions.

### The 48% cap (why frozen-bank-pct ≈ 0.48, not more)

`frozen-bank-pct` allocates **agent rows**, but each env carries 2 agents and only ONE
slot per env can be the frozen bank — the other slot is always the learner (it's the
learner's opponent seat). So the meaningful ceiling is **apb/2 = 50% of agent rows**
(setup raises past it; `selfplay.py:160`). At 0.48 (current config: 4096 agents,
2 buffers → 2048 rows/buffer, frozen_size = ⌊2048×0.48⌋ = 983):
**96% of envs play learner-vs-teacher, 4% are pure mirror, 48% of agent slots run the
teacher.** Pushing pct toward 0.50 just squeezes out the last mirror envs; it cannot
give the learner "more teacher than opponent seats exist". Don't chase it.

### Checkpoint formats

- **Native runs save flat fp32/bf16 blobs** (the `master_weights` dump) under
  `vendor/PufferLib/checkpoints/bloodbowl/<run>/` — directly usable as
  `--load-model-path` / `--load-enemy-model-path` for `puffer match` and as
  TEACHER/WARM for future native launches. **No conversion step.**
- **Torch-side needs** (bc_vN work, weight surgery, research): the direction flags
  are `--to-torch` (cuda→torch) and `--to-cuda` (torch→cuda) — there is no
  `--from-cuda`:
  `python training/convert_checkpoint.py --to-torch <BLOB> -o <OUT>.bin` and
  `python training/convert_checkpoint.py --to-cuda <TORCH>.bin -o <OUT>_cuda.bin`.
  **Mind `--obs-size`** — default 2782 (v4); v3 needs 1612, legacy 832. The CUDA
  backend has no bias terms: conversion **drops biases** going torch→cuda (with a
  max|bias| warning) and **zero-fills** them going cuda→torch — treat round-trips as
  lossy and convert both tournament sides the same way (D45).
- The current v4 blob size is **16,066,560 bytes** (4,016,640 fp32 params) — use it
  as a sanity check and as `expected_bytes` in league manifests.

### Parity verdict — `tools/parity_report.py`

The gate for "native replaces torch for this stage": learning parity at matched
steps, not SPS. The harness is `tools/parity_report.py` (NOT under `training/`).
Procedure:

1. Fetch both logs to the Mac (exact scp commands, including the box-1 hop for the
   pathologically slow Mac→ssh4 route, are in the script's docstring), then:
   `tools/parity_report.py /tmp/native.log /tmp/torch.log`
   (two positional args: log A = native, log B = torch reference twin; tune with
   `--interval` / `--tolerance` / `--parity-band` / `--target-tds` if needed).
2. It parses both dashboards, aligns frames at matched **global agent-steps** (NOT
   wall clock — native covers steps ~4x faster; default tolerance 200M, well above
   the ~100M display granularity at B scale) and prints a matched-step table, SPS
   ratio, per-metric verdicts (±15% band default), and wall-clock-to-target-tds
   projections.
3. The verdict metric is **`tds` at matched steps within the parity band** of the
   torch twin. Remember §7: tds is only comparable at the SAME maxdist stage — never
   feed it logs from different stages. A relaunched arm restarts its step counter:
   concatenate old+new logs or pass only the segment you want judged.
4. `block_2dred_frac` LOWER than torch is a finding in native's favor, not a parity
   failure (live early read: 0.105 native vs ~0.2 torch — half). Falling 2dred =
   planes working (§7). `gfi_attempts` is informational only (D46 artifact).
5. Verdict PARITY (or native ahead) → torch retires to bc_vN training + aux research
   only, and this section's launch becomes the default for all subsequent stages.
   Verdict FAIL → keep torch for RL, file the native log for diagnosis, and do NOT
   flip box build artifacts back and forth while investigating (one backend per box).

### TROUBLESHOOTING (from Audit 1 — verified failure modes)

- **The C bank loader fails SILENTLY on size mismatch** —
  `pufferl_load_frozen_bank` (pufferlib.cu:1830) only fprintf-warns and keeps the
  bank's previous weights (garbage at first load). The guards are `expected_bytes` in
  `league_seeds.json` (checked Python-side at setup, run aborts) plus the launch
  script's own blob-size/zip checks and its 40s log grep. Never hand-write a manifest
  without `expected_bytes`; never ignore a loader warning in the log. Healthy launch
  = zero loader warnings + `hist_score_bank_0` moving on the dashboard.
- **Liveness check for "is the teacher actually playing":** `hist_score_bank_0` on
  the dashboard is the learner's score rate vs the teacher (live run: ~0.59). A
  drifting bank Elo proves games ARE being scored every window. `hist_score_bank_0`
  stuck at exactly 0.000 with no Elo drift = bank not routed — recheck
  `--vec.num-frozen-banks` / `--vec.frozen-bank-pct` and the preseed path.
- **16-digit `.bin` files in the league dir = stale snapshots from an old launch.**
  The current script suppresses snapshots (`--selfplay.snapshot-interval 1e12`) and
  sweeps leftovers at launch; if they're accumulating DURING a run, you launched
  without the script or overrode the interval — harmless dead weight under pinning
  (never consumed: the only consumer sits behind the never-armed swap branch;
  restarts load from the manifest alone), safe to `rm`, but check what else you
  overrode.
- **Warm relaunch overwrites old snapshots silently.** `global_step` resets on
  relaunch, so new snapshots reuse old step-numbered filenames in the pool dir.
  Irrelevant while pinned (snapshots are suppressed/dead weight) but would CORRUPT
  pool history in a real rotating-pool run that restarts. Don't repurpose a
  relaunched run's league dir as a genuine pool.
- **Do not "fix" the swap-winrate to a reachable value.** 1.1 looks like a typo; it
  is the pin. Same for opp-timeout-steps 1e11 and snapshot-interval 1e12. And don't
  pass any of them as trailing args (last-wins would re-enable rotation).
- **`--selfplay.league-preseed` rejected at launch / preseed silently ignored** =
  vendored patches lost to a re-clone — run the pre-launch grep checks above and
  reapply `training/selfplay_league.patch` + refresh `config/bloodbowl.ini`.
- **Latent (only if banks are ever reused for team_size>1 envs):** Python aligns
  frozen_size down to a team_size multiple (`selfplay.py:155`) but the C allocator
  does not — for bloodbowl (team_size 1) both compute identically, but a
  multi-agent-team env could route learner rows into the frozen inference slice. Add
  an assert before reusing banks elsewhere.
- **Eviction can't hurt you here:** pool eviction trims only the in-memory list,
  never bank weights, never files; and with snapshots suppressed the pool holds just
  the teacher (max_size 200 never fires).

---

## CPU thread-pool cap (D59) — REQUIRED on every launch, automatic via the scripts

**The trap:** Vast boxes report VISIBLE logical CPUs via `nproc` (one box reads
**255**) but cap actual CPU TIME via a cgroup CFS quota (that same box: **61**
CPUs). With `OMP_NUM_THREADS` unset, PyTorch + OpenBLAS auto-size their intra-op
pools to `nproc`, spawning hundreds of threads that thrash on the quota — a
**measured 5x SPS loss** (114K vs 592K on identical configs; fixed → 500K). The
env-stepping OMP is independent (PufferLib vec `num_threads`) and is NOT the cause.

**The fix is `tools/cpu_cap.sh`** — the single source of truth. It derives the
cgroup quota (v1 `cpu.cfs_quota_us` AND v2 `cpu.max`, clamped ≤ nproc) and exports
`OMP_NUM_THREADS` / `OPENBLAS_NUM_THREADS` / `MKL_NUM_THREADS` /
`NUMEXPR_NUM_THREADS`. It is **already sourced automatically by**:
`tools/run_synthesis_c.sh`, `tools/run_native_asym.sh`, `fleet.sh launch`, and
(via `gpu_box_setup.sh` → `~/.bashrc`) any interactive ssh session.

**Verify it took** after any launch:
```bash
pid=$(pgrep -f 'puffer [t]rain' | head -1)
tr '\0' '\n' < /proc/$pid/environ | grep OMP_NUM_THREADS   # should = the quota, NOT nproc
ls /proc/$pid/task | wc -l                                  # hundreds = thrash; ~150-190 = healthy
```

**If you EVER launch `puffer train` by hand outside the scripts**, source the cap first:
```bash
cd /root/bloodbowl-rl && . tools/cpu_cap.sh && cd vendor/PufferLib && puffer train ...
```

**Quick health triage** for a slow box: compare `nproc` to the cgroup quota
(`awk '{print $1/$2}' /sys/fs/cgroup/cpu.max` or
`echo $(($(cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us)/100000))`). If nproc ≫ quota and
the trainer has >300 threads, the cap didn't apply — re-source and relaunch.
