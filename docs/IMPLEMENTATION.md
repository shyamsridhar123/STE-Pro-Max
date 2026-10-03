# Implementation and acceptance plan

This is the historical foundation plan. The broader active objective and its
completion requirements are tracked in `SUITE_PLAN.md`; meeting this document
alone does not complete the comprehensive-suite goal.

This is a new repository in the existing STE workspace. The original import,
other source checkouts, local memories, and global skills remain unchanged.

| Guideline | Concrete implementation | Acceptance evidence |
| --- | --- | --- |
| Constrained, easier-to-read prose | Working STE-ProMAX skill and advisory checker | Source-fidelity cases; read-only checker tests |
| Relax the style when strict STE hurts clarity | Default relaxed profile, no numeric compliance score | Tests preserve code, numbers, and source input |
| Explain with diagrams or images | Labeled SVG and a shared worked example | Visual inspection and accessible text equivalent |
| Use interactive HTML and animation | Native renderer plus Clarity Lab | Real artifact triple, gallery, browser interactions |
| Topic-specific narrated explanations | Small HyperFrames example, script, transcript, real local TTS | Composition validation, audio verification; export state reported separately |
| ElevenLabs or a local free alternative | Offline Windows System.Speech helper; documented optional provider handoff | Actual synthesis, preservation and error tests |
| Human oversight and understanding | Evidence boundaries and review checkpoints in each output mode | Independent behavioral forward-test |
| Cheap, disposable custom software | One focused local artifact, no server product or new platform | No unrelated-checkout edits or new app dependencies |
| Infographic writing guidance | Qualified, source-linked style checklist | Rule references checked against the standard where available |

## Sequence

1. Confirm the primary post and the native rendering contract.
2. Preserve originals and write a separate project-local skill.
3. Maintain the renderer directly, with regression tests and provenance.
4. Render and exercise real examples; investigate failures rather than hiding them.
5. Review output scope and factual fidelity independently.
6. Commit reviewed source and push the new private repository.

## Updated architecture decision

The user requested a standalone product, not a wrapper.
The native `ste_promax/` package owns rendering, templates, design parsing,
and gallery generation. Remove the experimental installed-CLI wrapper entirely.
Keep only the responsibilities needed for local explanation artifacts; do not copy
unrelated hooks, server lifecycles, global harness installation, or the Node bridge.
Preserve upstream behavior with regression cases before adapting it. Retain the
upstream license and mark modified source files.

## Stop condition

Every prescribed output option has an implemented route and an honest validation
status. Tests pass, source hashes are unchanged, the new remote is private, and the
pushed commit matches the validated local source. Optional external providers are
not claimed to be configured or tested.
