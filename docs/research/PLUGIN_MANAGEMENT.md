# Native plugin management: decisions from established repositories

Checked October 3, 2026. Source inspection, not endorsements or a popularity
leaderboard. The selected projects have substantial public adoption, but their
star counts are not evidence that every install choice is suitable here.

| Project and inspected revision | Observed pattern | STE-Pro Max decision |
| --- | --- | --- |
| [anthropics/skills](https://github.com/anthropics/skills/tree/8a1541c4a3ffa5a20a5a91de0dcf3f0bab1d1ef4) | Native marketplace groups skills; frontend-design is instruction-led | Let installed skills use the host's model and file tools |
| [EveryInc/compound-engineering-plugin](https://github.com/EveryInc/compound-engineering-plugin/tree/9af474a70e7f2a844338519ad9e92aafbd92d4fb) | Native Codex marketplace; migration docs warn about stale paths and legacy copies shadowing skills | Use one native lifecycle, not a second install manager or global skill copy |
| [github/awesome-copilot](https://github.com/github/awesome-copilot/tree/143a3d976b3c1603cc8932984d5e1f28501cb5fc) | Versioned focused plugin bundles, native install/update/uninstall | Keep three focused skills and a shared, versioned source |
| [obra/superpowers](https://github.com/obra/superpowers/tree/8ca22dba9a94f28898bbce59f2537ff4d87c747d) | Host-specific native installation; additional session-start instruction injection | Copy native packaging, not automatic global/session methodology changes |

Important counterexample: some helper skills run Node scaffolding and install
packages when invoked. That is a helper's side effect, not proof that plugin
installation supplies every runtime. STE's default templates need none of it.

## Native lifecycle

- **Copilot:** `plugin install/update/disable/enable/uninstall`.
- **Claude Code:** the same verbs, with explicit scope.
- **Codex 0.147.0:** `plugin add/list/remove`; marketplace
  `add/list/upgrade/remove`. Plugin `--enable` is not a lifecycle verb: inherited
  flags control features, not installed-plugin activation.

Marketplace registration and session-only `--plugin-dir` loading are not
persistent installation. The acceptance test is a fresh process seeing the
installed plugin, its cached content, and native removal afterward.

## Runtime decision

The default product is installed authoring skills plus dependency-free HTML/SVG
templates. The host supplies model, file, and optional browser tools. Python is
not needed by this path. The existing deterministic engine remains an advanced
option with explicitly separate prerequisites and stronger machine validations.

Do not invent portable `postinstall` or Python-dependency manifest fields.
Claude's supported locked Node dependencies and managed MCPB runtimes are
different host-specific mechanisms. They are not a generic three-host Python
installation guarantee. No bootstrap hooks or new remote service are added.

## Sources and verification limits

- [Copilot plugin reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference)
- [Claude plugin CLI](https://code.claude.com/docs/en/plugins/cli-reference)
- [Claude dependency loading](https://code.claude.com/docs/en/plugins/loading#node-js-package-dependencies)
- [Codex CLI reference](https://developers.openai.com/codex/cli/reference)
- [Codex plugin packaging](https://developers.openai.com/plugins/build/plugins)
- [Agent Plugins manifest](https://agent-plugins.org/schemas/1.0.0/plugin.schema.json)

Official documentation and installed help were checked together. Some packaging
documentation still emphasizes interactive Codex installation; the actual
installed CLI also supports `plugin add`. Use the tested version and command,
not an invented `codex plugin install`.

Implementation and isolated lifecycle evidence are recorded in `VALIDATION.md`.
No benchmark, user-adoption result, or full cross-host model behavior is inferred
from repository popularity or manifest validity.
