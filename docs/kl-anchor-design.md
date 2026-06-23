# Preserving the Human Defensive Prior Through RL — KL-Anchor Experiment Design

**Status:** DESIGN (not yet launched). Author pass 2026-06-23. Lever chosen by Alex: "do 1, lean in" — keep a KL/BC anchor to the human policy *through* RL to stop/reverse the champion's defensive-prior erosion (turnover3 ignores the ball carrier on defense; D170).

**One-line thesis:** The champion (`turnover3`) trained anchor-free in self-play (`bc_coef=0` lineage, D57/D58) and pruned its human-cloned defensive behavior as "wasted entropy." We re-introduce a human anchor that is held *persistently* through RL (no anneal-to-zero) and measure whether it prevents (control) and reverses (treatment) the D170 defensive leak (champion concedes ~2× a scripted bot on defense), at acceptable offensive cost.

---

## PART A — Technique (web + reasoning)

### A.1 Two anchor forms, and which one actually prevents drift

**(a) Auxiliary BC cross-entropy on logged human (obs, action) pairs — what we already have.**
`torch_pufferl.py` (the local BC-regularized-PPO patch, lines ~124–176 / 399–415 / 529–539 / 643–654) adds, to every PPO minibatch, a masked 3-head cross-entropy on a fresh random sample of human pairs:
```
loss = pg_loss + vf_coef*v_loss − ent_coef*entropy + bc_coef * CE(pi_RL(obs_human), a_human)
```
The CE is evaluated at **zero recurrent state** (`_bc_loss_and_acc`, L210–221: `state = policy.initial_state(...)` then `forward_eval`), i.e. iid / no-memory, matching `bc_pretrain.py` v0. The states scored are **exactly the states in the human replay corpus** (`validation/pairs_v4`, 2.09M pairs).

**(b) Persistent KL penalty `KL(pi_RL ‖ pi_BC_frozen)` on the policy's OWN visited states — AlphaStar / piKL.**
Here the anchor term is computed on the states the RL policy actually *visits* during self-play rollout, by penalizing divergence from a *frozen* copy of the supervised (BC) policy:
```
loss = pg_loss + ... + kl_coef * KL( pi_RL(s_visited) ‖ pi_BC_frozen(s_visited) )
```

**Why this distinction is the whole experiment.** The behavior we are trying to preserve — marking/screening the ball carrier on defense — is something humans *do*, but it appears in the exact logged replay states only sparsely and in a form the iid BC head already saturates at ~0.45–0.51 exact (D172/D174: corpus is data-saturated and obs-context-rich; the BC ceiling is recipe, not data). Crucially, the *off-distribution self-play states where the champion currently neglects the carrier* (the deep-safety / lane-walling decisions that D170 shows it gets wrong) are **not** densely represented in the human corpus. So:

- **CE-on-pairs (a)** only ever constrains the policy on *corpus* states. It cannot directly punish a bad defensive choice in a self-play state that the corpus doesn't contain. It anchors the *function* on the human manifold and hopes generalization carries to visited states. D27 is the evidence it *can* matter (10B self-play eroded the prior; the anchor was built to stop that), but it constrains the wrong support for the specific failure.
- **KL-to-frozen (b)** constrains the policy on **all visited states, including the off-distribution self-play states** where erosion happens. This is exactly the support where the carrier-neglect lives. This is why AlphaStar called the persistent KL-to-supervised **"critical"** — it both aids exploration and *preserves strategic diversity / human behaviors that pure reward would prune* ([AlphaStar, Nature 2019](https://storage.googleapis.com/deepmind-media/research/alphastar/AlphaStar_unformatted.pdf); [The Gradient summary](https://cyk1337.github.io/notes/2019/07/21/RL/DRL/Decipher-AlphaStar-on-StarCraft-II/)). piKL ([Bakhtin et al. 2022 ICLR'23, *Mastering No-Press Diplomacy via Human-Regularized RL and Planning*](https://arxiv.org/pdf/2210.05492); [Jacob et al. 2022, *Modeling Strong and Human-Like Gameplay with KL-Regularized Search*](https://proceedings.mlr.press/v162/jacob22a/jacob22a.pdf)) makes the same move: a per-state penalty `λ·D_KL(π ‖ τ_anchor)` against a fixed BC anchor τ, applied at the states the agent actually reasons about, producing strong-yet-human play. MimicBot ([Pratidhwani et al. 2021, *Combining Imitation and RL to win Bot Bowl*](https://arxiv.org/abs/2108.09478)) — notably *in Blood Bowl* — keeps a BC loss live *during* RL as a hybrid objective and is the existence proof that the hybrid beats pure-RL-from-weak-prior in this exact game.

**Recommendation (A.1).** The CE-on-pairs anchor we already have is **likely insufficient on its own** for the *specific* erosion we're fighting, because the failure lives in self-play-visited states that are off the human-corpus support, and CE never touches those states. The theoretically-correct lever for "prevent erosion of a behavior humans do but that rarely appears in the exact replay states" is **KL-to-frozen on visited states (b)** — this is precisely the AlphaStar/piKL design. **BUT**: (b) does not exist in our code and must be built (~a day of torch work, see Part C / §6), whereas (a) exists, is free to launch, and D27 already shows it does *something* against erosion. So the staged recommendation is:

1. **First run the persistent CE-on-pairs arm** (free; tests whether the *cheap* anchor, held strong-and-persistent rather than annealed to 10%, is enough — D47 never tested "strong + persistent," only "off," see B.4). If it restores defense at acceptable offensive cost, we are done without building anything.
2. **Only if persistent-CE underperforms** (defense doesn't recover, or recovers but generalizes poorly because it only anchored corpus states) **build KL-to-frozen** and run it as the principled fix. The frozen self-play enemy forward pass already in the rollout (`frozen_policy`, L368/L463–470) gives us a partial scaffold to compute a frozen-anchor distribution on visited states (see §6 caveat — it's the enemy, not necessarily the BC anchor, so this needs a dedicated frozen-BC handle).

This staging is deliberately the cheapest-decisive-first ordering the project's own doctrine prefers (D140: prove the cheap lever before building the expensive twin).

### A.2 Coefficient & schedule

**piKL λ:** the Diplomacy work uses **λ ≈ 10⁻³** for the KL-to-anchor term, with distributional-λ (DiL-piKL) sampling λ per iteration for robustness ([Bakhtin 2022](https://arxiv.org/pdf/2210.05492)). Note this λ multiplies a KL measured in nats per decision against a *search/regret* objective, so it is **not** directly transferable to our PPO loss scale — treat it as "small but never zero," not as a literal coefficient.

**AlphaStar KL weight:** a fixed KL cost toward the supervised policy held *throughout* RL (persistent, not annealed away), used both for exploration and to retain human behaviors. The operative property is *persistence*, not the exact magnitude.

**Our current schedule (the thing under test):** `bc_coef=1.0`, cosine-annealed to `bc_coef_floor*bc_coef0` with `bc_coef_floor=0.1` (10%) over `total_timesteps` (config L241–248; anneal logic L532–538). So today's anchor *decays to a 10% floor* — it weakens exactly as self-play gets long enough to erode the prior.

**Recommendation (A.2):** For this experiment, **the persistent floor is the right call** — set `bc_coef_floor=1.0` (no anneal: constant strong anchor) or close to it, mirroring AlphaStar's "persistent KL was critical." Concretely:
- **Treatment arm coefficient:** `bc_coef=1.0`, `bc_coef_floor=1.0` (constant 1.0) — the settled v4 anchor magnitude (CLAUDE.md reward economy) but **held**, not decayed. This is the minimal-change "lean in" config.
- If 1.0-constant visibly cripples offensive RL improvement (watch tds_t0 / win-rate, see §5), fall back to `bc_coef=0.5, floor=1.0` — still persistent, half strength — rather than re-introducing anneal. Persistence is the hypothesis; magnitude is the knob.
- **Do NOT use the cosine-to-10% default** for any treatment arm — that schedule is the thing D174/D172 named as the erosion enabler ("stop annealing to zero so self-play stops eroding the prior").

The riskiest assumption here (flagged for reviewer): that `bc_coef=1.0` *constant* on the iid CE term is a strong enough pull to overcome PPO's reward gradient on off-corpus defensive states. It may not be — that's exactly the A.1 case for KL-to-frozen.

---

## PART B — Codebase + prior results

### B.3 How the existing CE anchor works (exactly)

- **Where:** local patch in `vendor/PufferLib/pufferlib/torch_pufferl.py`. Config defaults in `puffer/config/bloodbowl.ini` L241–248 (`bc_coef=0.0`, `bc_pairs_dir=validation/pairs`, `bc_batch=512`, `bc_coef_anneal=1`, `bc_coef_floor=0.1`). Patch mirror: `training/torch_pufferl_bcreg.patch`.
- **What it computes:** every PPO minibatch, sample `bc_batch=512` human pairs uniformly at random (L646–651), forward them through the *current* policy, and add `bc_coef * masked_3head_CE` to the PPO loss (L652). `bc_loss`/`bc_acc`/`bc_coef` are exported to dashboard/wandb.
- **iid / zero recurrent state:** `_bc_loss_and_acc` (L210–221) calls `policy.initial_state(...)` then `forward_eval` — the human pairs are scored at **zero recurrent state (no memory)**, identical to `bc_pretrain.py` v0. So the anchor constrains the *single-frame* policy, not the recurrent rollout policy. (D174 showed single-frame is fine for BC accuracy — but note it means the anchor never sees the LSTM-carried context the RL policy uses in rollout.)
- **Torch-only:** the term is added inside the torch trainer. The forward uses `policy.forward_eval`, which under DDP binds to the unwrapped module — the BC anchor is single-process only (L146–148).
- **Native/CUDA backend has NO anchor — confirmed.** `grep -niE 'bc_coef|bc_loss|anchor|cross.?entropy|imitation|frozen.?bc' vendor/PufferLib/src/pufferlib.cu` → **empty**. The native backend cannot run any human anchor; all anchored training is torch-only. (This is consistent with D57/D58: native = anchor-free RL stages, torch = bc_vN + aux-research only.)
- **Bit-identical-when-off:** `bc_coef==0.0` performs no tensor ops and consumes no RNG (L143–144, L401–402) — the anchor-OFF control is genuinely upstream behavior.
- **The `frozen_policy` in the rollout (L368, L463–470) is the self-play frozen ENEMY, not a KL anchor.** It selects actions for non-learner rows; nothing computes a divergence against it. A KL-to-frozen anchor would need its own frozen-BC handle + a per-visited-state KL term (does not exist).

### B.4 Reconciling D45/D47 with the NEW question

- **D45** ("the prior is the bottleneck"): with a *frozen weak BC anchor pinned*, the learner (10B vs a non-adapting defense) showed behavioral divergence but couldn't convert to wins; concluded the 0.40-exact prior itself is the ceiling.
- **D47** ("anchor release verdict: NO breakout, NO collapse"): released the anchor (`bc_coef 0.5 → 0.000` cosine, ~6B continuation). `bc_acc` *held* ~0.39–0.42 even at `bc_coef<0.1` (PPO updates too local to leave the basin), tds unchanged, tournament identical to anchored. Conclusion: *the anchor was never the binding constraint — removing it caused no breakout and no collapse.*

**Why D47 does NOT close our question.** D47 asked **"does removing the anchor let the policy break OUT (improve)?"** — answer: no. Our question is the *opposite direction and a different observable*: **"does a STRONG, PERSISTENT anchor PREVENT/REVERSE defensive erosion?"** Three reasons D47 is silent on this:
1. **Direction:** D47 weakened the anchor toward zero and watched for *gains*. We *strengthen* it and watch for *retention/recovery of a specific behavior*. "Removing it didn't help offense" says nothing about "keeping it strong protects defense."
2. **Observable:** D47's readout was `tds`/tournament *offense/win* metrics and aggregate `bc_acc`. It never measured **defensive conceding** (tds_t1 vs a competent attacker — that telemetry didn't exist until D170). Erosion of defense is invisible in D47's instruments.
3. **Regime:** D47 ran *vs a non-adapting frozen defense* in the symmetric/asym v4 economy. The erosion we care about (D170) is a product of *self-play reaching a mutually-incompetent equilibrium where no opponent punishes carrier-neglect*. D47's opponent structure can't surface it.

**What WOULD close it:** an A/B where (control) reproduces the erosion (anchor-OFF, the D57/D58 recipe) and (treatment) holds a strong persistent anchor, **both measured on tds_t1 vs the competent cage-bot** (the D170/D173 instrument). That is this design.

**Supporting facts to hold:**
- **D170:** champion concedes `tds_t1=1.156` on defense vs the scripted cage-bot, while the bot's own defense concedes only `0.565` — champion is ~2× leakier; the "untrained on defense" erosion is empirically real and scoreboard-measurable.
- **D173:** `defense1` (warm champion vs cage-bot, no anchor, no new reward) pulled `tds_t1 1.156 → 0.718` (−38%) — *opponent quality alone* moves defense — but it was **confounded** (pre-fix bot, zero-biased warm-start, single deterministic opponent) and **saved no checkpoint** (no snapshot interval — the lesson we fix here).
- **D174:** the BC ceiling is *recipe/representation*, not data or temporal context (frame-stacking ≈ null; obs-v4 already context-rich). Implication: we should NOT expect a *better BC head* to fix this; the lever is keeping the existing prior *live through RL*, which is exactly the anchor-persistence hypothesis.
- **Lineage `bc_coef=0`:** the entire native block-economy lineage that produced turnover3 trained anchor-free (D57/D58). So "champion has eroded prior" is the expected outcome of its own recipe, and "anchor-OFF control reproduces erosion" should be a near-trivial reproduction.

---

## PART C — The Experiment Design (the deliverable)

### C.5 The concrete A/B

**Common setup (all arms):**
- **Warm-start:** `turnover3_torch.bin` — the torch-converted champion (`training/convert_checkpoint.py --to-torch`, hidden 512×3, obs 2782; **biases zero-filled** per D170-corr/D45 native↔torch limit, so the first frames re-learn biases — hold this as a confound, see risks).
- **Backend:** **torch `--slowly`**. Mandatory: the anchor is torch-only (B.3), AND the native guard (`pufferl.py:191`) rejects `scripted_opponent + learning` because native lacks the scripted-row exclusion. Torch `--slowly` has the scripted-row filter the cage-bot option needs.
- **Anchor corpus:** `validation/pairs_v4` (2.09M pairs; `pairs` symlink on v4 boxes / `bc_pairs_dir=validation/pairs`). bc_v4 anchor (val exact 0.508).
- **Reward economy:** the settled v4/block economy **unchanged** — NO new reward terms (this isolates the anchor as the only manipulated variable; defensive *shaping* is a separate, doctrine-gated lever per D118/D90 and is explicitly out of scope here).
- **Opponent:** **scripted cage-bot = team1** (the FIXED offense_bot, `150a1fb`, D173 clean re-run config), learner = team0 plays full games including defending the bot's drives. Rationale: the cage-bot is the *competent attacker* that exposes the defensive hole, and tds_t1 against it is our calibrated instrument (D170 baseline 1.156, bot's own floor 0.565). **Self-play is NOT used as the primary opponent** because (i) self-play is *what caused* the erosion (mutually-incompetent equilibrium, D170) so it's a poor test bed for *preventing* it, and (ii) the cage-bot gives a fixed, comparable conceded-TD scale across arms. (Optional third arm vs self-play below.)
- **Checkpointing:** **`--train.checkpoint-interval` SET explicitly** (e.g. every ~250M steps) and back the final cap to Mac — D173's hard lesson: no snapshot = trained defender lost. This is non-negotiable for a keeper run.
- **Step budget:** **4B effective learner-steps** per arm (mirrors defense1/defense2 sizing; ~4–4.5h @ ~250K SPS torch on a 64c box). Long enough to pass bias-recovery and reach a tds_t1 plateau (D171 saw movement by 31M; plateau read needs the full budget).

**Arms:**

| Arm | bc_coef | bc_coef_floor (anneal) | Purpose |
|-----|---------|------------------------|---------|
| **A0 — anchor-OFF control** | 0.0 | n/a | Reproduce erosion: warm champion vs cage-bot, no anchor. Expected: tds_t1 behaves like D173 (driven by opponent quality alone, ~0.72) and `bc_acc` is NOT held high. This is the D57/D58 anchor-free recipe and the baseline the treatment must beat *on defense retention*. |
| **A1 — anchor-ON persistent (primary treatment)** | 1.0 | **1.0 (constant, no anneal)** | The "lean in" config: strong human anchor held persistently through RL. Hypothesis: defense recovers *at least as well* as A0 AND the human defensive prior (carrier marking/screening) is retained/restored rather than pruned. |
| **A2 — anchor-ON half (fallback, launch only if A1 cripples offense)** | 0.5 | 1.0 (constant) | Persistent but weaker, in case 1.0-constant tanks offensive learning. |
| *(optional)* **A3 — anchor-ON persistent vs SELF-PLAY** | 1.0 | 1.0 | Does the persistent anchor prevent erosion in the *native failure regime* (self-play)? Torch self-play, no cage-bot. Secondary — answers generalization, but lacks the clean tds_t1 scale. |

Minimum viable experiment = **A0 vs A1**. A2/A3 are contingent.

**MEASUREMENT — how we detect "human defensive prior preserved/restored":**

1. **Primary scoreboard metric — `tds_t1` vs the fixed cage-bot (D170/D173 instrument).** Conceded TDs per episode when the bot attacks the learner's defense. Reference points: champion frozen baseline **1.156** (D170), opponent-quality-only **~0.718** (D173), bot's own defensive floor **~0.565** (the theoretical best). **Success direction: A1's tds_t1 ≤ A0's tds_t1**, ideally approaching 0.565, with the gap *attributable to the anchor* (since opponent is identical, A0 already captures the opponent-quality effect — any *additional* drop in A1 is the anchor preserving defense).
   - **Critical:** run this as a *frozen eval* at the same checkpoints for both arms (load each saved ckpt, freeze lr=0, run n≥300 dashboard frames vs the cage-bot, exactly as D170) so the conceded-TD number is comparable and not a moving training-time artifact.
2. **Behavioral defense telemetry — the def-canary fields.** `bloodbowl.h:209–213` already *computes* in-env: `def_deep_safety`, `def_carrier_path_zerotz`, `def_carrier_min_dodges`, `def_carrier_marked_frac` (ep_* sums L500–504). **These are NOT yet wired to the Log struct/dashboard** (D170 mechanism note). Wiring them is a **deferred nice-to-have that becomes load-bearing here** — `def_carrier_marked_frac` is the *direct* readout of "does the policy mark the ball carrier on defense," i.e. the exact behavior we claim is eroded. **Recommend wiring these to the dashboard before the keeper run** so the verdict rests on mechanism (is the carrier marked?) not only scoreboard (tds_t1). If wiring slips, the scoreboard still settles the question (as D170 did) — but the mechanistic readout is what distinguishes "anchor restored *marking*" from "anchor coincidentally lowered conceding."
3. **Offensive cost — `tds_t0` and win-rate.** The anchor must not cripple offense. Track `tds_t0` (champion offense vs bot defense; champion baseline ~0.565, D170; defense1 dipped to ~0.474, D173). **Cost guardrail:** A1's tds_t0 should not fall materially below A0's. The real strength scoreboard is a **kickoff-start tournament** (D50/D56 graduation rule): after the keeper run, convert A1 and A0 to CUDA and run `puffer match ... --num-games 4096`; read the decisive split, not the draw rate. A1 winning or drawing decisively vs A0 = anchor preserved defense *without* costing net strength.
4. **`bc_acc` trace.** A0's `bc_acc` should drift/erode (anchor-free); A1's should *hold* near the bc_v4 ceiling (~0.45–0.51) throughout — the direct evidence the prior is retained on-corpus. (Necessary but not sufficient — D47 showed bc_acc can hold while the visited-state behavior still differs; that's why #1/#2 are primary.)

**Success criterion (pre-registered):**
> **A1 (persistent anchor) achieves frozen-eval `tds_t1` at least as low as A0, AND retains `def_carrier_marked_frac` materially above A0's (if wired), AND does not lose a 4096-game kickoff tournament to A0 on offense.**
> Strong success: A1 `tds_t1` → toward the bot's 0.565 floor with marked_frac approaching human levels, at ≤ small tds_t0 cost.
> Null result that still informs: if A0 and A1 converge on tds_t1 *and* marked_frac (anchor changes nothing measurable), then the iid CE-on-pairs anchor is insufficient for this erosion → **escalate to building KL-to-frozen (A.1 step 2)**, which is the project's actual recommended next lever.

### C.6 What code (if any) must be built

**Primary A/B (A0 vs A1, vs A2): PURE CONFIG/LAUNCH — no code build required.**
The CE anchor exists, `bc_coef`/`bc_coef_floor` are live config, torch `--slowly` supports the scripted cage-bot, and `turnover3_torch.bin` already exists (or is one `convert_checkpoint.py --to-torch` away). The only thing that *should* be built first (strongly recommended, not strictly required) is **wiring the def-canary fields to the Log/dashboard** (`bloodbowl.h:209–213` → Log struct → dashboard) so the mechanistic readout exists — small, localized C/binding change.

**KL-to-frozen (only if the primary A/B returns the null): MUST BE BUILT.**
There is no KL-to-frozen-anchor term in either backend. Building it (torch-only) means: (1) instantiate a frozen BC-anchor policy handle distinct from the self-play `frozen_policy` enemy (the existing `frozen_policy` is the enemy, not the BC anchor — do NOT reuse it naively); (2) during rollout or at train time, forward visited-state obs through the frozen BC anchor; (3) add `kl_coef * KL(pi_RL ‖ pi_BC_frozen)` over visited states to the loss, persistent (no anneal). ~1 day of torch work + a review loop. Native backend would remain anchor-free (out of scope). **Recommendation: do NOT build this preemptively** — run A0/A1 first (D140 cheap-lever-first doctrine).

### Exact launch commands (mirroring defense1, WITH checkpoint interval this time)

Run on a torch-capable box from `~/bloodbowl-rl`, after `. tools/cpu_cap.sh` (footgun #11). Copy the live command of a defense twin and change only anchor/tag/bc knobs (footgun #6 — do NOT trust `run_synthesis_c.sh`'s baked-in synthesis-C economy; the trailing args below override the full settled v4 knob set, last-wins). **Confirm `turnover3_torch.bin` exists on the box** (`training/convert_checkpoint.py --to-torch turnover3_cap.bin -o training/turnover3_torch.bin --obs-size 2782`) and the cage-bot offense_bot build is the FIXED `150a1fb`.

```bash
# ---- A0: anchor-OFF control (reproduce erosion) ----
. tools/cpu_cap.sh
ANCHOR=training/turnover3_torch.bin LOG=/tmp/defense_a0.log STEPS=4000000000 \
  bash tools/run_synthesis_c.sh \
  --slowly \
  --env.scripted-opponent 1 \
  --train.checkpoint-interval 250000000 \
  --train.bc-coef 0.0 \
  --env.reward-ball-loss 0 --env.reward-ball-gain 0.05 --env.reward-possession 0.03 \
  --env.reward-dist-ball 0.05 --env.reward-dist-endzone 0.2 \
  --env.k-kd 0.03 --env.k-value 0.25 --env.k-ball 0.15 --env.k-seq 0.01 \
  --train.learning-rate 0.00028 --train.ent-coef 0.009 \
  --tag defense_a0_anchoroff

# ---- A1: anchor-ON persistent (primary treatment) ----
#  bc_coef=1.0 held constant: bc_coef_anneal 0 (no cosine) => floor irrelevant,
#  but set floor 1.0 too for belt-and-suspenders if anneal is forced on.
. tools/cpu_cap.sh
ANCHOR=training/turnover3_torch.bin LOG=/tmp/defense_a1.log STEPS=4000000000 \
  bash tools/run_synthesis_c.sh \
  --slowly \
  --env.scripted-opponent 1 \
  --train.checkpoint-interval 250000000 \
  --train.bc-coef 1.0 --train.bc-coef-anneal 0 --train.bc-coef-floor 1.0 \
  --train.bc-pairs-dir validation/pairs \
  --env.reward-ball-loss 0 --env.reward-ball-gain 0.05 --env.reward-possession 0.03 \
  --env.reward-dist-ball 0.05 --env.reward-dist-endzone 0.2 \
  --env.k-kd 0.03 --env.k-value 0.25 --env.k-ball 0.15 --env.k-seq 0.01 \
  --train.learning-rate 0.00028 --train.ent-coef 0.009 \
  --tag defense_a1_anchorpersist
```

> **VERIFY the exact flag spellings against a live defense twin's command line before launch** (`ps aux | grep 'puffer [t]rain'` or `head /tmp/defense1.log`). The CLI maps `bc_coef_anneal`/`bc_coef_floor` config keys to `--train.bc-coef-anneal`/`--train.bc-coef-floor`; if a key isn't exposed on the CLI, set it in `puffer/config/bloodbowl.ini` instead. The script prints LIVE/TRAINER DIED at ~40s — read it. Confirm `Loaded N demo states` and bank byte-size (footgun #13), and that the dashboard shows `bc_loss`/`bc_acc` nonzero for A1 and absent/zero for A0.

**Frozen eval (run on saved checkpoints of BOTH arms, mirroring D170):**
```bash
# load ckpt, lr=0, scripted cage-bot=team1, n>=300 dashboard frames, read tds_t0/tds_t1
# (use the same def-canary build as D170; capture def_carrier_marked_frac if wired)
```

**Tournament (final exam, on box-1 judge GPU):** convert both arms' best ckpts to CUDA (`convert_checkpoint.py --to-cuda --obs-size 2782`, equal treatment per D45), `puffer match bloodbowl --load-model-path A1_cuda.bin --load-enemy-model-path A0_cuda.bin --num-games 4096`, read the decisive split.

---

## Riskiest assumptions (flagged for the reviewer)

1. **[HIGHEST] iid CE-on-pairs may simply not reach the eroded states.** The whole A.1 argument says the failure lives in off-corpus self-play states that the CE term never scores. If true, A1 ≈ A0 on `tds_t1`/`marked_frac` and the experiment's *primary* value becomes the green light to build KL-to-frozen. The A/B is designed to *detect* this (the null is informative), but the reviewer should be clear we may be running the "wrong" anchor first on purpose (cheap-first). Decide explicitly whether to skip straight to KL-to-frozen.
2. **Zero-biased warm-start confound (D170-corr).** `turnover3_torch` has zero-filled biases; the first frames re-learn them. This conflates bias-recovery with anchor/defense effects early. Mitigation: read the *plateau* past bias-recovery (D171 caveat), and A0/A1 share the identical handicap so the *contrast* is still clean.
3. **Single deterministic opponent → overfitting (D171 caveat (c)/D173 confound 3).** Both arms vs the same cage-bot risks "learned to beat this bot," not "learned defense." Mitigation: the *contrast* A1−A0 is still valid for the anchor question; validate the winner later vs held-out anchors / self-play (A3). Do not claim "general defense" from this A/B alone.
4. **`bc_coef=1.0` constant may cripple offensive RL.** Persistent strong anchor could pin the policy and tank `tds_t0`/tournament strength (the D45 "anchor holds policy at teacher level" worry). Mitigation: the tds_t0 guardrail + the A2 fallback (0.5 constant). If even 0.5-constant cripples offense, that itself is a finding (the prior and the reward objective genuinely conflict on defense, motivating KL-to-frozen which constrains more surgically per-state).
5. **def-canary not wired → verdict rests on scoreboard only.** If we don't wire `def_carrier_marked_frac`, we infer "prior restored" from tds_t1 alone, which can't distinguish *marking the carrier* from *some other defensive change* that lowers conceding. Mitigation: wire it (small change) before the keeper run; D170 shows the scoreboard alone is *sufficient to settle the leak question* but not the *mechanism*.
6. **`bc_acc` holding ≠ behavior preserved (D47).** D47 showed `bc_acc` can stay ~0.40 while visited-state play is unchanged. So a high A1 `bc_acc` is necessary-not-sufficient evidence; weight #1/#2 over #4.
7. **Checkpoint-interval / cap-to-Mac discipline (D173 lesson).** If the interval isn't set or the cap isn't shipped to Mac, a successful run produces no keeper and the result evaporates. This is an *operational* risk that already bit once — verify the interval is in the live command and that ckpts are landing on disk before walking away (footgun #12: gate liveness on log mtime + `pgrep -xc puffer`).

---

### Sources
- AlphaStar (persistent KL-to-supervised "critical"): [Nature 2019 PDF](https://storage.googleapis.com/deepmind-media/research/alphastar/AlphaStar_unformatted.pdf) · [The Gradient summary](https://cyk1337.github.io/notes/2019/07/21/RL/DRL/Decipher-AlphaStar-on-StarCraft-II/)
- piKL / human-regularized RL (λ≈10⁻³ anchor): [Bakhtin et al. 2022, ICLR'23 — Mastering No-Press Diplomacy via Human-Regularized RL and Planning](https://arxiv.org/pdf/2210.05492) · [Jacob et al. 2022 — Modeling Strong and Human-Like Gameplay with KL-Regularized Search](https://proceedings.mlr.press/v162/jacob22a/jacob22a.pdf)
- MimicBot (hybrid BC-during-RL, in Blood Bowl): [Pratidhwani et al. 2021 — Combining Imitation and RL to win Bot Bowl](https://arxiv.org/abs/2108.09478)
- Internal: `DECISIONS.md` D27, D45, D47, D57/D58, D118/D90, D140, D170/D170-corr, D171, D172, D173, D174 · `torch_pufferl.py` (BC patch L124–176/210–221/399–415/463–470/529–539/643–654) · `puffer/config/bloodbowl.ini` L241–248 · `vendor/PufferLib/src/pufferlib.cu` (no anchor — grep-confirmed)
