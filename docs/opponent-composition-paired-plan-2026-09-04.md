# Opponent composition at fixed exposure: paired plan

Status: prospective plan only. Do not launch from this document. Freeze a
machine-readable plan after the trainer-repair build qualifies on the RTX 2070.

## Causal factor and invariant allocation

Compare the composition of six learned-opponent seats while holding every
other input fixed. Both arms use 2,048 agents, two buffers, 1,024 rows per
buffer, eight frozen banks, and `frozen_bank_pct=0.06`. Integer allocation is
61 rows per bank: 488 frozen rows, 536 learner rows. `scripted_bank_mask=3`
selects bank tags 1 and 2 for the contact script, so both arms have exactly 122
script rows, 366 learned-history rows, and 48 learner rows forming 24 mirror
matches per buffer. Adaptive rotation is disabled (`swap_winrate=1.1`,
`snapshot_interval=1000000000000`). The mask, pool order, warm checkpoint,
reward, start distribution, recurrent handling, optimizer, compiled module,
patch bundle, and seed are immutable plan inputs.

The control pool order is:

1. contact placeholder A (weights are loaded and validated but actions are
   replaced because mask bit 0 is set)
2. contact placeholder B (mask bit 1)
3. `anchor-kickbot` twice
4. `rung0warm` twice
5. `rung0warm1` twice

The three control checkpoint identities come from the chain-9 pool manifest:

- `anchor-kickbot`: SHA-256 `3541a65a915335e809a38ce39b9d7fb9719b5c1d2e4602980ca27850fa5e9e19`
- `rung0warm`: SHA-256 `73538579091314dfd18b6e123aaa6a5e83f9c32b72db6b2dc58e03967488527f`
- `rung0warm1`: SHA-256 `cf74503db2d62221af82d4792bf5f6511fec6180aa1ae24e4224f0119b6499b6`

The candidate retains one copy of each of those three policies in banks 3–5
and puts three contrasting eligible policies in banks 6–8. Candidate options
remain an exploratory inventory until `freeze_opponent_composition.py` receives
three explicit `--candidate` inputs. The resulting pool hashes freeze the
choice before either outcome exists.

Both arms warm from chain 9, SHA-256
`4344e588c124f7df2c887a824e1847008a02be57e63bd423c3c0b02964258dcc`,
use reward `r0_poss_half`, kickoff starts (`demo_reset_pct=0`), and seeds 42 and
44. Run order is paired and reversed: seed 42 control then candidate; seed 44
candidate then control. Never compare against the old source build as the
causal control.

## Qualification, pilot, and checkpoint exams

Before training, install and build the qualified integrated source in the
isolated audit checkout. Run the native hook/config tests, prove mask 3 produces
the same contact action trace as the legacy single tag in each selected seat,
prove unselected tags remain policy-controlled, prove the frozen PPO mask still
excludes all 488 frozen rows, and exercise all nine recurrent state groups at
eight banks. Reject any config with a tag and mask together, a negative or
out-of-range mask, a selected bit above bank count, non-AWAY scripted seats, or
any allocation other than 122/366/48.

Run the initial 100M-step paired screen at seeds 42 and 44, reversed in order,
with checkpoints at 50M and 100M. It is exploratory. At 0M, 50M, and 100M,
evaluate both arms from kickoff with `demo_reset_pct=0` against: both contact
sides, both offense-script sides, chain 9 on both orientations, each of the six
unique learned pool policies on both orientations, and mirror. Use common game
seeds within every arm/checkpoint/opponent/side cell. Require at least 1,000
completed games per scripted cell and 512 per learned/mirror cell, W/D/L and TD
for/against, final cumulative reprints, and zero clip, non-finite, engine-error,
demo, fallback, exact-action, and recurrent integrity counters.

Any run beyond 100M requires a new decision and separately frozen plan. Primary
reporting is paired macro match score over scripted style/side cells and
held-out learned opponents. Two seeds cannot promote a production default.

Every pool copy, manifest, plan, source/config/module/patch bundle, checkpoint,
result, and final analysis receives a SHA-256 identity. Any integrity failure
rejects that arm and its pair; do not average or resume a PPO arm under the same
identity.
