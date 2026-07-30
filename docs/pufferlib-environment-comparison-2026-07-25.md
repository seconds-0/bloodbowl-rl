# What PufferLib's environments actually teach us

An evidence-based comparison with the Blood Bowl RL environment

Date: 2026-07-25

Blood Bowl audit base:
`origin/main@73cba42d15cac8adc8654a5a247b12ed8c12718a`

PufferLib audit base:
`c5d3c637446047a6efbcaa74c039c5295d201ab0`

Puffer website audit base:
`09944e6d40a4267eb772aa21500bcfad4531d188`

Official experiment release commit:
`e87175a8db0c21c81f932f1b4e0867361812dc0f`

Historical documentation audit base:
`6c53e15d840f8a0ef55583545b724c33dc8bc0ef`

Implementation addendum, 2026-07-30:

- `tail-bootstrap-v1` remains implemented and locally validated, with its
  fresh target-NVIDIA acceptance run still pending.
- Entropy schedule/objective parity is now implemented in the pinned native
  eager, native graph, and Torch source stack under
  `cosine-update-index-over-total-updates-fp32-v1`.
- A primary fresh exact-pin macOS/ARM checkout installed twice and an
  independent fresh checkout installed three times. Both reproduced the same
  six installed source/contract identities, built real CPU extensions and
  standalones, passed the schema-3 compiled-extension Torch objective verifier
  and final installer drift guard, and authenticated the selected 11-patch
  causal trainer/binding audit set. The selected exact tree passed 92/92
  entropy/Torch tests, 179/179 combined
  qualification/exact/recurrent/rollout tests, and 7/7 strict-source tests;
  all five valid environment profiles constructed while all 44 malformed
  profiles were rejected. Repository discovery passed 364 tools tests with
  six skips and, with the selected exact root enabled, 309 training tests with
  one expected GPU skip; `make test` and the leak-disabled ASan/UBSan run also
  passed. The complete identity and endpoint ledger is in the entropy plan.
- The exact-pin x86 CI job is configured but has not run. Schema-11 NVIDIA
  eager/graph/Torch evidence has not run. Both production launchers therefore
  remain literally and unconditionally fail-closed with status
  `implemented_pending_nvidia`.

The immediate evidence sequence is now: finish target-GPU rollout-tail
validation, execute the exact-pin x86 job, then execute and independently
review the schema-11 NVIDIA matrix. Those are evidence-collection and release
gates for implemented code; they are not permission to start a production
training run.

## Executive verdict

The premise needs one important correction: I found no official open-source
PufferLib environment for Command & Conquer, Red Alert, or OpenRA, and no
official claim that PufferLib trains a Command & Conquer agent to win in two
minutes. I searched the current source tree, fetched branches and tags, project
history, the PufferAI organization, official site and documentation, published
paper, experiment release, and public experiment pages. The closest official
case is a purpose-built miniature 5v5 MOBA.

The old “10 seconds to 2 minutes” statement is real, but it described Puffer's
small first-party sanity environments. It predates MOBA in the stable Ocean
registry. The current published paper says Pong takes 3–5 seconds, Breakout
20–30 seconds, and most other environments 1–10 minutes on an RTX 5090—not that
arbitrary complex strategy games solve in two minutes. See the
[historical Ocean page](https://pufferai.github.io/build/html/rst/ocean.html),
[current documentation](https://puffer.ai/docs.html), and
[PufferLib paper](https://rlj.cs.umass.edu/2025/papers/RLJ_RLC_2025_151.pdf).

There is still a valuable lesson here, and it supports the user's intuition:
environment construction is currently a larger blocker than raw PPO throughput.
But the missing ingredient is not basic Puffer integration. Blood Bowl already
does several hard things better than most official Ocean examples:

- exact, conditional joint actions and legality masks in both backends;
- a native batched C environment with direct buffers;
- complete BB2025 matches rather than a toy rules subset;
- strong differential, mutation, sanitizer, observation, action, reward, and
  provenance tests;
- explicit terminal handling and much richer telemetry;
- self-play and a historical opponent pool.

The central gap is a **trainability contract** between rules correctness and
full-match self-play. The current program asks a recurrent policy to discover
pickup, protection, advancement, scoring, defense, clock management, and
long-horizon match strategy together, yet it has no production capability
ladder and no learning-level test that proves PPO can overfit even one known
state or a small scenario family. The existing authored drill machinery is a
promising foundation, but the proof bundle is small, not canonical or
training-ready, and the production configuration currently starts every game
from kickoff.

Two environment correctness defects were confirmed with runtime probes:

- a successful pass that exposes multiple interception candidates temporarily
  becomes `BB_BALL_ON_GROUND` across a defender decision. The environment emits
  a false possession loss and later a false gain, corrupting reward components,
  observations, possession paths, and PBRS state;
- an admitted nested state-bank reset can initialize exact PBRS from
  post-action `Phi(s1)` rather than restored-state `Phi(s0)`, producing the
  wrong first shaping emission.

The pass defect must be fixed before pass curricula or another reward screen.
The reset-baseline defect must be fixed before nested authored states are
eligible for PBRS training.

The highest-leverage execution order is therefore:

1. finish target-GPU validation of rollout-tail closure, run exact-pin x86
   validation, and qualify the implemented entropy schedule across native
   eager, native CUDA-graph, and Torch training on NVIDIA;
2. repair pass/possession and restored-state PBRS initialization, and make
   curriculum input fail-closed;
3. finish a typed, hash-pinned authored BB2025 scenario bank;
4. add deterministic one-state and randomized-family PPO trainability gates;
5. use an explicit pickup → protect → advance → score capability ladder first
   as a learnability gate, then as a bounded refinement curriculum where the
   transfer evidence supports it;
6. evaluate only on held-out full games from kickoff, paired on both sides
   against a versioned, style-diverse opponent set;
7. only after those gates pass, test observation normalization/structure,
   exact-action performance work, and joint environment/trainer sweeps.

This is not a proposal to make Blood Bowl into Puffer MOBA. The transferable
practice is to make each capability reachable, measurable, and cheap to
iterate. The non-transferable parts are the fixed map, fixed weak opponent,
automatic targeting, heavily simplified action semantics, and shaped proxy
objective.

## Scope, definitions, and method

### What “all open-source PufferLib environments” means here

There is no authoritative registry of every unaffiliated project that has ever
imported PufferLib. The exhaustive, reproducible scope for this audit is:

1. every directory under `ocean/` at the audited current PufferLib commit;
2. current build metadata, binding ABI, configuration, and tests;
3. the official experiment release and current website catalog;
4. historical first-party registries and Puffer-maintained third-party
   integration directories;
5. public official documentation, blog, paper, release artifacts, and public
   experiment records.

The audit does **not** silently equate a source directory with a maintained,
trainable benchmark. That distinction matters because the current repository's
top-level `all` build can record individual failures and still return success,
and CI does not build every environment.

I use four labels:

- **source directory**: code exists in the official repository;
- **current ABI candidate**: it has the current vector binding and required
  observation tensor metadata;
- **configured training candidate**: it also has a normal current config path;
- **result-backed environment**: the official `experiments` release contains
  run logs for it.

At the audited commit there are:

| Scope | Count |
|---|---:|
| Current `ocean/` source directories | 61 |
| Current ABI candidates | 41 |
| Plausible configured training candidates | 40 |
| Environments with official release result sets | 20 |
| Partial current migrations | 5 |
| Legacy/unfinished bindings using a removed API | 15 |
| Historical Puffer-maintained integration directories | 26 |

The full classified inventory is in the appendix.

### Depth of examination

Every current directory was structurally classified by binding generation,
tensor ABI, configuration, and presence in official result artifacts. I then
read representative environments across the important design families:

- very small diagnostic MDPs;
- board games with masks and curriculum;
- arcade/vector-control tasks;
- recurrent partial-observation tasks;
- reset-heavy procedural environments;
- multi-agent games and scripted-opponent tasks;
- the MOBA case study;
- the result and build infrastructure.

The purpose was not to summarize game rules. It was to find repeated
construction decisions that plausibly affect correctness, throughput, or
learning, and then check whether Blood Bowl already implements them.

### Limitations

- Official release logs establish that experiments were run, not that every
  environment is solved or maintained at current HEAD.
- Website demo readiness is not evidence of training readiness.
- Puffer's “SPS” is generally agent steps per second. Cross-environment values
  are not comparable without accounting for agents per world, what one step
  means, reset behavior, and hardware.
- The current selected MOBA artifact does not record a GPU model. Its measured
  wall time should not be attributed to an RTX 5090.
- The suspected upstream MOBA observation-layout defect is a high-confidence
  static finding, not an executable regression result.
- Blood Bowl experiment evidence is taken from the repository's decision ledger
  and plans at the pinned audit commit. The clean current-main checkout contains
  no local run/checkpoint corpus, so remote artifact claims should be reconciled
  against sidecars before a new launch.

## The timing claim, carefully reconstructed

### What Puffer officially says

The historical Ocean documentation described a small suite of environments
designed to expose implementation errors and said they trained in roughly
10 seconds to 2 minutes. A stable 1.0 registry still contained small tasks such
as Squared, Bandit, Memory, Password, Performance, and Stochastic, but not MOBA.
The inherited prose now appears above generated documentation for later-added
environments, which makes the scope easy to misread. See the
[stable 1.0 registry](https://github.com/PufferAI/PufferLib/blob/91460f7b14edd1b43d6b19150cef5c51b80cbb7f/pufferlib/environments/ocean/environment.py)
and the [Ocean 0.6 blog discussion](https://puffer.ai/blog.html#post-4).

The modern performance claims are impressive but different:

- current docs advertise up to roughly 20M simulation SPS for native
  environments and 5M end-to-end PyTorch SPS;
- the paper reports 12 first-party C environments above 1M simulation SPS and
  PPO throughput of roughly 300k–1.2M SPS on one RTX 4090;
- the paper's later version note gives seconds for Pong/Breakout and 1–10
  minutes for most other environments on one RTX 5090.

These are environment- and hardware-specific numbers. Throughput is not solve
time, and solve time against a fixed script is not general strategy competence.

### What the current MOBA artifact shows

The official `experiments` release contains 1,202 MOBA run records, which is an
important reminder that the polished final curve sits on top of a large
engineering and search process. A selected current artifact reports:

| Artifact time | Agent steps | Logged win fraction |
|---:|---:|---:|
| 2.48 s | 7.21M | 32.4% |
| 3.08 s | 9.31M | 61.4% |
| 4.02 s | 12.78M | 95.2% |
| 5.22 s | 17.24M | 100% |
| 11.11 s | 38.93M | run complete |

It runs at roughly 3.5–3.7M **agent** steps/s. The hardware model is not present
in the artifact, and the task is the narrow fixed-map/fixed-script matchup
described below. Treat this as evidence that a tuned, compact environment can
learn its showcased matchup extremely quickly—not as evidence about C&C or
general MOBA competence. The source of the artifact is the
[official experiments release](https://github.com/PufferAI/PufferLib/releases/tag/experiments).

### A transparent historical RTX 4090 MOBA run

A separately inspectable public run provides a more conservative reference:

| Property | Public run |
|---|---|
| Hardware | 1× RTX 4090, 16 physical / 32 logical CPU cores |
| Seed | 1 |
| Runtime | `_runtime` ≈ 775.96 s, about 12m56s |
| Final throughput | ≈ 348,028 agent SPS |
| Final logged steps | 276.48M agent steps |
| Opponent | fixed simple scripted Dire policy |
| Map/task | fixed |

Its training-window win fraction was approximately:

| Runtime | Agent steps | Radiant win fraction |
|---:|---:|---:|
| 118 s | 35.84M | 39.9% |
| 121 s | 36.86M | 33.3% |
| 139 s | 43.01M | 66.7% |
| 145 s | 45.06M | 81.0% |
| 181 s | 57.34M | 90.0% |
| 184 s | 58.37M | first 100% window |
| 776 s | 276.48M | approximately 100% |

At two minutes it was not yet consistently winning. It crossed majority wins
around 2m19s, reached 90% around 3m01s, and logged its first perfect recent-game
window around 3m04s. These are training-window aggregates, not held-out
evaluation. The public sources are
[run `evp6128l`](https://wandb.ai/jsuarez/pufferlib/runs/evp6128l),
[machine metadata](https://api.wandb.ai/files/jsuarez/pufferlib/evp6128l/wandb-metadata.json),
and its
[pinned source/config](https://github.com/PufferAI/PufferLib/tree/ef8cf350ab65136a337e29fa8cd63f893dd7448d).

The tempting 96-second public run is explicitly `--mode eval`: it loaded an
already-trained model. It is not a sub-two-minute training result. See
[run `2oiprf0p`](https://wandb.ai/jsuarez/pufferlib/runs/2oiprf0p) and its
[metadata](https://api.wandb.ai/files/jsuarez/pufferlib/2oiprf0p/wandb-metadata.json).

### The unrelated OpenRA result

There is a 2026 OpenRA/Red Alert RL project outside PufferLib. Its own write-up
says the baseline drew all five games, performed zero combat, and did not
demonstrate a winning agent. It uses an OpenEnv/Gym-style interface, not an
official Puffer environment. This is likely part of the conceptual
conflation—but it does not support the original claim. See the author's
[“what this baseline actually demonstrates” disclosure](https://huggingface.co/blog/jadetan/openra-rl#what-this-baseline-actually-demonstrates).

## Why the MOBA looks complex but learns quickly

The environment is visually busy, but its learning problem is aggressively
engineered.

| Dimension | Actual MOBA construction |
|---|---|
| World | One fixed 128×128 map |
| Entities | 10 heroes, 100 creeps, 72 neutrals, 24 towers |
| Learned side | Five Radiant heroes sharing one policy |
| Opponent | Five heroes driven by simple scripted `creep_ai` |
| Observation | 510 `uint8` values, intended as an 11×11×4 local crop plus 26 self/status values |
| Action | Six heads: `[7, 7, 3, 2, 2, 2]` |
| Semantics | x/y motion, coarse attack target class, three ability toggles |
| Automated mechanics | nearest-target scan, basic attack/targeting, pathing and many low-level mechanics |
| Reward | death, XP, distance, tower shaping; victory logged but no explicit win reward |
| Current parallelism | 2,048 controlled agents, approximately 409 concurrent five-agent matches |
| Current run budget | about 39.1M agent steps |
| Model | small recurrent policy; current tuned config uses 64 hidden units and approximately five layers after integer conversion |

The source is available at the
[audited PufferLib commit](https://github.com/PufferAI/PufferLib/tree/c5d3c637446047a6efbcaa74c039c5295d201ab0/ocean/moba);
the current parameters are in
[`config/moba.ini`](https://github.com/PufferAI/PufferLib/blob/c5d3c637446047a6efbcaa74c039c5295d201ab0/config/moba.ini).

The policy does **not** learn:

- an economy or build order;
- production queues;
- arbitrary unit selection and grouping;
- arbitrary target coordinates;
- human UI interaction;
- drafting;
- map variation;
- fog-management strategy;
- a population of competent opponent styles.

This is not a criticism. It is good environment design for a focused benchmark.
It explains why visual complexity is a poor proxy for learning complexity.

### MOBA resets and batching

Reset is deliberately cheap:

- the original map is restored by `memcpy`;
- towers and heroes are respawned/reset in place;
- immutable path data are shared;
- each environment keeps scratch state;
- observations are written directly into fixed buffers.

Puffer then trains thousands of shared-policy agent streams concurrently. In
the historical run, the config implies about 800 matches and 4,000 controlled
hero streams. Dividing the final 348k agent SPS by five gives roughly 69.6k
match ticks/s. That is still fast, but it shows why Blood Bowl must not compare
its coach decisions directly to the headline agent-SPS figure.

### It is a tuned final artifact, not the whole development cost

The historical reward and optimizer parameters are non-round sweep outputs. The
sweep target was a tower-survival metric. The current official release contains
1,202 MOBA experiment records. “It learns in seconds” describes the marginal
cost of one already-designed, already-tuned final run. It does not include:

- environment implementation and debugging;
- action/observation design;
- reward search;
- model and optimizer search;
- discarded seeds and configurations;
- robustness evaluation that was never part of the narrow showcase.

That distinction is directly relevant to Blood Bowl. We should optimize
wall-clock iteration, but we should not expect a single production run to pay
back missing capability scaffolding automatically.

### Upstream MOBA is not a correctness gold standard

The current source has several concerning properties:

1. It internally autoresets when a base dies but does not write terminal flags,
   so a trainer/recurrent state can cross the match boundary.
2. Some per-episode logger fields are assigned instead of accumulated before a
   generic normalization step, making parts of the detailed victory telemetry
   unreliable.
3. There is no time limit.
4. Several tuned floating-point config values are converted to integers.
5. The observation writer appears to use pixel base `p` instead of `4*p` while
   writing four channels. Adjacent pixels overwrite one another; only offsets
   0–123 of the intended 484-byte spatial block are actively touched before the
   model reshapes all 484 bytes to 11×11×4.

The fifth finding is a high-confidence static defect, but it was not confirmed
by compiling an upstream regression during this audit. The appropriate test is
to write distinct values into a known 2×2 neighborhood and assert:

```text
obs.reshape(11, 11, 4)[y, x]
    == [tile, health, mana, level]
```

The important conclusion is not “Puffer is buggy.” It is that a successful
learning curve can coexist with substantial environment defects when those
defects are stable enough for the policy to adapt. Fast learning does not prove
that an environment is correct or that its design should be copied wholesale.

## Repeated construction practices across Ocean

The current catalog contains tiny MDPs, arcade games, board games, navigation,
control, multi-agent, procedural, and external-engine tasks. No single recipe is
used everywhere, but several patterns repeat.

### 1. Fixed contiguous buffers and direct writes

Native environments allocate observations, actions, rewards, terminals, and log
storage up front. Step functions mutate plain state and write directly into
trainer-visible buffers rather than constructing Python dictionaries and
objects per decision.

Blood Bowl status: **already implemented.**

Action: preserve this property. New scenario and representation work should not
reintroduce per-step serialization.

### 2. Many simultaneous agents and overlap

Puffer batches many worlds per worker, uses multiple buffers, OpenMP where
appropriate, and overlaps CPU simulation with GPU learning. First-finished
pooling helps when episodes or resets are uneven.

Blood Bowl status: **substantially implemented.** The current default is 4,096
agent rows, 2 buffers, and 20 threads, corresponding to 2,048 two-team matches.

Gap: the current measurements should be reported as actual coach decisions/s,
matches/hour, and touchdown opportunities/hour. Puffer agent SPS is not a
like-for-like success metric.

### 3. Precompute and share immutable work

MOBA shares path data; several grid/control environments precompute maps,
neighborhoods, or reset templates. Craftax keeps a pool of pre-generated worlds,
trading memory and diversity for a roughly 500× reset improvement in the
documented configuration.

Blood Bowl status: **partially implemented.** Fixed layouts and native data are
already cheap, and exact legal-support work has been optimized before.

Gap: reprofile the current exact-action build. Historical prototype numbers
predate the present semantics. Cache only what the profile identifies, and keep
reset/scenario diversity visible in the benchmark.

### 4. Compact sufficient observations

The strongest environments avoid pixels when structured state is available.
Partial-observation tasks use local crops and recurrence. The official tutorial
also recommends keeping observation and reward magnitudes around `[-1, 1]`
where practical and inspecting scale explicitly.

Blood Bowl status: **semantically strong, numerically unproven.** `obs-v6`
exposes a rich 2,782-byte exact state interface, but it mixes binary,
categorical, count, and 0–255 features, which the default encoder simply casts
to float before a flat projection.

Gap: measure per-feature distributions, activation/gradient conditioning, and
then A/B normalization, embeddings, and a structured encoder. This is a
hypothesis, not yet a diagnosed defect.

### 5. Factor or automate low-level action mechanics

MOBA factors movement/target class/abilities and auto-selects precise targets.
Board games represent only legal moves. Several environments collapse
deterministic transitions internally.

Blood Bowl status: **already stronger than most examples.** The current exact
joint interface implements:

```text
type → arg
type → square
type,arg
```

with conditional support, singleton inactive masks, and fail-closed decoding in
both backends.

Gap: do not redesign this merely because MOBA has six heads. First measure what
fraction of decisions is genuinely forced or strategically redundant. Any
forced-window collapse or macro policy is a semantic and lineage change and
requires decision-trace equivalence tests plus a fresh canary. Prior macro-move
work improved a mirror-offense proxy but lost head-to-head, so “more
abstraction” is not automatically better.

### 6. Curriculum and reset engineering

Curriculum patterns are environment-specific:

- Chess samples FEN states heavily and randomizes color;
- Maze uses map pools and difficulty;
- Drone varies task/domain parameters;
- Tetris varies garbage/performance conditions;
- G2048 uses scaffold episodes but excludes them from the headline evaluation;
- Craftax pools generated worlds;
- Target respawns targets without treating every contact as the final task.

Blood Bowl status: **machinery exists, production trainability ladder does not.**
There is a replay bank, strict-bank tooling, authored state schemas, and a
26-record proof bundle. The default `demo_reset_pct` is zero, the authored proof
is explicitly not canonical/training-ready, and the replay bank is
opening-censored.

The project's curriculum history supplies important constraints:

- a 90% pickup mixture learned the drill while catastrophically regressing in
  full games;
- even some 50% pickup/post-kickoff mixtures distorted transfer;
- a 50% passing mixture did transfer when it refined an already
  kickoff-competent policy;
- that passing skill decayed at 10% maintenance and appeared to need roughly
  25% in that experiment.

Gap: finish the existing authored-bank plan and use it first for deterministic
and family-level learnability sentinels. Apply a training mixture only when a
specific capability's transfer evidence justifies it, keep it at or below 0.5,
and retain separate full-kickoff evaluation. The positive passing result does
not justify making a large drill mixture the permanent distribution for an
untrained fresh policy.

### 7. Scripted opponents, self-play, and fixed evaluation

Puffer uses fixed scripts to create cheap learnable targets, and some
environments support self-play or historical policies. Chess randomizes color.
The MOBA showcase, however, only proves performance against one simple script.

Blood Bowl status: **more advanced but not diverse enough.** It has self-play,
a historical pool, a contact bot, and a cage-offense bot.

Gaps:

- the existing scripted transfer evaluator already crosses bot styles and both
  sides, but that paired diagnostic should be a standard promotion gate;
- primary/frozen league routing fixes logical roles to physical slots, and
  historical score bookkeeping assumes slot zero is the learner; randomizing
  routing without changing the bookkeeping would be wrong;
- two scripted styles do not span passive, ballhawk, fast/wide, anti-stall,
  clock-management, and roster-conditioned behaviors;
- a historical pool can be broad in checkpoint count yet narrow in capability
  if all descendants come from the same behavioral basin.

### 8. Reward components plus real behavior telemetry

Ocean environments commonly use a small number of interpretable reward
components and expose episode outcomes separately. Protein runs joint searches
over reward, model, optimizer, and system parameters rather than treating the
trainer as fixed.

Blood Bowl status: **instrumentation is much stronger than upstream examples.**
The current environment exposes 144 logs and 16 hard counters, exact terminal
rebuilds, a reward envelope, and zero-budget integrity gates.

Gap: the latest eight-arm decomposition screen did not produce touchdowns and
could not identify a reward winner. Six runs converged to block-only behavior;
two converged to near-total abstinence. The same reward configuration produced
both regimes under different seeds, so a reward mechanism cannot be inferred.
The environment needs scoring-capability gates before another large reward
sweep.

### 9. Differential and stress testing

Craftax includes differential parity/stress work; current Puffer docs recommend
metadata checks, full buffer initialization, reset staggering, and sanitizers.

Blood Bowl status: **already a major strength.** It has canonical-engine
differential testing, exact action tests, mutation testing, AddressSanitizer /
UndefinedBehaviorSanitizer coverage, and detailed observation/reward
regressions.

Gap: correctness tests stop short of learning tests. “The transition is legal”
and “PPO can acquire the intended capability from this distribution” need to be
two separate required gates.

## Blood Bowl's current learning contract

At the audited commit:

| Dimension | Current environment |
|---|---|
| Rules/task | exact BB2025 C11 engine, full matches |
| Rosters | 30 teams plus procedural generation |
| Observation | `obs-v6`, 2,782 `uint8` values |
| Action | exact three-head conditional joint action: 30 × 33 × 391 supports |
| Parallelism | 4,096 agent rows / 2,048 matches, 2 buffers, 20 threads |
| Policy | hidden 512, three MinGRU layers |
| Training horizon | 64 |
| Discount / GAE | gamma 0.995, lambda 0.85 |
| Nominal budget | 2B agent steps |
| Opponents | self-play/historical league, contact bot, cage-offense bot |
| Curriculum | replay/authored machinery present; production default disabled |
| Metrics | 144 logs, 16 hard-integrity counters |
| Validation | 546 current C tests plus Python/integration tooling |

This is not an obviously underbuilt environment. It is attempting a much harder
learning distribution than the MOBA showcase:

- complete matches instead of a single fixed tactical objective;
- a much larger conditional action interface;
- dozens of asymmetric rosters;
- long delayed touchdown and win credit;
- alternating learned sides and historical opponents;
- stochastic dice plus reroll decisions;
- setup, turn, drive, half, and match phases;
- no production scenario ladder.

The right comparison is therefore not “why are we slower than 3.7M hero
steps/s?” It is:

> How many strategically meaningful coach decisions and touchdown opportunities
> do we generate per wall-clock hour, and can a small recurrent policy learn
> each prerequisite capability from the distribution it actually sees?

## Confirmed defects and evidence-backed missing pieces

### P0: pass flight creates phantom possession transitions

This was confirmed by a temporary compiled probe against the audited commit; no
repository file was modified.

Constructed state:

- away carrier at `(10, 7)`;
- away receiver at `(16, 7)`;
- two home interception candidates;
- scripted successful pass and catch rolls;
- possession gain `+0.05`, loss `-0.06`.

Observed transition:

1. On the away `PASS_TARGET` action, the engine calls `bb_drop_ball`, enters the
   defender's interception decision, and exposes the ball as
   `BB_BALL_ON_GROUND` at the thrower.
2. `bbe_update_ball_possession` ends away possession and emits `-0.06`.
3. Home declines the interception.
4. The pass resolves to a held ball at the away receiver.
5. The tracker starts a new away possession and emits `+0.05`.

Successful passes with zero or one interception candidate commonly settle
atomically and emit neither transition. Thus, the same football outcome has
different reward/observation semantics solely because an intermediate decision
window was exposed.

Affected current reward families:

- gain+loss families impose a phantom net `-0.01` completed-pass tax;
- gain-only families award a phantom `+0.05`;
- distance/PBRS families see a spurious loose-ball potential regime;
- observation and possession telemetry are wrong in all cases.

Required fix:

- represent the ball as `BB_BALL_IN_AIR` for the full interception/catch
  window only if that state contract is deliberately widened, or explicitly
  classify the relevant PASS phases as unsettled in the environment adapter;
- add exact transition tests for zero, one, and multiple candidates;
- cover decline, successful interception, failed interception, catch, and
  catch-reroll branches;
- assert observation, reward components, possession count/path, and PBRS
  potential on every exposed policy step.

This is a real correctness defect but not an explanation for the broad D233
zero-touchdown collapse: those policies rarely or never passed, and the defect
requires an exposed multi-candidate interception window. Obs-v6 already exposes
the candidate list; this is a state-settlement problem, not a missing candidate
feature.

### P0 before curriculum: the default bank pipeline is edition-blind and sampling can fail open

The clean audited checkout has no local bank because these artifacts are
gitignored, so it would be inaccurate to say a mixed file is staged in that
checkout right now. The static pipeline is nevertheless unsafe:

- `validation/build_state_bank.py` consumes normalized replays without a
  rules-version filter;
- `tools/install_puffer_env.sh` stages the unqualified
  `validation/states/bank.bbs`;
- repository documentation identifies the canonical input digest as 15,471
  records containing 123 BB2020 records;
- the documented strict 15,348-record BB2025 bank has a different path/digest;
- a corroborating operational artifact in the other local checkout matches the
  documented mixed digest.

Further, a missing/incompatible/malformed bank can silently disable curriculum.
Predicate selection rejection-samples up to 256 times and then can keep the last
out-of-predicate state. `demo_fallbacks` only increments for a later
non-decision restore, so telemetry can say the requested tier was used when it
was not.

Required fix:

- require an explicit bank kind: strict replay or authored scenario;
- pin file digest, edition, engine fingerprint, schema, and scenario manifest;
- pre-index eligible record IDs for every requested stratum;
- fail launch when curriculum is requested and the bank or stratum is absent;
- sample exactly from an eligible vector;
- log requested tier, eligible count, selected record ID/hash, and restore
  rejection separately;
- make the installer require an explicit bank path/manifest rather than copying
  the ambiguous default.

### P1 fairness diagnostic: frozen-league routing is fixed by side

The egocentric observation/action contract already mirrors Away, pure
self-play's shared policy sees both physical slots, and the existing scripted
transfer evaluator crosses both bot styles on both sides. It would therefore be
wrong to say that side invariance or paired scripted evaluation is absent.

The residual issue is narrower. Primary/frozen league routing fixes logical
roles to physical slots, and historical score bookkeeping assumes slot zero is
the learner. A persistent side effect could contaminate pool win-rate
accounting or training distribution.

Required sequence:

1. make paired side-conditioned evaluation a standard promotion gate;
2. measure whether the current egocentric contract leaves a material residual
   asymmetry;
3. only if it does, add a seeded logical-to-physical slot mapping;
4. carry explicit learner-side identity through permutation, rollout tagging,
   and historical pool-score bookkeeping.

Naively swapping physical slots would corrupt pool statistics. This is not the
main explanation for zero scoring and should not displace capability tests.

### P0 configuration hygiene: several environment kwargs lack strict validation

At minimum:

- `force_home_team`, `force_away_team`, and `exclude_team` must be `-1` or a
  valid team ID before indexing team definitions;
- `scripted_opponent_team=2` must implement and validate the documented
  0/1/2 enum rather than silently clamping values above one;
- curriculum percentages and predicate ranges need closed bounds;
- boolean-like flags should reject values other than 0/1.

The environment should abort before workers start. Silent coercion produces
plausible-looking experiments with the wrong task.

Implementation note (2026-07-28): this construction boundary is now specified
and operated in `docs/environment-configuration.md`; the schema validates all
51 keys before allocation while preserving empty and sparse dictionaries.

### P0 trainer/environment boundary: the final rollout transition was missing

The pinned Puffer trainer stores delayed rewards and terminals: slot `t`
contains the outcome of action `t-1`. It nevertheless executed the final action
in every horizon while CPU and CUDA advantage loops stopped at
`horizon-2`. Torch discarded the final pending reward/terminal at the next
training boundary; native copied the same outcome into the next rollout's slot
zero, which the advantage calculation did not consume. One real transition per
agent per rollout was therefore absent from the PPO objective.

This is especially destructive for short capability sentinels. An eight-action
scoring scenario with `horizon=8` emits its only touchdown reward and terminal
after the eighth action—the exact transition the old trainer dropped. The
unwritten final advantage remained zero and was then included in advantage
normalization, so this was not equivalent to omitting that row cleanly.

The same audit found a native V-trace split: CPU/CUDA scalar code weighted only
the reward by `rho`, while the CUDA vector path weighted the complete temporal
difference. The closure standardizes every path on
`rho * (reward + bootstrap - value)`.

Implementation status (2026-07-28): this branch adds `tail-bootstrap-v1` to
Torch, CPU, and native backends; retains one explicit post-action
reward/terminal/value record; computes every horizon slot; authenticates the
compiled contract through installer/launcher/qualification identities; and
adds an independent 14-case advantage oracle plus a real heterogeneous
rollout-to-train oracle. The Torch and CPU paths are locally testable. Native
CUDA compilation, graph replay, and device evidence still require the declared
fresh NVIDIA deployment-boundary run; no local macOS result is represented as
that evidence.

### P0 trainer objective: historical entropy divergence repaired in source; NVIDIA qualification pending

Before the 2026-07-29 entropy tranche, the production configuration enabled a
nonzero entropy coefficient, annealing to a minimum ratio, and
`cudagraphs=10`, but the audited pinned trainers did not apply that request
consistently. Native `current_ent_coef` was a host scalar passed while the
train graph was captured, so later graph replays retained the captured value
rather than the coefficient for the current update. Torch used
`config["ent_coef"]` directly and did not implement the configured anneal.
Native eager, native graph, and Torch therefore optimized different objectives
over time. This paragraph records the historical source defect; it does not
describe the repaired source stack below.

The transition-parity cells deliberately retain zero entropy and zero learning
rate, so they cannot prove the entropy schedule and are not repurposed to do
so. Schema 11 instead requires a separate nonzero entropy matrix: the five
primary artifacts
`entropy_native_eager_annealed`,
`entropy_native_graph_annealed`,
`entropy_native_graph_anneal_disabled`,
`entropy_torch_annealed`, and
`entropy_torch_anneal_disabled`, plus the mandatory sixth
`entropy_native_eager_anneal_disabled` gradient control. PufferLib later fixed
the native issue upstream by moving the coefficient to device-backed state
and added a multi-epoch effective-loss test, corroborating both the defect and
the appropriate implementation shape. See the official
[entropy coefficient annealing fix](https://github.com/PufferAI/PufferLib/commit/2753605e).

Implementation status (2026-07-30):

- `training/puffer_entropy_schedule_parity.patch` implements the named
  `cosine-update-index-over-total-updates-fp32-v1` contract.
- Native source owns a stable binary32 device coefficient and one
  kernel-local value for gradient scaling, signed entropy term, total loss,
  and telemetry. Torch computes the same applied binary32 coefficient once per
  public update and reuses it across minibatches.
- Both public update paths reject negative update indices and exhausted indices
  (`e < 0` or `e >= N`) before PPO work or schedule-state mutation.
- Once either trainer may have partially mutated model, optimizer, or RNG
  state, it fails closed for its remaining lifetime. Native uses a
  dispatch-aware RAII transaction and Torch a pessimistic latch. Every
  supported trainer-bound callable rejects a poisoned object before domain
  validation, I/O, environment/CUDA work, mutation, or publication; `close()`
  is the sole cleanup exception after the failed update has unwound.
  Distributed recovery is a whole-job restart from trusted state, not an
  in-process retry.
- Native exact-coefficient telemetry is a direct reduction: global index zero
  contributes the raw binary32 coefficient and every other lane contributes
  zero. An interval mean remains useful operational telemetry, but is not
  accepted as bit-exact proof of the coefficient applied by the kernel.
- Both compiled bindings export the contract. Installer, launch manifests,
  patch bundles, exact-source identity, and the schema-11 qualifier bind it.
- Schema 11 requires the six named artifacts above and compares
  first/middle/final schedule points, applied coefficient, signed objective
  term, and
  `ppo-entropy-preclip-gradient-v1`. Native graph/eager counters are genuinely
  measured native-only arrays; Torch is required to omit them rather than
  fabricate zero counters.
- A standalone CPU verifier executes selected Torch `PuffeRL.train` through
  backward, Torch's real gradient clip, and the following recording-optimizer
  step. Its active-clipping control proves the optimizer observes the clipped
  gradient. The ordinary schedule/gradient cells deliberately keep weights
  unchanged; separate injected incomplete-update cases intentionally mutate
  model/optimizer state before failing, then prove the trainer fails closed
  rather than presenting that object as retryable.
- A primary fresh exact-pin macOS/ARM checkout installed twice and an
  independent checkout installed three times; all five runs preserved the
  same six installed source/contract identities. Both checkouts built real CPU
  extensions and standalones and passed the compiled-extension verifier and
  installer `--check`. The selected patch-only chain passed all causal endpoint
  and final reverse/forward tree checks under independent review.
- On the selected exact trees, the entropy/Torch slice passed 92/92, the
  combined qualification/exact/recurrent/rollout slice passed 179/179, and the
  strict source contract passed 7/7. All five valid environment profiles
  constructed and all 44 malformed profiles were rejected. Full discovery
  passed 364 tools tests with six skips and 309 training tests with one
  expected GPU skip; `make test` and the leak-disabled ASan/UBSan run passed.

The fatal-first boundary is a supported-callable, single-threaded trainer
contract. Construction, factories, stateless helpers, direct mutable
attributes, and deliberate Python closure/code/global reflection, class
monkeypatching, or manual latch mutation are outside it. Torch preserves the
normal public name, qualified name, module, and exact signature without
publishing a standard `__wrapped__` alias, and its executable proof shows that
a poisoned evaluation-mode call rejects before the raw `bool(enabled)`
conversion. Native begins its guarantee after successful pybind argument
binding: the trainer cast is immediately followed by the fatal guard, before
raw delegation and every trainer-state, CUDA, environment, or I/O action.
Python arity errors and typed pybind conversion failures that occur before C++
body entry are outside the boundary. No method—including `close()`—is
supported concurrently with `train()`; cleanup remains available only after
the failed call has unwound and never clears the fatal latch.

The proof boundary is intentionally narrower than “optimizer parity.” Native
gradient evidence ends at raw PPO pre-clipping logits. Zero learning rate
proves unchanged weight bytes only; it does not prove native
`policy_backward`, clipping, Muon, parameter updates, or cross-backend
weight-update identity.

Remaining external evidence:

- run the configured exact-pin x86 CI job and retain its CPU evidence artifact;
- compile the final native source on the target NVIDIA toolchain;
- execute schema 11 for native eager, native graph, and Torch, including real
  graph handles/launches and the overrun guard; and
- independently review that target evidence before a separate
  release-authority change.

Both production launchers still bind the full requested schedule, report
`implemented_pending_nvidia`, and reject graph-plus-anneal execution before
creating a training run. Local CPU/source evidence cannot satisfy or bypass
those guards.

### P0 trainability: no learning-level capability gates

The repository has excellent transition-level tests but no production test that
trains PPO to overfit:

- one deterministic pickup;
- one protect/advance state;
- one scoring state;
- a small randomized family of each;
- one defensive sack/stop state;
- one pass state.

This is the missing bridge between “the environment is legally correct” and “a
gradient learner can acquire the intended behavior through this interface.”

The D233 screen is the strongest empirical warning. Across eight 500M-step arms:

- touchdown rate was zero;
- final performance was 0.5 and draw rate 1.0;
- six runs were active but learned block-only behavior;
- two collapsed to about 0.017 blocks and much shorter episodes;
- the same reward manifest produced both regimes across seeds.

That evidence does not identify a reward winner. It says the current
full-distribution training can fall into either an abstinence basin or a shaped
block-EV basin without acquiring scoring.

### P0 operational provenance: obs-v6 root status is inconsistent across docs

The top-level runbook and obs-v6 spec still say a fresh obs-v6 genesis and
genesis pool are required because the prior root is out of lineage. The later
D234 decision entry says all four obs-v6 genesis roots emitted zero clipping.
The clean local checkout contains no run artifact with which to reconcile those
statements.

Before the next run:

- designate one authoritative lineage ledger;
- identify the four D234 roots and their exact sidecars;
- verify source, module, patch-bundle, observation, action, precision, model,
  pool, and reward-manifest hashes;
- either bless one build-consistent genesis/pool or mint a new pair;
- update the stale top-level guidance.

This is an operational blocker, not evidence that obs-v6 itself is wrong.

### P0 before nested curriculum: exact-PBRS initializes the wrong reset baseline

The state-bank loader admits structurally valid resumable nested decisions, but
exact PBRS initializes its prior potential as inactive after every reset. On the
first action it substitutes the post-action potential for the missing baseline,
emitting:

```text
(gamma - 1) * Phi(s1)
```

instead of:

```text
gamma * Phi(s1) - Phi(s0)
```

A compiled probe restored a valid pending-Dodge-reroll state with a loose ball.
The successful reroll changed nearest-player fetch distance from three to two:
`Phi(s0)=1.10`, `Phi(s1)=1.15`. The environment emitted `-0.00575`; the exact
emission was `+0.04425`, a `-0.05` error.

Scope is narrow:

- ordinary historical boundary states generally first expose ACTIVATE/DECLARE,
  which leaves these ball-distance potentials unchanged;
- fresh kickoff starts have the relevant potentials inactive;
- the current F4 authored proof has the ball off-pitch.

This is not evidence that all existing runs were biased. It is a correctness
hole in the broader nested-state contract that the proposed authored curriculum
would rely on.

Required fix:

- compute and store exact-PBRS `Phi(s0)` immediately after restoring the banked
  state;
- retain the inactive sentinel only for the legacy `gamma=0` path;
- add first-action exactness tests for boundary records and nested held/loose
  ball states.

## Hypotheses that deserve experiments, not confident assertions

### Mixed observation scales

The default encoder casts the 2,782 bytes to float without feature-aware
normalization. Binary flags coexist with IDs, counts, and 0–255 maps. This can
distort first-layer optimization, but no current experiment isolates it.

Test:

1. log per-feature min/max/mean/variance and nonzero rate over at least one full
   held-out match corpus;
2. group features by semantic type;
3. compare the current raw encoder with:
   - normalized bounded scalars;
   - `/255` probability/map channels;
   - one-hot or embeddings for categorical IDs;
4. keep seeds, parameter budget, environment decisions, optimizer, and wall
   time paired.

Promote only if capability acquisition or full-kickoff transfer improves
without a material throughput regression.

### Flat representation of a relational board

The current model uses one biasless linear projection from the flat observation
into a 512-wide recurrent core. It must learn pitch geometry, entity identity,
and relation structure from scratch.

Test a Torch-side structured encoder first:

- spatial pitch planes;
- per-player/entity embeddings with team/role/status features;
- global phase/score/clock/resource features;
- action-head-conditioned pooled context;
- the same recurrent core and approximately matched parameter count.

Only write a native/CUDA encoder if the controlled Torch experiment wins. The
existing docs already anticipate this direction; the missing step is a clean
A/B after the trainability ladder exists.

### Phase-specific policies or auxiliary tasks

Setup, activation, block dice, pass/interception, and reroll decisions have very
different semantics. Phase-conditioned heads, a separate setup policy, or
auxiliary predictions may improve credit assignment:

- terminal result;
- next-turn possession;
- score within the current drive;
- loose-ball recovery;
- legal action family / procedure phase.

These are P2 until the base scenario ladder learns. Otherwise they add model
surface while the environment still cannot distinguish “bad representation”
from “never sees a reachable scoring target.”

### Forced/no-choice transition collapse

Fast-forwarding forced engine windows could improve meaningful decisions per
second. It could also change recurrent timing, reward timing, replay
compatibility, exact-action traces, and PBRS emission boundaries.

First measure:

- fraction of policy steps with one legal joint action;
- fraction with multiple encoded actions but one semantic outcome;
- time spent in each procedure family;
- reward/terminal events inside the candidate collapsed spans.

Only then implement under a new action/step lineage with trace-equivalence and
learning canaries.

## Ranked proposals

### P0-0 — Validate the implemented trainer/environment objective contract

Estimated effort: target evidence collection and review, plus any defects it
uncovers

Expected leverage: mandatory; all later learning evidence depends on it

Evidence class: locally implemented source/CPU/schema contract with target
execution still pending

Implemented locally:

1. `tail-bootstrap-v1` closes the final transition and standardizes the
   V-trace temporal difference in Torch, CPU, and native source.
2. The native entropy coefficient is device-backed with stable storage, and
   Torch implements the same checked update-index schedule. Both public paths
   reject `e < 0` and `e >= N` before PPO work or schedule-state mutation.
3. Requested schedule provenance and direct applied coefficient/signed-term
   telemetry are closed over installer, module, launcher, and qualification
   identities. The native raw coefficient comes from global index zero while
   all other lanes contribute zero; an interval mean is not treated as
   bit-exact raw proof.
4. The independent CPU Torch verifier covers first/middle/final, disabled,
   zero-base, real clipping, active clipping, and fail-closed negative and
   exhausted-index cases. It also injects second-minibatch and post-loop
   failures after mutation, then proves the epoch/evidence stays uncommitted,
   the object cannot be retried, and state, RNG, and filesystem publication do
   not advance through rejected surfaces.
5. Two fresh exact-pin installer runs preserve all six recorded
   source/contract identities; the available CPU surface is buildable and
   drift-checked, and the selected causal trainer/binding audit set is 11/11
   reverse-applicable.
6. Schema 11 requires five primary entropy artifacts—native eager annealed,
   native graph annealed/disabled, and Torch annealed/disabled—plus the
   mandatory native eager disabled gradient control.
7. The executable graph-plus-anneal guards remain literal and unconditional.

Remaining external deliverables:

1. Complete the fresh NVIDIA install/build and graph-on/graph-off acceptance
   run for `tail-bootstrap-v1`.
2. Run and retain the configured exact-pin x86 CPU job.
3. Run schema 11 on the target NVIDIA backend for native eager, native graph,
   and Torch with a coefficient that materially changes.
4. Independently review the raw target artifacts and only then plan a separate
   release-authority tranche.

Acceptance gates:

- every executed action has exactly one independently reconstructed advantage,
  including `H-1`;
- CPU, native scalar, and native vector V-trace agree for `rho != 1`;
- graph/eager transition outputs and graph execution counts match;
- effective entropy coefficient matches the declared schedule at the first,
  middle, and final epochs;
- negative and exhausted public update indices are rejected without state
  mutation or PPO work;
- after any post-latch Torch or post-dispatch native failure, the epoch and
  evidence remain uncommitted and the object permanently rejects all
  supported trainer-bound callables before validation, I/O, environment/CUDA
  work, mutation, or publication; only `close()` remains callable after the
  failed update has fully unwound, and a distributed run recovers only by
  restarting the whole job from trusted state;
- native eager, native graph, and Torch agree pointwise on the named schedule
  and applied binary32 coefficient;
- each backend independently satisfies its signed entropy-term and total-loss
  decomposition;
- native and Torch satisfy the declared pre-clipping entropy-gradient contract
  on their own captured logits/masks;
- requested/effective schedule provenance is present and finite;
- all six recorded source/contract identities are stable across repeated
  exact-pin installation, and the selected exact causal patch set is reverse
  applicable after build.

These gates do not require or claim native `policy_backward`, clipping, Muon,
parameter-update, or cross-backend optimizer parity. The schema-11
entropy-gradient diagnostic uses zero learning rate; unchanged weights in
those cells prove non-mutation only. Separate CPU failure-injection diagnostics
intentionally mutate model/optimizer state before proving fail-closed
behavior.

No capability or reward-training result is admissible while the target
rollout/entropy and release-authority gates remain blocked.

### P0-A — Correctness and input-integrity sprint

Estimated effort: 3–7 engineering days

Expected leverage: very high

Evidence class: confirmed/runtime and static defects

Deliverables:

1. Pass/possession settlement fix and branch-complete regression.
2. Typed, hash-pinned strict/authored bank loading.
3. Pre-indexed exact curriculum strata and fail-closed startup.
4. Exact-PBRS initialization from restored state `s0`.
5. Strict config validation.
6. Mandatory paired-side diagnostic, without changing league routing unless
   measured asymmetry justifies it.
7. Reconciled obs-v6 genesis/pool lineage record.

Acceptance gates:

- completed passes produce no phantom possession component under all
  interception-window shapes;
- exact observation and PBRS traces agree for equivalent pass outcomes;
- curriculum requested with an absent/wrong/empty bank aborts before training;
- zero BB2020 records can enter a BB2025 run;
- selected state always satisfies the requested stratum;
- paired fixed-opponent results are emitted for both sides;
- first exact-PBRS emission equals `gamma*Phi(s1)-Phi(s0)` for every admitted
  reset shape;
- invalid configuration mutations all fail.

Do not launch another reward screen until this tranche passes.

### P0-B — A learning-level environment test harness

Estimated effort: 4–8 engineering days

Expected leverage: highest

Evidence class: missing gate, strongly supported by D233

Build a fast harness that reuses the real observation, mask, decoder, reward,
trainer, and recurrent path while constraining reset distribution.

Initial scenarios:

| Capability | Deterministic seed | Randomized family |
|---|---|---|
| Pickup | one legal carrier/pickup path | ball/player/weather/opponent pressure |
| Protect | carrier plus reachable screen/cage choices | roster and defender geometry |
| Advance | carrier must improve field position safely | variable lane/screen geometry |
| Score | one- to three-turn scoring decisions | clock, movement, dodge/GFI variation |
| Sack/stop | defender can contest a scoring carrier | multiple defensive geometries |
| Pass | throw, interception window, catch/reroll | ranges, candidates, receiver geometry |

Each scenario should have:

- an explicit task-success signal and horizon;
- exact state and sidecar identity;
- held-out seeds/geometries;
- a random-action baseline;
- a scripted/reference baseline where possible;
- training and evaluation separated;
- deterministic replay and transition trace on failure.

Suggested initial gates—not universal truths; calibrate after random/scripted
baselines:

- deterministic training state: at least 95% success;
- held-out randomized family: at least 80% success;
- three seeds pass within a fixed decisions and wall-clock budget;
- no hard-integrity counters;
- no illegal decoder fallbacks;
- no reliance on a shaped metric when scenario success is zero.

The harness becomes environment CI. A future observation/action/reward/model
change is not eligible for a full run unless it preserves already-learned
capabilities and can still overfit the smallest cases.

Use these scenarios as sentinels before assuming they belong in the permanent
training distribution. A fresh obs-v6 lineage should first prove local
learnability. Where possible, use scenario mixtures to refine a policy that is
already capable from kickoff, matching the one positive historical passing
result.

### P1-A — Finish the authored capability ladder

Estimated effort: 1–3 weeks, much of it scenario authoring/validation

Expected leverage: very high

Evidence class: existing design and tooling, incomplete production asset

Finish the repository's authored-drill-state-bank plan rather than inventing a
parallel system.

Recommended ladder:

1. **Acquire** — pickup/recover a loose ball.
2. **Secure** — retain possession through one opponent turn.
3. **Advance** — move the ball toward the scoring end while controlling risk.
4. **Convert** — score from short and medium drive states.
5. **Defend** — mark, screen, sack, recover, and stop a near-term score.
6. **Pass** — select and execute tactically valid passing sequences.
7. **Drive** — combine acquire/secure/advance/convert over several turns.
8. **Match** — full kickoff distribution.

Implementation rules:

- scenario mode may end on scenario success/failure, but full-match mode must
  keep the true match objective and terminal boundary;
- pre-index and balance states by phase, half, score, clock, roster, side,
  ball state, action family, and difficulty;
- introduce a scenario mixture only after the local learnability sentinel
  passes and with an explicit full-match transfer hypothesis;
- cap scenario-reset mixture at 0.5;
- test an anneal such as 0.50 → 0.25 → 0.10 → 0.00, while recognizing that the
  historical passing result needed approximately 25% maintenance and therefore
  may require capability-specific scheduling;
- graduate on held-out capability success, not shaped return;
- evaluate every checkpoint from kickoff with `demo_reset_pct=0`;
- retain a zero-scenario control so transfer rather than memorization is
  measured.

The previous 0.9 pickup mixture is explicit negative evidence. Some 0.5
pickup/post-kickoff mixtures also distorted transfer. Passing at 0.5 was a
positive exception when refining a kickoff-capable policy. The purpose of the
ladder is to measure learnability first and then make a demonstrated rare
capability reachable without silently replacing the real task.

### P1-B — Diversify opponent capabilities and retain paired-side gates

Estimated effort: 1–2 weeks, incremental

Expected leverage: high

Evidence class: current opponent coverage and prior opponent-quality findings

Add versioned fixed anchors with deliberately different pressure:

- passive novice / legality sanity bot;
- contact/block pressure;
- cage/protection offense;
- fast/wide/switch offense;
- loose-ball ballhawk;
- anti-stall/clock pressure;
- conservative screening defense;
- roster-conditioned variants.

For each anchor:

- lock source and config digest;
- evaluate both sides on paired seeds;
- report win/draw/loss, TD for/against, drive conversion, possession recovery,
  episode decisions, and action-family rates;
- admit league checkpoints based on anchored capability and behavioral
  diversity, not self-play Elo alone.

This follows the useful part of Puffer's fixed-script practice while avoiding
MOBA's core limitation: optimizing solely against one weak script.

Opponent diversity follows local skill learnability. Adding more bots cannot
rescue a policy that fails a deterministic short scoring state.

### P1-C — Replace proxy-only dashboards with capability diagnostics

Estimated effort: 3–6 days

Expected leverage: high for iteration speed

Evidence class: D233 postmortem

Add:

- decision occupancy by procedure and action family;
- consumed-head entropy, KL, loss, and gradient norm by head/phase;
- forced/singleton joint-action fraction;
- decisions from possession start to turnover/TD;
- pickup → secure → advance → score funnel;
- value estimates and calibration by phase;
- side-conditioned performance;
- scenario-stratum identity and success;
- early block-only and abstinence alarms.

The D233 screen should have stopped early once all arms had zero touchdown
conversion and split into block-only/abstinence regimes. Better capability
telemetry reduces wasted wall time more than another raw-SPS optimization.

### P1-D — Run representation experiments after the ladder passes

Estimated effort: 1–2 weeks

Expected leverage: medium to high, uncertain

Evidence class: plausible conditioning/inductive-bias hypothesis

Experiment order:

1. raw feature-scale audit;
2. semantically normalized flat encoder;
3. categorical embeddings;
4. structured spatial/entity encoder;
5. only then native inference optimization.

Controls:

- same scenario/family seeds;
- same environment decisions and wall-time budget;
- matched parameter count where practical;
- capability time-to-threshold plus full-kickoff transfer;
- decisions/s and GPU utilization.

Reject an encoder that only improves shaped return or memorizes deterministic
states.

### P1-E — Reprofile and optimize exact support

Estimated effort: 3–10 days depending on profile

Expected leverage: medium

Evidence class: older pre-exact prototype profile, needs refresh

The old prototype found mask filling to be a large environment cost and showed
large gains from masked/factored legal sets. The current exact-joint
implementation is materially different.

Benchmark separately:

1. engine advance to next coach decision;
2. legal action generation;
3. observation encoding;
4. state copy/reset;
5. buffer/worker synchronization;
6. recurrent inference;
7. PPO update.

The current schema-11 qualification cell retains the rollout-timing design
introduced in schema 10 and times `_C.rollouts` only. It uses the production
collection shape—4,096 agents, two buffers, 20 threads, H512/L3,
`max_decisions=4096`—which makes it a useful rollout regression diagnostic,
but it is not end-to-end training SPS. Add an adjacent rollout-plus-train stage
timer before using the number to prioritize environment versus optimizer work.

Report:

- meaningful coach decisions/s;
- complete matches/hour;
- touchdown opportunities/hour;
- per-phase decision mix;
- p50/p95 step and reset latency;
- CPU/GPU utilization;
- agent SPS only as a secondary compatibility metric.

If exact support remains hot:

- factor repeated legality computation;
- cache procedure-local support until relevant state changes;
- precompute static pitch/neighborhood relations;
- eliminate duplicate support walks between masks and decode validation;
- preserve fail-closed exactness and mutation coverage.

### P2 — Specialize phases, collapse forced transitions, and add auxiliary heads

Estimated effort: several weeks

Expected leverage: uncertain

Evidence class: later-stage model/interface hypotheses

Candidates:

- separate setup policy/head;
- phase-conditioned actor/value projections;
- terminal/possession/drive-success auxiliary prediction;
- carefully collapsed forced/no-choice windows;
- macro actions only where exact trace-equivalence and head-to-head transfer are
  demonstrated.

Each changes the learning contract or lineage. None should precede the basic
proof that the current exact interface can learn the capability ladder.

### P2 — Resume joint Protein-style search

Estimated effort: experiment budget, after P0/P1 gates

Expected leverage: high only after the task is learnable

Evidence class: upstream search practice and current inconclusive screen

Once capabilities learn reliably, sweep jointly:

- scenario mixture/anneal;
- opponent mixture;
- bounded reward components;
- gamma, lambda, and horizon;
- recurrent size/depth;
- optimizer and batch/minibatch settings;
- system parallelism.

Use capability and full-kickoff anchored evaluation as multi-objective
selection. Do not select on block count, tower-like proxies, or self-play return
alone.

The current gamma/lambda/horizon imply difficult long credit assignment:
lambda 0.85 gives a direct GAE decay scale of only a handful of decisions even
though touchdown credit may be hundreds away. That deserves a sweep, but only
after the environment can generate and recognize reachable scoring sequences.

## A proposed six-week execution plan

### Week 1: correctness closure

- complete target-GPU rollout-tail validation;
- run the configured exact-pin x86 job;
- execute and independently review schema-11 NVIDIA evidence for the
  implemented cross-backend entropy schedule;
- retain both executable launch guards; removing them, if justified by the
  target evidence, is a separate release-authority tranche;
- repair pass settlement;
- add complete pass/interception/catch traces;
- make config validation strict;
- add side-paired evaluation;
- choose strict/authored bank identities and fail-closed loading;
- reconcile obs-v6 lineage artifacts.

Exit gate: target rollout/entropy evidence is accepted without overstating
optimizer parity, both launchers remain fail-closed absent separate authority,
and every P0-A acceptance test passes on a clean install.

### Week 2: trainability harness

- build deterministic single-state runner;
- implement pickup, score, sack/stop, and pass probes first;
- record random/scripted baselines;
- add capability success and per-head/phase instrumentation.

Exit gate: PPO overfits each deterministic probe across three seeds within a
declared wall-time/decision budget.

### Weeks 3–4: authored family and curriculum

- expand to held-out randomized families;
- finish typed authored bank/sidecars;
- implement exact strata and scenario terminals;
- run mixture 0.5 → 0.25 → 0.1 → 0 with kickoff-only evaluation.

Exit gate: capability-family success transfers to a nonzero full-kickoff
touchdown rate without integrity regressions.

### Week 5: opponent anchors

- add at least fast/wide and ballhawk/anti-stall styles;
- pair every matchup by side;
- define league admission on capability/behavior as well as strength;
- establish a fixed evaluation matrix.

Exit gate: improvement is visible against more than one opponent family and on
both sides.

### Week 6: representation and performance A/B

- run feature-scale audit;
- compare normalized flat vs current encoder;
- profile exact support and environment/trainer stages;
- decide whether structured encoder or legality-cache work is the next tranche.

Exit gate: select work from measured time-to-capability and full-kickoff
transfer, not intuition.

## Experiment promotion scorecard

The exact thresholds should be calibrated, but every promoted environment
revision should answer all five dimensions:

| Dimension | Required evidence |
|---|---|
| Correctness | zero hard counters; exact pass/terminal/reward traces; deterministic replay |
| Trainability | deterministic and randomized capability families meet declared success budgets |
| Transfer | improvement survives scenario mixture anneal to zero and full kickoff starts |
| Robustness | paired sides, multiple seeds, multiple fixed opponent styles, held-out scenario strata |
| Performance | coach decisions/s, matches/hour, TD opportunities/hour, p95 latency, end-to-end samples/s |

Stop rules:

- stop a reward/architecture arm early if scenario success remains at random
  while a shaped proxy rises;
- stop if the policy enters the established abstinence basin;
- stop if block/action volume rises without pickup/advance/score funnel
  improvement;
- stop if an integrity counter fires once;
- do not interpret one seed from a bimodal outcome distribution.

## What not to copy

The audit identifies several superficially attractive choices that would be
mistakes for Blood Bowl:

- **Do not call the MOBA result “C&C in two minutes.”**
- **Do not compare agent SPS directly.** Five controlled heroes produce five
  agent steps per match tick; Blood Bowl's relevant unit is a coach decision.
- **Do not reduce exact strategic choices merely to match a six-head action.**
- **Do not use one weak scripted opponent as the promotion target.**
- **Do not add a large reward menu.** D233 already shows a shaped block proxy
  becoming the objective.
- **Do not restore the old raw distance ratchet.** Prior Blood Bowl work showed
  it is farmable; exact PBRS exists for a reason.
- **Do not reactivate a 0.9 drill reset mixture.** The repository already has
  negative transfer evidence. Even 0.5 is capability-dependent; use scenarios
  as sentinels first and require full-match transfer.
- **Do not terminate ordinary full matches at a drive boundary.** Use a separate
  scenario mode so the real objective remains intact.
- **Do not assume an upstream successful curve certifies correctness.** The MOBA
  observation/terminal issues demonstrate otherwise.
- **Do not perform a broad architecture rewrite before behavior locks.** Fix the
  learning contract, then simplify around tests.

## Final recommendation

The Blood Bowl program is not missing “Puffer tricks” in the basic sense. It
already has the native buffers, batching, exact masks, recurrence, league
machinery, and testing discipline that distinguish serious Puffer environments.
Its blocker is that the distribution jumps directly from correct rules to the
full game without proving or staging the prerequisite capabilities.

The single most valuable deliverable is a production-grade **environment
trainability ladder**:

```text
correct transition
    → one-state overfit
    → randomized capability family
    → short multi-capability drive
    → mixed scenario/full-start curriculum
    → kickoff-only held-out evaluation
    → diverse paired opponents
```

That ladder will tell us where the failure actually lives:

- if one-state probes fail, inspect action/observation/reward/model plumbing;
- if one state learns but families fail, inspect representation and
  generalization;
- if families learn but transfer fails, inspect curriculum mixture and
  objective distortion;
- if full matches score but do not win, inspect opponent distribution,
  long-horizon credit, and strategy;
- if all of those work but are slow, optimize exact support and system
  throughput with a meaningful denominator.

That is the practical best practice behind Puffer's fastest demonstrations:
make the task boundary explicit enough that every failure is cheap to localize.

## Appendix A — Complete current Ocean inventory

The source tree audited here is
[PufferLib at `c5d3c637`](https://github.com/PufferAI/PufferLib/tree/c5d3c637446047a6efbcaa74c039c5295d201ab0/ocean).

### A1. Result-backed current ABI candidates (20)

Official `experiments` release record counts:

| Environment | Records |
|---|---:|
| `breakout` | 1,338 |
| `cartpole` | 1,219 |
| `connect4` | 1,201 |
| `drive` | 160 |
| `drone` | 1,201 |
| `enduro` | 1,200 |
| `freeway` | 1,200 |
| `g2048` | 626 |
| `go` | 177 |
| `maze` | 1,200 |
| `moba` | 1,202 |
| `nmmo3` | 1,476 |
| `pacman` | 1,200 |
| `pong` | 1,212 |
| `slimevolley` | 1,200 |
| `terraform` | 728 |
| `tetris` | 1,200 |
| `tower_climb` | 825 |
| `trash_pickup` | 903 |
| `tripletriad` | 1,199 |
| **Total** | **20,667** |

These are the strongest official evidence of exercised training paths. They do
not all establish solve thresholds or current-HEAD correctness.

### A2. Current ABI candidates without an official release result set (21)

`boxoban`, `chess`, `craftax`, `craftax_classic`, `dino`, `docking`,
`double_pendulum`, `drmario`, `hex`, `laser_puzzle`, `lightsout`, `minimal`,
`nethack`, `overcooked`, `robocode`, `rware`, `scape`, `squared`,
`squared_continuous`, `target`, `whackamole`.

`scape` lacks the normal config, leaving 40 of the 41 current ABI candidates as
plausible configured training paths.

### A3. Partial migrations rejected by the current build contract (5)

`benchmark`, `blastar`, `convert`, `snake`, `whisker_racer`.

These have vector bindings but retain older observation/action metadata and
omit the current required observation tensor type.

### A4. Legacy or unfinished directories using the removed binding API (15)

`asteroids`, `battle`, `boids`, `chain_mdp`, `checkers`, `convert_circle`,
`impulse_wars`, `matsci`, `memory`, `onestateworld`, `onlyfish`, `shared_pool`,
`tactical`, `template`, `tmaze`.

These should not be presented as 2026 maintained, trainable benchmarks merely
because code exists.

### A5. Observation storage among current ABI candidates

- 13 use byte observations.
- 28 use float observations.

That mix reinforces an important lesson: Puffer does not prescribe `uint8` for
all tasks. The representation should reflect semantics and conditioning, with
the tensor type declared explicitly.

## Appendix B — Historical Puffer-maintained integrations

Historical Puffer trees contained 26 integration directories:

`atari`, `bsuite`, `butterfly`, `classic_control`, `crafter`, `dm_control`,
`dm_lab`, `griddly`, `links_awaken`, `magent`, `microrts`, `minerl`,
`minigrid`, `minihack`, `nethack`, `nmmo`, `nmmo3`, `nocturne`, `ocean`,
`open_spiel`, `pokemon_red`, `procgen`, `slimevolley`, `smac`, `stable_retro`,
`vizdoom`.

These are primarily wrappers/integrations around third-party environments. They
are evidence of PufferLib compatibility work, not evidence that Puffer authors
implemented, tuned, solved, or still maintain every underlying environment.

## Appendix C — Pattern examples by environment family

| Pattern | Representative environments | Transferable point |
|---|---|---|
| Tiny diagnostic MDP | `minimal`, `squared`, `target`, historical sanity suite | Use fast tasks to verify the trainer/environment learning loop |
| Board-game legality | `chess`, `go`, `connect4`, `tripletriad` | Mask legal actions; randomize side/color; use position curricula |
| Arcade/native throughput | `breakout`, `pong`, `pacman`, `freeway`, `enduro` | Fixed buffers, cheap resets, direct structured/native state |
| Partial observation/recurrent | `maze`, `memory`, `nethack`, `nmmo3` | Give sufficient local/context state and preserve episode boundaries |
| Procedural/reset-heavy | `craftax`, `terraform`, `rware`, `trash_pickup` | Pool/precompute expensive reset work without hiding diversity |
| Continuous control | `cartpole`, `double_pendulum`, `drone`, `docking` | Match tensor type and scale to the task |
| Multi-agent/scripted opponent | `moba`, `robocode`, `slimevolley`, `overcooked` | Shared policies and scripts make capabilities cheap to exercise, but require held-out opponents |
| Curriculum/scaffold | `chess`, `maze`, `tetris`, `g2048`, `target` | Separate scaffold training from headline evaluation |

## Appendix D — Source map

Primary external sources:

- [PufferLib current source at the audited commit](https://github.com/PufferAI/PufferLib/tree/c5d3c637446047a6efbcaa74c039c5295d201ab0)
- [Puffer current documentation](https://puffer.ai/docs.html)
- [Puffer Ocean catalog](https://puffer.ai/ocean.html)
- [Puffer blog](https://puffer.ai/blog.html)
- [PufferLib paper](https://rlj.cs.umass.edu/2025/papers/RLJ_RLC_2025_151.pdf)
- [Official experiments release](https://github.com/PufferAI/PufferLib/releases/tag/experiments)
- [Historical MOBA training run](https://wandb.ai/jsuarez/pufferlib/runs/evp6128l)
- [Historical MOBA pinned source](https://github.com/PufferAI/PufferLib/tree/ef8cf350ab65136a337e29fa8cd63f893dd7448d)
- [Unrelated OpenRA-RL disclosure](https://huggingface.co/blog/jadetan/openra-rl#what-this-baseline-actually-demonstrates)

Primary Blood Bowl evidence at the audited commit:

- `CLAUDE.md`
- `DECISIONS.md`, especially D226, D233, and D234
- `puffer/config/bloodbowl.ini`
- `puffer/bloodbowl/bloodbowl.h`
- `puffer/bloodbowl/binding.c`
- `engine/src/proc_ball.c`
- `validation/README.md`
- `validation/build_state_bank.py`
- `tools/install_puffer_env.sh`
- `docs/obs-v6-spec.md`
- `docs/plans/authored-drill-state-bank.md`
- `docs/reward-and-replay-audit-2026-07-09.md`

The companion structural-risk report is
[`audit-artifacts/architecture-analysis-2026-07-25.md`](../audit-artifacts/architecture-analysis-2026-07-25.md).
