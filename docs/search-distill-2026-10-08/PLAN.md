# Search distillation, Test 1: plan, version 2, the narrow first slice (2026-10-08, not registered)

**Status: a plan for the operator to register. Nothing here is registered and no registered game has been played. No cloud resource exists for it and none was touched. Version 1 of this file (commit `1b6122c`) was read by an outside reviewer (`/Users/alexanderhuth/Code/bb-opt-build/.codex-reviews/distill-plan-review.md`); this version applies the operator's decisions on that review. The tools of section 7 now exist, and milestone 0 and the wide rehearsal were run on the Mac; what they showed is in `/Users/alexanderhuth/Code/bb-opt-build/docs/search-distill-2026-10-08/NOTES.md` and is never evidence. It adopts nothing.**

Short names used below.
- **C**: chain 55 (`f6ba3b449bf0cec15e37ba47b32b097dd513ee7dba3241b16ad90dd2a0675e0b`) played under the m1 mask, sampling at temperature 1.
- **S**: C with the search seat at the setting D430 registered and D434 read (+45.5 and +45.3 decisive-Elo over C against chain 37 and chain 46, at 48 times the cost).
- **F1, F4, F16**: three fine-tuned copies of chain 55, one per lambda (1, 4, 16), each played under m1 at plain speed. Player names `c55d1l1`, `c55d1l4`, `c55d1l16`.
- **A deviation root**: a decision in the seat's scope where the seat's rule deviates. **The label** there is the action the seat would play.
- **A loss decision**: a screened root that is not a cap rejection, or a sampled out-of-scope decision. Nothing else enters the fine-tune or any reported number.

## 0. What changed from version 1, and why

The review had five blocking findings and recommended a narrower first slice. The operator agreed. In short: one recipe, three arms, the gate decides.

1. **Recipe R1 only** (the policy rows of the output layer). R2 is postponed to a later entry (section 9). The exploratory preview on 87 seen labels suggests R1 may memorise its labels and change other decisions as a side effect. So a failure of this slice says "R1 failed to fit, or to transfer its labels, or to improve matches, at this label count" and nothing wider.
2. **Postponed:** the captured share and its rollouts, the fresh screen of F, the linear probes, the learning curve, selection by rollouts. The reviewer showed the captured share is not calibrated as version 1 defined it. It is not repaired here. Section 9 keeps the objections so a later entry starts from them.
3. **Held-out roots are reported numbers with no thresholds.** The only registered stop before the gate is the fit check.
4. **The gate decides, and it is batched.** 32 games per worker for every arm, as chain gates play masked seats. Because that makes the gate cheap, all three lambda arms are gated against chain 37 and chain 46 with C as the paired control on the same seeds: eight pairs. One arm is the registered arm, chosen on validation games before any gate game; its two contrasts carry the label. The other two are a registered descriptive dose-response and carry none.
5. **The loss is named for what it is:** a deviation cross-entropy plus a preservation KL to the original policy. It is not maximum-likelihood cloning of the seat (section 3).
6. **Corrections applied:** the KL is over the joint support's tuples; acceptance requires min(4, support size) x 16 screen returns; a judgment rollout that ends on the inherited decision cap has a registered rule; every reading has its undefined cases defined; every conclusion is restricted to the recipe and label count tested; an arm's sidecar hash is bound and verified beside its blob hash; teacher parity is tested on identical cloned roots after a game's first deviation; the longer horizon at a kick-off Blitz turn root is tested directly.

## 1. The question, and the claim it can support

**Question.** If states are labelled with the search seat's choice and the policy rows of chain 55's output layer are fine-tuned toward those labels, does the result (a) fit the labels, (b) give the labels probability on games it was not trained on, and (c) play stronger than C in fresh games at plain speed?

**The claim is about recipe R1 at this label count.** "Chain 55 with its output layer's policy rows fine-tuned by section 3 on about 2,900 labels made by the D430 seat at roots of C's own self-play does or does not improve plain-speed play against chain 37 and chain 46." (a) is a registered check. (b) is reported. (c) is the gate.

**What a Positive gate would mean.** This offline intervention improves plain-speed play against these two opponents. That justifies the next larger design. It is a strength result. It does not by itself show that the labels generalise: the held-out numbers are printed beside it for that, with no threshold.

**What it would not mean.**
- That an on-rig exploration scheme (candidate (g) of the study) would learn the same thing.
- That the gain survives further PPO training, or grows when the loop is repeated.
- That an arm can be a warm start: it is outside the trainer's lineage (section 3).
- Anything about another checkpoint, a stronger opponent, or a person.
- That it reproduces S's play. Labels are one changed action on C's own games; the arms meet states no label covers.
- That any single deviation is right. D434's limits travel with this plan: the seat's evaluator is the shaped reward plus the value head.
- That an arm is defined without m1.

**What a gate that is not Positive would mean.** R1 failed to fit, or to transfer its labels, or to improve matches, at this label count. The fit check and the held-out numbers say which is most likely.

**What it would not mean** (the review's item 2 on the study). That the tail cannot be learned by an online scheme, by another recipe (R2 trains the trunk), from more labels, or from labels made on the student's own games.

## 2. Data

Unchanged from version 1 except where marked.

**Checkpoint, mask and play.** C in both seats: chain 55 under m1, temperature 1, kick-off starts, reward manifest `r0_poss_half` (`433c792018acdc01f8c7168e824c9389bf99df2307d3260283b7877df3f69d5c`), gamma 0.999. Seat A is HOME in even games and AWAY in odd games. Seat B is the same network with its sampling seed offset by one stride. Harness: branch `feat/search-probe-20261007` at `5ab3ab6e195afbb717d7e0e7e62361a3b548fdd6`, used from a `git archive` export. Between D430's commit `06f0a5f` and this one only `tools/gate_acceptance.py` and its test changed.

**Why self-play roots.** They are where D2 was checked (0 false deviations of 87) and where the opponent model in the rollouts is exact. Chain 37 and chain 46 stay held out as opponents.

**Roots.** Seat A's decisions in the seat's scope: class `turn` (an ACTIVATE is legal after masks) and class `after_declare` (the first own decision after the own DECLARE), with two or more legal actions after masks. Never the DECLARE itself. Per game, 15 roots per class, a uniform sample of that game's searchable decisions of the class, drawn exactly as `tools/search_probe_diag.py` draws it. Each root carries the weight (searchable decisions of the class in the game) / (roots kept).

**The screen at a root, and the label.** Exactly the seat's computation at that decision.
- a0 is the action plain play sampled.
- The candidates are a0 and the other legal joint actions with the highest policy probability, ties in packed order: **min(4, support size) in all** (corrected: a root needs only two legal actions).
- 16 rollouts each through `play_harness.search.Rollouts.evaluate` on common random numbers, both sides played by chain 55 under m1, stopping at the end of A's team turn, the end of the match or 200 steps. Seeds from A's sampling seed, the engine step and the rollout index: the seat's own seeds.
- The label rule is `play_harness.search.deviation(returns, 0.10)`. A deviation root's label is the best alternative.
- A root where any screening rollout ends on the inherited decision cap is a cap rejection, as for the seat. It is counted and enters no loss and no number.

**a0 is the sampled action, on purpose.** Every root stores the original policy's log-probability of a0 and of the label, and the held-out numbers are also printed for "new" labels only (original probability of the label below 0.01).

**Labels judged on independent rollouts.** Every deviation root gets 128 fresh rollout pairs of a0 against the label (rollout indices 1000 to 1127, never used by the screen, same horizon), run while its clone is still held. Its fresh gain is the mean over pairs. A label is **false** when its fresh gain is at or below zero and **confirmed** when its fresh gain exceeds two of its own standard errors.
- **A judgment rollout that ends on the inherited decision cap** (new): that rollout index is dropped for both actions and counted. A label with fewer than 64 pairs left is **unjudged**: it is neither false nor confirmed, it is counted, and it is left out of every number that uses a fresh gain. A failed judgment rollout stops the shard.
- The fine-tune trains on every label the rule produced, false and unjudged ones included, because that is the seat that was gated.

**Decisions outside the scope.** Per game, 64 of seat A's other decisions with two or more legal actions (the DECLARE, and everything inside an activation), a uniform sample with weights as above. The seat never searches there, so its policy there is the original policy exactly. They need no rollouts.

**A decision inside a kick-off Blitz turn stays a root, flagged.** The label is by definition what the registered seat does, and the seat D434 read searched those decisions with a rollout that runs to the end of its next real turn (D437). Every root records `kickoff_turn` by D439's stack rule, each game counts them, and the held-out label numbers are printed with and without them. The reviewer agreed and asked that the horizon be tested directly; section 7's test `blitz` does.

**Recurrent state.** Not stored, recomputed. Each game stores its engine seed, both sampling seeds and its full action trail. The dataset tool replays the trail through a fresh engine and requires the final digest, the score and the sha256 of both observation rows to equal the game record's. It then runs chain 55 over seat A's row from the first step of the match, which is how the seat came by its state. At every root the recomputed a0 and candidates must be the recorded ones and a0's log-probability must agree to 1e-3. Two candidates that are within that tolerance of each other may change places on another machine; that is counted, and anything else is an error. For R1 the state at a root does not depend on the trained weights at all.

**What is stored**, per shard, under the git-ignored `/Users/alexanderhuth/Code/bb-opt-build/runs/search-distill-2026-10-08/<run>/<shard>/`: `games.jsonl` (seeds, rosters, the action trail and its hash, both observation hashes, the final digest, counts, the integrity counters), `roots.jsonl` (the root, its masked support, candidates, 16-rollout returns at full precision, the rule's result, the label, the judgment's returns), `other.jsonl` (the sampled out-of-scope decisions), `COMPLETE.json`, `plan.json`, `SHA256SUMS`.

**Size.** 10,000 games, 300,000 roots, about 4,000 to 4,400 labels (1.34% in D434, 1.46% [1.16, 1.78] in the screens).

**Split, by game.** With `i = engine seed - 26000000`, the group is `(i // 2) % 10`: 0 to 6 train (7,000 games, about 2,900 labels), 7 validation (1,000 games, about 420), 8 test (1,000, about 420), 9 reserve (1,000, about 420). The dataset tool has no option that writes the reserve group, so a later entry has games no model was fitted or chosen on.

**Seed blocks.** Found unused on 2026-10-08 (the search is in NOTES).

| Use | Engine seeds |
|---|---|
| Labels, milestone 1 | 26000000 to 26000999 |
| Labels, milestone 2 | 26001000 to 26009999 |
| Gate | 25200000 to 25206399 |
| Droplet smoke | 29980400 to 29980415 (labels), 29980900 on (gate) |
| Rehearsals, tests and tool work on the Mac (never evidence) | 29980000 to 29980899 |
| Milestone 0 (seen data, never evidence) | 29100000 to 29100199 |

27000000 to 27000666, version 1's fresh-screen block, stays unused for a later entry.

## 3. The fine-tune: recipe R1, three arms

**Trained:** `decoder.decoder.weight`, 454 x 512 = 232,448 weights. **Frozen:** the encoder, the three MinGRU layers, the value row, every bias (the native blob has none; all are zero, which the writer checks, because the conversion drops them).
- The decoder's input h at a decision does not depend on the trained weights. So the recurrent state at every loss decision is exactly chain 55's for every arm, h is computed once, and training is a linear model on 512 features.
- The critic and the trunk are byte for byte chain 55's.
- The loss is convex in the trained weights.

**The loss: a deviation cross-entropy plus a preservation KL.** Over the loss decisions of the training games, with each decision's weight w:

`L = [ lambda * sum over deviation roots of w * (-log p(label)) + sum over the other loss decisions of w * KL(p0 || p) ] / (sum of w)`

- p is the fine-tuned policy's exact joint distribution at the decision and p0 is chain 55's: type, then argument given type, then square given both, each a softmax over the values the masked support allows after that prefix. Inactive heads are singletons and contribute zero. m1 is applied before any normalisation.
- **The KL is on the joint:** the sum over the support's tuples of `p0 * (log p0 - log p)`. It is never three marginal KLs. The tools hold it equal to the p0-weighted conditional form.
- **It is not maximum-likelihood cloning of the seat.** At a screened root where the seat does not deviate, the seat keeps the sampled a0, and conditioning on "no deviation" changes a0's distribution; this loss pulls toward all of p0 there. Literal cloning would use the action the seat emitted at every screened root. This recipe was chosen because the preservation term is what protects the other decisions.
- **Not in the loss:** in-scope decisions that were not screened (their label is unknown, and at about 1.3% of them the seat deviates), cap-rejected roots, decisions with one legal action.
- **A caution about the KL term.** Chain 55 is saturated at about 70% of decisions, so the term has almost no gradient until the fine-tuned policy has already moved mass, and it only stands where there is a training example. The preview showed what that can cost (NOTES). This is why change at other decisions is reported on held-out games.

**Three arms, one per lambda: 1, 4, 16.** Each takes 2,400 Adam steps at learning rate 0.001 over fixed chunks of at most 8,192 training decisions (the chunks are a seeded partition, visited in a seeded order; at the registered size that is about 30 passes). Arithmetic in float64 on the stored float32 features; the blob is float32. **There is no stop rule:** an arm is its last step. Generator seed 0, one thread. A second run reproduces the blob byte for byte on the same machine (tested).

**The fit check (Reading 1).** The lambda 16 arm's weighted mean probability of the label on training deviation roots, recomputed from its blob. **FIT** is 0.80 or more. NOT FIT stops the plan.

**The registered arm, chosen without the test games or the match games, no rollouts.** On the validation games, for each arm:

`J = q * M * g - 0.016 * U`

- M: weighted mean probability the arm gives the label, over validation deviation roots.
- U: weighted mean total variation between the arm's policy and chain 55's, over the other validation loss decisions.
- q: weighted share of deviation roots among validation loss decisions. g: weighted mean fresh gain of the judged validation labels.
- 0.016 is the study's measured mean cost of an alternative the policy all but rules out (study section 2C). It stands in for the price of an unintended change.
- **The rule.** An arm is **eligible** when its blob passes its acceptance (section 5) and its J is a finite number. The registered arm is the eligible arm with the highest J. A tie goes to the smaller lambda. **With no eligible arm there is no registered arm, the gate is not played, and the plan stops unread at the selection.**
- J is a declared heuristic. It is not an evaluator estimate, its price was measured at in-scope decisions only, and it ignores the covariance of M and g. It only decides which of three arms carries the label; all three are gated.
- The selection is written to `SELECTION.json`, which binds the blob hash and the sidecar hash of every arm. Its sha256 is what opens the test games.

**Writing an arm back as a blob** (checked: NOTES, and section 7's test `blob`).
- `training/convert_checkpoint.py` `cuda_to_torch` then `torch_to_cuda` on chain 55's blob is byte-identical. Zero training steps write chain 55's blob back byte for byte. A trained arm differs from it only in floats 1,424,384 to 1,656,831; the value row (1,656,832 to 1,657,343) is untouched.
- `play_harness.policy.load_checkpoint` requires 16,066,560 bytes and a `.lineage.json` sidecar whose `compatibility` block is chain 55's and whose `checkpoint.sha256` is the blob's. Without a sidecar it refuses.
- **The sidecar an arm carries:** `schema_version` 1; `checkpoint` (bytes, sha256); `compatibility` (six fields); `ancestry` with `initialization: "offline-distill"`, `eligible: false`, `qualification_only: true`, the parent's blob and sidecar hashes and `valid_under_masks: ["m1"]`; `producer` with the plan hash, the recipe, the arm, lambda, the settings, the training file's hash, the tool hashes and the torch version. No `implementation` block: no trainer build produced it.
- **The sidecar's hash is bound** in `SELECTION.json`, in the gate's plan, in the gate launcher's preflight and in the gate's acceptance, which also requires the `producer` block the run's manifest recorded for each player to be that sidecar's. The stock acceptance tool binds blob hashes only.
- **An arm is not a warm start.** The trainer's `/Users/alexanderhuth/Code/bb-opt-build/tools/checkpoint_lineage.py` refuses the sidecar ("implementation must be an object"). That is intended and tested.
- Arms are kept under `/Users/alexanderhuth/Code/bb-opt-build/runs/search-distill-2026-10-08/<run>/finetune/checkpoints/<arm>/`, outside the harness's checkpoint store.

## 4. What is measured

**(i) Fit on training roots: a registered check.** Reading 1 above. Also printed per arm: training label probability (mean, and the share at 0.5 or more) and the change at the other training loss decisions (total variation, share of changed top actions).

**(ii) Held-out roots: reported, no threshold, no rule.** On the test games, opened once with the selection's hash, for each of the three arms. An arm's policy at a test decision uses the same h as chain 55's (the trunk is frozen). Intervals are 95% percentile bootstraps over games, 2,000 replicates, generator seed 0.
- The probability the arm gives the label at test deviation roots: all labels; new labels only; confirmed labels only; by class; without kick-off turn roots; and the share of labels at 0.5 or more.
- The total variation between the arm and chain 55, and the share of decisions whose most probable action changed, at the other test loss decisions: screened roots and out-of-scope decisions separately, and among those the original policy was sure of (top probability 0.999999 or more).
- With about 420 test labels a label-probability interval is about plus or minus 0.05.
- These numbers enter no reading. They are what a later entry starts from, and what tells "did not transfer" from "transferred and did not win".

**(iii) The gate, at plain speed, batched: it decides.** Registered in Entry B once the blobs exist.
- **Players.** F1, F4, F16 (blob and sidecar hashes fixed in Entry B) and C, all under m1, sampling at temperature 1. Opponents chain 37 (`268f1db08ca0c2bad88293ea56b3048a2a1c3a0ea9acdf0365fc023186c0f73f`) and chain 46 (`8eee9ac10f58eca57092013ac05db6f28fb5f7f2c6dc9ce850960c7bb2c7c467`), plain.
- **Pairs.** Eight: F1, F4, F16 and C, each against chain 37 and against chain 46. 12,800 naturally completed games each (102,400 in all): engine seeds 25200000 to 25206399, both legs of every seed, kick-off starts, no sampling offsets. The arms and C share sampling seeds.
- **Batched: 32 games per worker for every arm.** A search seat needs one game per worker; an ordinary masked seat does not, and chain gates play masked seats this way. A batch changes float rounding in the matrix products, so a rare game differs from its unbatched twin. **D434's +45 was played unbatched, so it stays a descriptive comparison:** nothing here is a paired statement against the search seat.
- **Statistic.** For each arm, the arm minus C against chain 37 and against chain 46, decisive-Elo with 95% seed-cluster intervals, by `paired_contrasts.py` (sha256 `722ece95b24eed07f017062c4a837d44d4a49c4e97a7082fbb6fa2c37cef6002`, 2,000 replicates, generator seed 0).
- **The registered arm's two contrasts carry the label** (Reading 2). **The other two arms' contrasts are a registered descriptive dose-response and carry no label.** Three arms make six intervals; only two are read.
- **Size.** D434's contrasts and D442's gains had half-widths of 18 to 20 Elo at 3,200 games a pair. Four times the games halves that: about plus or minus 9.5.
- **Machines.** Four droplets `s-8vcpu-16gb-amd`, 8 workers, each playing 1,600 seeds of all eight pairs by index slice, so no arm is tied to a machine. About 1.3 hours each; time limit 3 hours.
- **One look**, as D430: runner logs only until every shard is in and the merged run has passed acceptance; no early stop, no extension.
- **Registered diagnostics, not gates:** W / D / L, decisive-Elo and touchdown difference of the eight pairs; the D422 style table with mean log-probability per decision; per arm, the share of seed-legs whose game has C's action trail.

## 5. Acceptance, reading rules, consequences

**Acceptance of a label shard** (`distill_accept.py`), before any of it is used.
- Every file matches SHA256SUMS; the shard's plan copy is this plan; no `FAILED.json`; `COMPLETE.json` names the plan hash, the shard, the checkpoint hash, the harness commit, the tool hashes, the reward manifest, the label settings and the integrity list, with every game natural and no failed rollout.
- The games are exactly the shard's engine seeds, each once, each ended in the engine's match-over status with every hard counter zero, and each trail hashes to its recorded value. Roots and sampled other decisions belong to those games in the counts the games recorded.
- **Every root has min(4, support size) x 16 finite returns, or is a cap rejection with none.** a0 is its first candidate and the action the game played. The seat's rule, recomputed from the stored returns, gives the stored decision, best alternative, gain and standard error exactly. A label is the best alternative of a deviation root and of no other.
- Every deviation root has 2 x 128 judgment returns; a missing return occurs only with a counted cap stop; the kept pairs, the fresh gain and the judged, false and confirmed flags are the recount's.
- At most 1% of a shard's roots are cap rejections. All shards ran on one compiled library.
- The fifteen play-time integrity checks are listed in the plan file and in every `COMPLETE.json`. Any failure stops the worker and the shard writes `FAILED.json`.
- Not checked, as in D425 to D434: the env's own reward telemetry counters, which the shim does not export.

**Acceptance of the dataset** (`distill_dataset.py` refuses to build otherwise): the shards are accepted; every trail replays to its final digest, score and observation hashes; every root's recomputed a0 and candidates are the recorded ones within the stated tolerance; the splits follow the rule; the reserve group is not written.

**Acceptance of an arm's blob** (`distill_eval.py select`): the blob and sidecar hash to what the fine-tune recorded; the blob is the original's size and differs from it only in the decoder's policy rows; the sidecar describes this arm and says it is not eligible ancestry; the harness loads it; its float32 logits agree with the tool's float64 arithmetic to 0.01 on 1,000 stored decisions (logits are near 1,000); every weight is finite.

**Acceptance of the gate** (`gate/accept_from_plan.py`), four checks: `tools/gate_acceptance.py` at `5ab3ab6` (pairs, counts, seed block, both legs once, 32 games per worker, the commit, every player's blob hash, sample mode at temperature 1, natural endings, integrity counters zero); the mask checks (m1 on the three arms' and C's side of every game and on no other, no sampling offset, no truncation, no mask fallback, final status, decision counts, the native kernel); `tools/search_acceptance.py` (seats, modes, no search setting); the sidecar check (section 3). The merge requires one commit, torch, Python and library. Relaunch as D430 fixed it: only a droplet that dies, loses contact or reaches its limit; its shard whole, once, from the same plan; at most two replacements.

**Reading 1, fit** (after milestone 1 and again after milestone 2; printed by `distill_eval.py select`). First match:
1. **Unread:** the shards or the dataset are not accepted, or the lambda 16 arm has no finite fit value (it was not trained, or its blob fails acceptance). The plan stops until a new entry.
2. **NOT FIT:** the fit value is below 0.80. The plan stops. It says R1 could not fit its training labels at this size, and nothing about transfer.
3. **FIT:** otherwise.

**The selection** (after milestone 2, with Reading 1 FIT): the rule of section 3. Its undefined cases: a J that is not finite makes that arm ineligible; a tie goes to the smaller lambda; no eligible arm means no registered arm, no gate, and the plan stops unread.

**Reading 2, the gate** (applied by `gate/score_from_plan.py` to the registered arm's two contrasts and to nothing else). "Entirely above zero" means the interval's lower end is above 0; "entirely below zero" means its upper end is below 0. First match:
1. **Unread:** the merged run is not accepted, or a contrast or an end of its interval is missing or not a finite number.
2. **Negative:** either interval entirely below zero.
3. **Positive:** both point estimates at +15 or more and both intervals entirely above zero. This establishes gains above zero, not above +15. +15 is an engineering preference (a third of the search seat's gain, for nothing at play time), not a statistically established minimum.
4. **Flat:** both intervals inside -15 to +15, ends included. Flat therefore means "within plus or minus 15" only after Negative has been excluded.
5. **Inconclusive:** anything else.

**Consequences.** Each is about R1 at this label count and nothing wider.

| Outcome | What follows |
|---|---|
| Reading 1 Unread, or no eligible arm, or the gate Unread | Nothing is concluded. A new entry decides whether the stage is rerun. |
| Reading 1 NOT FIT | R1 does not fit its training labels at this size. No selection, no held-out look, no gate. The test and reserve games stay unopened for a later entry. |
| Gate Positive | R1 at this label count improves plain-speed play against these two opponents. The next larger design is registered in its own entry (section 9 lists the candidates). The registered arm under m1 may be proposed as a play-time option in its own entry. The held-out numbers are stated beside the result; a Positive gate with labels that did not transfer is reported as a strength result whose mechanism is not shown. |
| Gate Negative | The registered arm is weaker than C. R1 at this label count is closed. The held-out change numbers are the first place to look. |
| Gate Flat or Inconclusive | No improvement is established for R1 at this label count. Nothing is built on it. Whether R2 or more labels is tried next is a new entry that starts from the held-out numbers. This does not show that another recipe, more labels or an online scheme would fail. |
| A dose-response arm's contrasts both entirely above zero while the registered arm's reading is not Positive | Reported, no label. That arm may be carried to a confirmation on a fresh seed block in its own entry; nothing else follows from it. |

Nothing is adopted under any outcome: no training recipe, warm start, play-time default or evaluation default changes.

**Unread until its time.** The test games until `SELECTION.json` is written. The reserve games, for the whole plan. The gate's records until the merged run passes acceptance. Training and validation numbers, and the label shards' counts, are read freely.

## 6. Cost and wall-clock

Rates, and where each comes from.
- **A screened root on a droplet:** 1.84 s of one process with eight busy: (363.8 - 7.5) / 193.5 from D434. On the Mac 0.31 s. **A plain game on a droplet, unbatched:** about 8 s. **A fresh judgment:** 7.4 s. So a label game is about 66 s of one process, about 434 games an hour on a droplet. Not measured on a droplet for this tool.
- **A batched gate game on a droplet:** 5.7 to 7.0 games a second on 8 workers at 32 games per worker, measured on chain 60's gate today (four shards of 9,600 games in 1,375 to 1,695 s; the slowest held the masked pair).
- **Droplet:** `s-8vcpu-16gb-amd`, $0.167 an hour.

| Stage | Work | Droplet-hours | Cost |
|---|---|---|---|
| Milestone 0, the tests and the wide rehearsal | Mac only, done | 0 | $0 |
| Droplet smoke | one droplet, 16 label games; one droplet, a small batched gate | 0.6 | $0.10 |
| Labels, milestone 1 | 1,000 games on two droplets | 2.3 | $0.38 |
| Labels, milestone 2 | 9,000 games on six droplets | 20.7 | $3.46 |
| Dataset, three fine-tunes, selection, held-out numbers | Mac | 0 | $0 |
| Gate | 102,400 batched games on four droplets at about 6 games a second, plus setup | 5.1 | $0.85 |
| **Expected total** | | **about 29** | **about $4.80** |

- **Ceiling:** $12 for everything in the plan, counted from the runners' cost lines: the label stage at eight shards and a 5 hour limit ($6.67), two replacements ($1.67), the gate at four droplets and 3 hours ($2.00), two replacements ($1.00).
- **Wall-clock.** Milestone 1: about 1.3 hours. Milestone 2: about 3.6 hours on six droplets. Dataset on the Mac: about half an hour for 9,000 games (measured: 0.17 s a game). The three fine-tunes: about an hour of one Mac process (estimated from the rehearsals; at this size each step rebuilds its chunk). Selection and held-out numbers: minutes. Gate: about 1.3 hours. About 8 hours of machine time.
- **Droplet slots.** The account allows 15, shared with other projects. No stage needs more than six at once. On a quota or limit refusal nothing is deleted to make room: the launch waits.
- **Exposure** is as D436 wrote it: the time limit is enforced by the local runner, so a dead runner, a lost create or a failed delete can leave a droplet billing. The cleanup commands are written before anything is created.

## 7. Tools and tests

All in `/Users/alexanderhuth/Code/bb-opt-build/docs/search-distill-2026-10-08/`. The label, dataset, fine-tune and evaluation tools import the harness from a `git archive` export of `5ab3ab6` (`export_harness.sh`); the gate's scripts read the harness worktree `/Users/alexanderhuth/Code/bb-harness-search` as every gate's scripts do, because the droplet tool archives the commit from it. No worktree is written to. Each tool refuses a plan that does not hash to the value given and refuses when a tool file is not the one the plan names.

| Tool | What it does |
|---|---|
| `export_harness.sh` | Exports the pinned harness commit and builds its shim in the export |
| `make_plan.py` | Writes `PLAN.json` and its milestone 0, rehearsal, smoke and dev twins |
| `distill_common.py` | The plan loader, the harness loader, the split rule, the replay, the exact joint distribution, the scoring of a weight matrix, J |
| `distill_screen.py` | The label tool: play, sample roots, screen, apply the seat's rule, judge deviation roots, write records |
| `distill_accept.py` | Shard acceptance |
| `distill_dataset.py` | Replay, digests, observation hashes, states, split; the test split is locked and the reserve split is never written |
| `distill_finetune.py` | R1, the three arms, the blob and sidecar writer |
| `distill_eval.py` | `select`: blob acceptance, Reading 1, J, the registered arm, `SELECTION.json`. `heldout`: the reported numbers on the test games |
| `distill_droplet.py`, `test_launcher_flow.py` | The label stage's droplet launcher and its offline flow test. Never run against the network so far |
| `test_distill.py` | The tests below |
| `check_m0_regeneration.py`, `run_chain.sh` | Milestone 0's comparison with the 2026-10-07 screens; a runner for the two Mac-only chains |
| `gate/make_plan.py`, `launch_from_plan.py`, `accept_from_plan.py`, `score_from_plan.py`, `gate_diagnostics.py`, `paired_contrasts.py`, `play_local_from_plan.py` | The gate: plan, droplet launch, four-check acceptance, scoring with the reading, diagnostics; and a one-process local player for rehearsals, which only takes a plan named `distill-mac-...` |

**Tests** (`test_distill.py`; results and command lines in NOTES).
1. **rule:** the acceptance tool's restatement of the seat's rule equals the harness's, float for float.
2. **seat: the label is the seat's.** A real `SearchSeat` plays whole searched games. At every decision it searches, before and after its deviations, the label tool's screen is run on a clone of the seat's own root and must give the seat's candidates, returns and decision exactly: teacher parity on identical roots, which holds after the game has left the plain one. And the tool's own plain game is screened up to the seat's first deviation and must equal the seat's screens there, with the same first deviation: that tests the tool's game loop.
3. **blitz: the longer horizon, directly.** From a kick-off turn root every rollout that stops on a turn end holds a whole opponent team turn and ends with the completed-turn counter one higher; from an ordinary root none does.
4. **loss: the loss is the sampler's.** Joint log-probabilities equal `joint_log_probabilities` to 1e-9 and `select_joint`'s log-probability on every stored decision, the largest support included; the joint KL by enumeration equals the conditional form.
5. **blob:** zero-step identity, changed floats inside the decoder's policy rows only, a second run reproduces the bytes, the harness refuses a blob without a sidecar, the trainer's lineage tool refuses the sidecar.
6. **replay:** every stored trail regenerates its digest, score and observation hashes.
7. **locks:** the training reader refuses the test file; there is no path for the reserve split; the evaluation tool refuses the test split without the selection's hash.
8. **Milestone 0 and the wide rehearsal** (section 8).
9. **The launcher's offline flow test.**
10. **Before Entry A, not yet done: a droplet smoke** of the label tool and of a small batched gate, launched from hashed smoke plans. It is the only test of the droplet path, of its timing and of whether a droplet's observation bytes equal the Mac's.

## 8. Milestone ladder

**Milestone 0: seen data, the Mac, $0. Done; results in NOTES, never evidence.** The label tool regenerated the 200 games of block 29100000 and its 6,000 roots and 87 labels at the registered rollouts; then acceptance, the dataset, the three fits, blobs and sidecars, the selection, the reported numbers, and a Mac tournament of the three arms and C through the gate's merge-free path and all four acceptance checks. The wide rehearsal did the same on 300 fresh games (seeds 29980100 to 29980399) at reduced rollouts.

**Entry A** registers this plan: `PLAN.json` regenerated by `make_plan.py --kind registered` after the last tool edit and hashed, the droplet smoke done, the operator's expectation written.

**Milestone 1: 1,000 label games, about $0.38.** About 290 training labels. The dataset, the three fits and Reading 1 at this size. NOT FIT or Unread: **stop**. The validation numbers are printed and stop nothing. The test split is built and stays locked.

**Milestone 2: 9,000 more label games, about $3.46.** The dataset over all ten shards, the three fits, Reading 1 again, the selection, then the held-out numbers on the test games, once.

**Entry B:** the blob and sidecar hashes of all three arms, the registered arm, `SELECTION.json`'s hash and the gate plan's hash, fixed before any gate game.

**Milestone 3: the gate, about $0.85.** Reading 2 and the consequence table.

**Where the plan stops regardless of the outcome.** Three arms, one test look, one gate. No R2, no second pass, no other checkpoint, no lower delta, no rollout-valued statistic. Each of those is a new entry.

## 9. Postponed, with the objections a later entry must answer

1. **Recipe R2 (the whole policy path).** What it would be: the encoder, the three MinGRU layers and the decoder's policy rows trained on windows of the seat's own observations from a zero state, as the trainer trains, with the value row frozen and a value anchor. Why postponed: it is where the recurrent state and the critic can drift, and version 1 did not specify its training measure. The reviewer: label-centred windows, ten random windows per label, overlapping scored positions and scoring every out-of-scope decision create unequal multiplicities that the reservoir weights do not correct; window placement, early-match history, duplicate weighting, reference states and the value anchor's normalisation must be specified; top-action agreement of 99% between window and full-history policies permits large probability drift, so a total variation or KL bound is needed, especially at deviation roots; a mean value drift can hide large local errors. What exists for it: a measurement that a 64-step window from a zero state reproduces chain 55's top action at 1,233 of 1,233 decisions (two games), a batch timing, and the reserve games.
2. **The captured share** (the share of the seat's one-step evaluator gain an arm captures, net of its other changes, on fresh rollouts). The reviewer: at a deviation root a perfect label follower earns `G(label) - E_p0[G]` in the numerator while the denominator uses `G(label) - G(a0)`; a0 is sampled and the deviation depends on it, so perfect imitation need not score 1. Truncating to eight actions with probability differences of 0.01 or more drops mass, the kept coefficients need not sum to zero, and the result then depends on the a0 baseline. Independent rollouts remove selection optimism and neither defect. The 0.10 and 0.25 bars had no calibration, and a zero or negative denominator was undefined. A later entry must redefine the estimand before using it.
3. **Selection by rollouts on validation games.** Postponed with the captured share. J's price of an unintended change stays an assumption.
4. **The fresh screen of F** (does the search find less on the student's own games).
5. **The linear probes** ("where" and "what"). The preview's numbers are in NOTES.
6. **The learning curve** over label counts.
7. **Version 1's "not included" list:** a placebo arm, S minus F on the gate's seeds, F with the search seat on top, labels from the student's own games, value distillation from the stored returns.

## 10. Limits

- **One recipe, one label count, one teacher setting, one checkpoint.** The seat's scope, delta, 16 rollouts and candidates were chosen on exploratory runs (D425's limits).
- **The teacher's evaluator** is the shaped training reward plus chain 55's value head. Only the gate measures wins.
- **Labels are one-step,** on C's own trajectory. Once an arm deviates it meets states no label covers. The held-out numbers cannot see that; the gate can. This experiment can show that the intervention improves plain-speed play. It cannot show that it reproduces S's trajectory distribution.
- **Self-play labels, held-out opponents.** Chain 37 and chain 46 are older relatives about 190 to 200 Elo weaker than C. Nothing here is about a stronger opponent or a person.
- **The held-out numbers have no threshold** and value nothing: a changed decision at a near-tie costs little and one at a sure decision may cost a lot, and they are counted alike.
- **J is a heuristic** with an assumed price. It only chooses which of three gated arms carries the label.
- **Three arms are gated and one is read.** The dose-response is descriptive; six intervals are printed.
- **The gate is batched,** so its games are not the unbatched games of D430 and D435 on any seed, and the search seat's +45 is a descriptive comparison.
- **An arm is valid under m1 only,** and is not eligible ancestry for training.
- **False and unjudged labels are trained on.** D2 found 0 false of 87 (upper bounds 3.4% counting roots and 4.4% counting games, with the limits D430 lists). The share in this run is reported from the fresh judgments.
- **Acceptance checks declarations, counts, hashes and the rule's arithmetic from stored returns.** That the returns are the seat's rests on the pinned code and on the `seat` test.
- **Not measured:** the droplet rate of the label tool, whether a droplet's observation bytes equal the Mac's, the fine-tune's time at the registered size, and anything about R2.
- **Milestone 0 and the rehearsal are not evidence.** Milestone 0's labels were seen before this plan existed, and both ran on the Mac on a few hundred games.

## OPERATOR: expectation

*(To be written by the operator before Entry A, so that it cannot be adjusted later. Suggested items: Reading 1 at milestones 1 and 2; which arm J registers; the held-out label probability and the held-out change; the registered arm's two contrasts and the gate's reading; the direction of the dose-response.)*
