# Current handoff: paired memory-learning training is running

All integration edits are uncommitted in
`/Users/alexanderhuth/Code/bb-improvement-20260904`, branch
`codex/improvement-20260904`. Original user changes are preserved. No Vast
spend, commit, push, deployment or reward/checkpoint promotion. Read
`DECISIONS.md` through D335. The checklist is http://127.0.0.1:8768/.

## Current rig state

The user-approved managed WSL move to
`D:\WSL\Ubuntu-BloodBowl-20260904` is complete. C: recovered about277GB;
D: had1.338TB free at final canary verification. Ubuntu is online at
`rache@100.97.209.46`; Windows is accessible through `bblan`. Existing bbstream
restarted automatically under its unchanged configuration. Do not alter it.
The terminal-aware frozen-policy bridge, full-bank stress gate, clean 50M canary
and fresh checkpoint reload are complete. The next paired learning screen is now running under
`bb-memory-learning-paired-250m-v2.service` (control seed42 first;250M per arm,
four arms). The active local monitor is
`audit-artifacts/memory-learning-preflight-20260905/monitor_training.py`.
All old canary dashboard monitors have finished.
Do not run obsolete monitors or restart completed qualification runs.

Recovered canonical GPU/source/CPU/checkpoint evidence retains its original
hashes. Root filesystem read/write and fsync readback pass. No filesystem
repair was performed. The recovery evidence is under
`audit-artifacts/wsl-backing-storage-incident-20260904/`.

## Earlier accepted obs-v7 canary (D328; historical runtime)

- Runtime: `/home/rache/bloodbowl-rl-improve-20260904/integrated-runtime-obs7-reducer-v1`.
- Runtime closure: a5df1dd06820fc7440dab68cf6c043be0f82dbc69599fc4c213586b725cb8866.
- Module:553c70a9bc3ad33da20c34a52bbc7c2dd58c1f286f4e3dcff51c375ca8ba690b.
- Backend:f7eb385091f48231192c1e5483dc46433050f10dfdceb45827e6f0e4c0f2c54e.
- Actual patch bundle:cd3576ad38e3ba406b580476f40e04a35495d6f5754402406749649b2aa3f1c5.
- Reviewed package: `plans/exact-action-canary-50m-obs7-v9-r2/`.
- Plan:e4c8909f847f3877e6870af1746afc71be176e171a26adb1e5fdad602b21f1ea.
- Completed output: `experiments/integrated-v7-canary-50m-v9` (read-only).
- Local copy: `audit-artifacts/canary-recovery-plan-v9-r2-20260905/completed-run/`.
- Independent acceptance: `ROOT_COMPLETION_VERIFIED.json` beside that copy.

The native run completes381 updates/49,938,432 steps,379 episode-bearing
training windows/146,099 games, and10,194 final eval games. All16 hard fields
are zero. Checkpoint and numeric losses are finite. The checkpoint reloads and
saves byte-identically in a fresh native constructor without rollouts or
optimizer updates. Unit exit0/Result=success,6min21.488s wall time. Every
physical storage sample passes. The checkpoint is qualification-only and
ineligible; final eval is all draws and zero TDs, so no strength claim follows.

A redundant registry-digest field in PLAN was incorrectly copied from the
backend digest. Actual hash-pinned prelaunch and executed manifests agree
exactly, and the frozen runtime closure binds the correct registry bytes.
The explicit diagnostic amendment is in ROOT_COMPLETION_VERIFIED.json and
REVIEW_REGISTRY_METADATA.md. Never silently rewrite this frozen plan or use it
for causal reward evidence. Future plans must pass
`tools/validate_runtime_plan_identity.py`; this old plan intentionally fails
its new stricter check. Earlier old-bundle eight-bank qualification is rejected
and superseded by the corrected repeat; preserve every old artifact/amendment.

## Verified capability and audit evidence

- 49 dead worktrees removed out of77;28 valuable worktrees preserved,4.55GiB reclaimed.
- 616 native cases plus writer, normal and ASan/UBSan;15 targeted natural trajectories.
- Corrected GPU:557,056 ratios/1,072 primary rows,max9.54e-6 below2e-5,unchanged LR0 weights,zero16; generic and H512L3 gates pass.
- CPU viewer:6 full games,6,550 exact-support checks,zero11;7 actual viewer tests.
- Frozen Chain9:256 games,63W/142D/51L,52.34% utility,TD102–91; migrated weights remain qualification-only.
- Script search:1,280 games; contact+3.52pp,paired interval[+1.27,+5.66]; broader offense transfer uncertain.
- Narrow fixed-route BC/PPO capability is reproducible across3 seeds; not full-game learning.
- Latest focused Python suite:47 pass; canary supervisor19 pass on Mac and rig.

## Next work before paid scaling

Read `docs/training-and-funding-plan-2026-09-04.md` and
`docs/recurrent-memory-next-tranche-2026-09-05.md`. D329–D330 implement and qualify terminal-aware-tbptt-v1 on real Torch CPU and native CUDA. Episode boundaries clear memory; ordinary H64 boundaries preserve detached numeric state. PPO gathers exact segment initial states and observation-aligned terminal masks; tail evaluation uses copied carried state. H64 gradient detach remains. The previous zero-state tail was consistent with the old forced-window-reset regime, not an independent bug. Frozen evaluation parity passes16,913 paired decisions exactly; the clean 50M canary and fresh checkpoint reload also pass under D334. The next work is a frozen controlled learning comparison, followed by held-out match evaluation.

The broader29 mechanic gap groups/four shared tracks, replay adapter omissions,
diverse teacher curriculum, held-out learned-opponent transfer, local human
input adapter and FUMBBL integration remain explicit future work. No claim of
complete BB2025 conformance, interactive human play or championship strength.

## Current terminal-aware runtime

The isolated runtime is `integrated-runtime-terminal-aware-v2` on the local rig.
Module651ffc40e43e669912803e2f5bb3d3e641c34c0d8b431ab0f38f8393bbc700a3;
backend8f8d0563b3991b554d96c137c6928188f9c7e16d5e231d66ddbd19adca830385.
Environment and obs-v7/exact-joint-v1 are unchanged. Real CPU14/14, native
derivative checks, terminal controls, PPO gathering/ratio, graph execution and
H512/L3 throughput gates pass. Final graph and eager arrays are bit-identical;
root revalidates copied raw evidence in
`audit-artifacts/memory-integration-20260905/ROOT_NATIVE_REVALIDATION.json`.
This qualifies implementation behavior, not improved match strength.

The full eight-bank repeat checks475,136 saved ratios/all1072 primary rows,
maximum9.06e-6 below2e-5, unchanged weights and zero16. It uses the explicitly
hash-pinned external strict qualifier in
`plans/memory-canary-qualification-controllers-v4/`; the frozen runtime's older
copy intentionally remains unchanged and rejects the expanded snapshot schema.
The updated repository qualifier is the source for future installations.
Operational closure is full unfiltered4973b667… (5041 entries), distinct from
the supplementary excluded-derived closuree177dce8…. The first terminal-aware canary (PLANda8ded63…) was rejected for producer/supervisor
poll metadata mismatch. Its output is preserved read-only. The clean repeat
PLAN24a2f4a3… passes exact full-contract validation with poll 10/10/10.

## Accepted terminal-aware canary (D334)

- Remote output: `experiments/terminal-aware-memory-canary-50m-v2` (read-only).
- Launch package: `plans/terminal-aware-memory-canary-50m-v3`.
- Local evidence: `audit-artifacts/memory-canary-repeat-20260905/`.
- Root records: `ROOT_COMPLETION_VERIFIED.json` and `ROOT_RELOAD_VERIFIED.json`.
- 49,938,432 steps; 163,235 training games; 10,175 final evaluation games.
- All 16 hard fields zero; finite losses and weights; 36 physical storage samples pass.
- Fresh GPU load/save is byte-identical; checkpoint4886e464… remains ineligible.
- Zero touchdowns and all draws: integrity qualification only, no strength claim.

The current bounded memory implementation goal is complete. Next learning work
must freeze its own one-factor experiment, ancestry, source/runtime, rewards,
opponents and held-out evaluation before launching. The broader improvement
program remains open; this handoff does not claim a championship-ready bot.
