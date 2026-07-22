---
name: training-experiments
description: Run and audit Blood Bowl RL experiments with immutable reward manifests, paired seeds, provenance/integrity gates, held-out transfer, checkpoint/build discipline, metric interpretation, opponent controls, and DECISIONS.md ledger updates. Use for any training run, reward ablation, A/B, checkpoint operation, evaluation, metric read, transfer study, or promotion verdict in this repo.
---

# training-experiments — running the RL program

You are continuing a long experiment program. Historical findings were paid for
with substantial compute, but later controlled evidence can amend them. **Do not
retune from aesthetics, training curves, or human-looking behavior. Change one
declared factor through a frozen experiment, validate on match utility and held-out
transfer, and write every accepted finding to `DECISIONS.md`.**

State as of 2026-07-14 (reward/replay audit active, ledger through D189).
Always read `AGENTS.md`, the tail of `DECISIONS.md`, and
`docs/reward-and-replay-audit-2026-07-09.md` first. Newer ledger entries and
immutable result artifacts supersede older sections of this skill.

---

## 0. July 2026 reward verdict and next experiment

No reward has been promoted to production.

- The repaired R0–R3 2×2 completed all eight paired arms at exact
  `249,954,304` native steps with two seeds, ≥10,001 final eval games/arm,
  identical frozen provenance, and zero integrity counters. Distance supplied
  nearly all scoring learnability: TD/game `+0.76365`, match score `+0.11130`,
  ball-forward `+4.45069`. It also increased block volume and 2D-red rate.
- The R0/R2 transfer matrix completed 16 cells and 16,076 full games. Removing
  possession+gain (R2) reduced match score in all eight matched cells and raised
  losses and opponent TDs in all eight. R2 is not transfer-noninferior.
- Keep R0 only as the next experimental baseline. Raw distance `ΔΦ` is a
  temporary scaffold, not exact PBRS at `gamma=0.995` and not final utility.
- Next screen, with distance on in every arm:

  | Arm | Possession annuity | Ball-gain event |
  |---|---:|---:|
  | P0 | on | on |
  | P1 | on | off |
  | P2 | off | on |
  | P3 | off | off |

  Run `500M × 2 seeds`; then confirm R0 against the simplest
  transfer-noninferior survivor with learned opponents, roster macro, longer
  horizon, and a second ancestry. Do not change production defaults before all
  gates pass.
- The July 13–14 attempt completed all arms but is rejected under D182. One
  training emission exceeded the PPO clamp by exactly `0.015`; the retained
  schema cannot identify its sign or terminal context. The audit separately
  confirmed an unsafe result-plus-incidental-shaping terminal path. It has no
  completion proof and cannot feed transfer. Correct and review terminal
  composition, add terminal/non-terminal recurrence telemetry, then rerun every
  arm under one uniform semantic contract.

Canonical evidence:

- `runs/reward-screens/reward-screen-20260709-v1/SCREEN_COMPLETE.json`
- `runs/reward-transfer-20260713-v1/ANALYSIS.json`
- `docs/reward-and-replay-audit-2026-07-09.md`

### Immutable experiment contract

Use `tools/reward_manifest.py`, `tools/run_reward_screen.sh`,
`tools/analyze_reward_screen.py`, and `tools/analyze_reward_transfer.py` for the
audited workflow.

For every causal arm:

1. Freeze source, installed env/config, imported module, Puffer patches, warm
   checkpoint, pool, backend, optimizer, seeds, execution order, and eval policy.
2. Supply a complete reward JSON; omitted and explicit-zero fields are different.
3. Record all hashes and persist immutable plan/status/result/completion records.
4. Require explicit phase telemetry, the requested complete kickoff games, a
   final cumulative reprint, and zero clip/non-finite/engine-error/demo/fallback
   counts. Keep the acceptance floor equal to the explicit evaluation request;
   exact completion is valid and must not rely on vectorized overshoot.
5. Reject integrity failures rather than averaging them into the comparison.
6. Report W/D/L, TD for/against, both sides, paired common-seed differences, and
   in-sample versus held-out results separately.
7. Treat two-seed/scripted-bot screens as descriptive, never as confidence
   intervals, tournament-strength claims, or production promotion.
8. On an episode-ending step, emit only explicit current-step objective reward
   (TD), result utility, and separately declared episode-terminal terms. Never
   let incidental action/board shaping co-stack invisibly with the result.

---

## 1. Compute targets

**The table below is June historical context, not live inventory.** The paid Vast
fleet was stopped after D176. Discover external state before any action; do not
restart old instance IDs from documentation. The current free lightweight target
is the Tailscale `wsl-ubuntu` RTX 2070. July audit work used the isolated checkout
`/home/rache/bloodbowl-rl-audit`; `/home/rache/bloodbowl-rl` may host the production
evaluator/stream and is out of scope unless the user explicitly authorizes changes.

For any remote run, first record `tailscale status`, live processes, free disk,
GPU/driver/CUDA, Python/Torch/compiler, checkout path, Git/worktree state,
`_C.__file__`, `_C.env_name`, GPU flag, precision, and module SHA. Do not kill or
replace an existing `server.py` process as part of training work.

If Vast is intentionally reactivated, use `.claude/skills/fleet-ops/SKILL.md`
and live `vastai show instances --raw`; do not copy old IDs or endpoints from
the ledger. Use `ssh -n` plus timeouts in monitors, preserve cached replays and
checkpoints, and remember that stopped instances can be reclaimed.

---

## 2. Current era: v5

- **obs-v5 = 2782 bytes** — the obs-v4 probability planes plus observable block
  faces and decision-window movement, rush, TEST, ball-validity, and touchback
  state. Spec: `docs/obs-v5-spec.md`. Obs-v4 is also 2782 bytes, so tensor shape
  cannot identify or validate the semantic lineage.
- There is **no accepted obs-v5 BC anchor yet**. Historical
  **`training/bc_v4.bin`** (val exact 0.508, D53) and the 2.09M v4 pairs under
  `validation/pairs_v4` remain valid only in an explicitly pinned obs-v4 runtime.
  Never warm-start or evaluate them under the current v5 runtime merely because
  the shape loads. New exact-action obs-v5 exports use BBP v4; current BC/action
  training rejects BBP v1-v3 even though the tensor dimensions still match.
- **OBS SIZE SYNC POINTS — all three must agree:**
  1. `BBE_OBS_SIZE` in `puffer/bloodbowl/bloodbowl.h` (~line 96)
  2. `#define OBS_SIZE` in `puffer/bloodbowl/binding.c` line 8
  3. `--obs-size` in `training/convert_checkpoint.py` (`DEFAULT_OBS_SIZE`, now 2782)
  A `_Static_assert` ties (1)↔(2) at build time; **(3) is the unguarded one** — a
  wrong `--obs-size` converts to silent garbage (this exact miss bit D54).
- **Old obs-v3 lineage checkpoints are input-shape INCOMPATIBLE** with v4/v5.
  Converting a v3 checkpoint requires explicit `--obs-size 1612`. Obs-v4 and
  obs-v5 are instead same-shape but semantically incompatible. Flat checkpoints
  do not carry an observation-lineage header, so require a pinned source/module
  identity and external manifest; never infer compatibility from dimensions.
- Current checkpoints require the canonical adjacent `.lineage.json` produced
  and validated by `tools/checkpoint_lineage.py`. It binds the checkpoint hash,
  obs-v5/exact-joint-v1 ABI, policy shape, producer manifest, source/module/
  Puffer patch identities, and ancestry eligibility. Missing, mismatched, or
  qualification-only sidecars are not accepted warm starts or pool seeds.
  `tools/build_league.py` requires and copies eligible lineage by default;
  `--legacy-unlabeled` is for historical reconstruction only.
- The `exact-action-canary` is a fixed fresh-initialization qualification run.
  Launch it with both `WARM` and `POOL` absent (use `env -u WARM -u POOL` when
  the shell may inherit them). It uses zero frozen banks, and its output is
  permanently marked qualification-only; do not continue from it.
- The frozen screen launcher creates `$OUT_DIR/.screen.lock` before manifest
  freezing and retains the inode as its one-screen ownership surface. A canary
  plan-only output must contain exactly two regular files:
  `SCREEN_MANIFEST.json` and a zero-byte `.screen.lock`. Hash both and their
  modes/sizes, and require a successful nonblocking `flock` after the plan
  process exits. Never remove the lock to force one-file closure; missing,
  nonempty, held, or additional output rejects that canary identity.
- For a systemd-wrapped experiment, freeze the systemd-to-Bash escape boundary:
  `$$` in unit bytes delivers literal `$`, and `%%` delivers literal `%`.
  Therefore `printf "%s"` must be authored as `printf "%%s"` in the unit.
  Bare `%s` expands to the user shell. Run disposable empty-output,
  fixed-output, and command-failure units before installing the real unit.
- The recurrent runtime is part of the frozen implementation identity. Before
  the exact-action canary, a fresh isolated build must prove zero primary and
  frozen state after CUDA graph warmup, graph-on/off deterministic active-row output
  parity, fresh train→eval game boundaries, primary/frozen post-terminal parity,
  Torch/native parity, finite exact zero-update ratios, and target-GPU
  throughput without material regression. Every graph-enabled qualification
  cell uses `cudagraphs=10`, matching the frozen Puffer/canary warmup boundary;
  `0` is rejected because it captures the first execution, and `-1` is reserved
  for the explicit graph-off parity cell. Training requires
  `reset_state=True`; direct training while evaluation mode is active fails.
  Do not infer these guarantees from patch markers or CPU tests. Use the
  post-boundary fp32 `tools/qualify_recurrent_cuda.py` gate with a predeclared
  candidate source commit plus module/backend/environment hashes and an
  immutable same-host/config/precision throughput artifact captured from the immediately
  preceding exact-action runtime. That predecessor is a fresh isolated fp32
  build at exact commit `afc8008933548438ca93c41341f5f08fdd294386`, created
  only after atomic recovery completion and required to expose obs-v5,
  exact-joint-v1, matching compiled hashes, and no qualification bindings. The
  former exact candidate `a52fc6e2f4ece5a7ff16bb4791e3aca4dd72f2e3`
  used a different isolated source checkout and Puffer tree but is permanently
  rejected under D223. A clean merged schema-3 control-runner checkout records
  and revalidates both full commits,
  source-local Puffer paths, installer checks, and runtime hashes. The occupied
  marginal-action recovery runtime is historical evidence, not the
  predecessor; never modify or reuse the recovery Puffer tree. The gate must cover every
  learner row through the reported sampled indices, prove byte-identical
  weights at learning rate zero,
  bind all 16 hard-integrity counters at literal zero in every
  transition-executing cell (construction emits no episode telemetry), and
  accept all mandatory gates before the 50M canary. The ratio gate must use
  a real frozen bank and select zero frozen rows, including at `prio_alpha=0`.
  BF16 is not accepted because stored behavior-log-probability quantization can
  move an unchanged recomputation ratio beyond a strict near-unity budget.
  The first schema-3 predecessor capture is rejected and non-retryable because
  its immutable native digest used the historical backend registry while the
  runner recomputed the expanded registry. D224 records the role-correct
  compiled-source digest separately from a complete runtime-source digest.
  The latter always includes `pufferlib/selfplay.py` for both roles and must be
  predeclared for the predecessor and revalidated from disk. Preserve the
  predecessor's upstream/unpatched self-play file; only the candidate receives
  the league patch. Never rebuild the predecessor to retrofit a newer
  digest and never reuse the rejected output directory.
  The later `predecessor-throughput-v2` and `predecessor-throughput-v3`
  captures are likewise rejected before a transition and non-retryable. Their
  common failure is process-local CUDA initialization order, not an absent
  host GPU: importing `_C` first made that fresh WSL process report
  `cudaErrorNoDevice`, while initializing CUDART before `_C` preserved the
  device. Never use a different process's `nvidia-smi`, Torch, or CUDART result
  as worker evidence, and do not attempt a third unchanged capture. Both the
  qualification worker and actual Puffer trainer must enter through
  `tools/puffer_cuda_runtime.py`, require a successful positive device count
  before native import and the same result afterward through the retained
  resolved CUDART handle, and bind the wrapper, runtime path/hash, both probes,
  and `CUDA_VISIBLE_DEVICES` into provenance. Throughput roles must match the
  runtime hash/count. A failure exits the fresh process without repair. Before
  recapturing throughput, merge/review the contract, create fresh clean
  control/candidate roots, and pass one construction-only target check. The
  screen launcher remains frozen and cannot launch a replacement until a
  separate post-qualification authorization binds the wrapper and evidence.
  Both predecessor timing and full qualification require the same
  `--construction-gate` and revalidate/bind its current path, hash, candidate
  module/backend/environment, runner, and CUDART identity before output or
  worker dispatch.
  The timed predecessor worker must also receive every frozen predecessor
  identity field and reject a mismatch in its own process after native import
  but before backend construction, warmup, or rollout. Do not rely on a
  parent-only comparison after timing has already spent the capture identity.
  For an actual trainer, distinguish the launcher probe from
  runtime proof: the wrapper must explicitly import `_C`, publish its complete
  same-process pre/post evidence before optimization, require it to match the
  pending manifest expectation, and preserve the finalized manifest plus
  hash-bound evidence with checkpoints.
  The throughput predecessor must be its exact hashed wrapper and confined cell,
  with module/backend/runtime/environment hashes declared both when captured
  and when consumed, not a loose metrics dictionary or an unplanned old binary. Missing baseline,
  coverage, bank/buffer, tensor, or hard-integrity evidence fails closed.
  The clean merged control launcher must reject `exact-action-canary` before
  creating output. Never launch through the rejected `a52fc6e2` checkout;
  independently analyze its stopped artifact from the merged control. Only a
  separate reviewed post-qualification change may authorize a replacement.

---

## 3. Launch contracts

### Audited reward screens and transfer

Use complete reward manifests under `puffer/config/rewards/` and the immutable
workflow in §0. Do not reconstruct a July arm from a dashboard command and do not
send it through bare `run_synthesis_c.sh`: historical launcher defaults are not a
complete manifest and can silently inject old shaping. Preserve plan, per-arm
status/result JSON, completion proof, final checkpoint, and analyzer output.

### Historical curriculum/lineage launcher

`tools/run_synthesis_c.sh` has frozen v3 reward defaults, including the poisoned
ball-loss profile. It is allowed only for exact historical continuation with a
complete explicit override recovered from the original profile. Never use it
for a new reward comparison. `ANCHOR`, `LOG`, and `STEPS` are historical env-var
controls; choose a checkpoint by embedded step and hash, not mtime.

**After ANY env code change, do ALL of, in order.** Source of truth is
`puffer/bloodbowl/` (its `engine/`+`bb/` symlinks pull in `engine/src` +
`engine/include`); the build compiles the INSTALLED snapshot under
`vendor/PufferLib/pufferlib/ocean/bloodbowl/`, so an edit without re-install
silently trains on stale rules:

```bash
bash tools/install_puffer_env.sh          # --check = drift guard, run it when unsure
cd vendor/PufferLib && rm -rf build && ./build.sh bloodbowl --float
```

- `--float` is REQUIRED for the torch backend. Plain build = bf16, native CUDA only
  (that is the build `puffer match` needs — see §9).
- **NEVER skip `rm -rf build`** — stale objects bite (footgun 4).
- Sync `engine/` AND `puffer/bloodbowl/` **together**; a header without its
  `binding.c` builds a stale mixture (this hid the tier-distribution exports once,
  D49). After syncing to a box, `grep` the changed symbol on the box to prove the
  right code landed, then re-run install + rebuild ON THE BOX.

Verify every launch from process state, fresh logs, manifest/status records, and
the imported module. Do not trust a historical "LIVE" banner alone.

---

## 4. Reward economy (audited experimental baseline, not settled utility)

The canonical R0 values live in `puffer/config/rewards/r0_full.json`; do not
retype or partially override them. Important current values are terminal TD
`0.4`, win/loss `±0.6`, draw `0`; possession `0.03`, gain `0.05`, loss `0`;
distance-to-ball/endzone `0.02/0.04`; block terms
`k_kd/k_value/k_ball/k_turnover/k_seq = 0.10/0.50/0.15/0.15/0.03`; rush cost
`0.015`; other shaping zero. These define an **experimental control**, not a
recommended final objective and not a bit-identical historical continuation.

Interpretation after D177–D178:

- Distance supplies most learnability. Keep it during decomposition, but call it
  a scaffold. Raw state delta is not exact discounted PBRS.
- Possession+gain has a small screen effect but a consistent defensive transfer
  benefit. Keep the bundle only until the next screen isolates its components.
- Rush and block terms remain scaffolds. Higher block count is not a promotion
  criterion; R2 blocked more and lost more in transfer.
- Stalling is not an automatically accepted side effect. BB2025 explicitly
  penalizes a carrier who could score without dice; evaluate possession rewards
  against score/clock behavior and held-out match utility.

**Invariants for every reward variation:**

1. Use a complete canonical manifest; never inherit an omitted field.
2. Keep `ball_loss = 0` while the possession annuity is on; no double fine.
3. Any term called a potential must use the exact discounted form
   `beta*(gamma*Phi(s') - Phi(s))`, or be labeled a non-invariant scaffold.
4. Rush-gate blitz exposure and include rush-failure turnover probability.
5. Record and reject reward clipping or non-finite values.
6. Do not reward realized dice outcomes as shaping. Event/EV terms can still
   redefine utility and require held-out match validation.
7. Do not promote from human-stat proximity, TDs alone, or training-opponent
   success. Require W/D/L and TD for/against on held-out opponents.
8. Keep terminal match utility authoritative: incidental shaping on the action
   that ends an episode must not share the terminal result emission.

---

## 5. Historical curriculum ladder

The old Backplay ladder was `maxdist 6 → 9 → 12 → uniform → kickoff`,
advancing in three-square increments with retention probes. It remains useful
historical context, but July causal reward comparisons use full kickoff starts
(`demo_reset_pct=0`). Never compare curriculum TD rates across start depths.

---

## 6. Standing doctrines — IMPERATIVE form

These are laws, not suggestions. Each one was bought with a failed run.

### D46 — Discovery vs artifact (the 3-part grounding test)

- **NEVER patch out an inhuman behavior because it "looks absurd."** Aesthetics is
  not a filter (TD-Gammon's doubles, AlphaStar's worker saturation).
- Before patching ANY weird behavior, run all three:
  1. **Grounding:** does it persist when wins/TDs vs a competent opponent are the
     binding currency, not shaped income?
  2. **Routing:** is its profit causally routed THROUGH the objective, or around it?
  3. **Human rates are evidence, not law.** A 10× human rate is a flag, never a verdict.
- The verdict belongs to the **tournament**, not your taste. GFI-spam is the case
  study: presumed artifact (routed around the objective), still adjudicated by A/B —
  if the untaxed twin keeps high GFI AND wins, absurd is correct and the tax dies.
- Treat `reward_rush_cost` as **anti-degeneracy scaffolding** (k-knob category, to be
  annealed away). NEVER describe or use it as a permanent value statement.
- Remember the unifying diagnosis: ball-avoidance, scrum-hovering, and GFI-spam are
  ONE disease — positional value is denominated in points and there are no points.
  The cure is a working scoring economy, not taxes. (True GFI price is positional:
  prone players project no tackle zones; standing presence protects BOTH sides.)
  Testable prediction on file: GFI discipline emerges FIRST on the carrying team.

### D50 + D56 — Graduation rule

- **Run the grounded win-rate exam (4096 full games from kickoff vs a frozen
  reference) ONLY as the FINAL-stage graduation test.**
- **NEVER read a mid-curriculum tournament draw rate as failure.** Mid-curriculum
  tournaments draw 97–99% — that is EXPECTED. They are calibrations, not verdicts.
- Training-tds ≠ winning until starts reach kickoff: endgame skill exists but is
  unreachable from the opening whistle until backward expansion connects them.
- D56 nuance: draw rate RISES with prior strength (96.8% → 98.8% v3→v4) because
  stronger mirror priors mean fewer accident-decided games. The bar rises with the
  player — do not panic at a higher draw rate from a stronger anchor.

### D33/D34/D36 — Decision-time exposure pricing (Profile C)

- Exposure-EV transfer pricing (`bb_blockev` closed forms; the k knobs; spec in
  `docs/reward-audit-decision-time.md` Addendum 3) is the **ONLY mechanism known to
  create contact-seeking**. Do not substitute shaped rewards: shaped/anchored
  lineages collapse contact to zero (PPO descends the "random contact is net
  self-harm" gradient — D33, scope includes contact-PLUS-movement risk);
  unshaped-from-scratch stays at random (D34 control). Only Profile C gives ~2×
  random volume at ~2× per-declaration conversion.
- **ALWAYS rush-gate blitz exposure** (D36).
- Exposure knob magnitude moves the brawl pole, NOT scoring (D40/D41). Don't crank
  it hoping for TDs.
- Use `blocks_thrown` (one CHOOSE_DIE per resolved block) as the clean conversion
  denominator (D36/D34-AMENDED).

### D42/D43 — Anti-farming invariants

See §4. Check the invariants before every reward-config launch. No exceptions.

### D28 + D26 — Gradual anneal

- **NEVER cold-off a scaffold knob.** Halve per chained stage. Cold anneal decays
  scoring back to zero (D26: the D2 arm was dead by 5.4B steps).
- Applies to exposure knobs too (D41 chain). But note D49: exposure-anneal alone
  never produced scoring — annealing is how you REMOVE scaffolding, not how you
  create capability.

### D29 — Every "may" is policy surface

- **NEVER auto-resolve a rulebook optional choice.** Auto-policies delete tactics
  (the Wrestle counterexample reversed D9). All optional choices are
  USE_SKILL/DECLINE_SKILL or CHOOSE_OPTION windows. The probability engine resolves
  choice nodes owner-optimally; FUMBBL skillUse reports validate via lockstep AND
  feed BC pairs.

### D38 — Masked-sampler law

- The torch backend **MUST** apply per-head action masks (`masked_fill(-inf)`)
  before rollout sampling, store masks in experience, and re-apply at train-time
  recompute. The viewer inherits the same patch.
- **NEVER cite tds-emergence intuitions from pre-fix torch runs** (the unmasked era
  had `illegal_frac 1.000` and a decode-fallback shadow policy — all its measured
  dynamics are invalid). CUDA-backend results (D26–D28, D34) are unaffected.

### D218 — Exact sampled/executed action law

- Per-head marginal masks are historical and insufficient for Blood Bowl.
  Accepted native and Torch runs must consume packed joint support, sample
  sequential conditional heads, store the selected conditional masks, and
  require `illegal_frac == 0`.
- `bbe_decode` is a fail-closed assertion boundary, not a repair policy. Any
  decoder rejection, empty conditional head, missing exact-backend installer
  marker, or non-unit zero-update PPO ratio invalidates the run.
- BBP v4 is required for newly extracted action/BC pairs. v1-v3 pairs retain
  historical marginal/inactive-head semantics and cannot enter an exact-action
  training corpus by shape compatibility alone.

### D219 — Zero-contamination fail-fast error budget

- Zero accepted violations does not permit an unbounded late rejection. Current
  reward screens must freeze and run `tools/live_integrity_guard.py`, include
  `illegal_frac` in the same hard registry as reward/non-finite/error counters,
  terminate the recorded trainer on the first bad complete panel, and fail after
  180 seconds without an integrity-bearing machine panel. The same watchdog must
  live beside a detached trainer so outer-screen loss cannot remove the bound;
  the screen and watchdog use independent incremental state files, and metadata-only
  startup panels do not reset liveness. The exact env/backend remains
  first-transition fatal. Qualify a newly installed runtime through static
  provenance, CUDA graph/zero-update/deterministic smokes, and a disposable
  50M-step canary before launching the paired causal screen; never warm-start
  from or analyze the canary as a result cell.
- Apply the 180-second silence gate only while the trainer is live. Recovery and
  final validation must use complete-log mode: rescan all remaining bytes and
  enforce the same exact-zero registry without falsely aging a stopped log into
  a liveness failure. Terminate the trainer before publishing failure status so
  status I/O cannot delay containment.
- The archived candidate `a52fc6e2` froze an 11-key live registry. Preserve it
  only as rejected evidence; never launch, relabel, or reuse it. Require the
  merged control qualification and
  independent stopped canary validation to enforce five additional emitted
  redundancy counters at exact zero: signed clamp delta, clipped samples,
  terminal and non-terminal clipped samples, and non-finite samples per episode.
  Primary zero ratios should imply them; a disagreement is still invalid
  evidence. Freeze both registries rather than changing or relabeling the
  candidate.
- The sole `a52fc6e2` canary start is rejected, stopped, and non-retryable: its
  final preflight caught the existing `training/selfplay_league.patch` missing
  from vendored `selfplay.py` before GPU work. Qualification schema 3 makes the
  replacement candidate and control runner use the same operator-predeclared
  merged commit in different isolated source checkouts and rejects a value
  unequal to the control runner's clean `HEAD`. It binds that patch file, hashes patched
  `selfplay.py` into backend identity, and requires full reverse applicability.
  Recapture the predecessor
  at `afc8008933548438ca93c41341f5f08fdd294386` with the schema-3 runner, create
  entirely fresh runtime/qualification/unit/output/authorization identities,
  and never modify or reuse the recovery Puffer tree. Keep the replacement
  canary frozen until qualification accepts, then authorize its exact commit in
  a separate reviewed change.

### D174/D176 — Current BC and opponent verdicts

- D174 supersedes the old "sequence context first" ranking: frame-stacked
  structural context was null because obs-v4 already encodes within-turn state;
  last-action history added only `+0.002`, inside noise. Do not fund recurrence
  without full-game lockstep data and a new falsifiable hypothesis.
- D176 supersedes the old blanket "BC anchor prevents erosion" recommendation:
  full-strength persistent iid CE mechanically held BC accuracy but collapsed
  offense. Do not reintroduce it as the default and do not infer that a weaker
  coefficient must help.
- Competent opponent quality produced the strongest defensive improvement, but a
  single deterministic bot is an overfit probe. Prioritize diverse opponents and
  held-out transfer over more corpus volume or stronger iid anchoring.

### D35 — Optimization-bound before capacity claims

- **NEVER declare a BC model "capacity-bound" from val≈train alone.** Verify with
  extended cosine-decay steps first (bc_v3b gained +1.1pp val that the
  capacity-bound reading said couldn't exist).

### Misc standing rules

- D6: `make goldens` is explicit; rules fixes are EXPECTED to break goldens.
- D15: BB2025 team re-rolls are UNLIMITED per turn and replenish at half-time;
  skill re-rolls once per turn per player.
- D25: setup is reserves-first, budget 24 (amends D1's 64+autofix).
- D16-AMENDED (D36): check Claws BEFORE Mighty Blow; a Claws break leaves MB for
  the injury roll.
- D42 (same entry as the laundering invariant): filter boxes by
  cores_effective × clock (766K SPS on 64c/3.4GHz = 7× box-2); cores_effective is
  the CONTAINER allocation, not the host's.
- D44: the spectator event feed is POD-only cross-thread (see footgun 7).
- D31: `bb_match.fan_factor[2]` changed `engine_fp` — regenerate the demo-state
  bank on ANY engine_fp change.

---

## 7. DECISIONS.md ledger discipline

The ledger is at `DECISIONS.md` (through D189 as of 2026-07-14). It is the
program's chronological memory. D177–D189 cover the reward screen, transfer,
replay corpus, streaming loader, rejected partial-deployment run, corrected
confirmation, fail-closed vacation routes, and frozen 6B learning-curve verdict
that supersede this skill's June snapshots.

- **EVERY finding gets an atomic entry. No exceptions.** One decision/finding per
  entry, numbered D{n+1}, dated. If your write-up needs "and" between two findings,
  split into two entries.
- Write the entry **when the finding lands**, not at end of session. Sessions die;
  the ledger survives.
- Each entry records: what was run (boxes, configs, checkpoints, steps), what was
  measured (with numbers), the verdict, and what it amends or supersedes (cite the
  prior D-number explicitly, e.g. "amends D33").
- **NEVER act on an experimental verdict you haven't written down.** Ledger first,
  then change the default.
- Amendments never delete: D9 was reversed by D29, D33 was scope-corrected — the
  history is the value. Append, cross-reference, never rewrite old entries.

---

## 8. Metric semantics — what the dashboard numbers mean

| Metric | Reference values | How to read it |
|---|---|---|
| `tds` | stage-dependent | Per-episode touchdowns **FROM CURRICULUM STARTS**. NOT comparable across maxdist stages — a drop on stage advance is expected, not regression. |
| `block_2dred_frac` | human 0.017; v3 agent plateau ~0.20; v4 0.169 falling | Fraction of blocks thrown at 2-dice-against. **Falling = probability planes working.** |
| 2d : 2dred ratio | human 46:1 | Same axis as above. |
| `possession_rate` | corrected BB2025 human genuine-turn rate 0.47394; per-game mean 0.47453 | Metric semantics changed historically. Never compare old ~0.15 dashboard values or synthetic turns directly to the corrected baseline; use it as a diagnostic, not a target. |
| `gfi` (go-for-its) | human ~2–5/ep; agent ~25–35 | Presumed ARTIFACT per D46 unless it survives grounding. Track it; do not patch it outside the rush-tax A/B. |
| `bc_acc` | v4 ceiling ~0.51 (runs hold 0.49–0.55) | Anchor agreement. Don't expect above ceiling; collapse far below it = erosion. |
| `blocks_thrown` | — | Clean denominator for contact conversion (one CHOOSE_DIE per resolved block). |
| `illegal_frac` | must be ~0 | If ≈1.000 the masked sampler is broken (D38). Stop and fix before trusting anything. |
| Tournament draw rate | 96.8% (v3) → 98.8% (v4) mirrors | RISES with prior strength (D56). Mid-curriculum 97–99% is expected. |
| SPS | torch ~0.6–0.77M; native 2.1M on 24c (D57); 766K = v3-era 64c reference | Box-throughput sanity check; box-2 is ~1/7 of the 64c boxes. |

---

## 9. Tournament procedure

For July reward selection, first run the immutable final-policy evaluation and
held-out transfer matrix described in §0. `puffer match` remains useful for
checkpoint head-to-heads, but it is not a substitute for both sides, TD
for/against, scripted/learned opponent diversity, roster macro, provenance, or
integrity telemetry. Native↔Torch conversion zero-fills/drops biases; document
and apply conversions symmetrically.

1. Ship both checkpoints to **box-1** (judge GPU). Box-to-box via `ssh -A`, never
   Mac→ssh4 for big files.
2. Convert: `python training/convert_checkpoint.py --to-cuda <torch.bin> -o <out>`
   — **mind `--obs-size`** (2782 default = current v5; v3 ckpts need explicit
   `--obs-size 1612`). A 2782-byte v4 checkpoint is still semantically invalid in
   v5 despite matching the default. Wrong size or lineage = silent garbage;
   dimensions alone do not check it for you (§2).
3. Run on box-1 from `/root/bloodbowl-rl/vendor/PufferLib`:
   ```bash
   puffer match bloodbowl --load-model-path A_cuda.bin \
     --load-enemy-model-path B_cuda.bin --num-games 4096
   ```
   `match()` **hard-errors unless the NATIVE CUDA backend is loaded** ("match()
   requires the native CUDA backend") — a `--float` torch build cannot serve it;
   box-1 keeps a native build for judging. A = slot 0, B = slot 1.
4. The result line is `games=4096/4096 A=x B=y draw=z`. If games < 4096, the run
   died — investigate, don't extrapolate.
5. Interpret per D50/D56 (§6): final-stage exam vs mid-curriculum calibration are
   different instruments.

---

## 10. Footguns (each one cost real hours — obey)

1. **Python `str.replace` silently no-ops on anchor mismatch.** ALWAYS `grep` the
   file after any scripted edit to prove the change landed.
2. **zsh does NOT word-split unquoted vars** — `set -- $hp` fails. Use arrays or
   explicit splitting.
3. **`pkill -f` matches its own watcher commands.** Use `[b]racket` patterns:
   `pkill -f '[r]un_synthesis'`.
4. **Partial code syncs build stale mixtures, and the build compiles the INSTALLED
   snapshot, not your edits.** Sync `engine/` AND `puffer/bloodbowl/` together;
   re-run `tools/install_puffer_env.sh` (use `--check` as the drift guard) +
   `rm -rf build` + rebuild on the box; verify with `grep` on the box.
5. **Vast stopped instances can be RECLAIMED.** Restart promptly or accept a
   replacement (new id, new ssh endpoint). Box-1 holds the SOLE replay-cache copy —
   treat it accordingly.
6. The balance ladder (`/tmp/vast_ladder.sh`) stops boxes in value order below
   $5/$3.5/$2 credit. Stop-only, reversible — but see footgun 5. It lives in Mac
   `/tmp`, which a reboot wipes.
7. **Memorial/feed render hooks: NEVER format strings or do I/O from env-stepping
   threads.** POD staging slot + render-thread consumer. Two SIGSEGVs taught this.
8. **raylib `InitWindow` segfaults when the Mac display is asleep.** `spectate.sh`
   gates on display-awake — keep that gate.
9. **Monitor/SSH loops need `ssh -n` and `ConnectTimeout`** or they hang forever.
10. (Launcher) Asymmetric step-cap overshoot ~1.5× is known and benign (§3).
11. **`vastai` CLI < 1.0 (brew 0.4) creates zombie instances.** Check the version
    before provisioning.

---

## 11. Open experiment queue — PRIORITY ORDER

Work the queue top-down. Do not reorder without writing a ledger entry justifying it.

1. **Decompose R0's bundled possession family with distance fixed on:** both,
   possession-only, gain-only, neither; `500M × 2 seeds`, same frozen contract
   as D177. R2 is prior evidence for neither, not permission to skip a fresh
   matched cell.
2. **Confirm R0 against the simplest transfer-noninferior survivor:**
   `1B × 2 seeds`, learned-opponent transfer, both sides, roster-grid macro,
   TD for/against, and uncertainty. Reject any simplification that repeats R2's
   defense loss.
3. **Separate opponent curriculum from reward:** freeze the selected reward and
   compare diverse competent opponents. D176 shows opponent quality can dominate
   apparent defense improvements; a single deterministic bot is an overfit probe.
4. **Make distance policy-safer:** replace raw delta with exact discounted PBRS,
   or anneal it to zero and demonstrate non-inferiority against objective-only.
5. **Ablate rush and remaining block scaffolds one family at a time.** More blocks
   or more human-looking rates are not benefits unless held-out match utility
   improves.
6. **Reproduce the finalist from a second ancestry** (initial candidate:
   league9), then run the final long matched control. Only this stage can
   authorize a production default change.
7. **Improve replay sampling:** edition-exact, replay-disjoint, hierarchical
   depth/action/roster sampling with setup caps and grouped metrics; build
   replay-derived scenarios only after full-game lockstep coverage is verified.

### Background threads (not queue items, but don't lose them)

- The strict BB2025 replay corpus is opening-censored and nearly lacks pass,
  handoff, foul, Jump, TTM, and Special targets. Do not claim rare-action or
  late-game learning from aggregate BC accuracy.
- Recurrent sequence training remains contingent on full-game lockstep conversion;
  frame-stacked context was null in D174.
- Asymmetric-stop overshoot remains low priority while bounded and manifested.
- FUMBBL differential adjudications pending: D11 crowd-push dice order; D13
  Secure-the-Ball bounce+turnover; D18 Break Tackle always-on + Secret Weapon
  approximation; D21 Saboteur auto-KO; D36 documented engine-parity divergences
  (Frenzy-vs-Steady-Footing missing second block ≤5.6% pool mass; Dump-Off dead
  once-latch); D9-class auto-policy declines generally.
- Phase-3 rule TODOs: D4 kickoff events (7 of 11 no-ops; D31 landed Solid
  Defence/Quick Snap/Charge windows); D21 deferred Multiple Block + Pile Driver,
  Bloodlust/Animosity keyword data, Dodgy Snack drive-end restoration (needs
  procedural squads); D31 deferred Kick-off Return (BB2020 relic — stays a
  classified mapper divergence), Charge! up-front selection, TTM/KTM dice mapping;
  D19 Shadowing (needs per-turn MA-use counter); D12 Pitch-Invasion fan-factor
  modifiers partially landed in D31.
- D23 decode low-x fallback bias: documented, not fixed (irrelevant under masked
  sampling).
- The core July rules/reward corrections and experiment tooling are
  commit-backed. Production reward defaults remain unchanged: install/rebuild
  the corrected module only in an isolated experiment checkout for the next
  manifested run, then require the full promotion gates before any default.

### Unattended multi-day execution

Do not encode the priority list as an adaptive agent that chooses its next arm
from live metrics. Before an unattended window, resolve every branch that can be
resolved, then freeze literal commands and expected artifacts in a schema-1
`tools/experiment_queue.py` plan. Every job needs a maximum runtime and success
validator; long jobs need a progress artifact and short jobs need an explicit
progress exemption reason (the exemption is capped at 30 minutes). Use typed
command/validator/environment values: literal values cannot carry paths;
immutable file and directory-tree inputs are pinned; output paths are declared
mutable; generated inputs link to an earlier job's recorded artifact. Pin and
recheck every executable and transitive input by byte size and SHA-256/tree
identity, and use only the plan's allowlisted base environment. The queue root must be the
isolated audit checkout, and the service must use `KillMode=control-group`.
Every queue invocation is a pinned executable plus a reviewed, hash-pinned
runner file. Literal arguments are limited to numbers, lowercase SHA-256
digests, and long flags; categorical/free-form strings belong in the pinned
runner or config.

`resume_safe` means the job's own runner validates a frozen manifest and every
partial/completed artifact before continuing. It does not mean “probably okay
to rerun.” A plan drift, failed gate, missing/stale progress file, disk limit,
sustained thermal limit, or invalid success artifact halts the queue and leaves
later work pending. An unattended queue may produce evidence but may never
promote a reward or production default. Use
`docs/vacation-autonomy-2026-07.md` as the operational checklist.

A persisted halt is terminal. Do not restart it in place after editing state or
artifacts. Preserve the halted evidence and create a newly reviewed queue
ID/plan/state if human diagnosis authorizes follow-up work.
For the active vacation queues, follow
`docs/vacation-operator-runbook.md` before any recovery or return-day action.
Its state table keeps observation, watcher grace, terminal evidence, and the
post-run idle-GPU evaluation boundary distinct.

For the July vacation contract, do not hand-author the typed plan. After the
main `1B x 2` paired screen and both transfer strata pass, use
`tools/freeze_vacation_queue.py`. Its literal order is: second-ancestry `1B x 2`,
second scripted transfer, second learned-anchor transfer, two-lineage gate,
main `paired-final`, second `paired-final`. `paired-final` is a fixed six-arm
schedule (`both/candidate x seeds 42,43,44`) at `6B` requested steps per arm.
`tools/run_reward_learned_transfer.py` loads each focal policy in both native
backend roles against every pinned anchor. `tools/vacation_reward_gate.py` must
revalidate both self-play screens and both transfer strata before producing the
only artifact that unlocks the final screens. Never mark a PPO screen
`resume_safe`; its partial optimization trajectory is not restart-equivalent.

There are two reviewed no-candidate primary routes. If and only if the exact
decomposition analysis recommends `both` and its eligible-candidate list is
empty, freeze
`candidate_arm=both`, null `anchor_config` and `main_learned_complete`, and
`final_steps=12B`. The freezer then emits exactly two `control-final` jobs:
R0-only seeds 42/43/44 from the main ancestry, then the same schedule from
`league9`. This preserves the `72B` final budget without training a rejected
objective. If any simplification remains eligible, the fallback must fail
closed. The rejecting decomposition screen must also satisfy the full current
config-tree, explicit default-config, compiled-module, exact nine-file runtime,
patch, warm, and pool provenance contract. A legacy screen missing any of those
identities is screening evidence only and must be rerun before it can authorize
the control queue. The scripted matrix must also use `both` as reference and
evaluate all three simplifications. An empty eligible list from a subset is not
an all-candidates-rejected result.

If an already-selected candidate instead fails the unchanged paired
confirmation gate, the explicit `confirmation-rejected-baseline` route may emit
the same two R0-only jobs only after independently regenerating the failure and
matching the confirmation's embedded selection-transfer proof. It is not an
all-candidates-rejected result and cannot switch candidates.

D186 adds one optional, separate post-primary overflow because measured local
throughput can leave the owned GPU idle before return. Use only
`tools/freeze_vacation_overflow.py`: exact primary completion and its original
validators unlock one unchanged R0 `control-final` screen from the static
pool's exact netblock ancestry, `12B x seeds 42/43/44`. The delayed timer also
requires primary-service inactivity, unchanged pins, no existing overflow state,
and no GPU compute PID. It cannot run after primary failure/halt/drift, relaunch
an interrupted PPO screen, choose a reward, or change production.

D215/D216 govern the terminal July overflow. Its seed-42 training and 10,000
evaluation games are rejected historical evidence because that frozen screen
required 10,001; do not relabel or splice them into a completed screen. Preserve
the old root and queue unchanged. A human-authorized replacement must use
`tools/freeze_vacation_overflow_recovery.py`, the separately named recovery
root/queue, and the exact two-job shape: deterministic terminal-evidence
preflight, then a fresh ordinary R0 `control-final` at 12B for seeds 42/43/44
from netblock. The old checkpoint may be hashed as authorization context but is
not a result, warm start, candidate input, or milestone-evaluation input. Keep
the PPO job non-resume-safe and treat another interruption as terminal. The
freezer and evidence validator must accept only the exact reviewed recovery
root, pin every file in the seven-file Puffer patch bundle, and use the exact
pinned `nvidia-smi` to require no compute PID when the preflight success is
revalidated immediately before PPO starts.

D187 freezes the interpretation of the first seed-42 6B curve. Improvement
against the four static banks is in-pool and non-monotonic, not a newest-policy
selector. The same curve shows more carrier-focused risk, persistent Rush use
despite its tax, and near-absent pass/handoff actions; human frequencies remain
canaries, not objectives. Use the fixed paired milestone protocol after an
accepted screen. Future causal priorities are gamma-corrected distance/anneal,
the declared no-rush A/B, replay-derived rare-action scenarios, and a
per-component emitted-reward ledger before mechanism-dominance claims.

D188 corrects D187's mixed endpoint masks and static-pool weighting. Puffer
reports every field as a per-panel rate normalized by that panel's `n`; combine
ordinary fields as `sum(metric * n) / sum(n)` and static score as
`sum(hist_score_bank_i * n) / sum(hist_n_bank_i * n)`. Use one explicit mask
for every column. Over fixed `(0, 0.5B]` and `(5.5B, 6.0B]` bands, corrected
static score is `0.5337228569 -> 0.6205900025`; see D188 for the unified
behavioral table. D187's qualitative verdict stands. Any reusable analyzer
needs source hashes, explicit boundaries, and unequal-panel-size regression
coverage.

D189 records an operational interaction between qualitative BBTV and the
vacation overflow gate: the GPU-built match viewer appeared in the exact
compute-PID query and would prevent primary completion from unlocking overflow.
Conversion-only CPU isolation is insufficient. The match server must load a
separate CPU/fp32 Blood Bowl `_C`, hide CUDA, pass a real WebSocket-cycle probe,
and be absent from the pinned parser without touching either queue's inputs.

Vacation screen jobs must invoke `tools/run_frozen_reward_screen.py`, which sets
`ARM_DETACH=0`. The queue creates a new session for each job, and every screen,
arm wrapper, trainer, and descendant must remain in that process group so its
runtime/progress/capacity/thermal guards cannot strand GPU work. Do not add an
inner `setsid`, `nohup`, daemonizer, or process supervisor to a queue-owned
training path.

Post-run long-horizon characterization uses
`tools/run_checkpoint_milestone_eval.py` under the fixed protocol in
`docs/plans/r0-milestone-evaluation.md`. Accept only a completed and revalidated
`control-final` screen. Resolve the predeclared 0/1/2/4/6/8/10/12B points by
embedded native step (never mtime), freeze every hash before matching, use
common seeds and both native backend roles, and require an exclusive idle GPU
with the BBTV follower explicitly quiesced. Do not stop a training or BBTV
process to make the evaluator run; remain pending. Label the vacation static banks as in-pool, historical exact anchors
as lineage-connected transfer rather than independent holdout, scripted bots
as functional probes, and forced rosters as stratification because procgen
trained on every roster ID. The fixed plateau rule only compresses a later
evaluation. It cannot select/promote a reward, mutate a queue, or change a
production default.

---

## 12. Session checklist

Before doing anything: read `AGENTS.md`, D177–D189 and the ledger tail; discover
live Tailscale/Vast state and processes; confirm the intended checkout is not the
production checkout. Before launch: verify obs size, install drift, imported
module/provenance, disk, complete reward manifest, opponent/data hashes, seeds,
execution order, eval gate, and integrity rejection rules. After a run: analyze
the immutable result, copy/hash the cap, separate in-sample from held-out
evidence, append one atomic ledger finding, and only then consider a default.

## Run length / stopping rule (D168) — plateau, not a fixed budget

Reward-economy / behavioral DIAGNOSTIC probes are NOT stopped at a fixed step budget.
- **Extend-on-still-improving, stop-on-plateau.** Track the primary metric(s) the probe tests
  (block_2dred_frac, offassist_2d, etc.). At each cap, compare the metric over the last ~2B window
  to the prior ~2B. Still moving beyond noise → **chain a warm-restart from the cap** (same reward
  config + pool preseed; total-timesteps can't be raised mid-run) and continue until it flattens.
  Flat, or the verdict is already decisive → stop + record.
- Judge "still improving" on the metric that MATTERS: behavioral curve for a probe; Elo-vs-frozen-anchors
  for a strength/final run — and there also stop on the EvalStop overoptimization downturn (k=2 consecutive
  Elo drops), not just plateau (a proxy can climb toward human while true strength regresses).
- Probe = stop at behavioral plateau / clear verdict (cheap). Final policy = run to a real budget / Elo
  plateau for max strength.
- To extend: warm-restart from the latest snapshot/cap, same config, same `--selfplay.league-preseed`.
