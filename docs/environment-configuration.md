# Blood Bowl environment configuration

Blood Bowl uses the closed schema
`bloodbowl-environment-config-v1`. The authoritative key/default/domain ledger
is `puffer/bloodbowl/environment_config.h`; the normal training values are in
`puffer/config/bloodbowl.ini`.

## Input contract

The environment dictionary may contain any subset of the 51 known keys.
Missing keys receive their ledger defaults, so `{}` and deliberately sparse
evaluation dictionaries remain valid. A supplied dictionary must:

- contain at most 51 entries;
- use exact built-in Python `str` keys matching `[a-z0-9_]+`, with at most
  63 UTF-8 bytes;
- use only known schema keys; and
- use exact built-in Python `bool`, `int`, or `float` values. Numeric
  subclasses, custom `__float__` objects, strings such as `"nan"`, nonfinite
  numbers, and integers that cannot be transported exactly through `double`
  are rejected.

The main domain groups are:

- `seed`: an exact integer from zero through `2^53-1`;
- ordinary reward coefficients: finite `[-1, 1]` values that do not narrow
  from nonzero `double` to zero `float`;
- `reward_dist_pbrs_gamma`, `reward_statmatch_scale`, reset percentages, and
  unit-interval fields: finite `[0, 1]` values with the same nonzero-narrowing
  rule;
- boolean fields: exactly `0` or `1` (Python `False` and `True` are accepted);
- team selectors: `-1` or a generated team ID below `BB_TEAM_COUNT`;
- `scripted_opponent_type`: `0` or `1`;
- `scripted_opponent_team`: `0` for HOME, `1` for AWAY, or `2` for BOTH;
- `max_decisions`: an exact integer from `1` through
  `BBE_MAX_DECISIONS`; and
- selector/procgen fields: the exact closed integer ranges named by the
  authoritative ledger.

Cross-field reward, state-bank, and selector rules are validated after raw
domains but before state-bank I/O, environment allocation, engine reset, or
worker startup. Invalid construction raises one bounded field/domain
diagnostic. It no longer truncates, clamps, skips, or silently replaces a
supplied value.

## Compiled identity

Production CPU and CUDA modules must export:

```text
environment_config_schema = "bloodbowl-environment-config-v1"
strict_env_config_testing = false
```

The special stage-instrumented test build exports
`strict_env_config_testing = true` and is rejected by production installer,
qualification, launcher, lineage, and analyzer gates. Other Puffer
environments do not export the Blood Bowl schema; they retain Puffer's
historical generic dictionary behavior.

After changing the environment or any Puffer boundary patch, reinstall and
rebuild before training:

```bash
bash tools/install_puffer_env.sh vendor/PufferLib
cd vendor/PufferLib
./build.sh bloodbowl --cpu       # CPU integration
./build.sh bloodbowl --fast      # standalone
cd ../..
bash tools/install_puffer_env.sh --check vendor/PufferLib
```

CUDA qualification remains a separate real-GPU gate:

```bash
tools/qualify_recurrent_cuda.py run \
  --puffer-root vendor/PufferLib \
  --baseline-throughput /absolute/path/to/previous-qualification.json \
  --output validation/recurrent-cuda-qualification
```

That production qualifier accepts only
`strict_env_config_testing = false`. It deliberately rejects the
stage-instrumented module. The baseline argument is mandatory and must name a
bounded regular nonsymlink JSON artifact outside the candidate output. The
runner records and rechecks its byte count and SHA-256 and requires its
throughput record to match the candidate host, GPU, fp32 precision, complete
timing configuration, and zero hard-integrity counters.

That is not yet a complete predecessor-lineage proof. The current runner has no
`capture-throughput`, `validate-construction`, or independent `validate`
subcommand and does not authenticate who produced the supplied baseline. Until
the predecessor capture/validation workflow in
`docs/plans/recurrent-cuda-qualification.md` is implemented and reviewed, an
otherwise accepted schema-10 qualification is diagnostic evidence only and
does not complete the CUDA release gate.

Schema 10 binds fresh run/cell nonces, removes fixed-name worker artifacts
before dispatch, retains the exact worker JSON/NPZ byte identities, and writes
cell JSON through a bounded exclusive random descriptor so a stale predictable
temporary symlink cannot redirect a write outside the output. Its
throughput cell is rollout-only but now matches the production collection
shape, including H512/L3 and `max_decisions=4096`; it is not an end-to-end
training-speed measurement. The production entropy schedule is also not yet
qualified: native graph replay freezes the host-by-value coefficient and the
Torch trainer currently leaves it constant. That separate trainer-contract
repair must land before a CUDA training launch can be authorized. Until then,
the native constructor rejects `cudagraphs >= 0 && anneal_ent_coef` before CUDA
discovery, and both reward launchers reject executable runs before output/run
artifact creation. Dry-run and screen-plan modes are explicitly labeled
`BLOCKED_UNQUALIFIED_ENTROPY_SCHEDULE`; their manifests bind the requested
graph/anneal/minimum-ratio fields and mark the effective coefficient
unavailable.

## Mandatory CUDA constructor-order release gate

Releases also require dynamic evidence from the actual CUDA `create_vec` and
`create_pufferl` entry points on a real NVIDIA GPU. This is a distinct
external gate; CPU tests and source-order checks cannot complete it. Use a
disposable clone outside this repository, detached at the exact supported
Puffer commit, with its own virtual environment:

```bash
git clone https://github.com/PufferAI/PufferLib.git \
  /tmp/bloodbowl-strict-stage-PufferLib
git -C /tmp/bloodbowl-strict-stage-PufferLib checkout --detach \
  9836f0d2e78889c1aaf189c04d161b6fc61a9386
python3 -m venv /tmp/bloodbowl-strict-stage-PufferLib/.venv

# Install the pinned Python/CUDA build dependencies into that local venv,
# then run from this repository:
tools/qualify_recurrent_cuda.py strict-stage-order \
  --isolated-puffer-root /tmp/bloodbowl-strict-stage-PufferLib \
  --output validation/strict-cuda-stage-order \
  --confirm-isolated-test-checkout
```

The driver fails closed unless the checkout is pristine, outside this
repository, exactly pinned, free of an installed Blood Bowl environment,
build directory, and compiled `_C` module, and uses a checkout-local venv. It
also requires detached `HEAD` and a real, nonsymlinked `.venv` directory. A
pre-build probe proves that bare `python`, `sys.prefix`, pybind11, NumPy, and
the extension ABI suffix all come from that venv. The driver then uses one
sanitized child environment for the installer, build, and worker:
`.venv/bin` is first in `PATH`, `VIRTUAL_ENV` is exact, and
ambient Python controls, Bash startup files/options/exported functions, and
dynamic-loader injection variables are removed. Direct and noninteractive
Bash probes must resolve the same recorded Python identity. Shell activation
is therefore neither required nor trusted. The driver writes an isolation
receipt, passes the validated absolute interpreter to every installer Python
call as `PUFFER_INSTALL_PYTHON`, invokes the installer through absolute
`/bin/bash`, and invokes only `./build.sh bloodbowl` with
`PUFFER_STRICT_ENV_CONFIG_TESTING=1`. Never point this command at
`vendor/PufferLib`, another production checkout, or an active training tree.

The hidden worker requires `env_name == "bloodbowl"`, the exact schema,
`gpu == 1`, `strict_env_config_testing == true`, matching compiled/source
identities, the reverse-applicable strict patch, and a successful CUDART
pre/post-import device fingerprint. For both constructors it combines
`force_home_team=BB_TEAM_COUNT` with dangerous `vec`, `train`, `policy`, and
device inputs. Every rejection must report exactly one normalization call
with the GIL held and zero named downstream calls. Positive controls must
reach exactly the expected vector or CUDA/Puffer implementation stages and
close safely. The bounded, atomic `STRICT_STAGE_ORDER.json` also proves that
the ordinary production identity validator rejects this test-role module.
Both `ISOLATION.json` and `STRICT_STAGE_ORDER.json` are capped at 64 KiB and
must remain ordinary nonsymlink files. Retained evidence is revalidated with
exact nested keys and JSON scalar types, bounded strings, the exact
hazard-to-malformed-path mapping, an `invalid_team` value rederived from the
installed `BB_TEAM_COUNT`, interpreter/dependency/module/source hashes, and
the recorded extension suffix before it can satisfy the release gate.

This repository's CPU validation does not produce that artifact. Until the
command above succeeds on real NVIDIA hardware and its evidence is retained
with the release, the CUDA constructor-order release gate remains incomplete.

## Reproducible Linux check

CI uses a separate Ubuntu 24.04 job with the exact Puffer commit, exact Python
package pins, and the SHA-verified Raylib 5.5 Linux amd64 archive. The clean
build validation established that `python3-dev`, `python3-venv`, and `git` are
also required in addition to the C/C++/OpenMP/graphics packages: the Python
extension build needs `Python.h`, the isolated dependency set needs a venv,
and the pinned source checkout needs Git.

The job installs twice, builds the production CPU module and standalone,
runs installer drift checking, exercises full/empty/sparse/exact-bool/BOTH
valid profiles, and subprocess-isolates malformed transport and native-domain
rejections. A throwaway clone validates the stage-instrumented build and then
builds the marker-absent `minimal` environment to prove the strict behavior
does not leak into unrelated environments.
