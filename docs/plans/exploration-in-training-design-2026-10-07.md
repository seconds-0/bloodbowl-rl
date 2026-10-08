# Exploration in training: design study (2026-10-07, 19:50 PDT)

**Status: a design study by an agent on the session model. Nothing here is registered, nothing ran on the rig, no cloud resource was touched, and Codex has not reviewed it. Every measurement made for it is exploratory: no plan was committed before any of them, they are a few dozen games on the Mac, and they use one checkpoint unless stated. They decide what to measure properly next, not what to adopt.**

Sources used below, by short name:
- **Trainer.** PufferLib at commit `f14b71c` (the commit of the Mac's vendored trees; `vendor/PINS.md` names another one) with the five patches of the screen's bundle that touch `src/`, applied in bundle order (`tools/run_reward_screen.sh:893-915`) to a scratch copy. "patched `pufferlib.cu:N`" is a line in that copy. The patches and launchers are unchanged between the rig's commit `fc25468` and this worktree's head (`git diff --stat`, only stage wrappers differ). I did not see the rig's installed tree.
- **Search screens.** The search probe's existing records, `/Users/alexanderhuth/Code/bb-play-harness/.play-artifacts/search-diag-20261007/` (`run1/roots.jsonl`, 240 roots at 128 rollouts; `tail1` and `tail2` `screen.jsonl`, 2,010 roots at 16 rollouts; chain 55 + m1 in self-play). Re-read here by `sat_share.py` and `price_of_exploring.py`.
- **Head probe.** `head_sat_probe30.py`: 30 plain self-play games per checkpoint (seeds 29930000 to 29930029), every own decision of side 0 with two or more legal joint actions. Chain 55 unless stated: 10,593 decisions.
- **End probe.** `end_turn_probe2.py`: 40 plain self-play games of chain 55, no mask (seeds 29950000 to 29950039), 32 rollouts per candidate through the search probe's own `Rollouts.evaluate` (shaped return to the end of the searcher's team turn plus the value output, gamma 0.999, common random numbers). Intervals are 95% bootstraps over games.
- Scripts and outputs are in `/private/tmp/claude-501/-Users-alexanderhuth/3154e4ea-fc69-4ad8-9862-ba7ced2d5c60/scratchpad/explore-design/`. That directory does not survive a restart. The operator copied the scripts and text outputs to `docs/plans/exploration-design-2026-10-07/` beside this file and the whole directory (root records and the reconstructed trainer tree included) to `/Users/alexanderhuth/Archives/bb-explore-design-20261007/`. The harness worktree `bb-harness-search` was only read and is still clean at `06f0a5f`.

## Recommendation

1. **Do not register an exploration rung yet, and do not spend a rung on the entropy knob.** The entropy bonus has exactly zero gradient at a saturated decision in this trainer (section 1), so `LADDER_CHAIN_ENT_SCALE` cannot reopen one. It only softens the decisions that are already open.
2. **The hypothesis is half right.** Right: the search's large gains sit at actions the policy never samples, and PPO would see them in one sample if it took one. Wrong: that this explains the three-activations plateau. At the decisions where the policy ends its turn, its own objective says ending is correct, and where it declines a block the block is a bad one under that objective. The plateau is what the objective and the critic ask for. Exploration noise would push it the wrong way.
3. **The proposal as worded, a uniform mix with the exact mixed log-probability stored, gives the policy no learning signal at saturated decisions.** This is arithmetic, not a bug: with exact on-policy accounting the gradient on a logit is its probability times its advantage, and the probability is zero. An exploration scheme must also change the update so that it does not scale with the action's probability. That makes it a biased algorithm or a regulariser, and both need a rebuild.
4. **First, two cheap tests off the rig (section 4):** whether the search's tail is learnable at all from a few thousand examples (about $1, decisive for every exploration design), and a registered-size repeat of the end probe on chains 49, 55 and 58.
5. **If the tail is learnable, the rung I would register first** is "probe exploration" at 1% on a new build, against chain 55 or chain 58 as an existing control (section 5). I expect Flat or Inconclusive on the gate; the measurement I want from it is whether the search finds less to fix in the trained checkpoint.

## Where the framing is wrong, and what was missed

1. **"At saturated decisions PPO cannot discover the alternative" is true, but sampling is only half of the reason.** Three things must hold for training to learn an action: it is sampled, its advantage estimate has the right sign, and the update can move probability toward it at a rate that does not vanish. The hypothesis covers the first. The third fails independently (section 1, items 2 and 6).
2. **"The trainer's V-trace clips already correct for off-policy sampling" (LOGIT_SCALE_NOTE) is wrong for this trainer.** The importance weights are set to 1.0 at the start of every train call (patched `pufferlib.cu:1686-1687`) and are replaced only for rows a minibatch has already trained (`:1816-1822`). They correct for policy drift inside an epoch. On a row's first visit a mixed behaviour policy is treated as on-policy.
3. **"The search's deviations are mostly throwing the block and activating another player" overstates the block.** D426's counts: another player activated 1,978 (51%), a different step 953 (25%), a step in place of ending the activation 319 (8%), a block in place of ending the activation 207 (5%), standing up 146, ending the activation in place of a step 94. And "another player activated" is not a longer turn: the search ran under m1, where END_TURN is not on offer while an activation is, so it means a different player was chosen. **The search data cannot say anything about END_TURN.**
4. **"Logits span plus or minus 1,000 to 2,500" counts illegal actions.** The probe took the maximum over all 454 outputs. Among legal values the range is smaller: median 90 in the type head, 107 in the arg head, 142 in the square head; the gap between the most and least probable legal joint action has median 165 and 90th percentile 441 (head probe). Still far past saturation, which starts near 17.
5. **Missed: forcing the two targeted alternatives has already been tested at play time and loses.** D416: no activation ended at once, -25.4 [-38.3, -12.2]; no unthrown declared block, -24.5 [-36.7, -11.8], both against plain chain 41. Candidate (e) explores exactly there.
6. **Missed: noise taxes long turns.** Every extra activation is about seven own decisions. If each can be replaced by a random action, the on-policy value of activating falls and ending the turn looks better. At 1% uniform noise the tax is of the same order as the margin by which the policy prefers END_TURN (section 2). Any behaviour noise must be kept out of the value targets.
7. **Missed: the per-step discount is part of the END_TURN margin.** The critic's value after END_TURN averages +0.65 (end probe), so each extra engine step costs about 0.00065 of return at gamma 0.999. That is a third of the measured margin (section 2).

## 1. The mechanism: what the trainer does at a saturated decision

**Verified in code.**

1. **Sampling.** `sample_logits` draws each head by inverse CDF over fp32 probabilities `expf(l - logsumexp)` (patched `pufferlib.cu:616-633`; the same line is upstream `:527`). An action more than about 103 below the top (about 87 if the GPU flushes denormals) has probability exactly zero in fp32 and cannot be drawn. One at 20 below has probability 2e-9. Type is sampled first, then arg under the mask of values that continue the sampled type, then square (`:558-588`, from `training/puffer_exact_joint_actions.patch:414`). The stored behaviour log-probability is `sampled_logit - logsumexp` summed over heads (`:648-662`): a difference of logits, never the log of a probability, so it stays finite and accurate to about 3e-5 at logits of 300.
2. **The policy gradient at a saturated head is exactly zero.** `d_logit = (j == act ? d : 0) - p_j * d + d_entropy_term * p_j * (-ent - logp_j)` (patched `:1049-1051`, upstream `:924`). When the gap to the second value exceeds 16.6, `1 + exp(-gap)` rounds to 1 in fp32, the top value's probability is 1.0f, and its gradient is `d - d = 0`. The others get `-p_j * d` with `p_j` below 6e-8.
3. **The entropy bonus is also zero there.** Its term is `p_j * (-ent - logp_j)`: zero for the top value (`p = 1`, `logp = 0`, `ent = 0`) and at most `gap * exp(-gap)` for the rest, 4e-8 at a gap of 20. Scaling the coefficient scales zero. The coefficient is 0.009 and constant for a run: the annealed value is passed by value into the captured CUDA graph (`:1710-1715`, `:1764-1786`; D-ledger line 1691 says the same).
4. **Nothing pulls logits back.** Weight decay is hard-coded to zero (`muon_init(..., 0.0, acts)`, patched `:2211`, upstream `:2051`; the update `wb * (1 - lr * wd) - lr * scale * update` is in `muon.cu:68-80`). `models.cu` has no normalisation, clamp or dropout on the decoder output (searched). The only clamp is on the PPO log-ratio, plus or minus 10 (`:1014-1015`). Muon orthogonalises every 2-D update (`muon.cu:204-236`), so step size does not shrink when gradients do.
5. **No designed exploration source exists.** No epsilon or random action in `puffer/bloodbowl/` (searched). Priority replay resamples 64-step rows by summed absolute advantage (`:1250-1272`, `:1372-1404`; alpha 0.8 and beta 0.2 are `default.ini` values at the pin, not set by the launcher): it reweights data, it does not change which action was taken. The frozen banks (4 x 0.12) and the bot change the states met, not the learner's choices; their rows are excluded from PPO (`:1731-1735`). A warm restart re-peaks the learning rate, nothing else.
6. **If a rare action were sampled, what happens depends on the stored log-probability.**
   - Stored as the pure policy's (today's code): ratio near 1, and the sampled value's logit gets the full gradient `(1 - p) * d`. The update is alive.
   - Stored as the exact mixture's, `log(eps/n + (1 - eps) * p)`, with the loss recomputing the pure policy: the log-ratio is about -47 for a typical tail action, clamped to -10, ratio 4.5e-5. For a positive advantage the gradient is multiplied by that ratio. For a negative one PPO's clipped branch wins and the gradient is zero. Either way nothing is learned.
   - Mixture on both sides: the gradient carries the factor `(1 - eps) * p / mu`, again zero.
   - In-run KL would also break: `old_approx_kl` averages `-raw_logratio` (`:1076`), about +47 per explored sample.
7. **Recurrent state is consistent between rollout and update.** Training zeroes the state at the start of every 64-step rollout (`bindings.cu:146-148`) and of every minibatch segment (`pufferlib.cu:1750`); terminals do not reset it in training (`:426-432`). So a first-visit ratio is 1 up to float noise.
8. **Size of a rung.** 2,048 agents x 64 steps a batch, minibatch 16,384, replay ratio 1.0: 8 optimizer steps an epoch (`:1722`), about 183,000 a rung. Non-finite log-probabilities or advantages zero that element's gradients (`:982-988`).
9. **The 16 hard-integrity keys are all env-side** (`tools/live_integrity_guard.py:41-58`: illegal fraction, reward clip and non-finite counters, component mismatch, error episodes, demo fallbacks). A loss-only change cannot trip them. A sampler change can only through an illegal tuple.

**Measured (head probe, chain 55; exploratory).**

| | Has a choice | Top value above 0.999999 | Second value's log-probability, median |
|---|---|---|---|
| type head | 71% of decisions | 89% | -82 |
| arg head, given type | 40% | 65% | -25 |
| square head, given type and arg | 52% | 66% | -28 |
| joint action | all 10,593 | 69% | second action below 1e-6 at 69%, below e^-20 at 61%, below e^-100 at 16% |

- The type head is the saturated one. Because type is drawn first, the arg and square heads are only ever trained on the path of the top type.
- Chain 25, 37, 49, 58 on the same seeds: joint saturation 58%, 62%, 72%, 70%.

**Inferred, not measured.**
- Saturated gaps grow through shared weights: a saturated state gets no gradient of its own, so its logits move only because other states move the same weights, and nothing opposes growth.
- cuRAND's uniform draw can return exactly 1.0f (about 3e-8 of draws, from the header formula as I remember it). The sampler then falls through to the last enabled value (`:635-644`). That would be an index-biased exploration source of a few tens of events a rung. Negligible, but it means a stored log-probability near -80 can already occur.
- How far a tail action's log-probability drifts over the eight optimizer steps of an epoch. Large output weights make logits sensitive to small trunk changes, so the PPO ratio of a tail action is probably much noisier than that of a sampled one. This decides how any design that trains on rare actions must treat their ratio. Request 2.

## 2. Alternative explanations, and what separates them

**A. The saturated choice is right at most of those decisions.** Supported, with one exception that matters.

Search screens, 2,010 roots (turn-level and first choice after the declaration, chain 55 + m1), by how sure the policy was of the action it played:

| a0's probability | Roots | Tail (gain above 0.10 and two standard errors) | Share of the tail's gain |
|---|---|---|---|
| below 0.99 | 216 (11%) | 3 (1.39%) | 12% |
| 0.99 to 0.999999 | 375 (19%) | 4 (1.07%) | 12% |
| 0.999999 and above | 1,419 (71%) | 22 (1.55%) | 76% |

- Run 1 (240 roots, chosen on one half of 128 rollouts and judged on the other): saturated roots are 74% of roots and carry 88% of the judged gain.
- So about three quarters of the search's gain sits at saturated decisions, which is their share of decisions. The tail rate per decision is the same whether the policy was sure or not (small counts: 3, 4, 22). Saturated decisions are not more often wrong. They are simply most decisions.
- The alternative the search picks at a tail root has log-probability median -54; 86% are below 1e-6. Training has never tried these.
- A single rollout of the chosen alternative at a tail root beats a0's mean return in 93% of rollouts (mean +0.159, spread 0.097; `price_of_exploring.py`). **One sample would give PPO the right sign. For the tail, the missing piece is the sample and a live update, not credit assignment.**
- The exception is rare: 1.46% of searched decisions (FINDINGS section 3), about 1.5 a seat-game in plain play.
- A caution against reading too much into sampling: raw 16-rollout gains above 0.10 are as common among alternatives the policy samples often (2 of 240 with probability 0.01 or more) as among those it never samples (21 of 2,596 below e^-50). The counts are too small to conclude from. They do not show PPO clearing large errors where it does sample.

**B. The plateau is a credit or objective problem, not exploration.** Supported by the end probe.

| Roots (chain 55, plain play) | n | Most probable alternative minus the action played | Reward part | Value part, undiscounted | Discount on the bootstrap | Alternative better by 0.02 and two s.e. (judged on a held-out half) | Better by 0.10 | Worse by 0.02 |
|---|---|---|---|---|---|---|---|---|
| Played END_TURN with an ACTIVATE legal; alternative: activate | 120 | -0.0117 [-0.0166, -0.0072] | +0.0041 | -0.0120 | -0.0038 | 17% | 1% | 16% |
| the same, END_TURN saturated only | 49 | -0.0117 [-0.0209, -0.0028] | +0.0069 | -0.0144 | -0.0042 | 16% | 0% | 18% |
| Played END_ACTIVATION with a BLOCK_TARGET legal; alternative: block | 78 (73 saturated) | -0.049 [-0.073, -0.026] | -0.067 | +0.016 | +0.001 | 13% | 0% | 60% |
| Played ACTIVATE with END_TURN legal; alternative: END_TURN | 120 | -0.0144 [-0.0262, -0.0024] | -0.070 | +0.047 | +0.009 | 23% | 5% | 37% |

- **Ending the turn is right under the policy's own objective**, saturated or not. A perfect oracle at these decisions would add an activation at about one END_TURN in six: about 0.1 activations a team turn against a gap of four to human play.
- **A declined block is a bad block under the objective.** The loss is in the reward part (-0.067), which holds the turnover and sequence charges and the income lost when the block ends the turn; the value part slightly favours the block. This is the third explanation in the brief (the risk charges make ending the activation the optimum), and for this class the data support it. D416's masks show forcing these blocks also loses by match result.
- **The block choice is closed in both directions** (head probe, 290 decisions with END_ACTIVATION and a BLOCK_TARGET both legal): the block has probability 0.999999 or more at 69%, END_ACTIVATION at 27%, and both are below 0.99 at 2%. Training almost never samples this choice both ways. Where END_ACTIVATION was played, the end probe still finds the block worse by 0.02 at 60% of roots and better by 0.02 at 13%.
- **The END_TURN decision is not uniformly closed** (head probe, 1,682 turn-level decisions with both options legal): P(END_TURN) is between 1e-6 and 0.99 at 19% of them. Where END_TURN was played (335 times), it was saturated at 36% and below 0.99 at 26%. Training samples both options at the margin every game and still ends the turn. Along the ladder the saturated share of END_TURN plays rose from 17% (chain 25) to 36% (chains 49 and 55).
- **Yet m1 gains +32 to +43 Elo by forcing activations (D416).** The evaluator prices one more activation at about -0.012; the match result says it is worth a little. Those are small numbers of opposite sign, and the difference is in the value part: the critic expects a worse position after one more activation. That is an objective or critic question. Chain 58's lambda result (+0.33 activations, D428) points the same way.
- **A caution on the evaluator.** At 23% of the policy's own activations the probe finds ending at once better by 0.02. Either the policy activates at a loss that often or the critic is locally off by a few hundredths. The mean activation it makes is worth only +0.014. The margin is thin in both directions.

**C. Noise tax.** Search screens: an alternative among the three most probable costs -0.010 on average (median -0.0003, 18% worse than -0.02); alternatives below e^-50 cost -0.016, and 5% of them cost more than 0.10. At 1% noise per decision a seven-decision activation carries about a 7% chance of one such action, a tax near 0.001 to 0.003 on activating, against a margin of 0.012. Uniform noise that reaches the value targets makes the plateau worse.

**What would separate these further, cheaply:** section 4, tests 2 and 3.

## 3. Candidates compared

"Rebuild" means the compiled module changes: a new training checkout on the rig, an identity stage (the new flag off reproduces stored checkpoints byte for byte), an extended qualification and a 50M canary, as the b3 build did. Line counts are estimates for CUDA plus the Torch twin, config plumbing and tests.

| | Change | Rebuild | Reaches saturated decisions? | Main risks | Prior art |
|---|---|---|---|---|---|
| (a) entropy scale | `LADDER_CHAIN_ENT_SCALE` up to 4 (0.036) | no | **No** (section 1, item 3). Softens the open 15% to 30% | More conservative, lower-scoring play | D261: x2 lost on every exam cell (exam only, older recipe); D137's sweep preferred lower entropy; D259, D271 moved the learning rate too |
| (b) uniform mix, exact mixed log-probability | sampler, log-probability storage, loss; about 250 lines | yes | Samples them; **the policy learns nothing from the samples** (item 6) | Value targets absorb the noise tax; KL telemetry breaks; breaks D218's "PPO recomputes exactly the behaviour distribution" unless the loss mixes too | none |
| (c) temperature above 1 with corrected log-probability | sampler and loss, about 60 lines | yes | No: gaps of 20 to 1,000 need T of 4 to 200. Optimising the tempered policy is the same as rescaling the logits | Heats the open decisions most | D400, D401: T 0.75 at play did not explain chain 30's edge |
| (d1) hard logit clamp | sampler and loss, about 60 lines | yes | Samples at the floor; a clamped logit gets no gradient, so nothing rises | Needs a straight-through gradient, which is biased and lets raw logits drift | none |
| (d2) restoring term that does not vanish: cross-entropy to uniform over the legal values of each head, coefficient beta | loss kernel only, about 150 lines | yes | Yes, and it is exactly on-policy: sampling, stored log-probabilities, masks and the action contract are untouched | Dose, by my arithmetic and not measured: at equilibrium the play-time cost is about beta times the advantage scale per head-decision, about 570 head-decisions a game. A beta that moves gaps within a rung (near 0.01) costs real strength at T=1 and adds a noise tax; a safe one (near 0.0005) is too slow. Needs play below T=1, which no gate uses | Weight decay is the blunt relative: it also shrinks the value head |
| (e) forcing or exploring only END_ACTIVATION against a block and END_TURN against an activation | sampler needs the decision class from the mask, about 200 lines | yes | Yes | At those decisions the played action is right under the objective in about five of six cases (section 2) | D416: masks m2 and m3 lose 25; m1 gains through activations that are 58% empty; D421: training under m1 added filler |
| (f) distil the search's choices | offline first: a screening run and a fine-tune script, no trainer change. In the trainer: a native auxiliary loss, large | offline: no | Yes: cross-entropy has full gradient at saturation | Generalisation from a few thousand examples is unknown; D176's full-strength imitation anchor collapsed offence (human data, another setting); search is +47 in self-play only until D430 reads | D425, D426, D430 |
| (g) probe exploration: with probability eps one head is drawn uniformly; the pure log-probability is stored; the explored step is flagged; the trace is cut so earlier steps and the value head never see it; the explored step itself gets a plain advantage update | sampler, advantage kernel, loss; about 350 lines | yes | Yes, with a live update, a sharp play policy and unpolluted values | Biased by design (explored actions weighted by eps, not by their probability); ratio of tail actions (request 2); pushes bad tail actions further down unless negative updates are skipped below a log-probability floor; games in training get sloppier | It is the search's one-step test with one rollout, learned by gradient |

Notes.
- **(b) against (g).** The difference is whether the estimator is allowed to be biased. Exact accounting gives zero. The honest name for anything that learns from forced actions is "off-policy without the importance weight for that one step".
- **Why (g) cuts the trace.** GAE passes the explored step's outcome back to earlier steps and into the value target of the explored state. Zeroing the running sum after a flagged step (in `puff_advantage_row_vec` and its scalar twin, patched `:1408-1497`) and skipping the value gradient there keeps the critic an estimate of the policy without noise. Without that, item 6 of the framing section applies.
- **The floor in (g).** Below the floor only positive advantages act. That lifts lucky gambles until they reach the floor, where two-sided updates resume. A log-probability of -14 is one in a million, far below any sampling rate, so the lift is harmless and it stops explored bad actions from being pushed down without limit.
- **Uniform over what.** One head at a time, uniform over its enabled values, later heads from the policy. Uniform over joint tuples weights types by how many squares they have and needs the joint probability in the loss.
- **fp32.** Not the hazard in any variant (section 1, item 1). The hazards are the ratio of a tail action after a few optimizer steps and the clamp that lets a ratio reach 22,026.
- **Deep exploration is out of reach of all of these.** A useful fourth activation is a sequence of right choices. One-step noise finds it with probability eps to a power. Only a prior, the critic or the reward can supply sequences.

## 4. Cheap tests off the rig

**Test 0, done here for nothing (exploratory).** The tables of section 2: three quarters of the search's gain is at saturated decisions; the tail's alternatives are never sampled and are one-sample detectable; END_TURN and declined blocks are right under the objective.

**Test 1: is the tail learnable? About $1, no rig. This is the test that most changes what is worth building.**
- Screen about 300,000 roots of chain 55 + m1 self-play with the existing tool's screen step (16 rollouts, four candidates). The Mac did 1,350 roots in 412 s single-process (`tail1/tail_meta.json`), so about 25 CPU-hours, about four 8-vCPU droplet-hours (not measured on a droplet). Expect about 4,400 tail labels at 1.46% and about 26,000 band labels.
- Fine-tune a copy of chain 55 in Torch: cross-entropy toward the search's choice at tail roots, KL to the original policy at every other screened root, recurrent state from replaying the game prefix, split by game.
- Read on held-out games, with the rule committed first: the probability the fine-tuned policy gives the search's action at tail roots (now below 1e-6 at 86%); agreement with the original elsewhere; a fresh screen of the fine-tuned policy (does its tail rate fall?).
- If a few thousand labelled examples do not generalise, no exploration scheme will teach the same thing from the same number of unlabelled noisy samples in a rung, and (g) is not worth a build. If they do, the fine-tuned checkpoint can be gated like any candidate and (g) becomes the on-rig version of the same idea.
- D426's own records cannot be used: they store a hash of the action trail, not the states or the chosen actions (`tools/search_ab.py:426-551`).

**Test 2: the end probe at registered size. About $0.20.** Chains 49, 55 and 58, 200 games and 64 rollouts each, plan committed first. Questions: does the END_TURN margin hold (my 120 roots: -0.0117 [-0.0166, -0.0072])? Is it smaller for chain 58, which would show lambda 0.97 moved the critic's pricing? An added arm with rollouts to the end of the match that sum the 28 reward channels per candidate would name which terms the critic expects to lose after one more activation. Candidates worth naming in advance: the defender's side of the zero-sum block transfer (standing next to an opponent is charged when he blocks), the rush fine, the per-step discount.

**Test 3: where m1's gain sits. About $0.10 plus a small harness change in its own worktree.** Two masks: m1 applied only where the unmasked P(END_TURN) is 0.999999 or more, and only where it is below 0.99; each against plain chain 55, 3,200 games. If the gain is at open decisions, exploration is ruled out for the plateau by a tournament, not by an evaluator.

**What would change my mind.** Test 2 showing activation better at saturated END_TURN roots; test 3 putting m1's gain at saturated decisions; test 1 failing (then drop exploration and distillation both) or passing strongly (then build (g) and an off-rig distillation loop at once); D430 reading not Positive (then the tail's value against other opponents is unproven and all of this waits).

## 5. Ranked list, and the first rung

1. **Tests 1 to 3 and D430's reading.** Under $2 and a day.
2. **(f) offline**, if test 1 passes: gate the fine-tuned checkpoint. It uses no rig time and gives labels where (g) gives noise.
3. **(g) probe exploration** on a new build, if test 1 passes. The first exploration rung.
4. **(d2) the restoring term**, only together with a registered play temperature below 1 for arm and control. Second build priority. It is the only candidate that lowers the logit scale itself.
5. **(a) entropy x4.** Runnable tomorrow with no build, and I would not: by the code it cannot touch the decisions in question, and D261's one reading was negative. Its only use is as a null check of section 1 (prediction: joint saturation within three points of the control's 69%).
6. **Do not build:** (b) as worded, (c), (d1), (e) as forcing.
7. **For the plateau, separately:** finish the lambda pair (chain 60), run test 2, and choose the next objective-side rung from what test 2 names. `LADDER_GAMMA=0.9995` alone is the cheapest untested one (D396 moved lambda with it and was read on the exam only); I did not check that `r0_poss_half` passes the manifest guard at that gamma.

**The rung, written as it would be registered. Not to be registered before test 1 and D430 read.**

- **Name and factor.** Chain N, `LADDER_EXPLORE_EPS=0.01`, on build b4. With the knob at 0 the build takes today's code path and draws no extra random number, so the sampling streams are unchanged.
- **Code change (candidate g).** In `sample_logits`: per deciding row, with probability 0.01, one head that has two or more enabled values is drawn uniformly; the stored log-probability stays the pure policy's; the row's importance slot is written 0 as the flag. In `train_impl`: the importance fill keeps flags. In the advantage kernels: a flagged step uses its own TD error at full weight and resets the running sum, so no earlier step sees it. In `ppo_loss_compute`: a flagged step uses ratio 1, has no value gradient, and its negative-advantage update is skipped when the stored log-probability is below -14. New panel fields: explored steps per episode, their mean advantage, the share positive.
- **Before it trains.** Identity stage: knob at 0 reproduces chain 55's stored checkpoints byte for byte. Qualification extended: every explored tuple is in the joint support; flagged rows are excluded from the near-unity ratio check and unflagged rows still pass it. A 50M canary at 0.01 with the 16 hard counters at zero and zero truncated episodes, never continued from.
- **Control.** Chain 55 (`f6ba3b44...`): warm chain 49, seed 42, pool `2ae7448e...`, `r0_poss_half`, gamma 0.999, lambda 0.95, replay ratio 1.0, 3B steps. If lambda 0.97 is adopted first, chain 58 with lambda 0.97 on the arm. Either way the control exists. Declared differences: the knob, and build b4 against b3 (argued inert by the identity stage, as D416 did for b3).
- **Dose arithmetic (inferred).** About 3.5 explored decisions a seat-game. About 3 million tail decisions a rung on learner seats (1.46% of about 100 in-scope decisions a seat-game, about 2.25 million learner seat-games), of which about one in eight hundred is explored at the right value: about 4,000 positive tail samples a rung, the size test 1 trains on.
- **Hypothesis.** PPO does not fix the decisions where an action it never samples is better by 0.10 or more, because it never samples it and cannot move a saturated logit. Given one honest sample at a time and an update that does not scale with the action's probability, it fixes some of them.
- **What should move if it works.**
  - Primary diagnostic, off the rig: the search screen on the arm and on the control, same tool, seeds and settings (2,010 roots each, both under m1). The control's tail rate is 1.46% [0.92, 2.06]. The arm's should be lower, with the difference's interval below zero.
  - Style table (pair 1, per team turn): touchdowns per game up (the searching seat scored +0.13 a game, D426). Activations within about 0.15 of the control: I register no expectation of more. Empty activations and blocks unchanged; turnovers not higher by more than 0.01.
  - Logit statistics (head probe on both): joint saturation and the second action's median log-probability roughly unchanged. This candidate does not soften the policy; a large drop in saturation would mean it is doing something other than intended.
  - In-run: explored steps' mean advantage negative and small (about -0.01 to -0.03) with a positive share that rises over the rung; value loss, explained variance, deciding-row KL and clip fraction of unflagged rows inside chain 55's bands.
  - Gate: the usual eleven pairs and labels. Positive needs the direct gap above +40 with both held-out contrasts above zero.
- **What counts as failure.** The tail rate is not lower (the hypothesis fails in training, whatever the gate says). Pair 1's interval is entirely below zero, or the drift guard trips. Value loss more than half again above the control's, or explained variance lower by more than 0.02 (the trace cut is not holding). Any nonzero hard counter. Activations per team turn lower than the control's by more than 0.15 (the noise tax got through).
- **Written down now.** I expect Flat or Inconclusive as the label. I expect the tail rate to fall by less than half. I do not expect this rung to move the plateau.

## 6. Requests to the operator

1. D430's reading when it is in. Everything about the tail assumes the search's gain is not a self-play artefact.
2. On the rig, when free (minutes): the drift of log-probabilities of legal non-top actions at saturated decisions after 1, 8 and 64 optimizer steps on a fixed rollout batch, through the qualification snapshot. It sets how (g) or (f) must treat ratios.
3. From chain 55's and chain 58's logs: the advantage standard deviation if it is printed, and the deciding-row entropy over the run (D428 gives the end values, 0.170 and 0.178).
4. The trainer's printed `prio_alpha`, `prio_beta0`, `vtrace_rho_clip`, `vtrace_c_clip`. I read 0.8, 0.2, 1.0, 1.0 from `default.ini` at the pin; the launcher does not set them (`tools/run_reward_ablation.sh:941-963`).
5. The PufferLib commit of the rig's b3 tree. I assumed `f14b71c`.
6. The share of the learner's deciding rows with top probability above 0.999999 in a training rollout. The head probe is self-play at play time; training also meets banks and the bot.

## 7. Not verified, and limits

- Nothing on the rig was read. Line numbers are from my reconstruction of the patched tree, which leaves out the optional patches. The rig's b3 tree carries at least the deciding-row telemetry patch (D428 quotes its numbers): it adds log-only channels inside `ppo_loss_compute` and shifts later line numbers; its own comment says the loss and every gradient are computed before them and never read them. I read that patch and the scripted-bank-skip and dictionary-capacity patches but did not apply them; none changes sampling or the gradient lines quoted here.
- Every probe is exploratory: one checkpoint (chain 55) for the end probe, 40 games, 32 rollouts, seeds chosen here, no plan committed first. Its first run with other root draws gave -0.0069 [-0.0130, -0.0009] for the END_TURN row, the same sign and half the size.
- The end probe's evaluator is the policy's own critic. "Right under its own objective" is what it shows. It cannot show that ending the turn is right by match result, and m1 says it is not.
- The end probe and the search both test one changed action followed by the policy's own play. Neither tests a coordinated sequence.
- The tail-rate-by-sharpness table rests on 29 tail roots (3, 4 and 22 per row).
- The dose and cost arithmetic for (d2) and (g) uses an advantage scale of about 0.1 that I inferred from the value loss, not a logged number.
- The cuRAND remark is from memory of the header.
- I did not test that any code change compiles. The line counts are estimates.
- I did not check `LADDER_GAMMA=0.9995` against the manifest guard, or whether a derived checkpoint from test 1 can carry a lineage sidecar as a warm start.
