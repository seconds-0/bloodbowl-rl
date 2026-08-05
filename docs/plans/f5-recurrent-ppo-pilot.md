# F5 recurrent Torch PPO pilot

Status: accepted final-consumer import-phase and Puffer-log normalization
amendment; implementation not started.

Base:
`fc315d6454cc2975cdf295ed49098d904dd46799`
(`tranche/f5-trainability-foundation`).

This tranche is the diagnostic PPO pilot promised by the accepted F5
trainability-foundation plan. It is deliberately narrower than a trainability
gate. One prospectively frozen seed may expose a broken learning path or
provide positive fixed-instance acquisition evidence, but it cannot establish
three-seed reliability, held-out generalization, production curriculum
authority, or an acceptable permanent CI threshold.

Kimi review was explicitly waived by the user. Test-first implementation,
clear-eyed self-review, independent adversarial review of this plan before
implementation, and independent adversarial post-implementation review remain
mandatory.

## Objective

Run one uninterrupted, cold-start, objective-only recurrent Torch PPO
experiment against the sealed deterministic F5 role and answer this bounded
question:

> Under one prospectively frozen small-policy recipe, does the real trainer
> observe a Home touchdown within the declared exposure budget, and does the
> final frozen policy have a higher paired stochastic success point estimate
> than its own frozen initialization?

The experiment must use the production observation, exact conditional joint
support, three-head sampler, decoder, engine step, terminal reward, recurrent
collector tail, GAE, prioritized recurrent minibatch, Muon optimizer, and
entropy schedule. It may not use the reference route, demonstrations, action
forcing, shaping, a hidden curriculum, a warm start, best-checkpoint selection,
or result-dependent retries.

An accepted verifier verdict means only that the sealed protocol ran to its
declared boundary with valid integrity and reproducible evaluation evidence.
The learning outcome is a separate field. `accepted` must never be used as a
synonym for `learned`, `passed`, or `promoted`.

## Why this is the next tranche

The F5 foundation already closed the environment-side ambiguities that would
otherwise confound a PPO result:

- exact raw-state and role identity;
- exact observation and conditional joint-action support;
- a legal eight-decision scoring route;
- zero prefix reward and objective-only terminal `(+1, -1)` reward;
- dual terminal, immediate autoreset, and exact episode ledger;
- repaired recurrent rollout-tail reward, terminal, and bootstrap handling;
- ordinary/qualification role separation; and
- a measured masked-uniform exploration baseline.

Two independent read-only audits of the live staged stack also found:

1. Generic `puffer train bloodbowl --slowly` is not an admissible pilot
   launcher. It starts from the production config, owns lossy logging and
   non-atomic checkpointing, and does not enforce the sealed F5 invariants.
2. The Torch backend does not call `random.seed`, `numpy.random.seed`, or
   `torch.manual_seed` before policy construction, action sampling, or
   prioritized replay sampling. Existing config seed fields therefore do not
   determine a Torch run.
3. The real Torch collector does use exact conditional joint sampling, carries
   recurrence across all eight decisions, captures the eighth reward/terminal
   in the repaired tail, and rejects training without recurrent reset.
4. Static-vector logs divide float fields by completed episode count. Exact
   per-match success bits must come from the terminal reward vectors and be
   cross-checked against the aggregate TD log, not reconstructed from a
   rounded dashboard rate alone.
5. A deterministic four-update probe with explicitly owned RNG and thread
   state reproduced both logs and the final canonical parameter digest.
6. A local Darwin-arm64 CPU probe with the frozen small policy and 4,096 agent
   rows, horizon 8, replay `0.25`, minibatch 8,192, and Torch 4/1 threads
   measured `0.578` seconds/update (`0.378` rollout plus `0.200` train), about
   56.7k reported agent-SPS. The full prospectively declared exposure therefore
   predicts about 28.5 minutes before evidence overhead. An older
   differently configured 2,048-row probe observed about 17.5k SPS; even that
   lower envelope predicts about 92.3 minutes and is covered by the cap below.

No audit result is itself admissible learning evidence. It only fixes the
protocol below before the result seed is consumed.

The protocol helper therefore owns one explicit, closed normalization boundary
between the pinned flat `_vec.log()` result and an accepted rollout-integrity
object. The controller's training worker, every controller evaluation worker,
and every verifier replay worker must invoke the same adapter after each
rollout and before respectively `train()` or bitset acceptance; no population
has an already-normalized bypass. For each such training or evaluation
rollout, the adapter first requires the native completed count
`n` to be exactly the finite integral value `2048.0`. Every native
episode-total accumulator divided by `n` (including touchdown counts, reward
component totals, and Home post-clip return) is multiplied by `n`. A
count-valued result must be exactly integral before conversion to a
non-Boolean JSON integer; signed reward totals remain finite binary64 values.
Native rates and per-episode means remain in their declared units:
`episode_length` must be exactly `8.0` and
`reward_samples_per_episode` must be exactly the integral value `16`, not
`16 * n`. In particular, `tds_t0`, `tds_t1`, `episode_length`,
`reward_component_touchdown`, `reward_postclip_return`, and
`reward_samples_per_episode` are independently normalized and reconciled with
the accepted delayed-row-plus-tail reward and terminal vectors. A
one-Home-touchdown update therefore normalizes
`tds_t0 = 1/2048`, `tds_t1 = 0.0`,
`reward_component_touchdown = 1/2048`, and
`reward_postclip_return = 1/2048` to one Home objective, zero Away objectives,
one touchdown component, and one post-clip Home return. The accepted raw map
has exactly the pinned binding's 152 literal `my_log` keys plus the
vector-appended `n`. Sorting those 153 unique strings by UTF-8 bytes and
serializing the array with the canonical JSON serializer yields SHA-256
`6eb55b0fab1fe6c33ff41b8268c39783c583b7b762164b0216882b946193c497`;
watched tests own the independent literal string tuple as well as that digest,
without parsing the production binding at test time. Every consumed native
scalar, including `n`, must satisfy `type(value) is float` and
`math.isfinite(value)` before any comparison, multiplication, or conversion;
integer and Boolean test doubles are rejected even when numerically equal.
Missing or extra native keys, a nonintegral scaled count, a
one-float32-unit perturbation that breaks the exact count reconciliation, any
Away touchdown, an endpoint identity failure, or disagreement with the
accepted reward vectors aborts before `train()` or bitset acceptance. The
one-unit mutation is specifically adjacent IEEE-754 binary32, not binary64
`math.nextafter`: little-endian bit patterns `0x39ffffff`, `0x3a000000`, and
`0x3a000001` decode respectively to
`0.00048828122089616954`, `0.00048828125`, and
`0.0004882813082076609`; watched tests construct those bits independently.
After type, finiteness, operation, and semantic validation, every projected
numeric result equal to zero is canonicalized to the positive `0.0` literal
before evidence construction (integer projections remain integer `0`).
Negative-zero inputs therefore cannot create a second accepted JSON spelling;
watched tests exercise `-0.0` in every numeric-operation family. The
stored `projection_collisions = 0` leaf is explicitly a derived invariant—not
claimed native telemetry—established only from the authenticated fixed
module/role, successful closed rollout, zero illegal fraction, and accepted
exact conditional-joint-action path. Neither the flat native log nor a
test-only already-nested `env_logs["integrity"]` object is accepted as stored
evidence without passing this adapter.

The tracked manifest—not helper code—is the unit/projection authority. Its
`execution.rollout_log` object has exactly `derived`, `native_keys`,
`native_keys_sha256`, `projections`, and `validated_unretained`.
`native_keys` is the sorted literal 153-string array above and
`native_keys_sha256` is its frozen digest. `projections` is ordered by native
key and each closed record has exactly `native`, `operation`, and `target`.
The only operation literals are `completed-count`,
`scale-nonnegative-integer`, `scale-finite-number`,
`retain-nonnegative-integer`, `retain-finite-number`, and `require-zero`.
`validated_unretained` is the sorted literal array of every remaining native
key; each of those values is still required to be a finite exact Python
`float`, but it enters no evidence claim. Every native key occurs exactly once
as either one projection's `native` value or one
`validated_unretained` member, and their union must equal `native_keys`.
Duplicate, omitted, reclassified, retargeted, or extra keys reject the
manifest. The projection table below contains exactly 83 unique native keys;
the resulting 70-string sorted `validated_unretained` array, serialized with
the canonical JSON serializer, has SHA-256
`67167fd2e3ea29dadc26e3bf0e5ac35b0732a2d022fef5434ec163cb373e36a4`.
Watched tests own that independent literal array and digest.

The exact projected native-to-target groups are:

```text
completed-count:
  n -> integrity.completed_episodes

scale-nonnegative-integer:
  demo_endzone_episode_frac_all -> integrity.demo_endzone_episodes
  demo_episodes -> integrity.demo_episodes
  demo_fallbacks -> integrity.demo_fallbacks
  demo_pass_episode_frac_all -> integrity.demo_pass_episodes
  demo_pickup_episode_frac_all -> integrity.demo_pickup_episodes
  demo_postkick_episode_frac_all -> integrity.demo_postkick_episodes
  demo_uniform_episode_frac_all -> integrity.demo_uniform_episodes
  error_episodes -> integrity.error_episodes
  reward_clip_episodes -> integrity.reward_clip_episodes
  reward_clip_nonterminal_samples_per_episode
    -> integrity.reward_clip_nonterminal_samples
  reward_clip_terminal_samples_per_episode
    -> integrity.reward_clip_terminal_samples
  reward_clipped_samples_per_episode -> integrity.reward_clipped_samples
  reward_component_mismatch_samples_per_episode
    -> integrity.reward_component_mismatch_samples
  reward_component_nonfinite_samples_per_episode
    -> integrity.reward_component_nonfinite_samples
  reward_nonfinite_episodes -> integrity.reward_nonfinite_episodes
  reward_nonfinite_samples_per_episode
    -> integrity.reward_nonfinite_samples
  state_bank_config_episode_frac_all
    -> integrity.state_bank_config_episodes
  tds -> validation.total_touchdowns
  tds_t0 -> objective.events
  tds_t1 -> integrity.away_touchdowns

scale-finite-number:
  episode_return -> validation.home_episode_return
  reward_clip_excess -> integrity.reward_clip_excess
  reward_component_ball_gain -> integrity.reward_components.ball_gain
  reward_component_ball_loss -> integrity.reward_components.ball_loss
  reward_component_block_assist -> integrity.reward_components.block_assist
  reward_component_block_exposure
    -> integrity.reward_components.block_exposure
  reward_component_block_self_injury
    -> integrity.reward_components.block_self_injury
  reward_component_block_sequence
    -> integrity.reward_components.block_sequence
  reward_component_block_turnover
    -> integrity.reward_components.block_turnover
  reward_component_carrier_exposure
    -> integrity.reward_components.carrier_exposure
  reward_component_carrier_exposure_soft
    -> integrity.reward_components.carrier_exposure_soft
  reward_component_carrier_threat
    -> integrity.reward_components.carrier_threat
  reward_component_defensive_threat
    -> integrity.reward_components.defensive_threat
  reward_component_defensive_threat_soft
    -> integrity.reward_components.defensive_threat_soft
  reward_component_distance_ball -> integrity.reward_components.distance_ball
  reward_component_distance_endzone
    -> integrity.reward_components.distance_endzone
  reward_component_injury_inflicted
    -> integrity.reward_components.injury_inflicted
  reward_component_injury_taken
    -> integrity.reward_components.injury_taken
  reward_component_possession -> integrity.reward_components.possession
  reward_component_residual -> integrity.reward_component_residual
  reward_component_result_draw -> integrity.reward_components.result_draw
  reward_component_result_winloss
    -> integrity.reward_components.result_winloss
  reward_component_rush -> integrity.reward_components.rush
  reward_component_send_off -> integrity.reward_components.send_off
  reward_component_setup_autofix
    -> integrity.reward_components.setup_autofix
  reward_component_setup_done -> integrity.reward_components.setup_done
  reward_component_statmatch -> integrity.reward_components.statmatch
  reward_component_surf_inflicted
    -> integrity.reward_components.surf_inflicted
  reward_component_surf_taken -> integrity.reward_components.surf_taken
  reward_component_touchback -> integrity.reward_components.touchback
  reward_component_touchdown -> integrity.reward_components.touchdown
  reward_postclip_return -> integrity.reward_postclip_return
  reward_terminal_suppressed_abs
    -> integrity.reward_terminal_suppressed_abs
  reward_terminal_suppressed_signed
    -> integrity.reward_terminal_suppressed_signed
  score_diff -> validation.score_diff

retain-nonnegative-integer:
  demo_selector_eligible_mean_configured
    -> integrity.demo_selector_eligible_configured
  demo_selector_threshold_mean_configured
    -> integrity.demo_selector_threshold_configured
  reward_samples_per_episode -> integrity.reward_samples_per_episode

retain-finite-number:
  episode_length -> integrity.mean_episode_length
  illegal_frac -> integrity.illegal_fraction
  reward_episode_abs_max_mean -> validation.reward_episode_abs_max_mean

require-zero:
  hist_n_bank_0 -> validation.hist_n_bank_0
  hist_n_bank_1 -> validation.hist_n_bank_1
  hist_n_bank_2 -> validation.hist_n_bank_2
  hist_n_bank_3 -> validation.hist_n_bank_3
  hist_n_bank_4 -> validation.hist_n_bank_4
  hist_n_bank_5 -> validation.hist_n_bank_5
  hist_n_bank_6 -> validation.hist_n_bank_6
  hist_n_bank_7 -> validation.hist_n_bank_7
  hist_score_bank_0 -> validation.hist_score_bank_0
  hist_score_bank_1 -> validation.hist_score_bank_1
  hist_score_bank_2 -> validation.hist_score_bank_2
  hist_score_bank_3 -> validation.hist_score_bank_3
  hist_score_bank_4 -> validation.hist_score_bank_4
  hist_score_bank_5 -> validation.hist_score_bank_5
  hist_score_bank_6 -> validation.hist_score_bank_6
  hist_score_bank_7 -> validation.hist_score_bank_7
  reward_clip_frac -> validation.reward_clip_frac
  reward_clip_frac_nonzero -> validation.reward_clip_frac_nonzero
  reward_clip_signed_delta -> validation.reward_clip_signed_delta
  reward_nonfinite_frac -> validation.reward_nonfinite_frac
  statmatch_term -> validation.statmatch_term
```

The semantic adapter separately requires completed count `2048`, mean length
`8.0`, samples per episode `16`, all `require-zero` values and all hard
integrity targets except the reconciled touchdown/Home-return fields to be
zero, total touchdowns to equal Home plus Away touchdowns, score difference
to equal Home minus Away touchdowns, and Home episode return,
`reward_component_touchdown`, and `reward_postclip_return` to equal the Home
objective-event count. `reward_episode_abs_max_mean` equals successful
episodes divided by `2048`, preserving the distinction between event count
and the any-event success bit when a policy scores more than once in one
eight-decision episode. Every other reward component is zero. `derived` is
exactly one closed record with target `integrity.projection_collisions`, value
`0`, and the ordered basis
`["fixture_role","module_identity","rollout_closed","illegal_fraction",
"exact_joint_action"]`; all five bases must validate before the leaf exists.

## Claims and non-claims

### Admissible claims

If all protocol and integrity gates pass, this tranche may report:

- whether any objective event entered the training rollouts;
- the first and cumulative training-update objective counts;
- fixed-checkpoint stochastic F5 success estimates;
- paired initialization-versus-final discordance counts under common random
  number streams;
- policy parameter drift, entropy/loss diagnostics, and throughput;
- whether repeated initialization and repeated checkpoint-zero evaluation are
  byte-identical under the frozen RNG contract; and
- one of the predeclared exploratory outcome classifications below.

### Inadmissible claims

This tranche may not claim:

- that F5 is a passing trainability gate;
- that PPO reliably learns F5 across seeds;
- that the policy generalizes to another state, geometry, environment seed,
  team, side, capability, or opponent;
- that a zero-TD run proves PPO or the representation is broken;
- that a positive run identifies a universally good hyperparameter recipe;
- that the qualification fixture is authorized for production state-bank use;
- that local Torch CPU throughput predicts native CUDA or target-GPU
  throughput; or
- that a later three-seed threshold has already been calibrated.

The F5 role freezes the environment base seed to `1`. Evaluation separation is
therefore policy/action-RNG separation only. It is not a held-out environment
or geometry evaluation.

## Frozen source and runtime identity

The public runner accepts exactly:

```text
--puffer-root <prepared-pinned-root>
--artifact-dir <new-output-path>
```

It accepts no seed, budget, config, checkpoint, resume, device, thread,
evaluation, reference, or reward overrides.

For the canonical local run it must require:

- clean Blood Bowl source at one exact committed implementation revision;
- Puffer base commit
  `9836f0d2e78889c1aaf189c04d161b6fc61a9386`;
- the already qualified Darwin-arm64 CPU F5 module at
  `pufferlib/_C.cpython-312-darwin.so`;
- module SHA-256
  `0dd03bcf444f84241ef8f6724b5e7d1e8c572c56d66714ccd44c1f5be69f1488`;
- exact closed 73-file `pufferlib/**/*.py` plus `config/**/*.ini` source
  manifest SHA-256
  `961915f4caf5e0767ce8caaf6ae6e2623bfa3591befcb2913ba5eac561d82f2b`;
- specifically, the executed trainer/model/optimizer sources:
  `pufferlib/pufferl.py`
  `22bbbe209f5d73a397863b15ecb5e76af0617143bf8bf7158381f560f957526c`,
  `pufferlib/torch_pufferl.py`
  `30e36f98951b7c38541156835f83c06e6a8b3b475b65349812313825da36daec`,
  `pufferlib/models.py`
  `def01bf10ce48eabe9743a9dfb4d5ad635c214e14b07219e5c929b6ae61afd59`,
  and `pufferlib/muon.py`
  `105bfc542cdb125e384a3290f7d282b212379836bc9983290948b12b860ba888`;
- exact staged `config/default.ini`
  `6b129902269d99e5434a47a175e3ac4c13f30af4e4da613ebe158b02cd5bd9cc`
  and `config/bloodbowl.ini`
  `7ef064026b2d098d42d12c7ca67e1dd5b8ae3c4d584f788c03916a7d6bd08f1e`;
- qualification role `f5-fixed-state-v1`, enabled and qualification-only;
- compiled GPU flag `0`;
- state-bank kind `0` / `none`;
- PufferLib `4.0.0`;
- CPython `3.12.12`;
- Torch `2.9.1`;
- exact F5 environment JSON SHA-256
  `139248d25d37167bdfe7c43d5c01f4f7a6ddb850aa9392502f98a021961afe3f`;
  and
- exact tracked installation-requirements SHA-256
  `010a1f6a785d9c7e7b421f345eeae10a177891fae7e56454111da18c0bed9aa6`.

The 73-file digest uses
`puffer-python-config-source-manifest-v1`. Paths are normalized POSIX paths
relative to the prepared root, must be ASCII without dot/traversal components,
and are sorted by their UTF-8 bytes. The preimage is one JSON array whose
objects contain exactly the keys `bytes`, `path`, and `sha256`, whose values
are respectively a decimal JSON integer, a JSON string, and a lowercase
64-character hexadecimal JSON string. Encoding is UTF-8 with
`ensure_ascii=true`, sorted object keys, separators `(",", ":")`, no spaces,
and exactly one final LF. The SHA-256 above is over those complete encoded
bytes. Independent literal-vector tests construct a two-file manifest without
calling the production helper and require one prospectively hard-coded byte
string and digest; path order, key order, whitespace, final-LF, size, and file
hash mutations must all change or reject the digest.

That last digest is deliberately labelled a requirements-file digest, not an
installed-environment digest. The canonical prepared environment is separately
bound to all of the following startup inputs:

- `.venv/f5_trainability_distributions.json`, SHA-256
  `0d34d78502a93a64de8eb61e6a8415f3de1a106c4917211b126dd0904ebc44bd`;
- `.venv/f5_trainability_distributions.sha256`, SHA-256
  `b5e8efec9074603249e5bcec9159430b909364c8abd2a58bbaa53183ca970b35`;
- `.venv/pyvenv.cfg`, SHA-256
  `ddf5585cd4274da0c0d610db2fbaee4e9701667b63311f3121c7f0550ef9ab26`;
- the resolved `.venv/bin/python3.12` executable, SHA-256
  `d4706f4e64be2b6f94083b270a529469955f56d2438c03182427209fbbb65752`;
- the only site-packages `.pth` file,
  `pufferlib-editable.pth`, SHA-256
  `dad56aa4fa83edc15aa25d863172746d81920cdd05e98504fb04cb3a6a0a5ae6`;
  and
- the complete recursive site-packages entry manifest, including directories,
  regular-file sizes and hashes, and literal symlink targets, under
  `sorted-recursive-entry-manifest-v1`: 22,336 files, 1,860 directories, zero
  symlinks, 614,375,103 regular-file bytes, aggregate SHA-256
  `8129f1ce63bc0b3053132acb45e5c53e6a46715451f0231ca682c05a02dc50dc`.

The site-packages manifest byte-closes the installed Python packages rather
than trusting distribution names and versions alone. The exact Homebrew
standard library and host system frameworks remain a named local-host trust
boundary; they are not claimed to be reconstructible wheels. To keep that
boundary stable, the canonical run additionally requires:

```text
host model                   Mac16,7 / Apple M4 Pro
host architecture            arm64
macOS                        15.6
Darwin kernel                24.6.0
CPython build                3.12.12, Clang 17.0.0 (clang-1700.0.13.3)
Torch git revision           5811a8d7da873dd699ff6687092c225caffcf1bb
torch.__config__ SHA-256     2c00b2da0313cf2ae141fe02e05ea5466380d77f59208c92aade95dbe16909b2
Torch CPU dependencies       Accelerate LAPACK/BLAS and OpenMP
```

The public controller and verifier must themselves be launched as:

```text
/usr/bin/env -i \
  PATH=/usr/bin:/bin LANG=C LC_ALL=C TMPDIR=/private/tmp \
  /usr/bin/python3 -B -I -S <script> ...
```

They reject any other flag or environment state. The exact `/usr/bin/env`
SHA-256 is
`7259ae24c7f1907eede9230ddc3c6b44e811c64f9ccc0073681d560094e092f0`.
On this frozen macOS host the protected system launcher strips inherited
loader state before applying `-i`; a watched `DYLD_INSERT_LIBRARIES` injection
must still reach the exact clean outer process. The host Python command file
SHA-256 is
`7588ceab299393618d6f8861502ac0588d1594025f301d9a61a898215b5571d3`;
its resolved Xcode CPython 3.9.6 executable is
`/Applications/Xcode.app/Contents/Developer/usr/bin/python3`, SHA-256
`e7276a0ac27acdd53135450bd3038e8a6d77aad9df9ee06b05ef311ce9955db9`.
The outer process requires `isolated=1`, `ignore_environment=1`, `no_site=1`,
and a three-entry Xcode standard-library-only `sys.path`. Before completing
the source, implementation-manifest, Git-blob, zero-bytecode, and helper-file
identity preflight below, it imports no repository-local or third-party
module. Controller mode and ordinary verifier-writer mode retain that
restriction for their full outer-process lifetimes and delegate all
repository-local semantic work to capability-gated audited workers.

Final-consumer mode has one narrower post-preflight exception. After the outer
process has independently authenticated the exact clean source commit, all
seven implementation-manifest entries, their Git blobs and live descriptor
identities, the empty source status, and zero bytecode, it may load exactly
`tools/f5_recurrent_ppo_protocol.py` from the regular single-link
`O_NOFOLLOW` descriptor that the preflight already holds; it must not hand the
content read back to a pathname importer. It rechecks the descriptor's
device/inode/mode/link-count/size and raw Git-blob bytes/hash immediately
before and after the complete bounded read, compiles those authenticated bytes
with the frozen absolute source path as the diagnostic filename, executes
them in one `types.ModuleType` named exactly
`f5_recurrent_ppo_protocol_authenticated`, and calls that module's named
`validate_final_evidence` implementation. The module's `__file__` is set to
the frozen authenticated path, but that string is not treated as the content
identity proof. It may load no other repository-local module, may not extend
`sys.path`, and may not import a third-party module. The helper remains
standard-library-only at module import time. Preflight is allowed to
descriptor-open and bounded-read the helper only to establish its file/blob
identity; before the preflight success marker it may not compile, execute,
register, or pathname-import those bytes. A preflight failure, early helper
execution/registration/path import, different local module,
descriptor/path/source-name substitution, changed helper bytes or identity,
or third-party import fails before any artifact payload is opened. This
explicit exception avoids a second final-evidence validator and does not widen
controller or writer mode.

The verifier freezes these private, non-CLI test seams:

```text
_run_final_consumer_preflight(
    operations, *, artifact_dir, expected_verdict_sha256
) -> context
_load_authenticated_protocol_helper(
    operations, *, context
) -> module
_run_final_consumer_postflight(
    operations, *, context
) -> None
_consume_final(
    operations, *, artifact_dir, expected_verdict_sha256
) -> validated_result
```

`_consume_final` has exactly one call to each of the first three functions and
one call to the authenticated module's `validate_final_evidence`, in this
order: preflight; `operations.mark_preflight_complete(context)`; authenticated
held-descriptor load; evidence validation; postflight; return. A thrown
exception skips all later phases. `operations` is an internal fixed
collaborator constructed by the committed verifier, never a public argument,
environment value, plugin, or internal-mode caller override. The opaque
context owns the already validated source snapshot and still-held helper
descriptor; no later phase re-resolves it from caller data.

The complete outer environment is the exact nine-key map produced by that
command on the frozen host:

```text
CPATH=/usr/local/include
LANG=C
LC_ALL=C
LIBRARY_PATH=/usr/local/lib
MANPATH=/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk/usr/share/man:/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/usr/share/man:/Applications/Xcode.app/Contents/Developer/usr/share/man:/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/share/man:
PATH=/usr/bin:/bin
SDKROOT=/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk
TMPDIR=/private/tmp
__CF_USER_TEXT_ENCODING=0x1F5:0x0:0x0
```

Missing, extra, or changed keys, including every `DYLD_*`, `LD_*`, `OMP_*`,
`KMP_*`, Python, Torch, distributed, proxy, cache, or application-control key,
fail before worker construction.

That stdlib-only outer process performs the preflight *before it ever starts
the prepared interpreter*. It resolves the interpreter, hashes the files
above, recursively closes site-packages, rejects any additional `.pth`,
`sitecustomize`, editable-finder, hardlink, symlink, or unsupported filesystem
entry, and validates the exact two-line contents of
`pufferlib-editable.pth`. The recursive manifest sorts normalized POSIX
relative paths by UTF-8 bytes and hashes these unambiguous entry records:
`D\0<path>\n` for directories,
`F\0<path>\0<decimal-size>\0<sha256>\n` for regular files, and
`L\0<path>\0<literal-target>\n` for symlinks; the canonical tree has zero
`L` entries. NUL, newline, absolute, dot, and traversal names are rejected.

`-B` prevents bytecode writes but does not prevent bytecode reads. Before any
target process starts, the outer preflight must therefore recursively require
zero `__pycache__` directories and zero `.pyc`/`.pyo` files or links anywhere
under both the clean Blood Bowl source worktree and the editable prepared
Puffer root outside its already byte-closed `.venv/site-packages`. It repeats
that zero-bytecode check after every worker. The worker's fail-closed audit
hook independently permits editable-Puffer imports only from the exact
73-file Python/config manifest (plus the one exact compiled module) and permits
pilot-source imports only from the exact committed implementation manifest;
an unmanifested source, bytecode, or extension open aborts before its contents
execute. Watched fixtures place both timestamp-valid malicious bytecode and
stale bytecode in `pufferlib/__pycache__`, a sourceless `.pyc` beside the
package, and bytecode beside the Blood Bowl protocol helper; every case must
fail in the outer preflight before model construction.

The implementation manifest's path set is frozen to exactly:

```text
.github/workflows/ci.yml
docs/plans/f5-recurrent-ppo-pilot.md
tools/f5_recurrent_ppo_protocol.py
tools/run_f5_recurrent_ppo_pilot.py
tools/test_f5_recurrent_ppo_pilot.py
tools/verify_f5_recurrent_ppo_pilot.py
training/f5_recurrent_ppo_pilot.json
```

Each must be a tracked regular single-link file at the clean runtime source
commit. Paths obey the same ASCII/no-empty/no-dot/no-traversal/no-backslash/
no-NUL/no-newline rules as the Puffer source manifest and are ordered by UTF-8
bytes. The canonical entry array has exactly seven objects with exactly
`bytes`, `path`, and `sha256`, encoded with the pinned canonical JSON serializer
and one final LF. Its semantic digest is:

```text
SHA256(
    ASCII "bloodbowl-f5-implementation-manifest-v1\0"
    || canonical seven-entry array bytes
)
```

The runtime digest is not embedded in any of those seven source files; it is
recorded only in `identity.json`, avoiding self-reference. The outer
controller and verifier derive it independently from the exact clean Git
commit and exact path set. The worker audit allowlist is mechanically derived
from the same seven entries and may not add a caller-selected source. Missing,
extra, reordered, linked, worktree-dirty, Git-blob-mismatched, or byte-mutated
entries fail before a model or artifact is created.

The controller then launches the worker with the exact prepared interpreter
and `-B -s -P`. `-I` is forbidden for the worker because it implies `-E` and
silently ignores `PYTHONHASHSEED`. The first worker receipt must show `isolated=0`,
`ignore_environment=0`, `safe_path=1`, `no_user_site=1`,
`dont_write_bytecode=1`, `no_site=0`, user site disabled,
`sitecustomize is sys`, and exactly this ordered `sys.path`:

```text
/opt/homebrew/Cellar/python@3.12/3.12.12/Frameworks/Python.framework/Versions/3.12/lib/python312.zip
/opt/homebrew/Cellar/python@3.12/3.12.12/Frameworks/Python.framework/Versions/3.12/lib/python3.12
/opt/homebrew/Cellar/python@3.12/3.12.12/Frameworks/Python.framework/Versions/3.12/lib/python3.12/lib-dynload
<prepared-pinned-root>/.venv/lib/python3.12/site-packages
<prepared-pinned-root>
```

The controller never copies or subtractively filters `os.environ`. It creates
the worker environment from an empty mapping with exactly these twenty keys
and no others:

```text
PATH=/usr/bin:/bin
LANG=C
LC_ALL=C
HOME=<private-runtime-scratch>/home
TMPDIR=<private-runtime-scratch>/tmp
XDG_CACHE_HOME=<private-runtime-scratch>/cache
PYTHONHASHSEED=249709497
OMP_NUM_THREADS=4
OMP_DYNAMIC=FALSE
OMP_SCHEDULE=static
OMP_PROC_BIND=FALSE
MKL_NUM_THREADS=4
MKL_DYNAMIC=FALSE
OPENBLAS_NUM_THREADS=1
VECLIB_MAXIMUM_THREADS=4
NUMEXPR_NUM_THREADS=4
NUMEXPR_MAX_THREADS=4
BLIS_NUM_THREADS=1
CUDA_VISIBLE_DEVICES=
__CF_USER_TEXT_ENCODING=0x1F5:0x0:0x0
```

The three private scratch directories are newly created, empty, mode `0700`,
outside the evidence directory and are normalized to
`<private-runtime-scratch>` only in the protocol digest; the receipt also
records their literal resolved paths. The complete sorted input map, normalized
map, and first-line worker-observed map are hashed and must agree exactly.
Every unlisted loader, OpenMP/KMP behavior, Python, Torch, distributed, proxy,
cache, locale, checkpoint, W&B, or application variable is absent rather than
merely overwritten after startup. Unit and subprocess tests inject
`DYLD_INSERT_LIBRARIES`, `DYLD_LIBRARY_PATH`, `LD_PRELOAD`,
`OMP_DYNAMIC=TRUE`, `OMP_SCHEDULE=dynamic,1`, and unlisted `KMP_*`; the
environment validator must reject them before the target interpreter `exec`
probe is called.

Only after that runtime postcheck may the worker dynamically import NumPy,
Torch, Puffer, or the compiled module. The controller and independent verifier
repeat all startup, tree, and site-packages hashes after each worker exits.
This detects ordinary drift that persists across a validation boundary; it is
not an immutable source snapshot. From the first outer preflight through every
controller/verifier worker import and file use, every postflight, both
publication commits, and the final consumer's last stored-evidence read, the
protocol explicitly assumes no hostile concurrent filesystem mutation by the
same UID or another principal with write access. In particular, a
mutate/use/restore ABA between endpoint hashes is outside the evidence claim.
Protocol-owned namespaces separately require the zero-ACL private modes below,
but those modes do not protect against their owning UID. Watched ordinary
mutation fixtures add a second executable `.pth`, alter the allowed `.pth`,
inject `sitecustomize.py`, alter `sys.path`, and mutate an installed package
file, source-root bytecode, and sourceless bytecode, and must all fail before
model construction or at the next postflight; adversarial ABA is a named trust
boundary, not a tested exclusion.

The runner must independently inspect module metadata and hashes for the pilot;
it must not import or execute the foundation reference checker. The evidence
records the complete prepared-Puffer status digest, interpreter identity,
installed-distribution receipt, closed site-packages manifest, module metadata,
module hash, and exact closed Python/config source manifest. The verifier
requires the same live prepared root and rejects a missing, extra, or changed
Python/config or site-packages entry. The pilot does not claim that a
worker-authored receipt can independently prove a historical build; it relies
on the immediately preceding independently qualified F5 lifecycle and
independently authenticates the live module it actually executes.

A different host model, OS, kernel, architecture, Python or Torch build,
module, Puffer tree, installed package tree, or source commit requires a newly
reviewed protocol or an explicit portability qualification. Linux x86 and
NVIDIA execution remain pending external boundaries rather than silently
equivalent evidence.

## Frozen environment contract

The runner must load the tracked 51-key
`training/f5_trainability_env.json` byte-for-byte and replace the generic
Puffer environment mapping with that object. The resulting role requires:

- exact deterministic F5 reset;
- `seed = 1`;
- `max_decisions = 8`;
- `macro_moves = 0`;
- `reward_td = 1.0`;
- every shaping and result reward `0.0`;
- state-bank kind `NONE`;
- demo reset percentage `0.0`;
- no selectors, forced teams, scripted opponent, or skill entropy; and
- no caller-supplied environment keys.

The qualification module performs strict pre-allocation validation. The pilot
also compares the effective mapping to the tracked canonical object before
vector construction and records its canonical digest.

## Rollout-alignment prerequisite

The accepted F5 foundation proved the exact reference route, several legal
route corruptions, a 721-route safe Move subset, and 100,000 sampled
masked-uniform episodes. It did **not** prove a universal no-early-terminal
theorem. The Torch training collector resets the whole recurrent state at a
training-rollout boundary and its recurrent training pass cannot reset
individual rows inside a sampled horizon. Therefore an accepted PPO update may
contain only episodes whose first seven decisions are nonterminal and whose
eighth decision is terminal.

An adversarial feasibility audit rejected the draft universal graph as an
unnecessary and operationally unbounded prerequisite. A much narrower
zero-dice Move-only enumeration already replayed 37,206 prefixes in about 23.6
seconds; a complete tree adds blocks, passes, rerolls, armour, injury,
casualty, and variable-length dice. The draft's ten-million full-state bound
would also imply about 402 GB at the measured 40,256-byte `Bloodbowl` size.
Replacing that with a selective semantic hash could falsely merge different
legal futures. This plan consequently makes no universal reachability claim
and does not use a graph receipt as evidence.

Instead, actual-sequence rollout alignment is a hard pre-update gate:

1. One gate is invoked immediately after every complete training `rollouts()`
   call and immediately before the corresponding `train()` call.
2. All 4,096 rollout-boundary canaries in `terminals[0]` must be zero.
3. All `7 * 4,096` entries in `terminals[1:8]` must be zero, covering
   decisions 1–7 under the delayed-row contract.
4. All 4,096 entries in `tail_terminals` must be one, covering decision 8;
   Home/Away terminal pairs must agree for every match.
5. The same vector log must show exactly 2,048 completed eight-decision
   episodes, no error, no illegal action or projection collision, and no second
   episode from an early autoreset.
6. Any mismatch aborts before the optimizer is entered, invalidates the whole
   run, attempts only an `integrity-abort` receipt in the incomplete
   container, and leaves no checkpoint from that rollout; receipt failure does
   not weaken the abort.

Evaluation applies the identical first-seven-zero/eighth-one check before
accepting any success bitset. Evaluation mode already resets recurrent rows on
terminals, but this stricter gate preserves exactly one episode per
eight-decision vector rollout and keeps evaluation arithmetic paired with
training.

Watched real-stack tests inject an early terminal at each delayed row and prove
the optimizer, epoch, accepted global-step ledger, and checkpoint writer are
never entered. Each injected-abort test snapshots and requires byte/semantic
equality of model parameters, optimizer state, epoch, checkpoint directory,
and accepted evidence ledger before and after the fault. `rollouts()` itself
necessarily advances the learner's volatile collector `global_step` by 32,768
before the gate; the test requires that exact increment, quarantines it in the
failure receipt, and proves the poisoned learner is discarded rather than
committed to accepted progress. Other fixtures cover a nonzero
`terminals[0]` canary, a natural early Home touchdown with no terminal, the
ordinary decision-eight cap, ERROR, empty-legal, delayed empty-legal detection
after seven actual actions, asymmetric terminal, and autoreset/log-count
mismatches. The delayed-empty fixture deliberately proves that a terminal which
lands in the nominal eighth vector slot cannot pass merely by position: episode
length and error/log invariants must still identify its seven-action episode.
Static source review independently confirms that the pinned wrapper
terminalizes only ERROR, empty legal support, `MATCH_OVER`, or
`decisions >= max_decisions`, while a rules-level touchdown does not itself
terminalize the F5 episode.

The runtime transaction distinguishes the learner's volatile
`global_step`, the session's accepted global-agent-step counter, and its
append-only accepted trace-row ledger. `rollouts()` may advance only the first.
Only after rollout validation succeeds, the optimizer update completes, and
the complete trace row passes schema and semantic validation may the row be
appended and accepted progress advance; an optional fixed-schedule checkpoint
follows that accepted-update commit. A rejected rollout never appears in the
accepted ledger.

An integrity failure marks the session discarded before attempting a receipt,
closes or makes the learner/vector unreachable, and rejects every later
same-session operation before another rollout. Receipt failure cannot undo the
discard. The real watched early-terminal matrix uses seven independent fresh
sessions. Each first commits one real update, requiring epoch one, accepted
step 32,768, one accepted trace row, the frozen one-update raw/canonical
parameter digests, and seven nonempty real Muon momentum buffers totaling
879,900 bytes. The one-update raw `.f5w` digest is exactly
`0eff42539736bc01d67282e1c98a864f4e76a4ef91951d9f4749d3251b60a9b8`;
the canonical tensor digest is exactly
`bd1410bd0725f4074d6fd63fd4e59b78ab77dbcf8dceea72261c948283a889d4`.
It then injects exactly one Home/Away terminal pair at each delayed row 1
through 7 for match zero, flat agent rows exactly `[0,1]`, through a test-owned
wrapper around the real compiled `cpu_step`.
The test installs no-I/O tripwires at optimizer dispatch, accepted-commit
dispatch, fixed-checkpoint schedule dispatch *before* its update-membership
filter, and worker success-frame emission. This makes the checkpoint assertion
nonvacuous even though rejected update index one is not a fixed checkpoint.
It requires: volatile step 65,536; accepted step and epoch still 32,768/one;
byte-identical model, optimizer, accepted ledger, and in-memory checkpoint
serialization inputs; zero tripwire calls after the poisoned gate; a discarded
learner; a canonical rollout-alignment receipt derived from the production
error rather than the injected input; and same-session reuse rejected before
another rollout. A paired supervisor test starts from empty private spool and
destination topology, accepts only the sole failure frame, and proves no
success-frame temporary or final leaf is created. The seven real cases run
serially in one prepared-Python process, with one learner live at a time, a
90-second hard test timeout, and an expected duration below 60 seconds.

“Byte-identical optimizer state” is an exhaustive test-owned Muon snapshot,
not a comparison of momentum buffers alone. The live optimizer must be exactly
class `pufferlib.muon.Muon`, with exactly one parameter group; `defaults` and
that group have exactly `lr`, `weight_decay`, `momentum`, and `eps` (plus
`params` in the group); the parameter objects map bijectively to the seven
named policy tensors; and `state` has exactly those seven parameter keys, each
with only `momentum_buffer`. Defaults and group scalars are encoded as the 16
lowercase hex characters of `struct.pack(">d", float(value))`; group `params`
are exactly this ordered tensor-name array, preserving the live
`Policy.parameters()`/Muon construction order rather than checkpoint
lexicographic order:

```text
encoder.encoder.weight
encoder.encoder.bias
decoder.decoder.weight
decoder.decoder.bias
decoder.value_function.weight
decoder.value_function.bias
network.layers.0.weight
```

State rows are independently sorted by UTF-8 tensor name and close each CPU
strided contiguous float32 momentum tensor over exact name, dtype, shape,
stride, storage offset, element count, byte count, requires-grad flag, raw
SHA-256, and raw little-endian C-order bytes.

The snapshot frame is:

```text
ASCII "bloodbowl-f5-muon-snapshot-v1\0"
uint64-be canonical_metadata_byte_count
canonical ASCII JSON metadata bytes with one LF
for each state row in metadata order:
    uint64-be raw_momentum_byte_count
    exact raw momentum bytes
```

The metadata schema/name, exact class, defaults, group, state descriptors, and
row order are closed. The watched serializer is independent of production,
and its mutation matrix proves that every scalar, parameter order/membership,
state key, tensor metadata field, and tensor byte changes the framed bytes.
The before/after test also compares the exact raw `.f5w` model bytes, canonical
accepted-ledger JSONL bytes, and in-memory fixed-checkpoint serialization input.
Thus a poisoned gate cannot mutate learning rate, defaults, parameter groups,
or an unobserved optimizer field while leaving only seven buffers unchanged.

This is an empirical integrity guarantee over every one of the 6,053,888
training episodes and every fixed evaluation episode actually used by the
pilot. It is not a theorem about every possible legal F5 transcript. If a
sampled trajectory violates alignment, the next independently reviewed tranche
must repair terminal-aware recurrent training and multi-episode accounting (or
redesign the task horizon); this pilot may not replace the abort with ignored
rows, sampling-based reassurance, or a result-dependent retry.

## Frozen PPO recipe

### Vector and recurrence

```text
backend                     Torch CPU (`slowly = true`)
total agent rows            4,096
agent rows per match        2, identity ordered [Home, Away]
matches / episodes/update   2,048
vector buffers              1
Puffer vec.num_threads      20 (inert compatibility input on pinned CPU binding)
CPU-step OpenMP request     OMP_NUM_THREADS=4, OMP_DYNAMIC=FALSE
frozen banks                0
frozen-bank percentage      0.0
horizon                     8
recurrent reset             true
```

The configured `vec.num_threads=20` is retained because it is part of the
frozen effective Puffer argument mapping, but it is not an execution-thread
claim. In the pinned CPU binding, `create_vec` consumes `total_agents` and
`num_buffers` but does not consume `num_threads`; synchronous `cpu_vec_step`
reaches `_static_vec_env_step`, whose
`#pragma omp parallel for schedule(static)` has no `num_threads` clause.
Consequently, CPU step parallelism is requested by the already-frozen process
environment (`OMP_NUM_THREADS=4`, `OMP_DYNAMIC=FALSE`), not by the inert
Puffer field. Evidence must record both values and their distinct meanings and
must reject any claim that the literal `20` governed the CPU OpenMP team. The
pilot claims only the authenticated OpenMP request, not that the runtime
necessarily formed four workers on every loop.

The eight-step horizon is semantic, not a throughput tuning knob: one rollout
contains exactly one complete F5 episode per match, recurrence spans the full
decision sequence, and the repaired tail supplies the eighth reward and
terminal to training. No episode may cross a training-rollout boundary.

### Policy

```text
encoder                     Puffer DefaultEncoder
recurrent network           MinGRU
decoder                     Puffer DefaultDecoder
hidden size                 64
recurrent layers            1
expansion factor            1
expected trainable params   219,975
state tensors               7 float32 tensors / 879,900 raw bytes
precision                   float32
```

Seeded construction order is part of the policy definition. The worker must
use four separate statements in the pinned `torch_pufferl.load_policy` order:

```text
network = MinGRU(...)
encoder = DefaultEncoder(...)
decoder = DefaultDecoder(...)
policy = Policy(encoder, decoder, network)
```

Python left-to-right construction of `Policy(DefaultEncoder(...),
DefaultDecoder(...), MinGRU(...))` is not equivalent because it consumes the
Torch initialization stream in encoder/decoder/network order. A watched
wrong-order counterfixture must produce a different canonical tensor digest
and fail before checkpoint zero is published. Under model seed `1937413891`,
the correct order has canonical tensor SHA-256
`61e509fc5759940cedf557ea773d3d89bff35d2897082916c80a2f65c88c8882`
and raw `.f5w` SHA-256
`7d1a0e03f06b2f5e6142159b41a42bc07e01dca5400d8c4084ca6ea455e16007`.
The encoder/decoder/network wrong-order counterfixture instead has canonical
SHA-256
`97caeec26dcfefd621f9c51ea94c71254b650f66cfbbaa508fdae5dfd1514d60`
and must be rejected. The watched real-stack one-update smoke, which retains
the full 2,956-update schedule and merely stops after the first completed
update, must reproduce post-update canonical SHA-256
`bd1410bd0725f4074d6fd63fd4e59b78ab77dbcf8dceea72261c948283a889d4`
twice.

The manifest freezes this exact lexicographically sorted state schema:

```text
decoder.decoder.bias          float32 [454]       1,816 bytes
decoder.decoder.weight        float32 [454, 64] 116,224 bytes
decoder.value_function.bias   float32 [1]             4 bytes
decoder.value_function.weight float32 [1, 64]        256 bytes
encoder.encoder.bias          float32 [64]           256 bytes
encoder.encoder.weight        float32 [64, 2782] 712,192 bytes
network.layers.0.weight       float32 [192, 64]   49,152 bytes
```

This small recurrent policy is a fixed-instance acquisition probe, not the
production 512x3 architecture. A failure can therefore implicate exploration,
credit assignment, optimizer behavior, or this representation/configuration;
it cannot isolate one of those causes by itself.

### Optimizer and objective

```text
learning rate               0.0006
learning-rate schedule      cosine, floor ratio 0.1
gamma                       0.995
GAE lambda                  0.85
replay ratio                0.25
minibatch rows              8,192
minibatch recurrent segments 1,024
minibatches/update          1
clip coefficient            0.2
value coefficient           1.0
value clip                  0.5
max gradient norm           1.5
entropy coefficient         0.02
entropy schedule            cosine, floor ratio 0.1
priority alpha              0.8
priority beta0              0.2
V-trace rho/c clips         1.0 / 1.0
Muon momentum/beta1         0.95
Muon weight decay           0.0 (pinned constructor default)
beta2 compatibility field   0.999
Muon eps compatibility field 1e-12
Newton-Schulz norm floor    1e-7 (pinned hard-coded helper default)
```

With a batch of `4,096 * 8 = 32,768` agent rows,
`floor(0.25 * 32,768 / 8,192) = 1` real prioritized recurrent minibatch per
update. It draws 1,024 recurrent segments with replacement: 25% sampled-row
exposure, not 25% unique coverage. Under uniform probabilities the expected
number of unique segments is about 906 of 4,096 (22.1%); prioritization changes
that expectation. This preserves the repository's already-selected replay
exposure under the shortened horizon. Using replay `1.0` with a 32,768-row
minibatch would process four times as many sampled segments and is
intentionally not smuggled into this no-tuning diagnostic.

The standard masked entropy term remains enabled because it is part of the
current PPO exploration objective. It is not environment reward shaping. No
BC coefficient, BC asset, frozen enemy, self-play bank, warm load, load ID,
W&B, sweep, checkpoint resume, scripted row, or native/CUDA path is permitted.

The closed manifest also freezes the trainer-wrapper fields that the direct API
does not use: root `seed` and `train.seed` are both `267803525` (the low
signed-31-bit projection of `2415287173`) as inert compatibility copies of the
authoritative training Torch seed;
`selfplay.seed = 0` while self-play is disabled; `rank = 0`,
`world_size = 1`, `gpu_id = 0`, `train.gpus = 0`, `slowly = true`,
`reset_state = true`, `wandb = false`, `load_id = null`,
`load_model_path = null`, and `train.frozen_enemy_path = ""`.

The canonical manifest contains and hashes one dedicated minimal direct-API
argument mapping. It is not the result of serializing generic
`load_config("bloodbowl")` defaults. Its root has exactly these 16 keys:

```text
env, env_name, gpu_id, load_id, load_model_path, policy, rank, reset_state,
seed, selfplay, slowly, torch, train, vec, wandb, world_size
```

`env` is exact-equal, including types and all 51 keys, to the tracked canonical
`training/f5_trainability_env.json` object. The other scalar root values are
exactly:

```text
env_name="bloodbowl"  gpu_id=0  load_id=null  load_model_path=null
rank=0                reset_state=true        seed=267803525
slowly=true           wandb=false             world_size=1
```

The five remaining nested objects have exactly these canonical JSON values:

```json
{"expansion_factor":1,"hidden_size":64,"num_layers":1}
```

for `policy`;

```json
{"decoder":"DefaultDecoder","encoder":"DefaultEncoder","network":"MinGRU"}
```

for `torch`;

```json
{"enabled":false,"seed":0}
```

for `selfplay`;

```json
{"frozen_bank_pct":0.0,"num_buffers":1,"num_frozen_banks":0,
 "num_threads":20,"total_agents":4096}
```

for `vec`; and:

```json
{"anneal_ent_coef":true,"anneal_lr":true,"beta1":0.95,"beta2":0.999,
 "clip_coef":0.2,"ent_coef":0.02,"eps":1e-12,"frozen_enemy_path":"",
 "gae_lambda":0.85,"gamma":0.995,"gpus":0,"horizon":8,
 "learning_rate":0.0006,"max_grad_norm":1.5,
 "min_ent_coef_ratio":0.1,"min_lr_ratio":0.1,"minibatch_size":8192,
 "prio_alpha":0.8,"prio_beta0":0.2,"replay_ratio":0.25,
 "seed":267803525,"total_timesteps":96862208,"vf_clip_coef":0.5,
 "vf_coef":1.0,"vtrace_c_clip":1.0,"vtrace_rho_clip":1.0}
```

for `train`. Whitespace in these explanatory blocks is not data; the tracked
manifest uses the canonical serializer. The runner rejects a missing, extra,
or changed root or nested field rather than letting generic defaults become an
unrecorded input. In particular, generic loader-only checkpoint/log/eval,
render, W&B, sweep, BC, `update_epochs`, enemy-load, or asset-path keys are
absent and an attempted addition is fatal. A one-update smoke uses this same
mapping and stops after one manually driven update; it does not shorten
`total_timesteps` or alter either schedule.

The pinned Muon implementation uses `beta1` as momentum. It stores but does not
currently consume the configured `eps`, and the Torch trainer does not pass
`beta2` into Muon. The evidence labels those two values compatibility fields
rather than claiming they affect the update.

### Prospective RNG and execution contract

The tracked protocol manifest stores these exact unsigned 32-bit seeds:

```text
Python process RNG          249709497
NumPy process RNG           3265398457
model initialization        1937413891
training action/priority    2415287173
evaluation construction    38865036
evaluation action seeds     [
  2363161776, 2079938504, 2486426431, 1428436532,
  3852947533, 1935602315, 2884042901, 2683991200
]
```

They are the first four big-endian SHA-256 bytes of the following exact byte
domains:

```text
"bloodbowl-f5-recurrent-ppo-pilot-v1\0python"
"bloodbowl-f5-recurrent-ppo-pilot-v1\0numpy"
"bloodbowl-f5-recurrent-ppo-pilot-v1\0model-init"
"bloodbowl-f5-recurrent-ppo-pilot-v1\0train-torch"
"bloodbowl-f5-recurrent-ppo-pilot-v1\0eval-construction"
"bloodbowl-f5-recurrent-ppo-pilot-v1\0eval-0"
"bloodbowl-f5-recurrent-ppo-pilot-v1\0eval-1"
"bloodbowl-f5-recurrent-ppo-pilot-v1\0eval-2"
"bloodbowl-f5-recurrent-ppo-pilot-v1\0eval-3"
"bloodbowl-f5-recurrent-ppo-pilot-v1\0eval-4"
"bloodbowl-f5-recurrent-ppo-pilot-v1\0eval-5"
"bloodbowl-f5-recurrent-ppo-pilot-v1\0eval-6"
"bloodbowl-f5-recurrent-ppo-pilot-v1\0eval-7"
```

The literal manifest values and these literal derivation domains must agree.
The outer controller constructs the complete literal twenty-key worker map
above from empty and includes `PYTHONHASHSEED=249709497`; changing, omitting,
or adding a key is fatal. A watched two-process canary requires the same
literal `hash("f5-recurrent-ppo-pilot")` value,
`7634427924950824650`, in both workers and rejects the `-I` launch form.

The worker must:

1. require the complete literal worker environment and prove that no inherited
   key reached the target process;
2. require the already-set literal `PYTHONHASHSEED=249709497`;
3. set Python, NumPy, and Torch initialization seeds before constructing the
   first policy;
4. enable `torch.use_deterministic_algorithms(True)`;
5. set Torch intra-op threads to `4` and inter-op threads to `1`;
   require the already-normalized OpenMP, MKL, OpenBLAS, Accelerate, BLIS, and
   NumExpr variables before importing Torch;
6. run on CPU and reject CUDA availability as a selected device;
7. construct the model and record a canonical tensor digest;
8. independently reconstruct the same initialization and require the same
   canonical digest;
9. reseed Torch to the training action/priority seed immediately before the
   first rollout; and
10. record canonical Python, NumPy, and Torch RNG-state digests before and
    after training.

Torch action sampling and prioritized-row sampling share one global generator
in the pinned trainer, so they share the declared training Torch stream. The
pilot must not patch that behavior during this tranche.

Each evaluation runs in a fresh isolated worker. It constructs a throwaway
model/vector under the evaluation-construction seed, loads one frozen raw
`.f5w` tensor file through the fixed-schema loader, and only then seeds Python,
NumPy, and Torch with the declared evaluation action seed. Throwaway
construction therefore cannot shift the evaluation action stream.

### Exact identity and RNG digest preimages

Every `source.status_sha256` and `puffer.status_sha256` value uses the raw
stdout bytes from exactly:

```text
env -i PATH=/usr/bin:/bin LANG=C LC_ALL=C \
  git -C <root> status --porcelain=v1 --untracked-files=all
```

The command must exit zero, write an empty stderr, use LF line endings only,
and emit no NUL or carriage-return byte. The digest is:

```text
SHA256(ASCII "bloodbowl-f5-git-status-v1\0" || raw stdout bytes)
```

The final Blood Bowl source status is exactly empty and therefore has the
literal digest
`d57a6da845e01509ea868319ed03d107dcf81a5bd5cd323775eb7399b18600fa`.
The prepared Puffer root has exactly 3,437 status bytes and the literal digest
`60ff30fe6d00bd26ff2e7b2c041b44db2f1cade0dc3577c13e070dc7a7de57f2`.
The protocol owns both expected digests. Splitting lines, decoding/re-encoding,
sorting, stripping the terminal LF, or hashing a JSON projection is forbidden.

`startup.worker_environment_sha256` hashes the normalized exact twenty-key
`startup.worker_environment` map, including the three literal
`<private-runtime-scratch>` values, serialized with the canonical JSON
serializer and one LF:

```text
SHA256(
    ASCII "bloodbowl-f5-worker-environment-v1\0"
    || canonical normalized worker-environment bytes
)
```

Its prospectively frozen digest is
`de1e11609f4c0bec54a69894149f0200a3a41d94352fac3eb529b1290a0015da`.
Resolved scratch paths appear only in the separately typed
`startup.scratch_paths.resolved` map and never enter this digest.

`audit.opened_paths` is precisely the Python audit hook's open-*attempt* set,
not an OS-wide successful-open trace. A script-level hook cannot observe
CPython reads before script execution. Its explicitly excluded pre-hook phase
is native loader/interpreter bootstrap, encoding and standard-library startup
imports, `pyvenv.cfg`, site initialization and exact `.pth` processing,
sitecustomize probes, and loading/decoding the already outer-authenticated
worker script itself. Those accesses are bounded instead by the frozen
interpreter/stdlib trust boundary, executable/runtime hashes, closed
site-packages manifest, exact `.pth`, zero-sitecustomize preflight, exact
implementation manifest, and startup receipt.

The committed worker has one statically frozen minimal bootstrap prefix:
obtain the already loaded built-in `sys` module, obtain the already loaded
built-in `posix` module from `sys.modules`, call `posix.umask(0o077)` as the
first process-state protocol operation and never restore it, and obtain the
already loaded built-in `_signal` module. It blocks
`SIGHUP/SIGINT/SIGQUIT/SIGTERM`, requires none was inherited blocked, requires
the prior dispositions to be `SIG_DFL`, Python's `default_int_handler`,
`SIG_DFL`, and `SIG_DFL` in that numeric order, resets all four to `SIG_DFL`,
and restores the inherited mask. It then obtains the already loaded frozen
`os` module from `sys.modules`, creates in-memory receipt state, defines the
hook, and calls `sys.addaudithook`. The previous umask is exposed only to watched
instrumentation and is never evidence. Apart from the exact umask/signal
process-state calls, this prefix performs no filesystem, network, dynamic
import, model, or environment access.
The signal normalization is the only other pre-hook process-state mutation and
ensures every supervisor- or externally delivered signal death is silent:
there is no Python `KeyboardInterrupt` traceback to race stderr classification.
The hook is active at the first possible subsequent script-controlled
operation, before importing the protocol helper, NumPy, Torch, Puffer, or the
compiled module. A watched exact-interpreter subprocess proves both sides of
this boundary: named bootstrap/site sentinels are already in `sys.modules`
before the prefix: `encodings` at the exact Homebrew
`lib/python3.12/encodings/__init__.py` origin and `os`, `site`, and
`_sitebuiltins` with literal origin `"frozen"`. The first post-install marker
open and every subsequent Python open attempt must then be captured. No test
or claim retroactively attributes pre-hook reads to `audit.opened_paths`.

The hook records exactly events whose name is `"open"`, including attempts
that later fail. CPython applies `PyOS_FSPath` before emitting this event, so
the contract applies to the post-coercion event value and cannot identify the
caller's original type. The event argument tuple must have length three: its
post-coercion path must be an absolute ASCII `str`; mode must be `None`, `"r"`,
or `"rb"`; and flags must be a non-Boolean integer whose `O_ACCMODE` is
`O_RDONLY` with none of `O_WRONLY`, `O_RDWR`, `O_APPEND`, `O_CREAT`, `O_TRUNC`,
or `O_EXCL`. An original `PathLike` returning an accepted `str` is therefore
indistinguishable from and treated exactly like that `str`; a `PathLike`
returning `bytes` reaches the hook as `bytes` and rejects. Relative strings,
post-coercion `bytes`, integer file descriptors, writable modes/flags, and
malformed event tuples abort. Accepted workers do not open filesystem output;
they return typed bytes/records to the stdlib supervisor, which alone owns
evidence writes.

The worker cwd is the descriptor-proved prepared Puffer root and may never
change; any `os.chdir` or `os.fchdir` audit event aborts. Requiring every
`"open"` path itself to be absolute makes a hidden `dir_fd` irrelevant for an
accepted event and rejects the relative-path case whose base the Python audit
event does not expose. Before tokenization, the absolute string must begin
with `/`, contain only printable ASCII bytes `0x20` through `0x7e`, contain no
backslash, empty interior, `"."`, or `".."` component, and equal
`os.path.realpath(path, strict=False)`. Thus NUL/C0/DEL controls, lexical
traversal, repeated separators, and symlink components reject even for a
failed open attempt.

The only accepted physical paths are under these independently
descriptor-proved roots, substituted by longest component-boundary match:

```text
exact Blood Bowl worktree root       -> <bloodbowl-source>
exact completed/build artifact root  -> <artifact>
exact prepared Puffer root           -> <prepared-puffer-root>
exact private runtime scratch root   -> <private-runtime-scratch>
exact Homebrew Python 3.12.12 prefix -> <prepared-python-prefix>
```

The root itself becomes exactly its token; a descendant becomes
`<token>/<POSIX-relative-suffix>`. The sole outside-root literal exception is
the pinned Torch platform probe `/proc/self/maps`, normalized exactly to
`<absent-linux-proc-self-maps>`; on Darwin it is an allowed failed read probe,
not an allowed source of bytes. Every other outside-root attempt aborts. The
result is deduplicated and sorted by ASCII/UTF-8 bytes. The access allowlist
owns the exact allowed normalized paths/prefixes and rejects any reference,
BC, alternate artifact, network credential, or unmanifested source path.
Each individual worker receipt and each controller/verifier aggregate contains
at most `65,535` unique normalized paths. This is a prospective, result-blind
resource cap, not a claim about the observed cardinality or a substitute for
the exact allowlist. The audit recorder rejects the 65,536th distinct
per-worker token before the attempted operation and before producing a
receipt. Independently, before adding each new token, it prospectively requires
that the canonical ASCII JSON opened-path array bytes, including their one
final LF, remain at most `3,145,728` bytes; this bound makes the four-mebibyte
typed-result limit below enforceable. The
controller and verifier each build their union incrementally and apply both
limits before materializing or returning an accepted aggregate. Either
overflow is an `integrity-abort`, not a resource-truncation or learning
outcome. The `opened_paths` schema therefore freezes `minimum_length = 1` and
`maximum_length = 65535`; the semantic validator separately requires ASCII
byte ordering, uniqueness, token grammar, exact root/prefix allowlisting, the
3,145,728-byte canonical limit, and the framed digest.

The hook counts any event whose name starts with `"socket."` as a Python
network attempt and raises before the operation; a completed worker therefore
has exactly zero. It also rejects `subprocess.Popen`, `os.system`,
`os.posix_spawn`, and `pty.spawn`. `audit.opened_paths` and
`audit.network_attempts` make claims only about Python audit events. Direct
`libc` file or network operations inside a native extension are not surfaced
by this receipt and remain bounded only by the fixed module/dependency
identities, static forbidden-input checks, endpoint hashes, and the declared
full-lifetime no-hostile-ABA trust boundary.

Every prepared-Python worker installs this same hook and returns a separately
validated canonical audit receipt with its typed result. The training receipt
schema is `bloodbowl-f5-training-worker-audit-v1` and has exactly:

```text
network_attempts, opened_paths, opened_paths_sha256, schema, worker_kind
```

with `worker_kind = "training"`. The evaluation receipt schema is
`bloodbowl-f5-evaluation-worker-audit-v1` and has exactly:

```text
action_seed, checkpoint_update, network_attempts, opened_paths,
opened_paths_sha256, repeat_flag, schema, seed_index, worker_kind
```

with `worker_kind = "evaluation"` and the exact checkpoint/seed/repeat tuple
for that process. Each receipt owns its own sorted unique path array and digest
under the domain below; `network_attempts` must be zero. The tracked protocol's
`execution.audit` object freezes both schemas, the pre-hook exclusion, exact
normalization rules, worker populations, and aggregation.

The controller population is exactly 57 receipts: one training worker, 48
primary workers for six checkpoints by eight action seeds, and eight
checkpoint-zero-repeat workers. `identity.audit.opened_paths` is the sorted set
union across all 57 arrays, `identity.audit.opened_paths_sha256` frames that
union, `identity.audit.network_attempts` is their exact integer sum and must be
zero, and `identity.audit.worker_count` is exactly `57`. Missing, duplicate,
mislabelled, or out-of-order checkpoint/seed/repeat worker identities abort
before the evidence manifest.

The independent verifier population is exactly 56 fresh replay workers: 48
primary plus eight checkpoint-zero-repeat workers. The same aggregation is
stored under `verdict.audit`, with `worker_count = 56`; its exact fields are
`network_attempts`, `opened_paths`, `opened_paths_sha256`, and `worker_count`.
The canonical verdict bytes and precommit expected-verdict digest therefore
bind the verifier-side access receipt after the immutable evidence manifest
has closed. Neither aggregate includes the separately bounded pre-hook phase,
and neither silently combines controller and verifier workers.

### Bounded supervisor/worker IPC

At script entry, each committed script's minimal bootstrap imports only the
built-in `sys` module and reads an in-memory copy of `sys.argv[1:]` to select a
mode; neither operation opens a Python source file or mutates process state. A
first token equal to `--internal-f5-worker` selects internal-worker mode, whose
closed grammar requires no remaining token. The exact private
publication-child token
`--internal-f5-controller-publication-child` or
`--internal-f5-verdict-publication-child`, when it is the first token, selects
the corresponding publication child. Each internal branch validates its
remaining closed grammar and rejects a mismatch as an internal integrity
failure; an internal token is never reinterpreted by a public parser.
Otherwise the runner selects its public writer parser. The verifier selects
final-consumer mode only when the first argument is exactly
`"--consume-final"` and selects its writer parser otherwise; either parser
rejects mixed or extra mode tokens. Outside native interpreter/committed-script
loading and the exact built-in `sys`/`posix` cases below, no environment read,
dynamic import, clock, filesystem read/write/creation, network, native call,
or subprocess precedes the selected branch's one `posix.umask(0o077)` call.

Obtaining the mask primitive is mode- and runtime-exact. Both frozen
interpreters preload the built-in `posix` module. The bootstrap obtains
`sys.modules["posix"]`, requires literal origin `"built-in"` and the watched
runtime identity, calls `posix.umask(0o077)` exactly once, and never restores
the previous value. Interpreter/script loading and the built-in `sys` import
are the complete pre-mask read/import boundary; no repository-local or
third-party module, environment value, or protocol-owned path is touched.
The `posix.umask(0o077)` call remains the first process-state mutation and
occurs before every protocol-owned creation or write. All remaining imports
for the selected mode—including Xcode CPython 3.9's stdlib `os` import—occur
afterward. Prepared CPython 3.12 worker mode later obtains its already loaded
frozen `os` module from `sys.modules` without import.

Writer branches then capture their one whole-run start/deadline before public
argument parsing. The read-only final-consumer branch also applies the one
umask call, parses its exact arguments, and constructs no whole-run deadline.
An internal-worker branch applies its one umask call, installs and later seals
the audit hook as specified below, constructs its fixed worker operations once,
and reaches its owning script's `_run_internal_worker` exactly once. A
publication-child branch applies its one umask call, performs the same blocked
four-signal reset to `SIG_DFL`, validates its closed private grammar,
constructs its fixed construction-only publication operations once, and
reaches its named publication-child driver once; it does not install the
prepared-worker audit hook. No internal token is admitted by a public parser.

Prepared Python workers never write evidence files. Each is invoked exactly as
the prepared Python executable with `-B -s -P`, its absolute committed owning
writer path, and the fixed internal token `--internal-f5-worker`. The
controller's training and evaluation workers use the runner path; the
verifier's replay workers use the verifier path. The token is intercepted by
each owning script's bootstrap and is never accepted by either public
`parse_args`.
Standard input is the one-shot job channel, standard output is the result
stream, and standard error is captured separately. The spawn uses
`close_fds=True`, `start_new_session=True`, the exact twenty-key environment,
and the descriptor-proved prepared-Puffer cwd. No additional descriptor is
inherited. Direct internal invocation without pipe-shaped standard
descriptors, a canonical one-shot job, exact source/runtime identities, and a
matching live supervisor PID aborts before an artifact or checkpoint is
opened.

The job channel is exactly:

```text
uint32-be canonical_job_byte_count
canonical ASCII JSON job bytes, including exactly one LF
EOF
```

There is exactly one record and at most 4,096 job bytes. Short or long input,
a second frame, trailing bytes, noncanonical/duplicate-key/non-ASCII JSON,
missing LF, a Boolean integer, or an oversized declared length rejects. Every
job path is canonical printable absolute ASCII and at most 1,024 bytes. A job
nonce is exactly `os.urandom(16).hex()`. Deadlines are type-strict integers in
`[1, 2^63 - 1]`; the supervisor PID is in `[1, 2^31 - 1]`. The job digest is:

```text
SHA256(
    ASCII "bloodbowl-f5-worker-job-v1\0"
    || complete canonical job bytes
)
```

The training job schema is
`bloodbowl-f5-training-worker-job-v1`, with exactly:

```text
artifact_root, implementation_manifest_sha256, nonce, protocol_sha256,
puffer_root, schema, source_commit, source_root, supervisor_pid,
training_deadline_monotonic_ns, whole_deadline_monotonic_ns, worker_kind
```

`worker_kind` is exactly `"training"` and the training deadline does not
exceed the whole deadline. No checkpoint, resume state, retry number, seed,
budget, device, or output override exists. The evaluation job schema is
`bloodbowl-f5-evaluation-worker-job-v1`, with exactly:

```text
action_seed, artifact_root, checkpoint_raw_sha256,
checkpoint_tensor_sha256, checkpoint_update,
implementation_manifest_sha256, nonce, population, protocol_sha256,
puffer_root, repeat_flag, schema, seed_index, source_commit, source_root,
supervisor_pid, whole_deadline_monotonic_ns, worker_kind
```

`worker_kind` is exactly `"evaluation"`; `population` is `"controller"` or
`"verifier"`; and the checkpoint/update/seed/repeat/action tuple must be the
next exact member of that population's manifest-owned ordered list. The
checkpoint path is derived from `artifact_root` and `checkpoint_update`, never
supplied.

Every worker result frame is:

```text
uint32-be canonical_header_byte_count
canonical ASCII JSON header bytes, including exactly one LF
exact payload bytes declared by the header
```

The closed header schema is
`bloodbowl-f5-worker-payload-header-v1`, with exactly:

```text
bytes, frame_index, job_sha256, kind, logical_name, nonce, raw_sha256,
schema, semantic_sha256
```

A header is at most 4,096 bytes. The supervisor validates the next expected
index/kind/name and a safe payload cap before reading the payload, then drains
and hashes it incrementally in chunks no larger than 65,536 bytes into its own
private temporary file. It never allocates from an unchecked worker length.
The raw digest covers the exact payload. Semantic digests use the already
frozen trace, checkpoint, and bitset domains, or
`f5-canonical-json-v1` for typed JSON result/failure payloads. Job digest and
nonce must equal the request. Standard output and standard error are drained
concurrently; `wait()` or `communicate()` before both pipes are drained is
forbidden.

Because the public writer process keeps its full-lifetime prohibition on
repository-local imports, its supervisor performs framing through the
script-local operations parser rather than importing a protocol parser class.
Canonical request binding is explicit and begins a fresh parser session for
each worker supervision. That session retains bounded partial-header state and
the active frame's spool and incremental hasher across arbitrary stdout
fragmentation. Frame finalization occurs only after the final payload chunk has
passed its aggregate check, updated the hasher, and reached the private spool;
stdout finalization occurs only after a zero-byte read has actually observed
descriptor EOF, never after EAGAIN or loop exhaustion.

Header and binding leaf types are closed. `bytes` and `frame_index` are
type-strict nonnegative JSON integers, with `bytes` bounded by the
kind-specific limit and `frame_index` equal to the next expected index.
`job_sha256`, `raw_sha256`, and `semantic_sha256` are exactly 64 lowercase
hexadecimal characters; `nonce` is exactly the authenticated 32-character
lowercase hexadecimal job nonce. `kind`, `logical_name`, and `schema` are
exact ASCII literals from the expected sequence. A frame binding repeats the
same observed integer/digest/name values and admits no additional field.
Evaluation `successful_episodes` is a type-strict integer in `[0,32768]`;
all job and result seed/update/count fields are type-strict integers within
their already frozen seed/update/population ranges and reject Booleans.

A successful training stream has exactly eight frames and EOF, in this order:

```text
0  training-trace   training-trace.jsonl                    1..16,777,216
1  checkpoint       checkpoints/update-000000.f5w           879,900
2  checkpoint       checkpoints/update-000512.f5w           879,900
3  checkpoint       checkpoints/update-001024.f5w           879,900
4  checkpoint       checkpoints/update-001536.f5w           879,900
5  checkpoint       checkpoints/update-002048.f5w           879,900
6  checkpoint       checkpoints/update-002956.f5w           879,900
7  training-result  <training-result>                       1..4,194,304
```

Training payload bytes are capped at 33,554,432 and total wire bytes at
33,587,232. A successful evaluation stream has exactly two frames and EOF:
index zero is one 4,096-byte `evaluation-bitset` at the derived exact `.bits`
path, and index one is a 1..4,194,304-byte `evaluation-result` named
`<evaluation-result>`. Evaluation payload bytes are capped at 8,388,608 and
wire bytes at 8,396,808. Captured stderr is capped at 65,536 bytes and must be
empty for every typed success or failure.

The aggregate payload/wire ceilings are deliberately redundant derived
defense-in-depth limits for these closed sequences, not independently binding
accepted-stream boundaries: the sum of all training per-kind maxima is
26,250,920 bytes and the sum of both evaluation maxima is 4,198,400 bytes,
both below their aggregate payload ceilings, and the closed canonical headers
cannot bridge the corresponding wire gaps. Production still maintains and
checks both counters on every increment. Watched coverage proves the exact
arithmetic and statically proves the two checks are reachable in each drain
loop; it does not claim an impossible otherwise-valid closed stream whose
first failure is an aggregate/wire ceiling.

Typed result records refer to streamed payloads only through a closed frame
binding with exactly `bytes`, `frame_index`, `logical_name`, `raw_sha256`, and
`semantic_sha256`. The training result schema is
`bloodbowl-f5-training-worker-result-v1`, with exactly:

```text
audit, checkpoint_frames, effective_config, initial_parameter_sha256,
initial_reconstruction_sha256, job_sha256, nonce, rng, schema, startup,
trace_frame, training, worker_kind
```

It contains the exact training audit, effective-config, RNG, startup, and
training-results records already defined; its six checkpoint bindings and one
trace binding equal the independently streamed frames; both initialization
hashes equal the frozen initial canonical hash; and `worker_kind` is
`"training"`. The evaluation result schema is
`bloodbowl-f5-evaluation-worker-result-v1`, with exactly:

```text
action_seed, audit, bitset_frame, checkpoint_raw_sha256,
checkpoint_tensor_sha256, checkpoint_update,
construction_parameter_sha256, episode_count, job_sha256,
loaded_parameter_sha256, nonce, population, repeat_flag, schema, seed_index,
successful_episodes, worker_kind
```

It binds the exact evaluation audit/job/bitset, requires
`episode_count = 32768`, requires the construction hash to equal the frozen
initial hash and the loaded hash to equal the checkpoint tensor hash, and
requires the supervisor's independent bit count to equal
`successful_episodes`.

The worker failure schema is `bloodbowl-f5-worker-failure-v1`, with exactly:

```text
cause, job_sha256, nonce, phase, progress, schema, status, worker_kind
```

`phase` is one of `bootstrap`, `training`, `evaluation`, or `serialization`.
Cause membership is worker-kind-specific. A training worker's
`integrity-abort` cause is one of `job-contract`, `runtime-contract`,
`training-contract`, `rollout-alignment`, or `unexpected-exception`; an
evaluation worker's is one of `job-contract`, `runtime-contract`,
`evaluation-contract`, or `unexpected-exception`. `rollout-alignment` is
training-only. A training worker's `resource-truncated` cause is
`training-deadline` or `worker-resource`; an evaluation worker's is
`worker-resource`. Whole-run deadlines, handled signals, and supervisor loss
can never be accepted from a typed worker failure. The otherwise identical
evaluation rollout gate maps every terminal/log mismatch to
`evaluation-contract`.

`progress` is null for every evaluation worker and for a training worker
before learner construction. After training-learner construction, every
caught typed training failure returns one closed `progress` object with
exactly:

```text
accepted_global_agent_step, attempted_update_index, committed_epoch,
learner_disposition, rollout, volatile_global_agent_step
```

`learner_disposition` is always `"discarded"`.
`committed_epoch` is in `[0,2956]`;
`accepted_global_agent_step = committed_epoch * 32768`; and
`volatile_global_agent_step` is either the accepted step or exactly 32,768
greater. `attempted_update_index` is null or equals `committed_epoch` in
`[0,2955]`. It is non-null exactly while an update attempt has begun. When it
is null, volatile equals accepted. A rollout-alignment failure requires a
non-null attempted index and volatile equal to accepted plus 32,768.

`rollout` is non-null only for a training `rollout-alignment` failure and has
exactly:

```text
agent_row_count, agent_rows_bitset_hex, check, delayed_row, mode
```

`mode` is `"training"`. `agent_rows_bitset_hex` is exactly 1,024 lowercase
hexadecimal characters encoding a 512-byte, little-bit-order bitset over rows
0 through 4,095; `agent_row_count` is the type-strict integer popcount in
`[0,4096]`. This bounded representation, not an unbounded row array, owns the
complete offending-row set. `check` is one of `row-zero-canary`,
`early-terminal`, `tail-terminal`, or `home-away-terminal-asymmetry`.
The first three require a positive row count and delayed row exactly zero,
in `[1,7]`, or exactly eight respectively. The asymmetry check requires a
positive row count and delayed row in `[0,8]`. ERROR, empty-legal,
episode-count, episode-length, autoreset, and other flat-log failures use
`training-contract` with `rollout = null`.

Multi-fault selection is deterministic. The gate first scans delayed rows
zero through eight for Home/Away asymmetry in ascending row then match order.
If any exists, it selects the lowest bad delayed row and the bitset contains
both members of every asymmetric pair at that selected row. Otherwise it
checks the row-zero canary, then early-terminal rows one through seven in
ascending order, then the tail at row eight. For a selected row-value check,
the bitset contains every agent row at that one delayed row whose terminal
differs from the required value. Later row/topology/log faults do not alter
the selected `check`, row, or bitset. Only after all terminal-topology checks
pass does the gate validate ERROR, empty-legal, episode/autoreset counts,
length, and remaining flat-log invariants in their manifest-owned projection
order.

The watched early-terminal cases require exactly
`committed_epoch = 1`, `accepted_global_agent_step = 32768`,
`attempted_update_index = 1`, `volatile_global_agent_step = 65536`,
`check = "early-terminal"`, delayed row equal to the injected row, row count
two, and exactly the injected Home/Away row bits.

The valid `(worker_kind, status, phase, cause, progress)` combinations are
closed rather than independently mixed:

```text
training  integrity-abort     bootstrap      job-contract|runtime-contract|
                                            unexpected-exception       null
training  resource-truncated bootstrap      worker-resource            null
training  integrity-abort     training       training-contract|
                                            rollout-alignment|
                                            runtime-contract|
                                            unexpected-exception       object
training  resource-truncated training       training-deadline|
                                            worker-resource            object
training  integrity-abort     serialization  runtime-contract|
                                            unexpected-exception       object
training  resource-truncated serialization  worker-resource            object
evaluation integrity-abort    bootstrap      job-contract|runtime-contract|
                                            unexpected-exception       null
evaluation resource-truncated bootstrap      worker-resource            null
evaluation integrity-abort    evaluation     evaluation-contract|
                                            runtime-contract|
                                            unexpected-exception       null
evaluation resource-truncated evaluation     worker-resource            null
evaluation integrity-abort    serialization  runtime-contract|
                                            unexpected-exception       null
evaluation resource-truncated serialization  worker-resource            null
```

No training worker uses phase `evaluation`; no evaluation worker uses phase
`training`; and no other combination validates. Any audit-hook rejection,
forbidden process/cwd/network attempt, sealed-audit violation, or runtime
identity/security-contract failure maps deterministically to
`runtime-contract` in the phase where it occurs, never to the domain contract
or generic unexpected-exception cause.

A failure payload is at most 4,096 canonical bytes and is the sole index-zero
`worker-failure` frame with logical name exactly `<worker-failure>`, followed
by EOF; no failure frame is permitted after any success frame. Before a
canonical job digest and nonce have been authenticated, a failure exits 70
without attempting an unbound failure frame.

Internal worker exits are exactly `0` for success, `70` for
`integrity-abort`, and `75` for `resource-truncated`. Success requires the
exact request, complete ordered stream and EOF, empty stderr, matching exit
zero, all byte/semantic/schema bindings, and source/runtime postflight. A
typed failure requires one valid failure frame and EOF when emission was
possible, empty stderr, and the matching 70/75 exit. Any stderr byte, byte
65,537, partial/reordered/extra/oversized frame, trailing output, mismatched
exit/record, any other exit, unrequested signal death, or postflight drift is
an integrity failure. A crash, broken pipe, serialization failure, or
`SIGKILL` may prevent a typed failure frame; its absence never makes a worker
acceptable. For a success path, every source/runtime postflight and every
operation that may open a file occurs before the typed result is serialized.
The worker then serializes the result containing the current audit receipt in
memory, atomically seals the audit recorder, and emits the already serialized
final frame. Once sealed, the hook rejects every later `open`, `socket.*`,
forbidden process, `os.chdir`, or `os.fchdir` audit event; no import,
postflight, model operation, or filesystem access follows the seal. Only
bounded writes to the already inherited stdout descriptor and process exit are
permitted. Thus an allowed late open cannot escape the final receipt.

`audit.opened_paths_sha256` is:

```text
SHA256(
    ASCII "bloodbowl-f5-opened-paths-v1\0"
    || canonical opened-path array bytes
)
```

The independently constructed empty-array framing vector uses raw canonical
bytes `[]\n` and has digest
`82389ddf7c174161292ce15048b160bef0afd11ac5c57653cdda67883918333d`.
An independent four-root vector serializes exactly:

```text
["<artifact>/checkpoints/a.f5w","<bloodbowl-source>/tools/a.py","<prepared-puffer-root>/pufferlib/z.py","<private-runtime-scratch>/tmp/q"]
```

with one final LF and hashes to
`0d634cba84675ce881906cb3ddc0e8f0064ceb198d08f9ef20d75e907e2598c6`.
The real accepted array is nonempty and is closed by the protocol's exact
access allowlist. Tests construct normalization without the production helper
and own absolute, root-boundary, root-itself, longest-prefix, duplicate,
ordering, missing-path, `/proc/self/maps`, relative, `bytes`, path-like,
integer-fd, symlink, traversal, repeated-separator, writable, cwd-change, and
outside-allowlist vectors. The path-like vector is an end-to-end exact-CPython
test that proves a `PathLike` returning `str` reaches the hook as that `str`
and one returning `bytes` reaches it as rejected `bytes`; it does not claim
that caller-origin type remains observable.

The six training RNG digest fields use these exact state extractions and
preimages:

```text
Python:
  random.getstate() must be a three-tuple
    (3, state_tuple, gauss_next)
  state_tuple has exactly 625 integers: the first 624 are uint32 and the
    final element is an index in [0,624]
  gauss_next is null or a finite binary64 number
  canonical object:
    {"gauss":gauss_next,"state":[625 integers],"version":3}
  digest:
    SHA256("bloodbowl-f5-rng-python-v1\0" || canonical object bytes)

NumPy:
  numpy.random.get_state() must be the legacy global MT19937 five-tuple
  canonical object:
    {"cached_gaussian":finite binary64,"has_gauss":0-or-1,
     "keys":[624 uint32 integers],"name":"MT19937",
     "position":integer in [0,624]}
  digest:
    SHA256("bloodbowl-f5-rng-numpy-v1\0" || canonical object bytes)

Torch CPU:
  torch.get_rng_state() must be a CPU, contiguous, one-dimensional uint8
  tensor of exactly 5,056 bytes under frozen Torch 2.9.1
  raw_state is its bytes in index order
  digest:
    SHA256(
        "bloodbowl-f5-rng-torch-cpu-v1\0"
        || uint64-be 5056
        || raw_state
    )
```

No pickle, `repr`, platform-native integer encoding, CUDA RNG state, or
implementation-object serialization enters these digests. The `*_before`
states are captured after duplicate initialization and all construction:
Python and NumPy immediately before the first rollout, and Torch immediately
after reseeding to the training action/priority seed and before the first
action sample. All three `*_after` states are captured immediately after the
2,956th optimizer update and before checkpoint serialization, evaluation,
receipt serialization, or any further RNG call.

Independent tests build the following valid synthetic states without invoking
the production encoders: Python version 3 with `gauss = null` and state
`[0] * 624 + [624]` hashes to
`65918343143ac8d1b8c708a1c705efd2431c29e7b56ee5f33c1df29d36d0182b`;
NumPy MT19937 with 624 zero keys, position 624, `has_gauss = 0`, and
`cached_gaussian = 0.0` hashes to
`bc7557b8a4e8458765492ffa4e0d9c3517e303d317491c58ef7550ad9926bbe8`;
and 5,056 zero Torch bytes hash to
`2242b0ac30660da076a50b062f42c88e3378b0793aeda276b15d3b4398ffcd5c`.
The tests also mutate every framing domain, length, type, range, order, and
terminal LF independently.

## Frozen exposure budget

The foundation enumerated a safe zero-dice masked-uniform scoring subset with
per-episode probability:

```text
p = 4567 / 9,227,468,800
  = 4.9493529579856178977272...e-7 mathematically
  = 4.949352957985617e-7 as the nearest CPython binary64
```

For independent masked-uniform episodes, the first episode count giving at
least 95% probability of one event from this subset is:

```text
ceil(log(0.05) / log(1 - p)) = 6,052,775 episodes
```

Aligning to 2,048 matches/update freezes:

```text
updates                     2,956
episodes                    6,053,888
Home decisions              48,431,104
reported agent steps        96,862,208
total_timesteps             96,862,208
masked-uniform comparator   0.9500275582 probability of >=1 safe event
```

The comparator's authoritative manifest fields are integer numerator `4567`,
integer denominator `9227468800`, integer minimum episode count `6052775`,
and binary64 `probability_at_budget_rounded_10 = 0.9500275582`. Helpers derive
the binary64 minimum with
`ceil(log(0.05) / log1p(-numerator / denominator))` and the budget probability
with
`-expm1(episodes * log1p(-numerator / denominator))`, then test Python
ten-decimal rounding. The repeating per-episode decimal above is explanatory
and is never stored or compared as an exact manifest number. At the frozen
6,053,888-episode budget, the higher precision probability is
`0.9500275581996988870896248120710698...`.

This is a comparator, not a guarantee. The neural policy is not uniformly
distributed over conditional support, its trajectory probabilities change
during training, and other scoring routes may exist. A zero-event result is
therefore `exploration-inconclusive`, not a 5% hypothesis-test rejection and
not proof of an optimizer defect.

Training always runs all 2,956 updates. It may not stop on the first
touchdown, continue until a touchdown, retry a seed, extend the budget, or
choose a later checkpoint based on results.

Writer signal coverage begins with one exact post-umask bootstrap, before
argument parsing, deadline capture, factory construction, or preflight. Using
the already loaded built-in `_signal` module, it:

1. calls `_signal.pthread_sigmask(SIG_BLOCK, {SIGHUP,SIGINT,SIGQUIT,SIGTERM})`;
2. requires the returned inherited mask to contain none of those four signals;
3. creates an in-memory first-signal latch, pre-latched as
   `"pre-handler-pending"` if `_signal.sigpending()` intersects the set;
4. installs one non-raising, latch-only handler in numeric order `SIGHUP`,
   `SIGINT`, `SIGQUIT`, `SIGTERM`, requiring the previous dispositions to be
   exactly `_signal.SIG_DFL`, `_signal.default_int_handler`,
   `_signal.SIG_DFL`, and `_signal.SIG_DFL` in that order; and
5. restores the exact inherited mask with `SIG_SETMASK`.

The handlers remain installed through every writer phase and public result
write; they are never restored. Repeated signals cannot replace the first
latch. Every child/pipe/selector/reap and public-output user-space wait uses
nonblocking descriptors or a nonblocking child poll. No `communicate()`,
unbounded `wait()`, blocking pipe read/write, or whole-deadline-sized
`select()` is allowed. Each loop checks signal then deadline immediately
before and after a wait, and every selector/poll sleep is capped at exactly
50,000,000 monotonic nanoseconds even when more time remains. This literal
`signal_response_poll_nanoseconds` cap prevents PEP 475 restart of a
non-raising handler from hiding a signal until the three-hour deadline.

Nonblocking public output is temporary and, when restoration succeeds, does
not leak through a caller's duplicate of the inherited open-file description.
Before the first writer operation on stdout or failure stderr, the writer
snapshots that descriptor's exact `F_GETFL` file-status flags, applies
`F_SETFL(saved | O_NONBLOCK)`, and verifies the result. In an unconditional
`finally` after complete, short, failed, or expired output, it applies
`F_SETFL(saved)` and verifies exact restoration before process exit; it never
closes the inherited descriptor before this restoration attempt. A setup
failure emits no partial bytes. A restoration failure preserves the already
selected precommit classification, or follows the postcommit
caller-channel-failure rule, and can make no receipt or status claim that
rewrites that origin. Because `F_SETFL` acts on the shared open-file
description, a failed restoration may unavoidably leave the caller's duplicate
nonblocking; this is an explicitly detected OS/output failure, not a no-leak
claim. Watched subprocess tests retain a duplicate of the same pipe write end
in the caller, prove exact before/after flags for every path whose restoration
succeeds, and separately inject restoration failure to prove its detection,
classification, and explicit residual-flag non-claim.

A latched signal with no live child and before an exact/possible publication
commit stops before the next side effect, maps to that phase's
`handled-signal`, and attempts a receipt only when its private receipt
namespace is already valid. With a prepared or publication child, the
corresponding bounded terminate/reap state machine below applies. After an
exact/possible publication commit, the dedicated result-emission rule below
overrides this precommit rule. A signal delivered before the initial
successful `SIG_BLOCK` is outside the receipt guarantee, just as an
uncatchable pre-bootstrap kill. Watched hard-timed no-output child fixtures
deliver each handled signal during prepared-worker and publication-child
waits, require the first TERM decision within 500,000,000 monotonic
nanoseconds, and also cover signals in runtime preflight, runtime setup,
training, evaluation, artifact/verdict assembly, both publication boundaries,
and result emission.

All deadlines use type-strict `time.monotonic_ns()` values. Every selected
public or internal mode calls `posix.umask(0o077)` once; each public writer then
immediately records its start before parsing or preflight, while the read-only
final consumer creates no whole-run deadline. Controller and verifier whole
deadlines are start plus 10,800 seconds. Immediately before training-worker
spawn, the controller sets the
training deadline to the lesser of the whole deadline and current monotonic
time plus 7,200 seconds. Only the training worker checks that training deadline
at update boundaries; the outer supervisor hard-enforces the whole deadline.
The protocol budget also freezes `worker_stream_completion_seconds = 60` and
`termination_grace_seconds = 5`,
`signal_response_poll_nanoseconds = 50000000`, and
`public_output_completion_seconds = 5`; these begin only at the
stream/termination/output events defined below. They never extend the deadline
for accepted work or change its classification, but bounded termination/reap
or public failure/result delivery may consume up to five seconds after an
already expired whole-run deadline. Those are independent grace intervals: a
path that must first terminate/reap a child and then attempt public output may
consume at most ten seconds after expiry, while a path using only one interval
may consume at most five. Neither interval permits additional accepted work.
The controller and verifier recheck their whole deadlines immediately before
their durable external prospective intent and immediately before the
root/verdict rename.

There is at most one live prepared worker. The controller launches one
training worker and then its 56 evaluation workers serially in the exact
controller audit-population order; the verifier launches its 56 replay workers
serially in the verifier order. Worker and job retries are zero. A failure
forbids the next worker. No prior incomplete path, receipt, partial stream, or
checkpoint is opened as training input, and training jobs contain no resume
input. A new invocation always starts from update zero in a newly created
private child. Checkpoint-zero repeat evaluation is a declared evaluation, not
a retry.

The handled signal set is exactly `SIGHUP`, `SIGINT`, `SIGTERM`, and
`SIGQUIT`; the first signal is latched. On a whole/verifier deadline or
handled signal, the supervisor closes worker input, sends `SIGTERM` to the
worker process group, and sets a grace deadline to exactly the current
monotonic value plus five seconds. It continues concurrently draining both
pipes until the child is reaped or that deadline expires; it does not wait out
unused grace after a clean reap. At expiry it sends `SIGKILL` if the group is
still alive, reaps unconditionally, rejects all worker output, attempts its
resource failure receipt, and never retries. A worker checks
`os.getppid() == supervisor_pid` at startup and every update/evaluation-batch
boundary; supervisor loss makes the worker exit 75 without a typed frame
because no authenticated supervisor remains to accept one. An unrequested
worker signal with a live supervisor is
`integrity-abort / worker-signal`; a supervisor-initiated kill retains the
originating resource classification. `SIGKILL` of the public supervisor
promises no receipt. No orphan worker can publish evidence.

The exact resource errno set is `EDQUOT`, `EFBIG`, `EMFILE`, `ENFILE`,
`ENOMEM`, and `ENOSPC`. A caught member from any supervisor-owned OS/resource
operation in any phase—including open/stat/create/write/fsync, pipe creation,
descriptor duplication, or process spawn—is the historically named
`filesystem-resource`; the same errno from an attempted failure-receipt write
does not replace an already selected origin. The sole explicit override is the
closed postcommit public-result delivery continuation after exact/possible
commit plus durable handoff: its output descriptor setup, write, poll, or
flag-restoration errno cannot retroactively create a precommit origin and
follows the exit-zero caller-channel-failure rule below.
A caught member in a worker maps to its typed `worker-resource` cause. Every
other errno/OS failure follows the phase's integrity mapping. Training,
whole-controller, and verifier deadlines,
handled signals, filesystem-resource, and a valid worker resource failure are
`resource-truncated`; protocol/integrity failures, invalid IPC, unexpected
worker exit/signal, runtime drift, artifact drift, publication-precommit
failure, and caught unexpected exceptions are `integrity-abort`. Neither
status is a learning outcome.

Supervisor classification precedence is exact and first-origin-latched.
For each readiness turn, the supervisor first checks its signal latch, then
samples `monotonic_ns`, then observes child status once without blocking, and
only then services ready stderr and stdout descriptors. A previously latched
handled signal wins, otherwise an already expired whole-run deadline wins.
An observed unrequested signal death becomes `worker-signal` before any pipe
fault that was first visible in that same readiness turn. A normal exit is
remembered but is not itself classified until the stream/exit table can be
applied. Ready descriptors are then drained without blocking in fixed logical
order—stderr before stdout—through the currently available bytes/EOF and
validated incrementally. If no earlier origin exists, the first conclusive
IPC/cap/stream fault becomes the immutable origin. Thus invalid stdout that
was conclusively observed on an earlier turn remains `ipc-contract` if the
worker later dies, while an invalid header already buffered when a previously
unobserved `SIGSEGV` death first becomes ready is `worker-signal`. Once an
origin is selected, a later signal, deadline, postflight result, child record,
or kill outcome never replaces it; the bounded termination path preserves it.

Only when both pipes reach EOF and the child is reaped without an earlier
origin does the supervisor repeat signal-then-deadline, perform the
independently authenticated outer source/runtime/worker postflight, and repeat
signal-then-deadline once more before examining typed records or exit status.
A supervisor-owned condition at either check rejects all worker output and
selects `handled-signal`, `whole-deadline`, or `verifier-deadline`. Otherwise
an outer postflight identity/hash/status mismatch selects `runtime-drift`; one
of the exact resource errnos during postflight selects
`filesystem-resource`; and any other caught postflight exception selects
`unexpected-exception`. Outer postflight therefore wins over a worker's own
`runtime-contract` report for the same mutation when no earlier origin was
latched. Only after a successful outer postflight may child status be
classified.

For a complete authenticated typed worker failure, mapping is closed:
training `training-deadline` maps to controller `training-deadline`;
training or evaluation `worker-resource` maps to public `worker-resource`;
training `rollout-alignment` maps to controller `rollout-alignment`; and every
other valid typed integrity cause maps to public `worker-contract`. Evaluation
`evaluation-contract`, including its rollout-gate failures, never maps to
`rollout-alignment`. Transport faults—length/header canonicality, sequence,
index, kind/name/job/nonce binding, declared size, raw digest, EOF/trailing
bytes, stderr, or a wire/stream cap—map to `ipc-contract`. A well-framed
typed-JSON schema/field/range/frame-binding/semantic-equation fault, or a
semantic fault in a streamed trace/checkpoint/bitset before supervisor
publication, maps to `worker-contract`. A well-framed record/exit mismatch
maps to `worker-exit`, and an unrequested signal death maps to
`worker-signal`. `artifact-integrity` is reserved for supervisor-owned
materialized or already stored artifact bytes/topology, not prospective worker
stream semantics.

EOF/exit mapping is exhaustive after the precedence checks:

```text
unrequested signal death, any stdout prefix, no prior origin -> worker-signal
zero frames + any normal exit code                    -> ipc-contract
partial frame or nonfinal proper frame prefix + exit  -> ipc-contract
complete success sequence + exit 0                    -> candidate success
complete success sequence + any other normal exit     -> worker-exit
one complete failure frame + matching exit 70 or 75   -> mapped typed failure
one complete failure frame + any other normal exit    -> worker-exit
```

An unauthenticated-job exit 70 with no frame is therefore `ipc-contract`,
never an accepted typed failure. A previously latched stderr, cap,
stream-deadline, or framing origin remains authoritative over the later exit
row.

The same bounded termination primitive applies to every early integrity or
resource decision while a worker may still be live, including a wrong header,
an exceeded cap, the first stderr byte, incomplete or invalid payload,
postflight drift, and a typed failure whose EOF/exit does not arrive. It
preserves the already chosen originating classification, closes input, sends
group `SIGTERM`, drains only until clean reap or the exact five-second grace
deadline, sends group `SIGKILL` if still alive, and reaps unconditionally.
The first stdout byte starts one fixed stream-completion deadline exactly 60
seconds later; it never slides on progress. The complete final success or
failure frame must arrive before that deadline. After that complete final
frame, the supervisor starts the separate five-second completion deadline
while awaiting required EOF and exit; clean EOF/reap before it sends no
signal. Either overrun is `integrity-abort / ipc-contract`, triggers bounded
termination, and cannot hang until the three-hour whole deadline.

The canonical controller failure-receipt schema is
`bloodbowl-f5-controller-failure-receipt-v1`, with exactly:

```text
accepted_global_agent_step, artifact_basename, attempted_update_index, cause,
committed_epoch, learner_disposition, phase, protocol_sha256, resume_allowed,
rollout, schema, source_commit, status, volatile_global_agent_step,
worker_job_sha256
```

`resume_allowed` is literal `false`. Non-null progress values obey the exact
worker constraints above: epoch in `[0,2956]`, accepted step equal to epoch
times 32,768, attempted index equal to epoch in `[0,2955]`, and volatile step
equal to accepted or accepted plus 32,768 with the corresponding nullability.
`worker_job_sha256` names only the currently failing worker job: it is
non-null in `training-worker`, `controller-evaluation-worker`, or
`verifier-evaluation-worker` phase exactly after the supervisor has completed
and independently self-validated the canonical job bytes and derived their
domain-framed digest, before pipe creation/spawn. It is therefore non-null for
a later spawn or job-pipe failure even if the worker never parses the job. It
is null before that supervisor transition and in every non-worker phase; worker
acknowledgement is not the transition. It never names the most recently
accepted or any historical job. Progress provenance is closed:

- before a training job, all four progress integers and `rollout` are null and
  `learner_disposition` is `"not-created"`;
- after a training job fails without a complete authenticated worker-progress
  object, all four progress integers and `rollout` remain null and disposition
  is `"unknown-discarded"`; the killed/reaped worker is never reused;
- after a complete authenticated typed training failure whose mapped worker
  cause remains the selected public origin after all precedence checks, the
  four progress integers, disposition `"discarded"`, and nullable `rollout`
  are copied exactly from that worker record;
- if any other public origin instead wins during the training job—including a
  framing/stream fault, worker-exit/signal mismatch, or outer
  signal/deadline/postflight fault—the worker telemetry is not promoted: all
  four progress integers and `rollout` are null and disposition is
  `"unknown-discarded"`; and
- after a successful training worker has been accepted, later failures record
  accepted and volatile step `96862208`, committed epoch `2956`, null attempted
  update and rollout, and disposition `"completed"`.

For rollout alignment, `cause` is `"rollout-alignment"`,
`attempted_update_index` is the zero-based rejected update, and `rollout` is
the exact five-field bounded worker rollout object above. Other failures have
null rollout. The controller never promotes unauthenticated worker telemetry
into its receipt.

Controller phases are exactly `runtime-preflight`, `runtime-setup`,
`training-worker`, `controller-evaluation-worker`, `artifact-assembly`, and
`root-publication-precommit`. Controller resource causes are
`training-deadline`, `whole-deadline`, `handled-signal`,
`filesystem-resource`, and `worker-resource`; integrity causes are
`ipc-contract`, `worker-contract`, `worker-exit`, `worker-signal`,
`runtime-drift`, `artifact-integrity`, `publication-precommit`,
`rollout-alignment`, and `unexpected-exception`.

The verifier failure-receipt schema is
`bloodbowl-f5-verifier-failure-receipt-v1`, with exactly:

```text
artifact_basename, cause, phase, protocol_sha256, schema, source_commit,
status, worker_job_sha256
```

Verifier phases are exactly `runtime-preflight`, `evidence-preflight`,
`verifier-evaluation-worker`, `verdict-assembly`, and
`verdict-publication-precommit`. Its resource causes are
`verifier-deadline`, `handled-signal`, `filesystem-resource`, and
`worker-resource`; its integrity causes are the controller integrity set
without `rollout-alignment`.

Public phase/cause compatibility is closed. The following are the only allowed
causes in each phase; status is then fixed by the resource/integrity sets
above:

```text
controller runtime-preflight:
  whole-deadline, handled-signal, filesystem-resource, runtime-drift,
  unexpected-exception
controller runtime-setup:
  whole-deadline, handled-signal, filesystem-resource, runtime-drift,
  unexpected-exception
controller training-worker:
  training-deadline, whole-deadline, handled-signal, filesystem-resource,
  worker-resource, ipc-contract, worker-contract, worker-exit, worker-signal,
  runtime-drift, rollout-alignment, unexpected-exception
controller controller-evaluation-worker:
  whole-deadline, handled-signal, filesystem-resource, worker-resource,
  ipc-contract, worker-contract, worker-exit, worker-signal, runtime-drift,
  unexpected-exception
controller artifact-assembly:
  whole-deadline, handled-signal, filesystem-resource, runtime-drift,
  artifact-integrity, unexpected-exception
controller root-publication-precommit:
  whole-deadline, handled-signal, filesystem-resource, runtime-drift,
  artifact-integrity, publication-precommit, unexpected-exception

verifier runtime-preflight:
  verifier-deadline, handled-signal, filesystem-resource, runtime-drift,
  unexpected-exception
verifier evidence-preflight:
  verifier-deadline, handled-signal, filesystem-resource, runtime-drift,
  artifact-integrity, unexpected-exception
verifier verifier-evaluation-worker:
  verifier-deadline, handled-signal, filesystem-resource, worker-resource,
  ipc-contract, worker-contract, worker-exit, worker-signal, runtime-drift,
  unexpected-exception
verifier verdict-assembly:
  verifier-deadline, handled-signal, filesystem-resource, runtime-drift,
  artifact-integrity, unexpected-exception
verifier verdict-publication-precommit:
  verifier-deadline, handled-signal, filesystem-resource, runtime-drift,
  artifact-integrity, publication-precommit, unexpected-exception
```

Worker-only causes never appear outside a worker phase; `training-deadline`
and `rollout-alignment` are training-worker-only; and publication causes are
publication-phase-only.

Each receipt is at most 4,096 canonical bytes, is named exactly `receipt.json`,
and is published temporary-file-first, exclusive/new-only, mode `0600`,
single-link, and zero-ACL. A controller receipt is not promised until the
private container and its sole `artifact/` child have both been created,
pinned, mode/ACL checked, and the receipt temporary has not yet been created.
It is written only at
`<artifact-basename>.incomplete.<32-lowercase-hex>/receipt.json`. After
successful receipt publication, the controller container's exact immediate
path set is `["artifact","receipt.json"]`, its mode is `0700`, its ACL is
empty, and its APFS link count is four. Partial paths below the incomplete
`artifact/` do not alter that immediate closure. Runtime scratch is a separate
private root and never a child of the publication container.

The verifier writes only in a newly created
`<artifact-basename>.verify-incomplete.<32-lowercase-hex>/receipt.json`
sibling. After successful receipt publication its directory has exact path set
`["receipt.json"]`, mode `0700`, zero ACL, and APFS link count three. In both
cases the writer fsyncs the receipt, its immediate incomplete directory, and
the pinned target parent in that order.

Every 32-lowercase-hex namespace suffix in this protocol has the same
generation rule rather than merely a shape rule. Each worker job, controller
incomplete container, verifier incomplete receipt directory, controller
publication-intent directory, and verifier publication-intent directory uses
one fresh independent `os.urandom(16).hex()` call exactly once for that
object. The returned value is required to be exactly 32 lowercase hexadecimal
characters before path construction. A collision, short/invalid result, or
nonexclusive creation fails closed with no regeneration, counter, timestamp,
PID, deterministic fallback, or retry. An owning invocation never
intentionally reuses a nonce already retained in its in-memory job/object
ledger, and an actual name collision in an exclusive filesystem namespace
fails as above. No global or cross-process nonce-uniqueness claim is made:
independent controller and verifier invocations do not share a persisted nonce
ledger.

Receipt failure never changes the classification or permits continuation.
Before authenticated source and the corresponding fully validated private
failure namespace exist, no receipt is promised. No failure receipt is created
after root/verdict commit: the shared result literal is
`publication-indeterminate`, no destination is rolled back, and the final
consumer decides usability.

For public writer modes, a published or indeterminate publication result is
one canonical result object on stdout, empty stderr, and exit zero. A caught
precommit failure has empty stdout, exit `70` for integrity or `75` for
resource, and exactly one stderr line:

```text
bloodbowl-f5-controller-failure-v1 <status>
bloodbowl-f5-verifier-failure-v1 <status>
```

including exactly one LF. Argparse misuse remains exit two. Exit zero for an
indeterminate result authenticates only delivery of the external publication
result, never final evidence acceptance.

Precommit failure-stderr delivery uses the same temporary-nonblocking flag
transaction and one exact total bound. From its first write attempt, it has at
most five monotonic seconds, in 50,000,000-nanosecond poll slices, to emit the
already serialized one-line byte string. Later signal/deadline state,
`EAGAIN`, or short writes cannot replace the latched failure origin. With a
responsive channel, the exact line, flag restoration, stderr close/EOF, empty
stdout, and original 70/75 exit are required. On `EPIPE`, another hard
setup/write/poll/restoration error, caller closure, or five-second expiry, the
writer leaves partial stderr untouched, attempts no additional receipt or
alternate output, restores flags when possible, closes stderr, and exits with
the same original 70/75 code. A full-pipe watched fixture exercises every
partial offset, perpetual `EAGAIN`, hard error, signal, and expiry and proves
bounded exit plus unchanged classification.

Postcommit result emission is a closed continuation, not another precommit
failure boundary. The in-memory canonical result, including its one final LF,
must be at most 4,096 bytes. Immediately before its first stdout byte, the
writer checks signal then whole/verifier deadline once more. A newly latched
signal or expired deadline changes `publication_status` to
`"publication-indeterminate"` and the writer reserializes before emitting; it
does not attempt a receipt or select a nonzero precommit exit. Once any stdout
byte has been written, the serialized byte string is immutable: a later
signal/deadline can neither change status bytes nor switch to failure output.
The writer continues the same nonblocking offset-tracked write using the
50,000,000-nanosecond poll slices for up to exactly five seconds from the
first write attempt, then closes stdout.

With a responsive captured channel, exact flag restoration, the complete
object and EOF are required and the process exits zero with empty stderr. A
hard stdout setup/write/poll/flag-restoration error, caller closure, or
five-second delivery expiry after an exact/possible commit cannot be repaired
by the evidence protocol: the writer emits no stderr, attempts no receipt,
exits zero, and leaves any partial stdout bytes untouched. In that explicit
caller-channel-failure case the missing/noncanonical result channel is not
accepted as success; recovery requires the already durable external handoff
record and explicit trust path. Watched tests inject a signal and a
deadline immediately before byte zero and after every possible partial-write
offset, prove that any emitted suffix comes from the same frozen object, and
exercise `EAGAIN`, short writes, `EPIPE`, exact resource errnos, and output
expiry. This postcommit exception never applies when commit is ruled out or
when an exact/possible commit lacks a durable handoff; those cases retain the
precommit and no-handoff rules above.

The tracked canonical protocol manifest is the closed machine-readable owner
of these non-artifact contracts. `execution.entrypoints` owns bootstrap,
factory, reachability, and driver order; `execution.worker_ipc` owns invocation,
all job/header/binding/result/failure schemas, compatibility matrices, frame
sequences, semantic domains, and caps; `execution.supervision` owns deadlines,
precedence, population order, termination, resource errnos, and no-resume;
`execution.failure_receipts` owns both public receipt schemas, phase/cause
matrices, topology, publication, and output behavior; and
`execution.security.umask` owns the process mask rule. They do not enter
`artifact.schemas` because they are transport/control records outside the
completed evidence tree, but watched tests independently validate every
literal and cross-reference rather than trusting only the manifest hash.
`execution.rollout.transaction` and `execution.smoke.early_terminal_abort`
own the accepted/volatile transaction and watched real fault oracle;
`optimizer.parameter_telemetry` owns the exact norm/drift arithmetic.

## Checkpoints and training trace

Only these policy checkpoints are permitted:

```text
[0, 512, 1024, 1536, 2048, 2956]
```

Checkpoint `0` is the cold initialization; checkpoint `2956` is final.
Checkpointing is never triggered by a touchdown, loss value, or evaluation.
Each checkpoint is one fixed-schema `.f5w` file containing exactly 879,900
bytes: the seven prospectively named float32 tensors above, encoded
little-endian, C-contiguous, without a header, in lexicographic tensor-name
order. Files are written temporary-file-first, flushed, fsynced, renamed, and
hashed. Each checkpoint destination is new-only and is published through the
same watched exclusive no-clobber primitive specified below, using the pinned
checkpoint-directory descriptor and single-component temporary/destination
names. Exclusive rename is the checkpoint commit point. The destination is
then reopened relative to the same descriptor and its device/inode/mode/link
count/size/hash identity is proved before the checkpoint directory is fsynced.
An existing or racing destination is never overwritten or removed. A
post-commit identity/fsync failure aborts the still-private artifact build and
never tries to remove the complete checkpoint. They contain policy tensors
only because exact resume is explicitly unsupported. The manifest records both
the raw file SHA-256 and the canonical sorted-tensor digest.

The semantic digest uses `f5-canonical-tensors-v1` and has this exact binary
preimage, with no final newline or implicit padding:

```text
ASCII "f5-canonical-tensors-v1\0"
uint32-be tensor_count
for each tensor in UTF-8 name-byte order:
    uint32-be name_byte_count
    UTF-8 name bytes
    uint32-be dtype_token_byte_count
    ASCII "float32-le"
    uint32-be rank
    rank repetitions of uint64-be dimension
    uint64-be payload_byte_count
    little-endian C-contiguous float32 payload bytes
```

Names must be nonempty canonical ASCII, dimensions and byte counts must equal
the frozen seven-tensor schema, and `payload_byte_count` must equal four times
the dimension product without overflow. SHA-256 is applied once to the complete
framed preimage. It is intentionally different from the `.f5w` file SHA-256,
whose preimage is just the seven concatenated payloads. Independent tests
hard-code a tiny two-tensor framed byte vector and its digest without calling
the production serializer; they mutate name order, name length, dtype token,
rank, dimensions, byte count, endianness, payload, and trailing newline.

Neither controller nor verifier may call `torch.save`, `torch.load`, pickle,
ZIP, NumPy object loading, or the pinned backend checkpoint convenience
methods. Before reading one byte, the loader independently constructs the
frozen policy, requires the literal seven-name/dtype/shape schema and exact
219,975-element/879,900-byte size, and rejects a non-regular file, link,
truncation, or trailing byte. It then reads each known fixed slice into an
already-sized CPU float32 tensor, checks finiteness and the canonical tensor
digest, and calls strict `load_state_dict`. There is no attacker-controlled
shape, offset, allocation size, compression ratio, storage alias, or object
graph, so a pickle or ZIP/storage bomb is outside the format rather than
merely constrained after deserialization.

For every update, the append-only canonical training trace records:

- update index, epoch, global agent step, and exact episode count;
- exact successful-episode and objective-event counts from all eight delayed
  Home/Away transition reward vectors;
- aggregate TD-log cross-check and cumulative successes;
- first objective update, if any;
- terminal and reward-vector contract checks;
- entropy coefficient and learning rate actually applied;
- finite policy, value, entropy, total, KL, clip, and importance diagnostics;
- nullable explained variance when its denominator is exactly zero;
- the post-update parameter digest, norm, and drift on every committed row,
  with an independent raw-checkpoint cross-check on fixed checkpoint rows;
- profile times and observed SPS as descriptive, non-deterministic telemetry;
  and
- every hard-integrity value.

Calling the real trainer's logging method after every committed update is
allowed because it neither samples actions nor updates weights. The trace is
bounded to 2,956 rows and is not downsampled by wall-clock dashboard logic.

Parameter movement before any objective event must be visible in the trace.
It is expected that random critic values and the entropy/value objectives can
move parameters before the first TD; such movement is not evidence that the
task reward was discovered. On the first objective-bearing rollout only, the
worker records the pre-update canonical parameter digest without writing an
event-triggered checkpoint or changing RNG. That digest must equal the
previous committed row's post-update digest, or the frozen initial digest when
the first objective is on update index zero. The corresponding pre-update
distance is not a second row field: it is exactly the previous committed row's
post-update `drift_from_initial`, or binary64 positive zero at update index
zero. If no objective event occurs, the post-update values on every row and
the fixed final checkpoint bound the no-objective drift.

## Exact success authority and integrity gates

At every step, identity row order is
`[Home_0, Away_0, Home_1, Away_1, ...]`.

Puffer stores the reward/terminal produced by a vector step on the following
collector row. For one horizon-eight rollout, decisions 1–7 are therefore in
rollout rows 1–7 and decision 8 is in the repaired tail. Rollout row 0 is the
previous pending transition (zeroed in training mode and belonging to the
previous episode in evaluation mode) and must never be counted for the current
episode.

In training mode, the current episode's exact transition sequence is
`rewards[1:8] + tail_rewards` and
`terminals[1:8] + tail_terminals`. In evaluation mode it is
`rewards[1:8] + pending_rewards` and
`terminals[1:8] + pending_terminals`. At each of the eight decisions an
objective event is exactly:

```text
Home reward == +1
Away reward == -1
```

A non-objective transition has both rewards `0`. Any other reward pair aborts.
Terminals for decisions 1–7 must both be `0`; decision 8 terminals must both be
`1`. An episode-success bit is `1` if any of its eight Home transition rewards
is `+1`. The exact objective-event count equals the adapter-normalized
`tds_t0`, touchdown-component total, Home episode-return total, and Home
post-clip-return total. The successful-episode count equals
`reward_episode_abs_max_mean * 2048`. Both equalities are exact; no rounding or
tolerance is permitted. `tds_t1` must remain exactly zero.

The known safe subset scores on decision 8, but the policy is allowed to find a
different legal route that scores earlier. A natural Blood Bowl touchdown does
not itself end this qualification episode; `max_decisions = 8` still supplies
the rollout-aligned terminal. Earlier objective reward is trained from the
delayed rollout row and is not misclassified as a tail failure.

Every training update and evaluation rollout must also satisfy:

- exactly 2,048 completed episodes;
- mean episode length exactly `8`;
- finite observations, rewards, losses, and policy tensors where applicable;
- zero exact-action illegal fraction;
- zero error episodes;
- zero reward clipping, excess, non-finite, residual, mismatch, or suppressed
  terminal reward counters;
- zero demo, fallback, selector, and state-bank episode counters;
- no shaped reward component;
- no Away touchdown;
- epoch/update/global-step/tail-consumption consistency; and
- no environment, module, source, config, policy-shape, or seed drift.

Projection collisions are fatal in the environment and also increment the
illegal path; the pilot requires neither an abort nor an illegal emission.
Dice use is descriptive rather than a hard failure: the analytic comparator
covers a safe zero-dice subset, but the policy is allowed to discover any legal
objective-scoring F5 route.

An integrity breach stops immediately and yields `integrity-abort`, never a
partial accepted result.

## Frozen post-training evaluation

All checkpoint evaluation happens only after the uninterrupted training worker
has closed. Evaluation cannot consume or perturb training RNG.

For each of the six fixed checkpoints:

- evaluate all eight declared action seeds in exactly eight fresh worker
  processes, one checkpoint/action-seed pair per process;
- run exactly 32,768 episodes/seed;
- run exactly 16 vector rollouts/seed;
- collect 262,144 episodes/checkpoint;
- reuse the same seed and episode/vector ordering across checkpoints;
- record one little-bit-order packed success bitset per seed;
- record exact `k/n` and a two-sided 95% Wilson interval; and
- retain per-seed counts as well as the aggregate.

Checkpoint zero is evaluated a second time in exactly eight additional fresh
worker processes, one per declared action seed, and every repeat bitset digest
must match its corresponding primary bitset byte-for-byte. The independent
verifier later reconstructs checkpoint zero from the model-init seed, loads
every checkpoint through the fixed raw schema, reruns every evaluation seed
with the same 48-primary-plus-eight-repeat process topology, and requires
identical bitsets and summaries.

The sole pre-named learning contrast is final checkpoint `2956` versus
initial checkpoint `0`. With common random-number episode pairing, report:

- initial-only successes;
- final-only successes;
- both-success and neither-success counts; and
- `final-only - initial-only`.

No p-value, retrospective confidence threshold, or checkpoint selection is
used. Intermediate checkpoint curves are descriptive.

## Predeclared outcome classification

Classification occurs only after protocol acceptance:

1. `exploration-inconclusive`:
   zero training objective events. The fixed task did not supply a positive
   trajectory at this seed/budget. The next environment tranche should reduce
   discovery horizon/branching through a reviewed capability ladder rather
   than tune this result seed. Any final-versus-initial evaluation drift is
   still reported but cannot be attributed to task-reward acquisition: the
   critic, entropy objective, and sampling noise can move the policy without a
   positive reward.
2. `objective-observed-no-positive-final-point-estimate`:
   at least one training TD, but final-only evaluation successes are not
   greater than initial-only successes. Objective signal entered PPO, but this
   evaluation did not detect net final acquisition. Credit, optimizer,
   stability, sampling power, and representation remain competing
   explanations.
3. `positive-fixed-instance-acquisition-signal`:
   at least one training TD and final-only successes exceed initial-only
   successes. This is positive one-seed, one-state mechanism evidence only.
   It authorizes planning—not claiming—a separate prospective three-seed gate.

`resource-truncated` and `integrity-abort` are execution statuses, not learning
outcomes.

## Anti-leakage and no-tuning boundary

The pilot source, config, runtime access log, and evidence must establish that
training and evaluation did not consume:

- the eight reference action triples;
- `reference-trace.json`;
- generated F5 reference headers or raw reference match/BBS assets;
- the foundation reference executable or reference checker;
- BC checkpoints, BC pairs, demonstrations, or action labels;
- action forcing, scripted policy actions, a reference warm start, or a
  hand-coded policy;
- a shaped reward or scenario-progress pseudo-reward;
- a runtime state bank or hidden reset mixture;
- an alternate train/eval seed, budget, architecture, or optimizer value;
- an acceptance-triggered retry, continuation, early stop, or best checkpoint;
  or
- network/W&B artifacts.

The compiled F5 module necessarily contains the sealed fixture and exposes its
qualification identity, including a trace digest. Reading module role metadata
and the compiled binary is permitted. Loading the reference trace or reference
actions into Python, policy initialization, sampling, loss construction,
evaluation, or acceptance is not.

Every controller and verifier worker installs the fail-closed Python audit
hook above, returns its exact normalized open-attempt set, and rejects
forbidden Blood Bowl reference/BC paths and every Python socket event. The
controller's 57-worker union is bound in `identity.json`; the verifier's
56-worker union is bound in `verdict.json`. Neither is represented as an
OS-wide native-open tracer. Static tests also scan pilot implementation
surfaces for reference-action constants and forbidden imports.

Calibration performed before this plan was limited to stack correctness,
determinism, memory, and throughput. It did not observe or tune an acceptance
threshold, result seed, checkpoint result, or learning outcome. After plan
acceptance, no result-informed protocol change is permitted in this tranche.

## Implementation surfaces

The accepted implementation is expected to add:

- `training/f5_recurrent_ppo_pilot.json` — canonical closed protocol manifest;
- `tools/f5_recurrent_ppo_protocol.py` — pure schema, digest, bitset, interval,
  fixed-schema weight, config, and integrity helpers;
- `tools/run_f5_recurrent_ppo_pilot.py` — public controller plus isolated
  train/evaluation worker entry points;
- `tools/verify_f5_recurrent_ppo_pilot.py` — independent closed-artifact and
  live checkpoint evaluator/verdict writer plus its disjoint read-only final
  consumer mode;
- `tools/test_f5_recurrent_ppo_pilot.py` — watched unit/negative/integration
  tests; and
- this plan's implementation-status appendix, completed before the exact source
  commit used by the canonical run.

No Puffer patch, engine change, environment reward change, qualification-role
change, production launcher change, or source-tracked checkpoint/evidence
artifact is planned. If the real stack cannot satisfy the protocol without one
of those changes, implementation pauses and the plan returns to adversarial
review.

The production entrypoint and operating-system seams are also frozen so the
public CLIs cannot be stubs over dead helpers. The runner exposes one concrete
`_ControllerOsOperations` implementation,
`_make_controller_os_operations(*, puffer_root, artifact_dir, deadline_ns)`,
and `_run_controller(operations, *, puffer_root, artifact_dir)`. The verifier
writer analogues are `_VerifierOsOperations`,
`_make_verifier_os_operations(*, puffer_root, artifact_dir, deadline_ns)`, and
`_run_verifier_writer(operations, *, puffer_root, artifact_dir)`. Each public
writer bootstrap calls `posix.umask(0o077)` exactly once as its first
process-state protocol operation, installs the exact blocked signal/latch/
handler state machine above, captures exactly one whole-run start and derives
exactly one whole-run deadline, parses the fixed public arguments, calls its
corresponding factory exactly once with that deadline, and passes that exact
returned object to its driver. The driver neither calls `umask`, replaces
handlers, nor recomputes the whole deadline. Verifier final-consumer mode analogously
constructs its fixed final-consumer operations and must reach the already
frozen `_consume_final` chain. No public argument, environment key, plugin, or
collaborator override selects an operations implementation.

The verifier final consumer concretely uses `_FinalConsumerOsOperations` and
`_make_final_consumer_os_operations(*, artifact_dir,
expected_verdict_sha256)`. Its selected public branch calls that factory
exactly once and passes the exact object to
`_consume_final(operations, *, artifact_dir, expected_verdict_sha256)`.

Each owning script also exposes one concrete `_PreparedWorkerOsOperations`,
`_make_internal_worker_os_operations(*, request_fd, result_fd)`, and
`_run_internal_worker(operations, *, request_fd, result_fd)`. After the worker
umask/audit bootstrap, the exact-token branch calls its worker factory exactly
once with request descriptor zero and result descriptor one and passes that
same returned object and the same descriptor integers to
`_run_internal_worker` exactly once. The runner worker admits only training
and controller-evaluation jobs; the verifier worker admits only
verifier-evaluation jobs. No parallel token branch, alternate worker helper,
or dead-code-only seam is permitted.

Publication-child entrypoints are equally concrete. The runner exposes
`_ControllerPublicationChildOsOperations` and
`_make_controller_publication_child_os_operations(*, handoff_write_fd,
ack_read_fd, container_dir_fd, artifact_dir_fd, target_parent_dir_fd)`; its
private branch passes that exact one factory result to the already frozen
`_run_controller_publication_child(operations, *, deadline,
artifact_basename, evidence_manifest_sha256, protocol_sha256,
source_commit)` exactly once. The verifier exposes
`_VerdictPublicationChildOsOperations` and
`_make_verdict_publication_child_os_operations(*, handoff_write_fd,
ack_read_fd, artifact_dir_fd, scratch_dir_fd, target_parent_dir_fd)`; its
private branch passes that exact one factory result to
`_run_verdict_publication_child(operations, *, deadline, artifact_basename,
evidence_manifest_sha256, expected_verdict_sha256, protocol_sha256,
source_commit)` exactly once. In both branches `deadline` is the type-strict
integer parsed from `--deadline-monotonic-ns`, and every other driver keyword
is the exact parsed/authenticated private-argv value; dropping, defaulting,
deriving, reordering, or substituting a value is forbidden and watched.

The controller child internal argv is exactly the token followed in this order
by `--deadline-monotonic-ns <decimal>`, `--artifact-basename <component>`,
`--evidence-manifest-sha256 <64-lowercase-hex>`,
`--protocol-sha256 <64-lowercase-hex>`, and
`--source-commit <40-lowercase-hex>`. Its inherited descriptors are exactly
`3 = handoff-write`, `4 = ACK-read`, `5 = container-directory`,
`6 = artifact-directory`, and `7 = target-parent-directory`. The verdict
child grammar adds
`--expected-verdict-sha256 <64-lowercase-hex>` after the evidence-manifest
digest. Its descriptors are exactly `3 = handoff-write`, `4 = ACK-read`,
`5 = artifact-directory`, `6 = verifier-scratch-directory`, and
`7 = target-parent-directory`. Deadlines are type-strict decimal integers in
`[1,2^63-1]`; all other values obey their already frozen formats. Both spawns
use `close_fds=True` and the exact five-element `pass_fds` set; no descriptor
number or field is caller-selectable. Each driver descriptor-proves every
capability and value before opening or publishing an artifact path. A
malformed private grammar or missing/wrong descriptor exits integrity failure
before the factory result reaches the commit state machine and is never
reinterpreted as a public CLI.

The fixed numbers are produced by one exact parent-side staging transaction,
not assumed from incidental open order and not remapped by `preexec_fn`.
Immediately before `Popen`, in a supervisor that has created no thread, the
driver duplicates all five desired source capabilities to distinct descriptors
at or above 64 with `fcntl.F_DUPFD_CLOEXEC`. It then probes each target 3
through 7 with `F_GETFD`; every existing occupant is likewise saved at or
above 64 together with its exact close-on-exec/inheritable state, while
`EBADF` means absent and any other result aborts. Using only the safe desired
copies, it applies cycle-independent `dup2` mappings to 3 through 7 and marks
exactly those five targets inheritable. The `Popen` call receives literal
`pass_fds=(3,4,5,6,7)`. In an unconditional `finally` immediately after spawn
success or failure, each prior occupant is restored to the same number with
its saved inheritable state, each originally absent target is closed, and all
safe copies are closed. Identity checks prove the supervisor's original
capabilities and unrelated occupants are unchanged.

No parent-side staged target remains after that `finally`; the child sees
exactly 0/1/2 plus 3 through 7 after `close_fds`. A handled signal during the
short staging window is only latched, restoration completes first, and the
normal precommit or live-child state machine then handles it. Exact resource
errnos use `filesystem-resource`; all other staging/proof failures are
`publication-precommit`. Watched real-subprocess tests preoccupy all five
target numbers with distinct objects, use desired descriptors whose original
numbers form cycles through that range, inject failure at every duplication,
mapping, spawn, and restoration boundary, and prove exact parent restoration,
child capability identity, no extra inherited descriptor, and no
`preexec_fn`.

Each publication child is spawned exactly as the authenticated
`/usr/bin/python3 -B -I -S <absolute-owning-script> <private-argv...>` with the
exact four-key `Popen(env=...)` input (`PATH=/usr/bin:/bin`, `LANG=C`,
`LC_ALL=C`, `TMPDIR=/private/tmp`) and the authenticated Blood Bowl source root
as cwd. After the protected launcher transformation, the child requires the
same exact observed nine-key outer process environment frozen above; four-key
spawn input and nine-key observed state are distinct authorities. It uses
`start_new_session=True`, and the supervisor proves the child
PID is the distinct process-group ID before any handoff; every TERM/KILL target
after that proof is that group. If the proof itself fails, the supervisor
never calls `killpg` on the unproved numeric value: it closes the capability
pipes and uses bounded direct-PID `SIGTERM`, then direct-PID `SIGKILL` if
needed, to reap the exact `Popen` child. Standard input is `/dev/null`;
standard output and error are
separate concurrently drained capture pipes, each capped at 4,096 bytes and
required empty for every valid child result. The handoff/ACK capability pipes
are distinct from stdio. Site/user initialization, an environment extension,
an extra inherited descriptor, any stdout/stderr byte, a wrong process group,
or any exit outside exact `0`, `70`, or `75` is an integrity failure. Mandatory
real-branch tests deliver a handled signal before ACK and at the
ACK-to-rename boundary, prove the supervisor survives, prove bounded group
TERM/KILL/reap, and exercise both absent and committed destinations.

Every operations-factory implementation is construction-only. It may store
validated argument values and bind already imported stdlib callables, but may
not read
the environment or clock; open, stat, create, rename, or fsync a path; load a
native library; validate source/protocol semantics; install a signal handler;
open a pipe; spawn a process; access the network; or write output. Every such
effect belongs to the watched driver order after the exact factory object has
been passed. Factory construction itself is observed by reachability tests.

Prepared-worker supervision is owned by
`_supervise_prepared_worker(operations, *, job, expected_sequence,
deadline_ns)` in each writer. Failure-receipt
attempts are owned respectively by
`_attempt_controller_failure_receipt(operations, *, failure)` and
`_attempt_verifier_failure_receipt(operations, *, failure)`. These are
testable internal seams, not additional public modes. Watched reachability
tests invoke both public writer modes with production-shaped spy operations;
frozen-host integration instantiates the concrete OS operations on APFS
temporary directories and exercises the high-level leaf, root, and verdict
state machines rather than only the native rename wrapper.

After the public bootstrap's mask/deadline/factory sequence, the controller
driver order is exact: outer source/runtime/target-parent preflight; private
container, artifact child, and runtime scratch; one training worker;
validation/publication of its trace and six checkpoints; 56 serial controller
evaluation workers; validation of every bitset/result/audit receipt;
57-receipt aggregation; effective-config, identity, results, protocol, and
evidence-manifest assembly; durable closure of the 68-file pre-verdict tree;
supervised root publication; and one public publication result. After its
corresponding bootstrap sequence, the verifier writer order is exact:
source/runtime/artifact preflight; absent-verdict check; immutable evidence
validation; 56 serial verifier evaluation workers; bitset replay comparison
and receipt validation; 56-receipt aggregation; verdict construction;
supervised exclusive verdict publication; and one public result. Missing,
reordered, repeated, concurrent, or dead-code-only stages are watched
failures.

## Closed evidence contract

The controller opens and pins the requested artifact parent as an ordinary
non-symlink directory and validates that the requested artifact basename is
one canonical ASCII component with enough `NAME_MAX` headroom for every
protocol-owned suffix. It initially requires that basename to be absent by a
no-follow descriptor-relative lookup, while treating the final exclusive
rename—not that check—as the no-clobber authority. Relative to the pinned
parent it exclusively creates a new private `0700`
`<artifact-basename>.incomplete.<32-lowercase-hex-nonce>` container, opens and
pins it, and creates one `0700` child named exactly `artifact`. The nonce is
exactly `os.urandom(16).hex()`; a collision or nonexclusive creation fails
closed rather than selecting or reusing an existing object. That child is the
exact completed directory inode eventually published at the requested name.
No payload or incomplete-run receipt is ever a sibling in the target parent.

Before publication the controller reopens and fsyncs every one of the 67
payloads and the evidence manifest, verifies their descriptor/path identities,
then fsyncs all nine subdirectories leaf-to-root, the `artifact` child, its
private container, and the pinned target parent. Only that bottom-up durable
closure may be published. A precommit failure receipt is written only in the
private container root when the process can publish one, never inside the
`artifact` child, so no failure path can turn the child into a shortened
version of the completed schema.

Every one of the 67 payloads and the evidence manifest is first written as a
new regular single-link temporary file in its final containing directory,
flushed and file-fsynced, then published under its validated
single-component basename using that directory's pinned descriptor and the
exclusive wrapper. The destination is reopened without following links and
must match the held temporary descriptor's device/inode/mode/link-count,
expected size, raw hash, and semantic hash before the containing directory is
fsynced. Existing/racing leaves and post-rename identity/fsync failures abort
the private artifact build. They never overwrite or remove an unproved object,
and the artifact root is never published after such an abort.

Every new-only publication uses Darwin
`renameatx_np(source_dirfd, source_basename, destination_dirfd,
destination_basename, RENAME_EXCL)`, with `RENAME_EXCL = 0x00000004`, through
a watched fail-closed wrapper. `AT_FDCWD`, absolute/multi-component operands,
and ordinary `os.rename`/`os.replace` after an absence check are forbidden:
they leave ancestor-substitution or check-to-rename clobber races. Each parent
descriptor's device/inode/mode identity—including both distinct source and
destination parents for a cross-directory publication—is proved against its
expected path immediately before and after publication. Immediately before
the native call, the source basename is reopened/lstat'd relative to the
pinned source descriptor without following links and must match the
already-held source object's device/inode/mode/link-count/size/hash identity;
the root-directory case binds the complete `artifact` child inode and the file
cases bind the complete fsynced temporary inode. An unavailable API,
source-name swap, cross-device path, pre-existing destination of any
filesystem type, replaced parent, or racing creator fails without reading
destination file contents, unlinking, rewriting, replacing, or changing the
destination.
Every operand is nonempty canonical ASCII and contains no slash, backslash,
NUL, newline, `"."`, or `".."`. No unvalidated, absolute, or multi-component
caller-controlled path is passed to the native publication call. The sole
caller-derived native operand is the requested artifact basename after it is
proved to be one canonical ASCII component with the required `NAME_MAX`
headroom; all source names and every other destination name are frozen
protocol literals.

The production binding is exactly `ctypes.CDLL(None, use_errno=True)` with
`renameatx_np.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
ctypes.c_char_p, ctypes.c_uint]` and `renameatx_np.restype = ctypes.c_int`.
It sets ctypes errno to zero immediately before the call, snapshots errno
immediately after a nonzero return, and maps that saved value without making
another libc call first. A missing symbol, a nonzero return with zero errno, or
any errno other than an explicitly classified failure is an integrity abort;
an error/collision fixture also fails if its injected or native call
unexpectedly succeeds.

Portable CI exercises an injected fake native binding, the unavailable-symbol
path, exact ABI arguments, operation order, and the complete return/errno
matrix. Separately, a mandatory non-skipped frozen-macOS pre-pilot integration
uses the real `renameatx_np` symbol and APFS directories. It covers same- and
cross-directory regular-file publication, checkpoint publication, directory
root publication from the private container, cross-directory verdict
publication, source-name substitution before the syscall, actual directory
fsync, and `EEXIST` preservation for every locally constructible destination:
regular file, directory, symlink, hardlink, FIFO, and Unix-domain socket. Each
collision test proves the source and destination object identities, bytes
where applicable, and metadata are unchanged.

The wrapper closes the declared destination-clobber and
ancestor-substitution classes under this threat boundary, but it is not a
transactional source-inode binding primitive. A hostile same-UID process able
to mutate protocol-owned private `0700` source namespaces in the interval
between the final source check and the native syscall is explicitly outside
the threat model. Watched pre-syscall substitution tests remain mandatory. A
source or destination identity mismatch detected after the syscall is never
described as cryptographically eliminated: private payload/checkpoint
publication aborts before root publication, while a committed root or verdict
is left untouched and rejected by the final consumer unless it is the expected
complete object.

All uses of “durable,” “fsynced,” and ordered publication in this plan are
scoped to child/supervisor process death and signals while the OS, APFS volume,
storage device, and controller remain operational. Ordinary Darwin `fsync`
does not supply a strict power/OS-loss ordering barrier. Kernel panic, OS
crash, device/controller failure, and power loss may independently lose or
reorder an incomplete container, intent, supervisor handoff, root/verdict
rename, or directory metadata and are explicitly outside this tranche. The
protocol makes no `F_FULLFSYNC` claim. After such an event, any artifact
without a separately retained trusted expected verdict digest is rejected;
even with one, the final consumer must revalidate every surviving byte and
path.

Root and verdict commit syscalls run in a short-lived internal publication
child, not in the public CLI process. The public controller/verifier remains
the publication supervisor and sole public CLI surface. It creates two
dedicated close-on-exec pipes, deliberately passes only their publication-child
ends plus the already validated descriptors, and invokes the same committed
script in a fixed internal mode. That mode is not a public override: direct
invocation without the supervisor-created one-shot descriptor capability and
exact inherited identity aborts before opening an artifact. The supervisor
owns the child process, pipe endpoints, target-parent descriptor, deadline, and
external handoff directory. The exact tokens, ordered internal argv, fixed
descriptor numbers, construction-only factories, and one-call reachability
from bootstrap to `_run_*_publication_child` are the entrypoint contract above.
The mandatory real-APFS integration invokes each actual same-script private
subprocess branch end to end; calling the child helper directly is additional
unit coverage, not a substitute.

After durably publishing its on-disk prospective intent receipt, the child
sends exactly one length-prefixed canonical precommit handoff record to the
supervisor:

```text
uint32-be canonical_record_byte_count
canonical ASCII JSON record bytes, including exactly one LF
EOF on the child-to-supervisor record pipe
```

The record is at most 4,096 bytes. A short/long record, a second frame, trailing
bytes, noncanonical JSON, exhausted remaining whole-run monotonic deadline, or
binding mismatch aborts before ACK; no independent timeout is invented. The
controller record has schema
`bloodbowl-f5-controller-precommit-handoff-v1` and exactly:

```text
artifact_basename, evidence_manifest_sha256, external_handoff_path,
intent_receipt_path, intent_receipt_sha256, protocol_sha256, schema,
source_commit, status
```

The verifier record has schema
`bloodbowl-f5-verdict-precommit-handoff-v1` and the same keys plus
`expected_verdict_sha256`. Both statuses are exactly `"prospective"`.
`intent_receipt_path` is the nonce-qualified canonical sibling-relative path
to the already durable intent `receipt.json`, respectively exactly
`<artifact-basename>.publish-intent.<32-lowercase-hex>/receipt.json` or
`<artifact-basename>.verify-publication.<32-lowercase-hex>/receipt.json`;
`intent_receipt_sha256` is its raw digest. `external_handoff_path` is
respectively the deterministic, new-only sibling path:

```text
<artifact-basename>.controller-handoff/record.json
<artifact-basename>.verdict-handoff/record.json
```

Both records are closed canonical JSON objects. Artifact basenames are
validated single components; both paths are canonical ASCII relative paths;
commit/digest/schema fields use the exact formats already defined; and no
nullable or extension field exists. The tracked protocol's
`execution.publication` object freezes the six intent/handoff/result schema
IDs, their exact ordered field-name sets and field formats, both deterministic
external paths, the frame limit, and ACK literal. They are intentionally not
roots in `artifact.schemas` because they live outside the completed artifact;
independent validators and watched literal objects own them.

Before ACK, the supervisor independently opens the named intent receipt
relative to its pinned target parent, without following links; validates its
descriptor identity, zero ACL, mode, link count, raw digest, canonical schema,
and all record/evidence bindings; and publishes the exact received handoff
record temporary-file-first into a new `0700` zero-ACL deterministic handoff
directory. It fsyncs the `0600` zero-ACL record, handoff directory, and target
parent. Pre-existing handoff paths of any type fail without mutation. Only
after that durable capture does the supervisor write this exact
acknowledgement and close its ACK pipe:

```text
ASCII "bloodbowl-f5-publication-ack-v1 "
|| lowercase-hex SHA256(canonical handoff record bytes)
|| LF
```

The child requires that one exact ACK, with no extra byte, before its final
deadline and identity rechecks and commit syscall. EOF, exhausted remaining
whole-run deadline, hash mismatch, or supervisor death before a complete ACK
aborts precommit. Therefore a child killed at the first instruction after
successful rename cannot strand the
expected verdict digest: the supervisor already has the exact in-memory record
and a durably fsynced copy. If the supervisor itself dies after ACK, the record
is still at its deterministic external path; recovery requires the caller to
explicitly authenticate/trust and supply that record, never an automatic scan
or consumer default.

Every non-clean publication-child event or outcome uses one commit-aware
watched state machine because ACK and rename can race with any failure, not
only a signal or deadline. Each readiness turn uses the same fixed order:
first-signal latch, monotonic deadline, one nonblocking child-status
observation, then nonblocking ready descriptors in logical order `stderr`,
`stdout`, handoff-record pipe, and ACK-write endpoint. An unexpected signal
death is conclusive at the child-status step. A normal exit is only remembered;
after every descriptor ready in that turn has been drained through its
currently available bytes/EOF and validated, a still-unclassified exit `70`
or `75` becomes the corresponding publication origin and exit zero remains a
candidate clean completion. Therefore a malformed handoff or any stdio byte
buffered when exit 75 first becomes ready deterministically wins as
`publication-precommit`; a malformed handoff conclusively seen on an earlier
turn likewise remains authoritative. A zero-byte handoff EOF is deferred until
normal-exit classification: with valid-empty stdio plus exit 75 it is the
legitimate child resource report for failure before intent/handoff creation
and maps to `filesystem-resource`; with exit zero or 70 it maps to
`publication-precommit`. Any nonempty partial, noncanonical, extra, or
semantically invalid handoff beats every normal exit as
`publication-precommit`. The closed origin mapping is:

- the first handled signal or expired whole/verifier deadline retains its
  corresponding resource cause;
- an exact resource errno from a supervisor-owned publication operation is
  `filesystem-resource`;
- an authenticated outer source/runtime identity drift is `runtime-drift`;
- a supervisor-owned source artifact, verdict, parent, or topology identity
  mismatch before a possible commit is `artifact-integrity`;
- child process-group/environment/runtime/descriptor/private-grammar,
  handoff/intent/ACK, stdout/stderr/cap, framing/binding/identity, unexpected
  signal, and unexpected/incorrect normal-exit behavior is
  `publication-precommit`; a normal child exit `70` also has that cause;
- a normal child exit `75` is the child's closed precommit resource report and
  maps to `filesystem-resource`; and
- any remaining caught supervisor exception is `unexpected-exception`.

An event in a later bullet cannot replace an earlier latched origin. On every
such non-clean event, including any stdout/stderr byte, cap overrun, malformed
or incomplete handoff, wrong process group, child exit/signal, supervisor
resource error, runtime/identity drift, handled signal, or deadline, the
supervisor closes any unwritten ACK endpoint, sends `SIGTERM` to a still-live
publication-child process group after its PID-equals-PGID proof, or to the
exact child PID if that proof is the fault, concurrently drains both stdio
pipes only until a clean reap or the exact five-second grace deadline, sends
`SIGKILL` to the same proved target if still alive, and reaps unconditionally.
An already reaped child is not signalled, and an unproved group identifier is
never a signal target. Only after that bounded close does it
descriptor-inspect both the validated source inode/name and destination name
relative to their pinned parents before choosing public status:

- if the exact source still exists and the destination is absent or is a
  separately proved unchanged collision object, root/verdict commit did not
  occur under the declared trust boundary; the latched origin remains
  authoritative, exit is 75 for a resource cause or 70 for an integrity
  cause, and the appropriate failure receipt may be attempted;
- if the source is absent and the destination is the exact expected inode with
  its complete byte/topology identity, commit occurred; when the handoff was
  durably captured the supervisor emits the shared
  `publication-indeterminate` result with exit zero and creates no failure
  receipt; and
- any source/destination identity combination that cannot prove either state
  uses `publication-indeterminate` only when the handoff was durably captured,
  never rolls back or writes a precommit receipt, and leaves usability to the
  final consumer.

The child contract makes rename impossible before durable handoff plus ACK. If
an exact/possible commit is nevertheless observed without a durably captured
handoff, the child violated that contract and the required success-result
fields do not exist: the supervisor emits no success object, exits 70 with the
normal integrity stderr line, writes no failure receipt because commit cannot
be ruled out, and leaves the destination untouched for explicit final
consumption with separately trusted inputs.

This inspection rule applies both before and after a durable ACK. ACK proves
handoff durability, not commit; lack of observed clean child completion never
by itself selects precommit failure. No abnormal child or supervisor outcome
racing a successful rename can therefore emit a misleading precommit failure
receipt after an exact or possible commit.

On normal success or a child postcommit failure, the supervisor returns the
external handoff path, its raw SHA-256, the publication classification, and,
for a verdict, the expected verdict SHA-256 on its caller-owned result channel.
That channel emits exactly one canonical JSON object and EOF. The controller
result schema is `bloodbowl-f5-controller-publication-result-v1` with exactly
`artifact_path`, `external_handoff_path`, `external_handoff_sha256`,
`publication_status`, and `schema`. The verifier result schema is
`bloodbowl-f5-verdict-publication-result-v1` with those keys plus
`expected_verdict_sha256`. `publication_status` is exactly `"published"` or
`"publication-indeterminate"`; a precommit failure emits no success-channel
object and exits nonzero. The artifact path is the independently resolved
absolute destination, and all other values must match the durable record and
observed destination.
The outer handoff directory and supervised pipe establish precommit process
lineage and durability under the declared full-lifetime filesystem trust
boundary; they are not a digital signature and do not establish authorship
against the owning UID. The final consumer may receive the expected digest
directly from this supervisor state or from an explicitly trusted copy of the
known handoff record, but its API never reads that record itself.

After the completed child is closed, but before the root publication, the
controller publication child exclusively creates a second new sibling `0700`
directory named
`<artifact-basename>.publish-intent.<32-lowercase-hex-nonce>`. It publishes one
canonical ASCII `0600` `receipt.json` temporary-file-first and new-only, then
fsyncs the receipt file, intent directory, and pinned target parent. The
receipt has schema `bloodbowl-f5-controller-publication-intent-v1` and exactly
these keys:

```text
artifact_basename, evidence_manifest_sha256, protocol_sha256, schema,
source_commit, status
```

`status` is exactly `"prospective"`. The other values bind the requested
single-component destination and the already closed child. Receipt publication
and the supervisor's durable handoff ACK must succeed before the final deadline
recheck and root rename. Presence of a prospective receipt or handoff is not
proof that the root commit occurred, and neither is edited into a retrospective
success claim.

Exclusive
`renameatx_np(container_dirfd, "artifact", target_parent_dirfd,
artifact_basename, RENAME_EXCL)` is the controller commit point. Signals,
resource-cap failures, integrity failures, and unexpected exceptions before it
leave only the clearly named private incomplete container and external
prospective intent; failure receipts go only in the container root and never
manufacture a shorter completed schema. After the commit point, the controller
reopens the final name relative to the same pinned target parent, proves it is
the held child directory by descriptor/path/device/inode/mode identity, and
fsyncs the destination root, now-empty source container, and target parent. It
may remove only its own proven-empty source container after those checks and a
further parent fsync; it never removes an unproved or nonempty object. A
post-commit identity/fsync failure never removes, rolls back, chmods, or moves
the final destination; the durable prospective receipt, ACKed supervisor
handoff, and observed destination classify it as
`publication-indeterminate`. The final consumer—not controller process status
or receipt/handoff presence—decides whether the complete artifact is valid.

Every outer and worker process observes an arbitrary inherited umask only
through the return value of its first `posix.umask(0o077)` call, before any
filesystem creation; that value is available to watched test instrumentation
but is excluded from evidence because it cannot affect output. The process
then applies and verifies explicit modes with descriptor-based `fchmod`;
behavior may not depend on the inherited umask.

POSIX modes alone do not establish privacy on Darwin because `fchmod` does not
remove an inherited extended ACL. Before creating any protocol-owned namespace,
the controller/verifier pins and requires no extended ACL object on its
caller-selected target parent and private-runtime-scratch creation parent.
Every protocol-created directory and regular file is then ACL-checked on its
held descriptor immediately after creation/fchmod, after every publication,
and during final consumption. The protocol never attempts to sanitize or
inherit a caller ACL; a parent or created object with any extended ACL fails
closed before trusted contents or a publication ACK enter it.

The frozen check uses the same `ctypes.CDLL(None, use_errno=True)` libc handle,
`ACL_TYPE_EXTENDED = 0x00000100`, and exactly:

```text
acl_get_fd_np.argtypes = [ctypes.c_int, ctypes.c_int]
acl_get_fd_np.restype = ctypes.c_void_p
acl_free.argtypes = [ctypes.c_void_p]
acl_free.restype = ctypes.c_int
```

It sets errno to zero immediately before
`acl_get_fd_np(fd, ACL_TYPE_EXTENDED)`. On the frozen APFS host, the sole
accepted no-ACL result is a null pointer with saved errno `ENOENT`. A non-null
ACL pointer is always freed successfully and then rejected, even if it
describes an empty or deny-only ACL; a null pointer with any other errno,
failure to free, a missing symbol, or unsupported filesystem is an integrity
abort. Portable fake-binding tests and the non-skipped Darwin test own those
exact return/errno/free cases and an inheritable `everyone` allow-ACL fixture
that remains after `fchmod`.

Completed artifact, private source-container, incomplete,
controller/verifier-publication-intent, publication-supervisor-handoff,
verifier-scratch, runtime-scratch, checkpoint, evaluation, and evaluation-leaf
directories are mode `0700`. Every payload, evidence manifest, verdict,
handoff record, intent/failure receipt, and temporary file is mode `0600`. All
have no extended ACL object, and all regular files have link count one.

On the frozen APFS host, a directory's `st_nlink` is two plus its immediate
entry count, including ordinary files as well as subdirectories. The completed
tree therefore has two exact phase-specific link-count maps. Before
`verdict.json` publication, the artifact root is `10`, `checkpoints/` is `8`,
`evaluation/` is `9`, and each of the seven evaluation leaves is `10`. After
`verdict.json` publication, only the artifact root changes, to `11`; all other
directory counts remain the same. The protocol manifest records these as the
two closed maps `artifact.directory_link_counts.pre_verdict` and
`artifact.directory_link_counts.post_verdict`. The outer map has exactly those
two keys. Each phase map has exactly the ten path keys `.` plus every member of
`artifact.directories`, with type-strict integer values. Every protocol load
schema-validates both complete maps, independent of the current artifact
phase. Controller closure and verifier-writer preflight/precommit compare live
directories only with `pre_verdict`; immediately after the exclusive
`verdict.json` rename, the verifier writer compares the whole live tree only
with `post_verdict`; the authenticated final consumer also compares only with
`post_verdict`. Failure to set the process mask, chmod drift, unexpected
phase-specific link count, any extended ACL, or unsupported filesystem type
fails closed.

### Exact completed layout

The completed directory has exactly these nine ordinary, non-linked
subdirectories:

```text
checkpoints/
evaluation/
evaluation/update-000000/
evaluation/update-000512/
evaluation/update-001024/
evaluation/update-001536/
evaluation/update-002048/
evaluation/update-002956/
evaluation/update-000000-repeat/
```

Its 67 payload files are exactly:

```text
protocol.json
effective-config.json
identity.json
training-trace.jsonl
results.json

checkpoints/update-000000.f5w
checkpoints/update-000512.f5w
checkpoints/update-001024.f5w
checkpoints/update-001536.f5w
checkpoints/update-002048.f5w
checkpoints/update-002956.f5w

evaluation/update-NNNNNN/seed-II.bits
    for NNNNNN in {000000,000512,001024,001536,002048,002956}
    and II in {00,01,02,03,04,05,06,07}

evaluation/update-000000-repeat/seed-II.bits
    for II in {00,01,02,03,04,05,06,07}
```

That is five root payloads, six checkpoints, 48 primary bitsets, and eight
checkpoint-zero repeat bitsets. Each `.f5w` is exactly 879,900 bytes. Each
`.bits` contains exactly 32,768 little-bit-order success bits and is exactly
4,096 bytes. `identity.json` consolidates the source, runtime, dependency,
Puffer, module, startup, RNG, and access-audit subreceipts; `results.json`
consolidates the training summary, all evaluation summaries, repeat comparison,
paired final-versus-initial counts, and learning outcome.

`evidence-manifest.json` is a structural file, not one of its own payloads.
There are therefore exactly 68 regular single-link files before verification.
`verdict.json` must be absent then; it is the only permitted later addition,
giving exactly 69 regular single-link files after verification. Empty, extra,
linked, or differently named directories or files are rejected.

### Exact completed schemas

Every JSON document is ASCII, duplicate-key-free, finite-number-only,
canonical with sorted keys and separators `(",", ":")`, and terminated by
exactly one LF. Integer fields require `type(value) is int`; Python booleans
cannot satisfy them. Every object is closed recursively. The only serializer
is:

```text
json.dumps(
    value,
    ensure_ascii=True,
    allow_nan=False,
    sort_keys=True,
    separators=(",", ":"),
) encoded as ASCII, followed by exactly one LF
```

The pinned CPython 3.9.6 and 3.12.12 runtimes must emit identical shortest
round-trippable binary64 float spelling for every watched literal vector,
including lowercase `e` and Python's required `e+` spelling for a positive
exponent. Verification parses and then requires byte equality with reserialized
canonical bytes.

`protocol.json` is validated only by byte identity with the tracked manifest,
so it does not recursively describe itself. Its `artifact.schemas` registry
covers exactly `effective-config.json`, `identity.json`, one
`training-trace.jsonl` line, `results.json`, `evidence-manifest.json`,
`verdict.json`, and the reusable `wilson95` tuple. The registry has schema
`bloodbowl-f5-schema-registry-v1` and exactly `definitions`, `roots`, and
`schema`. `roots` maps those seven literal names to reference nodes;
`definitions` is a closed map of unique canonical ASCII names to nodes.

The finite node DSL permits only these exact tagged forms:

```text
{"kind":"boolean"}
{"kind":"null"}
{"kind":"literal","value":<finite JSON scalar>}
{"kind":"enum","values":[<unique finite JSON scalars>...]}
{"kind":"integer","maximum":<integer-or-null>,"minimum":<integer-or-null>}
{"finite":true,"kind":"number","maximum":<number-or-null>,
 "minimum":<number-or-null>}
{"format":<frozen-format-name>,"kind":"string"}
{"items":<node>,"kind":"array","maximum_length":<integer>,
 "minimum_length":<integer>,"ordered":true}
{"items":[<node>...],"kind":"tuple"}
{"closed":true,"fields":{<ASCII-field-name>:<node>...},"kind":"object"}
{"kind":"union","options":[<node>...]}
{"kind":"ref","name":<definition-name>}
```

Frozen string formats are exactly `absolute-path`, `ascii`, `git-object`,
`relative-path`, `schema-id`, and `sha256`. References must resolve, the graph
must be acyclic, and unreferenced definitions, duplicate union/enum members,
empty unions, extra descriptor keys, Boolean-as-integer values, and wider
schemas are rejected. The registry encodes every scalar/container type,
nullability, literal/enum set, numeric range, fixed/allowed list length and
order, item schema, and nested object key set specified below. Watched tests
own the entire finite registry object and reject any omitted or permissive
node.

The DSL's scalar types are disjoint. An `integer` accepts only
`type(value) is int`; a `number` accepts only `type(value) is float`, a finite
IEEE-754 binary64 value, and positive sign for zero. Neither accepts a Boolean,
and an integral JSON spelling such as `0` cannot satisfy a `number` node whose
artifact value is floating telemetry. No accepted artifact floating field may
store `-0.0`: evidence construction recursively canonicalizes every floating
zero to positive `0.0`, and validation rejects a negative-zero wire value in
loss, profile, interval, schedule, rollout, result, or other numeric evidence.
Literal and enum comparison is type-strict. Float members additionally compare
their exact binary64 bit patterns, so `-0.0` cannot satisfy a literal `0.0`
even though Python numeric equality considers them equal. Nullable-number
unions apply the same exact-float, finiteness, and positive-zero rules in their
numeric branch.

`protocol.json` is byte-identical to the tracked
`training/f5_recurrent_ppo_pilot.json`. Its schema is
`bloodbowl-f5-recurrent-ppo-pilot-v1` and its exact root keys are:

```text
artifact, budget, checkpoints, environment, evaluation, execution, optimizer,
plan_commit, policy, puffer, runtime, schema, seeds, source
```

`plan_commit` is the full commit that contains the accepted plan amendment and
is frozen in the manifest and watched tests immediately after that plan-only
commit. Every nested value is exact-equality data, including the full Puffer
arguments, 51-key environment, tensor schema, environment allowlists, seed
domains, budgets, schedules, layout, and schema identifiers. There is no
permissive extension mapping.

`effective-config.json` has schema `bloodbowl-f5-effective-config-v1` and exact
root keys:

```text
arguments, environment, protocol_sha256, schema
```

`environment` has exactly `mapping`, `path`, and `sha256`; it contains the
exact raw 51-key mapping, tracked path, and frozen config digest. `arguments`
is the complete effective nested Puffer argument object, not selected leaves.

`identity.json` has schema `bloodbowl-f5-runtime-identity-v1` and exact root
keys:

```text
audit, dependencies, module, protocol_sha256, puffer, rng, runtime, schema,
source, startup
```

Its exact nested key sets are:

```text
source:
  commit, implementation_manifest_sha256, status_sha256, tree, zero_bytecode
runtime:
  architecture, cpu_dependencies, host_model, kernel, macos,
  python_executable_sha256, python_version, torch_config_sha256,
  torch_git_revision, torch_version
dependencies:
  distributions_json_sha256, distributions_sha256_file_sha256, pyvenv_sha256,
  requirements_sha256, site_packages_directories, site_packages_files,
  site_packages_manifest_sha256, site_packages_regular_bytes,
  site_packages_symlinks
puffer:
  commit, source_file_count, source_manifest_sha256, status_sha256, tree,
  version
module:
  fixture_enabled, fixture_role, gpu_flag, path, sha256, state_bank_kind
startup:
  outer_environment, scratch_paths, worker_environment,
  worker_environment_sha256, worker_flags, worker_sys_path
rng:
  numpy_after, numpy_before, python_after, python_before, torch_after,
  torch_before
audit:
  network_attempts, opened_paths, opened_paths_sha256, worker_count
```

All source/Puffer Git commits and trees are respectively lowercase 40-hex
strings; every SHA-256 field is lowercase 64-hex. `zero_bytecode`,
`fixture_enabled`, and every RNG `*_before`/`*_after` field are respectively a
Boolean and digest strings. Runtime identity leaves are exact strings except
`cpu_dependencies`, which is the fixed ordered string array
`["Accelerate LAPACK/BLAS","OpenMP"]`. Dependency counts/bytes, Puffer
`source_file_count`, module `gpu_flag`/`state_bank_kind`, and
`audit.network_attempts`/`worker_count` are nonnegative JSON integers; their
accepted values are frozen literals, including zero network attempts, exactly
57 controller worker receipts, and zero symlinks.
`audit.opened_paths` is the ordered unique array of canonical normalized ASCII
Python `"open"` attempt tokens defined above—not a successful/native-open
list—and its digest frames that exact canonical array.

`startup.outer_environment` and `startup.worker_environment` are the exact
closed nine-key and normalized twenty-key string maps declared above.
`startup.worker_flags` is exactly `["-B","-s","-P"]`;
`startup.worker_sys_path` is the ordered five-string array declared above.
`startup.scratch_paths` has exactly `normalized` and `resolved`; each contains
exactly `cache`, `home`, `root`, and `tmp`. Normalized values are the four
literal `<private-runtime-scratch>` paths, while resolved values are absolute
canonical strings proven to name the same new `0700` directory tree outside
evidence. No receipt list or map admits an untyped additional item.

`training-trace.jsonl` contains exactly 2,956 canonical JSON objects, one per
LF-terminated line and no header/footer. Each line has schema
`bloodbowl-f5-training-update-v1` and exact root keys:

```text
committed_epoch, episodes, global_agent_step, losses, objective, parameters,
profile, rollout, schedule, schema, update_index
```

For line `i`, `update_index = i`, `committed_epoch = i + 1`, and
`global_agent_step = (i + 1) * 32,768`. Nested keys are exact:

```text
episodes:
  cumulative, this_update
objective:
  cumulative_events, cumulative_successful_episodes, events, first_update,
  successful_episodes
rollout:
  integrity, reward_contract, tail_consumed, td_log_crosscheck,
  terminal_contract
schedule:
  entropy_coefficient, learning_rate
losses:
  approx_kl, clip_fraction, entropy, explained_variance, importance, policy,
  total, value
parameters:
  canonical_sha256, checkpoint_update, drift_from_initial, norm,
  pre_objective_sha256
profile:
  rollout_seconds, sps, train_seconds
```

`rollout.integrity` has exactly:

```text
away_touchdowns, completed_episodes, config_unchanged,
demo_endzone_episodes, demo_episodes, demo_fallbacks, demo_pass_episodes,
demo_pickup_episodes, demo_postkick_episodes,
demo_selector_eligible_configured, demo_selector_threshold_configured,
demo_uniform_episodes, environment_unchanged, error_episodes,
illegal_fraction, mean_episode_length, module_unchanged,
projection_collisions, reward_clip_episodes, reward_clip_excess,
reward_clip_nonterminal_samples, reward_clip_terminal_samples,
reward_clipped_samples, reward_component_mismatch_samples,
reward_component_nonfinite_samples, reward_component_residual,
reward_components, reward_nonfinite_episodes, reward_nonfinite_samples,
reward_postclip_return, reward_samples_per_episode,
reward_terminal_suppressed_abs, reward_terminal_suppressed_signed,
seed_unchanged, source_unchanged, state_bank_config_episodes
```

Its `reward_components` object has exactly:

```text
ball_gain, ball_loss, block_assist, block_exposure, block_self_injury,
block_sequence, block_turnover, carrier_exposure, carrier_exposure_soft,
carrier_threat, defensive_threat, defensive_threat_soft, distance_ball,
distance_endzone, injury_inflicted, injury_taken, possession, result_draw,
result_winloss, rush, send_off, setup_autofix, setup_done, statmatch,
surf_inflicted, surf_taken, touchback, touchdown
```

All episode/update/step/objective fields are nonnegative JSON integers.
`objective.first_update` is null exactly while cumulative objective events are
zero; beginning with the first event-bearing line it is the same zero-based
update integer forever. `rollout.reward_contract`,
`rollout.tail_consumed`, `rollout.td_log_crosscheck`, and
`rollout.terminal_contract` are literal `true`, not strings or nested
extension maps.

Within `rollout.integrity`, the five `*_unchanged` fields are literal Booleans.
All fields ending in `_episodes` or `_samples`, plus
`away_touchdowns`, `completed_episodes`, `projection_collisions`, and both
configured selector fields, are normalized exact nonnegative integers after
proving their native float receipts are integral. `illegal_fraction`,
`mean_episode_length`, clip/excess/residual/return/suppression values, and each
reward component are finite JSON numbers with prospectively frozen ranges;
every hard-integrity value is exact zero/valid except
`completed_episodes = 2048`, `mean_episode_length = 8.0`,
`reward_samples_per_episode = 16`, and the reconciled
`touchdown` count.

Schedule values, non-null losses, parameter norm/drift, and profile values are
finite JSON numbers; norm/drift/profile values are nonnegative. Parameter hash
fields are lowercase 64-hex or, for `pre_objective_sha256`, null under the rule
above. `checkpoint_update` is a Boolean. Profile telemetry remains inside the
raw training-trace bytes and its `f5-training-trace-v1` semantic digest.
“Excluded from deterministic equality digests” means only that duplicate-run
reproducibility assertions project out the three profile values; it never
means those bytes are omitted from artifact integrity.

Parameter telemetry covers exactly the seven trainable policy tensors in
UTF-8 tensor-name order and every C-order element within each tensor; no
optimizer buffer or nontrainable buffer participates. Each stored binary32
value is converted exactly to binary64. `parameters.norm` starts with binary64
`0.0`, performs one left-to-right binary64 multiply and add
`sum = sum + value * value` per element without fusion, and applies one
binary64 `sqrt` after the final addition. `parameters.drift_from_initial` uses
the same order and accumulation, with each delta computed as the binary64
subtraction of the current and frozen-initial converted binary32 values before
squaring. Both are absolute L2 values, not means or normalized ratios. Watched
tiny vectors own the exact binary64 results and mutation order. On every row,
`parameters.canonical_sha256`, `parameters.norm`, and
`parameters.drift_from_initial` are computed from the live policy tensors
after that row's optimizer update has completed and before row validation and
accepted-ledger append. They are never null and are never carried forward from
a prior row. On a fixed checkpoint row, the same post-update tensors are
serialized into the prospective raw `.f5w` bytes without another optimizer
operation; after the accepted row append and fixed-schedule checkpoint
publication, an independent parse of the stored raw payload must reproduce all
three values exactly. A mismatch aborts the still-private artifact rather than
editing or removing the already appended row.

Among loss fields, only `explained_variance` may be null, and only for a zero
denominator. The only other nullable trace-row fields are
`objective.first_update` and `parameters.pre_objective_sha256` under their
rules above. `pre_objective_sha256` is non-null only on the first
objective-bearing rollout, is sampled after rollout validation and before the
optimizer update, and equals the previous committed row's post-update
`canonical_sha256` or the frozen initial digest on update index zero.
`checkpoint_update` is true exactly after updates
`512, 1024, 1536, 2048, 2956`; checkpoint zero precedes the trace. `profile`
values are finite nonnegative telemetry and excluded from deterministic
equality digests. Only the reward map's `touchdown` component may be nonzero
and it must reconcile with the exact reward vectors.

`results.json` has schema `bloodbowl-f5-results-v1` and exact root keys:

```text
checkpoint_zero_repeat, evaluations, learning_outcome,
paired_final_vs_initial, protocol_sha256, schema, training
```

`training` contains exactly:

```text
agent_steps, completed_budget, episodes, first_objective_update,
home_decisions, objective_events, successful_episodes, updates
```

`evaluations` is the ordered six-record checkpoint list. Each record has
exactly `episodes`, `seeds`, `successes`, `update`, and `wilson95`; each of its
eight ordered seed records has exactly:

```text
action_seed, bitset_path, bitset_semantic_sha256, bitset_sha256, episodes,
seed_index, successes, wilson95
```

Every `wilson95` is exactly a two-element JSON array `[lower,upper]` of finite
binary64 numbers satisfying `0.0 <= lower <= successes / episodes <= upper <=
1.0`. With `z = 1.959963984540054`, compute in this exact binary64 order:

```text
p = successes / episodes
d = 1.0 + z*z/episodes
c = (p + z*z/(2.0*episodes)) / d
m = z*sqrt(p*(1.0-p)/episodes
           + z*z/(4.0*episodes*episodes)) / d
lower = max(0.0, c-m)
upper = min(1.0, c+m)
```

The independent literal vector `successes = 0`, `episodes = 32768` must
serialize exactly as:

```text
[0.0,0.00011721827793903778]
```

`checkpoint_zero_repeat` has exactly `episodes`, `matches_primary`, `seeds`,
`successes`, and `wilson95`, using the same seed-record schema and repeat
paths. `matches_primary` is true only after all eight raw bitsets match.
`paired_final_vs_initial` has exactly `both`, `episodes`, `final_only`,
`initial_only`, `neither`, and `net_final_only`. `results.json` has no
`accepted`, `passed`, promotion, or verifier field.

All result counts, updates, seeds, and action seeds are nonnegative JSON
integers; `completed_budget` and `matches_primary` are Booleans; all paths are
exact canonical relative strings and all digests lowercase 64-hex.
`first_objective_update` follows the same null-or-zero-based-integer rule as
the trace. `net_final_only` is the one signed integer field. Evaluation,
repeat, and paired count equations are exact, and `learning_outcome` is exactly
one of the three predeclared strings with no fourth value.

`evidence-manifest.json` has schema
`bloodbowl-f5-evidence-manifest-v1` and exact root keys:

```text
completed_budget, execution_status, payload_count, payloads, protocol_sha256,
reserved_post_manifest_path, schema
```

The literals are `completed_budget = true`, `execution_status = "completed"`,
`payload_count = 67`, and
`reserved_post_manifest_path = "verdict.json"`. The 67 entries are sorted by
path UTF-8 bytes and each has exactly `bytes`, `path`, `semantic_sha256`, and
`sha256`. Every semantic digest is a lowercase 64-character string:

```text
canonical JSON:
  SHA256("f5-canonical-json-v1\0" || raw canonical bytes)
training trace:
  SHA256("f5-training-trace-v1\0" || raw JSONL bytes)
checkpoint:
  the specified f5-canonical-tensors-v1 digest
bitset:
  SHA256(
      "f5-success-bitset-v1\0"
      || uint32-be checkpoint_update
      || uint32-be seed_index
      || uint32-be action_seed
      || uint64-be episode_count
      || uint8 repeat_flag
      || raw bitset bytes
  )
```

`repeat_flag` is the literal byte `0x00` for every primary checkpoint bitset,
including primary checkpoint zero, and `0x01` only for paths under
`evaluation/update-000000-repeat/`. No other byte is valid.

The evidence manifest may not contain `accepted`, `passed`, or
`learning_outcome`.

`verdict.json` has schema `bloodbowl-f5-verdict-v1` and exact root keys:

```text
accepted, audit, completed_budget, evidence_manifest_sha256,
execution_status, learning_outcome, limitation, module_sha256,
protocol_sha256, puffer_commit, replay, schema, source_commit
```

The literals are `accepted = true`, `completed_budget = true`, and
`execution_status = "completed"`. `replay` has exactly
`all_bitsets_reproduced`, `checkpoint_zero_raw_sha256`,
`checkpoint_zero_tensor_sha256`, `final_checkpoint_raw_sha256`,
`final_checkpoint_tensor_sha256`, and `initialization_reproduced`. The four
hash fields bind respectively the raw `.f5w` bytes and
`f5-canonical-tensors-v1` semantic digest for checkpoints zero and 2956; the
two other replay fields are literal `true`.

`audit` has exactly `network_attempts`, `opened_paths`,
`opened_paths_sha256`, and `worker_count`. It is the validated verifier-only
set-union/sum over the exact 56 replay-worker receipts defined above:
`network_attempts = 0`, `worker_count = 56`, canonical ordered unique attempt
tokens, and their exact domain-framed digest.

`limitation` is exactly this ASCII string:

```text
The verifier independently authenticated source/module, initialization, checkpoint tensors, and checkpoint behavior but did not retrain the 2,956 historical updates.
```

Each valid learning outcome can coexist with `accepted = true`; there is no
`passed`, `learned`, or promotion Boolean. Every commit/tree/digest/module
identity has the exact lowercase-hex type already defined; all verdict strings
are frozen literals or the three-outcome enum.

The evidence manifest closes every payload and itself is never changed. It
also reserves exactly one non-payload path, `verdict.json`, which must be absent
before verification and is the sole permitted post-manifest addition. No
payload or manifest file may be missing, extra, non-regular, symlinked,
hardlinked, or changed after manifest creation. Paths are normalized relative
paths with fixed cardinality and naming. JSON is ASCII, canonical,
newline-terminated, duplicate-key-free, finite-number-only, and closed-schema.
Binary bitsets and checkpoints have exact expected sizes/types and separate
semantic digests.

After all checks and replay evaluations pass, the verifier supervisor creates
canonical `verdict.json` bytes in a new private sibling verifier-scratch
directory on the artifact filesystem, flushes and fsyncs the temporary regular
single-link file, computes its raw SHA-256, and passes only the validated
descriptors to its publication child. Before any verdict commit, that child
exclusively creates a separate sibling `0700`
`<artifact-basename>.verify-publication.<32-lowercase-hex-nonce>` directory
relative to the already pinned target parent. It publishes one canonical ASCII
`0600` `receipt.json` temporary-file-first and new-only, then fsyncs the receipt
file, publication-intent directory, and target parent. The receipt has schema
`bloodbowl-f5-verdict-publication-intent-v1` and exactly:

```text
artifact_basename, evidence_manifest_sha256, expected_verdict_sha256,
protocol_sha256, schema, source_commit, status
```

`status` is exactly `"prospective"` and `expected_verdict_sha256` is the raw
digest of the already fsynced canonical verdict temporary. The receipt is
outside the evidence tree and its 67/68/69-file cardinalities. Failure to
publish and durably close this receipt forbids verdict publication. The same
unchanged prospective receipt supplies the record that the supervisor
authenticates over its owned pipe and durably captures before ACK; no
postcommit receipt creation or status rewrite is required. Presence of the
receipt alone does not say whether the verdict rename occurred or authenticate
the digest to a caller.

After the intent is durable, the child sends the exact verifier precommit
handoff and waits for the supervisor's durable-capture ACK. Only after the ACK
does it immediately revalidate the complete evidence snapshot, the prospective
deadline, the absence of the reserved destination, and every
source/destination descriptor identity. It pins separate descriptors for the
scratch directory and artifact root, proves both against their expected paths,
and publishes the single-component temporary name to the single-component
reserved name with exactly the watched dirfd-relative Darwin exclusive wrapper
above. `EEXIST` or any other pre-commit publication failure is fail-closed: the
verifier never unlinks, truncates, rewrites, replaces, chmods, or otherwise
changes the destination. Cleanup is limited to its own temporary object after
proving the expected device/inode identity. A pre-existing or racing
destination of any type (regular file, directory, symlink, hardlink, FIFO,
socket, or device) remains the same object with the same contents and metadata.

After exclusive publication, the verifier reopens the destination relative to
the pinned artifact descriptor without following links, proves its
descriptor/path/device/inode/link-count/size/hash identity, and fsyncs both the
artifact and verifier-scratch directories. A crash or injected failure before
exclusive publication leaves no verdict in the evidence directory. Exclusive
rename is the verdict commit point: a later identity/fsync failure never
attempts to remove the destination and may leave only the complete
prevalidated canonical verdict, never partially written bytes; the verifier
reports that failure externally and does not claim its own run succeeded.

The named recovery/acceptance surface is
`validate_final_evidence(artifact_root, expected_verdict_sha256)` in
`tools/f5_recurrent_ppo_protocol.py`, also exposed by the independent
verifier's exact
`--consume-final --artifact-dir <completed-artifact>
--expected-verdict-sha256 <lowercase-64-hex>` mode. That expected raw verdict
digest is a mandatory trusted external input from the supervisor's
precommit-captured state/result channel or an explicitly caller-authenticated
copy of the deterministic verifier handoff record. The consumer itself may
not derive it from the candidate `verdict.json`, scan sibling directories,
read the evidence manifest as a default, or invent any fallback. The handoff
is an explicit trust boundary, not a digital signature: the artifact, intent
receipt, and handoff file alone cannot prove who authored the verdict or when
replay occurred. The mode is read-only and disjoint from ordinary
verification:
`--puffer-root <prepared-root> --artifact-dir <unverified-artifact>` always
rejects any pre-existing verdict, while `--consume-final` requires one. The
final-consumer outer first performs the exact stdlib-only source preflight and
then uses only the post-preflight authenticated-helper exception above to call
that one protocol implementation; it has no parallel JSON serializer, schema
registry, or artifact validator in the verifier script. A watched import/open
probe permits the preflight's descriptor open/read but proves that the helper
is not compiled, executed, registered in `sys.modules`, or pathname-imported
before the source preflight success marker; it also proves the authenticated
descriptor/path/blob binding and that no other repository-local or third-party
module is loaded. The final consumer never trusts verifier process
status. It independently pins the artifact root, validates every payload
against the immutable manifest,
requires exactly one additional regular single-link verdict, validates its
closed schema and evidence-manifest binding, requires its raw digest to equal
the supplied expected digest, and accepts only if the complete canonical
verdict and every immutable evidence gate still pass. An absent,
digest-mismatched, mutated, linked, second, schema-invalid, binding-invalid, or
evidence-drifted verdict is rejected. Whether a byte-identical verdict existed
before some claimed verifier invocation is not inferable by consumer mode and
is not one of its claims; ordinary writer mode owns and enforces the
pre-existing-verdict rejection. The verdict contains the immutable
evidence-manifest SHA-256 and repeats the exact source, module, protocol, and
learning-outcome identities. The external run handoff invokes this
final-consumer surface and records the verdict file SHA-256 because no file can
recursively authenticate its own bytes. Consumer mode authenticates all
immutable stored evidence, formulas, identities, and exact externally expected
verdict bytes but does not rerun the expensive live checkpoint behavior
replay; that replay remains a verification-time claim conveyed across the
explicitly trusted external handoff.

Immediately after the last `validate_final_evidence` payload read and before
returning acceptance, final-consumer mode repeats the clean raw Git-status
check, zero-bytecode scan, exact seven-entry implementation-manifest/Git-blob/
live descriptor identities, and the held protocol-helper descriptor's
device/inode/mode/link-count/size/bytes identity. Persistent ordinary source
or bytecode drift during validation therefore fails at the promised final
postflight; same-UID mutate/use/restore ABA between checks remains the already
declared full-lifetime trust boundary.

This authenticated helper is executed by the frozen Xcode CPython `3.9.6`,
whereas prepared Puffer workers use CPython `3.12.12`. The protocol helper
must therefore be syntactically and semantically compatible with both exact
runtimes and may not use a later-only construct such as PEP 604 `X | Y` type
unions, structural `match`, `zip(strict=True)`, or a later-only standard-library
API. Before the canonical pilot, a mandatory non-skipped exact-host subprocess
invokes `/usr/bin/python3 -B -I -S`, exercises the descriptor-authenticated
module load, positively consumes one complete valid 69-file fixture, and
rejects representative helper/source, verdict-digest, schema, and payload
mutations. Portable CI may skip only when the frozen Darwin/Xcode host identity
is absent; the declared host run may not skip.

The verifier:

1. requires a clean exact Blood Bowl source commit and the same live prepared
   Puffer root;
2. validates every path, mode, ACL state, link count, size, hash, schema,
   count, formula, source identity, runtime identity, module role, and config
   invariant;
3. rejects a pre-existing verdict;
4. reconstructs the frozen initialization twice and checks its canonical
   digest against checkpoint zero;
5. never invokes a Torch/pickle/ZIP container parser, loads each exact-size raw
   `.f5w` file only through the literal seven-tensor schema, calls strict
   `policy.load_state_dict`, and checks tensor finiteness/digests;
6. recomputes training totals, first-event classification, fixed schedules,
   intervals, bit counts, paired comparisons, and outcome classification;
7. reruns every fixed checkpoint evaluation under every fixed action seed and
   compares exact bitsets, requiring and aggregating all 56 typed replay-worker
   audit receipts into the verdict;
8. distinguishes independently replayed checkpoint behavior from the
   worker-authored historical training trace;
9. enforces its independently monitored 180-minute cap without writing inside
   the evidence directory on failure;
10. sends the exact prospective verdict digest to its supervisor, waits for
    the independently validated/durably captured handoff ACK, revalidates
    evidence and deadline immediately before exclusively publishing the
    canonical verdict into the sole reserved path, never clobbers or removes a
    pre-existing or racing object, then proves the published descriptor/path
    identity and fsyncs both affected directories; and
11. reports `accepted`, `completed_budget`, and `learning_outcome` as separate
    fields.

The verifier does not retrain 2,956 updates. It can authenticate the live
source/module, cold initialization, checkpoint tensors, and exact checkpoint
behavior; the historical update trace remains a self-consistent worker-authored
receipt. This limitation must appear in the verdict.

## Watched-red and negative-test matrix

Before implementation, tests must fail for the missing protocol surfaces and
watch at least:

- exact manifest schema, literals, SHA-256 values, seed derivation, checkpoint
  list, budget arithmetic, comparator probability, and evaluation arithmetic;
- no caller overrides and rejection of generic-launch, CUDA, DDP, self-play,
  frozen-bank, frozen-enemy, BC, load, resume, W&B, sweep, and reward changes;
- exact 51-key environment replacement and semantic mutation rejection;
- pre-update rollout alignment, early-terminal injection at each delayed row,
  ordinary decision-eight termination, natural early-TD/nonterminal behavior,
  error/empty-legal/asymmetric-terminal/autoreset counterfixtures, and proof
  that no optimizer or checkpoint action follows a rejected rollout;
- eight-step recurrence, one complete episode/rollout, exact tail consumption,
  and one real prioritized minibatch/update;
- explicit RNG call order, deterministic/thread settings, RNG-state digests,
  duplicate-init tensor digest, seed-domain separation, the exact
  Python/NumPy/Torch state encodings, and independent literal framing vectors;
- the inert configured `vec.num_threads=20` value versus the authoritative
  `OMP_NUM_THREADS=4`, `OMP_DYNAMIC=FALSE` CPU-step request, including
  rejection of receipts or prose that represent the former as actual CPU
  execution parallelism;
- raw Git-status, normalized worker-environment, and opened-path digest
  preimages, their exact domains/literal vectors, and rejection of line
  projection, reordering, decoding/re-encoding, or missing-LF alternatives;
- exact Python `"open"` event capture and physical/token normalization,
  explicit pre-hook bootstrap/site exclusions and exact-interpreter boundary
  canary, post-`PyOS_FSPath`/`PathLike` behavior, failed-attempt inclusion,
  read-only enforcement, deduplication/order, all five roots and the sole
  `/proc/self/maps` exception, explicit rejection vectors for every observable
  invalid event/path class, and a test that the receipt never claims
  native-open coverage;
- exact delayed-row plus tail Home/Away reward/terminal parsing, deliberate
  exclusion of rollout row 0, early-TD fixtures, bit packing, aggregate TD
  cross-checks, and every malformed reward/terminal combination;
- exact normalization of the real flat averaged `_vec.log()` map, including
  `n = 2048.0`, count-average scaling and integral conversion, the
  one-touchdown `1/2048` TD/component/post-clip-return vector, rejection of
  one-float32-unit and nonintegral perturbations, exact native key closure,
  the manifest-owned exhaustive 83-projection/70-unretained partition and
  operation/target mutation matrix, endpoint bindings, and proof that no
  nested test-double receipt bypasses the adapter before `train()` or bitset
  acceptance;
- fixed checkpoint-only behavior and rejection of event-triggered or extra
  checkpoints; every committed row independently computes post-update
  canonical digest/norm/drift, fixed rows cross-check the stored raw
  checkpoint, and the first-objective pre-update digest equals the prior
  committed digest or frozen initialization;
- training continuation after first TD and exact final update count;
- fixed post-training evaluation ordering, seed count, episode count,
  checkpoint-zero repeat, exact Wilson representation/arithmetic/literal bytes,
  and paired discordance math;
- nullable zero-denominator explained variance but rejection of non-finite
  objective losses or tensors;
- every hard-integrity counter mutation and impossible outcome classification;
- static and dynamic rejection of reference, BC, demo, forcing, shaped reward,
  alternate-seed, and network access;
- separately typed audit receipts for exactly 57 controller workers and 56
  verifier workers, rejection of a missing/duplicate/mislabelled receipt,
  exact union/sum/digest/worker-count aggregation, controller binding in
  `identity.json`, verifier binding in `verdict.json`, and mutations of either
  closed audit object;
- exact in-memory mode dispatch, one-umask ordering, one deadline capture for
  writer modes, construction-only operations factories, exact factory-object
  identity, and one-call reachability from both public writers, the final
  consumer, both owning internal-worker token branches, and both real
  publication-child subprocess token branches through every ordered stage;
  exact CPython prior signal dispositions, private grammar/descriptor
  mutations, cycle-safe fixed-fd staging/restoration with preoccupied 3..7,
  factory side effects, and no-op/dead-helper counterexamples reject;
- one-shot job framing and the complete eight-frame training/two-frame
  evaluation streams, including a 12-plus-megabyte concurrent stdout/stderr
  drain, incremental hashing/spooling, every length/header/order/name/hash/
  nonce/schema/semantic/EOF/trailing-byte mutation, kind/stderr cap boundary,
  exact redundant aggregate/wire arithmetic plus reachable drain-loop checks,
  exit/record mismatch, fixed 60-second first-byte stream
  deadline, five-second clean-completion deadline, early integrity termination,
  TERM/grace/KILL/reap order, zero retries, and no orphan or partial-stream
  acceptance;
- exact worker-kind/status/phase/cause/progress cross-products, deterministic
  supervisor signal/deadline/postflight/child precedence, public phase/cause
  cross-products, current-job-only digest provenance, all failure receipt
  field/range/equation/nullability rules, bounded rollout bitset and multi-fault
  selection, simultaneous-ready child/stderr/stdout/handoff/exit vectors,
  50,000,000-nanosecond PEP-475-safe poll slices, audit sealing with a late
  allowed-open counterexample, and exact public stdout/stderr/70/75 behavior;
- the seven-case mandatory prepared-Puffer early-terminal transaction at
  delayed rows one through seven for agent rows `[0,1]`, exact one-update raw
  and canonical digests, exhaustive Muon defaults/group/live-parameter-order/
  state/tensor-byte snapshots and mutation vectors, volatile-versus-accepted
  ledger split, no-I/O dispatch tripwires before checkpoint schedule filtering,
  failure-only IPC, unchanged supervisor spool/destination topology, discard,
  receipt derivation, and pre-rollout same-session reuse rejection;
- private-container plus exact-child construction, atomic new-directory
  behavior, incomplete/resource-truncated/integrity-abort semantics, controller
  and verifier wall-cap expiry, durable controller/verdict prospective intent
  receipts, exact supervisor frame/validation/persistence/ACK, child or
  supervisor EOF/timeout/hash/trailing-byte faults, child kill at the first
  instruction after each successful rename, uncatchable precommit termination
  with no promised failure receipt, external verifier failure receipts, and no
  resume;
- checkpoint truncation/trailing bytes, wrong exact size, non-finite raw
  tensors, attempted legacy Torch/pickle/ZIP containers, file-hash drift, and
  canonical-tensor-digest drift;
- evidence missing/extra/truncated/trailing/noncanonical files, wrong
  counts/hashes, traversal names, symlinks, hardlinks, and pre-existing or
  mutated verdicts; tests own the exact 67 payload paths, nine subdirectories,
  68-file pre-verdict and 69-file post-verdict cardinalities, every closed
  root/nested field set, and independent literal semantic-digest vectors;
  the sole reserved post-manifest verdict addition, evidence-manifest binding,
  and Darwin exclusive-publication operation ordering receive positive and
  negative coverage;
- the exact seven-path implementation manifest, canonical framing, Git-blob
  binding, audit-hook derivation, and rejection of any missing/extra/reordered/
  linked/dirty/mutated entry;
- mode/zero-ACL/link-count closure under hostile inherited umasks and
  inheritable allow ACLs; exact `umask`/`fchmod`/`acl_get_fd_np`/`acl_free`
  ordering and return/errno handling for every completed, temporary, scratch,
  intent, handoff, incomplete, and failure-receipt object;
- for payload/checkpoint, controller-root, and verdict publication alike,
  pre-existing destinations of every constructible filesystem type and a
  publication-boundary racing creator remain object-, byte-, and
  metadata-identical; directory-ancestor substitution and path/descriptor
  mismatches fail closed; source-basename substitution is injected separately
  for payload, checkpoint, controller-root, and verdict publication; injected
  failures at temporary creation, write, flush, file fsync, intent receipt
  creation/publication/fsync, exclusive dirfd-relative rename,
  descriptor/path revalidation, and each directory fsync never clobber another
  creator or leave an acceptably partial result;
- post-commit controller/verdict failures never roll back their destinations;
  signal/deadline before result byte zero selects the indeterminate object,
  signal/deadline after each partial-write offset finishes only the frozen
  object, and EAGAIN/short-write/EPIPE/resource/output-expiry cases never
  manufacture a postcommit failure receipt; retained caller duplicates prove
  exact `F_GETFL`/temporary-`O_NONBLOCK`/unconditional-restore behavior for
  stdout and failure stderr when restoration succeeds, while injected restore
  failure proves the explicit detected residual-flag non-claim;
  writer mode still rejects an existing verdict, while the read-only final
  consumer requires the externally supplied raw verdict digest, never derives
  or defaults it from candidate/storage state, accepts a complete bound
  artifact, and rejects every digest/byte/path/schema/binding/evidence
  mutation;
- final-consumer import-phase tests prove that stdlib-only source preflight
  may descriptor-open/read the protocol helper only for identity/hash, but
  succeeds before those bytes are compiled, executed, registered, or
  pathname-imported; execution rereads only the same held no-follow descriptor
  with before/after device/inode/mode/link/size/Git-blob checks,
  path/source-name substitution never executes, the fixed authenticated module
  name is used, exactly that one repository-local source is allowed afterward,
  no third-party import or `sys.path` extension occurs, and controller/writer
  outer modes retain the zero-repository-local-import rule;
- spy-operation tests own all four private final-consumer signatures, require
  exactly one `preflight -> marker -> helper load -> validator -> postflight`
  call sequence and returned-result object identity, and inject an exception
  at every boundary to prove that no later phase is called;
- final-consumer endpoint tests mutate each source/status/bytecode/
  implementation-manifest/helper identity after preflight and require the
  final postflight to reject after stored-evidence validation, while retaining
  the explicit same-UID ABA non-claim;
- an exact-host `/usr/bin/python3 -B -I -S` positive 69-file consumption test
  and negative helper/verdict/schema/payload vectors prove the protocol helper
  really runs under frozen CPython 3.9.6 as well as 3.12.12; static tests reject
  later-only syntax and APIs from the helper;
- portable fake-binding CI for the native ABI/unavailable-symbol/errno matrix,
  plus the mandatory non-skipped real-Darwin/APFS integration for file,
  directory-root, cross-directory verdict, collision preservation, inherited
  ACL rejection, and directory-fsync behavior;
- a root-publication native-call probe that receives exactly the validated
  caller-derived artifact basename and rejects empty, dot, traversal, slash,
  backslash, NUL, newline, non-ASCII, and insufficient-`NAME_MAX` variants
  before entering the native wrapper;
- source/Puffer/module/interpreter/dependency/config/role drift at every
  endpoint, with hostile same-UID mutate/use/restore ABA explicitly asserted
  as an unproved full-lifetime trust boundary rather than a passing test;
- `accepted` remaining independent of all three valid learning outcomes; and
- a short real-stack smoke replay that produces identical initial and
  post-update tensor digests twice under the frozen seed/thread contract.

The long 2,956-update training run is authoritative evidence, not a routine
unit test.

## Implementation order

1. Obtain independent adversarial acceptance of this exact plan and resolve
   every substantiated P0/P1/P2 finding.
2. Commit the accepted plan by itself.
3. Add and commit the watched-red tests, including explicit enumeration in the
   repository CI unittest command; show that they fail because the protocol
   implementation is absent, not because existing tests regressed.
4. Implement the smallest dedicated protocol without changing Puffer or the
   environment.
5. Prove with watched injected-terminal tests and a real-stack smoke that the
   rollout-alignment gate executes before every optimizer update.
6. Run focused tests, deterministic duplicate smoke runs, repository tests,
   portable fake-native tests, the non-skipped frozen-host real Darwin/APFS
   publication integration, sanitizer checks where relevant, lint, and
   source-cleanliness checks.
7. Perform a line-by-line self-review against this plan.
8. Obtain fresh independent adversarial post-implementation review and resolve
   every substantiated finding.
9. Commit the reviewed implementation.
10. From that exact clean commit, run the full uninterrupted pilot into an
   external artifact directory.
11. Run the independent evaluator/verifier against the exact live Puffer root,
    run the read-only final consumer with the external raw verdict digest,
    archive the supervisor-handoff/evidence/verdict hashes and outcome in the
    external receipt, and leave the source commit exact and clean. The
    user-facing handoff may summarize that receipt, but no post-result source
    commit is part of this tranche.
12. Use the predeclared outcome—not retrospective PPO tuning—to select the next
    independently reviewed environment tranche.

## Exit gates

Implementation is complete only when:

1. a fresh adversarial reviewer accepts the plan after revisions;
2. watched-red provenance is preserved;
3. the portable native-wrapper suite and mandatory non-skipped real
   Darwin/APFS ABI/zero-ACL integration both pass on their declared hosts;
4. the public CLI has no protocol overrides;
5. the canonical manifest and all arithmetic are exact;
6. the live prepared Puffer/module/environment/source identities match at all
   declared endpoints and the report names hostile full-lifetime filesystem
   ABA as out of scope;
7. every accepted training and evaluation rollout proves zero episode
   terminals through decision 7 and dual terminal on decision 8 before any
   corresponding optimizer update or bitset acceptance;
8. model initialization and the short real-stack run reproduce canonical
   tensor digests;
9. the real eight-step recurrent collector and PPO update run without
   reference or shaping access;
10. every hard-integrity check remains zero/valid;
11. training completes exactly 2,956 updates independent of objective events;
12. only the six fixed checkpoints exist;
13. every fixed evaluation and checkpoint-zero repeat completes;
14. the independent verifier reproduces every checkpoint bitset;
15. the verdict accurately separates protocol acceptance from learning
   outcome and names its historical-training trust boundary;
16. both prospective publication intents and exact supervisor handoff records
    are fsynced before ACK, survive every injected immediate-postcommit child
    process-crash window while the OS/storage remain operational, and are
    never interpreted as proof of commit or power-loss ordering;
17. the read-only final consumer validates the exact 69-file artifact against
    the mandatory trusted externally supplied raw verdict digest, never
    derives that digest from storage, and does not rerun behavior;
18. focused, full, lint, syntax, sanitizer-relevant, mutation, and clean-source
    checks pass;
19. a fresh adversarial post-review has no unresolved P0/P1/P2 finding; and
20. no push, PR, merge, deployment, production role change, or external spend
    occurs.

## Explicitly out of scope

- a second train seed or seed sweep;
- a 95% learned-success threshold;
- a three-seed deterministic trainability gate;
- randomized or held-out F5 geometry;
- pickup, protect, advance, sack/stop, or pass probes;
- demonstrations, behavior cloning, action forcing, reference warm starts, or
  scripted reference policies;
- reward shaping, PBRS, dense progress reward, or reward search;
- hyperparameter, architecture, budget, checkpoint, or seed search;
- production 512x3 architecture equivalence;
- production authored state-bank publication or launcher authorization;
- exact interruption resume;
- OS-crash, power-loss, or storage/controller-failure durability ordering;
- native/CUDA optimizer parity or target NVIDIA performance;
- Linux x86 runtime qualification;
- full-match kickoff transfer, opponent anchors, league admission, or paired
  sides;
- PR creation, push, merge, deployment, or production release.
