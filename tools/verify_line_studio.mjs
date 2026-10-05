/** Isolated, offline real-Chrome behavior checks. Never installs packages or browsers.
 * node tools/verify_line_studio.mjs --evidence-dir artifacts/line-studio-20261004/qa-verifier-<unique>
 * Optional --source-root; STE_PLAYWRIGHT_MODULE and STE_BROWSER_EXECUTABLE override existing tools.
 */
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
const require = createRequire(import.meta.url);
const args = process.argv.slice(2), flags = {};
for (let i = 0; i < args.length; i += 2) {
  assert(["--evidence-dir", "--source-root"].includes(args[i]) && args[i + 1], "Expected --evidence-dir PATH [--source-root PATH]");
  assert(!flags[args[i]], `Duplicate flag ${args[i]}`);
  flags[args[i]] = args[i + 1];
}
assert(flags["--evidence-dir"], "A NEW --evidence-dir is required");
const root = path.resolve(flags["--source-root"] || path.join(path.dirname(fileURLToPath(import.meta.url)), ".."));
const output = path.resolve(flags["--evidence-dir"]);
await fs.mkdir(output, { recursive: false });
const report = { command: [process.execPath, ...process.argv.slice(1)], sourceRoot: root,
  startedAt: new Date().toISOString(), scope: "Offline headless Chromium; mathematical readouts, keyboard/pointer behavior, lifecycle, export, no-JS, print, responsive. Not full accessibility certification.",
  sources: {}, cases: [], failures: [], gaps: [] };
let browser;
const sources = {};
async function read(relative, optional = false) {
  try {
    const content = await fs.readFile(path.join(root, relative), "utf8");
    sources[relative] = content;
    report.sources[relative] = createHash("sha256").update(content).digest("hex");
    return content;
  } catch (error) { if (optional && error.code === "ENOENT") return null; throw error; }
}
// Instrument native scheduling and listeners without replacing their behavior.
// Freeze listener enrollment after mounting in interactive leak checks so Playwright
// selector/action helpers are not misreported as product listeners.
function instrument() {
  const frames = new Set(), listeners = [], observers = new Set();
  let scheduled = 0, fired = 0, tracking = true;
  const request = window.requestAnimationFrame.bind(window), cancel = window.cancelAnimationFrame.bind(window);
  window.requestAnimationFrame = callback => {
    let id = request(time => { frames.delete(id); fired++; callback(time); });
    scheduled++; frames.add(id); return id;
  };
  window.cancelAnimationFrame = id => { frames.delete(id); cancel(id); };
  const add = EventTarget.prototype.addEventListener, remove = EventTarget.prototype.removeEventListener;
  const capture = options => typeof options === "boolean" ? options : !!options?.capture;
  EventTarget.prototype.addEventListener = function(type, callback, options) {
    if (tracking && !listeners.some(x => x.target === this && x.type === type && x.callback === callback && x.capture === capture(options))) {
      listeners.push({ target: this, type, callback, capture: capture(options) });
    }
    return add.call(this, type, callback, options);
  };
  EventTarget.prototype.removeEventListener = function(type, callback, options) {
    const index = listeners.findIndex(x => x.target === this && x.type === type && x.callback === callback && x.capture === capture(options));
    if (index >= 0) listeners.splice(index, 1);
    return remove.call(this, type, callback, options);
  };
  const IO = window.IntersectionObserver;
  window.IntersectionObserver = class extends IO {
    observe(target) { observers.add(this); return super.observe(target); }
    disconnect() { observers.delete(this); return super.disconnect(); }
  };
  window.__qa = { trackListeners: value => { tracking = value; }, snapshot: () => ({ pending: frames.size, scheduled, fired, listeners: listeners.length, observers: observers.size }) };
}
async function opened(html, options, work) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce",
    serviceWorkers: "block", acceptDownloads: true, ...options });
  const requests = [], errors = [];
  await context.route("**/*", async route => {
    const url = route.request().url();
    if (!/^(?:file:|data:|blob:|about:)/i.test(url)) { requests.push(url); await route.abort(); }
    else await route.continue();
  });
  if (context.routeWebSocket) await context.routeWebSocket(/.*/, socket => { requests.push(socket.url()); socket.close(); });
  await context.setOffline(true);
  const page = await context.newPage();
  page.setDefaultTimeout(5000);
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  try {
    if (options?.javaScriptEnabled !== false) await page.evaluate(instrument);
    await page.setContent(html, { waitUntil: "load" });
    const evidence = await work(page);
    assert.deepEqual(requests, [], "Unexpected outbound runtime request");
    assert.deepEqual(errors, [], "Browser errors");
    return { ...evidence, requests, errors };
  } catch (error) {
    error.browserEvidence = { requests, errors };
    await page.screenshot({ path: path.join(output, `failure-${report.cases.length + report.failures.length}.png`), fullPage: true }).catch(() => {});
    throw error;
  } finally { await context.close(); }
}
async function check(name, work) {
  try { const evidence = await work(); report.cases.push({ name, passed: true, ...evidence }); console.log(`PASS ${name}`); }
  catch (error) { report.failures.push({ name, error: error.stack || String(error), ...error.browserEvidence }); console.error(`FAIL ${name}: ${error.message}`); }
}
const retry = name => `[data-retry-${name}]`;
async function stationary(page, expression) {
  // A bounded observation window proves inactivity after cancellation; not a readiness sleep/retry.
  const before = await page.evaluate(expression);
  await page.evaluate(() => new Promise(resolve => setTimeout(resolve, 180)));
  assert.deepEqual(await page.evaluate(expression), before, "State or RAF activity changed after motion stopped");
  return before;
}
async function inspectSVG(page, svg) {
  const result = await page.evaluate(svg => {
    const xml = new DOMParser().parseFromString(svg, "image/svg+xml");
    return { parseErrors: xml.querySelectorAll("parsererror").length,
      root: xml.documentElement.localName, namespace: xml.documentElement.namespaceURI,
      forbidden: xml.querySelectorAll("script,foreignObject,image,iframe,object,embed").length,
      unsafe: [...xml.querySelectorAll("*")].flatMap(node => [...node.attributes].filter(a =>
        /^on/i.test(a.name) || (/^(href|xlink:href|src)$/i.test(a.name) && !a.value.startsWith("#")) ||
        /url\s*\(\s*["']?(?!#)[^\s]/i.test(a.value)).map(a => a.name + "=" + a.value)),
      title: xml.querySelector("title")?.textContent, description: xml.querySelector("desc")?.textContent,
      metadata: xml.querySelector("metadata")?.textContent };
  }, svg);
  assert.equal(result.parseErrors, 0); assert.equal(result.root, "svg");
  assert.equal(result.namespace, "http://www.w3.org/2000/svg");
  assert.equal(result.forbidden, 0); assert.deepEqual(result.unsafe, []);
  assert(result.title && result.description);
  return result;
}
try {
  const { chromium } = require(process.env.STE_PLAYWRIGHT_MODULE || "playwright");
  const math = await read("ste_promax/assets/line-math.js");
  const studio = await read("ste_promax/assets/line-studio.js");
  await read("ste_promax/assets/retry-observatory.js");
  const flagship = await read("examples/showcase/retry-observatory.html");
  const catalogue = await read("examples/showcase/line-studio.html", true);
  const safeScript = source => source.replace(/<\/script/gi, "<\\/script");
  const runtime = `<!doctype html><meta charset="utf-8"><style>body{margin:20px} .host{max-width:600px}</style><div id="one" class="host" data-owner="retained"><p id="retained">Owner content</p></div><div id="two" class="host"></div><script>${safeScript(math)}</script><script>${safeScript(studio)}</script>`;
  browser = await chromium.launch({ headless: true,
    ...(process.env.STE_BROWSER_EXECUTABLE ? { executablePath: process.env.STE_BROWSER_EXECUTABLE } : {}),
    args: ["--disable-background-networking", "--disable-component-update", "--no-first-run"] });
  report.browserVersion = browser.version();
  for (const width of [1440, 375, 240]) {
    await check(`retry responsive ${width}px`, () => opened(flagship, { viewport: { width, height: 1000 } }, async page => {
      const layout = await page.evaluate(() => {
        const region = document.querySelector("[data-retry-drawing-region]");
        return { viewport: innerWidth, width: document.documentElement.scrollWidth,
          regionWidth: region.clientWidth, chartWidth: region.scrollWidth,
          overflow: getComputedStyle(region).overflowX, tabIndex: region.tabIndex,
          name: region.getAttribute("aria-label"), overflowNodes: [...document.querySelectorAll(".workspace,.lesson,.inputs,.input-label,.chapter-list,.canvas-toolbar,.transport-buttons,.comparison,.lower,table")].map(node => ({ selector: node.className || node.tagName, width: node.getBoundingClientRect().width, right: node.getBoundingClientRect().right })).filter(node => node.right > innerWidth) };
      });
      await page.screenshot({ path: path.join(output, `retry-${width}.png`), fullPage: true });
      await fs.writeFile(path.join(output, `retry-${width}-layout.json`), JSON.stringify(layout, null, 2));
      assert(layout.width <= width + 1, `Page overflow: ${layout.width}px > ${width}px`);
      assert.equal(layout.tabIndex, 0); assert(layout.name);
      if (width < 640) {
        assert(layout.chartWidth > layout.regionWidth, "Small-screen chart should scroll within its region");
        assert.equal(layout.overflow, "auto");
        await page.locator(retry("drawing-region")).focus();
        await page.locator(retry("drawing-region")).press("ArrowRight");
        await page.waitForFunction(() => document.querySelector("[data-retry-drawing-region]").scrollLeft > 0, null, { polling: 20 });
      }
      return { layout };
    }));
  }
  await check("retry all 16 budgets via keyboard and mathematical accessible readouts", () => opened(flagship, {}, async page => {
    for (let A = 1; A <= 4; A++) for (let L = 1; L <= 4; L++) {
      for (const [name, value] of [["attempts", A], ["layers", L]]) {
        const slider = page.locator(retry(name)); await slider.focus(); await slider.press("Home");
        for (let i = 1; i < value; i++) await slider.press("ArrowRight");
      }
      assert.equal(await page.locator(retry("nested-total")).innerText(), String(A ** L));
      assert.equal(await page.locator(retry("owner-total")).innerText(), String(A));
      assert.equal(await page.locator(retry("counts") + " tr").count(), L);
      for (let i = 0; i < L; i++) assert.deepEqual(await page.locator(retry("counts") + " tr").nth(i).locator("td").allTextContents(), [String(A ** (i + 1)), String(A)]);
      const formula = await page.locator(retry("formula")).getAttribute("aria-label");
      const expected = A === 1 ? (L === 1 ? "1 equals 1" : `1 to the power ${L} equals 1`)
        : L === 1 ? `${A} equals ${A}` : `${A} to the power ${L} equals ${A ** L}`;
      assert.equal(formula.replace(/\s+/g, " ").trim(), expected);
      if (A === 1 || L === 1) assert.equal(await page.locator(retry("difference")).innerText(), "No amplification in this setting.");
    }
    return { combinations: 16, inputMethod: "native slider Home/ArrowRight" };
  }));
  await check("retry chapters, timeline, previous/next, reset and theme", () => opened(flagship, {}, async page => {
    for (let i = 0; i < 4; i++) {
      const button = page.locator(`[data-retry-chapter="${i}"]`); await button.press("Enter");
      assert.equal(await button.getAttribute("aria-current"), "step");
      assert.equal(await page.locator('[data-retry-chapter][aria-current="step"]').count(), 1);
      assert.equal(await page.evaluate(() => STERetryObservatory.explanation(steRetryExample.state).index), i);
    }
    const timeline = page.locator(retry("timeline")); await timeline.press("Home");
    assert(await page.locator(retry("previous")).isDisabled());
    await page.locator(retry("next")).press("Enter");
    assert.equal(await timeline.inputValue(), "160");
    await page.locator(retry("previous")).press("Enter"); assert.equal(await timeline.inputValue(), "0");
    await timeline.press("End"); assert(await page.locator(retry("next")).isDisabled());
    await page.locator(retry("theme")).press("Enter");
    assert.equal(await page.locator("[data-retry-observatory]").getAttribute("data-theme"), "light");
    await page.locator(retry("reset")).press("Enter");
    assert.equal(await timeline.inputValue(), "720");
    assert.equal(await page.locator(retry("nested-total")).innerText(), "81");
  }));
  await check("retry play advances then pause cancels every frame", () => opened(flagship, { reducedMotion: "no-preference" }, async page => {
    await page.locator(retry("play")).click();
    await page.waitForFunction(() => steRetryExample.state.playing && steRetryExample.state.progress > 0.002, null, { polling: 20 });
    await page.locator(retry("play")).click();
    assert.equal(await page.locator(retry("play")).getAttribute("aria-pressed"), "false");
    const stable = await stationary(page, () => ({ state: steRetryExample.state, frames: __qa.snapshot() }));
    assert.equal(stable.frames.pending, 0);
    return stable;
  }));
  await check("retry dynamic reduced motion cancels play and advances by discrete idea", () => opened(flagship, { reducedMotion: "no-preference" }, async page => {
    await page.locator(retry("play")).click();
    await page.waitForFunction(() => steRetryExample.state.progress > 0.002 && steRetryExample.state.playing, null, { polling: 20 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.waitForFunction(() => steRetryExample.state.reducedMotion && !steRetryExample.state.playing, null, { polling: 20 });
    assert.match(await page.locator(retry("drawing-region")).getAttribute("aria-label"), /Space advances to the next idea/);
    await page.locator(retry("drawing-region")).press("Space");
    assert.equal(await page.evaluate(() => steRetryExample.state.progress), 0.16);
    const stable = await stationary(page, () => ({ state: steRetryExample.state, frames: __qa.snapshot() }));
    assert.equal(stable.frames.pending, 0);
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await page.waitForFunction(() => !steRetryExample.state.reducedMotion, null, { polling: 20 });
    assert.equal(await page.evaluate(() => steRetryExample.state.playing), false);
    return stable;
  }));
  await check("retry no-JS static reading and assumptions", () => opened(flagship, { javaScriptEnabled: false }, async page => {
    assert.equal(await page.locator(retry("nested-total")).innerText(), "81");
    assert.equal(await page.locator(retry("owner-total")).innerText(), "3");
    assert(await page.locator(retry("drawing") + " svg").isVisible());
    assert.match(await page.locator("noscript").innerText(), /3 × 3 × 3 × 3 = 81/);
    for (const control of await page.locator("[data-retry-controls] button,[data-retry-controls] input").all()) assert(await control.isDisabled());
    assert(await page.getByText("What this model assumes", { exact: true }).isVisible());
    await page.screenshot({ path: path.join(output, "retry-no-js.png"), fullPage: true });
  }));
  for (const closed of [false, true]) await check(`retry print retains ${closed ? "collapsed" : "open"} assumptions`, () => opened(flagship, {}, async page => {
    if (closed) await page.getByText("What this model assumes", { exact: true }).click();
    await page.emulateMedia({ media: "print" });
    await page.pdf({ path: path.join(output, `retry-print-${closed ? "collapsed" : "open"}.pdf`), format: "A4", printBackground: true });
    assert(await page.getByText("One original request and serial layers, each calling only the next layer.", { exact: true }).isVisible(), "Print hides model assumptions");
    assert(await page.getByText(/Fewer attempts is not a resilience guarantee/).isVisible());
    assert(await page.locator(retry("drawing") + " svg").isVisible());
    assert.equal(await page.locator(retry("nested-total")).innerText(), "81");
  }));
  await check("retry downloaded SVG parses and embeds assumptions without executable or remote content", () => opened(flagship, {}, async page => {
    const event = page.waitForEvent("download"); await page.locator(retry("export")).click();
    const download = await event; const file = path.join(output, "retry-export.svg"); await download.saveAs(file);
    const svg = await fs.readFile(file, "utf8"); assert.equal(svg, await page.evaluate(() => steRetryExample.toSVG()));
    const parsed = await inspectSVG(page, svg); const metadata = JSON.parse(parsed.metadata);
    assert.equal(metadata.nestedBackend, 81); assert.equal(metadata.ownerBackend, 3);
    assert.match(metadata.limits, /Persistent failure/);
    return { download: download.suggestedFilename(), parsed };
  }));
  await check("retry policy transition 0.85 and 0.875 keeps figure, formula, chapter and comparison consistent", () => opened(flagship, {}, async page => {
    for (const [progress, index, count, policy, formula] of [
      [0.85, 2, "81", "nested", "3 to the power 4 equals 81"],
      [0.875, 3, "3", "owner", "3 times 1 times 1 times 1 equals 3"],
    ]) {
      await page.evaluate(progress => steRetryExample.set({ progress }), progress);
      assert.equal(await page.locator('[data-retry-chapter][aria-current="step"]').getAttribute("data-retry-chapter"), String(index));
      assert.equal(await page.locator(retry("comparison")).getAttribute("data-active"), policy);
      assert.equal((await page.locator(retry("formula")).getAttribute("aria-label")).replace(/\s+/g, " ").trim(), formula);
      const backendTexts = await page.locator('[data-retry-drawing] [data-boundary="4"] > text').allTextContents();
      assert.deepEqual(backendTexts, ["Backend", count, "attempts", policy === "nested" ? "×3" : "×1"]);
      assert.match(await page.locator('[data-retry-drawing] svg > desc').textContent(), /policy transition is in progress/);
    }
  }));
  await check("retry synchronous play/pause keeps visible state and export aligned; manual 0.72 resumes", () => opened(flagship, { reducedMotion: "no-preference" }, async page => {
    // Both clicks run in one browser task: no RAF can run between them.
    const evidence = await page.evaluate(() => {
      const root = document.querySelector("[data-retry-observatory]");
      const play = root.querySelector("[data-retry-play]");
      function snapshot() {
        const state = steRetryExample.state, exported = steRetryExample.toSVG();
        const expectedDrawing = document.createElement("div");
        expectedDrawing.innerHTML = exported; // Compare DOM serialization, not XML/HTML spelling.
        const expected = STERetryObservatory.explanation(state);
        return {
          progress: state.progress, playing: state.playing,
          visibleMatchesExport: root.querySelector("[data-retry-drawing]").innerHTML === expectedDrawing.innerHTML,
          exportedProgress: JSON.parse(expectedDrawing.querySelector("metadata").textContent).progress,
          timeline: Number(root.querySelector("[data-retry-timeline]").value),
          headlineMatchesState: root.querySelector("[data-retry-headline]").textContent === expected.title,
          formulaMatchesState: root.querySelector("[data-retry-formula]").getAttribute("aria-label").replace(/\s+/g, " ").trim()
            === expected.formula.replace(/\^(\d+)/g, " to the power $1").replace(/×/g, " times ").replace(/=/g, " equals ").replace(/\s+/g, " ").trim(),
          pressed: play.getAttribute("aria-pressed"), frames: __qa.snapshot(),
        };
      }
      const before = snapshot();
      play.click(); const started = snapshot();
      play.click(); const paused = snapshot();
      steRetryExample.set({ progress: 0.72 });
      play.click(); const resumed = snapshot();
      play.click(); const pausedAgain = snapshot();
      return { before, started, paused, resumed, pausedAgain };
    });
    assert.equal(evidence.before.progress, 0.72);
    for (const [name, progress, playing] of [["started", 0, true], ["paused", 0, false],
      ["resumed", 0.72, true], ["pausedAgain", 0.72, false]]) {
      const snapshot = evidence[name];
      assert.equal(snapshot.progress, progress, name);
      assert.equal(snapshot.exportedProgress, progress, `${name}: exported progress`);
      assert.equal(snapshot.timeline, Math.round(progress * 1000), `${name}: visible timeline`);
      assert(snapshot.visibleMatchesExport && snapshot.headlineMatchesState && snapshot.formulaMatchesState,
        `${name}: visible drawing/narrative/formula must match state and export`);
      assert.equal(snapshot.playing, playing);
      assert.equal(snapshot.pressed, String(playing));
      assert.equal(snapshot.frames.pending, playing ? 1 : 0);
      assert.equal(snapshot.frames.fired, evidence.before.frames.fired, "RAF ran between synchronous clicks");
    }
    await stationary(page, () => ({ state: steRetryExample.state, svg: steRetryExample.toSVG(), frames: __qa.snapshot() }));
    return evidence;
  }));
  await check("retry missing export rejects mount before mutation; restored mount destroys without leaks", () => opened(flagship, { reducedMotion: "no-preference" }, async page => {
    const evidence = await page.evaluate(() => {
      const root = document.querySelector("[data-retry-observatory]");
      steRetryExample.destroy();
      const exportButton = root.querySelector("[data-retry-export]");
      const parent = exportButton.parentNode, next = exportButton.nextSibling;
      exportButton.remove();
      const beforeHTML = root.innerHTML, beforeNodes = [...root.querySelectorAll("*")];
      const baseline = __qa.snapshot();
      let failure = null, unexpected;
      try { unexpected = STERetryObservatory.mount(root); }
      catch (error) { failure = error.message; }
      const rejected = {
        failure, unchangedHTML: root.innerHTML === beforeHTML,
        unchangedNodes: beforeNodes.every((node, index) => root.querySelectorAll("*")[index] === node),
        frames: __qa.snapshot(),
      };
      unexpected?.destroy();
      parent.insertBefore(exportButton, next);
      const fresh = STERetryObservatory.mount(root);
      const mounted = __qa.snapshot();
      fresh.set({ progress: 0.36 });
      const valid = Number(root.querySelector("[data-retry-timeline]").value) === 360
        && fresh.state.progress === 0.36 && !exportButton.disabled;
      root.querySelector("[data-retry-play]").click();
      const playing = { state: fresh.state, frames: __qa.snapshot() };
      fresh.destroy(); fresh.destroy();
      return { baseline, rejected, mounted, valid, playing, final: __qa.snapshot() };
    });
    assert.match(evidence.rejected.failure || "", /Incomplete observatory markup/);
    assert(evidence.rejected.unchangedHTML && evidence.rejected.unchangedNodes, "Invalid mount mutated existing DOM");
    assert.deepEqual(evidence.rejected.frames, evidence.baseline, "Invalid mount registered listeners, observers or frames");
    assert(evidence.valid, "Restored markup did not mount a usable instance");
    assert(evidence.mounted.listeners > evidence.baseline.listeners, "Listener instrumentation did not observe mount");
    assert.equal(evidence.mounted.pending, 0, "Fresh idle mount scheduled animation");
    assert(evidence.playing.state.playing);
    assert.equal(evidence.playing.frames.pending, 1);
    assert.equal(evidence.final.pending, 0);
    assert.equal(evidence.final.listeners, evidence.baseline.listeners, "Failed or destroyed mount leaked listeners");
    assert.equal(evidence.final.observers, evidence.baseline.observers, "Destroyed mount leaked an observer");
    await stationary(page, () => __qa.snapshot());
    return evidence;
  }));
  await check("retry destroy between beforeprint and afterprint restores details/theme and removes listeners/frames", () => opened(flagship, { reducedMotion: "no-preference" }, async page => {
    const evidence = await page.evaluate(() => {
      const root = document.querySelector("[data-retry-observatory]");
      steRetryExample.destroy();
      const baseline = __qa.snapshot();
      const fresh = STERetryObservatory.mount(root);
      const details = [...root.querySelectorAll("details")];
      root.querySelector("[data-retry-play]").click();
      details[0].open = false;
      const original = { details: details.map(node => node.open), theme: fresh.state.theme, svg: fresh.toSVG() };
      const before = __qa.snapshot();
      function snapshot() {
        const expected = document.createElement("div"); expected.innerHTML = fresh.toSVG();
        return {
          details: details.map(node => node.open), theme: fresh.state.theme,
          visibleTheme: root.dataset.theme, originalSVG: fresh.toSVG() === original.svg,
          visibleMatchesExport: root.querySelector("[data-retry-drawing]").innerHTML === expected.innerHTML,
          playing: fresh.state.playing, frames: __qa.snapshot(),
        };
      }
      window.dispatchEvent(new Event("beforeprint"));
      const printing = snapshot();
      fresh.destroy();
      const destroyed = snapshot();
      window.dispatchEvent(new Event("afterprint"));
      const afterPrint = snapshot();
      return { baseline, original: { details: original.details, theme: original.theme }, before, printing, destroyed, afterPrint };
    });
    assert(evidence.original.details.length > 0 && !evidence.original.details[0]);
    assert.equal(evidence.original.theme, "dark");
    assert.equal(evidence.before.pending, 1, "Expected active motion before print");
    assert(evidence.printing.details.every(Boolean));
    assert.equal(evidence.printing.theme, "light");
    assert.equal(evidence.printing.visibleTheme, "light");
    assert.equal(evidence.printing.frames.pending, 0, "Printing did not cancel motion");
    for (const name of ["destroyed", "afterPrint"]) {
      const snapshot = evidence[name];
      assert.deepEqual(snapshot.details, evidence.original.details, `${name}: original disclosure state not restored`);
      assert.equal(snapshot.theme, evidence.original.theme, `${name}: original state theme not restored`);
      assert.equal(snapshot.visibleTheme, evidence.original.theme, `${name}: original visible theme not restored`);
      assert(snapshot.originalSVG && snapshot.visibleMatchesExport, `${name}: original SVG theme not restored`);
      assert.equal(snapshot.playing, false);
      assert.equal(snapshot.frames.pending, 0);
      assert.equal(snapshot.frames.listeners, evidence.baseline.listeners);
      assert.equal(snapshot.frames.observers, evidence.baseline.observers);
    }
    assert.deepEqual(evidence.afterPrint, evidence.destroyed, "afterprint mutated an already destroyed instance");
    await stationary(page, () => ({ markup: document.querySelector("[data-retry-observatory]").innerHTML, frames: __qa.snapshot() }));
    return evidence;
  }));
  const items = [{ label: "First", detail: "First evidence." }, { label: "Second", detail: "Second evidence." }, { label: "Third", detail: "Third evidence." }];
  for (const kind of ["stack", "field", "layers", "signal", "orbit", "flow"]) {
    await check(`${kind}: keyboard/pointer, intensity, themes and static export`, () => opened(runtime, {}, async page => {
      await page.evaluate(({ kind, items }) => { window.handle = STELineStudio.mount(document.getElementById("one"), { kind, items, theme: "light" }); }, { kind, items });
      const part = page.getByRole("combobox");
      await part.focus(); await part.press("End"); await part.press("Enter");
      assert.equal(await part.inputValue(), "2");
      assert.match(await page.getByRole("status").innerText(), /Selected 3 of 3: Third/);
      const surface = page.getByRole("group"); await surface.press("Home");
      if (kind === "orbit") assert.equal(await page.getByLabel("Rotation", { exact: true }).inputValue(), "-180");
      else assert.equal(await part.inputValue(), "0");
      await surface.press("End");
      if (kind === "orbit") assert.equal(await page.getByLabel("Rotation", { exact: true }).inputValue(), "180");
      else assert.equal(await part.inputValue(), "2");
      const before = await page.evaluate(() => handle.toSVG());
      const box = await surface.boundingBox();
      await page.mouse.move(box.x + box.width * 0.2, box.y + box.height * 0.25);
      await page.mouse.down(); await page.mouse.move(box.x + box.width * 0.05, box.y + box.height * 0.25); await page.mouse.up();
      if (kind === "orbit") assert.notEqual(await page.getByLabel("Rotation", { exact: true }).inputValue(), "180");
      else assert.equal(await part.inputValue(), "0");
      assert.notEqual(await page.evaluate(() => handle.toSVG()), before);
      const intensity = page.getByLabel("Intensity", { exact: true });
      await intensity.press("Home"); const low = await page.evaluate(() => handle.toSVG());
      await intensity.press("End"); assert.equal(await intensity.inputValue(), "1");
      assert.notEqual(await page.evaluate(() => handle.toSVG()), low);
      await page.evaluate(() => handle.update({ theme: "dark" }));
      const dark = await page.evaluate(() => handle.toSVG());
      await page.evaluate(() => handle.update({ theme: "light" }));
      assert.notEqual(await page.evaluate(() => handle.toSVG()), dark);
      const svg = await page.evaluate(() => handle.toSVG());
      await inspectSVG(page, svg); await fs.writeFile(path.join(output, `${kind}-export.svg`), svg);
      assert.equal(await page.evaluate(() => __qa.snapshot().pending), 0, "Reduced-motion interaction queues frames");
      await page.screenshot({ path: path.join(output, `${kind}.png`) });
    }));
  }
  await check("runtime malicious text remains inert in browser and exported XML", () => opened(runtime, {}, async page => {
    const malicious = `<img src="https://invalid.example/x" onerror="window.pwned=1"><script>window.pwned=1</script>`;
    await page.evaluate(({ malicious, items }) => { window.handle = STELineStudio.mount(document.getElementById("one"), {
      title: malicious, summary: malicious, items: [{ label: "Hostile", detail: malicious }, items[1]] }); }, { malicious, items });
    assert.equal(await page.evaluate(() => window.pwned), undefined);
    assert.equal(await page.locator("#one img,#one script,#one iframe").count(), 0);
    assert((await page.getByRole("status").innerText()).includes(malicious));
    await inspectSVG(page, await page.evaluate(() => handle.toSVG()));
  }));
  await check("runtime isolated instances, atomic invalid updates, reset, remount and destroy preserve owner DOM", () => opened(runtime, {}, async page => {
    const evidence = await page.evaluate(({ items }) => {
      const baseline = __qa.snapshot();
      const first = STELineStudio.mount(document.getElementById("one"), { items });
      const second = STELineStudio.mount(document.getElementById("two"), { kind: "flow", items });
      const original = first.toSVG(), other = second.toSVG(); first.select(2);
      const isolated = second.toSVG() === other;
      let rejected = 0; const beforeInvalid = first.toSVG();
      for (const bad of [{ intensity: NaN }, { kind: "bad" }, { items: [] }]) { try { first.update(bad); } catch { rejected++; } }
      const atomic = beforeInvalid === first.toSVG(); first.reset(); const reset = first.toSVG() === original;
      const replacement = STELineStudio.mount(document.getElementById("one"), { kind: "signal", items });
      first.destroy(); const wrappers = document.querySelectorAll("#one .ste-line-studio").length;
      replacement.destroy(); replacement.destroy(); second.destroy();
      return { baseline, final: __qa.snapshot(), isolated, rejected, atomic, reset, wrappers,
        owner: document.getElementById("one").innerHTML, ownerAttribute: document.getElementById("one").dataset.owner };
    }, { items });
    assert(evidence.isolated && evidence.atomic && evidence.reset); assert.equal(evidence.rejected, 3);
    assert.equal(evidence.wrappers, 1); assert.equal(evidence.owner, '<p id="retained">Owner content</p>');
    assert.equal(evidence.ownerAttribute, "retained"); assert.equal(evidence.final.pending, 0);
    assert.equal(evidence.final.listeners, evidence.baseline.listeners); assert.equal(evidence.final.observers, evidence.baseline.observers);
    await stationary(page, () => __qa.snapshot()); return evidence;
  }));
  await check("runtime spring settles and dynamic reduced-motion stops flow without restart or leaks", () => opened(runtime, { reducedMotion: "no-preference" }, async page => {
    await page.evaluate(({ items }) => { window.baseline = __qa.snapshot(); window.handle = STELineStudio.mount(document.getElementById("one"), { kind: "flow", items }); __qa.trackListeners(false); handle.select(1); }, { items });
    await page.waitForFunction(() => __qa.snapshot().pending === 0, null, { polling: 20 });
    const settled = await stationary(page, () => ({ svg: handle.toSVG(), frames: __qa.snapshot() }));
    assert(settled.frames.fired > 0, "Selection spring did not animate");
    await page.getByRole("button", { name: "Start pulse", exact: true }).click();
    await page.waitForFunction(() => __qa.snapshot().pending > 0, null, { polling: 20 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.waitForFunction(() => __qa.snapshot().pending === 0 && document.querySelector('[role="status"]').textContent.includes("Reduced motion"), null, { polling: 20 });
    assert(await page.getByRole("button", { name: "Start pulse", exact: true }).isDisabled());
    await stationary(page, () => ({ svg: handle.toSVG(), frames: __qa.snapshot() }));
    await page.getByLabel("Pulse position", { exact: true }).press("End");
    assert.match(await page.getByRole("status").innerText(), /Pulse position: 100%/);
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await page.waitForFunction(() => !document.querySelector('[role="status"]').textContent.includes("Reduced motion"), null, { polling: 20 });
    await stationary(page, () => ({ svg: handle.toSVG(), frames: __qa.snapshot() }));
    await page.getByRole("button", { name: "Start pulse", exact: true }).click();
    const final = await page.evaluate(() => { handle.destroy(); return { baseline, final: __qa.snapshot() }; });
    assert.equal(final.final.pending, 0); assert.equal(final.final.listeners, final.baseline.listeners);
    assert.equal(final.final.observers, final.baseline.observers); await stationary(page, () => __qa.snapshot()); return final;
  }));
  if (catalogue) {
    for (const width of [1440, 375, 240]) await check(`catalogue responsive ${width}px`, () => opened(catalogue, { viewport: { width, height: 1000 } }, async page => {
      assert.equal(await page.locator(".ste-line-studio").count(), 6);
      const widthActual = await page.evaluate(() => document.documentElement.scrollWidth);
      await page.screenshot({ path: path.join(output, `catalogue-${width}.png`), fullPage: true });
      assert(widthActual <= width + 1, `Page overflow: ${widthActual}px > ${width}px`);
      return { width, widthActual };
    }));
    await check("catalogue real mounted controls and six SVG downloads", () => opened(catalogue, {}, async page => {
      const exported = [];
      for (const kind of ["stack", "field", "layers", "signal", "orbit", "flow"]) {
        const host = page.locator(`[data-figure="${kind}"]`);
        const part = host.getByRole("combobox");
        await part.focus(); await part.press("End"); await part.press("Enter");
        const last = await part.locator("option").count() - 1;
        assert.equal(await part.inputValue(), String(last));
        assert.match(await host.getByRole("status").innerText(), new RegExp(`Selected ${last + 1} of ${last + 1}`));
        await host.getByLabel("Intensity", { exact: true }).press("Home");
        assert.equal(await host.getByLabel("Intensity", { exact: true }).inputValue(), "0");
        const event = page.waitForEvent("download"); await host.getByRole("button", { name: `Save ${kind} SVG`, exact: true }).click();
        const download = await event; const file = path.join(output, `catalogue-${kind}.svg`);
        await download.saveAs(file);
        const svg = await fs.readFile(file, "utf8"); const parsed = await inspectSVG(page, svg);
        assert(parsed.description.includes(`Selected ${last + 1} of ${last + 1}`));
        assert.equal(download.suggestedFilename(), `ste-line-${kind}.svg`);
        exported.push(kind);
      }
      return { exported };
    }));
    await check("catalogue no-JS six static figures retain descriptions", () => opened(catalogue, { javaScriptEnabled: false }, async page => {
      assert.equal(await page.locator("[data-line-kind]").count(), 6);
      for (const svg of await page.locator("[data-line-kind]").all()) {
        assert(await svg.isVisible()); assert((await svg.locator("desc").textContent()).length > 30);
      }
      assert(await page.getByText("What these examples mean", { exact: true }).isVisible());
    }));
  } else report.gaps.push("Generated examples/showcase/line-studio.html absent at snapshot; six-kind runtime tested by isolated source injection.");
} catch (error) {
  report.failures.push({ name: "verifier setup", error: error.stack || String(error) }); console.error(error);
} finally {
  if (browser) await browser.close();
  report.sourceChangesDuringRun = [];
  for (const [relative, hash] of Object.entries(report.sources)) {
    const current = await fs.readFile(path.join(root, relative), "utf8").catch(() => "");
    if (createHash("sha256").update(current).digest("hex") !== hash) report.sourceChangesDuringRun.push(relative);
  }
  report.passed = report.failures.length === 0;
  report.counts = { passed: report.cases.length, failed: report.failures.length };
  report.finishedAt = new Date().toISOString();
  await fs.writeFile(path.join(output, "browser-results.json"), JSON.stringify(report, null, 2) + "\n");
  console.log(JSON.stringify(report.counts));
}
if (!report.passed) process.exitCode = 1;
