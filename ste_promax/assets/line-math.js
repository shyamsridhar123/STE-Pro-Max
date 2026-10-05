/* Original STE Line Studio geometry and motion primitives. Apache-2.0. */
(function (root, factory) {
  "use strict";
  const api = factory();
  root.STELineMath = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(globalThis, function () {
  "use strict";

  const DEFAULT_CAMERA = Object.freeze({
    yaw: Math.PI / 4, elevation: Math.PI / 6, scale: 1, cx: 200, cy: 160
  });
  const MAX_POINTS = 10000;
  const MAX_DT = 0.25;
  const SPRING_STEP = 1 / 240;

  function finite(value, name) {
    if (typeof value !== "number" || !Number.isFinite(value)) {
      throw new TypeError(name + " must be a finite number");
    }
    return value;
  }

  function result(value) {
    if (!Number.isFinite(value)) throw new RangeError("Numeric range exceeded");
    return value;
  }

  function object(value, name) {
    if (value === null || typeof value !== "object" || Array.isArray(value)) {
      throw new TypeError(name + " must be an object");
    }
    return value;
  }

  function vector(value, length, name) {
    if (!Array.isArray(value) || value.length !== length) {
      throw new TypeError(name + " must have " + length + " coordinates");
    }
    const copy = [];
    for (let i = 0; i < length; i++) copy.push(finite(value[i], name));
    return copy;
  }

  function points2(points) {
    if (!Array.isArray(points)) throw new TypeError("points must be an array");
    if (points.length > MAX_POINTS) throw new RangeError("Too many points (maximum 10000)");
    const copy = [];
    for (let i = 0; i < points.length; i++) copy.push(vector(points[i], 2, "point"));
    return copy;
  }

  function cameraFrame(camera) {
    object(camera, "camera");
    const c = {};
    for (const key of Object.keys(DEFAULT_CAMERA)) {
      c[key] = finite(camera[key] === undefined ? DEFAULT_CAMERA[key] : camera[key], key);
    }
    if (c.scale <= 0) throw new RangeError("scale must be positive");
    c.cosYaw = Math.cos(c.yaw);
    c.sinYaw = Math.sin(c.yaw);
    c.cosElevation = Math.cos(c.elevation);
    c.sinElevation = Math.sin(c.elevation);
    return c;
  }

  function projectWithFrame(p, c) {
    return [
      result(c.cx + c.scale * (p[0] * c.cosYaw - p[1] * c.sinYaw)),
      result(c.cy + c.scale * (
        (p[0] * c.sinYaw + p[1] * c.cosYaw) * c.sinElevation - p[2] * c.cosElevation
      ))
    ];
  }

  function project(point, camera = {}) {
    return projectWithFrame(vector(point, 3, "point"), cameraFrame(camera));
  }

  function unprojectOnPlane(point, z = 0, camera = {}) {
    const p = vector(point, 2, "point");
    finite(z, "z");
    const c = cameraFrame(camera);
    // At a ground-level view the ground plane collapses to a line.
    if (Math.abs(c.sinElevation) < 1e-12) {
      throw new RangeError("Cannot invert an edge-on ground plane");
    }
    const across = result((p[0] - c.cx) / c.scale);
    const along = result(((p[1] - c.cy) / c.scale + z * c.cosElevation) / c.sinElevation);
    return [
      result(across * c.cosYaw + along * c.sinYaw),
      result(-across * c.sinYaw + along * c.cosYaw),
      z
    ];
  }

  function depthWithFrame(p, c) {
    // Positive points toward the viewer. Sort centers ASCENDING to paint back-to-front.
    // This is the unit vector orthogonal to the screen-right and screen-down axes.
    return result(
      (p[0] * c.sinYaw + p[1] * c.cosYaw) * c.cosElevation + p[2] * c.sinElevation
    );
  }

  function depth(point, camera = {}) {
    return depthWithFrame(vector(point, 3, "point"), cameraFrame(camera));
  }

  function boxFaces(center, size, camera = {}) {
    const p = vector(center, 3, "center");
    const s = vector(size, 3, "size");
    if (s.some(value => value < 0)) throw new RangeError("size must be nonnegative");
    const c = cameraFrame(camera);
    // This top-visible pseudo-3D model deliberately does not render bottom faces.
    if (c.sinElevation <= 0) throw new RangeError("boxFaces requires a view above the ground");
    const lo = p.map((value, i) => result(value - s[i] / 2));
    const hi = p.map((value, i) => result(value + s[i] / 2));
    const x = c.sinYaw * c.cosElevation >= 0 ? hi[0] : lo[0];
    const y = c.cosYaw * c.cosElevation >= 0 ? hi[1] : lo[1];
    const face = (kind, vertices, midpoint) => ({
      kind,
      points: vertices.map(vertex => projectWithFrame(vertex, c)),
      depth: depthWithFrame(midpoint, c)
    });
    const sides = [
      face("side", [
        [x, lo[1], lo[2]], [x, hi[1], lo[2]], [x, hi[1], hi[2]], [x, lo[1], hi[2]]
      ], [x, p[1], p[2]]),
      face("side", [
        [lo[0], y, lo[2]], [hi[0], y, lo[2]], [hi[0], y, hi[2]], [lo[0], y, hi[2]]
      ], [p[0], y, p[2]])
    ];
    sides.sort((a, b) => a.depth - b.depth);
    sides.push(face("top", [
      [lo[0], lo[1], hi[2]], [hi[0], lo[1], hi[2]],
      [hi[0], hi[1], hi[2]], [lo[0], hi[1], hi[2]]
    ], [p[0], p[1], hi[2]]));
    return sides;
  }

  function samePoint(a, b) {
    return a[0] === b[0] && a[1] === b[1];
  }

  function roundedPolygon(points, radius = 3) {
    const input = points2(points);
    finite(radius, "radius");
    if (radius < 0) throw new RangeError("radius must be nonnegative");
    const p = input.filter((point, i) => i === 0 || !samePoint(point, input[i - 1]));
    if (p.length > 1 && samePoint(p[0], p[p.length - 1])) p.pop();
    // Empty input has no path. One/two vertices form a closed point/line, without curves.
    if (!p.length) return "";
    if (p.length < 3 || radius === 0) {
      return "M " + p.map(point => point.join(" ")).join(" L ") + " Z";
    }
    const corners = p.map((point, i) => {
      const prev = p[(i + p.length - 1) % p.length];
      const next = p[(i + 1) % p.length];
      const before = [result(prev[0] - point[0]), result(prev[1] - point[1])];
      const after = [result(next[0] - point[0]), result(next[1] - point[1])];
      const a = result(Math.hypot(...before));
      const b = result(Math.hypot(...after));
      // Radius is the corner cut-back distance, not a circular arc radius.
      // Each corner consumes at most half either adjacent edge, so curves cannot overlap.
      const trim = Math.min(radius, a / 2, b / 2);
      const offset = (edge, length) => point.map((v, j) => result(v + edge[j] * (trim / length)));
      return { entry: offset(before, a), exit: offset(after, b), point };
    });
    const path = ["M " + corners[0].entry.join(" ")];
    for (let i = 0; i < corners.length; i++) {
      const corner = corners[i];
      if (i) path.push("L " + corner.entry.join(" "));
      path.push("Q " + corner.point.join(" ") + " " + corner.exit.join(" "));
    }
    path.push("Z");
    return path.join(" ");
  }

  function convexHull(points) {
    const sorted = points2(points).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const unique = sorted.filter((point, i) => i === 0 || !samePoint(point, sorted[i - 1]));
    // Deterministic: lexicographically smallest start, counterclockwise, no repeated endpoint.
    // Collinear input reduces to its two extremes; duplicates reduce to a single point.
    if (unique.length < 3) return unique;
    function turn(a, b, c) {
      const dx = result(b[0] - a[0]), dy = result(b[1] - a[1]);
      const ex = result(c[0] - a[0]), ey = result(c[1] - a[1]);
      const scale = Math.max(Math.abs(dx), Math.abs(dy), Math.abs(ex), Math.abs(ey));
      return (dx / scale) * (ey / scale) - (dy / scale) * (ex / scale);
    }
    const lower = [], upper = [];
    for (const point of unique) {
      while (lower.length >= 2 && turn(lower[lower.length - 2], lower[lower.length - 1], point) <= 0) {
        lower.pop();
      }
      lower.push(point);
    }
    for (let i = unique.length - 1; i >= 0; i--) {
      const point = unique[i];
      while (upper.length >= 2 && turn(upper[upper.length - 2], upper[upper.length - 1], point) <= 0) {
        upper.pop();
      }
      upper.push(point);
    }
    lower.pop();
    upper.pop();
    return lower.concat(upper);
  }

  function stepSpring(state, target, dt, options = {}) {
    object(state, "state");
    object(options, "options");
    let value = finite(state.value, "value");
    let velocity = finite(state.velocity, "velocity");
    finite(target, "target");
    finite(dt, "dt");
    const stiffness = finite(options.stiffness === undefined ? 120 : options.stiffness, "stiffness");
    const damping = finite(options.damping === undefined ? 22 : options.damping, "damping");
    const epsilon = finite(options.epsilon === undefined ? 0.001 : options.epsilon, "epsilon");
    if (dt < 0 || stiffness <= 0 || damping < 0 || epsilon <= 0) {
      throw new RangeError("Require dt >= 0, stiffness > 0, damping >= 0 and epsilon > 0");
    }
    const settled = () => Math.abs(result(value - target)) <= epsilon && Math.abs(velocity) <= epsilon;
    if (settled()) return { value: target, velocity: 0, settled: true };
    // At most 60 implicit-Euler substeps. Unlike explicit Euler, large stiffness/damping
    // do not make the integrator unstable. A suspended tab cannot trigger unbounded catch-up.
    const elapsed = Math.min(dt, MAX_DT);
    const steps = Math.ceil(elapsed / SPRING_STEP);
    const h = steps ? elapsed / steps : 0;
    const kh = result(stiffness * h);
    const divisor = result(1 + damping * h + kh * h);
    for (let i = 0; i < steps; i++) {
      velocity = result((velocity - kh * result(value - target)) / divisor);
      value = result(value + h * velocity);
    }
    return settled() ? { value: target, velocity: 0, settled: true } : { value, velocity, settled: false };
  }

  function clamp(number, min, max) {
    finite(number, "number");
    finite(min, "min");
    finite(max, "max");
    if (min > max) throw new RangeError("min must not exceed max");
    return Math.min(max, Math.max(min, number));
  }

  function ease(t) {
    t = clamp(t, 0, 1);
    return clamp(t * t * t * (t * (t * 6 - 15) + 10), 0, 1);
  }

  return Object.freeze({
    DEFAULT_CAMERA, project, unprojectOnPlane, depth, boxFaces,
    roundedPolygon, convexHull, stepSpring, ease, clamp
  });
});
