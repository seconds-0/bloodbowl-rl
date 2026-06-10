# Blood Bowl Live — web frontend

Canvas renderer for the bbstream WebSocket protocol (`docs/stream-protocol.md`). Vanilla JS, no build step.

**Run locally:**
1. `cd stream/mock && npm install && node make_fixture.js` (regenerates the synthetic fixture)
2. `node play.js --speed 4` (mock server on `ws://localhost:8787/ws`; default speed = 1 delta / 600ms)
3. `cd ../web && python3 -m http.server 8000` then open <http://localhost:8000/>

**WebSocket URL:** defaults to `ws://localhost:8787/ws`; override with `?ws=wss://bbstream.seconds0.com/ws`.

**Mock vs real:** `mock/fixture_synthetic.jsonl` is generated fake-but-protocol-valid data for renderer dev; the real recorded fixture (`mock/fixture_match.jsonl`) and the live server replace it with zero frontend changes.

**Sprites:** FFB iconset sheets, served relative to `hello.sprite_base` (mock: `art/`, a few sample sheets + `pitch.png` committed under `web/art/`). Sheet layout: 4 columns `[home, home-active, away, away-active]`, square cells (`width/4`), rows = cosmetic variants picked by `slot % rows`. Players without a loaded sprite fall back to numbered circles.
