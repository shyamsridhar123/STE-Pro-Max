# Output modes

Use the mode that serves the request. All modes inherit the skill's factual-fidelity
and scope rules. None of these routes implies permission to publish.

## Prose

Keep the supplied format and requested register. Use the relaxed profile by default.
`python -m ste_promax check` flags mechanical length issues without changing the source;
`--fail-on-findings` is an explicit CI option, not the normal writing experience.
Review dictionary meanings, sentence purpose, causal support, and safety content
manually. There is no meaningful computed “80% STE” score.

## Diagrams and images

Choose the form by the relationship: sequence for time, a flow for decisions,
boxes and edges for architecture, or a chart for quantities. Label direction,
units, scope, evidence, and uncertainty. Give a text equivalent.

Prefer inline SVG for precise diagrams that stay editable. If raster artwork would
actually help, use an available image tool and label generated content. Never
substitute an invented photograph, diagram relationship, or chart datum for evidence.
Use the same nouns and facts as the accompanying prose. Export and inspect the
actual image before claiming it exists.

## Interactive HTML with the native PaperBoard-derived renderer

The `ste_promax/` package contains the renderer copied and adapted from PaperBoard.
It does not shell out to the installed `paperboard` command or require its checkout.
Run these commands from this repository's root.

```text
python -m ste_promax render explanation.html --title "Explanation" --output-dir artifacts/new-explanation --trusted-html
```

Use a **new or empty output directory**. The native command preserves source and
normalized input, renders HTML, and checks its `.DESIGN.md`, `.meta.yaml`, and
`gallery.html`. Read its manifest and warnings. Local design-token validation is
separate from factual review, browser QA, and formal standard compliance.

For Markdown:

```text
python -m ste_promax render explanation.md --output-dir artifacts/new-explanation
```

Use the native section graph for conventional reports. For authored interactive
content or inline SVG, JSON `body_html` is the escape hatch. Raw `.html` and JSON
with `body_html` require `--trusted-html`; ordinary Markdown escapes raw markup.
Nonempty `sections` takes precedence over `body_html`.

Keep executable HTML separate from untrusted source material. Render source strings
as text or escape them; never interpolate untrusted material into script or markup.
Provide labeled controls, a reset path, valid empty/error states, keyboard access,
text equivalents, and reduced-motion behavior. Show when values are illustrative.

Test the real output at desktop and phone widths. Exercise default, changed,
boundary, invalid, and reset states; check console errors and overflow. Verify
gallery links. The copied default template uses local CSS and system fonts rather
than remote Google Fonts. Authored content can still reference external assets;
inspect the asset report and browser behavior before calling an artifact offline.

Keep the normalized input and design sidecar for reproduction. Do not overwrite
unrelated galleries or artifacts. Changes belong in this repo's copied renderer,
not in a wrapper around someone else's executable.

## Narrated explainers

Build one concrete explanation with synchronized explanatory motion, rather than
a slide deck with incidental narration. A 3Blue1Brown-inspired approach means
geometric reasoning, visible intermediate states, and concept-driven motion—not
copying a person's voice, footage, or identity.

Use an installed HyperFrames workflow for HTML-to-video creation. Read its current
skill/CLI instructions and preserve its review and render gates. Use local renders
for local work; no hosting or new video platform is required.

1. Establish the source, one learning objective, a short script, and a visual beat plan.
2. Validate the script's facts before synthesizing speech.
3. Choose narration:
   - **Free/local Windows path:** run the bundled `scripts/narrate.ps1` with
     Windows PowerShell 5.1. It uses installed System.Speech voices, creates PCM
     WAV, refuses overwrites, and sends nothing to a service.
   - **Optional ElevenLabs:** use an already authorized connector/workflow when the
     user chooses it. Check permission to transmit the text and any cost; do not
     treat Karpathy's example as a required provider or store keys in the repo.
   - Elsewhere, inspect an already installed local TTS engine. If none exists,
     report the gap instead of silently installing or switching to a cloud service.
4. Set the visual timeline from real audio duration. Include a transcript and
   captions when useful. Avoid clipped narration and unearned causal arrows.
5. Check the composition, inspect representative frames, listen to the result,
   and distinguish a browser preview from an exported video.

The repository's small video fixture is an integration example, not a promise that
every fresh machine has HyperFrames, a browser, FFmpeg, or a speech voice installed.

## Oversight and disposable software

Make assumptions and limits visible in the artifact, not only in the chat.
Prefer a one-question calculator or explainer over a multi-page app. Reuse the
user's tooling, save source, and stop when the learning objective is demonstrated.
The user remains responsible for consequential interpretation; automation does not
turn estimates into commitments or demonstrations into live systems.
