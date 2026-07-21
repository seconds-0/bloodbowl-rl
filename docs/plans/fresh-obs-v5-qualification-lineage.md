# Fresh obs-v5 qualification and checkpoint lineage

Status: source implementation and local verification complete, 2026-07-21.
Source-only work remains isolated from the active RTX 2070 recovery queue and
BBTV. This plan does not authorize deployment or reuse a qualification
checkpoint as training ancestry.

Base: `origin/main` at `c7eb510b604de7fbda030dd0b6a5b82a095fc42d`.

## Why this tranche is next

D217 made obs-v5 a semantic ABI break while deliberately retaining obs-v4's
2,782-byte tensor shape. D218 changed the behavior policy from marginal heads
plus decoder repair to exact sequential joint-action sampling without changing
the three output-head sizes. Blob size therefore cannot distinguish either
boundary.

D219's next deployment stage is a 50M-step `exact-action-canary`, but the
current screen and arm launchers require the historical obs-v4 warm checkpoint
and four-bank marginal-action pool for every profile. Those inputs are
guaranteed to be the wrong lineage for the repaired runtime even though they
pass every byte-size check. A canary launched under that contract could not
qualify obs-v5 or exact-action training.

This tranche repairs the authorization boundary before GPU work resumes. The
canary becomes deterministic fresh obs-v5 self-play with no warm checkpoint or
frozen pool. Any later non-fresh v5 launch must present content-addressed
lineage records; an unlabeled same-size blob fails closed.

## Frozen compatibility contract

The accepted repaired lineage is:

- observation ABI `obs-v5`, semantic version `5`;
- action ABI `exact-joint-v1`;
- policy hidden size `512`, three layers, expansion factor `1`;
- native flat-fp32 checkpoint size `16,066,560` bytes;
- exact installed environment source, imported module, Puffer patch bundle,
  and producing run-manifest identities.

An `exact-action-canary`:

- requires `WARM` and `POOL` to be absent;
- uses fixed fresh initialization and the frozen seed;
- disables frozen banks and external league preseeding;
- records `qualification_only: true` and cannot produce promotable ancestry;
- omits both `--load-model-path` and `--selfplay.league-preseed` from the
  effective trainer command.

Historical analysis remains readable. This contract changes launch admission,
not old artifacts or their interpretation.

## Test-first implementation slices

1. Add launcher regressions proving the canary rejects either legacy input
   before artifact creation and emits a fresh, pool-free command contract.
2. Add one small `checkpoint_lineage.py` authority that writes and validates
   canonical, content-addressed lineage sidecars. Cover missing, malformed,
   hash-mismatched, ABI-mismatched, implementation-mismatched, and
   qualification-only inputs.
3. Split the arm launcher into explicit `fresh-v5-qualification` and
   `lineage-v5` bootstrap modes. Fresh qualification has no external assets;
   lineage-v5 requires a valid warm sidecar and valid sidecars for every pool
   bank before trainer construction.
4. Freeze bootstrap/ABI/ancestry fields into screen and arm manifests, then
   validate them again when materializing results or recovering an arm.
5. Publish a lineage sidecar for each accepted final checkpoint, binding it to
   the checkpoint, producing run manifest, source/module/patch identities, and
   qualification status.
6. Make `build_league.py` require and copy accepted lineage sidecars for current
   v5 pools; retain an explicitly named legacy-analysis mode only for historical
   reconstruction outside accepted training launchers.
7. Update D217-D219 operating guidance after the executable contract passes.

## Acceptance tests

- Canary plus `WARM` or `POOL` fails before creating `OUT_DIR`.
- Canary without either input reaches plan validation and its frozen command
  contains no warm load, league preseed, or frozen-bank allocation.
- Its screen and run manifests state fresh obs-v5/exact-joint initialization,
  fixed policy shape, fixed seed, zero frozen banks, and qualification-only.
- Same-size synthetic obs-v4/marginal checkpoint sidecars are rejected.
- Missing, malformed, noncanonical, hash-drifted, ABI-drifted, policy-drifted,
  source/module/patch-drifted, and qualification-only ancestry are rejected.
- One unlabeled or incompatible pool bank rejects the whole pool before any
  output is committed.
- Mutating any checkpoint or implementation identity invalidates the sidecar.
- Accepted result materialization writes a deterministic lineage sidecar and
  recovery recomputes and compares it instead of trusting its presence.
- Existing historical analysis tests remain green.

Run:

```text
python3 -m unittest tools.test_checkpoint_lineage
python3 -m unittest tools.test_experiment_contracts
python3 -m unittest tools.test_build_league
python3 -m unittest discover -s tools -p 'test_*.py'
PYTHONPATH=training python3.11 -m unittest discover -s training -p 'test_*.py'
make test
make asan
git diff --check
```

Vendored install/build and CUDA command execution remain deployment-boundary
checks because the active machine is still occupied by the immutable baseline.

## Source verification record

- Fresh pinned PufferLib install: exact-action patch applied cleanly; both CPU
  and CUDA bindings expose environment hash, observation ABI/version, action
  ABI, and exact-action source hash.
- Tools: 231 tests passed, 2 skips for the absent vendored checkout.
- Training: 30 tests passed under Python 3.11, 1 absent-vendor skip.
- Native: 442 engine tests plus 63 focused Puffer tests passed normally and
  under ASan/UBSan.
- `bash -n`, substantive ShellCheck diagnostics, Python compilation, and
  `git diff --check` passed.
- Independent Fable and Codex reviews found no P0/P1 implementation defect
  after fixes. Review findings led to fixed checkpoint byte-size authority,
  non-overridable semantic constants, compiled-module contract binding,
  accepted-result-only eligible publication, and atomic pool publication.

The positive end-to-end canary plan and result write/recovery paths still need
execution against the freshly built GPU runtime. Source tests cover their
components and rejection paths, but source-string assertions are not accepted
as deployment proof. These are mandatory zero-error deployment gates before
the 50M canary, alongside the recurrent and exact-support CUDA smokes.

## Rollout

1. Merge this source-only tranche after hosted checks and independent review.
2. Ship recurrent evaluation-state hardening and its zero-update qualifier.
3. Wait for the active baseline's atomic completion evidence.
4. Build the repaired runtime in a fresh isolated checkout and verify imported
   source/module/patch identities.
5. Pass construction, recurrent, exact-support, and zero-update CUDA smokes.
6. Run the disposable fresh 50M canary under the zero error budget.
7. Separately create accepted obs-v5 training ancestry and a same-lineage pool
   before any long causal comparison.

## Risks and simplification review

- Do not infer lineage from path, filename, timestamp, byte count, tensor
  dimensions, or a source-tree checkout alone.
- Do not let qualification-only output become a warm start by copying or
  renaming it; eligibility is inside the hash-bound sidecar.
- Keep one canonical JSON representation and one validator shared by launch,
  pool construction, result publication, and recovery.
- Validate all inputs before writing a pool or launching a trainer.
- Keep historical reconstruction explicit and outside accepted v5 launch
  paths; there is no automatic upgrade from legacy artifacts.

## Explicitly out of scope

- Bridging or converting obs-v4 weights to obs-v5.
- Reusing the canary checkpoint for a long run, reward comparison, promotion,
  or frozen pool.
- Generating the eventual obs-v5 BC anchor or training pool.
- Recurrent-state repair, decision-cap truncation, rewards, rules, BBTV, live
  services, or the active recovery queue.
