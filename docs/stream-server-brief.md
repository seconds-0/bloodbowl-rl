# Blood Bowl Live — game-server build brief (backend)

*Instructions for the agent building the stream backend in THIS repo
(bloodbowl-rl). The wire contract is `docs/stream-protocol.md` (v1, frozen —
additive only); the frontend is built separately against that same spec.
Read `CLAUDE.md` and the tail of `DECISIONS.md` first; where this brief and
the ledger disagree, the ledger wins.*

## What you're building

One long-running Python process, `stream/server.py`, that:
1. plays an endless series of Blood Bowl games between trained checkpoints
   at ~1-2 decisions/second,
2. after every decision, serializes the change per the protocol and fans it
   out to all connected WebSocket clients,
3. rotates matchups when games end, forever, and survives its own crashes.

No video, no rendering server-side. State JSON only.

## The machinery you reuse (verified locations)

| Piece | Where | Note |
|-------|-------|------|
| Env + engine | `puffer/bloodbowl/` (source of truth) → installed snapshot in `vendor/PufferLib/ocean/bloodbowl/` | build with `--float` (torch path) |
| Policy inference + LOGITS | torch backend (`vendor/PufferLib/pufferlib/torch_pufferl.py`) | the CUDA backend does NOT expose logits — you MUST use the torch path; CPU inference is plenty at 2 dec/s |
| Two-checkpoint play | `puffer match` pattern (`pufferl.py:509-577`): `--load-model-path A --load-enemy-model-path B` | torch state_dicts; convert flat blobs with `training/convert_checkpoint.py --to-torch` (obs-size 2782) |
| Game state | `env->match` via the binding; players `players[32].{x,y,stance,location}`, `ball.{x,y,state,carrier}`, `score`, `half`, `turn[2]`, `active_team` | serialize from match fields, not obs bytes |
| Block odds for the `ev` card | `bb_block_ev()` (`engine/include/bb/bb_blockev.h:41-63`) | computed at declaration; obs-v4 A1/A2/B planes carry per-square versions |
| Event ticker semantics | the feed-event taxonomy in `bbe_render.h:97-161` (BBE_EV_*) | mirror its event kinds/colors in the `feed` field |
| Value head → win_prob | torch policy value output, squash to P(home) | calibrate roughly; it's a vibe bar, not a market |
| Checkpoints | newest flagship ckpt BY STEP NUMBER in `vendor/PufferLib/checkpoints/bloodbowl/<newest dir>/` | footgun 10: mtime ≠ step |
| Pacing | do NOT use render_fps/raylib — the server is headless; throttle your own decision loop with asyncio sleep | 0.5-1s between decisions, faster during opponent turns is fine |

## Architecture (keep it boring)

Single asyncio process:
- **Game task:** steps ONE env (not the vec path — a single `Bloodbowl` env
  instance through the binding, or simplest: a 2-agent `puffer` env with
  batch size 1) with two torch policies (home/away). After each policy
  decision: build the `delta` message (moves diff, ball, dice events since
  last decision, action + top-3 probs from the logits over the legal mask,
  blockev card when the action was a block/blitz declaration, win_prob from
  the value head), `await broadcast(msg)`, `await asyncio.sleep(pace)`.
- **WS task:** `websockets.serve()`; on join send `hello` + current
  `snapshot`; keep a client set; broadcast = gather send to all, drop dead
  sockets. Send a fresh `snapshot` every ~100 deltas and on `resync`.
- **Matchmaker:** on game end emit `match_end`, wait `next_match_in_s`, pick
  next pairing, emit `match_start`. v1 rotation: flagship-newest vs one of
  {flagship-previous-stage, passing-lineage-best, bc_v4 teacher}; procgen
  rosters each game (the env does this on reset); name teams "Gen-<steps>
  <roster>" style.
- **Dice/event capture:** the engine resolves dice inside `bb_advance`; the
  cleanest capture is the existing feed-hook pattern (`bbe_on_feed`) — the
  env already emits BBE_EV_* events with actor/target; expose them through
  the binding the same way the Log dict is exposed (see binding.c dict_set
  block) or via a small ring the python side drains each step. If that
  binding change is needed, it follows the 3-sync-point rule (bloodbowl.h /
  binding.c / ini — see CLAUDE.md).

## Deliverables

1. `stream/server.py` + `stream/requirements.txt` (websockets, torch CPU).
2. `stream/PROTOCOL.md` → symlink/copy of `docs/stream-protocol.md`.
3. **`mock/fixture_match.jsonl`** — record one real flagship game as one
   protocol message per line (snapshot + every delta + match_end). This is
   owed to the website agent — generate it as soon as the serializer works.
4. Sprite pack: copy the FFB art the raylib viewer uses (`$BBE_ART_DIR`
   resources + `iconmap.txt` mapping) into a servable dir; art use is
   CLEARED (Alex, 2026-06-10). Serve via the same process (aiohttp static)
   or hand the dir to CF Pages.
5. Systemd-style run loop: restart-on-crash wrapper, single-flight lock,
   log to `/var/log/bbstream.log` or equivalent.

## Where it runs

- **v1: Railway** (Alex's standard stack) — CPU container, torch-cpu wheel,
  expose `/ws` + static art; CF DNS in front (`bbstream.seconds0.com`,
  final name TBD with Alex).
- Fallback/dev: the 2070 rig (rache@100.97.209.46, see rig-env.sh) behind a
  Cloudflare Tunnel — $0 but couples uptime to a home box.
- The checkpoint refresh path: a small cron/script that pulls the newest
  flagship ckpt from the training boxes (or a synced bucket) and hot-swaps
  at the next match boundary. v1 can ship with a fixed pair of bundled
  checkpoints — do NOT block launch on auto-refresh.

## Acceptance checklist

- [ ] `python stream/server.py --ckpt-a X.bin --ckpt-b Y.bin` runs a full
      game end-to-end and a `websocat` client sees hello→snapshot→deltas→
      match_end→match_start, valid per `docs/stream-protocol.md`.
- [ ] Action probs present on every agent decision; `ev` card present on
      every block/blitz declaration; win_prob in every snapshot/delta.
- [ ] Two browser tabs see identical seq streams; kill one mid-game, rejoin,
      `snapshot` recovers it.
- [ ] Server survives env crash / game exception: logs, restarts the match,
      stream continues (viewers see a new `match_start`).
- [ ] `mock/fixture_match.jsonl` generated and handed to the website agent.
- [ ] 24h soak on the dev box without memory growth (torch no_grad, no
      tensor accumulation).

## Non-goals (v1)

League/Elo persistence, viewer voting, replay archive (the bb_replay writer
exists — wire it later), multi-game concurrency, auto checkpoint refresh.
Ship the single canonical stream first.
