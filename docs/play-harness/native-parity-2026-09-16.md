# Native CUDA policy parity, 2026-09-16

**Question.** D399 and D400 left one item open: does the play harness's CPU torch
policy produce the same action distributions as the rig's native CUDA policy on
the same observations? It matters now because seating the offense bot in the
harness showed an unexplained offset. Against chain 30 the bot scores 0.309 TD
per game on the harness and 0.342 on the rig exam, a difference of -0.033
[-0.056, -0.009] (`scripted-anchors-2026-09-15.md`).

**Status.**

- The comparator is built and validated on the Mac.
- The rig recorder is built and passed a CPU dry run.
- The GPU recording is queued behind chain 34's exam, so no native numbers exist
  yet.
- The screening tolerances below were fixed before any rig data exists.

Branch `feat/harness-native-parity-20260916`. The code lives in
`play_harness/parity.py`, `tools/parity/record_native.py`,
`tools/parity/native_parity_queue.sh` and `tools/parity/dryrun_queue.sh`. A Codex
review found five P2 issues in the first version; all five are addressed here
(see "Review changes").

## What is compared

| Side | Forward | Sampler arithmetic | Recurrence |
|---|---|---|---|
| Native (rig) | live `_C` at fbaec58, built `--float`, module sha `d63498f6`. `policy_forward` (cuBLAS `puf_mm` plus the `mingru_gate` kernel) inside the captured rollout graph | `sample_logits`: fp32 running log-sum-exp, `expf(l - lse)`, cumulative sum against `curand_uniform`, and the remainder to the last legal action | evaluation mode: state persists across rollout calls and `reset_recurrent_state_on_terminal` zeroes terminal rows |
| Harness `native` kernel | `MinGRUPolicy.forward_eval`, `fast_sigmoid` and branchy lerp, fp32 CPU torch | `select_joint`: torch fp32 `log_softmax`, `exp`, `torch.multinomial` | `PolicySeat`: every c_step, zeroed at each new match |
| Harness `torch` kernel | same, with exact sigmoid and `torch.lerp` | same | same |

The checkpoint is chain 30's final blob (`41ecd998`, 4,016,640 floats).

## Method

**Recorder** (`tools/parity/record_native.py --backend native`). It runs the live
extension read-only, through `tools/puffer_cuda_runtime.py` (D225 init order),
with every CUDA library resolved from the live venv. It refuses to start if any
CUDA library in `/proc/self/maps` comes from outside the venv. The configuration
is the exam's native eval command, with three changes:

- **`train.horizon = 1`.** Each `rollouts()` call is one forward, one exact-joint
  sample and one `c_step`. `qualification_snapshot()` then returns that forward's
  decoder output (raw logits plus value), the rewritten conditional masks, the
  sampled actions, logprobs and terminal flags. The per-forward batch is
  unchanged: 2048 agents in 2 buffers gives the exam's 1024 rows per forward, so
  cuBLAS sees the exam's matrix shapes. This is the same horizon `puffer eval`
  and `puffer match` use.
- **`env.scripted_opponent = 0`.** The policy drives both seats, so both seats'
  forwards are recorded on on-policy observation streams.
- **`env.max_decisions`** is set per run, to force terminals in one of the two
  runs.

**Action source: the native side's own sampled actions, replayed into the
harness.** I chose this over a scripted action sequence for three reasons:

- It keeps chain 30 on its own state distribution, which is where the game
  outcomes come from.
- It exercises the native sampler's rewritten conditional masks, which a
  scripted sequence would bypass.
- The harness never has to sample, so no RNG has to match. The comparison is
  between distributions over identical observation streams.

**Lockstep shim.** For every recorded env the recorder steps the bbplay shim in
lockstep. The shim is compiled from the live env snapshot the extension was
built from (`vendor/PufferLib/ocean/bloodbowl`, `bloodbowl.h` sha `4e116972`).
It works as follows:

- It searches the bbplay `episode` argument that reproduces step 0. The env is
  reset twice before recording, so this should be 1.
- It requires byte-identical observations for both rows at every step.
- It requires the native terminal flag to follow exactly the steps where the
  shim's `c_step` ended a match.

Any disagreement aborts the run with `MISMATCH.json`.

**Joint support: what can be captured natively.** I read the live trainer source
read-only (`vendor/PufferLib/src/bindings.cu`, `pufferlib.cu`, `vecenv.h`,
`pufferlib/*.py`) to see what Python can reach:

- The support the exam samples from lives in the trainer vec's host buffers
  (`vec->joint_actions`, `joint_action_offsets`, `joint_action_counts`). The
  `PuffeRL` object from `create_pufferl` exposes no vec, and
  `qualification_snapshot()` copies only the rollout buffers and decoder outputs.
  Reading that exact buffer would require a new binding, which means patching
  and rebuilding the extension under test. I did not do that.
- The same extension exposes those three buffers on `VecEnv`
  (`joint_actions_ptr` and friends), the object `_C.create_vec` returns for the
  torch backend. The recorder builds such a vec on CPU buffers (8 agents, one
  buffer, the same env config and seeds), resets it until its step-0
  observations equal the native rows (one extra reset, because
  `create_pufferl` resets once more than `create_static_vec`), and steps it with
  the native sampled actions. At every forward boundary it reads the packed
  support for each recorded row into `native_support`. This is the exam binary's
  own env and packing code on the same state sequence. It is not the trainer
  vec's buffer.
- `native_support` is kept only if the mirror's observations and terminal flags
  stayed equal to the native rows for the whole trace. Any failure (construction,
  alignment or divergence) is written to `RUN.json` under
  `native_support_capture` and never aborts the recording, because this code path
  cannot run before the GPU window.
- Independently of the mirror, the native rewritten masks along the sampled tuple
  are checked against the shim's support conditioned on the native tuple
  (`masks_vs_support_mismatch_steps`). That covers natively observed data: the
  full type set (the head-0 mask is rewritten to every type in the support), the
  arg set of the sampled type, and the square set of the sampled (type, arg).

The shim's support (`support`) is always recorded too, and
`native_vs_shim_support_mismatch_steps` compares the two at every step. When the
mirror capture is present, the comparator uses `native_support` for joint
distributions. When it is absent, joint distributions assume that the native and
shim supports agree on branches the native sampler did not take. That
assumption rests on both sides compiling the same env TU from byte-identical
sources and producing byte-identical observations. A support difference on an
unsampled branch changes neither the observations nor the recorded masks, so it
would not be detected (`test_unsampled_branch_support_difference_is_invisible_to_masks`).

**Runs** (envs 0-3, both seats, so 8 fixtures per run):

| Run | Seed | Steps | `max_decisions` | Terminals |
|---|---|---|---|---|
| `md4096_s42` | 42 | 1000 | 4096 (exam default) | natural (about 614 c_steps per game) |
| `md150_s43` | 43 | 600 | 150 | truncation, several per env |

**Recorded per step, per seat** (`bbplay-parity-fixture-v1`, superset):

- `obs` bytes, the native `terminal` flag, `reset`, `deciding`;
- the native rewritten 454-bit `masks`, sampled `actions` and joint `logprob`;
- `value`, raw `logits` (all 454 columns);
- the shim `support`, and the mirror `native_support` when captured, each with
  its offsets;
- `masked_logits` (-inf outside the masks) and per-head `probs`, both computed
  in float64 from the native logits under the native masks.

**Comparator** (`python -m play_harness.parity compare`). It replays each
fixture's observation stream through both harness kernels with the recorded
reset boundaries. It rebuilds every match on the Mac shim, following terminals
into episode + 1, checks recorder self-consistency, and reports two distribution
families:

- **`forward_*`: forward-logit parity under a common float64 normalization.**
  Both sides' logits go through the same float64 softmax, so any difference comes
  from the forward pass: layout, kernels, recurrence or roundoff.
- **`sampler_*`: native sampler vs harness sampler.**
  `parity.native_fp32_head` reproduces `sample_logits`' fp32 per-head arithmetic
  on the recorded native logits. Under a uniform draw, the effective distribution
  is the difference of clipped cumulative sums, with the remainder given to the
  last legal action. `parity.harness_fp32_head` reproduces the harness sampler
  (torch fp32 `log_softmax`, `exp`, normalized by `torch.multinomial`) on the
  harness logits. This is what each backend actually samples from.

The difference between the two families isolates the sampler arithmetic. With
identical logits the sampler family still differs. Codex's example: two legal
logits of 1000 give fp32 log-sum-exp 1000.693176, native probabilities
0.49998546 and 0.50001454, and TV 1.45e-5 from the float64 0.5/0.5. The forward
family reads zero there.

**Validation of the fp32 routine.**
`play_harness/tests/native_sampler_ref.c` is a host transliteration of the
kernel's per-head loop, compiled with `cc -O0 -ffp-contract=off`. Against 240
random heads (sizes 30, 33 and 391, logit scales 1, 50 and 1000, exact ties at
the top):

- log-sum-exp agrees within two fp32 units in the last place;
- cumulative probabilities agree within a few units;
- selected indices agree on more than 1,500 uniform draws, excluding draws
  within 1e-5 of a boundary, where a one-unit difference in `expf` can move the
  selection.

The routine reproduces the Codex example. On the Mac validation traces it
reproduces the harness recorder's torch logprobs to 1.1e-5 (fp32 arithmetic
differences, not a defect). The rig recorder records
`recorded_logprob_vs_native_fp32_sampler_max_abs`, which checks the routine
against the native kernel's own logprobs. numpy's float32 `exp`/`log` and CUDA
libdevice `expf`/`logf` may differ by a unit in the last place.

## What is measured

| Metric | Definition | Role |
|---|---|---|
| `logit_step0_max_abs_diff` | first forward, no recurrence | gate |
| `logit_max_abs_diff`, `logit_mean_abs_diff` | all steps | report only: fp32 roundoff compounds through the recurrence (5.0 table: 1.6e-3 to 3.5e-3) |
| `head_prob_max_abs_diff` | unmasked per-head softmax, as in the 5.0 table | report |
| `value_max_abs_diff` | value column | gate |
| `unmasked_head_argmax_agreement` | as in the 5.0 table | report |
| `masked_head_prob_max_abs_diff` | float64 per-head softmax under the recorded conditional masks | gate |
| `masked_head_argmax_agreement` | deciding steps | gate |
| `logprob_max_abs_diff` | float64 harness joint log p of the native tuple vs the native fp32 logprob | gate |
| `forward_head_tv_max`, `forward_head_tv_mean` | per-head TV, float64 normalization, recorded masks | report |
| `forward_joint_tv_max`, `forward_joint_tv_mean`, `forward_joint_tv_p99` | TV between the float64 joint distributions over the packed support | gate |
| `sampler_head_tv_max`, `sampler_head_tv_mean` | per-head TV, native fp32 sampler vs harness torch fp32 sampler | report |
| `sampler_joint_tv_max`, `sampler_joint_tv_mean`, `sampler_joint_tv_p99` | the same over the joint support | gate |
| env parity | first step where the shim's obs, decision owner, support or terminal boundary differs | gate |
| consistency | step 0 resets; reset equals terminal; waiting rows carry the singleton NONE support and tuple; actions lie in support; native masks equal support conditioned on the tuple (`masks_vs_support_mismatch_steps`); mirror support equals shim support (`native_vs_shim_support_mismatch_steps`) | gate |

## The rig-parity tests

The original `test_rig_fixture_parity` expected four wrong things:

1. **It read `BBPLAY_CHECKPOINT`.** That variable is the conftest's chain 25
   default, so a rig run would have loaded the wrong checkpoint or raised
   `KeyError`.
2. **It took one fixture directory, one seat per env var.**
3. **Env parity stopped at the first terminal.** The recurrence reset after a
   terminal, the part most likely to differ, was never checked.
4. **It gated only the sampled tuple's logprob and the value, at 1e-4.** That
   bound says nothing about the probability of the actions not taken. It also
   sits near fp32 resolution at logits of |1e3|.

There are now two tests, at `BBPLAY_PARITY_FIXTURE` (default
`.play-artifacts/parity/native-20260916`) with chain 30 from
`BBPLAY_PARITY_CHECKPOINT`:

- **`test_rig_suite_parity`** runs only when `RESULT_COMPLETE.json` exists. It
  uses `parity.check_native_suite` to require a non-dry-run completion manifest,
  exactly the runs `md4096_s42` and `md150_s43` (a unit test pins these to the
  queue script's `RUNS`), each run's `RUN.json`, and exactly the 16 fixtures
  `<run>/<run>-env{0..3}-row{0,1}` with a native backend. It also requires a
  terminal in every truncated-run fixture and a natural terminal in the
  default-budget run. Then it applies `parity.ACCEPTANCE` to both kernels. A
  partial suite fails.
- **`test_rig_partial_fixture_integrity`** runs on whatever native fixtures exist,
  complete or not. It checks env replay and recorder consistency only, and makes
  no completeness or distribution claim.

Both skip with a reason when no fixture exists.

## Mac validation (harness native kernel vs harness torch kernel)

The harness backend of the same trace shape
(`python -m play_harness.parity record-selfplay`, native kernel, sampling, both
seats) recorded two chain 30 traces:

- `hv-md4096-s42`: 1000 c_steps, a natural terminal;
- `hv-md150-s43`: 500 c_steps, three truncation terminals.

Both traces have both seats, so 4 fixtures and 1,500 decisions. The comparator
then replayed them through both kernels
(`native-parity-2026-09-16/harness-validation.json`, comparator v2). The
recorded side here is the harness native kernel with the torch sampler, so the
sampler family measures the native-fp32 algorithm against the torch sampler, not
a CUDA backend.

| Metric | torch kernel vs recorded native kernel | native kernel vs itself |
|---|---|---|
| Logits, step 0 | 4.8e-7 | 0 |
| Logits, all steps | **6.1e-5** (D400: 6.1e-5) | 0 |
| Per-head probability (unmasked) | 3.7e-6 | 0 |
| Value | 2.4e-7 | 0 |
| Per-head argmax agreement | 1.0 | 1.0 |
| Masked per-head probability | 2.1e-7 | 0 |
| Joint logprob of the recorded tuple | 8.0e-7 | 2.4e-7 (recorder fp32 vs comparator float64) |
| Forward joint TV, max / mean / p99 | 2.1e-7 / 4.5e-10 / 2.1e-9 | 0 / 0 / 0 |
| Sampler joint TV, max / mean / p99 | 9.4e-6 / 2.3e-7 / 3.2e-6 | 9.4e-6 / 2.2e-7 / 3.2e-6 |
| Env parity across terminals | 4 of 4 fixtures byte-identical | same |
| Consistency violations, mask mismatches | 0, 0 | 0, 0 |

The native-vs-torch logit gap is 6.1e-5 on the natural trace and 3.1e-5 on the
truncated one, reproducing D400 and the 5.0 port table. The sampler family is
almost the same for both kernels, so on these states it is dominated by the fp32
sampler arithmetic, not by the forward difference.

The comparator reads exact zeros when the forward matches, and its unit tests
prove it detects:

- a step-0 logit offset;
- a flipped mask bit;
- an action outside the support;
- a non-singleton waiting row;
- a reset that disagrees with the terminal flag;
- a corrupted observation or missing reset after a terminal;
- a corrupted mirror support (recorder dry run).

## Dry run on the rig (CPU only)

`bash tools/parity/dryrun_queue.sh` runs the queue with `DRY_RUN=1`. That mode
uses the numpy recorder backend (the native fp32 sampler and a bbplay-backed
mirror with the `create_vec` pointer interface) and a scratch lock file; the
queue refuses a dry run on `kt-gpu.lock`. Everything else is the real code.

The run used rig sources at commit cac260f, installed in
`/home/rache/bbparity/src-v2`. Results are under
`/home/rache/bbparity/dryrun-20260916T171351Z`, and all ten scenarios passed:

| Scenario | Expected exit | Got | What it proves |
|---|---|---|---|
| A: live trainer blocks | 4 | 4 | With the marker present, the live chain 34 units (`train=active waiter=active`) and three trainer PIDs keep the gate closed; no lock is taken |
| B: gate, lock, success | 0 | 0 | The waiter is active, then writes the marker and exits while an exam process lingers. The gate opens only once no consumer is left (poll 7). The queue waits for another lock holder (holder released 17:14:15, queue acquired 17:14:15), records 16 fixtures with 0 violations and the mirror support available (one reset to align), publishes the result, and logs `released(exit 0)` |
| C: refuse overwrite | 2 | 2 | A second run on a finished result refuses before any gate or lock |
| D: recorder failure | 3 | 3 | An injected recorder failure propagates and logs `released(exit 3)` |
| E: runtime cap | 124 | 124 | A 4 s cap kills a slow recorder (the rig's `timeout` is uutils 0.8.0) and logs `released(exit 124)` |
| F: SIGTERM | 143 | 143 | `systemctl stop`'s signal stops the recorder child, leaves no recorder process, and logs `released(exit 143)` |
| G: no marker | 3 | 3 | Both units inactive without the marker: abort, no lock, no GPU work |
| J: publication failure | 8 | 8 | `RESULT_COMPLETE.json` cannot be written: exit 8, `released(exit 8)` and never `released(exit 0)`, no result file, no `QUEUE-PARITY-DONE` |
| H: override refused | 6 | 6 | `DRY_RUN=0` refuses any override, such as `OUT` |
| I: shared lock refused | 6 | 6 | A dry run refuses `kt-gpu.lock` |

Scenario B's lock log:

```
2026-09-16T17:14:04Z holder acquired
2026-09-16T17:14:15Z holder released
2026-09-16T17:14:15Z 266516 acquired(lock=.../B_gate_lock_success/dry-gpu.lock) bloodbowl-rl:parity-native-20260916-v2 (~20 min GPU cap)
2026-09-16T17:14:18Z 266516 released(exit 0) bloodbowl-rl:parity-native-20260916-v2
```

Earlier dry runs: `dryrun-20260916T164512Z` failed B and C because of the
scenario, not the queue. Its fake units were inactive before the marker
appeared, which is G's abort path; the fix models the real waiter ordering
through a dry-run-only `UNIT_STATE_DIR`. `dryrun-20260916T164811Z` passed the
nine v1 scenarios.

The dry runs did not touch the live checkout (`git status` shows only the
existing untracked `checkpoints/` and `logs/`, and no new `__pycache__`),
`kt-gpu.lock.log`, or any existing unit.

## Queued job

The job is installed as the transient user unit **`parity-native-20260916-v2`**,
running `/home/rache/bbparity/src-v2/tools/parity/native_parity_queue.sh` from
sources at commit cac260f:

```bash
systemd-run --user --unit=parity-native-20260916-v2 \
  --description="bloodbowl-rl native CUDA vs harness torch parity recorder v2 for chain 30 (D399/D400): waits for EXAMS_DONE_C34_BOTH_SEEDS and no trainer, then kt-gpu.lock, GPU phase capped at 20 min" \
  --property=TimeoutStopSec=90 \
  /usr/bin/bash /home/rache/bbparity/src-v2/tools/parity/native_parity_queue.sh
```

It replaced the first unit, `parity-native-20260916`, which ran the v1 queue.
That unit was stopped at 17:15:32Z while still in its first gate poll. It had
written no `kt-gpu.lock.log` line, so it held no lock. Its output (shim build,
checkpoint copy, `queue.log`) was removed, and its failed state cleared. The v1
script at `/home/rache/bbparity/src` was left in place, because bash reads a
running script incrementally.

The v2 unit started at 17:15:32Z and is `active (running)`. Its preflight did
three things:

- built the shim (sha `29c732a5`) from the live env snapshot, which matches
  `bloodbowl.h` `4e116972` and `binding.c` `ce1cf606`;
- copied and verified the checkpoint (`41ecd998`);
- polled the gate:
  `gate poll 1: train=active waiter=active marker=0 consumers=[252413 252418 252419 ]`.

`kt-gpu.lock.log` still ends with chain 34's `acquired` line. The job has done no
GPU work, and it cannot until chain 34's exam writes the marker.

The job waits for **all** of the following, polling once a minute for up to
24 hours:

- `/home/rache/exam_c34.log` contains `EXAMS_DONE_C34_BOTH_SEEDS`;
- `r0chain34-cont30-rr1.service` and `exam-c34-waiter.service` are both inactive;
- no process matches `puffer_cuda_runtime.py train`, `puffer train`,
  `eval_vs_contact_bot` or a native recorder, and no process is named `puffer`.

If both units go inactive without the marker (chain 34 failed and no exam ran),
it aborts without touching the GPU.

After the gate opens, the job:

- takes `/home/rache/kt-e2e/kt-gpu.lock` with `flock -w 7200`, logs `acquired` and
  `released(exit N)` lines to `kt-gpu.lock.log` tagged
  `bloodbowl-rl:parity-native-20260916-v2`, and releases on success, failure,
  timeout, publication failure and SIGTERM;
- re-checks for GPU consumers after locking;
- caps the GPU phase at 1200 s with `timeout`;
- writes only under `/home/rache/bbparity/native-20260916`: the verified
  checkpoint copy, the shim build, one directory per run and `queue.log`;
- reports `QUEUE-PARITY-DONE` and exits 0 only after the summary step succeeds
  and `RESULT_COMPLETE.json` exists; otherwise it exits 8;
- refuses to run once `RESULT_COMPLETE.json` exists;
- accepts none of the dry-run overrides.

Status:

```bash
ssh bbrig 'systemctl --user status parity-native-20260916-v2 --no-pager; tail -20 /home/rache/bbparity/native-20260916/queue.log'
```

## How to run the comparator once the job lands

```bash
cd ~/Code/bb-harness-parity
ssh bbrig 'cat /home/rache/bbparity/native-20260916/RESULT_COMPLETE.json'
rsync -a --exclude c30.bin --exclude build \
  bbrig:/home/rache/bbparity/native-20260916/ .play-artifacts/parity/native-20260916/
~/Code/bb-play-harness/.venv/bin/python -m play_harness.parity compare \
  --fixtures .play-artifacts/parity/native-20260916 \
  --checkpoint .play-artifacts/checkpoints/chain30/0000002999975936.bin \
  --out .play-artifacts/parity/native-20260916/COMPARE.json
~/Code/bb-play-harness/.venv/bin/python -m pytest -q play_harness/tests/test_parity_fixture.py
```

The compare command prints the metric table and exits 0 only when both kernels
pass. `RUN.json` in each run directory records:

- the CUDA runtime evidence, the loaded CUDA library paths, and the `_C` path and
  sha;
- the effective vec, train, env and policy config;
- the first bbplay episode per env;
- `native_support_capture`: whether the mirror support was available, and if
  not, why;
- per-fixture consistency, including both support mismatch counts and the
  native fp32 logprob reproduction.

## Screening tolerances (proposed before any rig data)

These are **screening tolerances**. Passing them shows that the harness and the
native backend agree closely on the recorded states: a few self-play traces,
including deliberately truncated games. They are not an outcome-level bound.
The mean TV is an empirical average over those states, not a uniform or
upper-confidence bound for full games against the offense bot. A pass therefore
does not rule out forward or sampler numerics as a cause of the -0.033 offset; it
makes them unlikely on the states measured. I have dropped the earlier
6 x 307 x TV "TD per game bound": it needed a bound on the summed per-decision TV
along the target trajectories and a hard outcome range, and this experiment
establishes neither.

| Check | Tolerance | Reason |
|---|---|---|
| Env parity | 0 differing steps | Same env TU, same config (`bloodbowl.ini` sha `b94973fd` on both sides) and the same seeds. A byte difference is an env or seeding defect, and then no policy comparison is valid |
| Consistency, native masks vs support, mirror vs shim support | 0 | Exact integer data |
| `forward_joint_tv_mean` | <= 2e-6 | The Mac torch-vs-native kernel gap reads 4.5e-10. fp32 cuBLAS vs CPU BLAS roundoff through the recurrence should stay orders of magnitude below 2e-6 on average; a systematic forward difference would not |
| `forward_joint_tv_max` | <= 1e-3 | The worst decision. fp32 recurrence drift reaches 3.5e-3 in raw logits at |1e3| (5.0 table). That can only move probability mass by about 1e-3 at a near-tie, so anything larger is not roundoff |
| `sampler_joint_tv_mean` | <= 2e-5 | Includes the fp32 sampler arithmetic, which alone reads 2.2e-7 mean on the Mac traces and up to 1.45e-5 at a tie of two logits of 1000. 2e-5 allows about 100 times the measured mean |
| `sampler_joint_tv_max` | <= 1e-3 | Same argument as the forward max |
| `masked_head_prob_max_abs_diff` | <= 1e-3 | Per head, float64 normalization |
| `masked_head_argmax_agreement` | >= 0.999 per head | Flips are allowed only at near-ties |
| `logprob_max_abs_diff` | <= 1e-3 | The native logprob is an fp32 log-sum-exp; 1e-3 allows its roundoff over three heads |
| `value_max_abs_diff` | <= 1e-3 | The value is not used in sampling. This check catches a wrong decoder row |
| `logit_step0_max_abs_diff` | <= 1e-3 | A single forward. cuBLAS and CPU BLAS GEMM rounding at |x| ~ 1e3 should give about 1e-4. A layout, kernel-formula or state-handling error shows up at O(1) |

These are not gates:

- **All-step raw logits**, because recurrence roundoff grows them. Both fp32
  implementations drift 5e-3 to 1.5e-2 from a float64 reference.
- **Unmasked probabilities**, because they include columns the sampler never
  reads.

How to read each outcome:

- **All pass.** On the recorded self-play states, the harness forward and sampler
  reproduce the rig's action distributions for chain 30 closely. Forward and
  sampler numerics become an unlikely explanation for the offense-bot offset,
  though not an excluded one. Other candidates:
  - the bot bench's seeds and state distribution;
  - the rig's two exam seeds sharing env seeds;
  - the exam's lr-1e-12 train phase touching the weights before its eval phase;
  - states against the offense bot that self-play does not visit.
- **Env parity or support checks fail.** That is itself the finding: the shim and
  the live env diverge, and harness observations or legality are wrong.
- **Forward passes but sampler fails.** The fp32 sampler arithmetic, not the
  forward, is the difference. Its size tells whether it could matter, and
  aligning the harness sampler with the native algorithm would remove it.
- **`forward_joint_tv_max` or step-0 logits fail by orders of magnitude.** A real
  forward or state-handling mismatch. The per-step columns in `COMPARE.json` show
  where it starts.

**Caveats.**

- The traces are self-play states. They are not states against the offense bot.
- The job does not replay the exam's lr-1e-12 train phase.
- bf16 builds are not covered.
- `native_support` comes from a mirror vec, not the trainer vec's buffer.
- The fp32 sampler reproduction uses numpy's float32 `exp`/`log`, which may
  differ from libdevice by a unit in the last place, and treats `curand_uniform`
  as continuous.

## Review changes (Codex, 2026-09-16)

1. **fp32 sampler.** Added `native_fp32_head`, `native_fp32_sample_head`,
   `native_fp32_logprob` and `harness_fp32_head`. The metrics now come in
   `forward_*` and `sampler_*` families, tested against the Codex two-logit
   example and the C transliteration.
2. **Outcome bound.** Removed `outcome_bound` and `td_per_game_bound`. The
   thresholds are now screening tolerances with the claims narrowed.
3. **Native support.** Added the `_C.create_vec` mirror capture
   (`native_support`, best effort), an explicit
   `masks_vs_support_mismatch_steps` gate, a `native_vs_shim_support_mismatch_steps`
   gate, and the support-equivalence qualification above.
4. **Queue success without a result.** The summary step's pipeline status is
   checked, and `RESULT_COMPLETE.json` is required before `QUEUE-PARITY-DONE`.
   The dry run gains scenario J (publication failure).
5. **Partial recordings.** The rig test is split into
   `test_rig_suite_parity` (completion manifest, exact runs, envs and seats) and
   `test_rig_partial_fixture_integrity`.
