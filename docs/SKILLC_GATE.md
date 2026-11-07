# Automatic STE checks with SkillC

**Available in v0.6.0.** Ordinary STE effectful operations use the
real SkillC engine automatically. There is no `stage`/`approve` sequence, review
token, or product confirmation prompt. Automatic checks still refuse invalid
operations. Existing host permission rules remain in force.

The published **v0.5.0** tag remains unchanged. A local
source edit does not establish that an installed host enforces it. The
[validation record](VALIDATION.md) distinguishes native tests, host tests, and
actual installed behavior. GitHub Copilot CLI testing is a release requirement.

## What runs

| Layer | Implementation | What it establishes |
| --- | --- | --- |
| Admission | Original SkillC parser, `bind_runtime`, and `checker.check` | The finite declared plan is admissible, `ACHIEVABLE`, and `WELL_TYPED` |
| Runtime policy | Real strict `Monitor.pre_action` / `post_action` | Declared roles and prerequisites permit the operation |
| STE validation | Native input validators plus concrete path, source, evidence, file-hash, metadata, and PCM checks | The inspected operation and files satisfy these bounded checks |
| Host adapters | Copilot CLI hooks/strict STE agent and OpenCode V2 hooks, with guarded typed tools | STE-scoped operations use the checked executor instead of unrestricted mutation tools |

SkillC is **not reimplemented** here. Credit belongs to **Gina Tcchen and
contributors**. STE-Pro-Max supplies the integration, concrete validators, host
adapters, and tests. See [licenses, citations, and proof limits](SKILLC_CREDITS.md).

Monitor trusts reported tool outcomes; it does not inspect files itself. The
adapter therefore verifies actual bytes before recording an `ALLOW` receipt.
Neither a positive abstract verdict nor a hash establishes factual truth,
authorship, semantic entailment, or a formally verified Python implementation.

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
