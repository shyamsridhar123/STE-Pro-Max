# Authoring original line-art explanations

Authoring reference for v0.5.0. Check runtime contracts and examples against the
files in the loaded bundle; this document is not a compatibility certificate.

## Choose a visual argument

Start with what the reader should understand, not a pattern name. Map every mark,
group, connection, and control to a source-supported meaning. If height, spacing,
color, or motion is decorative rather than quantitative, say so where ambiguity
would change the interpretation.

The six `kind` values offer starting arrangements:

| Kind | Possible explanatory use, not an imposed meaning |
| --- | --- |
| `stack` | Inspect parts of a grouped structure |
| `field` | Compare many elements under one condition |
| `layers` | Separate levels or nested responsibilities |
| `signal` | Trace a change or distinguish stages |
| `orbit` | Explore relationships around a focal element |
| `flow` | Follow a route or ordered handoff |

A signal is not automatically measured telemetry. An orbit is not a physical
simulation. A flow does not establish elapsed time, causality, or concurrency.
Write labels and qualifications that make the chosen meaning explicit.

Compose or adapt primitives when no pattern fits. Keep original geometry and
explanatory framing; do not reproduce upstream figures or promise compatibility
with Hairline or React. Avoid adding interaction when a labeled still is clearer.

## Purposeful pacing

Build understanding through a concrete trace before revealing a general formula.
Show the initial condition, change one meaningful thing, and hold the consequence
long enough to inspect it. Keep the caption and affected marks in agreement.
Preserve visual identity across steps so the reader can follow the same object.

Offer reader-controlled chapters or steps. If adding playback, start paused,
provide pause and a labeled scrubber, and make seeking reproduce the selected
state without waiting for earlier animation. Playback speed is presentation
pacing, not modeled time. Reduced motion should preserve the explanation using
direct state changes. Do not use perpetual movement to make a static claim feel
more convincing.

For a 3Blue1Brown-quality brief, pursue clarity of intuition: a small example,
an inspectable mechanism, a revealing comparison, and a useful generalization.
Do not treat that request as permission to copy visual compositions or to assert
equivalent teaching effectiveness.

## Files and ordinary authoring

Paths below are relative to the plugin/repository root:

| File | Role |
| --- | --- |
| `ste_promax/assets/line-math.js` | Original geometry and motion primitives, `STELineMath` |
| `ste_promax/assets/line-studio.js` | SVG rendering and mounted interactions, `STELineStudio` |
| `examples/showcase/line-studio.html` | Self-contained six-pattern starter |
| `examples/showcase/retry-observatory.html` | Self-contained flagship explanation |
| `examples/showcase/sources/retry-storm.json` | Editable illustrative model and qualifications |
| `tools/build_line_studio.mjs` | Developer-only example builder |

Read and adapt the standalone HTML with the host's file tools. Keep output in a
new workspace `artifacts/` directory, alongside source material and its normalized
copy. Never write to installed assets or reuse a previous artifact directory
without permission to replace its contents.

The ordinary authoring path does not invoke the builder or require Python, npm,
React, a package install, a server, or third-party runtime downloads. When composing
from runtime assets rather than a standalone starter, inline the reviewed math
runtime before the studio runtime. Keep their license notices.

Use trusted template code with source content inserted as text or escaped data.
Never concatenate source-supplied markup into HTML, execute embedded scripts, or
evaluate a formula supplied by a document. If embedding JSON in an HTML script
element, escape `<` so source text cannot terminate that element. Keep the
unmodified source separately; escape only the embedded representation.

Do not load fonts, scripts, telemetry, images, or data from remote URLs. Source
citations may remain readable references without fetching them on page load.

## Runtime API

`STELineStudio` is a browser-global API, not a React component library.
Its author-facing options are:

```js
const options = {
  kind: "layers", // stack | field | layers | signal | orbit | flow
  title: "Where does the responsibility sit?",
  summary: "An illustrative structure, not measured timing.",
  items: [
    { label: "Caller", detail: "Starts the request." },
    { label: "Service", detail: "Handles the downstream call." }
  ],
  intensity: 0.5, // 0..1; visual parameter, not a source metric
  theme: "system" // light | dark | system
};
```

`title`, `summary`, `label`, and `detail` are text, not markup. Supply reviewed
finite numeric inputs; do not rely on runtime coercion to repair bad source data.
The options describe the figure, not an evidence ledger or the retry arithmetic.
Keep source qualifications and any richer model alongside them.

| Entry point | Purpose |
| --- | --- |
| `STELineStudio.renderSVG(options)` | Produce a static SVG representation |
| `STELineStudio.mount(host, options)` | Mount an interactive figure in a dedicated DOM host |
| Returned `update` | Change figure options |
| Returned `select` | Select a figure item |
| Returned `reset` | Reset the mounted figure |
| Returned `toSVG` | Export a static SVG of the current figure state |
| Returned `destroy` | Tear down the mounted instance |

Inspect the current runtime and starter for method arguments, selection semantics,
and reset behavior before custom integration; do not invent extra option fields
or callbacks. Call `destroy()` before replacing an instance. Keep the readable
fallback outside the dedicated mount host so mounting cannot erase it.

An SVG string is not a downloaded file until it has been saved. Inspect the
saved SVG independently: labels, bounds, theme contrast, and current-state
selection must survive without scripts. Export does not capture playback or
encode video. Custom authored figures need their own checked static export path.

### Geometry for custom figures

Read `line-math.js` before changing geometry. Its primitives include:

- `project(point, camera)` and `unprojectOnPlane(point, z, camera)` for
  three-coordinate points and two-coordinate projected points. The inverse
  needs a specified plane; it cannot recover arbitrary depth from a screen point.
- `depth(point, camera)` for back-to-front ordering; sort ascending.
- `boxFaces(center, size, camera)` for projected top/side faces; this is
  pseudo-3D geometry, not a general solid renderer.
- `roundedPolygon(points, radius)` for an SVG path. Radius is corner cut-back
  distance, not a circular arc radius.
- `convexHull(points)` for a projected outline.
- `stepSpring(state, target, dt, options)` for presentation motion, with
  `{value, velocity}` state; `ease(t)` and `clamp(number, min, max)` for bounded
  interpolation.

Camera fields are `yaw`, `elevation`, `scale`, `cx`, and `cy`. Supply finite
values, use radians for angles, and keep scale positive. Projection does not
assign domain meaning to height or distance. Spring parameters describe visual
settling, not backend latency or a physical claim.

## Retry Observatory: the explanatory contract

Use the [editable model](../../../examples/showcase/sources/retry-storm.json)
as the authority for the example, not an observed incident:

- One original request passes through `L` nested, serial retrying layers.
- `A` means **total attempts per incoming call**, including the initial attempt;
  there are `A - 1` retries.
- The backend fails persistently. Every layer exhausts its budget, failures
  propagate upstream, and each upstream retry starts fresh downstream budgets.
- There are no shared budgets, early exits, deadlines, cancellation, caching,
  circuit breakers, or deduplication in this illustrative model.

Trace one layer's `A` attempts first. Then show that every attempt starts another
whole downstream budget, rather than adding one more call. At boundary `i`, the
cumulative count is `A^i`; the backend is the final boundary, `A^L`. Do not sum
all boundaries and call that the backend count.

For the one-owner comparison, layer 1 retains budget `A`; every other layer
forwards exactly once. Backend attempts are `A`, **not `A*L`**.
At the default `A = 3`, `L = 4`, nested boundary counts are `3, 9, 27, 81`;
one-owner counts are `3, 3, 3, 3`. The comparison is **81 versus 3**.
Let the reader predict a boundary count, reveal its grouping, and then change
`A` or `L` to test the rule.

Check `A = 1` (both counts are 1), `L = 1` (both are `A`), and
`A = 4, L = 4` (256 versus 4). A mark represents a cumulative attempt, not a
simultaneous request. Chapters and scrub positions are explanatory progress,
not measured elapsed time. This model establishes no timing, concurrency,
throughput, success probability, production performance, or resilience benefit.

## Quality and verification

Keep pointer targets stable while geometry moves. Provide native labeled
controls, visible focus, and keyboard/touch equivalents for hover and selection;
do not make thin strokes or drag-only gestures the sole access path. Keep text
details readable independently of the SVG, without relying on color alone.

Author a static initial figure and readable explanation in HTML before
enhancement. A JS-generated fallback cannot serve a no-JS reader. Print should
include the explanation, source qualifications, and useful stills rather than
empty interactive hosts. Test long labels and narrow screens.

Record checks actually performed:

1. Source review and arithmetic, including assumptions and boundary cases.
2. Browser interaction: selection, controls, pause/scrub if present, reset,
   keyboard, touch, resize, and reduced motion.
3. Static/no-JS reading, print, theme contrast, and independently opened SVG.
4. Offline operation with no external requests; source text stays inert.
5. For runtime integration, update/destroy/remount behavior and absence of
   lingering animation or event handlers.

Report unchecked surfaces explicitly. Structural validation is not source
verification, a screenshot is not an interaction test, and browser checks do not
prove accessibility conformance or learning outcomes. Check the installed
version and actual artifact rather than inferring behavior from documentation.
