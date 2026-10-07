# The rung after chain 57: recommendation (2026-10-06, 18:05 PDT)

**Status: a design study. Its recommendation was registered as D422 after a Codex review; where this text and D422 differ, D422 is the registration. The review found three statements here too strong: the 'about a tenth' volume bound, the reading of the halved-terms arm as evidence about the charges alone, and 'a positioning gap no charge removal reaches' (section 1).**

## Recommendation

Run chain 58 as chain 55's rung with one changed setting, `LADDER_GAE_LAMBDA=0.97` (control 0.95), because the second horizon step was closed in D396 on the scripted-bot exam alone, one day before that same exam was shown to miss a +108 Elo effect, and chain 29 never played a tournament. It needs no manifest, no tools change and no rebuild: one exported variable in a copy of `b3_chain55.sh`. Queue a training-seed replicate of chain 55 (seed 2042) behind it, and do not run the block-charge reward arm yet: the hypothesis behind it is half wrong and existing data bound its upside at about 0.8 blocks per team turn against a human 2.5.

## Where the framing is wrong, and what was missed

1. **"Nothing pays for a block" is wrong.** `reward_k_kd`, `reward_k_value` and `reward_k_ball` pay a block's expected knockdown, removal and ball-out value at declaration. A routine two-die block is net paid. Section 1.
2. **"A new manifest JSON and a wrapper" is not enough to launch a reward arm.** `LADDER_ARM` passes a closed list and a name-to-path map inside `tools/run_reward_screen.sh` (lines 56 to 59 and 394 to 437). A new manifest with legacy distance terms is refused unless it carries `"reward_dist_mode": "legacy_raw_delta"` or its digest is pinned (`tools/reward_manifest.py:81-99`, `:272-282`). So a reward arm needs a tools commit in the rig's b3 checkout, which is the checkout chain 57's screen script is running from. No env rebuild is needed: the drift guard hashes `puffer/bloodbowl` and compares `bloodbowl.ini` only.
3. **Candidate (c) is barred by the ledger.** D416 item 6 and D421 both say the rule "is not trained under again without a new idea".
4. **Candidate (b) is chain 57.** It is the fourth test of the pool change with tournament evidence behind it. A second pool arm designed before its gate reads is premature, and the "non-transfer pattern" it would chase rests on one training seed of the control.
5. **Missed: the horizon.** It is the largest replicated lever in this ledger (D391 to D393, D399), its second step was read on the exam only, and it speaks to turn length. Section 3, candidate (e).
6. **Missed: power.** Positive needs three intervals above zero from one training seed per side. Replicate-pair gaps in this ledger are +14.2, +39.9, -15.7, +15.4 (D400, D401). Expect Inconclusive again from any arm with a true effect under about +50. That is why the control replicate is the second choice.
7. **Operational.** If chain 57's stage does not write `EXAM_VERDICT_PASS.json` (guard trip, trainer failure), the supervisor halts at its attempt cap and no later stage runs (`tools/campaign_supervisor.py`, `tick`). A stage appended to the plan runs on the next tick otherwise, including after the plan had completed.

## 1. The reward-hypothesis check

Code is `puffer/bloodbowl/bloodbowl.h` in this worktree. The block-pricing section is byte-identical in the b3 branch (it starts at line 3603 there).

- **When.** One hook, at `BB_A_BLOCK_TARGET`, before any dice, for a standing attacker (`:3517-3526`). Probabilities come from `bb_block_ev` (`engine/include/bb/bb_blockev.h:41-48`).
- **What pays** (`:3572-3581`): `exposure = p_deliver * (k_kd * p_def_down + k_value * p_def_removed * cost/100k + k_ball * p_ball_out)`, added to the attacker's team and subtracted from the defender's. Zero-sum. With `r0_poss_half`: 0.1, 0.5, 0.15.
- **What charges, attacker only:**
  - `reward_k_turnover` (`:3590-3608`): `0.15 * p_turnover`, the block dice's own turnover probability.
  - `reward_k_seq` (`:3614-3628`): `0.03 * p_own_to * pending`, where `pending` counts the team's other standing, unused players. Exempt on the team's turn 8 and during Charge!.
- **Other dense terms:** rush fine 0.015 per rush square (`:3282-3284`), possession annuity at own turn end (`:3772-3775`), ball gain (`:2451`), the two distance channels (`:3999-4026`). The assist potential exists and is zero (`:3844`); carrier exposure, carrier threat and defensive threat are zero in the manifest.
- **The ledger cannot show what blocks earn.** `BBE_REWARD_BLOCK_EXPOSURE` is one channel holding own income minus what opponents' blocks took (`:190-225`).

Per block, computed by hand from those formulas with standard dice odds, equal strength, no skills, AV 8+ or 9+, a 50k to 100k target (not run through `bb_block_ev`):

| Block | p_def_down | p_turnover | Exposure | Turnover charge | Seq charge at 7 pending | Net |
|---|---|---|---|---|---|---|
| Two dice, attacker's choice | 0.56 | 0.11 | +0.07 to +0.10 | -0.017 | -0.023 | about +0.03 to +0.06 |
| Two dice, attacker has Block | 0.56 or more | 0.03 | +0.07 to +0.10 | -0.004 | -0.006 | about +0.06 to +0.09 |
| One die | 0.33 | 0.33 | about +0.05 | -0.050 | -0.070 | about -0.07 (about 0 as the last action) |
| Two dice, defender's choice | 0.11 | 0.56 | about +0.015 | -0.083 | -0.117 | about -0.19 |

**Verdict on the hypothesis.**
- **Wrong:** "nothing pays the attritional value" (`k_value` pays removal weighted by player cost; `k_kd` pays the knockdown) and "a block is net charged in expectation" as a general statement. The blocks this policy does throw are, on these numbers, net paid.
- **Wrong reading of the ledger:** chain 41's exposure line of -0.10 per game (D416 item 3) is not a charge on its blocks. It is the zero-sum net, and the contact bot plays about a quarter of the learner's games (122 of 536 learner rows per buffer at 4 x 0.12, by D274's arithmetic), blocking far more than the learner does.
- **Right, narrowly:** a one-die block without Block is net charged, and any block is charged more the earlier in the turn it is thrown. From the same ledger lines, turnover -0.13 and sequence -0.18 a game at about 7.5 own blocks a game give a mean `p_turnover` near 0.12 and a mean `pending` near 7: the policy blocks early and then ends the turn, so the sequence charge prices activations it never uses.
- **Right, and the part worth acting on:** nothing dense pays for where the other ten players stand. Every dense positive term is about the ball.
- **The charges are not why blocks are 0.47 a turn.** Three pieces of evidence:
  1. With almost no charge (`k_seq` 0.01, no turnover charge) the old lineage threw 15.7 blocks a game in training panels, against about 14 with both charges at today's values (D157, D160, D169). The charges bought dice discipline for about a tenth of the volume.
  2. Halving all five block terms lowered blocks (about 14 in the plain continuations to 12.4 and 11.7, D273, D279, D280). A family that taxed blocking would have raised them.
  3. Chain 41 throws 0.59 of its declared Blocks, humans 0.98 (`docs/human-prior-v1-2026-10-05.md` section 5, in the `bb-lockstep-probe` worktree). If every declined one were thrown, chain 55's 0.466 blocks a team turn would become about 0.8. Under the mask, with every player activated, it is 0.57 to 0.63. The policy is not standing next to opponents; that is a positioning gap no charge removal reaches.

`r0_blockev_half` (D278 to D281): all five `reward_k_` terms halved, two training seeds, exam only. Champion deltas -0.009, -0.001, +0.010. Rejected; D279a's one-seed pass was retracted. `r3_minimal_block`: used only in the July screen (D177). It removes the ball terms and keeps block and rush terms fixed, as every arm of that screen did, so it is not evidence about block charges. It scored 0.71 and 0.58 TD a game against R0's 1.42 and 1.45.

## 2. Prior art

"Panels" means in-training telemetry on the June lineage. "Exam" means the scripted-bot exam, whose veto D417 retired after its direction disagreed with tournaments on several rungs (D404, D410, D412).

| Entries | What was tried | Read on | Result | Settles a candidate here? |
|---|---|---|---|---|
| D156 to D158 | Block pay raised (k_kd 0.03 to 0.1, k_value 0.25 to 0.5), then doubled | Panels | Blocks 5 to 15.7 to 21.1; 2d-red 0.10 to 0.13 | Pay moves volume by a third per doubling, with a worse dice mix. No strength read. |
| D159 to D162 | `k_turnover` 0.15 added, then 0.30 | Panels | Blocks 15.7 to 14 (10 at 0.30); 2d-red 0.12 to 0.056; TDs held at 0.15 | The charge costs about 10% of volume. Bounds (a) for style. |
| D169 | `k_seq` 0.03 restored | Panels | 2d 0.61, 2d-red 0.044, "fewer, safer blocks", TDs 1.56 | Same. |
| D163 to D165 | Assist potential, `k_assist` 0.03 | Panels | Assists flat; blocks 14 to 16.8; TDs 1.46 to 1.66 | Failed its own target. Never tournament-read. |
| D132, D140, D148, D150 to D156 | Carrier exposure fine; injury reward; threat annuity | Tournament; panels | Win confounded with 28B more steps; tie; drift to passivity | Doctrine since D118 and D140: no positional bounty without a matched control. |
| D177 (July screen) | Ball terms on and off; block terms fixed | Paired eval | Distance carries scoring | Says nothing about block charges. |
| D278 to D281 | `r0_blockev_half`, two seeds | Exam | Rejected; blocks fell | Exam only. Direction argues against the hypothesis. |
| D288, D289 | Rush fine zero | Exam, one seed | Flat on contact, -0.02 offense | Exam only. |
| D264 to D270 | Distance, possession, ball-gain steps | Exam | `r0_poss_half` accepted, the rest rejected | Not relevant to blocks. |
| D391 to D393, D399 | Horizon step 1: gamma 0.995 to 0.999, lambda 0.85 to 0.95 | Exam, two seeds; round robin | Both contact cells +0.06; 0.999 chains take 64.6 to 82.5% of decisive games from 0.995 chains | The largest replicated lever in the ledger. |
| D396 | Horizon step 2: gamma 0.9995 with lambda 0.97 (chain 29) | Exam only | -0.023 on contact AWAY, "by the smallest margin" | **No.** Chain 29 is in no tournament. It moved gamma too, which its own registration said shrinks the distance bias and costs a critic re-fit. |
| D397, D399, D401 | Replay ratio 1.0 (chain 30) | Exam, then round robin | Exam Flat; +108 over chain 25 head to head; replicated | Shows what the exam can miss. |
| D389, D390, D398, D399 | Eight banks at 0.06 | Exam; round robin | Flat, Negative; chain 31 ties chain 25 | Ambiguous: bot exposure halves. |
| D260, D272, D277 | Offense bot in the seat | Exam | Conceded up; retracted as underpowered | Unread on tournaments. |
| D410 to D418 | Bot in the anchor's seat, three pairs | Tournament | +42.2, +9.0, +62.7; held-out contrasts against chain 37 +45.6, -3.3, +66.5 | Chain 57 is the fourth pair. |
| D276, D277, D282 to D287, D400, D401, D413, D414 | Seed replicates | Exam; tournament | Found the noise floors; chains 42 and 48 agree at +12.5 and +11.0 | The reason to replicate chain 55. |
| D407 to D410 | Restart learning rate x0.5 | Tournament | Flat, Negative | Closed in practice. |
| D416, D419, D421 | Mask at play; rule in training | Tournament | Mask +32 to +43; chain 56 Inconclusive, more empty activations, blocks unchanged | Bars (c) without a new idea. |
| D244, D245 | Four recent selves as the pool | Panels | Abstinence basin; a dip that can recover | The risk any pool arm carries. |

## 3. Candidates

**(e) GAE lambda 0.97. Recommended.**
- Hypothesis: the policy has no reason to use its other players because credit for an off-ball move arrives after the GAE window has closed, and the critic does not price off-ball position. A plain game is 695 engine steps (D416), about 43 per round of two team turns. The weight on a consequence 43 steps later is 0.11 at gamma 0.999 and lambda 0.95, and 0.26 at lambda 0.97. The mask result says those moves are worth +32 to +43, and the trainer has not found them.
- Change: `LADDER_GAE_LAMBDA=0.97`. Gamma stays 0.999, so the value target and the distance form do not change. The GAE window goes from 19.6 to 32.3 steps, which is chain 29's window (32.8) without chain 29's discount change.
- Prior art: D391 to D393 and D399 for step 1; D396 for step 2, exam only.
- Would change our mind: Flat or Negative on the tournament with turn shape unchanged closes the lambda half of step 2 properly. Positive, or a clear rise in non-empty activations with no loss, reopens the horizon and earns a second seed.
- Risk: noisier advantages. Chain 29 ran 3B at this window with integrity zero and no avoidance. Collapse is unlikely; the chain 30 drift guard applies as for chain 55.
- Readiness: one variable. `tools/ladder_stage.sh:36-37` forwards it and the marker records it.

**(f) Seed replicate of chain 55 at seed 2042. Second choice.**
- Hypothesis: none. It measures how far chain 55's pattern (+101.3 direct, -1.7 and +60.9 held out) moves with the training seed. That is the floor chains 56, 57 and 58 are read against.
- Change: `SEED=2042` (shares no env stream with 42, D412).
- Would change our mind: transfer on both held-out opponents makes it a warm-start candidate by the plain recipe and makes the "non-transfer pattern" a seed draw. The same split twice makes it a property of the recipe and justifies pool work.
- Risk and readiness: none beyond chain 55's; one variable.

**(a) Remove the block risk charges. Not now.**
- Exact change, if run: new manifest `r0_poss_half_blockrisk_zero` = `r0_poss_half` with `reward_k_seq` 0.03 to 0.0 and `reward_k_turnover` 0.15 to 0.0, plus top-level `"reward_dist_mode": "legacy_raw_delta"`. One declared family, two fields (D264 and D278 are the precedents). Leave `k_kd`, `k_value`, `k_ball` alone: they are the pay.
- Prior art: this is the June "violence" economy (D156, D157). Expect about 10 to 20% more blocks and two to three times the 2d-red share. Ceiling about 0.8 blocks a team turn (section 1).
- Would change our mind, cheaply and off the rig: in harness games of chain 55, price every thrown block and every declined Block offer with `bb_block_ev`. If declined offers are mostly net negative and far outnumber thrown blocks, the arm is worth a rung. I expect neither.
- Risk: low for collapse (two negative-only terms removed). Readiness: manifest, two edits to `run_reward_screen.sh`, tests, and a checkout move on the rig. Not safe to improvise by 01:00.

**(b) Pool arm.** Wait for chain 57's gate. If it reads Positive, the next question is whether the parent matters or any real opponent in the anchor's seat does; `POOL_ANCHOR=<chain 38>` tests that with no code change, but its pool hash differs from `2ae7448e` and chain 37 stops being cleanly held out (chain 38 is its sibling). Register it then, not tonight.

**(c) Rule pair at a second seed.** No. Barred as registered, 17 hours, and D421's diagnostics show the rule being met by empty activations with blocks unchanged. The new idea it would need is a reason for the forced activations to do something; (e) is the cheapest test of one.

**(d) Roadmap items.** The exploiter probe (M1) has never run, but it needs a hand-built pool through the first-rung path and is not a one-factor arm against chain 55. M2 (search) is off the rig. M3's trainer term read stop (D416 item 3).

## 4. Chain 58: settings

Wrapper `~/longrun/b3/b3_chain58.sh`: a copy of `b3_chain55.sh` with a new stamp and one added line after the pool pin.

```bash
export SEED=42 STAMP=r0chain58-lam097-from49-s42-20261007
export PREV_COMPLETE="$LONGRUN/runs/ladder-d0-r0chain49-botseat1-from41-s42-20261004/LADDER_RUNG_COMPLETE.json"
export LADDER_CHAIN_LR_SCALE=1.0 LADDER_CHAIN_ENT_SCALE=1.0
[ -z "${B3_POOL49_HASH:-}" ] || export EXPECTED_POOL_HASH="$B3_POOL49_HASH"
export LADDER_GAE_LAMBDA=0.97          # the one factor; b3_common_env.sh sets 0.95
export EXAM_RULE=drift-guard
export EXAM_GUARD_FLOOR_S42=0.541 EXAM_GUARD_FLOOR_S43=0.551 EXAM_GUARD_FLOOR_MEAN=0.546
exec bash "$C/tools/chain_stage.sh"
```

- Plan entry: name `b3_chain58`, launch `bash /home/rache/longrun/b3/b3_chain58.sh`, success and progress under `/home/rache/bloodbowl-rl-b3-20261006/runs/ladder-d0-r0chain58-lam097-from49-s42-20261007/` (`EXAM_VERDICT_PASS.json`, `SCREEN_STATUS.json`), attempts and stale limit as chain 55's entry.
- Before launch: `PLAN_ONLY=1 bash ~/longrun/b3/b3_chain58.sh` must verify with pool `2ae7448e...`, warm `a2d1d10d...`, reward `433c7920...` and print `horizon gamma=0.999 gae_lambda=0.97`. Plan-only passes have run beside a live trainer before (D416, D418).
- Expected: about 9 hours, ending near 11:00 PDT on 2026-10-07.

## 5. Pre-registration text for the ledger (D422)

**Chain 58, pre-registered: chain 55's rung with GAE lambda 0.97.**
- `r0chain58-lam097-from49-s42-20261007`: warm chain 49 (`a2d1d10d...`), training seed 42, pool `2ae7448e...`, `r0_poss_half`, gamma 0.999, replay ratio 1.0, 4 banks x 0.12 with the contact bot on tag 4, restart scale 1.0, 3B steps, on the b3 build (source `4c8a04b1...`, module `4156c9c3...`), rule flag off, `LADDER_GAE_LAMBDA=0.97`. **Control: chain 55** (`f6ba3b44...`).
- **Hypothesis.** With lambda 0.95 the direct credit window (19.6 engine steps) is shorter than one round of play (about 43), so an off-ball activation gets almost no advantage signal, and the policy ends its turn after about three activations. A 32.3-step window gives those moves credit. If true, chain 58 activates more players per team turn than chain 55 in unmasked play, the added activations are not all empty, and it is no weaker.
- **Declared differences from chain 55, all of them.** GAE lambda. The wrapper sets one more variable. The rung runs about 27 hours later on the same checkout, build and hardware; if the b3 checkout's commit has moved since chain 55's stage, that is declared with both hashes. Same stage rule (D405's chain 30 drift guard, same floors). No exam veto (D417).
- **Why D396 does not settle it.** Chain 29 changed gamma and lambda together and was read on the exam only, where one cell was 0.003 past the overshoot threshold. It has played no tournament, and the exam read chain 30 Flat (D397) a day before the round robin put it +108 over chain 25 (D399).
- **Gate.** Mask harness `7d0d547` for its activation log, seed block 22700000, 3,200 naturally completed games per pair, 32 per worker, T=1, kick-off starts, both legs, no sampling offsets, plan sha256 committed here before any shard is launched, accepted by `tools/gate_acceptance.py` and `accept_from_plan.py` before scoring. Eleven pairs, played without masks unless marked: (1) chain 58 against chain 55; (2) chain 58, (3) chain 55 and (4) chain 49, each against chain 37; (5) chain 58, (6) chain 55 and (7) chain 49, each against chain 46; (8) chain 58 against chain 49 (descriptive; chain 49 sits in the bot's seat in both pools); (9) chain 58 and (10) chain 55, each against the offense bot; (11) chain 58 + m1 against chain 55 + m1 (descriptive). Contrasts by `paired_contrasts.py` (sha256 `722ece95...`, 2,000 replicates, generator seed 0): chain 58 minus chain 55 against chain 37, chain 46 and the offense bot; retention, chain 58 minus chain 49, against chain 37 and chain 46.
- **Labels, applied in this order to accepted evidence only.** **Negative:** pair 1's interval entirely below zero, or the stage's chain 30 guard tripped. **Positive:** pair 1's point estimate above +40 with its interval entirely above zero, and both held-out contrasts (chain 58 minus chain 55, against chain 37 and against chain 46) with intervals entirely above zero. **Flat:** pair 1 within plus or minus 40 inclusive. **Inconclusive:** anything else. Missing, unaccepted or integrity-invalid evidence is unread. A trainer, integrity or marker failure is unread for chain 58 only.
- **Consequences.** Positive: lambda 0.97 is a candidate recipe component; adoption needs a second Positive pair at another training seed or parent, registered then. Chain 58 is a warm-start candidate only if both retention contrasts are also entirely above zero (D418 amendment item 6). Any other reading: lambda stays 0.95. Flat or Negative closes the lambda half of D396's step on tournament evidence at one training seed; the gamma half stays unread.
- **Registered style diagnostics, not gates.** Pair 1, per team turn unless noted, each with the difference chain 58 minus chain 55 and a 95% seed-cluster interval: activations; empty activations; non-empty activations (the difference of the two); blocks (block targets chosen); turnovers; own decisions per game; touchdowns per game. Reference from D421's pair 9, another seed block: plain chain 55 has 2.965 activations, 0.537 empty, 0.466 blocks and 0.326 turnovers per team turn. The same table for pair 11, beside D421's masked values. In-run, from the logs: value loss, explained variance, deciding-row KL and clip fraction against chain 55's bands. Resemblance to human play is a diagnostic; the gate decides.
- **Written down so it cannot be adjusted later.** I expect Inconclusive as the single most likely label, because Positive needs three intervals from one training seed. The style table is what I most want from this rung.

## 6. Second choice, and what to queue behind chain 58

**Chain 59, the control replicate:** `r0chain59-cont49-s2042-20261007`, `b3_chain55.sh` with `SEED=2042` and the new stamp. Nothing else differs from chain 55. Gate on seed block 22800000, harness `7d0d547` without masks: chain 59 against chain 49, chain 59 against chain 55, chain 59, chain 55 and chain 49 each against chain 37 and chain 46, chain 59 and chain 49 each against the offense bot. Labels as chain 55's in D418, against chain 49. Registered descriptive outputs: the replicate-pair gap (chain 59 against chain 55) and the difference between the two rungs' held-out contrasts.

- If chain 58 cannot launch for any reason, launch chain 59 in its place.
- Otherwise queue chain 59 as the stage after chain 58 so the rig does not idle from about 11:00 PDT. Replace it only if chain 57's gate names a new warm start first.

## 7. Not verified

- Nothing on the rig was read. The b3 wrappers and tools quoted are the Mac copies on branch `feat/no-early-end-turn-20261005` (head `94a95df`); the installed ones may differ.
- The per-block table is hand arithmetic from the formulas, not `bb_block_ev` output.
- The learner's gross exposure income, the bot's share of the exposure it loses, and the dice tier of the blocks it declines are inferred, not measured. The off-rig check under candidate (a) measures all three.
- The ledger figures for chain 41 are D416's; I did not see the panels. "About 7.5 own blocks a game" is chain 55's 0.466 per team turn times 16 turns, from tournament play, applied to a training ledger.
- That engine steps per round (43) is the right unit for the trainer's lambda rests on the August audit's statement that both agents step every decision (F11).
- Whether lambda 0.97 without a gamma change behaves like chain 29 in training. Chain 29 is the nearest run, not the same one.
- Whether a `git checkout` in the b3 checkout is safe while a screen script is running from it. The recommendation avoids needing to know.
