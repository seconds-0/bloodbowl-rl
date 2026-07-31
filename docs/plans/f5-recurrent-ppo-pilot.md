# F5 recurrent Torch PPO pilot

Status: accepted protocol; implementation not started.

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
and a three-entry Xcode standard-library-only `sys.path`; it imports no local
or third-party module. Its complete environment is the exact nine-key map
produced by that command on the frozen host:

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
This closes continuity against ordinary mutation; it assumes no adversarial
concurrent filesystem mutation between the outer preflight and `exec`.
Watched negative fixtures add a second executable `.pth`, alter the allowed
`.pth`, inject `sitecustomize.py`, alter `sys.path`, and mutate an installed
package file, source-root bytecode, and sourceless bytecode, and must all fail
before model construction.

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
   run, writes only an `integrity-abort` receipt to the incomplete directory,
   and leaves no checkpoint from that rollout.

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
vector threads              20
frozen banks                0
frozen-bank percentage      0.0
horizon                     8
recurrent reset             true
```

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
beta2 compatibility field   0.999
Muon eps compatibility field 1e-12
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
`load_model_path = null`, and `frozen_enemy_path = ""`. The canonical
manifest contains and hashes the full effective nested argument mapping,
including unused compatibility fields. The runner rejects a missing, extra, or
changed effective field rather than letting generic defaults become an
unrecorded input.

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

## Frozen exposure budget

The foundation enumerated a safe zero-dice masked-uniform scoring subset with
per-episode probability:

```text
p = 4567 / 9,227,468,800
  = 4.949352957985618e-7
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

This is a comparator, not a guarantee. The neural policy is not uniformly
distributed over conditional support, its trajectory probabilities change
during training, and other scoring routes may exist. A zero-event result is
therefore `exploration-inconclusive`, not a 5% hypothesis-test rejection and
not proof of an optimizer defect.

Training always runs all 2,956 updates. It may not stop on the first
touchdown, continue until a touchdown, retry a seed, extend the budget, or
choose a later checkpoint based on results.

A 120-minute monotonic training cap and 180-minute whole-controller cap protect
the host. The training cap is checked only at update boundaries and is
independent of success. Hitting either cap produces `resource-truncated`
failure receipt in the clearly named incomplete staging directory, not a final
evidence directory, not an accepted completed experiment, and not a learning
failure. There is no resume path; an interrupted run restarts from update zero
under a new empty artifact directory.

The independent verifier has its own prospective 180-minute monotonic cap.
Its workload is only source/runtime validation plus the same six-checkpoint
post-training evaluation workload already inside the controller's
training-plus-evaluation 180-minute envelope, so this is conservative relative
to the measured local stack. The stdlib-only outer verifier monitors the total
deadline and gives each child only the remaining allowance; on expiry it
terminates and reaps the child, writes a `verifier-resource-truncated` receipt
only in a new sibling `<artifact>.verify-incomplete.<nonce>` directory, and
leaves the closed evidence directory byte-for-byte unchanged with no verdict.
Verifier expiry is an execution failure, not a learning outcome, and has no
resume or partial-acceptance path.

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
hashed. They contain policy tensors only because exact resume is explicitly
unsupported. The manifest records both the raw file SHA-256 and the canonical
sorted-tensor digest.

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
- parameter norm and drift summaries at fixed checkpoints;
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
worker records the pre-update canonical parameter digest and distance from
initialization without writing an event-triggered checkpoint or changing RNG.
If no objective event occurs, the fixed final checkpoint bounds the
no-objective drift.

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
is `+1`. The exact objective-event count and successful-episode bit count are
authoritative and must reconcile with rounded `env/tds_t0 * env/n`, objective
reward-component totals, and the episode-return cross-check.
`env/tds_t1` must remain zero.

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

- evaluate all eight declared action seeds;
- run exactly 32,768 episodes/seed;
- run exactly 16 vector rollouts/seed;
- collect 262,144 episodes/checkpoint;
- reuse the same seed and episode/vector ordering across checkpoints;
- record one little-bit-order packed success bitset per seed;
- record exact `k/n` and a two-sided 95% Wilson interval; and
- retain per-seed counts as well as the aggregate.

Checkpoint zero is evaluated a second time in another fresh process and every
bitset digest must match byte-for-byte. The independent verifier later
reconstructs checkpoint zero from the model-init seed, loads every checkpoint
through the fixed raw schema, reruns every evaluation seed, and requires
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

The worker installs a fail-closed audit hook for file and network access,
records the normalized opened-file set, and rejects forbidden Blood Bowl
reference/BC paths and all network connections. Static tests also scan pilot
implementation surfaces for reference-action constants and forbidden imports.

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
  live checkpoint evaluator/verdict writer;
- `tools/test_f5_recurrent_ppo_pilot.py` — watched unit/negative/integration
  tests; and
- this plan's implementation-status appendix, completed before the exact source
  commit used by the canonical run.

No Puffer patch, engine change, environment reward change, qualification-role
change, production launcher change, or source-tracked checkpoint/evidence
artifact is planned. If the real stack cannot satisfy the protocol without one
of those changes, implementation pauses and the plan returns to adversarial
review.

## Closed evidence contract

The controller builds a sibling staging directory and atomically renames it to
the requested new artifact directory only after a complete status manifest is
fsynced. It refuses an existing output path. Signals or unexpected exceptions
leave a clearly named incomplete staging directory that the verifier rejects.
Resource-cap and integrity failures add only a canonical failure receipt to
that incomplete directory. They never manufacture a shorter instance of the
completed evidence schema.

Before verification, the closed directory contains only:

- canonical protocol and effective-config receipts;
- source, runtime, dependency, Puffer, and module receipts;
- the 2,956-row canonical training trace;
- the six fixed 879,900-byte raw policy tensor files;
- fixed evaluation bitsets and summaries;
- one evidence manifest listing every payload path, byte count, SHA-256, and
  semantic digest.

The evidence manifest closes every payload and itself is never changed. It
also reserves exactly one non-payload path, `verdict.json`, which must be absent
before verification and is the sole permitted post-manifest addition. No
payload or manifest file may be missing, extra, non-regular, symlinked,
hardlinked, or changed after manifest creation. Paths are normalized relative
paths with fixed cardinality and naming. JSON is ASCII, canonical,
newline-terminated, duplicate-key-free, finite-number-only, and closed-schema.
Binary bitsets and checkpoints have exact expected sizes/types and separate
semantic digests.

After all checks and replay evaluations pass, the verifier writes canonical
`verdict.json` temporary-file-first, flushes and fsyncs it, atomically renames
it into that reserved path, and fsyncs the directory. The verdict contains the
immutable evidence-manifest SHA-256 and repeats the exact source, module,
protocol, and learning-outcome identities. A final consumer validates the
payload set against the evidence manifest, requires exactly that one additional
regular single-link verdict path, validates its closed schema, and requires its
embedded evidence-manifest digest to match before accepting it. A pre-existing,
mutated, linked, or second verdict is rejected. The external run handoff
records the verdict file SHA-256 because no file can recursively authenticate
its own bytes.

The verifier:

1. requires a clean exact Blood Bowl source commit and the same live prepared
   Puffer root;
2. validates every path, mode, link count, size, hash, schema, count, formula,
   source identity, runtime identity, module role, and config invariant;
3. rejects a pre-existing verdict;
4. reconstructs the frozen initialization twice and checks its canonical
   digest against checkpoint zero;
5. never invokes a Torch/pickle/ZIP container parser, loads each exact-size raw
   `.f5w` file only through the literal seven-tensor schema, calls strict
   `policy.load_state_dict`, and checks tensor finiteness/digests;
6. recomputes training totals, first-event classification, fixed schedules,
   intervals, bit counts, paired comparisons, and outcome classification;
7. reruns every fixed checkpoint evaluation under every fixed action seed and
   compares exact bitsets;
8. distinguishes independently replayed checkpoint behavior from the
   worker-authored historical training trace;
9. enforces its independently monitored 180-minute cap without writing inside
   the evidence directory on failure;
10. writes a canonical verdict atomically into the sole reserved path only
    after every gate passes; and
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
  duplicate-init tensor digest, and seed-domain separation;
- exact delayed-row plus tail Home/Away reward/terminal parsing, deliberate
  exclusion of rollout row 0, early-TD fixtures, bit packing, aggregate TD
  cross-checks, and every malformed reward/terminal combination;
- fixed checkpoint-only behavior and rejection of event-triggered or extra
  checkpoints;
- training continuation after first TD and exact final update count;
- fixed post-training evaluation ordering, seed count, episode count,
  checkpoint-zero repeat, Wilson intervals, and paired discordance math;
- nullable zero-denominator explained variance but rejection of non-finite
  objective losses or tensors;
- every hard-integrity counter mutation and impossible outcome classification;
- static and dynamic rejection of reference, BC, demo, forcing, shaped reward,
  alternate-seed, and network access;
- atomic new-directory behavior, incomplete/resource-truncated/integrity-abort
  semantics, controller and verifier wall-cap expiry, external verifier failure
  receipts, and no resume;
- checkpoint truncation/trailing bytes, wrong exact size, non-finite raw
  tensors, attempted legacy Torch/pickle/ZIP containers, file-hash drift, and
  canonical-tensor-digest drift;
- evidence missing/extra/truncated/trailing/noncanonical files, wrong
  counts/hashes, traversal names, symlinks, hardlinks, and pre-existing or
  mutated verdicts; the sole reserved post-manifest verdict addition and its
  evidence-manifest binding receive positive and negative coverage;
- source/Puffer/module/interpreter/dependency/config/role drift;
- `accepted` remaining independent of all three valid learning outcomes; and
- a short real-stack smoke replay that produces identical initial and
  post-update tensor digests twice under the frozen seed/thread contract.

The long 2,956-update training run is authoritative evidence, not a routine
unit test.

## Implementation order

1. Obtain independent adversarial acceptance of this exact plan and resolve
   every substantiated P0/P1/P2 finding.
2. Commit the accepted plan by itself.
3. Add and commit the watched-red tests; show that they fail because the
   protocol implementation is absent, not because existing tests regressed.
4. Implement the smallest dedicated protocol without changing Puffer or the
   environment.
5. Prove with watched injected-terminal tests and a real-stack smoke that the
   rollout-alignment gate executes before every optimizer update.
6. Run focused tests, deterministic duplicate smoke runs, repository tests,
   sanitizer checks where relevant, lint, and source-cleanliness checks.
7. Perform a line-by-line self-review against this plan.
8. Obtain fresh independent adversarial post-implementation review and resolve
   every substantiated finding.
9. Commit the reviewed implementation.
10. From that exact clean commit, run the full uninterrupted pilot into an
   external artifact directory.
11. Run the independent evaluator/verifier against the exact live Puffer root,
    archive the evidence/verdict hashes and outcome in the external receipt,
    and leave the source commit exact and clean. The user-facing handoff may
    summarize that receipt, but no post-result source commit is part of this
    tranche.
12. Use the predeclared outcome—not retrospective PPO tuning—to select the next
    independently reviewed environment tranche.

## Exit gates

Implementation is complete only when:

1. a fresh adversarial reviewer accepts the plan after revisions;
2. watched-red provenance is preserved;
3. the public CLI has no protocol overrides;
4. the canonical manifest and all arithmetic are exact;
5. the live prepared Puffer/module/environment/source identities match;
6. every accepted training and evaluation rollout proves zero episode
   terminals through decision 7 and dual terminal on decision 8 before any
   corresponding optimizer update or bitset acceptance;
7. model initialization and the short real-stack run reproduce canonical
   tensor digests;
8. the real eight-step recurrent collector and PPO update run without
   reference or shaping access;
9. every hard-integrity check remains zero/valid;
10. training completes exactly 2,956 updates independent of objective events;
11. only the six fixed checkpoints exist;
12. every fixed evaluation and checkpoint-zero repeat completes;
13. the independent verifier reproduces every checkpoint bitset;
14. the verdict accurately separates protocol acceptance from learning
    outcome and names its historical-training trust boundary;
15. focused, full, lint, syntax, sanitizer-relevant, mutation, and clean-source
    checks pass;
16. a fresh adversarial post-review has no unresolved P0/P1/P2 finding; and
17. no push, PR, merge, deployment, production role change, or external spend
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
- native/CUDA optimizer parity or target NVIDIA performance;
- Linux x86 runtime qualification;
- full-match kickoff transfer, opponent anchors, league admission, or paired
  sides;
- PR creation, push, merge, deployment, or production release.
