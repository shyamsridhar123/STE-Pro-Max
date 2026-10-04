# Install and manage the plugin

The host's native plugin manager owns installation and lifecycle. No custom
installer, Python setup, global skill copy, or startup hook is required for the
three authoring skills and standalone HTML/SVG templates.

## Install a release

These commands select the pinned **v0.4.0** release, not the moving default
branch. Choose one host.

### GitHub Copilot CLI

```sh
copilot plugin marketplace add shyamsridhar123/STE-Pro-Max#v0.4.0
copilot plugin install ste-pro-max@ste-pro-max-plugins
copilot plugin list --json
```

### Claude Code

```sh
claude plugin marketplace add shyamsridhar123/STE-Pro-Max#v0.4.0
claude plugin install ste-pro-max@ste-pro-max-plugins --scope user
claude plugin list --json
```

User scope persists across projects. Use a supported project/local scope only
when that is the intended installation; it can write project settings.

### Codex CLI

```sh
codex plugin marketplace add shyamsridhar123/STE-Pro-Max --ref v0.4.0
codex plugin add ste-pro-max@ste-pro-max-plugins --json
codex plugin list --json
```

The tested CLI is **0.147.0**. Its verb is `plugin add`, not `plugin install`.
If your build lacks `add`, register the marketplace and install through
`/plugins` or the supported desktop plugin browser. Restart after installation.
Desktop UI behavior is not inferred from CLI installation tests.

## Use it

Ask for `STE-ProMAX`, `STE visual docs`, or `STE storytelling`, and supply the
material. The agent reads the installed skill and uses its normal model/file
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

## Local development is a different mode

`--plugin-dir` is temporary session loading, not persistent install. Local
marketplaces also have different cache semantics: a host may load in place or
copy the entire directory, including ignored files. **Do not install a dirty
working repository as a distributable.** Use the tagged remote or the whitelisted
source bundle built by `tools/build_plugin.py`.

The public repository includes developer tools, tests, and an optional Python
renderer. Their presence does not run them or install their dependencies.
The release source ZIP excludes workstation memory, Git state, generated local
evidence, caches, and credentials. No root Node manifest triggers an implicit
package install. No hooks, MCP servers, or additional permissions are bundled.

## Optional deterministic engine

For schema-driven compilation and batch workflows, see [Authoring](AUTHORING.md).
That separate path requires Python 3.10+, Jinja2, and PyYAML; the developer
`quickstart.py` prepares an isolated environment only when explicitly invoked.
It is **not plugin installation** and is never a default skill prerequisite.

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
