# Source-grounded local suite

These are **explicitly fictional authored exercises**, not real research results,
production measurements, vendor comparisons, or evidence of an executed system.
Each JSON source note in `sources/` is the input evidence for its fixture. Raw
observations, policies, qualifications and proposals remain separately inspectable.
`claim_support` maps claim IDs to the source fields that support them; it is an
authoring cross-reference, not independent verification.

| Fixture | Reader job | Distinct content |
| --- | --- | --- |
| `retry-explanation.json` | Explain why a retry need not add a write | Two beats; sequential messages including a self-message; 2 requests versus 1 record |
| `workshop-decision.json` | Apply a supplied gate before choosing a rehearsal | 24 versus 18 minutes for 40 sets; 1 versus 4 mislabels against a cap of 2 |
| `instruction-research.json` | Separate a small notebook from a general finding | Medians 12 and 9 seconds; supplied min–max ranges 10–14 and 8–16; qualified attribution |
| `queue-incident.json` | Review incomplete evidence without invented closure | Depths 2, 5, unknown, 4, 1; line gap; competing explanation; proposed follow-up |
| `caption-documentation.json` | Read an architecture and its current gate | Feedback and self-link; 7 corrected, 3 clear, 2 pending; visible source register and reader checks |

## Validate and render locally

The four story JSON files use the current `STORY_SCHEMA`; their visuals use
`DIAGRAM_SCHEMA` and `CHART_SCHEMA`. The report uses ordinary structured sections,
including native `diagram` and `chart` kinds, rather than raw HTML.

From the repository root, validate the fixtures and their exact evidence links:

```text
python -B -m unittest discover -s tests -p test_suite_examples.py -v
```

The tests call `validate_story`, `validate_diagram`, `validate_chart`,
`story_companions` and the figure/story renderers directly, then render all five
fixtures through real `cli.main` dispatch. They inspect the HTML/DESIGN/metadata
triples, galleries, retained sources, normalized inputs, story companions and all
manifest file hashes. Output lives in fresh temporary `artifacts/` subdirectories
and is cleaned up by the test. No runtime code is patched or emulated; no service,
browser or installation is used.

To keep a render for local inspection, choose a new output directory:

```text
python -m ste_promax render examples/suite/retry-explanation.json --output-dir artifacts/suite-retry-review
python -m ste_promax render examples/suite/caption-documentation.json --output-dir artifacts/suite-caption-review
```

The four story renders include `story.md`, `storyboard.json`, `narration.json`
and `evidence.json`. The visual-documentation report uses the standard triple and
gallery. Existing nonempty output directories are not overwritten.

`story_companions(json.loads(path.read_text(encoding="utf-8")))` returns a prose
outline, complete storyboard, draft narration cues and evidence ledger. It does
not synthesize audio or validate the truth of the supplied sources.

## Concise local narration QA

Use `retry-explanation.json` and its exact authored cue concatenation,
`retry-explanation.narration.txt`. Its two beats carry one short sequence and one
two-bar count comparison. Neither visual contains a prose paragraph.

The transcript is 73 whitespace-delimited words: approximately 29 seconds at
150 words/minute, or about 24–37 seconds at 120–180 words/minute. This is a planning
estimate, **not measured audio duration**. A local installed generic voice can
read the text; main owns actual synthesis, PCM checks and timing verification.
Do not infer a finished narrated video from these fixtures.

## Interpretation boundaries

- The research bounds are source-provided observed minima and maxima, not a
  confidence interval. No renderer-generated statistical claim is used.
- The incident's `null` is an unavailable sample, never zero or an interpolated
  measurement. Its categories are equally spaced scheduled one-minute snapshots;
  the chart is not a continuous-time telemetry plot.
- The two events in minute 1 have unknown relative order. The incident uses prose
  to preserve that ambiguity, rather than inventing order in a sequence diagram.
- Dashed diagram lines are presentation choices, not an evidence classification.
- Story source/claim links are structured. The report's native section schema has
  no claim ledger field: source and claim IDs are explicit in captions, notes and
  its register, with exact fixture-level tests.
- The CLI's conservative reference scan may list the SVG XML namespace as an
  external reference. The tests allow that namespace, not arbitrary external
  addresses; they do not turn `offline_verified: false` into a network QA claim.
- These tests check supplied relationships, quantities and cross-format fidelity.
  They do not prove causal validity, usability, accessibility conformance,
  successful external actions, browser layout or narration quality.
