# END_TURN probe: notes for the operator (2026-10-07, 22:15 PDT, after Codex's second pass)

**Nothing was launched. No cloud resource was created, no ssh was made, no commit or branch change was made in any repository, and nothing was deleted. Everything here is uncommitted in `docs/endturn-probe-2026-10-08/`.** Work was done by one agent on the session model, with no subagents.

- **Plan hash:** `PLAN.json` is `c1b98f4eaeb3ddb9e4072b760f626ef9a213121392d09a27028554162cf37902` (four shards; chain 60 not yet added). It is the last line of `PLAN.md`.
- **Smoke plan hash:** `smoke/PLAN.smoke.json` is `548136fac5e6bb316124cfb8c117fc14d23df3382507adb60684810b8f00f7e9`.
- Both plans name every tool file by hash. **Any edit to a tool file, and adding chain 60, changes both hashes:** rerun `make_plan.py` (once plain, once with `--smoke --out smoke/PLAN.smoke.json`) and update the hash line of `PLAN.md` and the smoke command below.

## The smoke shard on a real droplet: the exact commands

```
cd /Users/alexanderhuth/Code/bb-opt-build/docs/endturn-probe-2026-10-08
PY=/Users/alexanderhuth/Code/bb-play-harness/.venv/bin/python
X=/Users/alexanderhuth/Code/bb-opt-build/runs/endturn-probe-2026-10-08/export-06f0a5f   # git-ignored; must not exist yet
bash export_harness.sh $X

# what it would do, no network:
$PY endturn_droplet.py run --name etsmoke --plan smoke/PLAN.smoke.json \
    --expect-sha256 548136fac5e6bb316124cfb8c117fc14d23df3382507adb60684810b8f00f7e9 \
    --harness-export $X --shard chain55 --max-hours 0.5 --max-total-usd 0.2 \
    --dry-run --assume-hourly 0.16667

# the real smoke shard (one droplet, two games on seeds 29940000 and 29940001, 16 rollouts):
caffeinate -ims $PY endturn_droplet.py run --name etsmoke --plan smoke/PLAN.smoke.json \
    --expect-sha256 548136fac5e6bb316124cfb8c117fc14d23df3382507adb60684810b8f00f7e9 \
    --harness-export $X --shard chain55 --max-hours 0.5 --max-total-usd 0.2
```

- Expect about eight minutes and about $0.03; the guard's nominal budget is $0.08 (0.5 h x $0.167), which is not a ceiling if the teardown stalls. It prints the run id, the droplet's name and the cleanup commands first, and writes them to `runs/endturn-probe-2026-10-08/etsmoke/CLEANUP.txt`.
- It ends with `shard chain55 ACCEPTED` and the teardown's `HTTP 404` lines, or with an error and the teardown. Records land in `runs/endturn-probe-2026-10-08/etsmoke/chain55/`.
- A second smoke under the same `--name` is refused (the output directory exists): use `etsmoke2`.
- The same export `$X` serves the registered launch. The registered commands are in `PLAN.md` section 10.

## Second pass: the three blockers and four partials, and what changed

Line numbers in this section are of the files as they are now.

**1. Cancellation could still start paid shards.** Fixed. `run_children` (`endturn_droplet.py:583-628`) records a signal as a cancellation (`:596`), starts no further shard once cancelled (`:604-605`), signals a child whose start the signal interrupted as soon as it is recorded (`:611-613`), waits for every started child, and reports unstarted shards as not started, which makes the run a failure (`:671`). `test_launcher_flow.py:265-320` covers it with a real signal delivered during the second start: the third shard is never started, both started children are signalled and waited for, and the run does not count as a success; and a run without a signal starts all three.

**2. Cap drops did not apply to every reported number.** Fixed. The probe no longer stores means over all rollouts. It stores, per candidate and rollout, what the searcher did after the root action (`continuation_stats`, `endturn_probe.py:442-453`, used at `:468` and `:483`) and whether the forced rule fired (`:482`). The analysis computes the further-activation numbers, the block share and the squares moved over the same valid indices as the returns (`endturn_analyze.py:92-96`) and the forced share over the forced arm's valid pairs (`:122`). Question 2 reads those. Tested with a synthetic capped rollout carrying absurd trail values: they do not enter any number. The plan states the rule (`PLAN.md:49`).

**3. The worst-case spend was not established.** Rewritten as a nominal budget (`PLAN.md:190-198`, the launcher's docstring `endturn_droplet.py:20-27` and `:43-63`, and the text printed at launch `:358-363`). It now says: the budget holds when calls return; the launcher's own ssh and copy calls are bounded by the time left, the harness's key, create, boot-wait and poll calls are not and can overrun inside an attempt; the harness's teardown retries each API call up to 120 times, about 70 minutes and about $0.19 a droplet for one stuck call, with several calls in a row, so no finite worst case is stated; and a dead runner, a lost create or a failed delete leaves a droplet billing until an operator destroys it. The five-shard figure is given as nominal ($2.97 with the teardowns) beside the estimate ($1.58). The harness was not changed.

**4. Acceptance and the identity check.** Fixed. A class of a game is eligible when one of its roots has a turn arm with no capped rollout; the probe counts eligible classes and checked ones (`endturn_probe.py:605`, `:634`, `:666`, `:867`), and acceptance requires the two to be equal and at least one in the shard (`endturn_accept.py:102-108`), in place of "at least one per game". So permitted caps cannot refuse a valid shard, and the one refusal that remains (a shard with no eligible root at all) is in the plan (`PLAN.md:158`, `:167`). The edge under point 10: `identity_check` now returns before running anything when the recorded turn arm has a capped rollout (`endturn_probe.py:575-576`), and the two extra computations pass the turn arm's rollout checks before they are compared (`:584`).

**5. Equal weight per game for the contrasts.** Computed. `combine` carries the per-game estimates through (`endturn_analyze.py:241-256`), every contrast of section 6 is listed again in section 8 with equal weight per game (`:462-466`, `:474-475`), and the JSON has both. The plan says "every estimate and every contrast", and that the readings use the per-decision versions (`PLAN.md:54`).

**6. "All make the standard error larger".** Reworded (`PLAN.md:102-106`): the three match-arm rows are rough forecasts, not bounds; what they leave out usually raises the standard error and dependence can also lower it; I expect them to be too small.

**7. Cleanup commands and the plain statements.** `cleanup_text` (`endturn_droplet.py:284-314`) now takes the invocation: every command carries `--env-file` with the token file the run used, and for a non-default `--state-root` it gives `destroy --id $(cat <state root>/<name>/droplet-id)` and says that `destroy --name` cannot be used (the harness's `destroy --name` reads the default state directory only). Tested for both cases (`test_launcher_flow.py:322-335`). The plan says plainly that power loss, a killed runner, a delayed ambiguous create or a failed delete can leave a droplet billing until an operator destroys it (`PLAN.md:192`), and that recovery by run id is very unlikely to find anything else but is not a proof: first-page listings, a concurrent same-name create (`PLAN.md:189`; docstring `endturn_droplet.py:12-19`).

**Reruns after these changes** (single process, `OMP_NUM_THREADS=1`; outputs in `smoke/`): the two-game smokes at the plan's settings (62 and 56 seconds, no capped rollout, identity roots 6 of 6 and 5 of 5 eligible, returns identical to the previous round); the rehearsal with the smoke plan (both shards ACCEPTED); the registered-mode analysis on the rehearsed shards; the launcher flow test, 23 of 23; both dry runs; `make_plan.py` for both plans.

## The ten points of the first review, and what changed

Line numbers in this section are from the first pass and have moved since; the second-pass section above has current ones.

**Blocking 1, integrity.** Fixed.
- Real game (`endturn_probe.py:297-394`): the engine's return code on every step, the five hard counters after every step and at the end (`:371-373`, `:386-389`), both seats' logits and values finite (`:328-329`), the opponent-view state and value finite (`:331-334`), both seats' rewards finite and within the env's clip threshold (`:374-379`), and a natural match end required, `STATUS_MATCH_OVER` (`:382-385`). A game that ends on the decision cap is no longer taken for a finished game.
- The reward limit is the env's own `bbe_reward_clip_threshold`, read through a new read-only accessor (`endturn_shim.c:63-67`, `endturn_probe.py:177-185`), and both `Rollouts` instances now carry it (`:735-738`). It is 1.0 for `r0_poss_half`.
- Rollouts: `audit` (`:413-428`) makes a failed rollout, or a stop the arm does not allow, an `IntegrityError`. The decision-cap stop is the one permitted loss; it is counted per arm (`capped_rollouts`, `:664`, `:871`) and its rollout index is recorded as dropped.
- Fail-fast: an `IntegrityError` ends the worker with exit 2 (`:756-758`); the parent stops the other workers at once, writes `FAILED.json`, writes no `COMPLETE.json` and exits non-zero (`fail_run`, `:777-801`, `:824-825`). Tested: an injected component failure gives exit 2 with the reason; a bad checkpoint gives `FAILED.json` and no `COMPLETE.json`.
- The sixteen checks are a list in the tool (`:90-117`), in `PLAN.json` (`integrity_checks`) and in every `COMPLETE.json`; the probe refuses a plan whose list is not its own, and acceptance requires the plan's list.

**Blocking 2, the 200-step cut-off.** I chose to require an actual turn end, and the plan says why (`PLAN.md:47-50`): the estimand is the return to the end of the team turn, and the cut-off is a device for bounding search cost. Every rollout's step limit is now 8,192 (`endturn_probe.py:80-84`, `:735-738`), which no rollout can reach, and a stop on it is an integrity error (`:420-423`). The drop rule is in the plan: decision-cap indices are dropped for every candidate of that root and arm; a root needs 8 valid indices in each half of the turn arm and 16 valid pairs in the forced and match arms (`endturn_analyze.py:45-46`, `:76-81`, `:113`, `:121`); every drop is counted and reported. The returns of the earlier smokes are unchanged by the new limit (compared).

**Blocking 3, the analysis enforces acceptance.** Fixed. New file `endturn_accept.py` holds one set of rules (`checkpoint_problems` `:69-142`, `shard_problems` `:145-180`) used by the launcher after the fetch and by the analysis before it computes. `endturn_analyze.py` (`main`, `:628-698`) refuses with "REFUSED, nothing was computed" unless: the plan hashes to `--expect-sha256`; its own file and `endturn_accept.py` are the files the plan names (`:648-649`); every `--shard-dir` is an accepted shard (SHA256SUMS, the shard's `plan.json`, the built commit, `COMPLETE.json` against the plan, file hashes, exactly the plan's engine seeds once each, natural games with zero counters, roots matching the games' counts); and all shards ran on one engine library (`:661-663`). It no longer reads worker files. Unregistered local runs go through `--smoke-run`, are held to their own `COMPLETE.json`, and the report is headed "SMOKE, NOT EVIDENCE". Tested: a wrong plan hash, a shard of another plan, an unfinished run and a failed run are each refused.

**Blocking 4, the spend guard.** Fixed as far as a local runner can.
- Limits must be finite and above zero, at the parser (`endturn_droplet.py:106-110`, `:697-714`) and again in the guard (`:252-264`); `nan`, `inf`, 0 and negatives are refused.
- `--max-hours` is the limit on the droplet's whole life. `Clock` (`:176-193`) gives each phase at most the time left before the limit less a 300-second reserve, and refuses to start a phase past it; every create, install, upload, build, launch and fetch call in `run_shard` takes its timeout from it (`:421-477`); the poll's deadline is the same.
- On failure only small logs are fetched, 45 seconds in all, then the droplet is destroyed; records of a failed shard are not fetched (`fetch_failure_logs`, `:361-387`; `:495-498`).
- `--child` is gone. A child is given the number of shards of the whole run and applies the guard for all of them (`:592-599`).
- The handlers that pass an interrupt to the children are installed before the first child is started, and a failure while starting interrupts the ones already started (`run_children`, `:544-573`).
- Cleanup without the runner is written down in three places: the launcher's docstring, `PLAN.md` section 10, and `CLEANUP.txt` in the run's output directory, written with the real names before anything is created (`:267-279`, `:600-605`). The commands are the export's `tools/droplet_tournament.py status`, `destroy --name` and `destroy --id`.
- The plan and the launch output state a nominal budget and say it is not a ceiling (second pass, item 3). See "could not fix".

**Blocking 5, ownership.** Fixed without touching the harness. Every run draws a random six-digit run id (`:600`); the droplet, its key and its local state are named `NAME-SHARD-RUNID`, and the id is in the state and in `droplet_run.json`. Before the key is made, `run_shard` refuses if local state of that name exists (`:401-403`) or the account has a droplet or key of that name (`account_refusal`, `:331-340`, `:404-406`). After the teardown, `reconcile` (`:343-358`, `:506`) deletes an ssh key that carries the run's own name and whose id was lost, and reports (never deletes) a droplet of that name still listed. With unique names the lifecycle's adoption by tag, name and time can only match what this run created.

**Blocking 6, the plan's wording and rules.** Rewritten.
- (a) Question 3 (`PLAN.md:82-85`) is now two descriptive statements and no cause; it says a realised margin above zero does not by itself show under-pricing.
- (b) Question 7 (`PLAN.md:89-92`) has an exact range rule (both intervals exclude zero, same sign, and the smaller difference exceeds the seed gap) and an exact two-seed rule for chain 60.
- (c) Section 8 (`PLAN.md:116-152`) says chain 58 governs and why; gives R, G and L as numbered numeric conditions; says two named families give no recommendation; gives the outcome as a table, with lambda before gamma when both hold and the reason; and says "reported without a recommendation" for everything else.
- The analysis evaluates every one of these rules and prints its numbers (`readings`, `endturn_analyze.py:472-621`), so no reading is left to judgment after the data are in.

**Correction, E3.** The plan now says what the code does: each of the three shares also requires two standard errors of the judging half (`PLAN.md:58`, `endturn_analyze.py:105-107`). I kept the rule of the exploratory tables, which is what question 1 compares against, and did not loosen the code. The halves are now the original indices 0 to 31 and 32 to 63; an index without a return leaves its own half (`:79`, `:100-104`).

**Correction, equal weight per game.** Computed for every estimate: every call collects the per-game version (`Estimator.from_sums`, `endturn_analyze.py:204-225`) and section 8 of the report lists them all. The 29 single components have theirs in the JSON summary only, and the plan says so (`PLAN.md:54`).

**Correction, detectable sizes.** `PLAN.md:96-108`: the match-arm standard errors are labelled lower bounds with the reason, the table is said to be replaced by the run's own clustered values, and "can tell 0.012 from zero" is withdrawn.

**Correction, scope of the checks and hash binding.**
- `PLAN.md:166-169` states what the identity and component checks do and do not cover.
- The identity check is stronger than it was: on the first root of each class in each game the turn arm is computed with **both hooks removed** (`unhooked`, `endturn_probe.py:242-250`, `:568-590`), with both installed and idle, and for end_turn roots through the tool's own entry; all must agree exactly and every value must be finite (a root with a capped rollout is skipped for the next one, so matching NaNs can no longer pass).
- The component check now includes the part that can fail: on every step before a rollout's last the 28 components must sum to the step's reward within 1e-5 (`:513-518`, `:538-540`). Measured: 1.4e-8.
- `PLAN.json` now names by hash the launcher, the acceptance rules and the analysis (`local_sha256`) and the export's `tools/droplet_tournament.py` (`lifecycle_sha256`) (`make_plan.py:108-110`). The launcher checks the lifecycle file's hash before it imports it (`endturn_droplet.py:87-95`, `:725-735`) and its own and the acceptance file's hash in `prepare` (`:224-230`).

**Your two decisions.**
- Chain 60: `make_plan.py --with-chain60 <sha256>` adds the checkpoint and a fifth shard. `PLAN.md` reads correctly with and without it (`:25`, `:91`, `:137`, `:188`): five shards launched together, one look after all accepted shards are in, and if `PLAN.json` has no chain 60 the plan says its stage had not produced a checkpoint. Tested with a stand-in: the dry run shows five shards and a guard of $2.92.
- The smoke shard: the commands above.

## What I could not fix, and why

1. **A spend ceiling that holds when the runner dies.** A droplet cannot delete itself without the account's token on it, and powering it off does not stop the bill. So the limit is enforced by the local process only. The plan says this in bold, the cleanup commands are written before any create, and `caffeinate` is in the commands. If you want a second line of defence, the only one I see is a second local watchdog process, which I did not build.
2. **The harness's adoption rule itself** (tag, name, 120 seconds of slack). The worktree is read-only. Unique names and the refusals before any create make it unable to match anything but this run's droplet.
3. **The harness's calls are not bounded by the clock:** the key registration, the create (retries for about five minutes), the wait for boot and the poll can overrun inside an attempt, and the teardown retries each API call up to 120 times, about 70 minutes for one stuck call. The plan no longer claims a worst case.
4. **The account listing reads the first 200 droplets and 200 keys.** An account with more would not be fully checked for a name clash. The run id makes a clash a one in sixteen million event per existing name.
5. **The droplet path is still untested on a droplet,** and so is the gcc build of `endturn_shim.c`. The offline flow test (below) and the rehearsal cover everything that needs no network. The smoke shard covers the rest.
6. **What the component check cannot show** (the env's attribution, the last step's breakdown) and that the identity check does not exercise active hooks. Stated in the plan.

## What I verified this round

All on the Mac, single process, `OMP_NUM_THREADS=1`. Outputs are in `smoke/`.

1. **Two-game local smokes at the plan's settings,** chains 55 and 58, seeds 29940000 and 29940001: 62 and 56 seconds wall on the final files, about 172,000 rollout steps a game (earlier runs of the same games took 52 to 90 seconds, with the Mac's load). No capped rollout. Identity roots 6 of 6 and 5 of 5 eligible, difference 0. Component sum 1.9e-15, step residual 1.4e-8. `smoke/report-planned-size-2-games.txt`.
2. **Rehearsal of the droplet-side job** with the smoke plan, both shards, one library build: both shards ACCEPTED by `endturn_accept.py`. `smoke/rehearsal.txt`.
3. **Registered-mode analysis** on the two rehearsed shards with the smoke plan: accepted, every table and every rule of sections 5 and 8 evaluated. `smoke/report-rehearsal-16-rollouts.txt`. The rules that need chains 59 and 60 were exercised with aliased records to make sure the code runs; that output is not kept.
4. **Refusals of the analysis:** wrong plan hash, shard of another plan, unfinished run, failed run.
5. **Offline flow test of the launcher** (`test_launcher_flow.py`, fakes in place of the API and ssh, real records): 23 of 23 checks. It covers the order of calls, the name-clash and stale-state refusals, the phase timeouts against the limit, the failure path (logs only, capped, then teardown, no record fetched), the limit reached before a phase, the lost key, the guard, cancellation while shards are being started, and the cleanup commands. `smoke/launcher-flow-test.txt`.
6. **Dry runs** of the registered plan and of the smoke shard: no network call, no state, no `runs/` directory. `smoke/dryrun.txt`, `smoke/dryrun-smoke-shard.txt`.
7. **From the first round, still true:** the probe's library plays the same games as the pinned shim (two games, every action, reward and env digest); one and two worker processes give the same returns; seeds 29960000 onward are unused; the checkpoint hashes match the gate plans; `bb-harness-search` is unchanged (`git status --short` empty).

## Measured rate and estimated cost

- Mac, single process, the plan's settings: 26 to 45 seconds a game across six two-game runs.
- Droplet, not measured: 22 seconds a game by D426's rate, 32 assumed.
- 200 games a checkpoint: about 1.9 hours and $0.32 a shard. Four shards $1.26, five $1.58. All shards together finish in about two hours.
- With `--max-hours 3.5` the nominal budget is $0.58 a shard plus the teardown, about $2.97 for five. It is not a ceiling (second pass, item 3).

## Open choices

1. **Lambda before gamma when both rules hold** (`PLAN.md` section 8). That precedence is my proposal, for the reason given there. Overrule it before the commit if you want the other order or no order.
2. **E3 keeps the two-standard-error condition on all three shares.** The alternative was to drop it from "above 0.10" and "below -0.02" in the code. I kept the stricter rule because the exploratory tables used it.
3. **Chain 49.** It governs no rule. Dropping its shard saves $0.32.
4. **Games.** 200 as written. 120 would take 1.2 hours a shard and widen every interval by about 1.3.
5. **A ledger entry.** I did not write one.

## Where the framing still needs care

1. One checkpoint at lambda 0.97 against two at 0.95 cannot be a lambda effect. With chain 60 the most the design shows is the same sign at both seeds.
2. Each checkpoint is probed at its own END_TURN states, so a difference in the margin mixes the critic's pricing with which states are priced.
3. Whether the match arm can settle question 3 is not known before the run. My written expectation is that the realised margin spans zero and no rule of section 8 holds.
4. The probe cannot see the gain m1 shows: one forced activation is worth about 0.001 win score by D416's numbers.

## Housekeeping

- Files: `PLAN.md`, `PLAN.json`, `NOTES.md`, `make_plan.py`, `export_harness.sh`, `endturn_shim.c`, `build_shim.sh`, `endturn_probe.py`, `endturn_accept.py` (new), `endturn_analyze.py`, `endturn_droplet.py`, `test_launcher_flow.py` (new), `smoke/`.
- `smoke/report-rehearsal-8-rollouts.txt` is a one-line pointer now: the smoke plan uses 16 rollouts, because the analysis needs 8 valid rollouts in each half.
- `__pycache__/` in the directory is from a syntax check in the first round. It is git-ignored. I did not remove it because the rule is to delete nothing.
- Scratch: `/private/tmp/claude-501/-Users-alexanderhuth/3154e4ea-fc69-4ad8-9862-ba7ced2d5c60/scratchpad/endturn-probe/` holds the exports, the built libraries and every smoke, rehearsal and test directory. It does not survive a restart, and nothing in the deliverables depends on it.
- `git archive` and `git rev-parse` ran in `~/Code/bb-play-harness` (shared object store). In `bb-harness-search` I ran `git status` and read files.
- One slip in the first round stands disclosed: a rehearsal ran two worker processes for about seven seconds. Every run of this round was single-process.

## Third pass (operator, 2026-10-07 22:25 PDT)

Codex's third look (`.codex-reviews/endturn-probe-review3.md`) closed six of the seven second-pass items and left one: the forced arm's statistics used only the first forced candidate's finite mask, so an index capped in another forced candidate still entered E2, its parts, the forced share and E1 minus E2. Fixed by the operator in `endturn_analyze.py` (`root_stats`, the forced block): the mask is now finite across every forced candidate, combined with the turn arm's mask. Checked on a real smoke record with a synthetic capped index holding an absurd value: it enters no forced statistic. Both plan files were regenerated; the hashes at the top of this file and the last line of `PLAN.md` are the new ones.

A real smoke shard ran on a droplet at 22:15 PDT under the previous smoke plan (`af772890...`, run id `d52b32`): droplet up in 45 s, build and launch 191 s after create, 2 games in 52 s on 2 processes at 16 rollouts, shard ACCEPTED, droplet and key deleted (HTTP 404), 4.5 minutes, about $0.012. Log: `runs/endturn-probe-2026-10-08/etsmoke.launch.log` (git-ignored). The droplet path is the same code as now; only the analysis file changed after it.

## After the first launch (operator, 2026-10-08 04:10 PDT)

The registered launch of 03:42 (D436, run `et1`, run id `472b85`) is unread (D437). Two shards stopped on the registered check "forced arm: the rule ended a turn 2 times in one rollout": chain 58 at engine seed 29960001, step 26, and chain 59 at engine seed 29960027, step 32. The operator interrupted the other two. Nothing was fetched or analysed.

**Cause.** Both roots were END_TURN decisions inside the kicking team's free turn from a Blitz kick-off result. The engine plays that turn inside its kick-off procedure (stack: MATCH, KICKOFF), and ending it does not advance `turns_completed`, which is what `play_harness/search.py` stops a turn-horizon rollout on. The rollout therefore ran on through the receiving team's turn into the kicking team's first real turn, where the forced rule fired again. The failure reproduces on the Mac in 11 seconds (`endturn_probe.py run ... --seed0 29960000 --games 2 --processes 2` with the registered settings as flags).

**Change.** `endturn_probe.py` only: `in_kickoff_turn(E, match)` is true when a KICKOFF frame is on the engine's procedure stack (below `stack_top`); a decision there is left out of every class before the class's count and reservoir, and each game record gains `kickoff_turn_decisions` (the count left out per class). No other tool changed. The forced-arm check is unchanged and still fails closed if the rule fires twice for any other reason. The registered seed block moved to 29970000 (`make_plan.py`); 29960000 to 29960199 is retired.

**Checked.**
1. `test_kickoff_turn_roots.py`: unit tests of the stack rule (a live KICKOFF frame, an activation inside it, an ordinary team turn, a stale frame above the top), and with `--harness` and `--lib` a replay of the two failed games at the registered settings: both complete, each leaves out one END_TURN decision (chain 59's game also two ACTIVATE decisions), forced-arm maximum 1. Before the change the same replay stops on the registered message.
2. Two wide runs on the Mac, 60 games each at 4 rollouts, chain 58 on seeds 29950100 to 29950159 and chain 49 on 29950200 to 29950259 (scratch output, not evidence): both complete, no integrity failure, identity check on 166 of 166 and 172 of 172 eligible classes, forced-arm maximum 1. 17 of the 120 games had a kick-off turn decision; left out: chain 58, 6 END_TURN of 585 and 12 ACTIVATE of 2,992; chain 49, 0 END_TURN and 47 ACTIVATE of 2,789. So the rule removes about one decision in a hundred.
3. The droplet-side job script and the acceptance on two smoke shards rehearsed in one directory (chain 55, chain 58): both ACCEPTED; the registered-mode analysis runs on them (351 lines). These ran under smoke plan `d86c77ce...`; the final smoke plan differs from it only in the hash of `make_plan.py` (the seed block).
4. Not repeated: the droplet smoke. The launcher, the job script, the shim and the build are unchanged, and the first launch itself showed four droplets building and playing.

**What the operator saw of the retired block.** Completion lines, the failing roots' state and action trail header, and per-game decision counts for chain 58 on seeds 29960000 and 29960001 and chain 59 on seed 29960027. No return, margin or critic value.
