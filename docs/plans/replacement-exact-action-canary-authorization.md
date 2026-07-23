# Replacement exact-action canary authorization

Status: implementation plan; no canary authority or launch is created by this
document.

## Selected tranche and why now

D225's merged CUDA process boundary has completed one independently accepted
target-GPU qualification at `ee7ace47306b122f48439185e24e9a2cf00be42d` with
all mandatory gates accepted and all 16 hard-integrity counters exactly zero.
The same commit intentionally rejects `exact-action-canary` before creating an
output. The next tranche is therefore a fail-closed authorization path for one
fresh, reward-frozen 50M canary.

Changing launch code changes the candidate source identity. The accepted D225
qualification is a prerequisite for this tranche, not authority to stretch its
verdict over new launcher bytes. The final merged authorization commit must be
built in fresh isolated control/candidate roots and must pass a new schema-3
construction, predecessor-control consumption, full qualification, and
independent validation before plan-only or live canary work.

## Success criteria

1. An `exact-action-canary` invocation remains rejected before output creation
   unless it supplies an absolute, hash-bound authorization artifact through
   explicitly named environment variables.
2. Plan-only authority and live-launch authority are distinct. Plan-only may
   create only the immutable `SCREEN_MANIFEST.json` plus zero-byte released
   `.screen.lock`; live launch additionally requires an authorization that
   binds that exact two-file output and the exact systemd unit.
3. The authority validator independently revalidates the accepted schema-3
   qualification from its separately bound clean control/runner checkout using
   candidate Python, while requiring the runner and candidate roots to differ
   but their merged commits to match. It also revalidates the exact clean
   source commit/tree, candidate/Puffer/module/
   backend/environment identities, the byte-identical accepted Gate-6 recovery
   verdict and full preservation inventory, CUDA runtime identity, frozen
   one-seed 50M contract, zero error budget, and qualification/ancestry
   exclusions.
4. The screen manifest and per-run manifest bind the accepted qualification,
   authorization, shared CUDA wrapper, expected CUDART path/hash/device count,
   and exact 16-key hard-integrity registry.
5. The trainer's same-process pre/post CUDA evidence must equal the qualified
   CUDART declaration before optimization. A mismatch terminates the fresh
   process and no fallback exists.
6. The live unit is one-shot, disabled, `Restart=no`,
   `KillMode=control-group`, `ARM_DETACH=0`, and bounded to two hours. Its first
   `ExecStartPre` exclusively creates the immutable sibling
   `CANARY_LAUNCH_CONSUMPTION.json`; qualification and empty-GPU probes run only
   after that irreversible operation, so any later prestart or launcher failure
   consumes the sole attempt. The launcher validates that consumption before
   output mutation and uses `env -u WARM -u POOL`.
7. Any nonzero, missing, malformed, non-finite, or drifted integrity/provenance
   field rejects the attempt. No retry, resume, repair-in-place, checkpoint
   eligibility, reward evidence, or BBTV promotion is introduced.
8. Source tests, sanitizer/engine tests, Python 3.11 tests, independent code and
   test review, required GitHub checks, merge, fresh target deployment, new
   qualification, off-box preservation, and independent qualification review
   all pass before the canary can be started.

## Implementation slices

1. Add behavior-locking tests that prove the current frozen rejection and the
   required pre-output failure modes for absent, relative, malformed, digest-
   mismatched, stale-qualification, wrong-source, wrong-output, and wrong-mode
   authority.
2. Add one narrowly scoped authority tool with explicit `plan`, `launch`, and
   read-only `validate` contracts. It will create artifacts atomically and
   validate current files rather than accepting self-reported hashes.
3. Route only `exact-action-canary` through that authority boundary in
   `run_reward_screen.sh`; leave every other screen profile unchanged.
4. Bind qualification/authorization and expected CUDA identities through the
   immutable screen contract into `run_reward_ablation.sh` and
   `puffer_cuda_runtime.py`, and require the trainer process to match them.
5. Update the stopped analyzer, checklist, `AGENTS.md`, `CLAUDE.md`, relevant
   skills, and the decision ledger to describe the replacement contract and
   keep the rejected `a52fc6e2`/v1/v2/v3 artifacts immutable.
6. Add deterministic unit rendering and synthetic systemd escape probes. The
   real unit is rendered only from a fully validated launch authorization.

## Test plan

- Focused authority/launcher tests:
  `python3.11 -m unittest tools.test_experiment_contracts training.test_recurrent_cuda_qualification`
- Authority-tool tests, including mutation coverage for every required field:
  `python3.11 -m unittest tools.test_exact_action_canary_authority`
- Trainer/CUDA provenance tests:
  `python3.11 -m unittest training.test_recurrent_cuda_qualification.QualificationValidatorTests.test_trainer_wrapper_publishes_its_own_runtime_evidence_before_main`
- Full tool suite:
  `python3.11 -m unittest discover -s tools -p 'test_*.py'`
- Full training suite:
  `python3.11 -m unittest discover -s training -p 'test_*.py'`
- Static checks:
  `ruff check tools training`
  and `python3.11 -m py_compile` for every changed Python file.
- Engine and sanitizer checks:
  `make test` and `make asan`.
- Patch/application checks:
  fresh `tools/install_puffer_env.sh`, reverse applicability of every frozen
  Puffer patch, and local CPU-binding/native compile coverage where available.
- Diff hygiene:
  `git diff --check origin/main...HEAD` and an explicit full-diff review.
- Remote final-commit validation: fresh isolated fp32 build, one construction
  gate, exact untouched predecessor consumption, one full qualification, two
  fresh validator processes, closed inventories, and off-box hash verification.

## Rollout and validation

1. Merge only with required CI green and no unresolved P0-P3 review finding.
2. Create entirely fresh remote control, candidate, qualification, plan,
   stopped-validation, authorization, unit, and evidence identities. Never
   mutate the recovery, rejected canary, or D225 qualification roots.
3. Stop BBTV only inside bounded GPU cells, preserve the public tunnel, and
   restore/check BBTV and empty GPU state after every cell.
4. Requalify the exact merged authorization commit. Preserve and independently
   validate it locally and off-box.
5. Materialize plan-only exactly once. If its closed output is anything other
   than the expected manifest and released zero-byte lock, reject it permanently.
6. Freeze and independently review the live authorization and unit. Run only
   non-training systemd escape probes before installing the disabled unit.
7. Start the unit once only after all gates accept. Monitor at no more than the
   frozen 30-second interval, stop on the first violation, and never restart.
8. After exit, run the three independent stopped checks, seal/copy the complete
   output, and keep its checkpoint permanently qualification-only and ineligible.

## Risks and simplification checks

- Avoid two competing authority parsers: one Python validator owns schema and
  mutation checks; shell only normalizes environment and invokes it.
- Avoid circular authority: plan authority precedes the two-file plan; launch
  authority binds the resulting plan and unit. Neither is silently upgraded.
- Avoid self-attested evidence: paths and hashes are recomputed from disk, and
  qualification validation runs from a fresh process.
- Avoid source-identity ambiguity: the final launchable commit is requalified;
  the earlier `ee7ace4` result is never claimed to cover later code.
- Avoid output substitution: both plan-only and live launch require the
  validated authority's exact output path to equal `OUT_DIR` before `mkdir` or
  lock creation; stopped analysis requires the launch record's exact current
  manifest path rather than accepting only its basename.
- Avoid hidden fallback lanes, permissive defaults, optional digests, inherited
  warm/pool variables, or a general-purpose training authorization.

## Explicitly out of scope

- Launching or monitoring the 50M canary before this tranche merges and the
  exact merged commit passes fresh target-GPU qualification.
- Retrying or modifying any rejected `a52fc6e2` canary artifact.
- Changing rewards, optimizer settings, policy shape, opponent policy,
  production defaults, recovery artifacts, or BBTV checkpoint selection.
- Treating qualification or canary metrics/checkpoints as learning evidence,
  training ancestry, reward comparison, or promotion authority.
- Authorizing a multi-day or causal reward run.
