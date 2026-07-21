# Exact policy-action identity

Status: implemented locally; verification/review pending, 2026-07-21

## Selected tranche and why now

The ordinary Blood Bowl binding projects complete legal `bb_action` tuples into
three marginal masks (`type 30 | argument 33 | square 391`). Puffer samples the
heads independently and stores their summed log-probability. When the sampled
Cartesian combination is not an enumerated engine action, `bbe_decode` executes
a different legal tuple. The frozen-run panels measured this repair on roughly
16–22% of decisions and the audit's masked random probe measured 29.19%.

Obs-v5 repairs decision information, but it cannot make a reward experiment
scientifically interpretable while PPO credits a sampled code for a different
transition. Exact action identity is therefore the highest-leverage next
harness tranche.

## Scientific contract and success criteria

For every policy-controlled transition:

1. The sampler draws only from the engine's current legal joint support.
2. The action stored in rollout experience is the action applied by the engine.
3. Rollout and PPO recomputation use the same normalized joint probability.
4. Heads that do not participate in the selected action contribute neither
   log-probability nor entropy.
5. Home/away projection and decode round-trip to the same engine action.
6. Scripted bots continue selecting exact engine actions outside the policy
   sampler and preserve their behavior.
7. Policy-controlled action repair is zero. Any retained legacy snap path is
   explicitly named, disabled for accepted training/evaluation, and visible to
   an integrity gate.

The selected-path entropy scalar is an unbiased estimate of the factorized
joint entropy, but its ordinary pathwise gradient does not propagate
downstream conditional-entropy terms through earlier-head probabilities. This
bounded approximation does not affect exact behavior log-probabilities or PPO
ratios and is tracked separately from action identity.

The implementation should preserve the current semantic type/argument/square
heads and avoid a state-dependent categorical index into `legal[]`. Before
choosing a representation, measure legal-tuple cardinality and dependency
structure across full games and setup/kickoff extremes. Reject a design whose
rollout storage or host-to-device traffic is not viable on the owned RTX 2070.

Characterization result: 53,995 seeded decision windows, mean/max legal support
204.1/2,730, marginal-Cartesian valid fraction 0.591, and dependencies in
76.3% of windows. All 293 repeated projections were identical raw JUMP actions;
no distinct engine actions collided. The chosen transient packed support uses
10 bits per semantic head, reserves `BB_LEGAL_MAX + 391` entries per agent, and
copies only the compact current count per vec buffer. Horizon storage remains
the existing selected 454-wide mask.

## Implementation slices

1. Add a binding-level joint-support oracle and diagnostics segmented by
   procedure, sampled type, and repair tier. Characterize maximum and typical
   legal counts plus which action types require argument, square, or both.
2. Add fail-first tests for marginally legal but jointly invalid combinations,
   sampled/applied disagreement, irrelevant-head pollution, mirror identity,
   and exact probability recomputation.
3. Add the minimum Puffer/env interface required for conditional legal
   sampling. The selected type conditions the argument support; selected
   type+argument condition the square support. Store exactly the conditional
   masks used for the sampled transition so PPO recomputation is identical.
4. Remove first-match repair from the accepted policy path. Keep a defensive
   failure path for malformed/external actions, with no silent substitution.
5. Update standalone drivers, Torch/native patch tests, BBP projection and BC
   loss semantics if their action contract changes. Version any replay or
   checkpoint ABI whose bytes or meaning change; never infer compatibility from
   unchanged dimensions.
6. Update `DECISIONS.md`, `AGENTS.md`, `CLAUDE.md`, relevant skills, and action
   documentation with the exact final contract and residual limitations.

## Test and verification plan

Fail-first targeted coverage:

- C joint-support fixture with a legal set whose marginals admit a missing
  tuple; prove the current decoder substitutes another action.
- Binding property test over seeded full games: every sampled policy action is
  an exact member of the current legal list and equals the applied action.
- Conditional-mask tests for mixed action types, setup placement, Touchback
  recipient/fallback forms, mirrored sides, sentinels, and one-legal-action
  windows.
- Backend frozen-logit test: rollout joint log-probability equals independent
  reference math, and PPO zero-update recomputation yields ratio one.
- Inactive-head test: changing an unused-head logit cannot alter the selected
  action probability, entropy, or gradient.
- Malformed/external action test: fail closed without mutating engine state or
  silently choosing `legal[0]`.

Required local gates:

```text
make test
make asan
python3 -m unittest discover -s tools -p 'test_*.py'
PYTHONPATH=training python3.11 -m unittest discover -s training -p 'test_*.py'
bash tools/install_puffer_env.sh
bash tools/install_puffer_env.sh --check
installed standalone optimized self-test and deterministic FNV repeat
Torch/native backend action-contract tests in the pinned Puffer checkout
native CUDA graph-capture smoke with finite rollout/recompute ratio, entropy,
and gradients
git diff --check
```

Hosted CI, required repository checks, and independent exact-head reviews must
pass on the final commit before merge.

## Rollout and validation

This PR is source-only. It must not rebuild, stop, deploy into, or otherwise
change the occupied RTX 2070 recovery checkout or BBTV. After the immutable live
run reaches its experiment boundary, a separate reviewed deployment will:

1. preserve the final pre-repair baseline artifacts;
2. install the merged source into a new isolated checkout;
3. verify imported module and Puffer patch hashes;
4. run a deterministic integrity smoke requiring zero policy repairs; and
5. run a reward-frozen paired causal screen before any long obs-v5 training.

## Risks and simplification opportunities

- Full joint masks can exceed the RTX 2070 memory/transfer budget. Prefer sparse
  or staged conditional support, and store only the masks actually used by each
  sampled transition.
- A dynamic index into `legal[]` is exact but semantically unstable and damages
  transfer; do not choose it merely because it is easy to mask.
- Adding micro-decisions for each head changes discounting, horizon, recurrent
  timing, and throughput; reject that design unless no same-step conditional
  sampler is viable and a separate scientific review accepts the semantic cost.
- Canonicalizing after sampling without accounting for the full preimage gives
  PPO the wrong normalized probability. Writing the repaired action back is not
  sufficient.
- Look for a single conditional-support implementation shared by rollout,
  recompute, BC, and evaluation rather than parallel native/Torch definitions.

## Explicitly out of scope

- Recurrent rollout/recompute state repair, except for the action-only ratio-one
  test needed to prove this contract.
- Reward coefficients, reward defaults, PBRS, or reward-screen launches.
- New obs-v5 replay extraction, BC training, or checkpoint promotion.
- BB2025 optional-choice/rules work.
- The active RTX 2070 experiment, BBTV, PR #44, and every file under
  `tools/authored_sidecar_authority/`.
