# Blood Bowl RL reward and replay audit — 2026-07-09

Status: audit report and experiment specification. This document is deliberately
stricter than the historical decision log: it separates current BB2025 rules,
observed training results, confirmed implementation defects, plausible strategy
hypotheses, and experiments that have not yet been run.

The core rules/reward fixes, reward manifests, and BBTV safety corrections
referenced below have passed review and landed in the repository. That does not
make a target training environment deployment-complete: each future run still
requires an installed-snapshot drift check, clean Puffer rebuild, imported
module provenance, and a fresh baseline. Historical curves must not be compared
numerically across semantic fixes without an explicit bridge evaluation.

## Executive verdict

The reward problem is not one bad coefficient. Five effects have been
confounded repeatedly:

1. **The optimized utility has changed implicitly.** A touchdown bonus, a
   negative draw value, a possession annuity, and combat rewards all define a
   different game from match win/loss. Their coefficients are not merely
   learning-rate aids.
2. **Several reward measurements were wrong or invisible.** Turn completion
   was inferred from `active_team` changes, long-range distance potentials
   collided with a `-1` sentinel, explicit all-zero objectives could be
   overwritten by fallback defaults, and PPO's per-agent-step `[-1, 1]` clamp
   was not visible in the environment dashboard.
3. **Many successful-looking rewards optimized an instrument instead of Blood
   Bowl.** Possession could become camping, block upside could become indiscriminate
   violence, and threat could become passive menace. Decision-time expectation
   is better than paying realized dice luck, but it can still redefine the
   objective.
4. **The opponent distribution has been too weak and too narrow.** The strongest
   recent causal result is not a new reward: training against a competent cage
   offense sharply improved defense. The size of that in-sample gain also makes
   overfitting the next thing that must be tested.
5. **Replay artifacts mix editions and are sharply censored toward early game.**
   The raw archive contains both BB2020 and BB2025. Current behavior pairs and
   state banks stop at first lockstep divergence, contain no second-half states,
   and heavily over-represent turns 1–2.

The best current **historical anchor**, reconstructed from D169, is:

- touchdown `0.4`, terminal win/loss `±0.6`, draw `0`;
- possession `0.03`, ball gain `0.05`, ball loss `0`;
- distance-to-ball `0.05`, distance-to-endzone `0.20`;
- rush cost `0.015`;
- decision-time block terms `k_kd=0.10`, `k_value=0.50`, `k_ball=0.15`,
  `k_turnover=0.15`, and `k_seq=0.03`;
- all other shaping off.

That is an anchor, not the recommended final reward. Because the possession and
distance implementations have now been corrected, its next run must be called
**R0 full, re-baselined**, not a bit-identical D169 reproduction.

The first repaired 20M native preflight then invalidated the historical
distance magnitudes themselves. After correcting native eval/reprint counting,
the `.05/.20` recipe produced 22,859 unique completed games, 42 episodes with
at least one clipped reward (`0.1837%`), and `14.54` total raw reward excess.
The excess appeared in long-jump-sized increments consistent with same-team
catches, throw-ins, and transfers moving the carry/fetch potential several
squares in one decision. No non-finite, engine-error, or demo-fallback episode
occurred. The proposed R0/R2 distance scale is therefore `.02/.04`, matching
the repository's documented stage-1 scale and bounding either full-pitch
channel to at most `0.5/1.0` before runtime co-firing checks. The `.05/.20`
preflight is diagnostic evidence, not an experiment arm.

The immediate research recommendation is:

1. land and verify the audit fixes;
2. rebuild a strict BB2025 data allowlist and state bank;
3. re-evaluate the frozen checkpoints under the corrected metrics;
4. run a paired 2×2 ablation of possession/gain and distance shaping while
   keeping the settled block scaffold fixed;
5. test opponent diversity separately from reward design;
6. prefer the simplest reward that is non-inferior on held-out match strength;
7. require cross-seed, cross-ancestor, and held-out-opponent reproduction before
   changing the production recipe.

In the isolated audit checkout, items 1–4 are complete: all eight paired 250M
arms passed their immutable acceptance contract, and the R0/R2 finalists then
completed a 16-cell scripted-opponent transfer matrix. R0 retained a small but
consistent transfer advantage; R2 was worse in all eight matched
seed/style/side cells. This does not mark any production reward as promoted.
The combined possession-annuity/ball-gain family still needs decomposition,
learned-opponent and roster-grid transfer, longer confirmation, a second
ancestry, review/commit, and the normal deployment path.

The first full possession/gain decomposition attempt on July 13–14 completed
all eight arms but is rejected under D182. One training emission in the final
arm exceeded PPO's clamp by exactly `0.015`. The retained telemetry did not
record its sign or terminal context, so its exact co-firing components are
unknown. The any-clip gate correctly withheld `SCREEN_COMPLETE.json`; its
preliminary factorial is not causal evidence and cannot feed transfer. The
follow-up code audit independently confirmed that terminal result utility could
stack with arbitrary same-action shaping. Terminal composition must preserve
explicit current-step objective reward (TD), discard incidental shaping, add
result utility, leave deliberately episode-terminal terms separately
clip-visible, and split any future terminal/non-terminal clip recurrence. Every
arm must be rerun under that uniform corrected contract.

The likely destination is a zero-sum terminal match utility, exact
potential-based value shaping if it is needed, small temporary decision-time
scaffolds, replay-derived tactical curricula, and diverse competent opponents.
It is not another permanent menu of event bonuses.

## Scope and evidence standard

This audit used:

- the current engine, Puffer environment, reward hooks, tests, launchers, and
  reward configuration;
- the full `DECISIONS.md` reward history through D176;
- `docs/reward-audit-decision-time.md`,
  `docs/reward-design-coaching-wisdom.md`, and the reward-discovery documents;
- current BB2025 core rules and the May 2026 FAQ;
- current GW tactics articles, NAF resources, NAF-linked legacy playbooks, the
  vendored AndyDavo analyses, and canonical Blood Bowl AI papers;
- the local replay cache and the canonical B2 inventory of raw replays, BBP
  behavior pairs, and BBS state-bank records.

Evidence labels used below:

| Label | Meaning |
|---|---|
| **Rule** | Current BB2025 rulebook or FAQ text. |
| **Confirmed defect** | Reproduced in code/data with a focused test or exact audit. |
| **Historical result** | Recorded training/evaluation result; may predate current semantic fixes. |
| **Strategy doctrine** | Convergent coaching guidance; contextual rather than a scalar target. |
| **Hypothesis** | Requires the specified matched experiment. |

Historical dashboard values are evidence about direction, not automatically
comparable measurements. This is especially important for possession, distance
shaping, curriculum-start episodes, native/torch conversions, and tournament
runs whose effective sample size was smaller than the naive game count implied.

## BB2025 rule authority and edition hygiene

### Authority order

1. Games Workshop's Third Season core rules and current FAQ/errata are
   authoritative. The official download hub is
   [Warhammer Community: Blood Bowl downloads](https://www.warhammer-community.com/en-gb/downloads/blood-bowl/).
2. The current FAQ announcement is
   [Blood Bowl FAQs and Games Designers' Notes, May 2026](https://www.warhammer-community.com/en-gb/articles/wqewdcvv/blood-bowl-faqs-games-designers-notes/).
3. The searchable
   [Blood Bowl Base BB2025 core rules](https://bloodbowlbase.ru/bb2025/core_rules/the_game_of_blood_bowl/),
   [rules and regulations](https://bloodbowlbase.ru/bb2025/core_rules/rules_and_regulations/),
   and [latest FAQ mirror](https://bloodbowlbase.ru/bb2025/core_rules/latest_faq/)
   are useful local/search references but are unofficial mirrors; disputed
   points should be checked against the GW PDFs.
4. [NAF BB2025 recommendations and clarifications](https://www.thenaf.net/naf-recommendations-and-clarifications-for-bb2025/)
   are the relevant organized-play interpretation layer.
5. Strategy articles and older playbooks are advice, not rules authority.

The deployment target in this repository is **BB2025 / Third Season**, released
in November 2025, with the May 2026 FAQ. Do not silently combine it with:

- BB2, CRP, or LRB-era rules;
- BB2020 / Second Season;
- a digital game's partial implementation;
- Sevens, Dungeon Bowl, or house rules;
- league-persistent, resurrection-tournament, and match-only utilities.

[NAF's playbook index](https://www.thenaf.net/resources/playbooks/) explicitly
notes that many linked guides are BB2016/CRP-era. Their positional principles
often transfer; their reroll limits, skills, rosters, action rules, passing
math, and numeric foul/attrition advice do not transfer automatically.

### Rules that directly affect reward design

#### Match and turn structure

- A match normally has two halves and eight rounds per half.
- Each team receives one turn per round; the team that received at the start of
  the half acts first in each round.
- Each eligible player normally activates at most once per team turn.
- A turnover ends the active team's turn, so unspent activations are a real
  resource.
- A touchdown ends the drive. The winner is the team with more touchdowns;
  equal scores are a draw.
- Blitz, Pass, Hand-off, Foul, Secure the Ball, and Throw Team-mate are normally
  limited to one declaration of each kind per team turn. Move and Block actions
  are not globally limited in the same way.

The May 2026 erratum states that an inactive-team player ending in possession
after an attempted Pass **or Hand-off**, or by intercepting, causes a turnover.
The engine and any turnover telemetry must reproduce the current wording.

#### Team rerolls

A coach may use as many team rerolls as desired in one team turn, but a die or
dice pool cannot be rerolled twice. Team rerolls replenish at halftime and do
not carry from the first half into the second. They cannot reroll scatter,
armour, injury, casualty, throw-in, bribe, Argue the Call, or Crowd Takes
Action. BB2-era “one team reroll per turn” advice is obsolete.

This rules out a blanket “multiple rerolls in one turn is bad” metric. The
relevant quantity is the value of the reroll now versus its remaining half-long
option value.

#### Secure the Ball

Secure the Ball is a Third Season action:

- at declaration, the loose ball cannot be within two squares of any standing,
  non-Distracted opponent;
- it is normally limited to one declaration per team turn;
- Big Guys and players with the relevant prohibition cannot use it;
- the player may first Move to the ball, so movement can still require risky
  rolls;
- the pickup is a flat 2+ D6 roll and the activation ends;
- Pouring Rain applies;
- Agility-test modifiers do not apply because it is not an Agility Test;
- Sure Hands does not reroll it.

Secure the Ball is therefore not categorically safer. An AG2+ ordinary pickup
has the same base target and allows continued movement; Sure Hands, weather,
remaining movement, nearby opponents, and the failure state can reverse the
choice. Rewarding the action type would be wrong. Evaluate its contextual
regret against ordinary pickup and leaving the loose ball controlled.

#### Stalling

Third Season defines Stalling narrowly. A player is Stalling when the player:

1. possesses the ball when activated;
2. can score without rolling any dice; and
3. finishes the activation still carrying the ball without scoring.

A completed Pass or Hand-off that leaves that player without the ball is not
Stalling. If an earlier turnover ends the team turn before the carrier can be
activated, that carrier is not Stalling. Forgoing the carrier's activation
still triggers the check.

At the end of a Stalling activation, Crowd Takes Action knocks the carrier down
and causes a turnover on `D6 >= current team-turn number`. The roll cannot be
team-rerolled.

| Team turn | Crowd-action probability |
|---:|---:|
| 1 | 6/6 |
| 2 | 5/6 |
| 3 | 4/6 |
| 4 | 3/6 |
| 5 | 2/6 |
| 6 | 1/6 |
| 7 | 0 |
| 8 | 0 |

The executable engine now implements this consequence in the activation/team-
turn procedure boundary (D193). Eligibility is snapshotted before the declared
action, using an occupancy-aware reach field plus compulsory activation-roll
checks; the ordinary knockdown procedure owns Steady Footing, ball release,
armour/injury, and Turnover resolution. This is simulator law, not a reward
term. Residual scope is explicit: Fumblerooski is not implemented, and the
engine's broader Steady Footing path still auto-rolls without exposing the
FAQ-permitted team-reroll choice. The current action interface can voluntarily
end the whole team turn—and correctly treats that as forgoing the carrier—but
does not yet expose the finer choice to forego only one player and continue
activating others.

The classic turn-8 score and 2–1 grind remain important tempo concepts, but an
old unconditional “stall whenever possible” prior is no longer rule-correct in
early turns. In league play, a team also adds one unit when calculating
winnings if no player on the team was deemed to be Stalling, worth 10,000 gold
pieces. That league incentive is outside a match-only objective unless it is
modeled explicitly.

#### Match, tournament, and league utilities

Human replays do not all optimize the same future:

- a match-only agent values the current result;
- a league coach also values SPP allocation, player survival, treasury,
  winnings, future roster development, and sometimes concession effects;
- a resurrection tournament resets attrition and may use custom 3/1/0 points,
  margin, casualty, or tiebreak rules.

“Score with the right player,” safe vanity completions, protecting an expensive
star in a decided game, or declining early Stalling for league winnings can be
rational human actions and incorrect labels for a match-only bot. Replay format
must be tagged before imitation or inverse-reward work.

## Strategy implications for observables and reward design

Useful current official introductions include GW's
[cage, screen, and counterplay article](https://www.warhammer-community.com/en-gb/articles/buo482id/touchline-tactics-how-to-counter-common-plays/)
and its
[fouling, surfing, tempo, and probability article](https://www.warhammer-community.com/en-gb/articles/myjrlrb0/touchline-tactics-how-to-cheat-your-way-to-the-top-in-blood-bowl/).
The latter predates Third Season's Stalling rule, so its clock doctrine transfers
but its Stalling mechanics do not. NAF's old but durable
[The Art of Blocking](https://www.thenaf.net/wp-content/uploads/2013/06/The-Art-Of-Blocking.pdf)
is particularly clear that pointless blocks are not the objective: touchdowns
win games.

| Doctrine | What should be measured | Reward/evaluation implication |
|---|---|---|
| Consequence-aware ordering | Declared turnover probability and the value of actions/positions lost if the turn ends | `P(turnover) × raw unused-player count` is only a proxy. Weight a required screen square or scoring threat above an irrelevant lineman move. Urgent risky actions may correctly happen first. |
| Blocking is instrumental | Exact skill/assist matrix, target role/value, ball state, push/follow-up/chain-push/surf geometry, clock | Human 2D share is conditional on blocks chosen, not a target number of blocks. A decision-time knockdown bounty can still cause over-blocking. |
| Assists are relational | Counterfactual block odds before/after a move; offensive and defensive assists | Static player “threat” or standing-assist bonuses invite contact clustering. Use telemetry or auxiliary prediction before a permanent reward. |
| Cage and screen are functions | Opponent's best legal sack probability, lane displacement, Blitz scarcity, carrier progress, score/clock | Do not reward cage corners, adjacency, or a fixed template. A loose cage, sideline shape, staggered screen, or multiple receivers can all be correct. |
| Loose-ball control is not possession | Each side's next-turn secure probability, pickup odds, bounce/failure coverage, TZs on the ball | A 4+ pickup can be worse than standing on the ball. Gain bonuses invite suicidal attempts and cycles; loss fines can teach ball refusal. |
| Defense often wins by delay | Opponent next-turn TD probability, carrier progress, zero-TZ lanes, deep safety, forced dice | Do not reduce defense to immediate sacks or raw marking. Screens deliberately avoid contact; basing becomes correct when it consumes the scarce Blitz or the clock demands it. |
| Tempo is conditional | Score, both sides' turns left, receiving order, possession/control, material, rerolls | Do not scale TD reward by turn or pay Stalling directly. A calibrated value surface should express when to stall, score quickly, or accept an early score. |
| Rerolls are a half-long budget | Rerolls remaining, half-turn, action consequence, skill rerolls, Loner, future required rolls | “Never reroll a push” is false for a sack, surf, or critical lane. Measure contextual reroll regret. |
| Fouls, surfs, and attrition are contextual | Target value/skill, fouler cost, assists, bench, bribe/Argue odds, ball and clock | Flat removal, send-off, foul, or surf bonuses either suppress rational fouls or create a boot/sideline obsession. |
| Team identity matters | Every metric by roster archetype, matchup, score, clock, numerical strength, weather, and skills | A single pooled human action rate suppresses elf, bash, hybrid, and stunty strategies. |
| Multiple good lines are normal | Macro intent, end-of-turn function, action-value percentile or top-k equivalence | Exact human-action accuracy penalizes equivalent zero-roll orderings and destinations. It is not a sufficient policy-quality metric. |

Two coaching slogans require explicit qualification:

1. **“Safe actions first”** means bank actions whose value would be lost on a
   turnover. It does not mean every zero-roll move must precede an urgent sack,
   an opening block, or a volatile activation used to reveal information.
2. **“Throw as many two-dice blocks as possible”** is not a universal Blood
   Bowl objective. Agile and fragile teams often screen and disengage. Even a
   favorable block can be wrong when its turnover risk, activation cost,
   follow-up, carrier exposure, or clock consequence exceeds its value.

## Reward-history audit

### What “decision-time pricing” does and does not solve

Paying a realized casualty rewards luck and creates a sparse, high-variance
credit channel. Pricing expected removal at declaration is better attribution.
It is not automatically a correct reward. A pre-dice `P(knockdown)` bounty
still changes “win Blood Bowl” into “win Blood Bowl plus knock players down.”

The stricter rule is:

> Permanent shaping should either be exact potential-based shaping, or estimate
> a complete contextual advantage rather than one side of a bet. Narrow
> decision-time terms should be treated as temporary curricula, capped,
> monitored for Goodhart behavior, annealed away, and required to preserve
> terminal strength after removal.

This also explains why charging every own risky roll is dangerous: the immediate
downside is charged now, while its strategic upside arrives later through the
critic. A policy can learn passivity even when the action is positive EV.

### Historical findings

| Decision/result | Observed result | Durable lesson |
|---|---|---|
| D43, lump ball gain plus future loss fine | A kickoff-trained policy stopped attempting a free scoop and played around an untouched ball. | Ball gain/loss can make taking possession negative in expectation. The environment must not punish the entire future downside without pricing the upside. |
| Possession annuity | Restored willingness to hold/carry and produced some scoring progress. | It is an income stream, not PBRS. It can also pay for camping and Stalling, so it belongs in an ablation, not as unquestioned truth. |
| D34/D39, stronger contact EV | Cured never-blocking but earlier full-strength contact profiles could crowd out scoring. | Combat needs opportunity cost and terminal-strength gates. |
| D141/D148, realized injury restoration | Blocks moved only about 6.8→7.8; tournament result was effectively tied at 0.493/0.507. | Realized injury reward paid rare luck and was a dead end. |
| D150–D155, carrier-threat annuity | Expensive evaluation and drift toward positional passivity; contact and advancement fell. | Paying “being threatening” can substitute for committing the useful action and can create menace/camping equilibria. |
| D156/D157, block-upside “violence” arm | Blocks rose roughly 5→15.7, TDs about 0.35→1.43, and forward ball advancement rose to about 6.97; dice selection barely improved. | Blocking opened lanes and helped scoring, but scaling upside increased blocks of every quality. |
| D158, still larger block coefficients | Blocks rose to about 21.1 while 2D-red share worsened to about 0.13. | Multiplying a positive term cannot change its internal quality ratios. |
| D159/D160, flat block-turnover cost | 2D-red fell about 0.12→0.056, 2D rose to about 0.543, and scoring held. | Pricing block-dice turnover probability changed selection rather than only volume. This is the best-supported block-reward result. |
| D162, doubled turnover coefficient | 2D improved further, but block volume and TDs fell; 2D-red was sticky near 0.049. | Residual bad blocks were not simply under-priced. Raising the coefficient further became over-caution. |
| D163, assist audit | Agent offensive assists per block were roughly half the measured human values across tiers. | The remaining dice-mix gap was structural/positional, but human similarity alone does not prove assisting more wins. |
| D164/D165, assist potential | Did not increase assists or improve dice mix; did increase blocks and TDs. | A telescoping potential can accelerate a base preference but cannot manufacture a different optimum. |
| D169, pending-scaled sequence cost | 2D reached about 0.608, 2D-red about 0.044, TDs about 1.563; assists remained noisy/flat. | Expected lost activations materially improved block selection. The value of pending actions remains a better future refinement than their raw count. |
| D170–D176, competent offense opponent | The baseline champion allowed about 1.156 TD/episode to the cage bot. The clean no-anchor defense arm reached about 0.251 against that same bot. | Opponent quality created a strong defensive learning signal without a new defensive reward. The result is in-sample and must be tested for transfer. |
| D176, full-strength iid CE anchor | Offense collapsed to zero TDs while the unanchored control remained functional. | A coefficient-1 corpus CE anchor pinned the policy off its reward manifold. This does not prove every small/adaptive on-policy KL is impossible, but it makes a weak teacher and strong fixed anchor low priority. |

These were mostly warm-started, single-lineage experiments. Several used
curriculum-start episodes, old possession semantics, or checkpoints converted
between native and torch. The directional lessons are valuable; precise effect
sizes require the fresh matrix later in this report.

### Human block statistics are canaries, not objectives

The exact 11,580-game BB2025 rebuild, counting one resolved block at its dice
choice rather than every FUMBBL roll report/reroll, found:

- 2D attacker-choice blocks: `0.77146642`;
- 1D blocks: `0.11859591`;
- 2D-red defender-choice blocks: `0.01765550`;
- 3D-red defender-choice blocks: `0.00051228`;
- 3D attacker-choice blocks: `0.09176988`;
- all defender-choice red blocks: `0.01816779`;
- resolved blocks per game: `80.2394` (population SD `18.4838`).

The legacy `88.83` blocks/game and nearby fractions counted FUMBBL block-roll
reports, including rerolls, and are retained only as historical dashboard
context. Even the corrected shares are **conditioned on a human choosing to
block**. They cannot be compared directly to a single team's curriculum
episode. Target value, carrier status, skills, assists, roster, and clock strata
are required before diagnosing a residual red block as bad.

### Common reward-hacking modes

| Reward/proxy | Likely exploit |
|---|---|
| Possession annuity | Backfield camping, delaying a safe TD, excessive Stalling. |
| Ball gain plus loss fine | Refusing the ball; repeated transfer cycles if signs are reversed. |
| Distance to ball/endzone | Oscillation, ball chasing, unsupported carrier sprint. |
| Positive safe activation | Null-move farming and purposeless turn elongation. |
| Generic own-risk tax | Passivity, refusal to engage, draw lock. |
| Knockdown/removal/block volume | Brawling, low-value targets, blocks after the meaningful play is secured. |
| Threat/proximity/adjacency | Menace without action, marking spam, static contact clusters. |
| Fixed cage/setup shape | Brittle formation copying and team-style suppression. |
| Pass/handoff/completion | Vanity actions and ball-transfer loops. |
| Foul/send-off/surf | Boot parties, total foul suppression, sideline obsession. |
| Global human-stat distance | Pooled-style collapse, optimizing realized luck, untracked-dimension exploits. |
| Correlated reward terms | Double-counting one strategic transition several times. |

Zero-sum transfer prevents both players from jointly inflating total return. It
does **not** preserve the original game's Nash policies and does not prevent
over-blocking or mutual non-aggression equilibria.

## Confirmed defects, fixes, and remaining cautions

### Confirmed audit fixes in the current working tree

| Defect | Impact | Current fix/verification requirement |
|---|---|---|
| Explicit `reward_td=0` and `reward_win=0` were indistinguishable from “caller omitted defaults.” | A sparse or win-only experiment could be silently rewritten to legacy fallback values on reset. | `reward_configured` separates configured zero from absent configuration; standalone defaults are centralized at `TD=.4`, `win=.6`, `draw=0`. Focused tests cover both cases. |
| The environment logged raw accumulated return while PPO clamps each emitted agent-step reward to `[-1,1]`. | Objective stacks and statmatch penalties could silently saturate; raw `episode_return` described a reward the learner never received. | Per-step raw maximum, clip fraction, nonzero-step clip fraction, excess, non-finite fraction, and episode-level any-clip/non-finite indicators are added. Complete manifests reject non-finite/out-of-range coefficients and deterministic terminal stacks over 1. Final acceptance requires zero terminal clipping and effectively zero shaping clipping. |
| Possession/turnover bookkeeping and positional turn-end shaping inferred a completed turn from final `active_team` changes. | It missed scoring turns that unwind the stack without a flip and compressed empty turns that flip twice inside one advance; kickoff/Charge transitions could be mistaken for turn boundaries. Possession, turnover, and configured positional turn-end rewards could be skipped. | Monotonic engine counters record completed turns, held endings, and turnovers at real `TEAM_TURN`/touchdown boundaries and now gate every positional turn-end hook. Tests cover a normal end, scoring end, opponent-turn score, kickoff flip, compressed empty turn with positional shaping, and action-created turnover. |
| Distance potentials used `-1` as both inactive sentinel and a valid negative potential. | With `reward_dist_endzone=.20`, ordinary carrier distances produce values below `-1`; most of the pitch did not emit carry deltas. Once that defect was repaired, long same-team ball relocations exposed a second problem: `.05/.20` clipped real emissions. | Use `NaN` solely as inactive and treat every finite negative value as valid. Full-pitch fetch/carry tests verify one-square deltas. Manifest validation rejects a distance coefficient whose 25-square channel can itself exceed 1. R0/R2 now use `.02/.04` and passed their bounded 20M zero-clip smokes; zero clipping remains mandatory in every 250M/full arm. Historical distance curves and the unsafe repaired preflight are retired. |
| Human possession used `gameSetHomePlaying` toggles as turn ends. | Setup, kickoff mini-turns, defensive choices, and cleanup inflated the denominator by about threefold. | Open only `turnDataSetTurnStarted=true` in regular mode and close on `turnEnd`; exclude synthetic reports and preserve pre-cleanup possession at half end. Tests cover toggles, kickoff mini-turns, removed players, and half cleanup. |
| Launchers bake in divergent reward recipes and CLI is last-wins. | “One-knob” A/Bs could differ in several inherited terms; restarting with another launcher silently changed the control. Arbitrary trailing arguments could override the recorded warm start, seed, steps, optimizer, curriculum, or bot after the launcher had validated different values. | Complete JSON reward manifests plus a validator/CLI renderer require every reward key, compute a canonical SHA-256, enforce incompatible-family guards, and quarantine statmatch. Causal launch/eval scripts reject all trailing overrides, bind the vendored executable, pin the principal optimizer/rollout contract, refuse artifact overwrite, and write the effective command and source/config/module/artifact hashes to machine-readable manifests. |
| Torch evaluation relied on PyTorch's implicit `torch.load` default and accepted either native-flat or torch-looking `.bin` paths. | PyTorch 2.6+ changed the default to `weights_only=True`, rejecting trusted historical full-pickle checkpoints; a native flat checkpoint then failed later with an opaque unpickling error. Either failure could consume setup time before revealing an artifact-format mismatch. | A durable vendored patch uses explicit `weights_only=False` at policy construction and later warm load for trusted local artifacts. Eval launchers first load/validate a nonempty torch state dict, require the GPU fp32 build, and tell the operator to select/convert `*_torch.bin`; native reward launchers retain exact byte-size/precision checks for flat checkpoints. |
| BBP training did not require an edition allowlist. | `bc_v4` mixed BB2020 and BB2025 transitions despite the BB2025 deployment target. | Corpus audit writes an exact replay-ID allowlist from raw embedded `rulesVersion`; BC loaders accept it, fail on missing shards, validate filename/record IDs, and record allowlist hash/count. |
| An inactive-team direct catch in the catcher's endzone could score before normal Move re-entry, so completed-turn telemetry missed the active team's Pass/Hand-off turnover. | Turnover-rate and sequencing telemetry undercounted a current-FAQ turnover in a rare but strategically important scoring branch. | A successful inactive-team catch now latches the turnover before `bb_check_td()` only when the nearest Move parent is an unresolved Pass/Hand-off. A standalone-catch negative control remains turnover-free. The focused engine suite is 392/392 green; 25 reward and 2 bot tests, plus ASan/UBSan runs, are green. |
| Puffer printed only 30 environment metrics, Rich abbreviated long names, and `game_stats.py` read only the final dashboard interval. A first fix then treated every panel as independent, even though native `eval_log` is cumulative and Puffer unconditionally reprints its last dashboard. | Corrected possession and late telemetry were hidden; the original bridge used only 12 games; the intermediate analyzer double-counted the last torch interval and could inflate a native smoke from 22,859 unique games to 329,938 pseudo-samples. Arbitrary stdout also injected a fake `with=3` metric. | Durable Puffer patches print all Blood Bowl keys plus strict `PUFFER_ENV_JSON` with schema, backend, train/eval phase, interval/cumulative semantics, agent steps, and an explicit final-reprint bit. Analysis uses only machine payloads when present, excludes the marked reprint, sums torch intervals, retains only the final native cumulative eval snapshot, and reports final-policy eval separately from training. Synthetic tests pin all four semantics, including legitimately identical independent intervals. |
| Schema-1 machine telemetry inferred train/eval phase from the backend's epoch counter and merged new logs over sticky old `env/*` keys. | Both backends increment their epoch inside `train()`, so the final training interval was mislabeled as evaluation. An eval panel with no completed games could then inherit the prior training `n` and metrics and falsely satisfy an eval gate. Torch bot probes also included that one boundary interval until corrected. | Schema 2 passes phase and loop epoch explicitly from `_train`, clears all prior `env/*` keys before merging each fresh panel, and remembers the true last phase for the final reprint. The analyzer repairs exactly the one known schema-1 boundary transition in complete historical logs. Tests cover schema-1 recovery, native cumulative eval, torch intervals, and a train-only run with no eval sample. |
| Puffer's final-policy game gate compared `eval_episodes` to one `env/n` panel and capped evaluation at half the training epochs. | Native eval happened to work because its counter is cumulative. Torch resets `n` every interval, so a requested 1,000-game scripted evaluation could terminate at its epoch cap with only 1–31 analyzed games and still exit successfully; making the frozen training prefix shorter made the defect worse. | The loop now accumulates Torch eval intervals explicitly while retaining native cumulative semantics, gives short frozen runs a finite target-scaled eval budget, and publishes `_puffer_eval_episodes_completed` in schema-2 telemetry. The scripted evaluator requires one final eval reprint, a cumulative and analyzed sample at or above its explicit floor, zero integrity counters, and hashes both Puffer and the launcher. Rejected live cells were quarantined; a repaired smoke reached its exact gate before the 1,000-game matrix began. |
| Provenance code selected the first globbed `_C*.so`. | The RTX audit tree also contained an ignored macOS extension artifact; filesystem enumeration could hash that stale file rather than the Linux module actually imported by Puffer. | Launch/eval/install checks now resolve `_C.__file__` through the vendored interpreter, while the frozen screen plan selects the exact current-Python extension suffix. The live module is fp32 Linux SHA-256 `5fb1b1df2ca1d13d1af88adf663e4ef3a6690228f820afb2f4132b87db277de4`. |
| Per-arm manifests were strong, but the multi-arm screen originally trusted any existing result filename and had no immutable screen-level plan, exact PID monitor, durable completion proof, or completed-invalid outcome. | A corrupt/empty result could be skipped; code, warm bytes, pool, optimizer settings, or module could drift between arms; a status-publication race could fail a clean run; and a clipped or undersampled completed arm became an ambiguous partial artifact. | The screen now freezes and revalidates one content-addressed plan, explicitly assigns every causal launcher input, binds every run manifest to the plan hash, monitors the exact detached wrapper PID, recovers a clean completed arm after orchestrator loss, validates train and eval telemetry, exact final step/checkpoint size, and minimum eval games, writes structured invalid outcomes before stopping, and creates an atomic completion JSON over all eight result hashes. Live plan/restart/failure smokes passed on the RTX host. |

Two cautions and one telemetry naming rule remain explicit:

1. `turnovers_completed` means a failed-action turnover latch. It intentionally
   does not count every touchdown as a rulebook “turnover,” so do not compare it
   to a replay field with broader semantics without renaming/reconciling both.
2. A single engine advance can compress an empty opponent turn. The monotonic
   completed-turn gate correctly evaluates the acting team's settled board,
   but it cannot reconstruct a distinct intermediate board for the auto-empty
   team. That team made no policy decision and receives no separate positional
   shaping event.
3. `reward_episode_abs_max_mean` is explicitly the mean of episode maxima, not
   the run-wide maximum. `reward_clip_frac`,
   `reward_clip_frac_nonzero`, and `reward_nonfinite_frac` are formed after
   vector aggregation from raw emission counters, so their common episode
   divisor cancels and the ratios are emission-weighted. The any-clip episode
   indicator remains the fail-safe for rare saturation.

The fixes have been installed and rebuilt as native fp32 in the isolated
`/home/rache/bloodbowl-rl-audit` checkout, where source/config/build drift checks
and bounded smokes run without invoking or modifying the separate production
checkout/services. At the final screen preflight the three production services
were externally inactive; this audit did not stop or restart them. Production
adoption still requires review, commit, the normal deployment chain, and the
full causal matrix; an audit-checkout result is not a default-recipe change.

### Corrected BB2025 human possession baseline

The completed full-corpus rerun over **11,580 exact-BB2025 games** found:

| Statistic | Corrected value |
|---|---:|
| Genuine team turns | 365,449 |
| Team turns ending held, including own-turn TD endings | 173,200 |
| Turn-weighted possession rate | **0.4739375398482415** |
| Mean per-game possession rate | **0.4745251419141351** |
| Population SD of per-game rate | **0.06958465587874106** |
| Synthetic `turnEnd` reports excluded | 47,599 |
| Malformed replays | 0 |

The old `0.378` value is **retired**. It used an invalid boundary proxy and must
not be used by statmatch, dashboards, or reward tuning. It may remain visibly
labelled as a legacy artifact for historical reproduction. The turn-weighted
value is the direct reference for an aggregate completed-turn metric; the
per-game mean/SD are the appropriate distributional references when each game
receives equal weight.

### Why the old statmatch vector cannot be repaired with one new number

The same exact-BB2025 rebuild exposed a broader semantic mismatch. The table
below uses initial non-rerolled FUMBBL test reports and one record per resolved
block, which is closer to engine decision telemetry than the legacy all-roll
report census:

| Dimension | Exact mean/game | Empirical population SD | Legacy statmatch mean / SD |
|---|---:|---:|---:|
| Touchdowns | 2.20535 | 1.07072 | 2.217 / 1.4890 |
| Dodge tests reached | 22.0512 | 13.2649 | 25.68 / 5.0675 |
| Pickup tests reached | 6.10699 | 2.48294 | 7.29 / 2.7000 |
| Pass tests reached | 1.99344 | 2.27610 | 1.97 / 1.4036 |
| GFI/Rush tests reached | 15.4619 | 7.26099 | 17.38 / 4.1689 |
| Resolved blocks | 80.2394 | 18.4838 | not represented directly |
| Per-game red-block fraction | 0.0181565 | 0.0238111 | 0.0169 / 0.0500 floor |
| Corrected possession | 0.474525 | 0.0695847 | 0.378 / 0.08120 synthetic |
| Hand-offs | 1.18705 | 1.25190 | omitted |
| Fouls | 2.67461 | 2.66494 | omitted |

These are still tests that actually began, not a complete reconstruction of
every intended action. The engine counts several intentions before dice, so a
future like-for-like baseline needs a versioned per-game feature table and one
explicit semantic contract. Natural covariance is also substantial: dodge
tests versus resolved blocks `r=-0.410`, pickup attempts versus successes
`r=0.854`, touchdowns versus pickup successes `r=0.307`, pass tests versus
pickup successes `r=0.323`, and blocks versus fouls `r=-0.214`. A global
diagonal Z-distance therefore misprices variation and penalizes legitimate
roster styles even after its means are corrected.

### Quarantined or unresolved

- **Statmatch remains off.** Its old target vector mixed edition-contaminated
  data, obsolete possession semantics, report-vs-decision counts, and stale
  standard deviations/covariances. It should not be re-enabled merely by
  replacing one possession number.
- **Installed Puffer snapshots can be stale.** The build compiles the installed
  copy, not arbitrary working-tree edits. `tools/install_puffer_env.sh --check`
  and a rebuild are non-negotiable before every scientific run.
- **Native PPO numerical history remains relevant.** Earlier bf16 native runs
  exposed log-prob parity and `exp(logratio)` overflow issues; the RTX 2070's
  correct native mode is fp32 (`precision_bytes=4`). Every run must verify the
  backend actually executing and record non-finite telemetry.

## Exact replay and behavior-corpus audit

### Inventory

| Artifact | Exact inventory | Important qualifier |
|---|---:|---|
| Canonical raw Competitive/non-concession manifest | 15,347 games | 11,580 BB2025; 3,767 BB2020 by embedded raw `rulesVersion`. Dates overlap. |
| Local curated raw cache | 400 BB2025 games | Useful for local inspection, not the full training corpus. |
| Canonical `pairs_v4` | 12,304 shards; 2,085,330 records | 9,170 joined BB2025 shards / 1,622,231 records / 52 zero-record shards; 3,133 joined BB2020 shards / 462,825 records / 20 zero-record shards; plus one 274-record pair shard (`1559380`) absent from the manifest. Obs 2782, mask 454. |
| Strict nonempty BB2025 training allowlist | 9,118 replay IDs; 1,622,231 records | Allowlist SHA-256 `15d6f67852c6d556009a8f878f730c6fd6c0c45fdf77e1fd8a2b7d1b2c218585`; excludes all 52 zero-record BB2025 shards. |
| Current BBS state bank | 15,471 records from 5,370 replay IDs | 15,348 records / 5,328 IDs are BB2025; 123 records / 42 IDs are BB2020. |
| BBS binary contract | `BBS1` v1, `match_size=2240`, fingerprint `0x64897cde` | Confirms current struct/table compatibility, not source-edition purity. |

The BBS old-edition contamination is only `123 / 15,471 = 0.795%`, but it is
cheap to remove and should be removed for a strict BB2025 experiment. The
states were generated by the current engine while lockstep-applying recorded
actions; they are not raw FUMBBL memory copies. Loader structural checks do not
make an old source game's policy semantics BB2025.

### Structural limitations

1. **All BBP and BBS records are in half one.** Lockstep stops at the first
   divergence. No current action-pair or state-bank experiment evaluates
   second-half decision making.
   A bounded-memory streaming audit of the strict 9,118-ID BB2025 training
   set confirmed all 1,622,231 records are in half one. Pair counts by encoded
   turn `0..8` are
   `278,814 / 712,722 / 353,859 / 153,477 / 71,117 / 30,670 / 14,057 /
   6,158 / 1,357`. Turn 0 includes pre-team-turn decision contexts and must not
   be folded into turn 1. The audit-report SHA-256 is
   `f32e0032b568d80cf53ec87404e696ec72e5ca927c80ea94320ab93612eb70ba`.
2. **The state bank is opening-biased.** Counts by team-turn number are:

   | Turn | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
   |---:|---:|---:|---:|---:|---:|---:|---:|---:|
   | BBS records | 8,093 | 4,011 | 1,808 | 862 | 397 | 187 | 88 | 25 |

   Turns 1–2 are about 78% of the bank. Only 300 records reach turns 5–8,
   with no half-two context. This is not an adequate Stalling, late-score,
   reroll-budget, or desperation corpus.
3. **The raw, normalized, pair, and state snapshots drift in coverage.** The
   canonical raw manifest has 15,347 games, while pairs exist for 12,304
   shards and BBS states for 5,370 IDs. Every analysis must declare the joined
   denominator rather than call all three “the corpus.”
4. **BBP/BBS headers do not carry rules version, race, coach, outcome, TV, or
   format.** Those fields require a replay-ID join to the raw manifest/meta.
5. **Dates cannot select edition.** BB2020 and BB2025 games overlap in time.
   The nested raw `game.gameOptions.gameOptionArray` `rulesVersion` is the
   authoritative label.
6. **The repaired BC split is replay-disjoint but not yet stratified.** Exact
   edition filtering is now mandatory when an allowlist is supplied, and the
   default sampler weights replays equally rather than overweighting long
   lockstep survivors. The split still is not stratified by coach, team,
   matchup, chronology, outcome, or divergence depth; replay-equal sampling
   also strengthens the opening bias documented below.
7. **Coach/side bias exists.** Team 1 coach rating is systematically higher in
   the archived manifest, and race/action coverage is censored by which games
   and mechanics survive lockstep.
8. **Recorded outcomes are not decision quality.** A lucky casualty, pickup,
   pass, or GFI can train an outcome model; it must not label the pre-dice
   action intrinsically good.
9. **Exact action accuracy has a multimodality ceiling.** Equivalent safe-move
   orderings, destinations, and tactical lines create valid alternative labels.

### Prefix depth and action-label coverage

The strict nonempty 9,118-shard BB2025 audit shows how quickly demonstrations
disappear after the opening. Replay coverage reaching encoded turns `0..8` is:

```text
9,118 / 8,586 / 3,805 / 1,697 / 796 / 371 / 166 / 87 / 35
```

Only 35 replay prefixes reach turn 8. A further 288 nonempty shards contain
setup/kickoff labels but no gameplay action. The record-weighted turn shares
are about `17.19% / 43.94% / 21.81% / 9.46% / 4.38% / 1.89% / 0.87% /
0.38% / 0.084%` for turns `0..8`; replay-equal weighting makes the opening
bias stronger because long-surviving shards no longer dominate.

The label distribution is similarly narrow:

| Action label | Records | Share of BB2025 labels | Replay coverage |
|---|---:|---:|---:|
| STEP | 468,665 | 28.890% | 8,133 |
| SETUP_PLACE | 208,624 | 12.860% | 9,118 |
| ACTIVATE | 195,058 | 12.024% | 8,830 |
| DECLARE | 194,263 | 11.975% | 8,660 |
| END_ACTIVATION | 179,303 | 11.053% | 8,276 |
| PASS_TARGET | 313 | 0.0193% | 296 |
| HANDOFF_TARGET | 356 | 0.0219% | 339 |
| FOUL_TARGET | 371 | 0.0229% | 364 |

Pass, Hand-off, and Foul targets together are only `1,040 / 1,622,231 =
0.0641%` of labels. There are zero Jump, Throw Team-mate target, or Special
target labels. Secure the Ball is encoded under `DECLARE` argument 7 rather
than the standalone action-type label, so that apparent zero is a schema
detail; the other zeros are real coverage/mapper gaps. Declaration-to-target
retention is also diagnostic: Pass `313/564 = 55.5%`, Hand-off `356/413 =
86.2%`, Foul `371/395 = 93.9%`, Throw Team-mate `0/61`, and Special actions
`0/74`. Sampling cannot recover targets the mapper never emits.

Mask cardinality mixes qualitatively different tasks. The BB2025 record-level
mean is `36.534` legal entries across all three heads, but Setup Place averages
about `195`, routine Activate about `9.93`, Declare `6.20`, Step `12.64`, and
Pass Target about `317`. A single unweighted three-head cross-entropy and one
aggregate exact-accuracy number hide these differences. Report loss/accuracy
by action, phase, turn, and roster, and cap setup exposure.

### Selection bias and trainability limits

Pair survival is not neutral across rosters. The ratio of BB2025 BC record
share to raw team-side share is approximately:

- severely low: Vampire `0.265`, Goblin `0.360`, Snotling `0.374`, Black Orc
  `0.526`, Gnome `0.718`, Ogre `0.769`;
- high: Necromantic Horror `1.396`, Chaos Chosen `1.278`, Elven Union `1.276`,
  Shambling Undead `1.221`, Khorne `1.221`, Dwarf `1.207`, Orc `1.193`.

Winning sides contribute about `90.52` labels per appearance versus `84.59`
for losing sides, and higher-coach-rating sides contribute slightly more than
lower-rated sides. The raw archive is Competitive-division, non-concession,
strong-coach-heavy league play. Uniform record sampling consequently biases
toward long lockstep prefixes, winning/stronger sides, and mechanics/rosters
the mapper handles well. A replay-first sampler should choose replay, then
roster/matchup, turn/depth bucket, and action; importance weights are needed if
the goal is to estimate the natural archived distribution.

The historical BC loader was too memory-hungry for the owned rig at full
scale. Exact BB2025 pairs occupy about `5.276 GB`; retaining every shard body
and then concatenating it created roughly `10.55 GB` of CPU bytes before
tensors. CUDA observations, masks, and targets required about `5.29 GB`. The
RTX 2070 WSL instance has about 11 GiB system RAM and 8 GiB VRAM, so that path
could not honestly train the full corpus.

`training/bc_pretrain.py` now uses a metadata-only `ShardIndex`, validates
headers and embedded replay IDs in bounded chunks, keeps record bodies on
read-only memmaps behind an evict-before-open LRU, copies only one owning batch
to the selected accelerator, and evaluates train/validation shards batchwise.
It splits nonempty replay IDs before sampling and defaults to replay-first
sampling (uniform replay, then uniform record); `--sampling record-weighted`
retains the old objective explicitly. `--open-shard-cache` and
`--eval-batch-size` bound open mappings and evaluation memory. The legacy
in-memory API remains for small callers but now makes one final allocation
instead of holding full shard bodies and a concatenated duplicate.

Nine focused regression tests cover exact allowlists/missing shards, mixed
lineages, malformed/truncated records, embedded-ID mismatches, deterministic
replay-disjoint splitting, both sampling distributions, owning copies, the
strict memmap-cache bound, and maximum evaluation batch size. An obs-v4
end-to-end smoke produced a trainer-loadable checkpoint and exact Puffer
round-trip. The final full-corpus probe regenerated the 9,118-ID allowlist from
raw embedded edition metadata, indexed all 1,622,231 exact-BB2025 records,
made a replay-disjoint 7,294/1,824 replay split, and sampled an owning
4,096-record replay-first batch in 12.88 seconds. The configured and observed
memmap-cache peaks were both eight; macOS reported 227,360,768 bytes maximum
RSS and 178,586,560 bytes peak memory footprint for the Python/Torch process.
The durable corpus audit and allowlist are under
`runs/replay-audit-20260713/`; their SHA-256 values are respectively
`28ad9e5917fe81f63aab4507b1703653db49d1af8ff58a4736f8e564576d5227`
and `15d6f67852c6d556009a8f878f730c6fd6c0c45fdf77e1fd8a2b7d1b2c218585`.
This fixes the capacity blocker; it does not fix opening censorship, missing
action targets, roster imbalance, or the lack of recurrent sequences.

Finally, the current pretrainer draws IID records and zeros recurrent state for
every example. `bc_context` adds derived context features but is not sequence
training. A true sequence arm must group and order by `(replay_id, agent,
command)`, carry state across the intended window, and reset it at declared
boundaries. Given the demonstrated data/representation ceiling, test that arm
against the same grouped holdouts rather than assuming recurrence will help.

### Appropriate uses now

After exact edition filtering and replay-level splitting, current data is
suitable for:

- value/outcome-model training on the states it actually covers;
- contextual behavior priors and auxiliary prediction;
- opening, pickup, loose-ball, ordering, block/assist, and some carrier-safety
  scenarios;
- per-roster and matchup diagnostic baselines;
- replay-derived starting positions, with new dice, for tactical curricula;
- chosen-vs-legal counterfactual features reconstructed by the current engine.

It is not yet suitable as the sole source for:

- second-half strategy;
- score-and-clock Stalling policy;
- late reroll budgeting or desperation plays;
- full-drive imitation;
- a league-persistent utility;
- a global “human-like” reward vector.

For missing late contexts, use explicit engine fixtures spanning half, turn,
score, possession, rerolls, material, and Stalling risk, or improve lockstep to
reach full games. Do not repeatedly oversample the 25 turn-8 records and call
the result replay-grounded.

## Recommended reward hierarchy

### Layer 0: exact simulator semantics

Rules consequences belong in the engine: turnovers, Stalling crowd action,
ball scatter, removals, reroll restrictions, Secure the Ball, and score. Do not
duplicate a correct rules penalty as a shaping term merely to make it visible.

### Layer 1: explicit deployment utility

Choose one deployment utility and document it.

For neutral match play, the clean target is:

```text
win  = +1
draw =  0
loss = -1
```

with no separate permanent touchdown-margin reward. The current `.4 TD + .6
win` utility is a useful dense control, but it values score margin and drive
frequency in addition to winning. A negative draw value intentionally favors a
risky decisive result over a draw and is not a neutral zero-sum match utility.

League or tournament utilities should be separate named configurations, not
implicit coefficient changes in the same model lineage.

### Layer 2: exact potential-based shaping, if necessary

For discount `gamma`, policy-invariant shaping must be:

```text
F(s, a, s') = beta * (gamma * Phi(s') - Phi(s))
```

with consistent Markov boundaries and correct terminal handling. The current
raw `Phi(s') - Phi(s)` distance deltas are not theorem-safe at `gamma=.995`.
The possession annuity is not PBRS.

A useful learned `Phi` can include score, both teams' turns remaining,
receiving order, possession/loose-ball control, ball position, on-pitch
material and skills, rerolls, and weather. Split by whole match, coach, and
time; validate calibration and antisymmetry. Normalize `beta` so the 99th
percentile absolute shaping emission is at most about `0.05`, then prove reward
clipping is zero.

### Layer 3: opponent curriculum and replay scenarios

Before adding a defensive scalar, make the policy defend against an opponent
that can score. Use replay states to make pickup, ordering, carrier-security,
and loose-ball decisions frequent. These change the experience distribution
without redefining a successful action.

### Layer 4: auxiliary heads and observations

Prefer predicting useful quantities over paying them:

- block outcome and turnover probability;
- opponent best-sack probability;
- loose-ball control probability;
- next-turn TD threat;
- assist changes;
- contextual reroll value;
- terminal match value.

Auxiliary prediction can improve representation without making the proxy part
of the game score.

### Layer 5: temporary decision-time scaffolds

If a tactical skill still does not emerge, use one small, bounded,
decision-time term. Require:

- one causal variable per arm;
- a matching reward-off control;
- target-value and context telemetry;
- held-out terminal non-inferiority;
- annealing to zero;
- persistence of the skill after removal.

Outcome-priced injury, ball-loss, send-off, success-rate, and statmatch rewards
do not meet this standard.

## Complete reward manifests for the next experiment

The audit worktree contains proposed complete manifests under
`puffer/config/rewards/`. They must be treated as proposed until landed and
hashed by `tools/reward_manifest.py`.

### Common settings

All first-factorial arms use:

```text
reward_td                 0.40
reward_win                0.60
reward_draw               0
reward_k_kd               0.10
reward_k_value            0.50
reward_k_ball             0.15
reward_k_turnover         0.15
reward_k_seq              0.03
reward_rush_cost          0.015
```

All of the following are explicitly zero:

```text
setup_done, setup_autofix, ball_loss,
injury_inflicted, injury_taken, injury_value_scaled,
send_off, kickoff_touchback, surf_taken, surf_inflicted,
k_self_injury, k_assist,
carrier_exposure, carrier_exposure_soft, carrier_threat,
defensive_threat, defensive_threat_soft,
statmatch_scale
```

### Initial 2×2

| Manifest | Possession | Ball gain | Distance to ball | Distance to endzone | Purpose |
|---|---:|---:|---:|---:|---|
| R0 full, re-baselined | .03 | .05 | .02 | .04 | Corrected-code control; D169 economy with clamp-safe documented distance scale. |
| R1 no distance | .03 | .05 | 0 | 0 | Tests dependence on the previously broken distance scaffold. |
| R2 no possession | 0 | 0 | .02 | .04 | Removes annuity and outcome-priced gain; retains clamp-bounded navigation scaffold. |
| R3 minimal block | 0 | 0 | 0 | 0 | Terminal TD/win utility plus settled block/risk scaffold only. |

This is a true `{possession/gain on, off} × {distance on, off}` factorial.
Rush and block terms remain fixed. The JSON files are:

- `puffer/config/rewards/r0_full.json` — `14b718f28b2c925ea3279444dfbc679631c0cceea0f84d9e3547e3318ce6e90e`
- `puffer/config/rewards/r1_no_distance.json` — `13f8522fa08def678111a4a0592bf37d91fe65455fe8d971a69a23526ddb6c93`
- `puffer/config/rewards/r2_no_possession.json` — `5e31a13e5885c71c89af90f2ab504bbf7fcb94230ea33c834ba2d45fc9b930ae`
- `puffer/config/rewards/r3_minimal_block.json` — `0a486e01c326e51f14d873c85b8fc9f364dc00baabc6714a3f16159703ce08de`

These are canonical manifest hashes returned by `tools/reward_manifest.py`,
not raw-file hashes. Recompute and record them at launch; any metadata or
coefficient edit intentionally changes the identity.

`tools/run_reward_ablation.sh` is the corresponding fail-closed launcher. It
requires a complete manifest, warm checkpoint, and exactly four hash-verified
pool banks; requires the fixed pool identity
`18ec7cac858b71a6657003f454f19e232fb060f08b644c1e9e2f101076a9aac0`
and raw `league_seeds.json` hash
`ad2e7b1997d546ee35ad7719eff8e12db033dedfa2a975a7b41e2628dc9669f6`;
refuses every trailing override and existing output artifact; pins rewards,
seeds, warm start, pool routing, architecture, rollout quantum, curriculum,
checkpoint cadence, and principal optimizer fields; binds the exact vendored
Puffer entrypoint; verifies installed source/config/build drift; supports the
Turing fp32 native build; and has a `DRY_RUN=1` preflight. Each live run writes
an atomic run manifest, process-status sidecar, exact checkpoint-directory
pointer, and checkpoint-local copy of the effective command/hashes. A bad bank
load terminates the whole process group; a clean short run is accepted only if
its exact quantized final checkpoint exists. Do not launch these arms through a
historical partial-reward script.

### Second-stage candidates

| Name | Change from promoted first-stage manifest | Question |
|---|---|---|
| R3a minimal, no rush | `reward_rush_cost=0` | Does the own-dice tax still improve strength, or merely suppress useful risk? |
| R4 objective-only | Every shaping term zero; retain `.4 TD + .6 win` | Have the learned skills become self-sustaining? |
| R5 win-only plus selected scaffold | `TD=0`, `win=1`, `draw=0` | Does neutral match utility preserve strength and improve tempo decisions? |
| R6 win-only sparse | `TD=0`, `win=1`, `draw=0`, every shaping term zero | Long-term clean target. |

`win=1` is safe only if no shaping co-fires on the terminal step. Runtime clip
telemetry must prove this. Otherwise exclude/cancel terminal shaping or scale
the terminal magnitude; never rely on trainer clipping.

Do not initially rerun injury, send-off, surf, statmatch, carrier-threat, or
assist-potential arms. They already have negative evidence or unacceptable
Goodhart risk. Conditional fallback only:

- carrier exposure `.02/.01` versus zero, if held-out carrier-safety scenarios
  show a persistent functional defect;
- defensive threat `.01/.005` versus zero, only if diverse competent opponents
  fail to improve held-out defense.

Never stack those fallbacks. Any winner must survive annealing the term to zero.

## Opponent pools and replay-derived scenarios

### Static native pool for reward A/Bs

Use a frozen four-bank pool:

1. `runs/league9/league9_cap.bin`
2. `runs/caps/violence_cap.bin`
3. `runs/caps/netblock_cap.bin`
4. `runs/caps/turnover3_cap.bin`

The locally audited SHA-256 values are, in that order:

```text
359d14caa08f12362f799c4cab4f33301fc9ce2ba3dec85922abe9622670d5f5
cd35ec958e3d7bdaa418856dd3fe0dea49c944252ebbaf96604f71bc1f28c90c
9964cf4d4c9c2654157e898ff17327732e73c4c85a5883e7d311d8d3baade05e
fdcb2f0ebfbc88a29c026d51140ab008bd5dde5995ea5b3233fd0bd210110935
```

Use four banks at `frozen_bank_pct=.06`. Because the percentage is per bank,
the historical-game share is approximately `2 × 4 × .06 = 48%` (subject to
integer rounding); `.08` would be about 64%, not 47%. On the 8 GB RTX 2070,
override the default to `2048 agents / 2 buffers` unless a measured memory
preflight proves 4096 safe. Set `swap_winrate=1.1`, timeout beyond ten times the
arm budget, and a practically unreachable snapshot-rotation interval. Hash the
pool manifest and use it unchanged across R0–R6.

Do not add the current `bc_v4` to the training pool until an exact-BB2025 model
is rebuilt. Its source pairs mixed editions. It can remain a legacy diagnostic.

### Scripted-opponent study

Scripted-opponent learning currently requires torch `--slowly`; native and
torch runs are not causal comparators. Use the same converted warm checkpoint
and torch backend for every arm:

- O0: fixed frozen `turnover3_torch` enemy;
- O1: current cage-offense bot only, balanced across team 0/team 1;
- O2: four equal tranches — cage offense team 1, contact bot team 0, cage
  offense team 0, contact bot team 1. Reverse order in replicate two.

The repository currently has one competent cage script and one contact script.
Before calling defense general, add or hold out a fast/wide offense and a
loose-cage/switch offense, or demonstrate transfer to frozen learned attackers
and replay scenarios.

### Forced matchup grid

Use both orientations for each representative pair:

| Matchup | Team IDs | Purpose |
|---|---|---|
| Orc ↔ Dwarf | 22 ↔ 7 | Bash/bash. |
| Orc ↔ Wood Elf | 22 ↔ 29 | Bash/agility. |
| Skaven ↔ Dark Elf | 24 ↔ 6 | Speed/agility. |
| Human ↔ Necromantic Horror | 13 ↔ 17 | Hybrid. |
| Goblin ↔ Orc | 10 ↔ 22 | Stunty/strength mismatch. |
| Tomb Kings ↔ Wood Elf | 26 ↔ 29 | Extreme slow/fast. |

Macro-average the cells equally. Do not let common rosters dominate the result.

### Scenario buckets

Split by replay ID `70/15/15` train/dev/test, stratified by exact edition, race
pair, coach bracket, TV, outcome, and maximum lockstep turn. Cap each replay's
state contribution and sample buckets uniformly rather than records uniformly.

| Bucket | Predicate | Primary judgment |
|---|---|---|
| S1 ball recovery | Loose ball; active team can reach; subdivide legal Secure, AG, Sure Hands, weather, opponent distance | Secure vs ordinary vs control/leave; possession without suicidal pickup. |
| S2 loose contest | Both teams can contest/reach; especially opponent within two | Next-turn control and failure coverage, not immediate ownership alone. |
| S3 ordering | At least four unused players, at least two zero-roll activations, and a legal risky block/dodge/pickup | Chosen turnover probability × value of opportunities stranded. |
| S4 carrier safety | Own carrier with opponent full/soft sack access | Best sack probability/exposure paired with ball advancement and score. |
| S5 defense red zone | Opponent carrier, defender to act, one/two movement horizons from endzone | TD conceded, deep safety, zero-TZ path, minimum dodges, marking in context. |
| S6 block/assist | Legal alternatives span red/1D/2D, or a zero-roll move changes assists | Target-value block quality and assist credit, not raw block count. |
| S7 reroll | Pending TEST/block reroll and at least one team reroll | Contextual reroll regret by half-turn, score, and failure consequence. |
| S8 score/Stall | Carrier can score without dice, crossed with score and exact Third Season crowd risk | Score now vs wait under match value and the real rule. |

S1–S4 and S6 are feasible from the current early-game bank after strict
edition filtering. S5 and S7 are thin. S8 and second-half tempo require
engine-generated fixtures or deeper lockstep.

### Curriculum A/B

- C0: kickoff only, `demo_reset_pct=0`;
- C1: raw strict-BB2025 state bank at `0.5`;
- C2: equal-weight S1–S6 tactical mixture at `0.5`, with kickoff for the other
  half.

C1 versus C2 isolates balanced tactical sampling from merely seeing midgame
states. Any promoted curriculum anneals replay starts to zero in the final
quarter and is evaluated kickoff-only.

## Staged RTX 2070 experiment matrix

The measured 2070 throughputs are approximately:

| Mode | Measured SPS |
|---|---:|
| Native fp32, ordinary full game | 190K |
| Torch `--slowly` | 115K |
| Rejection-filtered/demo-heavy | 58–64K |

Approximate ideal wall times, before evaluation and pool overhead:

| Steps | Native 190K | Torch 115K | Filtered 58–64K |
|---:|---:|---:|---:|
| 250M | 0.37 h | 0.60 h | 1.1–1.2 h |
| 500M | 0.73 h | 1.21 h | 2.2–2.4 h |
| 1B | 1.46 h | 2.42 h | 4.3–4.8 h |
| 4B | 5.85 h | 9.66 h | 17–19 h |

Use step budgets, not wall time, for comparisons.

### Stage 0 — integrity and frozen baseline

1. Land audit fixes and tests.
2. Generate and hash strict BB2025 replay IDs and state bank.
3. Install/rebuild on the rig; verify `precision_bytes=4` for native fp32.
4. Re-evaluate `turnover3` and `defense2`:
   - 2,048 games per development opponent;
   - 512 games per forced-team orientation;
   - 4,096 games for a final claim;
   - current cage bot as team 0 and team 1;
   - common evaluation seeds.
5. Run an 8M-step kickoff-only dashboard evaluation for each cap.

Torch-checkpoint hashes for that bridge evaluation are
`turnover3_torch.bin` =
`75c736c8b2703a33e31277b8cb8d1f4eac67588364a51a4bf21a14647a0af747`
and `defense2_cap.bin` =
`abf7423aa9334091b0700c9dc6c0197f0d4ec765b1076df3b65aba243df181b7`.
The native flat turnover3 warm/pool checkpoint is a distinct artifact with
hash `fdcb2f0ebfbc88a29c026d51140ab008bd5dde5995ea5b3233fd0bd210110935`;
the eval preflight now prevents those two formats from being interchanged.

The corrected mirror bridge completed on the isolated RTX audit checkout. The
old logs predate explicit phase/reprint metadata, so their one source-confirmed
unconditional final panel was removed exactly once; this changes the previously
reported sample sizes from 7,367/4,060 to **7,353/4,051**. Do not generalize
value-equality de-duplication to new logs; the explicit reprint bit now owns
that decision.

| Kickoff mirror metric | turnover3 | defense2 |
|---|---:|---:|
| Completed games | 7,353 | 4,051 |
| TDs/game | 1.21095 | 0.52752 |
| Draw rate | 0.45766 | 0.65515 |
| Decisions/game (`episode_length`) | 624.65 | 1,101.01 |
| Genuine-turn possession share | 0.29675 | 0.33664 |
| Resolved blocks/game | 11.621 | 22.173 |
| 2D attacker-choice fraction | 0.66713 | 0.69017 |
| 2D defender-choice fraction | 0.02444 | 0.02104 |
| Ball forward displacement | 6.245 | 4.270 |
| Sampled-action repair fraction | 0.22801 | 0.28347 |

Both runs had zero reward-clip, non-finite, engine-error, demo, and fallback
episodes. Their log SHA-256 values are respectively
`3e233d234c6bdbde98b41a0252ed8a5ea77bf402e8522401bab42e302b05be91`
and `7c9e0790e235ccc67cf931a6fae70c311ecf651d389e9a858d218045a6078c6f`.
These are behavioral mirror baselines, not strength measurements: defense2's
lower scoring comes with nearly twice the game length and block volume. It
still requires scripted/held-out opponents in both team orientations.

All four **safe reward smokes** then completed at an effective `19,922,944`
native steps from the same turnover3 warm checkpoint and static pool. Every
training phase and final-policy eval snapshot had zero clipped, non-finite,
engine-error, demo, or fallback episodes. The four frozen banks occupied the
intended `47.65625%` (approximately 48%) of historical games. Final-policy
snapshots were:

| Arm | Eval games | TD/game | Possession | Blocks/game | 2D | 2D-red | Sampled-action repair |
|---|---:|---:|---:|---:|---:|---:|---:|
| R0 safe full | 7,225 | 1.38962 | .31076 | 15.1507 | .64778 | .03896 | .22186 |
| R1 no distance | 6,599 | 1.00333 | .29374 | 17.4158 | .65090 | .03742 | .24850 |
| R2 no possession/gain | 6,806 | 1.30929 | .31325 | 16.2129 | .64620 | .03961 | .22637 |
| R3 minimal block | 6,327 | .96428 | .30152 | 17.2409 | .66135 | .03622 | .25793 |

These smokes used schema-1 machine telemetry. The compatibility repair moves
their one mislabeled boundary panel back into the training phase; it does not
change this table because native evaluation is cumulative and the final
evaluation snapshot remains authoritative.

These are one-seed 20M scale/integrity probes, not arm rankings. The apparent
distance-family scoring advantage is entangled with episode length and policy
adaptation and must survive paired 250M seeds plus held-out strength tests.
Artifact SHA-256 values are:

```text
arm  log                                                               run manifest                                                        final checkpoint
R0   a0f0af02ac44e3eeca865be43844b47c4d7c6a197b660b0090f81e05da25cd1a  899d2f1dd6b40ffb0094917db6dc7c889673dccb72a0aabf6beb1cf3ecab6586  4198aafa94912db2aa02f3d477f9752a85c2b4642d6b1b0b88a160517186bb09
R1   08fa52ad1bc2295dacdda23b8e1ee4cca2d09c0194f6cac94e32d1aee43e5271  8202ffb2ae7062c573cb84a01457fd013e293d000dff65e7ea9d7d749f2b929a  fbfc1901fe140bf68a8084f401112c172c6e5844c675ea9224b615a6e5d9ef49
R2   92c8843a9d4311aa7290e4baee1f7a7c20eb8df0ff45c52e0c95bc29489e665f  3de70f18cae6d067b767cd94fd435e16f72c1d0f38328b81fb86dcc88cad7d6f  c1327dddafb69b8cc14169d5c92bd9de2a4dbb36f00db1f0580c2a0c6036c688
R3   f31c609712cde49a27910bb57a18cac2bd7c05ad2848449c8ea31df9cde9356e  a6c1d3f829e75856806c810b09d5cb170dc9b44178b86e1418d1a25145dba562  4ad0b13ebfd9987082a40e312d2375b3fb3efc6e61ed2846f2c0af33742edfb2
```

The common-seed, common-configuration **matched cage/offense-bot probes** are
also complete. Each checkpoint was forced through both team orientations for
3M requested torch steps. The schema-1 compatibility repair removes the one
final training interval that the old backend-epoch heuristic mislabeled as
evaluation; the corrected counts below therefore supersede the initial
676/664/553/564 readout.

| Checkpoint | Cage bot position | Games | Champion match score | Draw | Bot TD/game | Champion TD/game | Champion blocks | Bot blocks |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| turnover3 | HOME / team 0 | 666 | .39339 | .63964 | .37387 | .10210 | 5.826 | 13.706 |
| turnover3 | AWAY / team 1 | 663 | .50000 | .47813 | .41478 | .37707 | 6.658 | 14.048 |
| defense2 | HOME / team 0 | 548 | .44982 | .75365 | .22445 | .09854 | 8.867 | 13.697 |
| defense2 | AWAY / team 1 | 559 | .51878 | .62612 | .24687 | .26655 | 10.136 | 15.689 |

Equal-weighting the two orientations, defense2 raises champion match score
from **.44670 to .48430** and reduces the same cage bot's TD rate from
**.39433 to .23566** (a **40.2%** reduction). That defensive gain comes with a
champion TD-rate drop from **.23959 to .18254** (23.8%) and very high draw
rates. More specifically, the macro win/draw/loss rates shift from
`.16725/.55889/.27386` to `.13936/.68988/.17076`: the match-score improvement
is loss-to-draw conversion, while win rate falls 2.79 percentage points.
Decisions/game rise from `1,140.0` to `1,360.2`, champion block volume from
`6.24` to `9.50`, and sampled-action repair from `.07766` to `.12428`. Those
are meaningful passivity/contact/action-quality warnings, not cosmetic side
metrics. All four probes have zero clip, non-finite, engine-error, demo, and
fallback telemetry. Their log SHA-256 values, in table order, are:

```text
5d91647dbfac12386729de3fcf5a7a5e2f30cfb924de11d5973490e08daa3d4c
4c67b9808bc44e7cb1fc5c0c00601b6c465b456773cc77defa83129b2a6ea95c
97d15e8b601bb32c36bb42e03be643ef631c671b81e7add63e54d523b100d833
11ba60a47064e08ee3054ce7ee8310fd3a0fb02fdbd261f79574f062158d25f8
```

These are one-seed probes against the same cage-bot style that motivated the
defense lineage, not held-out transfer evidence. They clear the forced-team
development sample threshold but not the two learned/style probes required
for graduation.

`defense2` graduates only if its in-sample TD reduction transfers to at least
two held-out learned/style probes. Otherwise keep `turnover3` as the base and
label `defense2` bot-overfit.

### Stage 1 — reward 2×2 screen

Run R0–R3 for `250M` native steps with paired seeds `{42, 43}`, warm from
`turnover3`, static native pool, and `demo_reset_pct=0`.

Total: `2B` requested steps (`1,999,634,432` exact rollout-quantized steps),
about 3 ideal native hours; budget 5–8 hours with pool and evaluation overhead.
Retain the external warm checkpoint, then save at approximately 50M intervals
and at the exact final step. With this rollout quantum the first saved state is
`131,072`, followed by `50,069,504`, `100,007,936`, `149,946,368`,
`199,884,800`, and `249,954,304`. Interleave arm order and reverse it in seed
two.

This screen **completed atomically with all eight arms accepted** in the
isolated audit checkout. Its immutable plan SHA-256 is
`53d33f442be4a17577ec0fabf0bdff1d2dbf7ac35263a34ac9c8c58c6125a947`.
The fixed order is R0/R3/R1/R2 for seed 42 and R2/R1/R3/R0 for seed 43;
the first R0/seed-42 arm started on 2026-07-09 Pacific time. Every arm did:

- finish at exact quantized step `249,954,304`;
- produce the exact current-architecture `16,066,560`-byte checkpoint;
- expose only schema-2 telemetry and at least 10,001 final-policy eval games;
- have zero clip, non-finite, engine-error, and demo-fallback telemetry in
  both training and final evaluation; and
- match the frozen warm, pool, source, config, module, Puffer sources/patches,
  launcher, reward manifest, optimizer, batching, and arm/seed schedule hashes.

The accepted final-policy evaluations are:

| Seed | Arm | Games | Score | Draw | TD/game | Possession | Blocks | 2D | 2D-red | Repair | Ball forward/path |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 42 | R0 | 10,063 | .51744 | .38994 | 1.42323 | .33212 | 15.466 | .64650 | .03599 | .21783 | 7.775 / 9.646 |
| 42 | R1 | 10,063 | .41171 | .57856 | .68101 | .26807 | 13.191 | .66583 | .02669 | .27812 | 3.692 / 5.492 |
| 42 | R2 | 10,025 | .51686 | .41107 | 1.37446 | .32372 | 16.201 | .65613 | .03399 | .22192 | 8.010 / 10.254 |
| 42 | R3 | 10,040 | .39731 | .57450 | .71464 | .24339 | 12.789 | .68259 | .02317 | .29975 | 4.031 / 5.822 |
| 43 | R0 | 10,027 | .53291 | .41777 | 1.45158 | .33262 | 13.276 | .61993 | .04369 | .20168 | 8.384 / 10.463 |
| 43 | R1 | 10,044 | .39710 | .55127 | .74711 | .24316 | 12.577 | .67187 | .02456 | .27095 | 3.576 / 5.373 |
| 43 | R2 | 10,055 | .49378 | .40398 | 1.52481 | .31959 | 15.030 | .65393 | .03654 | .21582 | 8.540 / 10.537 |
| 43 | R3 | 10,003 | .40968 | .63321 | .57673 | .23919 | 11.490 | .67592 | .02070 | .30028 | 3.608 / 5.530 |

Every train and eval phase has zero reward clipping, non-finite rewards,
engine errors, demo episodes, and demo fallbacks. The independent analyzer
verified the manifest, canonical reward hashes, exact eight-file schedule,
every accepted result identity/provenance/checkpoint hash, and the atomic
completion proof. `SCREEN_COMPLETE.json` SHA-256 is
`9a060329a3aaffcf38bc84675b7ae1227def913a7a46f2ef9d925c0ad5c498a0`.
The compact immutable result bundle is retained under
`runs/reward-screens/reward-screen-20260709-v1/`.

The equal-seed descriptive factorial effects are:

| Metric | Possession/gain main effect | Distance main effect | Interaction |
|---|---:|---:|---:|
| TD/game | +.02807 | **+.76365** | -.08061 |
| Match score | +.01038 | **+.11130** | +.01894 |
| Draw rate | -.02130 | **-.17869** | +.03527 |
| Possession | +.01252 | **+.07856** | -.00361 |
| Blocks thrown | -.25009 | +2.48105 | -1.98904 |
| 2D fraction | -.01611 | -.02993 | -.01141 |
| 2D-red fraction | +.00413 | +.01377 | +.00088 |
| Sampled-action repair | -.01730 | **-.07296** | +.01636 |
| Ball forward | -.19064 | **+4.45069** | -.00976 |
| Ball path | -.29265 | **+4.67103** | -.09759 |

The distance family moves the target outcomes strongly in both seeds and is
responsible for nearly all of the scoring, possession, forward-ball, and
action-validity improvement. It also increases block volume and adverse-die
blocks, so the result is a learnability signal rather than proof of sound
clock/risk strategy. The possession/ball-gain family has a small average
match-score effect, inconsistent TD effect within the distance-on pair, and no
forward-ball benefit; its clearest contribution is a further reduction in
sampled-action repair. R2 (distance only) is therefore the parsimonious
transfer finalist from the self-play screen, with R0 retained as its direct
comparator. The next subsection's held-out scripted matrix then rejects R2 as
non-inferior and keeps R0 for confirmation. Two seeds are descriptive, not a
confidence interval or promotion claim.

The frozen screen script and per-arm launcher SHA-256 values are respectively
`cc28fa60f443e4b92e9f95ba4f947dac564bf79d24c00bc39acf1aca21c4421e`
and `f6e9db845af0f0fafb5e8db81fd73b3a8fad00c63670c436b51e5405ba7fba90`.
The plan also pins installed source
`2158480f8bf3bd44f2a7157e5e7f0e8527db7868648d62662e7083bcbde54d1a`,
config `e15beab94a13704164fab297995539336c240107f54653a2a2fcd940c71b63ed`,
imported Linux fp32 module
`5fb1b1df2ca1d13d1af88adf663e4ef3a6690228f820afb2f4132b87db277de4`,
and turnover3 warm checkpoint
`fdcb2f0ebfbc88a29c026d51140ab008bd5dde5995ea5b3233fd0bd210110935`.
The vendored Puffer tree is not a Git checkout on the rig, so its relevant
source and patch contents are hashed directly; this remains a working-tree
audit experiment rather than commit-backed production evidence.

`tools/analyze_reward_screen.py` verifies the plan,
canonical R0–R3 reward hashes, all eight accepted result/completion hashes, and
the optional expected screen SHA before calculating per-seed 2×2 effects. It
reports possession/gain and distance main effects plus their interaction, then
an equal-seed descriptive mean/SD/range. With only two seeds these are
descriptive contrasts, not confidence intervals, hypothesis tests, or a
held-out strength claim.

### R0 versus R2 scripted-opponent transfer

The simplest screen survivor, R2, was tested directly against R0 before any
promotion decision. Native checkpoints from both training seeds were converted
to Torch with zero-filled biases (the native backend has no bias parameters),
then converted back to native byte-identically. Each converted policy was
evaluated against both deterministic scripted styles—contact (`bot_type=0`)
and cage/offense (`bot_type=1`)—with the bot once HOME/team 0 and once
AWAY/team 1. The exact matrix is therefore `2 arms × 2 training seeds × 2
styles × 2 sides = 16` cells.

Each cell used a short 131,072-step loader/optimizer sanity prefix at learning
rate `1e-12`, followed by an explicit final-policy evaluation of at least
1,000 complete kickoff-start games. This is effectively frozen in float32 but
is not a substitute for a future eval-only API. All cells used
`demo_reset_pct=0`, schema-2 telemetry, the same config/module/Puffer/launcher
hashes, exactly one final eval proof, and zero clip, non-finite, engine-error,
demo, and fallback counters. Total analyzed games are 16,076.

| Equal-cell mean | R0 | R2 | Paired R2 - R0 |
|---|---:|---:|---:|
| Champion match score | .47586 | .44742 | **-.02844** |
| Win rate | .21437 | .20354 | -.01083 |
| Draw rate | .52298 | .48776 | -.03521 |
| Loss rate | .26265 | .30870 | **+.04605** |
| Champion TD/game | .33825 | .33227 | -.00598 |
| Bot TD/game | .43417 | .50741 | **+.07324** |
| Champion blocks/game | 7.0097 | 7.5202 | +.5105 |
| Bot blocks/game | 12.9746 | 12.4070 | -.5676 |

R2's match-score contrast is negative in all eight matched cells, ranging
from `-.04648` to `-.01263` (descriptive cell SD `.01303`). Its loss rate and
bot TD rate rise in all eight cells; own TD rate is mixed and nearly unchanged
on average. In other words, removing the combined possession/gain family does
not principally suppress offense here—it gives the opponent more scoring and
turns draws into losses. R0 therefore survives to confirmation. The result
does not identify whether the possession annuity, the one-time ball-gain term,
or their interaction supplies that defense, and scripted bots are not a
learned-opponent/roster grid. Do not promote R0 from this probe alone.

`tools/analyze_reward_transfer.py` verifies the exact 16 filenames, checkpoint
conversion hashes, command settings, config/module/Puffer/launcher hashes,
schema and cumulative game gates, final reprints, integrity counters, and
equal-cell paired contrasts. The durable logs and analysis are under
`runs/reward-transfer-20260713-v1/`; `ANALYSIS.json` SHA-256 is
`d8b688f78716705d8110ff73eaddbddaef58f67413c65549447cc93ed8f2d5ca`.
The Puffer and evaluator SHA-256 values are respectively
`1c2d0ce96e270e12113a037a77f488e850d39ec76e240650ad7e0214bc04dd81`
and `0623753810353def62de995c8cbfa6b1502fb1a5c590e54e1f41b4bed9296464`.
Two training seeds and deterministic bots remain descriptive evidence, not a
confidence interval or tournament-strength claim.

### Stage 2 — confirmation, simplification, and utility

1. Decompose R0's bundled family while distance remains on: possession+gain,
   possession-only, gain-only, and neither for `500M × 2 seeds`. This is the
   next causal screen; R2 is the already-measured neither cell.
2. Confirm R0 against the simplest transfer-noninferior survivor from that
   decomposition for `1B × 2 seeds`, including learned-opponent and roster
   macro evaluation.
3. If rush remains, selected manifest versus no-rush: `500M × 2` each.
4. Replace the raw distance delta with exact discounted PBRS or demonstrate
   non-inferiority after annealing it to zero; then compare with objective-only
   for `1B × 2`.
5. Compare current TD/win utility with win-only plus the selected temporary
   scaffold for `1B × 2`, then reproduce from a second ancestry (initially
   `league9`) for at least `1B × 2`.

A turnover3-only win is a lineage result, not a reward result.

### Stage 3 — opponent quality

Freeze the promoted reward. Run O0/O1/O2 for `500M × 2 seeds` on torch. Total
`3B`, about 7 ideal torch hours; budget 10–15 hours. Promotion is based on
held-out defense transfer and match strength, not `tds_t1` against the training
script.

### Stage 4 — replay curriculum

Run C0/C1/C2 for `250M × 2 seeds`; total `1.5B`, about 6.5–7.2 ideal filtered
hours. Promote C2 only if it beats C1. Confirm C0 versus C2 for `1B × 2`, then
anneal replay starts to zero.

### Stage 5 — contingent narrow scaffold

Only after a measured deficit survives diverse opponents and scenarios, run
reward-off versus exactly one carrier/defense fallback for `250M × 2`, then
`1B × 2` if promising. Require improvement in the exact held-out bucket,
terminal non-inferiority, and persistence after annealing the term to zero.

### Stage 6 — final reproduction

Run matched control and final recipe for `4B × 2 seeds` from a second ancestry:
`16B` total, about 23 ideal native hours or 69–77 filtered hours. This is
practical on the free always-on 2070. Only this stage authorizes a default
recipe change.

## Final working-tree verification

The final audited working tree passes:

- normal and ASan/UBSan engine/environment suites: 392 engine, 25 reward, and
  2 scripted-bot tests in each mode;
- 53 Python tool/analyzer tests;
- 23 replay-loader, converter, and league tests, including current-or-applied
  patch idempotence;
- all 6 contextual-BC feature tests;
- the BC-regularization contract: off-mode four-epoch bit identity and finite
  on-mode learning with decreasing BC loss;
- clean shell syntax for every changed experiment/install launcher;
- exact sequential applicability of the schema-2 phase, eval-game gate, and
  dynamic-metric-key Puffer patches;
- both immutable screen and transfer analyzers against their retained
  artifacts; and
- a clean local installed-source/config/dashboard/build drift check after a
  current bloodbowl CPU rebuild.

The RTX experiments used the separately hashed Linux fp32 module and isolated
audit checkout. No production checkout or service was restarted or modified.

## Metrics and acceptance gates

### Primary metrics

1. Held-out match score `(wins + 0.5 × draws) / games`, plus W/D/L and TD
   for/against.
2. Equal-weight macro-average across opponents and roster cells.
3. Paired/bootstrap 95% confidence interval using common evaluation seeds.
4. Scenario-level functional judgment or chosen-action regret, clustered by
   replay rather than treating decisions from one replay as independent.
5. Generalization gap between training opponent/scenario improvement and
   held-out improvement.

Tournament variance in this project has exceeded naive binomial confidence
intervals. Repeat seeds/batches and paired evaluation are required for close
results; one 2,048-game tournament is not decision-grade inside a narrow Elo
band.

### Secondary canaries

- Ball: pickup attempts/success, corrected possession rate, forward ball
  advancement, path length and path/forward ratio, Secure choice, loose-ball
  control.
- Block/order: dice tier, carrier/target-value split, offensive/defensive
  assists, chosen turnover probability, pending opportunities/value stranded.
- Defense: carrier exposure, deep safety, zero-safety fraction, zero-TZ path,
  minimum dodges, carrier marking, TD conceded.
- Resources/rules: rerolls by half-turn, foul attempts/send-offs, exact
  Stalling opportunity/action by turn and score, Secure use.
- Integrity: error episodes, demo fallbacks, illegal-action rate, reward clip
  fractions, non-finite reward fraction, SPS.
- Archetype: every behavioral metric split by bash/agility/hybrid/stunty and
  matchup.

Human rates are plausibility canaries. They are never promotion objectives.

### Hard rejection gates

Reject immediately on:

- any NaN or infinity;
- `error_episodes > 0`;
- `demo_fallbacks > 0`;
- any terminal reward clipping;
- shaping clip fraction above `0.1%` of shaped/nonzero emissions;
- installed source/config/bank fingerprint mismatch;
- `illegal_frac` more than `0.01` absolute above matched control;
- unexplained SPS below 70% of matched control.

Reject an early arm on:

- held-out macro match-score drop over `0.05`;
- any critical roster cell drop over `0.08`;
- TD-for or forward ball advancement drop over 20%;
- safe-pickup or possession collapse over 25%;
- defense TD-against rise over 20%;
- obvious camping, ball refusal, passivity, or reward farming.

### Promotion gates

Screen promotion requires:

- both seeds move the target metric in the same direction;
- paired macro-score 95% lower bound at least `-0.02`;
- no critical roster cell below `-0.05`;
- at least 15% improvement in the targeted functional metric on two held-out
  buckets.

Final adoption requires:

- paired macro-score lower bound at least `-0.01` versus control;
- no archetype cell worse than `-0.03`;
- if complexity is equal, a lower confidence bound above zero;
- if the candidate is materially simpler, non-inferiority plus removal of a
  demonstrated pathology is sufficient;
- no more than 10% loss in forward ball advancement;
- no more than 15% increase in path/forward ratio;
- no more than 25% increase in carrier exposure;
- no more than five percentage points of extra T1–T6 Stalling;
- no more than one percentage point increase in low-value-target 2D-red;
- at least half of any in-sample defensive TD reduction transfers to held-out
  probes;
- same-direction reproduction in two seeds and a second ancestry.

## Reproducibility checklist

### Source and build

- [ ] Main repository commit hash recorded.
- [ ] Working tree clean, or every diff archived and hashed.
- [ ] PufferLib fork/patch commit hash recorded.
- [ ] `tools/install_puffer_env.sh --check` passes.
- [ ] Installed environment/config hash recorded.
- [ ] GPU, driver, CUDA, Python, torch, compiler, and OS/WSL versions recorded.
- [ ] `_C.env_name`, GPU flag, and `precision_bytes` recorded.
- [ ] Full tests and targeted reward/rule/data tests green.

### Reward and training

- [ ] Complete reward-manifest canonical SHA-256 recorded.
- [ ] No launcher-inherited reward fields.
- [ ] Terminal-stack static validation passes.
- [ ] Terminal emission contains only explicit current-step objective reward
  plus result utility; incidental action/board shaping cannot co-stack.
- [ ] Runtime reward clip/non-finite telemetry inspected.
- [ ] Architecture, optimizer, LR, entropy, gamma, GAE, horizon, replay ratio,
  and all anneal settings recorded.
- [ ] Train seed, env seed, evaluation seeds, and arm execution order recorded.
- [ ] Native/torch backend identical within each causal contrast.
- [ ] Warm checkpoint format, size, SHA-256, and conversion route recorded.
- [ ] Bias dropping/zero-filling from native↔torch conversion documented.

### Opponents and data

- [ ] Opponent-pool manifest, bank order, percentages, and hashes recorded.
- [ ] All rotation triggers disabled or explicitly part of the experiment.
- [ ] Training and test opponents disjoint.
- [ ] Exact raw `rulesVersion` allowlist path/count/SHA-256 recorded.
- [ ] BBP/BBS header, obs/mask sizes, match size, and fingerprint recorded.
- [ ] Train/dev/test split is replay-disjoint and stratified.
- [ ] Replay contribution caps and bucket weights recorded.
- [ ] Any BB2020 record excluded from BB2025 training.
- [ ] Demo reset fraction, bucket predicate, fallback count, and bank hash
  recorded.

### Evaluation and operations

- [ ] Full-game evaluation always uses `demo_reset_pct=0`.
- [ ] Both home/away and receiving orientations covered.
- [ ] Representative roster grid macro-averaged equally.
- [ ] W/D/L, TD for/against, common-seed paired differences, and uncertainty
  reported.
- [ ] Human baselines labeled diagnostic rather than optimization targets.
- [ ] Metric definitions/version recorded; corrected possession semantics used.
- [ ] In-sample and held-out results shown separately.
- [ ] Checkpoint cadence and last-N pruning configured.
- [ ] Disk remains below 80%; final caps copied off-box and hashed.
- [ ] No reward, opponent, backend, observation, and replay-distribution change
  bundled into one causal arm.

## Primary references

Rules and organized play:

- [GW Blood Bowl downloads](https://www.warhammer-community.com/en-gb/downloads/blood-bowl/)
- [GW May 2026 FAQ announcement](https://www.warhammer-community.com/en-gb/articles/wqewdcvv/blood-bowl-faqs-games-designers-notes/)
- [Blood Bowl Base BB2025 searchable rules](https://bloodbowlbase.ru/bb2025/core_rules/the_game_of_blood_bowl/)
- [Blood Bowl Base BB2025 rules and regulations](https://bloodbowlbase.ru/bb2025/core_rules/rules_and_regulations/)
- [Blood Bowl Base latest FAQ mirror](https://bloodbowlbase.ru/bb2025/core_rules/latest_faq/)
- [NAF BB2025 recommendations and clarifications](https://www.thenaf.net/naf-recommendations-and-clarifications-for-bb2025/)

Strategy:

- [NAF new-player resources](https://www.thenaf.net/resources/newplayers/)
- [NAF playbook index](https://www.thenaf.net/resources/playbooks/)
- [The Art of Blocking](https://www.thenaf.net/wp-content/uploads/2013/06/The-Art-Of-Blocking.pdf)
- [GW: countering cages and screens](https://www.warhammer-community.com/en-gb/articles/buo482id/touchline-tactics-how-to-counter-common-plays/)
- [GW: fouling, surfing, tempo, and odds](https://www.warhammer-community.com/en-gb/articles/myjrlrb0/touchline-tactics-how-to-cheat-your-way-to-the-top-in-blood-bowl/)
- [BBtactics cage basics](https://bbtactics.com/cage-basics/),
  [cage breaking](https://bbtactics.com/cage-breaking/),
  [rerolls](https://bbtactics.com/rerolls/), and
  [2–1 grind](https://bbtactics.com/2-1-grind/) — legacy-edition numeric caveat.

AI and reward learning:

- [Justesen et al., Blood Bowl: A New Board Game Challenge and Competition for AI](https://njustesen.github.io/njustesen/publications/justesen2019blood.pdf)
- [MimicBot: Combining Imitation and Reinforcement Learning for Blood Bowl](https://arxiv.org/pdf/2108.09478)
- local synthesis in `docs/reward-discovery-sota.md` and
  `docs/reward-discovery-integration-plan.md`.

Justesen's dense small-board reward menu demonstrates that proxies can make a
sparse environment learn. It does not establish those proxies as a correct
full-game utility. MimicBot shows that imitation plus RL can stabilize Blood
Bowl learning on modest hardware, while also documenting collapse sensitivity
to reward changes. The appropriate inference for this repository is to use
human replays for priors, value, and scenario coverage—and to keep terminal
strength and held-out opponents as the arbiter.
