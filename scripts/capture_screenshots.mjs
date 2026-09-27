#!/usr/bin/env node
/**
 * Regenerate the screenshots in docs/screenshots/ from a live DEMO_MODE run.
 *
 * This script does not start the app. From the repository root, start it in
 * demo mode first (no API key or network access needed):
 *
 *   DEMO_MODE=1 uv run streamlit run app.py --server.headless true \
 *     --server.port 8599 --browser.gatherUsageStats false
 *
 * Playwright is not a dependency of this repository. Install it somewhere
 * outside the repo and point NODE_PATH at it, for example:
 *
 *   mkdir -p /tmp/pw && (cd /tmp/pw && npm init -y && npm install playwright@1.56.1)
 *   NODE_PATH=/tmp/pw/node_modules node scripts/capture_screenshots.mjs
 *
 * Environment overrides:
 *   APP_URL        default http://localhost:8599
 *   MODE           "real" captures gap-analyzer-real-scf-2026-3.png from a real-data run
 *   OUT_DIR        default docs/screenshots
 *   CHROMIUM_PATH  default: Playwright's bundled Chromium (set it to use an
 *                  installed binary, e.g. /opt/pw-browsers/chromium-1194/chrome-linux/chrome)
 *
 * Shots use a 1440x1100 viewport at deviceScaleFactor 1, and wait for a
 * visible selector rather than a fixed sleep.
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

// Resolve playwright through NODE_PATH as well (ESM imports ignore it).
const require = createRequire(path.join(process.cwd(), "noop.js"));
const { chromium } = require("playwright");

const APP_URL = process.env.APP_URL || "http://localhost:8599";
const OUT_DIR = process.env.OUT_DIR || "docs/screenshots";
const CHROMIUM_PATH = process.env.CHROMIUM_PATH || undefined;
// MODE=real captures the one real-data screenshot instead of the demo set:
// the Gap Analyzer against a downloaded SCF release (no Groq key needed).
// Start the app WITHOUT DEMO_MODE, with the SCF data in data/.
const REAL = process.env.MODE === "real";

async function shot(page, name) {
  await mkdir(OUT_DIR, { recursive: true });
  const file = path.join(OUT_DIR, `${name}.png`);
  await page.screenshot({ path: file, fullPage: false });
  console.log(`captured ${file}`);
}

async function idle(page) {
  // Streamlit shows a "Running..." status widget while a script run is active.
  await page.waitForTimeout(300);
  await page
    .locator('[data-testid="stStatusWidget"]')
    .waitFor({ state: "detached", timeout: 60_000 })
    .catch(() => {});
}

async function openTool(page, tool) {
  await page.goto(APP_URL, { waitUntil: "networkidle" });
  if (!REAL) await page.getByText("DEMO MODE").first().waitFor();
  await page.locator('[data-testid="stSidebar"]').getByText(tool).click();
  await page.getByRole("heading", { name: tool }).waitFor();
  await idle(page);
}

async function pick(page, label, option) {
  // Streamlit selectboxes are comboboxes labelled by their widget label.
  await page.getByRole("combobox", { name: label }).first().click();
  await page.getByRole("option", { name: option, exact: true }).click();
  await idle(page);
}

async function scrollTo(page, locator, offset = 0) {
  // Put the element near the top of Streamlit's scrolling main container.
  await locator.first().evaluate((el) => el.scrollIntoView({ block: "start" }));
  if (offset) await page.mouse.wheel(0, offset);
  await page.waitForTimeout(400);
}

async function main() {
  const browser = await chromium.launch({ executablePath: CHROMIUM_PATH });
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 1100 },
    deviceScaleFactor: 1,
    // The app's CSS is dark; match Streamlit's own theme to it.
    colorScheme: "dark",
  });
  const page = await ctx.newPage();

  if (REAL) {
    await openTool(page, "📉 Compliance Gap Analyzer");
    await pick(page, "Or select Lab Data", "sample_controls_with_scf_mapping.csv");
    await page.getByRole("button", { name: /Run Gap Analysis/ }).click();
    await page.getByText(/controls mapped/).first().waitFor();
    await idle(page);
    // The per-requirement table shows framework references and SCF IDs only.
    await scrollTo(page, page.getByText(/were not counted/), -90);
    await shot(page, "gap-analyzer-real-scf-2026-3");
    await ctx.close();
    await browser.close();
    return;
  }

  // 1. Crosswalker, single input: suggestions and the rejected-ID warning.
  await openTool(page, "🔍 SCF Auto-Crosswalker");
  await pick(page, "Select Sample", "sample_endpoint_policy.txt");
  await page.getByRole("button", { name: /Suggest .*Controls/ }).click();
  await page.getByText("Suggestions ready").first().waitFor();
  await idle(page);
  await scrollTo(page, page.getByText(/not among the .* candidates/), -120);
  await shot(page, "crosswalker-single-suggestions-and-rejected-id");

  // 2. Crosswalker, batch: the Security Hub lab export, ranked, with exports.
  await openTool(page, "🔍 SCF Auto-Crosswalker");
  await pick(page, "Select Sample", "aws_securityhub_finding.json");
  await page.getByRole("button", { name: /Suggest .*Controls/ }).click();
  await page.getByText("Batch mapping complete").first().waitFor();
  await idle(page);
  // Collapse the suggestion cards so the ranking and the exports fit.
  for (const n of [1, 2, 3]) {
    await page.locator("summary").filter({ hasText: `#${n} |` }).click();
  }
  await page.waitForTimeout(400);
  await scrollTo(page, page.getByText(/not among the .* candidates/), -120);
  await shot(page, "crosswalker-batch-ranked-summary-and-exports");

  // 3. Gap Analyzer on the demo lab CSV.
  await openTool(page, "📉 Compliance Gap Analyzer");
  await pick(page, "Or select Lab Data", "demo_existing_controls.csv");
  await page.getByRole("button", { name: /Run Gap Analysis/ }).click();
  await page.getByText(/controls mapped/).first().waitFor();
  await idle(page);
  await scrollTo(page, page.getByText(/cannot match anything/), -130);
  await shot(page, "gap-analyzer-metrics");

  // 4. Audit Scope Analyzer on the lab scope.
  await openTool(page, "🎯 Audit Scope Analyzer");
  await pick(page, "Select Sample", "sample_audit_scope.txt");
  await page.getByRole("button", { name: /Suggest Controls to Test/ }).click();
  await page.getByText("Suggested Controls to Test").first().waitFor();
  await idle(page);
  await scrollTo(page, page.getByText(/not among the .* candidates/), -120);
  await shot(page, "scope-analyzer-result");

  await ctx.close();
  await browser.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
