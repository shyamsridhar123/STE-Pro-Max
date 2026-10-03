# Plugin-first installation and example-led README

Date: October 3, 2026. Baseline: `4bd0169`.

## Outcome

Install through the agent host's real plugin manager, then ask for a useful
explanation. The README must explain Simplified Technical English and Karpathy's
output ideas, show a few excellent real examples, and stay short.

## Product boundary

The installed product is the three authoring skills plus self-contained example
templates. Writing and authoring HTML/SVG use the host's existing model/file tools:
they do not require Python, pip, uv, a package bootstrap hook, or a new service.
The deterministic Python renderer remains an explicit advanced/developer option,
not the default plugin runtime or an installation prerequisite. Do not imply that
native host authoring has the optional renderer's schema-validation guarantees.

## Changes

1. Use native persistent marketplace install/update/remove; no custom plugin
   manager, configuration-file editing, or session-only flag sold as installation.
2. Test real lifecycle operations in isolated host profiles. Record actual
   cached manifests, skills, versions, and removal state, not only JSON validity.
3. Route default skills to native host authoring and dependency-free templates.
   Preserve evidence review, optional deterministic tools, and video approval.
4. Add three compact, polished, self-contained examples: retry sequence,
   release decision, and percentage-point/rate lab. Include inspectable source
   and fictional-data qualifications. No external fonts, assets, or runtime calls.
5. Put readable screenshots/animation and concise prompts in a README with
   a hard budget of 150 nonblank lines. Move lifecycle/reference detail to docs.
6. Publish a versioned source tag only after verification, so native installs do
   not depend on an unmerged default branch. Keep the existing PR unmerged.

## Verification

- Preserve the original source ZIP and all existing renderer tests.
- Browser-test new examples at desktop/mobile, keyboard, controls, reset, and
  reduced motion; capture actual screenshots/animation without fake UI.
- Validate README images/links and the STE/Karpathy source distinction.
- Native host install, update/reinstall, disable/enable where supported, and
  uninstall in isolated profiles. No writes to normal user plugin settings.
- Verify source bundle and exact tagged commit, run CI, report any untested host
  surface explicitly. No more claims that a Python bootstrap is plugin install.
