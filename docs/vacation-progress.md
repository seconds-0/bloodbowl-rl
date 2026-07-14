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
