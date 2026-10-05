/**
 * Developer-only deterministic build. The generated examples open without Node.
 * No imports from npm, downloads, hidden user configuration, or external services.
 */
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const require = createRequire(import.meta.url);
const check = process.argv.slice(2).includes("--check");
const only = process.argv.slice(2).includes("--retry-only");
if (process.argv.slice(2).some(arg => !["--check", "--retry-only"].includes(arg))) {
  throw new Error("Usage: node tools/build_line_studio.mjs [--check] [--retry-only]");
}
const read = relative => fs.readFile(path.join(root, relative), "utf8");
const safeJSON = object => JSON.stringify(object, null, 2)
  .replace(/</g, "\\u003c").replace(/>/g, "\\u003e").replace(/&/g, "\\u0026");
const safeScript = text => text.replace(/<\/script/gi, "<\\/script");
const math = await read("ste_promax/assets/line-math.js");
const retrySource = await read("ste_promax/assets/retry-observatory.js");
const retry = require("../ste_promax/assets/retry-observatory.js");
let template = await read("examples/showcase/source-templates/retry-observatory.html");
const source = JSON.parse(await read("examples/showcase/sources/retry-storm.json"));
retry.validateSource(source);
template = template
  .replace("<!--__STE_STATIC__-->", () => retry.renderSVG())
  .replace("__STE_SOURCE__", () => safeJSON(source))
  .replace("/*__STE_MATH__*/", () => safeScript(math))
  .replace("/*__STE_RETRY__*/", () => safeScript(retrySource));

function assertFinished(text) {
  if (/__STE_[A-Z_]+__/.test(text)) throw new Error("Unreplaced template token.");
}
async function emit(relative, contents) {
  assertFinished(contents);
  const file = path.join(root, relative);
  if (check) {
    if (await fs.readFile(file, "utf8") !== contents) throw new Error(`Stale generated file: ${relative}`);
    console.log(`Current: ${relative}`);
  } else {
    await fs.mkdir(path.dirname(file), { recursive: true });
    await fs.writeFile(file, contents, "utf8");
    console.log(`Built: ${relative}`);
  }
}
await emit("examples/showcase/retry-observatory.html", template);
await emit("docs/assets/retry-observatory.svg", retry.renderSVG());

if (!only) {
  const studio = require("../ste_promax/assets/line-studio.js");
  const studioSource = await read("ste_promax/assets/line-studio.js");
  const catalogue = JSON.parse(await read("examples/showcase/sources/line-studio.json"));
  let page = await read("examples/showcase/source-templates/line-studio.html");
  const cards = catalogue.figures.map(figure =>
    `<section class="figure-card"><div class="figure-mount" data-figure="${figure.kind}">${studio.renderSVG(figure)}</div></section>`
  ).join("\n");
  page = page.replace("<!--__STE_FIGURES__-->", () => cards)
    .replace("__STE_SOURCE__", () => safeJSON(catalogue))
    .replace("/*__STE_MATH__*/", () => safeScript(math))
    .replace("/*__STE_STUDIO__*/", () => safeScript(studioSource));
  await emit("examples/showcase/line-studio.html", page);
}
