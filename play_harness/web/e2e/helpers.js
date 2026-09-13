// Shared driver for the browser suite. It plays from the human seat by clicking
// only elements the client marks data-legal (squares, players, menu items and
// dialog buttons built from the server's legal list). It never sends raw
// websocket messages and never builds an engine action.
const fs = require("fs");
const path = require("path");
const { expect } = require("@playwright/test");

const OUT = path.join(__dirname, "out");

function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function watchConsole(page) {
  const errors = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error" && !/GPU stall|ReadPixels/.test(m.text())) errors.push(`console: ${m.text()}`);
  });
  return errors;
}

// Load the app and open the lobby. The server keeps one game across page
// loads, so a running or finished game is left through its own lobby button.
async function toLobby(page) {
  await page.goto("/");
  await page.waitForSelector("#lobby:not([hidden]), #game:not([hidden]) [data-kind=to-lobby], #post:not([hidden]) [data-kind=change-checkpoint]");
  if (await page.locator("#game:not([hidden]) [data-kind=to-lobby]").count()) await page.click("#game [data-kind=to-lobby]");
  else if (await page.locator("#post:not([hidden]) [data-kind=change-checkpoint]").count()) await page.click("#post [data-kind=change-checkpoint]");
  await page.waitForSelector("#lobby:not([hidden])");
  await page.waitForSelector("#lobby-checkpoints .ck");
}

async function startGame(page, opts = {}) {
  await toLobby(page);
  const set = async (key, value) => page.click(`[data-kind=opt][data-key=${key}][data-value=${value}]`);
  await set("roster_mode", opts.roster_mode || "random");
  await set("human_side", opts.human_side || "home");
  await set("mode", opts.mode || "sample");
  await set("clock_mode", opts.clock_mode || "off");
  if (opts.roster_mode === "both" || opts.roster_mode === "mine") {
    await page.selectOption("#lobby-human-team", String(opts.human_team));
    if (opts.roster_mode === "both") await page.selectOption("#lobby-bot-team", String(opts.bot_team));
  }
  if (opts.clock_mode === "soft") await page.fill("#lobby-clock-seconds", String(opts.clock_seconds || 15));
  await page.locator("#lobby-think").evaluate((el, v) => { el.value = String(v); el.dispatchEvent(new Event("input", { bubbles: true })); }, opts.think_ms ?? 0);
  await page.fill("#lobby-seed", String(opts.seed || 12345));
  await page.click("#lobby-start");
  await page.waitForFunction(() => window.__bb && window.__bb.screen === "game" && window.__bb.display);
}

// Wait until the client is waiting for a human click, or the game is over.
async function waitIdle(page, timeout = 60000) {
  await page.waitForFunction(() => {
    const A = window.__bb;
    if (!A) return false;
    if (A.screen === "post") return true;
    if (document.querySelector("#pitch-overlay [data-kind=dismiss]")) return true;
    if (!document.querySelector("#modal").hidden) return true;
    return window.__bbApi.humanTurn() && !A.busy;
  }, null, { timeout, polling: 30 });
}

async function clickRandom(page, selector, r) {
  const loc = page.locator(selector);
  const n = await loc.count();
  if (!n) return false;
  await loc.nth(Math.floor(r() * n)).click();
  return true;
}

async function has(page, selector) {
  return (await page.locator(selector).count()) > 0;
}

// One human decision through the UI. Returns false when the game is over.
async function humanStep(page, r, strategy = {}) {
  await waitIdle(page);
  const st = await page.evaluate(() => ({
    screen: window.__bb.screen, kind: window.__bbApi.promptKind(), version: window.__bbApi.version(),
    modal: !document.querySelector("#modal").hidden,
    overlay: !!document.querySelector("#pitch-overlay [data-kind=dismiss]"),
    activations: window.__bb.e2eActivations || 0,
  }));
  if (st.screen === "post") return false;
  if (st.overlay) { await page.click("#pitch-overlay [data-kind=dismiss]"); return true; }
  if (st.modal) { await page.click("#modal [data-kind=confirm][data-legal]"); await settle(page, st.version); return true; }
  const k = st.kind;
  const menuItem = "#action-menu [data-legal]";
  if (await has(page, menuItem)) {
    await clickRandom(page, menuItem, r);
    await settle(page, st.version);
    return true;
  }
  if (["setup", "solid_defence", "quick_snap"].includes(k)) {
    const done = "#prompt-card [data-type=SETUP_DONE][data-legal]";
    if (await has(page, done) && r() < (strategy.setupDone ?? 0.85)) { await page.click(done); await settle(page, st.version); return true; }
    if (await has(page, "#pitch rect.hit[data-kind=place]")) { await clickRandom(page, "#pitch rect.hit[data-kind=place]", r); await settle(page, st.version); return true; }
    if (await clickRandom(page, "#reserve-list [data-legal]", r)) return true;
    if (await clickRandom(page, "#pitch rect.hit[data-kind=setup-player]", r)) return true;
    if (await has(page, done)) { await page.click(done); await settle(page, st.version); return true; }
  }
  if (k === "kick_target") {
    await clickRandom(page, "#pitch rect.hit[data-kind=kick]", r);
    await page.click("#prompt-card [data-kind=action][data-legal]");
    await settle(page, st.version);
    return true;
  }
  if (k === "select_player" || k === "charge") {
    const maxActs = strategy.maxActivations ?? 2;
    const wantEnd = st.activations >= maxActs || r() < 0.12;
    if (!wantEnd && await has(page, "#pitch rect.hit[data-kind=activate]")) {
      await page.evaluate(() => { window.__bb.e2eActivations = (window.__bb.e2eActivations || 0) + 1; });
      await clickRandom(page, "#pitch rect.hit[data-kind=activate]", r);
      await page.waitForSelector(menuItem);
      const prefer = strategy.preferDeclare;
      if (prefer && await has(page, `${menuItem}[data-declare=${prefer}]`)) await page.click(`${menuItem}[data-declare=${prefer}]`);
      else await clickRandom(page, menuItem, r);
      await settle(page, st.version);
      return true;
    }
    await page.evaluate(() => { window.__bb.e2eActivations = 0; });
    await page.click("#prompt-card [data-kind=end-turn][data-legal]");
    if (await page.locator("#modal [data-kind=confirm]").isVisible().catch(() => false)) {
      await page.click("#modal [data-kind=confirm][data-legal]");
    }
    await settle(page, st.version);
    return true;
  }
  if (k === "move") {
    const targets = "#pitch rect.hit[data-kind=target]";
    if (await has(page, targets) && r() < (strategy.targetRate ?? 0.6)) { await clickRandom(page, targets, r); await settle(page, st.version); return true; }
    const plans = "#pitch rect.hit[data-kind=plan]";
    const n = await page.locator(plans).count();
    if (n && r() < (strategy.moveRate ?? 0.6)) {
      const pick = page.locator(plans).nth(Math.floor(r() * n));
      await pick.hover();
      await pick.click();
      await page.waitForSelector("#prompt-card [data-kind=go-path]");
      await pick.click();
      await settle(page, st.version);
      return true;
    }
    const endAct = "#prompt-card [data-type=END_ACTIVATION][data-legal]";
    if (await has(page, endAct)) { await page.click(endAct); await settle(page, st.version); return true; }
  }
  // Dialogs, pitch squares for other windows, and every remaining legal button.
  const pools = ["#dialog [data-legal]", "#pitch rect.hit[data-legal]:not([data-kind=plan])", "#prompt-card [data-legal]"];
  for (const pool of pools) {
    if (await has(page, pool)) {
      await clickRandom(page, pool, r);
      await settle(page, st.version);
      return true;
    }
  }
  if (await has(page, "[data-kind=show-dialog]")) { await page.click("[data-kind=show-dialog]"); return true; }
  throw new Error(`no legal element to click for prompt ${k}`);
}

async function settle(page, version, timeout = 30000) {
  await page.waitForFunction((v) => {
    const A = window.__bb;
    return A.screen === "post" || (window.__bbApi.version() !== v && !A.playing) ||
      (!A.busy && window.__bbApi.humanTurn() && window.__bbApi.version() === v && document.querySelector("#action-menu"));
  }, version, { timeout, polling: 30 }).catch(async () => {
    // A click that only changed local UI (selection, plan) does not advance the version.
  });
}

async function playUntil(page, r, predicate, strategy = {}, maxSteps = 4000) {
  for (let i = 0; i < maxSteps; i++) {
    if (await predicate()) return true;
    const alive = await humanStep(page, r, strategy);
    if (!alive) return predicate();
  }
  return false;
}

function writeJson(name, data) {
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(path.join(OUT, name), JSON.stringify(data, null, 1));
}

async function shot(page, name) {
  fs.mkdirSync(path.join(OUT, "screens"), { recursive: true });
  await page.screenshot({ path: path.join(OUT, "screens", `${name}.png`) });
}

module.exports = { rng, watchConsole, toLobby, startGame, waitIdle, humanStep, playUntil, settle, has, clickRandom, writeJson, shot, expect, OUT };
