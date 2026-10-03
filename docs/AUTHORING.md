# Authoring with STE-Pro Max

Use one source-grounded explanation and the smallest useful medium. The native
engine supports prose documents, structured diagrams/charts, and evidence-linked
stories. It does not verify source truth, certify ASD-STE100 or accessibility,
measure learning, or turn a proposed action into an authorized one.

## Choose the reader's job

| Reader needs to… | Start with |
| --- | --- |
| Read a finding, update, or rewrite | [STE-ProMAX prose](../skills/ste-promax/SKILL.md) |
| Inspect relationships, message order, or quantities | [Visual documentation](../skills/ste-visual-docs/SKILL.md) |
| Follow evidence through an explanation or decision | [Storytelling](../skills/ste-storytelling/SKILL.md) |
| Hear an already reviewed story | Native narration preparation; export remains separate |

State the audience and question before choosing a visual. A tutorial can use a
worked example and a check question; a reference should support lookup rather
than force a lesson. An incident review need not end in resolution. These are
authoring choices, not guaranteed learning outcomes. See the
[source-to-design research note](research/VISUAL_LEARNING_AND_STORYTELLING.md).

## Inspect the installed shapes

Run these commands from the repository root with an existing Python environment
that has the renderer's Jinja2 and PyYAML dependencies. Nothing here installs them.

```text
python -m ste_promax --help
python -m ste_promax schema
python -m ste_promax schema story
python -m ste_promax schema diagram
python -m ste_promax schema chart
python -m ste_promax schema callout
```

`schema` emits JSON descriptions and examples; without a kind it returns the
whole catalog. It is input guidance, not a JSON Schema validator or a factual
review. Use an existing catalog kind instead of inventing an unsupported field.
If a bundle lacks these commands, report the version/integration gap.

### Run a bundle from an unrelated directory

A skill can be loaded while the shell is in an unrelated user workspace. Resolve
the loaded `SKILL.md` first, then walk upward to the nearest ancestor containing
both `ste_promax/` and root `__main__.py`. Use that directory as the bundle root.
Do not infer it from the current directory, change into a plugin cache, or rely
on a globally installed module.

The following PowerShell example uses a reviewed `story.json` already in the
user's current workspace. Replace the first path with the resolved bundle path:

```powershell
$bundle = (Resolve-Path 'C:\path\to\bundle').Path
$source = (Resolve-Path '.\story.json').Path
$run = Join-Path (Get-Location).Path ('artifacts\ste-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $run | Out-Null
python "$bundle" --help
python "$bundle" schema story
python "$bundle" render "$source" --output-dir (Join-Path $run 'document')
```

This calls the same engine as `python -m ste_promax`, without a wrapper or a
PaperBoard installation. Keep absolute source/output paths in the user's
workspace. Keep the full bundle together; copying only a skill file omits the
engine and shared authoring guidance.

## Render a supplied example

These fixtures are fictional authoring exercises, not production results or real
research. Read their source notes under `examples/suite/sources/` before adapting
them. The renderer preserves the input file; it does not fetch or copy every
document named in a source locator.

| File | Purpose and constraint to preserve |
| --- | --- |
| [retry-explanation.json](../examples/suite/retry-explanation.json) | `explanation`: sequential retry trace; no concurrency guarantee |
| [workshop-decision.json](../examples/suite/workshop-decision.json) | `decision-brief`: supplied quality gate; no general winner from one run |
| [instruction-research.json](../examples/suite/instruction-research.json) | `research-digest`: fictional min–max bounds, not confidence intervals |
| [queue-incident.json](../examples/suite/queue-incident.json) | `incident-review`: missing sample, ambiguous event order, no established closure |
| [caption-documentation.json](../examples/suite/caption-documentation.json) | Visual document: flow, counts, source register, and unmet review gate |

From the repository root, run this PowerShell example. Each run gets a fresh
artifact directory; the renderer refuses a nonempty destination.

```powershell
$run = 'artifacts/authoring-' + [guid]::NewGuid().ToString('N')
New-Item -ItemType Directory -Path $run | Out-Null
python -m ste_promax render examples/suite/retry-explanation.json --output-dir "$run/story"
python -m ste_promax render examples/suite/caption-documentation.json --output-dir "$run/visual-document"
```

Read the actual `manifest.json`, warnings, gallery, and output before reporting
success. Do not choose a generated filename by guessing the title's slug; use the
manifest's file records.
Structured visuals also export `visual-01.svg`, `visual-02.svg`, and so on.
The manifest maps each file to its source location; the files match the native
SVG used in HTML. Keep the adjacent explanation, text/data equivalent, source
caption, and qualifications when sharing an extracted image.

## Supported input shapes

### Documents and standalone visuals

Markdown uses the ordinary document renderer. A structured report has a `title`
and `sections` array. Each section names a supported `kind`; `sec` sections nest
children under `body`. Native `diagram` and `chart` objects work inside sections,
as a story beat's `visual`, or at the root with an explicit `kind`.

Prefer structured fields over raw HTML. A raw `.html` file or JSON `body_html`
requires `--trusted-html` after review; the flag is permission to render
executable content, not sanitization. Nonempty report `sections` takes precedence
over `body_html`. Do not mix a root story/visual shape with report fields.

### Diagrams

All diagrams need `type`, `title`, and `description`; `caption` is optional.
Text fields are literal text, not Markdown, HTML, or script.

| Type | Shape | Meaning and limits |
| --- | --- | --- |
| `flow` | `nodes: [{id, label, detail?}]`, `edges: [{from, to, label?, style?}]`; optional `direction: LR` or `TB` | 1–16 nodes, 0–32 edges; at most 16 incident edge ends per node, counting self-links twice |
| `sequence` | `participants: [{id, label}]`, `messages: [{from, to, label, note?, style?}]` | 1–12 participants, 1–32 messages; array order is message order |

IDs must be unique in the node or participant list; endpoints must exist. Use
the schema's text/layout bounds. Flow placement follows input order, not an
automatic topological ordering. Feedback, parallel edges, and self-links can be
valid relationships; dense graphs may still have crossing lines.

**Order is not duration.** Sequence spacing does not encode latency or elapsed
time. If the source leaves two events unordered, retain that ambiguity in prose
rather than invent an ordering. There is no native parallel-execution or
continuous-time timeline notation here.

An arrow documents the relationship the author supplies; it does not prove cause,
control, or approval. `solid` and `dashed` are presentation styles, not built-in
evidence categories. Describe a material distinction in text.

### Charts

Charts need `type: bar` or `line`, `title`, `description`, `categories`, `series`,
and `y_label`. Include units in `y_label`; the validator can require a label but
cannot determine whether the units are meaningful or correct.

- Supply 1–40 categories and 1–6 series. Each series has a unique `label` and a
  `values` array matching the category count. Values are finite numbers or `null`,
  not numeric strings or booleans.
- `null` means unavailable. Zero and negative values remain observations. Line
  paths break at missing values; the renderer does not interpolate missing data.
- Optional `lower` and `upper` arrays must both exist, match categories, and
  enclose each present value. A missing value cannot have present bounds. Paired
  `null` bounds mean unavailable uncertainty for that point.
- Intervals require `uncertainty_label`. State whether the source supplied a
  range, percentile interval, confidence interval, or another quantity. No
  statistical interval or confidence level is inferred.
- An optional `domain: [min, max]` must contain every value and bound. Bar domains
  must include zero. A nonzero line baseline should be explained, not concealed.
- Categories are equally spaced, even when labels are dates. A line chart is not
  a continuous time axis. It cannot faithfully encode unequal elapsed intervals.

For example, save this fictional standalone chart as `chart.json` and render it
with the same `render` command:

```json
{
  "kind": "chart",
  "type": "line",
  "title": "Illustrative queue snapshots",
  "description": "Fictional scheduled samples; the middle depth is unavailable.",
  "categories": ["Minute 0", "Minute 1", "Minute 2"],
  "series": [{"label": "Waiting jobs", "values": [2, null, 1]}],
  "y_label": "Waiting jobs (count)",
  "x_label": "Scheduled snapshot",
  "domain": [0, 3],
  "caption": "Illustrative only. Missing is not zero; no cause or recovery is established."
}
```

The visible table retains parsed numeric values while tick labels are rounded
guides. JSON decimal tokens that would lose their stated value during conversion
(such as `1e-400` becoming zero) are rejected before output. JSON normalization
need not retain a number's original lexical formatting;
the saved source bytes do. Split unsupported or dense charts deliberately rather
than silently dropping values or shrinking labels beyond readability.

### Stories

Use a root `kind: story` and integer `version: 1`. A story also requires `title`,
`audience`, `question`, `purpose`, `summary`, `sources`, `claims`, and `beats`.
Optional `context` and `limitations` describe scope and material qualifications.
Use `schema story` or a complete supplied fixture as the starting point.

| Part | Fields and contract |
| --- | --- |
| Source | `{id, title, url?, locator?, note?}`; at most 100; URLs are not fetched |
| Claim | `{id, type, text, source_ids, scope?, uncertainty?, attributed_to?, basis?}`; at most 200 |
| Beat | `{id, title, claim_ids, role?, text?, narration?, visual?, question?}`; 1–32 |
| Visual | One validated `diagram` or `chart` object |
| Question | `{prompt, answer?}`; an omitted answer stays unanswered |

Story IDs start with a lowercase letter and use lowercase letters, digits,
underscores, or hyphens, up to 64 characters. Duplicate IDs and dangling
references fail validation. Claim types are:

| Type | Author's responsibility | Structural requirement |
| --- | --- | --- |
| `observation` | Preserve what was observed and its scope | At least one registered source |
| `attribution` | Name whose statement this is; do not endorse it by relabeling | Sources and nonempty `attributed_to` |
| `inference` | Explain the reasoning and keep alternatives/uncertainty visible | Sources and nonempty `basis` |
| `proposal` | Keep action, conditions, and incomplete status explicit | `source_ids` array, which may be empty |

**The truth boundary:** IDs and field validation establish structural links only.
They do not show that a source exists, is authentic, entails the claim, or supports
a causal explanation. Review the actual source and arithmetic. Free-form summary,
beat text, captions, questions, and authored narration can disagree with a valid
ledger. The engine cannot adjudicate that conflict.

## Pace and frame the explanation

Use one manageable idea or comparison per beat. Begin with a concrete example
when it helps the audience, expose intermediate states, and put relevant words
near the visual they explain. Do not add motion or speech as a decorative quota.

The story initially shows all content. Guided mode provides Previous/Next and
outline navigation; readers can return to all content. Questions can disclose an
authored answer. Choose a question that reveals a likely misunderstanding, such
as confusing an observed range with a confidence interval. Do not grade mastery
from progress or answer-disclosure events.

Review framing before delivery:

- Which data, claims, options, or periods were selected or excluded?
- Does order, color, wording, or axis range imply a stronger finding?
- Are contrary evidence and qualifications visible at the relevant point?
- Are an observation, someone's explanation, an inference, and a proposal distinct?
- Does a time sequence imply cause, duration, or closure that the source lacks?

Unused claims stay in the complete ledger, but their presence alone does not
make narrative selection balanced. Explain material exclusions.

## Inspect the companion outputs

For every `render`, inspect saved `source.<extension>`, normalized `input.json`,
the HTML/`.DESIGN.md`/`.meta.yaml` triple, `gallery.html`, and `manifest.json`.
The manifest records artifact hashes and design lint separately from semantic
and visual review.

Story render adds:

| File | What to review |
| --- | --- |
| `story.md` | Prose, visual text/data equivalents, qualifications, complete claim/source ledger |
| `storyboard.json` | Ordered beats, structured visuals, claims, sources, and review diagnostics |
| `narration.json` | Draft cues; author-supplied speech or a literal claim outline; `review_required` remains true |
| `evidence.json` | Complete supplied story and explicit unperformed source-verification status |

Check that wording, units, order, uncertainty, and source IDs agree across formats.
An author's custom narration is preserved, not automatically reconciled with the
ledger. Default narration is a draft outline, not a polished or complete spoken
description of every visual and story-level limitation.

## Prepare narration without claiming an export

Inspect `narrate --help` in the selected bundle first. Give it the original story
JSON, not `narration.json`. Choose either a local installed voice or supplied PCM
WAV files; do not combine the two options.

Using `$bundle`, `$source`, and the existing `$run` from the unrelated-directory
example, choose **one** command. Replace the voice/audio path with a real local
resource:

```powershell
python "$bundle" narrate "$source" --output-dir (Join-Path $run 'media-local') --voice 'INSTALLED VOICE NAME'
python "$bundle" narrate "$source" --output-dir (Join-Path $run 'media-supplied') --audio-dir 'C:\path\to\beat-audio'
```

The equivalent repository-root command begins `python -m ste_promax narrate`.
The media destination must not exist, and its parent must already exist; unlike
`render`, an existing empty destination is not accepted. Keep paths local and
free of symlinks, junctions, or parent traversal.

`--audio-dir` contains `<beat-id>.wav` for each beat, not numbered or title-slug
filenames. The native route checks integer PCM, mono/stereo, 8/16/24/32-bit audio
at 8,000–192,000 Hz, complete frames, and a changing signal. This establishes
neither intelligible speech nor agreement with the script. Listen to the files.

Preparation retains source/companions and writes measured `timeline.json`,
`transcript.txt`, whole-beat `captions.vtt`, a composition `video/index.html`, a readable
`review.html`, and a preparation manifest. The `video/` directory contains the
HyperFrames composition and its WAV assets; source/evidence/review documents stay
outside it. Open **`<output-dir>/video`**, not the outer evidence bundle, in
HyperFrames. Studio otherwise treats ordinary review HTML as another video
composition. Oversized titles, complete text, or
visuals fail media preflight; split the beat without discarding qualifications.
Long captions may remain sidecar-only rather than fit into the composition;
inspect warnings and the actual composition. Timing follows real WAV duration,
not a words-per-minute estimate. Captions are not word-aligned.

Sequence messages can become ordered visual stages within a beat. Their stage
durations are demonstration pacing divided from the audio, not measured event
durations or verified speech-to-message alignment. Review that alignment before
delivery; audio must allow at least one second per message.

A successful preparation manifest says `prepared_not_rendered`. It is not a
HyperFrames check, browser preview, listening review, or encoded movie.
`partial_failure_not_rendered` retains failure evidence; do not call it success
or overwrite it for a retry. A requested MP4 needs a separate available export
workflow and inspection of the actual picture, audio, duration, and final frame.

After a user approves the final Studio preview, an installed HyperFrames 0.7.103
export can use the following command. The parent of the new MP4 path must already
exist; do not overwrite an earlier export:

```powershell
hyperframes render artifacts/retry-media/video --output artifacts/retry-explanation.mp4 --quality high --fps 24 --strict --no-best-effort
ffprobe -v error -count_frames -show_format -show_streams -of json artifacts/retry-explanation.mp4
```

Check the installed CLI's help before choosing quality names: 0.7.103 accepts
`draft`, `standard`, and `high`, but rejected the newer documentation's `delivery`
alias. Run against `video/`, not its evidence parent. Inspect decoded picture and
audio, not only the exit code. Preserve the preparation manifest and record export
verification separately. Export permission does not authorize uploading the movie.

## Delivery review and remaining gaps

| Check | Evidence to record | What it does not prove |
| --- | --- | --- |
| Source/claim review | Source locators, arithmetic, qualifications, conflicts | Authentication or authority to act |
| Native render | Real output, manifest hashes, warnings, saved input | Correct interpretation or learning |
| Visual equivalence | All relationships/values present in readable alternatives | Every assistive-technology combination works |
| Browser behavior | Keyboard, focus, controls, narrow width, contained scrolling, noncolor cues, reduced motion | Full WCAG conformance |
| Reading alternatives | No-JavaScript content and actual print output | A CSS rule alone is sufficient |
| Narration/media | Listened-to speech, timing, readable visuals/captions, export status | Correct speech from a PCM signal check |

Name unperformed checks explicitly. Keep HTML trust, source review, design lint,
browser QA, media preparation, and actual export separate. Do not claim a learning
benefit without an appropriate evaluation of this artifact and audience.
