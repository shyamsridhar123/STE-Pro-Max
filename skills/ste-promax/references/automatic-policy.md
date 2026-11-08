# Native checks without host-tool restrictions

STE does not restrict shell, Code Mode, file tools, browser tools, external agents,
or other integrations. Loading a skill or using an STE tool does not change that.
No off command or new session is needed. Existing host permissions and user
authorization for external actions still apply.

1. Keep a short rewrite in the conversation. `ste_check_prose` offers advisory
   diagnostics when useful, not factual certification or automatic chat policing.
2. For checked artifact production, use `ste_write_artifact`, `ste_render_bundle`,
   or the relevant native operation. These tools check their own inputs, evidence,
   workspace paths, and outputs automatically, without a manual approval step.
3. Use ordinary host tools when they fit the task. Such actions do not receive
   native STE validation or receipts. Report a failed native check honestly;
   using a different tool does not turn that failure into a pass.
4. Use `ste_status` when runtime information is needed. A missing runtime prevents
   native checked operations, not ordinary authoring or unrelated work. Do not
   silently install packages or claim checks that did not run.
5. Verify the actual result and state material limits. Static inspection is not
   browser QA; prepared narration is not an encoded movie. SkillC does not prove
   source truth, JavaScript safety, pronunciation, visual quality, accessibility
   conformance, or reader understanding.

Tools may carry a host/server prefix. Copilot retains hooks only to bind native
STE requests to the correct workspace. OpenCode registers tools and skills,
without session-wide interception. The `ste-author` agent has no STE tool allowlist.

See [the integration guide](../../../docs/SKILLC_GATE.md) for runtime setup,
native validation, limitations, and attribution.
