# Human prior v1 and the offline audit that gates a "stay close to humans" trainer term (2026-10-05)

**Status: offline measurement. No trainer change, nothing wired into training, no rig.**

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
