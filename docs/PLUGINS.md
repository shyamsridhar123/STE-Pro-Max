# Install and manage the plugin

The host's native plugin manager owns installation and lifecycle. The published
**v0.5.0** skills/templates need no Python setup. The **v0.6.0 automatic-policy
version** additionally needs a configured SkillC runtime and supported host adapter.
See [automatic checks](SKILLC_GATE.md); do not confuse the two installation states.

## Install a release

Copilot's commands select **v0.6.0**, not the moving default branch. The Claude
Code and Codex commands retain their last verified **v0.5.0 skills-only** route.

### GitHub Copilot CLI

```sh
copilot plugin marketplace add shyamsridhar123/STE-Pro-Max#v0.6.0
copilot plugin install ste-pro-max@ste-pro-max-plugins
copilot plugin list --json
```

### Claude Code (legacy v0.5.0 skills only)

```sh
claude plugin marketplace add shyamsridhar123/STE-Pro-Max#v0.5.0
claude plugin install ste-pro-max@ste-pro-max-plugins --scope user
claude plugin list --json
```

User scope persists across projects. Use a supported project/local scope only
when that is the intended installation; it can write project settings.

### OpenCode V2 (v0.6.0)

Configure the inspected [policy runtime](SKILLC_GATE.md#runtime-configuration),
download and unpack the v0.6.0 source bundle, and add its adapter directory to
the existing `plugins` array in `opencode.json(c)`:

```json
{
  "plugins": ["/absolute/path/to/ste-pro-max/integrations/opencode"]
}
```

Preserve unrelated configuration and permissions. The adapter registers all four
bundled STE skills and ten guarded tools. If older manually copied STE skills
already exist, back up only those four directories outside skill auto-discovery
so their old IDs do not shadow the bundle's current definitions. Verify the
registered skill paths and plugin status after configuration reload.

### Codex CLI (legacy v0.5.0 skills only)

```sh
codex plugin marketplace add shyamsridhar123/STE-Pro-Max --ref v0.5.0
codex plugin add ste-pro-max@ste-pro-max-plugins --json
codex plugin list --json
```

The tested CLI is **0.147.0**. Its verb is `plugin add`, not `plugin install`.
If your build lacks `add`, register the marketplace and install through
`/plugins` or the supported desktop plugin browser. Restart after installation.
Desktop UI behavior is not inferred from CLI installation tests.

## Use it

For the published v0.5.0 release:

Ask for `STE-ProMAX`, `STE visual docs`, `STE storytelling`, or `STE Line Studio`,
and supply the material. The agent reads the installed skill and uses its normal model/file
and browser tools. It can adapt the [standalone examples](../examples/showcase/README.md)
without a build, runtime bootstrap, provider key, or server.

A short rewrite stays in the conversation. HTML/SVG output is authored and checked
by the host; it does not implicitly receive the optional engine's machine
validation or hash manifest. Voice/video needs a separately available capability.

## Update, disable, uninstall

| Host | Refresh/update | Disable / enable | Remove |
| --- | --- | --- | --- |
| Copilot | `copilot plugin update ste-pro-max@ste-pro-max-plugins` | `copilot plugin disable` / `enable` followed by the plugin ID | `copilot plugin uninstall ste-pro-max@ste-pro-max-plugins` |
| Claude Code | `claude plugin update ste-pro-max@ste-pro-max-plugins --scope user` | `claude plugin disable` / `enable` followed by the ID and scope | `claude plugin uninstall ste-pro-max@ste-pro-max-plugins --scope user` |
| Codex | `codex plugin marketplace upgrade ste-pro-max-plugins --json` | Toggle the installed plugin in `/plugins` | `codex plugin remove ste-pro-max@ste-pro-max-plugins --json` |

A version-pinned marketplace stays on that ref. Refreshing it does not select a
new release. To move versions, select the new release/ref in your host's
marketplace configuration and reinstall/update its entry. Do not overwrite
existing tags or silently opt people into an unpinned development branch.
Codex's inherited `--enable`/`--disable` flags control features, **not plugins**.

### Move an existing Copilot installation to v0.6.0

If your marketplace is pinned to an earlier tag, `plugin update` alone stays on that
release. In PowerShell or your terminal, remove only the STE registration,
then select the new tag:

```powershell
copilot plugin uninstall ste-pro-max@ste-pro-max-plugins
copilot plugin marketplace remove ste-pro-max-plugins
copilot plugin marketplace add "shyamsridhar123/STE-Pro-Max#v0.6.0"
copilot plugin install ste-pro-max@ste-pro-max-plugins
copilot plugin list --json
```

Start a new Copilot session. The installed version should be `0.6.0`, with all four STE
skills available. These commands do not remove your authored workspace files.
For a first installation, use the shorter commands above.

## Local development is a different mode

`--plugin-dir` is temporary session loading, not persistent install. Local
marketplaces also have different cache semantics: a host may load in place or
copy the entire directory, including ignored files. **Do not install a dirty
working repository as a distributable.** Use the tagged remote or the whitelisted
source bundle built by `tools/build_plugin.py`.
Copilot CLI 1.0.103 loads a local marketplace plugin live from the supplied source
directory. Uninstall disables its active skills/MCP without deleting that source;
a disabled discovery row can remain. Marketplace removal is a separate command.

The public repository includes developer tools, tests, and an optional Python
renderer. Their presence does not run them or install their dependencies.
The release source ZIP excludes workstation memory, Git state, generated local
evidence, caches, and credentials. No root Node manifest triggers an implicit
package install. The published v0.5.0 bundle has no hooks or MCP servers. The
v0.6.0 version adds root `mcp.json`, Copilot hooks/agent, and an OpenCode
adapter. These are explicit components, not portable post-install scripts or new
global permission grants.

## Optional deterministic engine

For schema-driven compilation and batch workflows, see [Authoring](AUTHORING.md).
That separate path requires Python 3.10+, Jinja2, and PyYAML; the developer
`quickstart.py` prepares an isolated environment only when explicitly invoked.
It is **not plugin installation**. In the automatic-policy version, the separate
SkillC runtime is mandatory for effects; quickstart is not a policy bypass.

## Test the automatic development bundle locally

Configure the inspected runtime using [the runtime guide](SKILLC_GATE.md#runtime-configuration).
Then build a new whitelisted bundle; never install the dirty repository itself:

```sh
python tools/build_plugin.py --output-dir artifacts/plugin-test-build
```

The parent `artifacts` directory must exist and the build destination must be new.
The archive/hash manifest excludes generated evidence, credentials, tests, and
workstation state. SkillC source and Python dependencies remain in the configured
runtime rather than being silently downloaded by plugin installation.

For a bounded authenticated Copilot CLI development session, use its existing
supported login, a separate workspace, and temporary plugin loading:

```sh
copilot --plugin-dir /absolute/path/to/plugin-test-build/ste-pro-max -C /absolute/path/to/workspace --agent ste-pro-max:ste-author
```

This does not persistently install the plugin. For persistent lifecycle tests,
point `COPILOT_HOME` at a fresh test directory, register the built bundle as a
local marketplace, then install/list/disable/enable/uninstall it through the CLI.
Fresh profiles may not inherit authentication. Use supported login if a live
test needs it; **never copy credential configuration between profiles**.

The dedicated `ste-author` agent restricts its tool list. Ordinary STE skill
activation also enables session hooks, but Copilot command-hook outer timeouts
can fail open. Independently guarded tools and the strict agent are distinct
controls; see the integration guide for the remaining limit.

OpenCode uses its V2 plugin configuration to load the bundle's
`integrations/opencode` directory. Preserve unrelated plugins and permissions;
never replace `ask` rules with blanket `allow`. Apply activation last, then test
in a separate session: an existing session containing STE skill history can
immediately become STE-scoped on reload.

The supported v0.6.0 automatic host adapters are Copilot CLI and OpenCode. Claude Code
and Codex release-skill support does not establish equivalent runtime enforcement.
Do not announce universal automatic enforcement based on the portable manifest.

## Evidence and sources

Research inspected **Superpowers, Anthropic Skills, Compound Engineering, and
Awesome Copilot** plus the actual installed host commands. The resulting decision
is native lifecycle and a dependency-free default—not another plugin manager.
[Research notes](research/PLUGIN_MANAGEMENT.md) · [Verification](VALIDATION.md).

- [Copilot reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference)
- [Claude lifecycle](https://code.claude.com/docs/en/plugins/cli-reference)
- [Codex CLI reference](https://developers.openai.com/codex/cli/reference)
- [Codex packaging](https://developers.openai.com/plugins/build/plugins)

Host configuration was redirected into isolated test profiles for lifecycle
checks. No changes to the normal user's plugin installations were required.
The agent host's own access, tool approvals, model entitlement, and privacy rules
still apply; local HTML does not make the entire assistant session offline.
