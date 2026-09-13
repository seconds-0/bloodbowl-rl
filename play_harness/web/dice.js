/* Block dice faces drawn as cream cubes with ink glyphs (original drawings). */
(function () {
  const glyphs = {
    skull: `<path d="M20 9c-7 0-11 5-11 10 0 4 2 6 4 7v4h14v-4c2-1 4-3 4-7 0-5-4-10-11-10z" fill="#1c1915"/><circle cx="15.5" cy="19" r="3" fill="#f3ecd9"/><circle cx="24.5" cy="19" r="3" fill="#f3ecd9"/><rect x="16" y="27" width="2" height="3" fill="#f3ecd9"/><rect x="22" y="27" width="2" height="3" fill="#f3ecd9"/>`,
    both: `<path d="M13 9v14h-4l6 8 6-8h-4V9z" fill="#1c1915"/><path d="M27 9v14h-4l6 8 6-8h-4V9z" fill="#b3261e"/>`,
    push: `<path d="M8 17h15v-7l11 10-11 10v-7H8z" fill="#1c1915"/>`,
    stumble: `<path d="M8 17h12v-7l11 10-11 10v-7H8z" fill="#1c1915"/><rect x="31" y="9" width="3.5" height="13" fill="#b3261e"/><rect x="31" y="25" width="3.5" height="3.5" fill="#b3261e"/>`,
    pow: `<path d="M20 5l3.5 8.5 8.5-3.5-3.5 8.5 8.5 3.5-8.5 3.5 3.5 8.5-8.5-3.5L20 35l-3.5-8.5-8.5 3.5 3.5-8.5L3 18l8.5-3.5L8 6l8.5 3.5z" fill="#b3261e"/><circle cx="20" cy="20" r="6" fill="#1c1915"/>`,
  };

  function die(face, size = 64, opts = {}) {
    const ring = opts.selected ? `<rect x="1" y="1" width="38" height="38" rx="7" fill="none" stroke="#ffd23f" stroke-width="3"/>` : "";
    return `<svg width="${size}" height="${size}" viewBox="0 0 40 40" aria-label="${face}">
      <rect x="2" y="3" width="36" height="36" rx="6" fill="#0c0b08" opacity=".35"/>
      <rect x="2" y="1.5" width="36" height="36" rx="6" fill="#f3ecd9" stroke="#1c1915" stroke-width="1.8"/>
      <g transform="translate(0,-0.5)">${glyphs[face]}</g>${ring}</svg>`;
  }

  window.BBDice = { die };
})();
