# What good looks like

Working, single-file examples. Open an HTML file in a browser: no Python,
package installation, server, external font, or build step is required.
All data is explicitly fictional. These are reusable authoring starters, not
evidence of a real system's safety or a measured learning outcome.

| Example | Try it | What to preserve when adapting |
| --- | --- | --- |
| [Retry Observatory — Line Studio](retry-observatory.html) | Play or scrub the isometric explanation; change budgets and layers; save SVG | Cumulative attempt counts, initial attempt included, persistent failure, no timing or concurrency claim |
| [Line Studio patterns](line-studio.html) | Inspect six original line-art interactions by pointer or keyboard | Metaphors are illustrative, not measured data; retain equivalent controls and full descriptions |
| [From dense note to sharp brief](brief-transformation.html) | Trace the outcome, scope, and proposal to the original note | 240 total questions; 186 accepted, 38 requiring edits, 16 unanswered; limited scope; proposed, unstarted pilot |
| [One request. 81 backend attempts.](retry-storm.html) | Change layers and attempts; compare a single retry owner | Persistent-failure model, attempts including the initial call, worst-case counts rather than timing or telemetry |
| [One retry. One record.](retry-lab.html) | Step through K7/R9, play the trace, reset | Message order, 2 requests / 1 stored record, sequential-only scope |
| [Checks passed. Release on hold.](release-brief.html) | Inspect the evidence and reveal the reader check | Test scope, pending authority, proposed versus executed action |
| [A better number needs a better explanation.](rate-lab.html) | Change rates; try a zero baseline | Percentage points versus relative change, undefined comparisons, no invented cause |

[Previews, downloads, and copyable prompts](../../docs/EXAMPLES.md).

## Use from the installed plugin

Ask the host to read the relevant template, preserve your source, and adapt it
with its native file tools into a new `artifacts/` directory. Keep the installed
copy unchanged. Replace fictional values only with supplied evidence, and test
controls, keyboard use, mobile layout, no-JavaScript reading, and print output.

The v0.5.0 plugin includes all seven examples above, including Line Studio and
Retry Observatory, with editable templates, original JavaScript and source JSON.
The previous v0.4.0 tag remains unchanged and includes only the original
retry-lab, release-brief and rate-lab starters.

The template route is host-authored HTML/SVG. It does not implicitly run the
optional Python engine's schema validators or produce its hash manifest.
For deterministic compilation, use the separate [engine guide](../../docs/AUTHORING.md).

Source baselines: [pilot note](sources/launch-note.md),
[retry model](sources/retry-storm.json), [retry trace](../suite/sources/retry-trace.json),
[release records](../../ste_promax/data/quickstart.json), and
[rate comparison](../clarity-lab/source.md).
