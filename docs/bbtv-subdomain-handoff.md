# BBTV → permanent subdomain (bbtv.seconds0.com) — handoff

**For:** an AI agent with access to Alex's Cloudflare account + the `seconds0.com`
domain, but **no prior context** about this project. This document is
self-contained; you should not need to read anything else in the repo except the
one file you'll patch (`stream/web/app.js`).

**Goal:** replace the two ephemeral `*.trycloudflare.com` quick-tunnel URLs that
currently expose the "Blood Bowl Live" (BBTV) stream with **one permanent
hostname** — `bbtv.seconds0.com` — backed by a Cloudflare **named tunnel** with a
persistent credentials file. After this, the stream lives at a stable URL that
survives reboots and cloudflared restarts.

---

## 0. The deployment you're modifying (take this AS GIVEN — it is verified working today)

There is a home Windows box running WSL2 Ubuntu. Alex calls it **"the rig."**

- **Reachability:** ONLY via Alex's tailnet, at **`100.97.209.46`**. There is no
  public IP and no port-forward. SSH user is **`rache`** with **passwordless
  sudo**. You reach it with:
  ```bash
  ssh rache@100.97.209.46
  ```
  (Your machine must be on Alex's tailnet for this to resolve. If it doesn't
  connect, that's a tailnet-membership problem — stop and tell Alex; do not try
  to find another route to the box.)

- **What's running on the rig** — four **systemd _user_ services** (note: `--user`,
  not system units), with `loginctl enable-linger rache` already set so they run
  without an active login and survive reboot:

  | unit | what it does | port / path |
  |------|--------------|-------------|
  | `bbstream` | the game server; serves the live match as JSON over a **WebSocket** | `:8787`, path **`/ws`** |
  | `bbweb`    | `python -m http.server` serving the static page + sprite art | `:8788` |
  | `bbtun-web` | `cloudflared tunnel --url http://localhost:8788` — **QUICK tunnel for the page** | ephemeral `*.trycloudflare.com` |
  | `bbtun-ws`  | `cloudflared tunnel --url http://localhost:8787` — **QUICK tunnel for the WebSocket** | ephemeral `*.trycloudflare.com` |

  The two `bbtun-*` services are the **ephemeral things you are replacing.** Every
  time cloudflared restarts they hand out a brand-new random `trycloudflare.com`
  hostname, which breaks the page's saved WS URL. `bbstream` and `bbweb` are
  **off-limits — do not touch them** (see §8).

- **cloudflared binary:** already installed at **`/usr/local/bin/cloudflared`**,
  version **2026.6.0**. You do **not** need to install or upgrade it.

- **The page's WebSocket URL** is read from a `?ws=` query param or a
  `window.BB_WS_URL` global, with a hard-coded default. The exact mechanism and
  the patch are in §4.

- **`seconds0.com` zone status:** Alex is **migrating this domain to Cloudflare**.
  It may or may not be fully on Cloudflare when you run this. **This doc handles
  both cases** — see §1a. Short version: everything except the final DNS step can
  be pre-staged before the nameserver migration completes.

---

## 1. Design decision: ONE hostname, ingress path-routing (recommended)

You have two ways to expose page + websocket:

1. **Two hostnames** — `bbtv.seconds0.com` for the page (→ `:8788`) and
   `bbtv-ws.seconds0.com` for the websocket (→ `:8787`). Two DNS records, two
   certs, and the browser page on host A opens a socket to host B = a
   **cross-origin** request.
2. **One hostname, path-routed (USE THIS).** A single `bbtv.seconds0.com`. The
   tunnel's **ingress rules** send requests whose path is `/ws` to the websocket
   backend (`:8787`) and **everything else** to the static page backend (`:8788`).

**Recommend option 2.** Why:

- **No CORS / no mixed-origin.** The page and its websocket share one origin, so
  `wss://<same-host>/ws` "just works" with no cross-origin handshake surprises.
- **One certificate, one DNS record, one thing to reason about.** Cloudflare's
  edge cert for `bbtv.seconds0.com` covers both the page load and the WSS upgrade.
- **Simplest page config.** The page can derive its socket URL from its own
  location (`wss://<location.host>/ws`) and never needs a hard-coded hostname
  again (§4).

The rest of this doc implements option 2.

### 1a. Is the zone already on Cloudflare?

Check before you start:

```bash
# (run wherever you have the CF-authed agent / dashboard access)
# Dashboard: does seconds0.com appear as an Active zone?
```

- **Zone already Active on Cloudflare** → you can do every step end-to-end,
  including the DNS route in §2, and verify live.
- **Zone NOT yet migrated** (still on the old registrar's nameservers) → do
  **everything except** the live DNS verification. Specifically you can still:
  create the tunnel (§2 step 1–3), write `config.yml` (§2 step 4), install the
  systemd service (§3), patch the page (§4). The **only** blocked step is the
  `cloudflared tunnel route dns` / DNS-record creation actually resolving
  publicly — the CNAME can be **created in the (pending) Cloudflare zone** ahead
  of time and will go live the moment the nameserver migration completes. So:
  pre-stage all of it, then the migration cutover is the single switch that turns
  it on. Tell Alex which state you're in and what's left blocked.

---

## 2. Create the named tunnel + DNS

All tunnel commands run **on the rig, as `rache`** (the credentials file and the
systemd service that uses it both live on the rig). SSH in first:

```bash
ssh rache@100.97.209.46
```

### Step 1 — Authenticate cloudflared to the Cloudflare account (`cert.pem`)

The named tunnel needs an account cert at `~/.cloudflared/cert.pem`. Get it with:

```bash
cloudflared tunnel login
```

This prints a **URL to open in a browser** and waits. **You (the agent) cannot
open it** — the box has no browser and you're on it over SSH.
**Hand that URL to Alex** and ask him to open it, log into Cloudflare, and pick the
`seconds0.com` zone. This is the **same pattern as a device-auth / OAuth dance**:
you surface the link, the human approves, the CLI unblocks and writes
`~/.cloudflared/cert.pem`. Wait for the command to return success before
continuing.

> If the zone is **not yet on Cloudflare**, the login still works (it authorizes
> the *account*); you just won't be able to pick `seconds0.com` as an active zone
> until migration. You can still create the tunnel (next step). Note this to Alex.

### Step 2 — Create the tunnel

```bash
cloudflared tunnel create bbtv
```

This:
- creates a tunnel named **`bbtv`** and prints its **UUID** (capture it),
- writes the **credentials file** to **`~/.cloudflared/<UUID>.json`** (this is the
  long-lived secret that lets the tunnel run unattended — back-of-mind: it's what
  makes this *not* ephemeral).

Confirm:
```bash
cloudflared tunnel list          # 'bbtv' should appear with its UUID
ls -l ~/.cloudflared/            # cert.pem + <UUID>.json present
```

Record the UUID; you need it in the config and the DNS route. In the snippets
below, substitute it for `<UUID>`.

### Step 3 — Route DNS for the single hostname

```bash
cloudflared tunnel route dns bbtv bbtv.seconds0.com
```

This creates a **proxied CNAME** `bbtv.seconds0.com → <UUID>.cfargotunnel.com` in
the Cloudflare zone.

- **Zone Active:** record appears and resolves shortly after.
- **Zone pending migration:** if this command errors because the zone isn't on
  Cloudflare yet, create the same CNAME manually in the (pending) Cloudflare
  dashboard zone for `seconds0.com`:
  - Name: `bbtv`
  - Target: `<UUID>.cfargotunnel.com`
  - Proxy status: **Proxied (orange cloud)** — required; the tunnel only works
    proxied.
  It goes live at migration cutover.

> Only **one** hostname is needed (that's the whole point of §1). Do **not** route
> a second `bbtv-ws` name.

### Step 4 — Write the tunnel config with ingress path-routing

Create **`~/.cloudflared/config.yml`** on the rig with exactly this content
(substitute the real UUID twice):

```yaml
tunnel: <UUID>
credentials-file: /home/rache/.cloudflared/<UUID>.json

ingress:
  # WebSocket state feed → the game server on :8787.
  # cloudflared matches `path` as a Go regexp via MatchString (UNANCHORED),
  # so anchor it with ^ to avoid also matching things like /foo/ws.
  - hostname: bbtv.seconds0.com
    path: ^/ws
    service: ws://localhost:8787
  # Everything else on this host → the static page + art on :8788.
  - hostname: bbtv.seconds0.com
    service: http://localhost:8788
  # Required catch-all (any other host): refuse cleanly.
  - service: http_status:404
```

Notes that matter (verified against current Cloudflare tunnel docs, June 2026):
- **Rule order is top-to-bottom; first match wins.** The `/ws` rule MUST come
  before the catch-all page rule, or the page rule would swallow `/ws` too.
- **`path` is a Go regular expression matched with `MatchString` (unanchored).**
  `^/ws` anchors at the start of the path so it matches `/ws` (and `/ws?…`,
  `/ws/…`) but not an unrelated path that merely contains `ws`. The backend's
  websocket lives at exactly `/ws`, so `^/ws` is correct and the upstream
  `service: ws://localhost:8787` is given **without** the path (cloudflared
  forwards the original path through).
- **`ws://localhost:8787`** (not `http://`) tells cloudflared this is a websocket
  upstream. WebSocket upgrades are supported by cloudflared by default.
- The final `http_status:404` is the mandatory catch-all (a tunnel config is
  invalid without a catch-all last rule).

Validate the config before wiring it into systemd:

```bash
cloudflared tunnel ingress validate
cloudflared tunnel ingress rule https://bbtv.seconds0.com/ws    # → expect ws://localhost:8787
cloudflared tunnel ingress rule https://bbtv.seconds0.com/       # → expect http://localhost:8788
```

---

## 3. Replace the two quick-tunnel services with ONE named-tunnel service

### Step 1 — Inspect the existing units (model your new one on them)

```bash
systemctl --user cat bbtun-web bbtun-ws
ls ~/.config/systemd/user/
```

You'll see they're simple `cloudflared tunnel --url …` services. Note their
`[Service]` block (Restart=, RestartSec=, Environment=, etc.) and **mirror those
settings** so the new service behaves identically — just swap the command.

### Step 2 — Create the new unit

Write **`~/.config/systemd/user/bbtv-tunnel.service`**:

```ini
[Unit]
Description=BBTV named Cloudflare tunnel (bbtv.seconds0.com → :8788 page, /ws → :8787)
# Order after the backends if they're also user units; harmless if not present.
After=network-online.target bbstream.service bbweb.service
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/cloudflared --no-autoupdate tunnel run bbtv
Restart=always
RestartSec=5
# cloudflared reads ~/.cloudflared/config.yml by default (config-dir default is
# $HOME/.cloudflared). If you'd rather be explicit, use instead:
#   ExecStart=/usr/local/bin/cloudflared --no-autoupdate --config /home/rache/.cloudflared/config.yml tunnel run bbtv

[Install]
WantedBy=default.target
```

`tunnel run bbtv` finds the tunnel by name, reads `config.yml` for ingress, and
uses the credentials file referenced therein — no token needed, fully unattended.

### Step 3 — Enable the new service, disable (don't delete) the old ones

```bash
systemctl --user daemon-reload
systemctl --user enable --now bbtv-tunnel.service
systemctl --user status bbtv-tunnel.service          # expect active (running)
journalctl --user -u bbtv-tunnel -n 40 --no-pager     # expect "Registered tunnel connection" x4

# Stop + disable the ephemeral quick tunnels, but KEEP the unit files for rollback (§7):
systemctl --user disable --now bbtun-web.service bbtun-ws.service
systemctl --user status bbtun-web bbtun-ws            # expect inactive (dead), disabled
```

### Step 4 — Linger (already on, just confirm)

Linger lets these user services run with no logged-in session and start at boot.
It's already enabled, but confirm:

```bash
loginctl show-user rache | grep -i linger             # expect Linger=yes
# If somehow 'no':  sudo loginctl enable-linger rache
```

---

## 4. Patch the page's default WebSocket URL

**This is the only file in the repo you should touch.**

The page reads its socket URL here, in **`stream/web/app.js`** (served by `bbweb`
from the rig — the live copy is at `~/bloodbowl-rl/stream/web/app.js` on the rig):

```js
const PARAMS = new URLSearchParams(location.search);
const WS_URL = PARAMS.get('ws') || 'ws://localhost:8787/ws';
```

The override order is: explicit `?ws=` param wins; otherwise the hard-coded
default. We want the **default**, when the page is served from
`bbtv.seconds0.com`, to be `wss://bbtv.seconds0.com/ws` — and because we chose the
single-hostname design (§1), the cleanest, most robust default is **relative to
wherever the page is actually served from**:

> `wss://<the host that served this page>/ws`

That way the page is correct on `bbtv.seconds0.com`, on any future hostname, and
still works on `localhost` dev. Replace the `WS_URL` line with:

```js
const PARAMS = new URLSearchParams(location.search);
// Default: same-origin websocket at /ws (wss on https pages, ws on http/localhost).
// Single-hostname tunnel design routes /ws → :8787 and everything else → :8788,
// so the socket lives at the same host that served the page. ?ws= and
// window.BB_WS_URL still override for dev/other hosts.
const WS_SCHEME = location.protocol === 'https:' ? 'wss:' : 'ws:';
const WS_URL = PARAMS.get('ws') || window.BB_WS_URL ||
  (WS_SCHEME + '//' + location.host + '/ws');
```

Why same-origin/relative beats hard-coding `wss://bbtv.seconds0.com/ws`:
- An https page (served over the tunnel) automatically gets `wss:`; a `localhost`
  dev page over http gets `ws:` — no mixed-content error either way.
- No hostname baked into JS to drift if the subdomain ever changes.
- `?ws=` and `window.BB_WS_URL` still override, so dev workflows and the mock
  server (`ws://localhost:8787/ws`) are unaffected.

After editing on the rig, the change is live immediately (it's a static file
server; just hard-refresh). No build step. If you edited a copy elsewhere, make
sure the **rig's** `~/bloodbowl-rl/stream/web/app.js` is the one that changed,
since `bbweb` serves from there.

> Do not change anything else in `app.js` or anywhere else in `~/bloodbowl-rl`.

---

## 5. Cloudflare dashboard settings that matter

For the `seconds0.com` zone (most are defaults — just verify):

- **WebSockets: ON.** Network → WebSockets. On by default on all plans; confirm
  it's enabled or the WSS upgrade will fail.
- **SSL/TLS mode: Full is fine; Flexible also works.** The tunnel **terminates TLS
  at the Cloudflare edge** and connects to the origin over the tunnel (not over
  the public internet to an origin cert), so the edge↔origin leg is the encrypted
  tunnel regardless of this setting. **Full** is the clean choice; do **not** use
  *Full (strict)* expecting a public origin cert — there isn't one, the tunnel is
  the transport. Leave the zone on whatever it's already set to unless it's
  causing errors; don't flip it gratuitously.
- **Caching: no cache rule needed for `/ws`.** WebSocket traffic isn't cached.
  The static page/art can use default caching; if you see a stale page after an
  `app.js` edit, that's browser cache — hard-refresh — not an edge rule you need
  to add. Do not add a cache-bypass rule unless a real staleness problem appears.
- **Proxy (orange cloud): ON** for the `bbtv` record (already set by
  `route dns`). The tunnel requires proxied mode.

---

## 6. Verification checklist

Run these after §2–§5. (If the zone is pre-migration, the public-hostname checks
are blocked until cutover — run them then; the on-rig checks work now.)

**A. Tunnel is up (on the rig):**
```bash
systemctl --user is-active bbtv-tunnel        # active
cloudflared tunnel info bbtv                   # shows 4 active edge connections
journalctl --user -u bbtv-tunnel -n 20 --no-pager
```

**B. Page loads over the new hostname (from anywhere):**
```bash
curl -sS -I https://bbtv.seconds0.com/         # expect HTTP/2 200, served via cloudflare
curl -sS https://bbtv.seconds0.com/ | grep -i '<title>\|app.js'   # the BBTV page HTML
```

**C. WebSocket smoke — expect hello → snapshot → delta JSON:**
Using `websocat` (install locally if needed; or use the JS snippet below):
```bash
websocat -t wss://bbtv.seconds0.com/ws | head -c 1200
# Expect JSON frames: first {"v":1,"t":"hello",...}, then {"t":"snapshot",...},
# then a stream of {"t":"delta",...}. Heartbeat {"t":"ping"} every ~15s.
```
Browser-console equivalent (paste on https://bbtv.seconds0.com/):
```js
const w = new WebSocket('wss://bbtv.seconds0.com/ws');
w.onmessage = e => console.log(e.data.slice(0,200));
// Expect a 'hello' frame, then 'snapshot', then 'delta' frames flowing.
```
Also just **open `https://bbtv.seconds0.com/` in a browser** and confirm the
footer connection indicator shows **live** and players start moving — that
exercises the patched default WS URL end-to-end (no `?ws=` param).

**D. Reboot-survival (the whole point):**
```bash
# On the rig:
sudo reboot
# wait ~1–2 min, reconnect:
ssh rache@100.97.209.46 'systemctl --user is-active bbtv-tunnel bbstream bbweb'
# all three: active   (linger + WantedBy=default.target bring them back unattended)
```
Then re-run B and C and confirm `bbtv.seconds0.com` is live **without anyone
logging in** — that proves linger + the enabled user service survive reboot, and
the hostname is stable (unlike the old quick tunnels).

---

## 7. Rollback

The old quick-tunnel units still exist (you only *disabled* them, didn't delete).
If the named tunnel misbehaves, fall back in seconds:

```bash
# On the rig:
systemctl --user disable --now bbtv-tunnel.service        # stop the named tunnel
systemctl --user enable --now bbtun-web.service bbtun-ws.service   # bring quick tunnels back
journalctl --user -u bbtun-web -u bbtun-ws -n 30 --no-pager
```
Then read the new random `*.trycloudflare.com` hostnames from the logs and hand
them to whoever sets the page's `?ws=` (the quick-tunnel world is exactly where
you started). The named tunnel's `config.yml`, credentials file, and unit file
remain on disk, so you can re-enable it later with
`systemctl --user enable --now bbtv-tunnel.service` once the issue is fixed.

To fully remove the named tunnel (only if abandoning it): `systemctl --user
disable --now bbtv-tunnel`, `rm ~/.config/systemd/user/bbtv-tunnel.service`,
`cloudflared tunnel delete bbtv`, and delete the `bbtv` DNS record.

---

## 8. Constraints — read before you touch anything

- **Do NOT touch the `bbstream` or `bbweb` services**, and do **NOT** modify
  anything in `~/bloodbowl-rl` **except** the single `WS_URL` default in
  `stream/web/app.js` (§4). The game server and static server are verified working
  and out of scope.
- **Do NOT install anything system-wide** beyond the cloudflared **config** files
  you create (`~/.cloudflared/cert.pem`, `~/.cloudflared/<UUID>.json`,
  `~/.cloudflared/config.yml`) and the **user** systemd unit
  (`~/.config/systemd/user/bbtv-tunnel.service`). cloudflared itself is already
  installed — do not upgrade or reinstall it; do not apt-install packages; do not
  add system (`/etc/systemd/system/`) units.
- **All changes happen on the rig, as user `rache`, over the tailnet address
  `100.97.209.46`.** No other host, no root-owned system services.
- The `cloudflared tunnel login` browser URL **must be handed to Alex** — you
  can't complete that step yourself (§2 step 1). Surface it clearly and wait.
- If you hit a Cloudflare quota/limit or any blocker you'd resolve by **deleting
  an existing Cloudflare resource you did not create in this task** (a tunnel, a
  DNS record, a zone), **STOP and return the problem as a blocker — do not free up
  space yourself.**

---

## Appendix — quick fact sheet

| thing | value |
|-------|-------|
| Rig SSH | `ssh rache@100.97.209.46` (tailnet only, passwordless sudo) |
| cloudflared | `/usr/local/bin/cloudflared` v2026.6.0 (pre-installed) |
| Game server (WSS) | `localhost:8787`, path `/ws` (service `bbstream`) |
| Static page + art | `localhost:8788` (service `bbweb`) |
| Quick tunnels to replace | user services `bbtun-web`, `bbtun-ws` |
| New hostname | `bbtv.seconds0.com` (single, path-routed) |
| New tunnel | `bbtv` (named); creds `~/.cloudflared/<UUID>.json`; account cert `~/.cloudflared/cert.pem` |
| New config | `~/.cloudflared/config.yml` (ingress: `^/ws`→:8787, default→:8788) |
| New service | `~/.config/systemd/user/bbtv-tunnel.service` (`cloudflared tunnel run bbtv`) |
| Page file to patch | `stream/web/app.js` (rig: `~/bloodbowl-rl/stream/web/app.js`), `WS_URL` default → same-origin `/ws` |
| Linger | `loginctl enable-linger rache` (already on) |

**Sources** (cloudflared ingress / path-matching / websocket, verified June 2026):
- [Cloudflare Tunnel — Configuration file (ingress rules, path matching)](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/)
- [Many services, one cloudflared (Cloudflare blog)](https://blog.cloudflare.com/many-services-one-cloudflared/)
- [cloudflared ingress package (Go regexp path matching)](https://pkg.go.dev/github.com/cloudflare/cloudflared/ingress)
