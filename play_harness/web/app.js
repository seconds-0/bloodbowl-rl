/* Play harness client. The server owns the match; this client only renders
   state and submits action ids taken from the server's annotated legal list.
   Planning a path is local; executing it submits one validated STEP at a time. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s === undefined || s === null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const ACT_KINDS = ["MOVE", "BLOCK", "BLITZ", "PASS", "HANDOFF", "FOUL", "TTM", "SECURE_BALL",
    "STAB", "GAZE", "KTM", "CHAINSAW", "BREATHE_FIRE", "VOMIT"];
  const KIND_NAMES = { MOVE: "Move", BLOCK: "Block", BLITZ: "Blitz", PASS: "Pass", HANDOFF: "Hand-off",
    FOUL: "Foul", TTM: "Throw team-mate", SECURE_BALL: "Secure the ball", STAB: "Stab",
    GAZE: "Hypnotic Gaze", KTM: "Kick team-mate", CHAINSAW: "Chainsaw", BREATHE_FIRE: "Breathe Fire",
    VOMIT: "Projectile Vomit" };
  const KIND_KEYS = { MOVE: "m", BLOCK: "b", BLITZ: "z", PASS: "p", HANDOFF: "h", FOUL: "f",
    SECURE_BALL: "s", TTM: "t", KTM: "k", STAB: "x", GAZE: "g", CHAINSAW: "c", BREATHE_FIRE: "r",
    VOMIT: "v" };
  const FACE_NAMES = { skull: "Attacker down", both: "Both down", push: "Push", stumble: "Stumble", pow: "Pow" };
  const SPEEDS = [0, 150, 300, 450, 600, 900, 1300, 2000, 3000];
  const ERRORS = {
    stale_state_version: "The board changed before that move arrived. It shows the current position now.",
    not_your_decision: "The bot is deciding right now.",
    unknown_action: "That option is no longer available.",
    path_not_legal: "That path is no longer available.",
    match_over: "The match is over.",
    no_game: "No game is running.",
    server_error: "The server hit an error. The game state is unchanged.",
  };

  const App = {
    ws: null, rid: 0, connected: false, screen: null,
    lobby: null, lobbyOpts: null, header: null,
    snapshot: null, display: null, legal: null,
    queue: [], playing: false, paused: false, stepOnce: false, delay: 600, wake: null,
    gen: 0, gameId: null, snapVersion: -1,
    batchPolicy: 0, batchIndex: 0,
    log: [], botFrames: [], lastBotFrame: null, botTurnSteps: [],
    busy: false, clock: null, pitchApi: null,
    ui: { sel: null, planDest: null, hover: null, kickSel: null, dialogHidden: false, flag: null,
      menu: null, confirm: null, overlay: null, odds: {}, lastVersion: -1, surveys: {} },
    promptsSeen: new Set(), submittedTypes: new Set(), renderedIds: new Set(),
  };
  window.__bb = App;
  // Read-only probes for the end-to-end suite.
  window.__bbApi = {
    humanTurn: () => humanTurn(),
    promptKind: () => (prompt() ? prompt().kind : null),
    version: () => (App.display ? App.display.state_version : -1),
    coverage: () => ({ prompts: Array.from(App.promptsSeen), submitted: Array.from(App.submittedTypes) }),
  };

  // ---------------------------------------------------------------- network
  function connect() {
    const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
    App.ws = ws;
    ws.onopen = () => { App.connected = true; send({ t: "lobby" }); };
    ws.onmessage = (ev) => handle(JSON.parse(ev.data));
    ws.onclose = () => {
      App.connected = false;
      toast("Connection to the play server lost. Reconnecting.", true);
      setTimeout(connect, 1200);
    };
  }

  // Commands about the current game carry its id so the server refuses them
  // once another game has replaced it.
  const GAME_MSGS = new Set(["submit", "submit_path", "path_odds", "ready", "view", "flag", "survey", "replay_flag"]);

  function send(msg) {
    if (!App.ws || App.ws.readyState !== 1) return null;
    msg.v = 1;
    if (App.gameId && GAME_MSGS.has(msg.t)) msg.game_id = App.gameId;
    msg.rid = ++App.rid;
    App.ws.send(JSON.stringify(msg));
    return msg.rid;
  }

  function submit(actionId, follow) {
    if (App.busy || !App.legal) return;
    const a = App.legal.actions.find((x) => x.id === actionId);
    App.submittedTypes.add(a ? a.type : "SETUP_PLACE");
    App.busy = true;
    closeMenu();
    const msg = { t: "submit", state_version: App.legal.state_version, action_id: actionId };
    if (follow) msg.follow = follow;
    send(msg);
  }

  function handle(m) {
    switch (m.t) {
      case "hello":
        App.hasGame = m.has_game;
        break;
      case "lobby":
        App.lobby = m;
        if (!App.snapshot || App.screen === "lobby" || App.screen === null) {
          if (!m.has_game) showLobby();
          else if (App.screen === "lobby") renderLobby();
        }
        break;
      case "game_started":
        resetGame(m.header);
        break;
      case "game_closed":
        stopPlayback();
        App.gameId = null;
        App.snapshot = null;
        App.header = null;
        showLobby();
        break;
      case "frames":
        for (const fr of m.frames) {
          if (App.gameId && fr.game_id && fr.game_id !== App.gameId) continue;
          App.queue.push(fr);
          if (fr.actor === "policy") App.batchPolicy++;
        }
        pump();
        break;
      case "state": {
        // Ignore snapshots from a replaced game or older than the one on screen.
        const gid = m.snapshot.header && m.snapshot.header.game_id;
        if (App.gameId && gid && gid !== App.gameId) break;
        if (gid && gid === App.gameId && m.snapshot.state.state_version < App.snapVersion) break;
        if (gid) App.gameId = gid;
        App.snapVersion = m.snapshot.state.state_version;
        App.snapshot = m.snapshot;
        App.header = m.snapshot.header;
        if (App.screen !== "game" && App.screen !== "post") {
          if (App.screen === null || App.screen === "lobby" && !App.wantLobby) showGame();
        }
        if (!App.playing && App.queue.length === 0) applySnapshot();
        break;
      }
      case "ack":
        break;
      case "error":
        App.busy = false;
        toast(ERRORS[m.reason] || `Refused: ${m.reason}`, true);
        break;
      case "path_odds":
        App.ui.oddsPending = null;
        if (m.ok && m.steps && m.steps.length && App.legal && m.state_version === App.legal.state_version) {
          const last = m.steps[m.steps.length - 1];
          App.ui.odds[`${last.x},${last.y}`] = m;
          renderPitch();
          renderPrompt();
        }
        break;
      case "clock":
        App.clock = { info: m.clock, at: performance.now() };
        break;
      case "flagged":
        if (m.ok) {
          if (App.snapshot) App.snapshot.flags = m.flags;
          if (App.ui.flag && App.ui.flag.saving) {
            App.ui.flag = null;
            toast("Flag saved to the game record.");
          }
          render();
          if (App.screen === "post") renderPost();
        } else {
          toast("That move cannot be flagged.", true);
        }
        break;
      case "surveyed":
        if (m.ok) toast(`Survey saved to ${m.record_dir}`);
        else toast("The survey was not saved. Check the answers.", true);
        break;
      case "view":
        if (App.ui.flag && m.view && App.ui.flag.step === m.view.step) {
          App.ui.flag.view = m.view;
          renderFlagPanel();
        }
        break;
      case "replay":
        if (m.ok) onReplay(m);
        break;
      case "clock_expired":
        toast("Time ran out. The turn ended.");
        break;
    }
  }

  // ---------------------------------------------------------------- playback
  function sleepOrWake(ms) {
    return new Promise((res) => {
      const t = setTimeout(res, ms);
      App.wake = () => { clearTimeout(t); res(); };
    });
  }

  async function waitForFrame(fr) {
    if (fr.actor !== "policy") return;
    const t0 = performance.now();
    for (;;) {
      if (App.stepOnce) { App.stepOnce = false; return; }
      if (App.paused || App.ui.overlay && App.ui.overlay.hold) { await sleepOrWake(60000); continue; }
      if (!fr.think) return;
      const left = App.delay - (performance.now() - t0);
      if (left <= 0) return;
      await sleepOrWake(left);
    }
  }

  // Ends any playback loop: a sleeping pump wakes, sees the new generation and
  // returns without touching the queue of the game that replaced it.
  function stopPlayback() {
    App.gen++;
    App.queue = [];
    App.playing = false;
    App.paused = false;
    App.batchPolicy = 0;
    App.batchIndex = 0;
    wake();
  }

  async function pump() {
    if (App.playing) return;
    App.playing = true;
    const gen = App.gen;
    App.legal = null;
    render();
    while (App.queue.length) {
      const fr = App.queue[0];
      await waitForFrame(fr);
      if (gen !== App.gen) return;
      App.queue.shift();
      applyFrame(fr);
    }
    App.playing = false;
    App.batchPolicy = 0;
    App.batchIndex = 0;
    if (App.snapshot) applySnapshot();
  }

  function wake() { if (App.wake) App.wake(); }

  function applyFrame(fr) {
    App.display = fr.state;
    App.legal = null;
    for (const e of fr.log) App.log.push(e);
    if (App.log.length > 600) App.log.splice(0, App.log.length - 600);
    const bot = botSeat();
    if (fr.actor === "policy") {
      App.batchIndex++;
      App.lastBotFrame = fr;
      App.botFrames.push(fr);
      if (App.botFrames.length > 800) App.botFrames.splice(0, App.botFrames.length - 800);
    }
    for (const e of fr.log) {
      if ((e.kind === "turn" && e.team === bot) || e.kind === "half" || e.kind === "td") App.botTurnSteps = [];
      if (e.kind === "half" && e.parts[0].t === "Second half") {
        showOverlay({ title: "Half time", sub: scoreLine(), hold: true, button: "Start the second half" });
      }
      if (e.kind === "td") showOverlay({ title: "Touchdown", sub: e.parts.map((p) => p.t).join(""), ms: 1800, team: e.team });
      if (e.kind === "event" && e.parts[0].t === "Turnover" && e.team === humanSeat()) {
        showOverlay({ title: "Turnover", sub: "", ms: 1300, team: e.team });
      }
    }
    if (fr.actor === "policy" || (fr.team === bot)) App.botTurnSteps.push(fr);
    if (App.botTurnSteps.length > 400) App.botTurnSteps.splice(0, App.botTurnSteps.length - 400);
    render();
  }

  function applySnapshot() {
    const s = App.snapshot;
    if (!s) return;
    App.display = s.state;
    App.legal = s.legal;
    App.busy = false;
    if (s.log) App.log = s.log.slice();
    App.clock = { info: s.clock, at: performance.now() };
    if (s.state.state_version !== App.ui.lastVersion) {
      App.ui.lastVersion = s.state.state_version;
      App.ui.sel = keepSetupSelection();
      App.ui.planDest = null;
      App.ui.kickSel = null;
      App.ui.dialogHidden = false;
      App.ui.confirm = null;
      App.ui.odds = {};
      App.ui.oddsPending = null;
      closeMenu();
    }
    if (App.screen === "lobby") return;  // the lobby stays put until a new game starts
    if (s.legal && s.legal.prompt) App.promptsSeen.add(s.legal.prompt.kind);
    if (s.state.awaiting === "human") send({ t: "ready", state_version: s.state.state_version });
    if (s.state.awaiting === "over") {
      showPost();
      return;
    }
    if (App.screen === "post") showGame();
    render();
    if (s.legal && s.legal.prompt && s.legal.prompt.kind === "declare_action") openDeclareMenu();
  }

  function keepSetupSelection() {
    const p = App.legal && App.legal.prompt;
    if (!p || !["setup", "solid_defence", "quick_snap"].includes(p.kind)) return null;
    const sel = App.ui.sel;
    if (sel === null) return null;
    const rows = (App.legal.compact && App.legal.compact.SETUP_PLACE) || [];
    return rows.some((r) => r[1] === sel) ? sel : null;
  }

  // ---------------------------------------------------------------- helpers
  const humanSeat = () => (App.display ? App.display.human_seat : 0);
  const botSeat = () => 1 - humanSeat();
  const sideCls = (team) => (team === 0 ? "home" : "away");
  const humanTurn = () => !!(App.legal && App.legal.awaiting === "human" && !App.playing && App.queue.length === 0);
  const prompt = () => (humanTurn() ? App.legal.prompt : null);
  const acts = (type) => (App.legal ? App.legal.actions.filter((a) => a.type === type) : []);
  const player = (slot) => (App.display ? App.display.players.find((p) => p.slot === slot) : null);
  const teamName = (t) => (App.display ? App.display.teams[t].name : "");
  const scoreLine = () => (App.display
    ? `${teamName(0)} ${App.display.teams[0].score} : ${App.display.teams[1].score} ${teamName(1)}` : "");

  function abbr(p) {
    if (!p || !p.position) return "?";
    const team = teamName(p.team).toLowerCase().split(/\s+/);
    let words = p.position.split(/\s+/).filter((w) => !team.includes(w.toLowerCase()));
    if (!words.length) words = p.position.split(/\s+/);
    if (words.length === 1) return words[0].slice(0, 2);
    return (words[0][0] + words[1][0]).toUpperCase();
  }

  function pname(slot) {
    const p = player(slot);
    return p ? `#${p.number} ${p.position}` : "a player";
  }

  function pspan(slot) {
    const p = player(slot);
    if (!p) return "a player";
    return `<span class="${p.team === 0 ? "h" : "a"}">#${p.number} ${esc(p.position)}</span>`;
  }

  function fmtTime(sec) {
    sec = Math.max(0, Math.round(sec));
    return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
  }

  function pct(p) {
    if (p >= 0.995) return "100%";
    if (p > 0 && p < 0.01) return "<1%";
    return `${Math.round(p * 100)}%`;
  }

  function target(v) { return v === null || v === undefined ? "-" : `${v}+`; }

  function toast(text, bad) {
    const el = $("toast");
    el.textContent = text;
    el.className = "toast" + (bad ? " bad" : "");
    el.hidden = false;
    clearTimeout(App.toastTimer);
    App.toastTimer = setTimeout(() => { el.hidden = true; }, bad ? 4200 : 2600);
  }

  function btn(label, attrs = {}, cls = "btn") {
    const a = Object.entries(attrs).map(([k, v]) => ` ${k}="${esc(v)}"`).join("");
    return `<button type="button" class="${cls}"${a}>${label}</button>`;
  }

  function actBtn(a, label, cls = "btn", key) {
    App.renderedIds.add(a.id);
    return btn(`${esc(label || a.label || a.type)}${key ? ` <span class="k">${esc(key)}</span>` : ""}`,
      { "data-legal": "1", "data-kind": "action", "data-id": a.id, "data-type": a.type }, cls);
  }

  // ---------------------------------------------------------------- screens
  function show(name) {
    App.screen = name;
    $("lobby").hidden = name !== "lobby";
    $("game").hidden = name !== "game";
    $("post").hidden = name !== "post";
    closeMenu();
  }

  function showLobby() {
    App.wantLobby = true;
    show("lobby");
    if (!App.lobby) { send({ t: "lobby" }); return; }
    renderLobby();
  }

  function showGame() {
    App.wantLobby = false;
    show("game");
    render();
  }

  function showPost() {
    show("post");
    renderPost();
  }

  function resetGame(header) {
    stopPlayback();
    App.header = header;
    App.gameId = header.game_id;
    App.snapVersion = -1;
    App.snapshot = null;
    App.legal = null;
    App.display = null;
    App.log = [];
    App.botFrames = [];
    App.botTurnSteps = [];
    App.lastBotFrame = null;
    App.paused = false;
    App.delay = header.options.think_ms;
    App.ui.flag = null;
    App.ui.overlay = null;
    App.ui.lastVersion = -1;
    App.promptsSeen = new Set();
    App.submittedTypes = new Set();
    App.ui.replays = {};
    App.wantLobby = false;
    show("game");
  }

  // ---------------------------------------------------------------- lobby
  function lobbyDefaults() {
    const L = App.lobby;
    const prev = App.header ? App.header.options : null;
    return Object.assign({}, L.defaults, {
      checkpoint: L.default_checkpoint, human_team: 22, bot_team: 13,
      seed: Math.floor(Math.random() * 2147483646) + 1,
    }, prev ? { ...prev, seed: Math.floor(Math.random() * 2147483646) + 1 } : {});
  }

  function renderLobby() {
    const L = App.lobby;
    if (!L) return;
    if (!App.lobbyOpts) App.lobbyOpts = lobbyDefaults();
    const o = App.lobbyOpts;
    $("lobby-checkpoints").innerHTML = L.checkpoints.length ? L.checkpoints.map((c) => `
      <button type="button" class="ck${c.path === o.checkpoint ? " on" : ""}" data-legal="1" data-kind="checkpoint" data-path="${esc(c.path)}"${c.ok ? "" : " disabled"}>
        <span class="radio"></span>
        <span><div class="nm">${esc(c.label)}</div><div class="sub">${c.ok ? esc(c.path.split("/").slice(-2).join("/")) : esc(c.error)}</div></span>
        <span class="sha">${esc(c.sha8 || "no lineage")}</span>
      </button>`).join("") : `<p class="muted">No checkpoints with a lineage sidecar under .play-artifacts/checkpoints.</p>`;
    const opts = (id, key, items) => {
      $(id).innerHTML = items.map(([v, label]) =>
        `<button type="button" class="opt${o[key] === v ? " on" : ""}" data-legal="1" data-kind="opt" data-key="${key}" data-value="${esc(v)}">${esc(label)}</button>`).join("");
    };
    opts("lobby-mode", "mode", [["sample", "Sampling"], ["argmax", "Argmax"]]);
    $("lobby-mode-help").textContent = o.mode === "sample" ? "Sampling is the policy as examined." : "Argmax always takes the top option.";
    opts("lobby-rosters", "roster_mode", [["random", "Random for both"], ["both", "Pick both teams"], ["mine", "Pick your team"]]);
    opts("lobby-side", "human_side", [["home", "Home"], ["away", "Away"], ["random", "Random"]]);
    opts("lobby-clock", "clock_mode", [["off", "Off"], ["display", "Display only"], ["soft", "Soft limit"]]);
    const teams = L.teams.slice().sort((a, b) => a.name.localeCompare(b.name));
    const teamOpts = (sel) => teams.map((t) => `<option value="${t.id}"${t.id === sel ? " selected" : ""}>${esc(t.name)}</option>`).join("");
    $("lobby-human-team").innerHTML = teamOpts(o.human_team);
    $("lobby-bot-team").innerHTML = teamOpts(o.bot_team);
    $("lobby-team-pickers").hidden = o.roster_mode === "random";
    $("lobby-bot-team-field").hidden = o.roster_mode !== "both";
    $("lobby-clock-seconds-row").hidden = o.clock_mode !== "soft";
    $("lobby-clock-seconds").value = o.clock_seconds;
    $("lobby-think").value = o.think_ms;
    $("lobby-think-val").textContent = o.think_ms === 0 ? "(none)" : `(${(o.think_ms / 1000).toFixed(o.think_ms % 100 ? 2 : 1)} s)`;
    $("lobby-seed").value = o.seed;
    $("lobby-resume").hidden = !App.snapshot;
    $("lobby-start").disabled = !L.checkpoints.some((c) => c.ok && c.path === o.checkpoint);
  }

  function startGame() {
    const o = App.lobbyOpts;
    const seed = parseInt($("lobby-seed").value, 10);
    const options = {
      checkpoint: o.checkpoint, roster_mode: o.roster_mode, human_side: o.human_side, mode: o.mode,
      think_ms: parseInt($("lobby-think").value, 10) || 0, clock_mode: o.clock_mode,
      clock_seconds: parseInt($("lobby-clock-seconds").value, 10) || 240,
      seed: Number.isFinite(seed) ? seed : null,
    };
    if (o.roster_mode !== "random") options.human_team = parseInt($("lobby-human-team").value, 10);
    if (o.roster_mode === "both") options.bot_team = parseInt($("lobby-bot-team").value, 10);
    App.lobbyOpts = null;
    send({ t: "new_game", options });
    toast("Loading the checkpoint and starting the match.");
  }

  function bindLobby() {
    $("lobby").addEventListener("click", (ev) => {
      const b = ev.target.closest("button");
      if (!b || b.disabled) return;
      const o = App.lobbyOpts;
      if (b.dataset.kind === "checkpoint") o.checkpoint = b.dataset.path;
      else if (b.dataset.kind === "opt") o[b.dataset.key] = b.dataset.value;
      else if (b.id === "lobby-new-seed") o.seed = Math.floor(Math.random() * 2147483646) + 1;
      else if (b.id === "lobby-start") { startGame(); return; }
      else if (b.id === "lobby-resume") { showGame(); applySnapshot(); return; }
      else return;
      syncLobbyInputs();
      renderLobby();
    });
    $("lobby").addEventListener("input", () => { syncLobbyInputs(); renderLobby(); });
  }

  function syncLobbyInputs() {
    const o = App.lobbyOpts;
    o.think_ms = parseInt($("lobby-think").value, 10) || 0;
    o.clock_seconds = parseInt($("lobby-clock-seconds").value, 10) || 240;
    const seed = parseInt($("lobby-seed").value, 10);
    if (Number.isFinite(seed)) o.seed = seed;
    o.human_team = parseInt($("lobby-human-team").value, 10);
    o.bot_team = parseInt($("lobby-bot-team").value, 10);
  }

  // ---------------------------------------------------------------- render
  function render() {
    if (App.screen !== "game" || !App.display) return;
    App.renderedIds = new Set();
    renderBoard();
    renderRails();
    renderPitch();
    renderPrompt();
    renderLog();
    renderDialog();
    renderPlayback();
    renderFlagPanel();
    renderOverlay();
    updateClocks();
  }

  function renderBoard() {
    const s = App.display, H = App.header;
    const human = humanSeat();
    const side = (t) => {
      const tm = s.teams[t];
      const coach = t === human ? "You" : esc(H.checkpoint.name.replace("chain", "Chain "));
      return `<div class="side ${sideCls(t)}">
        <div class="score">${tm.score}</div>
        <div style="min-width:0"><div class="team">${esc(tm.name)}</div><div class="coach">${coach} · ${t === 0 ? "home" : "away"}</div></div>
        <div class="res"><span class="chip">Re-rolls ${tm.rerolls + tm.bonus_rerolls}</span><span class="chip">Apo ${tm.apothecary}</span></div>
      </div>`;
    };
    const track = (t) => {
      const tm = s.teams[t];
      let out = `<div class="track"><span class="lab">${esc(tm.name)}</span>`;
      for (let i = 1; i <= 8; i++) {
        const now = i === tm.turn && s.in_team_turn[t];
        const done = i < tm.turn || (i === tm.turn && !now && tm.turn > 0);
        out += `<i class="pip ${t === 0 ? "h" : "a"}${now ? " now" : done ? " done" : ""}"></i>`;
      }
      return out + "</div>";
    };
    const proc = s.procedure ? s.procedure.proc : "";
    const half = s.half === 2 ? "2nd half" : "1st half";
    let phase = "";
    if (proc === "SETUP" || proc === "KICKOFF" || s.in_kickoff) phase = "kick-off";
    else if (s.in_team_turn[botSeat()]) phase = "bot turn";
    else if (s.in_team_turn[human]) phase = "your turn";
    $("board").innerHTML = `${side(0)}<div class="mid"><div class="half">${half}${phase ? " · " + phase : ""} <span class="clock js-clock"></span></div>${track(0)}${track(1)}</div>${side(1)}`;
  }

  function renderRails() {
    const s = App.display, H = App.header;
    const human = humanSeat(), bot = botSeat();
    const p = prompt();
    const playingBot = App.playing || (!humanTurn() && s.awaiting === "policy");
    // Turn banner
    const tb = $("turn-banner");
    let title, sub;
    if (humanTurn()) {
      const k = p.kind;
      tb.className = `banner ${sideCls(human)}`;
      if (k === "setup") title = p.kicking ? "Set up to kick" : "Set up to receive";
      else if (k === "kick_target") title = "Kick off";
      else if (s.in_kickoff) title = { touchback: "Touchback", high_kick: "High kick", solid_defence: "Solid defence", quick_snap: "Quick snap" }[k] || "Charge";
      else if (s.in_team_turn[human]) title = "Your turn";
      else title = "Your decision";
      const weather = { sweltering: "Sweltering heat", sunny: "Very sunny", perfect: "Perfect conditions", rain: "Pouring rain", blizzard: "Blizzard" }[s.weather] || s.weather;
      sub = `Turn ${Math.max(1, s.teams[human].turn)} · ${esc(weather)} <span class="clock js-clock"></span>`;
    } else {
      tb.className = `banner ${sideCls(bot)}`;
      title = s.in_team_turn[bot] ? "Bot turn" : "Bot deciding";
      sub = App.paused ? "Paused" : `Turn ${Math.max(1, s.teams[bot].turn)} · ${App.delay ? `playing at ${(App.delay / 1000).toFixed(1)} s a move` : "no delay"}`;
    }
    tb.innerHTML = `<div class="edge"></div><div class="t">${title}</div><div class="c">${sub}</div>`;

    // Player card or reserves during setup
    const pc = $("player-card");
    const setupKinds = ["setup", "solid_defence", "quick_snap"];
    if (p && setupKinds.includes(p.kind)) {
      pc.innerHTML = reservesCard();
    } else {
      const focus = focusPlayer();
      pc.innerHTML = focus !== null ? playerCard(focus) : "";
    }
    pc.hidden = pc.innerHTML === "";

    // Bot moves this turn (left rail) while the bot plays
    const mc = $("moves-card");
    mc.hidden = !playingBot || !App.botTurnSteps.length;
    if (!mc.hidden) mc.innerHTML = `<h3>Bot moves this turn</h3><div class="log movelist" style="max-height:340px">${botMoveLines(App.botTurnSteps, true)}</div>`;

    const dug = (t) => {
      const ps = s.players.filter((x) => x.team === t);
      const n = (loc) => ps.filter((x) => loc.includes(x.location)).length;
      return `<h3>Dugout · ${esc(teamName(t))}</h3><div class="dug"><div class="box"><b>Reserves</b><span>${n(["reserves"])}</span></div><div class="box"><b>KO</b><span>${n(["ko"])}</span></div><div class="box"><b>Out</b><span>${n(["cas", "sent_off"])}</span></div></div>`;
    };
    $("dugout-left").innerHTML = dug(human);
    $("dugout-left").hidden = !mc.hidden && window.innerWidth > 720;
    const used = s.used_this_turn;
    const actNow = p && p.act_kind;
    const kv = (label, key, kind) => `<dt>${label}</dt><dd>${actNow === kind ? "Using" : used[key] ? "Used" : "Open"}</dd>`;
    $("this-turn").innerHTML = `<h3>This turn</h3><dl class="kv">${kv("Blitz", "blitz", "BLITZ")}${kv("Pass", "pass", "PASS")}${kv("Hand-off", "handoff", "HANDOFF")}${kv("Foul", "foul", "FOUL")}</dl>`;
    $("this-turn").hidden = !humanTurn() || !s.in_team_turn[human];

    // Right rail
    const bb = $("bot-banner");
    bb.className = `banner ${sideCls(bot)}`;
    bb.innerHTML = `<div class="edge"></div><div class="t">${esc(H.checkpoint.name.replace("chain", "Chain "))}</div><div class="c">${esc(teamName(bot))} · ${bot === 0 ? "home" : "away"}</div>`;
    const flagOpen = !!App.ui.flag;
    $("flag-panel").hidden = !flagOpen;
    $("bot-status").hidden = flagOpen;
    $("last-bot-turn").hidden = flagOpen;
    $("dugout-right").hidden = flagOpen;
    let status = `<i class="dot live"></i>Waiting for you`;
    if (App.paused && App.queue.length) status = `<i class="dot"></i>Playback paused`;
    else if (playingBot) status = `<i class="dot busy"></i>Bot is playing`;
    $("bot-status").innerHTML = `<div class="status">${status}</div>
      <dl class="kv"><dt>Checkpoint</dt><dd>${esc(H.checkpoint.sha8)}</dd><dt>Play</dt><dd>${H.options.mode === "sample" ? "Sampling" : "Argmax"}</dd>
      <dt>Move delay</dt><dd>${(App.delay / 1000).toFixed(1)} s</dd><dt>Seed</dt><dd>${H.options.seed}</dd></dl>
      <div class="actions" style="margin-top:8px">${btn("New game", { "data-kind": "to-lobby", "data-legal": "1" }, "btn ghost wide")}</div>`;
    const lastTurn = App.botTurnSteps.length ? App.botTurnSteps : [];
    $("last-bot-turn").innerHTML = `<h3>${playingBot ? "Bot moves" : "Last bot turn"}</h3>
      <div class="log movelist" style="max-height:220px">${lastTurn.length ? botMoveLines(lastTurn.slice(-40), false) : `<p class="muted">No bot moves yet.</p>`}</div>
      <div class="actions" style="margin-top:8px">${App.lastBotFrame ? btn("Flag a bot move <span class=\"k\">F</span>", { "data-kind": "open-flag", "data-legal": "1" }, "btn wide") : ""}</div>`;
    $("dugout-right").innerHTML = dug(bot);
  }

  function botMoveLines(frames, current) {
    const lines = [];
    const curStep = App.lastBotFrame ? App.lastBotFrame.step : -1;
    for (const fr of frames) {
      for (const e of fr.log) {
        if (e.kind === "turn" || e.kind === "half") continue;
        const last = lines[lines.length - 1];
        if (e.kind === "move" && last && last.kind === "move" && last.player === e.player) {
          last.n += 1;
          last.step = fr.step;
          continue;
        }
        lines.push({ kind: e.kind, player: e.player, parts: e.parts, n: 1, step: fr.step, policy: fr.actor === "policy" });
      }
    }
    return lines.slice(-24).map((ln) => {
      let html = partsHtml(ln.parts);
      if (ln.kind === "move") html += ln.n > 1 ? ` ${ln.n} squares` : " 1 square";
      const cur = current && ln.step === curStep ? " cur" : "";
      return `<p class="${cur.trim()}" data-kind="flag-step" data-step="${ln.step}">${html}</p>`;
    }).join("");
  }

  function partsHtml(parts) {
    return parts.map((pt) => pt.team === null || pt.team === undefined ? esc(pt.t)
      : `<span class="${pt.team === 0 ? "h" : "a"}">${esc(pt.t)}</span>`).join("");
  }

  function focusPlayer() {
    const p = prompt();
    if (App.ui.hover && App.ui.hover.slot !== undefined) return App.ui.hover.slot;
    if (p && p.player !== undefined && p.player !== null) return p.player;
    if (p && p.attacker !== undefined) return p.attacker;
    if (App.ui.sel !== null) return App.ui.sel;
    const fr = App.lastBotFrame;
    if (!humanTurn() && fr && fr.state.procedure && fr.state.procedure.a < 32 &&
      ["MOVE", "ACTIVATION", "BLOCK"].includes(fr.state.procedure.proc)) return fr.state.procedure.a;
    return null;
  }

  function playerCard(slot) {
    const p = player(slot);
    if (!p) return "";
    const pr = prompt();
    let sub = esc(teamName(p.team));
    if (pr && pr.player === slot && pr.act_kind) sub += ` · ${KIND_NAMES[pr.act_kind] || pr.act_kind} declared`;
    else if (p.location !== "on_pitch") sub += ` · ${p.location.replace("_", " ")}`;
    else if (p.stance !== "standing") sub += ` · ${p.stance === "prone" ? "down" : "stunned"}`;
    const ag = p.ag ? `${p.ag}+` : "-", pa = p.pa ? `${p.pa}+` : "-";
    const moveBar = pr && pr.kind === "move" && pr.player === slot
      ? `<div class="meter"><span>Moved</span><span>${p.moved} of ${p.ma} · ${Math.max(0, 2 - p.rushes)} rushes left</span></div><div class="bar"><i style="width:${Math.min(100, 100 * p.moved / Math.max(1, p.ma))}%"></i></div>` : "";
    return `<div class="pname">#${p.number} ${esc(p.position)}</div><div class="psub">${sub}</div>
      <div class="stats"><div><b>MA</b><span>${p.ma}</span></div><div><b>ST</b><span>${p.st}</span></div><div><b>AG</b><span>${ag}</span></div><div><b>PA</b><span>${pa}</span></div><div><b>AV</b><span>${p.av}+</span></div></div>
      <div class="skills">${p.skills.map((k) => `<span class="skill">${esc(k)}</span>`).join("") || `<span class="muted">No skills</span>`}</div>${moveBar}`;
  }

  function placeRows() {
    return (App.legal && App.legal.compact && App.legal.compact.SETUP_PLACE) || [];
  }

  function reservesCard() {
    const human = humanSeat();
    const rows = placeRows();
    const placeable = new Set(rows.map((r) => r[1]));
    const removable = new Set(acts("SETUP_REMOVE").map((a) => a.player));
    const res = App.display.players.filter((x) => x.team === human && x.location === "reserves");
    let html = `<h3>Reserves</h3><div class="roster" id="reserve-list">`;
    html += res.length ? res.map((x) => {
      const legal = placeable.has(x.slot);
      return `<button type="button" class="rrow ${sideCls(human)}${App.ui.sel === x.slot ? " sel" : ""}" data-kind="reserve" data-slot="${x.slot}"${legal ? ' data-legal="1"' : " disabled"}>
        <span class="tok">${esc(abbr(x))}</span><span>#${x.number} ${esc(x.position)}</span><span class="ma">MA ${x.ma}</span></button>`;
    }).join("") : `<p class="muted">Every player is on the pitch.</p>`;
    html += `</div>`;
    if (App.ui.sel !== null && removable.has(App.ui.sel)) {
      const a = acts("SETUP_REMOVE").find((x) => x.player === App.ui.sel);
      html += `<div class="actions" style="margin-top:8px">${actBtn(a, `Send #${player(App.ui.sel).number} to reserves`, "btn wide")}</div>`;
    }
    return html;
  }

  // ---------------------------------------------------------------- pitch scene
  function sceneFor() {
    const s = App.display;
    const p = prompt();
    const human = humanSeat();
    const scene = { players: [], highlights: [], targets: [], pushArrows: [], hits: [], labels: [], path: [] };
    const legalPlayers = new Set();
    const addHit = (x, y, kind, data, legal = true) => scene.hits.push({ x, y, legal, data: Object.assign({ kind }, data) });

    if (p) {
      const k = p.kind;
      if (["setup", "solid_defence", "quick_snap"].includes(k)) {
        const f = p.formation;
        const hx = f ? f.half_x : human === 0 ? [0, 12] : [13, 25];
        for (let x = hx[0]; x <= hx[1]; x++) for (let y = 0; y < 15; y++) scene.highlights.push({ x, y, kind: "half" });
        if (f) {
          for (let y = 4; y <= 10; y++) scene.highlights.push({ x: f.los_x, y, kind: "los" });
          const lowBad = f.left_is_low_y ? f.left_wide > 2 : f.right_wide > 2;
          const highBad = f.left_is_low_y ? f.right_wide > 2 : f.left_wide > 2;
          for (let x = hx[0]; x <= hx[1]; x++) {
            if (lowBad) for (let y = 0; y <= 3; y++) scene.highlights.push({ x, y, kind: "bad" });
            if (highBad) for (let y = 11; y <= 14; y++) scene.highlights.push({ x, y, kind: "bad" });
          }
        }
        const rows = placeRows();
        const movable = new Set(rows.map((r) => r[1]));
        for (const a of acts("SETUP_REMOVE")) movable.add(a.player);
        if (App.ui.sel !== null) {
          const hv = App.ui.hover;
          for (const r of rows) {
            if (r[1] !== App.ui.sel) continue;
            const over = hv && hv.x === r[2] && hv.y === r[3];
            scene.highlights.push({ x: r[2], y: r[3], kind: over ? "drop" : "reach" });
            addHit(r[2], r[3], "place", { id: r[0], slot: r[1] });
          }
        }
        // Removals are reached by selecting a placed player (token or drag to the reserves list).
        for (const a of acts("SETUP_REMOVE")) App.renderedIds.add(a.id);
        for (const pl of s.players) {
          if (pl.team === human && pl.location === "on_pitch" && movable.has(pl.slot)) {
            legalPlayers.add(pl.slot);
            if (App.ui.sel === null || pl.slot !== App.ui.sel) addHit(pl.x, pl.y, "setup-player", { slot: pl.slot });
          }
        }
      } else if (k === "kick_target") {
        for (const a of acts("KICK_TARGET")) {
          const sel = App.ui.kickSel && App.ui.kickSel.id === a.id;
          scene.highlights.push({ x: a.x, y: a.y, kind: sel ? "target" : "lit" });
          addHit(a.x, a.y, "kick", { id: a.id });
          App.renderedIds.add(a.id);
        }
      } else if (k === "move") {
        const mover = player(p.player);
        scene.tzTeam = botSeat();
        const reach = p.reach || [];
        for (const r of reach) {
          scene.highlights.push({ x: r[0], y: r[1], kind: "reach" });
          addHit(r[0], r[1], "plan", {});
        }
        for (const a of acts("STEP")) {
          let text = "";
          if (a.rush && a.dodge) text = "2 rolls";
          else if (a.rush || a.dodge) text = `${Math.round(7 - 6 * a.p_success)}+`;
          scene.highlights.push({ x: a.x, y: a.y, kind: "move", text: text.length < 4 ? text : "" });
          App.renderedIds.add(a.id);
        }
        for (const a of acts("JUMP")) {
          scene.highlights.push({ x: a.x, y: a.y, kind: "lit", text: "J" });
          addHit(a.x, a.y, "action", { id: a.id });
          App.renderedIds.add(a.id);
        }
        const kindLabel = { FOUL_TARGET: "Foul", HANDOFF_TARGET: "Hand-off", PASS_TARGET: "Pass", TTM_TARGET: "Throw", SPECIAL_TARGET: "Special" };
        for (const a of App.legal.actions) {
          if (a.type === "BLOCK_TARGET") {
            scene.targets.push({ x: a.x, y: a.y, kind: "block", dice: a.dice, who: a.who_picks });
            addHit(a.x, a.y, "target", { id: a.id });
            App.renderedIds.add(a.id);
          } else if (kindLabel[a.type]) {
            const occupied = a.target_player !== null && a.target_player !== undefined;
            if (a.type === "PASS_TARGET" && !occupied) {
              scene.highlights.push({ x: a.x, y: a.y, kind: "lit" });
            } else {
              scene.targets.push({ x: a.x, y: a.y, kind: "other", text: kindLabel[a.type] });
            }
            addHit(a.x, a.y, "target", { id: a.id });
            App.renderedIds.add(a.id);
          }
        }
        if (mover) {
          const dest = App.ui.planDest || (App.ui.hover && App.ui.hover.plan ? App.ui.hover : null);
          if (dest) {
            const sq = pathTo(dest, reach, mover);
            const odds = App.ui.odds[`${dest.x},${dest.y}`];
            scene.pathFrom = { x: mover.x, y: mover.y };
            scene.path = sq.map((q, i) => {
              const o = odds && odds.steps[i];
              return { x: q[0], y: q[1], step: i + 1, dodge: o && o.dodge ? `${o.dodge}+` : null, rush: o && o.rush ? `${o.rush}+` : null };
            });
            if (odds && sq.length) scene.labels.push({ x: dest.x, y: dest.y, text: pct(odds.p_success) });
            requestOdds(sq);
          }
        }
      } else if (k === "push_square") {
        const pushee = player(p.pushee);
        for (const a of acts("PUSH_SQUARE")) {
          const onPitch = a.x >= 0 && a.x < 26 && a.y >= 0 && a.y < 15;
          scene.pushArrows.push({ x: a.x, y: a.y, fromX: pushee ? pushee.x : a.x, fromY: pushee ? pushee.y : a.y, crowd: a.push_kind === "crowd", hover: App.ui.hover && App.ui.hover.id === String(a.id) });
          const hx = Math.max(0, Math.min(25, a.x)), hy = Math.max(0, Math.min(14, a.y));
          if (onPitch || a.push_kind === "crowd") addHit(hx, hy, "action", { id: a.id });
          App.renderedIds.add(a.id);
        }
      } else if (k === "follow_up") {
        const f = acts("FOLLOW_UP").find((a) => a.follow);
        if (f && p.vacated) {
          scene.highlights.push({ x: p.vacated[0], y: p.vacated[1], kind: "vacated" });
          addHit(p.vacated[0], p.vacated[1], "action", { id: f.id });
        }
      }
      for (const a of App.legal.actions) {
        if (a.type === "ACTIVATE") {
          const pl = player(a.player);
          if (pl && pl.x !== null) { legalPlayers.add(pl.slot); addHit(pl.x, pl.y, "activate", { id: a.id }); App.renderedIds.add(a.id); }
        } else if (a.type === "TOUCHBACK") {
          if (a.player !== undefined && a.player !== null) {
            const pl = player(a.player);
            if (pl && pl.x !== null) { legalPlayers.add(pl.slot); addHit(pl.x, pl.y, "action", { id: a.id }); App.renderedIds.add(a.id); }
          } else {
            scene.highlights.push({ x: a.x, y: a.y, kind: "lit" });
            addHit(a.x, a.y, "action", { id: a.id });
            App.renderedIds.add(a.id);
          }
        } else if (a.type === "CHOOSE_OPTION" && a.player !== undefined && a.player !== null) {
          const pl = player(a.player);
          if (pl && pl.x !== null) { legalPlayers.add(pl.slot); addHit(pl.x, pl.y, "action", { id: a.id }); }
        }
      }
    } else if (App.lastBotFrame && !humanTurn()) {
      const fr = App.lastBotFrame;
      const [t, , x, y] = fr.action;
      const squareTypes = [4, 5, 9, 11, 12, 13, 14, 15, 16, 21, 29];
      if (squareTypes.includes(t) && x < 26 && y < 15) {
        scene.highlights.push({ x, y, kind: botSeat() === 0 ? "ghosth" : "ghost" });
        const taken = fr.view && fr.view.alternatives.find((a) => a.taken);
        if (taken && [12, 13, 14, 15, 16, 29].includes(t)) scene.labels.push({ x, y, text: taken.label.split(" ")[0], fill: botSeat() === 0 ? "#c3142f" : "#2a3fbf" });
      }
    }

    // One hit per square. A reachable square that is also a target (a pass or
    // throw onto an empty square) opens a small menu instead of hiding one option.
    const bySquare = new Map();
    for (const h of scene.hits) {
      const key = `${h.x},${h.y}`;
      if (!bySquare.has(key)) bySquare.set(key, []);
      bySquare.get(key).push(h);
    }
    scene.hits = [];
    for (const list of bySquare.values()) {
      const plan = list.find((h) => h.data.kind === "plan");
      const others = list.filter((h) => h.data.kind !== "plan");
      if (plan && others.length) {
        scene.hits.push({ x: plan.x, y: plan.y, legal: true, data: { kind: "choice", ids: others.map((h) => h.data.id).join(",") } });
      } else {
        scene.hits.push(list[0]);
      }
    }

    const selected = new Set();
    if (p && p.player !== undefined && p.player !== null) selected.add(p.player);
    if (p && p.attacker !== undefined) selected.add(p.attacker);
    if (App.ui.sel !== null) selected.add(App.ui.sel);
    if (!p && App.lastBotFrame && App.display.procedure && ["MOVE", "BLOCK", "ACTIVATION"].includes(App.display.procedure.proc) && App.display.procedure.a < 32) selected.add(App.display.procedure.a);
    for (const pl of s.players) {
      if (pl.location !== "on_pitch") continue;
      scene.players.push({
        slot: pl.slot, team: pl.team, x: pl.x, y: pl.y, pos: abbr(pl), num: pl.number, big: pl.st >= 5,
        state: pl.stance, used: pl.flags.includes("used"), ball: pl.has_ball,
        selected: selected.has(pl.slot), legal: legalPlayers.has(pl.slot) && !selected.has(pl.slot),
      });
    }
    const b = s.ball;
    if ((b.state === "on_ground" || b.state === "in_air") && b.x < 26 && b.y < 15) scene.groundBall = { x: b.x, y: b.y };
    return scene;
  }

  function pathTo(dest, reach, mover) {
    const map = new Map(reach.map((r) => [`${r[0]},${r[1]}`, r]));
    const out = [];
    let cur = map.get(`${dest.x},${dest.y}`);
    let guard = 0;
    while (cur && guard++ < 40) {
      out.unshift([cur[0], cur[1]]);
      if (cur[5] === mover.x && cur[6] === mover.y) break;
      cur = map.get(`${cur[5]},${cur[6]}`);
    }
    return out;
  }

  function requestOdds(squares) {
    if (!squares.length || !App.legal) return;
    const key = `${squares[squares.length - 1][0]},${squares[squares.length - 1][1]}`;
    const pending = `${App.legal.state_version}:${key}`;
    if (App.ui.odds[key] || App.ui.oddsPending === pending) return;
    App.ui.oddsPending = pending;
    send({ t: "path_odds", state_version: App.legal.state_version, squares });
  }

  function renderPitch() {
    if (App.screen !== "game" || !App.display) return;
    App.pitchApi = BBPitch.render($("pitch"), sceneFor());
  }

  // ---------------------------------------------------------------- prompt card
  function renderPrompt() {
    const card = $("prompt-card");
    const p = prompt();
    const logCard = $("log-card");
    if (!p) {
      card.hidden = true;
      logCard.innerHTML = `<h3>Game log</h3><div class="log" id="log"></div>`;
      renderLog();
      return;
    }
    card.hidden = false;
    const k = p.kind;
    let what = "Choose an option", tags = [], buttons = [];
    const human = humanSeat();
    const setupKinds = ["setup", "solid_defence", "quick_snap"];
    if (setupKinds.includes(k)) {
      what = k === "setup" ? "Drag players into your half" : k === "solid_defence" ? "Solid defence: reposition players" : "Quick snap: move players one square";
      tags.push(`<span class="tag">${App.ui.sel === null ? "Pick a player, then a lit square" : `Placing #${player(App.ui.sel).number} ${esc(player(App.ui.sel).position)}`}</span>`);
      const f = p.formation;
      if (f) {
        if (f.left_wide > 2) tags.push(`<span class="tag risk">Left wide zone has ${f.left_wide} of 2</span>`);
        if (f.right_wide > 2) tags.push(`<span class="tag risk">Right wide zone has ${f.right_wide} of 2</span>`);
      }
      const done = acts("SETUP_DONE")[0];
      buttons.push(done ? actBtn(done, "End setup", `btn team ${sideCls(human)}`)
        : `<button type="button" class="btn team ${sideCls(human)}" disabled data-kind="end-setup-disabled">End setup</button>`);
      logCard.innerHTML = formationCard(p);
    } else {
      logCard.innerHTML = `<h3>Game log</h3><div class="log" id="log"></div>`;
      if (k === "kick_target") {
        what = "Pick where to kick";
        tags.push(`<span class="tag">Click a square in the receiving half</span>`);
        const sel = App.ui.kickSel;
        buttons.push(sel ? btn("Kick off", { "data-legal": "1", "data-kind": "action", "data-id": sel.id }, `btn team ${sideCls(human)}`)
          : `<button type="button" class="btn team ${sideCls(human)}" disabled>Kick off</button>`);
      } else if (k === "select_player" || k === "charge") {
        what = k === "charge" ? "Charge: activate a player" : "Pick a player to activate";
        tags.push(`<span class="tag">${p.can_act} can act</span>`);
        if (p.stalling_carrier !== undefined) tags.push(`<span class="tag risk">#${player(p.stalling_carrier).number} can score without a roll</span>`);
        for (const a of acts("END_TURN")) buttons.push(btn(`${k === "charge" ? "End charge" : "End turn"} <span class="k">Ctrl+T</span>`, { "data-legal": "1", "data-kind": "end-turn", "data-id": a.id }, `btn team ${sideCls(human)}`));
        for (const a of acts("END_TURN")) App.renderedIds.add(a.id);
      } else if (k === "declare_action") {
        what = `Declare an action for ${esc(pname(p.player))}`;
        for (const a of acts("DECLARE")) buttons.push(actBtn(a, KIND_NAMES[a.kind] || a.label, "btn", (KIND_KEYS[a.kind] || "").toUpperCase()));
      } else if (k === "move") {
        const act = KIND_NAMES[p.act_kind] || "Move";
        what = App.ui.planDest ? `Plan the ${act.toLowerCase()} path` : `${act}: ${esc(pname(p.player))}`;
        const odds = App.ui.planDest && App.ui.odds[`${App.ui.planDest.x},${App.ui.planDest.y}`];
        if (odds) {
          for (const st of odds.steps) {
            if (st.dodge) tags.push(`<span class="tag risk">Dodge ${st.dodge}+</span>`);
            if (st.rush) tags.push(`<span class="tag risk">Rush ${st.rush}+</span>`);
            if (st.pickup) tags.push(`<span class="tag risk">Pick-up ${st.pickup}+</span>`);
          }
          tags.push(`<span class="tag ${sideCls(human)}">${pct(odds.p_success)} before re-rolls</span>`);
        } else if (!App.ui.planDest) {
          tags.push(`<span class="tag">Click a square to plan, click it again to move</span>`);
        }
        const blocks = acts("BLOCK_TARGET");
        if (blocks.length) tags.push(`<span class="tag">Block ${blocks[0].dice} ${blocks[0].dice === 1 ? "die" : "dice"}, ${blocks[0].who_picks === "you" ? "you pick" : "bot picks"}</span>`);
        if (App.ui.planDest) {
          buttons.push(btn(`Move along path <span class="k">Enter</span>`, { "data-legal": "1", "data-kind": "go-path" }, "btn primary"));
          buttons.push(btn(`Clear path <span class="k">Esc</span>`, { "data-kind": "clear-path" }));
        }
        for (const a of acts("STAND_UP")) buttons.push(actBtn(a, "Stand up"));
        for (const a of acts("SECURE_BALL")) buttons.push(actBtn(a, "Secure the ball"));
        for (const a of acts("END_ACTIVATION")) buttons.push(actBtn(a, "End activation", "btn ghost"));
      } else if (k === "touchback") {
        what = "Touchback: give the ball to a player";
      } else if (k === "high_kick") {
        what = "High kick: send a player under the ball";
        for (const a of acts("CHOOSE_OPTION").filter((x) => x.decline)) buttons.push(actBtn(a, "Decline"));
      } else if (k === "interception_choice") {
        what = "Pick an interceptor";
        for (const a of acts("CHOOSE_OPTION").filter((x) => x.decline)) buttons.push(actBtn(a, "No interception"));
      } else if (k === "push_square") {
        what = `Push ${esc(pname(p.pushee))}`;
        tags.push(`<span class="tag">Click an arrow square</span>`);
      } else if (dialogKinds.includes(k)) {
        what = dialogTitle(p);
        if (p.dice) {
          const picker = (p.defender_chooses ? p.defender >> 4 : p.attacker >> 4) === human ? "you pick" : "bot picks";
          tags.push(`<span class="tag ${sideCls(human)}">${p.dice.length} ${p.dice.length === 1 ? "die" : "dice"}, ${picker}</span>`);
          if (p.strength) tags.push(`<span class="tag">Strength ${p.strength[0]} against ${p.strength[1]}</span>`);
        }
        if (App.ui.dialogHidden) buttons.push(btn(`Show the dialog <span class="k">H</span>`, { "data-kind": "show-dialog" }));
      }
    }
    // Every legal option stays reachable: anything no other surface drew becomes a button here.
    const leftovers = App.legal.actions.filter((a) => !App.renderedIds.has(a.id) && !dialogOwns(p, a));
    const leftoverHtml = leftovers.map((a) => actBtn(a, a.label || a.type, "btn")).join("");
    card.innerHTML = `<div class="what">${what}</div>${tags.length ? `<div class="detail">${tags.join("")}</div>` : ""}
      <div class="actions">${buttons.join("")}${leftoverHtml}</div>`;
    if (!setupKinds.includes(k)) renderLog();
  }

  function formationCard(p) {
    const f = p.formation;
    if (!f) return `<h3>Formation</h3><div class="budget"><span class="big">${p.placements_left}</span><small>moves left</small></div>`;
    const row = (ok, label, count) => `<div class="check"><span class="mark ${ok ? "ok" : "no"}">${ok ? "✓" : "!"}</span><span>${label}</span><span class="count">${count}</span></div>`;
    return `<h3>Formation</h3><div class="checks">
      ${row(f.on_pitch === f.want_on_pitch, "Players on the pitch", `${f.on_pitch} of ${f.want_on_pitch}`)}
      ${row(f.los >= f.want_los && f.on_pitch > 0, "On the line of scrimmage", `${f.los} of ${Math.max(3, f.want_los)}`)}
      ${row(f.left_wide <= 2, "Left wide zone", `${f.left_wide} of 2`)}
      ${row(f.right_wide <= 2, "Right wide zone", `${f.right_wide} of 2`)}
      </div><div class="budget" style="margin-top:8px"><span class="big">${p.placements_left}</span><small>setup moves left of ${p.budget || 24}</small></div>
      <div class="bar"><i style="width:${100 * (1 - p.placements_left / (p.budget || 24))}%"></i></div>`;
  }

  function renderLog() {
    const el = $("log");
    if (!el) return;
    const lines = [];
    for (const e of App.log.slice(-160)) {
      const last = lines[lines.length - 1];
      if (e.kind === "move" && last && last.kind === "move" && last.player === e.player) { last.n++; continue; }
      lines.push({ ...e, n: 1 });
    }
    el.innerHTML = lines.slice(-60).map((e) => {
      let html = partsHtml(e.parts);
      if (e.kind === "move") html += e.n > 1 ? ` ${e.n} squares` : " 1 square";
      const cls = ["turn", "half", "td"].includes(e.kind) ? e.kind : e.kind === "roll" ? "roll" : "";
      return `<p class="${cls}">${html}</p>`;
    }).join("");
    el.scrollTop = el.scrollHeight;
  }

  // ---------------------------------------------------------------- dialogs
  const dialogKinds = ["coin_toss_choice", "block_reroll", "block_choose_die", "test_reroll", "activation_reroll",
    "wrestle_attacker", "wrestle_defender", "stand_firm", "follow_up", "apothecary", "apothecary_result",
    "apothecary_ko", "argue_the_call", "high_kick", "interception_choice"];
  const DIALOG_TYPES = ["CHOOSE_DIE", "USE_REROLL", "DECLINE_REROLL", "USE_SKILL", "DECLINE_SKILL", "FOLLOW_UP", "APOTHECARY", "CHOOSE_OPTION"];

  function dialogOwns(p, a) {
    return p && dialogKinds.includes(p.kind) && DIALOG_TYPES.includes(a.type);
  }

  function dialogTitle(p) {
    const k = p.kind;
    if (k === "coin_toss_choice") return "You won the coin toss";
    if (k === "block_reroll" || k === "block_choose_die") return `Block ${esc(pname(p.defender))}`;
    if (k === "test_reroll") return `${esc(p.test_name || "Roll")} failed (${p.target}+)`;
    if (k === "activation_reroll") return `${esc(pname(p.player))} failed (${p.target}+)`;
    if (k === "wrestle_attacker" || k === "wrestle_defender") return "Use Wrestle?";
    if (k === "stand_firm") return "Use Stand Firm?";
    if (k === "follow_up") return "Follow up?";
    if (k === "apothecary") return `${esc(pname(p.player))} is a casualty`;
    if (k === "apothecary_ko") return `${esc(pname(p.player))} is knocked out`;
    if (k === "apothecary_result") return "Choose the casualty result";
    if (k === "argue_the_call") return `${esc(pname(p.player))} is sent off`;
    if (k === "high_kick") return "High kick";
    if (k === "interception_choice") return "Interception";
    return "Choose an option";
  }

  function faceOutcome(key, att, dfn) {
    const has = (pl, sk) => pl && pl.skills.includes(sk);
    const A = esc(pname(att.slot)), D = esc(pname(dfn.slot));
    if (key === "pow") return `${D} down`;
    if (key === "skull") return `${A} down · turnover`;
    if (key === "push") return `${D} pushed back`;
    if (key === "stumble") return has(dfn, "Dodge") && !has(att, "Tackle") ? `${D} pushed back` : `${D} down`;
    if (key === "both") {
      const ab = has(att, "Block"), db = has(dfn, "Block");
      if (ab && db) return "Both stay up";
      if (ab) return `${D} down`;
      if (db) return `${A} down · turnover`;
      return "Both fall · turnover";
    }
    return "";
  }

  function renderDialog() {
    const layer = $("dialog-layer");
    layer.innerHTML = "";
    const p = prompt();
    if (!p || !dialogKinds.includes(p.kind)) return;
    if (App.ui.dialogHidden) {
      layer.innerHTML = btn(`Show the dialog <span class="k">H</span>`, { "data-kind": "show-dialog" }, "btn dlg-show");
      return;
    }
    const human = humanSeat();
    const k = p.kind;
    const involved = [];
    const addP = (slot) => { const pl = player(slot); if (pl && pl.x !== null) involved.push([pl.x, pl.y]); };
    let head = dialogTitle(p), who = "", body = "";
    const hideBtn = btn(`Hide <span class="k">H</span>`, { "data-kind": "hide-dialog" }, "btn ghost");
    const buttons = (types, labels = {}) => App.legal.actions.filter((a) => types.includes(a.type))
      .map((a) => actBtn(a, labels[a.type + ":" + a.arg] || labels[a.type] || a.label, "btn", a.type === "USE_REROLL" && a.source === "TEAM" ? "R" : undefined)).join("");
    if (k === "block_reroll" || k === "block_choose_die") {
      addP(p.attacker); addP(p.defender);
      const att = player(p.attacker), dfn = player(p.defender);
      const pickerTeam = p.defender_chooses ? p.defender >> 4 : p.attacker >> 4;
      const youPick = pickerTeam === human;
      who = `<span class="who${youPick ? "" : " them"}">${youPick ? "You pick" : "Bot picks"}</span>`;
      const decline = acts("DECLINE_REROLL")[0];
      const choose = acts("CHOOSE_DIE");
      const faces = (p.dice_keys || []).map((key, i) => {
        const outcome = att && dfn ? faceOutcome(key, att, dfn) : "";
        const inner = `<div class="die">${BBDice.die(key, 52)}</div><div class="n">${esc(FACE_NAMES[key] || key)}</div><div class="o">${outcome}</div>`;
        let attrs = "";
        if (k === "block_choose_die") {
          const a = choose.find((c) => c.die_index === i);
          if (a) { App.renderedIds.add(a.id); attrs = ` data-legal="1" data-kind="action" data-id="${a.id}" data-type="CHOOSE_DIE"`; }
        } else if (youPick && decline) {
          attrs = ` data-legal="1" data-kind="die-after-decline" data-id="${decline.id}" data-die="${i}"`;
        }
        return `<button type="button" class="face"${attrs}${attrs ? "" : " disabled"}>${inner}<span class="k">${i + 1}</span></button>`;
      }).join("");
      const rr = App.legal.actions.filter((a) => a.type === "USE_REROLL").map((a) => actBtn(a, a.label, "btn", a.source === "TEAM" ? "R" : undefined)).join("");
      const keep = !youPick && decline ? actBtn(decline, "No re-roll") : "";
      if (decline && youPick) App.renderedIds.add(decline.id);
      const tm = App.display.teams[human];
      body = `<div class="dicerow">${faces}</div><div class="rr">${rr}${keep}${hideBtn}</div>
        <div class="sums"><span>Re-rolls left ${tm.rerolls + tm.bonus_rerolls}</span>${p.strength ? `<span>Strength ${p.strength[0]} against ${p.strength[1]}</span>` : ""}</div>`;
    } else if (k === "coin_toss_choice") {
      body = `<div class="rr">${buttons(["CHOOSE_OPTION"], { "CHOOSE_OPTION:0": "Kick", "CHOOSE_OPTION:1": "Receive" })}</div>`;
    } else if (k === "test_reroll" || k === "activation_reroll") {
      addP(p.player);
      body = `<div class="line">${pspan(p.player)}</div><div class="rr">${buttons(["USE_REROLL", "DECLINE_REROLL", "USE_SKILL", "DECLINE_SKILL"])}${hideBtn}</div>`;
    } else if (k.startsWith("wrestle") || k === "stand_firm") {
      addP(p.attacker); addP(p.defender); addP(p.pushee); addP(p.pusher);
      body = `<div class="rr">${buttons(["USE_SKILL", "DECLINE_SKILL"])}${hideBtn}</div>`;
    } else if (k === "follow_up") {
      addP(p.pusher); addP(p.pushee);
      if (p.vacated) involved.push(p.vacated);
      body = `<div class="rr">${buttons(["FOLLOW_UP"], { "FOLLOW_UP:1": "Follow up", "FOLLOW_UP:0": "Stay" })}${hideBtn}</div>`;
    } else if (k === "apothecary" || k === "apothecary_ko") {
      addP(p.player);
      body = `<div class="line">Apothecaries left ${App.display.teams[human].apothecary}</div><div class="rr">${buttons(["APOTHECARY"], { "APOTHECARY:1": "Use the apothecary", "APOTHECARY:0": "Keep the result" })}${hideBtn}</div>`;
    } else if (k === "apothecary_result") {
      addP(p.player);
      const r = p.rolls || [];
      body = `<div class="rr">${buttons(["CHOOSE_OPTION"], { "CHOOSE_OPTION:0": `First result (${r[0]} of 16)`, "CHOOSE_OPTION:1": `New result (${r[1]} of 16)` })}</div>`;
    } else if (k === "argue_the_call") {
      addP(p.player);
      body = `<div class="rr">${buttons(["CHOOSE_OPTION"], { "CHOOSE_OPTION:1": "Argue the call", "CHOOSE_OPTION:0": "Accept the send-off" })}${hideBtn}</div>`;
    } else if (k === "high_kick" || k === "interception_choice") {
      for (const a of acts("CHOOSE_OPTION")) if (a.player !== undefined && a.player !== null) addP(a.player);
      body = `<div class="rr">${App.legal.actions.filter((a) => a.type === "CHOOSE_OPTION").map((a) => actBtn(a, a.decline ? (k === "high_kick" ? "Decline" : "No interception") : a.label)).join("")}${hideBtn}</div>`;
    }
    layer.innerHTML = `<div class="dlg ${sideCls(human)}" id="dialog" role="dialog"><div class="head"><span class="t">${head}</span>${who}</div><div class="body">${body}</div></div>`;
    placeDialog(layer.firstElementChild, involved, p);
  }

  function placeDialog(el, involved, p) {
    if (!App.pitchApi || App.pitchApi.portrait || window.innerWidth <= 720) return;
    const frame = $("pitch");
    const B = 6; // frame border
    const W = frame.clientWidth, Hh = frame.clientHeight;
    const rects = involved.map(([x, y]) => {
      const b = App.pitchApi.squareBox(x, y);
      return { left: B + b.left - 8, top: B + b.top - 14, right: B + b.left + b.width + 8, bottom: B + b.top + b.height + 8 };
    });
    if (p && p.kind === "push_square") {
      for (const a of acts("PUSH_SQUARE")) {
        const b = App.pitchApi.squareBox(Math.max(0, Math.min(25, a.x)), Math.max(0, Math.min(14, a.y)));
        rects.push({ left: B + b.left - 6, top: B + b.top - 6, right: B + b.left + b.width + 6, bottom: B + b.top + b.height + 6 });
      }
    }
    const w = el.offsetWidth, h = el.offsetHeight;
    const area = { left: B + 4, top: B + 4, right: B + W - 4, bottom: B + Hh - 4 };
    if (!rects.length) {
      el.style.left = `${area.left + (area.right - area.left - w) / 2}px`;
      el.style.top = `${area.top + 12}px`;
      return;
    }
    const bb = rects.reduce((a, r) => ({ left: Math.min(a.left, r.left), top: Math.min(a.top, r.top), right: Math.max(a.right, r.right), bottom: Math.max(a.bottom, r.bottom) }));
    const cy = (bb.top + bb.bottom) / 2, cx = (bb.left + bb.right) / 2;
    const clampX = (x) => Math.max(area.left, Math.min(area.right - w, x));
    const clampY = (y) => Math.max(area.top, Math.min(area.bottom - h, y));
    const cands = [
      { free: area.right - bb.right, x: bb.right + 10, y: cy - h / 2 },
      { free: bb.left - area.left, x: bb.left - 10 - w, y: cy - h / 2 },
      { free: area.bottom - bb.bottom, x: cx - w / 2, y: bb.bottom + 10 },
      { free: bb.top - area.top, x: cx - w / 2, y: bb.top - 10 - h },
    ].sort((a, b) => b.free - a.free);
    const hit = (list, x, y) => list.filter((r) => x < r.right && x + w > r.left && y < r.bottom && y + h > r.top).length;
    const tokens = App.display.players.filter((pl) => pl.location === "on_pitch").map((pl) => {
      const b = App.pitchApi.squareBox(pl.x, pl.y);
      return { left: B + b.left, top: B + b.top, right: B + b.left + b.width, bottom: B + b.top + b.height };
    });
    // Never over the involved players or push squares; among the free spots,
    // cover as few other tokens as possible, then prefer the roomier side.
    let pick = null, best = Infinity;
    cands.forEach((c, order) => {
      const x = clampX(c.x), y = clampY(c.y);
      if (hit(rects, x, y)) return;
      const score = hit(tokens, x, y) * 10 + order;
      if (score < best) { best = score; pick = { x, y }; }
    });
    if (!pick) {
      // No free spot on the pitch: dock the dialog under the pitch instead.
      pick = { x: clampX(cx - w / 2), y: B + Hh + 16 };
    }
    el.style.left = `${pick.x}px`;
    el.style.top = `${pick.y}px`;
  }

  // ---------------------------------------------------------------- menus
  function closeMenu() {
    const layer = $("menu-layer");
    if (layer) layer.innerHTML = "";
    App.ui.menu = null;
  }

  function openMenuAt(slot, items, title) {
    const pl = player(slot);
    if (!pl || pl.x === null) return;
    openMenuAtSquare(pl.x, pl.y, items, title, slot);
  }

  function openMenuAtSquare(x, y, items, title, slot) {
    closeMenu();
    if (!App.pitchApi) return;
    const frame = $("pitch").getBoundingClientRect();
    const b = App.pitchApi.squareBox(x, y);
    const layer = $("menu-layer");
    layer.innerHTML = `<div class="menu" id="action-menu" role="menu"><div class="mh">${esc(title)}</div>${items.join("")}${btn("Cancel <span class=\"k\">Esc</span>", { "data-kind": "close-menu" })}</div>`;
    const m = layer.firstElementChild;
    const sx = window.scrollX, sy = window.scrollY;
    let left = frame.left + 6 + b.left + b.width + 12 + sx;
    if (left + m.offsetWidth > sx + window.innerWidth - 16) left = frame.left + 6 + b.left - m.offsetWidth - 12 + sx;
    left = Math.max(sx + 16, left);
    let top = frame.top + 6 + b.top - 8 + sy;
    top = Math.min(top, sy + window.innerHeight - m.offsetHeight - 16);
    m.style.left = `${left}px`;
    m.style.top = `${Math.max(sy + 8, top)}px`;
    App.ui.menu = { slot };
  }

  function openActivateMenu(actionId) {
    const a = App.legal.actions.find((x) => x.id === actionId);
    if (!a) return;
    const kinds = a.declare && a.declare.length ? a.declare : [];
    const items = kinds.length ? kinds.map((kind) => btn(`<span>${esc(KIND_NAMES[kind] || kind)}</span><span class="k">${esc((KIND_KEYS[kind] || "").toUpperCase())}</span>`,
      { "data-legal": "1", "data-kind": "declare", "data-id": a.id, "data-declare": kind, "data-key": KIND_KEYS[kind] || "" }))
      : [btn("Activate", { "data-legal": "1", "data-kind": "action", "data-id": a.id })];
    openMenuAt(a.player, items, pname(a.player));
  }

  function openDeclareMenu() {
    const p = prompt();
    if (!p || p.kind !== "declare_action") return;
    const items = acts("DECLARE").map((a) => btn(`<span>${esc(KIND_NAMES[a.kind] || a.label)}</span><span class="k">${esc((KIND_KEYS[a.kind] || "").toUpperCase())}</span>`,
      { "data-legal": "1", "data-kind": "action", "data-id": a.id, "data-key": KIND_KEYS[a.kind] || "" }));
    openMenuAt(p.player, items, pname(p.player));
  }

  // ---------------------------------------------------------------- playback card
  function renderPlayback() {
    const card = $("playback-card");
    const botPlaying = App.playing && App.queue.some((f) => f.actor === "policy") || (App.playing && App.lastBotFrame);
    card.hidden = !(App.playing && (App.batchPolicy > 0));
    if (card.hidden) return;
    const fr = App.lastBotFrame;
    card.innerHTML = `<h3 style="width:100%;margin:0">Bot playback</h3>
      <div class="row">
      ${btn(`${App.paused ? "Resume" : "Pause"} <span class="k">Space</span>`, { "data-kind": "pause" })}
      ${btn(`Step <span class="k">.</span>`, { "data-kind": "step" })}
      ${btn("Slower", { "data-kind": "slower" }, "btn ghost")}
      ${btn("Faster", { "data-kind": "faster" }, "btn ghost")}
      </div><div class="row">
      <span class="tag">Move ${Math.min(App.batchIndex, App.batchPolicy)} of ${App.batchPolicy}${fr ? ` · decision ${fr.step}` : ""}</span>
      ${fr ? btn(`Flag this move <span class="k">F</span>`, { "data-kind": "open-flag", "data-legal": "1" }, "btn primary") : ""}</div>`;
    void botPlaying;
  }

  // ---------------------------------------------------------------- flag panel
  function openFlag(step) {
    let fr = null;
    if (step === undefined || step === null) fr = App.lastBotFrame;
    else fr = App.botFrames.slice().reverse().find((f) => f.step <= step && f.actor === "policy");
    if (!fr) { toast("No bot move to flag yet."); return; }
    if (App.queue.length) App.paused = true;
    App.ui.flag = { step: fr.view ? fr.view.step : fr.step, frameStep: fr.step, reasons: new Set(), note: "", view: fr.view || null };
    if (!fr.view) send({ t: "view", step: fr.step });
    render();
    setTimeout(() => { const t = $("flag-note"); if (t && window.innerWidth > 720) t.focus({ preventScroll: true }); }, 0);
  }

  function renderFlagPanel() {
    const panel = $("flag-panel");
    const f = App.ui.flag;
    if (!f) { panel.hidden = true; return; }
    panel.hidden = false;
    const bot = botSeat();
    panel.className = `flagpanel ${sideCls(bot)}`;
    const v = f.view;
    const taken = v && v.alternatives.find((a) => a.taken);
    const alts = v ? v.alternatives.map((a) => `<div class="alt${a.taken ? " taken" : ""}"><span class="l">${esc(a.label)}</span><div class="b"><i style="width:${Math.max(1, Math.round(a.p * 100))}%"></i></div><span class="p">${pct(a.p)}</span></div>`).join("") : `<p class="muted">Loading the bot's options.</p>`;
    const rankWord = (r) => r === 1 ? "1st" : r === 2 ? "2nd" : r === 3 ? "3rd" : `${r}th`;
    const argmaxMode = App.header.options.mode === "argmax";
    const sampled = !v || !v.taken_rank ? "-"
      : argmaxMode ? (v.argmax_taken ? "Yes" : "No") : `${v.sampled_first ? "Yes" : "No"}, ${rankWord(v.taken_rank)} choice`;
    const reasons = (App.header.flag_reasons || []).map((r) => `<button type="button" class="reason${f.reasons.has(r) ? " on" : ""}" data-kind="reason" data-reason="${esc(r)}">${esc(r)}</button>`).join("");
    const noteVal = $("flag-note") ? $("flag-note").value : f.note;
    panel.innerHTML = `<div class="head"><div class="t">Flag this move</div><div class="s">${esc(taken ? taken.label : "Bot decision")} · decision ${f.step}</div></div>
      <div class="body">
        <div><div class="lab2">Bot's options at this decision</div><div class="alts" style="margin-top:6px">${alts}</div>
        <dl class="kv"><dt>Bot value</dt><dd>${v && v.value !== null && v.value !== undefined ? (v.value >= 0 ? "+" : "") + v.value.toFixed(2) : "-"}</dd><dt>${argmaxMode ? "Took the argmax" : "Sampled"}</dt><dd>${sampled}</dd><dt>Options</dt><dd>${v ? v.options : "-"}</dd></dl></div>
        <div><div class="lab2">What is wrong with it</div><div class="reasons" style="margin-top:6px">${reasons}</div></div>
        <textarea id="flag-note" placeholder="What should it have done?" aria-label="Flag note">${esc(noteVal)}</textarea>
        <div class="actions">${btn("Save flag", { "data-kind": "save-flag", "data-legal": "1" }, `btn team ${sideCls(bot)}`)}${btn("Cancel", { "data-kind": "close-flag" }, "btn ghost")}</div>
      </div>`;
  }

  // ---------------------------------------------------------------- overlays
  function showOverlay(o) {
    App.ui.overlay = o;
    clearTimeout(App.overlayTimer);
    if (o.ms) App.overlayTimer = setTimeout(() => { if (App.ui.overlay === o) { App.ui.overlay = null; renderOverlay(); } }, o.ms);
    renderOverlay();
  }

  function renderOverlay() {
    let el = $("pitch-overlay");
    const o = App.ui.overlay;
    if (!o) { if (el) el.remove(); return; }
    if (!el) {
      el = document.createElement("div");
      el.id = "pitch-overlay";
      $("pitchwrap").appendChild(el);
    }
    el.className = `overlay-banner ${o.team === 0 ? "home" : o.team === 1 ? "away" : ""}`;
    el.innerHTML = `<div class="ob"><div class="t">${esc(o.title)}</div>${o.sub ? `<div class="s">${esc(o.sub)}</div>` : ""}${o.button ? btn(esc(o.button), { "data-kind": "dismiss", "data-legal": "1" }, "btn primary") : ""}</div>`;
  }

  // ---------------------------------------------------------------- post-game
  function renderPost() {
    const s = App.snapshot;
    if (!s || !s.over) return;
    const st = s.state, over = s.over, H = s.header;
    const human = st.human_seat;
    const coach = (t) => t === human ? "You" : `${esc(H.checkpoint.name.replace("chain", "Chain "))} · ${esc(H.checkpoint.sha8)} · ${H.options.mode === "sample" ? "sampling" : "argmax"}`;
    const rows = over.stats.rows.map((r) => `<tr><th>${esc(r[0])}</th><td>${esc(r[1])}</td><td>${esc(r[2])}</td></tr>`).join("");
    const sv = App.ui.surveys[H.record_dir] || (over.survey ? { ...over.survey } : {});
    App.ui.surveys[H.record_dir] = sv;
    const scale = [1, 2, 3, 4, 5].map((n) => `<button type="button" class="${sv.strength === n ? "on" : ""}" data-kind="survey" data-key="strength" data-value="${n}" data-legal="1">${n}</button>`).join("");
    const yn = (key, items) => items.map(([v, l]) => `<button type="button" class="${sv[key] === v ? "on" : ""}" data-kind="survey" data-key="${key}" data-value="${v}" data-legal="1">${l}</button>`).join("");
    const flags = s.flags || [];
    const flagHtml = flags.length ? flags.map((f) => `
      <div class="flagrow"><div class="thumb" id="thumb-${f.index}"></div><div>
        <div class="ft">${f.half === 2 ? "2nd half " : ""}${f.turn ? `T${f.turn}` : "kick-off"} · ${esc(f.label)}</div>
        ${f.note ? `<div class="fn">${esc(f.note)}</div>` : ""}
        <div class="fr">${f.reasons.map((r) => `<span>${esc(r)}</span>`).join("")}${f.p !== null ? `<span>${pct(f.p)}</span>` : ""}
          ${btn("Replay", { "data-kind": "replay", "data-index": f.index, "data-legal": "1" }, "btn ghost")}</div>
      </div></div>`).join("") : `<p class="muted">No flagged moves in this game.</p>`;
    $("post").innerHTML = `
      <header class="final">
        <div class="s h"><div class="num">${st.teams[0].score}</div><div style="min-width:0"><div class="nm">${esc(st.teams[0].name)}</div><div class="cc">${coach(0)}</div></div></div>
        <div class="mid">Full time<small>${over.result && over.result.natural_completion ? "2nd half · turn 8" : "match ended"}</small></div>
        <div class="s a"><div class="num">${st.teams[1].score}</div><div style="min-width:0"><div class="nm">${esc(st.teams[1].name)}</div><div class="cc">${coach(1)}</div></div></div>
      </header>
      <main class="grid5">
        <section class="card"><h3>Match</h3>
          <table class="st"><thead><tr><th></th><td style="color:var(--home-deep)">${esc(over.stats.teams[0])}</td><td style="color:var(--away-deep)">${esc(over.stats.teams[1])}</td></tr></thead><tbody>${rows}</tbody></table>
          <div class="saved" style="margin-top:10px">Game record saved to <code>${esc(over.record_dir)}/</code></div>
          <div class="saved">Seed ${H.options.seed} · you played ${human === 0 ? "home" : "away"}</div>
        </section>
        <section class="card"><h3>Quick survey</h3>
          <div class="q"><div class="lab2">How strong did the bot play?</div><div class="scale">${scale}</div><div class="ends"><span>Clueless</span><span>Tough</span></div></div>
          <div class="q"><div class="lab2">Did it protect the ball well?</div><div class="yn">${yn("ball_protection", [["yes", "Yes"], ["sometimes", "Sometimes"], ["no", "No"]])}</div></div>
          <div class="q"><div class="lab2">Did it stall or waste turns?</div><div class="yn">${yn("stalling", [["yes", "Yes"], ["no", "No"]])}</div></div>
          <div class="q"><div class="lab2">Anything that looked like a rules bug?</div><textarea id="survey-bugs" aria-label="Rules bugs">${esc(sv.rules_bugs || "")}</textarea></div>
          <div class="actions">${btn("Save survey", { "data-kind": "save-survey", "data-legal": "1" }, "btn team home")}${btn("Play again", { "data-kind": "play-again", "data-legal": "1" })}${btn("Change checkpoint", { "data-kind": "change-checkpoint", "data-legal": "1" }, "btn ghost")}</div>
        </section>
        <section class="card"><h3>Flagged moves · ${flags.length}</h3>${flagHtml}
          ${flags.length ? `<div class="actions" style="margin-top:8px">${btn("Replay flagged moves", { "data-kind": "replay", "data-index": 0, "data-legal": "1" })}</div>` : ""}
        </section>
      </main>`;
    App.ui.replays = App.ui.replays || {};
    for (const f of flags) {
      const cached = App.ui.replays[f.index];
      if (cached) drawThumb(f.index, cached);
      else send({ t: "replay_flag", index: f.index, thumb: true });
    }
  }

  function playersForScene(state, highlightSlot) {
    return state.players.filter((pl) => pl.location === "on_pitch").map((pl) => ({
      slot: pl.slot, team: pl.team, x: pl.x, y: pl.y, pos: abbrIn(state, pl), num: pl.number, big: pl.st >= 5,
      state: pl.stance, used: pl.flags.includes("used"), ball: pl.has_ball, selected: pl.slot === highlightSlot,
    }));
  }

  function abbrIn(state, pl) {
    const team = (state.teams[pl.team].name || "").toLowerCase().split(/\s+/);
    let words = (pl.position || "?").split(/\s+/).filter((w) => !team.includes(w.toLowerCase()));
    if (!words.length) words = (pl.position || "?").split(/\s+/);
    return words.length === 1 ? words[0].slice(0, 2) : (words[0][0] + words[1][0]).toUpperCase();
  }

  function flagScene(m, which) {
    const st = which === "post" ? m.post : m.pre;
    const rec = m.flag.record;
    const [t, , x, y] = rec.action;
    const proc = m.pre.procedure;
    const actor = proc && proc.a < 32 ? proc.a : null;
    const scene = { orientation: "landscape", players: playersForScene(st, actor), highlights: [], labels: [] };
    if (x < 26 && y < 15 && [4, 5, 9, 11, 12, 13, 14, 15, 16, 21, 29].includes(t)) scene.highlights.push({ x, y, kind: "flag" });
    const b = st.ball;
    if ((b.state === "on_ground" || b.state === "in_air") && b.x < 26 && b.y < 15) scene.groundBall = { x: b.x, y: b.y };
    return scene;
  }

  function drawThumb(index, m) {
    const el = $(`thumb-${index}`);
    if (el) BBPitch.render(el, flagScene(m, "pre"));
  }

  function onReplay(m) {
    App.ui.replays = App.ui.replays || {};
    App.ui.replays[m.index] = m;
    drawThumb(m.index, m);
    if (App.ui.replayWanted === m.index) openReplayModal(m.index, "pre");
  }

  function openReplayModal(index, which) {
    const m = App.ui.replays[index];
    const flags = App.snapshot.flags || [];
    if (!m) { App.ui.replayWanted = index; send({ t: "replay_flag", index }); return; }
    App.ui.replayWanted = null;
    const v = m.flag.view;
    const alts = v ? v.alternatives.map((a) => `<div class="alt${a.taken ? " taken" : ""}"><span class="l">${esc(a.label)}</span><div class="b"><i style="width:${Math.max(1, Math.round(a.p * 100))}%"></i></div><span class="p">${pct(a.p)}</span></div>`).join("") : "";
    const modal = $("modal");
    modal.hidden = false;
    modal.innerHTML = `<div class="sheet" role="dialog"><div class="head">Flagged move ${index + 1} of ${flags.length}</div><div class="body">
      <div class="pitchframe" id="replay-pitch"></div>
      <div class="actions">${btn("Before the move", { "data-kind": "replay-which", "data-which": "pre", "data-index": index }, which === "pre" ? "btn primary" : "btn")}${btn("After the move", { "data-kind": "replay-which", "data-which": "post", "data-index": index }, which === "post" ? "btn primary" : "btn")}
        ${index > 0 ? btn("Previous", { "data-kind": "replay", "data-index": index - 1 }) : ""}${index + 1 < flags.length ? btn("Next", { "data-kind": "replay", "data-index": index + 1 }) : ""}${btn("Close", { "data-kind": "close-modal", "data-legal": "1" }, "btn ghost")}</div>
      <div class="flagpanel ${sideCls(1 - App.snapshot.state.human_seat)}" style="box-shadow:none"><div class="body"><div class="lab2">Bot's options at this decision</div><div class="alts">${alts}</div>
      ${m.flag.note ? `<div class="saved">${esc(m.flag.note)}</div>` : ""}</div></div>
    </div></div>`;
    BBPitch.render($("replay-pitch"), flagScene(m, which));
  }

  // ---------------------------------------------------------------- clocks
  function updateClocks() {
    const c = App.clock;
    let text = "", warn = false;
    if (c && c.info && c.info.mode !== "off" && c.info.running) {
      const elapsed = (performance.now() - c.at) / 1000;
      if (c.info.mode === "soft") {
        const left = c.info.remaining - elapsed;
        text = fmtTime(left);
        warn = left <= Math.max(10, 0.2 * c.info.seconds);
      } else {
        text = fmtTime(c.info.used + elapsed);
      }
    }
    for (const el of document.querySelectorAll(".js-clock")) {
      el.textContent = text ? `· ${text}` : "";
      el.classList.toggle("warn", warn);
    }
  }

  // ---------------------------------------------------------------- setup drag
  function bindDrag() {
    let drag = null;
    const start = (ev, slot) => {
      drag = { slot, x0: ev.clientX, y0: ev.clientY, moving: false, ghost: null };
    };
    document.addEventListener("pointerdown", (ev) => {
      const p = prompt();
      if (!p || !["setup", "solid_defence", "quick_snap"].includes(p.kind)) return;
      const row = ev.target.closest("[data-kind=reserve][data-legal]");
      if (row) { start(ev, parseInt(row.dataset.slot, 10)); return; }
      const hit = ev.target.closest && ev.target.closest("rect.hit[data-kind=setup-player]");
      if (hit) start(ev, parseInt(hit.dataset.slot, 10));
    });
    document.addEventListener("pointermove", (ev) => {
      if (!drag) return;
      if (!drag.moving && Math.hypot(ev.clientX - drag.x0, ev.clientY - drag.y0) > 6) {
        drag.moving = true;
        const pl = player(drag.slot);
        drag.ghost = document.createElement("div");
        drag.ghost.className = `drag-ghost ${sideCls(pl.team)}`;
        drag.ghost.textContent = abbr(pl);
        document.body.appendChild(drag.ghost);
        App.ui.sel = drag.slot;
        renderPitch();
      }
      if (drag.moving) { drag.ghost.style.left = `${ev.clientX}px`; drag.ghost.style.top = `${ev.clientY}px`; }
    });
    document.addEventListener("pointerup", (ev) => {
      if (!drag) return;
      const d = drag;
      drag = null;
      if (!d.moving) return;
      d.ghost.remove();
      App.suppressClick = true;
      setTimeout(() => { App.suppressClick = false; }, 0);
      const sq = App.pitchApi && App.pitchApi.squareAt(ev.clientX, ev.clientY);
      if (sq) {
        const row = placeRows().find((r) => r[1] === d.slot && r[2] === sq.x && r[3] === sq.y);
        if (row) { submit(row[0]); return; }
      }
      const reserves = $("player-card").getBoundingClientRect();
      if (ev.clientX >= reserves.left && ev.clientX <= reserves.right && ev.clientY >= reserves.top && ev.clientY <= reserves.bottom) {
        const rm = acts("SETUP_REMOVE").find((a) => a.player === d.slot);
        if (rm) { submit(rm.id); return; }
      }
      render();
    });
  }

  // ---------------------------------------------------------------- events
  function executePath() {
    const p = prompt();
    if (!p || p.kind !== "move" || !App.ui.planDest || App.busy) return;
    const mover = player(p.player);
    const squares = pathTo(App.ui.planDest, p.reach || [], mover);
    if (!squares.length) return;
    App.busy = true;
    App.submittedTypes.add("STEP");
    send({ t: "submit_path", state_version: App.legal.state_version, player: p.player, squares });
    App.ui.planDest = null;
  }

  function onPitchHit(ds) {
    if (App.busy || !humanTurn()) return;
    const id = ds.id !== undefined ? parseInt(ds.id, 10) : null;
    switch (ds.kind) {
      case "place": submit(id); break;
      case "setup-player": {
        const slot = parseInt(ds.slot, 10);
        App.ui.sel = App.ui.sel === slot ? null : slot;
        render();
        break;
      }
      case "kick": App.ui.kickSel = { id, x: +ds.x, y: +ds.y }; render(); break;
      case "action": case "target": submit(id); break;
      case "activate": openActivateMenu(id); break;
      case "choice": {
        const x = +ds.x, y = +ds.y;
        const items = ds.ids.split(",").map((s) => App.legal.actions.find((a) => a.id === parseInt(s, 10)))
          .filter(Boolean).map((a) => btn(esc(a.label || a.type), { "data-legal": "1", "data-kind": "action", "data-id": a.id }));
        items.unshift(btn("Move here", { "data-legal": "1", "data-kind": "plan-here", "data-x": x, "data-y": y }));
        openMenuAtSquare(x, y, items, `Square ${x},${y}`);
        break;
      }
      case "plan": {
        const x = +ds.x, y = +ds.y;
        if (App.ui.planDest && App.ui.planDest.x === x && App.ui.planDest.y === y) executePath();
        else { App.ui.planDest = { x, y }; renderPitch(); renderPrompt(); }
        break;
      }
    }
  }

  function bindEvents() {
    const pitch = $("pitch");
    pitch.addEventListener("click", (ev) => {
      if (App.suppressClick) return;
      const hit = ev.target.closest("rect.hit");
      if (hit) onPitchHit(hit.dataset);
      else if (App.ui.menu) closeMenu();
    });
    pitch.addEventListener("pointermove", (ev) => {
      const hit = ev.target.closest && ev.target.closest("rect.hit");
      const sq = App.pitchApi && App.pitchApi.squareAt(ev.clientX, ev.clientY);
      const pl = sq && App.display ? App.display.players.find((q) => q.x === sq.x && q.y === sq.y) : null;
      const next = hit ? { x: +hit.dataset.x, y: +hit.dataset.y, plan: hit.dataset.kind === "plan", id: hit.dataset.id, slot: pl ? pl.slot : undefined }
        : pl ? { x: pl.x, y: pl.y, slot: pl.slot } : null;
      const key = (h) => h ? `${h.x},${h.y},${h.plan},${h.slot}` : "";
      if (key(next) !== key(App.ui.hover)) {
        App.ui.hover = next;
        renderPitch();
        if (App.screen === "game") $("player-card").innerHTML = (prompt() && ["setup", "solid_defence", "quick_snap"].includes(prompt().kind)) ? reservesCard() : (focusPlayer() !== null ? playerCard(focusPlayer()) : $("player-card").innerHTML);
      }
    });
    pitch.addEventListener("pointerleave", () => { App.ui.hover = null; renderPitch(); });

    document.addEventListener("click", (ev) => {
      if (App.suppressClick) return;
      const b = ev.target.closest("button, p[data-kind=flag-step]");
      if (!b || b.disabled || $("lobby").contains(b)) return;
      const kind = b.dataset.kind;
      const id = b.dataset.id !== undefined ? parseInt(b.dataset.id, 10) : null;
      switch (kind) {
        case "action": submit(id); break;
        case "declare": submit(id, { type: "DECLARE", arg: ACT_KINDS.indexOf(b.dataset.declare) }); break;
        case "die-after-decline": submit(id, { type: "CHOOSE_DIE", arg: parseInt(b.dataset.die, 10) }); break;
        case "end-turn": confirmEndTurn(id); break;
        case "confirm": { const c = App.ui.confirm; closeModal(); if (c) submit(c.id); break; }
        case "close-modal": closeModal(); break;
        case "close-menu": closeMenu(); break;
        case "reserve": {
          const slot = parseInt(b.dataset.slot, 10);
          App.ui.sel = App.ui.sel === slot ? null : slot;
          render();
          break;
        }
        case "go-path": executePath(); break;
        case "plan-here":
          closeMenu();
          App.ui.planDest = { x: +b.dataset.x, y: +b.dataset.y };
          render();
          break;
        case "clear-path": App.ui.planDest = null; render(); break;
        case "hide-dialog": App.ui.dialogHidden = true; render(); break;
        case "show-dialog": App.ui.dialogHidden = false; render(); break;
        case "pause": App.paused = !App.paused; wake(); render(); break;
        case "step": App.stepOnce = true; wake(); break;
        case "slower": setSpeed(+1); break;
        case "faster": setSpeed(-1); break;
        case "open-flag": openFlag(); break;
        case "flag-step": openFlag(parseInt(b.dataset.step, 10)); break;
        case "close-flag": App.ui.flag = null; render(); break;
        case "reason": {
          const r = b.dataset.reason;
          App.ui.flag.note = $("flag-note").value;
          if (App.ui.flag.reasons.has(r)) App.ui.flag.reasons.delete(r); else App.ui.flag.reasons.add(r);
          renderFlagPanel();
          break;
        }
        case "save-flag": {
          const f = App.ui.flag;
          f.saving = true;
          send({ t: "flag", step: f.frameStep, reasons: Array.from(f.reasons), note: $("flag-note").value });
          break;
        }
        case "dismiss":
          App.ui.overlay = null; renderOverlay(); wake(); break;
        case "survey": {
          const sv = App.ui.surveys[App.snapshot.header.record_dir];
          sv.rules_bugs = $("survey-bugs").value;
          const v = b.dataset.key === "strength" ? parseInt(b.dataset.value, 10) : b.dataset.value;
          sv[b.dataset.key] = sv[b.dataset.key] === v ? null : v;
          renderPost();
          break;
        }
        case "save-survey": {
          const sv = App.ui.surveys[App.snapshot.header.record_dir];
          sv.rules_bugs = $("survey-bugs").value;
          send({ t: "survey", answers: sv });
          break;
        }
        case "play-again": {
          const opts = { ...App.snapshot.header.options, seed: null };
          delete opts.kernel;
          send({ t: "new_game", options: opts });
          toast("Starting a new match with the same options.");
          break;
        }
        case "change-checkpoint": App.lobbyOpts = null; showLobby(); break;
        case "to-lobby": App.lobbyOpts = null; showLobby(); break;
        case "replay": openReplayModal(parseInt(b.dataset.index, 10), "pre"); break;
        case "replay-which": openReplayModal(parseInt(b.dataset.index, 10), b.dataset.which); break;
      }
    });

    document.addEventListener("keydown", (ev) => {
      if (App.screen !== "game") { if (ev.key === "Escape") closeModal(); return; }
      const typing = ev.target.matches && ev.target.matches("textarea, input, select");
      if (typing) { if (ev.key === "Escape") ev.target.blur(); return; }
      const key = ev.key.toLowerCase();
      if (!$("modal").hidden) { if (key === "escape") closeModal(); if (key === "enter" && App.ui.confirm) { const c = App.ui.confirm; closeModal(); submit(c.id); } return; }
      if (App.ui.menu) {
        const item = document.querySelector(`#action-menu [data-key="${CSS.escape(key)}"]`);
        if (item) { item.click(); ev.preventDefault(); return; }
        if (key === "escape") { closeMenu(); return; }
      }
      if (ev.ctrlKey && key === "t") {
        const a = acts("END_TURN")[0];
        if (a && humanTurn()) { confirmEndTurn(a.id); ev.preventDefault(); }
        return;
      }
      if (key === " ") { if (App.playing) { App.paused = !App.paused; wake(); render(); ev.preventDefault(); } return; }
      if (key === ".") { App.stepOnce = true; wake(); return; }
      if (key === "f" && App.lastBotFrame) { openFlag(); return; }
      if (key === "enter") { executePath(); return; }
      if (key === "escape") { App.ui.planDest = null; App.ui.sel = null; App.ui.flag = null; render(); return; }
      if (key === "h" && document.getElementById("dialog-layer").innerHTML) { App.ui.dialogHidden = !App.ui.dialogHidden; render(); return; }
      if (["1", "2", "3"].includes(key)) {
        const face = document.querySelectorAll("#dialog .face")[parseInt(key, 10) - 1];
        if (face && !face.disabled) face.click();
        return;
      }
      if (key === "r") {
        const rr = document.querySelector('#dialog [data-type="USE_REROLL"]');
        if (rr) rr.click();
      }
    });
    window.addEventListener("resize", () => render());
    setInterval(updateClocks, 250);
  }

  function setSpeed(dir) {
    let i = SPEEDS.findIndex((v) => v >= App.delay);
    if (i < 0) i = SPEEDS.length - 1;
    i = Math.max(0, Math.min(SPEEDS.length - 1, i + dir));
    App.delay = SPEEDS[i];
    wake();
    render();
  }

  function confirmEndTurn(id) {
    const p = prompt();
    if (!p) return;
    const warnings = [];
    if (p.can_act > 0) warnings.push(`${p.can_act} ${p.can_act === 1 ? "player" : "players"} can still act.`);
    if (p.stalling_carrier !== undefined) warnings.push(`#${player(p.stalling_carrier).number} ${esc(player(p.stalling_carrier).position)} can score without a roll. Ending the turn now triggers the Stalling roll.`);
    if (!warnings.length) { submit(id); return; }
    App.ui.confirm = { id };
    const modal = $("modal");
    modal.hidden = false;
    modal.innerHTML = `<div class="sheet narrow" role="dialog"><div class="head">End the turn?</div><div class="body">
      ${warnings.map((w) => `<p class="line" style="margin:0;font-family:var(--cond);font-weight:600;font-size:16px">${w}</p>`).join("")}
      <div class="actions">${btn("End turn <span class=\"k\">Enter</span>", { "data-kind": "confirm", "data-legal": "1" }, `btn team ${sideCls(humanSeat())}`)}${btn("Keep playing", { "data-kind": "close-modal" }, "btn")}</div></div></div>`;
  }

  function closeModal() {
    $("modal").hidden = true;
    $("modal").innerHTML = "";
    App.ui.confirm = null;
  }

  bindLobby();
  bindEvents();
  bindDrag();
  connect();
})();
