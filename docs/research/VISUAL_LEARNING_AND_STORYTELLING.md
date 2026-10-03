# Visual learning and evidence-linked storytelling

## Evidence scope

Research retrieval date: **October 3, 2026**. This note records the completed
primary-source research handoff supplied to the documentation task. It does not
claim a new full-text review in this authoring pass. Mayer and Chandler was
inspected at **publisher-abstract level only**; that limitation remains explicit.

The sources below support bounded findings or guidance. Their translation into
suite behavior is a **design inference**, not an experimentally established
effect of this software. Existing tests establish specific artifact contracts,
not learning, trust, decision quality, or full accessibility conformance.

## Sources, findings, and limits

| ID | Primary source | What the source supports | Boundary |
| --- | --- | --- | --- |
| S1 | [IES practice guide (2007), *Organizing Instruction and Study to Improve Student Learning*](https://ies.ed.gov/ncee/WWC/Docs/PracticeGuide/20072004.pdf) | Recommendations include worked examples with practice, combined verbal/visual explanations, and retrieval with feedback. | An instructional practice guide, not a trial of this suite. It does not show that animation is always better than a static explanation. |
| S2 | [Mayer and Chandler (2001), publisher abstract](https://psycnet.apa.org/record/2001-06601-013?doi=1) | In the studied lightning-animation task, learner control improved transfer, not retention. | Abstract-only inspection. Task-specific evidence cannot establish a universal benefit for guided beats, diagrams, narration, or workplace decisions. |
| S3 | [W3C WAI, Complex Images tutorial](https://www.w3.org/WAI/tutorials/images/complex/) | Meaningful brief alternatives and structured long alternatives can expose a complex image's information. Referencing rich content through `aria-describedby` flattens its structure in the accessible description. | Accessibility guidance, not an outcome study. A name or description alone is not a complete equivalent for a graph or data table. |
| S4 | [W3C, WCAG 2.2](https://www.w3.org/TR/WCAG22/) | Relevant requirements address keyboard access, noncolor information, reflow, and motion. | The suite's selected checks are not a full WCAG conformance assessment. Criterion applicability and assistive-technology behavior still require review. |
| S5 | [Segel and Heer (2010), *Narrative Visualization*](https://idl.cs.washington.edu/files/2010-Narrative-InfoVis.pdf) | Analysis of 58 examples describes narrative techniques and the balance between author-directed structure and reader-directed exploration. | An example-based analysis, not a controlled learning or decision-outcome study. |
| S6 | [Hullman and Diakopoulos (2011), *Visualization Rhetoric*](https://users.eecs.northwestern.edu/~jhullman/vis_rhetoric.pdf) | Qualitative analysis of 51 examples examines framing through data selection, visual representation, annotation, and interaction. | It supports inspecting framing choices; it does not provide an automatic neutrality test or prove this suite is unbiased. |
| S7 | [Diataxis, Foundations](https://diataxis.fr/foundations/) | A practitioner framework separates learning-oriented work from tasks, reference, and explanation. | Useful authoring taxonomy, not an experimental finding that one document structure improves learning. |
| S8 | [*Timelines Revisited*, preprint](https://timelinesrevisited.github.io/preprint.pdf) | Distinguishes temporal representations, including chronological distance and sequential order. | The preprint is dated 2016; the journal issue is 2017. Do not collapse these into conflicting dates or infer a guaranteed learning benefit. |
| S9 | [van der Bles and colleagues (2020)](https://pure.rug.nl/ws/files/131063442/7672.full.pdf) | Across studies totaling 5,780 UK participants, communicating numerical uncertainty with ranges generally did not substantially reduce trust. | A bounded finding about trust in the studied settings, not proof of improved decisions, universal responses, or a reason to invent intervals. |
| S10 | [W3C PROV-DM Recommendation, April 30, 2013](https://www.w3.org/TR/2013/REC-prov-dm-20130430/) | Models provenance concepts such as derivation and attribution. | Provenance is not truth, authentication, endorsement, or authorization. The suite's small source/claim model does not claim PROV-DM conformance. |

## Source → design inference → acceptance evidence

The following decisions are **our design inferences**. Test identifiers name
existing repository tests inspected during this documentation pass; their
presence is not a claim that the full suite or every host has passed. Refer to
fresh test output and the main validation record for execution status.

| Design inference and sources | Implemented contract or authoring constraint | Existing test location | Review or future acceptance still needed |
| --- | --- | --- | --- |
| D1. Use a concrete explanation with optional checks, not compulsory media (S1, S2, S7) | Four story purposes; optional question/answer; no fabricated answer when omitted | `tests/test_suite_examples.py::SuiteExampleTests.test_four_distinct_purposes_and_one_structured_report`; `tests/test_stories.py::StoryTests.test_optional_unanswered_question_does_not_fabricate_answer` | Check that the example matches audience knowledge and that feedback explains the misconception. A learning claim needs a separate evaluation. |
| D2. Let the reader control pace without hiding the only copy of the evidence (S2, S5) | All-content reading plus guided controls, complete ledger, and no-JavaScript/print alternatives | `tests/test_stories.py::StoryTests.test_static_content_readable_without_javascript_and_print_rule_exists`; `test_claims_unused_by_beats_are_not_lost` in the same class | Real keyboard/focus, outline, guided/all-content, no-JavaScript, and printed-output checks. Static markup/CSS tests alone do not establish these behaviors. |
| D3. Preserve a useful long alternative, not only an image name (S3, S4) | Visible diagram relationship list and exact chart table; story prose includes visual equivalents | `tests/test_diagrams.py::DiagramTests.test_visible_equivalent_retains_exact_text_and_order`; `tests/test_charts.py::ChartRenderingTests.test_exact_table_preserves_every_value_and_bound`; `tests/test_stories.py::StoryTests.test_readable_sequence_preserves_message_order_and_notes` | Compare equivalence with source meaning; inspect assistive-technology navigation and dense/long-label cases. |
| D4. Keep noncolor meaning and narrow-screen access explicit (S3, S4) | Markers/dashes/series labels; focusable contained scrolling; authoring review checklist | `tests/test_charts.py::ChartRenderingTests.test_multiseries_has_noncolor_encodings`; `test_full_size_limit_is_bounded_and_scrollable` in the same class; `tests/test_diagrams.py::DiagramTests.test_accessible_name_description_caption_and_scrolling` | Browser viewport, zoom/reflow, focus visibility, contrast, and screen-reader checks. Do not label selected checks full conformance. |
| D5. Treat ordering, selection, and annotation as framing (S5, S6) | Typed claims, visible qualifications, unused-claim ledger, and explicit selection review | `tests/test_stories.py::StoryTests.test_claims_unused_by_beats_are_not_lost`; `test_attribution_and_inference_require_qualifying_fields` in the same class | Review free-form prose, chart emphasis, excluded evidence, alternative explanations, and options. Valid links cannot establish balanced framing. |
| D6. Do not encode duration with sequence spacing (S8) | Ordered messages and equally spaced chart categories; no continuous-time claim | `tests/test_diagrams.py::DiagramTests.test_sequence_order_and_self_message_geometry`; `tests/test_suite_examples.py::SuiteExampleTests.test_incident_missing_value_and_chronology_are_preserved` | Author-facing acceptance: unequal time intervals or unordered events must not become invented equal durations or a fabricated sequence. |
| D7. Display supplied uncertainty without manufacturing it (S9) | Explicit units, paired bounds and their meaning, missing values distinct from zero, domain checks | `tests/test_charts.py::ChartValidationTests.test_interval_validation`; `test_domain_cannot_clip_values_or_intervals` in the same class; `tests/test_charts.py::ChartRenderingTests.test_line_breaks_at_each_missing_value`; `tests/test_suite_examples.py::SuiteExampleTests.test_research_intervals_are_source_ranges_not_invented_statistics` | Check the statistical meaning and source adequacy manually. A nonempty uncertainty label can still be incorrect. |
| D8. Preserve traceability without claiming verification (S6, S10) | Source/claim IDs, attribution/basis fields, complete source and evidence companions; unperformed semantic/source review is explicit | `tests/test_stories.py::StoryTests.test_duplicate_and_dangling_references_fail`; `tests/test_suite_integration.py::SuiteIntegrationTests.test_story_dispatch_and_all_companions_preserve_input_and_hashes`; `tests/test_suite_examples.py::SuiteExampleTests.test_source_to_claim_crosslinks_match_exactly` | Source retrieval, authenticity, entailment, conflicts, and action authority remain outside the structural validator. |
| D9. Keep cross-format continuity reviewable, not self-certifying (S1, S3, S10) | Shared story source feeds prose, visuals, storyboard, and draft narration; authored speech is retained with review required | `tests/test_stories.py::StoryTests.test_default_narration_keeps_all_claim_qualifications`; `test_authored_narration_is_unchanged_unverified_and_caveats_remain` in the same class; `tests/test_suite_examples.py::SuiteExampleTests.test_authored_narration_and_all_claims_survive_companion_formats` | Check speech against all material qualifications, including story-level limits and visual data not spoken by default. |
| D10. Base media timing on audio and disclose unreadable frames (S1, S3, S4) | Local media preparation uses measured PCM duration, whole-beat captions, and explicit dense-content limits; it never auto-exports a movie | `tests/test_media.py::MediaTests.test_one_two_seven_and_thirty_two_beats_keep_order_audio_and_source`; `test_dense_text_and_visuals_produce_explicit_limitations_not_tiny_text` in the same class | Listen to actual speech; inspect frames, captions and ending. PCM checks are not speech alignment. A prepared composition is not an encoded video. |

### Claims this evidence does not justify

- “Animations always teach better,” “guided beats improve retention,” or
  “narration guarantees understanding.”
- “Showing uncertainty improves decision quality” or “ranges never affect trust.”
- “Source-linked” means verified, authentic, neutral, or authorized.
- An exact-value table, accessible name, keyboard button, or reduced-motion rule
  proves full accessibility conformance.
- A test fixture containing a question measures learning, or a completed story
  proves the reader understands it.
- A changing PCM signal proves intelligible or correct narration, or a prepared
  composition is an exported movie.

## Additional acceptance scenarios

These are **review targets**, not blanket claims of passed results. They
supplement the named contract tests and keep future claims falsifiable. Current
execution evidence is summarized after the table; untested outcomes remain open.

| ID | Scenario and acceptance boundary |
| --- | --- |
| A1 | Give a new reader a worked example and a transfer question. Record the evaluation method and actual responses before claiming learning gains; a render test is insufficient. |
| A2 | Navigate a story using only the keyboard, then disable JavaScript and print it. All beats, material qualifications, sources, and authored answers must remain reachable/readable. Inspect actual output, not merely a CSS rule. |
| A3 | Inspect a dense diagram and long-label multi-series chart at a narrow viewport and with assistive technology. Verify source-complete alternatives, noncolor meaning, contained scrolling, and usable focus. Record tested combinations and gaps. |
| A4 | Supply unequal event intervals and unknown relative order. The author must preserve the uncertainty or select a different representation, not present sequential spacing as measured duration. |
| A5 | Supply an unsupported claim with a syntactically valid source ID and a contrary source elsewhere in the ledger. Semantic/framing review must flag both problems even when structural validation passes. |
| A6 | Supply a min–max range, a missing value, and a proposal. Each must remain distinct from a confidence interval, zero, and completed action in prose, visuals, speech, and captions. |
| A7 | Prepare a story with a dense visual and long narration. Inspect media-fit rejection and caption warnings; split the beat without deleting qualifications when the requested medium cannot present its meaning legibly. Check sequence-stage pacing against the speech. Do not call sidecar retention an adequate finished video. |
| A8 | Request a short prose rewrite. The skill must preserve that format rather than generating an unsolicited story, application, voiceover, or video. |

## Execution evidence from the implementation pass

These results concern the implemented contracts, not educational efficacy:

- `tools/verify_browser.mjs` ran **42 Chromium scenarios** across the five
  examples and two dense/tall boundary fixtures. Keyboard/history navigation,
  1280/375/320-pixel layouts, no-JavaScript content, print visibility and bounded
  figure/table regions passed. Browser requests to external HTTP(S) addresses
  were blocked; none were attempted by these generated documents.
- Seven real PDFs were created. The tall-sequence PDF retained all 32 message
  labels and its complete text equivalent. Representative PDF pages were
  rasterized and inspected; dense figures can span pages.
- Six independent skill-behavior cases preserved partial completion, uncertainty,
  quote/command fidelity, percentage-point arithmetic, a zero-baseline limit, and
  the requested medium. A source-embedded instruction was not obeyed. This is
  bounded behavioral evidence, not a general prompt-injection defense claim.
- Real local speech produced a 34.738-second example with five sequence stages
  and a quantitative comparison. Frame/timing checks are separate from source
  truth, spoken-content review, and export approval.

Local evidence is under `artifacts/suite-verify-20261003-c/` and
`artifacts/suite-behavior-20261003/`; it is intentionally not distributed as
plugin payload. `VALIDATION.md` records final media/package checks and remaining
gates. Assistive-technology coverage, learner studies, decision-quality effects,
and general model reliability remain unclaimed.

The stop condition for this research note is a traceable, qualified rationale for
authoring and testing. It is not suite completion or validation of every proposed
educational, accessibility, or decision benefit.
