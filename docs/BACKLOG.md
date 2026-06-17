# bloodbowl-rl — Plan backlog & reasoning (v2, 2026-06-17, post-review)

Revised after triple review (self + adversarial Opus + Codex). Detail/provenance in
`DECISIONS.md`. This states the *prioritization thesis* and *reasoning* so it can be
attacked. **Changelog from v1 at the bottom** — including what I rejected and why.

## The reframe the reviews forced

v1 treated the critical path as "league9 → R12 (build the defensive reward)". Three
findings break that:

1. **R12 may violate the project's own doctrine.** D118 records a NON-MOVE: *"NO
   defensive reward shaping — D67-D69 proved distributions teach and bribes distort;
   defense needed an opponent, not a bounty."* R12 IS a defensive reward bounty. And
   **league9 already runs the doctrine-endorsed alternative** (`--selfplay.league-preseed`,
   `frozen-bank`, `swap-winrate 0.55` = the league-unpinning / growing-opponent
   machinery D118 prescribes for defense). So R12 would bolt the deprecated mechanism
   on top of the endorsed one that's already live. R12 is NOT the next build; it's an
   experiment that must first clear the doctrine.

2. **R6v1 (R12's parent) is probably doing nothing.** D132: league8's R6v1 win is
   confounded with 28B of extra training AND the metric R6v1 prices (`carrier_exposed_full`)
   **never moved** (~3.8 throughout). That is exactly the null the D67-D69 "bribes
   distort/don't help" doctrine predicts. Building R12 (the structural twin) on an
   unproven, possibly-null parent compounds the risk.

3. **The empirically strongest reward lever is being under-weighted.** The aggregate-
   stat-matching reward (statmatch, D114-A) took the **all-time #1 ladder spot**
   (statmatch1 +326.5 at only 5B steps, beating league6's 28B; wins the top-cluster
   head-to-heads outright). v1 buried statmatch3 in "longer-horizon" while foregrounding
   two unproven bounties. That's backwards.

## Resource reality (unchanged, still binding)

One real training box (`bb-japan-native`, running league9) + the owned 2070 rig (5–9×
slower, immune to Vast). The other 3 Vast boxes are gone. **Effectively single-box;
arms serialize.** So the plan must CUT, not just reorder, and push cheap controls to
the otherwise-idle rig in parallel.

## Revised critical path

**Resolve "do reward bounties actually do anything, and is league-unpinning enough for
defense" BEFORE building any new bounty.** Concretely, the next ~4 box-slots:

**1. [RIG, parallel, NOW] R6v1 isolation control.** Matched no-R6v1 28B continuation
from league7b (same warm-start as league8). Zero new code. Read the TREND vs league8 —
don't need full 28B to see if no-R6v1 climbs just as fast. *Resolves:* is R6v1
decoration? If yes, R12 (its dual) is cancelled before a GPU-hour is spent. This is the
gate on item 4, not "debt to pay later." [accepted: Opus H3 + the D118 doctrine]

**2. [japan, in flight] league9 → cap → tournament vs league8 + ladder.** Honest caveat
(M7): league9 bundles THREE changes (R6v1-continuation + swept HPs + warm-start), so its
result attributes to none of them alone — the item-1 control + item-5 ablation do the
attribution. Tournament is still the relative scoreboard; just don't over-claim.

**3. [cheap, parallel] Two grounding gaps the whole reward program rests on:**
   - **(a) An external skill anchor.** Every ladder node is the agent vs a prior version
     of ITSELF (gen1=0 anchor is also a checkpoint). No scripted/human head-to-head
     opponent exists (verified: none in tools/training). The human baseline (D61/D63) is
     a stat-*distribution* reference, not an adversary — AND the one "vs human" proxy the
     project did have (mirror-from-kickoff tds) is now BROKEN: D112-A found it degrades
     precisely as possession_rate rises, so it no longer tracks human-likeness. Risk: the
     population can sit in a shared local optimum (D27 documented a "universal avoidance
     equilibrium") and the self-referential ladder would never show it. FIX: a scripted
     greedy bot (run-to-endzone, cage carrier, mark deepest threat — ~1 day of C) as a
     FIXED ladder anchor. First real absolute "is it getting better at Blood Bowl" signal
     the project would have. [Opus C1 + Codex #7 + D112-A; nuance in rejected list]
   - **(b) A scoped reach/dodge/GFI replay-differential.** R6v1/R12 price dodge/GFI/TZ
     reachability; task #6 (FFB differential) — the layer that would validate exactly
     those mechanics — has been "in progress" the entire training era. Don't boil the
     ocean: replay N FUMBBL games, assert engine dodge/GFI/TZ-occupancy match the
     recorded rolls. Cheap subset of #6 that de-risks the reachability rewards.
     [accepted Opus C2, scoped]

**4. [japan, GATED on 1] R12 — only if it clears two gates.** (i) item-1 shows R6v1
   actually moves a positional metric (bounties work here at all), AND (ii) league9's
   league-mechanism does NOT already fix defensive clumping (measure it — it's running).
   R12 box-build/smoke/telemetry is cheap + default-inert — fine to do anytime; just
   don't count it as "the next experiment." Two corrections to v1's framing:
   - R12 is NOT literally "R6v1's dual" anymore — D133-A superseded the reachability-dual
     with a raw per-player deep-threat count. Its rationale is "defensive deep-threat
     coverage is unpriced," NOT "R6 worked on offense so build the dual" (and R6's own
     metric barely moved, so it lends no credibility). [Codex #2]
   - D121's corpus finding (passing is largely DEAD; ball moves by caged running)
     undercuts the "measure deep receivers" reframe — in a pass-dead meta the original
     lane-denial dual (D133) may be more correct. Also decide R12-as-obs-feature vs
     reward-only (D133-A: the threat flag is naturally an obs feature; reward-only may be
     a weaker, later credit signal). [Opus M8 + Codex #7]

## Promoted (was buried in v1)

**statmatch line (task #56 + beyond).** Empirically the strongest reward lever measured
(ladder #1, D114-A). statmatch3 duration-isolation (mirror +8B→16B on rig) separates
"statmatch helped" from "more training helped" — the SAME isolation discipline item 1
applies to R6v1, applied to the actually-winning lever. This deserves to be near the
top, not the bottom.

## Reward-economy hygiene

**Leave-one-out ablation: drop `rush_cost` and re-ladder.** It's self-described
scaffolding (D46, "never permanent") that was never removed, and D117-A found the GFI
pathology it targets may already be gone. The economy has ~14 hand-set coefficients and
a zero-length "remove" list — that asymmetry is the treadmill. One removal experiment
counterbalances the add-list. [accepted Opus H4]

**Config-truth cleanup (cheap).** D120: the checked-in `bloodbowl.ini` misrepresents the
actual settled economy. Fix it so the repo's default config matches doctrine — a
one-shot edit that prevents a future relaunch from shipping the wrong knobs.

## Standing experimental discipline (adopt as practice, not a one-off) [Codex #4]

The fix for confound-pileup isn't a factorial design; it's labels + a control lane:
1. **Label every arm `recipe verdict` or `causal verdict` BEFORE launch.** Most arms
   (incl. league9) are recipe verdicts — pre-register that wording so the ledger can't
   quietly harden a bundled arm into doctrine.
2. **Each new reward term gets one matched no-term continuation to 8–16B before it
   becomes default.**
3. **Compare against warm-start + immediate predecessor + 2–3 fixed anchors**, not just
   the nearest rival.
4. **Track the reward's own telemetry** — if `carrier_exposed_full` doesn't move while
   strength rises, do NOT claim the R6 mechanism did it.
5. **Freeze or account for live-pool drift** (D128-A: "same pool" only meant same seeds;
   live snapshots diverged per arm).
6. **Intermediate snapshot laddering** (2B/4B/8B/16B/28B) as the cheap diagnostic
   (D130-A already accepted this for statmatch).

## Awaiting Alex's decision (unchanged)

- PufferLib match-mode PR (task #58) — ready, not opened.
- Arm `bb_idle_guard_v2` (task #62) — warn-only; needs sign-off post-autostop-scare.
- Revoke API key 18088829 — optional.
- Full sweep go/no-go.

## Cut / parked (was an aspirational parallel queue v1 couldn't run)

- **REMOVED — native-asym parity (v1 item G):** already SHIPPED and settled. D58/D62/D64:
  "the native architecture is now the production default on scoring AND block-rationality."
  This was a v1 error — it was closed work listed as open. (Live tangent worth noting:
  league9 runs on TORCH at ~0.6M SPS while native does ~2.1M at parity — the league
  lineage may be needlessly 3.4× slow; worth a migration check, NOT a "parity verdict".)
- **DOWNGRADED — bc_v5 sequence-context (D):** moved OUT of the reward spine to "BC
  research." v1 called anchor quality "the binding constraint (D45/D47)" — that's
  BACKWARDS: D47 explicitly REFUTES it ("the anchor was never the binding constraint")
  and ranks **backplay curriculum ABOVE** bc_v5 sequence-context. So if anything in this
  area is mainline, it's backplay-curriculum levers, not a multi-day BC retrain. [Codex
  #8 — corrects a v1 error of mine]
- **REMOVED — v5 macro-moves (E):** SETTLED, not parked. D93: "THE MACRO QUESTION
  SETTLED: v4 stepwise WINS the deciding tournament at matched contested caps — macro
  path-actions are RETIRED as a training lineage." v1 (and my push-back on the Opus
  review) wrongly called it "re-opened" off stale D90/D91; D93 closed it. Keep v5 caps
  only as opponent/diversity artifacts, not as R&D. [Codex #8 — corrects a v1 error]
- **DEFERRED — Tier-4 OMP/CUDA knobs (H):** 80× regression risk, no urgency.
- Inducements/wizards/stars (task #23), team-comp (task #24): parked until the reward
  economy settles.

## What I REJECTED from the reviews (didn't just accept)

- **Opus "no absolute signal at all" (C1) — softened.** A human stat-distribution
  baseline DOES exist (D61/D63) and the statmatch reward that targets it is the ladder
  #1 lever — so the project is not flying fully blind on "human-like." The real gap is a
  head-to-head EXTERNAL OPPONENT, not absolute grounding wholesale. Added the scripted
  bot for that specific gap; did not adopt the stronger "everything is self-referential
  and possibly worthless" framing.
- **"Build the full FFB differential now" — rejected as scoped.** Full headless-FFB
  differential is weeks; the reward program only needs the reach/dodge/GFI subset (3b).
- **NOTE — I previously rejected Opus's "v5-macro is settled" and was WRONG.** Codex
  showed D93 explicitly settled it (v4 stepwise won the deciding tournament); I'd
  pushed back off the stale D90/D91 CLAUDE.md summary. Corrected above — this is the
  clearest case of the triple-review catching MY error, not the plan's.

## Small ops items the reviews surfaced

- **Disk/checkpoint integrity monitor.** D102-B + D132 both lost work to disk-full
  silently corrupting checkpoint writes. The plan only said "keep checkpoints fresh" —
  add an actual free-space gate to the heartbeat (japan currently 81%).
- **Config-truth cleanup** (D120) — see hygiene section.

## Changelog

**v1→v2:** Promoted R6v1 isolation control (was "debt", now the gate) + statmatch line.
Demoted R12 (gated experiment, not #2 build). Removed native-asym parity (shipped).
Added external opponent, scoped reach-differential, rush_cost ablation.

**v2→v3 (post-Codex):** Corrected TWO of my own errors — v5-macro is SETTLED by D93 (not
re-opened), and D47 REFUTES "anchor is the binding constraint" (bc_v5 downgraded, backplay
curriculum ranked above it). Added the standing experimental discipline (recipe-vs-causal
labels, no-term controls, telemetry tracking, pool-drift accounting, snapshot laddering),
config-truth cleanup, disk monitor, R12-obs-feature decision, and the D112-A fact that the
only "vs human" eval proxy is now broken. Reframed R12 as no-longer-literally-R6v1's-dual.
Three reviewers independently converged on: control-before-R12, R12-reverses-doctrine,
native-already-shipped, scoped-validation-before-trusting-reachability-rewards.
