# Local paired memory-learning screen

Status: training is running on the local RTX2070 under
`bb-memory-learning-paired-250m-v2.service`. The first control/seed42 arm
launched on September5 at19:50 local time. This is execution of section3 of the training and funding plan,
following the completed D334 recurrent-memory qualification.

The prospective matrix is control seed 42, repaired seed 42, repaired seed 43,
control seed 43. Every arm requests 250,000,000 transitions (249,954,304 aligned),
for 999,817,216 executed training transitions across four arms. The sole factor
is the entire recurrent-memory contract: historical tail-bootstrap-v1 versus
terminal-aware-tbptt-v1. Both retain H64 gradient truncation. This experiment
cannot separately attribute terminal clearing and cross-window state carry.

Both runtimes use the same game engine, obs-v7 and exact-joint-v1 support,
complete R0 reward, H512/L3 policy, fresh initialization, 2048 agents, two
buffers, 16 threads, minibatch 16384, LR0.00028, entropy0.009, gamma0.995,
GAE0.85, replay ratio0.25 and fixed optimizer schedule. There is no warm
checkpoint, replay data or frozen opponent pool. The same learner controls
both teams during training. The historical control stays isolated; its known
terminal-state leak is not reintroduced into the repaired runtime.

Fresh native constructor checks use the actual measured training arguments,
with zero rollout and optimizer calls. Old and repaired initial weights match
byte-for-byte within each seed; seed42 and seed43 differ. The seed42 digest is
ed441582c814be394f0029889f6fd71967b418e913f8a55b7f9796765826540c;
seed43 is4f995a42be802e30482e84838c6cd53ad82ffaae95e444276591ac5f22336683.
The frozen evidence is INITIALIZER_PARITY_ACCEPTED.json, SHA
ab9fa9b431ae7565778e5cdde8b4d921686e37e1f62b00b3b509df02345379ef,
under audit-artifacts/memory-learning-preflight-20260905/initializers/.
Those saved initial states are diagnostic evidence, never warm starts.

Each arm must finish its 10,000-game embedded evaluation and pass exact-zero
integrity, complete phase telemetry, finite checkpoint/loss, source/module/
config/producer hash, full runtime closure, physical backing-storage, guest
space/inodes, thermal, bounded-time and artifact checks. A failed arm halts
later arms and is never averaged into results. Every output remains diagnostic
and ineligible for promotion.

The prospective held-out exam is 128 kickoff games per model: four evaluation
seeds (2026090511–2026090514), contact/cage, home/away, eight games per cell.
All four trained models receive the same 128 game keys, yielding 512 played
games and 256 within-training-seed pairs. Full game records, W/D/L, TD for and
against, per-cell results and equal-weight training-seed summaries are required.
Two training seeds and scripted opponents are descriptive evidence only.

If scoring remains absent and held-out results do not distinguish the arms,
report that the screen cannot rank their learning performance. Do not invent
an outcome from possession/block/action rates or simply extend the budget.
The repaired memory contract remains the correctness-qualified implementation;
no noisy performance difference authorizes restoring the known leak. The next
local learning question is useful teacher/curriculum experience with held-out
geometry and match transfer, as described in section4 of the funding plan.
Longer gradient horizons require their own separate comparison.

Known limitations include incomplete BB2025 rule/choice coverage, procgen
learned skills, only two training seeds, no learned held-out opponent or roster
macro grid, no second ancestry, and a short local training budget. Identical
engine scope across arms supports this within-simulator diagnostic, not full
rules conformance or tournament readiness. Full backlog remains on the HTML
checklist. The existing CPU stream is outside the experiment and untouched.

Only the local RTX2070 is authorized for this screen. Paid Vast spend stays
zero. Measured useful steps/sec and complete games/sec will inform the next
funding recommendation after accepted learning/transfer evidence.

## Rejected first launch identity (historical)

Final plan SHAfd5f0274166ba6fa6dc7e24df3103f1ea2b3c9061d83b0feae670cd6d5932036.
Runner SHAe695a92677c069e2b4160ae059b9727c766e99f53af50f90df44a22a94502d98.
The final reviewed package is `plans/memory-learning-paired-250m-v2` on the rig.
Invocationc0b4747eb44a45949cf865ff2838e0f1; initial trainer wrapper PID36096.
Fresh process output confirms the expected historical module553c70… and R0;
GPU activity is measured independently. First observation:5440MiB,70%,71C.
This is liveness evidence, not completion. The live checklist follows actual
process/status sidecars and fresh train/eval panels for each scheduled arm.


## Accepted recovery training — D337–D338

The v2 launch above halted on its thermal guard at 127,270,912 steps and
contributes no accepted checkpoint or performance measurement. The recovery
restarted all four arms fresh at a symmetric 125W power limit. Its plan is
`8f1592f07da731536c1a687ed6a6dcf872d17c0ac2e54a711c811b56bec25df8`,
unit `bb-memory-learning-paired-250m-v3.service`, invocation
`de9f9abcc9d647879a840e9942421079`.

All four runs complete at 249,954,304 aligned steps each (999,817,216 total).
Independent acceptance verifies final checkpoint, lineage, producer, log,
CUDA/Puffer, runtime closure, finite values, final epochs, full-game gates,
and exact-zero integrity counters. The 611 hardware samples peak at 81°C.
Configured power is 125W throughout; instantaneous draw is diagnostic and can
transiently exceed that setting. Unit wall time is 6,212.869 seconds; summed
native reported uptime is 5,667.375 seconds. These are different measurements.

| Training arm | Completed embedded evaluation games | W/D/L | TD for/against |
| --- | ---: | --- | --- |
| Historical, seed 42 | 10,079 | 0 / 10,079 / 0 | 0 / 0 |
| Corrected, seed 42 | 10,030 | 0 / 10,030 / 0 | 0 / 0 |
| Corrected, seed 43 | 10,041 | 0 / 10,041 / 0 | 0 / 0 |
| Historical, seed 43 | 10,053 | 0 / 10,053 / 0 | 0 / 0 |

Training integrity acceptance is bound by
`audit-artifacts/memory-learning-thermal-review-20260905/ROOT_COMPLETION_VERIFIED.json`
(SHA `5ab2facf73d138f3e951b39b05e5186c286b088dba166dcfb8c87ac6e4e8676b`).
The embedded outcomes do not establish scoring ability or rank the memory
contracts by playing strength.

The separate 512-game held-out exam is now running with plan
`f584a077b43fa880cc951cb53410c6f54439b12df4db0882932c2d1e1de820df`,
unit `bb-memory-learning-heldout-512-v1.service`, invocation
`2d2e5d7510544ab1ad662bef0b487684`. Its saved completion and independent
raw-game verification remain required before interpreting its result.


## Held-out result — D339

The512-game exam completes with independent raw-record verification and exact
canonical-result reconstruction. All four learner policies score0TD. Historical
seed42 W/D/L0/50/78 (TD0/120), corrected42 0/46/82 (TD0/119); historical43
0/47/81 (TD0/115), corrected43 0/48/80 (TD0/121). Match utility differences are
-1.5625pp and+0.390625pp, macro-0.5859375pp. These inconsistent descriptive
results do not establish superior learning and do not justify reverting the
correctness repair. D340 selects fixed-budget recurrent teaching locally.

Unit wall1497.843s, maximum62C, power.limit125W. Raw result SHA
f84fbf728a12be4e17803a4a90a177fcd257ca0e41ec9a8abb8a38a7275d21ed;
root acceptance is `audit-artifacts/memory-learning-evaluation-20260905/ROOT_EVALUATION_VERIFIED.json`.
