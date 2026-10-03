---
name: ste-storytelling
description: "Author evidence-linked explanations, decision briefs, research digests, and incident reviews with the STE-Pro Max native story engine. Use for reader-controlled beats and consistent prose, visual, storyboard, and draft-narration companions; not for a short prose rewrite or automatic video export."
---

# STE storytelling

Use one reviewed story source and the bundle's native engine. A story is a way
to organize evidence, not a reason to invent a dramatic arc or stronger conclusion.

## Author the source

Read [Authoring](../../docs/AUTHORING.md) for the exact shapes, examples, and
review gaps. Apply [STE-ProMAX](../ste-promax/SKILL.md) writing priorities:
fidelity, requested scope/format, clarity, then style.

Choose the audience, one question, and a purpose:

| Purpose | Useful structure, not a mandatory plot |
| --- | --- |
| `explanation` | Concrete example, intermediate states, mechanism, understanding check |
| `decision-brief` | Decision question, evidence, options/proposal, unresolved conditions |
| `research-digest` | Research question, attributed findings, methods/limits, qualified implications |
| `incident-review` | Observed order, impact, hypotheses, proposed corrections; no invented closure |

Register sources with stable IDs and precise locators. Classify claims as
`observation`, `attribution`, `inference`, or `proposal`. Attribution names its
speaker; inference states its basis. Link claims to sources and beats to claims.
Source registration and reference validation do not establish truth, entailment,
causation, approval, or authenticity.

Keep material uncertainty in the claim and story, not only in a final chat note.
Review unlinked summary/beat prose and custom narration as carefully as linked
claims. A valid ledger cannot prevent an author from adding unsupported prose.
Unused claims remain reviewable; do not hide contrary evidence through beat
selection, ordering, captions, or emphasis.

Use optional native diagrams/charts only where they explain the beat. Read
[ste-visual-docs](../ste-visual-docs/SKILL.md) for visual-specific constraints.
Sequence order is not duration; categorical line spacing is not elapsed time.

Let readers choose guided progress or all content. Add a question when it tests
a specific likely misunderstanding. Supply a supported answer or leave it open;
do not invent feedback or call a click evidence of learning.

## Run from the user's workspace

Resolve this loaded skill's absolute path and walk upward to the nearest
directory containing both `ste_promax/` and root `__main__.py`. Use that bundle
root rather than the host's current directory or a global installation.

```text
python "<bundle-root>" --help
python "<bundle-root>" schema story
python "<bundle-root>" render "<absolute-story.json>" --output-dir "<absolute-new-output-dir>"
```

Replace angle-bracket paths with resolved paths. Keep source and output in the
user's workspace, with a fresh output directory under `artifacts/`, not in the
bundle cache. From the repository root, `python -m ste_promax` reaches the same
engine. If help lacks a command, report the bundle gap; do not invent a wrapper.

Inspect the HTML/design/metadata triple, gallery, manifest, saved source, and
normalized input. Review all four story companions: `story.md`, `storyboard.json`,
`narration.json`, and `evidence.json`. Draft narration is not approved speech,
and a complete manifest is not a semantic review.

## Prepare narration only when requested

Review the script before generating or pairing audio. Run `narrate` with the
original story JSON in a different fresh output directory. Select one route:

```text
python "<bundle-root>" narrate "<absolute-story.json>" --output-dir "<absolute-new-media-dir>" --voice "<installed-voice-name>"
python "<bundle-root>" narrate "<absolute-story.json>" --output-dir "<absolute-new-media-dir>" --audio-dir "<absolute-audio-dir>"
```

The supplied-audio directory contains `<beat-id>.wav` for every beat. Inspect
actual non-silent PCM audio and measured duration; listen and compare the speech
with the reviewed script, visual order, and qualifications. Do not silently
install a voice or move private text to a service.

Split content that fails the media fit checks without removing qualifications.
Inspect long-caption warnings. Sequence-stage pacing is not measured event time
or verified speech-to-message alignment.

Preparation does **not** export an MP4. If an encoded video is requested, use a
separately available export workflow and verify the actual movie. Report missing
capabilities or unperformed checks instead of calling a preview an export.

## Delivery gate

Compare all formats with the same evidence ledger. Exercise Previous/Next,
outline links, all-content mode, answer disclosure, keyboard use, narrow layout,
no-JavaScript reading, and print output. Record any untested surface.

Return the requested artifact with material source/review gaps. Stop at the
requested medium; successful rendering does not demonstrate learning,
accessibility conformance, publication, or a completed decision.
