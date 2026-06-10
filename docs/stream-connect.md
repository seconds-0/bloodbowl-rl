# Blood Bowl Live — CONNECTION INSTRUCTIONS (it's built)

*Supersedes the build briefs for integration purposes. Both halves exist and
are verified: the backend plays real games and broadcasts protocol-v1; the
frontend renders them. This doc is what the seconds0.com agent needs to put
it on the site. Wire contract: `docs/stream-protocol.md` (unchanged, v1).*

## What exists, where

| Piece | Path (bloodbowl-rl repo) | Status |
|-------|--------------------------|--------|
| Game server | `stream_backend/server.py` (+ `game.py`, `decoder.py`) | ✅ verified: full game = 816 valid messages, live WS client tested |
| Recorded real fixture | `stream_backend/fixture_match.jsonl` | ✅ a complete flagship-vs-teacher game (2 TDs, block odds cards) |
| Frontend page | `stream/web/` (index.html, app.js, style.css) | built against the same protocol |
| Mock WS player | `stream/mock/play.js` | replays any fixture JSONL at ws://localhost:8787/ws |

## Run it (dev, anywhere with the repo + torch)

```bash
# backend (on a box with the built env + venv — currently the 2070 rig):
source rig-env.sh && source vendor/PufferLib/.venv/bin/activate
cd stream_backend
python server.py --ckpt-a ../training/flagship_k2_torch.bin \
                 --ckpt-b ../training/bc_v4_torch.bin --pace 0.6
# -> ws on :8787, plays games forever

# frontend (any static server):
cd stream/web && python3 -m http.server 8080
# open http://localhost:8080/?ws=ws://<backend-host>:8787/ws
```

No backend handy? `node stream/mock/play.js --fixture ../../stream_backend/fixture_match.jsonl`
serves the recorded real game on the same port — the page can't tell the
difference.

## Putting it on seconds0.com

1. **Page:** copy `stream/web/` into the site (it's three static files, no
   build step, no dependencies) — serve at `/bloodbowl` or embed via iframe.
   The WebSocket URL is read from the `?ws=` query param or the
   `window.BB_WS_URL` global; set it in the page wrapper.
2. **Server:** one long-lived CPU container.
   - **Railway (recommended):** repo subdir deploy of `stream_backend/` +
     `pip install torch --index-url https://download.pytorch.org/whl/cpu websockets`
     + the two torch checkpoints (~16MB each, commit-lfs or volume) +
     `python server.py --ckpt-a ... --ckpt-b ... --pace 0.6`. Expose the port;
     put CF DNS in front: `wss://bbstream.seconds0.com/ws`.
     NOTE: the container needs the built `pufferlib` env (`_C` extension).
     Simplest image recipe: ubuntu + clang + libomp-dev + ccache +
     nvidia-cuda-toolkit-free alternative — OR just build on the 2070 and use
     option (b) below until the Docker image is sorted. The Dockerfile is the
     one genuinely remaining piece of work.
   - **2070 rig (works TODAY, $0):** the server is already running there.
     Expose with a Cloudflare Tunnel: `cloudflared tunnel --url
     http://localhost:8787` on the rig, then point the page's `?ws=` at the
     tunnel hostname (wss). Uptime = the rig's uptime (it auto-recovers from
     reboots; the babysitter keeps the trainer alive but a small systemd-style
     wrapper for the stream server is in stream_backend/ TODO).
3. **TLS note:** browsers require `wss://` from an https page — both Railway
   and CF Tunnel give you that for free; raw `ws://IP:8787` only works from
   http/localhost dev pages.

## Current live dev endpoint

On the tailnet right now: `ws://100.97.209.46:8787/ws` (the 2070). Any
device on Alex's tailnet can open the page with
`?ws=ws://100.97.209.46:8787/ws` and watch the flagship play. (Not reachable
from the public internet until the CF Tunnel step.)

## Known v1 limitations (by design, see DECISIONS)

- `dice.rolls` (literal die faces) are null — outcomes and pre-roll odds are
  shown instead; exposing raw rolls needs a small C-side feed export (queued).
- `ev` cards carry p_def_down/p_att_down (from the obs planes); p_ball_out
  needs the same C export.
- Team names are checkpoint names; roster names/league flavor come with the
  matchmaker upgrade.
