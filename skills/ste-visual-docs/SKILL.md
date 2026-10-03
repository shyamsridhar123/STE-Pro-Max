---
name: ste-visual-docs
description: "Create source-grounded technical visual documents with the STE-Pro Max native flow/sequence diagrams and bar/line charts. Use for relationships, message order, or quantitative explanations with readable text/data equivalents; not for decorative artwork or a prose-only rewrite."
---

# STE visual documentation

Produce a focused explanation from reviewed facts, using this bundle's native
engine. Do not require a separately installed PaperBoard CLI, new dependencies,
a wrapper, or a hosted service.

## Choose and ground the visual

Identify the reader, the question, and what the source actually establishes.
Use a flow for relationships, a sequence for message order, and a bar/line chart
for quantities. Keep the user's requested format; do not build an application
where a diagram and short explanation suffice.

Read [Authoring](../../docs/AUTHORING.md) for shapes and examples, and
[STE-ProMAX](../ste-promax/SKILL.md) for writing rules when revising prose.
For multiple evidence-linked beats, use
[ste-storytelling](../ste-storytelling/SKILL.md), not a second rendering engine.

- Keep units, baselines, populations, dates, and uncertainty attached to the data.
  Label illustrative or simulated material. Never fill an evidence gap with an
  invented relationship, measurement, benefit, or causal arrow.
- Sequence spacing means order, not duration. Chart categories are equally
  spaced, not a continuous time scale. State these limits when timing matters.
- Represent missing values with `null`, not zero. Supply uncertainty bounds only
  from the source; explain what they measure. Do not compute an interval or
  confidence level merely because the renderer supports one.
- Label the visual meaningfully and inspect its complete text/data equivalent.
  Color or dashed styling alone must not carry a qualification.
- Review framing: selection, exclusions, ordering, axis limits, labels, and
  annotations can change the apparent conclusion. Disclose material choices.

## Use the same native engine

Resolve the absolute path of this loaded `SKILL.md`. Walk upward to the nearest
directory containing both `ste_promax/` and root `__main__.py`; that is the bundle
root. Do not derive it from the current working directory or assume global
installation. From the user's workspace, inspect:

```text
python "<bundle-root>" --help
python "<bundle-root>" schema diagram
python "<bundle-root>" schema chart
```

Angle-bracket paths are substitutions, not literal filenames. Put reviewed
source JSON in the user's workspace and invoke:

```text
python "<bundle-root>" render "<absolute-source.json>" --output-dir "<absolute-new-output-dir>"
```

Choose a fresh subdirectory of the user's `artifacts/`, never the plugin cache.
The repository-root equivalent is `python -m ste_promax`. Author structured
`sections` with `kind: diagram` or `kind: chart`; consult `schema` for an existing
section kind rather than guessing fields. For a single visual, use the same
object at the root with an explicit `kind`. Structured visuals do not require
`--trusted-html`.

If the selected bundle lacks a command or rejects the shape, report the exact
gap. Do not edit runtime code, silently use another engine, or claim support from
instructions alone.

## Inspect before delivery

1. Read `manifest.json`, its warnings, and the generated HTML/design/metadata
   triple and gallery. Compare saved source bytes and normalized input with the
   authored JSON; inspect the actual rendered labels and text/data equivalent.
2. Check every node, edge, message, category, value, interval, and qualification.
   A valid reference or number is not proof that the source supports the claim.
3. Exercise desktop and narrow-width output, keyboard access to scroll regions,
   noncolor distinctions, and readable long labels. Record browser or assistive
   technology checks not performed; do not infer them from static markup.
4. Return the artifact and material gaps. Separate successful rendering, design
   lint, factual review, accessibility checks, and any learning evaluation.

Stop when the requested visual is source-faithful and the checks are recorded,
or report the specific blocker. Do not install globally or publish by default.
