# Plugin packaging

One shared native engine and three focused skills serve three target hosts.
There is no separately maintained renderer per host.

## Target surfaces

| Target | Native descriptor | Skill discovery |
| --- | --- | --- |
| GitHub Copilot **CLI** | Root `plugin.json`, Agent Plugins 1.0 | `skills/*/SKILL.md` |
| Claude **Code** | `.claude-plugin/plugin.json` | `skills/*/SKILL.md` |
| Codex **CLI and desktop app** | Root `plugin.json`, Agent Plugins 1.0 | `skills/*/SKILL.md` |

The shared skills are `ste-promax`, `ste-visual-docs`, and `ste-storytelling`.
They operate the same native engine; there are no per-host renderer implementations.

This is a packaging target matrix, not a claim that the plugin has been installed
or exercised in every host. GitHub.com, Copilot IDE integrations, generic Claude
web/Desktop, and the Codex IDE extension are not claimed by these tests.

The portable manifest and Claude's separate descriptor intentionally coexist.
Their payload is shared; each host's loading still needs its own validation.
The package contains no automatic hooks, provider credentials, MCP server, or
background service.

## Build

```powershell
python -c "from pathlib import Path; Path('artifacts').mkdir(exist_ok=True)"
python tools/build_plugin.py --output-dir artifacts/plugin-build
```

The output contains an assembled plugin directory, a ZIP, and a file/hash manifest.
The builder requires the output's parent to exist and the output directory itself
to be new; it never removes an earlier build.
The builder uses an explicit payload list, refuses unsafe replacement, and excludes
Git data, orchestration state, local memories, caches, and generated artifacts.

`ste_promax/`, `skills/`, templates, design files, README images, and examples come from the same
source used by local tests. `__main__.py` makes the bundle callable from another
workspace without a separate renderer executable:

```powershell
python "<absolute-plugin-root>" check "<workspace>/notes.md" --json
python "<absolute-plugin-root>" start "<workspace>/notes.md" --json
python "<absolute-plugin-root>" schema story
python "<absolute-plugin-root>" render "<workspace>/notes.md" --output-dir "<workspace>/artifacts/new-report"
python "<absolute-plugin-root>" narrate "<workspace>/story.json" --audio-dir "<workspace>/audio" --output-dir "<workspace>/artifacts/new-media"
```

Use the plugin root from the actual loaded skill location. Do not assume the
user's working directory is the plugin directory. Generated output belongs in the
user's workspace, not the plugin cache.

## Runtime preflight

Python 3.10+ is required. Prose checks use only the standard library. Native
rendering additionally uses Jinja2 and PyYAML. Plugin installation is **not**
evidence that these Python packages were installed.

For a first result from a checkout or extracted bundle:

```powershell
python "<absolute-plugin-root>/quickstart.py" --open
```

Run it from the intended output workspace. The user-invoked launcher reuses a
ready interpreter or prepares a private **`.ste-env` in that workspace**.
First-time setup can download the declared Python packages. It never mutates
global Python, replaces an unrelated environment, or writes build output into
a shared plugin cache. Later ready runs do not reinstall dependencies.
Use `--no-install` for ready-environment-only operation and `--no-open` for headless
operation. Ordinary skill discovery does not trigger this launcher.

`python "<absolute-plugin-root>" doctor --json` reports local readiness without
installing packages or executing optional tools. Use the same interpreter for
diagnostics and rendering. If quickstart created `.ste-env`, call its Python for
later native commands, or keep using quickstart to select it.

Rendering reports missing dependencies before creating output; it does not run pip.
When setup is explicitly requested, use an isolated environment in the user's
workspace, not a mutation of a shared plugin cache or global environment:

```powershell
python -m venv .ste-env
.ste-env/Scripts/python.exe -m pip install "Jinja2>=3.1.6,<4" "PyYAML>=6.0.3,<7"
.ste-env/Scripts/python.exe "<absolute-plugin-root>" --version
```

Use `.ste-env/bin/python` on macOS/Linux. Windows narration additionally needs
Windows PowerShell 5.1 and a generic installed speech voice. HyperFrames and movie
export requirements remain optional. Do not silently substitute a cloud provider.
The canonical helper is a package resource at `ste_promax/scripts/narrate.ps1`,
included in both source bundles and Python wheels. Supplied integer-PCM WAV files
provide a separate, cross-platform `--audio-dir` route.

## Host loading

These are documented user-controlled installation/development paths, **not actions
performed by the build script**.

### Copilot CLI

For session-only loading, use:

```text
copilot --plugin-dir "<absolute-plugin-root>"
```

For persistent local installation:
`copilot plugin install "<absolute-plugin-root>"`.
The repository also supplies a Copilot marketplace catalog. A private repository
requires appropriate GitHub access; the plugin does not create that access.

### Claude Code

Validate the plugin with the installed CLI. Current documentation includes strict
validation; report an older CLI's limitation rather than claiming that check ran:

```text
claude plugin validate <plugin-directory> --strict
```

For session-only development, use `claude --plugin-dir <plugin-directory>`.
For persistent installation, register the supplied marketplace and explicitly
select the intended user/project scope:

```text
claude plugin marketplace add "<absolute-plugin-root>" --scope user
claude plugin install ste-pro-max@ste-pro-max-plugins --scope user
```

Do not mutate global installations while
merely building or testing a package.

### Codex CLI / desktop

Register the local marketplace:

```text
codex plugin marketplace add "<absolute-plugin-root>"
codex
```

Inside Codex, use `/plugins`, select `ste-pro-max-plugins`, and install
`ste-pro-max`. Start a fresh session afterward. The supported desktop Plugins
Directory is an alternative local-authoring surface; older app versions may
differ. These are documented paths, not a claim of a completed local installation.

The repository's `.agents/plugins/marketplace.json` describes a local source at
`./`. OpenAI defines that path relative to the marketplace's repository root,
not the catalog file's directory. This applies the documented containment rule
to a repo-root plugin; host installation of that exact arrangement remains a
separate check. The entry declares availability, not an automatic installation.

Do not invent a `codex plugin validate` or standalone `codex plugin install`
command. The inspected documentation establishes marketplace registration plus
the interactive plugin browser.

### Select the preview branch, not an older default branch

This preview remains on `feat/comprehensive-suite` until its PR is merged. A plain
repository install can load older default-branch code. Prefer a local checkout
of the preview branch or an explicitly ref-selected marketplace:

```text
copilot plugin marketplace add "shyamsridhar123/STE-Pro-Max#feat/comprehensive-suite"
claude plugin marketplace add "shyamsridhar123/STE-Pro-Max#feat/comprehensive-suite" --scope user
codex plugin marketplace add shyamsridhar123/STE-Pro-Max --ref feat/comprehensive-suite
```

Choose the one matching your host, then install the marketplace entry. Copilot
and Claude use `ste-pro-max@ste-pro-max-plugins`; Codex uses `/plugins`.
Existing private-repository credentials are required. These are alternatives
to local registration, not three steps that every user should run.

## Evidence and references

Checked October 3, 2026:

- [GitHub Copilot CLI plugin reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference)
- [Agent Plugins 1.0 schema](https://agent-plugins.org/schemas/1.0.0/plugin.schema.json)
- [Claude manifest reference](https://code.claude.com/docs/en/plugins/manifest-reference)
- [Claude plugin CLI reference](https://code.claude.com/docs/en/plugins/cli-reference)
- [Claude dependency loading](https://code.claude.com/docs/en/plugins/loading#node-js-package-dependencies)
- [OpenAI plugin packaging](https://developers.openai.com/plugins/build/plugins)
- [OpenAI Codex plugins](https://developers.openai.com/codex/plugins)
- [OpenAI plugin surface guide](https://learn.chatgpt.com/docs/plugins)

Actual local checks and untested host behavior are recorded in `VALIDATION.md`.
