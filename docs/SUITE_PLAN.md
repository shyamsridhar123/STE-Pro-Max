# Comprehensive suite plan and completion audit

## Objective

> implement Karpathy guidelines on ste, visual documentation and story telling.
> Do relevant deep research to make this a comprehensive suite

This is the full active goal. The earlier `IMPLEMENTATION.md` records the
foundation; its limited acceptance criteria do not prove this broader goal complete.

## Current evidence and previous-turn classification

Audit started October 3, 2026, from clean local/remote commit
`126864de16ba5f3a6d169c1d02c1c237b4f22d95`.

The previous turn is **progress**, not a wait: it created and pushed native
renderer/skill/plugin code and produced executable tests and artifacts. Current
Git state confirms that foundation exists. It does not establish a comprehensive
visual-documentation or storytelling suite.

Changes continue on `feat/comprehensive-suite`. The imported ZIP, original skill,
other source checkouts, unrelated work, and global host installations remain
protected. A failed App worktree creation did not grant any additional authority;
the clean current checkout was placed on an ordinary feature branch instead.

## Required outcome

A usable, source-grounded suite—not merely a list of suggestions—must cover:

| ID | Requirement | Baseline evidence | Completion evidence required |
| --- | --- | --- | --- |
| R1 | Flexible STE writing without factual drift or fabricated compliance | `writing.py`, existing skill and tests | Writing workflows, appropriate review prompts, adversarial examples and explicit diagnostic limits |
| R2 | Relevant deep research translated into implementation | Original post/standard notes only | Opened primary sources, dated findings/limitations, research-to-feature/test traceability |
| R3 | First-class technical diagrams | Only one hand-authored SVG/HTML example | Safe structured flow/component and sequence diagrams, textual equivalents, real rendering and boundary tests |
| R4 | Faithful quantitative visual documentation | One fixed interactive rate example | Native bar/line views, units, missing values, uncertainty, numeric/axis validation, accessible data equivalents |
| R5 | Reusable evidence-backed storytelling | Generic prose guidance only | Audience/question/objective, claims and sources, qualified story beats, several useful narrative recipes |
| R6 | Author and reader control | One illustrative calculator | Navigable story/lesson HTML with readable no-JS/print output, keyboard controls, clear state and reduced motion |
| R7 | Cross-format continuity | Hard-coded examples are separate | A story source produces consistent prose, visual documentation, storyboard and narration script without inventing facts |
| R8 | Topic-specific narrated explanation | One four-cue preparation fixture | Reusable story-to-media path, real audio/timing checks, reviewed visual examples and verified export path; preparation must not masquerade as export |
| R9 | Agent-facing usability | One broad skill | Focused writing, visual-documentation and storytelling workflows with accurate executable commands and progressive references |
| R10 | Copilot/Claude/Codex delivery | Manifests and source bundle; not installed | Updated package payload/identity, portable execution, host-specific validation evidence and clearly bounded unverified surfaces |
| R11 | Complete verification | Foundation unit tests and narrow browser checks | Requirements-level coverage, real diverse artifacts, responsive/accessibility/negative tests, source preservation and package/CI checks |
| R12 | Honest completion audit | Foundation report only | Each row above mapped to current authoritative evidence; missing or indirect evidence remains open |

“Comprehensive” does not mean generating every medium for every request, supporting
every possible chart notation, inventing source facts, or installing services
without permission. It does mean real reusable pathways for these core jobs—not
calling an HTML escape hatch a diagram tool, or one prepared audio file a video suite.

## Research lanes

1. **Visual learning and documentation:** primary learning-science evidence,
   worked examples, verbal/visual integration, complex-image accessibility, and
   interaction controls. Distinguish findings from product design inferences.
2. **Storytelling and evidence:** original narrative-visualization research,
   documentation-purpose distinctions, reader/author control, uncertainty, and
   temporal explanation. Do not force every subject into a dramatic story.
3. **Technical implementation:** current native code, SVG/browser standards, local
   media tooling, and actual host contracts. Reuse existing dependencies.

Research must change decisions or tests. Store source-backed synthesis under
`docs/research/`; avoid shallow catalogs and unsupported universal learning claims.

## Implementation sequence

### A. Native visual-documentation primitives

- Extend the existing renderer with validated `diagram` and `chart` sections.
- Generate SVG from structured data; do not require raw HTML or new frameworks.
- Include a meaningful name/description and a visible text/data equivalent.
- Preserve all supplied nodes, relationships, categories, values and qualifications.
- Reject unsupported/ambiguous structures instead of silently losing information.
- Keep complex visuals legible in a contained scrolling region on small screens;
  do not shrink them into unreadable labels or overflow the whole page.
- Make supported input shapes discoverable through a native `schema` command.

### B. A reusable story source and compiler

- Define one versioned input with audience, question, purpose, sources, qualified
  claims, ordered beats, and optional validated visuals/check questions.
- Distinguish observations, attributed explanations, inferences and proposals.
- Validate references and preserve uncertainty; source registration is not proof
  that a claim is true or that the source was independently verified.
- Compile into native HTML plus a readable prose version, storyboard and narration
  script, keeping the exact input and traceable source/claim identifiers.
- Provide explanatory lesson, decision brief, research digest and incident
  explanation recipes. These are contextual choices, not mandatory plot structures.
- Support reader-controlled progress and an all-content view; avoid autoplay,
  hidden-only qualifications, or an interface that fails without JavaScript.

### C. Media and plugin completion

- Generalize the current narration fixture around a story, measured audio, and
  inspectable visual beats rather than a fixed four-part topic.
- Follow the actual media workflow's review/export gates. Do not claim MP4 output
  without reading the produced file and checking picture, audio, duration and timing.
- Update focused skills, examples, schema guidance, package resources, and host
  validation. Installation and publication remain explicit actions, not side
  effects of building a plugin.
- Packaging cleanup: move the existing narration helper unchanged into
  `ste_promax/scripts/` rather than duplicate it. The existing 13 narration tests
  lock its behavior; compare its SHA-256 before/after the move, and include that
  single resource in both wheel and source-plugin payload checks.

## Validation and stop rule

Run baseline regression tests before editing behavior. Add targeted tests for each
new contract, then real CLI renders and browser checks. Keep code-author and
reviewer passes separate for substantive changes. Test malicious/invalid input,
duplicate references, cycles/feedback where supported, missing data, negative
values, long labels, broken asset references, and preservation boundaries.

Produce examples with genuinely different structures, not cosmetic copies of one
dashboard. Record actual artifacts and observed results in the suite audit.
Freshly compare the plugin payload with the committed source and check CI.

The goal remains **active** while any R1–R12 requirement is absent, incomplete,
only described, weakly verified, or blocked on a required action. A passing unit
suite, a research document, or one attractive sample is not the stop condition.
