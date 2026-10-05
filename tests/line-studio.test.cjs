/* Original STE Line Studio tests. SPDX-License-Identifier: Apache-2.0 */
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const studio = require("../ste_promax/assets/line-studio.js");
const kinds = ["stack", "field", "layers", "signal", "orbit", "flow"];
const items = [{ label: "First", detail: "First evidence." }, { label: "Second", detail: "Second evidence." }];

test("UMD exports the same API and does not resolve math until runtime", () => {
  assert.equal(globalThis.STELineStudio, studio);
  const source = fs.readFileSync(path.join(__dirname, "../ste_promax/assets/line-studio.js"), "utf8");
  const context = vm.createContext({});
  vm.runInContext(source, context);
  assert.equal(typeof context.STELineStudio.mount, "function");
  assert.throws(() => vm.runInContext("STELineStudio.renderSVG()", context), /requires STELineMath/);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../ste_promax/assets/line-math.js"), "utf8"), context);
  assert.match(vm.runInContext("STELineStudio.renderSVG()", context), /^<svg /);
});

test("six original, distinct, deterministic named SVG renderers", () => {
  const svgs = kinds.map(kind => studio.renderSVG({ kind, items, title: "Evidence map", summary: "Full context." }));
  assert.equal(new Set(svgs).size, 6);
  for (let i = 0; i < kinds.length; i++) {
    const svg = svgs[i];
    assert.match(svg, /^<svg xmlns="http:\/\/www.w3.org\/2000\/svg"/);
    assert.match(svg, /role="img" aria-label="Evidence map"/);
    assert.match(svg, /<title>Evidence map<\/title><desc>Full context\./);
    assert.match(svg, /Selected 1 of 2: First\. First evidence\./);
    assert.match(svg, /<path /);
    assert.match(svg, /<\/svg>$/);
    assert.equal(svg, studio.renderSVG({ kind: kinds[i], items, title: "Evidence map", summary: "Full context." }));
  }
});

test("source text is escaped in names, descriptions, item titles and visible labels", () => {
  const malicious = `"><script>alert('x')</script><foreignObject onload="bad">&`;
  for (const kind of kinds) {
    const svg = studio.renderSVG({ kind, title: malicious, summary: malicious,
      items: [{ label: malicious, detail: malicious }, items[1]] });
    assert.ok(svg.includes("&lt;script&gt;"));
    assert.ok(svg.includes("&amp;"));
    assert.ok(svg.includes("&quot;"));
    assert.ok(svg.includes("&apos;"));
    assert.doesNotMatch(svg, /<(?:script|foreignObject)/i);
    for (const tag of svg.match(/<[^>]*>/g)) {
      // Inspect attribute names, not inert malicious text inside quoted values.
      const structure = tag.replace(/"[^"]*"/g, '""');
      assert.doesNotMatch(structure, /\son\w+=|\s(?:href|xlink:href|src)=/i);
    }
    assert.doesNotMatch(svg, /url\s*\(/i);
  }
});

test("full title, summary and selected detail survive visual truncation", () => {
  const title = "Long title ".repeat(14);
  const summary = "Long explanation. ".repeat(100);
  const detail = "Second context. ".repeat(60);
  const svg = studio.renderSVG({ title, summary, items: [items[0], { label: "Chosen item", detail }] }, { selected: 1 });
  assert.ok(svg.includes("<title>" + title + "</title>"));
  assert.ok(svg.includes(summary));
  assert.ok(svg.includes("Selected 2 of 2: Chosen item. " + detail));
  assert.match(svg, /…/);
});

test("defaults are useful and inputs are copied, not modified", () => {
  assert.match(studio.renderSVG(), /A closer look/);
  const input = Object.freeze({ items: Object.freeze(items.map(x => Object.freeze({ ...x }))), intensity: 0 });
  const state = Object.freeze({ selected: 1, pointer: Object.freeze([0, 1]), trail: Object.freeze([]) });
  assert.match(studio.renderSVG(input, state), /Selected 2 of 2/);
  assert.equal(input.items[1].label, "Second");
  assert.equal(state.selected, 1);
});

test("invalid options, extra properties and oversized content are rejected", () => {
  const invalid = [null, [], "stack", 4, new Date(), { kind: "unknown" }, { theme: "neon" },
    { kind: undefined }, { title: "" }, { title: " " }, { summary: null }, { title: "x".repeat(161) },
    { summary: "x".repeat(2001) }, { title: "\u0000" }, { title: "\ud800" }, { title: "\udfff" },
    { items: [] }, { items: [items[0]] }, { items: Array(10).fill(items[0]) }, { items: new Array(2) },
    { items: [null, items[0]] }, { items: [{ label: "x" }, items[0]] },
    { items: [{ ...items[0], label: "x".repeat(101) }, items[1]] },
    { items: [{ ...items[0], detail: "x".repeat(1001) }, items[1]] },
    { items: [{ ...items[0], extra: 1 }, items[1]] }, { extra: true }, { onclick: "bad" },
    { intensity: NaN }, { intensity: Infinity }, { intensity: -0.1 }, { intensity: 1.1 }, { intensity: "0.5" }];
  for (const options of invalid) assert.throws(() => studio.renderSVG(options), undefined, JSON.stringify(options));
  assert.throws(() => studio.renderSVG({ [Symbol("unknown")]: true }), /Unknown/);
  assert.throws(() => studio.renderSVG({ get title() { throw Error("getter executed"); } }), /data properties/);
  assert.throws(() => studio.renderSVG(JSON.parse('{"__proto__":{}}')), /Unknown/);
});

test("state validation rejects non-finite, unknown, out-of-range and unbounded data", () => {
  const invalid = [null, [], { selected: -1 }, { selected: 2 }, { selected: 0.5 }, { selected: NaN },
    { rotation: Infinity }, { rotation: 10 }, { phase: -1 }, { phase: 1.01 }, { lift: NaN },
    { pointer: [0, 2] }, { pointer: [NaN, 0] }, { pointer: [0] }, { pointer: "bad" },
    { trail: new Array(25).fill([0, 0]) }, { trail: new Array(2) }, { trail: [[0, Infinity]] },
    { playing: true }];
  for (const state of invalid) assert.throws(() => studio.renderSVG({ items }, state));
});

test("all bounded geometries have finite path coordinates and opaque faces", () => {
  for (const kind of kinds) for (const count of [2, 9]) for (const intensity of [0, 1]) {
    const opts = { kind, intensity, items: Array.from({ length: count }, (_, i) => ({ label: "Part " + i, detail: "Evidence" })) };
    for (const rotation of [-2 * Math.PI, -Math.PI / 2, 0, Math.PI, 2 * Math.PI]) {
      const svg = studio.renderSVG(opts, { selected: count - 1, rotation, phase: 1,
        pointer: [1, 0], trail: [[0, 0], [1, 1]] });
      assert.doesNotMatch(svg, /NaN|Infinity|undefined/);
      for (const match of svg.matchAll(/\sd="([^"]+)"/g)) {
        assert.match(match[1], /^[MLQZ0-9.,\s-]+$/);
        for (const value of match[1].match(/-?\d+(?:\.\d+)?/g) || []) assert.ok(Number.isFinite(Number(value)));
      }
      assert.match(svg, /fill="#ffffff" stroke=/);
      assert.match(svg, /fill="#e8ecee" stroke=/);
      assert.doesNotMatch(svg, /opacity=/);
    }
  }
});

test("nine-layer explosion stays inside the figure instead of clipping above its title", () => {
  const svg = studio.renderSVG({ kind: "layers", intensity: 1,
    items: Array.from({ length: 9 }, (_, i) => ({ label: "Layer " + i, detail: "Review" })) });
  for (const match of svg.matchAll(/\sd="([^"]+)"/g)) {
    const coords = (match[1].match(/-?\d+(?:\.\d+)?/g) || []).map(Number);
    for (let i = 0; i < coords.length; i += 2) {
      assert.ok(coords[i] >= 0 && coords[i] <= 600);
      assert.ok(coords[i + 1] >= 45 && coords[i + 1] <= 345);
    }
  }
});

test("selection, intensity, rotation, phase and signal trail affect their figures", () => {
  for (const kind of kinds) {
    const opts = { kind, items };
    assert.notEqual(studio.renderSVG(opts), studio.renderSVG(opts, { selected: 1 }));
  }
  assert.notEqual(studio.renderSVG({ kind: "stack", intensity: 0 }), studio.renderSVG({ kind: "stack", intensity: 1 }));
  assert.notEqual(studio.renderSVG({ kind: "orbit" }), studio.renderSVG({ kind: "orbit" }, { rotation: 1 }));
  assert.notEqual(studio.renderSVG({ kind: "flow" }), studio.renderSVG({ kind: "flow" }, { phase: 0.5 }));
  assert.notEqual(studio.renderSVG({ kind: "signal" }), studio.renderSVG({ kind: "signal" }, { trail: [[0, 0], [1, 1]] }));
  assert.match(studio.renderSVG({ theme: "dark" }), /fill="#10151b"/);
  assert.match(studio.renderSVG({ theme: "light" }), /fill="#faf9f6"/);
});

// Small DOM contract double: no browser/layout claims. It checks ownership,
// atomic updates and lifecycle scheduling without third-party dependencies.
function fakeDOM() {
  class Target {
    constructor() { this.listeners = new Map(); }
    addEventListener(type, fn) {
      if (!this.listeners.has(type)) this.listeners.set(type, new Set());
      this.listeners.get(type).add(fn);
    }
    removeEventListener(type, fn) { this.listeners.get(type)?.delete(fn); }
    emit(type, data = {}) { for (const fn of this.listeners.get(type) || []) fn({ type, ...data }); }
    count() { return [...this.listeners.values()].reduce((total, set) => total + set.size, 0); }
  }
  class Node extends Target {
    constructor(tag) {
      super(); this.tagName = tag; this.nodeType = 1; this.children = []; this.attributes = {};
      this.style = {}; this.ownerDocument = doc;
    }
    setAttribute(name, value) { this.attributes[name] = value; }
    appendChild(node) { this.children.push(node); node.parentNode = this; return node; }
    replaceChildren() { this.children = []; }
    remove() {
      if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(n => n !== this);
      this.parentNode = null;
    }
    focus() {}
    getBoundingClientRect() { return { left: 0, top: 0, width: 600, height: 300 }; }
  }
  const doc = new Target(), win = new Target(), frames = new Map(), media = new Map(), observers = [];
  let frameId = 0;
  doc.hidden = false; doc.defaultView = win; doc.createElement = tag => new Node(tag);
  win.matchMedia = query => {
    if (!media.has(query)) { const target = new Target(); target.matches = false; media.set(query, target); }
    return media.get(query);
  };
  win.requestAnimationFrame = fn => { frames.set(++frameId, fn); return frameId; };
  win.cancelAnimationFrame = id => frames.delete(id);
  win.IntersectionObserver = class {
    constructor(fn) { this.fn = fn; this.disconnected = false; observers.push(this); }
    observe(target) { this.target = target; }
    disconnect() { this.disconnected = true; }
  };
  return { host: new Node("host"), doc, win, frames, media, observers,
    tick(time) { const pending = [...frames.values()]; frames.clear(); pending.forEach(fn => fn(time)); } };
}

test("mount validates before mutation, preserves host, and update/select/reset are atomic", () => {
  const dom = fakeDOM(), child = dom.doc.createElement("original");
  dom.host.appendChild(child); dom.host.setAttribute("data-owner", "untouched");
  const api = studio.mount(dom.host, { items, title: "Original" });
  const svg = api.toSVG();
  assert.equal(dom.host.children.length, 2);
  assert.equal(dom.frames.size, 0, "idle mount must not request frames");
  for (const bad of [{ intensity: NaN }, { title: "x".repeat(161) }, { extra: true }]) {
    assert.throws(() => api.update(bad));
    assert.equal(api.toSVG(), svg);
  }
  assert.throws(() => api.select(1.5));
  assert.equal(api.toSVG(), svg);
  assert.throws(() => studio.mount(dom.host, { items: [] }));
  assert.equal(dom.host.children.length, 2);
  api.select(1);
  assert.match(api.toSVG(), /Selected 2 of 2/);
  assert.equal(dom.frames.size, 1);
  api.update({ title: "Updated", kind: "flow" });
  assert.match(api.toSVG(), /<title>Updated<\/title>/);
  assert.equal(dom.frames.size, 0);
  api.reset();
  assert.equal(api.toSVG(), svg);
  api.destroy(); api.destroy();
  assert.deepEqual(dom.host.children, [child]);
  assert.deepEqual(dom.host.attributes, { "data-owner": "untouched" });
  assert.equal(dom.win.count(), 0);
  assert.equal(dom.doc.count(), 0);
  assert.ok([...dom.media.values()].every(target => target.count() === 0));
  assert.ok(dom.observers.every(observer => observer.disconnected));
  assert.equal(dom.frames.size, 0);
});

test("springs settle, flow is explicit, and lifecycle events cancel motion", () => {
  const dom = fakeDOM(), api = studio.mount(dom.host, { kind: "flow" });
  const wrapper = dom.host.children[0], controls = wrapper.children[1], play = controls.children[3];
  assert.equal(dom.frames.size, 0);
  api.select(1);
  for (let frame = 0; frame < 300 && dom.frames.size; frame++) dom.tick(frame * 16.7);
  assert.equal(dom.frames.size, 0, "settled spring sleeps");
  play.emit("click"); assert.equal(dom.frames.size, 1);
  dom.tick(1000);
  dom.doc.hidden = true; dom.doc.emit("visibilitychange");
  assert.equal(dom.frames.size, 0);
  dom.doc.hidden = false; dom.doc.emit("visibilitychange");
  assert.equal(dom.frames.size, 0, "visibility does not auto-restart flow");
  play.emit("click"); assert.equal(dom.frames.size, 1);
  const reduced = dom.media.get("(prefers-reduced-motion: reduce)");
  reduced.matches = true; reduced.emit("change", { matches: true });
  assert.equal(dom.frames.size, 0);
  play.emit("click"); assert.equal(dom.frames.size, 0);
  const phaseControl = controls.children[7].children[0];
  phaseControl.value = "75"; phaseControl.emit("input");
  assert.match(api.toSVG(), /Pulse position: 75%/);
  assert.equal(dom.frames.size, 0, "a reduced-motion reader can still inspect pulse positions");
  reduced.matches = false; reduced.emit("change", { matches: false });
  play.emit("click"); assert.equal(dom.frames.size, 1);
  dom.win.emit("beforeprint"); assert.equal(dom.frames.size, 0);
  dom.win.emit("afterprint"); assert.equal(dom.frames.size, 0);
  play.emit("click"); assert.equal(dom.frames.size, 1);
  dom.observers[0].fn([{ target: wrapper, isIntersecting: false }]);
  assert.equal(dom.frames.size, 0);
  dom.observers[0].fn([{ target: wrapper, isIntersecting: true }]);
  assert.equal(dom.frames.size, 0);
  play.emit("click"); api.destroy();
  assert.equal(dom.frames.size, 0);
});

test("remount destroys only its prior wrapper; other instances remain independent", () => {
  const dom = fakeDOM(), sibling = dom.doc.createElement("sibling");
  const a = studio.mount(dom.host), b = studio.mount(sibling, { kind: "orbit" });
  a.select(1); b.select(1);
  assert.equal(dom.frames.size, 2);
  const c = studio.mount(dom.host, { kind: "signal" });
  assert.equal(dom.host.children.length, 1);
  assert.equal(dom.frames.size, 1);
  a.destroy(); assert.equal(dom.host.children.length, 1);
  assert.match(b.toSVG(), /data-line-kind="orbit"/);
  c.destroy(); b.destroy();
  assert.equal(dom.frames.size, 0);
  assert.equal(dom.win.count(), 0);
});

test("fixed hit plane, keyboard, touch and select control reach equivalent field state", () => {
  const scenarios = [
    (api, surface) => surface.emit("pointerdown", { pointerType: "mouse", pointerId: 1, button: 0, clientX: 580, clientY: 20 }),
    (api, surface) => surface.emit("pointerdown", { pointerType: "touch", pointerId: 1, button: 0, clientX: 580, clientY: 20 }),
    (api, surface) => surface.emit("keydown", { key: "ArrowRight", preventDefault() {} }),
    (api, surface, controls) => {
      const select = controls.children[0].children[0];
      select.value = "1"; select.emit("change");
    },
    api => api.select(1)
  ];
  const outputs = scenarios.map(action => {
    const dom = fakeDOM(), api = studio.mount(dom.host, { kind: "field", items });
    const wrapper = dom.host.children[0], stage = wrapper.children[0], surface = stage.children[1];
    const media = dom.media.get("(prefers-reduced-motion: reduce)");
    media.emit("change", { matches: true });
    action(api, surface, wrapper.children[1]);
    const output = api.toSVG();
    assert.equal(stage.children[1], surface, "rendering must not replace the hit plane");
    assert.equal(dom.frames.size, 0, "reduced-motion selection is immediate");
    api.destroy();
    return output;
  });
  assert.equal(new Set(outputs).size, 1);
  assert.match(outputs[0], /Selected 2 of 2/);
});

test("bounded pointer signal trail and orbit controls respond without perpetual motion", () => {
  const dom = fakeDOM(), api = studio.mount(dom.host, { kind: "signal", items });
  const wrapper = dom.host.children[0], surface = wrapper.children[0].children[1];
  dom.media.get("(prefers-reduced-motion: reduce)").emit("change", { matches: true });
  for (let i = 0; i < 100; i++) api.select(i % 2);
  assert.doesNotMatch(api.toSVG(), /NaN/);
  const signalPath = [...api.toSVG().matchAll(/d="([^"]+)" fill="none" stroke="#256b9c"/g)][0][1];
  assert.equal((signalPath.match(/ L /g) || []).length, 23, "trail retains at most 24 points");
  api.update({ kind: "orbit" });
  surface.emit("keydown", { key: "ArrowRight", preventDefault() {} });
  assert.match(api.toSVG(), /Rotation: 5 degrees/);
  wrapper.children[1].children[2].children[0].value = "90";
  wrapper.children[1].children[2].children[0].emit("input");
  assert.match(api.toSVG(), /Rotation: 90 degrees/);
  assert.equal(dom.frames.size, 0);
  api.destroy();
});

test("signal pointer, touch, arrows and native x/y ranges share the same trace state", () => {
  const scenarios = [
    (surface, controls) => surface.emit("pointerdown", { pointerType: "mouse", pointerId: 1, button: 0, clientX: 306, clientY: 150 }),
    (surface, controls) => surface.emit("pointerdown", { pointerType: "touch", pointerId: 1, button: 0, clientX: 306, clientY: 150 }),
    surface => surface.emit("keydown", { key: "ArrowRight", preventDefault() {} }),
    (surface, controls) => {
      controls.children[5].children[0].value = "51";
      controls.children[5].children[0].emit("input");
    }
  ];
  const outputs = scenarios.map(action => {
    const dom = fakeDOM(), api = studio.mount(dom.host, { kind: "signal", items });
    const wrapper = dom.host.children[0];
    action(wrapper.children[0].children[1], wrapper.children[1]);
    const svg = api.toSVG();
    assert.equal(dom.frames.size, 0);
    api.destroy();
    return svg;
  });
  assert.equal(new Set(outputs).size, 1);
});

test("one instance's render failure cancels its frame without breaking another", () => {
  const dom = fakeDOM(), sibling = dom.doc.createElement("sibling");
  const a = studio.mount(dom.host), b = studio.mount(sibling);
  a.select(1); b.select(1);
  const picture = dom.host.children[0].children[0].children[0];
  Object.defineProperty(picture, "innerHTML", { set() { throw Error("Simulated local DOM failure"); } });
  dom.tick(16);
  assert.equal(dom.frames.size, 1, "only the healthy instance keeps settling");
  assert.match(dom.host.children[0].children[2].textContent, /could not render/);
  for (let i = 2; i < 300 && dom.frames.size; i++) dom.tick(i * 16);
  assert.equal(dom.frames.size, 0);
  assert.match(b.toSVG(), /Selected 2 of 3/);
  a.destroy(); b.destroy();
  assert.equal(dom.win.count(), 0);
});
