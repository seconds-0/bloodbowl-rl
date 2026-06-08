# bloodbowl-rl

RL training harness for **Blood Bowl Third Season Edition (BB2025)**: deterministic C11 rules engine → PufferLib 4.0 native env → PPO + action masking + self-play curriculum, BC warm-start from curated FUMBBL replays. Full plan: `~/.claude/plans/i-need-you-to-merry-naur.md`. Decision log: `DECISIONS.md` (D1–D57 and counting) — **read the tail first; it IS the program state. Where this file and the ledger disagree, the ledger wins.**

## Project skills — use them

| Skill | When |
|-------|------|
| `fleet-ops` | Vast.ai fleet: box inventory, ssh routes, fleet.sh, launch/relaunch, balance ladder, hibernate/restart |
| `training-experiments` | Designing/launching/reading training arms: curriculum ladder, reward knobs, metrics, tournaments |
| `puffer-env-dev` | PufferLib binding, build, training CLI, selfplay config |
| `bb-rules` | Implementing/verifying any game rule, skill, table; edition-delta questions |
| `fumbbl-data` | Fetching/parsing FUMBBL API data or replays; BC corpus curation |
| `bb-validation` | Running/triaging the 7 validation layers; oracle setup (FFB/Jervis/Calculator) |

## Current program state (v4 era, 2026-06-08 — verify against DECISIONS.md tail)

- **Era: obs-v4 + bc_v4.** Sighted stage-1 dominated the v3 lineage on every axis at matched 15B (D55: ~6x faster tds, 2dred falling through the v3 plateau). Mid-curriculum kickoff tournament drew 98.8% — expected per D50/D56, not failure.
- **Running:** `v4_s2` flagship (bb-ballhawk, maxdist 9 from v4_s1_final 15B ckpt `0000014942470144.bin`) · `v4_s2tax` twin (bb-possession, + `reward_rush_cost 0.015`) · `v3_tax` completion (box-2) · **`profile-v4-native-asym` (box-1, D57): the 4x SPS lever FIRED — native CUDA backend, NO bc aux, frozen bc_v4 as selfplay teacher, 2.1M SPS vs torch's 0.6–0.77M. Open question: parity of its tds curve vs the torch flagship at matched steps; if parity holds, torch retires to bc_vN training only.**
- **Curriculum ladder** (stage knob = `--env.demo-endzone-maxdist`): 6 → 9 → 12 → 0 (= "uniform": any demo-bank start, no endzone filter) → kickoff starts (`--env.demo-reset-pct 0`). +3 squares per stage, never more (D51: 6→12 overshot). Advance at tds plateau; warm-start each stage from the previous stage's highest-STEP ckpt.
- **Open queue:** v4 stage-3 (maxdist 12) when s2 plateaus · rush-tax adoption decision (A/B leans adopt) · native-asym parity verdict (D57) · Tier-4 box-side OMP/CUDA knobs (A/B carefully; one config showed 80x regression) · bc_v5 with sequence context (D35) · frozen-opponent ladder if a stage stalls (D56) · Windows 2070 onboarding (task 22) · wizards/stars/team-comp (tasks 23–24).

## Hard-won facts (verified — don't relearn these)

### Obs / checkpoints / build
- **obs-v4 = 2782 bytes** (probability planes A1/A2/B; spec `docs/obs-v4-spec.md`). **Three OBS_SIZE sync points must agree** (static asserts catch 2 of 3): `BBE_OBS_SIZE` in `puffer/bloodbowl/bloodbowl.h`, `#define OBS_SIZE` in `puffer/bloodbowl/binding.c:8`, `--obs-size` in `training/convert_checkpoint.py` (default 2782; v3 ckpts need `--obs-size 1612`). Old obs-v3-lineage checkpoints are input-shape **incompatible**.
- **`puffer/bloodbowl/` is the SOURCE OF TRUTH; `vendor/PufferLib/ocean/bloodbowl/` is an installed snapshot** written by `tools/install_puffer_env.sh` — the build compiles the snapshot, NOT your edit. The snapshot can lag (the Mac checkout's may still say 1612). Drift guard: `tools/install_puffer_env.sh --check` (exit 1 = re-install). Run it before any build on a training box.
- After ANY env code change, ON THE BOX: `bash tools/install_puffer_env.sh` THEN `cd vendor/PufferLib && rm -rf build && ./build.sh bloodbowl --float` (torch needs `--float`; plain build = bf16 for native CUDA; **never skip `rm -rf build`**). Mac = standalone C binaries only (`build.sh <env> --local`, strip `-mavx2 -mfma`); all training/conversion happens on boxes at `/root/bloodbowl-rl`.
- **Launch contract** (`tools/run_synthesis_c.sh`, run on the box from `~/bloodbowl-rl`): `ANCHOR=<path>` (default bc_v3b; >13MB dead-lineage size guard), `LOG=`, `STEPS=` (default 10B; asymmetric runs overshoot ~1.5x, known, benign), trailing args are appended LAST and override (last-wins). **WARNING: the script hard-codes the DEAD synthesis-C economy** (`reward-ball-loss -0.2`, `reward-ball-gain 0.1`, full-k, `demo-reset-pct 0.5`, `--tag profile-synthesis-c`, `--vec.num-threads 20`). For ANY v4 arm you MUST override the full settled knob set as trailing args — at minimum `--env.reward-ball-loss 0 --env.reward-ball-gain 0.05 --env.reward-possession 0.03` plus k-half, dist potentials, stage knob, `--tag`. **Safest: copy the exact command line of a live v4 twin** (`ps aux | grep 'puffer [t]rain'` or head of `/tmp/<tag>.log` on its box) and change only the stage knob, anchor, and tag. Asymmetric: `--train.frozen-enemy-path <ckpt>`. The script requires the demo bank at `vendor/PufferLib/resources/bloodbowl/state_bank.bbs` (a missing bank is SILENT — env trains procgen-only) and prints LIVE/TRAINER DIED at 40s — read it before walking away.
- **bc anchors live per-box only**: `fleet.sh setup` excludes `training/*.bin`; the repo tops out at bc_v3b. `bc_v4.bin` (val exact 0.508; bc_v3b was 0.371) sits in `/root/bloodbowl-rl/training/` on the v4 boxes — ship box-to-box, never re-derive. 2.09M pairs in `validation/pairs_v4` (`pairs` symlink on v4 boxes). bc_acc ceiling ~0.51 in v4 arms.
- Warm relaunch: ANCHOR=newest ckpt, but **newest mtime ≠ highest step across run dirs** — check the step number embedded in the filename.
- **Masked sampling is now the default in BOTH backends** (D38): torch applies per-head `masked_fill(-inf)` before sampling, stores masks in experience, re-applies at train-time. All pre-fix torch-run intuitions (illegal_frac 1.000 era) are rebased. CUDA backend was always masked.

### Reward economy (the settled design — D42/D43/D46)
- Possession **annuity** `reward_possession 0.03` (±zero-sum per own-turn-ended-holding; **ball_loss MUST be 0 with it** — the loss-fine is measured poison; the launch script's baked-in -0.2 violates this, see above), `ball_gain 0.05`, `dist_ball 0.05`, `dist_endzone 0.2`, k-half (`k_kd/k_value/k_ball/k_seq` = 0.03/0.25/0.15/0.01), rush tax 0.015 (anti-degeneracy scaffolding per D46, never permanent). BC anchor `bc_coef 1.0` cosine to 10% (`bc_coef_floor` configurable).
- Anti-farming invariants: |ball_loss| > ball_gain when both nonzero; potentials telescoping; blitz exposure rush-gated.

### Metric semantics
- `tds` = per-episode TDs **from curriculum starts** — not comparable across maxdist stages. `block_2dred_frac`: human 0.017, agent ~0.18–0.20, **falling = planes working** (2d:2dred human 46:1). `possession_rate` raw prior ~0.15 (poisoned ~0.05). `gfi` human ~2–5/ep, agent ~25–35 (artifact per D46 unless tournament-grounded).
- **Graduation rule (D50/D56):** kickoff-start tournament win-rate is the FINAL exam only; mid-curriculum tournaments draw 97–99% and that is EXPECTED. Draw rate rises with prior strength.
- **Tournament procedure** (runs on box-1's judge GPU): ship both ckpts to box-1 box-to-box, convert BOTH sides — `python training/convert_checkpoint.py --to-cuda A.bin -o A_cuda.bin` (**mind `--obs-size`: 2782 default, 1612 for v3 lineage**; conversion drops biases, so equal treatment of both sides matters, D45) — then `puffer match bloodbowl --load-model-path A_cuda.bin --load-enemy-model-path B_cuda.bin --num-games 4096`. Read the decisive-game split, not the draw rate.

### Fleet (details + current state: `fleet-ops` skill)
- 4 Vast.ai boxes, **labels are state** (`vastai show instances --raw`): box-1 = bb-japan-native (24c; scraper + judge GPU + **SOLE COPY of the ~27K-file replay cache** — protect above all), box-2 = bb-taiwan-anchor (28c), box-3 = bb-ballhawk (64c FAST), box-4 = bb-possession (64c FAST). Key `~/.ssh/id_ed25519`, repo `/root/bloodbowl-rl`. Mac→ssh4 can be pathologically slow: **ship big payloads box-to-box via `ssh -A`** from a fast box. `tools/fleet.sh`: search/ls/setup/launch/status/collect (setup excludes venv/raylib/build/`training/*.bin` — rebuilt or shipped per-box; don't "fix" the excludes).
- Hibernated fleet restart: `vastai start instance 39322464 39471946 39790498 39745431` (39322464 also needs the scraper restarted), then resume arms via the warm-start procedure. Balance ladder `/tmp/vast_ladder.sh` (Mac-side) stops boxes in value order at credit <$5/$3.5/$2 — stop-only, reversible; stopped Vast instances can be RECLAIMED, restart promptly.

### Engine / rules / oracles (stable since v1)
- PufferLib 4.0 (`vendor/PufferLib`, branch 4.0) uses `src/vecenv.h` macros — the online `env_binding.h` ABI is dead 3.0. `ocean/chess/` is the template; `ocean/convert/` is stale.
- Rules source: `docs/vendor/bloodbowlbase/` mirror (May 2026 FAQ, inline `<del>` errata — second sentence is current law). BB2025: 30 teams, Devious category, Elite Skills 0–4 cap. May 2026 errata removed the "D6 never below 1" floor. Team re-rolls UNLIMITED per turn (D15).
- FUMBBL replays: `game` = END-of-game snapshot; kickoff state from setup-phase `fieldModelSetPlayerCoordinate`; dice/decisions in `reportList.reports`. `vendor/ffb/.../PlayerState.java` is the authoritative bit table.
- Jervis: parallel bb2020/bb2025 suites (~174 files, diff for deltas); foul conversion broken (@Ignore). ActionCalculator (281 rows) defaults Season3=BB2025 — valid oracle odds. FFB headless needs MySQL ≤5.6/MariaDB ≤10.4; `gamestate/get` is the differential extraction point.

## Top-10 footguns (each cost real hours)

1. `python str.replace` silently no-ops on anchor mismatch — ALWAYS grep the file after scripted edits.
2. zsh does NOT word-split unquoted vars (`set -- $hp` fails).
3. `pkill -f` matches its own watcher commands — use `[b]racket` patterns.
4. Partial code syncs (header without binding.c) build stale mixtures — sync `engine/` AND `puffer/` together (`fleet.sh setup`), re-run `install_puffer_env.sh` (or `--check`), and grep the changed symbol on the box.
5. Vast stopped instances can be RECLAIMED (GPU re-rented) — restart promptly or accept replacement.
6. Launching a "v4" arm via `run_synthesis_c.sh` without overriding its baked-in synthesis-C knobs ships the poisoned ball_loss fine — diff your trailing args against a live twin's command line before launch.
7. Memorial/feed render hooks: NEVER format strings or do I/O from env-stepping threads — POD staging slot + render-thread consumer (two SIGSEGVs).
8. raylib `InitWindow` segfaults when the Mac display is asleep — `spectate.sh` gates on display-awake.
9. Monitor/SSH loops need `ssh -n` and `ConnectTimeout`.
10. "Newest checkpoint" by mtime ≠ highest step across run dirs — check the step number in the filename before warm-relaunching.
11. **CPU thread cap (D59):** `nproc` (visible CPUs) ≫ cgroup quota (allowed CPUs) on some boxes → unpinned torch/BLAS pools thrash (5x SPS loss). `tools/cpu_cap.sh` fixes it and is auto-sourced by all launch scripts + `~/.bashrc`; any manual `puffer train` must `. tools/cpu_cap.sh` first. Verify: live trainer's `OMP_NUM_THREADS` == quota, thread count ~150-190 not hundreds.

## Conventions

- Engine: C11, zero hot-loop allocation, every die through `bb_rng` (PCG-64 or injected script). Deterministic always.
- Every rulebook "may" is policy surface (D29); discovery-vs-artifact discriminator before patching weird behavior (D46); gradual anneal, never cold-off (D28); `make goldens` is explicit — rules fixes are EXPECTED to break goldens (D6).
- Vendored clones read-only, pinned in `vendor/PINS.md` (`tools/vendor_sync.sh`). Doc cache: `docs/SOURCES.md` / `tools/fetch_docs.sh`.
- Atomic commits, no attribution footers, `--no-gpg-sign` if Yubikey absent. No GW rulebook text or assets in the repo.
