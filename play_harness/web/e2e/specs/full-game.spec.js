// A complete match from the human seat through the browser, clicking only
// elements the client marks legal, from the coin toss to the post-game survey.
const { test } = require("@playwright/test");
const H = require("../helpers");

for (const side of ["away", "home"]) {
  test(`full game from the human seat playing ${side}`, async ({ page }) => {
    const errors = H.watchConsole(page);
    const seed = side === "away" ? 2027 : 4242;
    await H.startGame(page, { human_side: side, seed, think_ms: 0, clock_mode: "display" });
    const r = H.rng(seed);
    let flagged = false;
    let steps = 0;
    for (;;) {
      const alive = await H.humanStep(page, r, { maxActivations: 3 });
      steps++;
      if (!alive) break;
      if (!flagged && steps > 60 && await page.evaluate(() => !!window.__bb.lastBotFrame && window.__bbApi.humanTurn())) {
        // Flag one bot move from the rail while it is the human's decision.
        await page.click("#last-bot-turn [data-kind=open-flag]");
        await H.expect(page.locator("#flag-panel .alt").first()).toBeVisible();
        await page.click("#flag-panel [data-kind=reason][data-reason='Wasted time']");
        await page.fill("#flag-note", "Flag recorded by the end-to-end suite.");
        await page.click("#flag-panel [data-kind=save-flag]");
        await H.expect(page.locator("#flag-panel")).toBeHidden();
        flagged = true;
      }
      if (steps > 6000) throw new Error("the match did not finish within 6000 human steps");
    }
    await page.waitForSelector("#post .final");
    const over = await page.evaluate(() => window.__bb.snapshot.over);
    H.expect(over.result.natural_completion).toBe(true);
    for (const key of ["illegal", "projection_collision", "error_episodes", "engine_rejections", "precheck_collisions"]) {
      H.expect(over.integrity[key]).toBe(0);
    }
    H.expect(over.integrity.forwards).toBe(over.integrity.c_steps);
    await H.expect(page.locator("#post table.st tbody tr")).toHaveCount(over.stats.rows.length);
    await H.expect(page.locator("#post .flagrow")).toHaveCount(1);
    await page.click("#post [data-kind=survey][data-key=strength][data-value='3']");
    await page.click("#post [data-kind=survey][data-key=ball_protection][data-value=sometimes]");
    await page.click("#post [data-kind=survey][data-key=stalling][data-value=no]");
    await page.fill("#survey-bugs", "No rules problems seen by the suite.");
    await page.click("#post [data-kind=save-survey]");
    await H.expect(page.locator("#toast")).toContainText("Survey saved");
    await page.click("#post [data-kind=replay][data-index='0']");
    await H.expect(page.locator("#replay-pitch svg")).toBeVisible();
    await page.click("#modal [data-kind=close-modal]");
    const coverage = await page.evaluate(() => window.__bbApi.coverage());
    H.writeJson(`coverage-${side}.json`, { seed, side, steps, coverage, result: over.result, integrity: over.integrity, api_rejections: over.integrity.api_rejections });
    H.expect(errors).toEqual([]);
  });
}
