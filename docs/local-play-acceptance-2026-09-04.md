# Local Blood Bowl bot acceptance (2026-09-04)

Scope: read-only review of `/Users/alexanderhuth/Code/bb-improvement-20260904` at `141708fcb95e0296f22929a8328c46a67cb23a0b`, including dirty integration changes and D289-D296. No source, production viewer, BBTV, GPU, remote, checkpoint, or account state was changed.

## Verdict

The repository has a reusable autonomous neural spectator path, but no usable interactive human-v-bot entry point. `tools/spectate.sh` is bot-v-bot only and must not be used for this acceptance: it polls a remote host, copies the newest checkpoint, and loops forever. Its underlying invocation shape can be adapted to the isolated CPU runtime already present on the local rig.

Chain 9 remains the declared neural frontier (D289). Its immutable identity is SHA-256 `4344e588c124f7df2c887a824e1847008a02be57e63bd423c3c0b02964258dcc`; the campaign path was `vendor/PufferLib/checkpoints/bloodbowl/1787584031608/0000002999975936.bin` (D266). Root has independently confirmed that the authorized local rig already holds the exact blob and sidecar at `/home/rache/bloodbowl-rl-improve-20260904/anchors/chain9/0000002999975936.bin`, together with separate native-GPU and CPU runtimes. The laptop integration checkout intentionally lacks `vendor/PufferLib`; that is not a program blocker.

The locally present `training/bc_v1.bin`, `bc_v2.bin`, `bc_v15.bin`, `bc_v2_cuda.bin`, and `bc_v3b.bin` are BC artifacts, not the chain-9 champion. Do not silently substitute one.

## Indicative autonomous local launch shape

The following is extracted from `tools/spectate.sh` and shows the intended local `puffer eval` invocation. It was not executed or verified in this review and is not yet an exact runbook. Run it only inside the rig's already-provisioned CPU viewer/runtime after confirming that runtime's activation path, installed-module identity, renderer build, and chain-9 sidecar. Use an acceptance-only output/config location; do not use `tools/spectate.sh`, the live checkpoint directory, BBTV, or its service.

```bash
cd /home/rache/bloodbowl-rl-improve-20260904
export CHAIN9=/home/rache/bloodbowl-rl-improve-20260904/anchors/chain9/0000002999975936.bin
test "$(sha256sum "$CHAIN9" | awk '{print $1}')" = 4344e588c124f7df2c887a824e1847008a02be57e63bd423c3c0b02964258dcc
# Activate the already-qualified isolated CPU runtime here; exact path TBD.
python training/convert_checkpoint.py --to-torch "$CHAIN9" -o /tmp/bb-local-acceptance-20260904/chain9.torch.bin
export BBE_BANNER=chain9
export BBE_PROFILE=local-acceptance
export BBE_CKPT_STEPS=2999975936
export BBE_ART_DIR=/home/rache/bloodbowl-rl-improve-20260904/resources/bloodbowl
puffer eval bloodbowl --slowly --selfplay.enabled 0 --vec.total-agents 2 --vec.num-buffers 1 --vec.num-threads 1 --train.minibatch-size 2 --env.demo-reset-pct 0 --env.render-fps 20 --load-model-path /tmp/bb-local-acceptance-20260904/chain9.torch.bin
```

This is neural self-play, not human-v-bot. Closing the raylib window exits with code 7. For a fixed matchup, append `--env.force-home-team N --env.force-away-team M`, where generated IDs cover 0 through 29 (`BB_TEAM_COUNT` is 30). Run both orientations explicitly.

Before treating the conversion as provenance-safe, require `tools/checkpoint_lineage.py` to accept the associated lineage sidecar and record the executed `_C.__file__`, `_C.env_name=bloodbowl`, GPU flag 0, precision bytes, installed module SHA-256, source commit/tree digest, original checkpoint digest, converted checkpoint digest, conversion command, full effective config, roster IDs, and seed. A bare blob hash proves identity but not runtime compatibility.

## Proposed executable acceptance gates

The numerical budgets below are recommendations for a future frozen acceptance plan. They are not an agreed experiment budget or evidence already collected.

### A. Autonomous engine/policy acceptance (available with existing code)

1. **Identity gate:** exact chain-9 SHA above; accepted lineage sidecar; load succeeds on the newly installed integration module; no use of `latest` checkpoint selection.
2. **Legal completion gate:** from kickoff (`demo_reset_pct=0`), complete at least 100 fixed-seed games in each of these cells: policy on HOME and AWAY; contact and offense scripted opponents; five representative roster matchups including bash, agility, stunty, and mixed rosters. Every cell must finish the requested game count with `error_episodes=0`, `illegal_frac=0`, non-finite=0, fallback=0, clip=0, and no max-decision truncation. Save per-game seed, roster IDs, side, W/D/L, TD for/against, decisions, and terminal status.
3. **Side/roster gate:** run both orientations for every matchup. Then run one deterministic smoke game for every ordered 30-roster diagonal and adjacent pair (60 cells) to catch unsupported roster/skill combinations. The existing environment supports random procgen rosters and `force_home_team`/`force_away_team`, but the current viewer command exercises only whatever is sampled unless these flags are set.
4. **Latency gate:** on the target local machine, record p50/p95/p99 wall time per non-singleton neural decision after warm-up. Accept p95 <= 250 ms and p99 <= 500 ms for responsive local play. If bounded tactical search is added, accept p95 <= 1 s at team-turn roots. D292/D293 measured the current scripted search at about 11 ms/root on the Mac CPU, but it has not been integrated with chain 9 and is not evidence of neural latency.
5. **Reproduction gate:** repeat ten named seeds from each cell in a fresh process. Require identical action/dice/terminal JSONL and matching file hashes. Engine replay format already captures init, packed actions, dice, and terminal score, but the environment does not currently attach its writer to played matches.

If adopted, the proposed 100-game cell floor would be a functional local-play gate, not a strength claim. Championship claims require learned-opponent, roster-grid, long-horizon, multi-seed, exploitability, and eventually FUMBBL evidence under the project contracts.

### B. Human-v-bot acceptance (blocked by a small missing adapter)

Current status is **not usable**. `bbe_render.h` draws a spectator window and reads no keyboard/mouse input. Puffer eval supplies policy actions for both agents. There is no CLI option for a human-controlled side, no UI legal-action selector, no turn ownership handoff, no clock/timeout policy, and no match-integrated replay recorder. The replay writer is currently called only by `tools/gen_goldens.c`.

Prefer a thin local adapter around existing engine/env surfaces instead of a new game architecture:

1. Reuse `bbe_refresh_legal`, exact tuple projection/decode, `c_step`, and the raylib board. Add a `human_team` local-play mode that pauses only when that team owns the decision and exposes the enumerated legal actions. Preserve every optional BB2025 `may` choice; never auto-resolve it.
2. Present action type first, then actor/argument and square, with cancel/back before submission. Highlight only exact joint-support choices. The adapter must submit an existing `bb_action`; it must not synthesize neighboring actions or use decoder repair.
3. Attach `bb_replay_writer` at match init, action submission, RNG sink, and terminal record. Write atomically to an acceptance-only directory with a sidecar containing checkpoint/runtime/config hashes. Verify each saved game by replaying it to the identical terminal score and action/dice digest.
4. Add explicit human side, fixed roster IDs, seed, checkpoint, output path, and per-decision timeout flags. Defaults must never touch the production viewer or BBTV.
5. Acceptance: a human completes two full kickoff games, one on each side, with fixed rosters; all optional decisions remain selectable; illegal submissions are impossible; save/replay hashes match; closing or aborting creates a clearly incomplete artifact; p95 bot response meets the latency gate.

## Dependency inventory

| Dependency | Present in integration tree | Needed state |
|---|---:|---|
| BB2025 deterministic C engine and exact legal support | yes | use integrated qualified source |
| Raylib spectator renderer | source yes | verify it is built into the existing isolated CPU runtime |
| PufferLib runtime/venv | intentionally absent on laptop; isolated CPU and native-GPU runtimes exist on local rig | verify and record the selected rig runtime identity |
| Chain-9 source blob | present on local rig | validate exact SHA `4344e588...` at the anchored path |
| Chain-9 lineage sidecar | present on local rig per root confirmation | validate before acceptance |
| Native-to-Torch converter | yes | run against exact chain-9 blob |
| Spectator art | not observed in reviewed tree | stage with existing `tools/stage_spectator_art.py`, or accept fallback circles |
| Fixed roster controls | yes | `force_home_team`, `force_away_team`, IDs 0-29 |
| Scripted comparison bots | yes | contact type 0; offense type 1 |
| Human action UI/ownership adapter | no | minimal implementation required |
| Engine replay JSONL reader/writer | yes | wire into local played matches |
| Per-game acceptance recorder | no for viewer | reuse/extend existing frozen-eval records where practical |
| Tactical search | standalone evidence only | optional later; first bridge against chain 9 and learned opponents |

## Practical next steps

1. Validate the exact chain-9 blob and sidecar already anchored on the local rig. Do not fetch `latest` or choose by mtime.
2. Identify and record the exact activation and renderer command for the rig's existing isolated CPU runtime; confirm its installed module matches the qualified integration source. This review did not verify a CPU build flag or provisioning command.
3. Smoke-test the indicative autonomous invocation in an acceptance-only session, then freeze a practical fixed-seed per-game acceptance budget using existing frozen-eval tooling rather than the looping spectator script.
4. Keep the human UI and replay-wiring gaps as a bounded implementation backlog; do not implement them as part of the current trainer/search work.
5. After autonomous local acceptance is reproducible, bridge bounded search with frozen chain 9. D292/D293 show search helps a scripted offense baseline against two scripts; they do not show it improves the neural champion.

## Evidence locations

- `DECISIONS.md`: D266 (chain-9 path/result), D289 (still frontier), D290 (1,301 mean decisions/full match), D292-D293 (bounded-search scope/latency), D296 (latest native objective proof).
- `tools/spectate.sh`: remote polling, conversion, and autonomous local `puffer eval` shape.
- `puffer/bloodbowl/bbe_render.h`: spectator-only rendering and event feed; no input handling.
- `puffer/bloodbowl/bloodbowl.h`: exact action support/decode, random/forced procgen rosters, environment reset.
- `puffer/bloodbowl/binding.c` and `puffer/config/bloodbowl.ini`: force-roster, script-side/type, rendering controls.
- `engine/include/bb/bb_replay.h`, `engine/src/bb_replay.c`, `tools/gen_goldens.c`: deterministic JSONL replay capability and its current limited wiring.
- `docs/opponent-composition-paired-plan-2026-09-04.md`: exact chain-9 digest and current runtime identity expectations.
