# Design

## Source of truth
Active, October 3, 2026. Applies to local STE-Pro Max explanation examples.
Evidence: the original writing skill, Karpathy's October 1 Chicago-time post, and
ATV-PaperBoard's renderer source. No independent brand assets were supplied.

## Brand
An explanatory notebook: precise, calm, and direct. Show evidence and limits.
Avoid decorative dashboards, invented metrics, AI badges, and claims of certification.

## Product goals
Make an explanation easier to understand without changing its meaning. Demonstrate
each supported output mode with a small, reusable example. Do not build a platform.
Success means the reader can distinguish absolute change, relative change, and cause.

## Personas and jobs
Technical and business readers need clear updates; learners need a concrete example
they can inspect and manipulate. An agent author needs a repeatable local workflow.

## Information architecture
The README is the entry point. The skill routes prose, diagrams, HTML, and video.
The Clarity Lab artifact moves from source values to a visual comparison, calculation,
and evidence boundary. Source disclosures remain visible.

## Design principles
Show the concept before notation. Use movement to explain change, not decorate.
Use one example across media. Keep controls next to the quantities they change.
Make uncertainty as legible as the headline.

## Visual language
PaperBoard's dark editorial shell; warm off-white text, muted stone labels, and
copper accent. System sans-serif for prose and monospace for values. Thin rules,
generous whitespace, minimal elevation. Inline SVG for accurate, labeled diagrams.

## Components
Labeled number inputs, accessible comparison bars, a calculation readout, a reset
button, source notes, and an evidence-boundary callout. The example owns its scoped
styles; the adapted native renderer owns the outer shell. Root tokens are recorded here, not in a
second design-system package.

## Accessibility
Target WCAG 2.2 AA behavior; do not claim conformance from a smoke test. Provide
labels, keyboard focus, textual equivalents, readable contrast, and narration
transcripts. Never encode meaning by color alone. Respect reduced motion.

## Responsive behavior
Two columns when space permits; stack below 720px. Controls remain usable at 375px.
No horizontal scrolling or hover-only information.

## Interaction states
Show baseline-zero relative change as undefined, not zero or infinity. Reject
non-finite values and rates outside 0–100. Reset restores the documented example.
No network, loading spinner, persistent user tracking, or live-data claims.

## Content voice
Use relaxed STE-inspired prose. Label illustrative numbers. State what changed;
do not invent why it changed. Keep percentage points distinct from percentages.

## Implementation constraints
Adapt the existing PaperBoard code, standard browser APIs, and standard-library helpers.
Keep PaperBoard's existing Jinja2/PyYAML dependencies; add no app framework. Save source inputs. Verify the rendered
HTML in a real browser at desktop and mobile sizes, including invalid input.
Narrated examples use a generic installed voice, not a cloned or imitated person.

## Open questions
None blocking. Default language is English and all examples are local-only.
