#!/usr/bin/env node
/* Generates fixture_synthetic.jsonl — a SYNTHETIC but protocol-valid game
 * (~400 deltas) per docs/stream-protocol.md. Plausible-looking only; the
 * real recorded fixture (mock/fixture_match.jsonl) replaces it later. */
'use strict';
const fs = require('fs');
const path = require('path');

// deterministic LCG so the fixture is reproducible
let rng = 0xC0FFEE;
const rnd = () => ((rng = (rng * 1103515245 + 12345) >>> 0) / 4294967296);
const ri = (n) => Math.floor(rnd() * n);
const pick = (a) => a[ri(a.length)];
const r2 = (x) => Math.round(x * 100) / 100;

const MATCH_ID = 'm_synthetic_0001';
const HOME = { name: 'Gen-90B Grizzlies', roster: 'Orc', color: '#8b1a1a', agent: 'flagship-kickoff4', elo: 1620 };
const AWAY = { name: 'Gen-60B Wolves', roster: 'Wood Elf', color: '#1a4d8b', agent: 'snapshot-60B', elo: 1544 };
const ORC = ['Blitzer', 'Blitzer', 'Black Orc', 'Black Orc', 'Thrower', 'Lineman', 'Lineman', 'Lineman', 'Lineman', 'Lineman', 'Goblin'];
const ELF = ['Wardancer', 'Wardancer', 'Thrower', 'Catcher', 'Catcher', 'Lineman', 'Lineman', 'Lineman', 'Lineman', 'Lineman', 'Lineman'];
const HN = ['Grimgor', 'Urzag', 'Morka', 'Gashnak', 'Snikrot', 'Drogg', 'Karg', 'Bolg', 'Ruknar', 'Zogwart', 'Skab'];
const AN = ['Aelric', 'Liandra', 'Thalion', 'Sylvas', 'Eredhel', 'Caelum', 'Nimriel', 'Ferenor', 'Lothuial', 'Galadhon', 'Mirthal'];
const ORC_STATS = { ma: 5, st: 3, ag: 3, pa: 4, av: 10 };
const ELF_STATS = { ma: 7, st: 3, ag: 2, pa: 3, av: 8 };

// ---- mutable game state ----
const P = [];   // 22 players: home slots 0..10, away slots 16..26
for (let i = 0; i < 11; i++) {
  P.push({ slot: i, side: 'home', x: -1, y: -1, stance: 'standing', position: ORC[i], num: i + 1, icon: 'orc_' + ORC[i].toLowerCase().replace(/ /g, '_') + '_' + (i + 1), name: HN[i], stats: ORC_STATS, skills: i < 2 ? ['Block'] : [] });
  P.push({ slot: 16 + i, side: 'away', x: -1, y: -1, stance: 'standing', position: ELF[i], num: i + 1, icon: 'welf_' + ELF[i].toLowerCase() + '_' + (i + 1), name: AN[i], stats: ELF_STATS, skills: i < 2 ? ['Dodge'] : [] });
}
const bySlot = (s) => P.find(p => p.slot === s);
let ball = { x: -1, y: -1, state: 'off_pitch', carrier: null };
let score = [0, 0], half = 1, turn = [0, 0], active = 0, wp = 0.5;
let firstBloodDone = false;

// ---- emit machinery ----
const msgs = [];
let seq = 0;
function emit(m) { msgs.push(Object.assign({ v: 1, seq: seq++ }, m)); }
function snapPlayers() {
  return P.map(p => ({
    slot: p.slot, side: p.side, x: p.x, y: p.y, stance: p.stance,
    position: p.position, num: p.num, icon: p.icon,
    has_ball: ball.state === 'held' && ball.carrier === p.slot,
    stats: p.stats, skills: p.skills,
  }));
}
function snapshot() {
  emit({ t: 'snapshot', match_id: MATCH_ID, score: score.slice(), half, turn: turn.slice(), active_team: active, weather: 'nice', ball: Object.assign({}, ball), players: snapPlayers(), win_prob: r2(wp) });
}
let sinceSnap = 0;
function delta(o) {
  emit(Object.assign({ t: 'delta', moves: null, ball: null, score: null, turn: null, active_team: active, action: null, dice: null, ev: null, win_prob: r2(wp), feed: null }, o));
  if (++sinceSnap >= 100) { sinceSnap = 0; snapshot(); }
}
const mv = (p) => ({ slot: p.slot, x: p.x, y: p.y, stance: p.stance });
const ballMsg = () => Object.assign({}, ball);
function probs(chosen, alts) {
  const p0 = 0.45 + rnd() * 0.4, p1 = (1 - p0) * (0.4 + rnd() * 0.3);
  return [[chosen, r2(p0)], [alts[0], r2(p1)], [alts[1], r2(Math.max(0.02, 1 - p0 - p1 - rnd() * 0.1))]];
}
function drift(d) { wp = Math.min(0.97, Math.max(0.03, wp + d)); }
const who = (p) => '#' + p.num + ' ' + p.name;

// ---- formations ----
function setupKickoff(receiving) {
  const homeSpots = [[12, 6], [12, 7], [12, 8], [10, 3], [10, 11], [9, 5], [9, 9], [8, 7], [6, 4], [6, 10], [4, 7]];
  const i2 = (s) => [25 - s[0], s[1]];
  let hi = 0, ai = 0;
  for (const p of P) {
    if (p.stance === 'cas' || p.stance === 'sent_off') { p.x = -1; p.y = -1; continue; }
    if (p.stance === 'ko' && rnd() < 0.5) { p.x = -1; p.y = -1; continue; }   // some KO'd recover
    p.stance = 'standing';
    if (p.side === 'home') { const s = homeSpots[hi++ % 11]; p.x = s[0]; p.y = s[1]; }
    else { const s = i2(homeSpots[ai++ % 11]); p.x = s[0]; p.y = s[1]; }
  }
  // ball kicked into the receiving half
  ball = { x: receiving === 0 ? 5 + ri(5) : 16 + ri(5), y: 3 + ri(9), state: 'on_ground', carrier: null };
  turn[receiving]++;
  active = receiving;
  delta({
    moves: P.filter(p => p.x >= 0).map(mv), ball: ballMsg(), turn: turn.slice(),
    feed: [{ kind: 'kickoff', text: 'Kickoff — ' + (receiving === 0 ? HOME.name : AWAY.name) + ' receive', side: receiving === 0 ? 'home' : 'away' }],
  });
}

// ---- drive simulation ----
function teamPlayers(side) { return P.filter(p => p.side === side && p.x >= 0 && p.stance === 'standing'); }

function doBlock(att, def) {
  const ev = { p_def_down: r2(0.45 + rnd() * 0.4), p_att_down: r2(0.03 + rnd() * 0.12), p_ball_out: r2(rnd() * 0.3), p_turnover: r2(0.03 + rnd() * 0.1) };
  const rolls = [1 + ri(6), 1 + ri(6)];
  const picked = Math.max(rolls[0], rolls[1]);
  const down = rnd() < ev.p_def_down;
  const result = down ? 'Defender Down' : (picked >= 4 ? 'Pushed' : 'Both Down');
  const moves = [];
  const feed = [{ kind: 'block', text: who(att) + ' blocks ' + who(def), side: att.side }];
  // attacker steps adjacent to the defender
  att.x = Math.max(0, Math.min(25, def.x + (att.side === 'home' ? -1 : 1)));
  att.y = def.y;
  moves.push(mv(att));
  if (down) {
    def.stance = 'prone';
    const inj = rnd();
    if (inj < 0.10) {
      def.stance = 'cas'; def.x = -1; def.y = -1;
      const fb = !firstBloodDone; firstBloodDone = true;
      feed.push({ kind: 'cas', text: who(def) + ' is carried off the pitch!', side: def.side, first_blood: fb });
      drift(def.side === 'away' ? 0.05 : -0.05);
    } else if (inj < 0.25) {
      def.stance = 'ko'; def.x = -1; def.y = -1;
      feed.push({ kind: 'ko', text: who(def) + ' is knocked out', side: def.side });
    } else if (inj < 0.5) {
      def.stance = 'stunned';
      feed.push({ kind: 'injury', text: who(def) + ' is stunned', side: def.side });
    }
    moves.push({ slot: def.slot, x: def.x, y: def.y, stance: def.stance });
  } else if (result === 'Pushed') {
    def.x = Math.max(0, Math.min(25, def.x + (att.side === 'home' ? 1 : -1)));
    def.y = Math.max(0, Math.min(14, def.y + ri(3) - 1));
    moves.push(mv(def));
  }
  delta({
    moves,
    action: { type: 'BLOCK', actor: att.slot, target: def.slot, probs: probs('BLOCK ' + def.slot, ['MOVE ' + att.x + ',' + att.y, 'END_TURN']) },
    dice: { kind: 'block', rolls, picked, result, reroll_used: false },
    ev,
    feed,
  });
  return result === 'Both Down';
}

function runDrive(receiving, budget) {
  setupKickoff(receiving);
  sinceSnap = 0; snapshot();   // fresh snapshot each drive: keeps mock joiners ~current
  const side = receiving === 0 ? 'home' : 'away';
  const enemySide = receiving === 0 ? 'away' : 'home';
  const dir = receiving === 0 ? 1 : -1;
  const goal = receiving === 0 ? 25 : 0;

  // pickup: nearest standing teammate walks on and grabs the ball
  let carrier = teamPlayers(side).sort((a, b) => Math.abs(a.x - ball.x) + Math.abs(a.y - ball.y) - (Math.abs(b.x - ball.x) + Math.abs(b.y - ball.y)))[0];
  carrier.x = ball.x; carrier.y = ball.y;
  ball = { x: carrier.x, y: carrier.y, state: 'held', carrier: carrier.slot };
  delta({
    moves: [mv(carrier)], ball: ballMsg(),
    action: { type: 'PICKUP', actor: carrier.slot, target: [carrier.x, carrier.y], probs: probs('PICKUP', ['MOVE ' + (carrier.x + dir) + ',' + carrier.y, 'END_TURN']) },
    dice: { kind: 'd6', target: 3, roll: 3 + ri(4), ok: true, label: 'Pick-up' },
    feed: [{ kind: 'pickup', text: who(carrier) + ' scoops up the ball', side }],
  });
  let passDone = false;

  while (msgs.length < budget) {
    const r = rnd();
    const distToGoal = Math.abs(goal - carrier.x);

    if (r < 0.20 && teamPlayers(enemySide).length) {                       // block
      const blocker = pick(teamPlayers(side).filter(p => p !== carrier)) || carrier;
      const def = pick(teamPlayers(enemySide));
      doBlock(blocker, def);
      drift((side === 'home' ? 1 : -1) * 0.01);
    } else if (r < 0.42) {                                                 // support move (no carrier progress)
      const sup = pick(teamPlayers(side).filter(p => p !== carrier)) || carrier;
      sup.x = Math.max(0, Math.min(25, sup.x + dir));
      sup.y = Math.max(0, Math.min(14, sup.y + ri(3) - 1));
      delta({
        moves: [mv(sup)],
        action: { type: 'MOVE', actor: sup.slot, target: [sup.x, sup.y], probs: probs('MOVE ' + sup.x + ',' + sup.y, ['BLOCK', 'END_TURN']) },
        feed: rnd() < 0.25 ? [{ kind: 'move', text: who(sup) + ' moves up in support', side }] : null,
      });
    } else if (r < 0.48 && !passDone && distToGoal > 8) {                  // pass
      const rx = Math.max(0, Math.min(25, carrier.x + dir * (3 + ri(3)))), ry = Math.max(0, Math.min(14, carrier.y + ri(5) - 2));
      const recv = pick(teamPlayers(side).filter(p => p !== carrier)) || carrier;
      recv.x = rx; recv.y = ry;
      ball = { x: rx, y: ry, state: 'held', carrier: recv.slot };
      delta({
        moves: [mv(recv)], ball: ballMsg(),
        action: { type: 'PASS', actor: carrier.slot, target: [rx, ry], probs: probs('PASS ' + rx + ',' + ry, ['MOVE ' + (carrier.x + dir) + ',' + carrier.y, 'HANDOFF ' + recv.slot]) },
        dice: { kind: 'd6', target: 4, roll: 4 + ri(3), ok: true, label: 'Pass' },
        feed: [{ kind: 'pass', text: who(carrier) + ' launches a pass to ' + who(recv), side }],
      });
      carrier = recv; passDone = true;
      drift((side === 'home' ? 1 : -1) * 0.03);
    } else if (r < 0.53 && distToGoal > 3) {                               // handoff
      const recv = pick(teamPlayers(side).filter(p => p !== carrier)) || carrier;
      recv.x = Math.max(0, Math.min(25, carrier.x + dir)); recv.y = carrier.y;
      ball = { x: recv.x, y: recv.y, state: 'held', carrier: recv.slot };
      delta({
        moves: [mv(recv)], ball: ballMsg(),
        action: { type: 'HANDOFF', actor: carrier.slot, target: [recv.x, recv.y], probs: probs('HANDOFF ' + recv.slot, ['MOVE', 'END_TURN']) },
        feed: [{ kind: 'handoff', text: who(carrier) + ' hands off to ' + who(recv), side }],
      });
      carrier = recv;
    } else {                                                               // move (the common case)
      const stepY = Math.max(0, Math.min(14, carrier.y + ri(3) - 1));
      const stepX = Math.max(0, Math.min(25, carrier.x + dir));
      const dodging = rnd() < 0.35;
      const gfi = distToGoal <= 2 && rnd() < 0.5;
      const failed = (dodging && rnd() < 0.32) || (gfi && rnd() < 0.18);
      if (failed) {                                                        // turnover!
        carrier.stance = 'prone'; carrier.x = stepX; carrier.y = stepY;
        ball = { x: Math.max(0, Math.min(25, stepX + ri(3) - 1)), y: Math.max(0, Math.min(14, stepY + ri(3) - 1)), state: 'on_ground', carrier: null };
        active = receiving === 0 ? 1 : 0;
        delta({
          moves: [mv(carrier)], ball: ballMsg(), active_team: active,
          action: { type: 'MOVE', actor: carrier.slot, target: [stepX, stepY], probs: probs('MOVE ' + stepX + ',' + stepY, ['END_TURN', 'BLOCK']) },
          dice: { kind: 'd6', target: dodging ? 3 : 2, roll: 1, ok: false, label: dodging ? 'Dodge' : 'GFI' },
          feed: [
            { kind: dodging ? 'dodge' : 'gfi', text: who(carrier) + (dodging ? ' trips mid-dodge' : ' stumbles going for it'), side },
            { kind: 'turnover', text: 'TURNOVER — ' + (side === 'home' ? HOME.name : AWAY.name) + ' lose the ball!', side },
          ],
        });
        drift((side === 'home' ? -1 : 1) * 0.08);
        return 'turnover';
      }
      carrier.x = stepX; carrier.y = stepY;
      ball = { x: stepX, y: stepY, state: 'held', carrier: carrier.slot };
      const feed = [];
      if (dodging) feed.push({ kind: 'dodge', text: who(carrier) + ' dodges free', side });
      else if (gfi) feed.push({ kind: 'gfi', text: who(carrier) + ' goes for it', side });
      else if (rnd() < 0.5) feed.push({ kind: 'move', text: who(carrier) + ' advances', side });
      delta({
        moves: [mv(carrier)], ball: ballMsg(),
        action: { type: 'MOVE', actor: carrier.slot, target: [stepX, stepY], probs: probs('MOVE ' + stepX + ',' + stepY, ['MOVE ' + stepX + ',' + Math.min(14, stepY + 1), 'BLOCK']) },
        dice: (dodging || gfi) ? { kind: 'd6', target: dodging ? 3 : 2, roll: 2 + ri(5), ok: true, label: dodging ? 'Dodge' : 'GFI' } : null,
        feed: feed.length ? feed : null,
      });
      drift((side === 'home' ? 1 : -1) * 0.005);
      if (carrier.x === goal) {                                            // touchdown!
        score[receiving]++;
        active = receiving === 0 ? 1 : 0;
        wp = receiving === 0 ? Math.min(0.95, wp + 0.15) : Math.max(0.05, wp - 0.15);
        delta({
          score: score.slice(), active_team: active, ball: ballMsg(),
          feed: [{ kind: 'td', text: 'TOUCHDOWN! ' + who(carrier) + ' crosses the line for ' + (side === 'home' ? HOME.name : AWAY.name), side }],
        });
        return 'td';
      }
    }
  }
  return 'time';
}

// ---- build the match ----
emit({ t: 'hello', match_id: MATCH_ID, proto: 1, server: 'bbstream-mock/0.1', sprite_base: '' });
emit({ t: 'match_start', match_id: MATCH_ID, home: HOME, away: AWAY, players: snapPlayers() });
snapshot();

let receiving = 0;
const BUDGET = 400;
while (msgs.length < BUDGET) {
  if (half === 1 && msgs.length > BUDGET / 2) {
    half = 2;
    delta({ feed: [{ kind: 'kickoff', text: '— Second half —', side: 'home' }] });
  }
  const res = runDrive(receiving, Math.min(BUDGET, msgs.length + 60 + ri(40)));
  receiving = res === 'td' ? (receiving === 0 ? 1 : 0) : (res === 'turnover' ? (receiving === 0 ? 1 : 0) : receiving);
}
const winner = score[0] > score[1] ? 'home' : score[1] > score[0] ? 'away' : 'draw';
const mvpSide = winner === 'away' ? 'away' : 'home';
const mvp = P.filter(p => p.side === mvpSide)[ri(3)];
emit({ t: 'match_end', score: score.slice(), winner, mvp: { slot: mvp.slot, name: mvp.name, tds: Math.max(score[mvpSide === 'home' ? 0 : 1] - ri(2), 0) }, next_match_in_s: 5 });

const out = path.join(__dirname, 'fixture_synthetic.jsonl');
fs.writeFileSync(out, msgs.map(m => JSON.stringify(m)).join('\n') + '\n');
const nDeltas = msgs.filter(m => m.t === 'delta').length;
console.log('Wrote ' + out + ': ' + msgs.length + ' messages (' + nDeltas + ' deltas), final score ' + score.join('-') + ', winner ' + winner);
