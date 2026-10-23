/* Original STE Line Studio mechanism figure tests. SPDX-License-Identifier: Apache-2.0 */
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = require("../examples/showcase/sources/token-bucket.json");

const html = fs.readFileSync(path.join(__dirname, "../examples/showcase/token-bucket-mechanism.html"), "utf8");
const script = html.match(/<script id="mechanism-model">([\s\S]*?)<\/script>/)[1];
const context = vm.createContext({});
vm.runInContext(script, context, { timeout: 1000 });
const M = context.MechanismFigure;

function near(actual, expected, tolerance = 1e-9) {
  assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} != ${expected}`);
}

test("model script runs without DOM or network and is self-contained", () => {
  assert.equal(typeof M.simulate, "function");
  assert.doesNotMatch(html, /<script[^>]+src=|<link[^>]+href="http|fetch\(|XMLHttpRequest/);
});

test("isometric projection: origin, axis directions and height", () => {
  const { cx, cy, scale } = M.CAMERA;
  assert.deepEqual(Array.from(M.project([0, 0, 0])), [cx, cy]);
  const x = M.project([1, 0, 0]), y = M.project([0, 1, 0]), z = M.project([0, 0, 1]);
  near(x[0] - cx, Math.cos(Math.PI / 6) * scale); near(x[1] - cy, scale / 2);
  near(y[0] - cx, -Math.cos(Math.PI / 6) * scale); near(y[1] - cy, scale / 2);
  near(z[0], cx); near(z[1], cy - scale);
  near(M.project([2, 2, 0])[0], cx);
});

test("source constants and the default run match the retained JSON", () => {
  const i = source.inputs;
  assert.equal(M.SOURCE.capacity, i.capacity_tokens);
  assert.equal(M.SOURCE.refill, i.refill_tokens_per_second);
  assert.equal(M.SOURCE.initial, i.initial_tokens);
  assert.equal(M.SOURCE.maxArrivals, i.arrivals_per_second.maximum);
  const run = M.simulate(i.arrivals_per_second.default, i.seconds.default);
  const d = source.default_example;
  assert.deepEqual(Array.from(run.steps, s => s.available), d.available);
  assert.deepEqual(Array.from(run.steps, s => s.admitted), d.admitted);
  assert.deepEqual(Array.from(run.steps, s => s.rejected), d.rejected);
  assert.deepEqual(Array.from(run.steps, s => s.after), d.tokens_after);
  assert.equal(run.arrivals, d.total_arrivals);
  assert.equal(run.admitted, d.total_admitted);
  assert.equal(run.rejected, d.total_rejected);
  for (const b of source.boundary_examples) {
    const r = M.simulate(b.a, 10);
    assert.deepEqual([r.admitted, r.rejected, r.tokens], [b.total_admitted, b.total_rejected, b.final_tokens]);
  }
});

test("model invariants hold for every arrival rate and time", () => {
  for (let a = 1; a <= 8; a++) {
    for (let t = 0; t <= 10; t++) {
      const r = M.simulate(a, t);
      assert.equal(r.admitted + r.rejected, a * t);
      assert.ok(r.admitted <= M.SOURCE.initial + M.SOURCE.refill * t);
      for (const s of r.steps) assert.ok(s.after >= 0 && s.available <= M.SOURCE.capacity);
      if (a > M.SOURCE.refill && t >= 10) assert.equal(r.steps.at(-1).admitted, M.SOURCE.refill);
    }
  }
});

test("no two solid parts intersect in any state, except tokens inside the hopper", () => {
  for (let a = 1; a <= 8; a++) {
    for (let t = 0; t <= 10; t++) {
      assert.deepEqual(Array.from(M.overlaps(M.parts(M.stateAt(a, t)))), [], `a=${a} t=${t}`);
    }
  }
  const crash = M.parts(M.stateAt(5, 0)).concat([{ name: "probe", x: 6, y: 3, z: 3, w: 1, d: 1, h: 1 }]);
  assert.ok(M.overlaps(crash).length > 0);
});

test("rendered SVG is deterministic, back-to-front, and labels the live state", () => {
  const s = M.stateAt(5, 3);
  const svg = M.renderSVG(s);
  assert.equal(svg, M.renderSVG(s));
  const order = [...svg.matchAll(/data-part="([^"]+)"/g)].map(m => m[1]);
  const byName = Object.fromEntries(Array.from(M.parts(s)).map(p => [p.name, p]));
  for (let i = 0; i < order.length; i++) {
    for (let j = i + 1; j < order.length; j++) {
      const early = byName[order[i]], late = byName[order[j]];
      assert.ok(!M.behind(late, early) || M.behind(early, late), `${late.name} must paint before ${early.name}`);
    }
  }
  assert.ok(order.indexOf("token 1") < order.indexOf("hopper"));
  assert.ok(order.indexOf("hopper") > order.indexOf("valve"));
  assert.match(svg, /hopper: 0 \/ 10 tokens/);
  assert.match(svg, /admitted: 4</);
  assert.match(svg, /rejected: 1</);
  assert.doesNotMatch(svg, /NaN|undefined/);
});

test("still table and stated totals agree with the model", () => {
  assert.match(html, /50 arrivals, 28 admitted, 22 rejected/);
  assert.match(html, /<td>3<\/td><td>4<\/td><td>4<\/td><td>1<\/td><td>0<\/td>/);
  assert.match(html, /Illustrative mechanism, not a real device/);
});
