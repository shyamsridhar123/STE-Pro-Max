# Design

## Source of truth
Active, October 3, 2026. Applies to STE-Pro Max visual documentation, stories,
lessons, and local explanation examples. `docs/SUITE_PLAN.md` defines the broader
suite objective; the original Clarity Lab remains a regression example.
Evidence: the original writing skill, Karpathy's October 1 Chicago-time post,
the native renderer, and the owner's October 3 identity/onboarding brief.
`docs/PLUGIN_FIRST_PLAN.md` supersedes the earlier runtime-first onboarding
in `docs/UX_PLAN.md`. The product entry is native plugin installation.

## Brand
Make complex ideas click. Confident, outcome-led product copy; precise, direct
explanations. Show evidence and limits without making defensive caveats the pitch.
Avoid decorative dashboards, invented metrics, AI badges, and claims of certification.
STE-Pro Max is the only product identity in current source and generated output.

## Product goals
Make explanations easier to understand without changing their meaning. Support
technical relationships, quantitative evidence, and coherent stories through real
reusable workflows. Do not build a hosted platform. Success means readers can
inspect the evidence, follow the explanation, and distinguish observations,
attributed explanations, inferences, and proposals.
First-use success: register/install through the selected host's plugin manager,
then ask for an explanation. Routine requests need no Python installation,
output-folder naming, schema choices, or repeated preference interview.

## Personas and jobs
Technical and business readers need clear updates; learners need a concrete example
they can inspect and manipulate. An agent author needs a repeatable local workflow.

## Information architecture
The README leads with the generated editorial hero and an STE-first,
Karpathy-inspired product promise. Named STE and Karpathy-guideline highlights
come before the large real examples: source-to-brief transformation, an interactive
retry model, and a rate lab. Native installation follows. Keep the foundations
visible, not buried in a footer or only in linked docs. Extended background,
limits, prompts, research, lifecycle, and developer detail belong behind the
`docs/README.md` hub. Focused skills route writing, visual documentation,
storytelling, and media. A story presents its question and audience, an overview,
ordered evidence-backed beats, and a source register. Guided and all-content views
share the same facts. Source disclosures remain visible and printable.

## Design principles
Show the concept before notation. Use movement to explain change, not decorate.
Use one example across media. Keep controls next to the quantities they change.
Make uncertainty as legible as the headline.

## Visual language
STE-Pro Max's dark editorial shell; warm off-white text, muted stone labels, and
copper accent. System sans-serif for prose and monospace for values. Thin rules,
generous whitespace, minimal elevation. Inline SVG for accurate, labeled diagrams.
Hero art uses a wide charcoal/ivory/copper composition, with generous negative
space and the idea of source material becoming a clear explanation. Keep brand
art distinct from the real rendered-output showcase. No fictitious endorsements.

## Components
Existing components include labeled inputs, comparison bars, calculation readouts,
reset, source notes, and evidence callouts. New native figures need names, captions
and equivalent text/data; story controls need an outline, progress and explicit
navigation. Use the renderer's shell/tokens, not a new design-system dependency.

## Accessibility
Target WCAG 2.2 AA behavior; do not claim conformance from a smoke test. Provide
labels, keyboard focus, textual equivalents, readable contrast, and narration
transcripts. Never encode meaning by color alone. Respect reduced motion.

## Responsive behavior
Two columns when space permits; stack below 720px. Controls remain usable at 375px.
No page-level horizontal overflow or hover-only information. Complex figures may
use a labeled, keyboard-focusable contained scroll region with a legible minimum
size and a visible text/data equivalent; do not shrink labels into unreadability.

## Interaction states
Show baseline-zero relative change as undefined, not zero or infinity. Reject
non-finite values and rates outside 0–100. Reset restores the documented example.
No network, loading spinner, persistent user tracking, or live-data claims.

## Content voice
Use relaxed STE-inspired prose. Label illustrative numbers. State what changed;
do not invent why it changed. Keep percentage points distinct from percentages.

## Implementation constraints
Use the existing native engine, standard browser APIs, and standard-library helpers.
Keep the existing Jinja2/PyYAML dependencies; add no app framework. Save source inputs. Verify the rendered
HTML in a real browser at desktop and mobile sizes, including invalid input.
Narrated examples use a generic installed voice, not a cloned or imitated person.
Default installed skills author with the host's own tools and dependency-free
HTML/SVG starters. They must not silently bootstrap Python or claim optional
engine validation when it did not run. No package manager is reimplemented.

## Open questions
None blocking. Default language is English and all examples are local-only.
