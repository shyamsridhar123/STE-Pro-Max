/* Original STE Retry Observatory behavior tests. SPDX-License-Identifier: Apache-2.0 */
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const retry = require("../ste_promax/assets/retry-observatory.js");
const source = require("../examples/showcase/sources/retry-storm.json");

test("retained source defaults, budgets and boundary counts must match the renderer", () => {
  assert.equal(retry.validateSource(source), true);
  const changes = [
    s => { s.inputs.serial_layers.default = 3; },
    s => { s.inputs.total_attempts_per_retrying_layer_per_incoming_call.default = 2; },
    s => { s.inputs.serial_layers.maximum = 5; },
    s => { s.inputs.original_requests = 2; },
    s => { s.inputs.backend_failure = "intermittent"; },
    s => { s.default_example.nested_boundary_counts[1] = 6; },
    s => { s.default_example.single_owner_backend_attempts = 4; },
    s => { s.default_example.retries_per_incoming_call = 3; },
    s => { s.boundary_examples[0].nested_backend_attempts = 2; },
  ];
  for (const change of changes) {
    const changed = structuredClone(source); change(changed);
    assert.throws(() => retry.validateSource(changed), /Retained source disagrees/);
  }
});

test("default persistent-failure model is 81 backend attempts versus 3", () => {
  assert.deepEqual(retry.model(), {
    attempts: 3, layers: 4, retries: 2, nested: [3, 9, 27, 81],
    owner: [3, 3, 3, 3], nestedBackend: 81, ownerBackend: 3, repeated: 78,
  });
  assert.equal(retry.explanation().formula, "3^4 = 81");
});
for (let attempts = 1; attempts <= 4; attempts++) {
  for (let layers = 1; layers <= 4; layers++) {
    test(`A=${attempts}, L=${layers}: cumulative boundaries and single-owner budget`, () => {
      const input = Object.freeze({ attempts, layers });
      const model = retry.model(input);
      assert.deepEqual(model.nested, Array.from({ length: layers }, (_, i) => attempts ** (i + 1)));
      assert.deepEqual(model.owner, Array(layers).fill(attempts));
      assert.equal(model.nestedBackend, attempts ** layers);
      assert.equal(model.ownerBackend, attempts);
      assert.equal(model.retries, attempts - 1);
      assert.equal(model.repeated, attempts ** layers - attempts);
      for (const progress of [0, ...retry.STOPS]) {
        const copy = retry.explanation({ ...input, progress });
        if (attempts === 1) {
          assert.equal(copy.title, "No retries. No amplification.");
          assert.equal(copy.formula, layers === 1 ? "1 = 1" : `1^${layers} = 1`);
        } else if (layers === 1) {
          assert.equal(copy.title, "One layer has one budget.");
          assert.equal(copy.formula, `${attempts} = ${attempts}`);
        } else if (progress === 1) {
          assert.equal(copy.formula, [attempts, ...Array(layers - 1).fill(1)].join(" × ") + ` = ${attempts}`);
        }
      }
    });
  }
}
for (const key of ["attempts", "layers"]) {
  test(`${key} rejects non-integers, non-finite values and out-of-range budgets`, () => {
    for (const value of [NaN, Infinity, -Infinity, 0, -1, 5, 1.5, "3", null, undefined]) {
      for (const api of [retry.options, retry.model, retry.explanation, retry.renderSVG]) {
        assert.throws(() => api({ [key]: value }), RangeError, `${key}=${String(value)}`);
      }
    }
  });
}
test("progress rejects non-finite and out-of-range values", () => {
  for (const progress of [NaN, Infinity, -Infinity, -0.01, 1.01, "0.5", null, undefined]) {
    assert.throws(() => retry.renderSVG({ progress }), RangeError);
  }
});
test("invalid option containers and themes fail before rendering", () => {
  for (const value of [null, [], "dark", false, 4]) assert.throws(() => retry.options(value), TypeError);
  for (const theme of ["unknown", "__proto__", "constructor", null, 42]) {
    assert.throws(() => retry.renderSVG({ theme }), RangeError);
  }
});
test("chapter boundaries select the intended explanation", () => {
  for (const [progress, chapter] of [[0, 0], [0.229, 0], [0.23, 1], [0.479, 1],
    [0.48, 2], [0.82, 2], [0.85, 2], [0.874, 2], [0.875, 3], [1, 3]]) {
    assert.equal(retry.explanation({ progress }).index, chapter);
  }
});
test("SVG is deterministic and retains model assumptions at every supported budget", () => {
  for (const theme of ["dark", "light"]) for (let attempts = 1; attempts <= 4; attempts++) {
    for (let layers = 1; layers <= 4; layers++) for (const progress of [0, 0.36, 0.72, 1]) {
      const input = Object.freeze({ theme, attempts, layers, progress });
      const svg = retry.renderSVG(input);
      assert.equal(svg, retry.renderSVG(input));
      assert.match(svg, /^<svg /);
      assert.match(svg, /<metadata>/);
      assert.match(svg, /Persistent failure; exhausted budgets/);
      assert.match(svg, /not production telemetry/);
      assert.match(svg, new RegExp(`nested retries produce ${attempts ** layers} backend attempts; one retry owner produces ${attempts}`));
      assert.doesNotMatch(svg, /NaN|Infinity|undefined|<(?:script|foreignObject)\b/);
      assert.equal((svg.match(/data-boundary=/g) || []).length, layers + 1);
    }
  }
});
test("model results and normalized options are isolated copies", () => {
  const input = Object.freeze({ attempts: 2, layers: 3 });
  const normalized = retry.options(input);
  normalized.attempts = 4;
  const first = retry.model(input);
  first.nested[0] = 999;
  first.owner.push(999);
  assert.deepEqual(retry.model(input).nested, [2, 4, 8]);
  assert.deepEqual(retry.model(input).owner, [2, 2, 2]);
  assert.equal(input.attempts, 2);
});

test("progress 0.85 retains nested policy until the shared 0.875 switch", () => {
  assert.equal(retry.explanation({ progress: 0.85 }).formula, "3^4 = 81");
  assert.match(retry.renderSVG({ progress: 0.85 }), /<title[^>]*>A retry budget inside a retry budget\.<\/title>/);
  assert.equal(retry.explanation({ progress: 0.875 }).formula, "3 × 1 × 1 × 1 = 3");
  assert.match(retry.renderSVG({ progress: 0.875 }), /<title[^>]*>One retry owner\. One shared path\.<\/title>/);
});
