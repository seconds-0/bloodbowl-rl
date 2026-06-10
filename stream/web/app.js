/* Blood Bowl Live — canvas renderer for the bbstream WebSocket protocol (proto 1).
 * Contract: docs/stream-protocol.md. Vanilla JS, no build step, no external assets. */
'use strict';

// ---------------------------------------------------------------- config
const PARAMS = new URLSearchParams(location.search);
const WS_URL = PARAMS.get('ws') || 'ws://localhost:8787/ws';
const COLS = 26, ROWS = 15, CELL = 36;
const TWEEN_MS = 250;        // move animation
const PROBS_MS = 700;        // "AI mind" card lifetime
const ARC_MS = 650;          // pass arc flash
const DEFAULT_HOME = '#8b1a1a', DEFAULT_AWAY = '#1a4d8b';

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
};

// transient animation state
const tweens = new Map();             // slot -> {fx,fy,t0}
let probsCard = null;                 // {px,py,lines,until}
let passArc = null;                   // {x0,y0,x1,y1,until}
let bannerUntil = 0;
const deltaTimes = [];                // arrival timestamps for dec/s

// ---------------------------------------------------------------- dom
const $ = (id) => document.getElementById(id);
const canvas = $('pitch'), ctx = canvas.getContext('2d');
const dpr = window.devicePixelRatio || 1;
canvas.width = COLS * CELL * dpr;
canvas.height = ROWS * CELL * dpr;
canvas.style.width = (COLS * CELL) + 'px';
ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

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
  updateFooter();
}

function onMatchStart(msg) {
  S.matchId = msg.match_id || S.matchId;
  if (msg.home) S.home = { name: msg.home.name || 'Home', color: msg.home.color || DEFAULT_HOME, roster: msg.home.roster };
  if (msg.away) S.away = { name: msg.away.name || 'Away', color: msg.away.color || DEFAULT_AWAY, roster: msg.away.roster };
  S.score = [0, 0]; S.half = 1; S.turn = [0, 0]; S.active = 0;
  S.winProb = 0.5;
  S.ball = { x: -1, y: -1, state: 'off_pitch', carrier: null };
  rebuildPlayers(msg.players || []);
  tweens.clear(); probsCard = null; passArc = null;
  addTickerLine({ kind: 'sys', text: '— New match: ' + S.home.name + ' vs ' + S.away.name + ' —' });
  showBanner(S.home.name + '  vs  ' + S.away.name, 'b-info', 2500);
  hideEvCard();
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
    const ty = String(msg.action.type || '').toUpperCase();
    if ((ty === 'PASS' || ty === 'HANDOFF' || ty === 'HAND_OFF' || ty === 'THROW') &&
        Array.isArray(msg.action.target)) {
      const actor = S.players.get(msg.action.actor);
      if (actor) {
        const from = displayPos(actor, now);
        passArc = { x0: from.x, y0: from.y, x1: msg.action.target[0], y1: msg.action.target[1], until: now + ARC_MS };
      }
    }
  }

  if (msg.ev) showEvCard(msg.ev);
  else hideEvCard();

  if (Array.isArray(msg.feed)) {
    for (const f of msg.feed) {
      addTickerLine(f);
      if (f.kind === 'td') {
        const side = f.side === 'away' ? S.away.name : S.home.name;
        showBanner('TOUCHDOWN — ' + side + '!', 'b-td', 2500);
      } else if (f.kind === 'turnover') {
        showBanner('TURNOVER', 'b-turnover', 1800);
      } else if (f.kind === 'cas' && f.first_blood) {
        showBanner('☠ FIRST BLOOD ☠\n' + (f.text || ''), 'b-memorial', 4000);
      }
    }
  }
  updateHud();
}

function onMatchEnd(msg) {
  if (msg.score) S.score = msg.score;
  const w = msg.winner === 'home' ? S.home.name : msg.winner === 'away' ? S.away.name : 'Draw';
  let txt = 'FULL TIME — ' + S.score[0] + '–' + S.score[1] + (msg.winner === 'draw' ? '' : ' — ' + w + ' win');
  showBanner(txt, 'b-info', 5000);
  addTickerLine({ kind: 'sys', text: 'Full time: ' + S.home.name + ' ' + S.score[0] + ' – ' + S.score[1] + ' ' + S.away.name });
  if (msg.mvp) addTickerLine({ kind: 'sys', text: 'MVP: ' + (msg.mvp.name || ('#' + msg.mvp.slot)) + ' (' + (msg.mvp.tds || 0) + ' TD)' });
  hideEvCard();
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
  ctx.fillStyle = '#2c5e34';
  ctx.fillRect(0, 0, COLS * CELL, ROWS * CELL);
  // subtle mowing stripes
  ctx.fillStyle = 'rgba(0,0,0,0.05)';
  for (let x = 0; x < COLS; x += 2) ctx.fillRect(x * CELL, 0, CELL, ROWS * CELL);
  // endzones
  ctx.fillStyle = 'rgba(255,255,255,0.10)';
  ctx.fillRect(0, 0, CELL, ROWS * CELL);
  ctx.fillRect((COLS - 1) * CELL, 0, CELL, ROWS * CELL);
  // grid
  ctx.strokeStyle = 'rgba(255,255,255,0.10)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let x = 0; x <= COLS; x++) { ctx.moveTo(x * CELL + .5, 0); ctx.lineTo(x * CELL + .5, ROWS * CELL); }
  for (let y = 0; y <= ROWS; y++) { ctx.moveTo(0, y * CELL + .5); ctx.lineTo(COLS * CELL, y * CELL + .5); }
  ctx.stroke();
  // halfway line + wide-zone lines
  ctx.strokeStyle = 'rgba(255,255,255,0.30)';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(13 * CELL, 0); ctx.lineTo(13 * CELL, ROWS * CELL);
  ctx.moveTo(0, 4 * CELL); ctx.lineTo(COLS * CELL, 4 * CELL);
  ctx.moveTo(0, 11 * CELL); ctx.lineTo(COLS * CELL, 11 * CELL);
  ctx.stroke();
}

/* Single player draw entry point.
 * Sprite-atlas hook: replace the body of this function with an atlas blit keyed
 * on p.icon (sprite_base + 'icons/' + p.icon + '.png'); keep the signature. */
function drawPlayer(p, px, py, isCarrier) {
  const color = p.side === 'home' ? S.home.color : S.away.color;
  const r = CELL * 0.38;
  ctx.save();
  ctx.translate(px, py);
  if (p.stance === 'prone' || p.stance === 'stunned') ctx.globalAlpha = 0.5;
  ctx.beginPath();
  ctx.arc(0, 0, r, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = 'rgba(0,0,0,0.55)';
  ctx.stroke();
  if (isCarrier) {                      // gold ring on the ball carrier
    ctx.beginPath();
    ctx.arc(0, 0, r + 2.5, 0, Math.PI * 2);
    ctx.lineWidth = 2.5;
    ctx.strokeStyle = '#e3b341';
    ctx.stroke();
  }
  if (p.stance === 'stunned') {         // X overlay (drawn unrotated)
    ctx.globalAlpha = 0.9;
    ctx.strokeStyle = '#ffdddd';
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    ctx.moveTo(-r * .7, -r * .7); ctx.lineTo(r * .7, r * .7);
    ctx.moveTo(r * .7, -r * .7); ctx.lineTo(-r * .7, r * .7);
    ctx.stroke();
  }
  // number (rotated when prone/stunned)
  ctx.fillStyle = '#fff';
  ctx.font = '700 ' + Math.round(CELL * 0.36) + 'px system-ui, sans-serif';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  if (p.stance === 'prone' || p.stance === 'stunned') ctx.rotate(Math.PI / 2);
  ctx.fillText(String(p.num), 0, 1);
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
  if (cx + w > COLS * CELL) cx = ax - w - CELL * 0.7;
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
}

// ---------------------------------------------------------------- dom panels
function updateHud() {
  $('name-home').textContent = S.home.name;
  $('name-away').textContent = S.away.name;
  $('swatch-home').style.background = S.home.color;
  $('swatch-away').style.background = S.away.color;
  $('score').innerHTML = S.score[0] + ' &ndash; ' + S.score[1];
  $('half').textContent = 'Half ' + S.half;
  $('turn-home').textContent = 'T' + S.turn[0];
  $('turn-away').textContent = 'T' + S.turn[1];
  $('arrow-home').classList.toggle('on', S.active === 0);
  $('arrow-away').classList.toggle('on', S.active === 1);
}

function updateWinProb(dt) {
  S.winProbShown += (S.winProb - S.winProbShown) * Math.min(1, dt * 4);
  const pct = S.winProbShown * 100;
  $('winprob-fill').style.width = pct.toFixed(2) + '%';
  $('winprob-label').textContent = Math.round(pct) + '%';
  $('winprob-fill').style.background = S.home.color;
  $('winprob').style.background = S.away.color;
}

const STANCE_GROUPS = [['ko', 'KO’d'], ['cas', 'Casualties'], ['sent_off', 'Sent off']];
function renderDugouts() {
  for (const side of ['home', 'away']) {
    const box = $('dugout-' + side).querySelector('.groups');
    const off = [...S.players.values()].filter(p => p.side === side && (!onPitch(p) || ['ko', 'cas', 'sent_off'].includes(p.stance)));
    let html = '';
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

const KNOWN_KINDS = ['move', 'block', 'blitz', 'dodge', 'gfi', 'pickup', 'pass', 'handoff', 'td', 'turnover', 'injury', 'ko', 'cas', 'kickoff', 'sys'];
function addTickerLine(f) {
  const div = document.createElement('div');
  const kind = KNOWN_KINDS.includes(f.kind) ? f.kind : 'move';
  div.className = 'fl fl-' + kind;
  div.textContent = f.text || '';
  const ticker = $('ticker');
  ticker.prepend(div);
  while (ticker.childNodes.length > 80) ticker.removeChild(ticker.lastChild);
}

const EV_LABELS = { p_def_down: 'def down', p_att_down: 'att down', p_ball_out: 'ball out', p_turnover: 'turnover' };
function showEvCard(ev) {
  const parts = [];
  for (const [k, label] of Object.entries(EV_LABELS)) {
    if (typeof ev[k] === 'number') parts.push(Math.round(ev[k] * 100) + '% ' + label);
  }
  if (!parts.length) return hideEvCard();
  $('evcard').innerHTML = '<div class="ev-title">AI sees</div>' + esc(parts.join(' / '));
  $('evcard').classList.remove('hidden');
}
function hideEvCard() { $('evcard').classList.add('hidden'); }

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
