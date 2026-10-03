# Comprehensive-suite completion audit

**Objective:** implement the Karpathy-inspired STE, visual-documentation, and
storytelling suite with relevant deep research.

**Audit date:** October 3, 2026. **State: requirements verified within the tested scope.**
The original scope in `SUITE_PLAN.md` remains unchanged. The user-approved local
MP4 now has encoded-picture and audio evidence; preparation is not substituted
for export. Final delivery must use the exact-commit payload/CI checks below.

| Requirement | Current evidence | Status / remaining work |
| --- | --- | --- |
| R1 — Flexible writing and factual fidelity | Primary and focused skills; writing tests; six independent behavioral cases; literal JSON precision and Markdown round-trip regressions | Implemented and checked within the documented scope; no automatic fact-check or STE certification claimed |
| R2 — Research translated into implementation | `research/VISUAL_LEARNING_AND_STORYTELLING.md` maps ten primary sources to decisions and tests; `research/OPEN_KNOWLEDGE_FORMAT.md` records the bounded interchange decision | Complete research deliverable; outcome studies and OKF implementation are not claimed |
| R3 — First-class technical diagrams | Native flow/component and sequence schemas, feedback/self-links, ordered text equivalents, standalone SVG exports, real fixture rendering | Implemented; dense/tall cases included in browser and print checks |
| R4 — Faithful quantitative documentation | Bar and categorical line charts, units, nulls, source-provided bounds, domain validation, noncolor encodings, exact tables | Implemented; lossy literal JSON numbers are rejected before output |
| R5 — Evidence-backed storytelling | Four distinct purposes and fixtures; audience/question/summary; typed claims with source IDs, scope, attribution, basis, uncertainty | Implemented; structural linkage is not proof of entailment or truth |
| R6 — Author/reader control | Guided/all-content views, outline/history navigation, native answer disclosure, print-only answer equivalents, no-JavaScript reading | 42 passing browser records, including three not-applicable story-control cases for non-story documents; no blanket WCAG or screen-reader claim |
| R7 — Cross-format continuity | One input produces HTML, SVGs, readable prose, complete evidence/storyboard/narration companions; hashes and tamper checks | Implemented and tested; free-form narration still requires semantic review |
| R8 — Topic-specific narrated explanation | Reusable speech/provided-PCM preparation; approved final Studio preview; actual 34.750-second 1080p/24-fps MP4; all 834 frames decoded; ten sampled pictures inspected; both audio clips compared with source | Verified local export, not merely preparation; manual listening and word alignment remain unclaimed |
| R9 — Agent usability | Three validated focused skills; `schema`, `check`, `render`, `narrate`; authoring guide and cross-directory invocation | Implemented; commands and structured examples exercised |
| R10 — Copilot/Claude/Codex delivery | Three skills; Agent Plugins 1.0 schema; strict Claude descriptors; Copilot session-only discovery; 65 saved plugin files and 18 wheel runtime files match source; both extracted packages execute | Verified package and bounded host discovery; no persistent installs or Codex desktop runtime acceptance claimed |
| R11 — Complete verification | 279 tests; all-surface Ruff/Pyright; seven rendered fixtures, browser/print evidence, source hashes, independent review, saved-package execution; Ubuntu/Windows CI on implementation and test-closeout commits | Verified; delivery snapshot must repeat exact-commit package and CI checks rather than reuse stale artifacts |
| R12 — Honest final audit | This requirements record, `VALIDATION.md`, export approval/input hashes, decoded-video evidence, package verification, exact-SHA CI, explicit untested surfaces | All requirements have concrete scoped evidence; release record ties final delivery to its commit |

## Independent defects found and repaired

- Lossy JSON float conversion could turn a nonzero quantity into zero or change
  its decimal value. The shared ingestion boundary now rejects such tokens with
  a source location instead of presenting altered values as exact evidence.
- Non-string story purpose values could escape validation as an uncaught type
  error. They now receive ordinary located validation errors.
- Escaped literal Markdown and table pipes did not reliably round-trip.
  Regression-tested literal handling and complete table cells now preserve them.
- Browser back-navigation could leave its targeted story beat hidden; printing
  could omit closed answers. Both behaviors were reproduced and corrected.
- A source table could overflow the whole mobile page. Focusable contained
  scrolling now preserves the table without cropping its cells.
- The initial media composition omitted the required root start time; a real
  HyperFrames check caught it. The root now declares zero explicitly.
- Legacy host pipe encodings could fail after rendering Unicode content.
  Machine JSON uses ASCII escapes while source/artifact files remain UTF-8.
- Broad typechecking exposed 100 diagnostics in test fixtures missed by the
  previous production-only pass. Types and assertion narrowing fixed them;
  all 279 tests and the broader static-analysis scope now pass.

The ordinary evidence-review page now stays outside the `video/` project.
Studio's broad HTML lint pass exposed that packaging boundary; it was corrected
by separating actual movies from review documents, not by inventing video
attributes on the latter.

## Preserved boundaries

The original archive and extracted source remain byte-identical. This work does
not modify unrelated source checkouts, add application dependencies, install global
skills/plugins, configure paid providers, or publish generated artifacts.

SCUBACRAZY has a pending write-access invitation; an invitation is not accepted
collaborator access. The repository remains private.

## Delivery evidence and stop condition

- Local movie and technical/picture review:
  `artifacts/retry-export-20261003-b/`.
- Self-contained MP4/source/transcript/review delivery:
  `artifacts/retry-delivery-20261003/`.
- Final source plugin, wheel, commit/hash comparison, and extracted executions:
  `artifacts/suite-release-20261003/`.
- Exact-commit GitHub job evidence:
  `artifacts/suite-final-github-20261003/`.

The final release record must name the same source SHA as the pushed branch and
successful CI. Do not declare delivery complete if that comparison fails.
Runtime acceptance in every host, full WCAG/screen-reader certification, learning
outcome studies, manual audio listening, word alignment, and an OKF exporter are
explicitly not established by this audit. They are not silently reported as passed.
The private PR remains unmerged; generated media stays local.

## v0.3 UX extension

The owner-requested standalone identity, `start`, `doctor`, explicit isolated
quickstart, lower-friction skill routing, generated hero, and real-output showcase
are tracked in `UX_PLAN.md`. Their new tests and fresh first-run/README evidence
are recorded under the v0.3 section of `VALIDATION.md`, not inferred from the
v0.2 media or packaging results above.
