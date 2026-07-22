# Selfplay runtime identity closure

Status: test-first implementation tranche after the v3 exact-action canary was
permanently rejected before training.

## Selected tranche and why now

Make `training/selfplay_league.patch` an installed, checked,
qualification-bound, and experiment-manifest-bound part of the one canonical
Puffer runtime. The v3 canary made its sole authorized start and failed before
GPU use because the runner requires this patch while the fresh qualified
candidate neither applied nor qualified it. The rejected unit, output, and
stopped evidence are immutable and may never be retried or reused.

The generic `plan-ship-tranche` workflow's LobsterClaw-specific
`docs/RECOMMENDED_ORDER.md`, `docs/JARVIS_PLAN.md`, and deployment files do not
exist here. The merged repository, sealed rejection bundle, recurrent
qualification plan, and exact-action canary checklist are the ordering inputs.

## Success criteria

1. A fresh install applies `training/selfplay_league.patch` exactly once and
   fails closed if it is neither cleanly applicable nor already applied.
2. `tools/install_puffer_env.sh --check` proves the patch is present and
   reverse-applicable; it may not accept a marker-only or stale partial patch.
3. Installed-runtime identity includes `pufferlib/selfplay.py`, so rebuilt
   module, qualification identity, and training manifest bind exact selfplay
   semantics.
4. `tools/qualify_recurrent_cuda.py` records and validates the exact patch hash
   in `source_files`. Schema 3 rejects schema-2 qualifications and baselines;
   the operator must predeclare the candidate commit, and that commit must equal
   both the clean control runner and clean isolated candidate checkout.
5. Experiment-manifest patch provenance explicitly includes the league patch,
   while critical-vendor identity binds patched `pufferlib/selfplay.py`.
6. Tests cover missing, unapplied, already-applied, and drifted patch states.
7. PR review and CI are clean before merge.
8. Remote rollout uses a new runtime, qualification, output directory,
   stopped-validation directory, unit, authorization, and one-shot marker.
   The merged launcher remains frozen against any replacement canary until the
   new qualification accepts; a later reviewed authorization change must name
   the replacement explicitly.

## Implementation slices

1. Add behavior-locking installer, qualification, and manifest tests that fail
   on the merged pre-fix tree.
2. Apply and validate the patch in the canonical installer before runtime hash
   and build-header creation.
3. Extend backend/runtime identity and qualification `source_files` identity.
4. Extend experiment-manifest provenance and contract tests.
5. Update qualification/canary docs with the rejected-v3 boundary and fresh
   identity requirement.
6. Run targeted and complete relevant suites; self-review; independent review;
   PR, CI, merge.
7. Build and qualify a fresh remote runtime. Prepare a separately reviewed new
   canary authority only after exact-zero qualification accepts.

## Test plan

- `python3 training/test_selfplay_league.py`
- `python3 -m unittest training.test_recurrent_cuda_qualification`
- `python3 -m unittest tools.test_experiment_contracts`
- Installer fixtures proving clean application, already-applied acceptance,
  unapplied `--check` rejection, and stale/partial rejection.
- Qualification fixtures proving `source_files` contains the exact league patch
  and validation rejects deletion or hash drift.
- Manifest contract tests proving the explicit patch map contains
  `selfplay_league.patch` and critical vendor identity contains
  `pufferlib/selfplay.py`.
- The repository's complete runnable C, `tools/`, and `training/` suites before
  PR readiness.
- A fresh bounded 2070 recurrent CUDA qualification after merge, requiring all
  hard-integrity fields at literal zero before a new canary authority.

## Rollout and validation

- Merge only with green required checks and no unresolved P0-P3 finding.
- Build from merged main in a new isolated remote path; never patch the rejected
  candidate in place.
- Pass the full merged commit through `--expected-source-commit`; require it to
  equal the clean control-runner `HEAD` and the clean candidate checkout
  `HEAD`. A self-discovered or dirty candidate is invalid.
- Verify patched selfplay by full hash and reverse patch check, not marker grep.
- Rebuild the module because runtime identity now includes selfplay.
- Produce and independently validate a new qualification.
- Freeze new plan-only output and systemd authority; run all prestart gates
  twice; only then permit one new start attempt.
- Keep BBTV outside bounded GPU cells and require public HTTP 200.

## Risks and simplification opportunities

- Patch ordering can invalidate context if applied from the wrong directory.
- Marker-only checks can accept partial patches; reverse applicability is
  mandatory.
- Broader identity intentionally invalidates the prior compiled hash and
  requires rebuild/requalification.
- Legacy runtime auto-fix paths can hide installer drift. This tranche makes
  installer/check authoritative; broader cleanup remains separately testable.
- Prefer a centralized ordered Puffer patch registry if it simplifies rather
  than enlarges this focused repair. Otherwise land explicit test-locked lists
  and extract the registry in a behavior-preserving follow-up.

## Out of scope

- Retrying, repairing, resetting, deleting, or reusing rejected v3 artifacts.
- Reward-weight changes or scientific interpretation of the failed canary.
- Long-duration training, promotion, pool ancestry, or BBTV follower changes.
- Preauthorizing or loosening the launcher freeze for a replacement canary
  before schema-3 qualification accepts.
- Broad refactoring of legacy launch scripts without behavior-locking tests.
