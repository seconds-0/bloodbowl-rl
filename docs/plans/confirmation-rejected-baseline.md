# Confirmation-rejected baseline characterization tranche

## Selected tranche

Add one explicit vacation-queue route for the case that the already-selected
candidate completes its paired `1B x 2` confirmation and fails the frozen
self-play non-inferiority gate. The route may run only the existing R0
(`both`) recipe as two long, three-seed baseline-characterization screens:
main ancestry followed by the frozen `league9` ancestry.

This is the highest-leverage safe use of the reserved RTX 2070 because the
candidate route is closed, trying another simplification would be post-hoc
selection, and the current all-candidates-rejected fallback is inapplicable.
Long R0 trajectories still measure seed and ancestry variation, establish
reusable learning curves/checkpoints for future matched comparisons, and keep
BBTV useful. They make no reward-promotion claim.

## Success criteria

- The schema-2 queue spec names its route explicitly; candidate acceptance,
  all-candidates-rejected control, and confirmation-rejected baseline evidence
  cannot be confused by overloading `candidate_arm`.
- The new route recomputes the fixed `1B` paired confirmation gate from the
  immutable screen and requires at least one failure. Passing or malformed
  evidence fails closed.
- The exact decomposition scripted transfer must still recommend the declared
  candidate and be bound to the confirmation screen through the existing
  screen/transfer contracts.
- The emitted queue contains only two non-resume-safe `control-final` jobs,
  each R0 at `12B x seeds 42/43/44`, with no learned transfer, candidate gate,
  reward candidate, or production mutation.
- Every source, config, checkpoint, evidence tree, and runner remains hash- or
  tree-pinned under the existing queue guard contract.

## Implementation slices

1. Add route-aware spec validation and names without weakening either existing
   route.
2. Reuse `vacation_reward_gate.validate_screen` with the existing fixed
   thresholds to prove confirmation rejection; preserve its diagnostic report
   in the frozen queue manifest.
3. Reuse the existing `control-final` screen and two-job queue construction for
   the new route, keeping one execution path for R0-only work.
4. Update the decision ledger, autonomy contract, AGENTS/CLAUDE guidance where
   relevant, and the hourly journal.

## Test plan

- Add focused unit tests first in `tools/test_freeze_vacation_queue.py` for:
  accepted rejection evidence; a passing confirmation; malformed/wrong-arm or
  wrong-budget confirmation; non-null learned inputs; wrong final budget; and
  exact two-job output.
- Run:
  `vendor/PufferLib/.venv/bin/python -m unittest tools.test_freeze_vacation_queue`
- Run the complete Python tools suite used by CI and the repository's existing
  experiment-contract checks.
- Freeze a synthetic route and validate the resulting plan through
  `experiment_queue.validate_plan`.
- On the RTX host, deploy the exact merged tree; freeze the real evidence;
  validate all pins; demonstrate non-resume-safe interruption cleanup,
  resume-safe recovery separately, and downstream halt; then launch the real
  service.
- Verify service state, progress freshness, GPU/temperature/capacity guards,
  exact checkpoint selection, and public BBTV rendering.

## Rollout and validation

Ship through reviewed PR and green CI. Deploy the exact merged archive to the
audit tree without mutating production. Freeze `QUEUE_PLAN.json` only after
deployment so it pins installed identities. Smoke the service before starting
the immutable real queue. BBTV may follow complete manifested checkpoints but
remains observational only.

## Risks and simplification checks

- Post-hoc reward selection: prohibited; the route has no candidate output.
- Mislabeling a failed candidate as all-candidates-rejected: prevented by an
  explicit route and independent gate recomputation.
- Duplicated queue construction: avoid it by sharing the existing R0-only job
  builder.
- A passing candidate accidentally entering the baseline route: test and fail
  closed.
- Long-run waste: accepted because the box is reserved; progress, runtime,
  thermal, disk, inode, and provenance guards remain mandatory.

## Out of scope

- Selecting or confirming a second simplification candidate.
- Relaxing any reward or transfer threshold.
- Promoting R0 or another reward to production.
- Changing the environment, backend, opponent distribution, roster, replay
  distribution, optimizer, or production BBTV services.
