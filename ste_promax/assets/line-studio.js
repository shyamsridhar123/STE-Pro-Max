/* Original STE Line Studio SVG runtime.
 * Copyright (c) 2026 Shyam Sridhar and contributors. SPDX-License-Identifier: Apache-2.0
 */
(function (root, factory) {
  "use strict";
  const api = factory(root);
  root.STELineStudio = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(globalThis, function (root) {
  "use strict";

  const instances = new WeakMap();
  const kinds = ["stack", "field", "layers", "signal", "orbit", "flow"];
  const optionKeys = ["kind", "title", "summary", "items", "intensity", "theme"];
  const stateKeys = ["selected", "rotation", "phase", "pointer", "trail", "lift"];
  const defaults = {
    kind: "stack", title: "A closer look", summary: "Select a part to inspect its place in the whole.",
    items: [
      { label: "Observe", detail: "Start with the available evidence." },
      { label: "Review", detail: "Inspect the relationship between parts." },
      { label: "Decide", detail: "Choose a next step and preserve the context." }
    ],
    intensity: 0.55, theme: "system"
  };

  // Resolve lazily: this file can load before the separately owned math module.
  function math() {
    const api = typeof module === "object" && module.exports
      ? require("./line-math.js") : root.STELineMath;
    if (!api) throw new Error("STE Line Studio requires STELineMath before rendering.");
    return api;
  }

  function record(value, keys, name) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new TypeError(name + " must be an object");
    }
    const prototype = Object.getPrototypeOf(value);
    if (prototype !== Object.prototype && prototype !== null) {
      throw new TypeError(name + " must be a plain object");
    }
    for (const key of Reflect.ownKeys(value)) {
      if (!keys.includes(key)) throw new TypeError("Unknown " + name + " property: " + String(key));
      const descriptor = Object.getOwnPropertyDescriptor(value, key);
      if (!("value" in descriptor)) throw new TypeError(name + " must contain data properties");
    }
  }

  function number(value, min, max, name) {
    if (typeof value !== "number" || !Number.isFinite(value)) {
      throw new TypeError(name + " must be a finite number");
    }
    if (value < min || value > max) throw new RangeError(name + " is out of range");
    return value;
  }

  function text(value, limit, name) {
    if (typeof value !== "string") throw new TypeError(name + " must be text");
    if (!value.trim() || value.length > limit) throw new RangeError(name + " has an invalid length");
    // XML 1.0 control characters and isolated surrogates cannot enter an SVG export.
    if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffe\uffff]/u.test(value) ||
        /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/u.test(value)) {
      throw new TypeError(name + " contains invalid XML text");
    }
    return value;
  }

  function normalize(options = {}) {
    record(options, optionKeys, "options");
    const next = { ...defaults, ...options };
    if (!kinds.includes(next.kind)) throw new RangeError("Unknown line-art kind");
    if (!["light", "dark", "system"].includes(next.theme)) throw new RangeError("Unknown theme");
    next.title = text(next.title, 160, "title");
    next.summary = text(next.summary, 2000, "summary");
    next.intensity = number(next.intensity, 0, 1, "intensity");
    if (!Array.isArray(next.items) || next.items.length < 2 || next.items.length > 9) {
      throw new RangeError("items must contain 2 to 9 entries");
    }
    next.items = Array.from(next.items, item => {
      record(item, ["label", "detail"], "item");
      return { label: text(item.label, 100, "label"), detail: text(item.detail, 1000, "detail") };
    });
    return next;
  }

  function point(value, name) {
    if (!Array.isArray(value) || value.length !== 2) throw new TypeError(name + " must be a point");
    return [number(value[0], 0, 1, name), number(value[1], 0, 1, name)];
  }

  // Public render state: selected 0..n-1, rotation in radians (-2PI..2PI),
  // phase 0..1, normalized pointer/trail points, lift 0..1.
  function normalizeState(value, options) {
    record(value, stateKeys, "state");
    const s = { selected: 0, rotation: 0, phase: 0, pointer: [0.5, 0.5], trail: [], lift: 1, ...value };
    number(s.selected, 0, options.items.length - 1, "selected");
    if (!Number.isInteger(s.selected)) throw new RangeError("selected must be an integer");
    number(s.rotation, -2 * Math.PI, 2 * Math.PI, "rotation");
    number(s.phase, 0, 1, "phase");
    number(s.lift, 0, 1, "lift");
    s.pointer = point(s.pointer, "pointer");
    if (!Array.isArray(s.trail) || s.trail.length > 24) throw new RangeError("trail allows at most 24 points");
    s.trail = Array.from(s.trail, p => point(p, "trail"));
    return s;
  }

  function escape(value) {
    return String(value).replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;"
    })[c]);
  }

  function fmt(value) {
    if (!Number.isFinite(value)) throw new RangeError("Non-finite geometry");
    return String(Math.round(value * 1000) / 1000);
  }

  function palette(theme) {
    const dark = theme === "dark" || (theme === "system" &&
      typeof root.matchMedia === "function" && root.matchMedia("(prefers-color-scheme: dark)").matches);
    return dark
      ? { bg: "#10151b", ink: "#e9edf2", quiet: "#98a4b1", top: "#202b36", side: "#141c25", blue: "#79bdf2", copper: "#dca879" }
      : { bg: "#faf9f6", ink: "#24313d", quiet: "#606e78", top: "#ffffff", side: "#e8ecee", blue: "#256b9c", copper: "#925c36" };
  }

  function description(o, s) {
    const selected = o.items[s.selected];
    return o.summary + " Selected " + (s.selected + 1) + " of " + o.items.length + ": " +
      selected.label + ". " + selected.detail + " Intensity: " + Math.round(o.intensity * 100) + "%." +
      (o.kind === "orbit" ? " Rotation: " + Math.round(s.rotation * 180 / Math.PI) + " degrees." : "") +
      (o.kind === "signal" ? " Signal point: x " + Math.round(s.pointer[0] * 100) + "%, y " +
        Math.round(s.pointer[1] * 100) + "%. Retained trail: " + s.trail.length + " points." : "") +
      (o.kind === "flow" ? " Pulse position: " + Math.round(s.phase * 100) + "%." : "");
  }

  function renderSVG(options = {}, state = {}) {
    const o = normalize(options);
    const s = normalizeState(state, o);
    return draw(o, s);
  }

  function draw(o, s) {
    const m = math(), p = palette(o.theme), n = o.items.length;
    const camera = { yaw: Math.PI / 4 + s.rotation, elevation: Math.PI / 6, scale: 1, cx: 300, cy: 225 };
    const shapes = [], boxes = [];
    const project = v => m.project(v, camera);
    const line = (a, b, color = p.quiet, width = 0.7) =>
      `<path d="M ${a.map(fmt).join(" ")} L ${b.map(fmt).join(" ")}" fill="none" stroke="${color}" stroke-width="${width}"/>`;
    const circle = (v, radius, color, fill = p.bg) =>
      `<circle cx="${fmt(v[0])}" cy="${fmt(v[1])}" r="${fmt(radius)}" fill="${fill}" stroke="${color}" stroke-width="1"/>`;
    const box = (center, size, index) => boxes.push({ center, size, index, depth: m.depth(center, camera) });
    const strength = o.intensity * s.lift;

    // Ground rules remain fixed while the metaphor's objects move above them.
    for (let i = -2; i <= 2; i++) {
      shapes.push(line(project([-150, i * 45, -12]), project([150, i * 45, -12])));
      shapes.push(line(project([i * 60, -95, -12]), project([i * 60, 95, -12])));
    }
    if (o.kind === "stack") {
      for (let i = 0; i < n; i++) {
        const selected = i === s.selected;
        box([(i - (n - 1) / 2) * 13, 0, 10 + i * 10 + (selected ? 40 * strength : 0)],
          [142, 94, 5], i);
      }
    } else if (o.kind === "field") {
      const cols = Math.ceil(Math.sqrt(n)), rows = Math.ceil(n / cols);
      for (let i = 0; i < n; i++) {
        const x = i % cols, y = Math.floor(i / cols);
        const distance = Math.hypot(x / Math.max(1, cols - 1) - s.pointer[0],
          y / Math.max(1, rows - 1) - s.pointer[1]);
        const height = 8 + Math.max(0, 1 - distance) * 64 * strength;
        box([(x - (cols - 1) / 2) * 68, (y - (rows - 1) / 2) * 68, height / 2], [48, 48, height], i);
      }
    } else if (o.kind === "layers") {
      const spacing = Math.min(9 + 15 * strength, 130 / (n - 1));
      for (let i = 0; i < n; i++) {
        box([0, 0, 6 + i * spacing], [170 - i * 6, 108 - i * 3, 4], i);
      }
      shapes.push(line(project([100, 60, 0]), project([100, 60, 6 + (n - 1) * spacing]), p.copper));
    } else if (o.kind === "signal") {
      const trail = s.trail.length ? s.trail : [[0.08, 0.58], [0.3, 0.58], [0.43, 0.22], [0.6, 0.78], [0.73, 0.44], [0.92, 0.44]];
      const points = trail.map(([x, y]) => [100 + x * 400, 124 + y * 142]);
      shapes.push(`<path d="M ${points.map(v => v.map(fmt).join(" ")).join(" L ")}" fill="none" stroke="${p.blue}" stroke-width="1.5" stroke-linejoin="round"/>`);
      shapes.push(circle(points[points.length - 1], 5, p.copper));
      for (let i = 0; i < n; i++) box([(i / (n - 1) - 0.5) * 285, 40, 8 + (i === s.selected ? 28 * strength : 0)], [20, 20, 12], i);
    } else if (o.kind === "orbit") {
      const ring = [];
      for (let i = 0; i <= 64; i++) {
        const a = i * Math.PI / 32;
        ring.push(project([116 * Math.cos(a), 116 * Math.sin(a), 0]));
      }
      shapes.push(`<path d="M ${ring.map(v => v.map(fmt).join(" ")).join(" L ")}" fill="none" stroke="${p.quiet}" stroke-width="0.8"/>`);
      for (let i = 0; i < n; i++) {
        const a = i * 2 * Math.PI / n;
        box([116 * Math.cos(a), 116 * Math.sin(a), 18 + (i === s.selected ? 26 * strength : 0)], [36, 36, 30], i);
      }
    } else {
      const centers = [];
      for (let i = 0; i < n; i++) {
        const x = (i / (n - 1) - 0.5) * 320;
        centers.push([x, 0, 14]);
        box([x, 0, 14], [26, 36, 28], i);
        if (i) shapes.push(line(project(centers[i - 1]), project(centers[i]), p.blue, 1.2));
      }
      const pulse = project([(s.phase - 0.5) * 320, -26, 42]);
      shapes.push(circle(pulse, 5, p.copper, p.copper));
      shapes.push(line(pulse, project([(s.phase - 0.5) * 320, -26, 0]), p.copper));
    }

    // Opaque visible faces, painted back-to-front; there is no x-ray wireframe.
    boxes.sort((a, b) => a.depth - b.depth);
    for (const b of boxes) {
      const selected = b.index === s.selected;
      const color = selected ? p.blue : p.ink;
      const faces = m.boxFaces(b.center, b.size, camera);
      const paths = faces.map(face => {
        const d = m.roundedPolygon(face.points, 1.6).replace(/-?\d+(?:\.\d+)?(?:e[+-]?\d+)?/gi,
          value => fmt(Number(value)));
        return `<path d="${escape(d)}" fill="${face.kind === "top" ? p.top : p.side}" stroke="${color}" stroke-width="${selected ? 1.3 : 0.8}" stroke-linejoin="round"/>`;
      }).join("");
      const marker = project([b.center[0], b.center[1], b.center[2] + b.size[2] / 2 + 1]);
      shapes.push(`<g><title>${escape(o.items[b.index].label + ": " + o.items[b.index].detail)}</title>${paths}<text x="${fmt(marker[0])}" y="${fmt(marker[1] + 4)}" fill="${selected ? p.blue : p.quiet}" text-anchor="middle" font-size="11">${b.index + 1}</text></g>`);
    }
    const selected = o.items[s.selected];
    const short = value => Array.from(value).length > 58 ? Array.from(value).slice(0, 55).join("") + "…" : value;
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 400" width="600" height="400" role="img" aria-label="${escape(o.title)}" data-line-kind="${o.kind}" style="display:block;width:100%;height:auto;font-family:system-ui,sans-serif"><title>${escape(o.title)}</title><desc>${escape(description(o, s))}</desc><rect width="600" height="400" fill="${p.bg}"/><text x="24" y="32" fill="${p.ink}" font-size="16">${escape(short(o.title))}</text><g>${shapes.join("")}</g><path d="M 24 345 L 576 345" fill="none" stroke="${p.quiet}" stroke-width="0.6"/><text x="24" y="369" fill="${p.ink}" font-size="13">${escape((s.selected + 1) + " / " + n + "  " + short(selected.label))}</text><text x="576" y="389" fill="${p.quiet}" text-anchor="end" font-size="10">STE LINE STUDIO · ${o.kind.toUpperCase()}</text></svg>`;
  }

  // update accepts only option keys and preserves selection when possible.
  // reset restores the original mount options and the initial, paused state.
  // All methods are local to this wrapper; destroy is safe to call repeatedly.
  function mount(host, options = {}) {
    if (!host || host.nodeType !== 1 || !host.ownerDocument || typeof host.appendChild !== "function") {
      throw new TypeError("host must be a DOM element");
    }
    let o = normalize(options);
    const original = normalize(o);
    let s = normalizeState({}, o);
    // Validate and render before altering even a previous instance.
    const initialSVG = draw(o, s);
    const doc = host.ownerDocument, win = doc.defaultView || root;
    const cleanups = [];
    let dead = false, failed = false, raf = null, lastTime = null;
    let visible = true, printing = false, running = false, pointerId = null, dragX = 0;
    let lift = { value: 1, velocity: 0, settled: true };
    const reduced = typeof win.matchMedia === "function" ? win.matchMedia("(prefers-reduced-motion: reduce)") : null;
    const colorScheme = typeof win.matchMedia === "function" ? win.matchMedia("(prefers-color-scheme: dark)") : null;
    let reduce = !!(reduced && reduced.matches);

    function element(tag, textValue) {
      const node = doc.createElement(tag);
      if (textValue !== undefined) node.textContent = textValue;
      return node;
    }
    const wrapper = element("section");
    wrapper.className = "ste-line-studio";
    wrapper.setAttribute("aria-label", o.title);
    const stage = element("div");
    stage.style.cssText = "position:relative;max-width:900px;";
    const picture = element("div");
    picture.innerHTML = initialSVG;
    const surface = element("div");
    surface.tabIndex = 0;
    surface.setAttribute("role", "group");
    surface.style.cssText = "position:absolute;inset:12% 4% 16%;cursor:crosshair;touch-action:pan-y;border-radius:4px;";
    const controls = element("div");
    controls.style.cssText = "display:flex;flex-wrap:wrap;gap:12px;align-items:center;padding:12px 0;";
    const selectLabel = element("label", "Part ");
    const selectControl = element("select");
    selectLabel.style.cssText = "display:flex;gap:6px;align-items:center;min-width:0;max-width:100%;";
    selectControl.style.cssText = "min-width:0;max-width:100%;";
    selectLabel.appendChild(selectControl);
    const intensityLabel = element("label", "Intensity ");
    const intensityControl = element("input");
    intensityControl.type = "range";
    intensityControl.min = "0"; intensityControl.max = "1"; intensityControl.step = "0.01";
    intensityLabel.appendChild(intensityControl);
    const rotationLabel = element("label", "Rotation ");
    const rotationControl = element("input");
    rotationControl.type = "range";
    rotationControl.min = "-180"; rotationControl.max = "180"; rotationControl.step = "5";
    rotationLabel.appendChild(rotationControl);
    const play = element("button", "Start pulse");
    play.type = "button";
    const resetButton = element("button", "Reset");
    resetButton.type = "button";
    const signalLabels = ["Signal x ", "Signal y "].map(label => element("label", label));
    const signalControls = signalLabels.map(label => {
      const control = element("input");
      control.type = "range"; control.min = "0"; control.max = "100"; control.step = "1";
      label.appendChild(control);
      return control;
    });
    const phaseLabel = element("label", "Pulse position ");
    const phaseControl = element("input");
    phaseControl.type = "range"; phaseControl.min = "0"; phaseControl.max = "100"; phaseControl.step = "1";
    phaseLabel.appendChild(phaseControl);
    const readout = element("p");
    readout.setAttribute("role", "status");
    readout.setAttribute("aria-live", "polite");
    readout.setAttribute("aria-atomic", "true");
    stage.appendChild(picture); stage.appendChild(surface);
    for (const node of [selectLabel, intensityLabel, rotationLabel, play, resetButton, ...signalLabels, phaseLabel]) controls.appendChild(node);
    wrapper.appendChild(stage); wrapper.appendChild(controls); wrapper.appendChild(readout);

    function active() { return !dead && !failed; }
    function canMove() { return active() && !reduce && !doc.hidden && visible && !printing; }
    function cancelFrame() {
      if (raf !== null) win.cancelAnimationFrame(raf);
      raf = null; lastTime = null;
    }
    function paint() { picture.innerHTML = draw(o, s); }
    function read() {
      readout.textContent = description(o, s) +
        (o.kind === "flow" ? (running ? " Pulse running." : " Pulse paused.") : "") +
        (reduce ? " Reduced motion: changes are immediate." : "");
      play.textContent = running ? "Pause pulse" : "Start pulse";
      play.disabled = reduce || !visible || !!doc.hidden || printing;
      selectControl.value = String(s.selected);
      intensityControl.value = String(o.intensity);
      rotationControl.value = String(Math.round(s.rotation * 180 / Math.PI));
      signalControls.forEach((control, i) => { control.value = String(Math.round(s.pointer[i] * 100)); });
      phaseControl.value = String(Math.round(s.phase * 100));
    }
    function syncControls() {
      selectControl.replaceChildren();
      o.items.forEach((item, index) => {
        const option = element("option", (index + 1) + ". " + item.label);
        option.value = String(index);
        selectControl.appendChild(option);
      });
      wrapper.setAttribute("aria-label", o.title);
      rotationLabel.hidden = o.kind !== "orbit";
      play.hidden = o.kind !== "flow";
      phaseLabel.hidden = o.kind !== "flow";
      signalLabels.forEach(label => { label.hidden = o.kind !== "signal"; });
      surface.style.touchAction = ["orbit", "signal"].includes(o.kind) ? "none" : "pan-y";
      surface.setAttribute("aria-label", o.kind === "orbit"
        ? "Drag or use left and right arrows to rotate. Use the Part control to select a block."
        : o.kind === "signal"
        ? "Trace a signal with a pointer or arrow keys. The Signal x and Signal y controls move the same point."
        : "Point or use arrow keys to select a part. Home and End select the first and last parts.");
      read();
    }
    function fail(error) {
      failed = true; running = false; cancelFrame(); releasePointer();
      readout.textContent = "This figure paused because it could not render. " + error.message;
      play.disabled = true;
    }
    function safely(action) {
      return event => {
        if (!active()) return;
        try { action(event); } catch (error) { fail(error); }
      };
    }
    function listen(target, type, action) {
      const handler = safely(action);
      target.addEventListener(type, handler);
      cleanups.push(() => target.removeEventListener(type, handler));
    }
    function schedule() {
      if (canMove() && raf === null && (!lift.settled || running)) {
        raf = win.requestAnimationFrame(frame);
      }
    }
    function frame(time) {
      raf = null;
      if (!canMove()) { lastTime = null; return; }
      try {
        const dt = lastTime === null ? 1 / 60 : Math.min(0.05, Math.max(0, (time - lastTime) / 1000));
        lastTime = time;
        lift = math().stepSpring(lift, 1, dt, { stiffness: 150, damping: 26, epsilon: 0.002 });
        s.lift = Math.min(1, Math.max(0, lift.value));
        if (running) s.phase = (s.phase + dt * (0.12 + 0.25 * o.intensity)) % 1;
        paint();
        if (lift.settled && !running) lastTime = null;
        schedule();
      } catch (error) { fail(error); }
    }
    function pause() {
      running = false; cancelFrame(); releasePointer();
      lift = { value: 1, velocity: 0, settled: true };
      s.lift = 1; paint(); read();
    }
    function animateSelection() {
      if (canMove()) lift = { value: 0, velocity: 0, settled: false };
      else lift = { value: 1, velocity: 0, settled: true };
      s.lift = lift.value;
      paint(); read(); schedule();
    }
    function selectedState(index) {
      number(index, 0, o.items.length - 1, "selected");
      if (!Number.isInteger(index)) throw new RangeError("selected must be an integer");
      const next = { ...s, selected: index };
      const cols = Math.ceil(Math.sqrt(o.items.length)), rows = Math.ceil(o.items.length / cols);
      next.pointer = o.kind === "field"
        ? [(index % cols) / Math.max(1, cols - 1), Math.floor(index / cols) / Math.max(1, rows - 1)]
        : [index / (o.items.length - 1), 0.5];
      if (o.kind === "signal") next.trail = s.trail.concat([next.pointer]).slice(-24);
      return next;
    }
    function select(index) {
      const next = selectedState(index);
      if (!active()) return api;
      draw(o, next); // Preflight errors cannot partially mutate the live state.
      if (index === s.selected && o.kind !== "signal" && o.kind !== "field") return api;
      s = next; running = false; animateSelection();
      return api;
    }
    function update(partial) {
      record(partial, optionKeys, "options");
      const next = normalize({ ...o, ...partial });
      const nextState = normalizeState({
        ...s, selected: Math.min(s.selected, next.items.length - 1), lift: 1,
        ...(next.kind !== o.kind ? { rotation: 0, phase: 0, trail: [], pointer: [0.5, 0.5] } : {})
      }, next);
      const svg = draw(next, nextState);
      if (!active()) return api;
      cancelFrame(); releasePointer(); running = false;
      o = next; s = nextState; lift = { value: 1, velocity: 0, settled: true };
      picture.innerHTML = svg; syncControls();
      return api;
    }
    function reset() {
      if (!active()) return api;
      const next = normalize(original), nextState = normalizeState({}, next);
      const svg = draw(next, nextState);
      cancelFrame(); releasePointer(); running = false;
      o = next; s = nextState; lift = { value: 1, velocity: 0, settled: true };
      picture.innerHTML = svg; syncControls();
      return api;
    }
    function releasePointer() {
      if (pointerId !== null && typeof surface.hasPointerCapture === "function" &&
          surface.hasPointerCapture(pointerId)) surface.releasePointerCapture(pointerId);
      pointerId = null;
    }
    function destroy() {
      if (dead) return;
      dead = true; running = false; cancelFrame(); releasePointer();
      for (const cleanup of cleanups.splice(0)) cleanup();
      wrapper.remove();
      if (instances.get(host) === api) instances.delete(host);
    }
    const api = Object.freeze({ update, select, reset, toSVG: () => draw(o, s), destroy });

    function locate(event) {
      const r = surface.getBoundingClientRect();
      if (!r.width || !r.height) return null;
      return [math().clamp((event.clientX - r.left) / r.width, 0, 1),
        math().clamp((event.clientY - r.top) / r.height, 0, 1)];
    }
    function chooseAt(event) {
      const p = locate(event);
      if (!p) return;
      if (o.kind === "signal") { trace(p); return; }
      let index = Math.min(o.items.length - 1, Math.floor(p[0] * o.items.length));
      if (o.kind === "field") {
        const cols = Math.ceil(Math.sqrt(o.items.length)), rows = Math.ceil(o.items.length / cols);
        index = Math.min(o.items.length - 1, Math.min(cols - 1, Math.floor(p[0] * cols)) +
          Math.min(rows - 1, Math.floor(p[1] * rows)) * cols);
      }
      // Quantized, fixed hit planes map pointer/touch to exactly the keyboard states.
      if (index !== s.selected || event.type === "pointerdown") select(index);
    }
    function trace(position) {
      // One-percent steps give pointer, touch, arrows and native ranges the
      // same reachable coordinates. Retain a bounded trail, never a timer.
      const next = point(position, "signal point").map(v => Math.round(v * 100) / 100);
      if (s.trail.length && next.every((v, i) => v === s.pointer[i])) return;
      s.pointer = next;
      s.trail = s.trail.concat([next]).slice(-24);
      s.selected = Math.min(o.items.length - 1, Math.floor(next[0] * o.items.length));
      paint(); read();
    }
    function rotate(radians) {
      s.rotation = Math.max(-Math.PI, Math.min(Math.PI, radians));
      running = false; paint(); read();
    }
    try {
      syncControls();
      listen(selectControl, "change", () => select(Number(selectControl.value)));
      listen(intensityControl, "input", () => update({ intensity: Number(intensityControl.value) }));
      listen(rotationControl, "input", () => rotate(Number(rotationControl.value) * Math.PI / 180));
      listen(phaseControl, "input", () => {
        s.phase = number(Number(phaseControl.value) / 100, 0, 1, "phase");
        pause();
      });
      signalControls.forEach((control, axis) => listen(control, "input", () => {
        const next = s.pointer.slice(); next[axis] = Number(control.value) / 100;
        trace(next);
      }));
      listen(resetButton, "click", reset);
      listen(play, "click", () => {
        if (running) pause();
        else if (canMove()) { running = true; read(); schedule(); }
      });
      listen(surface, "keydown", event => {
        const keys = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"];
        if (!keys.includes(event.key)) return;
        event.preventDefault();
        if (o.kind === "signal") {
          const next = s.pointer.slice();
          if (event.key === "Home" || event.key === "End") next[0] = event.key === "Home" ? 0 : 1;
          else {
            const axis = ["ArrowUp", "ArrowDown"].includes(event.key) ? 1 : 0;
            next[axis] = math().clamp(next[axis] +
              (["ArrowLeft", "ArrowUp"].includes(event.key) ? -0.01 : 0.01), 0, 1);
          }
          trace(next);
        } else if (o.kind === "orbit") {
          rotate(event.key === "Home" ? -Math.PI : event.key === "End" ? Math.PI :
            s.rotation + (["ArrowLeft", "ArrowDown"].includes(event.key) ? -1 : 1) * Math.PI / 36);
        } else {
          const stride = o.kind === "field" && ["ArrowUp", "ArrowDown"].includes(event.key)
            ? Math.ceil(Math.sqrt(o.items.length)) : 1;
          select(event.key === "Home" ? 0 : event.key === "End" ? o.items.length - 1 :
            Math.max(0, Math.min(o.items.length - 1, s.selected +
              (["ArrowLeft", "ArrowUp"].includes(event.key) ? -stride : stride))));
        }
      });
      listen(surface, "pointerdown", event => {
        if (event.button !== 0 || pointerId !== null) return;
        pointerId = event.pointerId; dragX = event.clientX;
        surface.focus({ preventScroll: true });
        if (typeof surface.setPointerCapture === "function") surface.setPointerCapture(pointerId);
        if (o.kind !== "orbit") chooseAt(event);
      });
      listen(surface, "pointermove", event => {
        if (pointerId !== null && event.pointerId !== pointerId) return;
        if (o.kind === "orbit" && pointerId !== null) {
          rotate(s.rotation + (event.clientX - dragX) * 0.012);
          dragX = event.clientX;
        } else if (pointerId !== null || (event.pointerType === "mouse" && ["field", "signal"].includes(o.kind))) {
          chooseAt(event);
        }
      });
      listen(surface, "pointerup", releasePointer);
      listen(surface, "pointercancel", releasePointer);
      listen(surface, "lostpointercapture", () => { pointerId = null; });
      listen(doc, "visibilitychange", () => { pause(); });
      listen(win, "beforeprint", () => { printing = true; pause(); });
      listen(win, "afterprint", () => { printing = false; read(); });
      if (reduced) listen(reduced, "change", event => { reduce = event.matches; pause(); });
      if (colorScheme) listen(colorScheme, "change", () => { if (o.theme === "system") paint(); });
      if (typeof win.IntersectionObserver === "function") {
        const observer = new win.IntersectionObserver(safely(entries => {
          const entry = entries.find(e => e.target === wrapper);
          if (entry) { visible = entry.isIntersecting; if (!visible) pause(); else read(); }
        }));
        observer.observe(wrapper);
        cleanups.push(() => observer.disconnect());
      }
      const previous = instances.get(host);
      if (previous) previous.destroy();
      host.appendChild(wrapper);
      instances.set(host, api);
    } catch (error) {
      destroy();
      throw error;
    }
    return api;
  }

  return Object.freeze({ renderSVG, mount });
});
