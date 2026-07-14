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
