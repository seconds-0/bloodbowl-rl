# Blood Bowl Live — frontend integration spec (v1)

*Handoff doc for the seconds0.com website agent. This is the complete contract
for embedding the 24/7 AI Blood Bowl stream. The backend (game server) is
built separately in the bloodbowl-rl repo against this same spec — build the
frontend against this document and the mock fixtures, not against the live
server. Protocol version: `1`. Owner: bloodbowl-rl repo, docs/stream-plan.md.*

## What you're building

A page (or embed) that renders a live, always-running Blood Bowl match
between AI agents. You receive **game state as JSON over a WebSocket** and
draw it on canvas. You are NOT receiving video. One shared canonical game;
all viewers see the same match.

- Pitch: **26 columns x 15 rows** of squares. Coordinate (0,0) = top-left.
  Home team attacks toward x=25 (their endzone to defend is x=0); away
  attacks toward x=0. Endzones are the x=0 and x=25 columns.
- Up to 32 players (16/side, slots 0-15 home, 16-31 away), one ball.
- Pace: ~1-2 decisions/second. Each decision arrives as one `delta` message.
- Games last ~15-30 min at this pace, then `match_end` → a few seconds →
  `match_start` for the next pairing. The stream never stops.

## Connection

- Endpoint (production): `wss://bbtv.seconds0.com/ws`. The bundled web client
  uses the current page host by default and still accepts a `?ws=...` override
  for development or alternate deployments.
- On connect the server sends `hello`, then a full `snapshot`, then `delta`
  messages as the game progresses.
- Heartbeat: server sends `{"t":"ping","seq":N}` every 15s; reply
  `{"t":"pong"}` (or ignore — server only drops you after 60s silence).
- Reconnect: exponential backoff (1s → 30s cap). On reconnect you get a fresh
  `snapshot` — discard any stale local state. `seq` is monotonically
  increasing; if you see a gap, request `{"t":"resync"}` and the server sends
  a fresh `snapshot`.

## Message types (server → client)

All messages: `{"v":1, "t":"<type>", "seq":<int>, ...}`.

### `hello`
```json
{"v":1,"t":"hello","seq":0,"proto":1,"server":"bbstream/0.1",
 "match_id":"m_20260610_1832","sprite_base":"https://bbstream.seconds0.com/art/"}
```

### `match_start`
```json
{"v":1,"t":"match_start","seq":1,"match_id":"m_20260610_1832",
 "home":{"name":"Gen-90B Grizzlies","roster":"Orc","color":"#8b1a1a",
         "agent":"flagship-kickoff4","elo":1620},
 "away":{"name":"Gen-60B Wolves","roster":"Wood Elf","color":"#1a4d8b",
         "agent":"snapshot-60B","elo":1544},
 "players":[ /* 32 entries, see snapshot.players */ ]}
```

### `snapshot` — full state (on join, resync, and every ~100 deltas)
```json
{"v":1,"t":"snapshot","seq":412,"match_id":"m_20260610_1832",
 "score":[2,1], "half":2, "turn":[5,4], "active_team":0,
 "weather":"nice",
 "ball":{"x":12,"y":7,"state":"held","carrier":3},
 "players":[
   {"slot":0,"side":"home","x":12,"y":7,"stance":"standing",
    "position":"Blitzer","num":1,"icon":"orc_blitzer_1",
    "has_ball":false,"stats":{"ma":6,"st":3,"ag":3,"pa":4,"av":9},
    "skills":["Block"]},
   {"slot":17,"side":"away","x":-1,"y":-1,"stance":"ko",
    "position":"Wardancer","num":2,"icon":"welf_wardancer_2", "...":"..."}
 ],
 "win_prob":0.64}
```
- `stance`: `standing | prone | stunned | ko | cas | sent_off`. Off-pitch
  players have `x:-1,y:-1` (render in dugout rails, see Rendering).
- `ball.state`: `held | on_ground | in_air | off_pitch`. When `held`,
  `carrier` is a player slot.
- `win_prob`: P(home wins) from the model's value head, 0..1.

#### Additive v1.x: `teamstats`
Snapshots may include a full per-game team-stat accumulator. This is additive
under protocol `v:1`; clients that do not render it should ignore it.

```json
"teamstats":{
  "home":{"blocks":12,"tier":[9,2,1],"dodge":[8,10],"gfi":[5,6],
          "pickup":[2,3],"turnovers":1,"pass":1,"handoff":1,"foul":2},
  "away":{"blocks":7,"tier":[3,3,1],"dodge":[4,6],"gfi":[2,2],
          "pickup":[1,2],"turnovers":2,"pass":0,"handoff":1,"foul":0}
}
```

`tier` is `[good, even, bad]`, where good is attacker-choice 2d/3d, even is
1d, and bad is defender-choice 2d-red/3d-red. Test rows use
`[successes, attempts]`.

### `delta` — one decision (the common message, ~1-2/sec)
```json
{"v":1,"t":"delta","seq":413,
 "moves":[{"slot":3,"x":13,"y":7,"stance":"standing"}],
 "ball":{"x":13,"y":7,"state":"held","carrier":3},
 "score":null,"turn":null,"active_team":0,
 "action":{"type":"MOVE","actor":3,"target":[13,7],
           "probs":[["MOVE 13,7",0.71],["MOVE 12,8",0.14],["BLOCK 19",0.09]]},
 "dice":null,
 "ev":null,
 "win_prob":0.65,
 "teamstats":null,
 "feed":[{"kind":"move","text":"#1 Grimgor advances","side":"home"}]}
```
Only changed fields are non-null. `moves` lists player position/stance
changes this step (usually 1, can be several after a push chain).
`teamstats` is the full object when the accumulator changed on that decision,
otherwise `null`. Older protocol-v1 servers may omit it entirely.

`action.probs`: the model's top-3 candidate actions with probabilities —
render as the "AI is thinking" overlay just before/as the action animates.

When dice are involved:
```json
 "dice":{"kind":"block","rolls":[5,2],"picked":5,"result":"Defender Down",
         "reroll_used":false},
 "ev":{"p_def_down":0.73,"p_att_down":0.08,"p_ball_out":0.22,"p_turnover":0.09}
```
`ev` is what the model *saw before rolling* (bb_blockev) — render as the
odds card ("AI saw: 73% knockdown, 22% ball out"). `dice.kind`:
`block | d6 | 2d6 | scatter`. For non-block d6 tests include
`{"target":4,"roll":5,"ok":true,"label":"Dodge"}`.

Current `stream_backend/game.py` runs from the Python vec observation/action
surface, not from inside the engine frame stack. For movement tests
(`GFI`/rush, `Dodge`, `Pickup`) that surface exposes the pre-step board,
target square, weather, player stats/skills, and post-step outcome, so the
backend emits inferred d6 objects such as:

```json
{"kind":"d6","label":"GFI","target":2,"roll":null,"ok":true,
 "source":"inferred_from_state"}
```

The exact consumed D6 face is not exported after `vec.step()`: successful
tests are popped immediately, failed tests may pause only at a reroll decision
with the target exposed, and the final die/result is consumed into parent
procedure state before Python receives the next observation. Block die faces
are likewise stored in the internal block frame data and are not exposed to
the Python stream; block dice may therefore include `rolls:null` plus
`result`, `ndice`, and `tier`.

When one engine decision resolves more than one inferred roll, the first item
is also placed in `dice` for old clients and the full ordered list is emitted
as additive `dice_seq:[...]`.

`feed`: pre-formatted ticker lines, color-key by `kind`:
`move|block|blitz|dodge|gfi|pickup|pass|handoff|foul|td|turnover|injury|ko|cas|kickoff`.
TD/turnover/cas lines deserve banner treatment (cas = the "memorial" —
the backend marks first blood with `"first_blood":true`).

### `match_end`
```json
{"v":1,"t":"match_end","seq":2200,"score":[3,1],"winner":"home",
 "mvp":{"slot":3,"name":"Grimgor","tds":2},
 "next_match_in_s":8}
```

## Rendering guide

- **Sprites:** the FFB sprite art is licensed-cleared for this use. The
  backend serves a sprite pack at `sprite_base`: `icons/<icon>.png` per
  player (the `icon` field), `pitch.png`, `ball.png`. Fallback: draw circles
  in side color with the player `num` — required anyway for loading states.
- Layout: pitch canvas + right sidebar (event ticker, ~12 lines, color-coded)
  + top HUD (team names, score, half, turn counters, active-team indicator) +
  win-prob bar. The bloodbowl-rl raylib viewer is the visual reference; match
  its information layout, modernize the skin freely.
- Ball-carrier: gold ring around the sprite. Prone/stunned: rotate sprite 90°/
  180° or use overlay glyphs. Dugouts: two side rails listing off-pitch
  players by stance (KO'd, casualties, sent off).
- The `action.probs` overlay: brief ghost-arrows or a small card near the
  actor; keep it subtle at 1-2 decisions/sec. The `ev` odds card on
  blocks/blitzes is the signature feature — make it legible.
- Animate moves as short tweens (~250ms); never block on animation — if
  deltas arrive faster, snap.

## Mock mode (build against this TODAY)

Until the backend is live, drive the UI from fixtures:
1. `mock/fixture_match.jsonl` — a full recorded match as one message per
   line (snapshot + ~2000 deltas + match_end). *The bloodbowl-rl side will
   generate this file from a real game and hand it over; ask for it.*
2. Dev player: `node mock/play.js --speed 1.5` — trivial script that reads
   the JSONL and emits each line over a local `ws://localhost:8787/ws` with
   the same pacing semantics. (~20 lines; write it in the website repo.)
The UI must not care which it's connected to.

## Non-goals for the frontend
- No game logic, no legality checking, no replay scrubbing (v1). Render what
  the server says, trust `seq` ordering, resync on gaps.
- No client→server messages besides `pong` and `resync` in v1. (Viewer
  voting/chat is a later protocol bump.)

## Versioning
`v` bumps only on breaking changes; additive fields may appear at any time —
ignore unknown fields. The backend will keep `proto:1` clients working.

## Contact surface between the two repos
- This file is the single source of truth (lives in bloodbowl-rl:
  `docs/stream-protocol.md`; copy is fine but upstream wins).
- The website agent owes: the page/embed, canvas renderer, mock player.
- The bloodbowl-rl side owes: the game server, the sprite pack at
  `sprite_base`, `mock/fixture_match.jsonl`, and the production endpoint URL.
