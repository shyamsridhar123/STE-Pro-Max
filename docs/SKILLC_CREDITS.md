# SkillC credits and primary sources

Attribution verified on **2026-11-06** against SkillC **0.3.0**, commit
`25cc63bf82e968da7d01e204dc6d99879b76c45b`. Links below pin the inspected revision
where possible. The implementation and bounded impact are documented in the
[automatic-policy guide](SKILLC_GATE.md).

## Upstream software credit

**SkillC was not invented or reimplemented by this integration.** The original
[skill-achievability-compiler](https://github.com/ginaecho/skill-achievability-compiler)
supplies the compiler/checker and strict runtime `Monitor` used by the automatic
workflow. Credit belongs to **Gina Tcchen and contributors**. The earlier manual
prototype also used upstream `Delivery` and `ApprovalGate`; the current workflow
does not use manual approval.

The upstream [MIT license](https://github.com/ginaecho/skill-achievability-compiler/blob/25cc63bf82e968da7d01e204dc6d99879b76c45b/LICENSE)
states:

```text
Copyright (c) 2026 Gina Tcchen and contributors
```

The software's [CITATION.cff](https://github.com/ginaecho/skill-achievability-compiler/blob/25cc63bf82e968da7d01e204dc6d99879b76c45b/CITATION.cff)
names **Gina Tcchen**, records version **0.3.0** and release date **2026-07-02**, and
asks academic users to cite that metadata. The repository account is `ginaecho`;
an account name is not a substitute for the supplied author metadata.

Suggested software citation, using that metadata and the inspected revision:

> Tcchen, Gina. (2026). *skill-achievability-compiler: A Static Compiler for Goal
> Achievability Verification in LLM-Synthesized Agent Skills* (Version 0.3.0)
> [Software]. Revision `25cc63bf82e968da7d01e204dc6d99879b76c45b`.
> https://github.com/ginaecho/skill-achievability-compiler

## STE-Pro-Max contribution and license boundary

**Shyam Sridhar and STE-Pro-Max contributors** maintain this project's native
integration: CLI commands, the STE-specific workflow plan, artifact/evidence
validation, host adapters, private policy state, local export, tests, and
documentation. The native STE renderer remains this project's implementation.

The integration calls SkillC as a **required external backend for effectful STE
operations**. SkillC source is not vendored into this repository, and its checker
and monitor algorithms are not
replaced with STE-owned equivalents. The [local worker](../ste_promax/_skillc_worker.py)
is an adapter to the real upstream APIs, not a new compiler or an endorsement by
upstream authors.

STE-Pro-Max retains its [Apache-2.0 license](../LICENSE) and [NOTICE](../NOTICE).
SkillC retains its separate MIT license. If SkillC source or substantial portions
are redistributed, its copyright and permission notice must accompany them as
the MIT license requires. Calling an external dependency does not relicense that
dependency or transfer authorship of its research to STE-Pro-Max.

## Manuscript citation and authorship limits

The inspected repository contains this manuscript:

> Anonymous Author(s). (2026). *Can This Agent Even Do That? A Decidable
> Goal-Achievability Type Discipline for LLM-Synthesized Agent Skills*.
> Repository manuscript, revision `25cc63bf82e968da7d01e204dc6d99879b76c45b`.

Primary sources are the [manuscript source](https://github.com/ginaecho/skill-achievability-compiler/blob/25cc63bf82e968da7d01e204dc6d99879b76c45b/paper/skillachievability.tex#L92-L94),
the [paper's repository guide](https://github.com/ginaecho/skill-achievability-compiler/blob/25cc63bf82e968da7d01e204dc6d99879b76c45b/paper/README.md),
and its [core formal rules](https://github.com/ginaecho/skill-achievability-compiler/blob/25cc63bf82e968da7d01e204dc6d99879b76c45b/paper/tas.tex).

The manuscript explicitly uses `Anonymous Author(s)` and a NeurIPS 2026
double-blind workshop template titled *Who Verifies the Agents? Toward Reliable
Agent Development*. Template use is **not evidence of acceptance or peer review**.
No DOI or arXiv identifier for this manuscript is supplied by the inspected
metadata. Do not infer the anonymous paper's full author list from the software
citation, account name, or comments about collaborators.

## Implementation and proof sources

| Source at the inspected SkillC revision | What it supports |
| --- | --- |
| [Checker and Verdict](https://github.com/ginaecho/skill-achievability-compiler/blob/25cc63bf82e968da7d01e204dc6d99879b76c45b/src/skillc/checker.py) | Separate goal and protocol results, admission fields, and abstract reachability analysis |
| [Runtime Monitor](https://github.com/ginaecho/skill-achievability-compiler/blob/25cc63bf82e968da7d01e204dc6d99879b76c45b/src/skillc/monitor.py#L980-L1175) | Pre-action policy, role/prerequisite checks, post-action handling, and Boolean-state limits |
| [Delivery and ApprovalGate](https://github.com/ginaecho/skill-achievability-compiler/blob/25cc63bf82e968da7d01e204dc6d99879b76c45b/src/skillc/security.py#L56-L202) | Historical manual-prototype mechanism; not used by the current automatic controller |
| [Verdict coverage](https://github.com/ginaecho/skill-achievability-compiler/blob/25cc63bf82e968da7d01e204dc6d99879b76c45b/docs/VERDICT_COVERAGE.md) | Formal coverage tags, trusted assumptions, and the limits of positive abstract witnesses |

These sources justify credit for the reused mechanisms. They do **not** make this
integration, its Python code, the renderer, natural-language claims, authenticated
human consent, or successful real-world delivery formally verified. Monitor does
not inspect artifact meaning; STE's adapter must validate the concrete files.

## Solver and rendering dependencies

| Dependency | Role here | License |
| --- | --- | --- |
| [Z3 Theorem Prover / Microsoft Corporation](https://github.com/Z3Prover/z3) | Solver used by the upstream SkillC backend | [MIT](https://github.com/Z3Prover/z3/blob/master/LICENSE.txt) |
| [Jinja2 / Pallets](https://github.com/pallets/jinja) | STE template rendering | [BSD-3-Clause](https://github.com/pallets/jinja/blob/3.1.6/LICENSE.txt) |
| [MarkupSafe / Pallets](https://github.com/pallets/markupsafe) | Jinja2's escaping dependency | [BSD-3-Clause](https://github.com/pallets/markupsafe/blob/3.0.4/LICENSE.txt) |
| [PyYAML / Ingy döt Net and Kirill Simonov](https://github.com/yaml/pyyaml) | YAML parsing in STE and SkillC | [MIT](https://github.com/yaml/pyyaml/blob/6.0.3/LICENSE) |
| [Model Context Protocol Python SDK](https://github.com/modelcontextprotocol/python-sdk) | Official stdio MCP transport for host tools | [MIT](https://github.com/modelcontextprotocol/python-sdk/blob/main/LICENSE) |

The local run used Z3 5.3.3.0, Jinja2 3.1.6, MarkupSafe 3.0.4, and PyYAML 6.0.3.
This is a focused credit list for the inspected runtime, not an exhaustive SBOM
or a claim that those dependency sources are bundled in the plugin.

Canonical solver citation:

> de Moura, Leonardo, and Nikolaj Bjørner. (2008). *Z3: An Efficient SMT Solver*.
> In *Tools and Algorithms for the Construction and Analysis of Systems*,
> LNCS 4963, pp. 337–340. Springer.
> https://doi.org/10.1007/978-3-540-78800-3_24

The DOI's title, authors, year, and pages were checked against its publisher
metadata indexed by Crossref. The same paper appears in the
[upstream bibliography](https://github.com/ginaecho/skill-achievability-compiler/blob/25cc63bf82e968da7d01e204dc6d99879b76c45b/paper/skillachievability.tex#L637).

## Existing STE-Pro-Max credits remain intact

The original writing import remains preserved as described in
[provenance](PROVENANCE.md). The [STE and Karpathy source note](../skills/ste-promax/references/source-evidence.md)
distinguishes style inspiration from the normative ASD-STE100 standard and from
certification. The Line Studio mechanism-figure method credits
[Anatomy by Ryan](https://github.com/wheresryan22/anatomy), as recorded in
[NOTICE](../NOTICE). These references do not imply endorsement by any author,
maintainer, standards body, or institution.
