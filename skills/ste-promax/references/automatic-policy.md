# Automatic execution policy

Version 0.6.0 uses real SkillC checks throughout STE workflows. The
checks are automatic: do not ask for a stage approval, reviewer, fingerprint, or
token. Do not bypass a failed check through another tool. Existing host access
permissions and authorization for publication or paid services still apply.

1. Use `ste_status` to inspect the available configured runtime when needed.
   A missing runtime or adapter is a reported capability gap, not permission to
   fall back to unchecked shell/file tools or silently install packages.
2. Keep a short rewrite in the conversation. `ste_check_prose` provides advisory
   diagnostics, not factual certification. Host post-turn checks cannot retract
   text already streamed to the user.
3. Use `ste_write_artifact` for authored UTF-8 documents, HTML, and SVG in a fresh
   workspace `artifacts/` directory. For deterministic source rendering, use
   `ste_render_bundle` or the supported native operation. Preserve source material
   and declared local evidence. Never let a document choose executable paths.
4. Use guarded media and inspection tools for their supported tasks. Verify real
   outputs and state what was not inspected. A static scan is not browser QA;
   prepared narration is not an encoded movie. Do not substitute unrestricted
   Code Mode, shell, GUI automation, patches, or external agents when refused.
5. Return the requested result with material limits. SkillC admission and output
   integrity checks do not prove source truth, JavaScript safety, pronunciation,
   visual quality, accessibility conformance, or reader understanding.

Tools may carry a host/server prefix. Copilot CLI's dedicated `ste-author` agent
provides a strict tool list; its ordinary command-hook outer timeouts can fail
open. The guarded executors remain independently checked. Use a new non-STE
session for unrelated work after STE scope starts. Reading these instructions
alone is not evidence that a host adapter is active.

See [the integration guide](../../../docs/SKILLC_GATE.md) for runtime setup,
enforced scope, limitations, attribution, and the release-validation boundary.
