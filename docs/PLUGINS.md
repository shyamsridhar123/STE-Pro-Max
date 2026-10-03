# Plugin packaging

One shared engine and one shared skill serve three target hosts. There is no
installed-PaperBoard wrapper and no separately maintained renderer per host.

## Target surfaces

| Target | Native descriptor | Skill discovery |
| --- | --- | --- |
| GitHub Copilot **CLI** | Root `plugin.json`, Agent Plugins 1.0 | `skills/ste-promax/SKILL.md` |
| Claude **Code** | `.claude-plugin/plugin.json` | `skills/ste-promax/SKILL.md` |
| Codex **CLI and desktop app** | Root `plugin.json`, Agent Plugins 1.0 | `skills/ste-promax/SKILL.md` |

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

`ste_promax/`, `skills/`, templates, design files, and examples come from the same
source used by local tests. `__main__.py` makes the bundle callable from another
workspace without installing or resolving a separate `paperboard` executable:

```powershell
python "<absolute-plugin-root>" check "<workspace>/notes.md" --json
python "<absolute-plugin-root>" render "<workspace>/notes.md" --output-dir "<workspace>/artifacts/new-report"
```

Use the plugin root from the actual loaded skill location. Do not assume the
user's working directory is the plugin directory. Generated output belongs in the
user's workspace, not the plugin cache.

## Runtime preflight

Python 3.10+ is required. Prose checks use only the standard library. Native
rendering additionally uses Jinja2 and PyYAML. Plugin installation is **not**
evidence that these Python packages were installed.

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

## Host loading

These are documented user-controlled installation/development paths, **not actions
performed by the build script**.

### Copilot CLI

Install a local assembled plugin with `copilot plugin install <plugin-directory>`,
or use the repository source when accessible:

```text
copilot plugin install shyamsridhar123/STE-Pro-Max
```

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
select the intended user/project scope. Do not mutate global installations while
merely building or testing a package.

### Codex CLI / desktop

Use the documented local marketplace/plugin directory flow and the `/plugins`
browser. The desktop Plugins Directory is the official local-authoring test
surface. Start a fresh session after installing a plugin.

The repository's `.agents/plugins/marketplace.json` describes a local source at
`./`. OpenAI defines that path relative to the marketplace's repository root,
not the catalog file's directory. This applies the documented containment rule
to a repo-root plugin; host installation of that exact arrangement remains a
separate check. The entry declares availability, not an automatic installation.

Do not invent a `codex plugin validate` or `codex plugin install` command: those
standalone commands were not established by the inspected official documentation.

## Evidence and references

Checked October 3, 2026:

- [GitHub Copilot CLI plugin reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference)
- [Agent Plugins 1.0 schema](https://agent-plugins.org/schemas/1.0.0/plugin.schema.json)
- [Claude manifest reference](https://code.claude.com/docs/en/plugins/manifest-reference)
- [Claude plugin CLI reference](https://code.claude.com/docs/en/plugins/cli-reference)
- [Claude dependency loading](https://code.claude.com/docs/en/plugins/loading#node-js-package-dependencies)
- [OpenAI plugin packaging](https://developers.openai.com/plugins/build/plugins)
- [OpenAI plugin surface guide](https://learn.chatgpt.com/docs/plugins)

Actual local checks and untested host behavior are recorded in `VALIDATION.md`.
