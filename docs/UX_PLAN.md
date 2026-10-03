# Low-friction authoring and repository refresh

Date: October 3, 2026. Baseline: `aca2811`.

## Requested outcome

Give STE-Pro Max a standalone identity, a useful first result with minimal setup,
and a visually strong README that shows what actually works. The owner has
authorized removing the prior product branding. Preserve the Apache-2.0 license,
the owner's copyright, original imported writing files, and existing user work.
This is a current-source cleanup, not a destructive Git-history rewrite.

## Behavior lock and boundaries

Before edits, run the existing regression suite. Preserve `render`, `schema`,
`check`, and `narrate` machine contracts and all factual-fidelity/trust boundaries.
No new application dependency, hosted service, hidden provider call, automatic
publication, global installation, or bypass of video-review approval.

## Implementation slices

1. Rename the native template, design, generator metadata, comments, and footer.
   Update affected tests and packaging paths. Remove obsolete brand assertions.
2. Add `start [source]`: a packaged fictional example when no source is supplied,
   automatic fresh output paths, a short useful result, opt-in local opening,
   and JSON for agents. Add a read-only `doctor` with actionable diagnostics.
   Keep the lower-level commands compatible.
   A user-invoked `quickstart.py` prepares a private workspace environment and
   runs `start`; it must never change global Python or silently take over an
   existing environment. Subsequent runs reuse the environment without network
   installation. `--no-install` and `--no-open` support constrained execution.
3. Reduce agent-side choices: infer the smallest useful medium from the request,
   reuse supplied source/audience, use safe defaults, and ask only when a material
   factual, privacy, cost, or execution boundary requires a decision.
4. Replace the README with a generated GPT Image 2.5 hero, a real-output showcase,
   one obvious quickstart, copyable agent prompts, host-specific setup, capability
   and input/output coverage, troubleshooting, and qualified validation evidence.
5. Update manifests, package resources, source notices, and release documentation.
   Keep README assets in the source bundle; no workstation artifacts or secrets.

## Design direction

An editorial engineering instrument: charcoal, warm ivory, and restrained copper.
The hero expresses dense information becoming a clear explanation. It is brand
art, not a product screenshot or measured performance result. Showcase images
must come from actual outputs. README text carries essential meaning and alt
text; never place the only installation command or claim inside an image.

## Verification and stop rule

- Baseline and final regression tests, lint, and all-surface typecheck.
- Exact new CLI examples, empty/error/missing-dependency cases, source
  preservation, repeated invocations, and output-path safety.
- Browser checks for real outputs and a rendered README at desktop/mobile sizes.
- Image and link integrity, archive/wheel execution from an unrelated directory.
- Current tracked source and shipped payload contain no old product references.
- Commit/push only verified changes; keep the repository private and PR unmerged.

Writer and reviewer passes stay separate. Do not call the work complete while
the requested image is missing or the new first-run flow is only documented.

## Integration review repairs

- Share the existing complete input validator at a standard-library-only
  boundary so invalid nested sections fail before any first-run installation.
- Make human CLI summaries safe for legacy Windows output encodings without
  altering Unicode source/artifact paths or agent JSON.
- Install only the two declared runtime requirements into the private
  environment. Running the source bundle does not need a second package build,
  build-backend downloads, or a duplicate staged copy of the engine.
