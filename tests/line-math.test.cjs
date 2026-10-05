"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const math = require("../ste_promax/assets/line-math.js");

function near(actual, expected, tolerance = 1e-9) {
  assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} != ${expected}`);
}

function nearPoint(actual, expected, tolerance = 1e-9) {
  assert.equal(actual.length, expected.length);
  actual.forEach((value, i) => near(value, expected[i], tolerance));
}

function finitePoints(points) {
  for (const point of points) {
    for (const value of point) assert.ok(Number.isFinite(value));
  }
}

test("CommonJS and offline script expose the same API without DOM or network", () => {
  assert.equal(globalThis.STELineMath, math);
  const context = vm.createContext({});
  const source = fs.readFileSync(path.join(__dirname, "../ste_promax/assets/line-math.js"), "utf8");
  vm.runInContext(source, context, { timeout: 1000 });
  assert.deepEqual(Object.keys(context.STELineMath), Object.keys(math));
  nearPoint(context.STELineMath.project([2, 3, 4]), math.project([2, 3, 4]));
  assert.deepEqual(math.DEFAULT_CAMERA, {
    yaw: Math.PI / 4, elevation: Math.PI / 6, scale: 1, cx: 200, cy: 160
  });
  assert.ok(Object.isFrozen(math.DEFAULT_CAMERA));
});

test("projection follows the given ground/vertical formula and partial camera defaults", () => {
  nearPoint(math.project([0, 0, 0]), [200, 160]);
  const camera = { yaw: 0, elevation: Math.PI / 6, scale: 2, cx: 10, cy: -20 };
  nearPoint(math.project([3, 4, 5], camera), [16, -16 - 5 * Math.sqrt(3)]);
  nearPoint(math.project([3, 4, 0], { yaw: 0 }), [203, 162]);
  assert.ok(math.project([0, 0, 10])[1] < math.project([0, 0, 0])[1]);
});

test("projection inversion covers yaw signs, scale, translation and raised planes", () => {
  for (const yaw of [-5, -Math.PI, -Math.PI / 2, -0.4, 0, 0.7, Math.PI / 2, 2.7, 7]) {
    for (const elevation of [-0.6, 0.2, Math.PI / 6, 1.3]) {
      for (const point of [[0, 0, 0], [5, -8, 13], [-80, 25, -3], [0.01, -0.02, 2]]) {
        const camera = { yaw, elevation, scale: 3.7, cx: -230, cy: 512 };
        const screen = math.project(point, camera);
        finitePoints([screen]);
        nearPoint(math.unprojectOnPlane(screen, point[2], camera), point);
      }
    }
  }
});

test("ascending center depth is back-to-front along the camera viewing ray", () => {
  for (const yaw of [-2.5, -0.8, 0, 0.8, 2.5]) {
    const elevation = 0.6;
    const camera = { yaw, elevation };
    const towardViewer = [
      Math.sin(yaw) * Math.cos(elevation),
      Math.cos(yaw) * Math.cos(elevation),
      Math.sin(elevation)
    ];
    const center = [4, -3, 2];
    const nearer = center.map((value, i) => value + 10 * towardViewer[i]);
    nearPoint(math.project(center, camera), math.project(nearer, camera));
    near(math.depth(nearer, camera) - math.depth(center, camera), 10);
    near(math.depth(center, camera), math.depth(center, { ...camera, scale: 20, cx: 3, cy: 4 }));
  }
  assert.ok(math.depth([1, 1, 1]) > math.depth([0, 0, 0]));
});

test("box sides face the viewer in every yaw quadrant; sides precede the top", () => {
  const center = [4, 6, 8], size = [10, 14, 18];
  for (const yaw of [-7, -2.4, -0.6, 0.6, 2.4, 7]) {
    const camera = { yaw, elevation: 0.5 };
    const x = center[0] + Math.sign(Math.sin(yaw)) * size[0] / 2;
    const y = center[1] + Math.sign(Math.cos(yaw)) * size[1] / 2;
    const expected = [
      [[x, -1, -1], [x, 13, -1], [x, 13, 17], [x, -1, 17]],
      [[-1, y, -1], [9, y, -1], [9, y, 17], [-1, y, 17]]
    ].map(vertices => vertices.map(point => math.project(point, camera)));
    const faces = math.boxFaces(center, size, camera);
    assert.deepEqual(faces.map(face => face.kind), ["side", "side", "top"]);
    assert.ok(faces[0].depth <= faces[1].depth);
    for (const points of expected) assert.ok(faces.slice(0, 2).some(face =>
      JSON.stringify(face.points) === JSON.stringify(points)));
    const sideDepths = [math.depth([x, 6, 8], camera), math.depth([4, y, 8], camera)].sort((a, b) => a - b);
    faces.slice(0, 2).forEach((face, i) => near(face.depth, sideDepths[i]));
    near(faces[2].depth, math.depth([4, 6, 17], camera));
    for (const face of faces) {
      assert.equal(face.points.length, 4);
      finitePoints(face.points);
      assert.ok(Number.isFinite(face.depth));
    }
  }
});

test("axis-aligned yaw and zero-sized boxes remain finite and deterministic", () => {
  for (const yaw of [0, Math.PI / 2, Math.PI, -Math.PI / 2]) {
    const camera = { yaw };
    for (const size of [[4, 6, 8], [0, 0, 0], [0, 4, 8]]) {
      const faces = math.boxFaces([0, 0, 0], size, camera);
      assert.equal(faces.length, 3);
      faces.forEach(face => finitePoints(face.points));
      assert.deepEqual(faces, math.boxFaces([0, 0, 0], size, camera));
    }
  }
});

test("rounding clamps to half adjacent edges, stays finite and closes the path", () => {
  const square = [[0, 0], [10, 0], [10, 10], [0, 10]];
  assert.equal(math.roundedPolygon(square, 100),
    "M 0 5 Q 0 0 5 0 L 5 0 Q 10 0 10 5 L 10 5 Q 10 10 5 10 L 5 10 Q 0 10 0 5 Z");
  assert.equal(math.roundedPolygon(square, 0), "M 0 0 L 10 0 L 10 10 L 0 10 Z");
  const thin = math.roundedPolygon([[0, 0], [2, 0], [2, 100], [0, 100]], 1e9);
  assert.ok(thin.startsWith("M 0 1 Q 0 0 1 0"));
  assert.equal((thin.match(/Q/g) || []).length, 4);
  assert.ok(thin.endsWith(" Z"));
  assert.ok(!/NaN|Infinity/.test(thin));
  assert.equal(math.roundedPolygon(square), math.roundedPolygon(square, 3));
});

test("degenerate polygon handling removes adjacent duplicates and explicit closing vertices", () => {
  assert.equal(math.roundedPolygon([]), "");
  assert.equal(math.roundedPolygon([[1, 2]]), "M 1 2 Z");
  assert.equal(math.roundedPolygon([[1, 2], [3, 4]]), "M 1 2 L 3 4 Z");
  assert.equal(math.roundedPolygon([[1, 2], [1, 2], [1, 2]]), "M 1 2 Z");
  const triangle = [[0, 0], [10, 0], [5, 5]];
  assert.equal(math.roundedPolygon([...triangle, triangle[2], triangle[0]]), math.roundedPolygon(triangle));
  assert.ok(!/NaN|Infinity/.test(math.roundedPolygon([[0, 0], [1, 0], [2, 0]])));
});

test("hull is deterministic, counterclockwise and omits duplicate/collinear interior vertices", () => {
  const cloud = [[1, 1], [2, 0], [0, 0], [2, 2], [0, 2], [0, 0], [1, 0], [0, 1]];
  const expected = [[0, 0], [2, 0], [2, 2], [0, 2]];
  assert.deepEqual(math.convexHull(cloud), expected);
  for (let i = 0; i < cloud.length; i++) {
    assert.deepEqual(math.convexHull(cloud.slice(i).concat(cloud.slice(0, i)).reverse()), expected);
  }
  assert.deepEqual(math.convexHull([]), []);
  assert.deepEqual(math.convexHull([[3, 4], [3, 4]]), [[3, 4]]);
  assert.deepEqual(math.convexHull([[2, 2], [-1, -1], [0, 0], [1, 1]]), [[-1, -1], [2, 2]]);
  assert.deepEqual(math.convexHull([[0, 3], [0, -2], [0, 1]]), [[0, -2], [0, 3]]);
  assert.deepEqual(math.convexHull([[0, 0], [1e200, 0], [0, 1e200]]),
    [[0, 0], [1e200, 0], [0, 1e200]]);
});

test("geometry functions do not mutate inputs or return aliases to them", () => {
  const point = Object.freeze([1, 2, 3]);
  const size = Object.freeze([4, 5, 6]);
  const camera = Object.freeze({ yaw: 0.3 });
  math.project(point, camera);
  math.boxFaces(point, size, camera);
  const cloud = Object.freeze([Object.freeze([0, 0]), Object.freeze([1, 0]), Object.freeze([0, 1])]);
  math.roundedPolygon(cloud);
  const hull = math.convexHull(cloud);
  hull[0][0] = 9;
  assert.equal(cloud[0][0], 0);
});

test("malformed and non-finite geometry is rejected rather than emitted into SVG", () => {
  for (const bad of [null, {}, "0,0,0", [1, 2], [1, 2, 3, 4], [1, NaN, 3], [Infinity, 2, 3], Array(3)]) {
    assert.throws(() => math.project(bad), TypeError);
    assert.throws(() => math.depth(bad), TypeError);
    assert.throws(() => math.boxFaces(bad, [1, 1, 1]), TypeError);
  }
  for (const bad of [null, {}, [[1]], [[1, 2, 3]], [[NaN, 1]], [[0, Infinity]], Array(1)]) {
    assert.throws(() => math.roundedPolygon(bad), TypeError);
    assert.throws(() => math.convexHull(bad), TypeError);
  }
  for (const camera of [null, [], { yaw: NaN }, { elevation: Infinity }, { cx: "2" }, { cy: null }]) {
    assert.throws(() => math.project([1, 2, 3], camera), TypeError);
  }
  for (const scale of [0, -1]) assert.throws(() => math.project([1, 2, 3], { scale }), RangeError);
  assert.throws(() => math.unprojectOnPlane([1, 2, 3]), TypeError);
  assert.throws(() => math.unprojectOnPlane([1, 2], NaN), TypeError);
  assert.throws(() => math.unprojectOnPlane([1, 2], 0, { elevation: 0 }), RangeError);
  assert.throws(() => math.unprojectOnPlane([1, 2], 0, { elevation: Math.PI }), RangeError);
  assert.throws(() => math.boxFaces([0, 0, 0], [-1, 2, 3]), RangeError);
  assert.throws(() => math.boxFaces([0, 0, 0], [1, 2, 3], { elevation: -0.5 }), RangeError);
  assert.throws(() => math.roundedPolygon([[0, 0]], -1), RangeError);
  assert.throws(() => math.roundedPolygon([[0, 0]], Infinity), TypeError);
  assert.throws(() => math.project([1e308, -1e308, 0], { scale: 1e308 }), RangeError);
  assert.throws(() => math.roundedPolygon([[1e308, 0], [-1e308, 0], [0, 1]]), RangeError);
  assert.throws(() => math.convexHull([[1e308, 0], [-1e308, 0], [0, 1]]), RangeError);
});

test("point collections have a bounded workload", () => {
  const oversized = Array(10001).fill([0, 0]);
  assert.throws(() => math.convexHull(oversized), RangeError);
  assert.throws(() => math.roundedPolygon(oversized), RangeError);
  assert.deepEqual(math.convexHull(Array(10000).fill([0, 0])), [[0, 0]]);
});

test("spring settles exactly and never drifts at an idle target", () => {
  let state = { value: -20, velocity: 0 };
  for (let frame = 0; frame < 600 && !state.settled; frame++) {
    state = math.stepSpring(state, 10, 1 / 60);
    assert.ok(Number.isFinite(state.value) && Number.isFinite(state.velocity));
  }
  assert.deepEqual(state, { value: 10, velocity: 0, settled: true });
  for (const dt of [0, 1 / 60, 1, 1e300]) {
    assert.deepEqual(math.stepSpring(state, 10, dt), state);
  }
  assert.deepEqual(math.stepSpring({ value: 10.0001, velocity: 0.0001 }, 10, 0),
    { value: 10, velocity: 0, settled: true });
  assert.equal(math.stepSpring(state, 20, 1 / 60).settled, false);
  assert.equal(math.stepSpring({ value: 10, velocity: 2 }, 10, 0).settled, false);
});

test("spring substeps agree across frame sizes and cap suspended-tab catch-up", () => {
  const initial = Object.freeze({ value: 0, velocity: 3 });
  const once = math.stepSpring(initial, 10, 1 / 30);
  let split = initial;
  for (let i = 0; i < 8; i++) split = math.stepSpring(split, 10, 1 / 240);
  near(once.value, split.value);
  near(once.velocity, split.velocity);
  assert.deepEqual(math.stepSpring(initial, 10, 1e300), math.stepSpring(initial, 10, 0.25));
  assert.deepEqual(math.stepSpring(initial, 10, 0), { ...initial, settled: false });
  const explicitDefaults = math.stepSpring(initial, 10, 1 / 60, {
    stiffness: 120, damping: 22, epsilon: 0.001
  });
  assert.deepEqual(math.stepSpring(initial, 10, 1 / 60), explicitDefaults);
  const stable = math.stepSpring(initial, 10, 0.25, { stiffness: 1e6, damping: 1e5 });
  assert.ok(Number.isFinite(stable.value) && Number.isFinite(stable.velocity));
  assert.ok(stable.value > 0 && stable.value <= 10);
});

test("spring rejects malformed state, time and options without unbounded integration", () => {
  const state = { value: 0, velocity: 0 };
  for (const bad of [null, [], {}, { value: NaN, velocity: 0 }, { value: 0, velocity: Infinity }]) {
    assert.throws(() => math.stepSpring(bad, 1, 0.1), TypeError);
  }
  assert.throws(() => math.stepSpring(state, NaN, 0.1), TypeError);
  assert.throws(() => math.stepSpring(state, 1, Infinity), TypeError);
  assert.throws(() => math.stepSpring(state, 1, -1), RangeError);
  assert.throws(() => math.stepSpring(state, 1, 0.1, null), TypeError);
  for (const options of [{ stiffness: 0 }, { stiffness: -1 }, { damping: -1 }, { epsilon: 0 }]) {
    assert.throws(() => math.stepSpring(state, 1, 0.1, options), RangeError);
  }
  for (const options of [{ stiffness: NaN }, { damping: Infinity }, { epsilon: "1" }]) {
    assert.throws(() => math.stepSpring(state, 1, 0.1, options), TypeError);
  }
  assert.throws(() => math.stepSpring({ value: 1e308, velocity: 0 }, -1e308, 0.1), RangeError);
});

test("clamp and quintic smootherstep are finite, clamped and monotonic", () => {
  assert.equal(math.clamp(-3, -2, 5), -2);
  assert.equal(math.clamp(7, -2, 5), 5);
  assert.equal(math.clamp(3, -2, 5), 3);
  assert.equal(math.clamp(3, 2, 2), 2);
  assert.equal(math.ease(-10), 0);
  assert.equal(math.ease(10), 1);
  assert.equal(math.ease(0.5), 0.5);
  let previous = 0;
  for (let i = 0; i <= 100; i++) {
    const t = i / 100, value = math.ease(t);
    assert.ok(Number.isFinite(value) && value >= previous && value <= 1);
    near(value, 6 * t ** 5 - 15 * t ** 4 + 10 * t ** 3);
    previous = value;
  }
  assert.ok(math.ease(0.001) < 1e-7);
  assert.ok(1 - math.ease(0.999) < 1e-7);
  for (const bad of [NaN, Infinity, "1", null]) {
    assert.throws(() => math.ease(bad), TypeError);
    assert.throws(() => math.clamp(bad, 0, 1), TypeError);
  }
  assert.throws(() => math.clamp(0, 1, -1), RangeError);
});
