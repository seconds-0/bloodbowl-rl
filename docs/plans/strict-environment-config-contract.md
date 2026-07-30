# Strict Blood Bowl environment configuration contract

Status: implemented and CPU/Puffer validated; mandatory real-NVIDIA gate
pending

External-gate status: the real-NVIDIA CUDA constructor-stage artifact is
mandatory and has not been completed on this local CPU-only validation host.

Base: `96f36e4`

Approved design SHA-256:
`9e9c936b2afbd44c7f99ede0080c94ec880c3014e6526b04b52999c6aba27f2e`

Independent native and pinned-Puffer integration reviewers each reported zero
open P0/P1/P2 findings for that exact 837-line design. This administrative
approval record is not a substantive change to the reviewed design.

## Objective

Make every Blood Bowl environment kwarg a typed, closed-domain input that is
validated from its original Python/Puffer numeric value before any narrowing
conversion, state-bank I/O, `Bloodbowl` array allocation, engine reset, or
worker startup.

The valid default configuration must remain behaviorally identical. Invalid
values must stop construction with one field-specific diagnostic; they must
never truncate, wrap, underflow to an inactive setting, fall back to a default,
silently disappear at the Python/C++ boundary, or reach an engine array index.

This closes the remaining P0 configuration-hygiene item from
`docs/pufferlib-environment-comparison-2026-07-25.md`.

## Confirmed current gap

`puffer/bloodbowl/binding.c` reads 51 environment keys as `double`, but only
the typed state-bank subset and the post-conversion reward coefficients have a
coherent validator.

The remaining paths include:

- `force_home_team`, `force_away_team`, and `exclude_team` are converted to
  `int` without a general `-1 | [0, BB_TEAM_COUNT)` check. An invalid forced
  team can reach `bb_team_defs[team_id]`.
- `scripted_opponent_team` is documented and consumed as the enum
  `HOME=0`, `AWAY=1`, `BOTH=2`, but the binding silently rewrites `2` and every
  other out-of-range value to `AWAY=1`.
- `scripted_opponent_type` silently rewrites invalid values to zero.
- `max_decisions` silently rewrites nonpositive and above-bound values to
  `BBE_MAX_DECISIONS`.
- 13 integer-like fields are narrowed before domain validation. Depending on
  the destination, fractions truncate, arbitrary nonzero integers act as true,
  and nonfinite/out-of-range conversion is undefined C behavior.
- procgen advancement fields accept negative, fractional, nonfinite, and
  out-of-range values before entering loop and random-range arithmetic.
- `seed` is converted from `double` to `uint64_t` without first proving a
  finite, nonnegative, exactly representable integer.
- reward validation occurs after `double -> float` conversion and omits
  `reward_dist_pbrs_gamma`; NaN gamma can select legacy behavior rather than
  failing.
- negative `reward_dist_pbrs_gamma` selects legacy behavior and negative
  `reward_statmatch_scale` becomes inert even though both look like active,
  valid coefficients under the current generic `[-1,1]` check.
- the generic CPU/CUDA Python bindings catch a nonnumeric environment value's
  cast error and silently omit that key, causing the Blood Bowl binding to use
  its default. Puffer's inferred INI typing makes `seed = nan` one concrete
  form: it becomes a string and disappears, while a float CLI override such
  as `--env.reward-td nan` reaches C as actual NaN.
- unknown numeric environment keys are ignored, so a misspelled override can
  produce a plausible run with the default task.

The bank validator also checks team sentinels only when a banked reset is
active. That protects the bank contract, not ordinary procgen construction.

## Scope

In scope:

- one authoritative schema for all 51 keys currently consumed by
  `binding.c`;
- exact domains, defaults, field names, and deterministic diagnostics;
- materializing one canonical raw config per environment callback from
  untouched `double` values, with no per-environment dictionary rereads;
- raw type/domain validation before any field is cast or any state bank is
  opened;
- removal of every silent clamp/default-on-invalid path;
- `scripted_opponent_team=2` support through the existing BOTH runtime path;
- strict malformed/unknown-key and nonnumeric-value rejection for a Blood
  Bowl module;
- a focused exact-pinned CPU/CUDA Puffer patch for the nonnumeric boundary;
- constructor preflight in CPU `create_vec`, CUDA `create_vec`, and native
  CUDA `create_pufferl` before vector/model/runtime allocation;
- preservation of intentional sparse dictionaries: an absent known key still
  receives its declared default;
- pure native tests, binding/source contract tests, and real CPU-module
  subprocess tests;
- a Linux clean-pinned-Puffer CPU build/construction CI job;
- a negative strict-config construction cell in recurrent CUDA qualification;
- configuration documentation and the corrected comparison-document spelling
  `scripted_opponent_team=2`;
- environment/backend identity updates caused by the actual source closure;
  and
- optimized, sanitizer, deterministic, clean-install, CPU-module, and
  standalone validation.

Out of scope:

- changing any valid default;
- changing reward values, reward equations, observation/action bytes,
  terminals, model architecture, or checkpoint format;
- adding new teams, scripted bots, procgen features, or curriculum selectors;
- changing Puffer trainer hyperparameter validation outside the environment
  dictionary;
- claiming generic constructor-time equality between
  `reward_dist_pbrs_gamma` and `train.gamma`; the primary launcher retains its
  existing equality gate, while this tranche enforces env-local `[0,1]`;
- accepting arbitrary strings or path-valued Blood Bowl environment kwargs;
- changing fixed/frozen league side routing or promotion evaluation;
- implementing the learning-level capability harness;
- launching training or mutating an active run; and
- widening production state-bank producer authorization.

## Canonical schema

The schema literal is `bloodbowl-environment-config-v1`.

The implementation owns one raw `bbe_environment_config` value. It contains
the exact doubles transported from one immutable Python snapshot, including
one embedded `bbe_state_bank_config_values`. Construction follows this order
exactly:

1. While holding the GIL, accept only exact built-in Python `bool`, `int`, and
   `float` values and exact built-in `str` keys. Reject subclasses, custom
   numeric protocols, non-string keys, embedded-NUL/control keys, malformed
   keys, and integers outside the exact double-integer transport range.
2. Before allocating or iterating a snapshot, prove
   `0 <= len(env_kwargs) <= 51`; 52 entries necessarily contain an unknown
   key because Python dictionaries are unique-key maps. Only after this proof
   may `Py_ssize_t` narrow to the C `int` capacity.
3. Capture every key/value exactly once into a new owned Python dictionary
   containing only inert built-in `str` keys and `float` values. Catch
   `OverflowError`, `py::error_already_set`, and all conversion failures and
   translate them into the same bounded, key-specific `ValueError`. No
   user-defined `__float__`, mapping hook, or mutable source object is
   evaluated again.
4. Convert that normalized snapshot to a temporary C `Dict`, call the
   exported native preflight, and free the temporary dictionary on every
   success/error path. Reject unknown keys and invalid raw/cross-field values.
5. Replace the constructor-local `env_kwargs` with the owned normalized
   snapshot so the existing later converter consumes exactly the values that
   passed preflight.
6. At the first line of each direct environment callback, reject NULL or
   structurally incoherent `Dict` storage and require
   `0 <= size <= capacity`, `size <= 51`, and non-NULL items when size is
   positive. In a structural first pass, require
   `items[i].key != NULL` for every occupied slot before any key reaches
   `strcmp`, `strnlen`, escaping, or diagnostic formatting. Then repeat the
   native dictionary preflight so unknown, duplicate, and invalid values fail
   even when Puffer's Python constructors are bypassed.
7. In the environment callback, read every known key once into the canonical
   raw value, applying a default only when the key is absent.
8. Validate every field's raw type/domain with the same pure validator and no
   casts or side effects.
9. Only after all raw domains pass, narrow into a local scratch applied config
   and run the current reward/state-bank cross-field and envelope semantics on
   the exact float/int values that the environment would receive. This second
   pure phase performs no I/O, allocation, engine call, or mutation.
10. Resolve and require the typed state bank, if requested.
11. In `my_vec_init`, allocate the environment array only now and fail closed
    if allocation returns NULL. In `my_init`, the caller already owns the
    destination.
12. Copy the already-proven scratch values into each `Bloodbowl`, assign the
    validated per-environment seeds, and return.
13. Permit worker and engine startup.

The schema cardinality is 51; a valid supplied dictionary contains any
cardinality from 0 through 51 because absent known keys receive defaults. The
env-only Python normalizer proves that bound before allocating/converting,
captures and validates each supplied entry once, retains its immutable-value
Python snapshot, and frees only its temporary C `Dict`. A source dictionary
above 51 receives the bounded cardinality diagnostic without iteration; it
necessarily contains an unknown key but cannot force an unbounded
key-by-key diagnostic or a narrowed C capacity. The unchanged downstream
converter scans only the bounded normalized snapshot to construct the callback
`Dict`.
`my_vec_init` then constructs one canonical value for the whole vector and
applies it to each environment without rereading that `Dict` per environment.
`my_init` uses the same parser and validator. These bounded
defense-in-depth rescans avoid an unsafe process-global config cache, preserve
the earlier exact patch's reverse applicability, and keep the three
construction paths on one rule set.

Constructor-order tests use one named special-build seam,
`PUFFER_STRICT_ENV_CONFIG_TESTING`, not source-text ordering alone. In that
non-production build:

- both `create_vec` paths record immediately before their
  `create_static_vec` handoff;
- `create_pufferl` records immediately before constructor-owned
  `cudaGetDeviceCount` and immediately before `create_pufferl_impl`;
- the normalizer records whether `PyGILState_Check()` is true before any
  translation or Python exception;
- a test-only read/reset API exposes only these stage counters; and
- native Blood Bowl tests separately instrument the environment allocator,
  state-bank require seam, and `bb_match_init_*` seam.

Representative malformed, unknown, and invalid-domain inputs must leave every
downstream counter at zero. A zero `create_pufferl_impl` count proves its
model, stream, worker, warmup, and reset code was never entered. This special
build supplements rather than replaces rejection tests against the exact
production CPU module and exact production CUDA qualification module.

The checked-in `tools/qualify_recurrent_cuda.py strict-stage-order` command
owns this special-build proof. It accepts only a pristine disposable Puffer
checkout outside this repository, detached at
`9836f0d2e78889c1aaf189c04d161b6fc61a9386`, with no prior build, installed
Blood Bowl tree, or native module and with a checkout-local venv. It writes
an atomic bounded isolation receipt before running the installer. The venv
directory must be real rather than symlinked. A pre-build probe binds the
lexical executable, executable bytes, `sys.prefix`, pybind11/NumPy origins,
Python version, and extension suffix. One sanitized environment with that
venv first in `PATH` and exact `VIRTUAL_ENV` removes ambient Python controls,
Bash startup files/options/exported functions, and dynamic-loader injection
variables. Direct and noninteractive-Bash probes must resolve the same
recorded Python identity. That environment then drives the absolute-Bash
installer, CUDA build, and worker. The selected absolute interpreter is also
passed as `PUFFER_INSTALL_PYTHON`, and every installer Python call uses that
single quoted command rather than ambient `python3`. It builds only that
checkout with `PUFFER_STRICT_ENV_CONFIG_TESTING=1` and invokes a hidden worker
under the same isolated interpreter. Neither this command nor its output may
target the production vendored checkout.

The worker exercises both CUDA entry points with
`force_home_team=BB_TEAM_COUNT` crossed with malformed/dangerous `vec`,
`train`, `policy`, and device inputs. Each case requires exactly one
normalizer call, exactly one GIL-held observation, and zero
`create_static_vec`, `cudaGetDeviceCount`, and `create_pufferl_impl` calls.
Valid controls require `create_vec` to reach `create_static_vec` exactly once
and `create_pufferl` to reach both CUDA device discovery and its implementation
handoff exactly once; both results must close safely. The worker then requires
all counters to be zero after cleanup.

The resulting bounded `STRICT_STAGE_ORDER.json` records the CUDA runtime
fingerprint; module, environment, backend-source, Puffer-commit, qualifier,
source-ledger, and strict-patch identities; the full negative matrix; both
positive controls; and proof that the production identity validator rejects
the test-role module. CPU fake-backend tests lock the counter semantics and
failure detection, and a mechanical source test requires the CPU and CUDA
normalizer/preflight bodies in the patch to be byte-identical. Those CPU
checks are supporting evidence only: dynamic execution of the actual CUDA
entry points on real NVIDIA hardware remains a mandatory external release
gate and is not represented as locally complete.

The retained receipt and final artifact must each be an ordinary nonsymlink
file no larger than 64 KiB. Revalidation requires exact nested keys, exact
JSON scalar types, bounded strings and paths, the closed
hazard-to-malformed-path mapping, `invalid_team` equal to the installed
generated `BB_TEAM_COUNT`, and the recorded interpreter, dependency, module,
source, ledger, patch, and extension-suffix identities.

Both bindings always export the exact boolean build-role attribute
`strict_env_config_testing`. It is `true` only when the named special-build
macro is compiled and `false` otherwise. Stage tests require `true`.
Installer `--check`, clean CPU production integration, recurrent production
qualification, reward-screen/ablation compiled probes, and newly minted run
metadata require `false`; a test-role module must be rejected even when all
source/environment/schema hashes match. Special builds use a throwaway clone
or distinct output tree and may never overwrite the production module being
qualified. A regression feeds a test-role module to every production identity
gate and requires rejection.

The exported preflight executes both pure phases, so an invalid cross-field
combination or applied-float envelope also becomes a constructor-time Python
error. The existing float-level reward validator and reset-time state-bank
validator remain defense-in-depth for direct native callers and
post-construction corruption. They are not substitutes for raw input
validation. The float-level validator gains a missing nonfinite-gamma check,
but direct-C lineage tests may retain the historical negative-gamma `<=0`
branch; only the public raw-configuration boundary makes negative gamma
invalid.

### Closed domains

| Fields | Raw domain |
|---|---|
| `seed` | exact integer `0..2^53-1`, the exact-integer domain transported by IEEE-754 double |
| 29 ordinary reward coefficients | finite `[-1, 1]`; a nonzero double may not narrow to float zero |
| `reward_dist_pbrs_gamma` | finite `[0, 1]`; zero means legacy, positive means exact PBRS, and nonzero may not narrow to float zero |
| `reward_statmatch_scale` | finite `[0, 1]`; zero means inactive, positive retains historical reproduction behavior, and nonzero may not narrow to float zero |
| `reward_injury_value_scaled` | exact boolean `0` or `1` |
| `demo_reset_pct` | existing finite `[0, 1]` rule and nonzero-float-underflow rejection |
| `state_bank_kind` | existing exact enum `NONE=0`, `STRICT=1`, `AUTHORED=2`, with authored still production-disabled |
| four selector fields | existing exact family-specific closed bounds and mutual exclusion |
| `exclude_team`, `force_home_team`, `force_away_team` | exact integer `-1` or `0..BB_TEAM_COUNT-1` |
| `skillup_max_players` | exact integer `0..BB_TEAM_SLOTS` |
| `skillup_max_each` | exact integer `0..12`, matching authored/procgen identity validation |
| `skillup_secondary_pct` | finite `[0, 1]`; nonzero may not narrow to float zero |
| `macro_moves` | exact boolean `0` or `1` |
| `scripted_opponent` | exact boolean `0` or `1` |
| `scripted_opponent_team` | exact enum `HOME=0`, `AWAY=1`, `BOTH=2` |
| `scripted_opponent_type` | exact enum `CONTACT=0`, `CAGE_ADVANCE=1` |
| `max_decisions` | exact integer `1..BBE_MAX_DECISIONS` |
| `render_fps` | exact integer `1..INT_MAX` |

The 29 ordinary coefficients are every `reward_*` float except
`reward_dist_pbrs_gamma` and `reward_statmatch_scale`; the boolean scale flag
is separate. Tests derive these sets from the authoritative ledger and fail
if a new reward field is added without a domain.

### Cross-field rules retained

- all current state-bank kind/reset/selector/compiled-identity rules;
- banked reset remains incompatible with team exclusion/forcing;
- authored state-bank mode remains rejected;
- carrier-threat versus carrier-exposure mutual exclusion;
- carrier-threat versus assist-annuity mutual exclusion;
- exact-PBRS distance coefficients remain nonnegative;
- the reward design envelope remains within the trainer clamp; and
- missing known keys continue to use the current binding defaults; and
- the deliberately sparse recurrent-qualification dictionary containing only
  `seed` and `max_decisions` continues to construct successfully.

The native gamma and statmatch rules are tightened from generic `[-1,1]` to
`[0,1]`. `tools/reward_manifest.py` must use the same gamma domain so
launcher-side and native validation cannot disagree; its existing production
rule continues to require statmatch exactly zero. These are public raw-input
rules, not removal of the engine's internal historical reproduction branches.

No new rule forbids a forced side from matching `exclude_team`: the engine
intentionally applies exclusion only to random sides, which permits held-out
evaluation with one forced held-out roster.

## Authoritative ledger and drift prevention

One checked-in ledger must enumerate, exactly once:

- key;
- raw struct field;
- default;
- domain category; and
- applied destination.

The ledger owns the INI's canonical decimal raw defaults. Historical C
fallbacks such as a `0.4f` macro promoted to `double` need not be bit-equal to
the parsed decimal double `0.4`; the contract asserts that both safely narrow
to the identical destination float and produce identical default behavior.
No test incorrectly requires one raw double to equal both representations.

The implementation may use X-macros or a comparably mechanical table, but it
must not maintain unrelated hand-written key/default lists in parsing,
validation, application, tests, and documentation.

Contract tests reconcile:

- 51 unique ledger keys;
- 51 unique `puffer/config/bloodbowl.ini` `[env]` keys;
- every binding-consumed key;
- every raw struct destination;
- every applied `Bloodbowl` destination; and
- the literal defaults.

Adding, removing, or renaming a kwarg without updating its type/domain must
fail tests.

## Failure interface

The pure validator returns a stable enum plus the offending field. Python
CPU/CUDA constructors translate it into a key-specific `ValueError` before
releasing the GIL or allocating runtime state. Direct C/static callbacks,
whose ABI has no error return, print one line in this form and exit before
Blood Bowl stateful construction; generic caller-owned `StaticVec` storage may
already exist when a callback is invoked:

```text
bloodbowl: invalid environment configuration: FIELD must be DOMAIN; got VALUE
```

At the Python boundary, unknown, malformed, and nonnumeric entries whose keys
fit the maximum identify their exact escaped UTF-8 bytes; Python dictionaries
cannot represent duplicate entries. Over-limit keys report a bounded escaped
prefix plus the total UTF-8 byte length; diagnostics never interpolate an
unbounded Python repr. A Unicode value that cannot be encoded by
`PyUnicode_AsUTF8AndSize` (including a lone surrogate) is converted into the
same stable key error while the pending Python exception is consumed, never
passed as a NULL pointer to `dict_set`. Type errors use only a bounded, escaped
type name. Numeric subclasses/custom `__float__` objects, conversion
exceptions, and Python integers too large for the exact double transport are
type/transport errors; the normalized snapshot never reenters them.

A native `DictItem` exposes only a NUL-terminated `const char*` and a numeric
`double`. Direct-C diagnostics therefore cover exactly the representable
NUL-terminated numeric key/value entry; they cannot promise to recover an
embedded suffix or a nonnumeric Python object that the ABI does not carry.
All diagnostics are newline-safe and deterministic for finite values, NaN,
and infinities. Tests assert the stable field/domain portion rather than
platform-specific floating formatting.

Invalid input must never:

- invoke `bbe_state_bank_require_or_abort`;
- call `bb_match_init_*`;
- allocate the environment array;
- start an OpenMP worker;
- be rewritten to a default;
- be reported only after another unrelated failure; or
- depend on debug-only `assert`.

## Puffer boundary

Both `src/bindings.cu` and `src/bindings_cpu.cpp` currently use one
`py_dict_to_c_dict` helper for both `[vec]` and `[env]`, assume string keys,
lose the Python key length at `PyUnicode_AsUTF8`, and ignore
`py::cast_error`. A focused exact-pinned patch will:

- detect the Blood Bowl binding's strict-numeric marker at build time;
- apply the marker to CPU and CUDA compilation;
- require exact string keys with no embedded NUL or control characters;
- require a nonempty ASCII identifier matching `[a-z0-9_]+` and at most
  `BBE_ENV_KEY_MAX=63` bytes before conversion (all 51 known keys are at most
  28 bytes);
- reject a nonnumeric `args["env"]` value with its key instead of dropping it;
- implement this as a separately named, guarded
  `bloodbowl_normalize_and_preflight_env(py::dict) -> py::dict` path used only
  for `args["env"]`; it must return the owned inert snapshot, not merely
  inspect and discard a temporary conversion, and must not change the shared
  converter's signature or legacy behavior for `[vec]` or marker-absent
  environments;
- declare the guarded native preflight symbol from `binding.c`;
- call it from CPU `create_vec`, CUDA `create_vec`, and native CUDA
  `create_pufferl` before `create_static_vec`, model allocation, stream
  creation, worker creation, or reset;
- raise a Python exception from a returned validation error rather than
  terminating the interpreter;
- leave other Puffer environments' string-valued dictionaries unchanged;
- leave Blood Bowl `[vec]` conversion unchanged, including its existing
  treatment of unrelated nonnumeric metadata;
- preserve sparse known-key defaults; and
- be applied/reverse-verified by `install_puffer_env.sh`.

The three constructor orders are explicit:

- CPU and CUDA `create_vec` first acquire/type-check `args["vec"]` and
  `args["env"]` as dictionaries; while the GIL is still held, they normalize
  and preflight env and replace local `env_kwargs`; only then may they call
  `get_config` or cast `total_agents`/`num_buffers`, convert `[vec]`, convert
  the normalized `[env]`, allocate the wrapper, release the GIL, or call
  `create_static_vec`.
- CUDA `create_pufferl` acquires/type-checks env/vec, then normalizes and
  preflights env before reading train/policy hypers, discovering a device, or
  constructing any backend state. Its later
  `py_dict_to_c_dict(env_kwargs)` line remains byte-identical but consumes the
  replacement snapshot.

A mixed-invalid constructor test pairs an invalid env field with a dangerous
or failing numeric `[vec]` field and requires the env diagnostic first. This
ordering rule does not claim that `[vec]` is safe; it prevents its unrelated
failure from masking the strict env contract.

The strict patch's installed effects in `build.sh`, `src/bindings_cpu.cpp`,
and `src/bindings.cu` fall inside the exact backend source digest closure. The
repository patch artifact itself does not; it is independently covered by the
strict-patch-inclusive bundle digests in both launchers. The installer must
prove the marker and both backend branches are present after a clean install.

The strict patch is applied last among patches that overlap `build.sh`,
`src/bindings_cpu.cpp`, or `src/bindings.cu`, and is generated against the
fully patched pinned tree. Its `create_pufferl` call and local normalized-dict
assignment are inserted near initial `env_kwargs` acquisition, before
hypers/device work and outside the hunk owned by
`puffer_recurrent_cuda_qualification.patch`; the existing later
`py_dict_to_c_dict(env_kwargs)` line remains byte-identical. The helper owns
and frees one temporary validated C `Dict`, while the retained normalized
Python snapshot feeds the historical downstream conversion. This bounded
rescan preserves reverse applicability of the earlier qualification patch,
eliminates conversion TOCTOU, and still rejects before `cudaGetDeviceCount`.

The installer must include the strict patch in its
applicable/already-applied state machine, forward-apply it on a clean pin,
verify its exact markers in both binding sources, and prove both the strict
patch and every earlier exact patch reverse-apply from the final installed
state. `tools/run_reward_ablation.sh` and the independent explicit patch list
in `tools/run_reward_screen.sh` must both add the patch in the same ordered
position so bundle hashes cannot disagree. Partial fake-Puffer fixtures in
`training/test_recurrent_cuda_qualification.py` must contain the exact
reachable hunks for `build.sh`, `src/bindings_cpu.cpp`, and
`src/bindings.cu`, rather than bypassing this last patch. Those fixtures assert
strict-marker detection and propagation into both compilation commands,
exactly two guarded helper bodies, exactly three constructor call sites, and
the pre-existing earlier-patch state-machine failure target.

Independent reverse applicability is a release gate. If a strict hunk breaks
an earlier exact patch's reverse check, the hunk/context must be redesigned;
an ordered reverse-unwind is not used to disguise overlapping final state.

One checked-in ordered compiled-backend ledger replaces the independent lists
in `tools/install_puffer_env.sh::exact_backend_hash` and
`tools/qualify_recurrent_cuda.py::BACKEND_SOURCE_FILES`. It includes
`build.sh`, the four deliberately selected Python paths
`pufferlib/pufferl.py`, `pufferlib/selfplay.py`, `pufferlib/sweep.py`, and
`pufferlib/torch_pufferl.py`, and the complete ten-file local quoted-include
closure of the CPU/CUDA extension roots. Its 15 entries contain no duplicates
or unsafe paths, and the manifest reader recursively reconciles native includes
while hashing the same descriptor-read snapshots. The generated
`exact_action_build_hash.h` is the single explicit self-reference exception
and remains independently checked.
This compiled registry is intentionally narrower than the complete Python
import/runtime closure; the separate vendor registry retains that broader
historical role.
Installer, CPU integration, and recurrent qualification compute the same
path-bound digest from it.

The broader launcher `vendor_source_sha256` deliberately includes
`pufferlib/__init__.py`, `pufferlib/models.py`, and `pufferlib/muon.py` as well.
A second canonical ordered vendor-source ledger therefore replaces the two
matching hand-written lists in `tools/run_reward_ablation.sh` and
`tools/run_reward_screen.sh`; this preserves rather than shrinks their
historical 12-path closure. Contract tests distinguish the two ledgers and
reconcile every consumer. Both clean CPU and real-GPU evidence require the
module's compiled backend digest to equal the compiled-backend on-disk digest
and the compiled environment digest to equal the installed snapshot digest.

Both bindings export
`environment_config_schema = "bloodbowl-environment-config-v1"` from the
native schema function. Installer `--check`, CPU construction tests, recurrent
qualification identities, reward-screen/ablation compiled-contract probes,
and immutable run metadata require this exact value. This makes the semantic
contract observable instead of relying on the environment source hash alone.
The same consumers require `strict_env_config_testing == false`; only the
throwaway stage-test identity accepts `true`.

Unknown numeric keys remain visible in `Dict` and are rejected by the native
51-key ledger before state-bank preparation. Duplicate C-Dict keys are also
rejected even though a Python dict cannot create them.

## Seed and construction semantics

The existing seed behavior is preserved:

- `my_vec_init` assigns `base_seed + env_index`;
- `my_init` preserves an already assigned nonzero seed and otherwise applies
  the validated configured seed; and
- default seed remains `1`.

The `2^53-1` input maximum plus the bounded native environment count cannot
approach `UINT64_MAX`, so per-environment addition is defined.

The vector geometry inputs are not part of the 51-key environment schema.
This tranche nevertheless records that Puffer casts `total_agents` and
`num_buffers` independently of the Blood Bowl env preflight. Their broader
generic validation belongs to a separate Puffer-core change. The strict hook
must run before Puffer uses the environment dictionary, but this tranche does
not claim to make malformed `[vec]` geometry safe.

## Watched-red plan

Before production implementation:

1. Extend the existing reward test through the current public helper to show
   that NaN `reward_dist_pbrs_gamma` is accepted.
2. Extend the existing raw state-bank config test to show that invalid
   ordinary-procgen team IDs are accepted when `demo_reset_pct=0`.
3. Add source-contract watches for the existing scripted-team/type and
   max-decision clamp branches, including documented BOTH mode.
4. Add Puffer-boundary watches showing a nonnumeric Blood Bowl value is
   discarded into a default and an embedded-NUL key loses its original length
   in both binding sources.
5. Record actual watched output and exit status.

The watched tests must use interfaces and source behavior present at
`96f36e4`; a compile failure caused only by naming the future validator is not
acceptable red evidence.

Commit the watched tests separately. Production implementation begins only
after adversarial approval of this plan and capture of the expected fail-open
behavior.

### Watched-red evidence

Captured against base `96f36e4` before any production change.

The focused native binaries rebuilt successfully with the repository's
`-Wall -Wextra -Werror` flags. The current reward helper then demonstrated
that it accepts NaN PBRS gamma and does not report the field:

```text
$ ./build/puffer_reward_tests puffer_reward_config_rejects_nonfinite_coefficients
FAIL puffer_reward_config_rejects_nonfinite_coefficients (puffer/bloodbowl/test_reward_send_off.c:1450): !bbe_reward_config_scalars_valid(&f.env, &bad_field)
FAIL puffer_reward_config_rejects_nonfinite_coefficients (puffer/bloodbowl/test_reward_send_off.c:1451): bad_field != NULL
1 tests, 2 failures
exit_status=1
```

The current state-bank raw validator demonstrated that an ordinary-procgen
configuration accepts `force_home_team=BB_TEAM_COUNT` when resets are
inactive:

```text
$ ./build/puffer_state_bank_tests state_bank_procgen_config_rejects_out_of_range_team
FAIL state_bank_procgen_config_rejects_out_of_range_team (puffer/bloodbowl/test_state_bank.c:2648): bbe_state_bank_validate_config_values( &values, BBE_STATE_BANK_STRICT_REPLAY) != BBE_SB_OK
1 tests, 1 failures
exit_status=1
```

The local source contract retained two passing controls (exact 51-key
binding/INI parity and the existing BOTH runtime branch) while demonstrating
all three silent binding clamps:

```text
$ env -u PUFFER_STRICT_TEST_ROOT python3 -m unittest tools.test_strict_environment_config_contract
Ran 5 tests in 0.003s
FAILED (failures=3, skipped=2)
exit_status=1
```

The exact pinned Puffer checkout at
`9836f0d2e78889c1aaf189c04d161b6fc61a9386` additionally demonstrated, in
both `src/bindings_cpu.cpp` and `src/bindings.cu`, that the current converter
does not retain the Python key byte length and has no length-aware strict
environment path:

```text
$ PUFFER_STRICT_TEST_ROOT=/tmp/bbe-puffer-plan.yDOWdD python3 -m unittest tools.test_strict_environment_config_contract
Ran 5 tests in 0.018s
FAILED (failures=7)
exit_status=1
```

These failures use only interfaces and source behavior present at the base.
They do not name a future validator or fail merely because production symbols
have not yet been introduced.

## Native test matrix

### Schema completeness

- exactly 51 unique keys;
- exact equality with `[env]` in `bloodbowl.ini`;
- empty and sparse dictionaries pass and the exact valid 51-key dictionary
  passes;
- a 52-entry Python dictionary fails before `Py_ssize_t -> int` narrowing,
  normalized-snapshot allocation, or temporary C-Dict allocation;
- a caller-owned native Dict with size 52 fails structural/cardinality
  validation before item iteration, environment allocation, bank access, or
  engine work;
- a caller-owned native Dict with one occupied NULL key fails deterministically
  before any `strcmp`/length/diagnostic access, environment allocation, bank
  access, or engine work;
- no ledger field lacks a default, domain, or destination;
- no destination is assigned from a fresh `kw()` call after validation;
- sparse dictionaries apply all historical defaults;
- the exact qualification dictionary `{seed, max_decisions}` is accepted and
  applies defaults for every other known key;
- default raw config narrows to the current default `Bloodbowl` values.

### Every field domain

For each field, table-driven tests cover:

- documented minimum and maximum;
- nearest representable valid values where relevant;
- just below and just above the domain;
- `DBL_MAX`, `-DBL_MAX`, and `nextafter` values immediately outside closed
  floating bounds;
- NaN, positive infinity, and negative infinity;
- positive and negative fractions for integer/enum/boolean fields;
- negative zero where its distinction matters;
- nonzero values that underflow to float zero for float-backed enablement
  fields; and
- values whose cast would otherwise be undefined or implementation-defined.

All failures must return the expected field and domain category without
mutating an output `Bloodbowl`.

### Teams and procgen

- team sentinel `-1`, team zero, and `BB_TEAM_COUNT-1` construct and reset;
- `-2`, `BB_TEAM_COUNT`, fractions, and nonfinite values fail before engine
  initialization;
- every combination of valid forced/random/excluded sides remains accepted;
- procgen min/max values complete deterministic games;
- negative or above-bound advancement counts never reach `pg_pick`;
- secondary probability zero/one boundaries are deterministic.

### Scripted and boolean configuration

- `scripted_opponent_team=0`, `1`, and `2` retain their exact stored value;
- BOTH mode exercises the existing two-sided scripted runtime branch;
- enum values outside the closed domains fail instead of clamping;
- `0.5`, `-1`, `2`, NaN, and infinities fail for every boolean;
- valid zero/one behavior and default action traces remain unchanged.

### Budgets and seed

- `max_decisions=1` terminates at one decision and
  `BBE_MAX_DECISIONS` remains valid;
- zero, negative, above-max, fractional, and nonfinite budgets fail;
- positive render rates retain exact integers and invalid rates fail;
- seeds zero, one, and `2^53-1` are deterministic;
- negative, fractional, nonfinite, and above-exact-double seed values fail;
- vector construction still produces distinct `base_seed + index` streams.

### Rewards

- every ordinary coefficient accepts both endpoints and zero;
- every coefficient rejects nonfinite and magnitude above one;
- gamma accepts zero and valid positive values through one, rejects negative,
  above-one, nonfinite, and underflow-to-zero values;
- statmatch accepts zero and positive historical values through one but
  rejects negative, above-one, nonfinite, and underflow-to-zero values;
- the injury scale flag is exact boolean;
- existing reward cross-field and envelope failures retain their diagnostic;
- manifest and native gamma decisions agree; and
- the default reward trajectory and component ledger are unchanged.

### Failure ordering

With an invalid non-bank field plus:

- a missing required state bank;
- an empty selector stratum;
- an invalid forced team that would index engine data; or
- an injected environment-allocation failure,

the configuration diagnostic must occur first and no later subsystem may be
observed.

The named special-build stage API proves the ordering dynamically: failed
preflight must report exactly one normalization call, exactly one GIL-held
translation, and zero named vector/CUDA/implementation handoffs. Native
seams separately require zero environment-array, state-bank, and engine-init
handoffs. Source-contract assertions are supplementary drift alarms, not the
ordering proof, and the special build cannot substitute for
production-module subprocess evidence.

## Puffer and Python test matrix

- CPU `create_vec`, CUDA `create_vec`, and CUDA `create_pufferl` each reject
  nonstring keys, embedded-NUL or control-containing keys, nonnumeric values,
  unknown numeric keys, and representative native-domain violations before
  their first owned allocation or worker/runtime action;
- empty, over-63-byte, non-ASCII, and bytes outside `[a-z0-9_]` env keys fail
  as malformed with a bounded diagnostic;
- environment dictionary sizes 0 and 51 safely normalize, while size 52 and
  a very large source dictionary raise the stable at-most-51-keys `ValueError`
  before allocating a snapshot or C `Dict`; within-capacity unknown keys still
  name the key;
- a Python key containing a lone surrogate or otherwise failing
  `PyUnicode_AsUTF8AndSize` becomes a clean `ValueError`, with no pending
  interpreter exception or NULL key reaching native code;
- exact built-in bool/int/float values normalize once; numeric subclasses,
  custom or stateful `__float__` objects, a mutator that rewrites its source
  dictionary, conversion exceptions, and Python integer overflow all fail
  before the permissive converter and cannot change a validated value or
  disappear into a default;
- other Puffer environments retain the historical skip behavior for
  string-valued dictionaries;
- a Blood Bowl args tree with all required numeric `[vec]` fields plus an
  unrelated nonnumeric `[vec]` metadata field retains the legacy vec
  conversion path; only `args["env"]` is strict;
- invalid env plus NaN, huge, or otherwise failing `[vec]` geometry reports
  the env field first in both CPU and CUDA `create_vec`;
- unknown and duplicate numeric Blood Bowl keys fail and name the key;
- absent known keys still use native defaults;
- the exact sparse qualification dictionary `{seed, max_decisions}` succeeds
  through all applicable constructors;
- integer, float, bool, NaN, and infinity values survive Python transport only
  when their native domain permits them;
- both an INI-inferred string such as `seed = nan` and a CLI-originated float
  NaN fail explicitly rather than taking different fallback paths;
- direct CPU-module construction is run in a subprocess for every invalid
  class, proving release builds fail before a worker can return;
- valid default and BOTH-scripted CPU-module constructions succeed;
- the recurrent CUDA qualifier contains two expected-negative construction
  subcells, one invoking `_C.create_vec(..., gpu=1)` and one invoking
  `_C.create_pufferl(...)`, each with
  `force_home_team=BB_TEAM_COUNT`. They require the exact field/domain
  `ValueError` before constructor-owned `cudaGetDeviceCount`,
  `create_static_vec`/`create_pufferl_impl`, allocation, model/stream/worker
  construction, warmup, or reset. The qualifier's already-required CUDART
  pre-import fingerprint is an allowed prerequisite, not constructor work;
- the negative-cell worker emits a structured expected-rejection record.
  Success, an ordinary nonzero exit, or an unrelated CUDA error is failed
  evidence. The record is reconciled with the special-build constructor-stage
  contract, while the exact production module supplies the authoritative
  field diagnostic;
- positive full and exact sparse `{seed,max_decisions}` construction,
  reset, and close execute through both CUDA entry points;
- installer application is exact and idempotent, and the new strict-config
  patch plus every existing patch in the final stack reverse-applies from the
  pinned installed tree;
- the throwaway instrumented module reports
  `strict_env_config_testing=true`; the ordinary CPU/CUDA modules report
  `false`, and every production identity/launcher gate rejects the test-role
  module despite matching source/schema digests;
- the checked-in isolated stage-order command crosses both CUDA constructors
  with malformed/dangerous `vec`, `train`, `policy`, and device inputs while
  the environment is invalid, requires the exact preflight/downstream counter
  vectors, runs valid reachability/cleanup controls, and writes bounded atomic
  source/module/patch/isolation evidence;
- the reward-ablation and reward-screen ordered patch lists produce the same
  strict-patch-inclusive bundle digest;
- both launchers require, not merely write, the exact config-schema and
  production-role module attributes; missing/mutated compiled-contract or run
  metadata fields fail contract tests;
- an unrelated Puffer environment still compiles with the conditional marker
  absent; and
- CUDA is patch/source compiled where available but no GPU training is
  launched.

The Linux CI job pins `runs-on: ubuntu-24.04` and installs
`build-essential`, `clang`, `libomp-dev`, `libomp5`,
`curl`, `ca-certificates`, `tar`, `pkg-config`, `libgl1-mesa-dev`,
`libx11-dev`, `libxrandr-dev`, `libxi-dev`, `libxcursor-dev`, and
`libxinerama-dev`. It creates a temporary venv with an
exact-version CI requirements file covering `pip`, `setuptools`, `wheel`,
`pybind11`, `numpy`, CPU `torch`, `rich`, `rich-argparse`, `scipy`,
`scikit-learn`, `linear-operator`, and `gpytorch`. The latter four close the
eager import dependencies of the selected `pufferlib.sweep` path; an isolated
selected-root import probe prevents a rich developer environment from masking
their absence. CI does not run PEP-517 or install the Puffer project package;
the exact checked-out source is used through an explicitly asserted
`PYTHONPATH`, avoiding a hidden build-isolation dependency fetch. It prefetches
the versioned Raylib 5.5 Linux amd64 archive, verifies a checked-in SHA-256,
and extracts it into the clone before `build.sh`; cache keys include that
digest.

Inside that isolated venv/tree, CI:

1. checks out Puffer at exactly
   `9836f0d2e78889c1aaf189c04d161b6fc61a9386` and asserts
   `git rev-parse HEAD`, then creates that clone's `.venv`;
2. runs the installer and runs it again;
3. builds `./build.sh bloodbowl --cpu` and the standalone
   `./build.sh bloodbowl --fast`, then runs installer `--check`;
4. imports `_C` with an explicit clone-root `PYTHONPATH` and asserts
   `_C.__file__` resolves beneath that clone, `_C.env_name == "bloodbowl"`,
   the config-schema export is exact, the testing-role attribute is false, and
   compiled/on-disk backend and environment digests agree;
5. imports the selected sweep implementation in an isolated interpreter and
   runs the selected-source entropy/Torch and strict-source suites;
6. constructs, resets, and always closes all five valid configuration profiles;
   and
7. subprocess-checks all 44 malformed transport, schema, integer, team, reward,
   gamma, and cross-field cases during construction, with fatal direct-C cases
   isolated.

The CPU evidence records exact Python, pip, setuptools, wheel, pybind11,
NumPy, Torch, Rich, SciPy, scikit-learn, linear-operator, GPyTorch, clang, C++
compiler, and OpenMP versions alongside the pinned Puffer/Raylib identities.

CUDA remains a real-GPU qualification artifact; CPU CI does not pretend to
validate device execution. The isolated test-role stage-order artifact is
mandatory external release evidence and is not complete merely because the
CPU fake-backend and source-lock tests pass.

## Validation gates

1. Adversarial plan approval with no open P0/P1/P2 blockers.
2. Watched-red commit and recorded fail-open output.
3. Focused optimized native schema/domain/configuration tests.
4. Focused ASan/UBSan tests, including invalid pre-cast values.
5. Full optimized native matrix.
6. Full native ASan/UBSan matrix.
7. Full Python tools and training suites.
8. Shell syntax and `shellcheck --severity=warning`.
9. Relevant `ruff check`, `ruff format --check`, `py_compile`, and
   `git diff --check`.
10. Default seed-42 100-episode FNV twice, preserving
    `ea1d720e69f5a491`, 26,251 steps, and zero illegal actions.
11. Clean exact-pinned Puffer install twice on
    `9836f0d2e78889c1aaf189c04d161b6fc61a9386`.
12. CPU module and standalone rebuild plus installer drift check.
13. Fresh Linux pinned-Puffer CPU CI/integration construction for full and
    sparse configs, plus real subprocess rejection for each domain category,
    malformed/unknown key, and nonnumeric key.
14. CPU `create_vec`, CUDA `create_vec`, and CUDA `create_pufferl`
    constructor-order contract tests, plus both recurrent production-CUDA
    expected-negative construction subcells and both positive constructor
    paths. Before release, execute the isolated
    `strict-stage-order` command on real NVIDIA hardware and retain its
    accepted bounded evidence. This is mandatory external evidence; lack of a
    local GPU leaves this gate incomplete rather than waived or passed.
15. Unrelated-environment build with the strict marker absent.
16. Canonical backend/vendor path-ledger reconciliation; exact engine,
    environment, backend, module, standalone, generated-header, config-schema,
    production/testing build role, toolchain/dependency, and patch-bundle
    identities recorded.
17. Self-review and independent native plus Python/Puffer adversarial reviews
    close all substantiated P0/P1/P2 findings.

## Implementation validation record

Local and exact-CPU evidence recorded on 2026-07-28:

- optimized `make test` passed the complete native surface: 476 engine,
  64 reward, 3 contact-bot, 55 state-bank, 22 strict-config, 7 binding,
  26 observation, BBP-writer, and state-bank integration checks;
- `make asan` passed the same native surface with ASan/UBSan;
- two independent default seed-42, 100-episode runs reproduced
  FNV `ea1d720e69f5a491`, 26,251 steps, and zero illegal actions;
- the Python tools suite passed 356 tests with 6 expected platform skips;
- the Python training suite passed 126 tests with 1 expected GPU skip,
  including 70 focused recurrent/CUDA-qualification contract tests;
- the exact-pinned strict Puffer source contract passed 7/7 checks;
- `py_compile`, `ruff check`, relevant new/rewritten-file
  `ruff format --check`, Bash syntax, `shellcheck --severity=warning`, YAML
  parsing, and `git diff --check` passed;
- a fresh Ubuntu 24.04 exact-Puffer checkout at
  `9836f0d2e78889c1aaf189c04d161b6fc61a9386` installed idempotently, built
  the unmodified upstream AVX2/FMA CPU module and standalone, and passed the
  literal installer drift/reverse/source-closure check;
- that real CPU module constructed/reset/closed the full 51-key, empty,
  sparse, exact-bool, and scripted-BOTH profiles, then cleanly rejected 44
  subprocess-isolated invalid cases spanning transport/structure/ordering,
  every one of the 19 native domain groups, special nonfinite/underflow
  values, and all three cross-field families;
- native, exact-Puffer, Python/CI, and overall adversarial reviews closed every
  substantiated P0/P1/P2 implementation finding; and
- the actual CUDA special-build command and retained-evidence validator are
  implemented and locally contract-tested, but their dynamic execution on a
  real NVIDIA GPU remains gate 14 and is not recorded as passed.

Frozen identities for that evidence:

- environment source/installed snapshot/compiled export:
  `6e018ac5a6b4b5cce0f004480e92d7708f7a06d6e6144ed81ea9b77e10fba015`;
- historical nine-file compiled backend (superseded by the 15-entry native
  closure; not valid for new modules):
  `56b4129ab362667a5a433cb00616ce661f8dbbd9b99e7f727b4823577023af27`;
- twelve-file vendor closure:
  `59e44b3a66e38aa6fe7a4d3bd4facd5ede6e4d4cb4e835513c1f7265f2c45fcd`;
- strict Puffer patch:
  `bf4d04e5bca634688662b73aeb5ad653cc0342ddfa1db477abff45630a121cee`;
- production CPU module:
  `3d92bc10203443c265bcc6b456ddc07dfc5e0a9a5707accd36e63c452e8b546d`;
- exact standalone:
  `36e2ead93dbe58baed8ae03c9eab261e1919d7358de22826d8d92e583fcb1c49`;
- generated exact-action build header:
  `a45333da3d22d63417d0c9cc1401e44d422cfc5023a86d6b10d9f32f73f811ad`;
- final CUDA qualifier:
  `331676ba18fdae6724ac70466e9fa2ab21bb92eb56f3877608fd2564bec7431c`;
  and
- final installer:
  `cbc51ad25951c5465079c2f0eb6763bdf5aec671f1d477b43a733f7ee482b620`.

Current-stack integration note, 2026-07-30: the entropy tranche recut the
strict artifact to
`a75bf6b57a1d6d2e50af0cd89adc9f40d9c54deb7b880d21925d3287593d7679`
without changing the strict configuration semantics. Two fresh exact-pin
macOS/ARM checkouts independently passed the 7/7 strict source contract, five
valid constructor profiles, and all 44 isolated invalid-case rejections. The
complete installed 15-entry compiled-source closure is now
`20934ecd87c9e23fa5943ba903ec15a1c76f22bcda59d486dce1680804264dff`,
and the generated header is
`774636bd5cd717b98e0925a52a083d5f07b1084a1becee5fd77912a8a434f507`.
This local rerun does not replace the historical Ubuntu evidence above and
does not satisfy the still-mandatory x86 CI or real-NVIDIA stage-order gate.
The full current identity and endpoint ledger is in
`docs/plans/entropy-schedule-parity.md`.

Kimi review remains waived only under the user's explicit instruction for this
goal; it is not silently represented as completed.

## Version and lineage decision

- Add the native config-schema literal
  `bloodbowl-environment-config-v1`, export it from both modules, require it in
  installer/qualification identity, and record
  `compiled_environment_config_schema` plus
  `compiled_strict_env_config_testing=false` in newly minted immutable run
  metadata.
  Run-manifest schema v1 is intentionally extensible and already hashes the
  complete metadata object, config tree, CLI overrides, module, and
  environment source, so this additive field does not change checkpoint or
  run-manifest encoding. Historical manifests remain validated/reproduced by
  their pinned tooling; new launchers must not omit the field.
- Valid default observations, exact actions, rewards, terminals, BBP,
  checkpoints, and FNV trajectory do not change.
- Environment source identity changes.
- Exact backend identity changes because the conditional CPU/CUDA Python
  boundary changes.
- Observation ABI remains `obs-v6`; action ABI remains `exact-joint-v1`.
- Production state-bank authorization remains empty.
- Historical runs remain reproducible from their pinned compiled module.
  Reusing their malformed or silently coerced configuration with this build
  is intentionally rejected rather than lineage-compatible, except that the
  formerly coerced numeric value `scripted_opponent_team=2` is now admitted
  and intentionally means BOTH. A historical run that supplied `2` remains
  reproducible only with its old pinned module, where it meant AWAY after the
  clamp; the new environment identity records the semantic change.

## Required adversarial-review blockers

Implementation must not begin while any of these remains:

- a consumed key has no explicit domain;
- parsing, validation, and application can drift between separate key lists;
- any integer/enum/boolean is cast before exactness and range are proved;
- a nonfinite value can reach a C integer cast;
- an invalid forced team can reach `bb_team_defs`;
- scripted BOTH is still rewritten to AWAY;
- an invalid budget or enum still falls back to a default;
- NaN or negative PBRS gamma can select legacy behavior;
- a malformed or nonnumeric Blood Bowl entry can disappear or be truncated at
  the generic binding;
- preflight validates a temporary conversion but downstream construction
  reconverts the mutable/original Python object instead of the inert snapshot;
- a Python numeric protocol, conversion exception, or oversized integer can
  run twice or escape the bounded `ValueError` contract;
- Python/native dictionary cardinality can narrow to `int` or allocate before
  the closed 51-key maximum is proved;
- an occupied native `DictItem` NULL key can reach `strcmp`, length scanning,
  escaping, or diagnostics before structural rejection;
- an unknown or duplicate numeric key can be ignored;
- invalid configuration can trigger bank I/O or engine initialization first;
- sparse valid configs lose their intentional defaults;
- the Puffer patch changes string handling for unrelated environments;
- Blood Bowl strict mode is applied to the shared `[vec]` converter rather
  than only `args["env"]`;
- CPU and CUDA bindings implement different boundaries;
- native CUDA `create_pufferl` bypasses the same preflight used by the two
  `create_vec` paths;
- either `create_vec` reads/casts `[vec]` numeric values before env preflight;
- constructor ordering is inferred only from source text instead of proved by
  the named GIL/stage API plus production-module rejection;
- an instrumented stage-test module is indistinguishable from or can overwrite
  a production-role module;
- the exact sparse `{seed, max_decisions}` qualification config stops working;
- the new overlapping Puffer patch is not last, marker-verified in both
  bindings, context-preserving for the recurrent-qualification hunk,
  reverse-applicable, and included in both ablation and screen patch-bundle
  provenance;
- clean pinned-Puffer CPU construction is absent from CI;
- clean CPU CI lacks an isolated venv/module-path proof, exact toolchain
  inputs, a no-build-isolation/source-only Puffer rule, recorded dependency
  versions, or a SHA-verified Raylib archive;
- recurrent CUDA qualification lacks separate structured expected-negative
  calls through both `create_vec` and `create_pufferl`;
- installer and qualifier compiled-backend source lists can drift, or the
  broader screen/ablation vendor-source lists can drift;
- the config-schema literal is not exposed, identity-checked, and recorded in
  new run metadata;
- `my_vec_init` is specified to copy into `Bloodbowl` before allocating its
  environment array, or allocates before config/bank validation succeeds;
- the default trajectory or any valid default changes;
- vector geometry is claimed covered without an actual pre-cast proof;
- production bank authorization widens; or
- implementation or validation launches training or mutates an active asset.
