# Line Studio implementation plan

Status: development branch, October 4, 2026. Not a published release.

## Outcome

Add original interactive isometric SVG authoring to STE-Pro Max. Show a complete,
carefully paced explanation before a catalogue of components. The flagship
**Retry Observatory** explains why nested retry budgets multiply, using the
existing `retry-storm.json` source and its persistent-failure assumptions.

## Scope and boundaries

- Fourth native skill, `ste-line-studio`, with offline HTML/SVG starters.
- Original projection, rounded geometry, springs and transitions; six reusable
  interaction patterns: stack, field, layers, signal, orbit and flow.
- A reader-controlled flagship with a seekable timeline, exact attempt counts,
  variable budgets/depth, a single-owner comparison, and source disclosure.
- Keyboard/touch equivalents, reduced motion, pause/reset, print/no-JS reading,
  safe static SVG export and complete runtime teardown.
- No new dependencies, wrapper, React requirement, Python bootstrap, network,
  copied code/illustrations, or automatic publishing. Existing Python renderers
  remain separate optional capabilities, not prerequisites.
- Public `v0.4.0` installation remains the stable release; describe this feature
  as development-only until a separate release is requested.

Hairline's public behavior informed the brief. Research inspected its
MIT-licensed source at `c3692e0c797956268847d843949f79714b6f7a41`; no
upstream code, templates, artwork or instructions are incorporated.

## Work and verification

1. Preserve primary-checkout changes and import hashes; use an isolated worktree.
   Existing package tests passed before implementation.
2. Build original geometry/motion and unit tests in a bounded executor lane.
3. Implement the six-pattern runtime independently in a second lane.
4. Author the narrow skill/reference documentation in a third lane.
5. Build Retry Observatory locally: clear visual intuition, meaningful motion,
   editable source, exact arithmetic, and a composed still at every chapter.
6. Integrate assets, package rules and short documentation links. Keep a single
   runtime source and inline it into the generated standalone HTML.
7. Run regression tests, Node tests, lint/type checks, real-browser interaction,
   offline, export, print, mobile, reduced-motion and lifecycle checks. Inspect
   screenshots and the actual packaged copy; review independently.
8. Open the working example for the user. Report measured checks and remaining
   gaps without claiming external accessibility certification or release.

## Stop condition

The new feature and flagship are useful from the packaged plugin, validation
has fresh evidence, the example has been opened, and the original dirty checkout
and immutable imports remain intact. No tag, public deployment or release is
created by this implementation task.
