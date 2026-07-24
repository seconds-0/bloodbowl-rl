# bloodbowl-rl

RL training harness for **Blood Bowl Third Season Edition (BB2025)**:
deterministic C11 rules engine → PufferLib 4.0 native env → PPO + action
masking + self-play curriculum, with BC support from curated FUMBBL replays.

**Read `AGENTS.md` first** — it holds the experimental contract, the rules/reward
semantics, the build sequence, and the project-skill map. This file holds current
program state, verified facts, and footguns. Then read the tail of `DECISIONS.md`
and, for reward/replay work, `docs/reward-and-replay-audit-2026-07-09.md`. The
ledger is chronological; the July audit and D177–D192 supersede older prose that
calls the June v4 reward economy "settled." Where this file and newer ledger
evidence disagree, the newer evidence wins.

## Current program state

- **No production reward has been promoted.** R0
  (`puffer/config/rewards/r0_full.json`) is the next-stage experimental baseline
  only. Don't silently change defaults or touch the production evaluator/stream.
- **Distance is the learnability scaffold (D177):** across the repaired paired
  2×2 its main effect was `+0.76365 TD/game` and `+0.11130` match score. It also
  increased blocks and 2D-red rate. Raw `ΔΦ` is not exact PBRS at `gamma=0.995`;
  make it discounted-exact or anneal it away once capability exists.
- **R2 failed transfer (D178):** removing possession+gain made match score worse
  in all 8 paired seed/style/side cells, and raised losses plus opponent TDs in
  all 8. Retain R0, but decompose possession annuity from ball-gain before any
  confirmation. **Next screen:** distance on in all arms; `{possession+gain,
  possession-only, gain-only, neither}` at `500M × 2 seeds`; then learned
  opponents, roster macro, longer run, and second ancestry.
- **D182 — the July 13–14 screen is unusable:** it finished all eight arms, but
  one train emission crossed PPO's clamp by exactly `0.015` and the old schema
  cannot classify its sign or terminal context; the audit independently found an
  unsafe terminal result-plus-shaping path. Do not feed it to transfer. Correct
  terminal composition, add split recurrence telemetry, rerun every arm.
- **Replay edition/coverage gate (D179):** 15,347 raw = 11,580 BB2025 + 3,767
  BB2020. Use the strict 9,118-ID non-empty BB2025 allowlist. The 1,622,231
  joined BB2025 records are sharply opening-censored and rare-action poor.
- **Strict replay-state bank (D191/D192):** the historical BBS bank contains 123
  BB2020-source records among 15,471. Use the hash-pinned
  `tools/filter_state_bank.py` subset: 15,348 records from 5,328 strict BB2025
  IDs. It is still all half one and opening-censored — filtering edition does not
  create passing or late-game coverage, so don't wire it into training without
  review. `bank_scenario_scan` / `report_scenario_coverage.py` classify
  overlapping S1–S6 *opportunity* structures only: no actions, outcomes, regret,
  or curriculum weight. The BBS1 fingerprint is an ABI/build guard, not content
  validation: preserve the loader's bounds, enum, grid/player, and ball-state
  checks for every raw snapshot before it enters reset selection.
- **Authored drill bank:** design, recipe families, and validator split live in
  `docs/plans/authored-drill-state-bank.md`. The load-bearing invariant: every
  state is reached only through legal `bb_apply` actions from an engine
  initializer and must reproduce the raw match bytes exactly under
  `bb_rng_script` — never construct one by writing score, half, turn, players,
  grid, ball, or procedure frames.
- **BC loader (D180):** bounded streaming loader, replay-disjoint split.
  Replay-first is the current default, not the final sampler; next stratify by
  roster/matchup, depth, and action family.
- **Long-horizon curve (D187/D188):** the frozen seed-42 0–6B curve improves
  against its four static training banks but is non-monotonic, in-pool evidence.
  Do not select the newest checkpoint or reward from it. Post-run selection uses
  the paired milestone matrix (`docs/plans/r0-milestone-evaluation.md`,
  `tools/run_checkpoint_milestone_eval.py`); its static-pool metrics are
  in-sample, its historical anchors are lineage-connected rather than held out,
  its roster grid is stratification (training sampled every roster), and a
  plateau nomination is a candidate for more evaluation, not a promotion.
- Canonical artifacts:
  `runs/reward-screens/reward-screen-20260709-v1/SCREEN_COMPLETE.json`,
  `runs/reward-transfer-20260713-v1/ANALYSIS.json`, and
  `runs/replay-audit-20260713/`.

### Historical lineage context (not current reward authority)

- **v5 PATH-ACTIONS (D85/D91 — REVISED):** `macro_moves=1` = STEP head selects any
  reachable destination, env auto-routes (engine untouched). Wins MIRROR offense
  evals (+26%, 1.625 from-kickoff) but LOST the first head-to-head tournament to
  the v4 lineage (~45% of decisive games, both env configs). **Mirror evals are
  offense diagnostics only; TOURNAMENTS are the strength scoreboard.** Eval/launch
  macro ckpts with trailing `--env.macro-moves 1`. Since the contested era (D90)
  arms train against their own caps and the possession metric counts TD-ends as
  held, so pre/post-D90 possession is not comparable.
- **Curriculum ladder** (stage knob `--env.demo-endzone-maxdist`): 6 → 9 → 12 → 0
  ("uniform": any demo-bank start, no endzone filter) → kickoff starts
  (`--env.demo-reset-pct 0`). +3 squares per stage, never more (D51: 6→12
  overshot). Advance at tds plateau; warm-start each stage from the previous
  stage's highest-STEP ckpt.

## Hard-won facts (verified — don't relearn these)

### Obs / checkpoints / build
- **obs-v6 = 2782 bytes** (obs-v5 decision-window truth plus the ten
  addressable-but-invisible blind spots; spec `docs/obs-v6-spec.md`, audit
  `docs/plans/obs-v6-blind-spot-inventory.md`). v6 spends the scalar bytes
  `s[22..47]` (obs offsets 806–831) that v5 left permanently zero: the
  `CHOOSE_OPTION` candidate table, PUSH POW/FROM_BLITZ, the declared
  `bb_act_kind`, both casualty rolls, the turnover/kickoff-charge flags, the
  placement budgets, the stashed MOVE target and `ktm_used`; and it widens
  `ctx[9]/ctx[12]` from the Dodge destination to a general pending consequence
  square, and `ctx[8]` to the ACTIVATION gate target.
  **Three OBS_SIZE sync points must agree** (static asserts catch 2 of 3):
  `BBE_OBS_SIZE` in `puffer/bloodbowl/bloodbowl.h`, `#define OBS_SIZE` in
  `puffer/bloodbowl/binding.c:8`, `--obs-size` in
  `training/convert_checkpoint.py` (default 2782; v3 ckpts need
  `--obs-size 1612`). **Obs-v4 AND obs-v5 are ALSO 2782 bytes** with different
  semantics — blob size cannot distinguish any of the three, so only
  `BBE_OBS_VERSION` plus source/module provenance can. No v4/v5 warm-start,
  replay mixing, or direct curve comparison without a reviewed bridge. (A v4/v5
  mixup already wasted a 12B-step run; that is why v6 bumped the version and
  why `checkpoint_lineage.py` refuses a v5 sidecar outright.) **The v5 lineage
  is closed: D228's genesis root is out of lineage and obs-v6 needs a fresh
  `genesis` + `genesis-pool` on one build.** Obs-v3 and older checkpoints are
  input-shape **incompatible**.
- **Checkpoint lineage is external and mandatory.** A flat blob has no header;
  require its canonical `.lineage.json` from `tools/checkpoint_lineage.py`, which
  binds obs-v6/exact-joint-v1, policy shape, checkpoint hash, producer manifest,
  and source/module/Puffer patch hashes. This is what prevents warm-starting an
  obs-v6 run from an obs-v4/obs-v5 checkpoint; launchers reject missing or mismatched
  sidecars. Build pools with `tools/build_league.py`; `--legacy-unlabeled` is
  historical reconstruction only.
- **Probe the compiled module, not the source tree.** Before launching, record
  `_C.__file__`, `_C.env_name`, GPU flag, precision bytes, and the imported module
  hash, and confirm the imported `_C` really is obs-v6 / exact-joint-v1 / fp32. A
  source-tree hash does not prove which extension ran.
- **CUDA init order (D225).** Importing `_C` before the process's first CUDART
  call leaves a fresh WSL process at `cudaErrorNoDevice`; a successful CUDART
  probe *before* import preserves the device. `nvidia-smi`, Torch, or a probe in
  another process prove nothing about this process. Every worker and the actual
  Puffer trainer must go through `tools/puffer_cuda_runtime.py` in the same
  process: require `cudaSuccess` and a positive device count, retain the resolved
  CUDART handle, import `_C` or the CLI, then require the same count afterward.
  Record the CUDART path/hash, both probe records, and `CUDA_VISIBLE_DEVICES`.
- **Recurrent evaluation boundary contract.** `puffer_recurrent_eval_state.patch`
  applies after the exact-action patches. Graph warmup restores primary and every
  frozen-bank state to exact zero; train→eval starts fresh games and clears state
  once; nonterminal evaluation state persists across rollout calls; terminal rows
  clear before the next game's observation. Training requires `reset_state=True`
  with evaluation mode off (recomputation does not capture trajectory initial
  state). Use `cudagraphs=10`: `0` captures the first execution before CUDA lazy
  initialization and is invalid; `-1` is the explicit graph-off parity cell. Keep
  the captured reset row-sized, not hidden-state-sized.
- **CUDA/recurrent verification is fp32-only.** BF16 rounds stored behavior log
  probabilities, so no strict near-unity PPO-ratio claim survives it.
  `tools/qualify_recurrent_cuda.py` checks graph-on/off parity, primary/frozen
  post-terminal parity, exact-zero construction state, learner-row coverage with
  unchanged weight bytes, zero frozen-row selections even at `prio_alpha=0`
  (`puffer_frozen_prio_mask.patch` — zeroed advantages are not enough because
  `0^0 == 1`), the 16 hard counters at zero, and throughput against a
  same-host/config/precision baseline.
- **`puffer/bloodbowl/` is the SOURCE OF TRUTH; `vendor/PufferLib/ocean/bloodbowl/`
  is an installed snapshot** written by `tools/install_puffer_env.sh` — the build
  compiles the snapshot, NOT your edit. The snapshot can lag (the Mac checkout's
  may still say 1612). Drift guard: `tools/install_puffer_env.sh --check`
  (exit 1 = re-install). Run it before any build on a training box.
- After ANY env code change, ON THE TARGET: `bash tools/install_puffer_env.sh`
  (this also applies the whole Puffer patch stack),
  `bash tools/install_puffer_env.sh --check`, then
  `cd vendor/PufferLib && rm -rf build && ./build.sh bloodbowl --float` (torch
  needs `--float`; plain build = bf16 native CUDA). Never skip the install or the
  clean rebuild. Audit runs use `/home/rache/bloodbowl-rl-audit` on the Tailscale
  `wsl-ubuntu` host; `/home/rache/bloodbowl-rl` may serve production evaluation
  and must not be disturbed.
- **Reward experiment launch contract:** complete JSON manifests under
  `puffer/config/rewards/` plus `tools/run_reward_screen.sh`. Never launch a July
  reward arm through bare `run_synthesis_c.sh` — it carries inherited historical
  reward defaults.
- **BC corpus:** the historical 12,304 shards / 2,085,330 records are mixed
  edition at the raw-replay layer. The strict current training surface is 9,118
  non-empty BB2025 replay IDs / 1,622,231 records, selected from embedded
  `rulesVersion`; use `runs/replay-audit-20260713/bb2025-nonempty.ids` and the
  streaming loader.
- Warm relaunch: ANCHOR=newest ckpt, but **newest mtime ≠ highest step across run
  dirs** — check the step number embedded in the filename.
- **Exact joint sampling is the accepted action contract in BOTH backends
  (D218).** The env transports the current packed joint support; native/Torch
  sample type, then arg conditioned on type, then square conditioned on both. The
  selected 454-bit conditional masks are stored and reused by PPO. Inactive heads
  are singleton sentinels, so they contribute zero log-probability and entropy.
  `bbe_decode` rejects instead of repairing. Historical marginal-mask
  checkpoints/corpora are a distinct behavior lineage; new pairs are BBP v4.
- **Detection is fail-fast, not paperwork.** The engine aborts on the first
  decode/support violation (`bloodbowl.h:2796-2803`) — stronger than any
  end-of-run audit. On top of that, `illegal_frac` and the 16 hard-integrity
  counters are a live kill switch: `tools/live_integrity_guard.py` checks every
  machine panel incrementally, from both the screen and a watchdog embedded beside
  the detached trainer (independent state files), stops the trainer on any
  missing, malformed, non-finite, or nonzero hard field, and fails after 180s with
  no integrity-bearing panel (metadata-only startup panels don't reset that
  clock). Before a long post-v5 run: provenance, CUDA graph/zero-update checks,
  deterministic full games, then a disposable 50M reward-frozen canary — never
  continue from its checkpoint.

### Reward economy (July-audited interpretation)
- **Reward objective outcomes or decision quality, not lucky dice.** Realized
  injury, pickup, scatter, send-off, and similar shaping pays variance and is
  normally invalid. Where a tactical scaffold is justified, price the declared
  decision from pre-roll expected value (`bb_block_ev`) or a settled state. This
  is necessary but not sufficient: EV/state shaping can still redefine the policy
  objective and must pass held-out match-utility and transfer gates.
  Win/loss/draw and touchdowns are genuine objective outcomes. Possession,
  ball-gain/loss, distance, threat, contact, and similar dense terms are
  experimental shaping — not mini-terminals whose legitimacy can be assumed.
- Any term advertised as PBRS must use the discounted form
  `beta*(gamma*Phi(s')-Phi(s))`, telescope in tests, and handle terminals
  correctly; raw `Phi(s')-Phi(s)` is not exact at `gamma != 1`. Distance shaping
  is a scaffold for present learnability, not validated utility: make it
  discounted-exact, or demonstrate non-inferiority while annealing it away.
- R0's combined possession-annuity/ball-gain family survived scripted transfer,
  but the audit has not identified which component helps defense. Decompose it
  before retuning coefficients.
- The 28-channel emitted-reward ledger (D190, team-0/home perspective, pre-clamp
  raw reward) must reconcile: `sum(components) + residual` equals raw
  `episode_return`, and `episode_return - reward_clip_signed_delta` equals
  `reward_postclip_return`, within float tolerance. A nonzero clamp delta fails
  integrity on its own even when both identities hold. This is diagnostic
  attribution, not evidence that a shaping term is beneficial.
- Anti-farming invariants: no ball-loss double fine with the annuity, exact
  telescoping for any claimed potential, blitz exposure rush-gated, terminal
  emissions composed from explicit objective plus result rather than incidental
  same-action shaping, and no reward clipping or non-finite values. Human-looking
  statistics are canaries, not goals.

### Metric semantics
- `tds` from curriculum starts is **not comparable across maxdist stages**.
  `block_2dred_frac` and action rates are diagnostic canaries, not objectives.
- Corrected genuine-turn BB2025 human possession is `0.47394` turn-weighted
  (`0.47453` per-game mean); old `~0.15` values used different/poisoned semantics
  and must not be reused as a target.
- **Graduation rule (D50/D56):** kickoff-start tournament win-rate is the FINAL
  exam only; mid-curriculum tournaments draw 97–99% and that is EXPECTED. Draw
  rate rises with prior strength.
- **Tournament procedure** (runs on box-1's judge GPU): ship both ckpts to box-1
  box-to-box, convert BOTH sides — `python training/convert_checkpoint.py
  --to-cuda A.bin -o A_cuda.bin` (**mind `--obs-size`: 2782 default, 1612 for v3
  lineage**; conversion drops biases, so equal treatment of both sides matters,
  D45) — then `puffer match bloodbowl --load-model-path A_cuda.bin
  --load-enemy-model-path B_cuda.bin --num-games 4096`. Read the decisive-game
  split, not the draw rate.

### Compute and remote operations
- The old four-box Vast table is stale; discover live state rather than restarting
  old IDs. The current free lightweight target is the Tailscale `wsl-ubuntu`
  RTX 2070. Use the isolated audit checkout; keep the production
  checkout/process separate. Don't kill or replace an existing `server.py`
  evaluator unless asked.
- Before launching, record GPU/driver/CUDA/Python/Torch/compiler versions, free
  disk, imported `_C.__file__`, precision, and module hash.
- One trainer per host: the launchers hold an `flock` and refuse to overwrite
  existing run artifacts. Don't defeat either.
- For unattended multi-day work, `tools/experiment_queue.py` plus
  `training/systemd/experiment-queue@.service` runs an explicit JSON job list
  (schema in the module docstring). Its guards that have actually caught things:
  free disk/inodes, bounded runtime, mtime-based progress, GPU temperature,
  process-group cleanup, `flock`. Run queue-owned screens with `ARM_DETACH=0` and
  never add nested `setsid`/daemonization that lets the trainer escape the job's
  process group. Never change a production default from unattended evidence.
- **systemd units escape before Bash reaches them:** `$$` delivers a literal `$`
  and `%%` a literal `%`, so an intended `printf "%s"` must be written
  `printf "%%s"` in the unit. Bare `%s` is a systemd specifier. Prove
  empty/fixed/command-failure cases with a disposable unit first.
- BBTV on the 2070 follows the newest complete manifested reward-screen
  checkpoint against that run's frozen warm start. Use the isolated float viewer
  and reversible service override in `docs/bbtv-latest-checkpoint.md`; never
  rebuild the trainer's Puffer tree or read a checkpoint still being written. A
  CPU match child must load the separate CPU/fp32 `_C` —
  `CUDA_VISIBLE_DEVICES=` alone makes a GPU-built `_C` fail (D189).

### Engine / rules / oracles (stable since v1)
- PufferLib 4.0 (`vendor/PufferLib`, branch 4.0) uses `src/vecenv.h` macros — the online `env_binding.h` ABI is dead 3.0. `ocean/chess/` is the template; `ocean/convert/` is stale.
- Rules source: `docs/vendor/bloodbowlbase/` mirror (May 2026 FAQ, inline `<del>` errata — second sentence is current law). BB2025: 30 teams, Devious category, Elite Skills 0–4 cap. May 2026 errata removed the "D6 never below 1" floor. Team re-rolls UNLIMITED per turn (D15). Stalling (D193) and the PA-/No Ball surfaces (D198) are specified in `AGENTS.md`; the "forego one player but continue the turn" choice is not yet in the 454-way action interface. Keep rules legality in engine semantics, never duplicate it as a reward fine.
- FUMBBL replays: `game` = END-of-game snapshot; kickoff state from setup-phase `fieldModelSetPlayerCoordinate`; dice/decisions in `reportList.reports`. `vendor/ffb/.../PlayerState.java` is the authoritative bit table.
- Jervis: parallel bb2020/bb2025 suites (~174 files, diff for deltas); foul conversion broken (@Ignore). ActionCalculator (281 rows) defaults Season3=BB2025 — valid oracle odds. FFB headless needs MySQL ≤5.6/MariaDB ≤10.4; `gamestate/get` is the differential extraction point.

## Top footguns (each cost real hours)

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
12. **A run completes/dies but the box keeps billing — detect via LOG MTIME, not log content (D65).** A finished trainer leaves its log frozen at the final dashboard; any monitor that greps log *content* reports it "running" forever. Two flagship arms idle-billed 8–13h this way. ALWAYS gate liveness primarily on `stat -c %Y <log>` age (>360s stale = dead/done). A run hitting its STEPS cap exits cleanly (not a crash) — advance the ladder or reassign/stop the box.
    **The process-name half of this check was silently dead and is now fixed.** Since D225 the trainer runs in-process under the CUDA wrapper, so its argv is `python .../tools/puffer_cuda_runtime.py train bloodbowl ...`: comm is `python`, and the cmdline contains neither `puffer train` nor a process named `puffer`. So `pgrep -xc puffer` AND every `pgrep -f 'puffer [t]rain'` guard returned constant zero — measured against a live run at 67% GPU. That silently reduced double-launch protection to `flock` alone in six scripts. Use `pgrep -f '[p]uffer_cuda_runtime.py train|[p]uffer train'`, which matches both the wrapper and any legacy direct launch and brackets each alternative so a watcher carrying the pattern inline cannot match itself (footgun 3).
13. **`fleet.sh setup` clobbers a box's demo bank with the Mac's (D65).** The rsync excludes don't cover `validation/states/` or `resources/bloodbowl/`, so setup overwrites the box's `state_bank.bbs` with whatever the Mac repo holds. Keep the canonical (largest) bank in the Mac's `validation/states/bank.bbs` (gitignored) so syncs ship it; after any setup, re-check `Loaded N demo states` / bank byte-size on the box.
14. **`fleet.sh <cmd> <name>` exact-matches `bb-<name>` and SILENTLY no-ops on a miss (D65).** `bb-taiwan-anchor` ≠ `bb-taiwan` → `setup taiwan` prints "no running instance labeled bb-taiwan" and the sync never runs (the box stays on stale code, e.g. obs-v3). Always pass the exact label suffix (`taiwan-anchor`) and confirm the rsync/build actually ran.
15. **A reward field omitted from a launcher/config is not the same as explicit
    zero.** Use a complete canonical reward manifest and validate its SHA; never
    inherit old synthesis defaults into a causal arm.
16. **A final Steps line is not an accepted result.** Require explicit eval phase,
    the explicitly requested completed games, final cumulative reprint,
    checkpoint hash, and zero integrity counters. The acceptance floor must
    equal the request; exact completion is valid and cannot rely on vectorized
    overshoot. Use the screen/transfer analyzers.
17. **Directory names are not edition proof.** Filter replay IDs from embedded
    `rulesVersion`; never mix BB2020 into BB2025 because a shard happens to parse.
18. **Replay-first is not depth-balanced.** It removes long-replay dominance but
    the corpus remains opening-censored; stratify/cap before claiming late-game
    or rare-action competence.
19. **Do not touch the production checkout or evaluator while using the 2070 audit
    checkout.** Confirm paths and processes before sync, build, kill, or launch.
20. **Do not infer Stalling from distance alone.** Use
    `bb_can_score_without_dice` at activation start and preserve its exemptions;
    checking only the end position misclassifies Rush/Dodge/Trait paths, prior
    Turnovers, and successful possession transfers. Crowd and Steady Footing
    dice must remain in the engine RNG stream.

## Conventions

- Engine: C11, zero hot-loop allocation, every die through `bb_rng` (PCG-64 or injected script). Deterministic always.
- Every rulebook "may" is policy surface (D29); discovery-vs-artifact discriminator before patching weird behavior (D46); gradual anneal, never cold-off (D28); `make goldens` is explicit — rules fixes are EXPECTED to break goldens (D6).
- Reward claims require complete hash-checked manifests, paired seeds, held-out
  transfer, integrity gates, and a `DECISIONS.md` entry. Do not promote from
  attractive behavior or training metrics alone.
- Replay splits are replay-disjoint and edition-exact. Use bounded streaming;
  never restore eager all-corpus materialization.
- Vendored clones read-only, pinned in `vendor/PINS.md` (`tools/vendor_sync.sh`). Doc cache: `docs/SOURCES.md` / `tools/fetch_docs.sh`.
- Atomic commits, no attribution footers, `--no-gpg-sign` if Yubikey absent. No GW rulebook text or assets in the repo.
