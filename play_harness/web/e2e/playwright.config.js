// Browser suite for the play harness. The server holds one game at a time, so
// specs run serially against one server process started by webServer.
const path = require("path");
const { defineConfig } = require("@playwright/test");

const PORT = Number(process.env.BBPLAY_E2E_PORT || 8797);
const ROOT = process.env.BBPLAY_ROOT || path.resolve(__dirname, "..", "..", "..");
const OUT = path.join(__dirname, "out");

module.exports = defineConfig({
  testDir: path.join(__dirname, "specs"),
  outputDir: path.join(OUT, "test-results"),
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 20 * 60 * 1000,
  expect: { timeout: 15000 },
  reporter: [["list"], ["json", { outputFile: path.join(OUT, "results.json") }]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    viewport: { width: 1440, height: 900 },
    actionTimeout: 30000,
    navigationTimeout: 30000,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    command: `bash ${path.join(ROOT, "play_harness", "run.sh")} --port ${PORT} --games-dir ${path.join(OUT, "games")}`,
    url: `http://127.0.0.1:${PORT}/health`,
    reuseExistingServer: false,
    timeout: 180 * 1000,
    stdout: "pipe",
    stderr: "pipe",
    env: { OMP_NUM_THREADS: process.env.OMP_NUM_THREADS || "2" },
  },
});
