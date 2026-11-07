# What SkillC does for STE-Pro Max

**SkillC checks the steps behind an STE artifact—not just whether a tool ran.**
It checks a workflow against declared rules:
what must be available, which actions are allowed, and what must be verified
before completion.

In STE-Pro Max, this runs automatically before and after supported operations.
The STE integration checks the actual source, evidence, output files, and audio.
A failed check is an error, not a successful result with a reassuring message.
There is no manual staging, approval token, or product confirmation step.

## Why it is relevant to STE-Pro Max

**Simplified Technical English does not need SkillC. Automated document production
benefits from it.** STE-Pro Max does more than rewrite sentences: it creates
evidence-linked reports, HTML/SVG explanations, and narrated material.

Instructions such as “keep the source intact,” “retain the evidence,” and
“verify the output” are easy for an assistant to skip. The integration turns the
checkable parts of those instructions into enforced workflow rules. Clear prose
does not compensate for a missing attachment, changed source data, or broken output.

For a short conversational rewrite, the benefit is limited. SkillC does not make
the English clearer, grade STE compliance, or establish that a claim is true.
Its main value is reliability when the assistant performs actions and produces files.
Enforcement applies to tool execution and results; it cannot guarantee that every
sentence in the assistant's chat response is accurate.

## Concrete problems it catches

| Situation | What the guarded STE workflow does |
| --- | --- |
| A report declares a local evidence file that is missing | Refuses to create the bundle rather than silently dropping that dependency |
| Source or declared evidence changes during a build or before export | Rejects the result or export instead of claiming it still matches the recorded inputs |
| An assistant requests a write outside its workspace or into a protected area | Refuses that target before writing through the guarded tool |
| A renderer returns success but a required output is missing or invalid | Reports failure after checking the actual files |
| A WAV exists but is empty, malformed, or constant | Refuses to mark narration preparation complete |

These are operational checks, not a guarantee of correct meaning. The system
cannot discover every undeclared source, prove that evidence supports a claim,
or establish that valid audio says the right words.

## What happens when you ask for a report

Suppose you supply `report.md` and declare `results.json` as evidence.

1. **Before building:** check that the required files and runtime are available,
   the output path is allowed, and the inputs meet the operation's requirements.
2. **Build:** run the existing STE renderer and retain the declared source/evidence.
3. **Before returning success:** inspect the produced files and compare recorded
   bytes and hashes. Refuse success if those checks fail.

If the evidence changes later, export refuses the stale bundle. It does not
silently approve the new evidence. Some failures are detected after output exists;
partial files remain for diagnosis. This is not a promise to undo every effect.

**Available from v0.6.0.** Existing host permissions still apply, and the v0.5.0
tag remains unchanged. See [tested behavior and limits](VALIDATION.md).

## Native use

Use the configured runtime from the checkout, or run the corresponding typed
host tool. These examples refer to existing local source/evidence files and new
output directories:

```sh
python -m ste_promax render report.md --evidence results.json --output-dir artifacts/report
python -m ste_promax export --input-dir artifacts/report --output-dir artifacts/report-copy
python -m ste_promax narrate story.json --audio-dir beat-audio --output-dir artifacts/story-media
```

`start`, direct `render_artifact`, gallery regeneration, media preparation, WAV
synthesis, and the supplied narration helpers also enter automatic checks. Pure
help, version, schema, input checks, and diagnostics remain usable without a
working backend. A renderer is not needed for a short conversational rewrite.

Native filenames and successful return types remain intact: HTML/design/metadata
triples, `gallery.html`, and the existing media manifest. Narration preparation
returns `prepared_not_rendered`, **not an encoded movie**. PCM checks establish
nonempty, nonconstant audio, not pronunciation or agreement with the script.

### Evidence and export

Repeat `--evidence FILE` for explicit dependencies. Local story `sources[].locator`
values resolve under `--evidence-root DIR`, normally the input's parent. Bundled
catalog examples use their known bundle root. Do not guess among ancestor roots
or silently omit missing files. Remote URLs remain references, not fetched proof.

Rendering records the declared source and evidence binding. Automatic export
checks the original source, captured evidence, manifest, and payload against
those records before copying checked bytes to a new destination. A legacy bundle
without required bindings is not silently upgraded by hashing whatever exists now.
Keep original sources and evidence available until export. Arbitrary citations,
remote resources, and undeclared dynamic assets are not automatically discovered.

Imported raw HTML requires deliberate `--trusted-html`; this is not sanitization.
The direct Python `render_artifact` API also requires `trusted_html=True` for raw
HTML; its default is false and non-boolean values are invalid. This is a
v0.6.0 API safety change, not a manual approval interaction.
Generated interactive HTML remains supported, but no JavaScript safety proof is
claimed. Rejected postconditions are failures even if a renderer returned
`status: complete`. Partial output is retained for diagnosis, never reported as
verified. Use a fresh destination after a failed operation; do not overwrite it.

The historical manual package under `artifacts/skillc-native-20261106/` remains
unapproved and unexported. The new policy does not retroactively authorize that
record or migrate its approval state.

## Installed host behavior

The four STE skills use `ste_status`, `ste_check_prose`, `ste_write_artifact`,
`ste_render_bundle`, and the relevant media/inspection/export tools. Hosts may
prefix these names with the server name. File-producing tools derive the
workspace from trusted host context, not a model argument. They protect plugin,
configuration, credential, and source areas, and check proposed and actual bytes.

Scope starts from actual STE skill/agent activation, not words in a prompt. It
persists across turns and follows native descendants; resume/reload must recover
the scope. Start a new non-STE session for unrelated unrestricted work. Non-STE
sessions keep their existing behavior. Within STE scope, raw shell, generic
patch/edit, opaque external agents, and other uncontrolled mutation routes are
refused rather than parsed with a supposedly safe command regex.

**Copilot CLI:** Agent Plugins 1.0 uses root `mcp.json`,
`com.github.copilot/hooks/hooks.json`, and the `ste-author` agent. The dedicated
agent restricts tool availability independently of hooks. Use it for the strongest
supported boundary. Copilot's outer command-hook **timeouts fail open**. An inner
watchdog reduces that risk but cannot eliminate an OS-level stall. Guarded MCP
executors independently check their effects. Do not advertise default-agent hooks
as an unconditional sandbox.
Copilot 1.0.103's `preMcpToolCall` hook binds its actual session ID and working
directory into request metadata. The MCP executor resolves that exact session
record; it does not guess the newest session or use the plugin directory as the
workspace. Missing or invalid bindings refuse effects.

**OpenCode V2:** pre-tool hooks can refuse before execution; post-hooks cannot
undo effects. Bounded top-level tools remain available without Code Mode. Host
permissions and other safety plugins are not changed from `ask` to `allow`.

Conversational prose can receive automatic preflight and post-generation
diagnostics. Streamed text has already appeared before post-turn checks. These
are advisory writing/source-limit diagnostics, **not pre-display semantic gates**.
Static inspection is not a browser interaction, visual QA, or accessibility audit.

The v0.6.0 enforcement adapters target Copilot CLI and OpenCode. Published
Claude Code/Codex skill support is not evidence that these hosts have equivalent
enforcement adapters. Loading instructions alone never counts as enforcement.

## Runtime configuration

Effectful operations require a configured backend. Plugin installation does not
silently install Python, SkillC, a voice, or a media encoder. Missing capability
produces an actionable refusal, not an unchecked fallback.

Default trusted configuration locations:

- Windows: `%LOCALAPPDATA%/STE-Pro-Max/skillc-runtime/runtime.json`.
- POSIX: `${XDG_DATA_HOME:-~/.local/share}/ste-promax/skillc-runtime/runtime.json`.

The `ste-promax.runtime.v1` record contains `managed_by: "ste-promax"`, absolute
`python`, `skillc_root`, `ste_root`, and `state_root` paths, plus `skillc_commit`
and dependency `versions`. A separate absolute `mcp_python` can supply the Python
MCP SDK. Installed code is loaded from the installed bundle, not from an arbitrary
document or the runtime record's development checkout. Keep private policy state
outside deliverables. Do not copy credentials into this configuration.

Trusted process overrides include `STE_SKILLC_RUNTIME_CONFIG`, paired
`STE_SKILLC_PYTHON`/`STE_SKILLC_ROOT`, and `STE_SKILLC_STATE_ROOT`. Interpreter/source
paths must be absolute. No document, manifest, or model argument may choose them.
The venv executable path is preserved rather than resolved into a different Python.

The inspected backend is SkillC **0.3.0**, revision
`25cc63bf82e968da7d01e204dc6d99879b76c45b`, with Z3. STE rendering needs Jinja2 and
PyYAML. The local offline provisioner at `tools/provision_skillc_runtime.py`
copies only verified installed distribution records and pristine pinned source
into a new owned runtime. It dry-runs by default and never downloads packages,
weakens TLS, repairs an unrelated environment, or overwrites an existing runtime.

## Impact: what changes and what does not

| Previous development workflow | Automatic workflow |
| --- | --- |
| Manual staging, approval, then export | Ordinary operations check themselves; no approval ceremony |
| Normal rendering bypassed the optional export gate | Public effectful renderer/media entry points enter the shared controller |
| Host skill instructions were only conventions | Supported host adapters restrict STE mutation paths and provide guarded tools |
| Export could use evidence found later | Export requires render-time bindings and rejects changed declared evidence |
| A successful function return could be mistaken for verification | The controller reads the actual outputs and can reject the result |

These are behavior changes, not measured productivity, accuracy, cost, or
learning gains. Test pass counts are not real-world success rates.

Same-user shell or filesystem access outside the controlled host can bypass or
alter local helpers/state. This is a local policy boundary, not an OS sandbox,
multi-party identity system, complete numeric/protocol monitor, or permanent file
lock. Existing host permissions, external-action authorization, and source trust
still apply. No publication, paid service, or unrelated global change follows
from an `ALLOW` receipt.

## Implementation map

- [Controller](../ste_promax/gate.py): admission, runtime checks, receipts, and export.
- [Runtime resolver](../ste_promax/policy_runtime.py): trusted configuration and typed errors.
- [Worker](../ste_promax/_skillc_worker.py): closed JSON `guard_pre`, `guard_post`, `guard_fail`, and `guard_status` actions.
- [Host operations](../integrations/mcp/operations.py): bounded shared executor, also used by adapters.
- [Copilot hooks](../integrations/copilot/hook_entry.py): session scope and pre-tool refusal.

The source checkout tests core/native boundaries, packaging, and host adapters.
Installed CLI workflows and retained artifacts remain separate evidence. See
[validation](VALIDATION.md) for the tested environments and remaining limits.

## Implementation details

SkillC supplies workflow checking and a strict runtime monitor. STE-Pro Max
supplies the file/evidence/audio validators and host-tool integration. The
monitor does not inspect document meaning or generated files on its own.

| Layer | Implementation | What it establishes |
| --- | --- | --- |
| Workflow admission | SkillC parser, `bind_runtime`, and `checker.check` | The declared finite plan is admissible, `ACHIEVABLE`, and `WELL_TYPED` |
| Runtime rules | Strict `Monitor.pre_action` / `post_action` | Declared roles and prerequisites permit the operation |
| Concrete validation | STE input, path, source, evidence, file-hash, metadata, and PCM checks | The inspected files satisfy the stated operational checks |
| Host adapters | Copilot CLI hooks/strict STE agent and OpenCode V2 hooks with guarded tools | Supported STE sessions use the checked executor rather than unrestricted mutation routes |

SkillC is by **Gina Tcchen and contributors**. STE-Pro Max maintains this
integration. See [credits, licenses, and primary sources](SKILLC_CREDITS.md).
A positive workflow verdict is not a certificate for factual truth or the
correctness of every line of this integration.
