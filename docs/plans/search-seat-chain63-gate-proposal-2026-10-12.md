# Step 0, Form A: the search seat on chain 63. Registration proposal and compatibility assessment (2026-10-12)

**Status: a proposal by the operator, for the owner. It registers nothing, changes no code, plays no game and ran nothing on the rig beyond reads. D486 permits exactly this document; implementation, the smoke and the gate wait for the owner's decision and their own reviewed entry. The diff below exists in this document only. Codex reviewed it before it was committed (`.codex-reviews/step0a-proposal-review.md`); section 10 says what the review changed.**

Labels: **[hypothesis]** the operator's judgment; **[ledger]** read from `DECISIONS.md` or a doc in this repository; **[code]** read from source at the commit named; **[read]** read by the operator on 2026-10-12 and not verifiable from the repository; **[estimate]** a planning extrapolation whose error bounds are unmeasured; **[proposal]** the operator's choice, open to the owner.

## 1. What the owner is asked to decide

1. **Go or no go** on Step 0, Form A ("go 0A"). Go means, in this order and each under a reviewed entry: the rig-runner change of section 3 with its tests, a smoke, the registration with the plan's hash, the gate.
2. **Size:** 1,600 games a pair (the proposal; about two days of idle rig at D434's rate for chain 55 + m1, which is a planning reference and no bound, since the rate for chain 63 + m1 on the rig is unmeasured) or 3,200, about twice the cost, giving roughly 80% probability of both intervals clearing zero if the true margin over temperature 0.5 is +30 Elo against each opponent under section 6's approximation.
3. **What a Positive means:** the searched player becomes a play-time option at its measured cost, as D434 did for chain 55 + m1 (the proposal, with the condition in section 5), or a Positive only permits a later proposal.
4. **Restart policy:** whole replay after a host restart (no extra code), or a `resume` command in the rig runner (extra code; section 7).

## 2. The gate proposed

- **Players** [proposal, as D486's design has Form A]. All four chain 63 players are the same checkpoint blob (`9c9f0ce8...`, lineage sidecar `2fcad24d...` [read: sha256 of the Mac's copies]).
  - **S** = chain 63 + m1 + the search seat at D430's setting: scope turn-level and the first decision after the own declaration; a0 and up to three most probable other actions; 16 rollouts each on common random numbers; stop at the end of the own team turn, the end of the match or 200 steps; deviate on a paired mean gain above 0.10 and above two floored standard errors; reward manifest `r0_poss_half` (`433c7920...`), gamma 0.999; in rollouts both sides are played by chain 63 under m1 [ledger: D430].
  - **C1** = chain 63 + m1. **C0** = chain 63 plain. **T** = chain 63 + m1 at per-head temperature 0.5 (D435's meaning of temperature: every head's logits divided by T before masking). **I** = S with delta infinity, the identity player.
  - Opponents chain 37 (`268f1db0...`) and chain 46 (`8eee9ac1...`), plain, as in every gate since D418.
- **Pairs.** S, C1, C0 and T, each against chain 37 and against chain 46: eight pairs of 1,600 naturally completed games, kick-off starts, both legs of every seed, temperature 1 except T, **one game per worker for every pair**. Identity: I against chain 37 on the first 10 seeds, 20 games, whose plain references are C1's games against chain 37 on those seeds. 12,820 games, 3,220 of them searched.
- **Seeds.** Candidate block 25800000 (engine seeds 25800000 to 25800799 for every pair). Searched for as `25800000` and `25,800,000` before this proposal was written: no occurrence in the ledger, STATUS.md, `docs/`, `tools/` or `.codex-reviews/` of this repository; none of the 263 `PLAN.json` and `manifest.json` files under the tournaments directory has a `seed0` in 25800000 to 25899999 (the blocks in use between 25000000 and 26100000 are 25100000, 25300000, 25400000, 25600000 and 25700000); no file under `docs/`, `tools/` or `play_harness/` of the 52 `bb-*` directories under `~/Code` names it, the mask and search harness worktrees among them; no plan, manifest, script or text file under the rig's gate directory names it [read]. That is a bounded search and no proof that no undocumented run used it. Smoke block candidate 29990000, searched the same way with no occurrence (29900000 to 29980900 hold earlier smokes and probes).
- **Harness.** `5ab3ab6` on `feat/search-probe-20261007`, worktree `~/Code/bb-harness-search`, clean at that commit [read]. It is a descendant of the mask harness `7d0d547`. No harness file changes in Form A.
- **Why the reward manifest is the right one.** The seat pins `r0_poss_half` by the digest `433c7920...`, which its source calls the manifest chain 55 trained on [code: `play_harness/search.py:437-439`]. Chain 63's rung is the arm `r0_poss_half` at gamma 0.999 [ledger: D448, D479]. The manifest file has the same sha256 (`16900416...`) in the search worktree, in this repository and in the rig's training checkout [read]. The registration re-checks this and records it.
- **Statistic.** Decisive-Elo with 95% seed-cluster intervals by `paired_contrasts.py` (sha256 `722ece95...`, 2,000 replicates, generator seed 0), for each opponent: S minus C1 (the label), S minus C0, S minus T, and, descriptive, T minus C1 and C1 minus C0. Ten contrasts, nominal intervals, no adjustment across the family.

## 3. Compatibility assessment and the rig-runner change

**What works today at `5ab3ab6`** [code]:
- One unbatched plan can hold S, C1, C0, T and I as five names for one blob. `tournament.player_specs` requires a mask, sample mode and temperature 1 of the searching player only; T's temperature and C0's empty masks are allowed beside it. `tournament_argv` already takes `search=` and `index0=`, and `verify_run` already takes the expected search mapping.
- The gate's scripts exist: the temperature control's set (`docs/search-probe-2026-10-07/tctl/`: `accept_from_plan.py`, `score_from_plan.py`, `gate_diagnostics.py`, `paired_contrasts.py`, `make_plan.py`) accepts masks, temperatures and search settings together and runs the three acceptance tools; its replay check is switched by a `reference` block the new plan would not have. For this gate the generator must drop its reference-gate argument and reads, omit the `reference` block and `reference_pairs`, write S's and I's complete settings and the search acceptance block, this gate's checkpoints, players, pairs, contrasts and diagnostics, whole-pair rig shards, and the changed `rig_gate.py` as the launch script by its hash; each of the five contrast sets gets its own output directory. The launcher is replaced by the rig runner.

**What does not work** [code: `docs/rig-gates-2026-10-09/rig_gate.py`, sha256 `ba494088...`]:
1. `shard_spec` forwards masks and ignores a player's `search` and `temperature`. S and I would be played plain and T at temperature 1.
2. `cmd_start` calls `tournament_argv` without `search=`.
3. `cmd_collect` calls `verify_run` without the expected search mapping, so a searched shard would be refused at collection even if 1 and 2 were repaired.
4. `verify_run` does not check temperatures at all; only `tools/gate_acceptance.py` (through the plan's `temperatures` mapping) and `tools/search_acceptance.py` (through the plan's player specs) do, at scoring. `accept_from_plan.py` derives `gate_acceptance`'s temperatures mapping from `players` and passes the original plan to `search_acceptance`, which independently reads modes and temperatures from that same block. For a valid Form A plan their expectations agree; the smoke exercises both checks.
5. The mask harness's `tournament_argv` and `verify_run` have no `search` or `index0` parameter [code: `bb-harness-masks/tools/droplet_tournament.py:172, 379`], so a changed runner must pass them only when a plan has a searching player, or the plain gates' procedure breaks.

**The proposed change, as a diff against the registered file. It is not applied anywhere.** The changed file would be a new registered file (for example `docs/rig-gates-2026-10-12/rig_gate.py`, with its own sha256 in the plan's launch block); the 2026-10-09 file stays byte for byte, so every earlier gate's `cmp` still holds.

```diff
@@ def shard_spec(plan, shard, runner):
-    checkpoints, bots, extra = {}, {}, []
+    checkpoints, bots, extra, search = {}, {}, [], {}
     for name in names:
         spec = plan["players"][name]
         if "bot" in spec:
             bots[name] = spec["bot"]
             continue
         checkpoints[name] = os.path.join(store, spec["checkpoint"], BLOB)
         if spec.get("masks"):
             extra += ["--mask", f"{name}={','.join(spec['masks'])}"]
+        temperature = float(spec.get("temperature", 1.0))
+        if temperature != 1.0:
+            extra += ["--temperature", f"{name}={temperature}"]
+        if spec.get("search"):
+            s = spec["search"]
+            search[name] = runner.parse_search(f"{s['k']}:{s['n']}:{s['delta']}")
     pairs = runner.plan_pairs([runner.parse_pair(",".join(p)) for p in raw],
                               set(checkpoints) | set(bots), None)
+    if search:
+        refusal = runner.search_refusal(search, checkpoints, bots, pairs,
+                                        plan["games_per_worker"], extra)
+        if refusal:
+            raise GateError(f"{shard}: {refusal}; nothing started")
     sha = {name: plan["checkpoints_sha256"][plan["players"][name]["checkpoint"]] for name in checkpoints}
+    temperatures = {name: float(plan["players"][name].get("temperature", 1.0)) for name in checkpoints}
     return {"checkpoints": checkpoints, "bots": bots, "pairs": pairs, "extra": extra,
-            "checkpoint_sha": sha, "tasks": runner.expected_tasks(pairs)}
+            "checkpoint_sha": sha, "tasks": runner.expected_tasks(pairs),
+            "search": search, "temperatures": temperatures}

@@ def cmd_start(args):
+        more = {"search": s["search"]} if s["search"] else {}
         argv = runner.tournament_argv(s["checkpoints"], s["bots"], s["pairs"], plan["seed0"],
                                       args.workers, out_dir=runner.REMOTE_OUT, extra=s["extra"],
-                                      games_per_worker=plan["games_per_worker"])
+                                      games_per_worker=plan["games_per_worker"], **more)

@@ def cmd_collect(args):
+        more = {"search": spec["search"]} if spec["search"] else {}
         problems += runner.verify_run(manifest, complete, games, plan["harness_commit"],
                                       spec["checkpoint_sha"], spec["pairs"], plan["seed0"],
-                                      bots=spec["bots"], games_per_worker=plan["games_per_worker"])
+                                      bots=spec["bots"], games_per_worker=plan["games_per_worker"],
+                                      **more)
+        if any(p.get("search") for p in plan["players"].values()):
+            got = {name: (manifest.get("players") or {}).get(name, {}).get("temperature")
+                   for name in spec["temperatures"]}
+            if got != spec["temperatures"]:
+                problems.append(
+                    f"manifest temperatures {got} != registered {spec['temperatures']}")
```

Also in the change: the docstring's first line and "beside the trainer" wording say what the tool now does; nothing else moves. The temperature check at collection runs only for a plan in which some player searches (the whole plan, since T can sit in a shard with no searching player), so collection of the plain gates is unchanged as well as their command lines. The source writes `manifest["players"][name]["temperature"]` for every checkpoint player [code: `tournament.player_specs`]; the collection test uses a fixture with that source-defined shape, and the smoke verifies the field in the produced manifests. The reviewer read the displayed `extra`, `parse_search`, `--temperature` and conditional `search=` lines against both runners and found no correction needed for Form A; `cmd_status`, the worker cap, the queue, the pinned torch 2.14.0 and NumPy 2.5.3 and `SYNC_PATHS` (which carries the reward manifest) need no change. The seven checkpoint names (five for chain 63's blob, two opponents) are uploaded once each, by name, not deduplicated by blob.

**Tests the change needs** (added to `test_rig_gate.py`; all on the Mac, no rig, no game):
1. **No change for plain gates:** for an existing registered plan at the mask harness (chain 70's), `start --dry-run` prints byte for byte what the registered runner prints. This is the regression that protects every later plain gate.
2. **Search is forwarded:** for a Form A plan the dry run's command line holds `--search S=4:16:0.1`, `--search I=4:16:inf` and both players' `--mask NAME=m1`, in the shards that hold those players and in no other.
3. **Temperature is forwarded:** `--temperature T=0.5` appears for T and for no player at temperature 1.
4. **Refusals before anything is created:** a searching player with no mask, with a non-unit temperature, or in a plan with more than one game per worker makes `start` exit 2 with the runner's own refusal text, and no `rig_start.json` is written and nothing is made on the rig. An explicit temperature of 1.0 on a searching player is accepted.
5. **Collection holds the run to the plan:** `verify_run` through the changed call refuses a manifest with no search setting for S, with another k, n or delta, and with a search setting for a player that should not search; the temperature check refuses a manifest in which T is at 1 or C1 is at 0.5; a matching manifest passes.
6. **The identity player's infinite delta** survives the round trip from the plan to the command line to the expected mapping (`"inf"` in all three).
7. **Also needed, by the review:** collection and `status` against the older mask runner (no `search` keyword reaches it); S, I and T placed in the right shards and no other; the plan's search block validated whole; the coverage check refusing a missing or duplicated pair; each of the five contrast sets writing to its own directory (`paired_contrasts.py` writes the same opponent file names for every set); a provenance failure refused.

The smoke (section 8) is the end-to-end test on the rig.

## 4. Acceptance, before anything is scored

As D430 and D435 registered it, with the rig runner in the launcher's place. The registration fixes by hash: the plan; the checkpoint blobs and their lineage sidecars; the reward manifest (digest `433c7920...` and the file's sha256); the harness commit; the runner `tools/droplet_tournament.py` (`bb0ece1c...` at `5ab3ab6`), `tools/gate_acceptance.py` (`71cb6d6b...`), `tools/search_acceptance.py` (`2b429a42...`); the changed `rig_gate.py`; the gate's five scripts. The registration records full blob and lineage-sidecar hashes for all three checkpoint identities. The reused runner checks that a sidecar exists and does not enforce its registered hash, so the entry must specify the local and uploaded-sidecar verification procedure or include that check in the reviewed runner change. Torch and NumPy versions are pinned by the harness runner, the actual Python version and runtime are recorded, and the newly built library's hash, which cannot exist before the start, is fixed in the start receipt before any game and held equal across shards by the merge.
- `tools/gate_acceptance.py`: the nine pairs and their game counts, the seed block, both legs of every seed exactly once, one game per worker, the commit, each player's checkpoint hash, sample mode, T at 0.5 and everyone else at 1 in the manifest and on its own side of every game, natural endings, every integrity counter zero.
- `accept_from_plan.py`: each player's masks in the manifest and on its side of every game (m1 for S, C1, T and I; none for C0 and the opponents), no sampling offset, no truncation, no mask fallback, final status equal to the engine's match-over status, both sides' decision counts positive and adding up, the native kernel, `COMPLETE.json` complete, both acceptance tools at their registered hashes on disk and at the commit.
- `tools/search_acceptance.py`: every record's seats are its pair's and leg's; each player's complete search setting in the manifest and on its side of every game; the reward manifest hash and D430's 13 integrity checks on every searched game; consistent search statistics, no failed rollout, one opponent-view forward per engine step; at most 1% of a pair's searched decisions with a cap rejection (ceiling 0.01); all 20 identity games equal to C1's games on the same seeds and legs in action trail, final digest, log-probability sums, score, steps, rosters and sampling seeds, having run their rollouts.
- The merge requires the same commit, settings, torch, Python and compiled library in every shard.
- **Not checked, as in D425, D430 and D434:** the env's own reward telemetry counters, which the shim does not export; the checks on the emitted rewards stand in for them. Hand-edited records and a seat that ran other arithmetic than it declared rest on the pinned code and its tests.
- **One look.** No outcome, shard report or game record, whole or partial, is inspected or tallied until every shard is collected and the merged run has passed acceptance. `status` prints game counts, rates and log age and no outcome. No early stop and no extension.
- **Unread, never a label:** missing, unaccepted or integrity-invalid evidence; a shard that aborts on an integrity failure or on a real game reaching the 4,096-decision cap; an identity mismatch; a cap-rejection share above the ceiling; a dead queue that the restart policy does not cover; an undefined pair or contrast estimate or interval; an early stop, a failed start, an ordinary job failure, a provenance or library mismatch, or exhaustion of the registered recovery allowance. Integrity and decision-cap failures get no automatic replay; any later action needs a new entry.

## 5. The reading

"Entirely above zero" means the lower end is above 0, "entirely below zero" that the upper end is below 0, and an end equal to zero is on neither side; "inside -20 to +20" includes the ends; decisions use the full-precision values. Each list is applied first match, in the order written, to accepted evidence only.

1. **The label, on S minus C1 against chain 37 and against chain 46 (D430's form).**
   - **Negative:** either interval entirely below zero.
   - **Positive:** both point estimates above +20 and both intervals entirely above zero. This establishes gains above zero, not above +20.
   - **Flat:** both intervals inside -20 to +20.
   - **Inconclusive:** anything else.
2. **S minus T, the temperature control (D435's form, one temperature).**
   - **Temperature 0.5 is better:** either margin's interval entirely below zero. Nothing builds on this search setting for chain 63; temperature 0.5 under m1 is carried to its own entry as a possible free play-time option.
   - **Search beats temperature 0.5 on chain 63 against these two opponents:** both margins' intervals entirely above zero. With a Positive label this permits entries that build on search for chain 63 (labels, a kernel, a larger budget), each with its own entry.
   - **Not separated:** anything else. No entry builds on search for chain 63 until a new entry says how the two are separated. It is no finding that sharpening matches search.
3. **S minus C0, the plain checkpoint the ladder uses.** Both intervals entirely above zero: the searched player is above plain chain 63 against these two opponents. Anything else: reported as measured, no claim. This reading enters the play-time consequence below and nothing else.
4. **Descriptive, no label:** T minus C1 and C1 minus C0 (D465 measured the mask on chain 63 at +14.0 [0.0, +28.0] in its own panel).

**Consequences** [proposal; the owner decides item 3 of section 1].
- **Positive, and S minus C0 entirely above zero against both opponents:** chain 63 + m1 with this seat becomes a play-time option at its measured slowdown, on this checkpoint only, as D434 registered for chain 55 + m1. It changes no training recipe, warm start or evaluation default, and it is no claim about a stronger or foreign opponent. The operator recommends this consequence: a play-time option commits nothing, and a measured option is what a later human-facing series would use.
- **Positive without that:** the seat adds to chain 63 under m1 and is not shown better than the plain checkpoint; no play-time option.
- **Negative or Flat:** this seat setting is not carried further on chain 63, and the ladder of D486's design stops at this setting until a new entry gives a reason. It would not decide the value of another evaluator, scope, budget or student recipe.
- **Inconclusive:** nothing is adopted; a further sample needs a new entry.
- Under every outcome: nothing trains, no recipe changes, and a Positive would support this searched player as a candidate teacher without validating any label.

## 6. Size and what it can show

- D434's contrasts had half-widths of 17.6 to 18.7 Elo at 3,200 games a pair. Scaled by the square root of two, 1,600 games a pair give about 25 to 26 [estimate].
- With a standard error of about 13 at 1,600 games, a true gain of +45 has both intervals above zero in roughly 85 to 90 cases in 100; a true gain of +25 in roughly 25 [estimate: normal approximation, the two opponents treated as independent]. A true margin of +30 over temperature 0.5 reads "search beats" in roughly 40 in 100 and otherwise "not separated". At 3,200 games a pair the last figure is roughly 80.
- These are conditional illustrations and no measured power for chain 63; the standard errors and the dependence between the two opponents' estimates are unmeasured.
- So 1,600 a pair is a screen for the label and a weak test of the temperature margin. **The proposal keeps 1,600** because the label is the question D486's design asks first and the cost doubles otherwise; the owner may choose 3,200.
- The operator's guesses [hypothesis], to be fixed again at registration: label Positive about 50 in 100; "search beats temperature 0.5" about 30 in 100 at 1,600 games; S minus C0 entirely above zero against both about 50 in 100.

## 7. Shards, time and restarts

- **Shards** (whole pairs, each shard a list of pair strings as the runner's present format and coverage check require, with names that sort in the intended order; one queue, one after another): (1) the six plain pairs and the identity pair, 9,620 games; (2) S against chain 37; (3) S against chain 46. A game depends only on the plan, its pair, seed and leg, so the order changes no result.
- **Time** [estimate]. D434 measured about 364 elapsed worker-seconds per searched game for chain 55 + m1 on droplets. Chain 63's lower activation rates when played plain do not justify scaling that cost down for Form A: D465 measured about seven activations a team turn for chain 63 + m1 against plain chain 63 (7.04, against 4.00 plain). Search runtime for chain 63 + m1 on the rig is unmeasured. At the 364-second reference, 3,220 searched games are about 40.7 hours at eight workers and 54.3 at six; a 150 to 364 second range (about 17 to 54 hours) is an illustrative planning scenario with neither end established as a bound, and the authorized smoke supplies the rate the registration uses. Plain games one per worker took 7.5 to 8.7 seconds on droplets; 9,600 over six to eight workers is about two to four hours. Setup, statistics and collection are minutes. Total about 19 to 58 hours on that scenario, about 43 to 58 at the reference rate. The smoke replaces these figures with the rig's own.
- **Workers.** The runner allows 1 to 8 and defaults to 6. With no trainer running the proposal is 8, if the smoke's memory reading allows it (chain 70's plain gate held 2.3 GB over 10 processes with 10.7 GB available; a search seat's memory on the rig is not measured).
- **A host restart** (the ledger records one unannounced restart, D470) kills the queue. Two policies:
  - **Whole replay (no extra code; the operator's recommendation if the smoke projects 30 hours or less).** A dead queue makes the gate Unread and no record of it is read. A new entry replays the whole gate under a new name from a new plan with the same seeds. A new start builds the shim in a new directory; prior rig starts at the same source commit produced different library hashes, and the merge refuses mixed libraries (D470, D472). The present runner has no approved continuation path, so this policy replays the whole gate and reuses no finished shard. The exposure is the whole elapsed time.
  - **`resume` (extra reviewed code; above 30 hours the operator would put this choice to the owner, and a projection alone adopts nothing).** A new runner command that, for a queue found dead after a restart (not for a failed job), keeps each exit-0 shard that passes the registered file, schedule, integrity and provenance verification, replays each unfinished shard whole into a new run directory inside the same gate directory with the existing build (library hash checked equal to the one `start` recorded), never reads a dead shard's partial records, and allows at most two resumes. With it the searched pairs would also be split by game index into slices of 400 games (the plan format and the runner's `index0` exist at `5ab3ab6`), so that during a searched slice one restart loses at most that slice's searched work; during the initial plain-and-identity shard that whole shard is replayed unless it is also subdivided. This needs the sliced shard format, a coverage check for slices, `index0` passed to the command line and to `verify_run`, and tests of each: the present rig runner has none of them. It is a larger change than section 3's, it is specified in the entry that adopts it, and it needs its own reviewed recovery smoke (non-zero index slices, an interrupted queue, kept finished shards, whole replay of unfinished slices, the original library, a single accepted copy of every shard, the two-resume limit).
- **Beside a trainer.** Nothing is registered to train. If a stage is registered later, the gate keeps playing at the lowest priority as the plain gates did, more slowly; the trainer's load statement then applies to that stage.

## 8. The smoke proposed (not evidence; under the owner's go and its own entry)

- **What:** the gate's plan generator and scripts with the changed runner, gate name of its own, seed block 29990000, 32 games a pair for the eight pairs and 4 identity games: 260 games, 68 of them searched. Illustratively about 25 to 60 minutes at eight workers, or 30 to 75 at six, before any separately scheduled profiling [estimate; the rate is unmeasured]. The smoke's first shard holds the gate's full player set, so that its memory reading is the gate's.
- **What it must show before a gate is registered:** the dry run's command lines; the start, the queue, collection, merge, the three acceptance tools and the scoring path all run; the 4 identity games equal C1's; the temperature arm is accepted at 0.5.
- **What it measures:** elapsed seconds a searched game and a plain game at the chosen worker count; searched decisions, deviations and cap rejections a game for chain 63 + m1; resident memory; the projected gate time, which informs the owner's restart-policy and size decisions; the reviewed registration that follows fixes both.
- **Step 1's profile, with it:** a few searched games in one process under a profiler in the smoke's directory, to split the seat's time between engine stepping, sampling, observation construction, forwards and Python overhead. Its games, seeds, output directory and exact command are fixed in the smoke's entry, and profiled games do not supply the unprofiled rate.
- **Reading discipline:** the smoke's contrasts are printed by the scoring path and say nothing at 16 seeds a pair; they are not evidence and are disclosed if seen.

## 9. Limits (D434's and D442's stand)

- Chain 37 and chain 46 are older relatives of chain 63. Nothing here measures a stronger or foreign opponent or a person.
- One seat setting, chosen on exploratory runs on chain 55 (D425's limits). The rollouts stop at the end of the seat's own team turn; the evaluator is the shaped reward plus chain 63's value head; the standard-error floor is the error of one candidate's mean.
- Form A is the seat under m1. It does not say what an unmasked seat would do, and a teacher under m1 yields labels for an m1 player while the ladder trains plain policies (Test 1's arms were valid under m1 only).
- The temperature control is one per-head temperature. It is no test of sharpening in general.
- The intervals are nominal 95% intervals over evaluation seeds, ten of them, with no adjustment.
- Every time figure is an estimate until the smoke.

## 10. What the review changed

Outside review (Codex, `gpt-6.1-sol`, read-only, on the default login) before this document was committed. **One blocking finding, corrected in sections 1, 7 and 8:** the draft scaled the cost of a searched game down by chain 63's low activation rate when played plain, while Form A's searched player is chain 63 + m1, which D465 measured at about seven activations a team turn; the lower end of the time range was unjustified, and at D434's reference rate the gate is about two days. No blocking defect was found in Form A's player layout, the game counts or the displayed forwarding diff, which the reviewer read against both runners. It confirmed from the source that one unbatched plan can hold the five chain 63 names, that the temperature control's script set is a suitable base, the seat's setting against D430, both reachable copies of the reward manifest (sha256 `16900416...`), the reading's order and end rules against D430 and D435, "nine pairs", and the arithmetic of sections 6 and 7. Eleven non-blocking corrections, all applied: how the acceptance wrapper feeds the two tools; the manifest's temperature key is established by source; the temperature check at collection is limited to plans with a searching player; test 4 says non-unit temperature and more tests are listed; what the reused runner enforces about sidecars and when the library hash can be fixed; more Unread conditions; the size figures are conditional on an effect size; why a whole replay reuses nothing; the limits of `resume`'s loss bound and its own recovery smoke; the smoke's time; and that the smoke informs the owner's decisions and does not set them. **The reviewer agrees with Form A as the next whole-game measurement if the owner chooses this direction, with 1,600 games a pair as a fixed-cost screen provided the owner accepts its limited ability to clear the temperature condition, and with the play-time consequence as conditioned. It would not choose `resume` solely because a noisy smoke projection crosses 30 hours;** that threshold now only triggers a question to the owner. Not verified by the review: the rig's state and the operator's reads there, the checkpoint and sidecar files, undocumented seed use, the counts of files searched, and any throughput or memory. The corrected text was not sent back a second time.
