# Comprehensive-suite completion audit

**Objective:** implement the Karpathy-inspired STE, visual-documentation, and
storytelling suite with relevant deep research.

**Audit date:** October 3, 2026. **State: active, not complete.**
The original scope in `SUITE_PLAN.md` remains unchanged. The remaining media
review/export gate is not replaced by a narrower “preparation passed” claim.

| Requirement | Current evidence | Status / remaining work |
| --- | --- | --- |
| R1 — Flexible writing and factual fidelity | Primary and focused skills; writing tests; six independent behavioral cases; literal JSON precision and Markdown round-trip regressions | Implemented and checked within the documented scope; no automatic fact-check or STE certification claimed |
| R2 — Research translated into implementation | `research/VISUAL_LEARNING_AND_STORYTELLING.md` maps ten primary sources to decisions and tests; `research/OPEN_KNOWLEDGE_FORMAT.md` records the bounded interchange decision | Complete research deliverable; outcome studies and OKF implementation are not claimed |
| R3 — First-class technical diagrams | Native flow/component and sequence schemas, feedback/self-links, ordered text equivalents, standalone SVG exports, real fixture rendering | Implemented; dense/tall cases included in browser and print checks |
| R4 — Faithful quantitative documentation | Bar and categorical line charts, units, nulls, source-provided bounds, domain validation, noncolor encodings, exact tables | Implemented; lossy literal JSON numbers are rejected before output |
| R5 — Evidence-backed storytelling | Four distinct purposes and fixtures; audience/question/summary; typed claims with source IDs, scope, attribution, basis, uncertainty | Implemented; structural linkage is not proof of entailment or truth |
| R6 — Author/reader control | Guided/all-content views, outline/history navigation, native answer disclosure, print-only answer equivalents, no-JavaScript reading | 42 browser scenarios passed; no blanket WCAG or screen-reader claim |
| R7 — Cross-format continuity | One input produces HTML, SVGs, readable prose, complete evidence/storyboard/narration companions; hashes and tamper checks | Implemented and tested; free-form narration still requires semantic review |
| R8 — Topic-specific narrated explanation | Reusable local speech/provided-PCM preparation; measured timing; sequence-message stages; real 34.738-second example; final `video/` project and Studio show zero errors | **Open:** preview/export approval requested; then inspect an actual encoded movie and audio |
| R9 — Agent usability | Three validated focused skills; `schema`, `check`, `render`, `narrate`; authoring guide and cross-directory invocation | Implemented; commands and structured examples exercised |
| R10 — Copilot/Claude/Codex delivery | Shared v0.2 source bundle and wheel resources; three skills; Agent Plugins 1.0 schema; strict Claude descriptors; Copilot session-only discovery | Packaging and local discovery checked; final saved bundle comparison still required. No persistent installs or Codex desktop runtime acceptance claimed |
| R11 — Complete verification | Full 279-test post-separation run; lint/typecheck; seven rendered fixtures, 42 browser scenarios, seven PDFs, source hashes, independent review | **Open:** final saved-package comparison and pushed-commit CI |
| R12 — Honest final audit | This requirement-by-requirement record, validation report, explicit open gates | Audit exists; update against final current evidence before claiming the objective complete |

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

The ordinary evidence-review page now stays outside the `video/` project.
Studio's broad HTML lint pass exposed that packaging boundary; it was corrected
by separating actual movies from review documents, not by inventing video
attributes on the latter.

## Preserved boundaries

The original archive and extracted source remain byte-identical. This work does
not modify the PaperBoard checkout, add application dependencies, install global
skills/plugins, configure paid providers, or publish generated artifacts.

SCUBACRAZY has a pending write-access invitation; an invitation is not accepted
collaborator access. The repository remains private.

## Stop condition

Do not mark the goal complete while R8, R10's final payload comparison, or R11's
final verification are open. Follow the installed HyperFrames preview/export
approval gate. Preserve this audit and the full objective across continuation.
