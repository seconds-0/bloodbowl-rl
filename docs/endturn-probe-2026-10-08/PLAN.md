# END_TURN probe at registered size: plan (written 2026-10-07 evening, for a run on 2026-10-08)

**Status: a plan, to be committed before any game of it is played. Nothing has been launched and no cloud resource exists for it. It is Test 2 of `docs/plans/exploration-in-training-design-2026-10-07.md`, with the corrections of that study's section 8 and of the Codex review of this plan (`.codex-reviews/endturn-probe-review.md`) applied. It adopts nothing. It is meant to inform which objective-side arm is registered after chain 61.**

Machine-readable twin: `PLAN.json` beside this file (written by `make_plan.py`). It is the authority for which checkpoints and shards exist. The probe, the launcher and the analysis refuse to run against any other plan hash, and each refuses when its own file is not the one the plan names. **sha256 of `PLAN.json` as written with this file: see the last line of this document.** If `make_plan.py` is rerun before the commit (to add chain 60, or after any edit to a tool), that line must be updated in the same commit.

## 1. What is measured, and the one thing it can say

A checkpoint plays plain self-play. At the decisions where it chose END_TURN while it could still activate a player, the probe compares ending the turn with activating the player the policy ranks highest, using **the checkpoint's own evaluator**: its shaped training reward up to the end of its team turn plus its own critic's value there. That is the quantity PPO's advantage is built from.

So the claim this probe can support is about **the critic's pricing**: "under this checkpoint's reward and critic, one more activation is priced above or below ending the turn, by this much, with these parts". It cannot show that ending the turn is right, that it is wrong, or that exploration could or could not change it. The match arm (section 2) adds a comparison that does not use the critic: the shaped return realised when both lines are played to the end of the match. That comparison shows whether the critic's price and the realised return differ. It does not show why.

## 2. Design

**Checkpoints** (blob `0000002999975936.bin` of each, hashes as in the gate plans of chains 58 and 59):

| Name | sha256 | What |
|---|---|---|
| chain55 | `f6ba3b449bf0cec15e37ba47b32b097dd513ee7dba3241b16ad90dd2a0675e0b` | from chain 49, lambda 0.95, training seed 42 |
| chain58 | `a03ed6084b7500cd0c09c89244a79d2ec93059c8cfd1bf98611ef03f22d6ec19` | from chain 49, lambda 0.97, training seed 42 |
| chain59 | `7346125415fecb938fe76e29af4640f4496d8f44fe3d70df6ce63d509b422d12` | from chain 49, lambda 0.95, training seed 2042 |
| chain49 | `a2d1d10dcea3967298e1359efdf831ebe96db19b349f3eca31c81587c7e8bce0` | their parent |
| chain60 | in `PLAN.json` (`checkpoints.chain60.sha256`) | from chain 49, lambda 0.97, training seed 2042 |

**Chain 60.** Its stage ends at about 03:45 PDT on 2026-10-08. It is added by hash (`make_plan.py --with-chain60 <sha256>`) before this plan is committed, and the plan then has five shards. If `PLAN.json` holds no `chain60`, its stage had not produced a checkpoint when the plan was committed, the plan runs with four shards, and every rule below that needs chain 60 reads "not evaluated". Chain 60 is not added after the commit.

**Games.** 200 per checkpoint, engine seeds 29970000 to 29970199, the same seeds for every checkpoint. The block is unused: it does not occur in `DECISIONS.md` or in `docs/` (searched 2026-10-08; blocks in use near it are 29900000, 29910000, 29920000, 29930000 and 29950000; the smokes for this plan use 29940000 and 29940001). The first launch (D436, unread, D437) used 29960000 to 29960199; that block is retired, and its seeds 29960001 and 29960027 are the regression test's (`test_kickoff_turn_roots.py`).

**Play.** The checkpoint against itself, no mask, T=1, kick-off starts, reward manifest `r0_poss_half` (`433c7920...`), harness commit `06f0a5f` (branch `feat/search-probe-20261007`, the reviewed search code). Seat A is HOME in even games and AWAY in odd ones. The other seat is the same network with its sampling seed offset by one stride, as in the search tools. Roots are taken at seat A's decisions only.

**Root classes, and how roots are drawn.**

| Class | Decision | Kept per game | Expected per game |
|---|---|---|---|
| end_turn (primary) | A played END_TURN while an ACTIVATE was legal | all, up to 24 | about 10 |
| decline_block | A played END_ACTIVATION while a BLOCK_TARGET was legal | all, up to 12 | about 3 |
| activate | A played an ACTIVATE while END_TURN was legal | 4, uniform without replacement | about 47 |

Where a cap binds, the kept roots are a uniform sample of that game's decisions of the class (a reservoir), and each root carries the weight (decisions of the class in the game) / (roots kept). Decisions with no legal action of the alternative type are recorded and skipped.

**A decision inside a kick-off Blitz turn is not a root** (added after the first launch, D437). When a kick-off result gives the kicking team a free turn, that team's decisions are made inside the engine's kick-off procedure. Ending that turn does not advance the engine's completed-turn counter, which is what the rollout core stops on, so a rollout from there runs to the end of the team's next real turn: the turn horizon does not apply, and the match arm's depth marks do not count the free turn (the match-end horizon would apply, but one scope for all arms is simpler). The probe leaves such a decision out of every class (`in_kickoff_turn` in `endturn_probe.py`: a kick-off frame on the engine's procedure stack), before the class's count and reservoir, and each game's record counts the decisions left out per class (`kickoff_turn_decisions`). The estimands are therefore about decisions in ordinary team turns. One exception: the style rates the analysis prints per own team turn (activations and END_TURNs over completed turns, from each game's `counts`) are whole-game rates that still include a Blitz turn's decisions. In the two games that failed, one END_TURN decision each was left out (of 8 and 12).

**Arms.** All rollouts use `play_harness.search.Rollouts` at the pin: the checkpoint's network plays both sides, clones are reseeded, and rollout j of every candidate at a root shares its dice and sampling seeds.

1. **Turn arm (every root).** Candidates: the action played (a0), then up to three legal actions of the other type in order of policy probability (ACTIVATE for end_turn, BLOCK_TARGET for decline_block, END_TURN for activate). 64 rollouts each, scored `G = sum of gamma^t r_t + gamma^T V(s_T)` with gamma 0.999, where T is **the actual end of A's team turn** (or the end of the match if it comes first, with no value added).
2. **Forced arm (end_turn roots).** The same alternatives and seeds, but at A's next decision that offers both END_TURN and an ACTIVATE the turn is ended. This is "exactly one more activation, then end". It answers the first review's point that the free continuation can hold further activations.
3. **Match arm (3 end_turn roots a game, uniform among the kept ones).** a0 and the first alternative, 64 rollout pairs each, played to the end of the match. Per rollout: the realised discounted shaped return at gamma 0.999, 0.9995 and 1.0; the return to A's first, second and third turn end with the critic's value there; the final score. Per root: the 28 reward components of the env's ledger, discounted at 0.999 and summed to each of those four horizons. The reward of a match's last step is not itemised by the env after its reset and is kept whole in a 29th entry, `terminal_or_residual`.

**The horizon and the drop rule.** The search's 200-step cut-off is not used. Every rollout's step limit is 8,192 engine steps. A real game allows 4,096 decisions and a clone inherits that budget part-spent, so a rollout ends on a turn end, on the match end or on the inherited decision cap before it can reach the limit. I chose to require an actual turn end, not to register the search's cut-off as part of the estimand, because the quantity in section 1 is the return to the end of the team turn and the cut-off is a device for bounding search cost.
- A rollout that stops on the step limit, or fails, is an integrity error and ends the shard (section 9).
- A rollout that ends on the decision cap has no return. Its rollout index is dropped for every candidate of that root in that arm, **and from every number reported for that root and arm**: the returns and their parts, what the continuation did (further activations, blocks, squares moved), and how often the forced rule ended the turn. The probe stores those per rollout, and the analysis applies one valid-index mask to all of them. This is the only permitted loss, and it is counted per arm in `COMPLETE.json` and in the report.
- A root is left out of every table when fewer than 8 of its turn-arm rollout indices remain in either half (indices 0 to 31, 32 to 63). Its forced-arm and match-arm numbers are left out when fewer than 16 valid pairs remain. Both counts are reported. I expect all of them to be zero.

## 3. Estimands

All are means over end_turn decisions unless a class is named. "Per decision" is the ratio estimate with the weights above, so a game counts in proportion to its decisions. Section 8 of the report gives every estimate and every contrast between checkpoints again with equal weight per game; the 29 single reward components have their per-game versions in the JSON summary only. The readings of sections 5 and 8 use the per-decision versions. Differences are alternative minus a0.

- **E1, the margin (primary).** Turn arm, first alternative minus END_TURN, all valid rollouts, no selection. Reported with its three parts: the shaped reward to the turn end, the critic's value (undiscounted), and what the per-step discount takes from the bootstrap.
- **E2, the isolated margin.** Forced arm, first alternative minus END_TURN, and E1 minus E2. Beside it: how many further activations the free continuation holds, and what the first alternative's activation does (share of rollouts with a block, squares moved).
- **E3, a noisy test over three candidates.** The alternative with the highest mean gain on rollout indices 0 to 31 is judged on indices 32 to 63. An index without a return is left out of its own half; the halves do not move. Shares of decisions where the judged gain is above +0.02, above +0.10, and below -0.02, **each also required to exceed two standard errors of the judging half** (the rule of the exploratory tables). Split by how sure the policy was of a0. This is a test with three candidates and 32 judging rollouts. It is not an oracle and is not called one.
- **E4, critic against realised return.** Match arm, on its sample of roots: the margin with the critic read at depth 1 (this is E1 on those roots), at depth 2 and 3, and the realised shaped return to the match end. The headline is **depth 1 minus realised**.
- **E5, reward components.** Match arm: the difference in each component and in four families fixed here, at A's second turn end and at the match end. Families: *block and rush charges* (block_sequence, block_turnover, rush); *block pay* (block_exposure); *ball* (distance_ball, distance_endzone, possession, ball_gain, touchdown); *result and final step* (result_winloss, result_draw, terminal_or_residual).
- **E6, match result.** Match arm: touchdown difference and win score.
- **E7, the discount.** The discount part of E1; the share of end_turn decisions whose first-alternative margin is above zero as measured, with half the discount part, and without it; "the flipped share", the last minus the first; the realised margin at gamma 0.9995 and 1.0 on the same trajectories. All hold behaviour and the critic fixed. They are arithmetic on these records, not a forecast of training at another gamma.
- **E8, the same tables for decline_block and activate** (turn arm only), and per checkpoint the activations and END_TURN choices per own team turn in the probe's own games.
- **E9, a consistency number.** The return of the action played minus the critic's value at the root, per class.

**Contrasts between checkpoints,** each for E1, its value and discount parts, E2, the realised margin, E4's headline, touchdown difference and activations per own team turn:
- seed: chain59 minus chain55 (both lambda 0.95);
- chain58 minus chain55; chain58 minus chain59; chain58 minus the mean of chain55 and chain59;
- chain55 minus chain49;
- with chain 60: chain60 minus chain59, the lambda difference averaged over the two seeds, and the lambda by seed interaction.

## 4. Intervals

95% percentile bootstrap, 2,000 replicates, generator seed 0, **resampling games (engine seeds)**: all roots and all rollouts of a game move together. All checkpoints play the same seeds and one draw of seeds is applied to all, so contrasts are paired by seed. No interval here covers the training seed. **One look:** `endturn_analyze.py` is run once, on all accepted shards, after the last shard is in. It reads nothing but accepted shards (section 9).

## 5. Questions, and the exact reading of each

"Below zero" and "above zero" mean the whole 95% interval. Every rule here is evaluated by the analysis script and printed with its numbers (report section 7).

1. **Does the exploratory margin repeat?** The exploratory value for chain 55 was -0.0117 [-0.0166, -0.0072] (120 roots, seeds 29950000 to 29950039, 32 rollouts). **Repeats** if chain 55's E1 is below zero. Meaning: at the decisions where it ends the turn, this critic prices the most probable activation below ending. If it is not below zero, the study's reading of its section 2B is withdrawn.
2. **Is it one activation that is priced?** Per checkpoint: **yes** if the interval of E1 minus E2 lies inside [-0.002, +0.002] and a further activation occurs in under 10% of the free continuation's rollouts. Otherwise E2 is the number to quote and E1 prices a longer turn.
3. **How does the critic's price compare with the realised return?** Two statements per checkpoint, and no cause:
   - the realised margin (gamma 0.999, to the match end) is below zero, above zero, or spans zero: whether the shaped return, played out, favoured ending or activating at these decisions;
   - depth 1 minus realised is below zero, above zero, or spans zero: whether the critic priced the activation, relative to ending, lower or higher than the realised return did.
   Neither statement says whether the reward or the fitting of the critic is responsible. A realised margin above zero does not by itself show that the critic under-prices: the critic's margin could be higher still. Only the second statement compares the two.
4. **Which families differ?** A family is **named** when its interval excludes zero at the second turn end or at the match end. All named families are listed with horizon and sign.
5. **Does the match result move?** Reported. An effect of the size the m1 mask implies for one activation is below what this arm can detect (section 6).
6. **How much of the margin is the discount?** E7, reported.
7. **Is chain 58's margin different from those of the lambda 0.95 checkpoints?** Write m for E1.
   - **Range rule** (always evaluated). Chain 58 differs from both by more than they differ from each other if all three hold: the intervals of m58 - m55 and of m58 - m59 both exclude zero; they have the same sign; and the smaller of |m58 - m55| and |m58 - m59| exceeds the seed gap |m59 - m55| (point estimates).
   - **Two-seed rule** (needs chain 60). The lambda 0.97 minus 0.95 difference has the same sign at both seeds if the intervals of m58 - m55 and of m60 - m59 both exclude zero with the same sign.
   - Neither rule is an estimate of a lambda effect. Each side of the comparison has at most two training seeds, and D432 shows two seeds of one recipe differing by 0.41 activations a team turn.

## 6. What the design can detect

"Detectable" is 2.8 standard errors (80% power, 5% two-sided). **Every standard error below is a forecast from a small sample; the report prints the run's own game-clustered bootstrap values, and those replace this table.**

| Quantity | Basis | Standard error | Detectable |
|---|---|---|---|
| E1 for one checkpoint (about 2,000 roots in 200 games) | exploratory run: 0.0024 at 120 roots in 40 games | 0.0006 to 0.0011 | 0.002 to 0.003 |
| E1, chain58 minus mean(chain55, chain59) | the same | 0.0007 to 0.0013 | 0.002 to 0.004 |
| realised margin, one checkpoint (600 roots, 38,400 pairs) | smoke: one pair's difference has spread 0.56 to 0.61 | about 0.003, probably too small | about 0.009, probably too small |
| touchdown difference, one checkpoint | pair spread 0.69 in the search probe's outcome records (under m1) | about 0.0035, probably too small | about 0.010, probably too small |
| win score, one checkpoint | pair spread 0.26, same records | about 0.0013, probably too small | about 0.004, probably too small |

- The three match-arm rows are rough forecasts, not bounds. They are one pair's spread divided by the root of the number of pairs. They leave out the differences between roots and between games and the unequal weights, which the clustered bootstrap includes. Those usually make the standard error larger. Dependence can also make it smaller. I expect the rows to be too small.
- Whether the match arm can tell a realised margin of the critic's size (0.012) from zero is therefore not known before the run. I withdraw the earlier statement that it can.
- m1 buys +32 to +43 Elo with about four more activations a team turn (D416). Spread over those activations that is of the order of 0.001 win score each, below even the forecast for this arm. A null on E6 says nothing about m1.

## 7. Written down before any registered game

- **Seen already.** The exploratory probe on chain 55 (seeds 29950000 to 29950039) and its recount by Codex. Two-game smokes of this tool on chains 55 and 58 at seeds 29940000 and 29940001 (`smoke/`), including their component tables: 12 match roots, which is where the family split comes from. Nothing from the registered block.
- **Families expected to carry a negative difference:** the block and rush charges, at the second turn end, by about -0.005 to -0.015. Expected positive: block pay. Expected to span zero: the ball family and the result. In the smokes the first alternative threw a block in about a tenth of its rollouts and moved one to three squares.
- **Expectations.** Chain 55's E1 below zero, between -0.006 and -0.018. E1 minus E2 inside plus or minus 0.002. The discount part between -0.003 and -0.005 for every checkpoint. E1 of chains 55, 58 and 59 within 0.004 of one another, and neither rule of question 7 holding. The realised margin spanning zero for every checkpoint. E6 spanning zero. No rule of section 8 holding.

## 8. What the result would point at for the rung after chain 61

The candidates named so far: lambda 0.97 from chain 58; `LADDER_GAMMA=0.9995` alone; a reward arm on a family E5 names. The probe can point at a mechanism. It does not rank strength, and a pointer is not a recommendation to adopt.

**Which checkpoint governs.** Chain 58, because the rung after chain 61 trains from it. Rules R and G are read on chain 58's own estimates. G also asks chains 55 and 59 for agreement in their point estimates. L is read on the contrasts of question 7 and on chains 55, 58 and 59 (and 60). Chain 49 governs nothing. If chain 58's shard is not accepted, no rule is evaluated and the outcome is reported without a recommendation.

**R, a reward pointer.** All of:
1. chain 58's realised margin (gamma 0.999, match end) is below zero;
2. chain 58's *block and rush charges* family at the match end is below zero;
3. that family's point estimate is at least half of the realised margin's point estimate in magnitude;
4. chain 58's *ball* family at the match end is not below zero.
If 1 to 3 hold and 4 fails, two families are named: the outcome is reported without a recommendation. The block pay and the result family are reported and enter no rule.

**G, a gamma pointer.** All of:
1. chain 58's depth 1 minus realised is below zero;
2. chain 58's E1 is below zero;
3. chain 58's discount part is at least a quarter of its E1 in magnitude (point estimates);
4. chain 58's flipped share (E7) is at least 0.10 and its interval is above zero;
5. conditions 3 and 4's point parts (a quarter; 0.10) also hold for chain 55 and for chain 59.

**L, a lambda pointer.** All of:
1. question 7 holds with chain 58 the less negative: the two-seed rule with a positive sign when chain 60 is in the plan, the range rule with a positive sign when it is not;
2. |depth 1 minus realised| of chain 58 is smaller than that of chain 55 and than that of chain 59 (point estimates);
3. the interval of chain 58's depth 1 minus realised, minus the mean of chain 55's and chain 59's, excludes zero.

**Outcome, by this table and nothing else.**

| Rules that hold | Outcome |
|---|---|
| R alone | The probe points at a reward arm on the block and rush charges (the arm D422 set aside). |
| L alone | The probe points at lambda 0.97. |
| G alone | The probe points at gamma 0.9995. |
| G and L | Lambda 0.97 first, gamma 0.9995 as the arm after it. Lambda takes precedence because it is the factor with a tournament reading (D428) and a registered second pair (D429); gamma has neither. |
| R together with G or L | Reported without a recommendation. |
| none | Reported without a recommendation. |

**Not licensed by any outcome:** adopting a setting; a statement that ending the turn is right or wrong by match result; a statement about exploration; a lambda effect; a statement of which of reward and critic fitting causes a gap; a forecast of what training at another gamma, lambda or reward would do.

## 9. Integrity and acceptance

**Fail-fast in the probe.** The sixteen checks are listed in `PLAN.json` (`integrity_checks`) and in every `COMPLETE.json`. In the real game: the engine's return code, the five hard counters after every step and at the end, both seats' logits and values and the opponent-view state finite, both seats' rewards finite and within the env's own clip threshold (`bbe_reward_clip_threshold`, read from the env), and a natural match end (`STATUS_MATCH_OVER`; a game that ends on the decision cap is not accepted). In rollouts: the rollout core's own checks with the same reward limit, no failed rollout, no stop on the step limit, the stop kinds each arm allows. Any failure stops the worker, the run writes `FAILED.json` and no `COMPLETE.json`, and the shard is not accepted. The only loss that does not end a shard is the decision-cap drop of section 2.

**A shard is accepted** (`endturn_accept.py`, used by the launcher after the fetch and by the analysis before it computes anything) when: every file matches the droplet's SHA256SUMS; the shard's `plan.json` is this plan; its machine built the pinned commit; `COMPLETE.json` names this plan's hash, the checkpoint's hash, the harness commit, the tool hashes, the manifest, the settings and the integrity list; no game is invalid and no rollout failed or hit the step limit; the probe's checks are inside their limits, and every class of every game that had an eligible root for the identity check had it, with at least one in the shard; `roots.jsonl` and `games.jsonl` hash to what `COMPLETE.json` recorded; the games are exactly engine seeds 29970000 to 29970199, each once, each natural with zero hard counters; and the roots belong to those games in the counts the games recorded.

**The analysis refuses** to compute anything unless the plan hashes to the value given, its own file and `endturn_accept.py` are the files the plan names, every input is an accepted shard, and all shards ran on one engine library. It does not read unfinished or worker files.

- A checkpoint whose shard is not accepted is unread, and the contrasts and rules that need it read "not evaluated".
- A shard cut by the time limit or stopped by an integrity failure is not completed by relaunching part of it. It is rerun whole under a new run name, or left unread. A rerun is decided before the analysis is run, never after.
- If the hourly price, a full account, a name already in use or a failed build stops a launch, nothing is read and nothing is deleted to make room.

**What the probe's checks do and do not cover.**
- The identity check runs on the first eligible root of each class in each game, not on every root. A root is eligible when its recorded turn arm lost no rollout to the decision cap; an ineligible root is passed over and nothing is run on it. The check compares the turn arm computed with both hooks removed, with both installed and idle (the record), and for end_turn roots through the tool's own entry; the two extra computations pass the turn arm's rollout checks themselves, and all must agree exactly with every value finite. It does not exercise the hooks while they are active. A shard with no eligible root at all is not accepted.
- The component check shows that the 28 components sum to the step's reward on every step before a rollout's last (within 1e-5), and that the components plus the last step's reward sum to the rollout core's total. It cannot show that the env attributes a reward to the right component, and it does not itemise the last step.
- The engine library is the pinned shim compiled together with four read-only accessors (`endturn_shim.c`). Two games were compared step for step against the pinned shim before this plan (`NOTES.md`); that comparison is not repeated on the droplet.

## 10. Operation

```
D=docs/endturn-probe-2026-10-08
bash $D/export_harness.sh <EXPORT>                 # git archive of 06f0a5f; changes no worktree
H=<sha256 of PLAN.json, the last line of this file>
# every shard of the plan, each on its own droplet, launched together:
python $D/endturn_droplet.py run --name et1 --plan $D/PLAN.json --expect-sha256 $H \
    --harness-export <EXPORT> --max-hours 3.5 --max-total-usd 3.5 --dry-run --assume-hourly 0.16667
# then the same line without the two dry-run options
R=runs/endturn-probe-2026-10-08/et1                # git-ignored; the launcher's default --out-root
python $D/endturn_analyze.py --plan $D/PLAN.json --expect-sha256 $H \
    --shard-dir chain55=$R/chain55 --shard-dir chain58=$R/chain58 --shard-dir chain59=$R/chain59 \
    --shard-dir chain49=$R/chain49 [--shard-dir chain60=$R/chain60] \
    --out $D/report.txt --json $D/report.json
```

- **Shards.** One per checkpoint, each on its own droplet (`s-8vcpu-16gb-amd`, sfo3, the harness's tag `bb-harness-tournament`, eight processes): five with chain 60, four without. They are launched together by one command. The analysis is run once, after every shard has either been accepted or been declared unread.
- **Names and ownership.** Each run draws a six-digit random run id. The droplet, its ssh key and its local state are named `et1-<shard>-<run id>`. Before it creates anything the launcher refuses if that local state exists or the account already lists a droplet or key of that name. The harness's lifecycle code is imported from the export, held to the hash in `PLAN.json`, and not changed. This makes it very unlikely that its recovery (by tag, exact name and creation time) finds anything but this run's droplet. It is not a proof of ownership: the listings read the first 200 droplets and keys only, and another process could create the same name between the check and the create. After the teardown the launcher removes an ssh key of the run's own name whose id was lost, and reports any droplet of that name still listed. It deletes nothing else.
- **The time budget.** `--max-hours` is the budget for a droplet's life, not a ceiling. Before each phase (key, create, boot, install, upload, build, launch, fetch) the launcher checks the time left before the limit less a 300-second reserve and does not start a phase past it. Its own ssh and copy calls get a timeout no longer than the time left. The harness's calls are not bounded that way: the key registration and the create are only checked before they start (the create can retry for about five minutes), and the wait for boot and the poll check their deadline between attempts and can overrun it inside one (a poll by about 90 seconds, an API read by about three minutes when DigitalOcean is slow). On any failure only small logs are fetched, for at most 45 seconds in all, and then the teardown starts. Records of a failed shard are not fetched. An interrupt (Ctrl-C) stops further shards from being started and makes every started shard tear down.
- **The spend guard.** Shards x `--max-hours` x the hourly price must not exceed `--max-total-usd`, or nothing is created. Limits that are not finite positive numbers are refused. A child process applies the guard for the whole run.
- **What a run costs, stated plainly.** *Nominal budget, when every call returns:* `--max-hours` x price a shard ($0.58 at 3.5 hours) plus the teardown, normally under five minutes and about $0.01: about $2.97 for five shards, against an estimate of $1.58. *This is not a ceiling.* The harness's teardown retries each of its API calls up to 120 times with a 30-second timeout and a 5-second sleep, so **one call can last about 70 minutes when DigitalOcean is slow or down, about $0.19 a droplet for each such call ($0.97 for five), and the teardown makes several calls in a row.** I cannot state a finite worst case for it. **Power loss or sleep of the Mac, a killed runner, a create whose answer is lost and whose droplet appears later than the recovery looks for it, or a delete that fails can each leave a droplet billing at $0.167 an hour until an operator destroys it. Nothing on the droplet stops it.** The cleanup needs only the export and the token file. It is printed at launch and written to `runs/endturn-probe-2026-10-08/et1/CLEANUP.txt` before anything is created, with this run's names, token file and state directory:
  ```
  python <EXPORT>/tools/droplet_tournament.py --env-file <ENV> status
  python <EXPORT>/tools/droplet_tournament.py --env-file <ENV> destroy --name et1-<shard>-<run id>
  python <EXPORT>/tools/droplet_tournament.py --env-file <ENV> destroy --id <DROPLET_ID>
  ```
  The first lists every tagged droplet and key. The second uses the local state the dead runner left; it reads the default state directory only, so a run started with another `--state-root` is cleaned up with the third, which needs no local state (`CLEANUP.txt` then gives that form with the path of the droplet's id). `<ENV>` is the token file the run used (default `~/code/killteam-3d/.env`). Keep the Mac awake and on power for the run (`caffeinate -ims`), and check `status` after it ends.
- **Cost.** Measured on the Mac, single process, at these settings (two-game runs, `smoke/`): 26 to 45 seconds a game, about 172,000 rollout engine steps a game at 4,100 to 8,000 steps a second depending on what else the Mac was doing. D426 measured the same rollout core on this droplet size at 963 steps a second per process with all eight busy, 7,700 a droplet, which would be 22 seconds a game. This probe's steps cost a little more, so the plan assumes 32 seconds a game. It had not been measured on a droplet when the plan was first written; the unread first launch then ran at 28 to 37 seconds a game on three droplets over their first 13 or 14 games. So about 1.9 hours and $0.32 a checkpoint: $1.26 for four, $1.58 for five.
- **The smoke shard.** One real droplet, two games on seeds outside the registered block, before the registered launch: the command is in `NOTES.md`. It is the only test of the droplet path and reads nothing. It ran on 2026-10-07 with the first version of the probe; the droplet path has not changed since. Two games are too few to meet a rare game situation, which is how the first launch failed (D437); before the second registration the changed probe also played 120 games on the Mac at four rollouts on seeds outside the registered block, with no integrity failure (`NOTES.md`).
- Records land in the repository's git-ignored `runs/endturn-probe-2026-10-08/<name>/<shard>/<checkpoint>/` (`roots.jsonl`, `games.jsonl`, `COMPLETE.json`), about 40 MB a checkpoint.

## 11. Limits

- Every root comes from the checkpoint's own plain self-play and from the action it sampled. The margin is conditional on the states where that checkpoint ends its turn. A checkpoint that activates more ends its turns in other states, so a difference in E1 between checkpoints mixes the critic's pricing with which states are being priced.
- The opponent in every rollout is the checkpoint's own network.
- One changed action followed by the policy's own play. A coordinated sequence of better actions is not tested.
- The realised return is the shaped reward. E6 is the only measure of match result and is weak (section 6).
- The alternative is the policy's most probable activation, not the best one. E3 looks at three.
- Question 3 compares two numbers. It does not separate the reward from the critic's fitting as the cause of a gap, and both can contribute.
- The checks of section 9 have the scope stated there.

sha256 of `PLAN.json`: `69132d835e49a0ca5cd619a2a0045d95dda50cfe47531e20ffeed50dc4dd58a7`
