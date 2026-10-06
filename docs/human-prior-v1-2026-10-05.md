# Human prior v1 and the offline audit that gates a "stay close to humans" trainer term (2026-10-05)

**Status: offline measurement. No trainer change, nothing wired into training, no rig.**

**Result in one paragraph (sections 1 to 6 have the numbers).** By the rule
registered in section 0 the answer to the roadmap's gate is **stop**: on
chain 41's own states the human prior puts *less* weight on Block
declarations than chain 41 does (0.59 against 0.83 where Block is legal), and
the Blitz gap it shows there (0.24 against 0.14) fails the cross-check on
human states. Chain 41 is not shy of declaring blocks. What differs is the
shape of its turns: 3.0 activations a team turn against the humans' 7.2, a
turn ended by choice with players still to activate in 62% of team turns
against 24%, 39% of its Block activations that had a target on offer ended
without a block against the humans' 0.9%, and three in four of its Blitz
declarations never reaching a block. Those were measured after the gate was
read and were not registered. They reconcile with the style panel: 0.45
block targets chosen a team turn against the humans' 2.49, which times 16
turns is about 7 and about 40 a game. A term that asks for more
block declarations would push a decision that is already at the human rate.

## 0. Thresholds, written before any audit number was computed

This section was committed before the audit script existed and before any
comparison between the prior, chain 41 and the human records had been run.
The only numbers known at this point were the corpus counts and the human
declaration counts in the shards (which involve no model).

The roadmap's registered gate (`docs/plans/superhuman-roadmap-2026-10-03.md`
on `opt/long-run-20261001`, M3): "on [the policy's] own game states, does the
human-imitation net put clearly more weight on blocks and blitzes than [the
policy] does? If not, stop." The current warm start is chain 41.

### Definitions

- **Declaration decision:** a decision whose legal action types are exactly
  `{DECLARE}`. The activated player's action kind is chosen in the argument
  head, so the legal kinds are the full argument mask. A kind is **legal** at
  a declaration when it is in that mask.
- **Rate of a kind for a net** over a set of decisions: the mean of the net's
  probability of that kind (the expected rate when the net samples at
  temperature 1). **Argmax rate:** the share of decisions where the kind is
  the argument head's argmax. **Human rate:** the share where the human
  declared it.
- **Recurrent state.** On human states every net runs at zero recurrent
  state. On chain 41's own states chain 41's probabilities are the ones it
  played with (state carried as in play), chain 9 and chain 36 are stepped
  on the same observation stream with their own carried state, and the prior
  runs at zero state, which is how it was trained.
- **Intervals:** 95% percentile bootstrap, 2,000 resamples of whole replays
  (human states) or whole games (chain 41's states).

### Gate B, the registered question (chain 41's own states)

For each kind k in {Block, Blitz}, over chain 41's self-play declaration
decisions where k is legal: `ratio_k = prior rate / chain 41 rate`. The prior
puts **clearly more** weight on k when all three hold:

1. `ratio_k >= 1.5`;
2. the game-clustered interval of `ratio_k` lies entirely above 1;
3. `prior rate - chain 41 rate >= 0.05` (so a ratio of two tiny numbers
   cannot pass).

### Gate A, the cross-check (held-out human states)

Over held-out human declaration decisions where k is legal:
`human rate / chain 41 rate` must meet the same three conditions with a
replay-clustered interval, and the prior must be a faithful stand-in for the
humans there: `prior rate / human rate` inside [0.80, 1.25].

### Verdict rule

- **Proceed** to design the trainer term for kind k: gate B passes for k,
  gate A passes for k, and the prior is faithful for k.
- **Stop:** gate B passes for neither Block nor Blitz.
- **Human-states only:** gate A passes for k but gate B does not. Chain 41
  differs from humans where humans play, but on the states chain 41 itself
  reaches the prior does not ask for more of k, so a declaration term would
  not act there. Reported as stop for the term as the roadmap describes it,
  with what the decomposition below says is different about its states.

Reported with the gate, not part of it: how often each side gets to a
Block-legal or Blitz-legal declaration at all (declarations per team turn,
share of them where the kind is legal), because a declaration term cannot
change how often the opportunity arises.

### Sanity anchor C (scale, not a gate)

The same quantities between chain 41 and chain 9 on chain 41's states: the
Block and Blitz ratios `chain 9 rate / chain 41 rate`, and mean KL in both
directions by decision context. "Prior versus policy" counts as larger than
"policy versus older policy" at declaration decisions when both directions
of mean KL between prior and chain 41 are at least twice the corresponding
chain 9 values. Chain 41 at zero state against itself with carried state is
reported too, so the cost of scoring the prior without recurrence is visible.

### Where a term could act: usable-target rule per decision type

The prior is a **usable target** for an action family when, on held-out
human records of that family (default evaluation subset):

- U1: mean `log p_prior(human action) - log p_chain41(human action)` is at
  least 0.20 nats with a replay-clustered interval above 0 (it knows
  something about humans that chain 41 does not), and
- U2: mean `log p_prior(human action)` beats the uniform-over-legal baseline
  (product of 1/legal count over the three heads) by at least 0.50 nats (it
  is not just diffuse).

A term **would act** on a decision context when additionally, on chain 41's
own states, mean `KL(prior || chain 41)` in that context is at least 0.10
nats. `KL(prior || policy)` is the direction that punishes the policy for
missing what humans do.

### The five examples

Chosen by rule, not by eye: the five decision contexts (legal type sets),
set-up excluded, with the largest summed symmetric KL between the prior and
chain 41 on chain 41's states; from each, the decision at the 90th percentile
of symmetric KL within the context.

### Subset and split, fixed here

- Split by replay ID with `training/human_prior.py holdout_split`
  (seed 20261005): 60 held-out replays, 339 training replays. No held-out
  replay is ever trained on. Model selection uses the last 30 replays of the
  training order as a dev set, never the held-out 60.
- The prior used in the audit is the one trained on the contract default:
  prefix records plus re-seated records whose span closed equal to the
  replay (stamp 1). Human-state audit numbers use the same subset of the
  held-out replays. Every table names its subset.

## 1. The contract change this work rests on

`AGENTS.md`, "Replay and BC contract", now has a third state provenance,
"replay-seated, observation only", an owner-approved exception to the
no-surgery invariant dated 2026-10-05 ("You can do reseats as often as you
need just don't fo overboard"). Re-seated states feed imitation pairs only,
stay in the stamped `BBR1` shard set, are never reset states, exam states or
opponent data, and a loader reads them only when asked and only for the span
stamps it names (default: stamp 1, closed equal to the replay).
`training/bc_pretrain.py` implements the rule and
`training/test_bc_pretrain_reseat.py` tests it. `validation/README.md`
matches.

## 2. Human prior v1

### What was trained on what

- **Data:** the 399 BB2025 FUMBBL replays of `runs/reseat-20261005/ids.txt`,
  regenerated with `validation/lockstep_reseat.py --modes reseat --map`:
  118,478 prefix records and 446,555 re-seated records (stamp 1: 317,628;
  stamp 0: 95,680; stamp 2: 21,442; stamp 4: 11,441; stamp 3: 364). BBP v4,
  observation version 6, exact-joint conditional masks.
- **Split:** by replay ID, seed 20261005. 60 held-out replays, never trained
  on, 339 training replays. Hyperparameters were chosen on a 30-replay dev
  set cut from the 339 (`docs/human-prior-v1/selection.json`), then every
  reported net was retrained on its full training set with the chosen budget.
- **Net:** the current policy architecture, built from the play harness's
  own `MinGRUPolicy` (native gate kernel), from scratch. AdamW, learning rate
  1e-3 with cosine decay to 1%, batch 1,024, replay-first sampling, 4 passes
  over the training records, weight decay 0.3, masked cross-entropy summed
  over the three heads under the records' conditional masks.
- **The prior used in the audit** is the default-subset net: 98,211 prefix +
  269,906 re-seated (stamp 1) training records from 339 replays. Native blob
  `runs/human-prior-20261005/final_default/prior.bin`, 16,066,560 bytes,
  sha256 `099438c05f59a8cff963e7f39a252ee49f1a35a55375ff47841f551149d0d286`
  (`runs/` is not tracked; retraining takes four minutes on four CPU threads).

### The three design choices

1. **Bias-free.** The three bias vectors are zero and frozen and the value
   row is zero, so `convert_checkpoint.py` drops nothing and the harness
   loads the blob through the loader it uses for RL checkpoints (tested: the
   loaded blob's logits equal the trained net's exactly). Cost, one seed
   each on the same held-out records: 51.3% exact and NLL 1.283 bias-free
   against 51.6% and 1.283 with biases. D172 measured about 1.3 points; here
   it is 0.3 points and nothing in likelihood.
2. **Zero-state i.i.d. for v1, with a measured cost.** A second recipe
   (`training/human_prior_seq.py`: windows of up to 16 consecutive decisions
   of one coach, state carried, same optimizer settings, same number of
   sampled records) scores 55.7% [54.7, 56.9] exact and NLL 1.160 on the same
   held-out records, against 51.3% and 1.283. The two recipes differ in more
   than recurrence (a replay-then-window sampler weights records differently
   from a replay-then-record sampler), so 4.4 points is a comparison of two
   recipes. The one-variable evidence is inside the sequence net: the same
   weights score 55.7% with the state carried and 49.5% (NLL 1.322) with it
   zeroed. Recent history carries real information about the next human
   action. v1 still runs stateless for three reasons. The audit needs one
   function of the observation that can be put on chain 41's states without
   deciding whose history to feed it. On the policy's states that history
   would be the policy's own non-human decisions. And the pairs cannot give
   the stream the policy sees in play, where the net is stepped on every
   engine step, the waiting coach's included. Sequence state is the first
   thing to revisit in a v2 (section 6).
3. **Subset: the contract default** (prefix plus closed-equal). Measured
   against the alternatives below (the every-stamp held-out column is the
   named measurement `--eval-all-stamps`). Training on everything is 0.6
   points better on held-out prefix records and 1.2 points better on the
   other two held-out sets, and 0.04 nats better on all three, so the
   excluded stamps look like useful data and the default costs something.
   One seed each.

### Training subset against held-out subset (60 replays never trained on)

Each cell is exact accuracy / NLL in nats.

| trained on | train records (prefix + re-seated) | held-out prefix (20,267) | held-out prefix + closed-equal (67,989) | held-out everything (86,451) |
|---|---|---|---|---|
| prefix only | 98,211 + 0 | 46.6% / 1.641 | 46.9% / 1.553 | 46.6% / 1.580 |
| prefix + closed-equal (default) | 98,211 + 269,906 | 50.7% / 1.385 | 51.3% / 1.283 | 51.2% / 1.297 |
| everything (stamps 0 to 4) | 98,211 + 380,371 | 51.3% / 1.347 | 52.5% / 1.241 | 52.5% / 1.252 |

Every table from here on is the **default prior** scored on the **held-out
default subset**: 67,989 records (20,267 prefix + 47,722 re-seated stamp 1)
from 60 replays. Overall exact 51.3% [50.1, 52.6] (replay-clustered).

### By head

| head | accuracy, all rows | rows with a choice | accuracy there | mean p(human) there | mean top probability there |
|---|---|---|---|---|---|
| type | 94.1% | 45,977 | 91.3% | 0.869 | 0.920 |
| arg | 84.6% | 25,311 | 58.7% | 0.513 | 0.601 |
| square | 70.9% | 27,914 | 29.2% | 0.233 | 0.371 |

"Exact" is teacher-forced: each head is scored under the masks that follow
from the human's own choice in the heads before it. Calibration: mean
probability on the human's joint action 0.455; NLL 1.283 nats; the type
head's expected calibration error is 0.007 (confidence within 0.03 of
accuracy in the five bins that hold 99.9% of its rows). The arg and square
heads are slightly overconfident (top probability 0.60 and 0.37 against
accuracy 0.59 and 0.29).

### By action family

"pass", "handoff" and "foul" are the declaration plus the target choice.

| family | n | exact | type | arg | square | mean p(human) | NLL |
|---|---|---|---|---|---|---|---|
| move (step, jump, stand up, end activation) | 31,932 | 42.2% | 89.9% | 100.0% | 50.5% | 0.368 | 1.52 |
| block declaration | 2,192 | 94.8% | 100.0% | 94.8% | 100.0% | 0.708 | 0.37 |
| blitz declaration | 1,053 | 3.7% | 100.0% | 3.7% | 100.0% | 0.249 | 1.53 |
| block-target choice | 3,134 | 85.7% | 98.6% | 100.0% | 86.9% | 0.820 | 0.30 |
| block die choice | 3,252 | 78.1% | 100.0% | 78.1% | 100.0% | 0.691 | 0.46 |
| pass | 49 | 0.0% | 71.4% | 38.8% | 61.2% | 0.006 | 6.26 |
| hand-off | 47 | 23.4% | 85.1% | 46.8% | 89.4% | 0.223 | 3.46 |
| foul | 100 | 31.0% | 85.0% | 49.0% | 97.0% | 0.272 | 2.10 |
| end turn | 296 | 0.0% | 0.0% | 100.0% | 100.0% | 0.079 | 2.81 |
| set-up | 2,826 | 19.9% | 98.4% | 80.4% | 23.5% | 0.142 | 3.77 |
| activate (which player) | 9,050 | 28.4% | 100.0% | 28.4% | 100.0% | 0.251 | 1.67 |
| move declaration | 5,652 | 93.5% | 100.0% | 93.5% | 100.0% | 0.803 | 0.27 |
| other declaration | 42 | 0.0% | 100.0% | 0.0% | 100.0% | 0.077 | 2.73 |
| push and follow-up | 4,854 | 53.5% | 100.0% | 81.4% | 72.1% | 0.503 | 0.80 |
| re-roll and skill use | 3,245 | 89.1% | 89.3% | 99.8% | 100.0% | 0.831 | 0.31 |
| other | 265 | 47.9% | 99.2% | 49.4% | 98.9% | 0.475 | 0.88 |

Read with care: the prior never names Blitz as its top declaration (3.7%)
but gives it the right mass (0.249 mean probability; rate 0.176 against the
humans' 0.185 where Blitz is legal). It has not learned passing (49 held-out
examples, about 300 in training) and it never predicts an early end of turn.

### By half and by team-turn band

| | n | exact | type | arg | square | mean p(human) | NLL |
|---|---|---|---|---|---|---|---|
| half 1 | 38,046 | 51.1% | 94.3% | 84.2% | 70.7% | 0.454 | 1.31 |
| half 2 | 29,943 | 51.6% | 93.9% | 85.1% | 71.3% | 0.456 | 1.25 |
| turn 0 (set-up, kick-off) | 2,177 | 25.0% | 98.6% | 78.7% | 30.8% | 0.189 | 3.40 |
| turns 1-2 | 21,609 | 52.4% | 93.7% | 85.2% | 72.5% | 0.466 | 1.19 |
| turns 3-4 | 17,830 | 53.9% | 94.1% | 84.7% | 74.0% | 0.482 | 1.15 |
| turns 5-8 | 26,373 | 50.9% | 94.1% | 84.6% | 70.9% | 0.450 | 1.27 |
| prefix records | 20,267 | 50.7% | 94.3% | 84.1% | 69.6% | 0.447 | 1.38 |
| re-seated records (stamp 1) | 47,722 | 51.6% | 94.0% | 84.9% | 71.5% | 0.458 | 1.24 |

The prior is as good in half two and in turns 5 to 8 as in the opening. The
same prior on held-out re-seated records it was not trained on: stamp 0
51.4% / NLL 1.35 (13,400), stamp 2 49.4% / 1.28 (3,301), stamp 4 50.3% /
1.45 (1,761).

### Learning curve: would more data help? Yes.

Default subset, nested training sets, same budget in passes, same held-out
records.

| training replays | training records | exact | NLL | mean p(human) |
|---|---|---|---|---|
| 100 | 107,448 | 48.0% | 1.425 | 0.416 |
| 200 | 218,604 | 49.7% | 1.339 | 0.438 |
| 339 | 368,117 | 51.3% | 1.283 | 0.455 |

Each step up still buys about 1.6 points and 0.06 to 0.09 nats, with no
flattening between 200 and 339. The budget is fixed in passes, so the larger
sets also get more optimizer steps (420, 854, 1,438). The selection runs say
the steps are not what helps: on a fixed set the dev NLL bottoms out near
four passes and rises after (1.339 at 4.6 passes, 1.442 at ten, while the
training batches go from about 0.50 to 0.69 exact). That is consistent with
a net short of data rather than of capacity or steps; it does not isolate
it. One seed per point and three points: the reading is that more replays
should help, not by how much. D172's saturation at 0.45
to 0.51 was measured on prefix-only data; this is a different, deeper record
mix and the comparison is not like for like. 11,580 BB2025 replays exist;
these are 399 of them.

## 3. The audit

Thresholds: section 0. Nets: the default prior, chain 41 (`b1830e23`), chain
36 (`b7fb6dee`), chain 9 (`4344e588`), all loaded through the harness's
`load_checkpoint` and run with its forward, native kernel.

- **Human states (A):** the held-out default subset, 67,989 records, 60
  replays, every net at zero recurrent state, the records' own masks.
- **Chain 41's own states (B, C):** 300 self-play games on CPU
  (`tools/selfplay_dump.py`, seeds 20261005 to 20261304, sampled at
  temperature 1, all 300 ended naturally, 0.705 touchdowns per team per
  game), 208,428 decisions, 695 a game. The dump was made twice from the
  same seeds and all 300 action trails were identical. The engine shim was
  compiled from this worktree's engine and env; two seeds replayed on the
  harness's own older engine gave identical action trails. Chain 41's probabilities are
  the ones it played with; chain 9 and chain 36 were stepped on the same
  stream with their own carried state.

Rates below are means of each net's probability (the T = 1 rate). Chain 41 is
close to deterministic (it gives the action it takes 0.94 on average), so its
argmax rates equal its T = 1 rates to two decimals and are not repeated.

### A. Human states

A1. Probability each net gives the human's action, and how often the net's
argmax is the human's action, by family. U1 and U2 are the usable-target
rule of section 0.

| family | n | prior | chain 41 | chain 36 | chain 9 | U1: log p prior - chain 41 | U2: prior - uniform | usable target |
|---|---|---|---|---|---|---|---|---|
| set-up | 2,826 | 0.142 / 20% | 0.076 / 8% | 0.088 / 9% | 0.094 / 10% | 97.6 [87.2, 111.0] | 2.63 | yes |
| activate | 9,050 | 0.251 / 28% | 0.080 / 8% | 0.084 / 8% | 0.104 / 10% | 112.2 [107.4, 117.2] | 0.61 | yes |
| end turn | 296 | 0.079 / 0% | 0.870 / 87% | 0.829 / 83% | 0.772 / 77% | 1.8 [-0.2, 3.8] | -2.11 | no |
| move declaration | 5,652 | 0.803 / 93% | 0.506 / 51% | 0.312 / 31% | 0.531 / 53% | 11.1 [9.9, 12.5] | 1.07 | yes |
| block declaration | 2,192 | 0.708 / 95% | 0.932 / 93% | 0.913 / 91% | 0.934 / 94% | 0.9 [0.5, 1.3] | 1.21 | yes |
| blitz declaration | 1,053 | 0.249 / 4% | 0.481 / 48% | 0.216 / 22% | 0.220 / 22% | 19.3 [17.2, 21.4] | -0.06 | no |
| pass | 49 | 0.006 / 0% | 0.122 / 12% | 0.345 / 35% | 0.191 / 18% | 171 [89, 254] | -2.80 | no |
| hand-off | 47 | 0.223 / 23% | 0.133 / 11% | 0.007 / 0% | 0.034 / 4% | 103 [60, 157] | -2.16 | no |
| foul | 100 | 0.272 / 31% | 0.033 / 3% | 0.036 / 2% | 0.005 / 0% | 126 [68, 197] | -0.61 | no |
| move | 31,932 | 0.368 / 42% | 0.330 / 33% | 0.318 / 32% | 0.331 / 33% | 78.9 [70.9, 86.6] | 0.53 | yes |
| block-target choice | 3,134 | 0.820 / 86% | 0.655 / 65% | 0.653 / 65% | 0.646 / 65% | 55.8 [51.2, 60.3] | 0.79 | yes |
| block die choice | 3,252 | 0.691 / 78% | 0.532 / 53% | 0.531 / 53% | 0.532 / 53% | 59.6 [55.3, 64.3] | 0.18 | no |
| push and follow-up | 4,854 | 0.503 / 53% | 0.432 / 43% | 0.429 / 43% | 0.434 / 43% | 68.1 [63.8, 72.6] | -0.03 | no |
| re-roll and skill use | 3,245 | 0.831 / 89% | 0.815 / 81% | 0.816 / 82% | 0.809 / 81% | 26.1 [23.1, 29.0] | 0.40 | no |
| all | 67,989 | 0.455 / 51% | 0.380 / 38% | 0.354 / 35% | 0.381 / 38% | 69.3 [65.1, 73.5] | 0.61 | yes |

U1 is tens of nats everywhere because the RL nets give e^-100 to actions they
would not take. It separates nothing; U2 does the work. The three chains pick
the human's action 35 to 38% of the time and that has not moved from chain 9
to chain 41.

A2. Marginal family rates per 1,000 decisions on human states (each net's
expected mass at the human's decision).

| family | human | prior | chain 41 | chain 36 | chain 9 |
|---|---|---|---|---|---|
| activate | 133.1 | 132.0 | 50.9 | 52.3 | 60.0 |
| end turn | 4.4 | 5.5 | 86.6 | 85.2 | 77.4 |
| move declaration | 83.1 | 84.8 | 49.6 | 32.5 | 54.6 |
| block declaration | 32.2 | 27.7 | 37.2 | 36.5 | 37.5 |
| blitz declaration | 15.5 | 14.7 | 26.4 | 11.0 | 13.8 |
| pass | 0.7 | 1.9 | 9.8 | 50.2 | 18.8 |
| hand-off | 0.7 | 2.1 | 5.9 | 2.5 | 8.3 |
| foul | 1.5 | 2.1 | 0.2 | 0.2 | 0.2 |
| move | 469.7 | 469.9 | 480.8 | 480.9 | 481.6 |
| block-target choice | 46.1 | 45.8 | 35.9 | 36.0 | 35.3 |

(Set-up, block die, push and follow-up, re-roll and skill, other: identical
across columns by construction, because the type is forced there.)

A3. Declarations where the kind is legal.

| kind | n legal | human rate | prior | chain 41 | chain 36 | chain 9 | human / chain 41 | prior / human |
|---|---|---|---|---|---|---|---|---|
| Block | 2,728 | 0.804 [0.775, 0.831] | 0.692 | 0.928 | 0.909 | 0.934 | 0.87 [0.83, 0.90] | 0.86 |
| Blitz | 5,702 | 0.185 [0.176, 0.193] | 0.176 | 0.315 | 0.131 | 0.164 | 0.59 [0.54, 0.64] | 0.95 |
| Pass | 8,885 | 0.003 [0.002, 0.005] | 0.013 | 0.074 | 0.384 | 0.143 | 0.05 [0.03, 0.07] | 3.82 |
| Hand-off | 8,970 | 0.003 [0.002, 0.004] | 0.013 | 0.044 | 0.018 | 0.062 | 0.06 [0.04, 0.09] | 4.58 |
| Foul | 1,561 | 0.033 [0.023, 0.044] | 0.059 | 0.003 | 0.001 | 0.005 | 11.1 [5.2, 42.7] | 1.80 |

Argmax rates: the prior's are 0.929 (Block), 0.017 (Blitz) and 0.000 for the
other three; each chain's equal its T = 1 rate to within 0.004. Pass and
Hand-off are legal at 98% of declarations (any player may declare them), so
"where legal" is nearly "per declaration" for those two.

A4. Ending the turn while a player could still be activated: 9,346
decisions. Humans 0.032 [0.028, 0.036]; prior 0.040 (argmax 0.000); chain 41
0.630; chain 36 0.620; chain 9 0.563.

### B. Chain 41's own states, with anchor C alongside

B1. Declarations where the kind is legal (28,430 declarations).

| kind | n legal | chain 41 | prior | prior / chain 41 | chain 9 | chain 9 / chain 41 | chain 36 | chain 41 at zero state |
|---|---|---|---|---|---|---|---|---|
| Block | 7,371 | 0.825 | 0.589 | 0.71 [0.70, 0.73] | 0.718 | 0.87 [0.86, 0.88] | 0.783 | 0.872 |
| Blitz | 19,584 | 0.140 | 0.237 | 1.69 [1.61, 1.77] | 0.213 | 1.52 [1.43, 1.62] | 0.103 | 0.147 |
| Pass | 25,079 | 0.072 | 0.028 | 0.38 [0.36, 0.41] | 0.149 | 2.08 [1.91, 2.24] | 0.337 | 0.072 |
| Hand-off | 27,499 | 0.025 | 0.026 | 1.04 [0.95, 1.16] | 0.041 | 1.66 [1.44, 1.90] | 0.021 | 0.019 |
| Foul | 2,855 | 0.003 | 0.087 | 27.1 [13.9, 75.3] | 0.001 | 0.26 [0.04, 0.99] | 0.002 | 0.003 |

Chain 41's sampled rates equal its T = 1 rates to within 0.001.

B2. Ending the turn while a player could still be activated: 34,312
decisions. Chain 41 0.172 (sampled 0.171); prior 0.013; chain 9 0.414; chain
36 0.221; chain 41 at zero state 0.179.

B3. Family rates per 1,000 decisions on chain 41's states.

| family | chain 41 did | prior wants | chain 9 wants | chain 36 wants |
|---|---|---|---|---|
| activate | 136.4 | 162.5 | 96.4 | 128.3 |
| end turn | 28.2 | 2.1 | 68.2 | 36.4 |
| move declaration | 81.9 | 83.4 | 67.6 | 55.5 |
| block declaration | 29.2 | 20.8 | 25.4 | 27.7 |
| blitz declaration | 13.1 | 22.2 | 20.0 | 9.7 |
| pass | 8.6 | 11.9 | 17.9 | 40.6 |
| hand-off | 3.3 | 3.5 | 5.4 | 2.8 |
| foul | 0.0 | 1.2 | 0.0 | 0.0 |
| move | 466.8 | 446.0 | 468.2 | 466.2 |
| block-target choice | 20.6 | 32.7 | 19.4 | 21.3 |

B4. Mean KL by decision context, nats, largest summed symmetric KL first.
"c41" is chain 41 as played.

| context (legal types) | n | share | KL(prior, c41) | KL(c41, prior) | KL(c9, c41) | KL(c41, c9) | KL(c36, c41) | KL(c41 at zero state, c41) |
|---|---|---|---|---|---|---|---|---|
| STEP, END_ACTIVATION | 73,287 | 35.2% | 91.6 | 2.43 | 40.1 | 30.0 | 11.8 | 22.0 |
| ACTIVATE, END_TURN | 34,312 | 16.5% | 87.1 | 2.43 | 14.6 | 10.8 | 4.8 | 2.0 |
| SETUP_PLACE | 21,577 | 10.4% | 78.2 | 11.73 | 23.5 | 17.9 | 8.1 | 0.2 |
| STEP, PASS_TARGET, END_ACTIVATION | 5,588 | 2.7% | 244.0 | 1.97 | 65.2 | 51.0 | 9.5 | 1.5 |
| STEP, JUMP, END_ACTIVATION | 8,839 | 4.2% | 80.8 | 2.21 | 23.6 | 19.9 | 12.0 | 23.9 |
| BLOCK_TARGET, END_ACTIVATION | 5,929 | 2.8% | 116.0 | 2.17 | 25.0 | 25.7 | 6.4 | 1.0 |
| DECLARE | 28,430 | 13.6% | 19.9 | 0.89 | 11.9 | 10.5 | 8.5 | 1.0 |
| CHOOSE_DIE | 4,490 | 2.2% | 50.9 | 0.67 | 0.1 | 0.2 | 0.1 | 0.0 |
| USE_REROLL, DECLINE_REROLL | 6,918 | 3.3% | 31.9 | 0.17 | 0.1 | 0.2 | 0.0 | 0.0 |
| PUSH_SQUARE | 3,017 | 1.4% | 67.0 | 1.06 | 27.1 | 22.3 | 8.1 | 0.1 |
| all | 208,428 | 100% | 78.7 [77.6, 79.8] | 2.94 [2.89, 2.99] | 25.7 [25.3, 26.1] | 19.7 [19.4, 20.0] | 8.3 [8.1, 8.4] | 9.4 [9.1, 9.6] |

`KL(prior, c41)` is at least 10 nats in every context that has a real
choice and 500 or more decisions (the lowest is STAND_UP, END_ACTIVATION at
10.1), so the registered "would act" threshold of 0.10 nats is met in all of
them and separates nothing.
The cause is chain 41's logit scale, not the size of the behavioural gap:
chain 41 gives one action 0.94 on average and the rest e^-100. The bounded
reading of the same comparison is D4.

Anchor C by the registered rule, at declaration decisions: `KL(prior, c41)`
19.9 against `KL(c9, c41)` 11.9 (1.7 times), and `KL(c41, prior)` 0.89
against `KL(c41, c9)` 10.5 (0.08 times). The rule needed twice in both
directions, so by the rule "prior versus policy" is **not** larger than
"policy versus older policy". The asymmetry is the finding: the prior is
diffuse and covers what chain 41 does (0.89 nats), while two near-deterministic
RL policies pay 10 nats whenever they differ.

### D. Added after the first read of the gate (not pre-registered)

The gate numbers said the block gap is not in the declaration, so I measured
where it is. These were chosen after seeing A and B. Humans are measured on
human states and chain 41 on its own self-play states: different rosters,
boards, clocks and opponents. The tables describe two populations; they do
not isolate a cause.

D1. Decisions whose legal types are exactly BLOCK_TARGET and END_ACTIVATION.
In both data sets every one of them has declared kind Block (observation
byte 807). Share that ended the activation without a block:

| | decisions | ended without blocking |
|---|---|---|
| humans (held-out, default subset) | 2,163 | 0.009 [0.003, 0.015] |
| chain 41 self-play | 5,929 | 0.391 [0.368, 0.414] |

On the human decisions the nets' probabilities of ending are: prior 0.011,
chain 41 0.195, chain 36 0.219, chain 9 0.232. On chain 41's decisions:
prior 0.009, chain 36 0.367, chain 9 0.422. The habit is as old as chain 9.

D2. The decision after a declaration is END_ACTIVATION by the same coach.
Only declarations whose next record is verified to be the next decision of
the game are counted (same shard, same re-seat segment, consecutive row; in
self-play every decision is in the dump). One of chain 41's 1,797 Pass
declarations was followed by a decision of the other coach; no other
declaration in either data set was.

| declared | humans: declarations | verified next | ended at once | chain 41: declarations | ended at once |
|---|---|---|---|---|---|
| Move | 5,652 | 5,642 | 0.002 [0.001, 0.005] | 17,078 | 0.178 [0.168, 0.188] |
| Block | 2,192 | 2,189 | 0.009 [0.003, 0.015] | 6,083 | 0.383 [0.360, 0.405] |
| Blitz | 1,053 | 1,052 | 0.005 [0.001, 0.010] | 2,732 | 0.149 [0.132, 0.165] |
| Pass | 30 | 29 | 0.000 | 1,797 | 0.198 [0.176, 0.219] |

D3. Per team turn. Turns are counted from turn-level decisions (ACTIVATE or
END_TURN legal), so a turn with no declaration counts. Human "whole turns"
are the turns made of re-seated records, whose span closed equal to the
replay; the prefix column is shown apart because the last turn of a replay's
prefix can be cut by the lockstep stop. Both human columns leave out every
turn in which the alignment stopped, which need not be a random sample.

| per team turn | humans, whole turns | humans, prefix records | chain 41 self-play |
|---|---|---|---|
| team turns | 899 | 323 | 9,491 |
| declarations (one per activation) | 7.16 | 7.99 | 2.97 |
| ended by choice with a player still to activate | 0.239 | 0.248 | 0.619 |
| Block-legal declarations | 2.18 | 2.38 | 0.78 |
| Block declared | 1.72 | 1.99 | 0.64 |
| block targets chosen in a Block action | 1.68 | 1.95 | 0.38 |
| Blitz declared | 0.86 | 0.85 | 0.28 |
| block targets chosen in a Blitz action | 0.81 | 0.79 | 0.07 |
| Pass declared | 0.024 | 0.025 | 0.189 |
| pass targets chosen | 0.017 | 0.012 | 0.000 |
| Foul declared | 0.048 | 0.025 | 0.001 |
| foul targets chosen | 0.046 | 0.025 | 0.000 |

These are counts of actions, not a product of rates. Actions are counted
only in turns that are in the denominator. They reconcile with the style
panel: block targets chosen are 2.49 a team turn for humans and 0.45 for
chain 41, which multiplied by 16 turns is about 40 and about 7 a game (the
panel measured 40.1 and 6 to 7; the multiplication is an extrapolation, not
a per-game average). For Block actions the 4.4-fold gap (1.68
against 0.38) factors exactly into: 2.4 times fewer declarations a turn,
1.16 times lower share of them with Block legal (0.26 against 0.30), 0.96
times in declaring Block when legal (0.82 against 0.79), and 1.65 times in
choosing a target once Block is declared (0.59 against 0.98). For Blitz
actions the 11-fold gap is 3.1 times fewer Blitz declarations a turn and 3.6
times fewer of them reaching a block (0.26 against 0.94). Chain 41 threw no
pass and no foul in 300 games.

D5. Ending the turn, by how many players were already activated in it
(whole turns; decisions where both ACTIVATE and END_TURN are legal).

| players already activated | human states: n | humans ended | chain 41 at zero state would end | prior would end | chain 41's states: n | chain 41 ended | prior would end |
|---|---|---|---|---|---|---|---|
| 0 | 899 | 0.012 | 0.341 | 0.024 | 9,491 | 0.034 | 0.010 |
| 1 | 858 | 0.003 | 0.395 | 0.027 | 7,133 | 0.147 | 0.012 |
| 2 | 832 | 0.006 | 0.492 | 0.031 | 5,383 | 0.228 | 0.013 |
| 3 | 787 | 0.004 | 0.598 | 0.036 | 3,843 | 0.223 | 0.014 |
| 4-5 | 1,408 | 0.016 | 0.726 | 0.045 | 4,940 | 0.253 | 0.015 |
| 6-7 | 1,130 | 0.050 | 0.853 | 0.057 | 2,345 | 0.368 | 0.017 |
| 8+ | 741 | 0.155 | 0.917 | 0.063 | 900 | 0.349 | 0.023 |

Three things. Chain 41 stops at 15 to 25% per decision from its second
to its sixth activation and at 35 to 37% after; humans almost never stop
before the sixth. Put on
human states, chain 41 would stop far more often than on its own at the
same depth (0.34 against 0.03 before any activation), so depth is not the
whole reason it says "end turn" at 63% of human decisions (A4): human
positions are ones it does not play on from, and its zero-state numbers on
them are those of a policy outside its own distribution. And the prior
follows the humans' rise with depth on human states (0.02 to 0.06) but stays
flat on chain 41's (0.01 to 0.02).

D4. Mean probability each net gives the action chain 41 took.

| context | n | chain 41 as played | chain 41 at zero state | chain 36 | chain 9 | prior |
|---|---|---|---|---|---|---|
| all | 208,428 | 0.94 | 0.77 | 0.69 | 0.51 | 0.29 |
| STEP, END_ACTIVATION | 73,287 | 0.98 | 0.61 | 0.69 | 0.42 | 0.17 |
| ACTIVATE, END_TURN | 34,312 | 0.95 | 0.90 | 0.69 | 0.49 | 0.12 |
| DECLARE | 28,430 | 0.98 | 0.93 | 0.64 | 0.60 | 0.60 |
| SETUP_PLACE | 21,577 | 0.65 | 0.64 | 0.30 | 0.15 | 0.01 |
| BLOCK_TARGET, END_ACTIVATION | 5,929 | 1.00 | 0.96 | 0.90 | 0.78 | 0.48 |
| CHOOSE_DIE | 4,490 | 1.00 | 1.00 | 1.00 | 0.99 | 0.61 |
| FOLLOW_UP | 2,353 | 1.00 | 1.00 | 1.00 | 1.00 | 0.51 |

Two readings. At declarations the prior agrees with chain 41 as much as
chain 9 does (0.60). In the other contexts of this table it is further from
chain 41 than either ancestor; the exceptions are small contexts not shown
(Stand Up: prior 0.73, chain 9 0.68; Touchback; Apothecary). And chain 41 at
zero state gives its own played action 0.61 at movement decisions and 0.90
to 0.96 at declarations, turn-level decisions and block targets. That is
measured on chain 41's own states. It suggests, and does not show, that the
zero-state scores of part A are closer to the played policy at type-level
decisions than at movement; D5 says they are also out of distribution.

### The five examples (chosen by the registered rule)

1. **STEP, END_ACTIVATION** (game 179, step 111). Half 1, turn 3, 0-0, ball
   held by an opposing Beastman Lineman at (6,2). Acting: own Stilty Runna
   at (18,4), just declared. Chain 41: **end the activation** (p 1.00). Prior:
   step to (18,3) 0.35, (19,3) 0.21, (17,4) 0.18; end the activation 0.00.
2. **ACTIVATE, END_TURN** (game 184, step 803). Half 2, turn 8, 0-3 down,
   own Hobgoblin Lineman holds the ball at (9,5). Chain 41: **activate the
   carrier** (p 1.00; prior 0.07). Prior: activate a Bull Centaur at (12,4)
   0.15, the other Bull Centaur 0.14, a Chaos Dwarf Blocker 0.13: its mass
   is on the players around the carrier, not on the carrier.
3. **STEP, PASS_TARGET, END_ACTIVATION** (game 86, step 369). Half 2, turn 2,
   0-0, own Skink Lineman holds the ball at (24,0), one square from the end
   zone. Chain 41: **step to (25,1)** (p 1.00; prior 0.04). Prior: step to
   (25,0) 0.73, end the activation 0.15. Both steps score. This is what a
   518-nat disagreement can look like: a difference with no consequence.
4. **STEP, JUMP, END_ACTIVATION** (game 266, step 65). Half 1, turn 2, 0-0,
   own Fun-hoppa holds the ball at (18,3). Chain 41: **step to (19,2)**
   (p 1.00; prior 0.12). Prior: step to (19,3) 0.45, end the activation 0.34.
5. **BLOCK_TARGET, END_ACTIVATION** (game 27, step 440). Half 2, turn 1, 0-2
   down, an own Bretonnian Squire at (12,4) has declared Block next to an
   Eagle Warrior at (13,5) and a Jaguar Warrior at (13,4). Chain 41: **end
   the activation without blocking** (p 1.00; prior 0.01). Prior: block the
   Eagle Warrior 0.66, the Jaguar Warrior 0.34.

## 4. Verdict against the thresholds of section 0

| | Block | Blitz |
|---|---|---|
| Gate B: prior / chain 41 on chain 41's states (needs >= 1.5, interval above 1, gap >= 0.05) | 0.71 [0.70, 0.73], gap -0.24: **fails** | 1.69 [1.61, 1.77], gap +0.10: **passes** |
| Gate A: human / chain 41 on human states (same conditions) | 0.87 [0.83, 0.90], gap -0.12: **fails** | 0.59 [0.54, 0.64], gap -0.13: **fails** |
| Prior faithful to humans (prior / human in [0.80, 1.25]) | 0.86: yes | 0.95: yes |
| Proceed | no | no |

**Verdict: stop.** The exact outcome is "gate B passes for Blitz, gate A
does not". Section 0 named three outcomes and this is not one of them: I had
not foreseen the prior asking for more of something that chain 41 already
does more than humans on human states. It does not meet the conditions for
"proceed", so I read it as stop. In words:

- **Blocks:** the human-imitation net does not put more weight on Block
  declarations than chain 41 on chain 41's own states. It puts less (0.59
  against 0.83). On human states chain 41 declares Block more often than the
  humans did (0.93 against 0.80).
- **Blitzes:** on its own states chain 41 declares Blitz less than the prior
  would (0.14 against 0.24), but put on human states it declares Blitz more
  than the humans did (0.32 against 0.19). The gap on its own states comes
  with its short turns, not with a reluctance that shows wherever it is asked.

**Where a term would act, by the usable-target rule:** the prior is a usable
target for set-up, which player to activate, the Move and Block
declarations, movement and the block-target choice. It is **not** a usable
target for the Blitz declaration, pass, hand-off, foul, the block die, push
and follow-up, re-roll and skill use, or the choice to end a turn early. The
"would act" half of the rule (KL at least 0.10 nats) is met in every context
with a real choice and 500 or more decisions, and decides nothing.

## 5. What the numbers say a trainer term could and could not change

These are readings of offline probabilities. None of them is a measured
effect on trajectories or on match results; each is a hypothesis for a
paired run to test.

- **Blocks: not through the declaration.** Chain 41 already declares Block
  at 0.83 where it is legal; the prior would pull that down to 0.59. The
  counted gap (D3) sits in how many players a turn activates (2.97 against
  7.16) and in whether a declared Block is thrown (0.59 against 0.98). The
  prior disagrees with chain 41 at exactly those decisions: ending the turn
  with a player left (prior 0.013, chain 41 0.172) and ending a Block
  activation with a target on offer (prior 0.009, chain 41 0.391). It is a
  usable target there when the human continues or blocks, which is nearly
  always.
- **Blitzes: possibly, as a side effect.** Humans declare a Blitz in 0.86 of
  team turns and 94% of those reach a block; chain 41 declares one in 0.28
  and 26% reach a block. Per Blitz-legal declaration the declaring rates are
  close (0.185 human, 0.140 chain 41). Longer turns and fewer empty
  activations might bring blitz blocks with them; nothing here measures
  that. The prior is not a usable target for the Blitz declaration itself.
- **Passing: the prior gives no reason to expect it.** Humans declare Pass
  at 0.3% of declarations, 0.02 a team turn. The prior's probability on the
  human passes it was tested on is 0.006. Chain 41 declares Pass ten times
  as often as humans (0.19 a turn) and threw none in 300 games; chain 36
  would declare it at 38% of human declaration states. The prior's pressure
  is toward fewer Pass declarations, and it has not learned when to throw.
- **Hand-offs: no evidence either way.** 47 held-out examples; the prior
  over-declares it 4.6 times against humans and both rates are under 3%.
- **Fouls: a little, and badly calibrated.** The prior wants a foul at 8.7%
  of chain 41's foul-legal declarations against chain 41's 0.3%, but it
  over-declares fouls 1.8 times against humans on human states. Humans foul
  0.05 times a team turn; chain 41 never did.
- **Turn ending: the largest disagreement, with one caveat.** Humans end a
  turn early in 24% of turns and almost never before the sixth activation
  (D5); chain 41 in 62%, at 15 to 25% per decision from the second to the
  sixth activation. The prior gives stopping 1 to 2% on chain 41's states
  at every depth and 2 to 6% on human states. Stopping is never its top
  choice, and it gives the human early endings it was tested on a mean
  probability of 0.079. A term built on it would push toward stopping less
  often than humans do.
- **Empty activations: a clear disagreement.** 18% of chain 41's Move
  activations and 38% of its Block activations end at once; humans 0.2% and
  0.9%.
- **Any full-distribution KL term is dominated by scale.** `KL(prior, chain
  41)` averages 79 nats a decision because chain 41 is near-deterministic.
  D176's collapse under a full-strength CE anchor is consistent with that.
  A term would have to be bounded, restricted to named contexts and
  probably to the type head.

## 6. Where the plan was wrong, what I missed, and what I would do next

**Where the plan was wrong.**

1. The gate asks about weight on block and blitz **declarations**. That is
   the one place the policy already looks human or more than human. The
   registered answer is stop, and it is the right answer to the question as
   written, but the question does not reach where the block counts differ.
2. "Zero recurrent state for both nets" on human states compares the prior
   in its trained regime with chain 41 outside its own. Chain 41 at zero
   state gives its own played action 0.61 at movement decisions (D4), and
   on human positions it would end a turn before any activation 34% of the
   time against 3% on its own (D5). Part A says how chain 41 scores human
   decisions; it is weak evidence about how chain 41 plays.
3. Human states and chain 41's states differ in turn depth and in the
   positions themselves. A comparison on human states alone would have
   overstated the turn-ending gap (0.63 against a played 0.17) and shown
   nothing about empty activations.
4. KL in nats is the wrong unit against a near-deterministic policy. Both my
   0.10-nat "would act" threshold and the anchor's factor-of-two rule were
   swamped by logit scale. Probability on the taken action (D4) and rates
   are the readable measures.
5. "Pass legal" is true at 98% of declarations, and a Pass declaration is
   not a pass: the RL chains use it as another way to move. The same holds
   for three in four of chain 41's Blitz declarations.
6. The default subset is not free: training on every stamp is 0.6 to 1.2
   points better on the three held-out sets.
7. My own section 0 was wrong in two places. Its verdict rule did not name
   the case that happened (gate B passes, gate A fails). And "a declaration
   term cannot change how often the opportunity arises" is too strong: it
   has no direct loss there, but changed actions and shared weights can
   change which states are visited.

**What I missed until the numbers showed it.** The engine can list the same
push square twice (one decision in 60,000); the sampler is unaffected, a
joint computed by summing tuples is not, and the audit deduplicates. The
three RL chains agree with each other at 99.5% on the block die and with
humans at 53%: either the replay's die index is arbitrary when faces tie,
or the chains share a non-human rule. I did not chase it; that family fails
U2 either way. The first selection run printed held-out scores before the
flag that suppresses them existed; the budget was chosen on dev NLL
(`docs/human-prior-v1/selection.json`), but I had seen them.

**What I would do next, in order.**

1. **Do not build the declaration term.** First ask whether the turn shape
   is load-bearing, with no training: in the harness, chain 41 against a
   copy of itself with three masks (no END_TURN while a player can be
   activated; no END_ACTIVATION as the first decision after a declaration;
   no END_ACTIVATION while a declared Block has a target), paired seeds,
   and the same masked copy against the scripted bots and an older chain.
   Register a non-inferiority margin and the interval before running it. A
   masked copy that is clearly weaker says chain 41 stops early for a
   reason. One inside the margin is evidence the habits are not
   load-bearing; it is not proof that a learned regularizer is safe, since
   a hard mask and a penalty are different interventions.
2. **Ask the trainer why turns are three activations long** before
   prescribing a cure. Candidates to check, none tested here: the
   per-decision discount (gamma 0.999 and lambda 0.95 apply per engine
   step, so a 60-decision turn discounts and blurs credit more than a
   25-decision one), any per-step cost in the reward manifest, and the
   decision cap. If the cause is in the objective, a prior term fights the
   trainer every step.
3. **If a term is built,** scope it to three contexts (`ACTIVATE, END_TURN`;
   the first decision after a declaration; `BLOCK_TARGET, END_ACTIVATION`),
   type head only, bounded, decayed, against a paired control. Its exit
   test is the roadmap's: the normal gate with no loss, and next to it the
   style panel plus declarations per team turn and block targets per turn.
   This audit is offline evidence that the prior and the policy disagree in
   those three contexts; it is not evidence about match results.
4. **Prior v2 is cheap and worth doing before any term:** all 11,580 BB2025
   replays through the re-seat pipeline (399 take 14 seconds to align), the
   wider stamp set if the owner agrees, and sequence state once it is
   decided what history the prior should see on policy states.

## 7. Reproduction and artifacts

```sh
PY=~/Code/bb-play-harness/.venv/bin/python
R=runs/human-prior-20261005
python3 validation/lockstep_reseat.py --ids runs/reseat-20261005/ids.txt \
    --out-dir $R/shards --map --modes reseat --jobs 4
$PY tools/selfplay_dump.py --checkpoint <ckpts>/chain41/0000002999975936.bin \
    --shadow chain9=<ckpts>/chain9/0000002999975936.bin \
    --shadow chain36=<ckpts>/chain36/0000002999975936.bin \
    --games 300 --slots 64 --out-dir $R/selfplay41
$PY training/human_prior.py --pairs-dir $R/shards/pairs \
    --reseat-dir $R/shards/pairs_reseat --replay-ids runs/reseat-20261005/ids.txt \
    --epochs 4 --weight-decay 0.3 --eval-all-stamps --out-dir $R/final_default
$PY analysis/human_prior_audit.py --prior $R/final_default/prior.bin \
    --pairs-dir $R/shards/pairs --reseat-dir $R/shards/pairs_reseat \
    --replay-ids runs/reseat-20261005/ids.txt --selfplay $R/selfplay41 \
    --out-dir $R/audit
python3 analysis/human_prior_report.py $R
```

Variants: `--reseat-stamps 0,1,2,3,4` (everything); no `--reseat-dir` plus
`--eval-reseat-dir` (prefix only, scored on the same held-out sets);
`--train-replays 100|200`; `--with-bias`;
`training/human_prior_seq.py --epochs 4 --weight-decay 0.3`.

Tracked result files: `docs/human-prior-v1/` (`audit.json`, `prior_*.json`,
`selection.json`, `selfplay41_manifest.json`, `tables.md`). Untracked, under
`runs/human-prior-20261005/`: the shards (1.8 GB), the self-play dump
(2.2 GB), the checkpoints.

Limits. One training seed per net. One prior (zero-state, 339 replays). 60
held-out replays. Humans are measured on human states and chain 41 on
self-play states. Human turns leave out every turn the alignment stopped
in. Self-play is chain 41 against itself, not against the pool it trains
in. Section D was not registered. Reviewed read-only by Codex; its findings
and what was done about them are in the commit history after `e98233a`.
