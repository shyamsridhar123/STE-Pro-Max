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

## Native engine and identity

STE-Pro Max is maintained as a standalone product by Shyam Sridhar. On October 3,
2026, the owner authorized an independent product identity across the engine,
templates, documentation, and generated artifacts. Copyright and Apache-2.0
licensing remain in `NOTICE`, source headers, and `LICENSE`.

The `ste_promax/` package owns rendering, design parsing, gallery generation,
writing checks, structured visuals, stories, and narration preparation. It runs
directly rather than delegating to another installed renderer. Jinja2 and PyYAML
are its two declared runtime dependencies. The default template uses local CSS
and system fonts. Other checkouts and the original writing import remain unchanged.

## Automatic SkillC integration

The v0.6.0 automatic workflow reuses the original
SkillC compiler and Monitor by **Gina Tcchen and
contributors**. The inspected software is version 0.3.0 at commit
`25cc63bf82e968da7d01e204dc6d99879b76c45b`, licensed under MIT.

STE-Pro-Max contributes its native CLI integration, fixed workflow plan,
artifact/evidence checks, scoped host adapters, and automatic local export handling.
Rendering remains in the native STE engine. The local worker delegates
SkillC policy operations, not rendering, to an inspected external backend.
No SkillC source is vendored or relicensed as STE-Pro-Max code.
The inspected MIT source, with its notice, was copied into a separate owned local
runtime from the pinned Git revision; its compiler was not modified. The earlier
manual approval package is preserved as historical evidence, not migrated.

[Credits and primary citations](SKILLC_CREDITS.md) distinguish the named software
author from the anonymous repository manuscript and preserve each license boundary.
This integration does not inherit an end-to-end formal correctness guarantee
from an upstream model or paper. See [implemented behavior and limits](SKILLC_GATE.md).

## Output ideas and standard

The [source-evidence note](../skills/ste-promax/references/source-evidence.md)
distinguishes Karpathy's output suggestions from ASD-STE100's normative rules.
Neither source endorses this project. The repository contains qualified guidance,
not a redistributed copy of the standard or a certified checker.
