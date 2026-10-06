# b3: the no_early_end_turn arm, from its own checkout

Stage scripts for campaign `longrun-20261002` that run from `/home/rache/bloodbowl-rl-b3-20261006` and
leave the long-run checkout alone. Background, evidence and the full runbook:
`docs/no-early-end-turn-2026-10-05.md`. Nothing here has been run on the rig.

| file | what it is |
|---|---|
| `make_b3_checkout.sh` | creates the b3 checkout (clone, vendor tree, venv copy with finder AND entrypoint shebangs repointed, install with both opt-in flags, `--float` build, `--check`, import check from `/`). Run once, by hand. |
| `b3_common_env.sh` | shared environment: `C`, the recipe (equal to `../common_env.sh`), the two-pair graft declaration. Sourced by the three stages. |
| `b3_identity.sh` | non-training stage. Flag-off identity against chain 42's stored checkpoints, flag-on trace and PPO smoke, under the GPU lock. Writes `B3_IDENTITY_PASS.json` only if everything passed. |
| `b3_canary54.sh` | 50M-step canary of chain 54's launch path with the rule on. Disposable. |
| `b3_chain54.sh` | the paired rung `r0chain54-noearlyend-from41-s42-20261006`. Control: chain 42. |

## Use

1. Copy this directory to `/home/rache/longrun/b3/` (the stages source `b3_common_env.sh` from their own
   directory, so keep the files together).
2. `bash /home/rache/longrun/b3/make_b3_checkout.sh`. CPU work plus one module import; it writes only under
   the new path. Write down the source digest and module sha256 it prints. If it fails part way, remove the
   half-made `/home/rache/bloodbowl-rl-b3-20261006` before running it again (it refuses an existing
   target).
3. Add the three stages to the campaign plan, in this order, after the last stage that must run whatever
   happens to b3 (a stage that exhausts its attempts halts the whole campaign, and a halt is sticky):

   ```json
   {"name": "b3_identity", "launch": "bash /home/rache/longrun/b3/b3_identity.sh",
    "success": "/home/rache/bloodbowl-rl-b3-20261006/runs/b3-identity-20261006/B3_IDENTITY_PASS.json",
    "progress": "/home/rache/bloodbowl-rl-b3-20261006/runs/b3-identity-20261006/B3_IDENTITY_STATUS.json",
    "max_attempts": 2, "max_stale_seconds": 6000},
   {"name": "b3_canary54", "launch": "bash /home/rache/longrun/b3/b3_canary54.sh",
    "success": "/home/rache/bloodbowl-rl-b3-20261006/runs/ladder-d0-canary54-noearlyend-from41-s42-20261006/EXAM_VERDICT_PASS.json",
    "progress": "/home/rache/bloodbowl-rl-b3-20261006/runs/ladder-d0-canary54-noearlyend-from41-s42-20261006/SCREEN_STATUS.json",
    "max_attempts": 3, "max_stale_seconds": 6000},
   {"name": "b3_chain54", "launch": "bash /home/rache/longrun/b3/b3_chain54.sh",
    "success": "/home/rache/bloodbowl-rl-b3-20261006/runs/ladder-d0-r0chain54-noearlyend-from41-s42-20261006/EXAM_VERDICT_PASS.json",
    "progress": "/home/rache/bloodbowl-rl-b3-20261006/runs/ladder-d0-r0chain54-noearlyend-from41-s42-20261006/SCREEN_STATUS.json",
    "max_attempts": 3, "max_stale_seconds": 6000}
   ```

   `success` and `progress` are absolute because they live in the other checkout;
   `tools/campaign_supervisor.py` takes absolute paths for both.
4. **Add `|[b]3_identity.sh` to the plan's `trainer_pgrep`.** The supervisor decides "a stage is running"
   from that pattern alone. Without it the supervisor sees nothing alive while the identity stage waits for
   the GPU lock or runs its probes, launches it again on the next ticks (each refused by the stage's own
   lock, exit 3) and halts the campaign at the attempt cap. The other two stages run `chain_stage.sh`,
   which the pattern already names.

By hand, in the same order: `bash b3_identity.sh`, then `PLAN_ONLY=1 bash b3_canary54.sh` and
`bash b3_canary54.sh`, then `PLAN_ONLY=1 bash b3_chain54.sh` and `bash b3_chain54.sh`, with the
supervisor paused.

## What each stage refuses

- `b3_identity.sh` exits non-zero and writes no pass marker unless: the install drift check passes; the
  venv's `puffer` entrypoint runs in this checkout's venv; the warm start, chain 42's two reference
  checkpoints and the pool copy have their pinned sha256; the flag-off run reproduces both reference files
  byte for byte with `end_turn_removed` exactly 0; both flag-on runs show `end_turn_removed` above zero; the
  forward skip is routed to bank 4; hard-integrity counters are zero; no flag-on episode was cut by the
  decision cap; no out-of-support abort; and every probe imported this checkout's compiled module. With the
  flag off, cut episodes are printed and recorded, not judged (the byte-equal weights settle that run). A relaunch after a pass
  exits 0 at once. A pass marker for a different build than the installed one exits 4.
- `b3_canary54.sh` refuses to train unless the identity pass marker is a pass against the pinned digests
  for the build installed now (source digest and module sha256).
- `b3_chain54.sh` refuses to train unless that holds and the canary passed under the rule on the build
  installed now (read from the canary checkpoint's lineage sidecar).
- So after any rebuild of the b3 checkout: move `B3_IDENTITY_PASS.json` away, run `b3_identity.sh`
  again, and run the canary again under a new stamp. The supervisor only looks for the files; the wrappers
  are what notice a rebuild.
- `PLAN_ONLY=1` is allowed through both guards: it trains nothing.

## Read before launching the rung

- The canary's `LADDER_RUNG_COMPLETE.json` records `regression_gate.eval_tds`. The D244 gate refuses a
  rung whose eval touchdowns fall under half the warm rung's (chain 41: 1.738, so 0.869), and touchdowns
  under the rule are not that number. If the canary lands near it, add `export LADDER_REGRESSION_FLOOR=0`
  to `b3_chain54.sh` and declare it as a difference from chain 42.
- `EXAM_RULE=none`: a paired arm never stops itself, and chain 42's drift-guard floor was registered on
  exams without the rule.
- Never set a `B3_TEST_*` variable on the rig. They replace the pinned digests for the unit tests, and a
  result produced with one goes to `B3_IDENTITY_PASS.unpinned.json`, which no stage reads.
