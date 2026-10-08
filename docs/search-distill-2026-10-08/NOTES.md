# Search distillation, Test 1: notes for the operator (version 3, 2026-10-08)

Written with `/Users/alexanderhuth/Code/bb-opt-build/docs/search-distill-2026-10-08/PLAN.md` (version 3, the narrow first slice). Nothing is registered. Nothing ran on a droplet or on the rig, and no cloud resource was created, listed or deleted. No harness worktree and no checkpoint store was written to (`git status --short` of `/Users/alexanderhuth/Code/bb-harness-search` is empty after the work). Nothing was committed, staged or deleted.

**Operator's addendum, round 4 (2026-10-08, after round 3; this paragraph and section 00 are the operator's, the rest is the tools' author's).** The second paragraph above was true when written. Since then two droplet smokes were run (section 00). Sections 0 to 10 describe the files before the round 4 changes.

**Section 0 is round 3: the tools review's ten gaps, what changed, what the rerun showed, and where I think a decision deserves a second look. Sections 1 to 10 are version 2's notes, kept as the record of what ran on the version 2 tool files (commit `806fe17`), with stale statements marked.**

Everything below ran on the Mac, one process at a time, `OMP_NUM_THREADS=1`, `PYTHONDONTWRITEBYTECODE=1`. The Mac's load average was between 8 and 20 throughout, so every wall-clock figure is a loaded-Mac figure.

Shorthand used in the command lines:

```
D=/Users/alexanderhuth/Code/bb-opt-build/docs/search-distill-2026-10-08
R=/Users/alexanderhuth/Code/bb-opt-build/runs/search-distill-2026-10-08     # git-ignored
X=$R/harness-5ab3ab6                                                         # the export
PY=/Users/alexanderhuth/Code/bb-play-harness/.venv/bin/python
CK=/Users/alexanderhuth/Code/bb-play-harness/.play-artifacts/checkpoints/chain55/0000002999975936.bin
export OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1
```

## 00. Round 4, by the operator: the review of the fixes, the smokes, the final hashes

**The review of round 3's fixes** (`/Users/alexanderhuth/Code/bb-opt-build/.codex-reviews/distill-fixes-review.md`, final answer after its last "tokens used" line). B1, B2, B3, B5, B6, B8 and B10 closed; B9 as far as decided. Three blocking findings, all applied:

1. **B4, coverage.** `select` trusted the shard names in `DATASET.json`. A one-shard dataset relabelled as all eight would have passed without any file hash changing. Now `select` also requires `FINETUNE.json` to have recorded every shard and, what it rests on, that the training and validation files hold exactly the plan's games of their split (from the engine seeds in the hash-bound files). `heldout` checks the test file the same way before it computes anything. In `distill_eval.py` only.
2. **B7, absent entries.** The scorer checked the manifest entries that were present. Now every registered checkpoint player must have an entry in every shard's manifest.
3. **The gate's plan generator took whatever commit the harness worktree was at.** It now refuses any commit but `5ab3ab6`.

**The operator's own changes in round 4.**
- A shard manifest that does not exist yet is a refusal, not Unread: the run is not complete and nothing of it has been read. A relaunched shard whose directory was not named with `--shard-dir` would otherwise have written Unread on a typing slip.
- B8 as a refusal (the author's departure) is kept. The reviewer found it sound: nothing of the run is read before it fires.
- The reserve games' supports are not replayed under this plan (the author's item 1). Left as a stated limit: a later entry that uses them replays them then.
- `make_plan.py`'s droplet rates are the label smoke's. Milestone 2's time limit is 7 hours. The allocation is $14.
- Wording the reviewer asked for: finite float cells, "for one selection only", who records Unread when a tool stops before a reading, pagination, two test descriptions.

**Tests added** (`test_distill.py`): the relabelled one-shard dataset; the fine-tune that recorded one shard; a blob changed in the value row with every hash brought up to date (the span check alone); a manifest without a registered player's entry; the scorer on a run with no manifest. Rerun: `chain, locks, milestone, fitblob, gate`, 5 of 5 pass, 364 s (`results/r4-tests/affected.log`). The other tests' files did not change.

**Label smoke** (`results/smoke-label/`). `distill_droplet.py run --name sdsmoke --plan PLAN.smoke.json` (as-run plan `3f05848536f1c79e862037a129f224487cdbfaf7c6b4e3274e027002527c2a63`, kept as `results/smoke-label/PLAN.json`), one droplet, 16 games, seeds 29980400 to 29980415.
- Accepted: 480 roots, 10 deviation roots (1 false, 9 confirmed, 0 unjudged), 0 cap rejections, 1,024 other decisions. Library on the droplet `32632f034a30...` (the Mac's is `3359eff5b536...`).
- Rate: 88.5 s a game of one process (18.0 s play), 213 s wall on 8 processes; create to launch 167 s; lifetime 6.7 minutes, $0.019. Droplet 607341725 deleted and verified gone; key gone.
- **Cross-machine replay:** the dataset tool on the Mac replayed all 16 droplet games to their digests, scores and observation hashes; 480 root supports rebuilt equal; largest a0 log-probability difference 1.23e-4; no candidates reordered.
- That plan's launcher, lifecycle and tool files are the registered plan's except `distill_eval.py`, which no droplet runs.

**Gate smoke** (`results/smoke-gate/`). `gate/make_plan.py --gate distill-smoke-20261008 --seed0 29980900 --games-per-pair 512 --shards 2 --max-hours 1 --finetune <the round 3 rehearsal's fine-tune>`, plan `6cd29a231b96ca6999eef7c5f3c4ab676410f747b884328c6375f41a5ebb995c`, on the final gate scripts.
- Two droplets, 2,048 games each, 3.69 and 3.75 games a second, 13.7 minutes and $0.038 each. Droplets 607345194 and 607345195 deleted and verified gone; keys gone.
- Scorer: `MANIFESTS-CHECKED 2`, the merge, `GATE-ACCEPTED 4096 games`, `MASKS-ACCEPTED`, `SEARCH-ACCEPTED`, `SIDECARS-ACCEPTED`, `SCORED`.
- Its numbers, which are the rehearsal's arms and never evidence: lambda 1 -28.3 [-83.9, +26.0] and -19.5 [-73.5, +30.9]; lambda 4 -42.4 [-92.1, +10.7] and -43.8 [-99.7, +9.9]; lambda 16 -62.2 [-112.0, -11.6] and -51.2 [-104.2, -1.3]. The operator's expectation in PLAN.md was written before this was scored.

**Final plan hashes, regenerated after the last tool edit.**

| File | sha256 |
|---|---|
| `PLAN.json` | `7833952041c0d3b9e98bf42471408d0552e4fe9a04d90c13c700ad16cf8dae00` |
| `PLAN.smoke.json` | `62040dfee57f73b5be2b893f4ed5def979cce0d2f65416bc5773d1149e5f249a` |
| `PLAN.rehearsal.json` | `73e42d12c19b2f18197ed788fd6bb9391f98197693fbad2d62796f93c5118f51` |
| `PLAN.m0.json` | `6350e6b3f928bd1448413bd0fa464894b06b8976556eef2c715bbfef33673bd7` |

The plans the smokes and rehearsals actually ran on are under `results/` (`smoke-label/PLAN.json`, `r3-rehearsal/PLAN.json`, `rehearsal/PLAN.json`, `m0/PLAN.json`). The hashes in section 0's table are round 3's and are superseded by these.

## 0. Round 3: the tools review's ten gaps

The review is `/Users/alexanderhuth/Code/bb-opt-build/.codex-reviews/distill-tools-review.md` (final answer from line 14427). It found the teacher path faithful and ten blocking gaps, B1 to B10. I applied the operator's decision on each, added a test for each, and reran. The diff is against commit `806fe17`, and `distill_screen.py` is not in it (`git diff --stat 806fe17` does not list it; its sha256 is still `d436299a...`). A running log with times is `/Users/alexanderhuth/Code/bb-opt-build/runs/search-distill-2026-10-08/ROUND3.log`.

### 0.1 What changed, finding by finding

- **B1, judgment returns** (`distill_accept.py`). Every judgment cell must be a finite number or an explicit null; NaN and infinity are refused. Stop counts, for the screen and for the judgment, must name all five kinds of stop, be non-negative integers and sum to the rollouts run (candidates x 16 for a screen, 2 x pairs for a judgment). Null cells must equal the counted cap stops one for one, and a root is a cap rejection exactly when its screen counted a cap stop. Test `accept`: six corrupted copies, each with its derived fields recomputed and its hashes rewritten so that only the new check can refuse it.
- **B2, other decisions** (`distill_accept.py`). No engine step of a game holds two records, across roots and sampled other decisions together. Each other record's engine seed, seat, searchable count and kept count must be its game's. Test `accept`: four copies.
- **B3, the recorded support.** `distill_accept.py` requires a root's candidates to be distinct tuples of its recorded support. `distill_dataset.py` rebuilds the masked support and the class at every root it replays and requires both to equal the record's before the candidate checks. Test `accept`: a candidate outside the support and a candidate listed twice are refused by acceptance; a legal action removed from a root's support passes acceptance (the records agree with each other, which is the reviewer's point) and is refused by the dataset tool's replay.
- **B4, milestone boundaries and bindings** (`distill_eval.py`, `distill_common.py`, `distill_dataset.py`, `distill_finetune.py`). New command `fit`: Reading 1 and the validation numbers, `REPORT.fit.txt`, no selection file. `DATASET.json` records the shards it holds; `select` refuses a dataset that does not hold every shard of the plan, and refuses when the dataset's files are not the ones `FINETUNE.json` recorded. `heldout` requires the plan's registered arm with an accepted blob, every arm accepted, Reading 1 FIT, the dataset files the selection recorded, and each arm's sidecar hash as well as its blob hash. `open_split` refuses by the path `DATASET.json` records, before anything is deserialised: the reserve split never, a file under `locked/` only as the test split, the test split only for `heldout`. Tests `milestone` (13 cases) and `locks`; the lock test no longer loads the test file.
- **B5, the loss** (`distill_finetune.py`). A step's loss is its chunk's numerator divided by (the training set's total weight / the number of chunks). Test `loss`: over 9 chunks of unequal weight the mean chunk loss equals the whole set's loss to 4.4e-16; dividing each chunk by its own weight would be off by 1.4e-2.
- **B6, blob acceptance apart from everything else** (`distill_eval.py`). An arm whose blob fails is not scored at all; Reading 1 is Unread when the fit arm's blob fails. Test `fitblob` (4 cases): the fit arm's blob changed in the value row, under `fit` and under `select`; another arm's sidecar changed by one byte stops the plan unread at the selection and leaves Reading 1 as it was.
- **B7, what each shard played** (`gate/score_from_plan.py`). Before the merge, every shard's own manifest is checked: each player's checkpoint entry has the registered blob hash, and its producer and compatibility blocks equal the registered sidecar's. No harness change. Test `gate`: another producer, another blob hash, another compatibility block, an unregistered player, a missing manifest, a local sidecar that is not the registered file; and the scorer itself run on a scratch gate whose run has another producer leaves `reading.json` saying Unread.
- **B8, the scoring code's pin** (`gate/score_from_plan.py`). The scorer refuses unless the harness worktree is clean at the plan's commit, before it imports or runs anything from it. Test `gate`, on a scratch git repository: a changed tracked file, an untracked file, a later commit, a directory that is no worktree; and the scorer itself run against the changed scratch worktree. **One departure, section 0.3 item 1: this refusal writes no reading.**
- **B9, ownership** (`distill_droplet.py`). A leftover ssh key is deleted only when its public key or fingerprint is the one this run generated locally; a key of the run's name with another public key is reported and left alone; key and droplet listings are read page by page; the printed fallback names only droplet ids this run recorded. The droplet side is the inherited lifecycle, unchanged, and the plan's Exposure paragraph states its adoption rule. Flow test checks 5b and 5c.
- **B10** (`distill_droplet.py`). `--keep` is refused unless the plan is the smoke or the dev plan. Flow test check 9b.
- **Non-blocking items applied.** A shard must name a valid sha256 of its engine library, and all shards the same one. The fit, selection and held-out numbers are computed from float32 logits as the harness computes them (the blob's float32 weights on float32 features), then the joint in float64; training stays float64 and the float64 fit value is printed beside the reading once. A malformed or missing interval gives Unread, and a rejected run leaves `reading.json` with Unread and the reason. The launcher requires `--shard` names for the registered plan. `DATASET.json` has no deviation count for the reserve group. The plan's text: eight shards; the literal stage commands; a quota refusal exits and is retried later; the $12 is the operator's allocation; "not Positive" means no improvement is established for the registered arm; what is and is not forbidden for the test and reserve games.
- **The design change.** The registered arm is named: lambda 4, `c55d1l4`, in the plan file (`finetune.registered_arm`), in `make_plan.py` and in `gate/make_plan.py`, which refuses a selection that registers any other arm. J is printed as a diagnostic. `select` writes `SELECTION.json` only when all three blobs pass and Reading 1 is FIT. The plan says why (sections 0 and 3) and has the placebo line in its limits.

### 0.2 What the rerun showed

All on the final files, one process at a time. The Mac's load average was 14 to 23.

**The fast tests: 11 of 11 pass, 379 s.**

```
$PY $D/test_distill.py --harness $X --checkpoint $CK --scratch $R/tests/r3-d \
    --only rule,blitz,chain,replay,loss,blob,locks,accept,milestone,fitblob,gate
```

| Test | Result |
|---|---|
| rule | PASS, 961 of 961 tables; the kinds of stop and the tuple packing are the harness's |
| blitz | PASS, as in round 2 (64 of 64 and 0 of 64) |
| chain | PASS, 300 s. 40 games in two shards through label, acceptance, dataset, fine-tune, `fit` and `select`; Reading 1 FIT at 0.9875345957643983 from float32 logits, 0.987534585962308 in float64; selection written |
| replay | PASS, 40 of 40 trails |
| loss | PASS, with the chunk identity of B5 |
| blob | PASS |
| locks | PASS, 4 of 4 refusals before anything is deserialised (0 loads) |
| accept | PASS, 15 of 15 (B1, B2, B3, the library hash) |
| milestone | PASS, 13 of 13 (B4) |
| fitblob | PASS, 4 of 4 (B6) |
| gate | PASS, 17 of 17 (B7, B8, the Unread outputs) |

The log is `$D/results/r3-tests/fast-final.log`. An earlier run of ten of these on the tool files as frozen for the rehearsal is `$D/results/r3-tests/fast.log` (10 of 10, 365 s); between the two only `gate/score_from_plan.py` and the `gate` test changed (section 0.3 item 1).

**The seat test: PASS, 504 s.** It did not need rerunning: `distill_screen.py` is untouched, and the functions it takes from `distill_common.py` (the harness loader, the plan loader, the kick-off turn rule, the hashes) are outside that file's changed lines. I reran it anyway because the test file was rewritten around it: 3 searched games, 521 decisions on the seat's own roots, 359 after the first deviation, 0 mismatches (`$D/results/r3-tests/seat.log`).

**The launcher's offline checks, on the final launcher** (sha256 `4217fb61...`):

```
S=$R/launcher-dev
$PY $D/make_plan.py --harness $X --kind dev --games 2 --out $S/PLAN.dev4.json       # prints H
$PY $D/distill_droplet.py rehearse --plan $S/PLAN.dev4.json --expect-sha256 $H \
    --harness-export $X --shard dev --dir $S/rehearse-4 --python $PY                # 13.4 s
$PY $D/test_launcher_flow.py --plan $S/PLAN.dev4.json --expect-sha256 $H \
    --harness-export $X --rehearsal $S/rehearse-4 --shard dev --scratch $S/flow-4b  # 0.5 s
$PY $D/distill_droplet.py run --name sddry4 --plan $S/PLAN.dev4.json --expect-sha256 $H \
    --harness-export $X --shard dev --max-hours 0.5 --max-total-usd 0.2 \
    --dry-run --assume-hourly 0.16667
```

- Rehearse: job exit 0, shard accepted (2 games, 60 roots).
- Flow test: **56 of 56 checks pass** (47 before; the new ones are the key of the run's name with another public key, which is reported and left alone; the run's key found on the third page of a paginated listing; `--keep` and missing `--shard` names by plan name).
- Dry run: exit 0, nothing created.
- After the plans were regenerated I dry-ran the plan's two literal launcher commands against the final `PLAN.json` (`$D/results/r3-launcher/dryrun-registered-m1-final.txt`, `dryrun-registered-m2-final.txt`): both exit 0; spend guards $1.67 of $1.70 and $5.00 of $5.10; the launcher's own estimates are $0.42 and $3.57 (it adds seven minutes of setup a droplet to the plan's $0.38 and $3.46). The same command with no `--shard`, and with `--keep`, is refused with "Nothing was created".

**The wide rehearsal, again, under a fresh name: chain exit 0, 40 minutes.**

```
bash $D/run_chain.sh rehearsal rehearsal-r3-20261008 32 29980870
```

**Not evidence.** Plan `$R/rehearsal-r3-20261008/PLAN.json`, sha256 `ced680a180fbd0338c8b4fddcdb6824644e42f6236c88a44a4da06f991876c1b`. Same 300 games as the first rehearsal (seeds 29980100 to 29980399), reduced rollouts, 1,200 steps.

| Step | Wall-clock | Result |
|---|---|---|
| label | 1,861 s | 300 games, 9,000 roots, 154 deviation roots, 0 cap rejections, 67 kick-off turn roots. **`roots.jsonl` and `other.jsonl` are byte for byte the first rehearsal's; `games.jsonl` differs only in each game's wall-clock seconds** |
| accept | 1 s | `SHARD-ACCEPTED rehearsal: 300 games, 9000 roots, 154 deviation roots (12 false, 105 confirmed, 0 unjudged), 0 cap rejections, 67 kick-off turn roots, 19200 other decisions; library 3359eff5b536` |
| dataset | 53 s | the same counts as before; **8,100 root supports rebuilt on replay and equal to the record's**; "holds 1 of the plan's 1 shards"; the reserve group shows games, roots and other decisions and no label count |
| finetune | 314 s | three arms, 1,200 steps, three chunks |
| fit | 4 s | Reading 1 FIT; no selection file |
| select | 3 s | Reading 1 FIT; three blobs accepted; registered arm `c55d1l4` "named in the plan, chosen by no rule"; `SELECTION.json` sha256 `e1b1100fa22bc8e4900b371f529fa862feeea5d0105a53919f3cfd1d7a68d1cc` |
| heldout | 2 s | the numbers below |
| gate plan, play, score | 0 s, 161 s, 9 s | 256 batched games; the manifest check and all four acceptance checks; reading Inconclusive |

Fit, with the declared loss (B5) and float32 logits. In brackets, the first rehearsal's value on the same data with version 2's per-chunk normalisation.

| Arm | lambda | Training label probability | Training change elsewhere (total variation) | Validation M (11 labels) | Validation U | J (diagnostic) |
|---|---|---|---|---|---|---|
| `c55d1l1` | 1 | 0.584 (0.583) | 0.0135 (0.0129) | 0.0003 | 0.0569 | -0.00091 |
| `c55d1l4` | 4 | 0.667 (0.668) | 0.0285 (0.0267) | 0.0013 | 0.0706 | -0.00113 |
| `c55d1l16` | 16 | 0.817 (0.805) | 0.0455 (0.0444) | 0.0000 | 0.0905 | -0.00145 |

- Reading 1: FIT, 0.8171654289910563 from float32 logits, 0.81716541779706 in the float64 training arithmetic. The two differ in the eighth decimal.
- The B5 change moves the fit by up to 0.012 here (three chunks of unequal weight). At the registered size chunks are near equal and it should move less; that is an expectation, not a measurement.
- Milestone 0 was not rerun. Its fit numbers in section 4 (0.70, 0.81, 0.93) were made with version 2's normalisation on two chunks.

Held-out numbers on the 30 test games (14 noisy labels; reported by the chain; they enter nothing): label probability 0.034, 0.007, 0.001 for lambda 1, 4, 16; top action changed at 8.4%, 10.1%, 12.0% of screened roots and 3.6%, 5.2%, 6.8% of out-of-scope decisions. The same picture as before: training fit, no transfer, about a tenth of in-scope decisions changed.

The gate rehearsal (`/Users/alexanderhuth/Code/bb-play-harness/.play-artifacts/tournaments/distill-mac-rehearsal-r3-20261008/`, a new directory; plan sha256 `60f1c3535d3de5250b7d08466fa40c4c5fa01218a296f6b829c6a0520902faff`; seeds 29980870 to 29980885). Verbatim:

```
MANIFESTS-CHECKED 1 manifest(s): every player's blob hash, producer and compatibility blocks are the registered ones
GATE-ACCEPTED 256 games, 8 pairs, seed0 29980870, games_per_worker 32, commit 5ab3ab6
MASKS-ACCEPTED 256 masked sides in 256 games as registered, no sampling offsets, 0 truncated, 0 mask fallbacks
SEARCH-ACCEPTED 0 searched games of 256 as registered; no searched decision; 0 cap-rejected decisions (0.000%), 0 cutoff rollouts of 0, 0 error rollouts; 0 identity game(s) equal to the plain game; 8 pair(s) held to the plan's schedule
SIDECARS-ACCEPTED 6 players' blobs and lineage sidecars as registered, and the manifest's producer blocks are the sidecars'
integrity totals {"error_episodes": 0, "illegal": 0, "precheck_collisions": 0, "projection_collision": 0, "rejected_submissions": 0}; unnatural endings 0
READING (c55d1l4 minus c55m1; first match of Unread, Negative, Positive, Flat, Inconclusive): Inconclusive
```

- The registered arm's contrasts: -112 [-391, +135] against chain 37 and -191 [-4609, +70] against chain 46, 16 seed clusters. Nothing can be read from 32 games a pair. One dose-response interval (lambda 1 against chain 46) is entirely below zero: that arm split its decisive games 9 to 9 where the control went 18 to 3. The lower ends of minus several thousand come from bootstrap replicates in which the control loses no decisive game, which happens with 16 seed clusters. That is the inherited contrast script at a tiny size, not a defect at 12,800 games.
- The scorer's worktree check passed on the real worktree (`/Users/alexanderhuth/Code/bb-harness-search`, clean at `5ab3ab6`, and still clean afterwards).
- **The gate once more with the final scorer.** After the chain I changed the scorer's worktree refusal (section 0.3 item 1), so I replayed and scored the same arms on the same seeds in a second new directory, `/Users/alexanderhuth/Code/bb-play-harness/.play-artifacts/tournaments/distill-mac-rehearsal-r3b-20261008/` (plan sha256 `27d9a3d24f5ee639d79d1e4298d3f5a226d8ef6cecc719cad9d537f04126e29e`; play 135 s, score 6 s). The same six lines, the same six contrasts to the digit, the same reading. Its `score_from_plan.py` is the final file (`ef2428a3...`). Logs in `$D/results/r3-rehearsal/gate-final-scorer/`.

### 0.3 Where I think a decision is wrong, or costs more than it is worth

1. **B8: I made the worktree refusal a refusal, not an Unread reading. This is my reading of the decision; overrule it if you meant the other.** My first version wrote `reading.json` = Unread when the harness worktree was not clean at the commit. The consequence table then sends an Unread gate to a new ledger entry. But a dirty or moved worktree is a fact about the scoring machine, found before anything of the run is merged or read, and that worktree is shared with other sessions: an untracked file or a later commit on its branch is likely within a day. Burning the plan's one gate on that is the wrong price. So the scorer now exits non-zero with "REFUSED, no reading", writes nothing, and can be run again once the worktree is back at the commit; the plan says "a refusal is not a reading". A wrong script hash was already handled this way. Unread is kept for failures of the run's own records (a shard manifest, the merge, acceptance, an interval). To flip it: one line in `gate/score_from_plan.py` (`unread(...)` in place of the `SystemExit`) and one case of the `gate` test.
2. **B3's replay check does not reach the reserve games.** The dataset tool skips them entirely, so here 8,100 of 9,000 root supports were rebuilt. That is the narrow version, and it is what "never looked at" asked for. The cost: a defect in a reserve shard's supports is found only when a later entry builds on the reserve. An integrity-only replay of the reserve games (digest, score, observation hashes, support and class; no feature, no label count, nothing written) is about fifteen lines and a tenth more dataset time. I would add it before Entry A. I did not, because it is a tool change beyond the decisions and it would have meant another full rerun.
3. **Reading 1 is on the lambda 16 arm and the gate's label is on the lambda 4 arm.** After the design change a FIT reading says R1 can fit at the largest dose; the registered arm's own training fit was 0.81 at milestone 0 and 0.67 here. The plan's limits now say so. If you want the stop to be about the arm that is read, the alternative is a second threshold on the registered arm, which is another unsupported number. I would leave it as it is and write the expectation for lambda 4's fit.
4. **Naming lambda 4: agreed, and nothing on the Mac contradicts it or supports it.** No rehearsal can rank the doses.
5. **The all-three-blobs rule: agreed.** It lets a descriptive arm's blob stop the registered arm's gate, but a blob that fails acceptance means the tool or the disk is at fault, and a rerun of the fine-tune reproduces its bytes on the same machine.
6. **B7 without a harness change leaves one hole, stated in the plan:** a droplet's sidecar that differed from the registered one outside the producer and compatibility blocks (its ancestry block) would not be seen. The launcher uploads the file it has just hashed, so this needs a fault in transit. The proper fix is one manifest field in the harness (the sidecar's sha256, recorded at load) at the next pin.
7. **B9's droplet side stays the inherited rule.** Adoption by exact name with the run's random id, the tag and a creation time after the attempt is not proof of ownership. The plan says so. A run-scoped wrapper around the inherited lifecycle would be a real piece of work and I did not start it.
8. **The placebo arm, postponed: the price of that, in one line.** A label-shuffled arm shares gate seeds with the registered arm only if it is in the same gate. Added later it needs the registered arm played again beside it. In this gate it would be one more fine-tune and two more pairs, about $0.21. I built nothing for it.

### 0.4 What I could not do, or did only narrowly

- **No real cap stop exists in any run so far,** so B1's null-cell rules are tested on corrupted copies only.
- **B8's refusals were tested on a scratch git repository.** The real harness worktree was never made dirty; only its accepting case ran (twice).
- **B4's lock is a check of the path `DATASET.json` records.** A hand-edited record, or a direct `torch.load` of `locked/test.pt`, goes around it. The plan's limits call the locks procedural.
- **B7's shard-by-shard check ran on one real manifest** (the local run's). Four droplet shards' manifests have never existed; the corrupted cases are scratch files in the shape the tournament writes.
- **The launcher has still never touched the network,** and its sub-agent's mutation checks were not rerun.
- **Milestone 0 was not rerun** (as agreed).
- Everything in section 7's "not verified" list still stands.

### 0.5 Plan files, regenerated last

`make_plan.py` for all four kinds, after the last tool edit. `PLAN.rehearsal.json` came out byte for byte the plan the rehearsal ran on, so the writer is deterministic.

| File in `$D` | sha256 | What it is |
|---|---|---|
| `PLAN.json` | `4a433d441d21ca4416e7c8f3d95e7d4beb8db68e0ffc16c45786413ebbd916b4` | the registered plan's draft: eight shards, registered arm `c55d1l4`, the final tool and launcher hashes |
| `PLAN.smoke.json` | `3f05848536f1c79e862037a129f224487cdbfaf7c6b4e3274e027002527c2a63` | the droplet smoke, 16 games, not played |
| `PLAN.rehearsal.json` | `ced680a180fbd0338c8b4fddcdb6824644e42f6236c88a44a4da06f991876c1b` | the plan `rehearsal-r3-20261008` ran on |
| `PLAN.m0.json` | `87eda3ecd810b5caf3125ee178f6b584c4ca95319bdbbe52574c0fed35e662b0` | milestone 0's plan on the final tools. **Not run.** The plan milestone 0 ran on (`f000c805...`, version 2 tools) is kept as `$D/results/m0/PLAN.json` |

Tool hashes the plans bind:

| File | sha256 |
|---|---|
| `distill_common.py` | `fcd663a076e08404475cf016aa1cc582dd4bc74f777807ecd3bfe5aa908dd048` |
| `distill_screen.py` | `d436299a4df262b461e6ec7a237d59e895786ae42803688fd3a4f56665b33524` (unchanged) |
| `distill_accept.py` | `2861a6e4b3a2a73e5b737b56a4bc016776be5b87608afe0266fa5897a46f3d28` |
| `distill_dataset.py` | `d9d0140f324c24a6d4f6a1c9cbd3e1a5d405857275a0d8d561fb33fa5801b2fb` |
| `distill_finetune.py` | `7b93677563763ddcfa0dc369551f306fd20c85a7fcab1498e95e06085f496866` |
| `distill_eval.py` | `f11d7872145fe7df304e6d78d681ff4e10362de76391cb7ed712ef284dacd167` |
| `distill_droplet.py` (the launcher, bound apart) | `4217fb6148f4ffe3a32711d1640baddd1f93544d64aaa27ab1c1bd5d5f27cfff` |

The gate's scripts are bound by the gate's own plan at Entry B. Today `gate/score_from_plan.py` is `ef2428a307744938f99d65485e7a6c76f95f6ae41b9777a4073ed7fb4537be79` and `gate/make_plan.py` is `2469a7c83bc3ef77252acae9185a4522a2accbee9205fc8fd93bffb2ecb3e93f`.

### 0.6 What round 3 wrote, and the seeds it played

- **Seeds, all on the Mac, none evidence:** 29980500 to 29980539 (the test chain's two shards, four runs; the launcher rehearsal's two games); 29980100 to 29980399 (the rehearsal's label games, the same games as the first rehearsal); 29980870 to 29980885 (the gate rehearsal, played twice); 29980702, 29980707, 29980730 (the seat and blitz tests).
- **New directories:** `$R/rehearsal-r3-20261008/`, `$R/rehearsal-r3b-gate-20261008/`, `$R/tests/r3-a` to `r3-d`, `r3-blitz`, `r3-seat`, `$R/launcher-dev/rehearse-4`, `flow-4`, `flow-4b`; the two tournament directories named above; `$D/results/r3-tests/`, `$D/results/r3-launcher/`, `$D/results/r3-rehearsal/`. The plans three runs ran on were copied into `$D/results/m0/`, `$D/results/rehearsal/` and `$D/results/r3-rehearsal/` as `PLAN.json`.
- **Changed files in `$D`:** `PLAN.md`, `NOTES.md`, the four plan files, `make_plan.py`, `distill_common.py`, `distill_accept.py`, `distill_dataset.py`, `distill_finetune.py`, `distill_eval.py`, `distill_droplet.py`, `test_launcher_flow.py`, `test_distill.py`, `run_chain.sh`, `gate/make_plan.py`, `gate/score_from_plan.py`.
- One stray: a final check of mine ran without bytecode turned off and left `$D/__pycache__/distill_common.cpython-312.pyc`. It is git-ignored and I left it (delete nothing).
- No existing run directory or tournament directory was written to. Nothing was deleted, committed, staged or pushed. No cloud call was made. `git status --short` of `/Users/alexanderhuth/Code/bb-harness-search` is empty and its HEAD is `5ab3ab6`.

## 1. What changed in the plan from version 1 to version 2, and why

The plan's section 0 lists it. In one paragraph (version 3 names the registered arm; J no longer chooses it): R1 only, three lambda arms, no stop rule, held-out roots reported without thresholds, the batched gate over all three arms with one registered arm chosen by J on validation games, every undefined case defined, conclusions restricted to R1 at this label count, sidecar hashes bound, and R2, the captured share, the fresh screen, the probes and the learning curve moved to a "postponed" section that keeps the reviewer's objections.

Things I fixed in the plan because the tools forced a decision:
- **Training length is in optimizer steps, not passes.** 2,400 Adam steps over fixed chunks of at most 8,192 decisions. At the registered size that is about 30 passes, which is what version 1 said. At milestone 0's size 30 passes would have been 60 steps and no arm would have fitted.
- **No stop rule inside an arm.** Version 1 kept the pass with the best J. With three arms gated anyway, an arm is its last step and lambda is the only knob. Fewer forking paths, and the problem is convex.
- **The dataset tool tolerates one thing:** two candidates whose log-probabilities are within 1e-3 of each other may change places when the logits are recomputed (another machine, or a batched forward). It counts those roots. Milestone 0 and the rehearsal had none.
- **Returns are stored at full precision,** so that the acceptance tool can recompute the seat's rule from the stored returns and require the stored result exactly.

## 2. Where I thought a version 2 decision deserved a second look

I built to every decision. Two notes, neither a disagreement that should hold anything up. **Round 3 took note 1: the registered arm is lambda 4 by name.** Note 2 stands and is now in the plan's limits.

1. **J will probably register the arm that changes least.** With the price at 0.016 and held-out change near a tenth of decisions (milestone 0 below, and the preview), J is negative for every arm and is highest for lambda 1. That is a defensible registered arm ("the most conservative fine-tune"), but it means the label statistic is not the arm that copies the labels best. A simpler rule with the same effect on paperwork would be to register lambda 4 by name in Entry A. The dose-response covers the others either way.
2. **The test split's protection is procedural.** The fine-tune's reader refuses the test file and the evaluation tool wants the selection's hash and leaves a marker, but the file is on disk beside the others. That is the same strength as the gate's one-look rule.

## 3. The tools, and which tests passed

All files are in `$D`: about 5,900 lines of Python and shell in all.

| File | What it does |
|---|---|
| `export_harness.sh` | `git archive` of harness commit `5ab3ab6` into a fresh directory, `SOURCE_COMMIT`, and the shim built inside the export. The export used here is `$X`; its library hashes to `3359eff5b536a07dd62ad96964bc2db7b981964e24bfac60689f744ce4658c1a` |
| `make_plan.py` | Writes the plan for `--kind registered`, `m0`, `rehearsal`, `smoke` or `dev`: checkpoint by blob and sidecar hash, seeds, shards, label settings, split, fine-tune settings, selection rule, tool hashes |
| `distill_common.py` | Plan loader (refuses a wrong hash or a changed tool file), harness loader (export only), split rule, kick-off turn rule, replay of a trail, the exact joint distribution, scoring of a weight matrix, J |
| `distill_screen.py` | The label tool (plan section 2) |
| `distill_accept.py` | Shard acceptance (plan section 5), with the seat's rule restated and recomputed from stored returns |
| `distill_dataset.py` | Replay, digests, observation hashes, features, split. Writes `train.pt`, `validation.pt`, `locked/test.pt`; has no path for the reserve group |
| `distill_finetune.py` | R1: three arms, blob and sidecar writer with its own checks |
| `distill_eval.py` | `fit` (blob acceptance, Reading 1, the validation numbers, no selection file), `select` (the same, then `SELECTION.json` with the plan's named arm) and `heldout` (the reported numbers, test split opened once) |
| `distill_droplet.py`, `test_launcher_flow.py` | The label stage's droplet launcher and its offline flow test, adapted from the END_TURN probe's by a sub-agent on the session model and checked by me (below). Never run against the network |
| `test_distill.py` | The tests of plan section 7 |
| `check_m0_regeneration.py` | Milestone 0 only: holds the label tool's shard on the seen block against the 2026-10-07 screens |
| `run_chain.sh` | Runs the whole chain for milestone 0 or the rehearsal, one step at a time, timing each |
| `gate/make_plan.py`, `gate/launch_from_plan.py`, `gate/accept_from_plan.py`, `gate/score_from_plan.py`, `gate/play_local_from_plan.py` | The gate, adapted from `/Users/alexanderhuth/Code/bb-opt-build/docs/search-probe-2026-10-07/tctl/`: batched (32 games per worker), per-player masks, three arms plus C, blob and sidecar hashes of every checkpoint, four acceptance checks (the replay check replaced by the sidecar check), the reading applied by the scoring script, and a one-process local player that only takes a plan named `distill-mac-...` |
| `gate/gate_diagnostics.py`, `gate/paired_contrasts.py` | Byte copies of the temperature control's (`1defdd33...`, `722ece95...`) |

**Tests, as run in round 2 on the version 2 files.** `test_distill.py` then made its own 20-game plan and records in a fresh scratch directory. Round 3's test list, command and results are in section 0.

```
$PY $D/test_distill.py --harness $X --checkpoint $CK --scratch $R/tests/<fresh name> \
    --only rule,blitz,chain,replay,loss,blob,locks        # 137 s here
$PY $D/test_distill.py --harness $X --checkpoint $CK --scratch $R/tests/<fresh name> \
    --only seat                                           # 377 s here
```

Round 2's results, on the version 2 tool files (the hashes are in section 4):

| Test | Result |
|---|---|
| rule | PASS. 961 of 961 random and knife-edge return tables give the harness's (deviate, best, gain, se) exactly; the match-over status is the engine's |
| seat | PASS, 377 s. 3 whole searched games by the real `SearchSeat` at k 4, n 16, delta 0.10 (seeds 29980730, 29980707, 29980702): **521 searched decisions screened by the tool on a clone of the seat's own root, 359 of them after the game's first deviation, 5 deviations, 8 inside a kick-off turn, 0 mismatches** in candidates, returns or decision. And 162 decisions of the tool's own plain game equal the seat's up to the first deviation, with the same first deviation and action |
| blitz | PASS. Seed 29980730: from the kick-off turn root at engine step 26, 64 of 64 rollouts that stop on a turn end hold a whole opponent team turn and end with the completed-turn counter one higher (mean 92 engine steps, no cut-off); from the ordinary turn-level root at step 112, 0 of 64 do (mean 51 engine steps) |
| chain | PASS, 132 s. 20 games at reduced rollouts through label, acceptance, dataset, fine-tune and selection: `SHARD-ACCEPTED dev: 20 games, 600 roots, 16 deviation roots (1 false, 13 confirmed, 0 unjudged), 0 cap rejections, 7 kick-off turn roots, 1280 other decisions` |
| replay | PASS. 20 of 20 stored trails regenerate the final digest, the score and both observation hashes |
| loss | PASS. 1,316 stored decisions, largest support 2,535 tuples: joint log-probabilities within 3.6e-15 of `joint_log_probabilities`; within 2.9e-07 of `select_joint`'s float32 log-probability on 329 sampled actions; joint KL by enumeration and by the p0-weighted conditional form within 3.3e-14 |
| blob | PASS. Zero steps: byte-identical to chain 55. 40 steps: 5,271 floats changed, all inside the decoder's policy rows 1,424,384 to 1,656,831, the value row unchanged. A second run gives the same sha256. The harness refuses the blob without a sidecar. The trainer's lineage tool refuses the sidecar ("checkpoint lineage implementation must be an object") |
| locks | PASS. The training reader refuses the test file as train and as validation; there is no path for the reserve split and no reserve game is in any file; the evaluation tool refuses the test split without the selection's hash and leaves it unopened |

- The seat test ran 3 games, not the 20 that version 1 named. Three whole games already compare 521 decisions on identical roots; 20 would have taken about 40 minutes here.
- Every round 2 test, milestone 0 and the first rehearsal ran on the version 2 tool files. The logs are in `$D/results/tests/`.

**The launcher** (`distill_droplet.py`, 840 lines). I read its dry-run path (no API object is built before the `--dry-run` return), its job script and its uploads, and reran its three offline checks on the version 2 files (round 3's rerun is in section 0):

```
S=$R/launcher-dev
$PY $D/make_plan.py --harness $X --kind dev --games 2 --out $S/PLAN.dev3.json      # prints H
$PY $D/distill_droplet.py rehearse --plan $S/PLAN.dev3.json --expect-sha256 $H \
    --harness-export $X --shard dev --dir $S/rehearse-3 --python $PY               # 13.5 s
$PY $D/test_launcher_flow.py --plan $S/PLAN.dev3.json --expect-sha256 $H \
    --harness-export $X --rehearsal $S/rehearse-3 --shard dev --scratch $S/flow-3   # 0.5 s
$PY $D/distill_droplet.py run --name sddry3 --plan $S/PLAN.dev3.json --expect-sha256 $H \
    --harness-export $X --shard dev --max-hours 0.5 --max-total-usd 0.2 \
    --dry-run --assume-hourly 0.16667                                               # 0.1 s
```

- Rehearse (the droplet-side job script run locally from a scratch source tree that holds only what a droplet gets): job exit 0, `SHARD-ACCEPTED dev: 2 games, 60 roots, 3 deviation roots (0 false, 3 confirmed, 0 unjudged), 0 cap rejections, 0 kick-off turn roots, 128 other decisions`.
- Flow test with fakes in place of the API and ssh: **47 of 47 checks passed** (order of calls with the six tool files, blob, sidecar and plan uploaded before the build; name-clash and stale-state refusals; phase timeouts; the failure path with logs only and no record fetched; the limit reached before a phase; the lost key; the spend guard; cancellation; the cleanup texts; a wrong plan hash; a launcher whose hash is wrong or null).
- Dry run: exit 0, "nothing is created, no network call is made".
- The sub-agent also broke the launcher five ways in memory and saw the matching checks fail (`$S/mutations-1.txt`). I did not rerun that.
- One finding of the sub-agent's I applied: the label tool printed a heartbeat every minute whether or not a game had finished, which would have kept the droplet runner's stale-log check from ever firing. It now prints only when the count has changed.

## 4. Milestone 0: the seen block, end to end

```
bash $D/run_chain.sh m0 m0-20261008 64 29980800        # 54 minutes here; every step's log is in $R/m0-20261008/
```

**Not evidence. The block's labels were seen before the plan existed, and 4 test labels say nothing.** What milestone 0 shows is that the chain runs and that the label tool is the 2026-10-07 screen.

Plan `$R/m0-20261008/PLAN.json`, sha256 `f000c8057f2cb80c322767181d08e082302fa948ff19777f208ed493ecc6db57`. Tool hashes it binds (the version 2 files, as committed in `806fe17`; `distill_screen.py` is unchanged since):

| File | sha256 |
|---|---|
| `distill_common.py` | `31797b5f61cbd6032d74010f72880ea1981d9ff32fc7e9ee27228b3703de92d3` |
| `distill_screen.py` | `d436299a4df262b461e6ec7a237d59e895786ae42803688fd3a4f56665b33524` |
| `distill_accept.py` | `1c5c9018ca7a13f36bba649baa9a0bf9d1ef042626c18d9198489f300fa30361` |
| `distill_dataset.py` | `e8b801e933832a2048eb049db55573e65381ca487415767574a7be3e944e313b` |
| `distill_finetune.py` | `f7cd329fc80344885623d8b334a951cfa568df13ea214d3307cf8da02b5d2c84` |
| `distill_eval.py` | `c6a87a87ade6795290d38ec2a8ad8904cb611c720603be5ba85df760795165db` |

| Step | Wall-clock | Result |
|---|---|---|
| label | 2,443 s | 200 games, 6,000 roots, 87 deviation roots, 0 cap rejections, 27 kick-off turn roots (in 17 games), 12,800 other decisions; 10.8 million rollout engine steps; the plain games themselves took 385 s |
| accept | 1 s | `SHARD-ACCEPTED m0: 200 games, 6000 roots, 87 deviation roots (0 false, 86 confirmed, 0 unjudged), 0 cap rejections, 27 kick-off turn roots, 12800 other decisions; library 3359eff5b536` |
| dataset | 21 s | train 140 games, 13,160 loss decisions, 64 labels; validation 20 games, 1,880, 6 labels; test 20 games, 1,880, 4 labels; reserve 20 games, not written. Largest a0 log-probability difference 1.2e-4; 0 roots with candidates reordered |
| finetune | 490 s | three arms, 2,400 steps each, about 162 s an arm (two chunks) |
| select | 2 s | Reading 1 FIT; registered arm `c55d1l1` |
| heldout | 1 s | the numbers below |
| gate plan, play, score | 1 s, 256 s, 6 s | 512 batched games; all four acceptance checks; reading Inconclusive |

**The label tool regenerates the seen screens root for root.**

```
A=/Users/alexanderhuth/Code/bb-play-harness/.play-artifacts
$PY $D/check_m0_regeneration.py --shard $R/m0-20261008/shard --seen $A/search-diag-20261007/tail1 \
    --seen $A/search-diag-20261007/tail2 --seen $A/search-d2-20261007/tail3a --seen $A/search-d2-20261007/tail3b
```

- 6,000 roots in both; equal class and seed 6,000, candidates 6,000, **all 16-rollout returns 6,000 (largest difference 0)**, rule result (deviate, best, gain, se) 6,000.
- Labels: 87 in the shard, 87 seen, 87 with the same action. 0 false and 86 confirmed by the shard's own judgment (D2 also found one root, seed 29100154, not above zero by two of its own standard errors).
- Judgments: 22,272 of 22,272 per-rollout returns within 1e-5 of the seen `depth1` returns, 15,273 exactly equal, largest difference 3.8e-6; largest difference of a root's fresh gain 2.9e-8. The differences are rounding: the old rollouts ran on to the end of the match, so the forward that read a value had other rows in its batch. No judgment rollout stopped on the 200-step cut-off.
- `REGENERATION-MATCHED`.

**Fit and selection** (`$R/m0-20261008/finetune/REPORT.select.txt`).

| Arm | lambda | Training label probability | Share at 0.5 or more | Training change elsewhere (total variation) | Validation M (6 labels) | Validation U | J |
|---|---|---|---|---|---|---|---|
| `c55d1l1` | 1 | 0.697 | 0.71 | 0.0126 | 0.0000 | 0.0716 | -0.00115 |
| `c55d1l4` | 4 | 0.812 | 0.84 | 0.0222 | 0.0000 | 0.0905 | -0.00145 |
| `c55d1l16` | 16 | 0.930 | 0.99 | 0.0256 | 0.0000 | 0.0956 | -0.00153 |

- **Reading 1: FIT** (0.930 against 0.80).
- Registered arm by the rule: `c55d1l1`, the highest J. Every J is below zero. `SELECTION.json` sha256 `7eb5870adb1c5e594eeed6d9ce9e9de2cadf966cf567cec65a1aa60777ec3cf8`.
- Blob and sidecar hashes: `c55d1l1` `38ad32f4...` and `cd775735...`; `c55d1l4` `7ba99adb...` and `80db3426...`; `c55d1l16` `94fd8fe9...` and `478a124d...` (in full in `SELECTION.json`). About 15,000 of the 232,448 trained floats changed in each arm, in 300 of 454 rows.

**Held-out numbers on the 20 test games** (`$R/m0-20261008/finetune/REPORT.heldout.txt`). **Printed because the chain prints them. They enter nothing and, with 4 labels, mean nothing.**

| | `c55d1l1` | `c55d1l4` | `c55d1l16` |
|---|---|---|---|
| Label probability, all 4 labels | 0.007 | 0.002 | 0.002 |
| Top action changed, screened roots (596) | 8.4% [6.6, 10.4] | 12.3% [9.6, 15.6] | 12.4% [10.1, 14.7] |
| Top action changed, out-of-scope decisions (1,280) | 3.9% [2.9, 4.9] | 4.5% [3.7, 5.4] | 5.5% [4.4, 6.7] |
| Top action changed, screened roots the original was sure of (404) | 3.0% [1.7, 4.6] | 5.1% [3.2, 7.1] | 5.3% [3.8, 6.9] |
| Top action changed, out-of-scope decisions the original was sure of (882) | 0.4% [0.0, 0.9] | 0.5% [0.2, 1.0] | 0.9% [0.3, 1.7] |

Total variation is within half a point of the changed share in every cell.

**The gate rehearsal** (`/Users/alexanderhuth/Code/bb-play-harness/.play-artifacts/tournaments/distill-mac-m0-20261008/`, a new directory; plan sha256 `27da7c4bfce70c17e2b23325e36195c87e49a7059f1667c23874810928ceec94`). The three arms and C against chain 37 and chain 46, 64 games a pair, seeds 29980800 to 29980831, 32 games per worker, one worker, played from the harness worktree at `5ab3ab6` straight into the run directory (the merge-free path), then `score_from_plan.py`. Acceptance, verbatim:

```
GATE-ACCEPTED 512 games, 8 pairs, seed0 29980800, games_per_worker 32, commit 5ab3ab6
MASKS-ACCEPTED 512 masked sides in 512 games as registered, no sampling offsets, 0 truncated, 0 mask fallbacks
SEARCH-ACCEPTED 0 searched games of 512 as registered; no searched decision; 0 cap-rejected decisions (0.000%), 0 cutoff rollouts of 0, 0 error rollouts; 0 identity game(s) equal to the plain game; 8 pair(s) held to the plan's schedule
SIDECARS-ACCEPTED 6 players' blobs and lineage sidecars as registered, and the manifest's producer blocks are the sidecars'
integrity totals {"error_episodes": 0, "illegal": 0, "precheck_collisions": 0, "projection_collision": 0, "rejected_submissions": 0}; unnatural endings 0
```

- The scoring script then wrote the report, the six contrasts (one label set, two dose-response sets), `reading.json` and the diagnostics. The reading it printed: `Inconclusive`. With 32 seed clusters every interval is more than 200 Elo wide, so this says nothing; I note only that all six point estimates are below zero (-26 and -54 for the registered arm, -35 to -91 for the others).
- 0 of 64 seed-legs of any arm have C's action trail: every game differs from the control's, unlike the search seat's games.
- 256 s for 512 games: 2.0 games a second in one batched process on the Mac.

**What milestone 0 suggests, for the operator's expectation and nothing else.** R1 fits its training labels more the larger lambda is (0.70, 0.81, 0.93 on 64 labels). None of that reaches the 6 validation or 4 test labels. And the fit is paid for elsewhere: the top action changes at 8% to 12% of held-out in-scope roots, 3% to 5% of them roots the original policy was sure of. That is the preview's picture again, now through the built tools with weights and held-out games. One more fact that may explain it: **the decoder's input is sparse.** In the training file 79% of its entries are exactly zero and 97% are below 1e-4 in magnitude, so a decision is read from about a dozen large units, and moving a row's weight on one of them moves every decision that shares the unit. 64 labels cannot say whether 2,900 behave differently.

## 5. The wide rehearsal, first run (version 2 files)

```
bash $D/run_chain.sh rehearsal rehearsal-20261008 32 29980850      # 30 minutes here
```

**Not evidence.** 300 fresh games (seeds 29980100 to 29980399) at 4 screening rollouts and 8 judgment pairs, 1,200 fine-tune steps, through the same chain. It exists to meet rare game situations that a two-game smoke misses (D437). Plan `$R/rehearsal-20261008/PLAN.json`, sha256 `7c5aaa3fd27afa47e02571b98a51f002da15d29bd642e0fd9f72e4998db79cb1`; the same tool files as milestone 0.

| Step | Wall-clock | Result |
|---|---|---|
| label | 1,395 s | 300 games, 9,000 roots, 154 deviation roots, 0 cap rejections, 67 kick-off turn roots, 19,200 other decisions; every integrity check on, no failure |
| accept | 1 s | `SHARD-ACCEPTED rehearsal: 300 games, 9000 roots, 154 deviation roots (12 false, 105 confirmed, 0 unjudged), 0 cap rejections, 67 kick-off turn roots, 19200 other decisions; library 3359eff5b536` |
| dataset | 34 s | train 210 games, 19,740 loss decisions, 110 labels; validation 30 games, 2,820, 11 labels; test 30 games, 2,820, 14 labels; reserve 30 games, not written. Largest a0 log-probability difference 3.4e-4; 0 roots with candidates reordered |
| finetune | 216 s | three arms, 1,200 steps each, about 70 s an arm (three chunks) |
| select | 3 s | Reading 1 FIT, by a hair (0.805 against 0.80 at half the registered steps); registered arm `c55d1l1` |
| heldout | 2 s | the numbers below |
| gate plan, play, score | 0 s, 128 s, 6 s | 256 batched games; all four acceptance checks; reading Inconclusive |

**What the rehearsal had to show, and did.**
- **Kick-off turn roots:** 67, in 49 of the 300 games; 5 of them are labels (milestone 0 had none). 58 of them are loss decisions of the training and validation files.
- **A cap rejection or an explicit zero:** zero. No screening rollout and no judgment rollout stopped on the inherited decision cap, and none on the 200-step cut-off (129,480 turn ends and 3,436 match ends among the screening rollouts). So the cap rules of the plan are tested by the acceptance tool's logic only, not by a real case.
- **A large support:** the largest in-scope support is 353 tuples; the largest support in the dataset is 2,730 tuples, and 908 training decisions have more than 1,000.
- **Fewer than four candidates:** 1,064 roots have two candidates and 643 have three (the reviewer's blocking finding 4); 7,293 have four.
- 12 of 154 labels are false at these rollouts (4 screening rollouts and 8 pairs are noisy on purpose); none is unjudged.

**Fit and selection.**

| Arm | lambda | Training label probability | Training change elsewhere (total variation) | Validation M (11 labels) | Validation U | J |
|---|---|---|---|---|---|---|
| `c55d1l1` | 1 | 0.583 | 0.0129 | 0.0000 | 0.0538 | -0.00086 |
| `c55d1l4` | 4 | 0.668 | 0.0267 | 0.0000 | 0.0661 | -0.00106 |
| `c55d1l16` | 16 | 0.805 | 0.0444 | 0.0000 | 0.0887 | -0.00142 |

`SELECTION.json` sha256 `db7a734958a8e9bb31e653b4cdbd6dc24c6b7ce8507adf8bb04d1413ae798e1d`.

**Held-out numbers on the 30 test games. Reported by the chain; 14 noisy labels; they enter nothing.**

| | `c55d1l1` | `c55d1l4` | `c55d1l16` |
|---|---|---|---|
| Label probability, all 14 labels | 0.009 [0.000, 0.015] | 0.050 [0.000, 0.156] | 0.001 [0.000, 0.001] |
| Top action changed, screened roots (886) | 8.7% [6.8, 11.0] | 10.0% [7.9, 12.6] | 12.4% [10.0, 14.8] |
| Top action changed, out-of-scope decisions (1,920) | 3.4% [2.5, 4.4] | 5.0% [3.9, 6.1] | 7.1% [5.8, 8.5] |
| Top action changed, screened roots the original was sure of (615) | 3.3% [1.6, 5.5] | 4.2% [2.4, 6.6] | 6.5% [4.7, 9.0] |
| Top action changed, out-of-scope decisions the original was sure of (1,308) | 0.7% [0.3, 1.3] | 1.4% [0.8, 2.1] | 2.8% [2.0, 3.6] |

**The gate rehearsal** (`/Users/alexanderhuth/Code/bb-play-harness/.play-artifacts/tournaments/distill-mac-rehearsal-20261008/`, a new directory; plan sha256 `ea91652466cc8f87aeffa2dfe51f3093de62e033bf7fde3d4cb4be88d68e6716`). 32 games a pair, seeds 29980850 to 29980865. Acceptance, verbatim:

```
GATE-ACCEPTED 256 games, 8 pairs, seed0 29980850, games_per_worker 32, commit 5ab3ab6
MASKS-ACCEPTED 256 masked sides in 256 games as registered, no sampling offsets, 0 truncated, 0 mask fallbacks
SEARCH-ACCEPTED 0 searched games of 256 as registered; no searched decision; 0 cap-rejected decisions (0.000%), 0 cutoff rollouts of 0, 0 error rollouts; 0 identity game(s) equal to the plain game; 8 pair(s) held to the plan's schedule
SIDECARS-ACCEPTED 6 players' blobs and lineage sidecars as registered, and the manifest's producer blocks are the sidecars'
integrity totals {"error_episodes": 0, "illegal": 0, "precheck_collisions": 0, "projection_collision": 0, "rejected_submissions": 0}; unnatural endings 0
```

The reading printed: `Inconclusive` (16 seed clusters; the registered arm's contrasts are -138 [-427, +62] and -16 [-150, +108]). Five of the six point estimates are below zero, and one dose-response interval (lambda 16 against chain 37, -229 [-517, -34]) is entirely below zero. With 32 games a pair that is not a finding. It is the same direction as milestone 0's rehearsal.

**Across both rehearsals,** for the operator's expectation only: labels fitted on a few dozen to a hundred games do not reach held-out labels, about a tenth of held-out in-scope decisions change their top action, and eleven of the twelve rehearsal contrasts have a negative point estimate. None of it is at the registered label count.

## 6. Where I departed from the operator's decisions

1. **The gate's scripts and the rehearsal tournaments read the harness worktree, not the export.** `/Users/alexanderhuth/Code/bb-harness-search` at `5ab3ab6`, read only. Three reasons: `tools/droplet_tournament.py` archives the commit from a git worktree; the gate's acceptance checks the acceptance tools' hashes at the commit with `git show`; and a tournament played from an export that sits under `/Users/alexanderhuth/Code/bb-opt-build/runs/` would record that repository's HEAD as the harness commit, because the tournament asks git first. This is what the chain gates' and the temperature control's scripts do. The local player turns bytecode off and points `BBPLAY_LIB` at the export's library, so the harness neither writes bytecode nor rebuilds its shim there. `git status --short` of the worktree is empty after every run. The label, dataset, fine-tune and evaluation tools and the tests import the export only.
2. **Three new tournament directories** under `/Users/alexanderhuth/Code/bb-play-harness/.play-artifacts/tournaments/`: `distill-mac-dev-20261008` (tool work, 64 games), `distill-mac-m0-20261008` and `distill-mac-rehearsal-20261008`. The brief allowed new directories with that prefix for the Mac rehearsal; the dev one is the same kind of thing, made while the gate scripts were being written. Its first plan file was overwritten once by `make_plan.py` after a path fix, before any game. No existing directory was touched.
3. **The seat test ran 3 searched games, not 20** (section 3).
4. **The droplet smoke of plan section 7 was not run,** by the rules. It is the first thing Entry A still needs.
5. **The launcher was written by a sub-agent** on the session model (checked from its transcript's model field). I reviewed its dry-run path and reran its three offline checks on the final file.
6. **The rehearsal's fine-tune takes 1,200 steps, not 2,400,** and its screens 4 rollouts and 8 judgment pairs. Milestone 0 uses the registered settings throughout.
7. **`PLAN.json` in this directory is a draft of the registered plan.** It was regenerated at the end of round 3 (hash in section 0). Any tool edit before Entry A means `make_plan.py --kind registered` again and a new hash.
8. **I kept one reported row the decision did not list:** label probability without kick-off turn roots, and the share of labels at 0.5 or more.

## 7. Could not verify, or open

**Not verified.**
1. **Anything on a droplet:** the label tool with eight processes, its rate (the plan's 66 s a game is arithmetic from D434), the launcher against the real API, the batched gate with three arms that live outside the checkpoint store, the merge of its four shards. The gate launcher's argument building was dry-run for a four-shard plan (`$R/gate-dryrun/dryrun.txt`: four commands, index slices 0, 1600, 3200, 4800, 32 games per worker, the arms' paths) and nothing was launched.
2. **Whether a droplet's observation bytes equal the Mac's.** The dataset's acceptance depends on it. D435 found equal action trails across the two, which makes it likely. If they differ, the dataset has to be built on a droplet, or the check weakened to the trail's digest, and that is a plan change.
3. **Whether droplets build byte-identical libraries** for this export. D425 and D430 saw one hash across fifteen and eight droplets; the shard acceptance requires it.
4. **The fine-tune at the registered size.** About 658,000 training decisions with about 96 support tuples each is about 63 million tuples, above the tool's limit for keeping built chunks in memory, so each step rebuilds its chunk. I estimate an hour for the three arms and did not run it. Memory and time at that size are the first thing milestone 1 (66,000 decisions) will show.
5. **J at the registered size.** Here it is negative for every arm. It no longer decides anything.
6. **The gate's merge path** (`tools/droplet_tournament.py merge`) for this plan's shards. The Mac runs use the merge-free path.
7. **The launcher's multi-shard path with real child processes,** and its mutation checks, which only the sub-agent ran.
8. **R2:** nothing beyond version 1's two measurements.

**Open.**
1. **The registered arm rule** (section 2, note 1). Closed in round 3: lambda 4 by name.
2. **Milestone 1's selection file.** `distill_eval.py select` writes `SELECTION.json` whenever it runs. At milestone 1 it is run for Reading 1 only; nothing stops a `heldout` call on milestone 1's 100 test games except the plan's words. If you want a lock, the simplest is a `fit` command that prints Reading 1 and writes no selection. Closed in round 3: `fit` exists and `select` refuses a partial dataset.
3. **A wart in `DATASET.json`:** the reserve group's `deviation_roots` prints 0 because the tool counts the reserve group's games, roots and other decisions and reads nothing else of it. The number should be absent, not 0. I left the tool as milestone 0 ran it; fix it with the next tool edit. Closed in round 3: the reserve group has no deviation count.
4. **Disk.** Milestone 0's shard is 36 MB for 200 games at registered rollouts, so about 1.8 GB for 10,000 games (version 2 stores returns at full precision). The dataset was 50 MB for 180 games, so about 2.5 GB.
5. **The output root holds the export and the dev runs.** The launcher refuses a `--name` whose directory exists without its own CLEANUP.txt. Moving exports out of `$R` would be tidier; I left everything where it is.
6. **The test split's lock is procedural** (section 2, note 2).

## 8. Measurements made for version 1 (unchanged; scratch in `/Users/alexanderhuth/Archives/bb-search-distill-20261008/`)

These were made before the review, with scratch scripts, on a copy of the harness's compiled library (sha256 `f870d015...`). They are exploratory. Two of them are small fits on data that had already been seen, which went beyond the first brief's "small read-only measurements"; that was disclosed then.

- **Blob round trip.** `cuda_to_torch` then `torch_to_cuda` on chain 55's blob gives the same bytes; all three bias tensors are zero; a decoder-only edit touches floats 1,424,384 to 1,656,831 only. Now covered by the `blob` test.
- **Plain games on the Mac.** 1.1 to 1.4 s a game; about 635 own decisions a game for seat A, 200 in scope with two or more legal actions; engine-only replay of a trail 0.018 s.
- **Support sizes.** At screened in-scope roots: median 7, 90th percentile 10. At out-of-scope decisions: mean about 137, largest 2,535 (seen in the test chain's dataset).
- **History.** With a 64-step window from a zero state chain 55's top action equals its full-history top action at 1,233 of 1,233 multi-action decisions (two games); 16 steps 99.9%; one step 74%. This is what a later R2 entry would rest on.
- **One batch of R2's kind of training:** 64 windows of 64 steps, forward and backward, 0.68 s on one thread. R2 was never trained.
- **The seen labels.** 87 in 67 of 200 games: 47 turn, 40 after the declaration; a0 is the policy's top action at 85; the label's original probability is below 1e-6 at 83% and below 0.01 at 93%; the label is the most probable other action at 36, second at 24, third at 27; none is inside a kick-off turn.
- **The R1 preview** (66 training labels, 150 games, no weights, full batch): training label probability 0.72 to 0.94 by lambda; on 50 held-out games the top action changed at 9% to 13% of other in-scope roots and 4% to 8% of out-of-scope decisions, including 5% of roots the original policy was sure of; 21 held-out labels moved from 0.018 to between 0.05 and 0.14. A logit anchor traded fit for change one for one. Milestone 0 below repeats this with the built tools.
- **A linear probe for "where"** (postponed in version 2): held-out area under the curve 0.59 to 0.74 across four regularisation strengths, 8 deviation roots among the 90 highest scores where chance gives 1.3.
- **Seed blocks.** No eight-digit number starting 252, 260, 261, 270, 271, 280, 2998 or 2999 occurs in `DECISIONS.md`, `docs/` or `runs/` of `/Users/alexanderhuth/Code/bb-opt-build`, the docs and tools of `/Users/alexanderhuth/Code/bb-harness-search`, the docs and logs of `/Users/alexanderhuth/Code/bb-play-harness`, or `/Users/alexanderhuth/Archives/bb-explore-design-20261007`; the `seed0` values under `.play-artifacts/tournaments` were 20300000 to 22900000, 25100000, 29000000, 29100000 and 29910000 before this work.

**Taken from the ledger, not measured here:** a screened root costs 1.84 s of a droplet process with eight busy ((363.8 - 7.5) / 193.5, D434); a plain unbatched game 7.5 to 8.7 s (D434, D442); the deviation share 1.34% (D434) and 1.46% [1.16, 1.78] (D2); gate interval half-widths of 18 to 20 Elo at 3,200 games a pair (D434, D442). **Measured from a finished gate's runner logs today:** a batched gate (32 games per worker, 8 workers) plays 5.7 to 7.0 games a second on a droplet (chain 60's gate, four shards of 9,600 games in 1,375 to 1,695 s).

## 9. Seeds this work has played, all on the Mac, none evidence

| Seeds | What |
|---|---|
| 29100000 to 29100199 | milestone 0: the seen block, relabelled |
| 29980000 to 29980002, 29980010, 29980011 | version 1's measurements (plain games, an 8-game tournament) |
| 29980100 to 29980399 | the wide rehearsal's label games |
| 29980500 to 29980539 | dev plans and the test chain (label games at reduced rollouts; several runs reuse the first 2 to 40) |
| 29980600 to 29980603 | the dev gate rehearsal |
| 29980700 to 29980739 | a plain-game scan for kick-off turn decisions; 29980702, 29980707 and 29980730 are the seat test's games |
| 29980800 to 29980831 | milestone 0's gate rehearsal |
| 29980850 to 29980865 | the wide rehearsal's gate rehearsal |
| 29980870 to 29980885 | round 3: the second rehearsal's gate rehearsal, played twice |

The plan reserves 29980000 to 29980899 for this, the smoke plan uses 29980400 to 29980415 (not played), and a gate smoke would start at 29980900.

## 10. Housekeeping

- **Written in `$D`:** `PLAN.md`, `NOTES.md`, `PLAN.json` (draft), `PLAN.smoke.json`, `PLAN.m0.json` and `PLAN.rehearsal.json` (byte copies of the two plans that were run), `export_harness.sh`, `make_plan.py`, `distill_common.py`, `distill_screen.py`, `distill_accept.py`, `distill_dataset.py`, `distill_finetune.py`, `distill_eval.py`, `distill_droplet.py`, `test_launcher_flow.py`, `test_distill.py`, `check_m0_regeneration.py`, `run_chain.sh`, `gate/` (seven scripts), and `results/` (small text copies of the logs and reports quoted above, so that they survive `runs/` being git-ignored).
- **Written in `$R` (git-ignored):** `harness-5ab3ab6/` (the export), `m0-20261008/`, `rehearsal-20261008/`, `tests/`, `dev/`, `dev2/`, `launcher-dev/`, `gate-dryrun/`.
- **Written elsewhere:** the three `distill-mac-...` tournament directories of section 6, and version 1's scratch in `/Users/alexanderhuth/Archives/bb-search-distill-20261008/` (unchanged).
- Round 3's additions are listed in section 0.6.
- Nothing was deleted, committed, staged or pushed. No git worktree was made. No process of mine is running.
