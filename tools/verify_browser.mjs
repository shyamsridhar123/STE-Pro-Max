/**
 * Real Chromium checks for native CLI artifacts, not a conformance certificate.
 * Uses an already installed Playwright library; never installs browsers/packages.
 * node tools/verify_browser.mjs <render-root> <new-evidence-directory>
 * STE_PLAYWRIGHT_MODULE / STE_BROWSER_EXECUTABLE can select existing local tools.
 */
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.STE_PLAYWRIGHT_MODULE || "playwright");
const [sourceRoot, evidenceRoot] = process.argv.slice(2);
if (!sourceRoot || !evidenceRoot) throw new Error("Provide a render root and a NEW evidence directory.");
const output = path.resolve(evidenceRoot);
await fs.mkdir(output, { recursive: false });
const cases = [];
for (const entry of await fs.readdir(sourceRoot, { withFileTypes: true })) {
  if (!entry.isDirectory()) continue;
  const file = path.join(sourceRoot, entry.name, "manifest.json");
  let manifest;
  try { manifest = JSON.parse(await fs.readFile(file, "utf8")); }
  catch (error) { if (error.code === "ENOENT") continue; throw error; }
  if (manifest.status !== "complete" || !manifest.files?.html) continue;
  assert.equal(path.dirname(path.resolve(manifest.files.html.path)),
    path.resolve(sourceRoot, entry.name), "HTML must stay in its artifact directory.");
  cases.push({ name: entry.name, html: manifest.files.html.path, manifest });
}
assert(cases.length > 0, "No complete native render manifests found.");
const report = {
  scope: "Chromium functional, responsive, no-JS, print, and network checks; not full WCAG or factual verification",
  cases: [], failures: [],
};
let browser;
async function check(name, work) {
  try {
    const evidence = await work();
    report.cases.push({ name, passed: true, ...evidence });
    console.log(`PASS ${name}`);
  } catch (error) {
    report.failures.push({ name, error: String(error.stack || error) });
    console.error(`FAIL ${name}: ${error.message}`);
  }
}
async function opened(item, options, work) {
  const context = await browser.newContext({ serviceWorkers: "block", ...options });
  const network = [], errors = [];
  await context.route("**/*", async route => {
    if (/^https?:/i.test(route.request().url())) {
      network.push(route.request().url());
      await route.abort();
    } else await route.continue();
  });
  const page = await context.newPage();
  page.setDefaultTimeout(5000);
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  try {
    await page.goto(pathToFileURL(path.resolve(item.html)).href, { waitUntil: "load" });
    const result = await work(page);
    assert.deepEqual(network, [], "Unexpected outbound runtime request");
    assert.deepEqual(errors, [], "Browser/runtime errors");
    return { ...result, outboundRequests: network, consoleErrors: errors };
  } finally { await context.close(); }
}
try {
  browser = await chromium.launch({
    headless: true,
    ...(process.env.STE_BROWSER_EXECUTABLE ? { executablePath: process.env.STE_BROWSER_EXECUTABLE } : {}),
  });
  report.browserVersion = browser.version();
  for (const item of cases) {
    for (const width of [1280, 375, 320]) {
      await check(`${item.name}-${width}px`, () => opened(item, {
        viewport: { width, height: 900 }, reducedMotion: "reduce",
      }, async page => {
        const layout = await page.evaluate(() => ({
          viewport: innerWidth,
          pageWidth: document.documentElement.scrollWidth,
          reducedMotion: matchMedia("(prefers-reduced-motion: reduce)").matches,
          duplicateIds: [...document.querySelectorAll("[id]")].map(e => e.id)
            .filter((id, i, ids) => ids.indexOf(id) !== i),
          brokenAnchors: [...document.querySelectorAll('a[href^="#"]')]
            .map(a => a.getAttribute("href"))
            .filter(href => href.length > 1 && !document.getElementById(decodeURIComponent(href.slice(1)))),
          unnamedImages: [...document.querySelectorAll('svg[role="img"]')]
            .filter(e => !(e.getAttribute("aria-label") || e.getAttribute("aria-labelledby"))).length,
        }));
        await page.screenshot({ path: path.join(output, `${item.name}-${width}.png`), fullPage: true });
        assert(layout.pageWidth <= width + 1, `Page-level overflow: ${layout.pageWidth} > ${width}`);
        assert(layout.reducedMotion);
        assert.deepEqual(layout.duplicateIds, []);
        assert.deepEqual(layout.brokenAnchors, []);
        assert.equal(layout.unnamedImages, 0);
        for (const region of await page.locator('figure [role="region"],.table-scroll[role="region"]').all()) {
          assert(await region.getAttribute("aria-label"));
          assert.equal(await region.getAttribute("tabindex"), "0");
          await region.focus();
          await region.press("ArrowRight");
        }
        return { layout, figures: await page.locator("figure").count() };
      }));
    }
    await check(`${item.name}-reader-controls-print`, () => opened(item, {
      viewport: { width: 1280, height: 900 },
    }, async page => {
      const root = page.locator("[data-ste-story]");
      if (!await root.count()) return { applicable: false };
      const count = await page.locator("[data-story-beat]").count();
      assert.equal(await page.locator("[data-story-beat]:visible").count(), count);
      const mode = page.locator("[data-story-mode]");
      await mode.focus();
      await mode.press("Enter");
      assert.equal(await mode.getAttribute("aria-pressed"), "true");
      assert.equal(await page.locator("[data-story-beat]:visible").count(), 1);
      assert(await page.locator("[data-story-previous]").isDisabled());
      for (let i = 1; i < count; i++) {
        await page.locator("[data-story-next]").press("Enter");
        assert.equal(await page.locator("[data-story-beat]:visible").count(), 1);
        assert.match(await page.locator("[data-story-progress]").innerText(), new RegExp(`Beat ${i + 1} of ${count}`));
        assert.equal(await page.evaluate(() => document.activeElement.tagName), "H2");
      }
      assert(await page.locator("[data-story-next]").isDisabled());
      if (count > 1) {
        await page.locator("[data-story-previous]").press("Enter");
        assert.match(await page.locator("[data-story-progress]").innerText(), new RegExp(`Beat ${count - 1} of`));
        await page.locator("[data-story-link]").last().click();
        await page.locator("[data-story-link]").first().click();
        await page.goBack();
        assert(await page.locator("[data-story-beat]").last().isVisible(), "History target is hidden");
      }
      await page.emulateMedia({ media: "print" });
      assert.equal(await page.locator("[data-story-beat]:visible").count(), count, "Print hides story beats");
      const printAnswers = page.locator("[data-story-print-answer]");
      assert.equal(await printAnswers.count(), await page.locator(".ste-question details").count());
      for (const answer of await printAnswers.all()) {
        assert(await answer.isVisible(), "Print hides an answer");
      }
      await page.screenshot({ path: path.join(output, `${item.name}-print.png`), fullPage: true });
      await page.emulateMedia({ media: "screen" });
      await mode.click();
      assert.equal(await page.locator("[data-story-beat]:visible").count(), count);
      for (const summary of await page.locator(".ste-question summary").all()) {
        await summary.press("Enter");
        assert(await summary.evaluate(node => node.parentElement.open));
      }
      return { beats: count, keyboardNavigation: true, historyNavigation: true, printAllContent: true };
    }));
    await check(`${item.name}-no-javascript`, () => opened(item, {
      viewport: { width: 375, height: 900 }, javaScriptEnabled: false,
    }, async page => {
      const count = await page.locator("[data-story-beat]").count();
      assert.equal(await page.locator("[data-story-beat]:visible").count(), count);
      if (count) {
        assert(!await page.locator(".ste-story-controls").isVisible());
        assert(await page.getByRole("heading", { name: "Source register", exact: true }).isVisible());
        await page.emulateMedia({ media: "print" });
        const printAnswers = page.locator("[data-story-print-answer]");
        assert.equal(await printAnswers.count(), await page.locator(".ste-question details").count());
        for (const answer of await printAnswers.all()) {
          assert(await answer.isVisible(), "No-JS print hides an answer");
        }
      }
      return { beatsVisible: count, noJavaScript: true };
    }));
    await check(`${item.name}-print-layout`, () => opened(item, {
      viewport: { width: 794, height: 1123 }, javaScriptEnabled: false,
    }, async page => {
      await page.emulateMedia({ media: "print" });
      const layout = await page.evaluate(() => ({
        pageWidth: document.documentElement.scrollWidth,
        viewport: innerWidth,
        clippedRegions: [...document.querySelectorAll('figure [role="region"]')].filter(region => {
          const svg = region.querySelector("svg");
          return svg && svg.getBoundingClientRect().bottom > region.getBoundingClientRect().bottom + 2;
        }).map(region => region.getAttribute("aria-label")),
      }));
      assert(layout.pageWidth <= layout.viewport + 1, "Print has page-level horizontal overflow");
      assert.deepEqual(layout.clippedRegions, [], "Print SVG extends beyond its allocated region");
      await page.pdf({ path: path.join(output, `${item.name}.pdf`), format: "A4", printBackground: true });
      return { layout, pdf: `${item.name}.pdf`, javascriptDisabled: true };
    }));
  }
} catch (error) {
  report.failures.push({ name: "browser-run", error: String(error.stack || error) });
  console.error(error.message);
} finally {
  if (browser) await browser.close();
  report.passed = report.failures.length === 0;
  await fs.writeFile(path.join(output, "browser-results.json"), JSON.stringify(report, null, 2) + "\n");
}
if (!report.passed) process.exitCode = 1;
