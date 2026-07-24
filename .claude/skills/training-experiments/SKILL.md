---
name: training-experiments
description: Design and read Blood Bowl RL experiments — complete reward manifests, paired seeds, integrity gates, held-out transfer, checkpoint lineage, metric semantics, opponent controls, tournaments, stopping rules, and DECISIONS.md entries. Use for any training run, reward ablation, A/B, evaluation, metric read, transfer study, or promotion verdict. Build and host operations live in puffer-env-dev and fleet-ops.
---

# training-experiments — running the RL program

Historical findings were paid for with real compute, but later controlled evidence can amend
them. **Do not retune from aesthetics, training curves, or human-looking behavior. Change one
declared factor, validate on match utility and held-out transfer, and write every accepted
finding to `DECISIONS.md`.**

Read `AGENTS.md`, the tail of `DECISIONS.md`, and
`docs/reward-and-replay-audit-2026-07-09.md` first; newer ledger entries supersede this file.

## 1. Where the program stands

No reward has been promoted to production.

- **D177:** the repaired R0–R3 2×2 completed eight paired arms at exactly `249,954,304`
  native steps, two seeds, ≥10,001 eval games/arm, zero integrity counters. Distance supplied
  nearly all scoring learnability: TD/game `+0.76365`, match score `+0.11130`, ball-forward
  `+4.45069`. It also raised block volume and 2D-red rate.
- **D178:** the R0/R2 transfer matrix (16 cells, 16,076 games) showed removing
  possession+gain lowered match score in all eight matched cells and raised losses and
  opponent TDs in all eight. R2 is **not** transfer-noninferior.
- Keep R0 as the next experimental baseline only. Raw distance `ΔΦ` is a scaffold: not exact
  PBRS at `gamma=0.995`, not final utility.
- **Next screen** — distance on in every arm, `500M × 2 seeds`, then confirm the simplest
  transfer-noninferior survivor with learned opponents, roster macro, longer horizon, and a
  second ancestry:

  | Arm | Possession annuity | Ball-gain event |
  |---|---:|---:|
  | P0 | on | on |
  | P1 | on | off |
  | P2 | off | on |
  | P3 | off | off |

- **D182:** the July 13–14 attempt finished every arm but is rejected — one training emission
  exceeded the PPO clamp by exactly `0.015` and the retained schema cannot identify its sign
  or terminal context, and the audit separately found an unsafe
  result-plus-incidental-shaping terminal path. Fix terminal composition, add
  terminal/non-terminal recurrence telemetry, rerun every arm under one semantic contract.

Evidence: `runs/reward-screens/reward-screen-20260709-v1/SCREEN_COMPLETE.json`,
`runs/reward-transfer-20260713-v1/ANALYSIS.json`,
`docs/reward-and-replay-audit-2026-07-09.md`.

## 2. The experimental contract

Tools: `tools/reward_manifest.py`, `tools/run_reward_screen.sh`,
`tools/analyze_reward_screen.py`, `tools/analyze_reward_transfer.py`.

1. Hold constant source, installed env/config, imported module, Puffer patches, warm
   checkpoint, pool, backend, optimizer, seeds, execution order, and eval policy. Change one
   declared factor, with paired seeds.
2. Supply a **complete** reward JSON. An omitted field and an explicit zero are different
   things — that is why the manifest is hash-checked. Never inherit a launcher default.
3. Record the hashes; keep the plan, per-arm status/result, final checkpoint, and analyzer
   output.
4. Require explicit phase telemetry, the requested number of complete kickoff games, a final
   cumulative reprint, and zero clip / non-finite / engine-error / demo / fallback counts.
   The acceptance floor equals the request: an exact count is complete and must not depend on
   vectorized overshoot.
5. Reject integrity failures instead of averaging them into the comparison.
6. Report W/D/L, TD for and against, both sides, paired common-seed differences, and
   in-sample versus held-out results separately.
7. Two-seed / scripted-bot screens are descriptive — not confidence intervals, not
   tournament-strength claims, not grounds for promotion.
8. On an episode-ending step emit only the explicit current-step objective reward (TD),
   result utility, and separately declared terminal terms. Incidental action or board shaping
   must never co-stack invisibly with the result.

Launch through complete manifests in `puffer/config/rewards/`. Never send a new reward arm
through bare `tools/run_synthesis_c.sh`: it has frozen v3 defaults including the poisoned
ball-loss profile, and is only for exact historical continuation with a complete explicit
override. Its `ANCHOR`/`LOG`/`STEPS` env vars are historical. Verify every launch from
process state, fresh logs, status records, and the imported module — a "LIVE" banner is not
evidence. Build/install liturgy: `puffer-env-dev` §7. Host and monitoring: `fleet-ops`.

For an unattended multi-day window, resolve every branch first, then freeze literal commands
and expected artifacts in a `tools/experiment_queue.py` plan with per-job max runtime, a
success validator, and progress artifacts. Unattended evidence never changes a production
default.

## 3. Current era: obs-v6

- **obs-v6 = 2782 bytes** — obs-v5's decision-window truth plus the ten
  addressable-but-invisible blind spots that audit closed: the `CHOOSE_OPTION` candidate
  table, PUSH POW/FROM_BLITZ, the declared `bb_act_kind`, both casualty rolls, the
  turnover/kickoff flags, the placement budgets, the stashed MOVE target, `ktm_used`, and a
  generalized pending consequence square (`docs/obs-v6-spec.md`). **Obs-v4 AND obs-v5 are
  also 2782 bytes**, so tensor shape cannot identify the semantic lineage — only
  `BBE_OBS_VERSION` plus source/module provenance can, and a v4/v5 mixup already wasted a
  12B-step run. **The v5 lineage is closed: obs-v6 needs a fresh `genesis` +
  `genesis-pool` on one build before any `lineage-v6` arm can launch.**
- **OBS_SIZE sync points — all three must agree:** `BBE_OBS_SIZE` in
  `puffer/bloodbowl/bloodbowl.h`, `#define OBS_SIZE` in `puffer/bloodbowl/binding.c:8`, and
  `--obs-size` in `training/convert_checkpoint.py` (`DEFAULT_OBS_SIZE`, 2782). A
  `_Static_assert` ties the first two at build time; **the converter is the unguarded one**
  and a wrong `--obs-size` converts to silent garbage (D54). Obs-v3 needs an explicit
  `--obs-size 1612`, obs-v2 `832`.
- Flat checkpoints carry no lineage header, so a current checkpoint requires its adjacent
  `.lineage.json` from `tools/checkpoint_lineage.py`, binding the checkpoint hash,
  obs-v6/exact-joint-v1 ABI, policy shape, producer manifest, source/module/patch identity,
  and ancestry eligibility. Missing, mismatched, or qualification-only sidecars are not warm
  starts or pool seeds. Build pools with `tools/build_league.py` (`--legacy-unlabeled` is
  historical reconstruction only).
- There is **no accepted obs-v6 BC anchor**. `training/bc_v4.bin` (val exact 0.508, D53) and
  the 2.09M v4 pairs in `validation/pairs_v4` are valid only in a deliberately pinned obs-v4
  runtime — never warm-start or evaluate them under v5/v6 because the shape loads. New
  exact-action obs-v6 exports are BBP v4; NOTE that the BBP header does not record which
  observation revision produced a shard, so v5 and v6 pairs are indistinguishable by header
  and must be kept separate by provenance. The loader rejects v1–v3 (version table in
  `puffer-env-dev` §9).
- The `exact-action-canary` is a fresh-initialization qualification run: launch with
  `env -u WARM -u POOL` and zero frozen banks. Its output is qualification-only — never
  continue from it, never analyze it as a result cell.
- A new runtime must pass the fp32 target-GPU recurrent gate
  (`tools/qualify_recurrent_cuda.py`) and then a disposable 50M-step canary before any long
  paired screen. What the gate proves and why bf16 is refused: `puffer-env-dev` §8.

## 4. Reward economy (experimental baseline, not settled utility)

Canonical R0 values live in `puffer/config/rewards/r0_full.json` — do not retype or partially
override them. Currently: terminal TD `0.4`, win/loss `±0.6`, draw `0`; possession `0.03`,
gain `0.05`, loss `0`; distance-to-ball/endzone `0.02/0.04`; block terms
`k_kd/k_value/k_ball/k_turnover/k_seq = 0.10/0.50/0.15/0.15/0.03`; rush cost `0.015`; other
shaping zero. This is an **experimental control**, not a recommended objective.

- Distance supplies most learnability. Keep it during decomposition, but call it a scaffold —
  raw state delta is not exact discounted PBRS.
- Possession+gain has a small screen effect but a consistent defensive transfer benefit. Keep
  the bundle only until the next screen isolates its components.
- Rush and block terms are scaffolds. More blocks is not a promotion criterion: R2 blocked
  more and lost more in transfer.
- Stalling is not an accepted side effect. BB2025 penalizes a carrier who could score without
  dice, so evaluate possession rewards against score/clock behavior and held-out utility.

**Invariants for every reward variation:**

1. Complete canonical manifest; never inherit an omitted field.
2. `ball_loss = 0` while the possession annuity is on — no double fine.
3. Anything called a potential uses the exact discounted form
   `beta*(gamma*Phi(s') - Phi(s))`, or is labeled a non-invariant scaffold.
4. Rush-gate blitz exposure and include rush-failure turnover probability.
5. Record and reject reward clipping or non-finite values.
6. Do not reward realized dice as shaping. Event/EV terms still redefine utility and need
   held-out match validation.
7. Do not promote from human-stat proximity, TDs alone, or training-opponent success. Require
   W/D/L and TD for/against on held-out opponents.
8. Terminal match utility is authoritative: incidental shaping on the episode-ending action
   must not share the terminal result emission.

Future builds expose a 28-channel emitted-reward ledger from the team-0 perspective
(pre-clamp raw reward). Require `sum(components) + residual == episode_return` and
`episode_return - reward_clip_signed_delta == reward_postclip_return` within float tolerance;
a nonzero clamp delta fails integrity even when both identities hold. This is attribution,
not evidence that any shaping term helps.

## 5. Standing doctrines — IMPERATIVE form

Each was bought with a failed run.

**D46 — discovery vs artifact.** **NEVER patch out an inhuman behavior because it "looks
absurd"** (TD-Gammon's doubles, AlphaStar's worker saturation). Run three tests first:
*grounding* — does it persist when wins/TDs vs a competent opponent are the binding currency
rather than shaped income? *routing* — is its profit routed THROUGH the objective or around
it? *human rates are evidence, not law* — a 10× human rate is a flag, never a verdict. The
verdict belongs to the tournament, not your taste: GFI-spam is presumed artifact (routed
around the objective) and is still adjudicated by A/B — if the untaxed twin keeps high GFI
AND wins, absurd is correct and the tax dies. `reward_rush_cost` is anti-degeneracy
scaffolding to be annealed away, never a permanent value statement. Unifying diagnosis:
ball-avoidance, scrum-hovering, and GFI-spam are ONE disease — positional value is
denominated in points and there are no points. The cure is a working scoring economy, not
taxes. (True GFI price is positional: prone players project no tackle zones.) Prediction on
file: GFI discipline emerges FIRST on the carrying team.

**D50/D56 — graduation rule.** The grounded win-rate exam (4096 full games from kickoff vs a
frozen reference) is the FINAL-stage test only. **NEVER read a mid-curriculum draw rate as
failure** — 97–99% is expected; those tournaments are calibrations. Training-tds ≠ winning
until starts reach kickoff. Draw rate RISES with prior strength (96.8% → 98.8% v3→v4) because
stronger mirror priors mean fewer accident-decided games.

**D33/D34/D36 — decision-time exposure pricing (Profile C).** Exposure-EV transfer pricing
(`bb_blockev` closed forms; the k knobs; `docs/reward-audit-decision-time.md` Addendum 3) is
the ONLY known mechanism that creates contact-seeking. Shaped/anchored lineages collapse
contact to zero (PPO descends the "random contact is net self-harm" gradient, D33);
unshaped-from-scratch stays at random (D34 control). Always rush-gate blitz exposure (D36).
Exposure knob magnitude moves the brawl pole, NOT scoring (D40/D41) — don't crank it hoping
for TDs. Use `blocks_thrown` (one CHOOSE_DIE per resolved block) as the conversion
denominator.

**D26/D28/D49 — gradual anneal.** NEVER cold-off a scaffold knob; halve per chained stage.
Cold anneal decays scoring to zero (D26's D2 arm was dead by 5.4B steps). Annealing REMOVES
scaffolding; it never creates capability (D49: exposure-anneal alone never produced scoring).

**D29 — every "may" is policy surface.** NEVER auto-resolve a rulebook optional choice;
auto-policies delete tactics (the Wrestle counterexample reversed D9). Optional choices are
USE_SKILL/DECLINE_SKILL or CHOOSE_OPTION windows. The probability engine resolves choice
nodes owner-optimally; FUMBBL skillUse reports validate via lockstep and feed BC pairs.

**D38/D218 — exact sampled/executed action law.** Per-head marginal masks are historical and
insufficient. Accepted native and Torch runs consume packed joint support, sample sequential
conditional heads, store the selected conditional masks, and require `illegal_frac == 0`.
`bbe_decode` is a fail-closed boundary, not a repair policy: any decoder rejection, empty
conditional head, missing exact-backend installer marker, or non-unit zero-update PPO ratio
invalidates the run. **NEVER cite tds-emergence intuitions from pre-fix torch runs** — the
unmasked era had `illegal_frac 1.000` and a decode-fallback shadow policy, so all its measured
dynamics are invalid; CUDA-backend results (D26–D28, D34) are unaffected. BBP v1–v3 pairs
cannot enter an exact-action corpus on shape compatibility alone.

**D219 — zero contamination, detected fail-fast.** Zero accepted violations does not permit
an unbounded late rejection. Freeze and run `tools/live_integrity_guard.py` with
`illegal_frac` in the same hard registry as the reward/non-finite/error counters (operational
detail in `fleet-ops`). While the trainer is live, 180 s without an integrity-bearing panel is
a failure; recovery and final validation instead use complete-log mode, rescanning all
remaining bytes under the same exact-zero registry so a stopped log is never aged into a
false liveness failure.

**D174/D176 — BC and opponent verdicts.** D174 supersedes "sequence context first":
frame-stacked structural context was null because obs-v4 already encodes within-turn state,
and last-action history added `+0.002`, inside noise. Do not fund recurrence without
full-game lockstep data and a new falsifiable hypothesis. D176 supersedes "a BC anchor
prevents erosion": full-strength persistent iid CE mechanically held BC accuracy but
collapsed offense — do not reintroduce it as default and do not infer that a weaker
coefficient must help. Opponent quality produced the strongest defensive improvement, but a
single deterministic bot is an overfit probe: prioritize diverse opponents and held-out
transfer over corpus volume or stronger anchoring.

**D35 — optimization-bound before capacity claims.** NEVER declare a BC model
"capacity-bound" from val≈train alone; verify with extended cosine-decay steps first (bc_v3b
gained +1.1pp val that the capacity-bound reading said couldn't exist).

**Misc.** D6: `make goldens` is explicit — rules fixes are EXPECTED to break goldens. D15:
BB2025 team re-rolls are UNLIMITED per turn, replenished at half-time; skill re-rolls once
per turn per player. D25: setup is reserves-first, budget 24. D16-AMENDED (D36): check Claws
BEFORE Mighty Blow. D44: the spectator event feed is POD-only cross-thread. D31:
`bb_match.fan_factor[2]` changed `engine_fp` — regenerate the demo-state bank on ANY
engine_fp change.

## 6. Metric semantics

| Metric | Reference values | How to read it |
|---|---|---|
| `tds` | stage-dependent | Per-episode touchdowns **FROM CURRICULUM STARTS**. NOT comparable across maxdist stages — a drop on stage advance is expected, not regression. |
| `block_2dred_frac` | human 0.017; v3 plateau ~0.20; v4 0.169 falling | Blocks thrown at 2-dice-against. **Falling = probability planes working.** |
| 2d : 2dred ratio | human 46:1 | Same axis. |
| `possession_rate` | corrected BB2025 human genuine-turn rate 0.47394; per-game mean 0.47453 | Semantics changed historically; never compare old ~0.15 values or synthetic turns to it. Diagnostic, not a target. |
| `gfi` | human ~2–5/ep; agent ~25–35 | Presumed ARTIFACT per D46 until it survives grounding. Track it; don't patch it outside the rush-tax A/B. |
| `bc_acc` | v4 ceiling ~0.51 (runs hold 0.49–0.55) | Anchor agreement; collapse far below = erosion. |
| `blocks_thrown` | — | Clean denominator for contact conversion. |
| `illegal_frac` | must be 0 | ≈1.000 means the sampler is broken (D38). Stop and fix before trusting anything. |
| Tournament draw rate | 96.8% (v3) → 98.8% (v4) mirrors | Rises with prior strength (D56); mid-curriculum 97–99% expected. |
| SPS | torch ~0.6–0.77M; native 2.1M on 24c (D57) | Throughput sanity check. |

**Combining panels (D188).** Puffer reports every field as a per-panel rate normalized by
that panel's `n`. Combine ordinary fields as `sum(metric * n) / sum(n)` and static-bank score
as `sum(hist_score_bank_i * n) / sum(hist_n_bank_i * n)`, with one explicit mask per column.
This changes answers: over `(0, 0.5B]` and `(5.5B, 6.0B]` corrected static score is
`0.5337228569 -> 0.6205900025`. Any reusable analyzer needs source hashes, explicit
boundaries, and unequal-panel-size regression coverage.

**Curve reading (D187).** The frozen seed-42 0–6B curve improves against its four static
training banks, but that is in-pool and non-monotonic — not a newest-policy selector. The same
curve shows more carrier-focused risk, persistent Rush use despite its tax, and near-absent
pass/handoff. Label static banks as in-pool, historical exact anchors as lineage-connected
transfer (not independent holdout), scripted bots as functional probes, and forced rosters as
stratification (procgen trained on every roster ID). Post-run trajectory characterization uses
`tools/run_checkpoint_milestone_eval.py` per `docs/plans/r0-milestone-evaluation.md`: resolve
the 0/1/2/4/6/8/10/12B points by embedded native step (never mtime), use common seeds and
both native backend roles, require an idle GPU with BBTV quiesced, and never stop a training
or BBTV process to make the evaluator run.

## 7. Tournament procedure

Run the final-policy evaluation and held-out transfer matrix (§2) first. `puffer match` is
useful for checkpoint head-to-heads but is not a substitute for both sides, TD for/against,
opponent diversity, roster macro, provenance, or integrity telemetry.

1. Ship both checkpoints to the judge GPU box-to-box (`ssh -A`), not Mac→box for big files.
2. Convert: `python training/convert_checkpoint.py --to-cuda <torch.bin> -o <out>` — **mind
   `--obs-size`**. A 2782-byte v4 checkpoint is still semantically invalid under v5 despite
   matching the default. Conversion drops biases, so treat both sides identically (D45).
3. From the judge's `vendor/PufferLib`:
   ```bash
   puffer match bloodbowl --load-model-path A_cuda.bin \
     --load-enemy-model-path B_cuda.bin --num-games 4096
   ```
   `match()` hard-errors unless the **native CUDA** backend is loaded — a `--float` torch
   build cannot serve it. A = slot 0, B = slot 1.
4. The result line is `games=4096/4096 A=x B=y draw=z`. Fewer games means the run died —
   investigate, don't extrapolate. Read the decisive-game split, not the draw rate.
5. Interpret per D50/D56: final exam and mid-curriculum calibration are different instruments.

## 8. Run length / stopping rule (D168) — plateau, not a fixed budget

- **Extend-on-still-improving, stop-on-plateau.** Track the metric the probe tests
  (`block_2dred_frac`, `offassist_2d`, …). At each cap compare the last ~2B window to the
  prior ~2B. Still moving beyond noise → warm-restart from the cap (same reward config and
  pool preseed; total-timesteps cannot be raised mid-run) and continue until flat.
- Judge "still improving" on the metric that matters: the behavioral curve for a probe;
  Elo-vs-frozen-anchors for a strength run — and there also stop on the EvalStop
  overoptimization downturn (k=2 consecutive Elo drops), since a proxy can climb toward human
  while true strength regresses.
- Probe = stop at behavioral plateau (cheap). Final policy = run to a real budget / Elo
  plateau. To extend: warm restart from the latest cap, same config, same
  `--selfplay.league-preseed`.

## 9. DECISIONS.md discipline

- **Every finding gets an atomic entry**, numbered `D{n+1}`, dated. If the write-up needs
  "and" between two findings, split it. Write it when the finding lands, not at session end.
- Each entry records what was run (box, config, checkpoint, steps), what was measured (with
  numbers), the verdict, and what it amends or supersedes (cite the D-number).
- **Never act on an experimental verdict you haven't written down.** Ledger first, then change
  the default.
- Amendments never delete: D9 was reversed by D29, D33 was scope-corrected. Append and
  cross-reference; never rewrite an old entry.

## 10. Open queue — priority order

1. **Decompose R0's possession family with distance fixed on** (both / possession-only /
   gain-only / neither; `500M × 2 seeds`, D177's contract). R2 is prior evidence for
   `neither`, not permission to skip a fresh matched cell.
2. **Confirm R0 against the simplest transfer-noninferior survivor:** `1B × 2 seeds`,
   learned-opponent transfer, both sides, roster-grid macro, TD for/against, uncertainty.
3. **Separate opponent curriculum from reward:** freeze the reward, compare diverse competent
   opponents (D176: opponent quality can dominate apparent defense gains).
4. **Make distance policy-safer:** exact discounted PBRS, or anneal to zero and show
   non-inferiority against objective-only.
5. **Ablate rush and remaining block scaffolds one family at a time.**
6. **Reproduce the finalist from a second ancestry** (candidate: league9), then the final long
   matched control. Only this stage can authorize a production default change.
7. **Improve replay sampling:** edition-exact, replay-disjoint, hierarchical
   depth/action/roster sampling with setup caps; replay-derived scenarios only after full-game
   lockstep coverage is verified.

**Background threads.** The strict BB2025 replay corpus is opening-censored and nearly lacks
pass, handoff, foul, Jump, TTM, and Special targets — never claim rare-action or late-game
learning from aggregate BC accuracy. Recurrent sequence training stays contingent on
full-game lockstep conversion. Historical curriculum ladder, for context only:
`maxdist 6 → 9 → 12 → uniform → kickoff`; July causal comparisons use full kickoff starts
(`demo_reset_pct=0`), and TD rates never compare across start depths. Pending FUMBBL
differential adjudications and phase-3 rule TODOs are enumerated in DECISIONS.md (D11, D13,
D18, D19, D21, D23, D31, D36) — read there rather than trusting a summary here.

## 11. Footguns specific to running experiments

1. **Python `str.replace` silently no-ops on anchor mismatch.** Always `grep` the file after a
   scripted edit to prove the change landed.
2. **A reward field omitted from a config is not an explicit zero.** Complete manifest,
   validated SHA.
3. **A final `Steps` line is not an accepted result.** Require the explicit eval phase, the
   requested completed games, the final cumulative reprint, the checkpoint hash, and zero
   integrity counters — and do not kill the evaluator because the dashboard stopped moving.
4. **Newest mtime ≠ highest step** across run dirs; read the step embedded in the filename.
5. **Liveness is log mtime plus the launcher's recorded PID, never log content** — a finished
   trainer leaves a frozen log forever (D65), and current arms are not named `puffer`
   (`fleet-ops`).
6. Build, sync, and host footguns: `puffer-env-dev` §13 and `fleet-ops`.
