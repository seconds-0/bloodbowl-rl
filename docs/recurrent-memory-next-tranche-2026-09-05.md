# Recurrent memory: next implementation tranche

Status: implementation plan only, written while the 50M canary uses the frozen
runtime. Implementation and rebuild work were not performed in this planning
subtask. This document changes no reward, opponent, curriculum, or production
process.

## Finding

The current runtime has one confirmed behavior-state bug and two deliberate,
internally consistent context limits.

The behavior bug is episode leakage. Blood Bowl auto-resets inside `c_step`: a
terminal transition returns `terminal=1` together with the first observation of
the next game. `puffer_recurrent_eval_state.patch` clears recurrent rows on that
terminal before the next forward pass only when `evaluation_mode` is true. In
training, a game that ends before decision 64 therefore leaves its hidden state
in the row used for the new game's first observation. At the next rollout call,
training clears every row, whether its preceding transition was terminal or
not. The cross-episode memory inside a window is the bug. Clearing valid
same-game state at each window edge is the declared finite-context training
regime; it may be undesirable, but it is not by itself a mathematical error.

The horizon-64 state reset and horizon-64 gradient boundary jointly define the
current finite-context policy used for training. Truncated backpropagation
through time can instead carry numeric hidden state into the next segment while
treating that state as detached input. Gradients would still cover at most 64
decisions. Adopting that carried-state form is a deliberate contract change,
not a correction forced by gradient mathematics. The first tranche should
remove terminal leakage and, if adopting carry, change behavior rollout, value
bootstrap, and PPO recomputation together at the existing horizon.

## Current frozen data flow

The evidence inspected for this plan is the source-controlled installed patch
stack, especially `training/puffer_recurrent_eval_state.patch` and
`training/puffer_rollout_transition_closure.patch`, plus the captured runtime
and qualification manifests. The frozen module reports
`rollout_transition_contract=tail-bootstrap-v1`, `reset_state=true`, and
`horizon=64`. No live constructor or GPU process was used.

At construction, primary and frozen-bank recurrent buffers are allocated per
vector buffer and zeroed. CUDA graph warmup snapshots and restores those
buffers to zero. Torch initializes the equivalent policy state to zero.

At a training rollout boundary, `reset_state=true` causes all primary and
frozen-bank rollout state to be zeroed. Torch's
`prepare_recurrent_rollout` performs the same unconditional zeroing and also
zeros its pending reward and terminal inputs. This makes every 64-decision
window a fresh-memory sequence even when the game continues.

Within a training rollout, the state returned by one policy forward is used by
the next forward. Terminal-row clearing is guarded by evaluation mode in both
backends. Because the environment auto-resets immediately, a terminal at step
`t` means the observation consumed at `t+1` belongs to a new game; training
currently forwards that observation with the old game's state.

Evaluation switches mode, resets the vector and all recurrent buffers once,
carries state across rollout calls, and clears a row when the preceding
terminal is set. This is the intended match-memory behavior and explains why
evaluation differs from training.

`tail-bootstrap-v1` closes the transition at the end of a rollout by retaining
the post-step reward and terminal and evaluating the post-step observation.
Torch constructs the training tail recurrent state with `zeros_like(state)`,
and native uses separate zeroed tail-state storage. This is consistent with the
current policy: the next training rollout forcibly starts from zero, so the
bootstrap values the state the next behavior step will actually use. It would
become inconsistent only if behavior state were carried across the window
while the tail continued to use zero state.

PPO recomputation operates on horizon-sized row segments. The existing
training contract does not retain the exact initial recurrent state of each
collected segment; requiring `reset_state=true` makes zero the assumed segment
initial state. That assumption matches the current forced window reset, but it
cannot remain correct once rollout state is carried across windows.

The transition indexing must be made explicit during implementation rather
than inferred from buffer names. For every environment row, the semantic record
should be treated as:

```text
(observation_t, state_in_t, action_t, behavior_logprob_t, value_t,
 reward_t, terminal_t, state_out_t, observation_t+1)
```

Here `terminal_t=1` ends the transition after `action_t` and identifies
`observation_t+1` as the auto-reset game's first observation. The next policy
input state is therefore zero for that row. For a nonterminal transition it is
`detach(state_out_t)`.

## Smallest coherent contract

Call the replacement contract `terminal-aware-tbptt-v1`; the exact exported
name should be fixed before qualification and included in module, run, and
checkpoint provenance.

1. **One state transition rule in every mode and backend.** Immediately before
   forwarding an observation, clear each active row whose preceding terminal
   is one. Otherwise preserve that row's state. Apply this to the primary
   policy and every frozen bank in training, evaluation, graph-on, and
   graph-off execution. Mode changes and fresh vector resets still clear all
   rows.

2. **Carry behavior state across rollout windows.** Do not zero recurrent state
   merely because a 64-step collection window ended. The next window starts
   from the detached state resulting from the preceding transition, after the
   terminal-row rule. This changes behavior context but does not extend the
   autograd graph across windows.

3. **Store exact segment initial state.** Before the first forward of each
   collected row segment, copy its post-terminal-mask `state_in` into rollout
   storage. Store every recurrent layer and every learner-owned row. Frozen
   rows require correct behavior-state handling but remain excluded from PPO.
   Minibatch selection must carry the selected segment's stored state with its
   observations, actions, selected joint masks, and behavior log probabilities.

4. **Recompute from the stored state.** PPO forward/recompute initializes each
   selected horizon segment from its recorded detached `state_in`, applies the
   same terminal reset before each later observation, and never substitutes
   zero except where the stored state or a terminal requires zero. The stored
   initial state is data: no gradient flows into the preceding segment.

5. **Change bootstrap with carry, as one atomic contract.** After the final environment step
   of a segment, preserve the final reward and terminal exactly as
   `tail-bootstrap-v1` does. For a nonterminal tail, evaluate
   `observation_H` using `detach(state_out_H-1)`. For a terminal tail, use value
   zero for advantage recursion; clearing the tail state before any diagnostic
   forward is still required because that observation belongs to a new game.
   Tail evaluation must not advance or overwrite the persistent behavior state.

6. **Keep the present TBPTT length.** Recompute exactly 64 decisions and detach
   at every segment boundary. Do not combine this correctness change with a
   longer horizon, burn-in, overlapping sequences, changed GAE lambda, or
   changed minibatch geometry.

7. **Preserve exact-action and ownership contracts.** State rows must follow the
   same primary/frozen bank layout and permutation as observations, actions,
   selected conditional masks, and log probabilities. Frozen rows must remain
   mathematically ineligible for PPO sampling. Tail and recompute forwards must
   consume the same exact joint-action support as behavior collection where an
   action distribution is evaluated.

8. **Fail closed on lifecycle misuse.** A second rollout may not overwrite an
   unconsumed tail or segment-initial-state record. Training may not consume a
   segment without a complete initial state and tail record. Shape, layer,
   ownership, terminal, or sequence-index disagreement is an error rather than
   a zero-state fallback.

This contract makes the policy's training behavior history match its evaluation
history, except for the deliberate detach at each 64-step boundary. It does not
claim that 64 decisions are sufficient for Blood Bowl strategy.

## Implementation sequence

### 1. Freeze executable semantic fixtures before changing the trainer

Add backend-independent fixture definitions for at least four row histories:

- nonterminal continuation across a window boundary;
- a terminal in the middle of a window followed by auto-reset;
- a terminal on the final transition of a window;
- interleaved primary and frozen-bank rows with different terminal patterns.

Use a deterministic tiny recurrent policy whose state and output are directly
inspectable. A useful fixture increments or hashes its state from the current
observation, making stale carry, accidental zeroing, row swaps, and double
advancement distinguishable.

Acceptance: the fixture declares, for every step, exact `state_in`,
`state_out`, terminal mask, tail state/value input, and segment initial state.
The existing runtime must fail the nonterminal-window and training-auto-reset
expectations, establishing that the tests detect F9 rather than merely replaying
the implementation.

### 2. Repair Torch rollout state first

Replace training-window zeroing with the universal terminal-row rule. Snapshot
the segment initial state after applying the pending terminal mask and before
the first policy forward. Preserve detached final state for the next rollout.
Evaluate a nonterminal tail from a copy of final carried state, without mutating
the persistent state.

Acceptance, CPU executable:

- two consecutive rollouts over a nonterminal row produce the same actions,
  values, and states as one uninterrupted `2H` reference rollout;
- inserting a terminal produces byte-identical post-terminal outputs to a
  separately initialized zero-state reference for that row;
- other rows are unchanged by the terminal reset;
- terminal-at-`H-1` yields zero bootstrap, while nonterminal-at-`H-1` matches a
  direct value forward from recorded `state_out_H-1`;
- a tail forward leaves persistent behavior state byte-identical;
- attempting rollout overwrite or train without complete state/tail evidence
  raises.

### 3. Make Torch PPO recomputation sequence-exact

Extend rollout/minibatch storage with the per-layer segment initial state and
gather it by the same sampled segment indices used for all other PPO tensors.
Run recomputation from that state and apply stored terminals between steps.

Acceptance, CPU executable with learning rate zero and fixed weights:

- every executed learner transition has recomputed log probability equal to
  its stored behavior log probability within the existing fp32 tolerance;
- PPO ratios are finite and near exactly one for every primary row, including
  segments beginning mid-game and segments containing auto-resets;
- recomputed values and recurrent states equal a direct deterministic replay;
- mutating one stored segment initial state changes only that segment and makes
  the ratio fixture fail;
- permuting state indices independently of action/mask indices makes the
  ownership fixture fail;
- no frozen row is selected at `prio_alpha=0` or any supported priority value.

### 4. Port the same storage and rules to native CUDA

Add primary segment-initial-state storage with explicit layer, segment, row,
and hidden strides. Keep rollout state, stored initial state, recompute working
state, and tail state as distinct buffers so CUDA graph capture cannot alias or
advance behavior memory. Apply terminal clearing to active rows before every
behavior and recompute forward. Mirror the rule for every frozen bank's
behavior state.

Acceptance, source and target GPU:

- allocation sizes and stride calculations are checked for overflow and exact
  bank layout;
- construction and graph warmup restore persistent, stored-initial, recompute,
  and tail states to exact zero;
- graph-on and graph-off fixtures are byte-identical for states and actions;
- native and Torch fixtures agree within the established fp32 tolerance;
- the terminal-auto fixture equals its explicit zero-state control after every
  terminal for primary and all frozen banks;
- the nonterminal cross-window fixture equals uninterrupted reference carry;
- tail evaluation neither advances behavior state nor consumes rollout RNG;
- zero-learning-rate PPO covers every primary row with finite near-one ratios,
  no frozen selections, byte-identical weights, and exact-zero integrity
  counters;
- CUDA graph execution counters prove the intended rollout, tail, and train
  paths actually ran.

### 5. Bind and independently validate the new runtime identity

Update the compiled rollout-transition contract string and include every new or
changed trainer source in the backend/runtime closure. Extend qualification
artifacts with the recurrent contract, state tensor shapes, terminal fixture
digests, segment-initial-state digest, tail-state digest, and graph execution
evidence. The validator must recompute these fields independently and reject
the old `tail-bootstrap-v1` contract for this tranche.

Acceptance: installation check, relevant Python unit suites, clean native
build, graph-on/off qualification, terminal controls, exact ratio tests, and
throughput gate all pass from a fresh isolated runtime. No source-only test is
sufficient for CUDA acceptance.

## Scientific comparison after correctness qualification

The correctness tranche changes the trajectories produced during training, so
old checkpoints cannot establish a causal learning improvement. Existing
checkpoints may remain readable for inference if architecture and tensor layout
are unchanged, but their lineage belongs to the old memory contract. Do not
warm-start a scientific comparison across that boundary unless an explicit
graft design treats ancestry as a factor.

First run a bridge evaluation before comparing historical metrics: evaluate the
same frozen old checkpoint with the old and new evaluation implementations on
common seeds and both sides. Expected behavior is identical because current
evaluation already carries through a match and clears terminals. Any material
difference indicates an unintended evaluation regression and blocks training.

Then compare learning from the same declared initialization under exactly two
trainer contracts: frozen current memory behavior versus
`terminal-aware-tbptt-v1`. Freeze reward manifest, environment/module except
the memory patch, optimizer, horizon 64, GAE, total transitions, minibatch
geometry, self-play settings, opponents, seed order, and evaluation policy.
The current arm is a diagnostic control despite its known episode leakage; it
must run only in a separately frozen old runtime, never by reintroducing a
runtime switch into the repaired implementation.

Promotion evidence must include kickoff-start full games with
`demo_reset_pct=0`, both sides, W/D/L and TD for/against, common-seed paired
differences, and held-out opponents. Add memory-specific diagnostics that do not
become objectives: fraction of segments beginning mid-game, terminals per
segment, cross-window continuation count, state norm by time since reset, and
ratio error split by segment-start context and terminal presence. Require zero
clip, non-finite, engine-error, demo-fallback, ownership, state-shape, tail, and
recompute-integrity failures.

Only after the terminal-aware contract passes correctness and held-out bridge
gates should horizon length become an experimental factor. A later fixed-data
comparison can test 64 against one longer trace length while adjusting agent
count/minibatch geometry so total transitions and optimizer exposure remain
comparable. The observed median 146.5 decisions from uninterrupted possession
to score motivates that test; it does not select the winning horizon in
advance.

## Compatibility boundaries and nonclaims

- Saved policy weights can remain tensor-compatible if no policy parameter
  shape changes. Optimizer/checkpoint ancestry is still semantically different
  because rollout collection and PPO inputs change.
- Run manifests, module attributes, checkpoint lineage, qualification schema,
  and analyzer compatibility must name the recurrent contract. Shape alone is
  insufficient.
- Frozen opponent weights need no conversion, but their recurrent behavior
  buffers must obey the new terminal rule and bank permutation.
- Replay BC that trains zero-state independent decisions does not validate this
  contract. Context-BC sequences require their own terminal masks and initial
  state semantics before they can serve as evidence.
- The tranche does not lengthen memory gradients, add burn-in, change the
  MinGRU architecture, alter rewards, or prove better match play.
- If a future implementation passes these gates, that evidence would establish
  the proposed F9 behavior contract. This planning document itself fixes
  nothing, and the broader recurrent-memory debt would remain open until the
  fixed-data horizon comparison and held-out match evaluation are complete.

## Execution amendment — D329–D330, 2026-09-05

The planned contract is now implemented in separate Torch and native patches.
Real CPU trainer tests and native CUDA qualification pass, including terminal
controls, physical row ownership, copied tail state, backward gradient cuts,
unchanged-weight PPO replay, and recorded graph/eager callback execution.
The final native runtime is terminal-aware-v2 (module651ffc40…); raw evidence
and root revalidation are under audit-artifacts/memory-integration-20260905/.
The evaluation bridge and disposable50M canary remain pending. This amendment
updates implementation status; the scientific learning comparison and longer
horizon experiment above remain future work with no strength verdict.

## Completion amendment — D331–D334, 2026-09-05

The frozen evaluation bridge now passes all 16,913 paired decisions exactly.
The full eight-bank test covers all 1,072 primary rows and 475,136 ratios, with
maximum residual 9.06e-6 below 2e-5. The clean 50M canary and fresh GPU checkpoint
reload pass independent artifact verification. It completes 163,235 training
games and 10,175 evaluation games with zero hard-integrity counters and exact
producer-contract agreement. The rejected first canary remains rejected.

The implementation and qualification tranche is complete. This supersedes the
pending implementation statuses above. It does not complete the controlled
learning comparison, longer-horizon experiment or held-out strength gates.
All-draw, zero-touchdown evaluation makes that distinction explicit. Evidence:
`audit-artifacts/memory-canary-repeat-20260905/ROOT_COMPLETION_VERIFIED.json`
and `ROOT_RELOAD_VERIFIED.json`, with the CPU/native evidence under
`audit-artifacts/memory-integration-20260905/`.
