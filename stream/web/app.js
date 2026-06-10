/* Blood Bowl Live — canvas renderer for the bbstream WebSocket protocol (proto 1).
 * Contract: docs/stream-protocol.md. Vanilla JS, no build step.
 * Sprites: FFB iconset sheets served under hello.sprite_base — 4 columns
 * [home, home-active, away, away-active], square cells (w/4), rows = cosmetic
 * variants. Circle fallback always available. */
'use strict';

// ---------------------------------------------------------------- config
const PARAMS = new URLSearchParams(location.search);
const WS_URL = PARAMS.get('ws') || 'ws://localhost:8787/ws';
const COLS = 26, ROWS = 15, CELL = 36;
const TWEEN_MS = 250;        // move animation
const PROBS_MS = 700;        // "AI mind" card lifetime
const ARC_MS = 650;          // pass arc flash
const DEFAULT_HOME = '#8b1a1a', DEFAULT_AWAY = '#1a4d8b';
const LOG_CAP = 50;          // action log entries
const DICE_CAP = 6;          // dice & odds cards

// ---------------------------------------------------------------- state
const S = {
  conn: 'connecting', connDetail: '',
  matchId: '—',
  home: { name: 'Home', color: DEFAULT_HOME },
  away: { name: 'Away', color: DEFAULT_AWAY },
  players: new Map(),                 // slot -> player object
  ball: { x: -1, y: -1, state: 'off_pitch', carrier: null },
  score: [0, 0], half: 1, turn: [0, 0], active: 0,
  winProb: 0.5, winProbShown: 0.5,
  lastSeq: -1, resyncPending: false,
  spriteBase: '',                     // hello.sprite_base; '' = circles only
  actorSlot: null,                    // current actor (active sprite column)
};

// transient animation state
const tweens = new Map();             // slot -> {fx,fy,t0}
let probsCard = null;                 // {slot,lines,until}
let passArc = null;                   // {x0,y0,x1,y1,until}
const deltaTimes = [];                // arrival timestamps for dec/s

// ---------------------------------------------------------------- dom
const $ = (id) => document.getElementById(id);
const canvas = $('pitch'), ctx = canvas.getContext('2d');
const dpr = window.devicePixelRatio || 1;
const W = COLS * CELL, H = ROWS * CELL;
canvas.width = W * dpr;
canvas.height = H * dpr;
canvas.style.width = W + 'px';
ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

// ---------------------------------------------------------------- sprites
const spriteCache = new Map();        // icon -> {img, ready}
let pitchImg = null;                  // loaded sprite_base + 'pitch.png'

function loadPitchArt() {
  if (!S.spriteBase || pitchImg) return;
  const img = new Image();
  img.onload = () => { pitchImg = img; };
  img.src = S.spriteBase + 'pitch.png';
}

/* Lazy per-icon Image cache. Returns the Image only once loaded; callers fall
 * back to circles until then. icon is a path under sprite_base
 * ("iconsets/woodelf_lineman.png"); bare legacy ids map to icons/<id>.png. */
function getSprite(icon) {
  if (!icon || !S.spriteBase) return null;
  let e = spriteCache.get(icon);
  if (!e) {
    e = { img: new Image(), ready: false };
    e.img.onload = () => { e.ready = true; };
    e.img.src = S.spriteBase + (icon.indexOf('.') >= 0 ? icon : 'icons/' + icon + '.png');
    spriteCache.set(icon, e);
  }
  return e.ready ? e.img : null;
}

// ---------------------------------------------------------------- websocket
let ws = null, backoff = 1000;

function connect() {
  setConn('connecting', '');
  try { ws = new WebSocket(WS_URL); } catch (e) { return scheduleReconnect(); }
  ws.onopen = () => { backoff = 1000; setConn('live', ''); };
  ws.onmessage = (ev) => {
    let msg; try { msg = JSON.parse(ev.data); } catch (e) { return; }
    handleMessage(msg);
  };
  ws.onclose = () => scheduleReconnect();
  ws.onerror = () => { try { ws.close(); } catch (e) {} };
}

function scheduleReconnect() {
  setConn('reconnecting', ' (retry ' + (backoff / 1000) + 's)');
  setTimeout(connect, backoff);
  backoff = Math.min(backoff * 2, 30000);
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

// ---------------------------------------------------------------- messages
function handleMessage(msg) {
  if (msg.t === 'ping') { send({ t: 'pong' }); S.lastSeq = msg.seq; return; }
  if (typeof msg.seq === 'number') {
    if (msg.t === 'delta' && S.lastSeq >= 0 && msg.seq > S.lastSeq + 1 && !S.resyncPending) {
      S.resyncPending = true;          // gap: ask for a fresh snapshot
      send({ t: 'resync' });
    }
    S.lastSeq = msg.seq;
  }
  switch (msg.t) {
    case 'hello':       onHello(msg); break;
    case 'match_start': onMatchStart(msg); break;
    case 'snapshot':    onSnapshot(msg); break;
    case 'delta':       onDelta(msg); break;
    case 'match_end':   onMatchEnd(msg); break;
  }
}

function onHello(msg) {
  S.matchId = msg.match_id || S.matchId;
  if (msg.sprite_base != null) S.spriteBase = msg.sprite_base;
  loadPitchArt();
  updateFooter();
}

function onMatchStart(msg) {
  S.matchId = msg.match_id || S.matchId;
  if (msg.home) S.home = { name: msg.home.name || 'Home', color: msg.home.color || DEFAULT_HOME, roster: msg.home.roster };
  if (msg.away) S.away = { name: msg.away.name || 'Away', color: msg.away.color || DEFAULT_AWAY, roster: msg.away.roster };
  S.score = [0, 0]; S.half = 1; S.turn = [0, 0]; S.active = 0;
  S.winProb = 0.5;
  S.ball = { x: -1, y: -1, state: 'off_pitch', carrier: null };
  S.actorSlot = null;
  rebuildPlayers(msg.players || []);
  tweens.clear(); probsCard = null; passArc = null;
  addFeedLine({ kind: 'sys', text: '— New match: ' + S.home.name + ' vs ' + S.away.name + ' —' });
  showBanner(S.home.name + '  vs  ' + S.away.name, 'b-info', 2500);
  updateHud(); renderDugouts(); updateFooter();
}

function onSnapshot(msg) {
  S.resyncPending = false;
  S.matchId = msg.match_id || S.matchId;
  if (msg.score) S.score = msg.score;
  if (msg.half != null) S.half = msg.half;
  if (msg.turn) S.turn = msg.turn;
  if (msg.active_team != null) S.active = msg.active_team;
  if (msg.ball) S.ball = msg.ball;
  if (msg.win_prob != null) S.winProb = msg.win_prob;
  rebuildPlayers(msg.players || []);
  tweens.clear();                      // snapshot = authoritative, no stale tweens
  updateHud(); renderDugouts(); updateFooter();
}

function onDelta(msg) {
  const now = performance.now();
  deltaTimes.push(now);

  if (Array.isArray(msg.moves)) {
    for (const mv of msg.moves) {
      const p = S.players.get(mv.slot);
      if (!p) continue;
      if (mv.x != null && mv.y != null && (mv.x !== p.x || mv.y !== p.y)) {
        if (onPitch(p) && mv.x >= 0) {
          const d = displayPos(p, now);  // snap any in-flight tween to its current spot
          tweens.set(mv.slot, { fx: d.x, fy: d.y, t0: now });
        } else {
          tweens.delete(mv.slot);
        }
        p.x = mv.x; p.y = mv.y;
      }
      if (mv.stance) p.stance = mv.stance;
    }
    renderDugouts();
  }
  if (msg.ball) S.ball = msg.ball;
  if (msg.score) S.score = msg.score;
  if (msg.turn) S.turn = msg.turn;
  if (msg.active_team != null) S.active = msg.active_team;
  if (msg.win_prob != null) S.winProb = msg.win_prob;

  if (msg.action) {
    const ty = String(msg.action.type || '').toUpperCase();
    if (ty && ty !== 'NONE' && msg.action.actor != null) S.actorSlot = msg.action.actor;
    addLogAction(msg.action);
    if (Array.isArray(msg.action.probs) && msg.action.probs.length) {
      const actor = S.players.get(msg.action.actor);
      if (actor && onPitch(actor)) {
        probsCard = {
          slot: msg.action.actor,
          lines: msg.action.probs.slice(0, 3).map(([lbl, p]) => [String(lbl), p]),
          until: now + PROBS_MS,
        };
      }
    }
    if ((ty === 'PASS' || ty === 'HANDOFF' || ty === 'HAND_OFF' || ty === 'THROW') &&
        Array.isArray(msg.action.target)) {
      const actor = S.players.get(msg.action.actor);
      if (actor) {
        const from = displayPos(actor, now);
        passArc = { x0: from.x, y0: from.y, x1: msg.action.target[0], y1: msg.action.target[1], until: now + ARC_MS };
      }
    }
  }

  // ---- dice & odds panel ----
  let card = null;
  if (msg.ev) {                        // block (or blitz) declaration: open an odds card
    const label = msg.action && msg.action.type ? String(msg.action.type).toUpperCase() : 'BLOCK';
    card = newDiceCard(label, msg.ev);
  }
  if (msg.dice) {
    if (card) appendDice(card, msg.dice);
    else if (msg.dice.kind === 'block' && diceCards[0] && diceCards[0].open) appendDice(diceCards[0], msg.dice);
    else { card = newDiceCard(String(msg.dice.label || msg.dice.kind || 'ROLL').toUpperCase(), null); appendDice(card, msg.dice); }
  }

  if (Array.isArray(msg.feed)) {
    for (const f of msg.feed) {
      addFeedLine(f);
      if (f.kind === 'td') {
        const side = f.side === 'away' ? S.away.name : S.home.name;
        showBanner('TOUCHDOWN — ' + side + '!', 'b-td', 2500);
      } else if (f.kind === 'turnover') {
        showBanner('TURNOVER', 'b-turnover', 1800);
      } else if (f.kind === 'cas' && f.first_blood) {
        showBanner('☠ FIRST BLOOD ☠\n' + (f.text || ''), 'b-memorial', 4000);
      }
      // resolve the newest open odds card
      if (f.kind === 'injury' || f.kind === 'ko' || f.kind === 'cas') appendOutcome('→ Defender down!', 'out-down');
      else if (f.kind === 'turnover') appendOutcome('→ TURNOVER!', 'out-turnover');
    }
  }
  // a block result with no injury feed still resolves the card
  if (msg.dice && msg.dice.kind === 'block' && msg.dice.result && diceCards[0] && diceCards[0].open) {
    const r = msg.dice.result;
    if (r === 'Defender Down') appendOutcome('→ Defender down!', 'out-down');
    else if (r === 'Both Down') appendOutcome('→ Both down!', 'out-down');
    else appendOutcome('→ ' + r, 'out-push');
  }

  updateHud();
}

function onMatchEnd(msg) {
  if (msg.score) S.score = msg.score;
  S.actorSlot = null;
  const w = msg.winner === 'home' ? S.home.name : msg.winner === 'away' ? S.away.name : 'Draw';
  let txt = 'FULL TIME — ' + S.score[0] + '–' + S.score[1] + (msg.winner === 'draw' ? '' : ' — ' + w + ' win');
  showBanner(txt, 'b-info', 5000);
  addFeedLine({ kind: 'sys', text: 'Full time: ' + S.home.name + ' ' + S.score[0] + ' – ' + S.score[1] + ' ' + S.away.name });
  if (msg.mvp) addFeedLine({ kind: 'sys', text: 'MVP: ' + (msg.mvp.name || ('#' + msg.mvp.slot)) + ' (' + (msg.mvp.tds || 0) + ' TD)' });
  updateHud();
}

function rebuildPlayers(list) {
  S.players.clear();
  for (const p of list) {
    S.players.set(p.slot, {
      slot: p.slot,
      side: p.side || (p.slot < 16 ? 'home' : 'away'),
      x: p.x, y: p.y,
      stance: p.stance || 'standing',
      num: p.num != null ? p.num : (p.slot % 16) + 1,
      position: p.position || '', icon: p.icon || '',
    });
  }
}

const onPitch = (p) => p.x >= 0 && p.y >= 0;

// ---------------------------------------------------------------- pitch drawing
function cellCenter(x, y) { return [x * CELL + CELL / 2, y * CELL + CELL / 2]; }

function displayPos(p, now) {
  const tw = tweens.get(p.slot);
  if (tw) {
    const t = (now - tw.t0) / TWEEN_MS;
    if (t >= 1) { tweens.delete(p.slot); return { x: p.x, y: p.y }; }
    const e = t * (2 - t);             // ease-out
    return { x: tw.fx + (p.x - tw.fx) * e, y: tw.fy + (p.y - tw.fy) * e };
  }
  return { x: p.x, y: p.y };
}

function drawPitch() {
  if (pitchImg) {                      // FFB pitch art, stretched to the grid
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(pitchImg, 0, 0, W, H);
    return;
  }
  // painted fallback
  ctx.fillStyle = '#2c5e34';
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = 'rgba(0,0,0,0.05)';  // subtle mowing stripes
  for (let x = 0; x < COLS; x += 2) ctx.fillRect(x * CELL, 0, CELL, H);
  // endzones
  ctx.fillStyle = 'rgba(255,255,255,0.10)';
  ctx.fillRect(0, 0, CELL, H);
  ctx.fillRect((COLS - 1) * CELL, 0, CELL, H);
  // grid
  ctx.strokeStyle = 'rgba(255,255,255,0.10)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let x = 0; x <= COLS; x++) { ctx.moveTo(x * CELL + .5, 0); ctx.lineTo(x * CELL + .5, H); }
  for (let y = 0; y <= ROWS; y++) { ctx.moveTo(0, y * CELL + .5); ctx.lineTo(W, y * CELL + .5); }
  ctx.stroke();
  // halfway line + wide-zone lines
  ctx.strokeStyle = 'rgba(255,255,255,0.30)';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(13 * CELL, 0); ctx.lineTo(13 * CELL, H);
  ctx.moveTo(0, 4 * CELL); ctx.lineTo(W, 4 * CELL);
  ctx.moveTo(0, 11 * CELL); ctx.lineTo(W, 11 * CELL);
  ctx.stroke();
}

let vignetteGrad = null;
function drawVignette() {
  if (!vignetteGrad) {
    vignetteGrad = ctx.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.55, W / 2, H / 2, Math.max(W, H) * 0.70);
    vignetteGrad.addColorStop(0, 'rgba(0,0,0,0)');
    vignetteGrad.addColorStop(1, 'rgba(0,0,0,0.40)');
  }
  ctx.fillStyle = vignetteGrad;
  ctx.fillRect(0, 0, W, H);
}

/* Single player draw entry point. FFB sheet slicing: 4 columns
 * [home, home-active, away, away-active], cell = imageWidth/4, row =
 * slot % (imageHeight/cell) for cosmetic variety. Circle fallback when the
 * sprite isn't available (yet). */
function drawPlayer(p, px, py, isCarrier) {
  const color = p.side === 'home' ? S.home.color : S.away.color;
  const r = CELL * 0.38;
  const img = getSprite(p.icon);
  ctx.save();
  ctx.translate(px, py);
  if (img) {
    const cw = Math.max(1, Math.floor(img.width / 4));
    const rows = Math.max(1, Math.floor(img.height / cw));
    const col = (p.side === 'home' ? 0 : 2) + (S.actorSlot === p.slot ? 1 : 0);
    const row = p.slot % rows;
    const size = CELL * 0.95;
    ctx.save();
    if (p.stance === 'prone') ctx.rotate(Math.PI / 2);
    else if (p.stance === 'stunned') ctx.rotate(Math.PI);
    ctx.imageSmoothingEnabled = false;  // crisp pixel art
    ctx.drawImage(img, col * cw, row * cw, cw, cw, -size / 2, -size / 2, size, size);
    ctx.restore();
  } else {
    if (p.stance === 'prone' || p.stance === 'stunned') ctx.globalAlpha = 0.55;
    ctx.beginPath();
    ctx.arc(0, 0, r, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = 'rgba(0,0,0,0.55)';
    ctx.stroke();
    if (p.stance === 'stunned') {       // X overlay
      ctx.globalAlpha = 0.9;
      ctx.strokeStyle = '#ffdddd';
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      ctx.moveTo(-r * .7, -r * .7); ctx.lineTo(r * .7, r * .7);
      ctx.moveTo(r * .7, -r * .7); ctx.lineTo(-r * .7, r * .7);
      ctx.stroke();
    }
    ctx.fillStyle = '#fff';
    ctx.font = '700 ' + Math.round(CELL * 0.36) + 'px system-ui, sans-serif';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.save();
    if (p.stance === 'prone' || p.stance === 'stunned') ctx.rotate(Math.PI / 2);
    ctx.fillText(String(p.num), 0, 1);
    ctx.restore();
    ctx.globalAlpha = 1;
  }
  if (isCarrier) {                      // gold ring on the ball carrier
    ctx.beginPath();
    ctx.arc(0, 0, r + 2.5, 0, Math.PI * 2);
    ctx.lineWidth = 2.5;
    ctx.strokeStyle = '#e3b341';
    ctx.stroke();
  }
  if (img && p.stance === 'stunned') {  // small "seeing stars" marker
    ctx.fillStyle = '#e8c563';
    for (let i = -1; i <= 1; i++) {
      ctx.beginPath();
      ctx.arc(i * 5, -CELL * 0.46, 1.6, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  ctx.restore();
}

function drawBall() {
  const b = S.ball;
  if (!b || b.state === 'held' || b.state === 'off_pitch' || b.x < 0) return;
  const [px, py] = cellCenter(b.x, b.y);
  ctx.save();
  ctx.beginPath();
  ctx.arc(px, py - (b.state === 'in_air' ? 6 : 0), CELL * 0.16, 0, Math.PI * 2);
  ctx.fillStyle = '#8a5a2b';
  ctx.fill();
  ctx.strokeStyle = '#3d2812';
  ctx.lineWidth = 1.5;
  ctx.stroke();
  if (b.state === 'in_air') {
    ctx.setLineDash([3, 3]);
    ctx.strokeStyle = 'rgba(255,255,255,0.6)';
    ctx.beginPath();
    ctx.arc(px, py - 6, CELL * 0.3, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.restore();
}

function drawPassArc(now) {
  if (!passArc || now > passArc.until) { passArc = null; return; }
  const [x0, y0] = cellCenter(passArc.x0, passArc.y0);
  const [x1, y1] = cellCenter(passArc.x1, passArc.y1);
  const mx = (x0 + x1) / 2, my = Math.min(y0, y1) - CELL * 1.6;
  ctx.save();
  ctx.globalAlpha = Math.min(1, (passArc.until - now) / 250);
  ctx.setLineDash([6, 6]);
  ctx.strokeStyle = '#ffe9a8';
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  ctx.moveTo(x0, y0);
  ctx.quadraticCurveTo(mx, my, x1, y1);
  ctx.stroke();
  ctx.restore();
}

function drawProbsCard(now) {
  if (!probsCard || now > probsCard.until) { probsCard = null; return; }
  const actor = S.players.get(probsCard.slot);
  if (!actor || !onPitch(actor)) { probsCard = null; return; }
  const d = displayPos(actor, now);
  const [ax, ay] = cellCenter(d.x, d.y);
  const w = 150, lh = 15, h = probsCard.lines.length * lh + 10;
  let cx = ax + CELL * 0.7, cy = ay - h - 6;
  if (cx + w > W) cx = ax - w - CELL * 0.7;
  if (cy < 0) cy = ay + CELL * 0.7;
  ctx.save();
  ctx.globalAlpha = 0.85;
  ctx.fillStyle = '#10141a';
  ctx.strokeStyle = 'rgba(227,179,65,0.6)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.roundRect(cx, cy, w, h, 5);
  ctx.fill(); ctx.stroke();
  ctx.font = '11px system-ui, sans-serif';
  ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
  probsCard.lines.forEach(([lbl, p], i) => {
    ctx.fillStyle = i === 0 ? '#e3b341' : '#9aa6b5';
    ctx.fillText(lbl.slice(0, 18), cx + 8, cy + 5 + lh * i + lh / 2);
    ctx.textAlign = 'right';
    ctx.fillText(Math.round(p * 100) + '%', cx + w - 8, cy + 5 + lh * i + lh / 2);
    ctx.textAlign = 'left';
  });
  ctx.restore();
}

function render(now) {
  drawPitch();
  drawBall();
  // prone/stunned first so standing players draw on top
  const sorted = [...S.players.values()].filter(onPitch)
    .sort((a, b) => (a.stance === 'standing' ? 1 : 0) - (b.stance === 'standing' ? 1 : 0));
  for (const p of sorted) {
    const d = displayPos(p, now);
    const [px, py] = cellCenter(d.x, d.y);
    drawPlayer(p, px, py, S.ball.state === 'held' && S.ball.carrier === p.slot);
  }
  drawPassArc(now);
  drawProbsCard(now);
  drawVignette();
}

// ---------------------------------------------------------------- dom panels
function lighten(hex, f) {             // mix a #rrggbb toward white for dark-bg legibility
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
  if (!m) return '#ccc';
  const n = parseInt(m[1], 16);
  const ch = (v) => Math.round(v + (255 - v) * f);
  return 'rgb(' + ch((n >> 16) & 255) + ',' + ch((n >> 8) & 255) + ',' + ch(n & 255) + ')';
}

function pipsHtml(n) {
  let h = '';
  for (let i = 0; i < 8; i++) h += '<span class="pip' + (i < n ? ' on' : '') + '"></span>';
  return h;
}

function updateHud() {
  const nh = $('name-home'), na = $('name-away');
  nh.textContent = S.home.name;
  na.textContent = S.away.name;
  nh.style.color = lighten(S.home.color, 0.45);
  na.style.color = lighten(S.away.color, 0.45);
  nh.classList.toggle('active', S.active === 0);
  na.classList.toggle('active', S.active === 1);
  $('score').innerHTML = S.score[0] + ' &ndash; ' + S.score[1];
  $('half').textContent = S.half === 2 ? '2nd Half' : '1st Half';
  $('pips-home').innerHTML = pipsHtml(Math.min(8, S.turn[0]));
  $('pips-away').innerHTML = pipsHtml(Math.min(8, S.turn[1]));
}

function updateWinProb(dt) {
  S.winProbShown += (S.winProb - S.winProbShown) * Math.min(1, dt * 4);
  const pct = S.winProbShown * 100;
  const fill = $('winprob-home');
  fill.style.width = pct.toFixed(2) + '%';
  fill.style.background = S.home.color;
  $('winprob').style.background = S.away.color;
  const label = $('winprob-label');
  label.textContent = Math.round(pct) + '%';
  label.style.left = Math.max(7, Math.min(93, pct)) + '%';
}

const STANCE_GROUPS = [['ko', 'KO’d'], ['cas', 'Casualties'], ['sent_off', 'Sent off']];
function renderDugouts() {
  for (const side of ['home', 'away']) {
    const box = $('dugout-' + side).querySelector('.groups');
    const off = [...S.players.values()].filter(p => p.side === side && (!onPitch(p) || ['ko', 'cas', 'sent_off'].includes(p.stance)));
    const color = side === 'home' ? S.home.color : S.away.color;
    // ON PITCH roster first — who's in play right now (Alex, 2026-06-10)
    const inplay = [...S.players.values()]
      .filter(p => p.side === side && onPitch(p) && !['ko', 'cas', 'sent_off'].includes(p.stance))
      .sort((a, b) => a.num - b.num);
    let html = '';
    if (inplay.length) {
      html += '<div class="grp-title">On Pitch (' + inplay.length + ')</div>';
      for (const p of inplay) {
        const mark = (S.ball && S.ball.carrier === p.slot) ? ' <span class="ballmark">●</span>'
                   : (p.stance === 'prone' ? ' <span class="downmark">▾</span>'
                   : (p.stance === 'stunned' ? ' <span class="downmark">✶</span>' : ''));
        html += '<div class="chip onpitch"><span class="pnum" style="background:' + color + '">' + p.num + '</span><span>' + esc(p.position) + mark + '</span></div>';
      }
    }
    for (const [st, label] of STANCE_GROUPS) {
      const grp = off.filter(p => p.stance === st);
      if (!grp.length) continue;
      html += '<div class="grp-title">' + label + '</div>';
      for (const p of grp) {
        const color = side === 'home' ? S.home.color : S.away.color;
        html += '<div class="chip"><span class="pnum" style="background:' + color + '">' + p.num + '</span><span>' + esc(p.position) + '</span></div>';
      }
    }
    const misc = off.filter(p => !['ko', 'cas', 'sent_off'].includes(p.stance));
    if (misc.length) {
      html += '<div class="grp-title">Reserves</div>';
      for (const p of misc) {
        const color = side === 'home' ? S.home.color : S.away.color;
        html += '<div class="chip"><span class="pnum" style="background:' + color + '">' + p.num + '</span><span>' + esc(p.position) + '</span></div>';
      }
    }
    box.innerHTML = html || '<div class="empty">all on pitch</div>';
  }
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

// ---------------------------------------------------------------- action log
const KNOWN_KINDS = ['move', 'block', 'blitz', 'dodge', 'gfi', 'pickup', 'pass', 'handoff', 'td', 'turnover', 'injury', 'ko', 'cas', 'kickoff', 'sys'];

function pushLog(div) {
  const log = $('actionlog');
  log.prepend(div);
  while (log.childNodes.length > LOG_CAP) log.removeChild(log.lastChild);
}

function sideColor(side) {
  return side === 'away' ? S.away.color : side === 'home' ? S.home.color : '#777';
}

/* One line per decision: team chip + actor + verb + chosen-action confidence,
 * e.g. "Wardancer #3 — MOVE 87%". Skips NONE. */
function addLogAction(action) {
  const verb = String(action.type || '').toUpperCase();
  if (!verb || verb === 'NONE') return;
  const actor = S.players.get(action.actor);
  let conf = null;
  if (Array.isArray(action.probs) && action.probs.length && typeof action.probs[0][1] === 'number') {
    conf = Math.round(action.probs[0][1] * 100);
  }
  const div = document.createElement('div');
  div.className = 'log-entry';
  const who = actor ? ((actor.position ? actor.position + ' ' : '') + '#' + actor.num) : '';
  div.innerHTML =
    '<span class="chip" style="background:' + sideColor(actor && actor.side) + '"></span>' +
    (who ? '<span class="log-who">' + esc(who) + '</span><span class="log-dash">—</span>' : '') +
    '<span class="log-verb">' + esc(verb) + '</span>' +
    (conf != null ? '<span class="log-conf">' + conf + '%</span>' : '');
  pushLog(div);
}

function addFeedLine(f) {
  const div = document.createElement('div');
  const kind = KNOWN_KINDS.includes(f.kind) ? f.kind : 'move';
  div.className = 'log-entry fl-' + kind;
  const chip = (kind !== 'sys' && f.side)
    ? '<span class="chip" style="background:' + sideColor(f.side) + '"></span>' : '';
  div.innerHTML = chip + '<span class="log-text">' + esc(f.text || '') + '</span>';
  pushLog(div);
}

// ---------------------------------------------------------------- dice & odds
const diceCards = [];                  // newest first: {el, open}

function newDiceCard(title, ev) {
  const el = document.createElement('div');
  el.className = 'dcard';
  let html = '<div class="dcard-title">' + esc(title) + '</div>';
  if (ev) {
    html += oddsRow('P(def down)', ev.p_def_down, 'red');
    html += oddsRow('P(att down)', ev.p_att_down, 'gold');
    const extra = [];
    if (typeof ev.p_ball_out === 'number') extra.push(Math.round(ev.p_ball_out * 100) + '% ball out');
    if (typeof ev.p_turnover === 'number') extra.push(Math.round(ev.p_turnover * 100) + '% turnover');
    if (extra.length) html += '<div class="dcard-extra">' + esc(extra.join(' · ')) + '</div>';
  }
  el.innerHTML = html;
  $('dicepanel').prepend(el);
  const card = { el, open: true };
  diceCards.unshift(card);
  while (diceCards.length > DICE_CAP) diceCards.pop().el.remove();
  return card;
}

function oddsRow(label, p, tone) {
  if (typeof p !== 'number') return '';
  const pct = Math.round(p * 100);
  return '<div class="odds odds-' + tone + '"><span class="odds-label">' + esc(label) + '</span>' +
    '<span class="odds-bar"><i style="width:' + Math.max(0, Math.min(100, pct)) + '%"></i></span>' +
    '<span class="odds-pct">' + pct + '%</span></div>';
}

const DIE_FACES = ['⚀', '⚁', '⚂', '⚃', '⚄', '⚅'];
const face = (n) => (n >= 1 && n <= 6 ? DIE_FACES[n - 1] : String(n));

function diceText(d) {
  if (d.kind === 'block' && Array.isArray(d.rolls)) {
    let s = d.rolls.map(face).join(' ');
    if (d.result) s += '  ' + d.result;
    if (d.reroll_used) s += ' (reroll)';
    return s;
  }
  if (d.roll != null) {
    let s = (d.label || d.kind || 'Roll') + ': ' + d.roll + (d.target != null ? ' vs ' + d.target + '+' : '');
    if (d.ok != null) s += d.ok ? '  ✓' : '  ✗';
    return s;
  }
  return d.label || d.kind || 'dice';
}

function appendDice(card, d) {
  const div = document.createElement('div');
  div.className = 'dcard-dice';
  div.textContent = diceText(d);
  card.el.appendChild(div);
}

/* Outcome lines attach to the newest card only while it's still open. */
function appendOutcome(text, cls) {
  const card = diceCards[0];
  if (!card || !card.open) return;
  card.open = false;
  const div = document.createElement('div');
  div.className = 'dcard-outcome ' + cls;
  div.textContent = text;
  card.el.appendChild(div);
}

// ---------------------------------------------------------------- misc dom
let bannerTimer = null;
function showBanner(text, cls, ms) {
  const b = $('banner');
  b.className = cls;
  b.textContent = text;
  if (bannerTimer) clearTimeout(bannerTimer);
  bannerTimer = setTimeout(() => b.classList.add('hidden'), ms);
}

function setConn(state, detail) {
  S.conn = state; S.connDetail = detail;
  updateFooter();
}

function updateFooter() {
  $('f-match').textContent = 'match: ' + S.matchId;
  const c = $('f-conn');
  c.textContent = S.conn + S.connDetail;
  c.className = 'conn-' + S.conn;
}

function updateRate(now) {
  while (deltaTimes.length && deltaTimes[0] < now - 10000) deltaTimes.shift();
  $('f-rate').textContent = (deltaTimes.length / 10).toFixed(1) + ' dec/s';
}

// ---------------------------------------------------------------- main loop
let lastFrame = performance.now();
function frame(now) {
  const dt = Math.min(0.1, (now - lastFrame) / 1000);
  lastFrame = now;
  render(now);
  updateWinProb(dt);
  updateRate(now);
  requestAnimationFrame(frame);
}

updateHud();
renderDugouts();
updateFooter();
requestAnimationFrame(frame);
connect();
