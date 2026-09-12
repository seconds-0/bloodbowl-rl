# Blood Bowl RL training and funding plan

Current as of September 11, 2026, D387. All four local training runs and the
fixed512-game evaluation are complete and independently verified. The
predeclared scoring gate failed: every model scored zero learner touchdowns.
The [live checklist](http://127.0.0.1:8768/) reads actual progress; it is the
current source for run status. Additional Vast budget for this stage: **$0**.
No checkpoint, reward configuration, or production default is promoted.

The immediate goal is reproducible full-game scoring and match-strength gains.
The present learned policy is not yet an acceptable local opponent. Championship
play and FUMBBL integration remain later milestones requiring substantially
stronger opponents, broader rules coverage, and an independently qualified
execution adapter.

## What the current evidence supports

| Evidence | Measured result | Consequence |
| --- | --- | --- |
| Local RTX 2070 memory comparison | 999,817,216 aligned steps in 1h43m33s; zero TD across its four-model exam | Execution correctness is qualified; more scratch PPO of this recipe has no demonstrated scoring benefit. |
| Short finishing demonstrations | 17 TD in 64 trained-policy authored-position trials; zero TD in subsequent full kickoff games | The main recurrent policy can learn a scoring skill, but the narrow state distribution does not transfer. |
| Full-match BC across four initialization seeds | Trained W/D/L 2/195/315, TD 2/454 over512 games; fresh 0/175/337, TD 0/543 | Aggregate utility improves, but the fresh-seed confirmation fails scoring and cage-opponent gates. Do not select the favorable aggregate. |
| Development imitation | Original trained exact-action fit about51% on DEV versus81% on train | A generalization gap is present; its cause is not established by accuracy alone. |
| Demonstration coverage | Old32 matches have280 near-end-zone own-carrier records; additional32 have119 | More unconditional matches do not guarantee more finishing exposure. These are geometric decision counts, not possession rates or scoring feasibility. |

The accepted conclusions and immutable evidence links are in D338–D370 of
[DECISIONS.md](../DECISIONS.md). Different runtimes, reward semantics, and
observation contracts must not be compared as interchangeable benchmarks.

## Latest full-game result and next action

| Seed | Repeat32 W/D/L; TD for/against | Diverse64 W/D/L; TD for/against | Utility difference |
| --- | --- | --- | --- |
| 20260909 | 0/42/86; 0/123 | 0/49/79; 0/115 | +2.7344 percentage points |
| 20260910 | 0/46/82; 0/119 | 0/54/74; 0/113 | +3.1250 percentage points |

All512 games ended naturally with zero integrity counters. Broader data converts
some losses into draws and reduces conceded touchdowns, but it does not produce
scoring or wins. The fixed learner-touchdown gate fails. Keep the complete
negative result. The independently verified DEV diagnostic improves exact imitation from51.4%
to54.5% and51.1% to53.5% across the paired seeds. It has no authority to
override the failed scoring outcome.

The exact-trace diagnostic is complete and accepted through a separately
reviewed recovery of a supervisor final-report error. All 64 games reproduce
their original observation/action traces and raw results across 32,791 learner
decisions. The original supervisor failure remains preserved; no game rerun
was needed. The child took 33.59 active seconds on local CPU.

The learner was observed owning the ball in 28 of 64 games. Only one game
reached carrier distance eight or less, and no game presented a legal carrier
step into the end zone. This points to acquisition and progression as the next
training targets; it does not prove a cause or measure continuous possession.
See D380 and the immutable recovered raw proof for exact per-model denominators.

The next fixed scientific comparison changes only the source of supervised states:
continued learning from new teacher-played games versus the same teacher's
labels on frozen learner-played games. Both arms start from the same accepted
checkpoint within each seed and receive the same optimizer-update budget.
This is one batch of teacher labels on learner-visited states, not full DAgger.
The teacher may use privileged state and is not assumed optimal.

The actual native-to-training-reader path now passes a complete historical
576-decision sequence, including34 teacher choices unsupported by the actor
mask. Each teacher label receives its own conditional mask, and deliberately
substituting an incorrect mask is rejected. Root independently verified all
labels and unchanged qualification inputs/outputs (D381). Independent native-query review also passes all32,791 historical decisions
(D382). The complete collection runner and external supervisor remain under
final review. Actor
traces are frozen before offline teacher labeling in the same owned child;
pointer-bearing internal hashes are only same-process purity witnesses.
Fresh128-game collection is complete and accepted (D386):80,342 decisions,
zero integrity errors,532.43 active seconds and1.84GB retained output.
The longest full match is1,228 decisions, within the2,048 training bound.
The actual trainer reads all128 payloads. The four-arm training plan passes independent review and is RUNNING
(session17971, D387). The first arm has emitted finite optimizer updates;
512total updates and192fresh evaluation games remain the fixed experiment. The prospective training
controller passes7 focused tests and provisional review; the implemented
evaluation worker/controller passes8 tests including actual historical
unique-turn metrics. D384 fixes possession-gate denominators to unique
observed (half,drive,learner-turn) keys, with boundary counts diagnostic only.
The collection shutdown and trainer-interface checks now pass. All four complete corpora now pass independent raw-data verification.

The fixed local screen has four continuation arms, 128 full-match
updates each, followed by 32 fresh-seed games per model for two unchanged
starts and four trained models (192 games). Scientific seeds and update schedules are fixed in
`TEACHER_LABEL_CONTINUATION_PROTOCOL_V1.json`. Runnable source identities,
collection and evaluation commands will be frozen after qualification.
The earlier measured training gives a rough 26-minute active training estimate;
allow up to 90 active minutes for the full local screen. Sequence lengths can
change this estimate. The pre-collection storage measurement implies about1.34GiB for128 games at
the historical fixture size. D383 fixes an8GiB collection cap and5GiB free-space
reserve; training and evaluation each retain a1GiB output cap. This changes
no scientific input or gate. Additional Vast funding remains **$0**. Stage improvements
cannot establish competence; positive scoring and stronger independent
confirmation remain required before goal completion.

## Completed comparison and retained measurement contract

The frozen comparison uses paired initializations20260909/10. Each seed trains
one model on32 matches repeated8 times and one on64 matches repeated4 times.
Both receive256 complete-match optimizer updates. Control has183,600 decision
presentations; diversity has189,664. Architecture, teacher, Adam settings,
conditional masks, recurrent semantics and shuffle rule remain fixed. The
counterbalanced run order is09 control,09 diverse,10 diverse,10 control.

All four completed trainer results total **51.24 minutes of active elapsed
time**, including their final fit and checkpoint reload checks. This replaces
the earlier39- and42.5-minute estimates. The Mac power log records a lid-close
sleep during the third run, so total civil wall time is longer. No run restarted.
The corresponding earlier512-game direct Torch/C exam took65.46 seconds on
the Mac CPU. That is a reference measurement, not a guaranteed duration or a
benchmark of the GPU PPO path. No rental capacity is needed for this screen.

The retained measurement contract is:

1. Verify exact source/runtime/checkpoint hashes, all256 update rows per arm,
   finite changed weights, complete-match state handling, and completion links.
2. Evaluate every trained model in the predeclared512-game exam:128 games per
   model, contact and cage opponents, both sides, common untouched kickoff
   seeds, natural game endings, no demonstration resets, and exact-zero
   integrity counters. Any integrity failure rejects evidence.
3. Independently reconstruct raw W/D/L, TDs, paired differences and all fixed
   gates. Diversity must improve utility and learner TDs in each seed, with
   combined positive utility for each opponent style and each side. All gates
   were fixed before training. Two seeds remain descriptive screening evidence.
4. Run the separately reviewed eight-match DEV diagnostic for all four models.
   Its exact, optional-head, action-family and joint-NLL metrics explain fit;
   they cannot select a checkpoint or cancel its full-game exam. The eight
   reserved test trajectories remain unused for neural inference.

If the fixed game gates fail, retain every result and use the failure pattern
to choose one new local factor. Candidate questions include targeted drive-stage
coverage, teacher quality, label equivalence and spatial representation. None
is authorized as a scientific winner by the current training curve. A new
experiment must freeze its own population, held-out games and success criteria.

If the screen passes, replicate with fresh initializations and new game seeds,
then evaluate learned opponents, a roster/matchup grid and longer-horizon play.
Successful scripted-opponent screening alone does not establish local competence
or justify promotion. Reward changes additionally retain the July audit's
multi-seed, second-ancestry and terminal/clip integrity requirements.

## Conditions for a paid proposal

A paid proposal becomes useful only when a locally supported learning question
needs more capacity than this local setup can reasonably supply. Before asking
for funds, produce a concrete bounded workload and evidence-based comparison:

- Benchmark the exact proposed trainer/runtime on the intended GPU; do not
  extrapolate the RTX2070 or CPU measurements into an invented speedup.
- Record useful training throughput, completed full-game evaluation cost,
  setup/build/transfer overhead and storage requirements.
- Obtain a current hourly quote and terms when provisioning is actually in
  scope. No current Vast quote or paid launch is assumed here.
- Calculate rental hours as setup + training steps/useful throughput + evaluation
  + artifact transfer. Multiply by the quoted hourly price and add storage or
  other quoted charges. Include a stated contingency and an absolute spend cap.
- Freeze the experiment before launch. Enforce runtime, progress, disk, thermal,
  output and integrity stops; retain failed evidence and release rented capacity
  at completion or the cap. Do not let an unattended job invent new experiments.

No dollar request is warranted by the present results. The next funding revision
will report the completed four-arm wall time, full-game outcomes, and whether
there is evidence supporting replication or a different local training factor.

The exact earlier version of this document is preserved in
[the historical plan](training-and-funding-plan-history-2026-09-06.md), SHA-256
`daf9bc36ddc9ab572bf0b6e7f20b265b614ee3ecfea9e02ce7a0fdf7b71b65f0`. It contains dated operational snapshots, including superseded
statements about which jobs were running; the current plan above replaces those
status statements without modifying the scientific ledger or frozen artifacts.
