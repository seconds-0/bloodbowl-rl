/* Static mockup pitch renderer. Scene coordinates are engine squares:
   x 0..25 along the length, y 0..14 across. The human coach is always drawn
   attacking to the right (landscape) or upward (portrait, phone). */
(function () {
  const S = 40;
  const LEN = 26;
  const WID = 15;

  function portraitWanted(scene) {
    if (scene.orientation) return scene.orientation === "portrait";
    return window.matchMedia("(max-width: 720px)").matches;
  }

  function mapper(portrait) {
    return portrait
      ? { w: WID * S, h: LEN * S, at: (x, y) => [y * S, (LEN - 1 - x) * S] }
      : { w: LEN * S, h: WID * S, at: (x, y) => [x * S, y * S] };
  }

  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");
  }

  function grass(m, portrait) {
    let out = `<rect width="${m.w}" height="${m.h}" fill="#3f7a2e"/>`;
    for (let x = 0; x < LEN; x += 2) {
      const [px, py] = m.at(x, 0);
      out += portrait
        ? `<rect x="0" y="${(LEN - 2 - x) * S}" width="${m.w}" height="${2 * S}" fill="#478935"/>`
        : `<rect x="${px}" y="0" width="${S}" height="${m.h}" fill="#478935"/>`;
    }
    out += `<rect width="${m.w}" height="${m.h}" filter="url(#grain)" opacity=".55"/>`;
    return out;
  }

  function chalk(m, portrait) {
    const line = (x1, y1, x2, y2, w = 3, o = 0.8) =>
      `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#fff" stroke-opacity="${o}" stroke-width="${w}"/>`;
    let out = "";
    // faint square grid
    for (let x = 1; x < LEN; x++) {
      const [a] = portrait ? [null] : m.at(x, 0);
      out += portrait ? line(0, x * S, m.w, x * S, 1, 0.08) : line(a, 0, a, m.h, 1, 0.08);
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
    if (!scene.tz) return "";
    const counts = {};
    for (const p of scene.players) {
      if (p.team !== scene.tz || (p.state && p.state !== "standing")) continue;
      for (let dx = -1; dx <= 1; dx++)
        for (let dy = -1; dy <= 1; dy++) {
          if (!dx && !dy) continue;
          const x = p.x + dx, y = p.y + dy;
          if (x < 0 || y < 0 || x >= LEN || y >= WID) continue;
          counts[x + "," + y] = (counts[x + "," + y] || 0) + 1;
        }
    }
    const color = scene.tz === "h" ? "#c3142f" : "#2a3fbf";
    let out = "";
    for (const key in counts) {
      const [x, y] = key.split(",").map(Number);
      out += square(m, x, y, color, Math.min(0.11 * counts[key], 0.3));
    }
    return out;
  }

  function highlights(m, scene) {
    let out = "";
    for (const h of scene.highlights || []) {
      const styles = {
        half: ["#ffffff", 0.07, ""],
        los: ["#ffffff", 0.12, ""],
        ok: ["#3f9b2f", 0.35, ""],
        bad: ["#b3261e", 0.2, ""],
        drop: ["#ffd23f", 0.28, `stroke="#ffd23f" stroke-width="2" stroke-dasharray="6 4"`],
        target: ["#ffd23f", 0.22, `stroke="#fff" stroke-width="2"`],
        flag: ["#ffffff", 0.0, `stroke="#fff" stroke-width="3" stroke-dasharray="5 4"`],
        ghost: ["#2a3fbf", 0.28, `stroke="#d3d8f5" stroke-width="2" stroke-dasharray="4 3"`],
      }[h.kind];
      out += square(m, h.x, h.y, styles[0], styles[1], styles[2]);
    }
    return out;
  }

  function path(m, scene) {
    if (!scene.path) return "";
    let out = "";
    const pts = [];
    for (const st of scene.path) {
      const [px, py] = m.at(st.x, st.y);
      pts.push([px + S / 2, py + S / 2]);
      out += square(m, st.x, st.y, "#ffd23f", st.rush || st.dodge ? 0.62 : 0.4,
        `stroke="#ffd23f" stroke-width="2"`);
    }
    if (scene.pathFrom) {
      const [fx, fy] = m.at(scene.pathFrom.x, scene.pathFrom.y);
      pts.unshift([fx + S / 2, fy + S / 2]);
    }
    out += `<polyline points="${pts.map((p) => p.join(",")).join(" ")}" fill="none" stroke="#1c1915" stroke-opacity=".55" stroke-width="3" stroke-linejoin="round"/>`;
    for (const st of scene.path) {
      const [px, py] = m.at(st.x, st.y);
      if (st.dodge && st.rush) {
        out += `<line x1="${px + 4}" y1="${py + S - 4}" x2="${px + S - 4}" y2="${py + 4}" stroke="#1c1915" stroke-width="1.5"/>`;
        out += `<text x="${px + 11}" y="${py + 16}" class="num sm">${esc(st.rush)}</text>`;
        out += `<text x="${px + S - 11}" y="${py + S - 7}" class="num sm">${esc(st.dodge)}</text>`;
      } else if (st.dodge || st.rush) {
        out += `<text x="${px + S / 2}" y="${py + S / 2 + 6}" class="num">${esc(st.dodge || st.rush)}</text>`;
        out += `<text x="${px + S / 2}" y="${py + 10}" class="num tiny">${st.dodge ? "DODGE" : "RUSH"}</text>`;
      } else {
        out += `<circle cx="${px + S / 2}" cy="${py + S / 2}" r="9" fill="#1c1915" fill-opacity=".72"/>`;
        out += `<text x="${px + S / 2}" y="${py + S / 2 + 4.5}" class="step">${st.step}</text>`;
      }
    }
    return out;
  }

  function token(m, p) {
    const [px, py] = m.at(p.x, p.y);
    const cx = px + S / 2, cy = py + S / 2;
    const fill = p.team === "h" ? "#c3142f" : "#2a3fbf";
    const deep = p.team === "h" ? "#6d0a19" : "#121c6b";
    const r = p.big ? 17.5 : 15;
    let g = "";
    const op = p.used ? 0.5 : 1;
    if (p.selected) {
      g += `<circle cx="${cx}" cy="${cy}" r="${r + 4.5}" fill="none" stroke="#ffd23f" stroke-width="3.5"/>`;
    }
    if (p.state === "prone" || p.state === "stunned") {
      g += `<g opacity="${op}"><ellipse cx="${cx}" cy="${cy + 3}" rx="${r + 2}" ry="${r * 0.62}" fill="${fill}" stroke="${deep}" stroke-width="3"/>`;
      g += `<text x="${cx}" y="${cy + 7}" class="pos lying">${esc(p.pos)}</text>`;
      g += `<rect x="${cx - 13}" y="${cy + r * 0.62 + 5}" width="26" height="9" rx="1.5" fill="#f1ead8" stroke="#1c1915" stroke-width="1.2"/>`;
      g += `<text x="${cx}" y="${cy + r * 0.62 + 12.2}" class="state">${p.state === "prone" ? "DOWN" : "STUN"}</text>`;
      g += `</g>`;
    } else {
      g += `<g opacity="${op}"><circle cx="${cx}" cy="${cy + 1.5}" r="${r}" fill="#0c0b08" fill-opacity=".35"/>`;
      g += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${fill}" stroke="${deep}" stroke-width="3"/>`;
      g += `<circle cx="${cx}" cy="${cy}" r="${r - 4.5}" fill="none" stroke="#fff" stroke-opacity=".28" stroke-width="1.5"/>`;
      g += `<text x="${cx}" y="${cy + 5}" class="pos${p.big ? " big" : ""}">${esc(p.pos)}</text></g>`;
    }
    if (p.num !== undefined) {
      g += `<rect x="${px + 1}" y="${py + 1}" width="15" height="12" rx="2" fill="#f1ead8" stroke="${deep}" stroke-width="1.5"/>`;
      g += `<text x="${px + 8.5}" y="${py + 10.5}" class="jersey">${p.num}</text>`;
    }
    if (p.used) {
      g += `<circle cx="${px + S - 8}" cy="${py + 8}" r="6.5" fill="#1c1915"/>`;
      g += `<path d="M ${px + S - 11} ${py + 8} l 2.5 2.6 l 4.5 -5" fill="none" stroke="#f1ead8" stroke-width="2"/>`;
    }
    if (p.ball) {
      g += ball(px + S - 9, py + S - 8, 7.5);
    }
    return g;
  }

  function ball(cx, cy, r) {
    return `<ellipse cx="${cx}" cy="${cy}" rx="${r}" ry="${r * 0.72}" fill="#8a4b1f" stroke="#2b1507" stroke-width="1.8"/>` +
      `<line x1="${cx - r * 0.45}" y1="${cy}" x2="${cx + r * 0.45}" y2="${cy}" stroke="#fff" stroke-width="1.4"/>`;
  }

  function markers(m, scene) {
    let out = "";
    for (const b of scene.blockTargets || []) {
      const [px, py] = m.at(b.x, b.y);
      const col = b.who === "you" ? "#3f9b2f" : "#c8411b";
      const n = b.dice;
      const w = n * 11 + 3;
      out += `<rect x="${px + S / 2 - w / 2}" y="${py - 9}" width="${w}" height="13" fill="#1c1915" rx="2"/>`;
      for (let i = 0; i < n; i++) {
        out += `<rect x="${px + S / 2 - w / 2 + 3 + i * 11}" y="${py - 6.5}" width="8" height="8" fill="${col}" stroke="#fff" stroke-width="1"/>`;
      }
      out += `<rect x="${px + 2}" y="${py + 2}" width="${S - 4}" height="${S - 4}" fill="none" stroke="${col}" stroke-width="3"/>`;
    }
    for (const a of scene.pushArrows || []) {
      const [px, py] = m.at(a.x, a.y);
      const angle = { e: 0, se: 45, s: 90, sw: 135, w: 180, nw: 225, n: 270, ne: 315 }[a.dir];
      const cx = px + S / 2, cy = py + S / 2;
      out += `<rect x="${px + 3}" y="${py + 3}" width="${S - 6}" height="${S - 6}" fill="#ffd23f" fill-opacity="${a.hover ? 0.75 : 0.28}" stroke="#ffd23f" stroke-width="2"/>`;
      out += `<path transform="rotate(${angle} ${cx} ${cy})" d="M ${cx - 10} ${cy - 6} h 9 v -6 l 11 12 l -11 12 v -6 h -9 z" fill="#1c1915" fill-opacity=".85"/>`;
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
      out += `<text x="${px + S / 2}" y="${y + 16}" class="label"${l.ink ? ` fill="${l.ink}"` : ""}>${esc(l.text)}</text>`;
    }
    return out;
  }

  function render(el, scene) {
    const portrait = portraitWanted(scene);
    const m = mapper(portrait);
    const svg = `<svg viewBox="0 0 ${m.w} ${m.h}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="pitch">
      <defs>
        <filter id="grain"><feTurbulence type="fractalNoise" baseFrequency=".85" numOctaves="2" seed="4"/>
          <feColorMatrix values="0 0 0 0 .08 0 0 0 0 .18 0 0 0 0 .05 0 0 0 .35 0"/></filter>
        <style>
          .pos{font:700 13px "Barlow Semi Condensed",Arial,sans-serif;fill:#fff;text-anchor:middle}
          .pos.big{font-size:14px}
          .pos.lying{font-size:11px}
          .state{font:800 7.5px "Barlow Semi Condensed",Arial,sans-serif;fill:#1c1915;text-anchor:middle;letter-spacing:.02em}
          .jersey{font:700 9.5px "Barlow Semi Condensed",Arial,sans-serif;fill:#1c1915;text-anchor:middle}
          .num{font:800 17px "Barlow Semi Condensed",Arial,sans-serif;fill:#1c1915;text-anchor:middle}
          .num.sm{font-size:12px}
          .num.tiny{font-size:7.5px;letter-spacing:.04em}
          .step{font:700 11px "Barlow Semi Condensed",Arial,sans-serif;fill:#fff;text-anchor:middle}
          .label{font:700 14px "Barlow Semi Condensed",Arial,sans-serif;fill:#fff;text-anchor:middle}
        </style>
      </defs>
      ${grass(m, portrait)}${chalk(m, portrait)}${highlights(m, scene)}${tackleZones(m, scene)}${path(m, scene)}
      ${scene.players.map((p) => token(m, p)).join("")}${markers(m, scene)}
    </svg>`;
    el.innerHTML = svg;
    return { portrait, S, at: m.at, w: m.w, h: m.h };
  }

  window.BBPitch = { render, S };
})();
