---
name: training-experiments
description: Run the Blood Bowl RL experiment program — fleet ops on the 4 Vast.ai boxes, the launch contract (run_synthesis_c.sh, warm-start, rebuild discipline), the settled v4 reward economy and its invariants, the curriculum ladder (maxdist 6→9→12→uniform→kickoff), metric interpretation against reference values, tournament procedure, the standing doctrines (D46 discovery-vs-artifact, D50/D56 graduation rule, decision-time pricing, anti-farming invariants, gradual anneal, masked sampler), DECISIONS.md ledger discipline, and the open experiment queue. Use for ANY training run, A/B, checkpoint op, metric read, or experimental verdict in this repo.
---

# training-experiments — running the RL program

You are continuing a long experiment program alone. Everything settled here was paid
for with GPU-weeks and dead lineages. **Do not re-derive, re-tune, or "improve" the
settled design on aesthetics. Change knobs only through the experiment queue, with
A/Bs, and write every finding to DECISIONS.md.**

State as of 2026-06-08 (v4 era, stage-2 live, ledger D1–D57). When state changes,
update this skill. ALWAYS read the tail of `DECISIONS.md` first — anything newer
than D57 supersedes this file.

---

## 1. The fleet

4 Vast.ai boxes. **Labels are state** — confirm with `vastai show instances --raw`
(or `tools/fleet.sh ls`) before trusting anything below. SSH host/port CHANGE after
a stop/start — the endpoints below are a snapshot, re-resolve them after any
restart. SSH key `~/.ssh/id_ed25519`, repo at `/root/bloodbowl-rl` on every box.
`vastai` CLI must be ≥ 1.0 (the brew 0.4 build makes zombie instances).

| Label | SSH (snapshot) | Cores | Role |
|---|---|---|---|
| `bb-japan-native` (box-1, id 39322464) | `ssh3.vast.ai:12464` | 24c | scraper + judge GPU + native-asym run (D57) + **replay cache SOLE COPY (~27K files — never delete, never let this box be reclaimed without backing it up)** |
| `bb-taiwan-anchor` (box-2, id 39471946) | `ssh2.vast.ai:31946` | 28c | anchor training / overflow |
| `bb-ballhawk` (box-3, id 39745431) | `ssh4.vast.ai:25430` | 64c | FAST — flagship runs |
| `bb-possession` (box-4, id 39790498) | `ssh7.vast.ai:30498` | 64c | FAST — twin/A-B runs |

Fleet rules:

- **NEVER ship big payloads Mac→ssh4 directly.** The Mac→ssh4 route can be
  pathologically slow. Ship box-to-box: `ssh -A` (agent forwarding) from a fast box,
  then `scp`/`rsync` between boxes.
- `tools/fleet.sh` subcommands: `search | provision | ls | ssh | setup | launch |
  status | collect | destroy`. `setup` deliberately excludes `vendor/PufferLib/
  {.venv,build,raylib*,checkpoints}`, `validation/replay_cache`, **and
  `training/*.bin`** — venv/raylib/build rebuild per-box (do not "fix" that by
  syncing them), and **anchors + checkpoints never sync via setup: ship them
  box-to-box yourself.**
- Vast **stopped** instances can be RECLAIMED (the GPU re-rented under you). Restart
  promptly after a stop, or accept you may get a replacement box.
- The balance ladder `/tmp/vast_ladder.sh` (Mac-side; `/tmp` is wiped on Mac reboot
  — recreate it if missing) stops boxes in value order when credit drops below
  $5 / $3.5 / $2. It is stop-only and reversible. Spend cap is $50 (D7).
- All monitor/SSH loops MUST use `ssh -n -o ConnectTimeout=...` (footgun 9).
- **Restart after hibernation** (D55 procedure, lost zero data):
  ```bash
  for i in 39322464 39471946 39790498 39745431; do vastai start instance "$i"; done
  tools/fleet.sh ls        # re-resolve ssh endpoints — they change on restart
  ```
  Then on box-1 restart the scraper: `cd /root/bloodbowl-rl && nohup bash
  tools/long_scrape.sh >/dev/null 2>&1 &` (resumable, manifest dedupes; stop with
  `pkill -f '[l]ong_scrape'`). Resume training runs via the warm-start procedure
  in §3. If an id no longer exists, the box was reclaimed — re-provision and
  re-`setup`, then re-ship anchors/checkpoints.

---

## 2. Current era: v4

- **obs-v4 = 2782 bytes** — probability planes A1/A2/B. Spec: `docs/obs-v4-spec.md`.
- Anchor: **`training/bc_v4.bin`** (val exact 0.508, D53). **It lives ON THE BOXES
  only** — it is not in the local repo and `fleet.sh setup` excludes `training/*.bin`;
  copy it box-to-box for any new box. 2.09M pairs in `validation/pairs_v4`
  (`validation/pairs` is a symlink to it on v4 boxes).
- **OBS SIZE SYNC POINTS — all three must agree:**
  1. `BBE_OBS_SIZE` in `puffer/bloodbowl/bloodbowl.h` (~line 96)
  2. `#define OBS_SIZE` in `puffer/bloodbowl/binding.c` line 8
  3. `--obs-size` in `training/convert_checkpoint.py` (`DEFAULT_OBS_SIZE`, now 2782)
  A `_Static_assert` ties (1)↔(2) at build time; **(3) is the unguarded one** — a
  wrong `--obs-size` converts to silent garbage (this exact miss bit D54).
- **Old obs-v3 lineage checkpoints are input-shape INCOMPATIBLE** with v4. Converting
  a v3 checkpoint requires explicit `--obs-size 1612`. Never mix lineages in a run or
  a tournament without converting deliberately.

---

## 3. Launch contract

Launcher: **`tools/run_synthesis_c.sh`**, run on the box from `/root/bloodbowl-rl`.

**CRITICAL: the script's baked-in defaults are the FROZEN v3 synthesis+C profile**
(`ball-gain 0.1 / ball-loss -0.2`, full-strength k `0.06/0.5/0.3/0.02`,
`demo-reset-pct 0.5`, no possession/rush/maxdist knobs). The settled v4 economy
(§4) exists ONLY as overrides passed after the script name. Launching "bare"
ships a config that VIOLATES the D43 invariant (loss fine + annuity). Canonical
v4 stage-2 launch:

```bash
ANCHOR=<ckpt-or-anchor> LOG=/tmp/v4_s2.log bash tools/run_synthesis_c.sh \
  --env.reward-possession 0.03 \
  --env.reward-ball-gain 0.05 --env.reward-ball-loss 0 \
  --env.reward-dist-ball 0.05 --env.reward-dist-endzone 0.2 \
  --env.reward-k-kd 0.03 --env.reward-k-value 0.25 \
  --env.reward-k-ball 0.15 --env.reward-k-seq 0.01 \
  --env.demo-reset-pct 0.9 --env.demo-endzone-maxdist 9 \
  --train.frozen-enemy-path training/bc_v4.bin
```

Taxed twin adds `--env.reward-rush-cost 0.015`. **When RESUMING a live arm, do not
reconstruct flags from memory: recover the exact prior command from the box**
(`head` of its `/tmp/*.log`, or the PROFILE file in the run's checkpoint dir) and
change only `ANCHOR`/the intended knob.

Script mechanics (it enforces all of these — know them before you launch):

- Refuses to double-launch: kill any live trainer first with
  `pkill -f 'puffer [t]rain'` (bracket pattern, footgun 3).
- `ANCHOR=<path>` (default `training/bc_v3b.bin`) — passed as `--load-model-path`,
  so it is both warm-start and BC-anchor init. Guard: rejects files ≤13,000,000
  bytes (dead 832-obs lineage ≈12.08MB; v3b 13.68MB; v4 files are larger — pass).
- Requires the demo bank at `vendor/PufferLib/resources/bloodbowl/state_bank.bbs`
  (>1MB or it exits; a missing bank would otherwise SILENTLY train procgen-only).
- `LOG=<path>` (default `/tmp/synthesis_c.log`), `STEPS=<n>` (default 10B).
- Asymmetric runs **OVERSHOOT the step cap ~1.5×** (runner `global_step` advances
  train-batch-width under asymmetry — open thread 7). Benign; budget for it. Do
  not "fix" a run mid-flight because of it.
- BC knobs: `--train.bc-coef 1.0` (cosine); floor via `--train.bc-coef-floor`.

**Warm relaunch:** `ANCHOR=<newest checkpoint>`. Checkpoints live at
`vendor/PufferLib/checkpoints/bloodbowl/<run-id>/<step>.bin` on the box. Find with
`ls -t vendor/PufferLib/checkpoints/bloodbowl/*/0*.bin | head -1` — **CAUTION:
newest mtime ≠ highest step across run dirs.** When multiple run dirs exist, compare
the step number embedded in the filename, not mtime.

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

**Verify every launch:** the script prints `LIVE` or `TRAINER DIED` at the 40-second
mark, plus a warm-start/demo-bank echo. Do not walk away before reading it.

### Runs live right now (verify with `tools/fleet.sh status` before believing this)

| Run | Box | Config |
|---|---|---|
| `v4_s2` flagship (torch) | bb-ballhawk | maxdist 9, warm from v4_s1_final 15B ckpt (`0000014942470144.bin`, tds 0.42–0.49 at maxdist-6 starts) |
| `v4_s2tax` twin (torch) | bb-possession | same + `--env.reward-rush-cost 0.015` |
| `v4-native-asym` (D57) | bb-japan-native | native CUDA, NO bc aux, frozen bc_v4 selfplay-pool teacher (~48% vs-teacher / rest mirror), warm from v4_s1_final_cuda, stage-2 knobs, 2.1M SPS |
| `v3_tax` completion | box-2 | finishing the v3 rush-tax arm |

---

## 4. The reward economy (SETTLED — do not retune)

These are the §3 override values, NOT the launcher defaults — see the warning there.

| Knob (`--env.` flag) | Value | Why |
|---|---|---|
| `reward-possession` | **0.03** | Possession **annuity**: ±zero-sum payment at every own-turn boundary while holding (~16 binary events/side/game → unfarmable income stream, D43). |
| `reward-ball-loss` | **0 (with the annuity)** | INVARIANT. The annuity already prices a loss as (lost stream + opponent's gained stream). Adding an exit fine on top is **measured poison**: lump-sum+fine made refusing the free ball rational (kzero probe: `pickup_attempts 0.000` from kickoff). NEVER reintroduce a loss fine alongside the annuity. |
| `reward-ball-gain` | **0.05** | Pickup coupon, small. |
| `reward-dist-ball` | **0.05** | Potential shaping toward the ball. |
| `reward-dist-endzone` | **0.2** | Potential shaping toward scoring. |
| **k-half** (exposure) | **`reward-k-kd 0.03 / reward-k-value 0.25 / reward-k-ball 0.15 / reward-k-seq 0.01`** | Decision-time exposure pricing (D33/D34, §6). "k-half" = the original synthesis+C k values (0.06/0.5/0.3/0.02 — still the script defaults) halved once per the D28/D42 gradual-anneal chain. |
| `reward-rush-cost` | **0.015** | Rush tax. A/B leaning ADOPT, but it is **scaffolding to be annealed away** (D46), never permanent. |
| `--train.bc-coef` | **1.0, cosine** | BC anchor weight; floor via `--train.bc-coef-floor` (default decays to 0.1× — D45 made it configurable). |

**Invariants — check these before launching ANY reward variation:**

1. **`|ball_loss| > ball_gain` in any config that has a loss fine** (D42) — otherwise
   pickup→drop laundering. (v2 shipped 0.3/−0.4 after a premortem caught 0.3/−0.2.)
2. **`ball_loss = 0` whenever the possession annuity is on** (D43) — no double fine.
3. **All potentials must telescope** (unfarmable; D41 ballhawk design).
4. Exposure rewards on blitz MUST be rush-gated (D36): scale by P(rush succeeds) and
   fold rush-failure turnover, or attackers farm fictitious zero-sum reward.

Accepted known trade: the annuity mildly rewards stalling. That is real Blood Bowl.
Do not patch it.

---

## 5. Curriculum ladder

Stage variable: `--env.demo-endzone-maxdist`. Backplay stages run
`--env.demo-reset-pct 0.9` (90% of resets from the demo bank). Ladder:

```
6  →  9  →  12  →  uniform (maxdist 0 = whole bank)  →  kickoff starts (demo-reset-pct 0)
```

- **+3 squares per stage, never more.** D51: a 6→12 jump overshot (tds flat
  0.03–0.07). Small steps only.
- **Advance on tds plateau** at the current stage's starts.
- **Warm-start every stage** from the newest checkpoint of the previous stage (mind
  the mtime-vs-step caveat in §3).
- **Watch retention at every expansion.** The Backplay-literature failure mode is
  forgetting the endgame. Per-stage progress = tds-at-stage-starts PLUS retention
  probes of earlier stages (D50/D56).
- If a stage stalls: the designed (not yet built) escalation is the **frozen-opponent
  ladder** (D56) — train vs weaker frozen defenses first to manufacture decisive
  games earlier. Build it before inventing something else.
- Stage-1 depth finding (D52/D54): starting deeper-trained (15B ckpt) converges
  faster than shallower (5.24B) but to a similar band. Don't burn compute re-asking
  this in the v4 lineage without new cause.

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

### D45/D47 — Anchor verdicts

- The BC anchor prevents erosion (D32: bc_acc 0.93–0.96, tds 0.39–0.45 sustained
  where every unanchored arm died) but is **NOT the binding constraint**: full
  anchor release (bc_coef floor → 0) produced no breakout AND no collapse — PPO
  updates are too local to leave the basin.
- The PRIOR's quality is the bottleneck. Lever ranking, in order:
  **sequence context > bigger policy > more data** (D35-VERDICT/D45). Spend anchor
  effort in that order.

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

The ledger is at `DECISIONS.md` (D1–D57 so far). It is the program's memory.

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
| `possession_rate` | raw prior ~0.15; v4 s1 best 0.193; poisoned ~0.05 | If you see ~0.05, suspect a loss-fine-poisoned config (D43). |
| `gfi` (go-for-its) | human ~2–5/ep; agent ~25–35 | Presumed ARTIFACT per D46 unless it survives grounding. Track it; do not patch it outside the rush-tax A/B. |
| `bc_acc` | v4 ceiling ~0.51 (runs hold 0.49–0.55) | Anchor agreement. Don't expect above ceiling; collapse far below it = erosion. |
| `blocks_thrown` | — | Clean denominator for contact conversion (one CHOOSE_DIE per resolved block). |
| `illegal_frac` | must be ~0 | If ≈1.000 the masked sampler is broken (D38). Stop and fix before trusting anything. |
| Tournament draw rate | 96.8% (v3) → 98.8% (v4) mirrors | RISES with prior strength (D56). Mid-curriculum 97–99% is expected. |
| SPS | torch ~0.6–0.77M; native 2.1M on 24c (D57); 766K = v3-era 64c reference | Box-throughput sanity check; box-2 is ~1/7 of the 64c boxes. |

---

## 9. Tournament procedure

1. Ship both checkpoints to **box-1** (judge GPU). Box-to-box via `ssh -A`, never
   Mac→ssh4 for big files.
2. Convert: `python training/convert_checkpoint.py --to-cuda <torch.bin> -o <out>`
   — **mind `--obs-size`** (2782 default = v4; v3 ckpts need `--obs-size 1612`).
   Wrong size = silent garbage; nothing checks it for you (§2).
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

1. **v4 stage-3 (maxdist 12)** when `v4_s2` plateaus on tds-at-maxdist-9 starts.
   Warm-start from newest s2 ckpt; run retention probes at maxdist 6.
2. **Rush-tax adoption decision** (D46 A/B, leaning ADOPT): bp_tax matched/beat
   untaxed pace with 3–5 fewer gfi/ep across D51/D52/D55. Make the call from the
   v4_s2 vs v4_s2tax twins; whatever the verdict, the tax must eventually be
   ANNEALED away (D46), never enshrined.
3. **Native anchor-free parity VERDICT (run is already LIVE — D57).**
   `v4-native-asym` fired 2026-06-08 on box-1: native CUDA, no bc aux, frozen
   bc_v4 selfplay-pool teacher, 2.1M SPS (3× the torch twins on the WEAKEST box).
   Early tds 0.229@0.5B in the stage-2 band. The pending work is the JUDGMENT:
   compare its tds curve vs the torch flagship at matched steps; if parity holds,
   write the ledger entry, make native the default backend, and retire torch to
   bc_vN training only. Do NOT re-launch this experiment from scratch.
4. **Tier-4 box-side OMP/CUDA knobs.** A/B carefully, ONE knob at a time — one
   config showed an 80× regression.
5. **bc_v5 with sequence context** (D35 lever ranking: sequence context first).
6. **Windows 2070 onboarding** (task 22).
7. **Wizards / star players / team-comp backlog** (tasks 23–24).

### Background threads (not queue items, but don't lose them)

- Frozen-opponent ladder: designed, not built — build it if a stage stalls (§5).
- bc_v4 confound (D53): more-data + obs-v4 planes deliberately confounded; if
  decomposition ever matters, train a v3-obs anchor on the same 12K-replay corpus.
- Asymmetric-stop overshoot bug: fix with epoch-based stop or full-width accounting
  (open thread 7) — low priority while benign.
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
- D8 GitHub remote: still deferred/local.

---

## 12. Session checklist

Before doing anything: `vastai show instances --raw` (labels are state; endpoints
change after restarts), check what's running (`tools/fleet.sh status`), read the
tail of DECISIONS.md for anything newer than D57/this skill. Before any launch:
invariants (§4), obs-size sync points (§2), the launcher-default warning + rebuild
discipline (§3), recover live-run flags from the box before resuming. After any
finding: ledger entry (§7), then act.

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
