# F5 trainability foundation

Status: implementation and local qualification complete, 2026-07-30.
Clean authoritative evidence is the immediate post-commit gate.

Base:
`24eccda6fafdef26d237ee85ef4e2c6819dd4fa9`
(`tranche/entropy-schedule-parity`).

This is the authored-scenario foundation that precedes a recurrent PPO pilot.
It is not a PPO learning result, a production authored state bank, a canonical
authored-sidecar publication, or deployment authority.

Kimi review was explicitly waived by the user. Test-first implementation,
clear-eyed self-review, and independent adversarial post-implementation review
remain mandatory.

## Objective

Create the smallest sealed Blood Bowl task that can answer a later learning
question without conflating environment construction, state transport, action
encoding, reward semantics, recurrent rollout closure, or PPO optimization.

The task is the reviewed F5 score-now state:

- build and identity-reconcile the complete 26-record authored proof bundle;
- extract the one exact F5 record without assigning a second identity;
- install that raw state only in a dedicated compile-time qualification role;
- reset through the ordinary environment bookkeeping downstream of state
  selection;
- execute a fixed eight-decision scoring oracle through the production
  observation, exact joint support, three-head decoder, `c_step`, reward,
  terminal, autoreset, and rollout-tail boundaries;
- measure, but never promote on, a bounded masked-random baseline; and
- prove that ordinary modules and production launchers cannot enable or accept
  the qualification fixture through their supported workflows.

The immediately following implementation is a diagnostic recurrent Torch PPO
pilot. Its configuration and budget will be planned only after this foundation
has produced exact exploration and throughput measurements. A later, separate
implementation may freeze a prospective three-seed learning gate.

## Why this tranche is separate from PPO

The exact safe random baseline is extremely sparse. An independent feasibility
probe at the base commit enumerated 721 distinct zero-dice six-Step scoring
continuations after the required Activate and Declare actions. Their total
masked-uniform probability is:

```text
4.949352957985618e-7
```

That is approximately one safe score per 2,020,466 eight-decision episodes.
One selected reference path has probability:

```text
1 / (22 * 4 * 16^6)
= 1 / 1,476,395,008
= 6.773255088112571e-10
```

A direct 100,000-episode masked-uniform probe produced zero touchdowns, as
expected. At 4,096 agent rows (2,048 two-agent matches), the exact safe subset
predicts roughly one random score per 986 rollouts, or about 32.3 million
reported agent-steps.

Therefore an uncalibrated “PPO reaches 95%” requirement would be circular. A
failed run could be fixture transport, reset bookkeeping, action projection,
terminal timing, recurrence, reward wiring, or simply the absence of a positive
trajectory. This tranche resolves the first six categories before optimizer
behavior enters the claim.

No later pilot may silently respond to sparse exploration by consuming the
reference actions, adding behavior cloning, forcing actions, adding a hidden
curriculum, changing reward, or tuning on future acceptance seeds. Each such
change requires its own reviewed proposal.

## Frozen source facts

The implementation must derive and verify these facts from repository source;
the literals below are watched expectations, not an alternative source of
truth.

### Authored identity

- full proof-bundle records: `26`;
- F5 proof-bundle index: `25`;
- proof-local BBS source ID: `0xA9000019`;
- durable authored source ID: `0xAE00001A`;
- template ID/key: `5` / `f5-score-or-wait`;
- recipe revision, cell, and variant: `1`, `1`, `1`;
- variant/controller seed: `410`;
- capture action count: `51`;
- capture dice count: `19`;
- ruleset: `BB2025`.

The existing immutable identity API accepts the complete 26-record bundle, not
an isolated F5 recipe. The generator must:

1. build the complete bundle with `ad_build_authored_proof_bundle`;
2. validate its exact composition;
3. identity-reconcile that complete bundle with the existing public mapper;
4. locate F5 by the A9 and AE identities and exact template facts, not merely
   by array position;
5. revalidate the F5 predicate and safe continuation;
6. extract the existing recipe and raw match into a qualification fixture; and
7. write one BBS1 record only as a transport oracle.

It must not create a second recipe-to-identity implementation or reinterpret
the proof-local A9 ID as the durable identity.

### Watched byte identities

- complete 26-record BBS bytes: `58,568`;
- complete BBS SHA-256:
  `c984e22178901539157be062764dcaff1efac345836dffb5be17a5b7537447a1`;
- one-record F5 BBS bytes: `2,268`;
- one-record F5 BBS SHA-256:
  `0fe8f1ea3f0470bef2c43709947d2bd3a9fd418b0b7b9d5ca93003e720702e71`;
- raw `bb_match` bytes: `2,240`;
- raw match SHA-256:
  `aab28e6e08184d05a6912d033899916d0228984c38c87e606ee3f2a5d25ac9f2`;
- engine fingerprint: `0x64897cde`;
- team count: `30`;
- skill count: `108`;
- action type count: `30`.

Tests must compare complete hashes and sizes. Prefix comparisons are
insufficient.

### Exact reference route

The captured match is half 1, Home turn 2, Away turn 2, tied 0–0. Home carrier
slot 6 is standing at `(19,10)` with MA 6. With `macro_moves=0`, the canonical
scoring route is exactly:

| Decision | Engine action | Factorized policy tuple |
| ---: | --- | --- |
| 1 | Activate slot 6 | `[6, 6, 390]` |
| 2 | Declare Move | `[7, 0, 390]` |
| 3 | Step to `(20,9)` | `[9, 32, 254]` |
| 4 | Step to `(21,8)` | `[9, 32, 229]` |
| 5 | Step to `(22,7)` | `[9, 32, 204]` |
| 6 | Step to `(23,6)` | `[9, 32, 179]` |
| 7 | Step to `(24,5)` | `[9, 32, 154]` |
| 8 | Step to `(25,4)` | `[9, 32, 129]` |

All eight decisions belong to Home, consume no game dice, and leave Away with
the singleton null support. With `max_decisions=8`, the eighth call emits both
terminal flags, logs one Home touchdown and episode length eight, then
autoresets before the caller can inspect the completed match. Tests must
therefore inspect terminal/reward outputs and the completed-episode log rather
than treating the post-call match score as the finished episode.

`macro_moves=1` invalidates the boundary: Activate, Declare, and one virtual
Step can execute the six engine steps inside the third `c_step`, terminate at
rollout slot three, and spend the remaining five slots in a second episode.
The qualification role must reject it before environment allocation.

## Trust and authority boundary

### Qualification fixture, not a state bank

The role token is:

```text
f5-fixed-state-v1
```

The ordinary module must export:

```text
qualification_fixture_role = "none"
```

The dedicated module must export immutable task facts, including:

- `qualification_fixture_role`;
- fixture/task schema;
- qualification-only boolean;
- full environment source identity;
- fixture source/header identity;
- complete-bundle and one-record BBS identities;
- raw-match identity;
- proof-local and durable IDs;
- exact reference-trace identity;
- horizon/max-decisions requirement; and
- reward-contract identity.

Both ordinary and qualification modules continue to report:

```text
state_bank_kind = 0
state_bank_kind_name = "none"
```

The qualification configuration requires:

```text
demo_reset_pct = 0
state_bank_kind = 0
all state-bank selectors = 0
```

The implementation must not change:

- `PRODUCTION_AUTHORIZED_PRODUCER_KINDS`;
- Python state-bank request reconciliation;
- C production authored validation;
- `test_only_allow_authored`;
- the ordinary installer state-bank CLI;
- production state-bank kind/config validation; or
- production state-bank publication semantics.

The one-record BBS is an independently verifiable oracle. The role resets from
the exact compiled fixture bytes and never claims that BBS to be a production
bank or revision-1 canonical sidecar product.

### Supported-workflow isolation

A compile-time role cannot prevent an arbitrary source editor from compiling a
different program. The enforceable claim is:

- the ordinary installer has no option that enables the role;
- the dedicated installer accepts no fixture path, bytes, hash, durable ID,
  role token, or task override;
- the fixture and every identity derive from reviewed repository source;
- no runtime CLI option, environment variable, environment kwarg, state-bank
  path, or hidden selector changes the fixture;
- the dedicated installer operates only on a caller-designated fresh pinned
  Puffer checkout and fails if it is dirty, unpinned, already role-staged, or
  lacks the exact ordinary install;
- the ordinary install/check path rejects a role-staged tree;
- the role-specific check rejects an ordinary or mutated role tree;
- production launchers reject any module whose fixture role is not `"none"`;
  and
- evidence binds the source, installed snapshot, Puffer commit, ordered
  patches, generated build authority, imported module, configuration, task
  descriptor, and fixture hashes.

Changing shared source necessarily changes source and module bytes. The
ordinary-build claim is behavior preservation and unchanged production
authorization, not binary identity across commits.

## Environment contract

### Reset placement

The dedicated role may replace only match-state selection. It must install the
exact F5 match after the ordinary reset preflight and before the ordinary
post-selection reset baselines. The following path stays shared:

```text
exact fixture copy
  -> in-match RNG seed
  -> bb_advance
  -> legal-action refresh
  -> decision/error/episode counter reset
  -> score baseline
  -> possession baseline
  -> exact-PBRS baseline
  -> injury/surf/send-off baselines
  -> obs-v6 encode
  -> exact joint support
  -> factorized decoder
  -> engine apply
  -> reward ledger
  -> terminal/result handling
  -> log aggregation
  -> autoreset
```

There must be no second observation, mask, decoder, reward, or autoreset
implementation. Every reset must reproduce the exact raw match, first
observation bytes, masks, deciding team, legal list, and packed joint support.
No procgen or state-bank fallback is reachable under the role.

### Exact environment configuration

The role preflight must fail before environment allocation or RNG consumption
unless its environment configuration is the frozen F5 configuration. At
minimum it requires:

- `seed = 1`;
- `macro_moves = 0`;
- `max_decisions = 8`;
- `demo_reset_pct = 0`;
- `state_bank_kind = 0`;
- all selectors `0`;
- all team forcing/exclusion `-1`;
- scripted opponent disabled;
- default, inert procgen controls; and
- the objective-only reward contract below.

The dedicated checked-in config must spell every environment key so omitted
defaults cannot silently change the task in a future Puffer version. Mutation
tests must change every field one at a time and require a precise preallocation
failure. Fields that are genuinely operational only, such as render rate, may
be explicitly classified outside the semantic preflight, but they must still
be recorded in evidence.

The later trainer preflight, not this environment-only tranche, will additionally
require:

- `horizon = 8`;
- recurrent `reset_state = true`;
- self-play disabled;
- zero frozen banks;
- no frozen enemy;
- a two-agent row layout; and
- one environment episode per rollout.

This foundation may exercise an untrained/reference Torch rollout solely to
prove terminal-tail transport. It does not optimize weights.

### Objective-only reward

The F5 reward contract is:

```text
reward_td = 1
reward_win = 0
reward_draw = 0
every shaping, possession, field-position, contact, casualty,
behavioral, and stat-matching coefficient = 0
```

Decisions 1–7 must emit exactly `(0,0)`. Decision 8 must emit exactly
`(+1,-1)`. The terminal result must not add a win coefficient, and no shaped
metric may satisfy task success.

Task success is exactly one completed-episode Home touchdown:

```text
tds_t0 == 1
tds_t1 == 0
episode_length == 8
```

## Implementation slices

### Slice 1 — plan and watched-red tests

Commit this accepted plan before implementation. Then add watched tests which
fail because the repository has no:

- F5 foundation generator/task descriptor;
- complete isolated identity/hash gate;
- compile-time fixture role;
- role-aware strict config;
- fixture identity exports;
- exact eight-decision environment oracle;
- exact safe random enumerator;
- dedicated role installer/checker; or
- production-module rejection of the role.

The watched-red commit must establish that the tests fail for missing
functionality, not syntax or fixture mistakes.

### Slice 2 — deterministic task generator

Add a narrow generator that:

- transiently builds and identity-reconciles the complete authored bundle;
- generates the complete-bundle and extracted one-record BBS twice;
- validates exact bytes, hashes, ABI, capture facts, and raw match;
- derives the canonical reference route from real reachability and reconciles
  it with the frozen tuple trace;
- emits the exact compiled fixture/header and closed task descriptor
  atomically; and
- supports strict independent verify mode.

Generation must reject null/overlapping output, partial writes, trailing bytes,
unknown/extra descriptor keys, wrong ordering, mutation of any identity,
different recipe/transcript, wrong ruleset/fingerprint, mixed records, and
nondeterministic regeneration.

### Slice 3 — isolated reset role and exact config

Add the default-off role and one reset-selection hook. The ordinary role uses
the existing procgen/state-bank logic. The F5 role copies the exact reviewed
fixture and cannot reach procgen or a state bank.

Add one qualification config preflight after the ordinary strict parser. It
must reject every semantic mutation before allocation/RNG use and preserve the
ordinary strict-config error behavior when the role is absent.

### Slice 4 — transport and baseline oracles

Add a real environment oracle that:

- checks Home is the deciding team on all eight steps;
- checks the selected tuple against each conditional exact-support slice;
- checks Away has exactly the null singleton;
- decodes to the expected engine action without fallback/collision;
- captures observation, mask, support, reward, terminal, and state hashes;
- proves zero unexpected TEST decisions and zero dice;
- proves zero reward, TD, and terminal on decisions 1–7;
- proves `(+1,-1)`, both terminals, one Home TD, and length eight on decision
  8; and
- proves immediate autoreset to the exact first fixture/observation/support.

The random baseline must distinguish exact evidence from descriptive sampling:

- exactly enumerate the safe zero-dice scoring subset and its probability;
- run a bounded, fixed-seed masked-uniform sample;
- report its episode count and zero or observed successes without treating an
  observed success as required; and
- never substitute the reference action when random output fails.

The canonical transcript is a transport/control oracle only. No training API
may consume it.

### Slice 5 — fresh Puffer role build and foundation evidence

Add a dedicated role installer/checker which begins from a clean ordinary
install at pinned Puffer commit
`9836f0d2e78889c1aaf189c04d161b6fc61a9386`.

The ordinary module exports role `"none"`. The dedicated module exports the
exact role and task identities while retaining state-bank kind NONE. Both CPU
and native binding sources receive the same immutable exports. Source tests
must catch one-sided binding changes.

The fresh-build validation must:

1. install and check the ordinary no-bank module;
2. prove ordinary authored/state-bank rejection remains unchanged;
3. stage the dedicated role with no caller-controlled fixture inputs;
4. build and import it in a fresh process;
5. run exact reset/reference/random/terminal-tail diagnostics;
6. prove ordinary checks and production launchers reject it; and
7. emit one atomic foundation evidence artifact.

The evidence schema binds:

- clean repository commit/tree;
- pinned Puffer commit and dirty status;
- ordered patch/source closure;
- environment/install/generated-authority/module hashes;
- observation/action/config/rollout/entropy contracts;
- complete bundle, extracted BBS, raw match, task descriptor, and reference
  trace identities;
- exact config/reward identity;
- every reference transition row;
- exact safe probability and bounded random sample;
- episode/decision/TD/reward/terminal/reset counts;
- illegal/collision/dice/early-terminal/hard-integrity counters; and
- local platform/compiler/Python/Torch identities.

An independent verifier reparses the closed schema, rehashes every local
artifact, recomputes all integer/rational gates, and writes the final foundation
verdict atomically and last. A worker-authored `passed` field is not
authoritative.

## Test-first commands and evidence

The exact command names may be refined during implementation, but the stable
surface should remain narrow:

```bash
make build/f5_trainability_foundation \
     build/puffer_f5_trainability_tests

build/f5_trainability_foundation generate \
  --output build/f5-trainability/foundation

build/f5_trainability_foundation verify \
  --input build/f5-trainability/foundation

build/puffer_f5_trainability_tests

python3 -m unittest -v \
  tools.test_f5_trainability_foundation \
  training.test_f5_trainability_role

python3 -B -I -S tools/run_f5_trainability_foundation.py \
  --artifact-dir build/f5-trainability/evidence \
  --random-episodes 100000

python3 -B -I -S tools/verify_f5_trainability_foundation.py \
  build/f5-trainability/evidence

make test
ASAN_OPTIONS=detect_leaks=0 make asan
git diff --check
```

Fresh exact-install validation uses a new isolated Puffer checkout and a newly
prepared CPython 3.12 venv. The outer verifier independently reconstructs the
ordinary Puffer source checkout and native build from the pinned commit, while
sharing that lifecycle's sealed prepared venv as an explicit trusted dependency
layer. It does not rely on or mutate a pre-existing repository vendor tree.

The prepared venv is closed against automatic Python startup injection: its
directory chain and `pyvenv.cfg` are sealed, default editable/distutils hooks
are removed, venv customization modules are rejected, and one exact two-line
bootstrap/path hook is admitted. Its executable line preloads a sentinel for
`sitecustomize` before its path line admits the pinned Puffer root. A real
`-B -I` startup probe must then prove that the sentinel remains installed,
user-site loading is disabled, the Puffer root and venv site-packages each
occur exactly once, and every other `sys.path` entry remains under the trusted
base stdlib. The foundation runner and verifier themselves, and every
installer-owned base-interpreter probe, run with `-B -I -S`.

Installed dependency distribution names and versions are snapshotted, but
wheel origin, `RECORD`/file bytes, and loose installed package bytes are not
independently reconstructed or hash-pinned. Those package bytes, the base
CPython executable, and its standard-library bytes remain a trusted external
input to both the worker and independent ordinary-source replay; execution of
the base installation's `sitecustomize.py` is explicitly blocked.
Accordingly, "independent" here means independent source checkout, patching,
native build, ordinary module import, and module/authority hash binding over
that declared prepared-toolchain layer—not independent dependency/toolchain
supply-chain reproduction.

### Required negative coverage

At minimum:

- full-bundle count 25/27, missing/duplicate F5, wrong family composition;
- A9/AE/template/revision/cell/variant/seed/action/dice mutation;
- raw match, one-record BBS, complete BBS, ABI, ruleset, and trace mutation;
- absent/truncated/trailing/extra-key/noncanonical task artifacts;
- ordinary module role activation attempts;
- role installer fixture/path/hash/ID/role override attempts;
- dirty/unpinned/wrong Puffer and already-staged destination;
- normal checker against role module and role checker against normal module;
- every semantic environment-config mutation;
- `macro_moves=1`;
- `max_decisions=7/9`;
- nonzero bank/demo/selector/scripted/forcing controls;
- any non-objective reward coefficient or win/draw coefficient;
- wrong player, wrong declaration, altered square, incomplete path, extra
  action, unexpected dice, early terminal, nonzero prefix reward;
- nondeciding support other than null singleton;
- decoder tuple outside exact support or projection collision;
- missing eighth terminal/reward/TD/log row;
- autoreset mismatch;
- worker/evidence/verdict hash or count mutation; and
- production launcher given the role module.

## Implementation result

The accepted foundation was implemented test-first on
`tranche/f5-trainability-foundation`. The resulting qualification role remains
compile-time-only, retains state-bank kind NONE, accepts no caller-selected
fixture input, and is rejected by the ordinary installer and both production
reward launchers.

Local qualification established:

- byte-identical regeneration and verification of the 26-record proof bundle,
  extracted F5 BBS, raw match, generated fixture header, task descriptor, and
  eight-action trace at all watched hashes;
- exact reference execution through the real support/decoder/`c_step` path:
  zero dice, reward, touchdown, or terminal on decisions 1–7; Home touchdown,
  `(+1,-1)`, dual terminal, and episode length eight on decision 8; then exact
  autoreset;
- real-environment negative routes for wrong player, wrong declaration,
  altered square, seven-action truncation, and the putative ninth action, plus
  the closed config/artifact/evidence mutation matrices;
- exact enumeration of 721 safe zero-dice scoring trajectories with probability
  `4567 / 9227468800`, and the frozen seed-245 100,000-episode masked-uniform
  baseline with zero successes, 472,158 dice, and 11,396 TEST windows;
- recurrent Torch CPU collector-tail closure with eight environment steps,
  nine policy forwards, exact terminal bootstrap, recurrent-state reset, and
  no ninth environment action;
- a new pinned Puffer checkout and newly prepared CPython 3.12 venv completing
  the 14-step pristine → ordinary CPU/standalone → dedicated F5 CPU lifecycle;
  its starting Git status was empty;
- live startup closure on the affected Homebrew host: ordinary `-B -I`
  startup retained only base-stdlib paths, the exact venv site-packages path,
  and the exact pinned Puffer root, while `sitecustomize is sys` proved the
  base customization module never executed;
- 53 focused Python contract tests, the full native `make test` suite,
  `ASAN_OPTIONS=detect_leaks=0 make asan`, relevant Ruff checks, shell syntax
  checks, patch apply/reverse checks, and `git diff --check`; and
- independent adversarial post-review with no unresolved P0, P1, or P2
  findings after the startup-boundary fix.

The fresh development evidence intentionally records the repository as dirty,
so the strict verifier rejects it rather than conferring authority. After this
implementation commit, the runner must produce evidence from the clean tree
and the verifier must independently reconstruct the ordinary source/build,
bind its module, authority, and exact Git status, and publish the verdict.

## Validation boundary

This tranche can establish on local macOS/ARM and a fresh CPU Puffer build:

- deterministic task construction and identity;
- compile-time role isolation;
- strict configuration;
- exact environment transport;
- observation/mask/decoder/reward/terminal/autoreset behavior;
- Torch CPU terminal-tail transport without optimization;
- exact and sampled random baselines;
- evidence/verdict integrity; and
- behavior preservation of ordinary builds.

It cannot establish:

- PPO learnability;
- a 95% success threshold;
- exact-pin hosted x86 acceptance unless that job is actually run;
- schema-11 target-NVIDIA rollout/entropy acceptance;
- Torch CUDA, native eager, or native graph learning;
- production state-bank or launcher authority; or
- transfer/generalization.

The existing exact-pin x86 and target-NVIDIA schema-11 rollout/entropy gates
remain mandatory before an F5 PPO result can become admissible. Local CPU
foundation evidence cannot bypass those gates.

## Exit gates

The tranche is complete only when all are true:

1. Two independent complete-bundle, extracted-BBS, task, and fixture
   generations are byte-identical.
2. Every complete expected size/hash/ABI/identity matches.
3. Durable identity is exactly `0xAE00001A`, obtained through complete-bundle
   reconciliation.
4. Ordinary builds export fixture role `"none"` and retain every production
   state-bank rejection.
5. The qualification build exports the exact role and hashes while reporting
   state-bank kind NONE and accepting no bank/demo input.
6. No supported runtime argument, environment variable, bank override, or
   ordinary installer option enables or alters the fixture.
7. Production launchers reject the qualification module.
8. Every qualification reset reproduces the exact reviewed raw state,
   observation, masks, legal actions, and joint support.
9. All eight reference tuples pass the real conditional mask and decoder.
10. Away support is exactly the null singleton at all eight decisions.
11. Decisions 1–7 have no touchdown, terminal, game die, unexpected TEST, or
    nonzero reward.
12. Decision 8 emits exactly one Home touchdown, rewards `(+1,-1)`, both
    terminals, episode length eight, and immediate exact autoreset.
13. `tds_t0 == completed episodes`, `tds_t1 == 0`, and every illegal,
    collision, early-terminal, nonfinite, and hard-integrity counter is zero.
14. The eighth reward/terminal is present in the captured recurrent rollout
    tail and terminal bootstrap is zero; no ninth environment action occurs.
15. Exact safe baseline enumeration and the bounded random sample reproduce
    under fixed seeds.
16. A fresh pinned Puffer install builds, imports, runs, and independently
    verifies in a new process.
17. Focused tests, complete project tests, sanitizers, and `git diff --check`
    pass.
18. Self-review and independent adversarial post-review have no unresolved
    P0/P1 findings.

## Risks and controls

### Qualification code reaches production

Control: default role `"none"`, no ordinary installer/runtime enablement,
separate checker, production launcher rejection, module/evidence role binding,
and behavior-locking ordinary-path tests.

### Fixture resembles a production bank

Control: bank kind NONE, demo reset zero, no state-bank authorization changes,
qualification-only task schema, and explicit prohibition on treating the BBS
oracle as a canonical sidecar or training bank.

### The task terminates early

Control: exact eight-action oracle, `macro_moves=0`, max decisions eight,
prefix terminal assertions, completed-episode length, autoreset identity, and
rollout-tail capture.

### Success is inferred from reward

Control: success is the exact Home TD log with episode denominator; reward is
cross-checked, not substituted.

### Reference labels leak into a learner

Control: foundation has no optimizer/training mode. The reference transcript
is accessible only to generator/oracle surfaces and must not be imported by
the later training worker.

### Random baseline is misinterpreted

Control: exact safe-subset probability is distinguished from an empirical
sample and from total success probability. A zero sampled TD is expected and
is never a required promotion result.

### Two-agent bookkeeping is called one agent

Control: evidence reports matches, environment decisions, Home meaningful
rows, Away null rows, and Puffer agent-steps separately.

### Evidence overstates platform acceptance

Control: foundation verdict names local platform/backend explicitly and carries
the pending x86/NVIDIA gates without launcher changes.

## Explicitly out of scope

- PPO rollouts that update weights;
- calibration or hyperparameter search;
- a three-seed or 95% learning gate;
- behavior cloning, demonstrations, action forcing, or reference warm start;
- PBRS/distance shaping or reward experimentation;
- production authored producer authorization;
- forward-porting PR44;
- canonical 26-record sidecar serialization;
- manifest-last production publication;
- runtime state-bank authored admission;
- randomized or held-out F5 geometries;
- pickup, protect, advance, sack/stop, or pass tasks;
- general scenario success log fields or early scenario terminals;
- recurrent segmentation across multiple/early episodes per horizon;
- league, opponent, paired-side promotion, or checkpoint admission;
- GPU provisioning or external spend;
- PR creation, push, merge, deployment, or production launcher release.
