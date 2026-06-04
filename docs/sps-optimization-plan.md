# BB2025 SPS Optimization Plan

Synthesized from four measurement/analysis passes (env hot-path profiling + prototypes on Mac M-series; code-traced vec/trainer/GPU analysis; PufferLib 4.x field lore). Config verified on disk: `vendor/PufferLib/config/bloodbowl.ini` [vec] = `total_agents=4096, num_buffers=1, num_threads=8`; upstream `default.ini` ships `2/16`. Env prototype branch verified present: worktree `worktree-wf_7ddff3ba-252-1` @ `b5a48de`.

**Units.** "c-step" = one `c_step` call (one decision; emits obs+mask for both agents). Dashboard SPS counts agent-steps; 4096 agents = 2048 envs, so SPS ≈ 2× aggregate c-steps/s. The "~1M steps/sec" box figure is ambiguous between the two — probe P0 pins it from the dashboard before any ratio math is trusted.

---

## 1. Measured cost model of one training step

### 1a. Box-level loop structure (code-traced, vecenv.h:239-334)

With `num_buffers=1` the loop is **strictly serial per timestep**: cudagraph forward + sample → actions D2H → `cudaStreamSynchronize` (vecenv.h:284, CPU blocks) → OMP `parallel for schedule(static)` c_step over 2048 envs with **8 workers** (vecenv.h:291, `num_workers = num_threads/num_buffers`) → async H2D of obs/mask/rew/term. GPU and CPU **never overlap**; ~16 of 24 vCPUs idle during env stepping; all 24 idle during the GPU phase. Dashboard split: eval_env ~75-85%, eval_gpu ~10-15%, train 7-11% (train excludes rollout forward — that's inside eval_gpu).

### 1b. Inside one c-step (Mac M-series, clang -O2, masked random play, 513K steps, instrumented driver `puffer/bloodbowl/bbe_profile.c` + `sample` corroboration; baseline 2295 ns)

| Phase | ns | % | Status |
|---|---|---|---|
| bb_apply internal re-enumeration (mask-soundness revalidation) | 455 | 19.8 | **fixed** (`bb_apply_trusted`, dcf52ca) |
| bb_apply membership eq-scan | 63 | 2.7 | fixed (same) |
| apply + advance (actual game logic) | ~10-60 | ~2 | untouched — all review LOW items (push_flags ×4, assists, ctx-TZ) live here; negligible for SPS |
| bbe_refresh_legal (2nd enumeration) | 496 | 21.6 | setup_legal template fix (78fe6df) cut the dominant proc 1174→346 ns/call |
| bbe_fill_mask ×2 | 639 | 27.8 | partially fixed (head-projection cache, 0d5b5ed); **now 49.5% of remaining step** |
| bbe_encode_obs ×2 | 377 | 16.4 | fixed (skill-row + TZ caches, fb576f3) |
| bbe_decode (3-pass) | 256 | 11.1 | fixed (single-pass fold, 0d5b5ed) |

Enumeration cost is **96.2% SETUP** (~1354 actions = 11 players × ~190 free squares; 39% of random-play decisions). PASS/TTM enumeration: 5 and 0 occurrences in 513K steps — the review's 390-square bounding-box items are currently dead weight.

**Net measured result of the prototype stack:** 389,425 → 692,558 c-steps/s masked (+77.8%); 697,706 → 1,337,959 unmasked (+91.8%). Trajectories bit-identical to baseline (illegal_frac, all aggregate stats, seeds 42+1337). 280/280 tests incl. ASan/UBSan, selftest 300 eps clean, 90 s libFuzzer clean.

### 1c. GPU side (code-traced)

Policy = 3.02M params (bias-free 832→512 GEMM, 3× MinGRU, fused 512→455 decoder). Rollout forward 24.7 GFLOPs/vec-step vs ~83 TFLOPS bf16 peak — GPU demand is ~7%-of-a-4090 territory. Already cudagraph-captured (one graph per (t,buf) + one train graph, ~30 nodes/rollout step, 1 launch); **kernel-execution-bound, not launch-bound** — no graphs/fusion win left. H2D 5.3 MB/vec-step, pinned, ~1.3 GB/s = 5% of PCIe4 x16 — non-issue. Train epoch = 4 minibatches (replay_ratio 0.25), ~1.34 TFLOP + a ~145-node serial Muon Newton-Schulz chain; matches the 7-11% dashboard share.

### 1d. The open anomaly

Per-worker env rate on the box back-computes to ~78-156K c-steps/s (depending on SPS unit reading) vs 389K on one Mac core — a 2.5-5× per-core gap. Candidate causes, in likely order: Vast vCPU = SMT sibling / weaker core, **static-schedule straggler waves** (all 2048 envs start at kickoff together → synchronized setup-enumeration spikes; per-t OMP barrier ticks at the slowest 256-env chunk), LLC thrash (~32 KB/env × 256 envs/worker ≈ 8 MB hot set, dominated by `legal[4096]`). P0/P1/P5 resolve this; it is the main uncertainty in the ceiling estimate.

---

## 2. Ranked optimizations

**Golden-trace / comparability legend:** changes marked **[TRACE-SAFE]** produce bit-identical env outputs and consume RNG identically — golden traces and cross-run learning comparisons survive. **[RUN-AFFECTING]** = engine semantics untouched (goldens fine) but run-to-run scheduling/batching differs — fine for new runs, never mid-experiment. **[SEMANTICS]** = changes decision sequence / RNG consumption order / state distribution — **invalidates golden traces and all cross-run comparability; requires explicit experiment epoch boundary and replay-alignment sign-off.**

| # | Change | Expected gain | Conf. | Risk | When |
|---|---|---|---|---|---|
| 1 | **Merge env prototype branch** (4 commits: `bb_apply_trusted`, setup template, encoder caches, decode fold + mask projection cache) | +78% per-core env (random mix; ~+50-70% on trained mix — setup share dilutes) | High (measured, bit-identical, 280/280 + ASan + fuzz) | Low; only `bb_apply_trusted` carries a semantic contract, and it's delegated + differential-tested; tests/fuzz/lockstep keep checked path | **Now.** [TRACE-SAFE] |
| 2 | **[vec] `num_threads=20, num_buffers=2`** (from 8/1) | 1.5-2.7× SPS (10 workers ×2 bufs; eval_gpu fully hidden by overlap) | Med-high (code-traced; upstream default is 2/16; Peru's 4090 tables: 1→2 bufs = +50%, 1→8 threads = +65%) | Low — config-only; selfplay perm/bank code is per-buffer-aware; divisibility guards hold | **Now** (commit; takes effect next launch — do NOT touch the running A/B). [RUN-AFFECTING] |
| 3 | **OMP env vars**: `OMP_WAIT_POLICY=PASSIVE`, `OMP_PROC_BIND=close/spread + OMP_PLACES=cores` | +2-8% (spin-waste at threads≈vCPUs; EnvPool pinning lore) | Med | None (env vars) | Box-probe (P4). [RUN-AFFECTING] |
| 4 | **`schedule(static)`→`schedule(runtime)`** at vecenv.h:291 + `OMP_SCHEDULE=guided` | +3-10% (straggler waves from phase-correlated setup costs) | Med | Low (1-word vendored patch; Mac-testable first) | Box-probe (P5). [RUN-AFFECTING] |
| 5 | **Factored legal sets** — stop materializing the player×square cross product in fill_mask/setup (49.5% of post-prototype step) | +30-50% more per-core env | Med (clear profile target; design work needed) | Med — touches mask construction; must stay bit-identical to survive goldens | Next env workstream; prototype on Mac. [TRACE-SAFE if mask bytes identical — verify with the existing bit-identity harness] |
| 6 | **replay_ratio 0.25→0.5/1.0** | Not SPS — 4× updates/sample for est. 20-25% SPS cost (train is near-free in env-bound regime) | Med | Learning-stability risk (KL/clipfrac guardrails; chess swept to 0.25) | Probe prices wall-clock (P9); learning A/B separately. [RUN-AFFECTING] |
| 7 | **Stagger env phases at init** (puffer.ai docs' explicit advice) via `my_vec_init` fast-forward | +0-10% (kills synchronized setup/reset cost waves; compounds with #4) | Low-med | Low code risk | After P1 quantifies straggle. **[SEMANTICS-lite: engine goldens unaffected, but initial-state distribution changes → training runs not comparable to unstaggered runs]** |
| 8 | **uint8 masks (opt. obs) end-to-end in rollout buffers** | ~0-3% SPS; −675 MB VRAM; shorter rollout-graph critical path | Med | Med — generic trainer code, all envs; `select_copy` row-byte math assumes `sizeof(precision_t)` (pufferlib.cu:1457) | Park until hidden-size growth needs the headroom. [TRACE-SAFE] |
| 9 | **hidden 512→768/1024** | Negative SPS (−10% @768, −20% @1024 *after* #2; −30-35% before it) for 2.25-3.56× params | High (FLOP math) | Quality trade, not perf | After #2 lands + probe (c) confirms forward still hides. [RUN-AFFECTING] |
| 10 | **Forced-move collapse** (auto-apply `n_legal==1` inside c_step) | Multiplies effective SPS by forced-move fraction — frame-skip for turn-based | Med | **HIGH for consistency** | **LOUD FLAG: [SEMANTICS].** Changes decision sequence, episode lengths, per-decision RNG alignment; breaks golden traces AND FFB replay-differential alignment (review D10/D17). Park behind Phase-4 replay-alignment decision; only at an experiment epoch boundary. |
| 11 | total_agents 8192/16384 | ~0% SPS (CPU-bound; epoch wall-clock doubles); batch-quality knob only | High | LLC-pressure regression possible | Probe P7 only if batch stability wanted. [RUN-AFFECTING] |
| 12 | Log gate 0.6→5.0 s | <2-3% | Med | None | Probe P10; likely leave at 0.6. |
| 13 | TTM/pass bounding boxes, push_flags ×4, assist 8-neighbor, ctx-TZ, interception ruler ×4 | ~0% SPS (inside the ~2% apply+advance slice; PASS=5, TTM=0 in 513K steps) | High (measured) | — | Park; revisit for fuzz/replay throughput or when trained policies actually pass. [TRACE-SAFE] |
| 14 | Mask bit-packing, --float, cudagraphs changes, EnvPool-style partial batching, encoder sparsity | None or negative | High | — | **Don't.** bf16 stays (Ada tensor cores, fp32 accum); cudagraphs=10 stays; sparsity saves FLOPs on an idle GPU. |

---

## 3. On-box probe matrix (A→B gap; ~3-5 min steady-state each after ~30 s graph warmup; record SPS, perf/eval_env, perf/eval_gpu, perf/train, util/gpu_percent; fixed seed)

Ordered by decision value per minute. Budget ~75-90 min for P0-P6; rest opportunistic.

| # | Probe | Cells | Decision rule |
|---|---|---|---|
| P0 | **No-run facts** (~5 min): `lscpu`, `nproc`, `numactl --hardware`, `nvidia-smi -q \| grep -i pcie`; final A/B dashboard eval_gpu:eval_env split; **pin SPS units** (agent vs c-step) | — | Physical-core count sets the thread ceiling for everything below; NUMA>1 → prefer buffers=NUMA nodes |
| P1 | Thread scaling, buffers=1 | threads ∈ {8,12,16,20,24} | T* = last point with ≥80% incremental scaling. If 8→16 < 1.3×, env stepping is memory-bound → env micro-opts outrank vec tuning, stop sweeping threads |
| P2 | Double buffering | buffers=2 × threads {T*, T*±4} | Adopt if ≥+5% over P1-best AND error_episodes=0 AND selfplay winrate logs sane; prefer 2 bufs on a tie (removes serialization) |
| P3 | buffers=4, threads=24 | 1 cell | Adopt only if >+5% vs P2-best (expect neutral-worse: spinning managers, 1 copy engine/direction) |
| P4 | OMP env vars at P2-best | PASSIVE; PROC_BIND/PLACES (htop-verify no core overlap between buffer teams) | Keep if ≥+2% |
| P5 | `schedule(runtime)` rebuild + OMP_SCHEDULE ∈ {static, guided, dynamic,16} | 3 cells | Adopt guided/dynamic if ≥+3%; note for upstream |
| P6 | **Env prototype branch rebuilt on box** at P2-best | 1 cell | The headline number: confirms Mac per-core gains translate; re-ranks everything below |
| P7 | total_agents=8192 at best config | 1 cell | Adopt only if SPS within 5% and 2× batch is wanted |
| P8 | cudagraphs=-1 sanity | 1 short cell | Confirm graphs load-bearing; keep 10 regardless |
| P9 | replay_ratio {0.5, 1.0} | SPS + kl + clipfrac only | If rr=1.0 costs <20% SPS, schedule a proper learning A/B |
| P10 | Log gate 5.0 s / verbose off | 1 cell | Raise gate permanently only if >3% |
| P11-12 | Optional: minibatch 32768; horizon 128 (+1.3 GB, expect flat) | — | Wall-clock-only; learning decisions deferred |
| P13 | Optional: 30-s `nsys` trace at best config | — | Splits eval_gpu into graph-exec vs sync-wait; informs hidden-size headroom (#9) |

---

## 4. Ship now vs park

**Ship immediately (zero contact with the running A/B):**
1. Merge `worktree-wf_7ddff3ba-252-1` (commits `dcf52ca`, `78fe6df`, `fb576f3`, `0d5b5ed`, + `e4189da` profiler, `b5a48de` fuzz corpus) to main. Measured +77.8% masked / +91.8% unmasked, bit-identical, fully validated. Per house rules: adversarial-review the merge before it becomes the new baseline (the `bb_apply_trusted` contract is the one item with a dissent history — its differential test and delegation answer the deferred P1 review).
2. `config/bloodbowl.ini` [vec]: `num_threads = 20`, `num_buffers = 2`. Sight-unseen floor ~1.5×, ceiling ~2.7×; worst plausible case flat (P1 would expose memory-boundedness at zero cost). If single-variable conservatism is wanted: `num_threads = 20` alone is strictly safe.
3. Keep: bf16, cudagraphs=10, log gate 0.6 s, total_agents 4096, horizon 64 — all confirmed correct as-is.

**Park (with re-entry condition):**
- Factored legal sets — start design now, it's the next env frontier (fill_mask = 49.5% of post-prototype step); gate on bit-identity.
- Forced-move collapse — **[SEMANTICS]**, blocked on Phase-4 replay-alignment ruling.
- Env init staggering — after P1 quantifies straggle; new-experiment-epoch only.
- uint8 rollout buffers — when hidden-size growth needs VRAM/latency headroom.
- hidden 768/1024, replay_ratio ≥0.5, total_agents 8192 — quality/learning levers, priced, awaiting probes + learning A/Bs.
- TTM/pass/push micro-items — fuzz/replay-speed backlog only.

---

## 5. Realistic ceiling estimates

**Vast 4090 / 24 vCPU.** Current: ~1M SPS, env-bound. Stack = env prototypes (×1.5-1.78 per-core, trained-mix-adjusted) × workers 8→20 (×1.5-2.5, knee depends on physical cores per P0/P1) × eval_gpu hidden (÷0.85-0.90), train un-hideable remainder ~8-10%.
- **Conservative** (12 physical cores + SMT, weak vCPUs, straggle persists): **~2.5M SPS** (2.5×).
- **Expected** (P0-P6 land as traced): **3.5-4.5M SPS**.
- **With factored legal sets** (#5) on top: **~5-6M SPS** — the practical ceiling of this stack without semantic changes. Beyond that requires forced-move collapse (effective-SPS multiplier = forced-move fraction, [SEMANTICS]) or a bigger box. Per-core sanity bound: 20 Mac-class cores × 692K c-steps/s would be ~27M SPS; the 4090-box numbers assume Vast cores deliver 25-45% of that per core, which P0/P1 will pin — the 2.5-5× per-core anomaly in §1d is the swing factor.

**14-core M-series Mac.** No CUDA trainer (pufferlib.cu is CUDA-only) — Mac is the env-benchmark + unmasked torch/MPS practice rig. Post-prototypes: 692K masked / 1.34M unmasked c-steps/s per core; ~12 usable P+E cores ≈ **6-8M masked c-steps/s aggregate** for standalone sweeps/fuzz/replay work. Use it to prototype #4 (OMP schedule) and #5 before box time.

**RTX 2070 WSL2 box.** GPU is not the constraint (24.7 GFLOPs/vec-step vs ~7.5 TFLOPS fp32; forward hides under env with buffers=2; train share grows but stays minor). Two checks before relying on it: (1) **bf16 GEMM on Turing (sm_75)** — `cublasGemmEx` with `CUDA_R_16BF` generally wants sm_80+; expect to need the `--float` build there (≤ few % cost, doubles rollout VRAM — fine at 8 GB only if total_agents drops to 2048, ~0.65 GB rollouts + fixed bufs); (2) WSL2 pinned-memory + cudaHostAlloc behavior. Throughput is then pure CPU: assuming a typical 8C/16T desktop at 200-350K post-prototype c-steps/s/core with 6-7 effective workers ≈ **1-2M SPS** — usable for config probes and learning A/Bs, not for production runs. If its CPU is bigger, scale linearly with physical cores; it's env-bound everywhere this plan looks.

Key files: `vendor/PufferLib/src/vecenv.h` (:239-334, :258, :284, :291), `vendor/PufferLib/src/pufferlib.cu` (:573-699, :1457, :1550, :2102-2170), `vendor/PufferLib/config/bloodbowl.ini`, `puffer/bloodbowl/bloodbowl.h`, `puffer/bloodbowl/bbe_profile.c` (worktree), `engine/src/proc_match.c`, `.reviews/adversarial-20260603.md`, worktree `/Users/alexanderhuth/Code/bloodbowl-rl/.claude/worktrees/wf_7ddff3ba-252-1` (branch `worktree-wf_7ddff3ba-252-1`).