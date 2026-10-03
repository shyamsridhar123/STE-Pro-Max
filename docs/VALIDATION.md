# Validation evidence

Verified locally on October 3, 2026. This records what ran, not an assertion of
formal STE certification or universal host compatibility.

## Plugin-first v0.4.0

The default installed workflow is now three native skills plus standalone
HTML/SVG starters. It uses the host's existing authoring tools, not `quickstart.py`
or a Python environment. The deterministic engine and media tools remain
explicitly optional. This corrects the v0.3 runtime-first onboarding claim below.

### Native installation, not just manifest discovery

Fresh child processes used isolated `COPILOT_HOME`/`COPILOT_CACHE_HOME`,
`CLAUDE_CONFIG_DIR`, or `CODEX_HOME` plus isolated home discovery. The normal
user's config hashes remained unchanged.

| Host version tested | Actual local-marketplace evidence |
| --- | --- |
| Copilot 1.0.90-0 | Native persistent install; fresh list reports three-skill plugin enabled; disable/enable; update reports live source; uninstall disables that live source |
| Claude Code 2.1.288 | Native user-scoped install; fresh list and details show v0.4.0 and three skills; disable/enable; update check; uninstall leaves empty installed list |
| Codex CLI 0.147.0 | Native `plugin add`; fresh process reports installed/enabled v0.4.0 and cache path; `plugin remove` leaves empty installed list |

These were actual plugin-manager operations, not `--plugin-dir` discovery.
They did not invoke a paid model or prove every host's model-driven behavior.
Codex desktop UI installation/toggling remains separate from these CLI checks.

Local raw-repository installation exposed an important distribution difference:
some hosts copied ignored workstation files into their local cache. They were
not uploaded. The documented consumer path therefore uses the tagged remote;
local installation should use the whitelisted source bundle, not a dirty
checkout. Release lifecycle tests inspect the tagged cache, version, skills,
templates, and subsequent removal in separate profiles.

The **public `v0.4.0` tag** was then tested through the exact README commands
against GitHub—not a local source alias:

- All three hosts downloaded, installed, and exposed v0.4.0 in a fresh process.
  Installed skills/templates matched the tag bytes; no local memory, artifacts,
  environment, or orchestration files entered those release caches.
- Copilot and Claude passed update-at-the-pinned-version, disable/enable, and
  uninstall. Codex passed marketplace upgrade, persistent installed discovery,
  and removal. All three installed-plugin lists were empty after removal.
- The three examples executed directly from each installed copy: retry counts,
  rate/zero-baseline behavior, and release-answer disclosure passed without
  Python or outgoing HTTP(S) runtime requests.
- Normal user config hashes stayed unchanged. Tests used installed CLI versions
  from the table above; no live model invocation or Codex desktop UI test occurred.
- Source plugin: **84 files** compared with commit
  `1b50fb0fed3bfa4f9f7c783280b0979c54fe06b3`.
  **353 local tests**, lint/typechecks, three skill validators, and Windows/Ubuntu
  CI run **37158472362** passed on that source.

The [v0.4.0 release](https://github.com/shyamsridhar123/STE-Pro-Max/releases/tag/v0.4.0)
contains the plugin ZIP, eight-file standalone example ZIP, source hashes, and
the native lifecycle receipt. Anonymous downloads matched the local SHA-256
values. The immutable tag was not moved after testing.

### Real examples and concise README

- Retry lab: **60 browser checks**, including exact stage/counter transitions,
  play/pause/reset, keyboard, responsive layout, print, no-JavaScript and no
  outgoing runtime requests.
- Release brief and rate lab: **112 checks**, including default/changed/invalid
  rates, zero baseline, source disclosures, reader answer, keyboard, narrow
  layouts, print/no-JavaScript and no outgoing requests.
- Three static screenshots and a seven-frame GIF were captured from actual
  example HTML. The GIF repeats once; a static preview is linked. These are not
  generated product mockups or live-production measurements.
- The short README defines Simplified Technical English, links Karpathy's exact
  post, distinguishes inspiration from certification, and presents native
  installation. Detailed setup moved to `PLUGINS.md`.
- A local GFM-compatible preview passed at 1280/375/320 pixels: four visible
  images, all install disclosures, and 16 local links/anchors. No horizontal
  page overflow or external runtime requests.

Source, test, native lifecycle, and image evidence is under
`artifacts/plugin-first-20261003/`. The release's source/plugin and examples
archives are assembled from the verified tagged source. Source ZIP immutability,
native renderer regressions, lint, typechecks, and all three skill validators
remain required; authoring templates do not claim engine checks that never ran.

## UX and identity refresh v0.3.0

### New first-use behavior

- `start [source]` accepts a source or runs the packaged fictional example.
  It chooses a fresh output directory and has opt-in `--open` and machine `--json`.
- No-command help and read-only `doctor` make the next action discoverable.
  Diagnostics check declared dependency versions without importing render
  packages or invoking optional media tools.
- The explicit `quickstart.py` reuses a ready interpreter or a private workspace
  `.ste-env`; it never mutates global Python or another existing environment.
  Setup installs only runtime requirements, not a second engine/build backend.
- Full input validation, including nested sections, runs before setup. The
  shared preflight imports with `python -S`, with no third-party packages.
- Legacy output encoding no longer prevents a successfully rendered Unicode
  path from reaching the requested browser-open step. Exact file paths and
  JSON remain unchanged.

### Local checks

**352 tests passed**, including original preservation tests and new onboarding,
bootstrap, Unicode, and README contracts. Ruff and all-surface Pyright passed;
all three skills validated in UTF-8 mode. Evidence:
`artifacts/ux-refresh-20261003/final/`.

The five suite examples were rendered again under the standalone identity.
**30 browser scenario records passed** at 1280, 375, and 320 pixels, with
keyboard/history, no-JavaScript, print, and no-outbound-request checks.
Six of those records cover each artifact; the non-story control record is
explicitly not applicable, not an interaction test. A separate onboarding
browser pass checked the built-in demo. These are bounded Chromium checks,
not full accessibility certification.

The README was rendered locally with GitHub-flavored Markdown semantics at the
same three widths. Both raster assets loaded; disclosures expanded; all **25**
local links/anchors resolved; there was no page-level horizontal overflow.
This is a GFM-compatible preview, not a pixel-identical GitHub rendering claim.
Evidence: `artifacts/ux-refresh-20261003/readme-final/`.

The requested hero was generated with **GPT Image 2.5 Sunburst**, inspected, and
saved into `docs/assets/hero.png`. The showcase is assembled from actual output
captures, not generated screenshots. See `docs/assets/README.md`.
All current tracked source and new outputs use the standalone product identity;
historical Git commits and previous local evidence were not rewritten.

Ready-interpreter quickstart executions succeeded and preserved artifact hashes.
Two fresh-environment local attempts encountered a Python package-server TLS
handshake failure. The command failed visibly, retained partial evidence, and
did not disable TLS checks.

### Real first-time setup and portable delivery

GitHub run **37154588384** passed on
`8251b027e4585f7b578011b8780ddbb692fed8ca` for **Windows and Ubuntu**.
Both jobs created a clean interpreter with no render dependencies, ran the
actual launcher to install into a private workspace environment, then rendered
a supplied source with `--no-install`. Each checked **17 output hashes**,
unchanged environment bytes on reuse, preserved source, and unchanged bundle.
This is real setup evidence, separate from the workstation TLS failure.

The first CI pass exposed a genuine isolated-interpreter import failure when
preflighting a supplied source. The launcher now imports its shared preflight
from the already-validated bundle root and restores its import path afterward.
A real `-I -S` subprocess regression confirms that path without site packages.

The source bundle includes both README images and the first-run helper. A saved
v0.3 snapshot matched **74 files** to committed source; the wheel matched all
**21 runtime files** and **27 hashed RECORD entries**. Both extracted archives
executed `doctor`, no-input `start`, schema, story/SVG render, and provided-PCM
narration from unrelated directories; the source plugin also ran quickstart
with installation disabled. The final delivery repeats these comparisons after
documentation closeout under `artifacts/ux-refresh-20261003/release/`.

Strict Claude plugin and marketplace validation passed; Copilot session-only
discovery reported the external v0.3.0 plugin. The portable descriptor passed
its saved official schema. GitHub's actual README-render endpoint returned the
new hero and showcase references. The repository description/topics now use the
standalone identity. Visibility remains private, and no host was globally installed.

Host evidence: `artifacts/ux-refresh-20261003/final/`.
CI and repository evidence: `artifacts/ux-refresh-20261003/github/`.
Codex Desktop runtime installation, full three-host model execution, and full
accessibility certification remain untested; no such claim is made.

## Suite v0.2.0

### Code, skills, and source preservation

- Final local run: **279 tests passed**, no skips, including the real Windows
  speech tests. Evidence: `artifacts/test-typing-closeout-20261003/`.
- Ruff passed across the package, tests, builder, entry point, and examples.
  Pyright on those same surfaces reported **0 errors and 0 warnings**.
  The earlier production-only check did not cover tests; a broader pass exposed
  100 test-fixture diagnostics. Explicit fixture types and assertion narrowing
  resolved them without changing production code or removing test assertions.
- All three working skill manifests passed the installed skill validator.
- Real bundle tests run `schema`, story/SVG rendering, and provided-PCM media
  preparation from a separate workspace. Preparation does not emit an MP4.
- Literal JSON precision-loss, invalid purpose, hostile Markdown, escaped table
  pipes, saved-output tampering, Unicode host pipes, and media failure states have
  regressions. Duplicate JSON fields cannot replace earlier qualifications.
- The original ZIP and extracted files retain their pinned hashes. The single
  narration helper moved into the Python package without byte changes:
  `D2A1E68E79DC8C535098AA44769BFAA9BA35136ED75270D6C5BBC1221D24FAE4`.
  It is included in both source bundles and wheel resources.

### Native browser and print evidence

`tools/verify_browser.mjs` recorded **42 passing Chromium scenarios** across the five
suite examples plus dense-visual and tall-sequence fixtures:

- 1280px, 375px and 320px layouts without page-level horizontal overflow.
- Keyboard operation, guided/all-content navigation, browser history, source
  anchors, and focusable figure/table scrolling.
- No-JavaScript content and actual print visibility, including closed answers.
- Seven actual PDFs. All 32 tall-sequence message labels and the text equivalent
  survived extraction; representative pages were rasterized and inspected.
- No observed console errors or outgoing HTTP(S) runtime requests; such requests
  were blocked during this check.

Evidence: `artifacts/suite-verify-20261003-c/browser/`. Dense diagrams may span
printed pages. Screen-reader coverage and complete WCAG conformance are not
claimed. The explanatory and source/data equivalents remain part of delivery;
do not detach an SVG from its material qualifications.
Three scenario records mark story controls not applicable to non-story
documents; these are not 42 independent interaction tests. An independent
closeout inspection matched all 69 manifest-referenced files across the seven
fixtures and their seven source hashes.

### Approved narrated story and verified local MP4

Actual local System.Speech audio for the retry example totals
**34.73804988662132 seconds**: 15.22185941043084 and 19.516190476190477 seconds.
The final preparation reuses those exact hashed WAV bytes. Five message stages
partition the first clip; their pacing is demonstration timing, not measured
event time or verified word alignment. Both whole-beat captions fit on screen.

Final media evidence: `artifacts/retry-media-20261003-d/`.
The HyperFrames project is its **`video/` subdirectory**. Ordinary review HTML
and source/evidence companions stay outside the composition directory so Studio
does not misclassify the review page as a movie.

HyperFrames **0.7.103** checked the final composition at
**1, 4, 7, 10, 13, 18, 26 and 33 seconds**:

- No lint errors, runtime errors, or layout errors.
- **78/78 sampled contrast checks passed**.
- One non-blocking `timeline_track_too_dense` warning: six timed scene elements
  share one track. This is retained and disclosed, not suppressed.
- Representative frames were inspected. Motion-sidecar assertions were not
  enabled; no separate motion-verifier result is claimed.

The user approved the final Studio preview on October 3, 2026. That approval was
used only for a local export. The actual encoded movie is
`artifacts/retry-export-20261003-b/retry-explanation.mp4`:

| Property | Verified result |
| --- | --- |
| Picture | H.264, 1920 × 1080, 24 fps; all **834 frames** decoded |
| Duration | **34.750 seconds**, 0.011951 seconds longer than the source audio; within one frame |
| Sound | AAC, 48 kHz stereo; both original speech clips retained |
| Size | 1,642,732 bytes |
| SHA-256 | `b93e910e8d43f61d5905325be60c84789becaef5729f84c2885c0caedf25f2b4` |

The entire file decoded without errors. Both decoded speech segments were
non-silent, had no clipped PCM samples, and retained their non-silent tails.
Normalized waveform correlation against the source WAVs was **0.988 / 0.981**,
with measured codec delays of about **21.3 / 21.5 ms**, less than one video frame.
These are signal-integrity checks, not manual listening or pronunciation review.

Ten decoded frames, including the first and last, were inspected as a contact
sheet; individual sequence and chart frames were also inspected. The five messages
remain in order, the comparison retains **2 requests / 1 stored record**, both
whole-beat captions fit, and the fictional/sequential qualifications remain visible.
This is sampled picture review, not manual inspection of every frame.

The installed CLI rejected its newer skill documentation's `delivery` alias.
The successful invocation used the installed **`--quality high --fps 24 --strict
--no-best-effort`** options instead. Logs report three workers, hardware browser
GPU, drawElement capture, and eight successful capture self-checks. HyperFrames
also reported fetching/caching Inter fonts; local encoding is not a claim of
network-free execution. Telemetry was disabled and no media was uploaded.

Evidence, exact inputs, commands, probe output, decoded samples, failed initial
diagnostics, and picture review remain under `artifacts/retry-export-20261003-b/`.
The unchanged approved preparation still says `prepared_not_rendered`; the
export evidence is separate. A self-contained viewing folder with the MP4,
transcript, captions, source, and review page is
`artifacts/retry-delivery-20261003/`.

**Manual listening, speech-to-message alignment, and measured event timing are
not claimed.** No publication or global installation followed the approval.

### Host-specific evidence

- The v0.2 portable descriptor passed the fetched Agent Plugins **1.0** schema.
- Claude Code **2.1.288** strictly validated the exact plugin descriptor and
  marketplace file. Validating the directory alone selected the marketplace;
  the plugin file was therefore checked separately.
- Copilot CLI **1.0.90-0** listed `ste-pro-max` **0.2.0** as enabled with
  `source: external` using session-only `--plugin-dir` discovery. No persistent
  installation or model invocation was needed for that check.
- Codex's descriptor/catalog and shared bundle are structurally checked.
  **Codex desktop plugin installation and host-driven execution remain untested.**
- The final wheel was built offline from the saved source bundle using existing
  bundled build tools. No package was installed or fetched to make the build pass.

Schema/discovery evidence is under `artifacts/plugin-schema-20261003/` and
`artifacts/plugin-host-checks-20261003/`.

### Saved payload, extracted execution, and CI

The saved v0.2 plugin ZIP was checked against both committed source
`a75814102aa2bbd28adb05c3d5dc4d9173837293` and the checkout:
**65 payload files matched exactly**. The wheel retained all **18 native runtime
files**, including the single canonical narration helper, and all **24 hashed
wheel RECORD entries** verified. Evidence:
`artifacts/suite-release-check-20261003/verification-b/result.json`.

Both actual archives were extracted into new directories. From unrelated
working directories, each returned version **0.2.0**, exposed the story schema,
rendered a story with two SVGs and 12 checked output files, and prepared the
34.738-second narration with five sequence stages. Input/audio bytes were
preserved. This is real package execution, not a claim of model-driven execution
inside all three hosts.

GitHub run **37149381447** passed both Ubuntu and Windows jobs on that exact
implementation SHA. After test-only typing cleanup, run **37150962561** also
passed both jobs on **`958462dfe605d6930e3582efb1f4e7cba832e6d5`**.
The final delivery snapshot repeats the byte comparison and extracted execution
after documentation closeout; its exact source commit, hashes, and final CI
result are recorded under `artifacts/suite-release-20261003/` and
`artifacts/suite-final-github-20261003/`. Do not substitute an older ZIP or wheel.

Generated media, verification logs, local memory, and orchestration state are
workstation-local and excluded from the distributable plugin and Git history.
See `SUITE_AUDIT.md` for the complete requirements audit and bounded claims.

## Foundation v0.1.0 (historical)

The following records the earlier foundation, not the expanded suite's current
test count or its completion state.

### Automated checks

`python -m unittest discover -s tests -v` — **106 tests passed**, no skips on the
verification machine:

| Area | Tests |
| --- | ---: |
| Native CLI, source preservation, failure reporting | 21 |
| Bundle entry point and missing-dependency handling | 3 |
| Real Windows speech and input/output protection | 13 |
| Plugin assembly, deterministic ZIP, extracted-bundle execution | 13 |
| Original archive/extracted-file preservation | 2 |
| Native rendering, escaping, schema/data-loss and gallery protections | 40 |
| Audio timing, silence/truncation rejection, video preparation | 6 |
| Advisory writing checks | 8 |

Ruff passed for the native package, tests, builder, entry point, and video example.
The installed skill-creator validator reported `Skill is valid!` for
`skills/ste-promax` (run with `python -X utf8` on Windows).

### Native renderer and browser

The actual CLI rendered the reviewed HTML into
`artifacts/clarity-lab-final/`, including the HTML/design/metadata triple, gallery,
original source, normalized input, and hash manifest. No external renderer
command or source-checkout fallback was used. Local design-token lint passed.

Real browser checks covered:

- Default 97.4 → 99.7: **+2.3 percentage points**, **+2.36% relative**.
- 40 → 60: **+20 points**, **+50% relative**.
- Zero starting rate: relative change **undefined**, including 0 → 0.
- Equal, decreasing, and 100% boundary values.
- Empty, out-of-range, and invalid-precision inputs: explicit errors and hidden results.
- Reset, keyboard stepping, and an explicitly labeled truncated-axis zoom.
- Desktop 1280px and mobile 375px: no horizontal overflow.
- Mobile SVG labels enlarged; reduced-motion transitions effectively disabled.
- No browser console warnings/errors or declared external runtime assets.
- Gallery and design-sidecar links point to the generated local files.

The manifest still correctly distinguishes asset detection from a general offline
guarantee. Authored HTML is intentionally trusted, not sanitized.

### Narration and animation

Real System.Speech synthesis used **Microsoft David Desktop** in the default test:
265,912 bytes of non-silent PCM, approximately 6.03 seconds. Installed-voice
selection was also exercised. No narration service or account was used.

The four-cue example prepared actual WAV clips and a **35.242-second** HyperFrames
composition. HyperFrames **0.7.103** checked it at **1, 10, 18, and 28 seconds**:

- No lint, runtime, layout, or contrast findings.
- **52/52 contrast checks passed**.
- Representative generated frames were visually inspected.
- A dedicated motion-sidecar audit was not enabled; do not interpret its zero
  findings as a separate motion test.

The composition, transcript, and captions are prepared. **No MP4 export or manual
listening review is claimed.** Follow the preview/approval/export workflow for an
actual delivered video. Silence/truncation tests do not prove narration quality.

### Plugin and package verification

- Root `plugin.json` validated against the actual Agent Plugins **1.0** JSON Schema.
- Installed Claude's **strict** validator accepted both its plugin descriptor and
  marketplace descriptor with zero errors/warnings.
- Plugin tests build deterministic ZIPs, exclude private state, compare payload
  hashes, and launch/render the extracted native bundle from an unrelated directory.
- A native Python wheel was built offline using already installed build tools.

The shared source bundle targets Copilot CLI, Claude Code, and Codex CLI/desktop.
**No global plugin installation, three-host runtime acceptance test, marketplace
submission, or automatic Python dependency installation was performed.**
Descriptor/schema validation does not replace those host-specific checks.

### Independent review

A separate behavioral pass exercised six writing/mode-selection requests. It
preserved uncertainty, quotations and commands, distinguished percentage points
from relative changes, refused a fabricated compliance score, and kept media local.

An independent code review found two issues, both fixed with regressions:

1. Unsupported structured sections, malformed children, and extra table
   qualifications could disappear. They now fail explicitly before output creation.
2. Audio headers alone could admit truncated or silent clips. Complete PCM frame
   data and signal variation are now checked.

### Preservation and remaining boundaries

The original ZIP and both extracted source files retain the SHA-256 hashes in
`PROVENANCE.md`. Other source checkouts remain unchanged. Workstation
memories and orchestration state are excluded from distribution.

Optional paid narration, hosted publishing, formal ASD-STE100 conformance, and
full cross-host installation remain outside this validation. CI results are
available in the repository's Actions history; this report records the local run.
