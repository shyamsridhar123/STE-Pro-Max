# Validation evidence

Verified locally on October 3, 2026. This records what ran, not an assertion of
formal STE certification or universal host compatibility.

## Suite v0.2.0

### Code, skills, and source preservation

- Full local run: **279 tests passed**, no skips, after the final video-directory
  separation. Evidence: `artifacts/suite-tests-20261003-final3.log`.
- Ruff passed; Pyright reported **0 errors and 0 warnings**.
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

`tools/verify_browser.mjs` exercised **42 Chromium scenarios** across the five
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

### Narrated story and the remaining export gate

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

**No MP4 export or manual listening approval is claimed.** The final Studio
preview is open and shows **0 errors, 1 warning**; export approval was requested.
The preview/export gate remains open. A prepared timeline, a successful browser
check, and nonconstant PCM do not establish a finished, reviewed movie.

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
- The wheel was built using existing bundled build tools after the ordinary
  Python environment lacked its build backend. No package was installed or
  fetched to make the build pass.

Schema/discovery evidence is under `artifacts/plugin-schema-20261003/` and
`artifacts/plugin-host-checks-20261003/`. See `SUITE_AUDIT.md` for the remaining
payload, CI, and media gates. Generated evidence is workstation-local and excluded
from the distributable plugin.

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
original source, normalized input, and hash manifest. No installed PaperBoard
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
`PROVENANCE.md`. The original PaperBoard checkout remains unchanged. Workstation
memories and orchestration state are excluded from distribution.

Optional paid narration, hosted publishing, formal ASD-STE100 conformance, and
full cross-host installation remain outside this validation. CI results are
available in the repository's Actions history; this report records the local run.
