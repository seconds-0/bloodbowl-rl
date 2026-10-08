# Search distillation, Test 1: plan, version 3, the narrow first slice (2026-10-08)

**Status: the plan Entry A (D444 in `/Users/alexanderhuth/Code/bb-opt-build/DECISIONS.md`) registers. No registered game was played before that entry was committed and pushed. Two droplet smokes were run before it and are never evidence (section 7). Version 1 of this file (commit `1b6122c`) was read by an outside reviewer (`/Users/alexanderhuth/Code/bb-opt-build/.codex-reviews/distill-plan-review.md`); version 2 applied the operator's decisions on that review and built the tools (commit `806fe17`). A second outside review, of the tools (`/Users/alexanderhuth/Code/bb-opt-build/.codex-reviews/distill-tools-review.md`), found the teacher path faithful and ten blocking gaps in acceptance, milestone boundaries, artifact binding and cloud ownership; this version applies the operator's decisions on those (section 0, "Version 3"), and then the three further findings of a review of those fixes (`/Users/alexanderhuth/Code/bb-opt-build/.codex-reviews/distill-fixes-review.md`; section 0, item 10). Milestone 0 and the wide rehearsal were run on the Mac; what they showed is in `/Users/alexanderhuth/Code/bb-opt-build/docs/search-distill-2026-10-08/NOTES.md` and is never evidence. It adopts nothing.**

Short names used below.
- **C**: chain 55 (`f6ba3b449bf0cec15e37ba47b32b097dd513ee7dba3241b16ad90dd2a0675e0b`) played under the m1 mask, sampling at temperature 1.
- **S**: C with the search seat at the setting D430 registered and D434 read (+45.5 and +45.3 decisive-Elo over C against chain 37 and chain 46, at 48 times the cost).
- **F1, F4, F16**: three fine-tuned copies of chain 55, one per lambda (1, 4, 16), each played under m1 at plain speed. Player names `c55d1l1`, `c55d1l4`, `c55d1l16`. **F4 (`c55d1l4`) is the registered arm, by name.**
- **A deviation root**: a decision in the seat's scope where the seat's rule deviates. **The label** there is the action the seat would play.
- **A loss decision**: a screened root that is not a cap rejection, or a sampled out-of-scope decision. Nothing else enters the fine-tune or any reported number.

## 0. What changed from version 1, and why

The review had five blocking findings and recommended a narrower first slice. The operator agreed. In short: one recipe, three arms, the gate decides.

1. **Recipe R1 only** (the policy rows of the output layer). R2 is postponed to a later entry (section 9). The exploratory preview on 87 seen labels suggests R1 may memorise its labels and change other decisions as a side effect. So a failure of this slice says "R1 failed to fit, or to transfer its labels, or to improve matches, at this label count" and nothing wider.
2. **Postponed:** the captured share and its rollouts, the fresh screen of F, the linear probes, the learning curve, selection by rollouts. The reviewer showed the captured share is not calibrated as version 1 defined it. It is not repaired here. Section 9 keeps the objections so a later entry starts from them.
3. **Held-out roots are reported numbers with no thresholds.** The only registered stop before the gate is the fit check.
4. **The gate decides, and it is batched.** 32 games per worker for every arm, as chain gates play masked seats. Because that makes the gate cheap, all three lambda arms are gated against chain 37 and chain 46 with C as the paired control on the same seeds: eight pairs. One arm is the registered arm, named in the plan (lambda 4); its two contrasts carry the label. The other two are a registered descriptive dose-response and carry none.
5. **The loss is named for what it is:** a deviation cross-entropy plus a preservation KL to the original policy. It is not maximum-likelihood cloning of the seat (section 3).
6. **Corrections applied:** the KL is over the joint support's tuples; acceptance requires min(4, support size) x 16 screen returns; a judgment rollout that ends on the inherited decision cap has a registered rule; every reading has its undefined cases defined; every conclusion is restricted to the recipe and label count tested; an arm's sidecar hash is bound and verified beside its blob hash; teacher parity is tested on identical cloned roots after a game's first deviation; the longer horizon at a kick-off Blitz turn root is tested directly.

**Version 3: what the tools review changed.** The review's numbers (B1 to B10) are kept so that the diff can be read against it.

1. **The registered arm is named: lambda 4, `c55d1l4`.** Version 2 let J on the validation games choose it. J cannot do that job. Its first term is at most q times g, reached only if every validation label had probability 1. Measured on the Mac runs, q is about 0.004 and g about 0.08 to 0.09, so that ceiling is 0.0003 to 0.0004, and about 0.001 on any generous reading. Its penalty, 0.016 times the change at other decisions, was 0.0009 to 0.0015 at the changes measured (0.05 to 0.10). So on these runs J is negative for every arm and picks the smallest dose, and at sizes like these it would go on doing so, on a price that was never measured where it is applied. J is still printed for every arm on validation games. It decides nothing.
2. **`select` writes the selection file only when all three arms' blobs pass acceptance and Reading 1 is FIT.** If any arm's blob fails acceptance the plan stops unread at the selection and no gate is played. Blob acceptance is decided before anything is scored and apart from everything else; Reading 1 is Unread when the fit arm's blob fails it (B6).
3. **Milestone 1 uses a new command, `fit`,** which gives Reading 1 and the validation numbers and writes no selection file. `select` refuses a dataset that does not hold every shard of the plan and one whose files are not the ones the fine-tune recorded. `heldout` requires a registered arm whose blob passed, the dataset files the selection recorded, and every arm's sidecar hash as well as its blob hash. The reader refuses a split by the path the dataset's record gives, before it deserialises anything (B4).
4. **Shard acceptance** now refuses a judgment cell that is NaN or infinity, a null cell without a counted cap stop, and stop counts that are incomplete, negative or do not sum (B1); a sampled other decision that repeats, sits on a root's step, or carries another seed, seat or weight than its game's (B2); candidates that are not distinct tuples of the recorded support (B3); and a shard that names no engine library hash. **The dataset tool rebuilds the masked support and the class at every root on replay** and requires them to equal the record's before anything else (B3).
5. **The step is the declared loss's:** each chunk's numerator is divided by (the training set's weight / the number of chunks) (B5).
6. **Every reported number is computed from float32 logits as the harness computes them at play.** Training stays float64.
7. **The gate's scorer** refuses unless the harness worktree is clean at the plan's commit, before it imports or runs anything from it (B8; a refusal, not a reading); checks every shard's own manifest before the merge (B7); and leaves `reading.json` saying Unread whenever the run's own records are rejected. Section 3 now says exactly what is bound where, because the harness at this commit does not record a sidecar's hash at play.
8. **The label launcher** deletes a leftover ssh key only when it holds the public key this run generated, reads listings page by page, prints cleanup commands for recorded droplet ids only (B9), refuses `--keep` except for the smoke and dev plans (B10), and requires the shards to be named for the registered plan.
9. **No placebo arm in this slice.** A Positive result's mechanism would need a label-shuffled arm in a later entry (section 10).
10. **After the review of those fixes** (three blocking findings, all applied by the operator):
    - `select` and `heldout` decide "the whole plan" from the games the hash-bound files themselves hold (exactly the plan's games of each split), not from the shard names in `DATASET.json`, which can be edited without changing a file hash. `select` also requires the fine-tune to have recorded every shard.
    - The scorer requires an entry for every registered checkpoint player in every shard's manifest. A manifest that left one out would otherwise have that player supplied by another shard in the merge.
    - `gate/make_plan.py` refuses any harness commit but `5ab3ab6`.
    - The operator's own change: a shard manifest that does not exist yet (a shard not played or fetched, or a relaunched shard's directory not named) is a refusal, not Unread. Nothing of the run has been read at that point.
    - The droplet rates in section 6 are the label smoke's measurements, and milestone 2's time limit is 7 hours.

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

**What a gate that is not Positive would mean.** No improvement is established for the registered arm, lambda 4, at this label count. Negative says that arm is weaker than C. Flat and Inconclusive say less: they do not show that R1 failed, and the other two doses are descriptive. The fit check and the held-out numbers say whether the labels were fitted and whether they transferred.

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

**Recurrent state.** Not stored, recomputed. Each game stores its engine seed, both sampling seeds and its full action trail. The dataset tool replays the trail through a fresh engine and requires the final digest, the score and the sha256 of both observation rows to equal the game record's. It then runs chain 55 over seat A's row from the first step of the match, which is how the seat came by its state. **At every root the masked support and the decision class are rebuilt from the replayed engine and must equal the record's** (a recorded support is never trusted: an omitted legal action would change both the candidates and the loss). Then the recomputed a0 and candidates must be the recorded ones and a0's log-probability must agree to 1e-3. Two candidates that are within that tolerance of each other may change places on another machine; that is counted, and anything else is an error. For R1 the state at a root does not depend on the trained weights at all.

**What is stored**, per shard, under the git-ignored `/Users/alexanderhuth/Code/bb-opt-build/runs/search-distill-2026-10-08/<run>/<shard>/`: `games.jsonl` (seeds, rosters, the action trail and its hash, both observation hashes, the final digest, counts, the integrity counters), `roots.jsonl` (the root, its masked support, candidates, 16-rollout returns at full precision, the rule's result, the label, the judgment's returns), `other.jsonl` (the sampled out-of-scope decisions), `COMPLETE.json`, `plan.json`, `SHA256SUMS`.

**Size.** 10,000 games, 300,000 roots, about 4,000 to 4,400 labels (1.34% in D434, 1.46% [1.16, 1.78] in the screens).

**Split, by game.** With `i = engine seed - 26000000`, the group is `(i // 2) % 10`: 0 to 6 train (7,000 games, about 2,900 labels), 7 validation (1,000 games, about 420), 8 test (1,000, about 420), 9 reserve (1,000, about 420). The dataset tool has no option that writes the reserve group, so a later entry has games no model was fitted or chosen on. **What is and is not allowed before their time.** The test and reserve games are generated by the label tool and integrity-checked by shard acceptance like every other game: their records are read for that. What is forbidden is fitting on them, selecting on them, and any look at their labels' numbers: the dataset tool computes no feature and counts no label of a reserve game, and the test split's file is opened only by the `heldout` step.

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
- **A step uses one chunk.** The training set is cut once into fixed chunks. A step's loss is its chunk's numerator (the two sums above, over the chunk) divided by (the whole training set's weight / the number of chunks). Chunks are visited equally often, so the expected step is the gradient of L over the whole training set, whatever the chunks' own weights are. Dividing each chunk by its own weight, as version 2's code did, is another objective when chunk weights differ.
- **A caution about the KL term.** Chain 55 is saturated at about 70% of decisions, so the term has almost no gradient until the fine-tuned policy has already moved mass, and it only stands where there is a training example. The preview showed what that can cost (NOTES). This is why change at other decisions is reported on held-out games.

**Three arms, one per lambda: 1, 4, 16.** Each takes 2,400 Adam steps at learning rate 0.001 over fixed chunks of at most 8,192 training decisions (the chunks are a seeded partition, visited in a seeded order; at the registered size that is about 30 passes). Arithmetic in float64 on the stored float32 features; the blob is float32. **There is no stop rule:** an arm is its last step. Generator seed 0, one thread. A second run reproduces the blob byte for byte on the same machine (tested).

**The fit check (Reading 1).** The lambda 16 arm's weighted mean probability of the label on training deviation roots, recomputed from its blob with float32 logits as the harness computes them (the value in the float64 training arithmetic is printed beside it once and decides nothing). **FIT** is 0.80 or more. NOT FIT stops the plan. The reading is Unread when that arm's blob fails acceptance.

**The registered arm is named: lambda 4, `c55d1l4`.** It is written in the plan file (`finetune.registered_arm`). No rule chooses it.
- Why not J. Version 2 chose the arm with the highest `J = q * M * g - 0.016 * U` on the validation games (M: mean probability of the label at validation deviation roots; U: mean total variation at the other validation loss decisions; q: share of deviation roots among loss decisions; g: mean fresh gain of the judged validation labels; 0.016: the study's mean cost of an alternative the policy all but rules out). J's first term can be at most q times g (0.0003 to 0.0004 on the Mac runs, about 0.001 at most), and its penalty at the changes measured is 0.0009 to 0.0015. At sizes like these it picks the smallest dose whatever the arms do, on a price that was measured at in-scope decisions only and is applied everywhere. That is a weak reason to let one arm stand for the experiment.
- Why lambda 4. It is the middle dose. Nothing claims it is the best one. The other two doses are gated beside it and stay descriptive; a dose that looks better needs its own confirmation on fresh seeds.
- **J is still printed** for every arm on the validation games, as a diagnostic. It decides nothing.

**The selection file.** `distill_eval.py select` writes `SELECTION.json` only when the dataset holds every shard of the plan (by the shard names the dataset and the fine-tune recorded, and by the games its training and validation files hold: exactly the plan's games of each split), its files are the ones the fine-tune recorded, **all three arms' blobs pass acceptance** (section 5) and Reading 1 is FIT. The file names the registered arm (the plan's) and binds the blob hash and the sidecar hash of every arm and the hashes of the dataset's files. Its sha256 is what opens the test games. **If any arm's blob fails acceptance, the plan stops unread at the selection: no file, no held-out look, no gate.**

**Writing an arm back as a blob** (checked: NOTES, and section 7's test `blob`).
- `training/convert_checkpoint.py` `cuda_to_torch` then `torch_to_cuda` on chain 55's blob is byte-identical. Zero training steps write chain 55's blob back byte for byte. A trained arm differs from it only in floats 1,424,384 to 1,656,831; the value row (1,656,832 to 1,657,343) is untouched.
- `play_harness.policy.load_checkpoint` requires 16,066,560 bytes and a `.lineage.json` sidecar whose `compatibility` block is chain 55's and whose `checkpoint.sha256` is the blob's. Without a sidecar it refuses.
- **The sidecar an arm carries:** `schema_version` 1; `checkpoint` (bytes, sha256); `compatibility` (six fields); `ancestry` with `initialization: "offline-distill"`, `eligible: false`, `qualification_only: true`, the parent's blob and sidecar hashes and `valid_under_masks: ["m1"]`; `producer` with the plan hash, the recipe, the arm, lambda, the settings, the training file's hash, the tool hashes and the torch version. No `implementation` block: no trainer build produced it.
- **What is bound where, exactly.** The harness at this commit records a checkpoint's blob hash at play, and the `producer` and `compatibility` blocks of its sidecar; it does not record the sidecar's own hash. So:
  - the **blob hash** is bound per game: every game record's manifest entry is checked by the stock acceptance tool;
  - the **sidecar's full hash** is checked on the local files three times: when the gate's plan is written, at the launcher's preflight, and at acceptance;
  - **what a droplet played** is bound by the blob hash and by the `producer` and `compatibility` blocks its manifest recorded, **shard by shard, before the merge** (the merge keeps the first shard's entry and compares the others by blob hash only, so a later shard's other sidecar would vanish in it);
  - a sidecar that differed from the registered one only outside those two blocks, on a droplet, would not be seen. The launcher uploads the local file it has just hashed.
- **An arm is not a warm start.** The trainer's `/Users/alexanderhuth/Code/bb-opt-build/tools/checkpoint_lineage.py` refuses the sidecar ("implementation must be an object"). That is intended and tested.
- Arms are kept under `/Users/alexanderhuth/Code/bb-opt-build/runs/search-distill-2026-10-08/<run>/finetune/checkpoints/<arm>/`, outside the harness's checkpoint store.

## 4. What is measured

**(i) Fit on training roots: a registered check.** Reading 1 above, from float32 logits. Also printed per arm: training label probability (mean, and the share at 0.5 or more) and the change at the other training loss decisions (total variation, share of changed top actions).

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
- **The registered arm's (lambda 4, `c55d1l4`) two contrasts carry the label** (Reading 2). **The other two arms' contrasts are a registered descriptive dose-response and carry no label.** Three arms make six intervals; only two are read.
- **Size.** D434's contrasts and D442's gains had half-widths of 18 to 20 Elo at 3,200 games a pair. Four times the games halves that: about plus or minus 9.5.
- **Machines.** Four droplets `s-8vcpu-16gb-amd`, 8 workers, each playing 1,600 seeds of all eight pairs by index slice, so no arm is tied to a machine. About 2.0 hours each at the gate smoke's rate; time limit 3 hours.
- **One look**, as D430: runner logs only until every shard is in and the merged run has passed acceptance; no early stop, no extension.
- **Registered diagnostics, not gates:** W / D / L, decisive-Elo and touchdown difference of the eight pairs; the D422 style table with mean log-probability per decision; per arm, the share of seed-legs whose game has C's action trail.

## 5. Acceptance, reading rules, consequences

**Acceptance of a label shard** (`distill_accept.py`), before any of it is used.
- Every file matches SHA256SUMS; the shard's plan copy is this plan; no `FAILED.json`; `COMPLETE.json` names the plan hash, the shard, the checkpoint hash, the harness commit, the tool hashes, the reward manifest, the label settings and the integrity list, with every game natural and no failed rollout.
- The games are exactly the shard's engine seeds, each once, each ended in the engine's match-over status with every hard counter zero, and each trail hashes to its recorded value. Roots and sampled other decisions belong to those games in the counts the games recorded.
- **No engine step of a game holds two records** (a root and a sampled other decision, or one of them twice), and every sampled other decision carries its game's engine seed, seat, searchable count and kept count: the last two are its weight.
- **Every root has min(4, support size) x 16 finite returns, or is a cap rejection with none.** Its candidates are distinct tuples of its recorded support; a0 is the first and the action the game played. Its stop counts name every kind of stop, are non-negative and sum to the rollouts run. The seat's rule, recomputed from the stored returns, gives the stored decision, best alternative, gain and standard error exactly. A label is the best alternative of a deviation root and of no other.
- Every deviation root has 2 x 128 judgment returns. **Each cell is a finite float or an explicit null; NaN and infinity are refused.** The judgment's stop counts are complete, non-negative and sum to 256. A null cell occurs only where a cap stop is counted, one for one. The kept pairs, the fresh gain and the judged, false and confirmed flags are the recount's.
- At most 1% of a shard's roots are cap rejections. Every shard names the sha256 of the engine library it ran on, and all shards name the same one.
- That a root's recorded support is the engine's is not something records can show; the dataset tool checks it on replay.
- The fifteen play-time integrity checks are listed in the plan file and in every `COMPLETE.json`. Any failure stops the worker and the shard writes `FAILED.json`.
- Not checked, as in D425 to D434: the env's own reward telemetry counters, which the shim does not export.

**Acceptance of the dataset** (`distill_dataset.py` refuses to build otherwise): the shards are accepted; every trail replays to its final digest, score and observation hashes; every root's masked support and class, rebuilt from the replayed engine, equal the record's; every root's recomputed a0 and candidates are the recorded ones within the stated tolerance; the splits follow the rule; the reserve group is not written and its labels are not counted. `DATASET.json` records which shards the dataset holds.

**Acceptance of an arm's blob** (`distill_eval.py fit` and `select`; decided first and apart from everything else): the blob and sidecar hash to what the fine-tune recorded; the blob is the original's size and differs from it only in the decoder's policy rows; the sidecar describes this arm and says it is not eligible ancestry; the harness loads it; the float32 logits the tool scores with are the harness decoder's own on the same features, and agree with the float64 training arithmetic to 0.01 (logits are near 1,000); every weight is finite. An arm whose blob fails is not scored at all.

**Acceptance of the gate.** Before anything of the harness is imported or run, `gate/score_from_plan.py` refuses, with no reading, unless the harness worktree is clean at the plan's commit (the merge, the acceptance tools, the statistics and the contrasts all run its code, so a file changed after play would change the reading). Then it refuses, again with no reading, if a shard's manifest file does not exist: the run is not complete. Then it checks every shard's own manifest: it has an entry for every registered checkpoint player and for no other, each entry has the registered blob hash, and its producer and compatibility blocks are the registered sidecar's. Then the merge, then `gate/accept_from_plan.py`, four checks: `tools/gate_acceptance.py` at `5ab3ab6` (pairs, counts, seed block, both legs once, 32 games per worker, the commit, every player's blob hash, sample mode at temperature 1, natural endings, integrity counters zero); the mask checks (m1 on the three arms' and C's side of every game and on no other, no sampling offset, no truncation, no mask fallback, final status, decision counts, the native kernel); `tools/search_acceptance.py` (seats, modes, no search setting); the sidecar check (section 3). The merge requires one commit, torch, Python and library. Relaunch as D430 fixed it: only a droplet that dies, loses contact or reaches its limit; its shard whole, once, from the same plan; at most two replacements.

**Reading 1, fit** (after milestone 1 by `distill_eval.py fit`, after milestone 2 by `distill_eval.py select`). First match:
1. **Unread:** the shards or the dataset are not accepted (the tools then stop before any reading is written, and the operator records Unread), or the lambda 16 arm was not trained, or its blob fails acceptance, or its fit value is not a finite number (`fit` and `select` then print Unread). The plan stops until a new entry.
2. **NOT FIT:** the fit value is below 0.80. The plan stops. It says R1 could not fit its training labels at this size, and nothing about transfer.
3. **FIT:** otherwise.

**The selection** (after milestone 2). `select` refuses, writing nothing, when the dataset does not hold all eight shards (by name and by the games its files hold) or its files are not the ones the fine-tune recorded. Otherwise, first match:
1. **The plan stops unread at the selection:** some arm's blob fails acceptance (this includes an arm that was not trained). No selection file, no held-out look, no gate.
2. **The plan stops:** Reading 1 is Unread or NOT FIT. No selection file.
3. **Selected:** `SELECTION.json` is written, with `c55d1l4` as the registered arm.

**Reading 2, the gate** (applied by `gate/score_from_plan.py` to the registered arm's two contrasts and to nothing else). "Entirely above zero" means the interval's lower end is above 0; "entirely below zero" means its upper end is below 0. First match:
1. **Unread:** a shard's manifest that exists does not hold the registered checkpoints (a player missing, a stranger, another blob hash, another producer or compatibility block), the merge fails, the merged run is not accepted, or a contrast file is missing or its point or the two ends of its interval are not finite numbers. On a rejection the script writes `reading.json` with Unread and the reason and exits non-zero. A gate whose shards cannot all be completed within the relaunch rule is Unread too, recorded by the operator.
2. **Negative:** either interval entirely below zero.
3. **Positive:** both point estimates at +15 or more and both intervals entirely above zero. This establishes gains above zero, not above +15. +15 is an engineering preference (a third of the search seat's gain, for nothing at play time), not a statistically established minimum.
4. **Flat:** both intervals inside -15 to +15, ends included. Flat therefore means "within plus or minus 15" only after Negative has been excluded.
5. **Inconclusive:** anything else.

**A refusal is not a reading.** When the scorer's own scripts or the harness worktree are not the registered ones (a file changed, an untracked file, another commit), or a shard's manifest file does not exist yet, it stops before any record of the run (a manifest, a game, a report) is read, merged or scored, and writes no reading. That is a fact about the scoring machine or about a run that is not complete, not about the games. The worktree is restored to the plan's commit, or the missing shard is completed under the relaunch rule, and the scorer is run again; this is not a second look, because nothing was looked at. The check is made when the scorer starts; it is not a lock on the shared worktree while the scorer runs.

**A failure after the look is not a refusal.** Once the scorer has printed the four acceptance lines the look has happened, whatever happens next. If a later step of the scorer fails (the report, a contrast, the diagnostics), the scorer is run again from the same plan on the same merged run, with the same hash-bound scripts; it is deterministic (fixed bootstrap seed), and the reading it then writes is the reading. The failure and its cause are reported with the result. If it cannot be completed without changing a hash-bound script, the gate is Unread, and every number that was printed is reported as seen. The first `reading.json` that holds a reading stands: a later invocation does not replace it.

**Relaunching a label shard.** Only when its droplet dies, loses contact or reaches its time limit, or its launch is refused: the shard whole, from the same plan and the same seeds (the label tool is deterministic in its seeds, so a relaunch makes the same games), at most two replacements over the whole label stage. A shard that completes and whose records acceptance rejects is not relaunched: Reading 1 is Unread. A label stage that cannot be completed within two replacements stops the plan until a new entry.

**Consequences.** Each is about R1 at this label count and nothing wider.

| Outcome | What follows |
|---|---|
| Reading 1 Unread, or an arm's blob fails acceptance at the selection, or the gate Unread | Nothing is concluded. A new entry decides whether the stage is rerun. |
| Reading 1 NOT FIT | R1 does not fit its training labels at this size. No selection, no held-out look, no gate. The test and reserve games stay unopened for a later entry. |
| Gate Positive | The registered arm (R1 at lambda 4, at this label count) improves plain-speed play against these two opponents. The next larger design is registered in its own entry (section 9 lists the candidates). The registered arm under m1 may be proposed as a play-time option in its own entry. The held-out numbers are stated beside the result; a Positive gate with labels that did not transfer is reported as a strength result whose mechanism is not shown. |
| Gate Negative | The registered arm is weaker than C. R1 at this label count is closed. The held-out change numbers are the first place to look. |
| Gate Flat or Inconclusive | No improvement is established for the registered arm at this label count. Nothing is built on it. Whether R2 or more labels is tried next is a new entry that starts from the held-out numbers. This does not show that another recipe, more labels or an online scheme would fail. |
| A dose-response arm's contrasts both entirely above zero while the registered arm's reading is not Positive | Reported, no label. That arm may be carried to a confirmation on a fresh seed block in its own entry; nothing else follows from it. |

Nothing is adopted under any outcome: no training recipe, warm start, play-time default or evaluation default changes.

**Not looked at before its time.** The test games' labels and numbers until `SELECTION.json` is written. The reserve games' labels and numbers, for the whole plan. Both groups' games are generated and integrity-checked with the rest (section 2); what is forbidden is fitting, selection and any look at their labels' numbers. The gate's records until the merged run passes acceptance. Training and validation numbers, and the label shards' counts, are read freely.

## 6. Cost and wall-clock

Rates, and where each comes from.
- **A label game on a droplet: about 87 s of one process**, measured on the label smoke (16 games on 8 processes: 88.5 s a game, of which 18.0 s is play, at 30 screened roots and 0.625 judgments a game). That gives a screened root 2.17 s and a fresh judgment 8.7 s, and at the expected 0.42 judgments a game 86.8 s: about 330 games an hour on a droplet. Version 2 estimated 66 s from D434's rates; the smoke replaced it. Sixteen games is a small sample; milestone 1 measures it on 1,000.
- **A batched gate game on a droplet:** 3.7 games a second on 8 workers at 32 games per worker, measured on the gate smoke (two shards of 2,048 games of these eight pairs, 3.69 and 3.75). Chain 60's gate ran at 5.7 to 7.0 with one masked pair in four; here all eight pairs have a masked side, and a short run pays its start-up on fewer games.
- **Droplet:** `s-8vcpu-16gb-amd`, $0.167 an hour.

| Stage | Work | Droplet-hours | Cost |
|---|---|---|---|
| Milestone 0, the tests and the wide rehearsal | Mac only, done | 0 | $0 |
| Droplet smokes, done | one droplet, 16 label games ($0.02); two droplets, a small batched gate ($0.08) | 0.6 | $0.10 |
| Labels, milestone 1 | 1,000 games on two droplets | 3.2 | $0.53 |
| Labels, milestone 2 | 9,000 games on six droplets | 27.5 | $4.59 |
| Dataset, three fine-tunes, selection, held-out numbers | Mac | 0 | $0 |
| Gate | 102,400 batched games on four droplets at about 3.7 games a second, plus setup | 8.0 | $1.33 |
| **Expected total** | | **about 39** | **about $6.55** |

- **Allocation: $14 for everything in the plan.** It is the operator's allocation, not a limit any tool enforces across the plan. Its parts, each at its time limit: milestone 1 at two shards and 5 hours ($1.67), milestone 2 at six shards and 7 hours ($7.00), two replacement label shards ($2.33), the gate at four droplets and 3 hours ($2.00), two replacements ($1.00). Each invocation of the label launcher enforces its own dollar guard (shards x `--max-hours` x the hourly price must not exceed `--max-total-usd`, or nothing is created); the sum across invocations, and the count of replacements, are kept by the operator from the runners' cost lines.
- **Wall-clock.** Milestone 1: about 1.6 hours. Milestone 2: about 4.6 hours on six droplets (time limit 7 hours). Dataset on the Mac: about half an hour for 9,000 games (measured: 0.17 s a game). The three fine-tunes: about an hour of one Mac process (estimated from the rehearsals; at this size each step rebuilds its chunk). Selection and held-out numbers: minutes. Gate: about 2.0 hours. About 10 hours of machine time.
- **Droplet slots.** The account allows 15, shared with other projects. No stage needs more than six at once. On a quota or limit refusal the launch exits and is retried later. Nothing is deleted to make room.
- **Exposure** is as D436 wrote it: the time limit is enforced by the local runner, so a dead runner, a lost create or a failed delete can leave a droplet billing. The cleanup commands are written before anything is created.
- **Ownership, stated exactly.** The label launcher deletes a leftover ssh key only when it holds the public key (or fingerprint) this run generated locally; a key of the run's name with another public key is reported and left alone; the launcher's own listings are read page by page (the inherited lifecycle's lost-create adoption reads the first 200 tagged droplets only). The droplet side is the inherited lifecycle of `tools/droplet_tournament.py`, unchanged: it destroys the droplet id it recorded when the create was answered, and after a create whose answer was lost it adopts a droplet by the shared tag, the exact name (which carries this run's random six-digit id) and a creation time after the attempt. That is very unlikely, not impossible, to be another process's droplet. The printed fallback commands act only on droplet ids this run recorded in its own state directory; where none was recorded they say to look and decide by hand. `--keep`, which leaves a droplet billing, is refused except for the smoke and dev plans.

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
| `distill_eval.py` | `fit`: blob acceptance, Reading 1 and the validation numbers, no selection file (milestone 1). `select`: the same on the whole dataset, then `SELECTION.json`. `heldout`: the reported numbers on the test games |
| `distill_droplet.py`, `test_launcher_flow.py` | The label stage's droplet launcher and its offline flow test. Run against the network once, by the label smoke (item 10 below) |
| `test_distill.py` | The tests below |
| `check_m0_regeneration.py`, `run_chain.sh` | Milestone 0's comparison with the 2026-10-07 screens; a runner for the two Mac-only chains |
| `gate/make_plan.py`, `launch_from_plan.py`, `accept_from_plan.py`, `score_from_plan.py`, `gate_diagnostics.py`, `paired_contrasts.py`, `play_local_from_plan.py` | The gate: plan, droplet launch, four-check acceptance, scoring with the reading, diagnostics; and a one-process local player for rehearsals, which only takes a plan named `distill-mac-...` |

**Tests** (`test_distill.py`; results and command lines in NOTES).
1. **rule:** the acceptance tool's restatement of the seat's rule equals the harness's, float for float.
2. **seat: the label is the seat's.** A real `SearchSeat` plays whole searched games. At every decision it searches, before and after its deviations, the label tool's screen is run on a clone of the seat's own root and must give the seat's candidates, returns and decision exactly: teacher parity on identical roots, which holds after the game has left the plain one. And the tool's own plain game is screened up to the seat's first deviation and must equal the seat's screens there, with the same first deviation: that tests the tool's game loop.
3. **blitz: the longer horizon, directly.** From a kick-off turn root every rollout that stops on a turn end holds a whole opponent team turn and ends with the completed-turn counter one higher; from an ordinary root none does.
4. **loss: the loss is the sampler's.** Joint log-probabilities equal `joint_log_probabilities` to 1e-9 on every stored decision, the largest support included, and `select_joint`'s log-probability to 2e-3 on every fourth; the joint KL by enumeration equals the conditional form.
5. **blob:** zero-step identity, changed floats inside the decoder's policy rows only, a second run reproduces the bytes, the harness refuses a blob without a sidecar, the trainer's lineage tool refuses the sidecar.
6. **replay:** every stored trail regenerates its digest, score and observation hashes.
7. **locks:** the reader refuses the test split, the reserve split and a record that names the locked file as another split, each before anything is deserialised; there is no path for the reserve split; the evaluation tool refuses the test split without the selection's hash. The test never loads the test file.
7a. **accept, milestone, fitblob, gate:** one test per fix of the tools review, each on a copy of a record or file corrupted for the check under test (B1, B2, B3, B4, B6, B7, B8; B5 is in `loss`; B9 and B10 are in the launcher's flow test). After the review of the fixes: a one-shard dataset relabelled as every shard is refused by the games its files hold; a blob changed in the value row with every recorded hash brought up to date is refused by the span check alone; a manifest without an entry for a registered player is refused; the scorer refuses, with no reading, a run whose manifest does not exist.
8. **Milestone 0 and the wide rehearsal** (section 8).
9. **The launcher's offline flow test.**
10. **The droplet smokes, done before Entry A on 2026-10-08, never evidence.**
    - **Label smoke** (`results/smoke-label/`): 16 games (seeds 29980400 to 29980415) on one droplet from the hashed smoke plan `3f058485...`, whose launcher, lifecycle and every tool file but `distill_eval.py` are the registered plan's (`distill_eval.py` is uploaded with the others and no droplet runs it; the smoke uploaded its round 3 version). Accepted: 480 roots, 10 deviation roots (1 false, 9 confirmed), 0 cap rejections. 88.5 s a game of one process. Droplet destroyed and verified gone, key gone, $0.019. **The droplet's games replayed on the Mac to the same digests and observation hashes;** all 480 root supports were rebuilt equal and the largest a0 log-probability difference was 1.2e-4.
    - **Gate smoke** (`results/smoke-gate/`): the final gate scripts from a hashed plan (`6cd29a23...`, gate `distill-smoke-20261008`, seeds 29980900 to 29981155), two droplets, 512 games a pair with the wide rehearsal's arms. Both shards' manifests checked, the merge of two shards, all four acceptance lines, scored. 3.7 games a second. Both droplets destroyed and verified gone, $0.076.
    - **What the smokes do not test:** fine-tuning at the registered size, the evaluation tool on a dataset of droplet shards beyond the 16-game replay, a kick-off turn root made on a droplet (the 16 games had none), and any failure, time-limit or relaunch path on a real droplet.
    - **What the gate smoke's numbers were, for the record:** the rehearsal's arms (fitted on 210 training games at reduced rollouts and half the steps) against C at 256 seeds a pair: lambda 1 -28 and -20, lambda 4 -42 and -44, lambda 16 -62 and -51, lambda 16's two intervals entirely below zero. They are not the registered arms. The operator's expectation below was written before this smoke was scored and was not changed after it.

## 8. Milestone ladder

**Milestone 0: seen data, the Mac, $0. Done; results in NOTES, never evidence.** The label tool regenerated the 200 games of block 29100000 and its 6,000 roots and 87 labels at the registered rollouts; then acceptance, the dataset, the three fits, blobs and sidecars, the selection, the reported numbers, and a Mac tournament of the three arms and C through the gate's merge-free path and all four acceptance checks. The wide rehearsal did the same on 300 fresh games (seeds 29980100 to 29980399) at reduced rollouts.

**Entry A** registers this plan: `PLAN.json` regenerated by `make_plan.py --kind registered` after the last tool edit and hashed, the droplet smokes done, the operator's expectation written.

The stage commands, literally. `D` is this directory, `X` the harness export, `H` the registered sha256 of `PLAN.json`, `CK` chain 55's blob, `R` the run directory `/Users/alexanderhuth/Code/bb-opt-build/runs/search-distill-2026-10-08/sd1`. The launcher refuses the registered plan unless the shards are named.

**Milestone 1: 1,000 label games, about $0.53.** Two shards, about 290 training labels.

```
python $D/distill_droplet.py run --name sd1 --plan $D/PLAN.json --expect-sha256 $H \
    --harness-export $X --max-hours 5 --max-total-usd 1.70 --shard m1-s1 --shard m1-s2
python $D/distill_dataset.py --harness $X --plan $D/PLAN.json --expect-sha256 $H --checkpoint $CK \
    --shard-dir m1-s1=$R/m1-s1 --shard-dir m1-s2=$R/m1-s2 --out-dir $R/dataset-m1
python $D/distill_finetune.py --harness $X --plan $D/PLAN.json --expect-sha256 $H --checkpoint $CK \
    --dataset $R/dataset-m1 --out-dir $R/finetune-m1
python $D/distill_eval.py fit --harness $X --plan $D/PLAN.json --expect-sha256 $H --checkpoint $CK \
    --dataset $R/dataset-m1 --finetune $R/finetune-m1
```

Reading 1 at this size, from `fit`. NOT FIT or Unread: **stop**. The validation numbers are printed and stop nothing. `fit` writes no selection file, `select` refuses this dataset (two shards of eight), and `heldout` finds no selection: the test split cannot be opened at milestone 1.

**Milestone 2: 9,000 more label games, about $4.59.** Six shards of 1,500 games, about 4.6 hours each at the measured rate, time limit 7 hours. **The rate stop, as a formula.** T is the mean of `wall_seconds` in the `COMPLETE.json` of the two accepted milestone 1 shards (each is 500 games on 8 processes; a replaced shard counts by its accepted run only). The projection for a milestone 2 shard is (3 x T + 240) / 3600 hours. If it is above 6.0, milestone 2 is not launched as written and a new entry says what replaces it. Nothing else about milestone 1's timing enters.

```
python $D/distill_droplet.py run --name sd1 --plan $D/PLAN.json --expect-sha256 $H \
    --harness-export $X --max-hours 7 --max-total-usd 7.10 \
    --shard m2-s1 --shard m2-s2 --shard m2-s3 --shard m2-s4 --shard m2-s5 --shard m2-s6
python $D/distill_dataset.py --harness $X --plan $D/PLAN.json --expect-sha256 $H --checkpoint $CK \
    --shard-dir m1-s1=$R/m1-s1 --shard-dir m1-s2=$R/m1-s2 --shard-dir m2-s1=$R/m2-s1 \
    --shard-dir m2-s2=$R/m2-s2 --shard-dir m2-s3=$R/m2-s3 --shard-dir m2-s4=$R/m2-s4 \
    --shard-dir m2-s5=$R/m2-s5 --shard-dir m2-s6=$R/m2-s6 --out-dir $R/dataset
python $D/distill_finetune.py --harness $X --plan $D/PLAN.json --expect-sha256 $H --checkpoint $CK \
    --dataset $R/dataset --out-dir $R/finetune
python $D/distill_eval.py select --harness $X --plan $D/PLAN.json --expect-sha256 $H --checkpoint $CK \
    --dataset $R/dataset --finetune $R/finetune
python $D/distill_eval.py heldout --harness $X --plan $D/PLAN.json --expect-sha256 $H --checkpoint $CK \
    --dataset $R/dataset --finetune $R/finetune --expect-selection-sha256 <sha256 of SELECTION.json>
```

The dataset over all eight shards, the three fits, Reading 1 again and the selection file (`select`), then the held-out numbers on the test games, for one selection only (`heldout` leaves a marker and refuses any other selection; a repeat with the same selection hash recomputes the same numbers). If the six droplets are not free at once, the launcher is run again with the remaining shard names under the same `--name`.

**Entry B:** the blob and sidecar hashes of all three arms, the registered arm `c55d1l4`, `SELECTION.json`'s hash and the gate plan's hash, fixed before any gate game.

```
python $D/gate/make_plan.py --out-dir <gate directory> --gate <gate name> --registered-in "<Entry B>" \
    --seed0 25200000 --games-per-pair 12800 --shards 4 --max-hours 3 \
    --finetune $R/finetune --expect-selection-sha256 <sha256 of SELECTION.json>
```

**Milestone 3: the gate, about $1.33.** `launch_from_plan.py`, then `score_from_plan.py`, from the gate directory with the gate plan's hash. Reading 2 and the consequence table.

**Where the plan stops regardless of the outcome.** Three arms, one of them registered by name, one test look, one gate. No R2, no second pass, no other checkpoint, no lower delta, no rollout-valued statistic. Each of those is a new entry.

## 9. Postponed, with the objections a later entry must answer

1. **Recipe R2 (the whole policy path).** What it would be: the encoder, the three MinGRU layers and the decoder's policy rows trained on windows of the seat's own observations from a zero state, as the trainer trains, with the value row frozen and a value anchor. Why postponed: it is where the recurrent state and the critic can drift, and version 1 did not specify its training measure. The reviewer: label-centred windows, ten random windows per label, overlapping scored positions and scoring every out-of-scope decision create unequal multiplicities that the reservoir weights do not correct; window placement, early-match history, duplicate weighting, reference states and the value anchor's normalisation must be specified; top-action agreement of 99% between window and full-history policies permits large probability drift, so a total variation or KL bound is needed, especially at deviation roots; a mean value drift can hide large local errors. What exists for it: a measurement that a 64-step window from a zero state reproduces chain 55's top action at 1,233 of 1,233 decisions (two games), a batch timing, and the reserve games.
2. **The captured share** (the share of the seat's one-step evaluator gain an arm captures, net of its other changes, on fresh rollouts). The reviewer: at a deviation root a perfect label follower earns `G(label) - E_p0[G]` in the numerator while the denominator uses `G(label) - G(a0)`; a0 is sampled and the deviation depends on it, so perfect imitation need not score 1. Truncating to eight actions with probability differences of 0.01 or more drops mass, the kept coefficients need not sum to zero, and the result then depends on the a0 baseline. Independent rollouts remove selection optimism and neither defect. The 0.10 and 0.25 bars had no calibration, and a zero or negative denominator was undefined. A later entry must redefine the estimand before using it.
3. **Any rule that chooses the registered arm from data.** Selection by rollouts is postponed with the captured share. J is reported and decides nothing (section 3); a validation budget on the change at other decisions would add another unsupported threshold.
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
- **The registered arm is one dose, named in advance.** Lambda 4 is the middle of three; nothing shows it is the best, and a Flat or Inconclusive reading for it is not a reading of the whole grid. J is a printed diagnostic with an assumed price.
- **Reading 1 is about the lambda 16 arm, not the registered arm.** FIT says R1 can fit its training labels at the largest dose. The registered arm's own training fit is printed beside it and has no threshold (on the Mac runs it was 0.81 at milestone 0 and about 0.67 at the rehearsal's half steps).
- **Three arms are gated and one is read.** The dose-response is descriptive; six intervals are printed.
- **No placebo arm.** A Positive result is the registered arm's strength result. It could come from a general perturbation of the output layer and not from the labels: the rehearsals show training fit without held-out label transfer while many held-out decisions change. Attributing a gain to the search's deviations would need a label-shuffled arm (the same fit toward permuted labels, weights and classes kept) in a later entry.
- **The gate is batched,** so its games are not the unbatched games of D430 and D435 on any seed, and the search seat's +45 is a descriptive comparison.
- **An arm is valid under m1 only,** and is not eligible ancestry for training.
- **False and unjudged labels are trained on.** D2 found 0 false of 87 (upper bounds 3.4% counting roots and 4.4% counting games, with the limits D430 lists). The share in this run is reported from the fresh judgments.
- **Acceptance checks declarations, counts, hashes and the rule's arithmetic from stored returns.** That the returns are the seat's rests on the pinned code and on the `seat` test. Teacher parity is parity on an identical root: after the seat's first deviation its real game leaves C's, so a label at a later root of C's game is the seat's computation there, not the action S took at that step of its own game.
- **The splits' locks are procedural.** The test file is on disk; the tools refuse to read it out of turn and leave a marker when they do read it. That is the same strength as the gate's one-look rule.
- **A sidecar's full hash is not recorded at play** by the harness at this commit (section 3 says what is bound instead). No harness change is made in this plan.
- **Measured only on the 16-game smoke:** the droplet rate of the label tool. The smoke's games, made on a droplet, replayed on the Mac to the same digests and observation hashes, with all 480 root supports rebuilt equal. **Not measured:** the fine-tune's time at the registered size, and anything about R2.
- **Milestone 0 and the rehearsal are not evidence.** Milestone 0's labels were seen before this plan existed, and both ran on the Mac on a few hundred games.

## OPERATOR: expectation

Written by the operator on 2026-10-08 before Entry A, after the Mac rehearsals and the label smoke and before any registered game, so that it cannot be adjusted later.

- **Reading 1.** FIT at milestone 1: about two chances in three. The Mac runs fitted 0.93 (milestone 0) and 0.82 (the rehearsal) at lambda 16, on 64 and 110 training labels, with each label visited hundreds of times; at milestone 1 each is visited about 270 times. FIT at milestone 2, given FIT at 1: about three in five. There each label is visited about 30 times, and there are ten times as many preservation examples pulling on the same weights. A NOT FIT would say more about the step budget than about the recipe, and the entry that follows would have to say so.
- **Held-out, lambda 4, at the full label count.** Label probability between 0.03 and 0.12 over all test labels (the original gives them about 0.01 to 0.02). The top action changed at 3% to 8% of held-out screened roots (the Mac runs showed 10% to 12% with a tenth of the data or less).
- **The gate.** Both of the registered arm's contrasts between -30 and +10. Reading: Negative about 45%, Inconclusive about 30%, Flat about 15%, Positive about 10%. Dose-response: more negative the larger lambda.
- **Why it is run at these odds.** It costs about $6.50, the labels (the expensive part) are reusable by any later recipe, and after a Negative the held-out change numbers show where the policy moved, which is where a larger design would start looking. They do not show which changes cost the games.
- **Disclosed.** Lambda 4 was named after two Mac rehearsals' gate rehearsals had been seen (16 to 32 seeds a pair, eleven of twelve point estimates below zero, lambda 1 the least negative). They are not evidence and they did not favour lambda 4.
