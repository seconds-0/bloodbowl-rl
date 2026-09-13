// Focused checks: block dice dialog, move path preview, setup formation checks,
// the bot playback flag panel, the phone layout order and the soft turn clock.
const { test } = require("@playwright/test");
const H = require("../helpers");

const kind = (page) => page.evaluate(() => window.__bbApi.promptKind());

function intersects(a, b) {
  return a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
}

test("setup checks follow placements and End setup waits for a legal formation", async ({ page }) => {
  const errors = H.watchConsole(page);
  await H.startGame(page, { human_side: "home", seed: 777, think_ms: 0 });
  const r = H.rng(777);
  const ok = await H.playUntil(page, r, async () => (await kind(page)) === "setup", {});
  H.expect(ok).toBe(true);
  const checks = page.locator("#log-card .check");
  await H.expect(checks.first()).toContainText("Players on the pitch");
  const onPitch = async () => (await checks.first().locator(".count").textContent()).trim();
  const start = await onPitch();
  H.expect(start.startsWith("0 of")).toBe(true);
  await H.expect(page.locator("#prompt-card [data-kind=end-setup-disabled]")).toBeDisabled();
  await H.shot(page, "setup-empty");
  // Place one player by click: reserve row, then a lit square.
  await page.locator("#reserve-list [data-legal]").first().click();
  await H.expect(page.locator("#pitch rect.hit[data-kind=place]").first()).toBeAttached();
  const v0 = await page.evaluate(() => window.__bbApi.version());
  await page.locator("#pitch rect.hit[data-kind=place]").nth(40).click();
  await page.waitForFunction((v) => window.__bbApi.version() > v && window.__bbApi.humanTurn(), v0);
  H.expect((await onPitch()).startsWith("1 of")).toBe(true);
  // Place a second player by dragging the reserve row onto the pitch.
  const row = page.locator("#reserve-list [data-legal]").first();
  const rb = await row.boundingBox();
  const pb = await page.locator("#pitch svg").boundingBox();
  const v1 = await page.evaluate(() => window.__bbApi.version());
  await page.mouse.move(rb.x + rb.width / 2, rb.y + rb.height / 2);
  await page.mouse.down();
  await page.mouse.move(pb.x + pb.width * 0.3, pb.y + pb.height * 0.5, { steps: 8 });
  await page.mouse.move(pb.x + pb.width * 0.3 + 3, pb.y + pb.height * 0.5 + 3, { steps: 2 });
  await page.mouse.up();
  await page.waitForFunction((v) => window.__bbApi.version() > v && window.__bbApi.humanTurn(), v1);
  H.expect((await onPitch()).startsWith("2 of")).toBe(true);
  // Keep placing until the engine offers SETUP_DONE; the button follows the legal list.
  // Fill the line of scrimmage first, then the centre rows, so the formation becomes legal.
  const losX = await page.evaluate(() => window.__bb.legal.prompt.formation.los_x);
  for (let i = 0; i < 30; i++) {
    if (await H.has(page, "#prompt-card [data-type=SETUP_DONE][data-legal]")) break;
    if (await H.has(page, "#reserve-list [data-legal]")) {
      await page.locator("#reserve-list [data-legal]").first().click();
    } else {
      // Pitch full: pick a player off the line and move them onto it.
      await page.evaluate((lx) => { window.__e2eLos = lx; }, losX);
      await H.clickRandom(page, `#pitch rect.hit[data-kind=setup-player]:not([data-x="${losX}"])`, r);
    }
    await page.waitForSelector("#pitch rect.hit[data-kind=place]");
    const onLine = `#pitch rect.hit[data-kind=place][data-x="${losX}"]`;
    const centre = ["4", "5", "6", "7", "8", "9", "10"].map((y) => `#pitch rect.hit[data-kind=place][data-y="${y}"]`).join(", ");
    const los = await page.evaluate(() => window.__bb.legal.prompt.formation.los);
    const target = los < 3 ? ["4", "5", "6", "7", "8", "9", "10"].map((y) => `${onLine}[data-y="${y}"]`).join(", ") : centre;
    const v = await page.evaluate(() => window.__bbApi.version());
    await H.clickRandom(page, target, r);
    await page.waitForFunction((vv) => window.__bbApi.version() > vv && window.__bbApi.humanTurn(), v);
  }
  await H.expect(page.locator("#prompt-card [data-type=SETUP_DONE][data-legal]")).toBeEnabled();
  await H.shot(page, "setup-ready");
  H.expect(errors).toEqual([]);
});

test("move path preview draws the planned squares and executes step by step", async ({ page }) => {
  const errors = H.watchConsole(page);
  await H.startGame(page, { human_side: "away", seed: 901, think_ms: 0 });
  const r = H.rng(901);
  let found = false;
  for (let i = 0; i < 3000 && !found; i++) {
    const k = await kind(page);
    if (k === "move") {
      const far = await page.evaluate(() => {
        const p = window.__bb.legal.prompt;
        return (p.reach || []).filter((q) => q[2] >= 3).map((q) => [q[0], q[1], q[2]]);
      });
      if (far.length) {
        const [x, y, len] = far[Math.floor(r() * far.length)];
        const hit = page.locator(`#pitch rect.hit[data-kind=plan][data-x="${x}"][data-y="${y}"]`);
        await hit.hover();
        await H.expect(page.locator("#pitch .path-sq")).toHaveCount(len);
        await hit.click();
        await H.expect(page.locator("#prompt-card [data-kind=go-path]")).toBeVisible();
        await H.expect(page.locator("#prompt-card .tag").last()).toContainText("before re-rolls");
        await H.shot(page, "move-path");
        const p0 = await page.evaluate(() => { const p = window.__bb.legal.prompt; const pl = window.__bb.display.players.find((q) => q.slot === p.player); return [p.player, pl.x, pl.y]; });
        const v = await page.evaluate(() => window.__bbApi.version());
        await page.keyboard.press("Enter");
        await page.waitForFunction((vv) => window.__bbApi.version() > vv && !window.__bb.playing, v);
        const moved = await page.evaluate((slot) => { const pl = window.__bb.display.players.find((q) => q.slot === slot); return [pl.x, pl.y]; }, p0[0]);
        H.expect(moved[0] !== p0[1] || moved[1] !== p0[2]).toBe(true);
        found = true;
        break;
      }
    }
    await H.humanStep(page, r, { preferDeclare: "MOVE", targetRate: 0, moveRate: 0.2, maxActivations: 4 });
  }
  H.expect(found).toBe(true);
  H.expect(errors).toEqual([]);
});

test("block dice dialog sits away from the players and can be hidden", async ({ page }) => {
  const errors = H.watchConsole(page);
  await H.startGame(page, { human_side: "home", seed: 314, think_ms: 0 });
  const r = H.rng(314);
  const ok = await H.playUntil(page, r, async () => ["block_reroll", "block_choose_die"].includes(await kind(page)),
    { preferDeclare: "BLOCK", targetRate: 1, moveRate: 0.3, maxActivations: 5, setupDone: 0.9 }, 5000);
  H.expect(ok).toBe(true);
  const dlg = page.locator("#dialog");
  await H.expect(dlg).toBeVisible();
  const p = await page.evaluate(() => window.__bb.legal.prompt);
  await H.expect(dlg.locator(".face")).toHaveCount(p.dice.length);
  await H.expect(dlg.locator(".who")).toHaveText(/You pick|Bot picks/);
  const box = await dlg.boundingBox();
  for (const slot of [p.attacker, p.defender]) {
    const tok = await page.locator(`#pitch g.token[data-slot="${slot}"]`).boundingBox();
    H.expect(intersects(box, tok)).toBe(false);
  }
  await H.shot(page, "block-dialog");
  await page.keyboard.press("h");
  await H.expect(dlg).toBeHidden();
  await page.click("[data-kind=show-dialog]");
  await H.expect(page.locator("#dialog")).toBeVisible();
  const v = await page.evaluate(() => window.__bbApi.version());
  await H.clickRandom(page, "#dialog [data-legal]", r);
  await page.waitForFunction((vv) => window.__bbApi.version() > vv, v);
  H.expect(errors).toEqual([]);
});

test("flag panel shows the bot's options during playback without moving the pitch", async ({ page }) => {
  const errors = H.watchConsole(page);
  await H.startGame(page, { human_side: "home", seed: 555, think_ms: 700 });
  const r = H.rng(555);
  // Wait for bot playback: the playback card appears while policy frames play.
  let seen = false;
  for (let i = 0; i < 2000 && !seen; i++) {
    seen = await page.locator("#playback-card").isVisible();
    if (seen) break;
    const idle = await page.evaluate(() => window.__bbApi.humanTurn() && !window.__bb.busy);
    if (idle) await H.humanStep(page, r, { maxActivations: 1 });
    else await page.waitForTimeout(40);
  }
  H.expect(seen).toBe(true);
  await page.click("#playback-card [data-kind=pause]");
  await page.waitForFunction(() => !!window.__bb.lastBotFrame);
  const before = await page.locator("#pitch").boundingBox();
  await page.click("#playback-card [data-kind=open-flag]");
  const panel = page.locator("#flag-panel");
  await H.expect(panel).toBeVisible();
  await H.expect(panel.locator(".alt").first()).toBeVisible();
  const after = await page.locator("#pitch").boundingBox();
  H.expect(after).toEqual(before);
  const pcts = await panel.locator(".alt .p").allTextContents();
  H.expect(pcts.length).toBeGreaterThan(0);
  await H.expect(panel.locator(".kv")).toContainText("Bot value");
  await panel.locator("[data-kind=reason]").first().click();
  await H.expect(panel.locator(".reason.on")).toHaveCount(1);
  await page.fill("#flag-note", "Recorded by the focused flag test.");
  await H.shot(page, "bot-turn-flag");
  await panel.locator("[data-kind=save-flag]").click();
  await H.expect(panel).toBeHidden();
  await page.waitForFunction(() => (window.__bb.snapshot.flags || []).length === 1);
  await page.click("#playback-card [data-kind=pause]").catch(() => {});
  H.expect(errors).toEqual([]);
});

test("phone layout puts the pitch, turn banner and player card above the action panel", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 400, height: 860 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  const errors = H.watchConsole(page);
  await H.startGame(page, { human_side: "away", seed: 99, think_ms: 0 });
  const r = H.rng(99);
  const ok = await H.playUntil(page, r, async () => (await kind(page)) === "move",
    { preferDeclare: "MOVE", targetRate: 0, moveRate: 0, maxActivations: 4 }, 3000);
  H.expect(ok).toBe(true);
  await H.shot(page, "phone-move");
  const y = async (sel) => (await page.locator(sel).boundingBox()).y;
  const pitch = await y("#pitch"), banner = await y("#turn-banner"), card = await y("#player-card"), prompt = await y("#prompt-card");
  H.expect(pitch).toBeLessThan(banner);
  H.expect(banner).toBeLessThan(card);
  H.expect(card).toBeLessThan(prompt);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  H.expect(overflow).toBe(false);
  H.expect(errors).toEqual([]);
  await ctx.close();
});

test("soft turn clock ends the human turn through legal moves", async ({ page }) => {
  const errors = H.watchConsole(page);
  await H.startGame(page, { human_side: "home", seed: 808, think_ms: 0, clock_mode: "soft", clock_seconds: 15 });
  const r = H.rng(808);
  const ok = await H.playUntil(page, r, async () => (await kind(page)) === "select_player", { maxActivations: 0 }, 2000);
  H.expect(ok).toBe(true);
  const turn = await page.evaluate(() => { const s = window.__bb.display; return [s.half, s.teams[s.human_seat].turn]; });
  await H.expect(page.locator("#board .js-clock")).toHaveText(/0:1\d|0:0\d/);
  await page.waitForFunction(() => document.querySelector("#toast") && document.querySelector("#toast").textContent.includes("Time ran out"), null, { timeout: 30000 });
  await page.waitForFunction((t) => {
    const s = window.__bb.display;
    return s.awaiting === "over" || s.half !== t[0] || s.teams[s.human_seat].turn !== t[1] || !s.in_team_turn[s.human_seat];
  }, turn, { timeout: 30000 });
  H.expect(errors).toEqual([]);
});
