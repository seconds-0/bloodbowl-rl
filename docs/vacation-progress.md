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

Public-viewer addendum: an external secure-WebSocket client connected to
`wss://bbtv.seconds0.com/ws` after the 849M rollover and received protocol-v1
`hello`, `match_start`, full `snapshot`, and continuously advancing `delta`
messages. The public matchup metadata named the away agent as
`vacation-r0-baseline-20260714-v1-final-main-control-both-s42-step000849084416-075937bd49.b`
and the home agent as `baseline-turnover3_cap-fdcb2f0ebf`. The observed game
was Dwarf versus Wood Elf in the second half; frames advanced through actions,
blocks, a turnover, score/turn state, ball ownership, team statistics, and
sequence numbers 1,043--1,053. This proves the post-rollover game is reaching
an unaffiliated public client, not merely running behind the tunnel.

The in-app browser had no attachable tabs in this session, so a fresh rendered
canvas screenshot could not be claimed. Public HTML, secure WebSocket upgrade,
correct matchup identity, complete snapshot state, and live frame progression
were verified directly instead; visual canvas inspection remains a tooling
limitation rather than a BBTV service failure.

Behavior-health addendum: live phase-tagged training telemetry was aggregated
read-only across 7,519 schema-v2 dashboard windows (about 755,000 games), using
game-count weighting and excluding final reprints/evaluation windows. Comparing
the first 200M steps (141,785 games) with the most recent 200M steps through
991,035,392 (155,020 games), frozen-history win rate rose from 0.5331 to 0.5528.
The change was broad rather than isolated: bank 0 rose 0.4537 -> 0.4856, bank 1
0.6050 -> 0.6212, bank 2 0.5600 -> 0.5723, and bank 3 0.5251 -> 0.5420.
Score differential rose 0.0748 -> 0.0956, illegal-action fraction fell 0.2204
-> 0.2106, and forward ball advancement rose 7.45 -> 8.67.

The behavior shifted rather than improving monotonically on every measure:
touchdowns fell 1.352 -> 1.192, possession 0.3295 -> 0.3223, draw rate rose
0.4133 -> 0.4451, and total blocks thrown fell 15.28 -> 12.35. At the same time,
blitzes rose 5.19 -> 5.61, blocks against the carrier 1.18 -> 1.30, carrier
knockdowns 1.63 -> 1.92, pickup success 2.09 -> 2.26, ball-path length 9.51 ->
10.90, and average episode length fell about 58 steps. That combination is
consistent with more selective ball-directed contact and lower-scoring games,
not an obvious no-play/collapse signature. It is still correlated,
nonstationary training telemetry—not independent final evaluation—and cannot
select or promote a checkpoint. Continue watching the touchdown/possession
decline while reserving conclusions for the frozen 10,000-game evaluations.

Subsequent BBTV verification: at 14:12:34 PDT, after the two games using the
849M checkpoint completed, the follower selected the newest stable checkpoint
then available at 948,961,280 steps. Its native SHA-256 is
`9f7543dad59ebcad8e1ca9c30e25880ecb056fb35a13638de17eee377c4b3cf5`;
the viewer conversion SHA-256 is
`d1636093e10f79e6fd2e2734563ae9565816af9d39147369818b7b6e6d67f5be`.
Selection and server-status manifests agree on both learner and frozen opponent,
the public page returns HTTP 200, and all three BBTV services remain active
with zero restarts. This is the eighth observed vacation-checkpoint rollover
and further verifies that BBTV shows the newest stable model at completed
matchup boundaries rather than interrupting games or remaining stale.

Capacity addendum: storage growth was measured from the live arm at roughly
1.0B steps. Its 21 native checkpoints consume 337,397,760 bytes and its learner
log 72,886,195 bytes, about 410 MB combined. Checkpoints are published about
every 50M steps, implying roughly 240 per 12B arm; linear projection for all
nine arms is approximately 42--44 GB including logs. The BBTV converted cache
currently uses 771,766,522 bytes and is bounded by its 24-checkpoint retention.
The volume has 966,073,585,664 bytes free (about 900 GiB). The projected full
schedule therefore consumes under 5% of current free capacity; even a 2x
projection error remains under 10%. Storage and inode exhaustion are not a
credible six-day failure mode at the observed growth rate, but free space will
remain part of each hourly guard check.

Memory capacity is similarly healthy. WSL reports 11 GiB total and 9.4 GiB
available, with only 33 MiB of 4 GiB swap in use. The experiment-queue cgroup
uses 2.87 GB (2.88 GB peak) with no cgroup swap; BBTV uses 1.74 GB (2.35 GB
peak) and 6.4 MB cgroup swap. Both have unlimited configured memory/swap rather
than a hidden unit cap. Load average near 17.7 is expected from the frozen
16-thread environment workload, and it coincides with stable learner
throughput rather than memory pressure or process churn.

The 14:19:26 PDT overflow watcher invocation also completed with result
`success` and exit status 0, logged `primary service is still active; waiting`,
and left the real overflow state absent. The roughly 37-second delay from the
timer's nominal 14:18:49 trigger is within systemd's default timer-accuracy
coalescing window and did not represent a stalled watcher.

One-billion-step continuity addendum: the current 12B seed-42 run was compared
with the prior accepted 1B R0 seed-42 run from the same turnover3 ancestry. The
full manifest diff contains only the intended identity/horizon changes: tag and
screen-manifest identity, requested/final steps (1B/999,948,288 ->
12B/11,999,903,744), and the opponent-timeout scaling (10B -> 120B) that keeps
opponent swapping disabled for the longer arm. Reward, warm start, static pool,
compiled engine, source/config trees, optimizer, rollout, network, historical
share, and every other command field are byte-identical. The reward SHA-256 is
`14b718f28b2c925ea3279444dfbc679631c0cceea0f84d9e3547e3318ce6e90e` in
both runs.

Across roughly the first billion training steps, the current run remains close
to the accepted predecessor: performance 0.5276 versus 0.5308, score
differential 0.0810 versus 0.0911, illegal fraction 0.2086 versus 0.2106, and
ball advancement 8.40 versus 8.25. Its latest 200M frozen-history win rate is
0.5528, effectively matching the predecessor's full-train 0.5513. The current
recent window still has fewer touchdowns and more draws, consistent with the
behavior watch above. Because a 12B annealing horizon intentionally leaves
learning rate and entropy much less decayed at 1B than a 1B run, exact
trajectory equality is neither expected nor desired; the manifest comparison
rules out accidental reward/config drift as the explanation.

Sustained-throughput addendum: native checkpoint modification times provide an
independent wall-clock rate series at the approximately 50M-step publication
cadence. Across 21 consecutive intervals through 1,048,838,144 steps, mean
throughput is 185,327 steps/second, median 184,837, standard deviation 1,505,
and range 183,762--190,829. The first half averages 186,163 and the second half
184,567 steps/second; the most recent five average 184,493. The sub-1% half-to-
half difference is dominated by the unusually fast initial interval and does
not show progressive thermal degradation. End-to-end checkpoint throughput is
185,315 steps/second, agreeing with the prior whole-arm forecast and current
dashboard rather than relying on either alone.

BBTV freshness addendum: all nine vacation-rollover records were compared with
the native checkpoint files that existed at each viewer start time. Every
selection was the newest available checkpoint at that boundary (9/9); no
rollover selected an older stable model when a newer one was available.
Conversion-to-server-start latency is consistently 1.05--1.12 seconds. The
observed two-game cycles last 520--793 seconds (8.7--13.2 minutes), mean 668
seconds, while selected checkpoints had waited only 50--262 seconds after
native publication. Thus cycle duration, not conversion or stale discovery,
sets viewer freshness.

At 14:23:59 PDT BBTV completed its ninth vacation rollover to the
1,048,838,144-step checkpoint, native SHA-256
`ebd3b05ddfe895a2c1eb65870624030deacc496a3cdb7d4a1062da6975dc3a92`
and converted SHA-256
`71c07b3e970297e6e3487f2fd22c3bed408afbc3d8c3dbd28fad204d5e39968b`.
At verification it was only one approximately 50M checkpoint behind the live
learner. Selection/server manifests agree, the public page returns HTTP 200,
and all viewer services remain active with zero restarts.

Host-kernel addendum: privileged read-only journal inspection since the 12:45
launch found zero NVIDIA Xid/NVRM faults, OOM kills, ext4/I/O errors, or
critical thermal/shutdown messages. The only repeated GPU-adjacent warning is
11 instances of WSL `dxgkio_is_feature_enabled: Ioctl failed: -75`: one at
trainer initialization and exactly one 3--5 seconds after each of ten viewer
server starts. There are no instances during steady-state execution.

Microsoft's [WSL2 kernel implementation](https://github.com/microsoft/WSL2-Linux-Kernel/blob/linux-msft-wsl-6.6.y/drivers/hv/dxgkrnl/ioctl.c)
identifies this ioctl as a `D3DKMTIsFeatureEnabled` capability query forwarded
through `dxgvmb` to the Windows host; on this Linux guest, errno 75 is
`EOVERFLOW`. The timestamp
correlation plus successful CUDA training, successful viewer model loads/live
frames after every warning, zero Xid events, stable checkpoint throughput, and
inactive hardware slowdown support the inference that this is a tolerated
optional feature-probe mismatch rather than a compute failure. It does not
justify restarting WSL, changing drivers, or mutating the live arm. Treat a
future warning as actionable only if it loses this process-start correlation
or is accompanied by Xid, process exit, failed model load, frozen steps, or
hardware slowdown.

The 14:30:26 PDT overflow watcher was another successful primary-running no-op:
result `success`, exit status 0, no unit restart, and no real overflow state.
The learner simultaneously remained active at 1,173,356,544 steps with all
integrity counters zero; the GPU was 81 C with hardware slowdown inactive.

Repository-handoff addendum: the live-journal branch had forked before merged
PR #14, so current `origin/main` was merged into it as `2d12e19`. The merge was
conflict-free and preserved all 1,679 journal lines while bringing D186,
AGENTS/CLAUDE guidance, project skills, overflow plan/runtime/tests, and tracked
systemd templates into the branch history. Against `origin/main`, draft PR #13
now changes exactly one file: 579 added lines in `docs/vacation-progress.md`.
GitHub reports it mergeable; combined-history CI is running. This was local
repository maintenance only and did not write the audit host, restart a
service, or change any primary/overflow pin.

## 2026-07-14 14:34 PDT

Status:

- The primary remains healthy on main-ancestry R0 seed 42 at 1,206,386,688
  exact steps (epoch 9,203). The latest dashboard rate was 182K steps/second;
  the independent 21-interval checkpoint series remains 185,315 steps/second
  end to end. The progress sidecar was fresh at 14:33:41 PDT.
- The latest 106-game diagnostic window reported performance 0.5613, score
  differential 0.1415, 1.2925 touchdowns/game, possession 0.3139, historical
  win rate 0.5595, and illegal fraction 0.2042. Engine-error, clipping,
  non-finite reward, demo, and demo-fallback counters remained zero. This is
  health telemetry, not final-evaluation or promotion evidence.
- The queue, BBTV follower/server, web service, and tunnel are active with zero
  restarts. The RTX 2070 was 81 C, 75% utilized, using 5,737 MiB at about 115 W;
  software target capping was active and hardware slowdown inactive. Memory
  available remains 9.4 GiB, swap use 33 MiB, and free storage 900 GiB.
- BBTV completed its tenth vacation rollover at 14:32:52 PDT to the newest
  available 1,148,715,008-step checkpoint. Native SHA-256 is
  `23ac14668e46866536509722341055f6791fc41b76854a543ca068333eda941b`;
  converted SHA-256 is
  `b8a52d044a06f21ef06ed15a9f1e712b1603323dd73fda65625d307c6ab7fd62`.
  The public page returns HTTP 200.
- The overflow timer is active and waiting. Its latest invocation at 14:30:26
  PDT was a successful primary-running no-op. The real overflow still has no
  state. The 65 primary and 74 overflow pins revalidate; their plan hashes
  remain `4ee72e3c58f09786cdd3bbf78a772e8de2d9a93e21a8b065cf0c5976ecced270`
  and `d90ee01c8c459f599c8601934f545ccb7783261edae3bcb6e9e3878036d37d3e`.

Completed since the previous full checkpoint:

- Closed the end-to-end utilization forecast with 27 historical 10,000-game
  evaluations. The fixed startup/evaluation intercept is about 223 seconds per
  arm; the complete 108B primary-plus-overflow schedule projects to finish near
  07:30 PDT on July 21, with the 72-hour per-screen caps retaining roughly
  18--20 hours of headroom at the live sustained rate.
- Re-audited automatic acceptance: exact final steps/checkpoints, complete
  train/eval telemetry, at least 10,001 observed evaluation games, zero
  integrity counters, and full manifest/hash/process containment are required
  per seed. All three seeds must pass before a screen completes; the queue then
  independently repeats the frozen artifact validator.
- Proved the promotion boundary: every screen is unchanged R0 `control-final`,
  candidate transfer is null, writable paths are confined to work outputs, the
  completion proof cannot select a reward, and BBTV is viewer-only. No
  unattended command can promote a checkpoint or change production.
- Verified the public secure WebSocket with correct 849M matchup identity, a
  complete snapshot, and advancing game deltas. Across ten rollovers, all ten
  audited boundaries selected the newest checkpoint available; conversion adds
  about 1.1 seconds and the deliberate two-game cycle sets freshness.
- Aggregated about 755,000 live training games. Recent frozen-bank performance
  improved broadly without a collapse signature, while lower touchdowns and
  possession/higher draws remain watch items. Manifest comparison against the
  accepted 1B R0 predecessor found only the intended 12x horizon/timeout and
  identity changes; reward, engine, pool, model, optimizer, and rollout fields
  are identical.
- Quantified storage, memory, and kernel risk. The schedule projects to 42--44
  GB against 900 GiB free; memory has 9.4 GiB available. There are no Xid, OOM,
  filesystem/I/O, or critical thermal events. WSL feature-query warnings occur
  only at successful process starts and are not accompanied by runtime failure.
- Merged current `origin/main` into the journal branch. Draft PR #13 is
  mergeable, changes only this journal relative to main, and is running CI on
  the exact combined history.

Departure-gate audit:

- **Merged/deployed identity: achieved.** PR #12 primary and PR #14 overflow
  merges, exact archive/deployment hashes, and before/after primary-pin checks
  are preserved.
- **Validation and recovery semantics: achieved.** Hosted/local tests, installed
  source checks, terminal non-resume interruption, downstream halt,
  resume-safe recovery, overflow failure/success/idempotence smokes, and real
  primary-running no-ops are recorded.
- **Autonomous utilization: achieved and live.** Exactly 108B reviewed R0 steps
  across nine seed/ancestry arms fill essentially the six-day window; no dynamic
  experiment selection exists.
- **Provenance/fail-closed: achieved and live.** Both immutable plans and all
  pins validate; active progress, cgroup containment, success validators,
  runtime/progress/capacity/thermal guards, and terminal state ownership are
  observed.
- **BBTV visibility: achieved.** A prior headed-browser canvas verification,
  current public HTTP/WebSocket frames, manifested hashes, and ten live
  rollovers cover both rendered and transport paths.
- **Host resilience/capacity: achieved at this checkpoint.** Windows sleep and
  hibernate are disabled, WSL keepalive and linger are active, Tailscale has no
  key expiry, pending updates do not include a downloaded reboot-forcing OS
  package, and disk/memory/thermal/kernel guards are healthy.
- **Promotion prohibition: achieved.** The unattended graph can collect and
  validate evidence only; evaluation results require human interpretation after
  return.
- **Hourly durable reporting: achieved so far and ongoing.** The journal is
  current, branch-synchronized, committed, pushed, and covered by draft PR CI.

Current blockers / risks:

- The real primary and overflow evaluations are intentionally incomplete; no
  scientific conclusion or reward promotion can be made before their atomic
  completion artifacts exist and validate.
- A physical power/host/WSL interruption remains terminal for the current PPO
  arm by design. Host hardening reduces this risk but cannot make a
  non-resume-safe trajectory recoverable without changing the experiment.
- The GPU operates near its 81 C target with a high fan duty cycle. Stable
  checkpoint throughput, zero Xid, and inactive hardware slowdown argue against
  intervention, but temperature/fan/rate remain hourly watch signals.

Next steps:

1. Continue hourly learner, integrity, progress-freshness, pin, service,
   thermal, capacity, kernel, watcher, and BBTV checks through departure.
2. Repeat the complete host/departure gate immediately before the user leaves,
   including Windows power/update state and public BBTV transport.
3. Leave the immutable queues and promotion boundary unchanged. At primary
   completion, accept overflow start only after the exact completion proof and
   idle-GPU gates pass; never manually bypass or relaunch state.

## 2026-07-14 14:41 PDT

Event addendum:

- The 14:40:36 PDT overflow watcher completed another successful no-op while
  the primary service was active. It exited 0 with the expected `primary
  service is still active; waiting` result, retained zero restarts, and did not
  create the real overflow `QUEUE_STATE.json`.
- A fresh public secure-WebSocket session independently received the correct
  1,148,715,008-step learner versus frozen turnover3 matchup and advancing
  protocol traffic from sequence 705 through at least 742. The stream included
  the full match start/snapshot followed by live action, player, ball, dice,
  score/turn, and setup deltas; this proves current public transport and game
  progression rather than only page availability.
- During that check, the learner advanced through 1,254,883,328 steps at about
  184.4K steps/second. The newest 107-game diagnostic retained zero engine
  errors, clipped or non-finite reward episodes/samples, demos, and demo
  fallbacks. Its short-window performance, touchdown, and possession values are
  recorded as noisy health telemetry only and are not promotion evidence.
- Both immutable plans were reloaded from their deployed paths and all 65
  primary plus 74 overflow pinned inputs rehashed successfully. Draft PR #13's
  combined-history CI completed successfully; the branch remains a journal-only
  change relative to merged `main`.

## 2026-07-14 15:27 PDT

Status:

- Main-ancestry R0 seed 42 remains healthy at 1,783,103,488 exact learner
  steps (epoch 13,603 at the last complete machine panel). It advanced by
  22.2M steps across the BBTV deployment window without changing trainer PID
  `431596` or queue PID `431309`. The latest 102-game diagnostic reported
  performance 0.4755, 1.9118 touchdowns/game, possession 0.3735, historical
  win rate 0.5609, and illegal fraction 0.1781. Engine-error, clipping,
  non-finite reward, demonstration, and fallback counters were all zero. The
  panel is short-window health telemetry, not final-policy evidence.
- The RTX 2070 was 83 C with 89% fan, 76% utilization, 5,737 MiB VRAM, about
  116 W, and hardware slowdown inactive. Sustained checkpoint throughput and
  the six-day completion forecast remain consistent with the prior audit.
- The immutable primary and overflow plans revalidated immediately before and
  after the viewer deployment: 65/65 and 74/74 pins, plan hashes
  `4ee72e3c58f09786cdd3bbf78a772e8de2d9a93e21a8b065cf0c5976ecced270`
  and `d90ee01c8c459f599c8601934f545ccb7783261edae3bcb6e9e3878036d37d3e`,
  with no drift. The primary queue remains active with zero restarts. The
  15:23:26 PDT overflow watcher was another successful primary-active no-op and
  the overflow state remains absent.
- BBTV now samples legal policy actions rather than taking independent greedy
  argmax actions. It is showing the newest checkpoint available at restart,
  step 1,747,976,192, against the same frozen turnover3 baseline. The public
  page returned HTTP 200; a new external secure-WebSocket client received the
  exact sampled matchup, a full snapshot, and advancing deltas through sequence
  50. `bbstream`, `bbweb`, and `bbtv-tunnel` are active with zero restarts.

Completed since the previous full checkpoint:

- Observed two complete/near-complete greedy BBTV games before changing the
  presentation mode. Both ended 0-0 but contained active movement, blocks,
  blitzes, pickups, passes, turnovers, and rushes. One learner game made 39/39
  rush rolls. This was useful qualitative evidence of modal behavior, but two
  greedy games are neither an unbiased draw-rate estimate nor evidence that the
  rush tax is wrong: training/evaluation sample the masked policy distribution,
  and live aggregate rush volume remains near the current human reference.
- Re-traced the shaped reward. A forward carrier square is worth +0.04 while a
  rush declaration costs -0.015, leaving +0.025 for a successful forward
  carrier rush; moving toward a loose ball is +0.02, leaving +0.005; a rush with
  neither potential change pays only the cost. No reward change is justified
  by the two displayed games.
- Extended the longitudinal reward analysis. Relative to the first 200M steps,
  the recent period shows broadly stronger frozen-bank match score and more
  ball advancement, while touchdowns/possession are lower and draws are higher.
  Per-bank expected match score improved from approximately 0.467 to 0.526
  (league9), 0.611 to 0.645 (violence), 0.565 to 0.608 (netblock), and 0.528 to
  0.594 (turnover3). That pattern has no bank-collapse signature, but it keeps
  tempo/conversion as a required terminal-evaluation watch item. It also
  reinforces the decision to collect the full nine-policy matrix and not tune
  from stream aesthetics.
- Implemented the viewer-only sampled-mode change test-first. The follower now
  accepts and provenance-records `--sample`; the checked-in production launcher
  defaults `BBTV_SAMPLE=1`, with `BBTV_SAMPLE=0` as the immediate greedy
  rollback. Documentation explicitly classifies BBTV games as qualitative and
  prohibits their use for reward tuning or promotion.
- Inline review found a separate operational defect in the same follower:
  96-character truncation changed long converted names from `_torch.bin` to
  `_torch.b`, so the intended `*_torch.bin` pruning glob could never see them.
  A red regression test reproduced it. The corrected label preserves both a
  source digest and the prunable suffix within the existing 96-character bound.
  All 14 follower tests, Bash syntax, ShellCheck, and whitespace checks passed.
- PR #15 passed full hosted CI on its reviewed head, including reward/replay,
  analyzer, BC-streaming, build/unit, ASan, and UBSan contracts. External Codex
  review could not run because its local installed binary is missing; Gemini
  stopped at interactive authentication. The review record makes no external-
  review claim. Inline review plus both PR-head and merged-main CI were green.
  PR #15 merged as
  `d712d2976a40b8147db40e80ef7269a7bd14236f`; its source branch was removed.
- Built a two-runtime-file archive directly from that merge. Archive SHA-256 is
  `c0897a94822612702b971fa0141ac5b56dc67a571b54ac2790650b6a4e60fae7`;
  deployed `follow_latest.py` and `run_follow_latest.sh` hashes are
  `3560289ee7524d2e5f903fe0ae38c2a99337b2e84815b36469249fd2e25c18f5`
  and `bfee407ee4b0100521fe50a70da7647fd24c6f50cbea9cc13e99072a237ebed0`.
  Prior bytes are backed up at
  `/home/rache/deployments/pr15-bbtv-backup-before-d712d297`; production records
  commit, tree, archive, old/new hashes, and backup in
  `.deployed-bbtv-source.json`.
- The first provenance-record command discovered that the host lacks `jq` only
  after the two exact files had been overlaid. `set -e` stopped before any
  service restart. Checks proved the trainer and old viewer were still running,
  the overlay hashes were exact, and backups existed. The record was then
  generated and JSON-validated locally, copied atomically, and hashed before
  proceeding. This was a deployment-tooling correction, not an experiment or
  viewer failure.
- Restarted only `bbstream.service`. Queue, trainer, web, and tunnel PIDs were
  unchanged; the new follower and child command both contain `--sample`.
  Conversion produced the corrected digest-bearing `_torch.bin` path and the
  selected native/converted hashes are recorded in the standard sidecars. The
  sole new kernel line was the already-classified WSL feature query 10 seconds
  after viewer startup; there was no Xid, OOM, I/O, or hardware-slowdown event.

Cache-accounting correction:

- The earlier journal statement that the converted cache was already bounded
  by 24 files was incorrect. It was the intended configuration, but the long-
  label truncation excluded 30 learner cache entries (482,300,490 bytes) from
  the pruning glob. There are also 26 currently recognized `_torch.bin` entries
  (417,990,372 bytes); the active cycle has not yet reached its end-of-cycle
  prune. The 30 legacy malformed entries are retained as derived evidence and
  will not grow under the corrected naming path. Future recognized entries will
  be bounded normally. At roughly 0.9 GB total against about 900 GiB free, the
  residue does not change the capacity conclusion or justify destructive
  cleanup during a live run. The next completed BBTV cycle will verify that the
  recognized set returns to its configured bound.

Current risks / interpretation:

- Sampled BBTV is a more representative and satisfying qualitative view of the
  policy used in training/evaluation, but it is still a tiny unpaired stream
  with random matchups. Scorelines and individual decisions remain anecdotes;
  only the pinned 10,000-game terminal evaluations and post-return paired matrix
  may support reward conclusions.
- Recent broad frozen-bank strength alongside reduced touchdown tempo remains
  genuinely ambiguous: longer training may be learning stronger risk control,
  or it may be settling into draw-heavy play. Historical R0 terminal snapshots
  show the same direction, so no unattended reward mutation or promotion is
  warranted.
- Physical host/WSL interruption and sustained near-target GPU temperature
  remain the principal operational risks. Current process containment,
  throughput, pins, capacity, kernel state, and fail-closed recovery behavior
  remain healthy.

Next steps:

1. At the next two-game boundary, prove sampled BBTV selects the newest stable
   checkpoint, completes successfully, and prunes recognized cache entries to
   the configured bound while the trainer rate remains unchanged.
2. Continue hourly queue/progress/integrity, pins, thermal, storage/memory,
   kernel, overflow-watcher, and public-BBTV checks through departure.
3. Repeat the full host/departure gate before handoff. Leave both immutable
   queues and the no-promotion boundary unchanged; terminal evidence will be
   interpreted only after the user returns.

## 2026-07-14 15:35 PDT

Sampled-BBTV boundary addendum:

- The first post-deployment sampled two-game cycle completed normally after
  8 minutes 47.7 seconds. The follower did not restart, retry, quarantine a
  pair, or fall back. At 15:33:58 PDT it selected step 1,847,853,056, which was
  the greatest native checkpoint present at that exact boundary. Native
  SHA-256 is
  `00aba3f98d09b39ef52e18b80c954f772253338e7df23825b7b6b0bc0d2deb28`;
  converted SHA-256 is
  `13f314699592e5400c61c952f5f8c80d68d088e5e56b77dfc127a557c5cc1d3a`.
  Selection and server-status sidecars agree and the new child command retains
  `--sample`.
- An independent public secure-WebSocket connection received the exact 1.848B
  learner-versus-frozen-turnover3 identity, a complete snapshot, heartbeat,
  and advancing deltas through sequence 58. This proves both boundary rollover
  and live external progression, not merely service liveness.
- End-of-cycle pruning now sees corrected learner filenames. The recognized
  cache is 26 files in steady operation: up to 24 recent entries retained by
  `--keep-converted 24`, plus the old protected frozen baseline when it falls
  outside that recent set, plus the newly converted current entry prepared
  after the prior cycle's prune. This is the effective bounded maximum for the
  present sequence, not an ongoing leak. The 30 pre-fix `_torch.b` learner
  entries remain a fixed 482 MB legacy residue and no new malformed name was
  created.
- The primary queue and BBTV services remained active with zero restarts; queue
  PID `431309` was unchanged. The GPU was 82 C, 79% utilized, using 5,737 MiB
  at about 137 W with hardware slowdown inactive. The overflow state remained
  absent. No experiment, reward, queue, checkpoint, or promotion input changed.

## 2026-07-14 16:16 PDT

Status:

- Main-ancestry R0 seed 42 is healthy at 2,336,882,688 exact learner steps
  (epoch 17,828). The latest 97-game diagnostic reported performance 0.5309,
  1.5979 touchdowns/game, draw rate 0.4227, possession 0.3710, historical win
  rate 0.5564, illegal fraction 0.2016, and 8.68 forward ball squares. All
  engine-error, clipping, non-finite, demonstration, and fallback counters were
  zero. This remains health telemetry rather than final-policy evidence.
- Forty-seven checkpoints now give an end-to-end rate of 185,470 steps/second,
  median interval rate 185,356, and latest-five mean 185,540. The first 12B arm
  still projects to finish near 06:43 PDT July 15. At the same rate, the full
  remaining nine-arm schedule plus measured evaluation overhead projects near
  07:05 PDT July 21, spanning the requested six-day absence rather than leaving
  an idle tail.
- The RTX 2070 was 82 C with 89% fan, 78% utilization, 5,737 MiB VRAM, about
  108 W, and hardware slowdown inactive. A ten-minute one-minute-cadence watch
  ranged 81--83 C; isolated load-transition samples reached 84 C but were
  separated by 80--81 C samples and never approached the 88 C three-poll
  fail-closed guard. Storage remains 900 GiB free, memory 9.1 GiB available,
  and swap use 27 MiB.
- Both immutable plans revalidated again: 65/65 primary and 74/74 overflow
  pins, unchanged plan hashes, no drift. Queue, BBTV stream/web/tunnel, and
  watcher timer are active with zero restarts. The latest completed watcher was
  a successful primary-active no-op and overflow state remains absent.
- Kernel inspection since the viewer deployment found zero NVIDIA Xid/NVRM,
  OOM, I/O, critical-temperature, or shutdown events. Only the already
  classified WSL capability-query warning occurred after viewer startup.

Completed since the previous full checkpoint:

- PR #13 CI passed on exact journal head `26cac63`, including reward/replay,
  analyzer, BC streaming, build/unit, ASan, and UBSan checks. The draft is
  mergeable and remains a journal-only diff relative to current `main`.
- Verified three additional sampled BBTV cycles after deployment. They
  completed in approximately 8m48s, 11m48s, and 9m01s without restart, retry,
  quarantine, or fallback, selecting the greatest native checkpoint present at
  each boundary. The most recent selection is step 2,297,298,944; an external
  secure-WebSocket client received its exact learner/frozen identity, complete
  snapshot, and advancing deltas through sequence 98. Every child command and
  sidecar retained `--sample`.
- Observed one sampled game from pre-play setup through `match_end`. The
  current learner's Halflings, playing away against the frozen turnover3
  Lizardmen, won 1-0. The learner recorded three blocks, 3/3 rushes, and two
  turnovers; the frozen opponent recorded five blocks, 7/7 rushes, 0/2
  pickups, five turnovers, four passes, and one hand-off. This is the satisfying
  qualitative behavior BBTV is intended to expose. It is one stochastic game,
  not evidence for a reward change, checkpoint choice, or promotion.
- Ran a continuous ten-sample host watch at one-minute cadence. All five
  required units were active in every sample, hardware slowdown was inactive,
  two new learner checkpoints appeared on schedule, BBTV crossed a natural
  cycle boundary, and no overflow state appeared. This directly checks the
  sampled viewer's resource impact rather than inferring isolation only from
  code.
- Repeated the host-resilience audit. Windows remains on High Performance;
  sleep and hibernate timers are zero on AC and DC. User lingering is enabled;
  Tailscale is `Running`, online, and has no key expiry. All required user units
  are enabled and active. `RigWSLKeepalive` is enabled/running with boot,
  logon, and two-minute triggers, and its marker process has run continuously
  for 34 days. The task's repeat-trigger result `0x800710e0` is expected while
  its existing infinite instance is already running.
- Windows Update, component servicing, and the Update SystemInfo API all report
  no reboot requirement. Pending rename entries are only removal of two old
  Microsoft Edge updater directories. A fresh read-only Update API search
  returned only the not-downloaded malicious-software removal tool and a
  Defender definition; no cumulative, feature, driver, WSL, CUDA, or downloaded
  reboot-forcing update exists. No update, power, or reboot policy was changed.

Learning/reward research update:

- Recomputed the live trajectory through 2,127,298,560 steps from 16,226 valid
  schema-2 training panels representing about 1.67 million games. Behavioral
  means are game-count weighted; final reprints/eval panels are excluded; each
  frozen-bank score is reconstructed from interval `hist_score_bank_i /
  hist_n_bank_i`, avoiding the prior cumulative-panel error.
- The low-touchdown/high-draw phase was not monotonic collapse. Comparing the
  first and newest rolling 200M steps, touchdowns recovered 1.352 -> 1.627,
  possession 0.3295 -> 0.3561, and draw rate fell 0.4133 -> 0.4033. Illegal
  actions fell 0.2204 -> 0.1950, forward ball advancement rose 7.45 -> 9.12,
  pickup success 2.09 -> 2.53, blocks against the carrier 1.18 -> 1.87,
  carrier knockdowns 1.63 -> 2.32, and episode length shortened 702 -> 613.
  Rush attempts rose 16.70 -> 20.11 and total blocks thrown fell 15.28 ->
  12.22.
- Match strength did not improve monotonically with that tempo recovery.
  Overall frozen-bank expected score moved only 0.5399 -> 0.5470. Recent bank
  scores versus the first band are 0.4732 vs 0.4668 (league9), 0.6109 vs
  0.6107 (violence), 0.5623 vs 0.5645 (netblock), and 0.5507 vs 0.5279
  (turnover3). Fixed 200M bands peaked around 1.2--1.4B and then softened while
  true-game tempo recovered. This is oscillating nonstationary learning, not a
  bank-collapse signature and not a trustworthy in-sample checkpoint ranking.
- Therefore preserve and later evaluate predeclared fixed milestones as well as
  terminal checkpoints with paired mirrored held-out games; do not choose the
  visually best or highest-training-score point. The queue already retains the
  complete checkpoint curve, so no vacation mutation is required.
- Corrected BB2025 human references remain diagnostic only: 2.205 TDs/game,
  0.4745 possession, and 15.46 rush tests versus the recent learner's 1.627,
  0.356, and 20.11. Because replay states are opening-biased, action semantics
  differ, and valid play is multimodal, those numbers must not become a global
  stat-matching reward. The higher-leverage next causal arm remains the
  predesigned C2 replay-state curriculum: exact-BB2025, replay-disjoint,
  equal-weight tactical scenario starts using true game reward, annealed to
  kickoff-only evaluation.

Current interpretation / risks:

- Sampled BBTV is now both fresh and more representative of training policy
  behavior. A 1-0 learner win demonstrates its qualitative value, but the
  1.67M-game machine trajectory and future 10,000-game terminal panels remain
  the evidentiary surfaces.
- Tempo has recovered while frozen strength oscillates. This argues for the
  planned long-horizon seed/ancestry matrix, exact milestone learning curves,
  and paired held-out evaluation; it does not justify changing R0 mid-run.
- Physical host/WSL interruption remains the principal irreducible risk for
  the non-resume-safe PPO arms. Power, keepalive, network, update, capacity,
  thermal, provenance, and fail-closed checks are currently healthy.

Next steps:

1. Continue hourly learner/integrity, rate, service, pin, thermal, capacity,
   kernel, watcher, and public-BBTV checks; add material events between full
   entries.
2. Preserve fixed milestone checkpoints and pre-register the post-return paired
   learning-curve comparison. Do not select from training telemetry or BBTV.
3. Repeat the full host/departure gate near 21:00 PDT, including Windows power,
   update/reboot state, keepalive, Tailscale, both immutable plans, public BBTV,
   and the latest progress/ETA. Leave promotion disabled.

## 2026-07-14 17:16 PDT (reconstructed at 21:12 PDT)

Reporting note:

- This entry was reconstructed after the fact from immutable checkpoint mtimes,
  the last valid schema-2 training panel at or before that checkpoint, append-
  only BBTV follower output, and systemd journals. It is authoritative machine
  evidence but was not written contemporaneously. The late write is a journal-
  cadence defect, not an experiment-monitoring or host-runtime gap.

Status at the checkpoint:

- The newest complete native checkpoint was exactly 2,996,436,992 steps,
  published at 17:14:26 PDT and 94 seconds old at the target time. End-to-end
  throughput was 185,554 steps/second.
- Its matching schema-2 panel (epoch 22,860; 103 games) reported performance
  0.5388, 1.5534 touchdowns/game, draw rate 0.3786, possession 0.3780,
  historical win rate 0.5599, and illegal fraction 0.1796. Engine errors,
  clipped/non-finite rewards, demos, and fallbacks were all zero.
- BBTV started a sampled presentation of that exact checkpoint at 17:15:19
  PDT; digest prefix `5236bbed77` matches the native SHA-256. The primary and
  viewer processes later retained their original PIDs and zero-restart state,
  proving this hour was part of the same continuous run.

Next steps at that point remained unchanged: continue the immutable arm,
observe natural BBTV boundaries, and reserve all reward conclusions for the
validated terminal and paired held-out evaluations.

## 2026-07-14 18:16 PDT (reconstructed at 21:12 PDT)

Status at the checkpoint:

- The newest checkpoint was 3,645,636,608 steps, published at 18:12:40 PDT and
  200 seconds old. End-to-end throughput was 185,600 steps/second.
- The matching 116-game panel at epoch 27,813 reported performance 0.5603,
  1.5948 touchdowns/game, draw rate 0.4138, possession 0.3557, historical win
  rate 0.5676, and illegal fraction 0.1827. All five integrity families were
  zero.
- BBTV was sampled and showing the most recent completed presentation-boundary
  checkpoint, 3,545,759,744 steps, started at 18:07:05 PDT. This expected
  one-to-two-checkpoint lag reflects the two-game viewing cycle, not stale
  discovery or conversion.

No systemd failure/restart or overflow start occurred. The appropriate next
step remained passive evidence collection with no reward/config mutation.

## 2026-07-14 19:16 PDT (reconstructed at 21:12 PDT)

Status at the checkpoint:

- The newest checkpoint was 4,344,774,656 steps, published at 19:15:25 PDT and
  only 34 seconds old. End-to-end throughput was 185,613 steps/second.
- The matching epoch-33,147 panel contained 145 games: performance 0.4931,
  1.7034 touchdowns/game, draw rate 0.4207, possession 0.3848, historical win
  rate 0.5700, and illegal fraction 0.1767. Integrity counters remained zero.
- Sampled BBTV was showing boundary-selected step 4,244,897,792, started at
  19:09:22 PDT, again within normal presentation lag.

The noisy short-window performance dip alongside improving tempo reinforced
the predeclared rule not to choose checkpoints from one dashboard panel.

## 2026-07-14 20:16 PDT (reconstructed at 21:12 PDT)

Status at the checkpoint:

- The newest checkpoint was 4,993,974,272 steps, published at 20:13:38 PDT and
  142 seconds old. End-to-end throughput was 185,647 steps/second.
- The matching epoch-38,100 / 108-game panel reported performance 0.5509,
  1.7778 touchdowns/game, draw rate 0.3981, possession 0.3691, historical win
  rate 0.5761, and illegal fraction 0.1774. All integrity fields were zero.
- Sampled BBTV was presenting step 4,944,035,840 from its 20:11:15 boundary,
  less than one checkpoint behind the learner.

Across 16:16--21:10, append-only service journals contain zero stop, failure,
main-process-exit, scheduled-restart, or fallback events for the primary queue
and three BBTV units. Twenty-seven overflow watcher invocations logged the
expected primary-active no-op; none created overflow state.

## 2026-07-14 21:12 PDT — final departure gate

Current experiment state:

- The learner is at 5,630,984,192 exact steps (epoch 42,960). The latest
  107-game diagnostic reported performance 0.5701, 1.6262 touchdowns/game,
  draw rate 0.3178, possession 0.3592, historical win rate 0.5816, illegal
  fraction 0.1685, and 8.47 forward ball squares. Every engine-error, clipping,
  non-finite, demonstration, and fallback counter is zero.
- The newest complete checkpoint at the gate was 5,593,235,456 steps, only 203
  seconds old. Across 113 checkpoints, end-to-end throughput is 185,658
  steps/second, median interval throughput 185,728, and latest-five mean
  185,539. First-arm completion remains near 06:45 PDT July 15; the full nine-
  arm primary-plus-overflow matrix plus measured evaluation overhead projects
  near 06:57 PDT July 21.
- `SCREEN_STATUS.json` is fresh, names arm `both`, seed 42, index 1, and the
  exact frozen screen-manifest SHA. Queue PID `431309`, trainer PID `431596`,
  and wrapper PID `431316` are unchanged. All tasks remain in the queue cgroup;
  the only extra task seen was the queue guard's bounded 30-second sleep.

Provenance and autonomous-transition gate:

- The primary plan revalidated all 65 pins with SHA-256
  `4ee72e3c58f09786cdd3bbf78a772e8de2d9a93e21a8b065cf0c5976ecced270`.
  The overflow plan revalidated all 74 pins with SHA-256
  `d90ee01c8c459f599c8601934f545ccb7783261edae3bcb6e9e3878036d37d3e`.
  Both pin validators returned no error.
- Primary queue, BBTV stream, web service, tunnel, and overflow timer are
  enabled and active with zero restarts. The 21:01:26 watcher was a successful
  primary-active no-op, and real overflow state remains absent. It cannot start
  until the primary completion proof, exact plan/pin revalidation, and idle-GPU
  gates all pass.
- Promotion remains structurally unavailable: these are unchanged R0 control
  screens, candidate transfer is null, and no unattended path can select a
  reward or alter production.

Host/capacity/thermal gate:

- GPU snapshot: 81 C, 88% fan, 76% utilization, 5,737/8,192 MiB VRAM, about
  116 W, hardware slowdown inactive. Kernel inspection since 16:16 found zero
  Xid/NVRM, OOM, I/O, critical-temperature, or shutdown events.
- The volume has 898 GiB free and 1% inode use. Memory has 8.7 GiB available;
  swap use is 27 MiB. The primary run directory is 387 MB at 5.6B steps, in
  line with the previously bounded full-schedule projection.
- User lingering is enabled and active. Tailscale is `Running`, online, and has
  no key expiry. Windows remains on High Performance; AC/DC sleep and hibernate
  timers are zero. `RigWSLKeepalive` is enabled/running and its marker process
  remains continuously alive.
- Windows Update, component servicing, and Update SystemInfo all report no
  reboot requirement. The only pending renames are deletion of two old Edge
  updater directories. A fresh read-only Update API search found only a not-
  downloaded malicious-software removal tool and Defender intelligence update;
  no cumulative, feature, driver, WSL, CUDA, or downloaded reboot-forcing item
  exists. No policy or update was changed.

BBTV/public gate:

- BBTV is sampled and currently presents exact native step 5,493,358,592
  (source SHA prefix `785f1da12f`) against the frozen turnover3 warm. Selection
  metadata records the exact step/source/hash, the server command contains
  `--sample`, and service PID `444521` has not restarted.
- The public page returns HTTP 200. A fresh external secure-WebSocket session
  received the correct learner/frozen matchup, full snapshot, and advancing
  deltas through sequence 1,177.
- Known presentation-only caveat: the length-bounded public agent filename
  preserves the source digest and `_torch.bin` suffix but abbreviates the last
  two digits of the 12-digit step component for this long tag. Exact selection
  and provenance remain in `selection.json` and conversion metadata. Do not
  hotfix the viewer during the departure gate; correct the label layout later
  with test/review/CI while leaving training untouched.

Reporting correction and next steps:

- The missing contemporaneous 17:16--20:16 journal writes are a real reporting
  defect and are explicitly backfilled above rather than disguised. Machine
  monitoring itself remained continuous: checkpoints, schema telemetry,
  service journals, BBTV follower output, queue guards, and watcher invocations
  cover the interval with no health gap.
- Continue autonomous monitoring and durable reporting during the vacation.
  Preserve all fixed milestones for post-return paired learning-curve
  evaluation. Never promote from training telemetry or BBTV aesthetics.
- If a guard fails, accept the queue's terminal halt and preserve evidence; do
  not manually bypass pins, capacity, thermal, progress, completion, or idle-
  GPU checks. At primary success, overflow may start only through its reviewed
  watcher and exact completion validator.

Post-gate verification at 21:19 PDT:

- GitHub Actions run `29388512699` completed successfully for journal commit
  `809f1c6`. Reward/replay/analyzer contracts, BC streaming checks, build and
  unit tests, and the ASan/UBSan suite all passed. The monitoring branch is
  clean and remains an unmerged draft so later hourly evidence can be appended.

## 2026-07-14 21:31 PDT — first vacation check and exact BBTV step labels

Experiment and host state:

- The learner reached 5,849,874,432 steps (epoch 44,630). The current 100-game
  panel reported 1.6000 touchdowns/game, performance 0.5050, draw rate 0.4500,
  possession 0.3898, historical win rate 0.5831, and illegal fraction 0.1781.
  Reward clipping, non-finite rewards, engine errors, demonstrations, and
  demonstration fallbacks all remain zero.
- The newest completed checkpoint is 5,842,927,616 steps, written at 21:29:48
  PDT; the trainer log and `SCREEN_STATUS.json` remain fresh. Queue PID `431309`,
  wrapper PID `431316`, and trainer PID `431596` are unchanged with zero service
  restarts. GPU state is 81 C, 89% fan, 79% utilization, 5,737/8,192 MiB, about
  119 W, with hardware slowdown inactive. The volume still has 898 GiB free;
  memory has 8.7 GiB available and swap use is 27 MiB.
- Both plans revalidated after the viewer deployment: all 65 primary pins match
  plan SHA `4ee72e3c58f09786cdd3bbf78a772e8de2d9a93e21a8b065cf0c5976ecced270`,
  and all 74 overflow pins match plan SHA
  `d90ee01c8c459f599c8601934f545ccb7783261edae3bcb6e9e3878036d37d3e`.
  Overflow state remains absent. The 21:23 watcher invocation was a successful
  primary-active no-op. An earlier probe requested the nonexistent
  `experiment-overflow-watch@...timer`; the actual reviewed unit is
  `vacation-overflow-watch@...timer`, and it is enabled, active, and waiting.
  This was a monitoring-command naming error, not a scheduler outage.

Viewer-only provenance correction:

- The known long-tag defect truncated the last two digits of the native step in
  public converted filenames even though `selection.json` retained the exact
  value. The focused fix now reserves the complete 12-digit step, ten-digit
  source digest, and `_torch.bin` pruning suffix before abbreviating the tag.
  A long-tag regression plus a 12-case empty/short/very-long tag and step-boundary
  matrix passed; all 14 follower tests, Python compilation, Bash syntax,
  ShellCheck, and whitespace checks passed.
- PR #16 passed its complete PR-head CI: reward/replay/analyzer contracts, BC
  filtering/streaming, build/unit tests, and ASan/UBSan. Inline review found no
  P0--P3 product finding. External Codex review could not start because its
  installed bundled executable is missing; Gemini stopped at interactive
  authentication. The only hosted annotation is the repository-wide
  `actions/checkout@v4` Node-20 deprecation notice. PR #16 merged as
  `8e99a9b9cecaacddce6675be44b17e38515ca01d`; merged-main CI is still running
  at this timestamp.
- The exact one-file merged archive is
  `/home/rache/deployments/pr16-8e99a9b-bbtv.tar`, SHA-256
  `e56f5239a892947f6c78003d23eee77f0e7404b793c0f1569ce388e52545f2b4`.
  Prior bytes and deployment record are backed up under
  `/home/rache/deployments/pr16-bbtv-backup-before-8e99a9b`. Deployed
  `follow_latest.py` SHA-256 is
  `548617ab133a44fd688ede7489a65c56ae92c1a8018bac99e7abe93ca9540e2b`;
  `.deployed-bbtv-source.json` SHA-256 is
  `5095a7507db1fe7abb4224b65e97c3357da6d9f99424eb3033af0099b8cd45a2`.
- Restarted only `bbstream.service`, deliberately changing its PID from
  `444521` to `453879`. Trainer/queue, `bbweb`, and tunnel PIDs did not change.
  The new sampled child selected exact native step 5,792,989,184 with source
  SHA prefix `912a7deee3`, and its public agent label now contains the complete
  `step005792989184` value. The public page returned HTTP 200; a fresh external
  secure-WebSocket session received the exact matchup followed by `hello`,
  `match_start`, full `snapshot`, and advancing `delta` messages.

Next steps:

1. Require merged-main CI to pass and observe at least one normal two-game BBTV
   rollover with the new full-step naming before closing the viewer fix.
2. Continue the hourly queue/progress/integrity, pin, thermal, capacity,
   overflow, BBTV, and public-stream checks. Do not interpret the displayed
   sampled game as evaluation evidence.
3. Preserve every fixed checkpoint milestone. Do not choose, transfer, or
   promote any policy from live panels or viewer aesthetics.

Post-entry verification at 21:38 PDT:

- Merged-main CI run `29389029603` passed all stages on exact merge
  `8e99a9b9cecaacddce6675be44b17e38515ca01d`. Journal-head CI run
  `29389177912` also passed on commit `055e719`.
- The initial post-deploy two-game sampled cycle completed normally. Without a
  service restart, follower PID `453879` advanced from exact step 5,792,989,184
  to exact step 5,892,866,048 (source SHA prefix `41baf4c394`) at 21:37:50 PDT.
  The new converted filename retains full `step005892866048`, the digest, and
  `_torch.bin`. A fresh public WSS connection received that exact new matchup,
  a full snapshot, and advancing deltas. The viewer correction is therefore
  closed; routine hourly monitoring continues.

## 2026-07-14 21:46 PDT — fixed 6B longitudinal reward snapshot

Evidence and live state:

- Preserved an append-only copy immediately after the first learner crossed 6B:
  `/home/rache/deployments/vacation-r0-main-seed42-6b-20260714.log`,
  431,525,243 bytes, SHA-256
  `7fa83012f4bc9f0beb5a74d3cf7c3ea8618b93259d339ae865ee3f9246c17b5f`.
  The Mac copy is byte-identical. Its last complete schema-2 panel is exact step
  6,005,587,968. Analysis used 45,815 independent train panels and 4,821,395
  completed kickoff episodes; startup and non-game panels were excluded.
- Across that frozen prefix, episode-weighted totals for clipped rewards,
  non-finite rewards, engine errors, demonstrations, and demonstration
  fallbacks are all zero.
- Live training continued through the snapshot/copy and is now at 6,023,806,976
  steps. Queue PID `431309` is unchanged with zero restarts. GPU is 83 C, 89%
  fan, 81% utilization, 5,737 MiB VRAM, and hardware slowdown is inactive.

First-versus-recent 200M episode-weighted diagnostics:

| Metric | First 200M | Recent 200M |
|---|---:|---:|
| In-panel performance | 0.5232 | 0.5491 |
| Touchdowns/game | 1.3520 | 1.4965 |
| Draw rate | 0.4133 | 0.4063 |
| Possession | 0.3295 | 0.3724 |
| Illegal/sampled-repair fraction | 0.2204 | 0.1802 |
| Forward ball squares | 7.452 | 8.462 |
| Pickup successes | 2.087 | 2.708 |
| Rush attempts | 16.699 | 19.758 |
| Blocks thrown | 15.277 | 12.994 |
| 2D-red fraction | 0.0371 | 0.0438 |
| Blocks against carrier | 1.178 | 2.087 |
| Carrier knockdowns | 1.630 | 2.536 |
| Decisions/game | 702.2 | 630.7 |
| Recomputed fixed-bank score | 0.5399 | 0.6134 |

The fixed-bank score improved in every bank over the same comparison:
league9 `0.4668 -> 0.5403`, violence `0.6107 -> 0.6766`, netblock
`0.5645 -> 0.6325`, and turnover3 `0.5279 -> 0.6126`.

One-billion-step bands show why no single live panel or newest checkpoint is a
safe selector:

| Band | TD/game | Possession | Illegal frac | Ball forward | Fixed-bank score |
|---|---:|---:|---:|---:|---:|
| 0--1B | 1.3388 | 0.3291 | 0.2085 | 8.345 | 0.5563 |
| 1--2B | 1.5097 | 0.3408 | 0.1984 | 8.982 | 0.5592 |
| 2--3B | 1.5888 | 0.3600 | 0.1905 | 8.710 | 0.5642 |
| 3--4B | 1.5388 | 0.3655 | 0.1789 | 8.588 | 0.5952 |
| 4--5B | 1.5533 | 0.3687 | 0.1774 | 8.760 | 0.6046 |
| 5--6B | 1.5109 | 0.3680 | 0.1797 | 8.482 | 0.6231 |

Interpretation and next steps:

- There is no current reward-collapse signature: in-sample fixed-bank score
  rises across all six 1B bands and all four banks, action repair improves, and
  the ball is carried forward more efficiently than in the opening window.
- The trajectory is nevertheless non-monotonic. TD rate peaked in the 2--3B
  band, ball advancement peaked in 1--2B, and recent decisions/game rose from
  the 3--4B minimum while possession, pickup success, and carrier contact kept
  increasing. This could be useful strength, a style shift, or in-pool
  specialization; training-bank evidence cannot distinguish them.
- Preserve the fixed intermediate checkpoints and terminal checkpoint. After
  the run, compare milestones with paired, mirrored, kickoff-only held-out
  evaluation across opponents/rosters. Do not select from this curve, BBTV, or
  human-stat proximity, and do not mutate the reward during the vacation.

Post-entry checkpoint-retention audit at 21:50 PDT:

- The active seed-42 run directory contains 122 native checkpoints from exact
  step 131,072 through 6,042,681,344. Every adjacent save is separated by the
  expected 49,938,432-step interval; no interval is missing. The files occupy
  1,960,120,320 bytes and each has the frozen 16,066,560-byte architecture
  size. Nearest retained milestones to 1B--6B are 998,899,712;
  1,997,668,352; 2,996,436,992; 3,995,205,632; 4,993,974,272; and
  5,992,742,912 steps.
- The exact installed `pufferlib/pufferl.py` writes each interval checkpoint
  to a step-named file and contains no checkpoint rotation or deletion path.
  The screen runner and queue do not clean these native run directories.
  BBTV's `keep-converted=24` pruning is confined to its separate converted
  `_torch.bin` cache and cannot remove native learner checkpoints. At the
  current cadence, one complete 12B arm needs about 3.9 GB of native
  checkpoints; all six primary arms plus the optional three-arm overflow fit
  comfortably within the roughly 898 GiB currently free.
- Therefore no live copying, pin change, runner edit, or extra retention
  service is warranted. The native milestones already survive by construction
  and can be hashed into a post-run evaluation manifest without disturbing the
  active job.
- A first service probe incorrectly used the system manager and reported the
  templated user unit as missing. Immediate process, GPU, queue-state, and
  corrected `systemctl --user` checks showed no transition: the service has
  remained active since 12:45 PDT, queue PID `431309`, trainer PID `431596`,
  process group `431313`, persisted `running` state, and zero restarts. Future
  probes must query the user manager. This was a monitoring-command error, not
  an experiment outage or restart.

## 2026-07-14 22:21 PDT — post-run milestone evaluator frozen and reviewed

Live experiment and autonomy state:

- At 22:20:58 PDT the first primary control arm was still healthy on seed 42 at
  6,413,090,816 agent steps (epoch 48,927). Its latest 109-game train panel
  reported 1.5963 touchdowns/game, performance 0.5550, draw rate 0.3945,
  possession 0.3673, historical win rate 0.5865, illegal/sampled-repair
  fraction 0.1724, forward ball progress 8.545 squares, 19.725 rush attempts,
  and 12.780 blocks thrown. Reward clipping, non-finite rewards, engine errors,
  demonstrations, and demonstration fallbacks all remain zero.
- Queue PID `431309`, screen wrapper PID `431316`, and trainer PID `431596` are
  unchanged; the queue and user service remain `running` with zero restarts.
  The newest completed native checkpoint is exact step 6,392,250,368, written
  at 22:19:06 PDT, 16,066,560 bytes. There are now 129 interval checkpoints in
  this run directory.
- The RTX 2070 was 81 C, 89% fan, 78% utilization, 5,737/8,192 MiB VRAM, and
  113.6 W. Software thermal limiting was reported active, as throughout this
  run, while hardware slowdown remained inactive. The volume has 898 GiB free
  at 7% use, memory has 8.6 GiB available, and swap use is 27 MiB.
- Read-only revalidation matched all 65 primary pins at plan SHA
  `4ee72e3c58f09786cdd3bbf78a772e8de2d9a93e21a8b065cf0c5976ecced270`
  and all 74 overflow pins at plan SHA
  `d90ee01c8c459f599c8601934f545ccb7783261edae3bcb6e9e3878036d37d3e`.
  Overflow state remains absent. Its enabled timer is active/waiting, and the
  22:18 watcher invocation successfully exited after reporting that the primary
  service was still active.
- `bbstream`, `bbweb`, and `bbtv-tunnel` are active with zero restarts. The
  sampled follower advanced without a restart to exact checkpoint
  6,342,311,936, seed 42, source SHA-256
  `17b172ccaf408cedf965a2402dc1cce4d9d674a496f77e5c5c353c14576b7706`.
  <https://bbtv.seconds0.com/> returned HTTP 200. This remains a qualitative
  latest-checkpoint view, not policy-selection evidence.

Scientific partition correction:

- The live `historical_winrate` and earlier `league9`, `violence`, `netblock`,
  and `turnover3` summaries measure the fixed training pool. They are useful
  longitudinal diagnostics, but they are not held-out transfer evidence. The
  procedural training pool also used all roster identities, so a forced roster
  grid is balanced matchup stratification rather than unseen-roster
  generalization. The available exact learned anchors are excluded from the
  focal milestones but remain lineage-connected checkpoints, not independent
  external training lineages. The evaluator and report now state these limits
  explicitly.
- The fixed post-run Stage-A protocol is documented in
  `docs/plans/r0-milestone-evaluation.md` and implemented by
  `tools/run_checkpoint_milestone_eval.py`. It resolves exact retained
  checkpoints at warm/1/2/4/6/8/10/12B for seeds 42/43/44, within a 50M-step
  maximum gap, against the four predeclared exact learned anchors in both
  native backend roles. Common match seeds are reused across milestones, with
  2,048 games per cell and 393,216 games per completed ancestry. It reports raw
  W/D/L, TD-for/against, environment metrics, zero-integrity checks, and the
  exact 27-resample three-seed cluster bootstrap.
- Stage B compares the exact terminal to a distinct fixed-rule nonterminal
  nominee using scripted bots and the six-pair ordered roster grid. This is a
  post-run characterization and early-stopping study only: no evaluator result
  changes a reward, training queue, deployed opponent, or production default.

Implementation and review state:

- PR #17 (<https://github.com/seconds-0/bloodbowl-rl/pull/17>) now has exact head
  `cd2337682671ee3326fa940273f58d5e64dc77a6`. It validates the accepted
  `control-final` screen before freezing inputs; hashes the spec, screen
  completion/manifest/results, run manifests, warm/milestone/anchor
  checkpoints, native module, implementation files, and config tree; writes
  atomic restart-validating cells; and revalidates the complete transitive
  provenance chain before accepting completion. A shared GPU lock, idle-GPU
  gate, and explicit BBTV-quiescence gate prevent concurrent evaluation.
- Final self-review found and fixed three reproducibility gaps before merge:
  anchor order is now immutable because it determines common match seeds; the
  plateau comparator must be nonterminal and have two observed later
  milestones, preventing a vacuous terminal-versus-terminal Stage B; and the
  new regression module is now explicitly part of repository CI. The exact
  local suite passes 160 tests with two platform-specific skips, plus Ruff,
  formatting, Python compilation, and whitespace checks. Fresh GitHub CI for
  `cd23376` is still running at this entry timestamp; PR #17 remains unmerged.
- No evaluator code, plan, service, or artifact was deployed into the pinned RTX
  checkout. The active primary and overflow plan snapshots were not modified.
  The monitoring branch was advanced with the reviewed evaluator commits so it
  cannot later propose stale reverse changes after PR #17 merges.

Next steps:

1. Require green CI on exact PR #17 head `cd23376`, merge it, then merge the new
   `main` into the monitoring branch and push the journal. Do not deploy or run
   the evaluator on the occupied RTX 2070.
2. Continue hourly progress, integrity, checkpoint, pin, thermal, capacity,
   overflow, BBTV-selection, and public-transport checks while the two frozen
   primary screens run.
3. Only after an ancestry has an exact accepted `control-final` completion and
   the training GPU is idle, explicitly quiesce BBTV, freeze the Stage-A
   manifest, execute/validate the paired matrix, restore the viewer, and record
   its exact hashes. Never promote from the result automatically.

Post-entry merge verification at 22:25 PDT:

- Exact PR #17 head `cd2337682671ee3326fa940273f58d5e64dc77a6`
  passed GitHub run `29391178519`: code generation, all reward/replay/analyzer
  contracts including the new milestone evaluator tests, BC filtering and
  bounded streaming, compiled unit tests, and ASan/UBSan. The only annotation
  is the repository-wide `actions/checkout@v4` Node-20 deprecation notice.
- PR #17 merged without further changes as
  `d933dc06aa019b0a4819c14344604bae0b78d648`. The monitoring branch then merged
  that exact `origin/main`; because its evaluator blobs already matched the
  reviewed PR, the merge introduced no evaluator conflict or reverse diff.
  Deployment to the occupied RTX checkout remains intentionally deferred until
  a post-run evaluation window; the pinned live experiment remains untouched.

## 2026-07-14 23:02 PDT — hourly health check and reproducible curve correction

Live experiment and autonomy state:

- At 23:00:27 PDT the first primary control arm remained healthy on seed 42 at
  exact step 6,859,522,048 (epoch 52,333). Its latest 128-game train panel
  reported 1.6016 touchdowns/game, performance 0.5391, draw rate 0.3750,
  possession 0.3803, historical in-pool win rate 0.5896,
  illegal/sampled-repair fraction 0.1833, forward ball progress 8.065 squares,
  17.328 Rush intentions, 11.570 blocks thrown, 0.0156 pass intentions, and no
  handoff. Reward clipping, non-finite rewards, engine errors, demonstrations,
  and demonstration fallbacks were all zero in the panel.
- Queue PID `431309`, screen wrapper PID `431316`, trainer wrapper PID `431592`,
  and trainer PID `431596` are unchanged. The queue and user service are
  `running` with zero restarts; `final-main-control` is running and
  `final-second-control` remains pending. The current run directory contains
  138 interval checkpoints. The newest completed checkpoint at the check was
  exact step 6,841,696,256, 16,066,560 bytes, written at 22:59:23 PDT.
- The RTX 2070 was 81 C, 89% fan, 79% utilization, 5,737/8,192 MiB VRAM, and
  122.86 W. Software thermal limiting remained active while hardware slowdown
  remained inactive. The volume had 898 GiB free at 7% use, memory had 8.6 GiB
  available, and swap use was 27 MiB.
- Read-only plan revalidation again matched all 65 primary pins at SHA-256
  `4ee72e3c58f09786cdd3bbf78a772e8de2d9a93e21a8b065cf0c5976ecced270`
  and all 74 overflow pins at SHA-256
  `d90ee01c8c459f599c8601934f545ccb7783261edae3bcb6e9e3878036d37d3e`.
  Both pin validators returned no error. Overflow state remains absent; its
  enabled timer is active/waiting, and the 22:51 watcher exited successfully
  after observing the active primary service.
- `bbstream`, `bbweb`, and `bbtv-tunnel` are active with their original PIDs and
  zero restarts. At 23:01:59 PDT the follower selected exact checkpoint
  6,841,696,256, seed 42, source SHA-256
  `ca108eed03b45d80b4573a9a173690548171594c68a2ff3bb637a635b73d3e44`.
  <https://bbtv.seconds0.com/> returned HTTP 200 in 0.264 seconds. BBTV remains
  a qualitative latest-versus-frozen-warm viewer, never selection evidence.

Learning-curve audit correction and implementation:

- PR #18 merged D187's frozen 6B behavioral interpretation and the associated
  `AGENTS.md`, `CLAUDE.md`, and training-skill guidance. A subsequent reusable
  implementation audit found two scratch-analysis defects that require an
  append-only D188 correction: Puffer's `hist_score_bank_*` and
  `hist_n_bank_*` are both per-panel rates normalized by panel `n`, and D187's
  scratch table mixed a nominal-6B mask with the exact-checkpoint-overshoot mask
  across columns. The qualitative result is unchanged, but exact endpoint
  numbers must use one declared mask and correct episode weights.
- The unified fixed windows are `(0, 500,000,000]` and
  `(5,500,000,000, 6,000,000,000]`. Their static-pool scores are
  `0.5337228569 -> 0.6205900025`. First/last counts are 3,810/3,815 panels,
  365,615/395,560 episodes, and 175,000.000869/183,050.000779 frozen-bank
  games. The exact source extends to step 6,005,587,968, but the 5.59M-step
  checkpoint overshoot is deliberately excluded from the nominal last band.
  Every aggregate integrity total is zero.
- D188 records the full corrected table without rewriting D187. Guidance now
  points through D188. `tools/analyze_reward_learning_curve.py` hashes the full
  source, requires schema-2 independent native train panels and an exact cap,
  declares interval boundaries, applies `metric*n` episode weights, restores
  both sides of the static-pool ratio with `n`, labels the banks as in-pool, and
  explicitly says its output cannot select or promote a checkpoint or reward.
  An unequal-panel-size regression would report the deliberately constructed
  `17/25 = 0.68`, catching the original weighting class of error.
- The immutable 431,525,243-byte frozen log reproduced the report at SHA-256
  `7fa83012f4bc9f0beb5a74d3cf7c3ea8618b93259d339ae865ee3f9246c17b5f`:
  45,815 eligible panels, 4,821,395 episodes, exact cap 6,005,587,968, the two
  corrected static scores above, and no nonzero integrity total. The D188 and
  analyzer commits are `07cf4c8` and `92d5e6f` on
  `codex/reward-learning-curve-analyzer`; they are not merged at this entry.
- Local verification passes 166 analyzer/queue/replay/reward tests with two
  platform skips, Ruff, formatting, Python compilation, whitespace checks, 392
  compiled engine tests, 27 reward tests, and two contact-bot tests. The same
  392/27/2 compiled suites pass under ASan/UBSan.

Safety and next steps:

1. Self-review the two-commit D188/analyzer branch, open a PR, require fresh
   green GitHub CI on its exact head, address any review findings, and merge.
   Then merge the resulting `main` into this monitoring branch before pushing
   any post-merge journal update.
2. Continue hourly checks of exact progress, integrity, checkpoint production,
   service/PID identity, both pin sets, thermal/capacity state, the fail-closed
   overflow watcher, BBTV selection, and public HTTP transport.
3. Do not deploy the analyzer or milestone evaluator into the occupied pinned
   checkout and do not interrupt primary or overflow work. Stage-A evaluation
   remains an explicit post-run action only after accepted completion, an idle
   GPU, and BBTV quiescence; it cannot promote a reward automatically.

Post-entry review and merge verification at 23:26 PDT:

- PR #19 (<https://github.com/seconds-0/bloodbowl-rl/pull/19>) opened from the
  clean D188/analyzer branch. The installed Codex reviewer could not start
  because its package pointed at a missing native binary, and Gemini required
  an interactive login. Inline review found and fixed three P2 hardening gaps:
  remove the misleading generic mean of `historical_winrate` in favor of the
  restored bank ratio, require binary Puffer markers, and reject historical
  bank-ID schema drift.
- At the user's request, Claude Code v2.1.209 was verified in non-interactive
  mode and Fable was consulted headlessly as a read-only independent reviewer.
  Fable approved the weighting, endpoint, provenance, D188, and CI contracts,
  then identified three low/nit gaps: possible overlap for short endpoint
  windows, no explicit all-zero integrity verdict, and theoretical acceptance
  of an episode-bearing step-zero panel. Commit `1560d9c` rejects overlapping
  windows, emits `integrity_totals_all_zero` in every aggregate, rejects step
  zero after preserving empty startup panels, and adds regressions for all
  three. A focused Fable re-review approved every fix and found no regression.
- Exact-head local verification passed 168 Python contract tests with two
  platform skips, Ruff, formatting, compilation, whitespace checks, and the
  normal plus ASan/UBSan 392-engine/27-reward/2-contact-bot suites. The frozen
  6B log still reproduces 45,815 panels, 4,821,395 episodes, static scores
  `0.5337228569 -> 0.6205900025`, and explicit all-zero integrity verdicts.
  GitHub run `29393972805` then passed reward/replay/analyzer contracts, BC
  filtering/streaming, compiled tests, and ASan/UBSan on exact head
  `1560d9c0bcc1786b83aa289f009ed8b046fba67b`.
- PR #19 merged as `5fc6ae98dd03851de8f86305c0eefad6bc780823`.
  The monitoring branch merged that exact `origin/main`; its remaining PR diff
  is still only this durable journal. Claude/Fable consultation guidance was
  also added to `/Users/alexanderhuth/.codex/memories/memory_summary.md`: for
  nontrivial plan review, scientific interpretation, PR review, or debugging,
  prefer bounded `claude -p --model fable --effort xhigh` consultation with
  read-only tool allowlists and structured output, then independently verify
  the result. No live queue, pinned input, service, reward, checkpoint, or
  deployed production default changed during this work.

## 2026-07-14 23:58 PDT — hourly health check, headless Fable review, and BBTV handoff blocker

Live experiment and autonomy state:

- At 23:55 PDT `final-main-control` remained healthy at exact learner step
  7,476,477,952 (epoch 57,040), approximately 62.3% of its 12B seed-42 run.
  The current 105-game native train panel reported 1.5714 touchdowns/game,
  performance 0.5667, draw rate 0.3333, possession 0.3863, historical in-pool
  win rate 0.5918, illegal/sampled-repair fraction 0.1712, forward ball progress
  8.638 squares, 20.505 Rush intentions, 12.695 blocks thrown, and zero pass or
  handoff intentions. Every reward-clip, non-finite, engine-error,
  demonstration, and fallback counter was zero.
- Primary queue PID `431309`, screen wrapper PID `431313`, trainer wrapper PID
  `431592`, and trainer PID `431596` remain live; the queue service is
  active/running with zero restarts. `final-main-control` is running and
  `final-second-control` remains pending. The current run has 150 complete
  16,066,560-byte interval checkpoints; the newest was exact step
  7,440,957,440 at 23:53:00 PDT. The dashboard estimated 182.3K SPS and about
  6h54m remaining in this seed-42 arm.
- The RTX 2070 was 81 C, 89% fan, 76% utilization, 5,737/8,192 MiB VRAM, and
  127.75 W. Software thermal limiting remained active; hardware slowdown was
  inactive. The reviewed plans' thermal ceiling is 88 C, sampled every 30
  seconds with a three-poll sustained-hot guard. Disk had 897 GiB free at 7%
  use, memory had 8.5 GiB available, and swap use was 27 MiB.
- Primary plan SHA-256
  `4ee72e3c58f09786cdd3bbf78a772e8de2d9a93e21a8b065cf0c5976ecced270`
  still has all 65 pinned files and no pin error. Overflow plan SHA-256
  `d90ee01c8c459f599c8601934f545ccb7783261edae3bcb6e9e3878036d37d3e`
  still has all 74 pinned files and no pin error. Overflow state remains
  absent. Its enabled timer is active/waiting; the 23:46 watcher poll exited
  successfully after observing that the primary service is still active.
- `bbstream`, `bbweb`, and `bbtv-tunnel` are active with zero restarts. BBTV
  selected exact seed-42 checkpoint 7,391,019,008 at 23:52:18 PDT, source
  SHA-256 `bef8f0c2254ce5d37767ac000bf6fe12a4d63aa8c8388875cbb2e1d8e5eb0428`,
  against the frozen turnover3 baseline. The public page returned HTTP 200 in
  0.250 seconds. It remains qualitative only.

Headless Claude/Fable capability and independent review:

- Claude Code v2.1.209 supports bounded noninteractive use through `claude -p`
  with `--model fable`, effort, text/JSON/stream-JSON output, JSON Schema,
  read-only `--allowedTools`, `--permission-mode dontAsk`, turn and dollar
  limits, optional resume, and `--no-session-persistence`. The global Codex
  memory now says to consult Fable for nontrivial scientific, plan, PR, and
  debugging review with bounded read-only permissions, then independently
  verify its conclusions. This is advisory, not permission to modify external
  state.
- Fable's six-day autonomy review returned `READY_WITH_ACTIONS`: the frozen
  primary plus overflow budgets approximately 159 training hours for the
  144-hour vacation, but thermal trend/ETA, the no-evaluation-until-overflow-
  terminal rule, recovery notes, and the BBTV/GPU handoff needed explicit
  attention. Its source-only inference that BBTV would not occupy the GPU was
  subsequently falsified by live evidence, reinforcing the independent-
  verification rule.

Accepted D189 finding and fix status:

- The exact GPU parser pinned by the overflow completion config returned
  `[431596, 460528]`: the trainer and the current BBTV match server. Repeated
  direct queries and the server's `/dev/dxg` descriptors confirm BBTV is a real
  compute PID. The follower hides CUDA only for checkpoint conversion; its
  match child inherits GPU access. Because both the primary-completion report
  and the overflow starter's immediate recheck require an empty compute-PID
  list, always-on GPU BBTV would strand the overflow after primary completion.
- A spare-port probe with `CUDA_VISIBLE_DEVICES=` disappeared from the GPU PID
  list but failed during policy construction: the isolated viewer extension is
  compiled with `_C.gpu=1`, so PuffeRL attempted CUDA and raised `No CUDA GPUs
  are available`. Environment hiding alone is therefore not deployable.
- D189 records the reviewed resolution without weakening or changing either
  queue: build a second isolated fp32 CPU viewer with `./build.sh bloodbowl
  --cpu`; prove the exact imported `_C` path, SHA-256, `env_name=bloodbowl`,
  `gpu=0`, and `precision_bytes=4`; hide CUDA from match children; prove both a
  current-checkpoint and static-fallback WebSocket cycle on a private port; and
  require the exact pinned parser to show only the trainer before restarting
  `bbstream` alone.
- Fable's focused design review returned `APPROVE_WITH_CHANGES`. The patch now
  decouples the existing viewer Python environment from the new CPU source
  tree, injects that tree only into the match child, validates the in-tree
  native module before follower startup, and defines rollback as removing the
  whole systemd follower override. A partial rollback to the old GPU viewer
  while retaining CUDA hiding is explicitly forbidden. All 15 focused BBTV
  unit tests, shell syntax, and whitespace checks pass locally. The CPU viewer
  has not yet been built, the PR has not yet been opened, and production BBTV
  has not been restarted; the active trainer and every pinned input remain
  untouched.

Next steps:

1. Build and provenance-check the separate CPU viewer tree without modifying
   the trainer or existing GPU viewer; run isolated latest-policy and forced-
   fallback WebSocket probes and measure trainer SPS before/during them.
2. Enumerate both plans' pinned paths and prove zero overlap with the explicit
   BBTV deploy list. Finish review, open the D189 PR, require green exact-head
   CI, merge, and deploy only the BBTV-side files from the merged archive.
3. Restart only `bbstream` at a match boundary. Verify public HTTP/WebSocket,
   checkpoint freshness, the exact parser showing trainer-only, unchanged
   primary service/PIDs/progress, and byte-identical primary/overflow pins.
4. Continue hourly durable health checks. Do not run the milestone evaluator
   until both primary and overflow are terminal, the GPU is idle, and BBTV is
   explicitly quiesced.

Post-entry D189 merge and deployment verification at 00:15 PDT:

- The separate CPU viewer build completed without touching the trainer or old
  GPU viewer. Its exact in-tree module is
  `/home/rache/bloodbowl-rl-bbtv-cpu/vendor/PufferLib/pufferlib/_C.cpython-311-x86_64-linux-gnu.so`,
  SHA-256 `0814398b0685438e9b23bfbb20f45d5b88fcd2c0c829f5448dec2ec59d8188d1`;
  it reports `bloodbowl`, `gpu=0`, and fp32. The 439-file source snapshot digest
  is `baa348a27edf6cfc43970c860bc0d99bee9577b38dfdb47ed99e91233abaa90f`.
- Separate latest-checkpoint and forced static-fallback probes each delivered
  public-protocol messages `hello`, `match_start`, and `snapshot`; neither CPU
  probe appeared in the exact pinned GPU parser. A 29.91-second worst-case
  overlap probe advanced training 5,505,024 steps, approximately 184K SPS, so
  the low-priority CPU viewer did not measurably reduce the 182.3K dashboard
  baseline.
- Fable's final exact-diff review returned `APPROVE`. Its two nonblocking
  hardening suggestions were applied before ship: the startup identity import
  also hides CUDA, and documentation makes the converter-versus-match import
  boundary explicit. PR #20 passed GitHub run `29396272190` on exact head
  `663245e8a8f5ef3c82f516f63f22b3a7dd401ef9`: reward/replay/analyzer
  contracts, BC streaming, compiled unit tests, and ASan/UBSan. It merged as
  `11bfe7c2d5c99cb744b5202754e2440b768da322`.
- The explicit two-file deploy list had zero overlap with either the 65 primary
  or 74 overflow pins. Only merged `stream_backend/follow_latest.py` and
  `stream_backend/run_follow_latest.sh` were staged from the exact merge
  archive and overlaid into the artifact-preserving production tree. Their
  deployed SHA-256 values are respectively
  `f24fe6c570a3ac87525168f851cd1ba3f5c70af5cc231e334c0c62adfbe0c192`
  and `01061aa832ade80314716b1105a84799a414c074cd52c6d43cd39c93dd32d946`;
  the prior copies are preserved under
  `/home/rache/deployments/pr20-backup-before-11bfe7c2`.
- Only `bbstream` was restarted. Local and public WebSockets both immediately
  delivered `hello`, `match_start`, and `snapshot`; public HTTP returned 200.
  The live match child maps the exact CPU module above with
  `CUDA_VISIBLE_DEVICES=` and
  `PYTHONPATH=/home/rache/bloodbowl-rl-bbtv-cpu/vendor/PufferLib`. The exact
  pinned GPU parser now returns only trainer PID `431596`; BBTV is no longer a
  handoff blocker. It selected fresh exact checkpoint 7,640,711,168, source
  SHA-256 `2f404238dd485cb55e97faa68d40cf6cc703af360e7784b83dff14f4698911ba`.
- Queue PID `431309`, trainer wrapper `431592`, and trainer `431596` were proved
  unchanged after the earlier shell self-match was corrected. Training then
  advanced to exact step 7,678,459,904 (epoch 58,581) with all displayed clip,
  non-finite, and error counters zero. Both plan validators still return no
  pin error. Atomic identical provenance records were written at
  `/home/rache/bloodbowl-rl/.deployed-bbtv-source.json` and
  `runs/bbtv-follow/VIEWER_PROVENANCE.json`, SHA-256
  `c80415ec13c1917756e7d592147487772c24b92a10127b2d14fc1341ec7b0955`.
- Removing BBTV briefly let the trainer draw up to 166.65 W and produced one
  85 C sample, still below the immutable 88 C three-poll ceiling. Seven samples
  across 30 seconds then ranged 80–85 C with 88–89% fan, 74–80% utilization,
  intermittent software thermal limiting, and no hardware slowdown. There was
  no sustained-hot sequence and no guard action.

## 2026-07-15 00:53 PDT — hourly health check and provenance-bound 8B curve

Live experiment and autonomy state:

- At 00:51 PDT `final-main-control` remained healthy at exact learner step
  8,097,497,088 (epoch 61,778), approximately 67.5% of its 12B seed-42 run.
  The latest complete 102-game native train panel reported 1.6176
  touchdowns/game, performance 0.5539, draw rate 0.3627, possession 0.3934,
  historical in-pool win rate 0.5939, illegal/sampled-repair fraction 0.1720,
  forward ball progress 8.571 squares, 20.706 Rush intentions, 11.490 blocks
  thrown, 0.0098 pass intentions, and zero handoff intentions. Reward-clip,
  non-finite, engine-error, demonstration, and fallback episode counters were
  all zero.
- Primary queue PID `431309`, screen wrapper PID `431313`, trainer wrapper PID
  `431592`, and trainer PID `431596` remain live and unchanged. The primary
  service is active/running with zero restarts; `final-main-control` is running
  and `final-second-control` remains pending. Run `1784058310965` has 163
  complete 16,066,560-byte checkpoints; the newest observed interval file was
  exact step 8,090,157,056. No completion or handoff was inferred from a
  dashboard line.
- The 65-file primary and 74-file overflow pin sets revalidate with no error.
  Their plan SHA-256 values remain respectively
  `4ee72e3c58f09786cdd3bbf78a772e8de2d9a93e21a8b065cf0c5976ecced270`
  and
  `d90ee01c8c459f599c8601934f545ccb7783261edae3bcb6e9e3878036d37d3e`.
  Overflow state remains absent and its service inactive. The enabled timer's
  00:51 watcher invocation returned success after observing that primary was
  still active; it did not create state or start overflow.
- The exact pinned GPU parser returned only trainer PID `431596`. Seven samples
  over 30 seconds held at 81–82 C, 88–89% fan, 75–81% utilization, 5,554 MiB
  VRAM, and 114.65–148.06 W. Software thermal limiting was intermittent and
  hardware slowdown remained inactive. This is below the plans' current 88 C,
  three-consecutive-poll guard. Disk remains 7% used with 897 GiB free, inodes
  1% used, memory 8.9 GiB available, and swap use 27 MiB.
- `bbstream`, `bbweb`, and `bbtv-tunnel` are active with zero restarts. The CPU
  follower selected exact seed-42 checkpoint 8,040,218,624 at 00:47 PDT,
  source SHA-256
  `af8c1e572838a45ff4a1f72ccb9d48d75d240134da93a7c32236e07a5b2d9234`,
  against the frozen turnover3 baseline. Public HTTP returned 200 in 0.252
  seconds. BBTV is current qualitative visibility only and remains outside the
  GPU handoff gate.

Provenance-bound 8B descriptive curve:

- After seed 42 crossed the nominal 8B landmark, the live log was not edited or
  truncated. A separate frozen copy ending at the first complete schema-2 panel
  at or beyond the landmark is
  `/home/rache/deployments/vacation-r0-main-seed42-8b-20260715.log`: exact cap
  8,000,110,592, 574,748,729 bytes, 4,004,961 lines, and SHA-256
  `e776e4f9d1c5d0aa7e6f6fa354bba9b36bbab825cba1c17200e793251508857e`.
  Its adjacent JSON records those bounds and identity. The immutable
  `origin/main` analyzer produced
  `/home/rache/deployments/vacation-r0-main-seed42-8b-curve-20260715.json`,
  SHA-256
  `949cdf992ea87049f977e59cd77abc11338865d550caf50c30e4f6952258326d`.
- The report saw 61,037 machine panels, accepted 61,032 independent native
  train panels, and episode-weighted 6,434,021 games through the exact cap. All
  aggregate integrity totals are zero. Its declared first endpoint is
  `(0, 500M]`; its comparable last endpoint is `(7.5B, 8B]`, deliberately
  excluding the 134-game post-8B sliver from the endpoint comparison.
- First-to-last endpoint movement is directionally encouraging: static in-pool
  score `0.5337 -> 0.6198`, performance `0.5191 -> 0.5574`, touchdowns
  `1.3350 -> 1.6410`, possession `0.3304 -> 0.3819`, illegal fraction
  `0.2161 -> 0.1759`, and forward ball progress `7.937 -> 8.559`. Total blocks
  fell `14.493 -> 12.269`, while blocks against the carrier rose
  `1.169 -> 2.054` and their fraction rose `0.0865 -> 0.1790`. Rush intentions
  rose `17.387 -> 19.293`; pass and handoff intentions remained nearly absent.
- This is not a monotonic learning curve or selection evidence. The static
  in-pool score reached 0.6196–0.6260 at 5–6.5B, peaked at 0.6313 in the
  6.5–7B band, fell to 0.6137 in 7–7.5B, and partly recovered to 0.6198 in
  7.5–8B. The bank is part of training rather than a holdout. These data support
  the narrower conclusion that the run learned substantial behavior before a
  noisy plateau; they cannot choose a checkpoint, establish external strength,
  or promote the reward.

Completed operational hardening and next steps:

- PR #21 merged the Fable-reviewed fault/return runbook as
  `5fe2b21bcacd17c97c90de3bb2bc5b529b358606`. It makes evaluation a separate-
  checkout action, requires the overflow timer/state to be explicitly resolved
  before return-day evaluation, verifies pinned monitoring-module hashes before
  import, and treats the displayed guard values as current plan facts rather
  than timeless defaults. It was intentionally not deployed into the occupied
  audit snapshot.
- The global Codex memory records the safe headless Fable consultation pattern
  and the session-persistence caveat. Fable remains advisory: every suggested
  change is independently checked against the live system and frozen contracts.
- Continue hourly service/PID, progress, integrity, pins, timer, thermal,
  capacity, BBTV-selection, and public-transport checks. Preserve the 8B report
  as descriptive interim evidence and allow the frozen queue to finish.
  Milestone evaluation remains pending until primary and overflow are terminal,
  the GPU is idle, the overflow timer cannot fire, and BBTV is explicitly
  quiesced. No reward, checkpoint, plan, pin, queue order, or production
  training default changed in this interval.

## 2026-07-15 01:34 PDT — hourly health check and behavior-evidence hardening

Live experiment and autonomy state:

- At 01:33 PDT `final-main-control` remained healthy at exact learner step
  8,562,540,544 (epoch 65,326), approximately 71.4% of its 12B seed-42 run.
  The latest complete 109-game native train panel reported 1.7890
  touchdowns/game, performance 0.5321, draw rate 0.3670, possession 0.3923,
  historical in-pool win rate 0.5957, illegal/sampled-repair fraction 0.1663,
  forward ball progress 8.586 squares, 19.872 Rush intentions, 12.110 blocks
  thrown, 2.046 blocks against the carrier, carrier-target fraction 0.1779,
  1D fraction 0.2212, 2D-red fraction 0.0442, 0.0092 pass intentions, and zero
  handoff intentions. Reward-clip, non-finite, engine-error, demonstration, and
  fallback episode counters were all zero.
- Primary queue PID `431309`, screen wrapper `431313`, trainer wrapper `431592`,
  and trainer `431596` remain live and unchanged. The primary service is
  active/running with zero restarts; `final-main-control` remains running and
  `final-second-control` remains pending. Run `1784058310965` has 172 complete
  16,066,560-byte checkpoints; the newest observed interval checkpoint was
  exact step 8,539,602,944.
- The 65 primary and 74 overflow pins revalidate without error at unchanged plan
  SHA-256 values
  `4ee72e3c58f09786cdd3bbf78a772e8de2d9a93e21a8b065cf0c5976ecced270`
  and
  `d90ee01c8c459f599c8601934f545ccb7783261edae3bcb6e9e3878036d37d3e`.
  Overflow state remains absent and its service inactive. The enabled timer is
  active/waiting; its 01:24 watcher run returned success after observing that
  primary was still active and made no state change.
- The exact pinned GPU gate returned only trainer PID `431596`. Seven samples
  over 31 seconds held at 80–84 C, 88–89% fan, 78–82% utilization, 5,554 MiB
  VRAM, and 107.09–177.80 W. Software thermal limiting was intermittent and
  hardware slowdown remained inactive. No sample reached the current 88 C,
  three-consecutive-poll queue guard. Disk has 896 GiB free at 7% use, inodes
  are 1% used, memory has 8.8 GiB available, and swap use is 27 MiB.
- `bbstream`, `bbweb`, and `bbtv-tunnel` remain active with zero restarts. The
  CPU viewer selected exact seed-42 checkpoint 8,439,726,080 at 01:26 PDT,
  source SHA-256
  `aba23c7a31e7dd9622cd5cf8fc5b899631ef0be2fff46a7b8a6c4e3febd2ec89`,
  against the frozen turnover3 warm baseline. Public HTTP returned 200 in
  0.214 seconds. BBTV remains qualitative and outside the GPU handoff gate.

BH-001 and merged milestone-evaluator hardening:

- The 8B scientific review exposed a contract defect: Stage-A cells already
  wrote raw native environment metrics, but `validate_cell` and the final
  analysis accepted a cell that omitted them and then reduced the durable
  report to score, draws, touchdowns, and integrity. A focused regression
  proved the omission on the prior code before the fix.
- The post-run evaluator now requires a fixed 23-metric behavior panel covering
  illegal repairs, block volume/dice tiers/carrier targeting, possession, ball
  movement, dodge/Rush/pickup/pass/handoff actions, and knockdown outcomes. It
  rejects missing, non-object, non-finite, negative, out-of-range, pickup-
  inconsistent, or per-team-block-inconsistent evidence. Validated joint
  behavior means and warm deltas survive into `ANALYSIS.json`; focal and
  opponent block volumes use explicit side counters.
- Orientation is no longer an implicit assumption. One checked mapping loads
  the focal policy as team 0 for orientation 0 and team 1 for orientation 1,
  writes `focal_team` plus policy-A/policy-B path identity into the cell, and is
  reused by production assembly and validation. Orientation-asymmetric tests
  fail if focal/opponent paths or block counters are swapped. Side counters are
  excluded from `joint_behavior`; all remaining metrics are explicitly labelled
  as match-level behavior of both policies and cannot be attributed to the focal
  policy alone.
- The tests now build every synthetic cell through the same pure payload
  assembler called by `run_cell`, closing the producer/validator schema-drift
  class that caused BH-001. Before the first real cell, `verify_plan_sources`
  still re-hashes the compiled module, package/config/tree, runner, and analyzer;
  the payload records that just-observed frozen identity. A live native panel
  contained all 23 keys and its per-team block sum differed from total by less
  than `5e-7`, well inside the fail-closed `2e-4` float tolerance.
- Three bounded, tools-disabled Fable review passes found the implicit mapping,
  swap-invariant test, joint-label, tolerance/preflight, and producer-schema
  issues. Each concrete finding was independently checked and resolved. Local
  verification passed 171 Python contracts with two platform skips, Ruff,
  formatting, whitespace, 392 engine tests, 27 reward tests, two contact-bot
  tests, and the same compiled suites under ASan/UBSan. PR #22 passed exact-head
  GitHub run `29400744247` on
  `38d4b38e8e1cbceb7d0f9f05d28664f3a15d9ddc` and merged as
  `af1240c35e8e9d25e7c50dcc750d9f8e46aa1e35`. The monitoring branch merged
  that main as `5bc3555`; the active pinned audit checkout was not modified.

Corrected 8B interpretation and replay boundary:

- Fable's valid high-level warning is to test whether carrier-focused blocking
  reflects tactics or reward following, but its rough `~0.75` carrier-block
  comparison was not a faithful description of this implementation. R0 emits
  a zero-sum declaration-time expectation:
  `p_deliver * (0.10*P(def-down) + 0.50*P(removal)*victim_cost/100k +
  0.15*P(ball-out))`, then subtracts `0.15*P(block-turnover)` and
  `0.03*P(own-turnover)*pending-safe-activations`. It does not pay a flat or
  realized 0.50 injury coupon. The canary remains important, but magnitude and
  causality must come from the fixed evaluation rather than coefficient sums.
- Across the last six complete 500M bands `(5B,8B]`, static in-pool score has
  mean 0.6228, range 0.6137–0.6313, and an ordinary descriptive slope of
  `-0.00255/B`; performance is essentially flat. Touchdowns and possession keep
  rising while illegal repairs fall. Carrier-block count/fraction are stable to
  slightly down late; 2D-red share improves, while 1D share worsens. Rush
  attempts fall from 20.95 to 19.29 across those bands. This supports a noisy
  performance plateau with continuing behavior change, not a demonstrated
  regression, escalating carrier farm, or runaway rushing. The bands are
  temporally correlated policy snapshots, not millions of independent samples.
- Pass and handoff intentions were already nearly absent in the first 500M
  window, so the curve proves a persistent capability hole, not that this run
  newly extinguished passing. The exact-BB2025 replay corpus cannot repair or
  validate that hole alone: it contains only 313 pass-target and 356 handoff-
  target labels among 1,622,231 records, all records are from half one, and
  turns 1–2 dominate. Replay-derived states remain appropriate for opening,
  loose-ball, pickup, block/assist, and selected carrier-safety probes with new
  dice. Authored, predeclared fixtures are required for passing and late-game
  score/clock/reroll decisions; replay outcomes must not label pre-dice action
  quality.

Next steps and safety boundary:

1. Continue hourly live checks and allow all frozen primary/overflow work to run
   without adaptive checkpoint selection or reward changes.
2. Preserve the merged evaluator as post-run code only. Do not deploy it into
   the occupied pinned checkout or start it while either queue can run.
3. After both queues are terminal, the GPU is idle, the overflow timer cannot
   fire, and BBTV is explicitly quiesced, freeze Stage A in a separate checkout.
   Use its fixed milestone/opponent/seed grid to determine whether score and the
   validated behavior panel transfer together. No result promotes a reward or
   checkpoint automatically.

## 2026-07-15 02:33 PDT — hourly health check and future-run reward attribution

Live experiment and autonomy state:

- At 02:29 PDT `final-main-control` remained healthy at exact learner step
  9,195,225,088 (epoch 70,153), approximately 76.6% of its 12B seed-42 run.
  The latest complete 106-game native train panel reported 1.3396
  touchdowns/game, performance 0.4764, draw rate 0.4057, possession 0.3887,
  historical in-pool win rate 0.5987, illegal/sampled-repair fraction 0.1770,
  forward ball progress 8.115 squares, 18.774 Rush intentions, 11.679 blocks
  thrown, 2.142 blocks against the carrier, carrier-target fraction 0.1955,
  1D fraction 0.1809, 2D-red fraction 0.0453, and zero pass or handoff
  intentions. Reward-clip, non-finite, engine-error, demonstration, and
  fallback episode counters were all zero.
- Primary queue PID `431309`, screen wrapper `431313`, trainer wrapper `431592`,
  and trainer `431596` remain live and unchanged. The exact primary service is
  active/running with zero restarts; `final-main-control` remains running and
  `final-second-control` pending. Run `1784058310965` has 184 complete
  16,066,560-byte checkpoints; the newest observed interval checkpoint was
  exact step 9,138,864,128.
- The 65 primary and 74 overflow pins revalidate without error at unchanged
  plan SHA-256 values
  `4ee72e3c58f09786cdd3bbf78a772e8de2d9a93e21a8b065cf0c5976ecced270`
  and
  `d90ee01c8c459f599c8601934f545ccb7783261edae3bcb6e9e3878036d37d3e`.
  Overflow state remains absent, its latest watcher invocation returned success
  without starting work, and its enabled timer is active/waiting.
- The exact GPU process query returned only trainer PID `431596`. Seven samples
  over 30 seconds held at 81-84 C, 88-89% fan, 75-83% utilization, 5,554 MiB
  VRAM, and 117.77-168.51 W. Software thermal limiting was intermittent and
  hardware slowdown remained inactive. No sample reached the current 88 C,
  three-consecutive-poll queue guard. Disk has 896 GiB free at 7% use, inodes
  are 1% used, memory has 8.8 GiB available, and swap use is 27 MiB.
- `bbstream`, `bbweb`, and `bbtv-tunnel` remain active with zero restarts. The
  CPU viewer selected exact seed-42 checkpoint 9,138,864,128 at 02:25 PDT,
  source SHA-256
  `9fe2fdb8d383bb0264ce19b6d254ad3f2369e020788f4e16b12d4bedb2c7daa9`,
  against the frozen turnover3 warm baseline. Public HTTP returned 200 in
  0.338 seconds. BBTV remains qualitative visibility and outside the GPU
  handoff gate.

Future-run reward attribution tranche:

- In an isolated checkout based on merged `origin/main`, added one centralized
  reward-emission seam and a 28-channel signed episode ledger covering every
  ordinary reward family. It exports the team-0/home perspective so zero-sum
  terms do not disappear, preserves a signed float residual, separates raw
  component totals from signed clamp delta and post-clamp return, and counts
  component mismatches/non-finite values as integrity failures. Terminal
  attribution follows the repaired semantics: discard incidental terminal-step
  shaping, preserve explicit touchdown reward, then add result/statmatch once.
- The Puffer log contract grows from 88 to 123 environment keys. Both vector
  dictionary allocations and the visible dashboard limit are raised from 96 to
  160, with installer migrations, drift checks, launcher guards, and four
  machine-readable Python contract tests. `CLAUDE.md`, `AGENTS.md`, the Puffer
  environment skill, and new D190 explicitly say this telemetry is diagnostic,
  future-only, and cannot be attributed retroactively to the active pinned run.
- Behavior-locking evidence remains green: pristine and instrumented default
  1,000-episode and R0 100-episode trajectory hashes match; throughput is
  indistinguishable; all 431 C tests pass normally and again under ASan/UBSan;
  and all four Python log-contract tests pass. A real vectorized Puffer CPU
  smoke completed 128 evaluation episodes with 132 JSON fields and nonzero
  setup-autofix/touchback attribution; component sum reconciled to post-clamp
  and episode return within float tolerance with zero mismatch/non-finite
  counters.
- Fable's first tools-disabled architecture review approved the arithmetic with
  requested hardening around dashboard capacity, real vector execution,
  call-site labels, draw/objective-bypass tests, dead code, and exact-float
  wording. Those findings are resolved. A final complete-diff Fable review is
  still running; no PR or merge will precede its verdict. This checkout has not
  been installed on the 2070, and the active source, module, plans, pins, queue,
  trainer, and reward coefficients remain unchanged.

Next steps and safety boundary:

1. Finish the bounded Fable review; fix and re-run verification for any concrete
   finding, otherwise commit the exact reviewed tree and require exact-head CI
   before merge.
2. Treat merge to `main` as availability for future builds only. Do not install
   or rebuild it in the occupied audit checkout and do not claim component
   attribution for the live vacation logs.
3. Continue hourly live checks and BBTV latest-checkpoint visibility. Start the
   fixed milestone evaluator only after primary plus overflow are terminal, the
   GPU is idle, the overflow timer cannot fire, and BBTV is explicitly quiesced.

02:40 PDT addendum:

- The final complete-diff Fable review found one documentation-only error in the
  clamp identity and otherwise approved the code, terminal semantics,
  dictionary/dashboard migration, tests, and vacation-queue boundary. The two
  guides now state the tested identities: component sum plus residual equals
  raw `episode_return`; raw return minus signed clamp delta equals post-clamp
  return; any nonzero clamp delta independently fails integrity.
- Reward/replay/analyzer contracts, corpus streaming checks, the normal C suite,
  and ASan/UBSan all passed in exact-head GitHub run `29405017314` on
  `946ae5ffb38c1ef1fc61dc3e381d28e2c528090f`. PR #23 merged as
  `97edd7c1799471d6cfc4ea55930590a4e0f0c990`. This makes the ledger available
  to future builds only; no file, process, pin, plan, module, or service in the
  occupied 2070 audit checkout was changed.

## 2026-07-15 03:28 PDT — hourly health check and strict-BB2025 scenario foundation

Live experiment and autonomy state:

- At 03:27 PDT `final-main-control` remained healthy at exact learner step
  9,840,099,328 (epoch 75,073), approximately 82.0% of its 12B seed-42 run.
  The latest complete 94-game native panel reported performance 0.5532, 1.5957
  touchdowns/game, draw rate 0.3404, possession 0.3764, historical in-pool win
  rate 0.6018, illegal/sampled-repair fraction 0.1721, forward ball progress
  8.342 squares, 19.032 Rush intentions, 11.766 blocks thrown, 1.989 blocks
  against the carrier, carrier-target fraction 0.1941, 1D fraction 0.2171,
  2D-red fraction 0.0328, 0.0213 pass intentions, and zero handoffs. Reward
  clipping, non-finite reward, engine-error, demonstration, and fallback
  counters were all zero.
- The exact primary service remains active/running with queue PID `431309` and
  zero restarts; `final-main-control` remains running and
  `final-second-control` pending. Trainer PID `431596` is still the only GPU
  compute process. Run `1784058310965` now has 198 complete 16,066,560-byte
  checkpoints; the latest observed interval checkpoint is exact step
  9,838,002,176.
- All 65 primary and 74 overflow pins revalidated with no error at unchanged
  plan SHA-256 values
  `4ee72e3c58f09786cdd3bbf78a772e8de2d9a93e21a8b065cf0c5976ecced270`
  and
  `d90ee01c8c459f599c8601934f545ccb7783261edae3bcb6e9e3878036d37d3e`.
  Overflow state is still absent. Its watcher service is inactive/dead with a
  successful result and zero restarts, while the enabled timer remains
  active/waiting.
- Seven GPU samples over 30 seconds held at 80–83 C, 88–89% fan, 76–81%
  utilization, 5,554 MiB VRAM, and 113.39–166.42 W. Software thermal limiting
  was intermittent; hardware thermal slowdown was absent. No sample approached
  the 88 C three-poll queue guard. Disk remains 7% used with 896 GiB free,
  inodes 1% used, memory 8.7 GiB available, and swap use 27 MiB.
- `bbstream`, `bbweb`, and `bbtv-tunnel` are active with zero restarts. The CPU
  viewer selected exact checkpoint 9,738,125,312 at 03:22 PDT, source SHA-256
  `5859f805f793b5e2497f640d750f689117d3ca30a13eb5d7a23ec4a4ed1619ce`,
  against the frozen turnover3 baseline. Public HTTP returned 200 in 0.242
  seconds. BBTV remains observational and holds no GPU process.

Strict-edition state-bank tranche:

- A standalone streaming filter now turns the historical mixed BBS bank into
  an exact, provenance-bound BB2025 subset without decoding or rewriting match
  blobs. It requires the canonical bank and allowlist hashes, validates all
  BBS1 boundaries and metadata, detects source mutation, and publishes a
  selected-ID sidecar plus deterministic manifest through exclusive,
  ownership-safe same-directory hard links. The manifest is the commit marker;
  racing writers cannot be overwritten.
- The canonical double-run selected 15,348 records from 5,328 replay IDs and
  excluded 123 records from 42 IDs. An independent polite fetch confirmed all
  42 exclusions embed `rulesVersion=BB2020`. The output bank SHA-256 is
  `bcd9daf55ac5d177f48160092f17a9b4978da877455b830ba33a9c1b5ba84d22`;
  the selected-ID SHA-256 is
  `7e22604b51010317059213f285e30a90d6f8fc2b2b358ec5d71fbcd09130c6fd`.
  The existing reader accepted every record, and the header plus full ordered
  body matched the source exactly.
- Two complete Fable reviews approved the filter with no blockers; its
  concurrency and post-commit cleanup notes were hardened before publication.
  Eight focused tests, 179 Python contracts, all 431 normal C tests, and all
  431 ASan/UBSan tests passed. Exact-head GitHub CI run `29407279791` passed on
  `6d6f325852def41c9372fab35780c4bea5697b71`; PR #24 merged as
  `a03a2ab3cbb28f2a7d92b697ee3f131ef0643b86`. A durable gitignored 33 MiB
  artifact and sidecars now exist locally. Nothing was copied to or rebuilt in
  the active 2070 checkout.
- A clean post-merge worktree is now recovering the audit's S1–S6 scenario
  taxonomy. The dump path proves each BBS record is the first resumable
  decision of a fresh team turn and is committed only after the next replay op
  succeeds. Fable's read-only plan review recommends a deterministic C fact
  scanner plus a Python provenance/report layer. The report must classify
  opportunity structure only, publish record/replay/per-replay-capped
  denominators and overlaps, and label static opponent reach, geometric score
  horizons, S3 ordering pressure, and S6 one-move assist counterfactuals as the
  approximations they are. No replay outcome may become an action-quality
  label.

Next steps and safety boundary:

1. Write fixtures and contract tests before the S1–S6 scanner. Keep bucket
   flags non-exclusive, prove `S2` is contained in `S1`, and publish thin
   turn-band counts rather than smoothing away the opening bias.
2. Do not wire the strict bank or classifier into training. Use its measured
   empty/thin buckets only to size a separately reviewed authored-fixture
   tranche for passing, handoffs, second half, score/clock, Stalling, and
   contextual rerolls.
3. Continue hourly live/BBTV checks. The milestone evaluator still waits for
   both queues terminal, an idle GPU, an inert overflow timer, and explicit
   BBTV quiescence.

## 2026-07-15 04:28 PDT — hourly health check and strict-bank coverage result

Live experiment and autonomy state:

- At 04:24 PDT `final-main-control` remained healthy at exact learner step
  10,479,992,832 (epoch 79,955), approximately 87.3% of its 12B seed-42 run.
  The latest complete 119-game native panel reported performance 0.6303,
  1.5630 touchdowns/game, draw rate 0.3361, possession 0.3851, historical
  in-pool win rate 0.6047, illegal/sampled-repair fraction 0.1700, forward ball
  progress 8.335 squares, 17.958 Rush intentions, 11.748 blocks thrown, 2.143
  blocks against the carrier, carrier-target fraction 0.2031, 1D fraction
  0.2000, 2D-red fraction 0.0367, 0.0168 pass intentions, and zero handoffs.
  Reward clipping, non-finite reward, engine-error, demonstration, and fallback
  counters were all zero.
- The exact primary service is active/running with zero restarts. Queue PID
  `431309`, screen wrapper `431313`, trainer wrapper `431592`, and trainer
  `431596` are unchanged; `final-main-control` is running and
  `final-second-control` remains pending. Run `1784058310965` has 210 complete
  16,066,560-byte checkpoints; the latest observed interval checkpoint is
  exact step 10,437,263,360.
- All 65 primary and 74 overflow pins revalidated with no error at unchanged
  plan SHA-256 values
  `4ee72e3c58f09786cdd3bbf78a772e8de2d9a93e21a8b065cf0c5976ecced270`
  and
  `d90ee01c8c459f599c8601934f545ccb7783261edae3bcb6e9e3878036d37d3e`.
  Overflow state remains absent. Its latest watcher invocation returned success
  without starting work; the watcher service is inactive/dead with zero
  restarts and its enabled timer is active/waiting.
- The exact GPU compute query returned only trainer PID `431596`. Seven samples
  over 30 seconds held at 80–82 C, 88–89% fan, 76–81% utilization, 5,554 MiB
  VRAM, and 110.61–154.09 W. Software thermal limiting was active in five
  samples and inactive in two; hardware thermal slowdown was absent throughout.
  No sample approached the 88 C three-poll guard. Disk remains 7% used with
  896 GiB free, inodes 1% used, memory 8.6 GiB available, and swap use 27 MiB.
- `bbstream`, `bbweb`, and `bbtv-tunnel` remain active with zero restarts. The
  CPU viewer selected exact checkpoint 10,337,386,496 at 04:14 PDT, source
  SHA-256
  `c2ea24869b2794605b45013d2acb94130aa1e216e3218e530e1d59585a191511`,
  against the frozen turnover3 baseline. Public HTTP returned 200 in 0.299
  seconds. The only GPU compute PID remains the trainer; BBTV remains
  observational.

Strict-bank S1–S6 coverage tranche:

- A pure C classifier and fail-closed scanner now measure overlapping tactical
  opportunity structures at the bank's validated fresh-team-turn boundaries.
  A deterministic Python layer binds the D191 bank/manifest, scanner binary and
  sources, engine Git tree, command, thresholds, and outputs; it publishes the
  JSONL records and aggregate report before a manifest commit marker without
  overwriting racing writers. It does not select actions, consume outcomes,
  set sampling weights, or wire the bank into training.
- Canonical raw/capped/distinct-replay counts are S1
  `5,023/4,935/4,153`, S2 `3,047/2,973/2,403`, S3
  `12,661/9,961/5,322`, S4 `2,883/2,703/1,745`, S5
  `3,605/3,280/1,983`, and S6 `11,763/8,993/4,950`; 840 records from 672
  replays satisfy none of the six. The scanner exactly reconciles the
  independent pickup probe's 5,312 loose and 10,036 held states. All structural
  anomaly counters are zero: S2 is contained in S1, S4/S5 are disjoint, and S6
  is the S6A/S6B union.
- Fable's independent C review found one genuine raw-record bounds-validation
  blocker. The scanner now validates stack depth, enum/index ranges,
  bidirectional grid/player consistency, coordinates, and ball carrier state
  before any engine query; focused corrupt-record fixtures cover the fix.
  Fable separately approved the aggregation, pinning, mutation detection,
  deterministic bytes, and exclusive publication layer. A final C re-review
  could not start after Claude Code's OAuth session expired, so it is not being
  represented as an approval.
- Nine focused C tests pass normally and under ASan/UBSan; six report-layer
  tests cover deterministic splits/caps/overlaps, hash drift, input mutation,
  existing outputs, and injected publication failure. Optimized and sanitized
  full-bank scans emitted the identical 15,348-line record SHA-256
  `6c4c4ef221a9d8667cf098c6fe91aa72a2d34b228e0b985201fc46bb87058daa`.
  The current canonical aggregate-report SHA-256 is
  `2983f2e0c1f01902a56c7ff079df2d0b59ab00e7314cc3e5bd2ec1988f5eae88`.

Next steps and safety boundary:

1. Finish CI/guide/decision integration, rerun the full normal and sanitizer
   suites, and obtain a final exact-tree review if Claude Code authentication
   becomes available. Otherwise preserve the successful review plus explicit
   local proof without inventing a verdict.
2. Commit, open a PR, require exact-head CI, merge, rebuild the scanner from
   merged `main`, and publish the durable gitignored report transaction with
   post-merge source/binary/Git pins.
3. Use the measured thin/empty regions only to size a separately reviewed
   authored-fixture tranche. Do not stage the strict bank in the occupied 2070
   checkout or start the milestone evaluator before both queues are terminal,
   the GPU is idle, the overflow timer is inert, and BBTV is quiesced.

04:41 PDT addendum:

- PR #25 passed exact-head GitHub CI run `29412069280` on
  `dd817eff6d59432a9144f4d01d1078202ae224f4` and merged to `main` as
  `9a4112ef3ef07740f5c485caaf362e1891fe6c55`. The remote feature branch was
  deleted manually after GitHub's automatic cleanup could not switch a local
  worktree whose `main` branch is in use elsewhere.
- A force rebuild from the merged tree produced scanner binary SHA-256
  `fa4572123be07ddff77ad2edd3c8bc02e50459eb76378175749447ee5ec2d2d4`.
  The durable gitignored post-merge transaction now exists at
  `validation/states/bb2025-strict/scenarios/`: records SHA-256
  `6c4c4ef221a9d8667cf098c6fe91aa72a2d34b228e0b985201fc46bb87058daa`,
  report SHA-256
  `2983f2e0c1f01902a56c7ff079df2d0b59ab00e7314cc3e5bd2ec1988f5eae88`,
  and manifest SHA-256
  `9842b1e6b0c05acb576db562d96579da61a63187e7e33da162ddbb810646c911`.
  The manifest binds merged Git/tree identity, the clean tracked engine,
  D191 inputs, four source hashes, the exact binary, command, thresholds, and
  both output hashes.
- The optional Codex review CLI was broken locally and Gemini required
  interactive authentication, so neither produced review evidence. The merged
  review set is the actionable Fable C review, Fable's explicit provenance
  approval, the exact committed-diff inline review, local normal/sanitizer
  evidence, and exact-head CI. No code or artifact from this tranche was
  installed in the occupied 2070 checkout.

04:55 PDT addendum:

- A read-only 04:51 host check found the primary queue still healthy on
  `final-main-control` at exact learner step 10,790,502,400 (epoch 82,324),
  approximately 89.9% of 12B. The primary, `bbstream`, `bbweb`, and
  `bbtv-tunnel` services remain active/running with zero restarts; the overflow
  service remains inactive/dead with no state, and its 04:41 watcher invocation
  correctly returned success after reporting that the primary was still
  active. The only GPU compute PID remains trainer `431596`; the sampled GPU
  state was 81 C, 89% fan, 80% utilization, 5,554/8,192 MiB, and 149.28 W,
  with software thermal limiting active, hardware slowdown inactive, and no
  approach to the 88 C three-poll guard. Disk remains 7% used with 896 GiB
  free, memory 8.6 GiB available, and swap use 27 MiB.
- The latest complete native panel (`n=113`) reported performance 0.6018,
  1.5310 touchdowns/game, draw rate 0.3540, possession 0.3717, historical
  in-pool win rate 0.6062, illegal/sampled-repair fraction 0.1655, forward ball
  progress 8.377 squares, 19.425 Rush intentions, 12.796 blocks thrown, 2.062
  blocks against the carrier, carrier-target fraction 0.1658, 1D fraction
  0.1780, 2D-red fraction 0.0279, and zero pass/handoff intentions. All reward
  clipping, non-finite reward, engine-error, demonstration, and fallback
  counters remain zero.
- BBTV advanced observationally to exact checkpoint 10,686,955,520 at 04:43,
  source SHA-256
  `3c21dbb75ab6ce7295b0f60137b34c78bdf74c42a0fd756df299a4665bf86ec6`,
  against the frozen turnover3 baseline. Its server remains CPU-only and the
  public page returned HTTP 200 in 0.378 seconds.
- While beginning authored-fixture planning, a focused bug hunt confirmed that
  the demo-state loader accepted unsafe raw record content even when the BBS1
  build fingerprint matched. The pre-fix regression proved acceptance of an
  oversized stack, impossible player coordinate, corrupt grid slot, invalid
  ball carrier, and invalid procedure ID. PR #26 added bounds/enum,
  bidirectional grid/player, ball, and procedure validation plus a dedicated
  ingestion test; all 15,471 historical records remained accepted and two
  forced demo-reset episodes completed with zero fallback. The exact commit
  passed 401 engine, 37 reward, 2 contact-bot, and 1 loader tests normally and
  under ASan/UBSan; exact-head CI run `29413024709` passed in 4m05s. PR #26
  merged to `main` as `fb5f9271d1abdc59ccf5b536c7e933d0e3aeed10`.
  Claude/Fable remained unavailable because `claude auth status` reported no
  active login, so that auth failure was not counted as a review verdict. The
  fix was not installed in the occupied 2070 checkout.

## 2026-07-15 05:14 PDT — hourly health check and BB2025 Stalling implementation proof

Live experiment and autonomy state:

- At 05:13 PDT `final-main-control` remained healthy at exact learner step
  11,028,660,224 (epoch 84,141), approximately 91.9% of its 12B seed-42 run.
  The latest complete 116-game native panel reported performance 0.5862,
  1.3621 touchdowns/game, draw rate 0.4310, possession 0.3687, historical
  in-pool win rate 0.6072, illegal/sampled-repair fraction 0.1733, forward ball
  progress 8.219 squares, 18.181 Rush intentions, 12.276 blocks thrown, 2.086
  blocks against the carrier, carrier-target fraction 0.1787, 1D fraction
  0.2015, 2D-red fraction 0.0444, 0.0259 pass intentions, and zero handoffs.
  Reward clipping, non-finite reward, engine-error, demonstration, and fallback
  counters were all zero.
- The exact primary service is active/running with zero restarts and queue PID
  431309; `final-main-control` is running and `final-second-control` remains
  pending. The exact compute-PID gate still returns only trainer PID 431596.
  Run `1784058310965` has 221 complete 16,066,560-byte checkpoints; the latest
  observed complete checkpoint is exact step 10,986,586,112.
- All 65 primary and 74 overflow pins revalidated with no error at unchanged
  plan SHA-256 values
  `4ee72e3c58f09786cdd3bbf78a772e8de2d9a93e21a8b065cf0c5976ecced270`
  and
  `d90ee01c8c459f599c8601934f545ccb7783261edae3bcb6e9e3878036d37d3e`.
  Overflow state remains absent. Its service is inactive/dead with zero
  restarts; the enabled timer remains active/waiting, and the 05:03 watcher
  invocation returned success after correctly reporting that the primary was
  still active.
- The sampled GPU state was 80 C, 88% fan, 83% utilization, 5,554/8,192 MiB,
  and 109.92 W. Software thermal limiting was active, hardware slowdown was
  inactive, and the sample remained below the frozen 88 C three-poll guard.
  Disk remains 7% used with 895 GiB free, inodes 1% used, memory 8.5 GiB
  available, and swap use 27 MiB.
- `bbstream`, `bbweb`, and `bbtv-tunnel` remain active with zero restarts. The
  CPU viewer selected exact checkpoint 10,886,709,248 at 05:04 PDT, source
  SHA-256
  `3ae7c120f3dcb5081ef32a4fb78b3cd26c47a44686f66f57665d8f14977f59cb`,
  against the frozen turnover3 baseline. The public page returned HTTP 200 in
  0.266 seconds. BBTV remains observational and owns no GPU compute process.

BB2025 Stalling rules audit:

- The current rulebook mirror defines Stalling as ending an activation still
  holding the ball after having been able to score without a Dodge, Rush,
  Block, activation Trait, or any other dice. It requires an end-of-activation
  D6; a result at least equal to the current team turn Knocks the carrier Down
  and causes a Turnover. Forgoing the carrier's activation still requires the
  roll, while a prior Turnover that denies the carrier an activation does not.
  A successful Pass/Hand-off that transfers possession is exempt. The May 2026
  FAQ interaction allows Steady Footing to prevent both the crowd knockdown and
  its Turnover, although the crowd-action roll itself cannot be rerolled.
- A focused bug hunt proved the executable engine contained no Stalling logic:
  the pre-fix regression left an eligible turn-1 carrier standing with the ball
  and consumed zero of four scripted crowd/armour/bounce dice. A local fix now
  computes whether any scoring path is free of Dodge/Rush and compulsory
  activation dice, snapshots eligibility at activation start, and resolves the
  non-rerollable crowd roll after activation or explicit forgoing. It uses the
  existing knockdown procedure so Steady Footing, ball release, armour/injury,
  Turnover, and procedure unwinding keep one owner.
- Nine focused Stalling tests now cover the crowd knockdown, turn-number
  threshold, Rush/Dodge/activation-gate exemptions, successful Hand-off,
  forgoing, prior-Turnover exemption, and Steady Footing. The existing
  touchdown test now also proves a real score never falls through into a crowd
  roll. The full optimized and ASan/UBSan suites both pass: 410 engine, 37
  reward, 2 contact-bot, and 1 state-bank-loader test. Golden replay
  resimulation remains exact. The change adds no match fields or procedure
  identifiers and therefore does not change the serialized match ABI.
- This rule fix remains local and uncommitted pending a final diff review,
  guide/decision integration, and exact-head PR/CI. It was not copied to,
  rebuilt in, or deployed over the source-pinned 2070 experiment. Claude/Fable
  is recorded as the preferred independent plan/debug reviewer, but its local
  OAuth session remains expired; that availability failure is not a review
  verdict.

Next steps and safety boundary:

1. Review the Stalling diff for omitted compulsory-roll interactions and query
   side effects, update the durable rules/decision guidance, then commit and
   take it through independent diff review, exact-head CI, and merge.
2. Resume the deterministic authored-fixture plan for Pass, Hand-off, second
   half, contextual reroll, and score/clock/Stalling decisions. Keep recipe
   construction engine-driven with scripted RNG and keep the authored bank out
   of the occupied checkout until separately reviewed.
3. Continue hourly read-only live/BBTV monitoring. Do not deploy this rule fix,
   start overflow manually, or start milestone evaluation while either queue
   remains pending/running.

05:25 PDT addendum:

- The final Stalling tree added a read-only query-purity canary, making the
  verified totals 411 engine, 37 reward, 2 contact-bot, and 1 loader test in
  both optimized and ASan/UBSan builds. Rules and operator guidance now state
  three residuals explicitly: Fumblerooski is not implemented; Steady Footing
  still lacks its FAQ-permitted team-reroll choice; and the 454-way policy
  interface can end the whole team turn but cannot yet forego only one player
  and continue activating others.
- PR #27 passed exact-head CI run `29414745156` in 4m08s on commit
  `3f4a81cbb8fc16f8cf4d9ee056413e3d67b64002` and merged to `main` as
  `0844ec6f444a434da161aeaff25df920b68bf7c9`. The remote feature branch was
  deleted manually because another local worktree owns `main` and prevented
  `gh` from performing local cleanup after the authoritative GitHub merge.
- No external-model verdict was available: Claude/Fable remained logged out,
  the required Codex CLI wrapper pointed to a missing vendor binary, and
  Gemini stopped at interactive authentication. Those availability failures
  were not counted as reviews. The inline rules/procedure/RNG/ABI review found
  no actionable P0-P3 issue; dual-mode local tests and exact-head hosted CI are
  the positive evidence. The merged source remains undeployed and the occupied
  2070 checkout, queue inputs, services, and BBTV processes were not changed.

## 2026-07-15 06:06 PDT — hourly health check and authored-state safety review

Live experiment and autonomy state:

- At 06:04 PDT `final-main-control` remained healthy on seed 42 at exact
  learner step 11,598,430,208 (epoch 88,488), 96.65% of its nominal 12B cap.
  The advance since the 05:13 observation was approximately 186K steps/s,
  implying roughly 36 minutes to the nominal cap if that short-window rate
  holds; this is an observation, not a completion claim. The next queue job,
  `final-second-control`, remains pending.
- The latest complete 109-game native panel reported performance 0.6101,
  1.6514 touchdowns/game, draw rate 0.3578, possession 0.3721, historical
  in-pool win rate 0.6094, illegal/sampled-repair fraction 0.1684, forward ball
  progress 8.891 squares, 20.275 Rush intentions, 11.844 blocks thrown, 1.954
  blocks against the carrier, carrier-target fraction 0.1759, 1D fraction
  0.2024, 2D-red fraction 0.0421, and zero pass and handoff intentions. Reward
  clipping, non-finite reward, engine-error, demonstration, and fallback
  counters all remained zero.
- The primary service is active/running with queue PID 431309 and zero
  restarts. The exact compute-PID gate still reports only trainer PID 431596.
  Run `1784058310965` has 233 complete 16,066,560-byte checkpoints; the latest
  complete checkpoint observed was exact step 11,585,847,296.
- All 65 primary and 74 overflow pinned inputs revalidated without error at
  unchanged plan SHA-256 values
  `4ee72e3c58f09786cdd3bbf78a772e8de2d9a93e21a8b065cf0c5976ecced270`
  and
  `d90ee01c8c459f599c8601934f545ccb7783261edae3bcb6e9e3878036d37d3e`.
  Overflow state remains absent, its service inactive/dead with zero restarts,
  and its enabled timer active/waiting. The 05:58 watcher invocation returned
  success after correctly reporting that the primary was still active.
- The sampled GPU state was 81 C, 89% fan, 81% utilization, 5,554/8,192 MiB,
  and 142.95 W. Software thermal limiting was active, hardware slowdown was
  inactive, and the sample remained below the frozen 88 C three-poll guard.
  Disk remained 7% used with 895 GiB free, inodes 1% used, memory 8.5 GiB
  available, and swap use 27 MiB.
- `bbstream`, `bbweb`, and `bbtv-tunnel` remained active with zero restarts.
  The CPU viewer selected exact checkpoint 11,485,970,432 at 05:56 PDT, source
  SHA-256
  `7ff2b60156903178522fb72d6f5c9b362c005f646c401e04c04557997bbfdb0f`,
  against the frozen turnover3 baseline. The public page returned HTTP 200 in
  0.242 seconds. BBTV remains observational and owns no GPU compute process.

Authored deterministic state-bank work:

- PR #28 initially established separate procgen/game RNG streams, action and
  dice transcripts, exact reinitialization/replay, full raw-state drift checks,
  and a proof BBS1 writer. Independent review correctly blocked merge on two
  paths: corrupt `TEAM_TURN.a` could reach out-of-bounds legal-action logic,
  and a caller could mutate a replayed raw `bb_match` before asking the public
  writer to serialize it.
- Exact head `8e5dbac95baf93d4d22bdfaa96f53057035fe2d3` now makes the writer consume a
  recipe and serialize only its own private exact-replay output. A single
  engine-owned `bb_state_bank_boundary_valid` function is shared by the writer,
  Puffer loader, and scenario scanner. BBS1 remains intentionally narrow: it
  accepts only the supported `MATCH phase 3 -> TEAM_TURN phase 1` boundary with
  canonical frames, valid clock/team metadata, player/grid bijection, and
  consistent ball state; future nested decision windows require explicit
  procedure-specific validation rather than widening this predicate.
- Regression coverage now rejects caller mutation, corrupt turn-team indices,
  invalid or mismatched clock metadata, zero source IDs, and nonzero metadata
  padding, then proves a positively loaded record can safely enumerate legal
  actions. A clean optimized run and ASan/UBSan run each passed 414 engine, 37
  reward, 2 contact-bot, and 2 loader tests. Clang static analysis and
  `git diff --check` passed. The shared validator accepted all 16,528 nonempty
  historical BBS records available locally. The 25 empty/header-only shard
  files were excluded explicitly because they contain no whole record.
- The fixes are pushed and exact-head hosted CI plus three independent
  re-reviews are in progress. Prior-head approvals are not being reused.
  Nothing from this PR or the earlier merged source work has been installed in
  the occupied 2070 checkout.

Next steps and safety boundary:

1. Require exact-head CI success and fresh approval from all three reviewers;
   fix any actionable P0-P3 finding before merging PR #28.
2. After merge, implement the separately reviewed F1-F5 authored recipe
   families, quotas, sidecars/transactional manifest, and one-action
   continuation checks. The current proof foundation alone is not a training
   bank and authorizes no deployment.
3. Continue read-only monitoring through the seed-42 cap and the queue-owned
   transition into seed 43. Do not manually start overflow, interrupt a queue,
   or start milestone evaluation while any primary/overflow job is pending or
   running.

06:27 PDT addendum:

- A third independent review found that the authored writer still trusted a
  caller-provided capture decision index even though it privately replayed the
  state. The writer now requires that index to equal the exact-replayed
  recipe's bounded action count before boundary validation or any output. A
  regression supplies an off-by-one index and proves both rejection and an
  empty stream. Optimized and ASan/UBSan suites each remained green at 414
  engine, 37 reward, 2 contact-bot, and 2 loader tests.
- A final documentation review found and removed the obsolete loader-local
  validator name from `AGENTS.md`; guidance now names the engine-owned
  `bb_state_bank_boundary_valid` shared by writers, readers, and scanners.
  Three independent reviewers approved final exact head
  `51a9b94dc4f26fb70a20d2ab6e641af6144f801f` with no P0-P3 findings, and
  exact-head CI run `29418716064` passed in 4m11s including ASan/UBSan. PR #28
  merged to `main` as `29fc531b15495d660290a1d4cf128e565a9fb6b7`.
  GitHub merged authoritatively; its local branch-cleanup step alone failed
  because a separate worktree owns `main`, so the remote feature branch was
  deleted manually. Nothing was deployed to the occupied 2070 checkout.
- A 06:26 read-only live check found seed 42 at exact step 11,841,568,768
  (98.68% of 12B), epoch 90,343. The primary and BBTV services still had zero
  restarts, overflow remained absent and gated, the only compute PID remained
  trainer 431596, and the GPU sample was 81 C with hardware slowdown inactive.
  The queue-owned cap/evaluation/seed transition is being observed without
  intervention.

06:49 PDT addendum:

- Seed 42 reached its queue-owned terminal checkpoint and exited zero at
  06:41:18 PDT. The accepted result has no acceptance failures, records exact
  step 11,999,903,744, 10,057 final-evaluation episodes, and binds checkpoint
  SHA-256
  `cc9ecd5f29f700e83a0852af7f85b3652a6d6bfe1d2de1038458a332263950f9`
  plus log SHA-256
  `e201c5606a2c75b9f93bc1cc9c1fee2997c11a0a8857f3fc5c246bca41531368`.
  Final evaluation reported performance 0.5721, 1.5165 touchdowns/game, draw
  rate 0.3846, possession 0.3818, illegal/sampled-repair fraction 0.1720,
  forward ball progress 8.378, 18.851 Rush intentions, 11.759 blocks thrown,
  2.129 blocks against the carrier, carrier-target fraction 0.1943, pass
  intentions 0.0161, and handoffs 0.00010. All reward clipping, non-finite,
  error, demonstration, and fallback counters were zero.
- The expected GPU-idle interval from 06:41 to 06:43 was the screen's CPU-only
  parse of the 863 MB append-only log, not a queue failure. The parser used one
  CPU core, wrote the accepted result at 06:43:33, and the screen automatically
  launched seed 43 at 06:43:35 without intervention. By 06:46 seed 43 had
  reached exact step 27,000,832 with zero integrity counters. Its sole GPU
  compute PID was 473422; the sample was 81 C, 85% fan, 78% utilization,
  5,554/8,192 MiB, 121.85 W, software thermal limiting active, and hardware
  slowdown inactive. `final-main-control` remains the running queue job with
  one of three arms complete; `final-second-control` remains pending.
- The separately CPU-only one-action continuation tranche added a writer
  pre-emission canary and repeats it after real BBS close/load/byte verification.
  It validates before legal enumeration, applies the lowest packed legal action
  only to a private copy with a bounded 256-face scripted suffix, and rejects
  RNG or engine error. Full historical diagnostics continued all 15,471 mixed
  and 15,348 strict-bank records without mutation or sanitizer findings. D195
  records that this proves resumability, never action quality, and leaves all
  F1-F5/report/manifest/training work pending. Three independent reviewers
  approved exact head `217ae6703ec45f47226da66da830690ab8ba869f` with no
  P0-P3 findings; exact-head CI run `29420244059` passed in 4m09s. PR #29
  merged to `main` as `1a031b748fe763fd34b6238ef1899c0dcd3d3780`.
  As with PR #28, only local branch cleanup failed because another worktree
  owns `main`; the authoritative merge was verified and the remote branch was
  deleted manually. No merged source was deployed to the live checkout.

## 2026-07-15 07:03 PDT — hourly health check and F3 authored-proof validation

Live experiment and autonomy state:

- Seed 43 is running normally in `final-main-control` after seed 42's accepted
  completion. At 07:02 PDT it had reached exact learner step 212,467,712 at
  epoch 1,620. The latest complete 90-game native panel reported performance
  0.4611, 1.3111 touchdowns/game, draw rate 0.4778, possession 0.3165,
  illegal/sampled-repair fraction 0.2149, forward ball progress 8.518, 18.822
  Rush intentions, 15.144 blocks thrown, 1.300 blocks against the carrier,
  carrier-target fraction 0.0929, 0.0444 Pass intentions, and zero Hand-off
  intentions. Reward clipping, non-finite reward, engine-error, demonstration,
  and fallback counters all remained zero. This is an early 90-game training
  panel, not checkpoint-selection or promotion evidence.
- The primary queue remains active/running with queue PID 431309, one of three
  main-lineage arms complete, seed 43 current, and zero service restarts. The
  exact completion-gate parser reports only trainer PID 473422. The current run
  directory `1784123019013` had five complete checkpoints; the newest observed
  was exact step 199,884,800.
- All 65 primary and 74 overflow pinned inputs revalidated with no error at the
  unchanged plan SHA-256 values
  `4ee72e3c58f09786cdd3bbf78a772e8de2d9a93e21a8b065cf0c5976ecced270`
  and
  `d90ee01c8c459f599c8601934f545ccb7783261edae3bcb6e9e3878036d37d3e`.
  Overflow state remains absent, its service inactive/dead with zero restarts,
  and its timer active. The 06:53 watcher invocation exited successfully after
  correctly reporting that the primary was still active.
- The sampled GPU state was 81 C, 89% fan, 77% utilization, 5,554/8,192 MiB,
  and 109.56 W; both software and hardware slowdown flags were inactive in
  that sample. Disk remained 7% used with 895 GiB free, inodes 1% used, memory
  9.9 GiB available, and swap use 27 MiB.
- `bbstream`, `bbweb`, and `bbtv-tunnel` remain active with zero restarts. BBTV
  has rolled to seed 43 and selected exact checkpoint 50,069,504 at 06:51 PDT,
  source SHA-256
  `c908a38352ca45c89f9a0834300b7894d2fd357ee1bc14ab61ae7d7f6e715021`,
  against the frozen turnover3 baseline. The public page returned HTTP 200 in
  0.291 seconds. The CPU viewer remains observational and owns no GPU compute
  process.

Authored deterministic state-bank work:

- The first F3 proof recipe now reaches a fresh supported team-turn boundary
  in half two, active-team turn 5, tied 0–0, through 660 enumerated legal engine
  decisions and 175 recorded game dice. Setup remains deterministic and all
  later choices use a third RNG stream independent of procgen and game dice.
  No match, clock, score, grid, player, ball, resource, status, or procedure
  field is synthesized.
- Exact replay alone did not prove that caller-declared seeds generated an
  otherwise valid transcript. The writer now independently rediscovers each
  complete recipe from its configuration fields and requires full recipe byte
  identity before replay or serialization, binding procgen, game, and
  controller seeds to initialized/captured bytes and all transcripts. A mixed
  first-turn/F3 regression proves that provenance failure in the later record
  leaves the output at byte zero.
- Focused checks, the complete optimized suite, and the complete ASan/UBSan
  suite pass at 417 engine, 37 reward, 2 contact-bot, and 3 production-loader
  tests. Clang static analysis and `git diff --check` pass. Guidance and D196
  record the narrow claim: one tied late-second-half F3 template only, with no
  quota, bank-publication, training, or deployment authorization. The live
  checkout and both queues remain untouched.

Next steps and safety boundary:

1. Commit and push the F3 branch, require exact-head hosted CI and independent
   review of long-horizon RNG/provenance, memory bounds, semantic scope, loader
   behavior, and the no-surgery boundary; fix every actionable P0-P3 finding
   before merge.
2. Continue one reviewed proof recipe per remaining family. Keep F1/F2/F5 on
   the already validated fresh-team-turn boundary; do not admit F4's nested
   reroll frame until its complete resumable stack has an explicit shared
   validator.
3. Continue hourly read-only live/BBTV monitoring. Do not alter the occupied
   source checkout, manually start overflow, or start milestone evaluation
   while either frozen queue remains pending or running.

07:16 PDT addendum:

- Independent review found one P2 in the first PR head: the deterministic
  first-team-turn recipe did not consume its controller RNG, so copying a
  changed controller seed/stream through rediscovery let inert values appear
  provenance-bound. The writer never emitted an unsafe match, but its declared
  provenance contract was too broad. The fix canonicalizes both unused fields
  to zero for that recipe kind; post-discovery mutation of either field now
  fails provenance before byte zero. F3 retains and binds its actually used
  nonzero controller stream. AGENTS, CLAUDE, the authored-bank plan, and D196
  now distinguish used controller streams from canonical-zero unused fields.
- All three independent re-reviews approved exact head
  `dfda8cc70e08de832ab7eeaa28b66e0cf57c117c` with no P0-P3 findings. Reviewer
  probes covered 256 F3 controller seeds, all of which reached a valid half-two
  late-turn boundary, independently rediscovered/replayed exactly, and stayed
  within 304-748 actions and 105-214 dice. The fixed optimized and sanitized
  F3 recipe bytes matched at SHA-256
  `0c5f0c871dc2551f032a65fac9024291d1afd6a00e5dcba3bf98086b4893f833`.
  Exact-head CI run `29422332626` passed in 4m40s, including ASan/UBSan.
- PR #30 merged authoritatively to `main` as
  `02f0f15a86ad209609402e8de6df27f6538e43b6`; the remote feature branch was
  deleted. No source or authored artifact was deployed to the occupied 2070
  checkout, and neither frozen queue or viewer service was changed.

07:42 PDT addendum:

- The first F1 proof reaches a fresh half-two, away-turn-1, tied 0-0 boundary
  after 414 legal decisions and 108 recorded game dice. On a discarded private
  copy, it requires a zero-die legal carrier activation and Pass declaration
  plus a distinct standing, tackle-zone-capable teammate target. The ordinary
  raw match necessarily retains and observes its ball carrier, but no separate
  probe metadata, chosen action, target, nested frame, outcome, reward, BC
  target, or policy-quality label is added. The loader-compatible proof remains
  unpublished, unstaged, and unauthorized for training.
- Review exposed three rules-semantic false positives and one documentation
  overclaim before merge. The final predicate now rejects PA-dash carriers, No
  Ball carriers, and No Ball receivers even when a forged raw state remains
  structurally BBS-valid. Documentation now distinguishes the ordinary carrier
  field from absent probe metadata. The audit also found a separately pending
  engine-mask defect: activation currently exposes Pass declaration to PA-dash
  players before `proc_ball` rejects them. That engine rule fix is not hidden in
  the authored-data tranche.
- Three final independent reviews approved exact head
  `0896116370bd870808ece524ec0ca59656a736eb` with no P0-P3 findings. Adversarial
  evidence included 11,200 systematic single-byte mutations, 100,000 randomized
  1-8-byte mutations, structured procedure/grid/carrier/Pass-used/gate/trait
  cases, provenance mutations, and mixed later-record failure; inputs remained
  unchanged and no sanitizer finding occurred. Optimized and ASan/UBSan suites
  each passed 418 engine, 37 reward, 2 contact-bot, and 4 loader tests. Exact-
  head CI run `29424320219` passed in 4m08s.
- PR #31 merged authoritatively to `main` as
  `85f239cf196b8958282981b46e6a2d77f9bd03a5`; the remote branch was deleted.
  The fixed optimized/sanitized 61,912-byte recipe SHA-256 remained
  `5908432e21034920e6aa80ed702145952dc5eda4b3f3d9a2199da0225d91d6e1`.
  No source or artifact was deployed to the occupied 2070 checkout.

## 2026-07-15 07:54 PDT — hourly health check and rules-layer follow-up

Live experiment and autonomy state:

- Seed 43 remains healthy in `final-main-control`. At 07:52 PDT its last
  complete native panel was exact learner step 772,669,440 at epoch 5,894 over
  85 games: performance 0.5353, 1.1294 touchdowns/game, draw rate 0.3647,
  possession 0.3037, illegal/sampled-repair fraction 0.2169, forward ball
  progress 9.615, 19.176 Rush intentions, 13.247 blocks thrown, 1.165 blocks
  against the carrier, carrier-target fraction 0.1025, and zero Pass or
  Hand-off intentions. Reward clipping, non-finite reward, engine-error,
  demonstration, and fallback counters all remain zero. This small live panel
  is observational training telemetry, not checkpoint-selection or promotion
  evidence.
- The primary queue is active/running with service PID 431309, screen state
  `running`, one of three arms complete, seed 43 current, and zero restarts.
  Trainer PID 473422 is the only GPU compute process. The newest complete
  checkpoint observed was exact step 749,207,552 in run directory
  `1784123019013`. Recent progress implies roughly 185-190K agent steps/second,
  so any completion estimate remains approximate and excludes queue-owned
  final evaluation.
- All 65 primary and 74 overflow pinned inputs revalidated with no error at the
  unchanged plan SHA-256 values
  `4ee72e3c58f09786cdd3bbf78a772e8de2d9a93e21a8b065cf0c5976ecced270`
  and
  `d90ee01c8c459f599c8601934f545ccb7783261edae3bcb6e9e3878036d37d3e`.
  Overflow state remains absent, its service inactive/dead with zero restarts,
  and its timer active. The 07:48 watcher invocation exited successfully after
  correctly reporting that the primary service was still active.
- The sampled GPU state was 81 C, 89% fan, 76% utilization, 5,554/8,192 MiB,
  and 112.50 W, with software thermal limiting and hardware slowdown both
  inactive. Disk remains 7% used with 895 GiB free, inodes 1% used, memory
  9.8 GiB available, and swap use 27 MiB.
- `bbstream`, `bbweb`, and `bbtv-tunnel` are active with zero restarts. BBTV
  selected seed 43 checkpoint 699,269,120 at 07:48 PDT, source SHA-256
  `dbda2a9ec9adac1ba78ea9a0df7fced24d57184dd75634dfc2c9b4ddfcf77047`,
  against the frozen turnover3 baseline. The public page returned HTTP 200 in
  0.290 seconds and `/ws` returned the expected HTTP 101 WebSocket upgrade.
  The CPU viewer remains observational and owns no GPU compute process.

Rules-layer follow-up and next steps:

- The F1 audit's PA-dash and No Ball false positives were traced to engine
  legality, not reward shaping. A separate local branch now makes the shared
  catch predicate reject No Ball players, with the intended consequences for
  Hand-off, pass landing, scatter/throw-in, and kickoff touchback; Pass
  declaration is no longer offered to PA-dash players while Hand-off remains
  available. Focused tests cover PA-dash declaration, No Ball Hand-off,
  accurate-pass bounce without a catch die, and all-No-Ball touchback fallback.
- The complete optimized and ASan/UBSan suites pass at 422 engine, 37 reward,
  2 contact-bot, and 4 production-loader tests. Three affected golden traces
  were deliberately regenerated twice and produced identical hashes; the
  other five remained byte-identical. Clang static analysis and
  `git diff --check` pass. D198 and contributor guidance keep this explicitly
  outside reward shaping, state-bank admission, training, and live deployment.
- Next, commit and publish the rules fix, require exact-head hosted CI and
  independent review of rules semantics, RNG/dice behavior, golden
  determinism, and scope, then fix every actionable P0-P3 finding before any
  merge. Continue the F2 authored proof only after that rules foundation is
  merged. The occupied 2070 checkout, frozen queues, and BBTV services remain
  untouched.

08:14 PDT addendum:

- Exact-head review materially corrected the initial No Ball implementation
  before merge. Hand-off target eligibility is Standing plus Tackle Zone, not
  successful-catch capability: a No Ball team-mate remains selectable, then
  automatically fails the required Catch without a catch die, Bounces, and
  causes the ordinary Hand-off Turnover. A second reproduced pre-existing bug
  allowed No Ball players to Intercept and gain possession; interception
  candidate construction now excludes them explicitly.
- The strengthened tests prove the No Ball Hand-off consumes exactly one D8
  Bounce die and no catch die, leaves the ball on the ground with no carrier,
  and turns over. A successful-pass regression proves a No Ball defender gets
  no interception choice or possession. The Touchback test now validates all
  194 eligible empty squares in the receiving half, excludes occupied and
  wrong-half squares, applies the selected fallback with zero extra RNG, and
  verifies exact ground-ball state and receiving-team continuation.
- Three independent reviewers approved final exact head
  `15daf22c561c3f563118d76e6d9ca77dc8209bdf` with no P0-P3 findings. Optimized
  and ASan/UBSan suites each passed 423 engine, 37 reward, 2 contact-bot, and 4
  loader tests; Clang analysis and diff checks passed. An independent fresh
  double regeneration matched all eight committed goldens byte-for-byte.
  Exact-head CI run `29426743816` passed in 4m15s.
- PR #32 merged authoritatively to `main` as
  `f1271e44369beb7b083e9875ee27087cf51a70e6`; the remote feature branch was
  deleted. No source or artifact was deployed to the occupied 2070 checkout,
  and neither frozen queue or BBTV service was changed. The next authored-bank
  step remains the narrow F2 Hand-off-opportunity proof on the corrected rules
  foundation.
