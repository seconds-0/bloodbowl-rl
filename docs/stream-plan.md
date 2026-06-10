# bloodbowl.live — 24/7 AI Blood Bowl stream (plan)

*Planned 2026-06-10. Status: approved concept (Alex), build deferred until he
migrates seconds0.com to Cloudflare and redoes it. Target: a page on
seconds0.com (or a subdomain, e.g. `bloodbowl.seconds0.com`) with a live,
always-on model-vs-model game.*

## Concept

One canonical, always-running Blood Bowl game between trained checkpoints,
streamed to the browser as **game state over WebSocket** (not video), rendered
client-side on canvas. The hook: overlays that show *the AI's mind* — win
probability, the dice odds it sees (bb_blockev), and the action probabilities
behind each move. When a game ends, the next matchup starts. Forever.

**Why state-feed beats video:** kilobytes per decision instead of megabits of
video; one broadcast fans out to unlimited viewers; crisp at any zoom; viewers
can pan/zoom independently; and we already compute everything worth showing.

## Architecture

```
[game server: python, plays 1 game at ~1-2 decisions/sec]
    puffer-eval-style loop, torch backend (exposes LOGITS for the overlay)
    flagship ckpt vs rotating opponents; procgen rosters each game
        | per decision: JSON event {state delta, dice, action, probs}
        v
[broadcaster: websocket fanout]  -- full snapshot on join, deltas after
        |
        v
[frontend: static page on Cloudflare Pages @ seconds0.com]
    canvas pitch renderer + event ticker + "AI mind" overlays
```

## Reuse map (what already exists — verified 2026-06-10)

| Need | Existing piece | Where |
|------|----------------|-------|
| Game state | direct `env->match` fields (players x/y/stance, ball, score, half, turn, active_team) | `puffer/bloodbowl/bloodbowl.h:335` |
| Event ticker | `bbe_on_feed()` hook + ring buffer + per-type color codes (BLOCK/DODGE/GFI/PICKUP/PASS/TD/TURNOVER...) | `bbe_render.h:97-161, 531-555` |
| Casualty drama | memorial hook (`bbe_on_casualty`) — first blood / deaths | `bbe_render.h:205-273` |
| Dice odds overlay | `bb_block_ev()` queryable at decision time (P(def down), P(ball out), P(turnover)...) | `engine/include/bb/bb_blockev.h:41-63`, `bb_blockev.c:461` |
| Move odds overlay | obs-v4 B plane (step success per square), A1/A2 (block outcome per square) | `bloodbowl.h:114-122` |
| Action probabilities | torch backend logits (CUDA backend does NOT expose them) → **server runs the torch path** | `torch_pufferl.py` |
| Pacing | `--env.render-fps` kwarg (decisions/sec) | `bbe_render.h:319`, binding kwarg |
| Two-checkpoint play | `puffer match --load-model-path A --load-enemy-model-path B` | `pufferl.py:509-577` |
| Replay theater (later) | bb_replay JSON-Lines writer/reader, deterministic re-sim | `engine/include/bb/bb_replay.h` |
| Visual language | the raylib viewer's layout/colors/iconography as the design reference | `bbe_render.h` |

Inference at 1–2 decisions/sec is trivial (1–2M param net) — CPU-only torch is
fine; no GPU needed in the serving container.

## Components & phases

### Phase 1 — broadcaster MVP (~2 days)
- `stream/server.py`: headless eval loop (torch backend, no raylib), plays
  flagship-vs-opponent at throttled pace; after each decision emits a JSON
  event: `{seq, state?, delta, event_feed[], dice, action, action_probs,
  blockev?}`. Full state snapshot every N events + on client join.
- WebSocket fanout (`websockets` or FastAPI). Single process, asyncio.
- State schema doc (`stream/PROTOCOL.md`) — versioned from day 1.
- Matchmaker: game ends → pick next pairing (flagship vs snapshot ladder /
  scripted bot / mirror), procgen fresh rosters; emit `match_start` with
  team sheets.

### Phase 2 — frontend MVP (~2-3 days)
- Static page (vanilla TS + canvas, no framework needed): 26×15 pitch,
  players (team colors, stance, ball carrier ring), score/half/turn HUD,
  scrolling event ticker with the viewer's color language.
- Connect/reconnect/snapshot-then-delta client.
- Deploy to Cloudflare Pages; route from seconds0.com when the CF migration
  lands (until then: any preview URL).

### Phase 3 — the "AI mind" overlays (~1-2 days, the differentiator)
- Win-probability bar (derive from value head — torch backend exposes it).
- On block declarations: the bb_blockev card ("AI sees: 73% knockdown, 22%
  ball out, 9% turnover").
- Action-probability ghost: before each move animates, show the top-3
  candidate actions with percentages (from logits over the legal mask).
- Dice roll presentation with the pre-roll odds it faced.

### Phase 4 — league wrapper (later, makes it sticky)
- Persistent standings: checkpoint generations as named teams ("Gen-30B
  Grizzlies"), Elo over streamed games, title defenses.
- Replay theater: archive .bbr of every streamed game; "best of yesterday"
  reel via deterministic re-sim.
- Viewer interaction: vote next matchup; maybe a "beat the AI's pick" widget
  (show a decision, let viewers guess, reveal what the model chose).

## Hosting

- **Frontend:** Cloudflare Pages (free), on seconds0.com post-migration.
- **Game server + WebSocket:** needs a long-lived process — NOT a CF Worker.
  Options, in preference order:
  1. **Railway** (Alex's standard stack) — small CPU container, ~$5-10/mo;
     CF DNS/proxy in front (`wss://stream.seconds0.com`).
  2. **The 2070 rig** via Cloudflare Tunnel — $0, plenty of headroom (the
     stream is ~3% of a core), but couples uptime to a home Windows box.
  3. Fly.io equivalent of (1).
  Start on Railway for clean uptime; the rig is the free fallback.
- Scale note: state-feed fanout handles hundreds of viewers on one tiny
  container; if it ever matters, add a fanout relay (or CF Durable Object) —
  not a day-1 problem.

## Open decisions (cheap to defer)

- Exact event schema (write PROTOCOL.md first thing in Phase 1).
- Rendering style: clean 2D vector look vs FFB sprite art (sprites exist in
  the repo's art dir but check license posture before public use — engine
  rule: no GW assets shipped; the procedural token fallback at
  `bbe_render.h:362-407` is the safe default).
- Server language: Python first (reuses the torch eval path directly); a C
  inference rewrite is possible later but unnecessary at 2 decisions/sec.
- Whether the stream server doubles as the eval-tournament runner (same
  machinery, different pacing).

## Effort summary

~1 focused week to a public, genuinely novel page: Phases 1-3 ≈ 5-7 days.
Phase 4 is open-ended polish. Total run cost ≈ $5-10/mo.
