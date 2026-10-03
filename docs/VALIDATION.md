# Validation evidence

Verified locally on October 3, 2026. This records what ran, not an assertion of
formal STE certification or universal host compatibility.

## Automated checks

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

## Native renderer and browser

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

## Narration and animation

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

## Plugin and package verification

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

## Independent review

A separate behavioral pass exercised six writing/mode-selection requests. It
preserved uncertainty, quotations and commands, distinguished percentage points
from relative changes, refused a fabricated compliance score, and kept media local.

An independent code review found two issues, both fixed with regressions:

1. Unsupported structured sections, malformed children, and extra table
   qualifications could disappear. They now fail explicitly before output creation.
2. Audio headers alone could admit truncated or silent clips. Complete PCM frame
   data and signal variation are now checked.

## Preservation and remaining boundaries

The original ZIP and both extracted source files retain the SHA-256 hashes in
`PROVENANCE.md`. The original PaperBoard checkout remains unchanged. Workstation
memories and orchestration state are excluded from distribution.

Optional paid narration, hosted publishing, formal ASD-STE100 conformance, and
full cross-host installation remain outside this validation. CI results are
available in the repository's Actions history; this report records the local run.
