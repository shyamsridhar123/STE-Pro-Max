# STE Line Studio

**Included in STE-Pro Max v0.5.0.**

Line Studio adds original line-art SVG figures and reader-controlled explanations
as a fourth native STE skill for Copilot CLI, Claude Code, and Codex. The aim is
to help a reader see a mechanism, inspect its parts, and test an idea—not just
watch a polished animation.

Use the [v0.5.0 installation guide](PLUGINS.md) to get all four skills.
[Recorded checks](VALIDATION.md#line-studio-development-050) cover the original
implementation; release-specific checks are attached to the
[release](https://github.com/shyamsridhar123/STE-Pro-Max/releases/tag/v0.5.0).
They are not a universal compatibility claim.

## Start with a complete explanation

[Retry Observatory](../examples/showcase/retry-observatory.html) is the flagship:
one original request, nested retry budgets, and a comparison with one retry
owner. Its [editable source](../examples/showcase/sources/retry-storm.json)
keeps the definitions and limitations inspectable.

The intended reading experience starts small: follow one attempt budget, see
why a downstream budget repeats, predict the next boundary count, then compare
the two policies. Chapters and a scrubber should make the mechanism inspectable
at the reader's pace. Movement connects ideas; it is not the explanation itself.

### Why 81 versus 3?

In this illustrative model, `A` is the **total attempts per incoming call at
each retrying layer**, including the initial attempt. `L` is the number of
nested serial layers before the backend.

The backend fails persistently. Every layer exhausts its budget, and each
upstream retry starts fresh downstream budgets. With retries at every layer,
the backend receives `A^L` attempts. With one retry owner and other layers
forwarding once, it receives `A`, not `A*L`.

| Default: `A = 3`, `L = 4` | Layer 1 boundary | Layer 2 | Layer 3 | Backend |
| --- | ---: | ---: | ---: | ---: |
| Nested retry budgets | 3 | 9 | 27 | **81** |
| One retry owner | 3 | 3 | 3 | **3** |

Each mark is a cumulative attempt, not a simultaneous request. Backend attempts
are the final boundary count, not the sum of every boundary. The model excludes
shared budgets, early exits, deadlines, cancellation, caching, circuit breakers,
and deduplication. It makes no timing, concurrency, throughput, success-rate,
production-performance, or resilience claim. It is not production telemetry or
a policy recommendation.

## Make your own figure

After installing the plugin, ask:

> Use STE Line Studio to explain this mechanism. Start with a concrete example,
> let me inspect the meaningful changes, and keep the source limitations visible.

Or request a still:

> Make an original SVG showing these responsibilities. Keep it static and retain
> the qualifications in my notes.

The host reads and adapts self-contained HTML/SVG with its own file and browser
tools. Ordinary authoring needs **no Python, npm, React, third-party runtime
installation, server, or provider key**. Outputs go into a new workspace
`artifacts/` subdirectory, with preserved source material. Installed templates
and the original source are not overwritten.

The [six-pattern starter](../examples/showcase/line-studio.html) provides `stack`,
`field`, `layers`, `signal`, `orbit`, and `flow` arrangements. These are reusable
building blocks, not a requirement to fit every explanation into a preset demo.
The host can adapt the original projection and SVG primitives for a custom
figure. There is no Hairline API or React parity promise, and the figures are
not copies of upstream illustrations.

Preserve the requested medium. A short prose answer need not become interactive;
a static SVG need not become a video.

## Reader control and honest delivery

Authored explanations should provide stable hit targets, keyboard/touch-equivalent
controls, visible focus, reduced motion, and pause/scrubbing where playback is
used. Static/no-JS and print reading should retain the explanation and source
qualifications. Source-provided markup stays inert; artifacts make no external
requests.

SVG export is a **static current-state figure**, not a video or animated export.
Check the saved file, not only the export button.

Ask for the actual artifact and checks performed. Source review, structural
validation, browser behavior, and accessibility checks are different forms of
evidence. None is implied by this guide, and none establishes learning outcomes.

## Author and developer references

- [Skill entrypoint](../skills/ste-line-studio/SKILL.md)
- [Authoring, runtime API, pacing, and verification](../skills/ste-line-studio/references/authoring.md)
- [Original math primitives](../ste_promax/assets/line-math.js)
- [SVG and interaction runtime](../ste_promax/assets/line-studio.js)
- [Developer-only example builder](../tools/build_line_studio.mjs)
- [Plugin installation and update guide](PLUGINS.md)

The example builder is for maintainers rebuilding standalone examples, not a
setup requirement for readers or ordinary authoring.
