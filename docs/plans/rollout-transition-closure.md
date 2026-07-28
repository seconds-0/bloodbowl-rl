# Rollout transition closure

Status: planned, 2026-07-28. No implementation or deployment is authorized by
this document alone.

Base: local strict-environment-config commit
`c1acdd7d1e94c1d46a930443edbabc8d07732282`.

This is P0-B0, the first trainer prerequisite for deterministic trainability.
A later tranche must make recurrent rollout and PPO recomputation
terminal-aware inside a horizon before any variable-length or early-terminal
capability family is credible. A fixed sentinel may precede that larger repair
only if it fails closed on `max_decisions == horizon`, exactly one episode per
environment per rollout, and no earlier terminal. This tranche, by itself,
does not qualify an authored scenario or prove that Blood Bowl is trainable.

Kimi review was explicitly waived by the user. Adversarial plan review,
post-implementation independent review, and self-review remain mandatory.

## Confirmed defect

Pinned PufferLib commit
`9836f0d2e78889c1aaf189c04d161b6fc61a9386` stores a delayed transition:

```text
rollout slot t = observation_t, action_t, value_t, logprob_t,
                 reward_(t-1), terminal_(t-1)
```

GAE therefore reads reward and terminal from `t + 1`. Both the CPU and CUDA
implementations iterate only from `horizon - 2` down to zero. The action in
`horizon - 1` is nevertheless sampled and executed.

Its outcome arrives after the rollout has ended:

- Torch saves it as `pending_rewards` / `pending_terminals`, then clears it at
  the next training rollout boundary.
- Native leaves it in the live environment buffer, copies it into slot zero of
  the next rollout, and never reads that slot for an advantage.

Thus one executed transition per agent per rollout is absent from the
objective. The corresponding last-slot advantage remains zero, but PPO later
mean-centres the full advantage tensor, so the action can still receive an
unrelated policy gradient.

This is not a negligible edge case for the first authored trainability probe.
The reviewed F5 score state requires exactly eight legal environment decisions,
and `max_decisions=8` emits its only touchdown reward and terminal after the
eighth action. With `horizon=8`, the existing trainer deterministically drops
the success transition.

Changing the horizon, adding a dummy environment action, retaining Torch's
pending tensors, or treating a positive proxy reward as success does not repair
the missing transition.

## Confirmed adjacent parity defect

The same advantage code has two V-trace equations. CPU and CUDA scalar paths
currently use:

```text
rho * reward + gamma * next_value * nonterminal - value
```

The CUDA vector path uses:

```text
rho * (reward + gamma * next_value * nonterminal - value)
```

They disagree whenever `rho != 1`. The latter is the V-trace temporal-difference
definition in the IMPALA paper. Tail closure changes all three kernels and
requires executable parity, so this plan explicitly standardizes on:

```text
delta = rho * (reward + gamma * next_value * nonterminal - value)
```

This is a reviewed part of `tail-bootstrap-v1`, not an incidental rewrite.

## Bounded contract

1. Preserve the existing delayed in-rollout layout for slots zero through
   `horizon - 1`; changing all buffer layouts is unnecessary for this repair.
2. After all `horizon` actions have executed and their environment writes are
   complete, capture one explicit tail record per agent:
   `reward_h`, `terminal_h`, and `bootstrap_value_h`.
3. Compute `bootstrap_value_h` from the post-action observation using the same
   behavior-policy weights and a fresh zero recurrent state. Training requires
   `reset_state=True` and the next rollout evaluates that observation from
   zero state, so carrying slot `horizon - 1` state into the bootstrap would
   value a policy state that behavior never uses.
4. GAE must consume the tail record first and write an advantage for every
   executed action, iterating from `horizon - 1` through zero. For earlier
   actions it must retain the existing delayed-slot relationship.
5. CPU scalar, CUDA scalar, and CUDA vectorized implementations must agree on
   tail indexing, the canonical whole-TD V-trace weighting above, and all
   `horizon` outputs. Tests must exercise `rho != 1`; ratio-one tests alone
   cannot prove this.
6. Tail rewards must pass through the same `[-8, 8]` pathology clamp as
   in-rollout rewards. A terminal tail must contribute exactly zero bootstrap,
   irrespective of the numerical value output by the network. The terminal
   branch must select zero before bootstrap arithmetic so even a nonfinite
   ignored value cannot contaminate the terminal advantage.
7. Torch must take the extra value-only forward pass only during training and
   must pass a fresh initial state. Native must use a dedicated tail
   observation tensor plus per-bank/per-buffer scratch recurrent state and
   policy activations. The scratch state is zeroed before every tail forward.
   Tail capture must leave live behavior state and ordinary rollout decoder
   activations byte-identical.
8. Native must invoke the tail callback on each worker's existing stream after
   that worker enqueues the final observation/reward/terminal host-to-device
   copies and before its final stream synchronization. A per-buffer tail graph
   must be captured and replayed when CUDA graphs are enabled. Host dispatch
   must require `reset_state && !evaluation_mode`; evaluation must retain its
   current persistent-state behavior and must not run the training-only
   callback.
9. The tail forward pass must not sample or execute another action, advance an
   environment, or increment `global_step`. Exactly `horizon` actions per agent
   remain executed and counted.
10. Primary and frozen-bank rows must use their own policy weights,
    architectures, zero-state scratch, and activations when producing tail
    values. Frozen rows remain ineligible for learner advantages under the
    existing mask.
11. The imported CPU and native modules must advertise
    `rollout_transition_contract = "tail-bootstrap-v1"`. The new Puffer patch is
    part of the installer, compiled-backend identity, qualification evidence,
    and ordered experiment patch-bundle hash.
12. The tail outcome may still appear as the ignored delayed slot zero of the
    next rollout, but it must contribute to advantages exactly once: through
    the preceding rollout's tail record.
13. Default no-bank builds, state-bank authorization, environment semantics,
    observations, exact joint actions, rewards, and production services remain
    unchanged.
14. Tail graph ownership must be explicit. Graph-disabled construction and
    close must not index null rollout/tail graph arrays or destroy an
    uncaptured train graph; graph-enabled close must destroy every non-null
    graph handle before activation storage is freed. Every graph pointer,
    handle, and capture flag is initialized explicitly rather than relying on
    allocator zeroing. Close synchronizes the device, guards the train handle
    with both its capture flag and handle value, and guards each rollout/tail
    array and each member handle independently so partial construction is also
    safe. This removes the existing qualification workaround that relies on
    process teardown for graph-off cells.

The causal installer order is explicit:

```text
puffer_exact_joint_actions.patch
-> puffer_recurrent_eval_state.patch
-> puffer_rollout_transition_closure.patch
-> puffer_frozen_prio_mask.patch
-> puffer_recurrent_cuda_qualification.patch
-> puffer_reward_clamp_range.patch
-> later scripted/warm-start/other patches
-> puffer_state_bank_contract.patch
-> puffer_strict_environment_config.patch
```

Strict configuration remains last. Every patch, including transition closure,
must be exactly reverse-applicable after installation.

## Test-first slices

1. Add red source-contract tests requiring:
   - an ordered `puffer_rollout_transition_closure.patch`;
   - tail reward, terminal, and value storage;
   - a training-only Torch value pass;
   - a native value-only tail callback captured once per buffer;
   - full-horizon GAE loops in CPU, CUDA scalar, and CUDA vector paths;
   - canonical whole-TD V-trace weighting in every path;
   - worker-stream ordering after the final environment upload;
   - dedicated native tail observation/state/activation scratch;
   - module contract markers in both bindings;
   - the explicit installer position after recurrent evaluation and before
     frozen priority;
   - installer, qualifier, screen, ablation, and equality-test identity
     integration.
2. Add executable CPU advantage tests against an independent recurrence
   oracle. Cover:
   - a reward emitted only by the final action;
   - terminal tails ignoring an adversarially large bootstrap value;
   - nonterminal tails using the supplied bootstrap value;
   - terminal tails with `NaN`, positive-infinite, and negative-infinite ignored
     bootstrap values;
   - `rho != 1` and horizons both divisible and not divisible by the CUDA
     vector width;
   - all-zero rewards and one-step horizons;
   - exact-once tail contribution when the same outcome appears in the next
     rollout's intentionally ignored slot zero;
   - finite outputs and exact writes to the final advantage slot.
3. Add an executable Torch rollout test with a deterministic one-agent fake
   vector environment and a stateful test policy. Prove that:
   - exactly `horizon` actions execute;
   - the final reward and terminal become the current rollout's tail;
   - the bootstrap observation is forwarded once without another step;
   - a state-sensitive policy receives zero state at a nonterminal tail, not
     the live end-of-rollout state;
   - evaluation does not perform the extra training bootstrap;
   - two consecutive evaluation rollouts are behaviorally identical to the
     pre-patch evaluation contract, not merely equal in forward-call count;
   - terminal and nonterminal bootstrap behavior differ only as specified.
4. Add native source and target-GPU checks proving the callback is ordered on
   the worker stream after the final upload; tail scratch leaves behavior state
   and ordinary decoder outputs unchanged; all bank layouts stay in bounds;
   and the tail graph is present in graph-enabled execution. Qualification
   snapshots must expose tail rewards, terminals, and values without changing
   the meaning of ordinary decoder outputs. Frozen-bank routing must use
   intentionally distinguishable value heads and a heterogeneous-architecture
   cell, then prove correct per-bank tail values, zero frozen advantages, and
   no frozen priority selection. Add graph-on and graph-off construction/close
   tests that both call ordinary `_C.close`, so neither path relies on process
   teardown.
5. Apply the complete ordered patch stack to a fresh pinned Puffer checkout.
   Build the CPU extension and run the executable tests against the applied
   sources, not merely against patch text.
6. Run the repository's focused trainer, installer, qualification, experiment,
   and engine suites, followed by Python compilation, shell syntax, and
   `git diff --check`.

## Local acceptance

- The current code fails the red tests for a missing tail contract.
- A synthetic terminal reward present only after action `horizon - 1` produces
  the oracle advantage at that action; the old implementation produces zero.
- A nonterminal tail uses `reward_h + gamma * bootstrap_value_h`; a terminal
  tail uses only `reward_h`.
- A state-sensitive nonterminal oracle proves that bootstrap uses the same
  zero recurrent state as the following training rollout.
- Terminal tails with deliberately `NaN`, positive-infinite, and
  negative-infinite ignored values still produce finite reward-only
  advantages.
- CPU scalar and the two CUDA source paths implement the same whole-TD V-trace
  equation for a non-unit importance ratio.
- Tail capture does not change live recurrent state or the ordinary final
  behavior decoder output.
- No rollout executes `horizon + 1` actions, and no evaluation observation is
  forwarded twice.
- Applied CPU Puffer tests and the existing recurrent, exact-action, strict
  configuration, state-bank, experiment-contract, and engine tests pass.
- Patch application is clean and installer drift checking is idempotent on a
  fresh pinned Puffer tree.
- The qualifier rejects a missing or wrong `tail-bootstrap-v1`, binds the
  transition patch path and SHA-256 in its evidence, and records the module
  marker; both experiment launchers hash the same ordered bundle; every
  installed patch is exactly reverse-applicable.
- Self-review and an independent post-implementation review find no unresolved
  correctness issue.

## Deployment-boundary acceptance

These checks are mandatory on a fresh isolated NVIDIA checkout before this
repair is accepted for native training:

- source, module, Puffer commit, ordered patch bundle, and
  `tail-bootstrap-v1` identities match the reviewed evidence;
- a CUDA synthetic rollout shows a nonzero oracle-matching last-action
  advantage for both graph-enabled and graph-disabled execution;
- CPU, CUDA scalar, and CUDA vectorized tail advantages agree within the
  existing precision tolerance at both unit and non-unit importance ratios;
- terminal tails have zero bootstrap contribution, including under deliberately
  extreme finite bootstrap values;
- deliberately different primary and frozen value heads, including a
  heterogeneous frozen architecture, produce their expected zero-state tail
  values without changing live state or ordinary decoder diagnostics; frozen
  advantages remain zero and frozen rows are never selected;
- zero-update rollout/recompute ratios are finite and equal to one for every
  executed slot, including `horizon - 1`;
- graph-enabled and graph-disabled deterministic tail values and advantages
  match;
- throughput regression is measured on the same host/configuration and is no
  more than the explicitly reviewed one-extra-forward-per-horizon budget;
- every hard-integrity counter, including `illegal_frac`, remains exactly zero.

No F5 PPO gate, canary, or long run starts if any deployment-boundary check
fails.

## Explicitly out of scope

- Resetting recurrent state at terminals inside a training horizon or teaching
  PPO recomputation the same segmentation. That remains mandatory before
  variable-length or early-terminal capability families.
- Calling a future boundary-aligned sentinel deterministic before the
  production Torch path seeds Python, NumPy, and Torch before policy
  construction and sampling.
- Publishing or authorizing an authored state bank. The future F5
  qualification must preserve its proof-local BBS identity
  `0xA9000019`; durable identity `0xAE00001A` belongs in the reviewed
  manifest/sidecar unless the frozen schema is explicitly superseded.
- Claiming the current strict pickup fixture can satisfy a 95% pickup-success
  gate. It is test-only and its AG3+ pickup probability remains below that
  threshold even with the available team reroll.
- Reward tuning, scenario success predicates, scripted baselines, self-play,
  held-out scenario families, BBTV, or production deployment.
- Treating local CPU qualification as native CUDA acceptance.
