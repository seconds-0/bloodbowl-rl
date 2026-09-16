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
- The acceptance thresholds below were fixed before any rig data exists.

Branch `feat/harness-native-parity-20260916`. The code lives in
`play_harness/parity.py`, `tools/parity/record_native.py`,
`tools/parity/native_parity_queue.sh` and `tools/parity/dryrun_queue.sh`.

## What is compared

| Side | Forward | Precision | Recurrence |
|---|---|---|---|
| Native (rig) | live `_C` at fbaec58, built `--float`, module sha `d63498f6`. `policy_forward` (cuBLAS `puf_mm` plus the `mingru_gate` kernel) inside the captured rollout graph, then `sample_logits` (exact-joint-v1) | fp32 | evaluation mode: state persists across rollout calls and `reset_recurrent_state_on_terminal` zeroes terminal rows |
| Harness `native` kernel | `MinGRUPolicy.forward_eval`, `fast_sigmoid` and branchy lerp | fp32 CPU torch | `PolicySeat`: every c_step, zeroed at each new match |
| Harness `torch` kernel | `MinGRUPolicy.forward_eval`, exact sigmoid and `torch.lerp` | fp32 CPU torch | same |

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
- It records the packed joint support. The vec's support buffer is not exposed
  to Python, but once observations agree the shim computes the same support.

Any disagreement aborts the run with `MISMATCH.json`.

**Runs** (envs 0-3, both seats, so 8 fixtures per run):

| Run | Seed | Steps | `max_decisions` | Terminals |
|---|---|---|---|---|
| `md4096_s42` | 42 | 1000 | 4096 (exam default) | natural (about 614 c_steps per game) |
| `md150_s43` | 43 | 600 | 150 | truncation, several per env |

**Recorded per step, per seat** (`bbplay-parity-fixture-v1`, superset):

- `obs` bytes, the native `terminal` flag, `reset`, `deciding`;
- the native rewritten 454-bit `masks`, sampled `actions` and joint `logprob`;
- `value`, raw `logits` (all 454 columns), and the packed joint `support` with
  its offsets;
- `masked_logits` (-inf outside the masks) and per-head `probs`, both computed
  in float64 from the native logits under the native masks.

**Comparator** (`python -m play_harness.parity compare`). It replays each
fixture's observation stream through both harness kernels with the recorded
reset boundaries. It rebuilds every match on the Mac shim, following terminals
into episode + 1, checks recorder self-consistency, and reports the metrics
below. All probability math is float64 over fp32 logits.

## What is measured

| Metric | Definition | Role |
|---|---|---|
| `logit_step0_max_abs_diff` | first forward, no recurrence | gate |
| `logit_max_abs_diff`, `logit_mean_abs_diff` | all steps | report only: fp32 roundoff compounds through the recurrence (5.0 table: 1.6e-3 to 3.5e-3) |
| `head_prob_max_abs_diff` | unmasked per-head softmax, as in the 5.0 table | report |
| `value_max_abs_diff` | value column | gate |
| `unmasked_head_argmax_agreement` | as in the 5.0 table | report |
| `masked_head_prob_max_abs_diff` | per-head softmax under the recorded conditional masks | gate |
| `masked_head_argmax_agreement` | deciding steps | gate |
| `logprob_max_abs_diff` | harness joint log p of the native tuple vs the native fp32 logprob | gate |
| `head_tv_max`, `head_tv_mean` | total-variation distance per head under the recorded masks | report |
| `joint_tv_max`, `joint_tv_mean`, `joint_tv_p99` | TV distance between the exact joint distributions over the packed support (type, arg given type, square given both) | gate |
| `td_per_game_bound` | 6 x 307 x `joint_tv_mean` (see thresholds) | report |
| env parity | first step where the shim's obs, decision owner, support or terminal boundary differs | gate |
| consistency | step 0 resets; reset equals terminal; waiting rows carry the singleton NONE support and tuple; actions lie in support; masks equal support conditioned on the tuple | gate |

## The skipped rig-parity test

`test_rig_fixture_parity` expected four wrong things:

1. **It read `BBPLAY_CHECKPOINT`.** That variable is the conftest's chain 25
   default, so a rig run would have loaded the wrong checkpoint or raised
   `KeyError`.
2. **It took one fixture directory, one seat per env var.**
3. **Env parity stopped at the first terminal.** The recurrence reset after a
   terminal, the part most likely to differ, was never checked.
4. **It gated only the sampled tuple's logprob and the value, at 1e-4.** That
   bound says nothing about the probability of the actions not taken. It also
   sits near fp32 resolution at logits of |1e3|.

The rewritten test finds every `native-cuda` fixture under
`BBPLAY_PARITY_FIXTURE`, by default `.play-artifacts/parity/native-20260916`,
and loads chain 30 from `BBPLAY_PARITY_CHECKPOINT`. It requires both seats and at
least one terminal reset, and applies `parity.ACCEPTANCE` to both kernels. With
no fixture present it skips with a reason.

## Mac validation (harness native kernel vs harness torch kernel)

The harness backend of the same trace shape
(`python -m play_harness.parity record-selfplay`, native kernel, sampling, both
seats) recorded two chain 30 traces:

- `hv-md4096-s42`: 1000 c_steps, a natural terminal;
- `hv-md150-s43`: 500 c_steps, three truncation terminals.

Both traces have both seats, so 4 fixtures and 1,500 decisions. The comparator
then replayed them through both kernels
(`native-parity-2026-09-16/harness-validation.json`).

| Metric | torch kernel vs recorded native kernel | native kernel vs itself |
|---|---|---|
| Logits, step 0 | 4.8e-7 | 0 |
| Logits, all steps | **6.1e-5** (D400: 6.1e-5) | 0 |
| Per-head probability (unmasked) | 3.7e-6 | 0 |
| Value | 2.4e-7 | 0 |
| Per-head argmax agreement | 1.0 | 1.0 |
| Masked per-head probability | 2.1e-7 | 0 |
| Joint logprob of the recorded tuple | 8.0e-7 | 2.4e-7 (recorder fp32 vs comparator float64) |
| Joint TV, max / mean / p99 | 2.1e-7 / 4.5e-10 / 2.1e-9 | 0 / 0 / 0 |
| Env parity across terminals | 4 of 4 fixtures byte-identical | same |
| Consistency violations | 0 | 0 |

The native-vs-torch logit gap is 6.1e-5 on the natural trace and 3.1e-5 on the
truncated one, reproducing D400 and the 5.0 port table. The comparator reads
exact zeros when the forward matches, and its unit tests prove it detects a
step-0 logit offset, a flipped mask bit, an action outside the support, a
non-singleton waiting row, a reset that disagrees with the terminal flag, and a
corrupted observation or missing reset after a terminal.

## Dry run on the rig (CPU only)

`bash tools/parity/dryrun_queue.sh` runs the queue with `DRY_RUN=1`. That mode
uses the numpy recorder backend and a scratch lock file; the queue refuses a dry
run on `kt-gpu.lock`. Everything else is the real code.

The run used rig sources at commit 61319ea. Results are under
`/home/rache/bbparity/dryrun-20260916T164811Z`, and all nine scenarios passed:

| Scenario | Expected exit | Got | What it proves |
|---|---|---|---|
| A: live trainer blocks | 4 | 4 | With the marker present, the live chain 34 units (`train=active waiter=active`) and three trainer PIDs keep the gate closed; no lock is taken |
| B: gate, lock, success | 0 | 0 | The waiter is active, then writes the marker and exits while an exam process lingers. The gate opens only once no consumer is left (poll 7). The queue waits for another lock holder (holder released 16:48:35, queue acquired 16:48:35), records 16 fixtures with 0 violations, and logs `released(exit 0)` |
| C: refuse overwrite | 2 | 2 | A second run on a finished result refuses before any gate or lock |
| D: recorder failure | 3 | 3 | An injected recorder failure propagates and logs `released(exit 3)` |
| E: runtime cap | 124 | 124 | A 4 s cap kills a slow recorder (the rig's `timeout` is uutils 0.8.0) and logs `released(exit 124)` |
| F: SIGTERM | 143 | 143 | `systemctl stop`'s signal stops the recorder child, leaves no recorder process, and logs `released(exit 143)` |
| G: no marker | 3 | 3 | Both units inactive without the marker: abort, no lock, no GPU work |
| H: override refused | 6 | 6 | `DRY_RUN=0` refuses any override, such as `OUT` |
| I: shared lock refused | 6 | 6 | A dry run refuses `kt-gpu.lock` |

Scenario B's lock log:

```
2026-09-16T16:48:24Z holder acquired
2026-09-16T16:48:35Z holder released
2026-09-16T16:48:35Z 260564 acquired(lock=.../B_gate_lock_success/dry-gpu.lock) bloodbowl-rl:parity-native-20260916 (~20 min GPU cap)
2026-09-16T16:48:37Z 260564 released(exit 0) bloodbowl-rl:parity-native-20260916
```

The first dry run (`dryrun-20260916T164512Z`) failed B and C because of the
scenario, not the queue. Its fake units were inactive before the marker
appeared, which is exactly G's abort path, so B aborted with exit 3. C then ran
B's flow instead of refusing. The fix models the real ordering, with the waiter
active until it writes the marker, through a dry-run-only `UNIT_STATE_DIR`.

The dry runs did not touch the live checkout (`git status` shows only the
existing untracked `checkpoints/` and `logs/`, and no new `__pycache__`),
`kt-gpu.lock.log`, or any existing unit.

## Queued job

The job is installed as the transient user unit **`parity-native-20260916`**,
running `/home/rache/bbparity/src/tools/parity/native_parity_queue.sh` from
sources at commit 61319ea:

```bash
systemd-run --user --unit=parity-native-20260916 \
  --description="bloodbowl-rl native CUDA vs harness torch parity recorder for chain 30 (D399/D400): waits for EXAMS_DONE_C34_BOTH_SEEDS and no trainer, then kt-gpu.lock, GPU phase capped at 20 min" \
  --property=TimeoutStopSec=90 \
  /usr/bin/bash /home/rache/bbparity/src/tools/parity/native_parity_queue.sh
```

It started at 16:49:52Z and was `active (running)` when checked. Its preflight
did three things:

- built the shim (sha `2e845be4`) from the live env snapshot, which matches
  `bloodbowl.h` `4e116972` and `binding.c` `ce1cf606`;
- copied and verified the checkpoint (`41ecd998`);
- polled the gate: `train=active waiter=active marker=0 consumers=[252413 252418 252419]`.

`kt-gpu.lock.log` still ends with chain 34's `acquired` line, so the job has not
touched the lock. It has done no GPU work, and it cannot until chain 34's exam
writes the marker.

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
  `bloodbowl-rl:parity-native-20260916`, and releases on success, failure,
  timeout and SIGTERM;
- re-checks for GPU consumers after locking;
- caps the GPU phase at 1200 s with `timeout`;
- writes only under `/home/rache/bbparity/native-20260916`: the verified
  checkpoint copy, the shim build, one directory per run and `queue.log`;
- refuses to run once `RESULT_COMPLETE.json` exists;
- accepts none of the dry-run overrides.

Status:

```bash
ssh bbrig 'systemctl --user status parity-native-20260916 --no-pager; tail -20 /home/rache/bbparity/native-20260916/queue.log'
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
- per-fixture consistency.

## Acceptance thresholds (proposed before any rig data)

| Check | Threshold | Reason |
|---|---|---|
| Env parity | 0 differing steps | Same env TU, same config (`bloodbowl.ini` sha `b94973fd` on both sides) and the same seeds. A byte difference is an env or seeding defect, and then no policy comparison is valid |
| Consistency | 0 violations | Masks, support, waiting rows and resets are exact integer data |
| `joint_tv_mean` | <= 2e-6 | Trajectory TV is at most the sum of per-decision TVs. One side's TDs per game lie in [0, 6], and a seat makes about 307 decisions per game (614 c_steps). The TD-per-game bound is therefore 6 x 307 x 2e-6 = 0.0037, a ninth of the -0.033 offset and a sixth of its interval half-width. A pass rules out forward numerics as the offset's source |
| `joint_tv_max` | <= 1e-3 | The worst decision. fp32 recurrence drift reaches 3.5e-3 in raw logits at |1e3| (5.0 table). That can only move probability mass by about 1e-3 at a near-tie, so anything larger is not roundoff |
| `masked_head_prob_max_abs_diff` | <= 1e-3 | Same argument, per head |
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

- **All pass.** The harness forward reproduces the rig's action distributions
  for chain 30, and the offense-bot offset has another cause. Candidates are the
  bot bench's seeds and state distribution, the rig's two exam seeds sharing env
  seeds, or the exam's lr-1e-12 train phase touching the weights before its eval
  phase.
- **Env parity fails.** That is itself the finding: the shim and the live env
  diverge, and the bench's observations are wrong.
- **Only `joint_tv_mean` sits between 2e-6 and 1.8e-5.** Inconclusive for a
  0.033 offset (bound 0.0037 to 0.033). Record a longer trace before drawing a
  conclusion.
- **`joint_tv_max` or step-0 logits fail by orders of magnitude.** A real
  forward or state-handling mismatch. The per-step columns in `COMPARE.json` show
  where it starts.

**Caveats.**

- The traces are self-play states. They are not states against the offense bot.
- The job does not replay the exam's lr-1e-12 train phase.
- bf16 builds are not covered.
