# Vacation training progress journal

This is the durable hourly handoff for the July 2026 unattended Blood Bowl
reward-training preparation and run. Times are America/Los_Angeles. Entries are
append-only summaries; immutable experiment manifests and completion artifacts
remain the scientific source of truth.

## 2026-07-13 23:51 PDT

Status:

- The corrected possession/gain screen is healthy on the RTX 2070 under
  `reward-screen-possession-gain-v3.service`. It is on arm 1/8 (`both`, seed
  42), with zero accepted arms so far. GPU snapshot: 81 C, 79% utilization,
  5,737 MiB used. Screen manifest SHA-256 is
  `16a969a349c72454578113833cfde05ad80f412fad14837a0440fbe2abcd89f9`.
- BBTV remains observational and is following completed manifested checkpoints;
  it is not an experiment input.
- PR #8 exists and its first GitHub CI run is green. Independent review found
  merge-blocking issues, so it has not been merged or deployed.

Completed since the previous handoff:

- Implemented the closed six-job vacation queue, learned-anchor transfer,
  two-lineage gate, fixed three-seed final screens, artifact validators, docs,
  and tests.
- Local verification reached 110 Python tests plus 392 engine, 27 reward, and
  2 contact-bot tests passing before review fixes.
- Fixed review findings already identified in the working tree: scripted
  transfer status recovery, exact 1B main confirmation, exact 4,096-game
  learned transfer, matching main/second learned contracts, main warm/pool and
  scripted-source binding, distinct second ancestry, actual learned runtime
  config hashes, and mode-aware process-group result validation.
- Removed the pseudoreplicated learned-transfer “95% confidence” gate. The
  replacement is explicitly a fixed-stratum descriptive gate over mean,
  training-seed, anchor, backend-orientation, and worst-cell thresholds.

Current blockers / review work:

- Finish and test the process-group cleanup changes so queue guards cannot
  strand descendants after a wrapper exits.
- Close the complete immutable runtime dependency set in the frozen queue.
- Make checkpoint conversion fully restart-safe across every publication
  boundary.
- Add the new vacation suites to CI and rerun all local/GitHub checks.
- Obtain re-review approval on the correction commit before merge.

Next steps:

1. Finish the review-fix batch and its negative regression tests.
2. Run Ruff, shell syntax, all Python discovery, native tests, and queue process
   smokes.
3. Commit/push the fixes, wait for green CI, request independent re-review, and
   merge only with no P0/P1/P2 blockers.
4. Leave the live v3 screen source untouched until it completes; then audit all
   eight arms and proceed through candidate transfer and the 1B predeparture
   confirmation gates.
5. Deploy the exact merged source artifact-preservingly, freeze the final queue,
   smoke it on the 2070, start it, and verify BBTV before departure.

## 2026-07-14 00:34 PDT

Status:

- The corrected possession/gain screen remains healthy on arm 2/8
  (`neither`, seed 42). The latest durable training readout is 408,682,496 of
  500,000,000 requested steps, still in training, with zero reward clipping,
  non-finite rewards, error episodes, demonstrations, or demonstration
  fallbacks. GPU snapshot: 83 C, 80% utilization, 5,737 MiB used; disk is 6%
  full and inode use is 1%.
- Arm 1/8 (`both`, seed 42) completed and passed its acceptance contract at
  499,908,608 exact learner steps and 10,026 evaluation games.
- BBTV's follower, tunnel, and public WebSocket are healthy. Its manifested
  selection is arm 2 at step 299,761,664 versus the frozen turnover3 warm;
  the follower will select a newer complete checkpoint after the current
  two-game presentation cycle finishes.

Completed since the previous handoff:

- PR #8 passed hosted CI and three independent reviews, then merged to `main`
  as `4ec580d3c57148716965c4890aac51f0f6d5a7b0`.
- Deployed that exact tracked tree to `/home/rache/bloodbowl-rl` without
  deleting remote-only artifacts or rebuilding/restarting live services.
  A checksum-and-mode dry run is clean across all 4,148 archive entries;
  overwritten content is preserved at
  `/home/rache/deployments/pr8-backup-before-4ec580d`, and production records
  the deployment in `.deployed-source.json`.
- Rechecked user-service liveness, Tailscale, linger, capacity, thermal state,
  the public HTTP page, and an external secure WebSocket handshake. All are
  healthy.

Current blockers / review work:

- The public page's deployed JavaScript still defaults external viewers to
  `ws://localhost:8787/ws`, even though the tunnel correctly exposes
  `wss://bbtv.seconds0.com/ws`. A scoped same-host WebSocket default fix is in
  progress. The in-app browser is unavailable in this session, so visual
  canvas inspection remains an explicit pending verification; transport can
  still be verified externally.
- The audit snapshot must remain untouched until all eight screen arms finish.
  The vacation queue cannot be frozen until the main-lineage confirmation,
  scripted transfer, and learned transfer produce accepted literal evidence.

Next steps:

1. Test, review, merge, and deploy the BBTV default-WebSocket fix, then verify
   public JavaScript plus the external `hello`/`match_start`/`snapshot` flow.
2. Continue monitoring all integrity, capacity, thermal, and BBTV indicators
   while the corrected screen runs.
3. After the eight-arm screen finishes, atomically analyze it, run the
   predeclared transfer and paired-confirmation gates, and select at most one
   simplification candidate.
4. Deploy the exact merged queue source to the now-idle audit snapshot, freeze
   every input, execute the interruption/failure/resume smokes, start the user
   service, and complete the departure gate.

## 2026-07-14 01:05 PDT

Status:

- The corrected possession/gain screen is healthy on arm 3/8
  (`possession_only`, seed 42). Its latest machine readout is 258,473,984 of
  500,000,000 requested steps with zero reward clipping, non-finite rewards,
  engine errors, demonstrations, or demonstration fallbacks. GPU snapshot:
  83 C, 81% utilization, 5,737 MiB of 8,192 MiB used; disk is 6% full and inode
  use is 1%.
- Arms 1 and 2 are complete and accepted. Arm 2 (`neither`, seed 42) finished
  at 499,908,608 exact learner steps and 10,022 final-policy games, with all
  integrity counters zero.
- The actual BBTV units (`bbstream`, `bbweb`, and `bbtv-tunnel`) and the reward
  screen service are active. The follower is currently presenting arm 3's
  complete 100,007,936-step checkpoint against the frozen turnover3 baseline.

Completed since the previous handoff:

- PR #9 passed CI, merged to `main` as
  `c32ecb65690af01197e2f2233987f86056549417`, and was deployed
  artifact-preservingly to production. Public JavaScript now selects the
  same-host secure WebSocket endpoint; an external connection received the
  `hello`, `match_start`, and `snapshot` sequence. No BBTV service was restarted.
- A reliability audit found that the documented all-candidates-rejected route
  could not actually be frozen. Added a closed fallback that is authorized only
  by exact scripted evidence recommending `both` with an empty eligible list.
  It emits exactly two non-resume-safe R0-only `control-final` jobs, each
  `12B x seeds 42/43/44`, preserving the 72B total across the two ancestries.
- Added fail-first regression coverage for the analyzer, launcher, frozen
  wrapper, spec validator, two-job freezer, candidate-input rejection, and the
  exact six-file legacy provenance contract. Focused tests are 51/51 green;
  full Python discovery is 128/128 green; native suites are 421/421 green.
  Ruff, shell syntax, and whitespace checks pass.
- Updated `AGENTS.md`, `CLAUDE.md`, the fleet/training skills, the vacation plan,
  and decision D184 so the implementation and operating guidance describe the
  same two reviewed routes.

Current blockers / review work:

- The fallback change still needs commit, hosted review/CI, merge, and exact
  deployment staging. The active audit checkout remains intentionally untouched.
- The final queue cannot be selected or frozen until the corrected eight-arm
  screen and its exact scripted transfer finish. Candidate confirmation and
  learned transfer are required only if a simplification remains eligible.
- Visual BBTV canvas inspection remains pending because this session has no
  in-app browser target; public HTTP, JavaScript, and WebSocket transport are
  verified independently.

Next steps:

1. Finish the control-route diff review, commit it, push a PR, wait for green CI
   and review, then merge and stage the exact source artifact without disturbing
   the live audit process.
2. Continue integrity, progress, thermal, capacity, and BBTV monitoring while
   arms 3-8 run.
3. Analyze the immutable completed screen, run the exact four-arm scripted
   transfer, and follow only the evidence-selected candidate or R0-control route.
4. Once the audit checkout is idle, deploy the merged source, freeze the literal
   queue, run the departure smokes, start its user service, and verify BBTV.

## 2026-07-14 01:15 PDT — review correction

Status / correction:

- PR #10 opened at `428604d4f3b875cc12e4688bc06e364491595254` and
  hosted CI passed, but two independent reviewers correctly rejected that head.
  It has not been merged or deployed.
- The first head allowed a control fallback from the active v3 screen's older
  six-file provenance record. That is insufficient: the manifest omitted the
  recursive Puffer config-tree hash, explicit `default.ini` hash, and three
  Python runtime files. Current pins cannot retroactively prove launch-time
  bytes.
- It also treated an empty eligible list as “all candidates rejected” without
  requiring the transfer to have evaluated all three simplifications. A valid
  one-candidate matrix could therefore have authorized the fallback.

Fix in progress:

- Removed the legacy provenance exception. Both queue routes now require the
  complete config-tree/default-config/compiled-module/exact-nine-file/patch/
  warm/pool source-screen contract, with control-specific drift tests for an
  alternate config, `default.ini`, package initialization, models, and Muon.
- The control route now requires reference `both`, the exact candidate list
  `possession_only,gain_only,neither`, and the reviewed preference order before
  an empty eligible list can mean every simplification failed. A candidate-
  omission regression failed against the first head and passes after the fix.

Operational consequence / next steps:

1. Re-run the complete local suite, amend PR #10, and obtain exact-new-head
   re-review plus hosted CI before merge.
2. Continue the active v3 screen unchanged. If it selects a candidate, it can
   route that candidate into a new fully closed paired confirmation. If it
   rejects all candidates, it cannot directly authorize the control queue; run
   a provenance-complete decomposition rerun first.
3. Keep the audit checkout untouched until the current screen completes, then
   deploy only the exact reviewed merged source.

## 2026-07-14 01:30 PDT

Status:

- Arm 3/8 (`possession_only`, seed 42) is now accepted at 499,908,608
  exact learner steps and 10,066 final-policy games. Performance was 0.519322,
  TD/game was 1.350387, checkpoint SHA-256 is
  `dcbaba4d62f2c042a82ca4d45de9186aea21407f0c33490c6aaf60b5fb863916`,
  and every integrity counter is zero.
- Arm 4/8 (`gain_only`, seed 42) is healthy at 17,039,360 steps. Its latest
  readout has zero clipping, non-finite rewards, and engine errors. GPU snapshot:
  81 C, 79% utilization, 5,737 MiB of 8,192 MiB used.
- BBTV is presenting arm 3's latest completed manifested checkpoint against the
  frozen turnover3 baseline. Public HTTP and the secure WebSocket both pass;
  a fresh client received `hello`, `match_start`, and live snapshot messages.

Completed since the review correction:

- PR #10's first head was held. The full-provenance and full-candidate-matrix
  fixes passed 128/128 Python tests, 421/421 native tests, Ruff, ShellCheck,
  compilation, shell syntax, and whitespace checks.
- Three independent reviewers approved exact corrected head
  `a0dc804ae252ccb5cc3508b2819b57bf86a01e42`; hosted CI also passed. PR #10
  merged as `ce5ef24457eed3d49903e56eb2a652e3918fed66`.
- Deployed the exact 4,148-entry merged archive to production without deleting
  remote artifacts, rebuilding, or restarting services. Archive SHA-256 is
  `ff21ef64c8aaa97ff7eed1f8aba852ac030130292b45a80be607cbdcc83a0646`;
  the post-overlay content/symlink comparison is empty. The 15 overwritten files
  are preserved at `/home/rache/deployments/pr10-backup-before-ce5ef244`, and
  production records the exact commit/tree/archive in `.deployed-source.json`.
- BBTV and reward-screen service PIDs were unchanged across deployment. The
  active audit checkout was not modified.

Current blockers / review work:

- The merged source cannot be deployed into the audit checkout until the live
  eight-arm screen finishes.
- If v3 selects a simplification, it must still pass a new fully provenance-
  complete paired confirmation and both transfer strata. If v3 rejects all
  simplifications, its older manifest cannot authorize the control fallback;
  the decomposition must be rerun under the complete source contract.
- The remaining utilization risk is a predeparture pipeline that is healthy but
  incomplete when the user leaves. Audit whether a separately predeclared,
  fully pinned R0 deadline-control route can provide useful two-ancestry
  replication without depending on incomplete or legacy selection evidence.

Next steps:

1. Continue monitoring arms 4-8, BBTV, thermals, capacity, and integrity.
2. Review the deadline-control question against the no-adaptive-selection and
   provenance requirements; implement it only if it is scientifically useful
   and strictly safer than leaving the GPU idle.
3. After v3 completes, deploy the merged archive to the idle audit tree, verify
   every tracked byte, and run the exact four-arm scripted transfer.
4. Follow only a fully satisfied candidate or control contract, freeze the
   literal queue, execute the departure smokes, start its user service, and
   verify BBTV.

## 2026-07-14 01:46 PDT

Status:

- This file is now the explicit durable hourly progress journal requested for
  the unattended-training handoff. During active work, append a timestamped
  entry at least once per hour covering status, evidence, blockers or risks,
  and the next concrete steps; chat updates continue on the roughly 30-minute
  cadence.
- The corrected screen remains healthy on arm 4/8 (`gain_only`, seed 42) at
  208,928,768 of 500,000,000 requested steps. The latest readout has zero reward
  clipping, non-finite rewards, engine errors, demonstrations, and demonstration
  fallbacks. GPU snapshot: 82 C, 80% utilization, 5,737 MiB of 8,192 MiB used.
- BBTV has advanced to this arm's complete 100,007,936-step manifested
  checkpoint against the frozen turnover3 baseline. `bbstream`, `bbweb`, and
  `bbtv-tunnel` are all active.

Completed since the previous handoff:

- Revalidated the exact merged deployment archive staged on the 2070: SHA-256
  `ff21ef64c8aaa97ff7eed1f8aba852ac030130292b45a80be607cbdcc83a0646`.
- Rechecked the three reserved post-screen destinations. The candidate-transfer,
  provenance-complete rerun, and final vacation queue paths are all absent and
  therefore cannot collide with stale output.
- Rechecked the host boundary: Windows uses the High Performance power plan,
  AC and DC sleep are both disabled, no Windows Update or component-servicing
  reboot is pending, Tailscale is online without key expiry, and user-service
  lingering is enabled. Updates have not been paused or otherwise changed.

Current blockers / risks:

- The active audit tree must remain immutable until `SCREEN_COMPLETE.json`
  records all eight accepted arms. Deployment, transfer, and queue freezing are
  deliberately gated on that artifact rather than process state.
- A candidate still requires fully closed paired confirmation plus scripted and
  learned transfer. If every candidate is rejected, the legacy v3 source cannot
  authorize control training; the complete-provenance decomposition must be
  rerun.
- Visual canvas inspection is still unavailable from this session. Public HTTP,
  deployed JavaScript, secure WebSocket messages, and the follower's immutable
  selection record provide independent transport and freshness evidence.

Next steps:

1. Continue monitoring arms 4-8, integrity, GPU thermals, disk/inodes, services,
   and BBTV selection without modifying the active audit tree.
2. On screen completion, verify all eight result contracts and the completion
   manifest before deploying any source.
3. Back up every overwritten audit file, overlay the exact merged archive,
   verify all 4,148 tracked entries plus installed runtime identity, and run the
   plan-only launcher smoke.
4. Launch the exact 32-cell scripted transfer as a durable user service, then
   follow only the evidence-authorized candidate or complete-control route.

## 2026-07-14 02:15 PDT

Status:

- Arm 4/8 (`gain_only`, seed 42) completed and passed its immutable acceptance
  contract at 499,908,608 exact learner steps and 10,076 final-policy games.
  Performance was 0.530915, TD/game was 1.452263, score difference was
  0.097757, and checkpoint SHA-256 is
  `b97bfe681ebacf8eec72f9cf98e59b66fa2ea61e226fe6dcb3dcfc936ed3f6a1`.
  Reward clipping, non-finite rewards, engine errors, demonstrations, and
  demonstration fallbacks were all zero in training and evaluation.
- Arm 5/8 (`gain_only`, seed 43) started from the frozen warm and static pool
  and is healthy at 13,238,272 steps. The screen service remains on its original
  PID with zero restarts. GPU snapshot at the arm transition: 83 C, 78%
  utilization, 5,737 MiB of 8,192 MiB used.
- Four of eight arms are now accepted. The observed completed-arm cadence is
  about 46 minutes 24 seconds, keeping the screen-completion estimate near
  05:20 PDT.

Completed since the previous handoff:

- Used a real headed Chrome session against `https://bbtv.seconds0.com` to close
  the visual-verification gap. The live canvas rendered the pitch, players,
  scoreboard, action log, dice odds, decision rate, and exact manifested
  `gain_only-s42-step000249823232` policy label against turnover3.
- The browser initially encountered four WebSocket 502 handshakes during the
  bounded checkpoint handoff. Origin port 8787 and the public tunnel then
  returned the expected HTTP 426 upgrade response, and the existing exponential
  retry logic recovered automatically. The new server/selection record was
  published at 01:53:21 PDT; this was a brief viewing gap, not an experiment or
  service failure.
- Opened draft PR #11 for this ongoing journal. Its first hosted CI run passed.
  It remains draft until the queue is frozen, smoke-tested, started, and visibly
  advancing.
- Repeated the staged-to-audit checksum dry run. Exactly 31 tracked paths have
  content changes or are new, matching the reviewed `f468762..ce5ef244` change
  set; all other archive differences are metadata timestamps only.

Current blockers / risks:

- The remaining four seed-43 arms and atomic `SCREEN_COMPLETE.json` are still
  required before deployment or analysis. No preliminary seed-42 metric is
  being used to select a route.
- BBTV checkpoint rollover can briefly show `reconnecting` while the next
  bounded server loads. The client recovers and the immutable selection moves
  forward; a persistent failure would still require separate investigation.
- Candidate and control paths retain the same evidence requirements described
  in the previous entry. Neither route can be frozen yet.

Next steps:

1. Monitor arms 5-8 and verify each result at its acceptance boundary; keep
   BBTV, thermal, capacity, Tailscale, and service checks live.
2. Require the exact eight-arm completion artifact, then run the merged analyzer
   read-only from its staged path before deploying that source into the idle
   audit tree.
3. Back up the 21 existing content-changed audit files plus the prior deployment
   record, overlay and byte-verify the exact merged tree, and perform the
   plan-only launcher smoke.
4. Start the complete 32-cell scripted transfer under a contained durable user
   service and proceed only through the predeclared evidence route.

## 2026-07-14 03:02 PDT

Status:

- Arm 5/8 (`gain_only`, seed 43) completed and passed its acceptance contract at
  499,908,608 exact learner steps and 10,007 final-policy games. Performance was
  0.513990, TD/game was 1.580394, score difference was 0.046068, and checkpoint
  SHA-256 is
  `2a307f4b7a4d352cd02b9a68018f8f1d5bb280f376cfb71ad497703a69f6fe95`.
  Every training and evaluation integrity counter remains zero.
- Arm 6/8 (`possession_only`, seed 43) is running cleanly. At the transition the
  original screen service still had zero restarts; GPU snapshot: 81 C, 79%
  utilization, 5,737 MiB of 8,192 MiB used. All three BBTV services are active.
- Five of eight arms are accepted. The cadence remains consistent, moving the
  screen-completion estimate slightly earlier to approximately 05:17 PDT.

Completed since the previous handoff:

- BBTV advanced to seed 43 during arm 5 and presented its complete
  249,823,232-step checkpoint against turnover3. It is therefore following the
  newest run identity rather than remaining pinned to seed 42.
- Draft PR #11 passed hosted CI again on journal head `ba58cf6`.
- Rechecked systemd health: neither the user manager nor the system manager has
  a failed unit. GPU, memory, disk, and inode headroom remain healthy.

Current blockers / risks:

- Arms 6-8 and the atomic eight-arm completion proof remain mandatory. The
  seed-43 `gain_only` result is replication evidence, not a route selection.
- The post-screen analyzer, audit deployment, and scripted transfer are ready
  to execute but remain intentionally blocked on that completion proof.
- BBTV's brief checkpoint-rollover reconnect behavior remains observational;
  it has not interrupted training or stopped the follower from advancing.

Next steps:

1. Verify arms 6, 7, and 8 as each crosses its immutable acceptance boundary,
   and continue the service, integrity, thermal, capacity, and BBTV checks.
2. On atomic screen completion, run the merged analyzer read-only from the
   staged source and preserve its exact output as the first routing evidence.
3. Deploy and byte-verify merged commit `ce5ef244` in the now-idle audit tree,
   run the plan-only smoke, then launch the exact 32-cell scripted transfer as a
   durable user service.
4. Select no training queue until the resulting evidence satisfies one of the
   two reviewed literal route contracts.

## 2026-07-14 03:48 PDT

Status:

- Arm 6/8 (`possession_only`, seed 43) completed and passed its acceptance
  contract at 499,908,608 exact learner steps and 10,032 final-policy games.
  Performance was 0.519886, TD/game was 1.301435, score difference was
  0.065391, and checkpoint SHA-256 is
  `45568bc64a1fdb557de4c8f7f00d8fdb4b053429222470c04dc262e00e873b20`.
  All training and evaluation integrity counters were zero.
- Arm 7/8 (`neither`, seed 43) is running from the same immutable warm and pool.
  The screen service remains on its original PID with zero restarts. GPU
  snapshot at transition: 81 C, 79% utilization, 5,737 MiB of 8,192 MiB used.
- Six of eight arms are accepted. At the observed cadence, arm 7 should finish
  near 04:33 PDT and the complete screen near 05:19 PDT.

Completed since the previous handoff:

- BBTV advanced to arm 6's complete 249,823,232-step seed-43 checkpoint against
  turnover3. The public follower is continuing to track the current run.
- Rechecked Tailscale (`Running`, online, no key expiry), user lingering,
  memory, swap, disk, and inode capacity. About 9.5 GiB RAM and 904 GiB disk
  remain available; inode use is 1%.
- Draft PR #11 passed hosted CI on journal head `e6cc49b`.

Current blockers / risks:

- Arms 7 and 8 plus the atomic completion proof are still required; neither
  the analyzer nor source deployment will run early.
- The GPU occasionally touches its normal 81 C software target and briefly
  adjusts clocks, but hardware thermal slowdown is inactive and the exact-step
  cadence remains stable. No power or cooling setting has been changed during
  the experiment.
- Queue routing remains blocked on the post-screen scripted transfer and, if a
  candidate survives, the full confirmation and learned-transfer evidence.

Next steps:

1. Continue the same fail-closed monitoring through arms 7 and 8 and verify the
   atomic completion hash chain.
2. Run the staged merged analyzer read-only, retain and hash its output, then
   deploy `ce5ef244` into the idle audit tree with the reviewed 21-file backup
   and all-entry verification.
3. Execute the installed-source and plan-only smokes and start the restart-safe
   32-cell scripted transfer under a durable contained user unit.
4. Use only its literal recommendation and evidence contract to choose the next
   predeclared route.

## 2026-07-14 04:35 PDT

Status:

- Arm 7/8 (`neither`, seed 43) completed and passed its acceptance contract at
  499,908,608 exact learner steps and 10,035 final-policy games. Performance
  was 0.511460, TD/game was 1.454210, score difference was 0.038964, and
  checkpoint SHA-256 is
  `d76d95c0b51de1d002cc6d4c73a23faa719f9f0b7756c62fd4fa395490a898e9`.
  All training and evaluation integrity counters were zero.
- Arm 8/8 (`both`, seed 43) is running cleanly. At transition, the screen
  service remained on its original PID with zero restarts; GPU snapshot: 80 C,
  78% utilization, 5,737 MiB of 8,192 MiB used.
- Seven of eight arms are accepted. The final arm and atomic screen completion
  remain on track for approximately 05:20 PDT.

Completed since the previous handoff:

- BBTV followed arm 7 during training, presenting its complete manifested
  checkpoint against turnover3 rather than remaining on arm 6.
- Rechecked Windows host restart state: neither Windows Update nor component
  servicing reports a pending reboot. No update or power policy was modified.
- Draft PR #11 passed hosted CI on journal head `f89a26f`.

Current blockers / risks:

- A seventh accepted result is not screen completion. Deployment remains gated
  on arm 8 acceptance and the exact `SCREEN_COMPLETE.json` hash chain.
- The first post-screen scripted matrix is expected to take roughly 42 minutes;
  a candidate route then requires several hours of confirmation and transfer
  work before freezing. Current timing still preserves a substantial departure
  buffer.
- If every candidate is rejected, legacy v3 cannot authorize the control route;
  the reviewed provenance-complete rerun remains mandatory.

Next steps:

1. Monitor the final arm through exact training and evaluation completion, then
   verify all eight result files and `SCREEN_COMPLETE.json` with the staged
   merged analyzer.
2. Back up the prior audit deployment record and 21 changed existing files;
   overlay, provenance-record, and byte-verify merged commit `ce5ef244` without
   deleting any run, checkpoint, or vendor artifact.
3. Run the installed-source and plan-only smokes, then start the 32-cell transfer
   in a durable restart-safe user service.
4. Continue hourly journal and roughly 30-minute chat updates while the
   predeparture evidence pipeline runs.

## 2026-07-14 05:24 PDT

Status:

- The corrected v3 screen is atomically complete. All eight arms passed their
  contracts; `SCREEN_COMPLETE.json` SHA-256 is
  `0cb5b65a1908f6e710997a92afdfbeaaac015f9b66f8df5fd6d3b907ba681f21`.
  The merged analyzer independently regenerated and verified the complete
  eight-result hash chain. Its preserved JSON SHA-256 is
  `d04ca9e3dcd23d54fa9e24bb80d700f48f148e4200d3ee9c6a4f5bd9e17f6f0e`.
- Merged commit `ce5ef24457eed3d49903e56eb2a652e3918fed66` is now deployed in the idle
  audit tree. The pre-overlay delta contained exactly 21 changed existing files
  and 10 new files; every existing file plus the prior deployment record is
  backed up at
  `/home/rache/deployments/pr10-audit-backup-before-ce5ef244`.
- The 32-cell scripted transfer is running under
  `reward-candidate-transfer-v3.service`. It started with zero restarts,
  `Restart=on-failure`, `KillMode=control-group`, and the exact reserved output
  path. Current status is cell 1/32 (`both`, seed 42, bot 0, team side 0).

Completed since the previous handoff:

- Arm 8/8 (`both`, seed 43) passed at 499,908,608 exact steps, completing the
  screen and stopping its service normally.
- Ran the merged analyzer read-only from the staged tree before deployment; it
  verified all eight result contracts and the atomic completion artifact.
- Recomputed the deployment delta, backed up all overwritten content, overlaid
  the exact 4,148-entry archive without deletes, wrote the exact commit/tree/
  archive deployment record, and verified zero post-overlay content or symlink
  drift. The installed Puffer source/config/dashboard/build check passed.
- The merged `control-final` launcher plan-only smoke passed with screen
  manifest SHA-256
  `e351de0d4ce46aa480bdb467f8dafad7c0851eb8ec073d4e285b7ab38617aad1`.
  The real transfer plan-only freeze also passed: manifest SHA-256
  `84f168704bf2e18b3a249653b4ef80245b3ba39da2c7489815a7a76c374f8f7f`.
- Verified that the real matrix is exactly reference `both` plus candidates
  `[possession_only, gain_only, neither]`, seeds `[42,43]`, both bot styles, and
  both team sides, with preference order
  `[neither, possession_only, gain_only]` and full merged runtime provenance.
- BBTV advanced to the final accepted `both`, seed-43, 499,908,608-step
  checkpoint against turnover3; all three viewer services remain active.

Current blockers / risks:

- The scripted transfer must publish and validate all 32 atomic cells plus
  `TRANSFER_COMPLETE.json` before its recommendation is actionable.
- If a simplification is eligible, the longer paired confirmation plus scripted
  and learned transfer remain required before queue freeze. If none is eligible,
  the legacy v3 source still requires the complete-provenance v4 rerun.
- The transfer is restart-validating, but any source, manifest, checkpoint, or
  completed-cell drift will fail closed and block the next route.

Next steps:

1. Monitor all 32 transfer cells, service restarts, atomic status, GPU/host
   health, and BBTV. Preserve the final completion and analysis hashes.
2. Apply only the transfer's literal recommendation: either launch the reviewed
   paired confirmation for its one eligible candidate or launch the complete-
   provenance v4 decomposition rerun if all simplifications are rejected.
3. Continue through the required confirmation/transfer gates, freeze the exact
   candidate or control queue, and execute the interruption/failure/resume and
   departure smokes before enabling the persistent service.

## 2026-07-14 06:03 PDT

Status:

- The complete 32-cell scripted transfer finished successfully with zero
  service restarts. `TRANSFER_COMPLETE.json` SHA-256 is
  `d25ef35f672ed63518473cdeb116294179d5eabf0daabf07dc592f6c445e9cdc`;
  `ANALYSIS.json` SHA-256 is
  `5edde996666a6f532ea5240829dfc7373fcde1e0b40c67f9864c629f0e4442d9`.
  Regenerating the analysis from all 32 cell logs produced byte-identical JSON.
- All three simplifications passed the conservative scripted gate. The frozen
  preference order `[neither, possession_only, gain_only]` therefore selected
  `neither` for longer confirmation. This is a routing decision only, not reward
  promotion.
- The exact main-lineage `1B x 2` paired confirmation is running under
  `reward-paired-confirmation-neither-v1.service`. Its manifest SHA-256 is
  `5021875f9d7816d77b520d8616e5a9acbe419c0bcdca93bc78f2655e633380da`;
  the fixed schedule is `both42, neither42, neither43, both43`.

Completed since the previous handoff:

- Validated 32,092 scripted-opponent games across all predeclared cells. The
  three candidate score-delta means/minima were: `neither -0.000712/-0.026463`,
  `possession_only -0.009396/-0.030401`, and
  `gain_only -0.001000/-0.015702`; all also passed the champion-TD and bot-TD
  relative gates.
- Froze the paired confirmation with candidate `neither`, exact transfer
  completion/analysis/manifest hashes, frozen turnover3 warm, static pool,
  exact merged implementation, and final step boundary 999,948,288.
- Ran its plan-only validation, then launched the real screen with
  `ARM_DETACH=0`, `Restart=no`, and `KillMode=control-group`. The first
  `both`, seed-42 trainer is inside the service cgroup, and the unit has zero
  restarts.
- BBTV remains on the final accepted v3 checkpoint until the confirmation emits
  a newer complete manifested checkpoint; all three viewer services are active.

Current blockers / risks:

- The four-arm paired confirmation is non-resume-safe and will fail closed on a
  service or host interruption. Automatic restart is deliberately disabled.
- Scripted eligibility is not enough to freeze a vacation queue. Main-lineage
  self-play, scripted transfer, and learned-anchor transfer must all pass, then
  the frozen queue must reproduce the same evidence on the second ancestry.
- At the measured 2070 cadence, this confirmation should take about six hours;
  the predeparture buffer remains adequate but is now dominated by real training
  rather than setup work.

Next steps:

1. Monitor all four 1B arms through their exact acceptance boundaries, including
   integrity, service containment, thermals, capacity, and BBTV freshness.
2. If the paired screen passes, run its exact 16-cell scripted transfer and
   32-cell learned-anchor transfer, then evaluate the fixed main-lineage gates.
3. Freeze the candidate queue only after all main evidence is literal; otherwise
   stop or follow the separately reviewed fail-closed route authorized by the
   exact evidence.

## 2026-07-14 07:00 PDT

Status:

- The main-lineage paired confirmation remains healthy on arm 1/4 (`both`, seed
  42): 651,165,696 steps at the latest complete trainer report. The service is
  active with zero restarts, all trainer descendants remain in its cgroup, and
  reward clipping, nonfinite rewards, and error episodes remain zero.
- The RTX 2070 was at 81 C, 79% utilization, 5,737 MiB VRAM, and 118 W. No
  hardware thermal slowdown is active; disk, memory, user services, and the
  Tailscale path remain within the previously verified departure margins.
- BBTV is following this exact confirmation arm against the frozen turnover3
  baseline. Its latest selected complete checkpoint was `both`, seed 42, at
  549,453,824 steps; `bbstream`, `bbweb`, and `bbtv-tunnel` are all active.

Completed since the previous handoff:

- Froze and validated the learned-transfer anchor configuration at
  `/home/rache/bloodbowl-rl-audit/runs/vacation-inputs-20260714/LEARNED_ANCHORS.json`.
  It is read-only and has SHA-256
  `ac2fcd8c27093122937510348262804647c2480bca357e8597fd81ec52b8a9c7`.
- The configuration pins four exact 16,066,560-byte learned checkpoints
  (`league9`, `violence`, `netblock`, and `turnover3`), 4,096 games per cell,
  and the reviewed gates: mean score delta at least -0.02; per-seed,
  per-anchor, and per-orientation means at least -0.05; and every cell at least
  -0.10. Validation used the merged learned-transfer runner without touching
  the active screen.
- Rechecked live service containment, checkpoint progress, GPU health, and the
  BBTV follow record immediately before this journal entry. The active screen
  manifest remains the frozen SHA-256
  `5021875f9d7816d77b520d8616e5a9acbe419c0bcdca93bc78f2655e633380da`.

Current blockers / risks:

- No arm result exists until the trainer reaches the exact 999,948,288-step
  acceptance boundary and its evaluation/result contract passes. This
  four-arm screen is deliberately non-resume-safe and will fail closed after a
  service or host interruption.
- A passing paired screen still cannot authorize the vacation queue by itself.
  Its exact 16-cell scripted transfer and exact 32-cell learned-anchor transfer
  must pass before the candidate is frozen.
- BBTV restarts briefly when a newer checkpoint is atomically selected. Prior
  visual verification showed its websocket retry recovering from this rollover;
  a persistent viewer outage would still block departure readiness.

Next steps:

1. Monitor arm 1 through its exact boundary and verify the atomic arm result,
   evaluation count, integrity counters, service state, and BBTV rollover before
   allowing arm 2 to count.
2. Continue all four fixed arms (`both42`, `neither42`, `neither43`, `both43`)
   without modifying the experiment; preserve and independently regenerate the
   final analysis/completion artifacts.
3. If and only if the paired gate passes, run the exact scripted and frozen
   learned transfers, freeze the literal candidate queue, then execute the
   interruption/failure/resume and departure smokes before enabling it.

## 2026-07-14 07:55 PDT

Status:

- Arm 1/4 (`both`, seed 42) is atomically accepted. It reached the exact
  999,948,288-step boundary, completed 10,024 final-policy evaluation games,
  and recorded `acceptance_pass=true` with no failures. Its checkpoint SHA-256
  is `329a0d2488da832979415a4c18394845f3b77d1bf2c494a904b33d64ca829a17`;
  its result SHA-256 is
  `f9073bb157d06a5c39eab42e7561becdde7e1f4b49d050170e508f637b5096cd`.
- Arm 2/4 (`neither`, seed 42) is running at 234.5M steps. Reward clipping,
  nonfinite rewards, and engine-error episodes are still zero, the enclosing
  service has zero restarts, and all 38 tasks remain in its cgroup.
- BBTV has advanced to the exact arm-2 checkpoint at 199,884,800 steps against
  the frozen turnover3 baseline. All three viewer services are active and the
  public endpoint returned HTTP 200.

Completed since the previous handoff:

- Verified arm 1's final cumulative evaluation rather than inferring success
  from trainer exit. Its accepted final metrics include performance 0.538657,
  score differential +0.109836, and 1.266461 total touchdowns per game, with
  zero clip, nonfinite, error, demo, and fallback counters.
- Independently checked the accepted result, run manifest, process record,
  status record, checkpoint byte count, and their SHA-256 links before allowing
  the orchestrator's transition to arm 2 to count.
- Rechecked the post-screen launch inputs. The read-only learned-anchor config
  still hashes to
  `ac2fcd8c27093122937510348262804647c2480bca357e8597fd81ec52b8a9c7`,
  and the planned scripted-transfer, learned-transfer, and vacation-queue
  destinations are all absent/free. This preserves a fail-first launch instead
  of reusing ambiguous output.
- Rechecked host margin: about 968 GB of disk and 10.2 GB of available memory.
  The RTX 2070 was at 83 C, 79% utilization, 5,737 MiB VRAM, and 163 W with no
  hardware thermal slowdown. No user service is failed.

Current blockers / risks:

- Three fixed arms remain. The screen has no actionable completion or paired
  comparison until `neither42`, `neither43`, and `both43` each publish an
  accepted result and `SCREEN_COMPLETE.json` validates all four result hashes.
- Arm 1 alone cannot justify removing either shaping term. Even a passing
  four-arm comparison only authorizes the predeclared scripted and learned
  transfer gates; it does not promote a reward.
- The screen remains deliberately non-resume-safe. A service/host interruption,
  artifact drift, nonzero integrity counter, undersampled evaluation, or wrong
  step boundary must stop the route rather than silently restarting it.

Next steps:

1. Monitor arm 2 through exact training, evaluation, and atomic acceptance,
   then do the same for the fixed seed-43 candidate/reference pair.
2. On a complete passing screen, run the scripted-transfer plan-only validation
   in its fresh destination and launch the exact 16-cell restart-validating
   matrix; preserve its literal completion and analysis hashes.
3. If scripted transfer passes, run the exact 32-cell learned-anchor matrix from
   the frozen config. Only then evaluate queue freezing and execute all
   departure interruption/failure/resume smokes before persistent start.

## 2026-07-14 08:50 PDT

Status:

- Arm 2/4 (`neither`, seed 42) is running at 854.2M of the exact
  999,948,288-step boundary. Arm 1 remains accepted, the screen manifest remains
  SHA-256 `5021875f9d7816d77b520d8616e5a9acbe419c0bcdca93bc78f2655e633380da`,
  and the service remains active with zero restarts and 38 contained tasks.
- The arm-2 train telemetry still reports zero clipping, nonfinite rewards, and
  engine-error episodes. At the measured cadence, its training boundary is due
  shortly after 09:02 PDT, followed by the required 10,000-game evaluation and
  atomic acceptance check.
- BBTV is serving the exact arm-2 699,269,120-step checkpoint against the frozen
  turnover3 baseline. `bbstream`, `bbweb`, and `bbtv-tunnel` are active and the
  public endpoint returned HTTP 200 with the expected page.

Completed since the previous handoff:

- Monitored arm 2 continuously from 234.5M through 854.2M steps without an
  integrity event, service restart, task escape, or host-capacity regression.
  BBTV advanced across multiple complete manifested checkpoints rather than
  reading an in-progress file.
- Audited the deployed freezer's exact candidate-mode spec contract. It accepts
  no live candidate choice: the same candidate must already be accepted by the
  completed 1B paired screen, exact scripted transfer, and four-anchor learned
  transfer before it can emit the fixed six-job plan.
- Preselected conservative departure guard values for the eventual literal
  spec: at least 100 GiB free disk, at least 1,000,000 free inodes, and an 88 C
  thermal ceiling. These are not active or frozen yet; they will be written only
  after all main evidence paths are literal. The queue requires three
  consecutive 30-second over-temperature polls before terminating a job.
- Rechecked the live margins against those proposed guards: 967.9 GB free,
  66.9M free inodes, and 10.1 GB available memory. The GPU was at 82 C, 80%
  utilization, 5,737 MiB VRAM, and 132 W with no hardware thermal slowdown;
  no user unit is failed.

Current blockers / risks:

- Arm 2 still needs its exact boundary, final cumulative evaluation, immutable
  checkpoint/result links, and orchestrator acceptance. Arms 3 and 4 have not
  started, so there is no paired seed comparison or screen completion yet.
- The resource thresholds are operational planning values, not permission to
  freeze early. `VACATION_SPEC.json` must not exist until the main screen,
  scripted completion, and learned completion paths and hashes all exist.
- The public viewer is healthy but may briefly restart between checkpoint
  selections. Persistent BBTV failure, any integrity counter, process escape,
  or source/input drift remains a departure blocker.

Next steps:

1. Validate arm 2's final training/evaluation/result boundary, then monitor the
   fixed `neither43` and `both43` arms to atomic acceptance and screen
   completion.
2. Regenerate the complete screen analysis independently. Only if its paired
   gate passes, run the fresh 16-cell scripted transfer and the frozen 32-cell
   learned-anchor transfer, preserving every completion and analysis hash.
3. Freeze the exact candidate spec/plan with the reviewed resource guards, run
   the non-resume-safe interruption, resume-safe recovery, and downstream-stop
   smokes, then enable/start the persistent queue and visibly verify BBTV.

## 2026-07-14 09:45 PDT

Status:

- Arm 2/4 (`neither`, seed 42) is atomically accepted. It reached exactly
  999,948,288 steps and 10,079 final-policy games with no acceptance failures.
  Its checkpoint SHA-256 is
  `af63fe924d84fa4bbb5000b38f80a55a4e9d03faf56969baf23c7d26820e40d2`;
  its result SHA-256 is
  `a547bbc70e8d540d68629dbf2cb7d6b5f65fe5d7b3e6309b3beaae36c5461dba`.
- Arm 3/4 (`neither`, seed 43) is running at 450.1M steps with zero clipping,
  nonfinite rewards, and engine-error episodes. The screen service is active
  with zero restarts and all 38 tasks contained in its cgroup.
- BBTV is serving the exact arm-3 399,638,528-step checkpoint against the frozen
  turnover3 baseline. All viewer services are active, and the public endpoint
  returned HTTP 200 with the expected page.

Completed since the previous handoff:

- Verified arm 2's final cumulative reprint, 10,079-game count, checkpoint size
  and hash, result/manifest/status links, and `acceptance_pass=true` before
  counting the orchestrator transition to arm 3.
- Arm 2's final evaluation was performance 0.505407, score differential
  +0.020439, and 1.219169 total touchdowns per game, with zero clip,
  nonfinite, error, demo, and fallback counters.
- Computed the frozen self-play gate diagnostic without routing on it: seed 42
  has candidate-minus-reference performance -0.033250. That passes the -0.05
  per-seed floor, while the -0.02 across-seed floor requires the eventual
  seed-43 contrast to be about -0.006750 or better. Only the completed analyzer
  and gate may decide this.
- Rechecked host and viewer health. The machine has 967.5 GB free, 66.9M free
  inodes, and 10.2 GB available memory. The RTX 2070 was at 81 C, 73%
  utilization, 5,737 MiB VRAM, and 108 W with no hardware slowdown; no user
  unit is failed.

Current blockers / risks:

- Arm 3 needs another ~550M exact steps plus its final evaluation and atomic
  result. Arm 4 (`both`, seed 43) has not started, so the decisive seed-43
  contrast and the completed two-seed self-play gate do not exist.
- If the frozen paired self-play gate rejects `neither`, the reviewed route
  stops. A confirmation failure does not authorize the all-candidates-rejected
  R0 fallback and must not be converted into an improvised candidate switch.
- Even a passing self-play comparison remains only routing evidence. The exact
  scripted and learned transfers must still accept the same candidate before a
  vacation queue can be frozen.

Next steps:

1. Monitor arm 3 to exact acceptance, then the final `both`, seed-43 arm through
   its exact boundary and evaluation. Independently regenerate and preserve the
   completed screen analysis and artifact hashes.
2. Apply the frozen self-play thresholds. On rejection, stop fail-closed; on
   pass, immediately plan-only validate and launch the fresh exact 16-cell
   scripted transfer, followed by the frozen 32-cell learned transfer.
3. Only after all main gates pass, write/freeze the literal vacation spec and
   plan, execute the live departure smokes, start the persistent user service,
   and verify BBTV against the queue-owned run.

## 2026-07-14 10:40 PDT

Status:

- Arm 3/4 (`neither`, seed 43) is atomically accepted at the exact
  999,948,288-step boundary with 10,018 final-policy games and no acceptance
  failures. Its checkpoint SHA-256 is
  `6515bfea719c59bba95957cf6408922733474e7bec48bcb1723dff59c30307c0`;
  its result SHA-256 is
  `7d49c6ba417eca47dd9b4347f12d04ac0c9febae0acb8691e98fb43ca2841f2d`.
- The final arm 4/4 (`both`, seed 43) is running at 39.3M steps with zero
  clipping, nonfinite rewards, and engine-error episodes. The screen service
  remains active with zero restarts and all 38 tasks in its cgroup.
- BBTV is serving the final stable arm-3 checkpoint at 948,961,280 steps against
  turnover3 while it waits for arm 4's first complete manifested checkpoint.
  All viewer services are active and the public endpoint returned HTTP 200.

Completed since the previous handoff:

- Monitored arm 3 from 450.1M through exact training and final evaluation,
  verified its final cumulative reprint, 10,018-game count, checkpoint size and
  hash, result/manifest/status links, and `acceptance_pass=true`, then verified
  the orchestrator's transition to the last fixed arm.
- Arm 3's final evaluation was performance 0.514923, score differential
  +0.045818, and 1.665103 total touchdowns per game, with zero clip,
  nonfinite, error, demo, and fallback counters.
- Preserved the gate discipline: seed 43's candidate value is now literal, but
  its candidate-minus-reference contrast is still unknowable until arm 4's
  accepted result exists. No partial score has been routed.
- Rechecked live host margins: 967.2 GB free, 66.9M free inodes, and 10.2 GB
  available memory. The RTX 2070 was at 81 C, 80% utilization, 5,737 MiB VRAM,
  and 112 W with no hardware slowdown; no user unit is failed.

Current blockers / risks:

- Arm 4 requires its full exact training boundary, 10,000-game evaluation,
  immutable checkpoint/result links, and atomic acceptance. Until then there is
  no seed-43 paired contrast, completed two-seed analyzer output, or screen
  completion proof.
- The seed-42 candidate difference passed its per-seed floor but was below the
  across-seed mean floor. The final reference value can make the paired gate
  pass or fail; neither outcome may be presumed from arm 3 alone.
- On gate rejection the reviewed route stops. On pass, scripted and learned
  transfer are still mandatory and can independently reject the candidate.

Next steps:

1. Monitor the final reference arm through exact acceptance and verify
   `SCREEN_COMPLETE.json`, all four result hashes, and an independently
   regenerated paired analysis.
2. Apply the frozen self-play gate literally. If rejected, stop fail-closed. If
   accepted, run the fresh 16-cell scripted transfer and frozen 32-cell learned
   transfer without an idle planning gap.
3. If every main gate passes, freeze the exact six-job vacation queue, execute
   interruption/recovery/downstream-stop smokes, enable/start its persistent
   service, and visibly verify BBTV before departure.

## 2026-07-14 11:35 PDT

Status:

- The final arm 4/4 (`both`, seed 43) is running at 643.6M of the exact
  999,948,288-step boundary. Arms 1-3 remain atomically accepted and the screen
  manifest remains SHA-256
  `5021875f9d7816d77b520d8616e5a9acbe419c0bcdca93bc78f2655e633380da`.
- Arm 4 still reports zero clipping, nonfinite rewards, and engine-error
  episodes. The screen service remains active with zero restarts and all 38
  tasks contained in its cgroup. At the observed rate its training boundary is
  due around 12:07 PDT, followed by final evaluation and screen publication.
- BBTV is serving the exact arm-4 549,453,824-step checkpoint against the frozen
  turnover3 baseline. All viewer services are active and the public endpoint
  returned HTTP 200 with the expected page.

Completed since the previous handoff:

- Monitored the final arm continuously from 39.3M through 643.6M steps without
  an integrity event, service restart, task escape, or source/input change.
  BBTV rolled from arm 3 to arm 4 and advanced across stable manifested
  checkpoints without reading an in-progress file.
- Reconfirmed the three accepted result/checkpoint pairs and that no partial
  seed-43 contrast is being routed. The decisive reference performance, atomic
  fourth result, and `SCREEN_COMPLETE.json` still do not exist.
- Kept the post-screen commands mechanical: independently regenerate the
  analyzer; apply mean performance >= -0.02, every seed >= -0.05, and candidate
  TD relative drop <= 0.20; then either stop or create the fresh scripted plan.
- Rechecked live host margins: 966.9 GB free, 66.9M free inodes, and 10.2 GB
  available memory. The RTX 2070 was at 81 C, 69% utilization, 5,737 MiB VRAM,
  and 119 W with no hardware slowdown; no user unit is failed.

Current blockers / risks:

- The final reference arm and atomic screen completion remain mandatory. A
  process exit, last dashboard panel, or partial reference metric is not
  sufficient to evaluate the candidate.
- The seed-43 reference can still make the frozen two-seed self-play gate pass
  or fail. A rejection ends the reviewed route; it cannot be repurposed as the
  all-candidates-rejected control fallback or an unreviewed candidate switch.
- A passing self-play gate only permits the exact scripted and learned transfer
  strata. Neither a passing screen nor a visually promising BBTV matchup is a
  reward promotion.

Next steps:

1. Monitor arm 4 through exact training, 10,000-game final evaluation, atomic
   result, service completion, and `SCREEN_COMPLETE.json` publication.
2. Independently regenerate the completed paired analysis, verify every result
   and completion hash, and apply the frozen self-play thresholds literally.
3. On pass, immediately run the exact 16-cell scripted and 32-cell learned
   transfers; on their pass, freeze/smoke/start the persistent vacation queue
   and visibly verify BBTV. Stop fail-closed on any rejection or drift.

## 2026-07-14 12:15 PDT

Status:

- The four-arm paired screen completed successfully as an experiment but
  rejected `neither` as the vacation candidate. `SCREEN_COMPLETE.json` SHA-256
  is `96d8ab1d3dbbea438005780d8ba92a3b20e54175d885f3d460be4530e9c724ad`;
  the independently regenerated analysis SHA-256 is
  `a113fad8626f314ea7bed7dde8871892707b0242d0a8b6f80f5391dcb43c1a77`.
- The frozen mean performance contrast is -0.025273, below the required -0.02.
  Per-seed contrasts are -0.033250 and -0.017296, both above their -0.05
  floors. Candidate TD relative drop is -0.118247 (an increase, so it passes the
  0.20 ceiling). The literal failure is `mean_perf_delta` only and is decisive.
- The candidate route is stopped. No paired scripted transfer, learned transfer,
  `VACATION_SPEC.json`, queue plan, or queue state has been created from this
  screen. The GPU is idle rather than consuming time on a guaranteed-to-fail
  downstream gate.

Completed since the previous handoff:

- Arm 4 (`both`, seed 43) passed at exactly 999,948,288 steps and 10,025 final-
  policy games with all integrity counters zero. Its performance was 0.532219,
  score differential +0.098055, and 1.312818 TD/game; checkpoint SHA-256 is
  `9b936ff6f45ad70315b1340fd583aee7202d2c22034a51f713f02d0964c106a8`.
- Verified the screen service ended normally with result success, exit status
  zero, and zero restarts. Verified all four accepted result hashes and the
  atomic completion artifact before analyzing the comparison.
- Regenerated the complete analysis a second time and obtained byte-identical
  JSON. Then ran `vacation_reward_gate.validate_screen` with the reviewed
  thresholds; it independently returned exactly `mean_perf_delta`.
- BBTV advanced to the exact final arm-4 999,948,288-step checkpoint against
  turnover3; all viewer services remain active. The GPU returned to idle at
  59 C and 252 MiB VRAM after the screen completed.

Current blockers / risks:

- The reviewed candidate queue is now unavailable: its main self-play evidence
  is known to fail, so running scripted/learned transfer or a second ancestry
  would waste compute before the immutable two-lineage gate rejects it.
- A candidate confirmation failure does not prove that every decomposition
  candidate failed. Therefore it cannot authorize the existing all-candidates-
  rejected R0 control fallback, and silently switching candidates would violate
  the reviewed routing decision.
- Maximizing vacation GPU use now requires either an already justified non-
  promotion workload or a newly reviewed fallback contract. Neither may weaken
  the reward evidence, mutate production defaults, or relabel this rejection.

Next steps:

1. Preserve the rejected screen and its exact analysis/gate evidence; keep the
   candidate transfers and vacation freezer untouched.
2. Audit the existing reviewed workloads for a safe non-promotion option that
   produces useful Blood Bowl evidence and BBTV matchups without claiming a
   reward win. If none fits literally, prepare a separately reviewed contract
   rather than improvising a command queue.
3. Only deploy/start an alternative after its source, typed plan, provenance,
   failure behavior, resource guards, and BBTV path pass the same departure
   smokes. Otherwise hand off an evidence-backed stop instead of unsafe compute.

## 2026-07-14 12:25 PDT

Status:

- Selected a safe, non-promotion vacation workload: long R0 baseline
  characterization from the main and exact `league9` ancestries. The intended
  queue remains `72B` learner steps but contains no reward candidate.
- The implementation is isolated on
  `tranche/confirmation-rejected-baseline`. Focused freezer tests are green.
  The GPU remains idle while source review and departure smokes are incomplete.

Completed since the previous handoff:

- Wrote the test-first tranche contract in
  `docs/plans/confirmation-rejected-baseline.md`.
- Added an explicit `confirmation-rejected-baseline` spec route. It regenerates
  the fixed paired gate, requires at least one literal failure, verifies that
  the confirmation embeds the exact validated selection transfer, and rejects
  non-null learned inputs.
- Reused the existing two-job R0 `control-final` execution path and added a
  pinned `BASELINE_AUTHORIZATION.json` containing the exact failure and a
  no-promotion warning. A passing candidate cannot enter this route.
- Updated `DECISIONS.md`, `AGENTS.md`, `CLAUDE.md`, and the autonomy contract to
  distinguish candidate acceptance, all-candidates-rejected control, and
  confirmation-rejected baseline evidence.

Current blockers / risks:

- This source is not yet reviewed, merged, deployed, or frozen against the real
  host evidence. No real queue spec or state exists.
- The most important remaining risk is a route/provenance bypass in the freezer
  or an incomplete deployment pin. Broader tests and adversarial self-review
  must pass before the RTX 2070 starts.
- BBTV is still showing the completed reference matchup; it cannot show the new
  workload until the first manifested R0 checkpoint completes.

Next steps:

1. Finish the fail-open/route-confusion audit and strengthen tests for malformed,
   passing, wrong-arm, and drifted evidence.
2. Run the full queue/tool contract suite, commit and review the diff, obtain
   green CI, merge, and deploy the exact tree.
3. Freeze the real two-job plan, run interruption/recovery/downstream-halt
   smokes, launch it under systemd, and verify GPU health plus public BBTV.

## 2026-07-14 12:50 PDT

Status:

- The real vacation queue is live under
  `experiment-queue@vacation-r0-baseline-20260714-v1.service`. It is running
  `final-main-control`, arm 1/3, R0 (`both`), seed 42. The exact `league9`
  second-ancestry job is pending.
- Queue plan SHA-256 is
  `4ee72e3c58f09786cdd3bbf78a772e8de2d9a93e21a8b065cf0c5976ecced270`;
  the main screen manifest SHA-256 is
  `0a9b8fd435aeb41fcea9ad9ea2539b87bb9d900cb11de079c4b7e14a5945063a`.
- The trainer is using the frozen turnover3 warm SHA
  `fdcb2f0ebfbc88a29c026d51140ab008bd5dde5995ea5b3233fd0bd210110935`
  and the four-bank pool identity
  `18ec7cac858b71a6657003f454f19e232fb060f08b644c1e9e2f101076a9aac0`.
  At the first live check the RTX 2070 was 76 C, 78% utilized, using 5,707 MiB
  of 8,192 MiB at 145 W.

Completed since the previous handoff:

- PR #12 passed hosted CI and merged to `main` as
  `0eb3f4d4fc805e15ab50f293f2f2f483830e7498`; merged-main CI also passed.
  Review found no P0/P1 issue. The schema-version and missing negative-proof
  P2 findings were fixed before merge.
- Deployed the exact 4,150-entry archive to the isolated audit tree. Archive
  SHA-256 is
  `d8360742eeda56dc7065250c36d118d78984768b0135412f974ce81e3efba95d`;
  tree SHA is `fd3e9a2cd76d22881de7797702c98939ed2aceb6`. The prior seven
  overwritten files and deployment record are backed up at
  `/home/rache/deployments/pr12-audit-backup-before-0eb3f4d`; no remote-only
  artifact was deleted and no BBTV service was restarted.
- The deployed schema-2 freezer independently regenerated the exact
  `mean_perf_delta` rejection and wrote pinned
  `BASELINE_AUTHORIZATION.json`. The frozen plan contains exactly two R0-only,
  non-resume-safe jobs, 65 pins, 100 GiB/1M-inode capacity floors, a 10-minute
  progress limit, and an 88 C three-poll thermal guard.
- Revalidated the prior live systemd smokes: non-resume interruption is
  terminal, a failed job leaves its successor pending, resume-safe artifact
  recovery completes, and all recorded child PIDs are dead. The queue runtime
  and installed service-template hashes are unchanged from those smokes.
- The real service started with zero restarts. All 41 queue, wrapper, trainer,
  and worker tasks are contained in its systemd cgroup. The launch log confirms
  `r0_full_rebaselined`, exact 12B request / 11,999,903,744 rollout-aligned
  steps, no demos, and the audited optimizer/rollout contract.

Current blockers / risks:

- BBTV remains on the preceding completed paired-reference matchup until the
  first new R0 checkpoint is atomically published. Public HTTP and the three
  viewer services are healthy; visual rollover is still pending.
- The first progress status currently says `launching arm`; the next monitoring
  read must confirm advancing learner steps, fresh status, and zero integrity
  counters rather than relying only on process/GPU activity.
- Both PPO jobs are intentionally non-resume-safe. A service/host interruption
  during an arm halts the queue for inspection instead of silently restarting
  a changed trajectory.

Next steps:

1. Verify advancing dashboard steps, progress freshness, integrity counters,
   thermals, capacity, cgroup containment, and zero restarts.
2. Confirm BBTV selects the first atomically complete checkpoint from this
   queue and that the public page/WebSocket continues rendering the matchup.
3. Continue hourly durable entries and concise conversational monitoring;
   intervene only on a frozen guard breach or other evidence-backed failure.

## 2026-07-14 12:55 PDT

Status:

- The first vacation R0 arm is making real learner progress. At 12:55 PDT it
  had reached 114,163,712 agent steps (epoch 870); the queue service remained
  active with main PID 431309 and zero restarts.
- BBTV has rolled over between completed two-game viewing cycles to the exact
  100,007,936-step checkpoint from
  `vacation-r0-baseline-20260714-v1-final-main-control-both-s42`. The native
  checkpoint SHA-256 is
  `6c83f0eca621799e24d3f7e9c566585844dc1b27f38c409311b24b59f9a3a2ee`;
  its frozen opponent remains turnover3 SHA-256
  `fdcb2f0ebfbc88a29c026d51140ab008bd5dde5995ea5b3233fd0bd210110935`.
- Public transport is live: `https://bbtv.seconds0.com/` returned HTTP 200 and
  the public `/ws` endpoint completed an HTTP 101 WebSocket upgrade and
  delivered live frames. `bbstream`, `bbweb`, and `bbtv-tunnel` are all active
  with zero restarts.

Completed since the previous handoff:

- Verified the trainer advanced through 39,190,528, 46,137,344, 69,861,376,
  103,022,592, and 114,163,712 steps rather than merely holding GPU processes.
- Verified atomic native checkpoints at 50,069,504 and 100,007,936 steps. The
  follower correctly ignored the bootstrap checkpoint, finished its current
  matchup cycle, selected the newest available 100M checkpoint, converted it,
  and started the next stream cycle without restarting the trainer.
- Rechecked the live safety telemetry at 114M steps: reward clipping episodes
  and excess, non-finite rewards, engine-error episodes, demos, and demo
  fallbacks were all zero. The RTX 2070 was 81 C, 76% utilized, using 5,737 MiB
  at 166 W; free storage remained 901 GiB.

Current blockers / risks:

- The dashboard behavior figures are still very early, short-window samples
  and are not evidence for promotion or a reward conclusion. The latest window
  contained 97 games (performance 0.494845, score differential -0.030928,
  1.515464 TD/game, possession 0.344840); only the completed 10,000-game arm
  evaluations are decision evidence.
- The in-app browser surface was unavailable in this monitoring session, so a
  fresh visual canvas inspection could not be claimed. Backend selection,
  public HTML, WebSocket upgrade, and streamed frame bytes were verified
  directly instead.
- The PPO arm remains intentionally non-resume-safe. Any host/service
  interruption must halt for inspection; it must not be silently relaunched.

Next steps:

1. Continue hourly checks of learner-step freshness, service restarts, thermal
   and capacity guards, integrity counters, and atomic checkpoint publication.
2. Confirm BBTV continues advancing at matchup boundaries as newer checkpoints
   appear; perform a visual canvas check when the in-app browser is available.
3. Monitor all three main-ancestry seeds through exact 12B-step training and
   10,000-game final evaluations, then the three exact league9-ancestry seeds.
   Preserve every result hash and stop fail-closed on any guard breach.

## 2026-07-14 13:25 PDT

Status:

- The primary queue remains active on `final-main-control`, R0 seed 42, with
  zero service restarts and 40 tasks in its cgroup. At the latest machine-log
  observation it had reached 393,609,216 agent steps (epoch 3,002) at about
  186K steps/second.
- The latest 88-game diagnostic window reported performance 0.545455, score
  differential 0.147727, 1.329545 touchdowns/game, and possession 0.333179.
  Reward-clipping episodes/excess, non-finite rewards, engine-error episodes,
  demos, and demo fallbacks all remained zero. These short-window figures are
  health telemetry, not reward-selection evidence.
- The RTX 2070 was 83 C at 76% utilization, using 5,737 MiB VRAM and about
  150 W; free storage remained 901 GiB. `bbstream`, `bbweb`, and
  `bbtv-tunnel` were active with zero restarts.

Completed since the previous handoff:

- Measured throughput shows that the immutable 72B primary queue is likely to
  finish before the user's return. Designed a separate fail-closed overflow
  tranche for one additional unchanged R0 `control-final` screen from the
  static pool's exact netblock ancestry: 12B x seeds 42/43/44, or 36B and
  roughly 53 additional training hours. This is third-ancestry replication,
  not a candidate switch or reward promotion.
- Implemented, on an isolated worktree, a closed-schema primary-completion
  validator, overflow freezer, idempotent delayed starter, systemd oneshot/timer
  templates, and focused negative tests. The overflow can start only after the
  exact reviewed primary plan is complete, both recorded success artifacts pass
  their original validators, the primary service is inactive, every overflow
  pin is unchanged, no overflow state exists, and the GPU has no compute PID.
- The new contract tests and the existing queue/freezer/frozen-screen contract
  tests passed together: 73 tests green, with two expected skips because the
  vendored Puffer checkout is unavailable in this local worktree. Python compile,
  shell syntax, and patch-whitespace checks are also clean.

Current blockers / risks:

- The overflow code has not yet passed the repository-wide suite, independent
  simplify/bug-hunt review, hosted CI, merge, exact-archive deployment, or live
  failure/success smokes. Its timer is therefore not installed or armed.
- Deployment must be strictly additive: changing even one of the primary
  plan's 65 pinned paths would invalidate the running experiment. Before and
  after hashes will be compared before any overflow is frozen on the host.
- The primary PPO arm remains non-resume-safe. Any interruption is terminal for
  this queue and must never be hidden by the overflow timer.

Next steps:

1. Finish the clear-eyed code review and repository-wide verification, then run
   the required simplify and bug-hunt analysis passes.
2. Commit the overflow tranche, open a reviewed PR, obtain green hosted CI, fix
   any findings, and merge only if all gates pass.
3. Deploy only new runtime files from the exact merged archive, prove all 65
   live primary pins stayed byte-identical, run negative/success starter smokes,
   and arm the watcher only after a primary-running poll is a verified no-op.
4. Continue primary learner, integrity, thermal, capacity, checkpoint, and BBTV
   monitoring while the implementation proceeds.

## 2026-07-14 13:40 PDT

Status:

- The primary queue remains healthy on main-ancestry R0 seed 42. At the latest
  observation it had reached 591,921,152 steps (epoch 4,515), with zero service
  restarts and 40 tasks in the queue cgroup. Reward clipping, non-finite reward,
  engine-error, demo, and demo-fallback counters all remained zero.
- The latest 98-game diagnostic window reported performance 0.530612, score
  differential 0.132653, 1.5 touchdowns/game, and possession 0.330672. The GPU
  was 82 C at 79% utilization, using 5,737 MiB VRAM and about 134 W.
- BBTV continued its matchup-boundary rollover and selected the manifested
  499,515,392-step vacation checkpoint at 13:31:10 PDT. `bbstream`, `bbweb`,
  and `bbtv-tunnel` remain active with zero restarts.
- The post-primary watcher timer is enabled and active. Its first armed poll at
  13:37:54 PDT logged `primary service is still active; waiting`, returned
  success, and created no overflow state. It is scheduled every ten minutes.

Completed since the previous handoff:

- PR #14 passed hosted CI, including the Torch-dependent BC tests unavailable
  locally, and merged to `main` as
  `92196867f371ccf276021044ac569902e83379a5`. The review found no P0/P1 issue;
  two P2 fail-closed gaps were proven with red tests and fixed before publication:
  unknown systemd units can no longer masquerade as inactive, and the overflow
  plan hash is rechecked immediately before start.
- Built a five-file deployment archive from the exact merge, SHA-256
  `356b6bed4e1de6662c6be595ce9bb0a75c0a1e5a066f77a98f6b06a5009b250d`,
  and deployed only new freezer/starter/completion-validator and watcher-unit
  paths. None existed or overlapped a primary tree pin. All 65 primary pins
  validated before and after deployment; the trainer was not restarted.
- Froze the real separate overflow queue
  `vacation-r0-overflow-20260714-v1`. Its plan SHA-256 is
  `d90ee01c8c459f599c8601934f545ccb7783261edae3bcb6e9e3878036d37d3e`;
  all 74 pins validate. It contains only a resume-safe primary-completion proof
  followed by one non-resume-safe netblock-ancestry R0 screen at 12B x seeds
  42/43/44. It currently has no state and has never started.
- The real primary-running negative smoke passed both directly and through the
  installed systemd unit: completion returned the designated not-ready code,
  the watcher waited, and no overflow state appeared.
- A first synthetic child smoke correctly exercised terminal ownership but its
  dummy job halted because the fixture runner omitted its output-directory
  creation. That halted queue was preserved and a new ID used. The corrected
  v2 smoke reached validated `complete`; a second watcher invocation reported
  existing complete state and left the state SHA byte-identical, proving no
  relaunch. Neither synthetic job used the GPU.

Current blockers / risks:

- The real overflow must remain state-less until both primary screens finish
  exactly and their original validators pass. The timer is an outer readiness
  gate; the overflow queue independently repeats the completion proof.
- The two external CLI review sources were unavailable (missing Codex native
  binary; Gemini required interactive OAuth). Inline review, red-then-green bug
  tests, full local verification, and hosted CI are the available review
  evidence; this limitation is recorded on PR #14.
- Both real PPO screens remain non-resume-safe. Primary or overflow interruption
  is terminal and cannot be timer-relaunched.

Next steps:

1. Observe at least one more armed timer poll while the primary runs and confirm
   it remains a successful no-op with no overflow state or primary pin drift.
2. Continue learner-step, integrity, thermal, capacity, checkpoint, and BBTV
   monitoring; keep the hourly journal current.
3. At primary completion, preserve and validate both success artifacts and the
   atomic completion proof before accepting the overflow start. Never interpret
   or promote a reward automatically.

Post-entry verification: the next automatic timer poll fired at 13:48:26 PDT,
again logged `primary service is still active; waiting`, exited successfully,
created no overflow state, and scheduled its next ten-minute poll. Both the
65-pin primary plan and 74-pin overflow plan still revalidated without drift.

Additional departure audit: Windows is on High Performance with sleep and
hibernate disabled on AC and DC. WSL has a running keepalive task with boot,
logon, and two-minute triggers; Tailscale is enabled, online, and has no key
expiry. A direct Windows Update search found no cumulative/feature update or
downloaded reboot-forcing package—only the July malicious-software tool and a
Defender definition—so update policy was left unchanged. BBTV subsequently
selected the 599,392,256- and 699,269,120-step vacation checkpoints at matchup
boundaries. The journal branch's hosted CI passed at commit `76ca189`.

## 2026-07-14 13:57 PDT

Status:

- The primary queue remains active on `final-main-control`, R0 seed 42. It
  reached 799,801,344 agent steps (epoch 6,101) at 13:57 PDT. The current
  dashboard rate was about 190K steps/second; the whole-arm rate measured from
  the recorded 12:45:04 PDT start was 184,982 steps/second.
- The queue service is active with zero restarts. Live integrity telemetry
  remains clean: engine-error episodes, non-finite reward episodes/fraction,
  reward-clipping episodes/excess/fraction, demos, and demo fallbacks are all
  zero. Both the primary plan's 65 pins and overflow plan's 74 pins revalidated
  from disk with no mismatch.
- The RTX 2070 was 83 C at 78% utilization, using 5,737 MiB VRAM and about
  142 W. Free storage is 900 GiB. Temperature is a watch item, but step rate is
  stable and there is no restart or integrity evidence of thermal failure.
- `bbstream`, `bbweb`, and `bbtv-tunnel` are active with zero restarts, and the
  public BBTV page returns HTTP 200. The latest completed viewer rollover is the
  699,269,120-step checkpoint; the learner has reached the next checkpoint
  boundary, and the follower is allowed to finish its current two-game cycle
  before switching.
- The overflow timer remains active and scheduled every ten minutes. Its latest
  completed poll at 13:48:26 PDT correctly logged that the primary was active,
  returned success, and left the real overflow state absent.

Completed since the previous handoff:

- Recomputed the end-to-end utilization window from live evidence rather than
  the instantaneous dashboard rate. Across the immutable 72B primary and 36B
  overflow plans, 107,200,198,656 of 108B steps remained. At the measured
  whole-arm average, training projects to finish around 2026-07-21 06:56 PDT,
  or about 161 hours from this observation. Final 10,000-game evaluations add
  unmeasured overhead, so this remains a planning estimate rather than a
  completion guarantee.
- Rechecked the exact queue identities: the primary plan SHA-256 remains
  `4ee72e3c58f09786cdd3bbf78a772e8de2d9a93e21a8b065cf0c5976ecced270`;
  the overflow plan remains
  `d90ee01c8c459f599c8601934f545ccb7783261edae3bcb6e9e3878036d37d3e`.
  The real overflow has no state and has never started.
- Verified all four live user services relevant to the unattended run: the
  primary experiment queue, BBTV follower/server, BBTV web service, and named
  tunnel are active with zero restarts. The public viewer remains reachable.

Current blockers / risks:

- Each PPO arm is intentionally non-resume-safe. A host, WSL, service, or
  trainer interruption is terminal and must remain visible rather than being
  silently relaunched. The Windows sleep/hibernate, WSL keepalive, Tailscale,
  lingering user-service, and pending-update audits reduce but cannot eliminate
  that physical-host risk.
- The 83 C GPU reading is below the observed failure boundary and throughput is
  stable, but it warrants continued hourly trending. Intervention is justified
  only if temperature rises further with throttling, process loss, integrity
  errors, or a frozen learner; changing the live workload without those signals
  would destroy this non-resume-safe arm.
- Short-window training behavior is health telemetry only. No checkpoint or
  reward configuration may be promoted automatically; conclusions wait for
  complete, validated 10,000-game evaluations across all three seeds and
  ancestries.

Next steps:

1. Confirm the 13:58 overflow watcher poll is another successful no-op and that
   the overflow state remains absent.
2. Confirm BBTV atomically selects the new ~800M checkpoint after its current
   matchup cycle while the public page and three services remain healthy.
3. Continue hourly durable checks of step freshness, integrity counters,
   thermals, capacity, service restarts, pin hashes, watcher behavior, and BBTV
   rollover through departure; preserve all evidence without interpreting or
   promoting a winner early.

Post-entry verification: the 13:58:48 PDT watcher invocation completed with
result `success` and exit status 0, logged `primary service is still active;
waiting`, and left the real overflow state absent. This is the fourth observed
real primary-running no-op after the pre-arm smoke and the 13:37, 13:48, and
13:58 automatic invocations.

Thermal addendum: NVIDIA's active clock-reason bit resolves specifically to
software thermal capping at the configured temperature target, not hardware
thermal slowdown. The card reports an 81 C target, 89 C maximum operating
temperature, 91 C slowdown temperature, and 94 C shutdown temperature. Over a
30-second sample it was mostly 81--82 C, with one 84 C observation; utilization
was 77--83%, clocks were 1,620--1,785 MHz, and hardware thermal slowdown stayed
inactive. The fan was at 89%. Because the card's own target control is working,
learner throughput remains stable, and there is no restart or learner-integrity
signal, the evidence does not justify mutating power or clocks during a
non-resume-safe arm. Continue trending temperature, fan, rate, and both
software/hardware slowdown signals hourly.

BBTV addendum: at 14:03:54 PDT the current two-game cycle ended and the
follower atomically selected the newest stable checkpoint then available,
849,084,416 steps. It correctly skipped superseded intermediate checkpoints
instead of interrupting or replaying stale matchups. The selected run tag is
`vacation-r0-baseline-20260714-v1-final-main-control-both-s42`, seed 42; the
native source SHA-256 is
`075937bd49110a9b7d406e9f031421c572850c505abcf8795cf31ffc026c9e59`,
and the converted viewer artifact SHA-256 is
`855b281cb8aa3e2f65d501981ac7474240d992f0b57b3f128c1260681802d943`.
The selection manifest, conversion sidecar, and running server command agree.
The public page returned HTTP 200, and all three BBTV services remained active
with zero restarts after rollover.

Forecast addendum: evaluation overhead is now measured from historical local
artifacts instead of left unbounded. Twenty-seven accepted arms used the same
10,000-game final-evaluation contract: eight 249,954,304-step arms had a median
process duration of 1,561 seconds, fifteen 499,908,608-step arms had a median
of 2,771 seconds, and four 999,948,288-step arms had a median of 5,477.5
seconds. A linear fit gives 191,814 training steps/second plus a 223-second
fixed initialization/evaluation intercept per arm. Nine such intercepts total
about 33.5 minutes. Combining that conservative fixed overhead with the live
whole-arm step forecast moves expected end-to-end completion from about 06:56
to about 07:30 PDT on 2026-07-21. This remains an estimate, but it is now based
on 27 complete evaluations and supports the conclusion that the immutable
108B schedule should occupy essentially the full six-day absence without an
idle gap.

Automatic-evaluation addendum: the live primary screen manifest and queue plan
were re-audited after launch. Each 36B screen is exactly R0 `control-final` at
seeds 42/43/44, requested 12B per seed and rollout-rounded to 11,999,903,744
final steps. Each trainer performs a nominal 10,000-episode evaluation, while
acceptance requires at least 10,001 observed evaluation games. A result is
rejected if either train or evaluation telemetry is missing; if clipping,
non-finite rewards, engine errors, or demo fallbacks are nonzero; if the exact
final checkpoint, run manifest, reward, warm start, pool, implementation, PID,
process group, or hashes disagree; or if the final step differs from the frozen
manifest. `SCREEN_COMPLETE.json` cannot be emitted until all three results pass,
and the queue then independently runs the pinned artifact validator before it
may advance.

Each 36B screen has a 259,200-second (72-hour) queue cap. The historical fit
projects about 52.3 hours including fixed per-arm overhead, leaving roughly
19.7 hours of headroom. Equivalently, the observed 184,982-step/second rate
could decline by about 25% and still meet the timeout. The screen progress
sidecar was fresh at 14:09:04 PDT (`waiting for current trainer`, R0 seed 42),
and the queue's independent staleness limit is 600 seconds. The 14:08:49
overflow watcher invocation also exited successfully, logged that the primary
was active, and left the real overflow state absent.

Promotion-boundary addendum: all three live/frozen screen configs were checked
again. Each is `profile: control-final`, `candidate_arm: both`, with
`candidate_transfer: null` and exactly one of the three approved ancestry hashes.
In this profile, `both` maps to the existing full R0 reward manifest; it is a
legacy arm label, not a candidate or promotion. The two primary queue commands
and the overflow training command can only invoke the pinned frozen-screen
runner, and their success commands can only invoke the pinned artifact
validator. The overflow's other job can only write and validate the primary
completion proof; that proof's own contract explicitly says it does not select
or promote a reward. All queue mutable paths are confined to their work/output
directories.

The BBTV selection remains `latest_vs_frozen_warm`: the current vacation
checkpoint is converted into the viewer-only directory and played against the
frozen turnover3 source SHA-256
`fdcb2f0ebfbc88a29c026d51140ab008bd5dde5995ea5b3233fd0bd210110935`.
The follower can atomically replace its conversion/selection/status files and
its child viewer process, but no viewer path is a queue input or deployed model
destination. Therefore the unattended schedule can generate evidence and live
matchups, but it has no command or writable path that can declare a winner,
change a reward, or promote a checkpoint.
