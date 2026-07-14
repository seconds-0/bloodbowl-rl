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
