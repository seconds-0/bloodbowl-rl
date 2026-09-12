# September improvement results and next decisions

## Recurrent-memory evidence update — September 5, D329–D334

The terminal-aware memory contract is implemented and passes real CPU and CUDA
qualification. The old trainer leaked recurrent state across completed games
inside a rollout window. The replacement clears those boundaries and preserves
detached numeric state across ordinary H64 windows, with coherent PPO initial
state gathering, terminal masking and copied tail evaluation. Native direct
derivative error is below8.36e-8; the focused PPO ratio residual is below9.54e-7.
Recorded counters prove graph and eager execution took their intended paths;
all saved arrays match exactly. H512/L3 LR0 throughput is100,758 steps/sec.

A frozen-checkpoint bridge completes16 games per runtime across two opponents,
both sides and two seeds. All16,913 paired decisions match exactly, including
observations, exact legal support, sampled actions, log probabilities and values.
All16 integrity counters are zero and serialized weights remain unchanged.
The full eight-bank gate also passes: 475,136 ratios, all 1,072 primary rows,
maximum ratio error 9.06e-6 below 2e-5, unchanged LR0 weights, and zero integrity
counters. The clean sustained canary completes 49,938,432 training steps,
163,235 training games and 10,175 evaluation games with all 16 hard fields zero.
Its checkpoint reloads and saves byte-identically in a fresh GPU constructor.
The entire measured producer contract matches without an audit amendment.

Final evaluation is all draws and zero touchdowns. This completes memory and
execution qualification; controlled learning and held-out match-strength tests
remain future experiments. The earlier canary with a monitor interval mismatch
remains rejected. No paid GPU use, production change or promotion occurred.

Evidence: `audit-artifacts/memory-integration-20260905/`,
`audit-artifacts/memory-canary-repeat-20260905/` and D329–D334.


This is an active work log, not a production promotion. Chain 9 remains the
reference neural checkpoint. All work uses local compute; Vast spend is zero.
The live checklist is at `http://127.0.0.1:8768/` while its local server runs.

Earlier obs-v7 runtime qualification (D328; superseded for recurrent behavior): the user-approved WSL relocation to D: is complete
and verified. All preserved runtime/source/checkpoint identities survived.
The corrected native trainer now completes a full local integrity canary:
49,938,432 training steps, 146,099 completed training games and 10,194 evaluation
games, with all16 integrity counters zero. Its checkpoint is finite and reloads
byte-identically; native results and phase telemetry are preserved. The unit
exits0 and the GPU is released. See
[the independent final verification](../audit-artifacts/canary-recovery-plan-v9-r2-20260905/ROOT_COMPLETION_VERIFIED.json).

The run scored no touchdowns and every evaluation game was a draw. This is
execution-integrity evidence, not useful playing strength or promotion. A
redundant plan registry-hash label was explicitly corrected in the audit; the
actual hash-pinned prelaunch and executed runtime manifests agree exactly.
The original plan remains intact and fails the new stricter plan-identity guard.
All failed preparations and their amendments remain preserved.

The latest focused qualifier/reducer/output/storage/plan-identity suite passes47
tests; the actual canary supervisor passed19 tests locally and on the rig.
The native engine/environment evidence remains616 cases plus the writer,
passing normally and under ASan/UBSan before this unchanged-engine canary.
Next implementation priorities and executable gates are in
[the recurrent-memory tranche plan](recurrent-memory-next-tranche-2026-09-05.md)
and [the training/funding plan](training-and-funding-plan-2026-09-04.md).

Current-source search improves normalized match utility by **3.52 percentage
points against contact** (paired-seed interval +1.27 to +5.66). Offense transfer
is +2.73 points with an interval reaching zero. All 1,280 games complete with
zero real-game/counterfactual errors. Contact losses increase from 57 to 63,
so the primary-utility gain is not improvement on every outcome. This is a
script-plus-search result, not a stronger neural checkpoint.

The frozen migrated Chain9 baseline completes all 256 games: 63 wins,
142 draws, 51 losses, 102–91 touchdowns and 52.34% match utility. The cage
opponent result differs sharply by learner side (64.84% home, 45.31% away).
That is a diagnostic needing attribution, not a confirmed new encoding defect.
The migrated checkpoint remains qualification-only and ineligible for promotion.

Actual execution also exposed and repaired tiny-evaluation constructor replay
inheritance and float32 cumulative-length decoding. Thirty evaluator/comparison
tests pass. A separate read-only host-capacity checker rejects the full C:
drive and accepts D: for the proposed move plus a 100 GiB reserve. It has three
focused tests. Future execution plans must integrate host capacity throughout
the run; the old canary plan must not be resumed without those changes.

## What the evidence establishes

| Work | Measured result | Scope |
|---|---|---|
| Worktree cleanup | 49 of 77 old worktrees removed; about 4.55 GiB recovered; refs unchanged | Dirty, unique, active and vendored work preserved. New experimental trees are separate. |
| Integrated engine/environment fixes | 616 native test cases plus writer passed; matching ASan/UBSan coverage; 100 standalone self-test episodes | Pass/handoff settled possession, restored-state potential history, safe multiple-script routing, sole-interceptor choice, Dump-off/Trickster/My Ball and obs-v7 integration. |
| Rollout ownership | Native CUDA and Torch CPU scoped verifiers passed | Explicit final reward/terminal/value and exactly one training consumption per rollout. |
| Direct recurrent calculation | Native gradients pass eight cases; eight-bank maximum ratio error 8.34e-6 below unchanged 2e-5; generic gates pass | Private candidate module 9fc1ffcb. All 1,072 learner rows and 18 recurrent state groups covered; weights unchanged; zero hard-integrity counters and eager fallback. The final integrated gate also passes: maximum ratio error 9.54e-6, all 557,056 saved ratios independently checked; qualification-only migrated banks remain ineligible for training. |
| Matched recurrent throughput | 141,736 versus 136,862 steps/s, +3.56% | One-bank, one-layer LR=0 full rollout-plus-train, explicitly matched configuration. One measurement per runtime, not a confidence interval or eight-bank production speed claim. |
| Model-facing action contract | 14,115,881 enumerated actions survived projection and decoding over 26,038 decision windows | This cannot detect choices omitted by the engine before enumeration. Several such omissions are now confirmed from current BB2025 rules. |
| Integrated obs-v7 viewer | Seven actual viewer tests; six natural kickoff matches, 6,550 exact-support checks, all 11 required counters zero | Exact joint selection and batch configuration. Production viewer unchanged; native PPO used a different action path. |
| CPU entropy objective | Three real train-method SGD-update effects matched independent derivatives; maximum error 1.14e-8 | Deterministic scalar-policy fixture; native proof is reported separately. |
| Native CUDA entropy objective | Eight isolated cells passed; gradient error at most 2.17e-8; positive versus zero entropy changed saved weights | Actual eager/graph execution counters and exact coefficient-specific checkpoint parity; controlled objective proof, not match learning. |
| Exact-route BC then PPO | Final scores 4016, 4023, 4009 of 4096; scratch 0 in each seed | One fixed cooperative both-decision-sides drill. Extra supervised information and updates in BC arm. |
| Reproduction | All 18 parameter digests and phase evaluation records reproduced; all checkpoints saved/reloaded | Reproducibility at the same seeds, not six independent training seeds. |
| Corrected backward curriculum | Final scores 3468, 3225, 90 of 4096 | Learns the same fixed drill but with substantial seed variance. |
| Final current-source search versus contact | 48.63%→52.15% match utility; +3.52 pp, interval [+1.27,+5.66] pp | 512 paired cases / 1,024 complete games on the rig; same script with/without search, source da3d855a. |
| Final current-source search versus offense | 50.00%→52.73%; +2.73 pp, interval [0,+5.47] pp | 128 pairs / 256 complete games; broader transfer remains uncertain. |
| Frozen Chain9 baseline on corrected obs7 | W63/D142/L51; 52.34% utility; TD102–91 | 256 exact-matrix games; no optimizer; new baseline only, no old-ABI numerical comparison. |
| Pre-Blitz-context-repair search versus contact | Match utility 49.71% to 53.81%; +4.10pp, 95% seed-cluster interval [+1.95,+6.25]pp | Prospectively frozen fresh seeds 4001–4256, both sides: 512 pairs / 1,024 games. Root recomputed raw results and bootstrap. |
| Pre-Blitz-context-repair search versus offense | Match utility 50.00% to 51.56%; +1.56pp, interval [−1.95,+5.08]pp | Fresh seeds 5001–5064, both sides: 128 pairs / 256 games. Transfer sign remains inconclusive. |
| Decision clock | 1,301 mean decisions per scripted match; 4.8% singleton active decisions | Median observed uninterrupted held-ball-to-score interval 146.5 decisions, not a neural-policy measurement. |

The historical search rows below retain their pre-repair source identities and are not pooled with the final rig matrices.

Search used two counterfactual samples and 64 decisions per candidate at fresh
team-turn roots, TD-differential utility, and the offense baseline on ties. It
averaged 11.92 ms per searched root in the fresh contact confirmation. Every played and counterfactual error
counter was zero in the final contact and offense tests. These results concern
a script plus search; they do not establish an improvement to chain 9 itself.

## Corrections that matter

The targeted-action engine repairs broke exact reproduction of the historical
search results. D308 preserves that failed compatibility comparison. The table
above now reports a separate, prospectively frozen confirmation on unused seeds,
with unchanged search code. The old +3.81pp contact and +3.52pp offense estimates
retain their old-source scope and are not pooled with these results. Current
offense transfer is inconclusive. Evidence and root recomputation are in
`audit-artifacts/tactical-search-obs7-fresh-confirmation-20260904/`.

The first version of the **new standalone curriculum diagnostic written during
this work** had incorrect return tuple indices. Its zero-scoring result is
rejected. This was not a discovered defect in the historical production PPO
return implementation. The separate BC-versus-scratch loop used correct indices
and its result was independently reviewed and reproduced.

The original tactical reporting mixed 3/1/0 tournament points with normalized
W+0.5D match utility. That reporting error was corrected. The planner also
needed decision-owner dispatch and explicit counterfactual failure accounting.
Both fixes preceded the separately frozen final 512-pair confirmation. Earlier
screens were not pooled into that primary result.

The old F5 branch contains extensive protocol but lacks its required controller
and verifier. The new diagnostic does not claim to satisfy that sealed pilot.
Its two-sided policy control after turnovers and its fixed geometry are
explicit limitations.

Runtime qualification exposed stale test assumptions after strict rollout-tail
ownership was introduced. The qualification loops now consume each fresh tail
once at zero learning rate. Later checks found missing read-only native entropy
instrumentation and an oversized full eight-bank diagnostic snapshot. The
instrumentation exposes actual gradients and graph counters; compact snapshots
retain only the evidence needed by the eight-bank gate. Failed attempts remain
preserved and do not count as accepted training evidence.

## Why these are useful low-cost directions

1. **Validate the learning objective through actual parameter updates.** Logged
   entropy coefficients and passing helper tests are insufficient to establish
   behavior inside a captured CUDA graph. The compact native proof uses raw
   tensors and an independent derivative, plus saved-weight comparisons.
2. **Provide useful early learning data.** Eight reviewed legal demonstration
   pairs made this drill reliable across the tested seeds. This supports testing
   complete current-engine teacher trajectories, particularly late-drive and
   recovery states missing from prefix-censored replay data. It does not justify
   assuming scripts are optimal teachers everywhere.
3. **Use the simulator at decision time.** Bounded search found a reproducible
   scripted match gain at modest CPU cost. Next neural-policy work should test
   it as a proposal checker or teacher, with learned-opponent and latency gates.
4. **Change opponent diversity without changing exposure.** Two equal-layout
   eight-bank pools now freeze 122 script rows and 366 historical-policy rows per
   buffer. The candidate changes which historical policies occupy the seats;
   it does not silently change the amount of scripted or mirror play.
5. **Make evaluation cheap enough to use.** The current lossless serial runner
   costs about 2 seconds/game. Four models across eight cells at 1,000 games/cell
   would take roughly 17.8 hours. A per-environment completion snapshot can make
   batched frozen evaluation lossless; it needs an explicit implementation and
   throughput benchmark before any speed claim.

## Remaining local sequence

The original instrumented runtime passed generic recurrence, entropy gradients
and graph replay but failed the actual eight-bank, three-layer ratio check.
The preserved repeat retained all 557,056 ratios: 0.714% exceeded 2e-5, with
maximum 9.1314e-5 despite unchanged weights. A same-input, same-action,
same-weight dual-forward diagnostic localized the discrepancy to the sequence
calculation: the scan's native ratio error was 6.25e-5 in the selected cell,
while direct recurrence reduced it to 8.58e-6. An independent float64 head
calculation agreed. The replacement direct forward/backward then passed actual
native gradient tests, the unchanged full eight-bank gate, and generic
qualification. This establishes numerical correctness on the tested fp32
configuration, not improved playing strength. BF16 is unqualified.

The user's decision-interface audit changes the order of work. Sole interception,
Dump-off and Trickster now have explicit coach-owned windows and integrated
procedure tests. Obs-v7 exposes temporary rerolls, effective skill parameters,
and nested targeted-action context. The combined source passes 616 native
cases and writer under normal and sanitizer builds. The fresh compiled runtime passes its numerical and viewer gates.
Migrated checkpoints remain qualification-only; the frozen neural baseline
has not yet completed because its first launch rejected canonical source symlinks.
The failed attempt is preserved and a focused provenance repair is in review.
The complete registry inventory now has source/rules review for all 108 IDs,
with 29 documented gap groups and four shared repair tracks. This is not full
executable conformance. Missing reroll windows and common rule semantics take
precedence over another broad reward sweep. Passing masks alone cannot make
an omitted choice learnable.

Training still resets recurrent memory every 64 decisions and carries it across
auto-reset episodes within that window; evaluation carries memory through the
whole game and clears it at terminals. This is the known August F9 debt, not a
newly discovered mismatch. The present comparison holds that behavior fixed;
terminal-aware recurrent training needs a separate coherent rollout/recompute
change and experiment. After qualification, run the disposable 50M
qualification-only canary.
Neither its checkpoint nor its short training curve is a strength result.

The previously frozen obs-v6 opponent-composition proposal was 100M steps for control/candidate
at seeds 42/44, reversing arm order. The initial final-checkpoint exam uses
32 completed games per cell, contact and offense, both sides, and fresh exam
seeds 6001/6002: 256 games/model and 1,024 across the four trained policies. Its historical runtime and checkpoint identities cannot launch the new v7
stack. After explicit rule-scope and migration eligibility decisions, a new
prospective plan at this budget could expose large failures and asymmetry. It cannot rule out
long-horizon benefits, select a production candidate, or establish a narrow
promotion margin. Larger confirmation gets a separately frozen plan.

## Conditions for spending on Vast again

Do not fund a broad hyperparameter sweep merely because infrastructure now
works. First establish a qualified stack, a reproducible saved baseline exam,
and a measured learning or transfer signal worth scaling. Then fund one
bounded comparison with an unchanged control, exact source/runtime/checkpoint
identities, fixed exposure and independent training seeds.

Before larger paid runs, implement and benchmark lossless batched evaluation,
then add held-out learned opponents and a representative roster/side grid.
Measure games per second and useful training throughput for the actual policy
and bank configuration. Use those measurements to choose a capped experiment
and expected wall time. Final confirmation needs another ancestry and longer
horizon; a positive two-seed scripted screen is not enough.

The first product target remains reliable local play: complete legal matches,
useful score/defense behavior across held-out states, reproducible saves and
replays, and measured tail decision latency. FUMBBL integration is a later
adapter/conformance project. A supported route for automated online play still
needs verification before any account or match action; no such action has
been taken.

## Evidence map

- Original audit and cleanup: the original task tree's
  `audit-artifacts/training-review-2026-09-04.md` and
  `audit-artifacts/worktree-cleanup-2026-09-04.md`.
- Integrated qualification: `audit-artifacts/rig-stage-2/` and
  `audit-artifacts/entropy-cpu-new/`, and `audit-artifacts/rig-stage-3/`.
- Preserved learned policies:
  `audit-artifacts/f5-september-bc-vs-scratch-ppo-preserved-20260904/`.
- Corrected curriculum:
  `audit-artifacts/f5-september-full8-ppo-corrected-returns-20260904/`.
- Search final contact and offense transfer:
  `audit-artifacts/tactical-search-v2-final-contact-20260904/` and
  `audit-artifacts/tactical-search-v2-offense-transfer-20260904/`.
- Numerical attribution and candidate qualification: `audit-artifacts/rig-stage-4/`
  and `audit-artifacts/rig-stage-5/`, including root-verified accepted hashes.
- Model-facing action/observation/rule evidence:
  `audit-artifacts/model-facing-audit-20260904/`.
- Atomic accepted findings: `DECISIONS.md` D290 onward.
- Prospective initial exam amendment and lossless batching design:
  `docs/opponent-composition-initial-exam-amendment-2026-09-04.md` and
  `docs/vectorized-frozen-eval-design-2026-09-04.md`.
