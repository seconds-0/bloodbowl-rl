// Renders the review screens at 1440x900 and phone width from one real match.
// A second tab at phone width watches the same game; local UI steps (a planned
// path, an open flag panel) are repeated there before each phone capture.
const fs = require("fs");
const path = require("path");
const { test } = require("@playwright/test");
const H = require("../helpers");

const DIR = path.join(H.OUT, "screens-final");

async function capture(desk, phone, name, phoneSetup) {
  fs.mkdirSync(DIR, { recursive: true });
  await desk.evaluate(() => document.fonts.ready);
  await desk.waitForTimeout(250);
  await desk.screenshot({ path: path.join(DIR, `${name}-desktop.png`) });
  if (!phone) return;
  await phone.waitForFunction(() => window.__bb && window.__bb.display);
  await phone.waitForTimeout(400);
  if (phoneSetup) await phoneSetup(phone);
  await phone.evaluate(() => document.fonts.ready);
  await phone.waitForTimeout(250);
  await phone.screenshot({ path: path.join(DIR, `${name}-phone.png`), fullPage: true });
}

test("capture the review screens from one match", async ({ page, browser }) => {
  test.setTimeout(45 * 60 * 1000);
  const errors = H.watchConsole(page);
  const phoneCtx = await browser.newContext({ viewport: { width: 400, height: 860 }, deviceScaleFactor: 2 });
  const phone = await phoneCtx.newPage();

  // Lobby, both widths.
  await page.goto("/");
  await page.waitForSelector("#lobby:not([hidden])");
  await page.click("[data-kind=opt][data-key=roster_mode][data-value=mine]");
  await page.selectOption("#lobby-human-team", "22");
  await page.click("[data-kind=opt][data-key=clock_mode][data-value=soft]");
  await page.fill("#lobby-clock-seconds", "240");
  await page.fill("#lobby-seed", "20260913");
  await capture(page, null, "01-lobby");
  await phone.goto("/");
  await phone.waitForSelector("#lobby:not([hidden])");
  await phone.waitForTimeout(300);
  await phone.screenshot({ path: path.join(DIR, "01-lobby-phone.png"), fullPage: true });

  await H.startGame(page, { roster_mode: "mine", human_team: 22, human_side: "home", seed: 20260913, think_ms: 250, clock_mode: "display" });
  await phone.goto("/");
  const r = H.rng(20260913);
  const kind = () => page.evaluate(() => window.__bbApi.promptKind());
  const got = new Set();

  // Setup with a few players placed.
  await H.playUntil(page, r, async () => (await kind()) === "setup", {});
  for (let i = 0; i < 6; i++) {
    await page.locator("#reserve-list [data-legal]").first().click();
    const v = await page.evaluate(() => window.__bbApi.version());
    const losX = await page.evaluate(() => window.__bb.legal.prompt.formation.los_x);
    const sel = i < 3 ? ["5", "7", "9"].map((y) => `#pitch rect.hit[data-kind=place][data-x="${losX}"][data-y="${y}"]`)[i]
      : `#pitch rect.hit[data-kind=place][data-x="${losX - 3 + (i % 2)}"][data-y="${4 + i}"]`;
    if (await H.has(page, sel)) await page.click(sel); else await H.clickRandom(page, "#pitch rect.hit[data-kind=place]", r);
    await page.waitForFunction((vv) => window.__bbApi.version() > vv && window.__bbApi.humanTurn(), v);
  }
  await page.locator("#reserve-list [data-legal]").first().click();
  await page.locator("#pitch rect.hit[data-kind=place]").nth(60).hover();
  await capture(page, phone, "02-setup");
  got.add("setup");

  const want = ["move-path", "block-dialog", "reroll", "flag", "half-time"];
  for (let i = 0; i < 9000 && want.some((w) => !got.has(w)); i++) {
    const st = await page.evaluate(() => ({
      k: window.__bbApi.promptKind(), human: window.__bbApi.humanTurn(), playing: window.__bb.playing && window.__bb.batchPolicy > 0,
      overlay: !!document.querySelector("#pitch-overlay [data-kind=dismiss]"), screen: window.__bb.screen,
    }));
    if (st.screen === "post") break;
    if (st.overlay && !got.has("half-time")) {
      await capture(page, phone, "07-half-time", async (ph) => { await ph.waitForSelector("#pitch-overlay .ob"); });
      got.add("half-time");
      await page.click("#pitch-overlay [data-kind=dismiss]");
      const phoneDismiss = phone.locator("#pitch-overlay [data-kind=dismiss]");
      if (await phoneDismiss.count()) await phoneDismiss.click();
      continue;
    }
    if (st.playing && !got.has("flag") && i > 40) {
      await page.click("#playback-card [data-kind=pause]");
      await page.waitForFunction(() => !!window.__bb.lastBotFrame);
      await page.click("#playback-card [data-kind=open-flag]");
      await page.waitForSelector("#flag-panel .alt");
      await page.click("#flag-panel [data-kind=reason][data-reason='Too risky']");
      await page.fill("#flag-note", "Left the carrier open to a one-die blitz.");
      await capture(page, phone, "06-bot-turn-flag", async (ph) => {
        await ph.waitForFunction(() => !!window.__bb.lastBotFrame, null, { timeout: 60000 });
        if (await ph.locator("#playback-card [data-kind=pause]").count()) await ph.click("#playback-card [data-kind=pause]");
        await ph.click("[data-kind=open-flag]");
        await ph.waitForSelector("#flag-panel .alt");
        await ph.click("#flag-panel [data-kind=reason][data-reason='Too risky']");
        await ph.locator("#flag-panel").scrollIntoViewIfNeeded();
      });
      await page.click("#flag-panel [data-kind=save-flag]");
      await page.waitForSelector("#flag-panel", { state: "hidden" });
      await page.click("#playback-card [data-kind=pause]");
      const phPause = phone.locator("#playback-card [data-kind=pause]");
      if (await phPause.count() && await phPause.isVisible()) await phPause.click();
      if (await phone.locator("#flag-panel [data-kind=close-flag]").count()) await phone.click("#flag-panel [data-kind=close-flag]").catch(() => {});
      got.add("flag");
      continue;
    }
    if (!st.human) { await page.waitForTimeout(40); continue; }
    if (st.k === "move" && !got.has("move-path")) {
      const far = await page.evaluate(() => {
        const p = window.__bb.legal.prompt;
        return (p.reach || []).filter((q) => q[2] >= 4 && q[3] >= 1).map((q) => [q[0], q[1]]);
      });
      if (far.length) {
        const [x, y] = far[0];
        const sel = `#pitch rect.hit[data-kind=plan][data-x="${x}"][data-y="${y}"]`;
        await page.hover(sel);
        await page.click(sel);
        await page.waitForSelector("#pitch text.num, #pitch .path-sq");
        await page.waitForTimeout(300);
        await capture(page, phone, "03-move-path", async (ph) => {
          await ph.waitForFunction(() => window.__bbApi.promptKind() === "move");
          await ph.click(sel);
          await ph.waitForTimeout(300);
        });
        got.add("move-path");
      }
    }
    if (["block_reroll", "block_choose_die"].includes(st.k) && !got.has("block-dialog")) {
      await capture(page, phone, "04-block-dialog", async (ph) => { await ph.waitForSelector("#dialog"); await ph.locator("#dialog").scrollIntoViewIfNeeded(); });
      got.add("block-dialog");
    }
    if (["test_reroll", "activation_reroll"].includes(st.k) && !got.has("reroll")) {
      await capture(page, phone, "05-reroll-prompt", async (ph) => { await ph.waitForSelector("#dialog"); await ph.locator("#dialog").scrollIntoViewIfNeeded(); });
      got.add("reroll");
    }
    await H.humanStep(page, r, { maxActivations: 4, preferDeclare: got.has("block-dialog") ? "BLITZ" : "BLOCK", targetRate: 0.7, moveRate: 0.8 });
  }
  // Finish the match quickly, then capture the post-game screen.
  await page.evaluate(() => { window.__bb.delay = 0; });
  for (let i = 0; i < 8000; i++) {
    const alive = await H.humanStep(page, r, { maxActivations: 1 });
    if (!alive) break;
  }
  await page.waitForSelector("#post .final");
  await page.click("#post [data-kind=survey][data-key=strength][data-value='3']");
  await page.click("#post [data-kind=survey][data-key=ball_protection][data-value=sometimes]");
  await page.click("#post [data-kind=survey][data-key=stalling][data-value=yes]");
  await page.fill("#survey-bugs", "Stand Firm never came up.");
  await page.waitForTimeout(800);
  await capture(page, phone, "08-post-game", async (ph) => { await ph.waitForSelector("#post .final", { timeout: 120000 }); await ph.waitForTimeout(800); });
  H.writeJson("screens-captured.json", { captured: Array.from(got) });
  H.expect(errors).toEqual([]);
  await phoneCtx.close();
});
