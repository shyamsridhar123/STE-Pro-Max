# Provenance and preserved sources

## STE-ProMAX writing package

Imported from the user-supplied SharePoint file on October 3, 2026. Sharing tokens,
browser session data, and credentials are not included in this repository.

| Preserved file | SHA-256 |
| --- | --- |
| `STE-ProMAX.zip` | `9AEF3BFC674679BE945CF812D32E2233F4683E158661A9C49EE02D31E0CB6F49` |
| `ste-promax/SKILL.md` | `E7D580281112FD76D7A74150EB029F7F81F90DF726F9623E30199F178091163D` |
| `ste-promax/agents/openai.yaml` | `DE2184D0787E9BC7880C24A39CBCDAFD1B8882DB1361ED04D442E58D4AD96304` |

The original contains editorial references. It is preserved byte-for-byte rather
than retroactively rewritten. The separate working skill supplies the new behavior.

## PaperBoard source

- Repository: `https://github.com/All-The-Vibes/ATV-PaperBoard`
- Revision: `4b068bcab8e4dc105f0ef975ee224564f5d63383`
- Source package version at that revision: `0.1.4`
- License: Apache-2.0; the upstream license is copied into `LICENSE`.
- The user explicitly authorized copying and modifying their PaperBoard code.

The native renderer and gallery are adapted from `core/render.py`,
`core/gallery.py`, their templates, and the bundled PaperBoard design.
Modified copies carry notices. The original checkout remains untouched.

The new code does not import the installed PaperBoard package or launch its CLI.
It retains its two Python libraries, Jinja2 and PyYAML, while dropping unrelated
harness installation, server lifecycle, and Node-bridge responsibilities.
The default template uses local CSS and system fonts.

## Output ideas and standard

The [source-evidence note](../skills/ste-promax/references/source-evidence.md)
distinguishes Karpathy's output suggestions from ASD-STE100's normative rules.
Neither source endorses this project. The repository contains qualified guidance,
not a redistributed copy of the standard or a certified checker.
