#!/usr/bin/env node
/* Mock bbstream server: replays a JSONL fixture (one protocol message per line)
 * over ws://localhost:8787/ws with pacing, looping forever. See
 * docs/stream-protocol.md. Usage:
 *   node play.js [--fixture <file>] [--speed <mult>] [--port <n>]
 * Pacing: hello/match_start/snapshot are instant; deltas/match_end one per
 * 600ms / speed. After match_end the fixture restarts with fresh seq numbers
 * and a new match_id. New clients get the cached last snapshot. */
'use strict';
const fs = require('fs');
const path = require('path');
const WebSocket = require('ws');

// ---- args ----
const args = process.argv.slice(2);
function arg(name, dflt) {
  const i = args.indexOf('--' + name);
  return i >= 0 && args[i + 1] != null ? args[i + 1] : dflt;
}
const SPEED = parseFloat(arg('speed', '1')) || 1;
const PORT = parseInt(arg('port', '8787'), 10);
const FIXTURE = path.resolve(__dirname, arg('fixture', 'fixture_synthetic.jsonl'));
const DELTA_MS = 600 / SPEED;
const INSTANT = new Set(['hello', 'match_start', 'snapshot']);

const lines = fs.readFileSync(FIXTURE, 'utf8').split('\n').filter(l => l.trim());
const fixture = lines.map((l, i) => {
  try { return JSON.parse(l); }
  catch (e) { throw new Error(FIXTURE + ' line ' + (i + 1) + ': bad JSON'); }
});
console.log('Loaded ' + fixture.length + ' messages from ' + FIXTURE);

// ---- replay state ----
let seq = 0;                  // global, monotonic across loops
let idx = 0;
let matchId = freshMatchId();
let lastSnapshot = null;      // last stamped snapshot (for joiners / resync)
let lastHello = null;
let lastMatchStart = null;    // replayed to joiners so they get team names/colors

function freshMatchId() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return 'm_' + d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate()) + '_' +
    pad(d.getHours()) + pad(d.getMinutes()) + '_' + Math.floor(Math.random() * 1e4);
}

const wss = new WebSocket.Server({ port: PORT, path: '/ws' });
wss.on('connection', (sock) => {
  console.log('client connected (' + wss.clients.size + ' total)');
  // hello + match_start + the cached snapshot, stamped so the next broadcast delta is seq-continuous
  if (lastHello) sock.send(JSON.stringify(Object.assign({}, lastHello, { seq: Math.max(0, seq - 3), match_id: matchId })));
  if (lastMatchStart) sock.send(JSON.stringify(Object.assign({}, lastMatchStart, { seq: Math.max(0, seq - 2), match_id: matchId })));
  if (lastSnapshot) sock.send(JSON.stringify(Object.assign({}, lastSnapshot, { seq: seq - 1, match_id: matchId })));
  sock.on('message', (raw) => {
    let m; try { m = JSON.parse(raw); } catch (e) { return; }
    if (m.t === 'resync' && lastSnapshot) {
      sock.send(JSON.stringify(Object.assign({}, lastSnapshot, { seq: seq - 1, match_id: matchId })));
    } // pong: ignored
  });
  sock.on('error', () => {});
});

function broadcast(msg) {
  const stamped = Object.assign({}, msg, { seq: seq++ });
  if ('match_id' in stamped) stamped.match_id = matchId;
  if (stamped.t === 'hello') lastHello = stamped;
  if (stamped.t === 'match_start') { lastMatchStart = stamped; lastSnapshot = null; }
  if (stamped.t === 'snapshot') lastSnapshot = stamped;
  const data = JSON.stringify(stamped);
  for (const c of wss.clients) if (c.readyState === WebSocket.OPEN) c.send(data);
  return stamped;
}

function step() {
  if (idx >= fixture.length) {           // loop: fresh match id, seq keeps climbing
    idx = 0;
    matchId = freshMatchId();
    console.log('fixture looped → new match ' + matchId);
    return setTimeout(step, 3000 / SPEED);
  }
  const msg = broadcast(fixture[idx++]);
  if (msg.t === 'match_end') {
    const wait = (msg.next_match_in_s || 3) * 1000 / SPEED;
    return setTimeout(step, wait);
  }
  setTimeout(step, INSTANT.has(msg.t) ? 0 : DELTA_MS);
}

setInterval(() => broadcast({ v: 1, t: 'ping' }), 15000);  // heartbeat

console.log('Serving ws://localhost:' + PORT + '/ws  (speed x' + SPEED + ', ' + Math.round(DELTA_MS) + 'ms/delta)');
step();
