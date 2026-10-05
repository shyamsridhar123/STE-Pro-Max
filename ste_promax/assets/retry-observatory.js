/* STE Retry Observatory. Original, deterministic SVG explanation; no dependencies. */
(function (root, factory) {
  const math = typeof module === "object" && module.exports
    ? require("./line-math.js") : root.STELineMath;
  const api = factory(math);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.STERetryObservatory = api;
})(typeof globalThis === "object" ? globalThis : this, function (M) {
  "use strict";
  const STOPS = Object.freeze([0.16, 0.36, 0.72, 1]);
  const OWNER_SWITCH = 0.875;
  const COLORS = Object.freeze({
    dark: { bg: "#10151b", face: "#151e28", side: "#111922", ink: "#e9edf2",
      muted: "#a3b0bf", rule: "#344452", blue: "#79bdf2", gold: "#efc97b", mint: "#8ad4be" },
    light: { bg: "#f7f9fb", face: "#ffffff", side: "#e6ecf2", ink: "#172333",
      muted: "#526173", rule: "#b0becb", blue: "#176698", gold: "#82600a", mint: "#176b55" },
  });
  const escape = value => String(value).replace(/[&<>"']/g, character =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;" })[character]);
  const smooth = value => {
    const t = Math.max(0, Math.min(1, value));
    return t * t * (3 - 2 * t);
  };
  const lerp = (a, b, t) => a + (b - a) * t;
  const number = value => Number(value.toFixed(3));

  function options(input = {}) {
    if (!input || typeof input !== "object" || Array.isArray(input)) throw new TypeError("Expected model options.");
    const out = { attempts: 3, layers: 4, progress: 0.72, theme: "dark", ...input };
    for (const key of ["attempts", "layers"]) {
      if (!Number.isInteger(out[key]) || out[key] < 1 || out[key] > 4) {
        throw new RangeError(`${key} must be an integer from 1 to 4.`);
      }
    }
    if (!Number.isFinite(out.progress) || out.progress < 0 || out.progress > 1) {
      throw new RangeError("progress must be between 0 and 1.");
    }
    if (!Object.hasOwn(COLORS, out.theme)) throw new RangeError("theme must be dark or light.");
    return out;
  }

  function model(input) {
    const { attempts: A, layers: L } = options(input);
    return {
      attempts: A, layers: L, retries: A - 1,
      nested: Array.from({ length: L }, (_, index) => A ** (index + 1)),
      owner: Array(L).fill(A),
      nestedBackend: A ** L, ownerBackend: A,
      repeated: A ** L - A,
    };
  }

  function validateSource(source) {
    const fail = field => { throw new Error(`Retained source disagrees with the model: ${field}.`); };
    const defaults = options(), inputs = source?.inputs;
    if (inputs?.original_requests !== 1 || inputs?.backend_failure !== "persistent") fail("request/failure assumptions");
    for (const [key, value] of [
      ["serial_layers", defaults.layers],
      ["total_attempts_per_retrying_layer_per_incoming_call", defaults.attempts],
    ]) {
      const input = inputs[key];
      if (!input || input.default !== value || input.minimum !== 1 || input.maximum !== 4 || input.step !== 1) fail(key);
    }
    const expected = model(), sample = source.default_example;
    const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);
    if (!sample || !equal(sample.nested_boundary_counts, expected.nested)
        || !equal(sample.single_owner_boundary_counts, expected.owner)
        || sample.nested_backend_attempts !== expected.nestedBackend
        || sample.single_owner_backend_attempts !== expected.ownerBackend
        || sample.retries_per_incoming_call !== expected.retries
        || sample.additional_nested_backend_calls_after_first !== expected.nestedBackend - 1) fail("default counts");
    if (!Array.isArray(source.boundary_examples) || source.boundary_examples.length < 1
        || source.boundary_examples.length > 64) fail("boundary examples");
    for (const example of source.boundary_examples) {
      const result = model({ attempts: example?.A, layers: example?.L });
      if (example.nested_backend_attempts !== result.nestedBackend
          || example.single_owner_backend_attempts !== result.ownerBackend) fail("boundary counts");
    }
    return true;
  }

  function chapter(progress) {
    return progress < 0.23 ? 0 : progress < 0.48 ? 1 : progress < OWNER_SWITCH ? 2 : 3;
  }

  function explanation(input) {
    const state = options(input), result = model(state), index = chapter(state.progress);
    const A = result.attempts, L = result.layers;
    if (A === 1) return {
      index, title: "No retries. No amplification.",
      text: "One total attempt means zero retries. More layers lengthen the path, but the backend still receives one attempt.",
      formula: `1${L > 1 ? `^${L}` : ""} = 1`,
    };
    if (L === 1) return {
      index, title: "One layer has one budget.",
      text: `With just one retrying layer, both designs make ${A} backend attempts. Multiplication across owners requires more than one layer.`,
      formula: `${A} = ${A}`,
    };
    return [
      { index, title: "First, give one call a budget.",
        text: `${A} total attempts means one initial call and ${A - 1} ${A === 2 ? "retry" : "retries"}. Assume every attempt fails, so the whole budget is used.`,
        formula: `1 × ${A} = ${A}` },
      { index, title: "Now put a budget inside it.",
        text: `Each of those ${A} calls gets a fresh ${A}-attempt budget downstream. The second boundary sees ${A} groups of ${A}, not ${A} plus ${A}.`,
        formula: `${A} × ${A} = ${A * A}` },
      { index, title: "The next layer repeats the work.",
        text: `At every boundary, each incoming call can start ${A} more. After ${L} layers, the backend can receive ${result.nestedBackend} attempts from one original request.`,
        formula: `${A}^${L} = ${result.nestedBackend}` },
      { index, title: "Give the retry budget one owner.",
        text: `Only the outermost layer retries. Every other layer forwards once. Same ${A}-attempt budget; ${result.ownerBackend} backend attempts, not ${result.nestedBackend}.`,
        formula: [A, ...Array(L - 1).fill(1)].join(" × ") + ` = ${A}` },
    ][index];
  }

  function renderSVG(input = {}) {
    const state = options(input), result = model(state), palette = COLORS[state.theme];
    const ownerMix = smooth((state.progress - 0.80) / 0.15);
    const isOwner = chapter(state.progress) === 3;
    const title = isOwner ? "One retry owner. One shared path." : "A retry budget inside a retry budget.";
    const description = `${result.layers} serial retry layers; ${result.attempts} total attempts per retrying layer, including the initial call. `
      + `Under persistent failure, nested retries produce ${result.nestedBackend} backend attempts; one retry owner produces ${result.ownerBackend}. `
      + "Each tile is one cumulative attempt, not a simultaneous request or a unit of time. This timeline reveals the explanation, not production telemetry."
      + (ownerMix > 0 && ownerMix < 1 ? " The policy transition is in progress; fading tiles illustrate calls removed, not an intermediate production measurement." : "");
    const pieces = [
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 440" role="img" aria-labelledby="retry-title retry-description">`,
      `<title id="retry-title">${escape(title)}</title><desc id="retry-description">${escape(description)}</desc>`,
      `<metadata>${escape(JSON.stringify({ type: "illustrative-model", ...result, progress: state.progress,
        limits: "Persistent failure; exhausted budgets; no shared deadline, cancellation, caching, circuit breaker or deduplication; not a resilience guarantee." }))}</metadata>`,
      `<rect width="960" height="440" fill="${palette.bg}"/>`,
      `<defs><marker id="retry-arrow" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="5" markerHeight="5" orient="auto"><path d="M1 1 L6 4 L1 7" fill="none" stroke="${palette.muted}" stroke-width="1.2"/></marker></defs>`,
      `<text x="38" y="42" fill="${palette.muted}" font-family="system-ui, sans-serif" font-size="14">One original request</text>`,
      `<text x="922" y="42" fill="${palette.muted}" text-anchor="end" font-family="system-ui, sans-serif" font-size="14">Every backend attempt fails</text>`,
    ];
    const positions = Array.from({ length: result.layers + 1 }, (_, i) => 78 + i * 804 / result.layers);
    const activeBoundary = Math.min(result.layers, Math.floor(Math.max(0, state.progress - 0.015) / (0.65 / result.layers)) + 1);
    for (let i = 0; i <= result.layers; i++) {
      const isLast = i === result.layers, x = positions[i];
      const nestedCount = i === 0 ? 1 : result.nested[i - 1];
      const ownerCount = i === 0 ? 1 : result.attempts;
      const reveal = i === 0 ? 1 : smooth((state.progress - (i - 1) * (0.65 / result.layers)) / (0.55 / result.layers));
      const columns = i === 0 ? 1 : result.attempts ** Math.ceil(i / 2);
      const rows = Math.ceil(nestedCount / columns);
      const cell = Math.min(21, 110 / Math.max(columns, rows));
      const gap = cell * 0.14;
      const stride = cell + gap;
      const halfX = columns * stride / 2, halfY = rows * stride / 2;
      const camera = { cx: x, cy: 225, yaw: Math.PI / 4, elevation: Math.PI / 6, scale: 1 };
      const ink = i === 0 ? palette.ink : (isOwner ? palette.mint : palette.blue);
      const dim = i === 0 ? 1 : lerp(0.12, 1, reveal);
      const floor = [[-halfX - 7, -halfY - 7, -7], [halfX + 7, -halfY - 7, -7],
        [halfX + 7, halfY + 7, -7], [-halfX - 7, halfY + 7, -7]].map(p => M.project(p, camera));
      pieces.push(`<g data-boundary="${i}" opacity="${number(dim)}">`);
      pieces.push(`<path d="${M.roundedPolygon(floor, 5)}" fill="none" stroke="${palette.rule}" stroke-width="1" stroke-dasharray="3 5"/>`);
      const tileCamera = { ...camera, cx: 0, cy: 0 };
      const faces = M.boxFaces([0, 0, 0], [cell, cell, 5], tileCamera);
      pieces.push(`<defs><g id="retry-tile-${i}" stroke="currentColor" stroke-width="${nestedCount > 100 ? 0.65 : 0.9}" stroke-linejoin="round">`);
      for (const face of faces) pieces.push(`<path d="${M.roundedPolygon(face.points, 1.1)}" fill="${face.kind === "top" ? palette.face : palette.side}"/>`);
      pieces.push(`</g></defs>`);
      const cells = Array.from({ length: nestedCount }, (_, index) => {
        const col = index % columns, row = Math.floor(index / columns);
        return { index, col, row, z: col + row };
      }).sort((a, b) => a.z - b.z || a.index - b.index);
      for (const tile of cells) {
        const stays = tile.index < ownerCount;
        const tileProgress = smooth((reveal * 1.28 - tile.index / Math.max(1, nestedCount) * 0.28) / 0.92);
        const fade = (stays ? 1 : 1 - ownerMix) * (i === 0 ? 1 : lerp(0.06, 1, tileProgress));
        const baseX = (tile.col + 0.5) * stride - halfX;
        const baseY = (tile.row + 0.5) * stride - halfY;
        const finalX = (tile.index - (ownerCount - 1) / 2) * (cell + gap);
        const position = M.project([
          stays ? lerp(baseX, finalX, ownerMix) : baseX,
          stays ? lerp(baseY, 0, ownerMix) : baseY,
          (1 - tileProgress) * 18 + (stays ? ownerMix * 9 : 0),
        ], camera);
        pieces.push(`<use href="#retry-tile-${i}" transform="translate(${number(position[0])} ${number(position[1])})" color="${ink}" opacity="${number(fade)}" data-attempt="${tile.index + 1}"/>`);
      }
      const count = isOwner ? ownerCount : nestedCount;
      pieces.push(`<text x="${number(x)}" y="112" fill="${palette.muted}" text-anchor="middle" font-family="system-ui, sans-serif" font-size="14">${i === 0 ? "Input" : isLast ? "Backend" : `After layer ${i}`}</text>`);
      pieces.push(`<text x="${number(x)}" y="325" fill="${ink}" text-anchor="middle" font-family="Georgia, serif" font-size="${isLast ? 54 : 40}">${count}</text>`);
      pieces.push(`<text x="${number(x)}" y="352" fill="${palette.muted}" text-anchor="middle" font-family="system-ui, sans-serif" font-size="13">${count === 1 ? "attempt" : "attempts"}</text>`);
      if (i > 0) {
        const previous = positions[i - 1], middle = (previous + x) / 2;
        const factor = isOwner && i > 1 ? 1 : result.attempts;
        const focus = i === activeBoundary && ownerMix < 0.5;
        pieces.push(`<path d="M ${number(previous + 31)} 159 L ${number(x - 32)} 159" stroke="${focus ? palette.gold : palette.rule}" stroke-width="${focus ? 1.7 : 1.1}" marker-end="url(#retry-arrow)" fill="none"/>`);
        pieces.push(`<text x="${number(middle)}" y="141" text-anchor="middle" fill="${factor === 1 ? palette.mint : palette.gold}" font-family="Georgia, serif" font-size="26">×${factor}</text>`);
      }
      pieces.push(`</g>`);
    }
    pieces.push(`<path d="M38 389 H922" stroke="${palette.rule}" stroke-width="0.7"/>`);
    pieces.push(`<text x="38" y="419" fill="${palette.muted}" font-family="system-ui, sans-serif" font-size="13">Each tile = one cumulative downstream attempt.</text>`);
    pieces.push(`<text x="922" y="419" text-anchor="end" fill="${palette.muted}" font-family="system-ui, sans-serif" font-size="13">Spatial arrangement does not represent time or concurrency.</text></svg>`);
    return pieces.join("");
  }

  const mounted = new WeakMap();
  function mount(root) {
    if (!root || !root.querySelector) throw new TypeError("Expected an observatory element.");
    const document = root.ownerDocument, view = document.defaultView;
    const select = name => root.querySelector(`[data-retry-${name}]`);
    const required = ["drawing", "timeline", "attempts", "layers", "play", "next", "previous",
      "reset", "theme", "export", "drawing-region", "formula", "comparison", "counts"];
    if (required.some(name => !select(name))) throw new Error("Incomplete observatory markup.");
    if (mounted.has(root)) mounted.get(root).destroy();
    const drawing = select("drawing"), timeline = select("timeline");
    const attempts = select("attempts"), layers = select("layers");
    let state = options(), destroyed = false, playing = false, frame = 0, last = 0;
    let printing = false, printTheme = state.theme, onScreen = true, printDetails = [];
    let firstPlay = true, observer, blobUrl = null;
    const cleanups = [], reduced = view.matchMedia("(prefers-reduced-motion: reduce)");
    const duration = 26;
    function listen(target, type, handler, settings) {
      target.addEventListener(type, handler, settings);
      cleanups.push(() => target.removeEventListener(type, handler, settings));
    }
    function motionInstructions() {
      select("drawing-region").setAttribute("aria-label",
        "Attempt map. Scroll horizontally on small screens. " +
        (reduced.matches ? "Space advances to the next idea; " : "Space plays or pauses; ") +
        "Home and End seek.");
    }
    function pause() {
      playing = false; last = 0;
      if (frame) view.cancelAnimationFrame(frame);
      frame = 0;
      const play = select("play");
      play.textContent = reduced.matches ? "Next idea" : "Play the explanation";
      play.setAttribute("aria-pressed", "false");
      motionInstructions();
    }
    function text(name, value) { const node = select(name); if (node) node.textContent = String(value); }
    function update(announce = true) {
      if (destroyed) return;
      const result = model(state), copy = explanation(state), owner = chapter(state.progress) === 3;
      drawing.innerHTML = renderSVG(state); // only our escaped, bounded renderer; never source markup
      root.dataset.theme = state.theme;
      motionInstructions();
      timeline.value = String(Math.round(state.progress * 1000));
      timeline.setAttribute("aria-valuetext", `${Math.round(state.progress * 100)} percent; ${copy.title}`);
      attempts.value = String(state.attempts); layers.value = String(state.layers);
      text("attempt-value", `${state.attempts} total`);
      text("layer-value", state.layers);
      text("headline", copy.title); text("copy", copy.text);
      const formula = select("formula");
      formula.replaceChildren();
      formula.setAttribute("aria-label", copy.formula.replace(/\^(\d+)/g, " to the power $1").replace(/×/g, " times ").replace(/=/g, " equals "));
      for (const part of copy.formula.split(/(\^\d+)/)) {
        if (/^\^\d+$/.test(part)) {
          const sup = document.createElement("sup"); sup.textContent = part.slice(1); formula.append(sup);
        } else {
          const span = document.createElement("span"); span.textContent = part; formula.append(span);
        }
      }
      text("nested-total", result.nestedBackend); text("owner-total", result.ownerBackend);
      text("difference", result.repeated === 0 ? "No amplification in this setting."
        : `${result.repeated} fewer backend attempts in this model.`);
      select("comparison").dataset.active = owner ? "owner" : "nested";
      const table = select("counts");
      table.replaceChildren();
      for (let i = 0; i < state.layers; i++) {
        const row = document.createElement("tr");
        for (const value of [`${i + 1}${i === state.layers - 1 ? " — backend" : ""}`, result.nested[i], result.owner[i]]) {
          const cell = document.createElement(row.children.length === 0 ? "th" : "td");
          if (row.children.length === 0) cell.scope = "row";
          cell.textContent = String(value); row.append(cell);
        }
        table.append(row);
      }
      for (const button of root.querySelectorAll("[data-retry-chapter]")) {
        const selected = Number(button.dataset.retryChapter) === copy.index;
        button.setAttribute("aria-current", selected ? "step" : "false");
      }
      const next = select("next"), previous = select("previous");
      next.disabled = state.progress >= 1; previous.disabled = state.progress <= 0;
      text("position", `${Math.round(state.progress * duration)} / ${duration} s`);
      const theme = select("theme");
      theme.textContent = state.theme === "dark" ? "Light canvas" : "Dark canvas";
      theme.setAttribute("aria-pressed", state.theme === "light" ? "true" : "false");
      if (announce) text("status", `${copy.title} Nested: ${result.nestedBackend}. One owner: ${result.ownerBackend}.`);
    }
    function set(patch, announce = true) {
      if (destroyed) return;
      const next = options({ ...state, ...patch });
      pause(); state = next; firstPlay = false; update(announce);
    }
    function advance(direction) {
      if (direction > 0) set({ progress: STOPS.find(stop => stop > state.progress + 0.008) ?? 1 });
      else set({ progress: [...STOPS, 0].sort((a, b) => b - a).find(stop => stop < state.progress - 0.008) ?? 0 });
    }
    function tick(timestamp) {
      frame = 0;
      if (destroyed || !playing || printing || reduced.matches || document.hidden || !onScreen) { pause(); return; }
      const delta = last ? Math.min((timestamp - last) / 1000, 0.08) : 0;
      if (last && delta < 1 / 32) { frame = view.requestAnimationFrame(tick); return; }
      last = timestamp;
      state = options({ ...state, progress: Math.min(1, state.progress + delta / duration) });
      update(false);
      if (state.progress >= 1) { pause(); update(true); }
      else frame = view.requestAnimationFrame(tick);
    }
    function togglePlay() {
      if (reduced.matches) { advance(1); return; }
      if (playing) { pause(); return; }
      if (state.progress >= 0.99 || firstPlay) state = options({ ...state, progress: 0 });
      firstPlay = false;
      update(false); // The visible/exported state agrees even if paused before the first frame.
      playing = true; last = 0;
      select("play").textContent = "Pause";
      select("play").setAttribute("aria-pressed", "true");
      frame = view.requestAnimationFrame(tick);
    }
    function restorePrint() {
      if (!printing) return;
      for (const { node, open } of printDetails) node.open = open;
      printDetails = []; printing = false;
      state = options({ ...state, theme: printTheme }); update(false);
    }
    try {
    listen(select("play"), "click", togglePlay);
    listen(timeline, "input", () => set({ progress: Number(timeline.value) / 1000 }));
    listen(attempts, "input", () => set({ attempts: Number(attempts.value) }));
    listen(layers, "input", () => set({ layers: Number(layers.value) }));
    listen(select("next"), "click", () => advance(1));
    listen(select("previous"), "click", () => advance(-1));
    listen(select("reset"), "click", () => {
      set({ attempts: 3, layers: 4, progress: 0.72 }); firstPlay = true;
    });
    listen(select("theme"), "click", () => set({ theme: state.theme === "dark" ? "light" : "dark" }));
    for (const button of root.querySelectorAll("[data-retry-chapter]")) {
      listen(button, "click", () => set({ progress: STOPS[Number(button.dataset.retryChapter)] }));
    }
    listen(select("drawing-region"), "keydown", event => {
      if (event.key === " " || event.key === "Enter") { event.preventDefault(); togglePlay(); }
      else if (event.key === "Home") { event.preventDefault(); set({ progress: 0 }); }
      else if (event.key === "End") { event.preventDefault(); set({ progress: 1 }); }
      else if (event.key === "Escape") { event.preventDefault(); pause(); }
    });
    listen(select("export"), "click", () => {
      pause();
      if (blobUrl) view.URL.revokeObjectURL(blobUrl);
      blobUrl = view.URL.createObjectURL(new view.Blob([renderSVG(state)], { type: "image/svg+xml;charset=utf-8" }));
      const link = document.createElement("a");
      link.href = blobUrl; link.download = `ste-retry-${state.attempts}-attempts-${state.layers}-layers.svg`;
      root.append(link); link.click(); link.remove();
      text("status", "Saved the current static SVG, including model assumptions.");
    });
    listen(reduced, "change", () => { pause(); update(); });
    listen(document, "visibilitychange", () => { if (document.hidden) pause(); });
    listen(view, "beforeprint", () => {
      pause();
      if (!printing) {
        printTheme = state.theme;
        printDetails = [...root.querySelectorAll("details")].map(node => ({ node, open: node.open }));
      }
      printing = true;
      for (const { node } of printDetails) node.open = true;
      state = options({ ...state, theme: "light" }); update(false);
    });
    listen(view, "afterprint", () => {
      pause(); restorePrint();
    });
    if (view.IntersectionObserver) {
      observer = new view.IntersectionObserver(entries => {
        onScreen = Boolean(entries[0]?.isIntersecting);
        if (!onScreen) pause();
      });
      observer.observe(root);
    }
    const api = {
      get state() { return { ...state, playing, reducedMotion: reduced.matches }; },
      set,
      toSVG: () => renderSVG(state),
      destroy() {
        if (destroyed) return;
        pause(); restorePrint(); destroyed = true; observer?.disconnect();
        for (const cleanup of cleanups) cleanup();
        if (blobUrl) view.URL.revokeObjectURL(blobUrl);
        for (const control of root.querySelectorAll("[data-retry-controls] button,[data-retry-controls] input")) control.disabled = true;
        mounted.delete(root);
      },
    };
    for (const control of root.querySelectorAll("[data-retry-controls] button,[data-retry-controls] input")) control.disabled = false;
    mounted.set(root, api);
    pause(); update(false);
    return api;
    } catch (error) {
      pause(); restorePrint(); destroyed = true; observer?.disconnect();
      for (const cleanup of cleanups) cleanup();
      if (blobUrl) view.URL.revokeObjectURL(blobUrl);
      mounted.delete(root);
      throw error;
    }
  }
  return Object.freeze({ model, options, validateSource, chapter, explanation, renderSVG, mount, STOPS });
});
