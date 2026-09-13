/* Interactive pitch renderer. Scene coordinates are engine squares: x 0..25
   along the length, y 0..14 across. Home (x 0..12) is drawn on the left in
   landscape and at the bottom in portrait (phone). Only squares and players
   the app marks as hits carry data-legal; everything else is decoration. */
(function () {
  const S = 40;
  const LEN = 26;
  const WID = 15;
  const HOME = "#c3142f", HOME_DEEP = "#6d0a19", AWAY = "#2a3fbf", AWAY_DEEP = "#121c6b";

  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
  }

  function mapper(portrait) {
    return portrait
      ? { w: WID * S, h: LEN * S, at: (x, y) => [y * S, (LEN - 1 - x) * S] }
      : { w: LEN * S, h: WID * S, at: (x, y) => [x * S, y * S] };
  }

  function grass(m, portrait) {
    let out = `<rect width="${m.w}" height="${m.h}" fill="#3f7a2e"/>`;
    for (let x = 0; x < LEN; x += 2) {
      out += portrait
        ? `<rect x="0" y="${(LEN - 1 - x) * S}" width="${m.w}" height="${S}" fill="#478935"/>`
        : `<rect x="${x * S}" y="0" width="${S}" height="${m.h}" fill="#478935"/>`;
    }
    out += `<rect width="${m.w}" height="${m.h}" filter="url(#grain)" opacity=".55"/>`;
    return out;
  }

  function chalk(m, portrait) {
    const line = (x1, y1, x2, y2, w = 3, o = 0.8) =>
      `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#fff" stroke-opacity="${o}" stroke-width="${w}"/>`;
    let out = "";
    for (let x = 1; x < LEN; x++) {
      out += portrait ? line(0, x * S, m.w, x * S, 1, 0.08) : line(x * S, 0, x * S, m.h, 1, 0.08);
    }
    for (let y = 1; y < WID; y++) {
      out += portrait ? line(y * S, 0, y * S, m.h, 1, 0.08) : line(0, y * S, m.w, y * S, 1, 0.08);
    }
    const xl = (x) => (portrait ? (LEN - x) * S : x * S);
    const yl = (y) => y * S;
    if (portrait) {
      out += line(0, xl(1), m.w, xl(1)) + line(0, xl(25), m.w, xl(25)) + line(0, xl(13), m.w, xl(13), 4, 0.9);
      out += line(yl(4), xl(1), yl(4), xl(25), 2, 0.55) + line(yl(11), xl(1), yl(11), xl(25), 2, 0.55);
    } else {
      out += line(xl(1), 0, xl(1), m.h) + line(xl(25), 0, xl(25), m.h) + line(xl(13), 0, xl(13), m.h, 4, 0.9);
      out += line(xl(1), yl(4), xl(25), yl(4), 2, 0.55) + line(xl(1), yl(11), xl(25), yl(11), 2, 0.55);
    }
    out += `<rect x="1.5" y="1.5" width="${m.w - 3}" height="${m.h - 3}" fill="none" stroke="#fff" stroke-opacity=".85" stroke-width="3"/>`;
    return out;
  }

  function square(m, x, y, fill, opacity, extra = "") {
    const [px, py] = m.at(x, y);
    return `<rect x="${px + 2}" y="${py + 2}" width="${S - 4}" height="${S - 4}" fill="${fill}" fill-opacity="${opacity}" ${extra}/>`;
  }

  function tackleZones(m, scene) {
    if (scene.tzTeam === undefined || scene.tzTeam === null) return "";
    const counts = {};
    for (const p of scene.players) {
      if (p.team !== scene.tzTeam || p.state !== "standing" || p.x === null) continue;
      for (let dx = -1; dx <= 1; dx++)
        for (let dy = -1; dy <= 1; dy++) {
          if (!dx && !dy) continue;
          const x = p.x + dx, y = p.y + dy;
          if (x < 0 || y < 0 || x >= LEN || y >= WID) continue;
          counts[x + "," + y] = (counts[x + "," + y] || 0) + 1;
        }
    }
    const color = scene.tzTeam === 0 ? HOME : AWAY;
    let out = "";
    for (const key in counts) {
      const [x, y] = key.split(",").map(Number);
      out += square(m, x, y, color, Math.min(0.11 * counts[key], 0.3));
    }
    return out;
  }

  const HL = {
    half: ["#ffffff", 0.07, ""],
    los: ["#ffffff", 0.14, ""],
    ok: ["#3f9b2f", 0.35, ""],
    bad: ["#b3261e", 0.22, ""],
    drop: ["#ffd23f", 0.3, `stroke="#ffd23f" stroke-width="2" stroke-dasharray="6 4"`],
    lit: ["#ffd23f", 0.18, `stroke="#ffd23f" stroke-opacity=".7" stroke-width="1.5"`],
    move: ["#ffd23f", 0.26, `stroke="#ffd23f" stroke-opacity=".85" stroke-width="1.5"`],
    reach: ["#ffd23f", 0.1, ""],
    target: ["#ffd23f", 0.4, `stroke="#fff" stroke-width="3"`],
    flag: ["#ffffff", 0.0, `stroke="#fff" stroke-width="3" stroke-dasharray="5 4"`],
    ghost: ["#2a3fbf", 0.28, `stroke="#d3d8f5" stroke-width="2" stroke-dasharray="4 3"`],
    ghosth: ["#c3142f", 0.28, `stroke="#f3cfd3" stroke-width="2" stroke-dasharray="4 3"`],
    vacated: ["#ffffff", 0.15, `stroke="#ffd23f" stroke-width="3" stroke-dasharray="6 4"`],
  };

  function highlights(m, scene) {
    let out = "";
    for (const h of scene.highlights || []) {
      const st = HL[h.kind] || HL.lit;
      if (h.x < 0 || h.y < 0 || h.x >= LEN || h.y >= WID) continue;
      out += square(m, h.x, h.y, st[0], st[1], st[2]);
      if (h.text) {
        const [px, py] = m.at(h.x, h.y);
        out += `<text x="${px + S / 2}" y="${py + S / 2 + 6}" class="num">${esc(h.text)}</text>`;
      }
    }
    return out;
  }

  function path(m, scene) {
    if (!scene.path || !scene.path.length) return "";
    let out = "";
    const pts = [];
    if (scene.pathFrom) {
      const [fx, fy] = m.at(scene.pathFrom.x, scene.pathFrom.y);
      pts.push([fx + S / 2, fy + S / 2]);
    }
    for (const st of scene.path) {
      const [px, py] = m.at(st.x, st.y);
      pts.push([px + S / 2, py + S / 2]);
      out += square(m, st.x, st.y, "#ffd23f", st.rush || st.dodge ? 0.62 : 0.4,
        `stroke="#ffd23f" stroke-width="2" class="path-sq" data-step="${st.step}"`);
    }
    out += `<polyline points="${pts.map((p) => p.join(",")).join(" ")}" fill="none" stroke="#1c1915" stroke-opacity=".55" stroke-width="3" stroke-linejoin="round"/>`;
    for (const st of scene.path) {
      const [px, py] = m.at(st.x, st.y);
      if (st.dodge && st.rush) {
        out += `<line x1="${px + 4}" y1="${py + S - 4}" x2="${px + S - 4}" y2="${py + 4}" stroke="#1c1915" stroke-width="1.5"/>`;
        out += `<text x="${px + 12}" y="${py + 17}" class="num sm">${esc(st.rush)}</text>`;
        out += `<text x="${px + S - 12}" y="${py + S - 7}" class="num sm">${esc(st.dodge)}</text>`;
      } else if (st.dodge || st.rush) {
        out += `<text x="${px + S / 2}" y="${py + S / 2 + 8}" class="num">${esc(st.dodge || st.rush)}</text>`;
        out += `<text x="${px + S / 2}" y="${py + 11}" class="num tiny">${st.dodge ? "DODGE" : "RUSH"}</text>`;
      } else {
        out += `<circle cx="${px + S / 2}" cy="${py + S / 2}" r="10" fill="#1c1915" fill-opacity=".72"/>`;
        out += `<text x="${px + S / 2}" y="${py + S / 2 + 5}" class="step">${st.step}</text>`;
      }
    }
    return out;
  }

  function ball(cx, cy, r) {
    return `<ellipse cx="${cx}" cy="${cy}" rx="${r}" ry="${r * 0.72}" fill="#8a4b1f" stroke="#2b1507" stroke-width="1.8"/>` +
      `<line x1="${cx - r * 0.45}" y1="${cy}" x2="${cx + r * 0.45}" y2="${cy}" stroke="#fff" stroke-width="1.4"/>`;
  }

  function token(m, p) {
    const [px, py] = m.at(p.x, p.y);
    const cx = px + S / 2, cy = py + S / 2;
    const fill = p.team === 0 ? HOME : AWAY;
    const deep = p.team === 0 ? HOME_DEEP : AWAY_DEEP;
    const r = p.big ? 17 : 15;
    let g = `<g class="token" data-slot="${p.slot}" data-team="${p.team}">`;
    const op = p.used ? 0.5 : 1;
    if (p.legal) {
      g += `<circle cx="${cx}" cy="${cy}" r="${r + 4}" fill="none" stroke="#ffd23f" stroke-width="2.5" stroke-dasharray="4 3"/>`;
    }
    if (p.selected) {
      g += `<circle cx="${cx}" cy="${cy}" r="${r + 4.5}" fill="none" stroke="#ffd23f" stroke-width="3.5"/>`;
    }
    if (p.state === "prone" || p.state === "stunned" || p.state === "stunned_used") {
      const stun = p.state !== "prone";
      g += `<g opacity="${op}"><ellipse cx="${cx}" cy="${cy - 2}" rx="${r + 2}" ry="${r * 0.6}" fill="${fill}" stroke="${deep}" stroke-width="3"/>`;
      g += `<text x="${cx}" y="${cy + 2.5}" class="pos lying">${esc(p.pos)}</text></g>`;
      g += `<rect x="${cx - 19}" y="${py + S - 15}" width="38" height="15" rx="2" fill="${stun ? "#1c1915" : "#f1ead8"}" stroke="#1c1915" stroke-width="1.4"/>`;
      g += `<text x="${cx}" y="${py + S - 3.2}" class="state${stun ? " stun" : ""}">${stun ? "STUN" : "DOWN"}</text>`;
    } else {
      g += `<g opacity="${op}"><circle cx="${cx}" cy="${cy + 1.5}" r="${r}" fill="#0c0b08" fill-opacity=".35"/>`;
      g += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${fill}" stroke="${deep}" stroke-width="3"/>`;
      g += `<circle cx="${cx}" cy="${cy}" r="${r - 4.5}" fill="none" stroke="#fff" stroke-opacity=".28" stroke-width="1.5"/>`;
      g += `<text x="${cx}" y="${cy + 5}" class="pos${p.big ? " big" : ""}">${esc(p.pos)}</text></g>`;
    }
    if (p.num !== undefined) {
      const w = p.num >= 10 ? 21 : 16;
      g += `<rect x="${px - 1}" y="${py - 1}" width="${w}" height="16" rx="2" fill="#f1ead8" stroke="${deep}" stroke-width="1.5"/>`;
      g += `<text x="${px - 1 + w / 2}" y="${py + 11.6}" class="jersey">${p.num}</text>`;
    }
    if (p.used) {
      g += `<circle cx="${px + S - 7}" cy="${py + 7}" r="7" fill="#1c1915"/>`;
      g += `<path d="M ${px + S - 10.5} ${py + 7} l 2.5 2.6 l 4.5 -5" fill="none" stroke="#f1ead8" stroke-width="2"/>`;
    }
    if (p.ball) g += ball(px + S - 8, py + S - 9, 7.5);
    g += `</g>`;
    return g;
  }

  function markers(m, scene) {
    let out = "";
    for (const b of scene.targets || []) {
      const [px, py] = m.at(b.x, b.y);
      const col = b.who === "them" ? "#c8411b" : b.kind === "block" ? "#3f9b2f" : "#ffd23f";
      if (b.dice) {
        const n = b.dice, w = n * 12 + 4;
        out += `<rect x="${px + S / 2 - w / 2}" y="${py - 10}" width="${w}" height="14" fill="#1c1915" rx="2"/>`;
        for (let i = 0; i < n; i++) {
          out += `<rect x="${px + S / 2 - w / 2 + 3 + i * 12}" y="${py - 7}" width="9" height="9" fill="${col}" stroke="#fff" stroke-width="1"/>`;
        }
      }
      out += `<rect x="${px + 2}" y="${py + 2}" width="${S - 4}" height="${S - 4}" fill="none" stroke="${col}" stroke-width="3"/>`;
      if (b.text) {
        const w = b.text.length * 7.6 + 12;
        out += `<rect x="${px + S / 2 - w / 2}" y="${py + S + 1}" width="${w}" height="17" fill="#1c1915" rx="2"/>`;
        out += `<text x="${px + S / 2}" y="${py + S + 13.5}" class="label sm">${esc(b.text)}</text>`;
      }
    }
    for (const a of scene.pushArrows || []) {
      const cx0 = Math.max(0, Math.min(LEN - 1, a.x)), cy0 = Math.max(0, Math.min(WID - 1, a.y));
      const [px, py] = m.at(cx0, cy0);
      let [fx, fy] = m.at(a.fromX, a.fromY);
      const [tx, ty] = m.at(a.x, a.y);
      const angle = Math.atan2(ty - fy, tx - fx) * 180 / Math.PI;
      const cx = px + S / 2, cy = py + S / 2;
      out += `<rect x="${px + 3}" y="${py + 3}" width="${S - 6}" height="${S - 6}" fill="#ffd23f" fill-opacity="${a.hover ? 0.75 : 0.3}" stroke="#ffd23f" stroke-width="2"/>`;
      out += `<path transform="rotate(${angle} ${cx} ${cy})" d="M ${cx - 10} ${cy - 6} h 9 v -6 l 11 12 l -11 12 v -6 h -9 z" fill="#1c1915" fill-opacity=".85"/>`;
      if (a.crowd) {
        out += `<rect x="${cx - 23}" y="${py + S - 16}" width="46" height="15" rx="2" fill="#b3261e"/>`;
        out += `<text x="${cx}" y="${py + S - 4.5}" class="label xs">CROWD</text>`;
      }
    }
    if (scene.groundBall) {
      const [px, py] = m.at(scene.groundBall.x, scene.groundBall.y);
      out += ball(px + S / 2, py + S / 2, 9);
    }
    for (const l of scene.labels || []) {
      const [px, py] = m.at(l.x, l.y);
      const w = l.text.length * 8.4 + 14;
      const x = px + S / 2 - w / 2, y = py + (l.below ? S + 4 : -26);
      out += `<rect x="${x}" y="${y}" width="${w}" height="22" fill="${l.fill || "#1c1915"}" rx="2"/>`;
      out += `<text x="${px + S / 2}" y="${y + 16}" class="label">${esc(l.text)}</text>`;
    }
    return out;
  }

  function hits(m, scene) {
    let out = "";
    for (const h of scene.hits || []) {
      if (h.x < 0 || h.y < 0 || h.x >= LEN || h.y >= WID) continue;
      const [px, py] = m.at(h.x, h.y);
      const attrs = Object.entries(h.data || {}).map(([k, v]) => ` data-${k}="${esc(v)}"`).join("");
      out += `<rect class="hit${h.legal ? " legal" : ""}" x="${px}" y="${py}" width="${S}" height="${S}" fill="transparent" data-x="${h.x}" data-y="${h.y}"${h.legal ? ' data-legal="1"' : ""}${attrs}/>`;
    }
    return out;
  }

  function render(el, scene) {
    const portrait = scene.orientation
      ? scene.orientation === "portrait"
      : window.matchMedia("(max-width: 720px)").matches;
    const m = mapper(portrait);
    const onPitch = scene.players.filter((p) => p.x !== null && p.x !== undefined);
    el.innerHTML = `<svg viewBox="0 0 ${m.w} ${m.h}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="pitch">
      <defs>
        <filter id="grain"><feTurbulence type="fractalNoise" baseFrequency=".85" numOctaves="2" seed="4"/>
          <feColorMatrix values="0 0 0 0 .08 0 0 0 0 .18 0 0 0 0 .05 0 0 0 .35 0"/></filter>
        <style>
          .pos{font:700 13px "Barlow Semi Condensed",Arial,sans-serif;fill:#fff;text-anchor:middle}
          .pos.big{font-size:14px}
          .pos.lying{font-size:12px}
          .state{font:800 12.5px "Barlow Semi Condensed",Arial,sans-serif;fill:#1c1915;text-anchor:middle;letter-spacing:.03em}
          .state.stun{fill:#f1ead8}
          .jersey{font:700 13px "Barlow Semi Condensed",Arial,sans-serif;fill:#1c1915;text-anchor:middle}
          .num{font:800 17px "Barlow Semi Condensed",Arial,sans-serif;fill:#1c1915;text-anchor:middle}
          .num.sm{font-size:13px}
          .num.tiny{font-size:8.5px;letter-spacing:.04em}
          .step{font:700 12px "Barlow Semi Condensed",Arial,sans-serif;fill:#fff;text-anchor:middle}
          .label{font:700 14px "Barlow Semi Condensed",Arial,sans-serif;fill:#fff;text-anchor:middle}
          .label.sm{font-size:12px}
          .label.xs{font-size:10px;letter-spacing:.04em}
          .hit{cursor:pointer}
        </style>
      </defs>
      ${grass(m, portrait)}${chalk(m, portrait)}${highlights(m, scene)}${tackleZones(m, scene)}${path(m, scene)}
      ${onPitch.map((p) => token(m, p)).join("")}${markers(m, scene)}${hits(m, scene)}
    </svg>`;
    const svg = el.firstElementChild;
    return {
      portrait, S, w: m.w, h: m.h, at: m.at, svg,
      // Square under a client point, or null.
      squareAt(clientX, clientY) {
        const r = svg.getBoundingClientRect();
        const ux = (clientX - r.left) * (m.w / r.width);
        const uy = (clientY - r.top) * (m.h / r.height);
        if (ux < 0 || uy < 0 || ux >= m.w || uy >= m.h) return null;
        const a = Math.floor(ux / S), b = Math.floor(uy / S);
        return portrait ? { x: LEN - 1 - b, y: a } : { x: a, y: b };
      },
      // Bounding box of a square in coordinates relative to the SVG element.
      squareBox(x, y) {
        const r = svg.getBoundingClientRect();
        const k = r.width / m.w;
        const [px, py] = m.at(x, y);
        return { left: px * k, top: py * k, width: S * k, height: S * k };
      },
    };
  }

  window.BBPitch = { render, S, LEN, WID };
})();
