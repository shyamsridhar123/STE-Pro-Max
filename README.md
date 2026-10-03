# STE-Pro Max

Clear explanations without factual drift—in prose, diagrams, interactive HTML,
or a narrated walkthrough.

The renderer is **copied and adapted directly from ATV-PaperBoard**. It runs inside
this repository; it does not wrap the installed `paperboard` CLI or depend on that
checkout. The original STE-ProMAX writing package remains unchanged.

**Plugin targets:** GitHub Copilot CLI, Claude Code, and Codex CLI/desktop. The
native manifests share `skills/ste-promax/` and the same Python engine.
See [plugin packaging and runtime requirements](docs/PLUGINS.md). No global host
installation or automatic dependency installation is performed.

## What is implemented

- **Flexible STE-inspired writing:** factual fidelity first, with an advisory
  checker for sentence and paragraph length. The approximate “80%” idea is a style
  preference, not a computed compliance score.
- **Diagrams and images:** editable SVG explanations, consistent labels, and text equivalents.
- **Interactive HTML:** native rendering, design and metadata sidecars, a local
  gallery, preserved inputs, and an explicit trust boundary for authored HTML.
- **Narrated explanations:** an offline Windows speech helper and a HyperFrames
  example whose timing follows the generated audio. ElevenLabs remains an optional,
  separately authorized alternative.
- **Oversight:** visible assumptions, source qualifications, and real output checks.
  Choose one useful medium; do not generate every format for every answer.

Read the [guideline-to-implementation map](docs/IMPLEMENTATION.md) and
[source evidence](skills/ste-promax/references/source-evidence.md).

## Run it

Python 3.10+ and PaperBoard's two existing Python dependencies, Jinja2 and PyYAML,
are required. From a checkout with those dependencies available:

```powershell
python -m ste_promax --help
python -m ste_promax check examples/clarity-lab/source.md --profile relaxed --json
python -m ste_promax render examples/clarity-lab/source.md --output-dir artifacts/prose-demo
python -m ste_promax render examples/clarity-lab/explanation.html --trusted-html --title "Clarity Lab" --output-dir artifacts/clarity-lab-demo
```

Use a new output directory for each run. A successful render preserves its input
and produces HTML, a `.DESIGN.md`, a `.meta.yaml`, `gallery.html`, and a manifest.
Read the manifest: local design validation is not a factual or accessibility audit.

For an isolated installation on another machine:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e .
.venv/Scripts/python.exe -m ste_promax --help
```

On macOS/Linux, the virtual environment's executable is `.venv/bin/python`.
The installed console command is `ste-promax`.

### Clarity Lab

The interactive example explains a fictional change from **97.4% to 99.7%**.
Change the values, compare percentage points with relative change, zoom the
explicitly labeled axis, and test a zero baseline. It never invents a cause.

![Two measures of an illustrative change](examples/clarity-lab/diagram.svg)

The default template uses local CSS and system fonts. Source-authored external
assets are still possible; they are reported, not silently downloaded or removed.

### Local narrated example

This optional path needs Windows PowerShell 5.1 and an installed speech voice.
It uses no cloud account, API key, voice cloning, or speech-service upload.

```powershell
powershell.exe -NoProfile -File skills/ste-promax/scripts/narrate.ps1 -ListVoices
python examples/narrated-demo/prepare.py --output-dir artifacts/narrated-demo
```

Preparation writes actual WAV clips, a transcript, captions, a measured timeline,
and `index.html`. It does **not** claim to have exported a movie.

If HyperFrames is already installed, inspect the composition:

```powershell
hyperframes check artifacts/narrated-demo --json
hyperframes preview artifacts/narrated-demo
```

After reviewing and approving the preview, export with the installed CLI:

```powershell
hyperframes render artifacts/narrated-demo --output artifacts/narrated-demo/explainer.mp4 --quality draft
```

Follow the installed HyperFrames workflow for a real new video, including its
review/render gates. Check the final movie's audio, timing, and frames; a valid
composition or generated WAV alone is not proof of a successful export.

## Agent workflow

`AGENTS.md` routes work to the project-local
[STE-ProMAX skill](skills/ste-promax/SKILL.md). It contains the prose policy,
medium-selection rules, safety boundaries, and output checks.

Use the current project skill rather than silently replacing a global installation.
Its renderer commands run from this repository; copying the skill folder alone is
not a full installation of the native renderer.

For plugins, keep the complete bundle. Its root entry point also runs from an
unrelated workspace: `python "<plugin-root>" <command> ...`.

## Verification

```powershell
python -m unittest discover -s tests -v
```

Speech synthesis tests run on Windows and explicitly skip unsupported platforms.
The video-preparation tests use deterministic test audio; separate Windows tests
exercise real speech. See [validation evidence](docs/VALIDATION.md) for the actual
integration runs and any remaining gaps.

## Boundaries

- This is **not ASD-STE100 certification**. Approved vocabulary, exact word-counting
  rules, technical naming, procedural safety, and factual review need human judgment.
- `--trusted-html` allows executable authored content; it is not a sanitizer.
- The included numbers are examples, not production metrics.
- Nothing is hosted or published by the renderer. Generated artifacts and
  workstation-local memory are excluded from Git by default.
- No paid narration provider is configured or claimed to be tested.

## Provenance

The PaperBoard-derived files retain Apache-2.0 attribution; see [NOTICE](NOTICE),
[LICENSE](LICENSE), and [provenance](docs/PROVENANCE.md).
The original `STE-ProMAX.zip` and root `ste-promax/` files are preserved imports.
The working skill is under `skills/ste-promax/`.
