# Line Studio: reference and implementation boundary

The user requested an original implementation inspired by
[Hairline](https://github.com/lucasmarkes/hairline), followed by a worked visual
explanation with the care and pedagogical clarity of a mathematical explainer.
Research inspected Hairline's default branch at
[`c3692e0c797956268847d843949f79714b6f7a41`](https://github.com/lucasmarkes/hairline/tree/c3692e0c797956268847d843949f79714b6f7a41)
on October 4, 2026. It was not installed or executed.

## Relevant behavior

The reference combines an SVG illustration library with an agent-authoring
workflow. Its geometry uses orthographic projection and opaque painter-ordered
faces. Interactions use stable input planes, bounded responses, springs or
transitions, and reduced-motion handling. A standalone HTML can contain the
rendering code and the figure. These are useful product ideas, not a reason to
add a framework or repackage its implementation.

Primary reference files at that revision:

- [`README.md`](https://github.com/lucasmarkes/hairline/blob/c3692e0c797956268847d843949f79714b6f7a41/README.md)
- [`skills/hairline-create/SKILL.md`](https://github.com/lucasmarkes/hairline/blob/c3692e0c797956268847d843949f79714b6f7a41/skills/hairline-create/SKILL.md)
- [`src/core/iso.ts`](https://github.com/lucasmarkes/hairline/blob/c3692e0c797956268847d843949f79714b6f7a41/packages/hairline/src/core/iso.ts)
- [`src/core/stage.ts`](https://github.com/lucasmarkes/hairline/blob/c3692e0c797956268847d843949f79714b6f7a41/packages/hairline/src/core/stage.ts)
- [`LICENSE`](https://github.com/lucasmarkes/hairline/blob/c3692e0c797956268847d843949f79714b6f7a41/LICENSE)

## STE's own feature

Line Studio has original JavaScript, artwork, copy, templates and tests. It
does not import Hairline or copy its kernel, figure catalogue, naming/API,
React adapters, or authoring files. This is source-informed independent
implementation, not a claimed clean-room process, endorsement, or full parity.

The differences are deliberate:

- Six bounded patterns rather than nineteen copied illustrations.
- Equivalent keyboard and native controls, not pointer-only authoring output.
- Static SVG export includes full descriptions even when visible labels shorten.
- No automatic browser/package installation, telemetry, or runtime network.
- One real source-backed mathematical example before a component catalogue.
- Developer Node tools rebuild the examples; opening or adapting the bundled
  HTML/SVG requires no Node or Python installation.

The retry math comes from STE's pre-existing
[`retry-storm.json`](../../examples/showcase/sources/retry-storm.json).
Isometric tiles are an original representation of that illustrative model.
Motion illustrates explanatory progression, not elapsed request time.
