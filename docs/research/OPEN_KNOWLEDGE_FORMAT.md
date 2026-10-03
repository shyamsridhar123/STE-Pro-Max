# Open Knowledge Format: applicability to STE-Pro Max

**Decision:** useful as optional knowledge interchange; not a replacement for the
native story model, renderer, or host plugins.

**Research date:** October 3, 2026. **Scope:** research and local compatibility
probes only. No OKF adapter, dependency, cloud service, or host integration was
added. This report does not complete the broader comprehensive-suite goal.

## Evidence and version boundary

The supplied Google article introduced OKF v0.1 on June 12, 2026. Its motivation
is exchanging reusable organizational context as files rather than requiring a
new service or SDK. The accompanying tools are examples, not mandatory parts of
the format. [S1]

The current canonical specification declares **v0.2**, inspected at
`GoogleCloudPlatform/open-knowledge-format@ad30107c31c06aec8a7d5636e0d1058118604e6f`.
The default-branch commit API returned the same SHA, with a committer timestamp
of **August 21, 2026, 20:08:36 UTC**. This is the revision date, not the v0.2
announcement date. Pin the revision rather than implementing from the older
article alone. [S2, S3]

Important specification boundaries:

- Concepts are Markdown/YAML files whose paths identify them. `type` is the only
  always-required metadata key, not the only conformance requirement.
- Provenance, review, freshness, and lifecycle metadata are available. Review
  labels are advisory assertions, not authenticated approval.
- Unknown metadata must be accepted; retaining it on round-trip is recommended,
  not guaranteed. Broken links are permitted.
- Frontmatter resource values can describe a scope rather than a fetchable
  artifact. Relative resource resolution is not fully explicit.
- Domain schemas and execution packaging remain outside the format's scope. [S2]

Three specialist lanes supplied adoption/tooling research, an independent
specification cross-check, and host-contract research. Main inspected the local
source and ran the two probes below.

## Where it fits

**Proposed architecture, not implemented behavior:**

```text
Original source material
        |
Native source and qualified-claim records
        |--------------------> Optional OKF knowledge export
        |
Native story: audience, question, purpose, ordered beats
        |
STE prose / diagrams / charts / HTML / narration
```

Use a knowledge bundle to reuse definitions, source notes, supported findings,
and qualifications across explanations and agent hosts. Do not make it necessary
for a one-off rewrite or diagram. Do not turn the format's concept links into
causal or process-diagram edges automatically.

The following mapping uses the **current working-tree** `ste_promax/stories.py`,
not a claim about the already released package:

| Local record | Proposed interchange representation | Preserve outside generic OKF semantics |
| --- | --- | --- |
| `sources`: ID, title, URL, locator, note | Source concept and explicit references | Original bytes, exact locators, capture evidence, hashes |
| `claims`: text, source IDs, type, scope, uncertainty, attribution, basis | Claim concept with stable source attribution | Distinction between observation, attribution, inference, and proposal |
| Story question, audience, purpose, limitations | Story overview linking relevant concepts | The full native story record |
| Ordered beats, visuals, narration, questions | Links to native story and media attachments | Ordering, quantitative data, visual semantics, timing, and narration |

One document per source or claim is an **STE profile proposal**, not an OKF rule.
Use producer-specific metadata such as a `ste` namespace to retain native IDs.
Keep native JSON and attachment bytes authoritative; generic Markdown cannot
reconstruct every story field reliably.

## Verified local gaps

Inspected baseline:
`126864de16ba5f3a6d169c1d02c1c237b4f22d95`, branch
`feat/comprehensive-suite`, with in-progress visual/story modules present.

1. **Ordinary Markdown rendering is not OKF import.**
   `ste_promax/cli.py:29-59` calls `strip_frontmatter()` and creates normal renderer
   input. A temporary fictional OKF-like fixture retained its original bytes,
   but normalized into only `body_md` and `title`. Its `type` and `sources`
   metadata were absent from normalized input. Thus the original is preserved,
   but its knowledge metadata is not interpreted or displayed.
2. **The story schema is deliberately stricter.**
   `ste_promax/stories.py:100-156` validates explicit fields. Adding OKF-style
   `verified` metadata directly to an otherwise valid claim produced:
   `story.claims[0].verified: unsupported field`.
   Do not loosen that validator indiscriminately; translate through a separate
   knowledge boundary.

These are two successful characterization probes, not an implemented OKF
round-trip or host acceptance test. Temporary probe files were removed by their
temporary-directory context. No runtime source was edited.

The two preserved-source regression tests also passed
(`python -m unittest discover -s tests -p test_preserved_sources.py -v`).
The full in-progress suite was not rerun for this documentation-only change.

The story module is still separate from the current CLI integration. Its presence
does not establish a completed story-to-OKF or story-to-media pipeline.

## Plugin compatibility

OKF would be **content the plugin reads or writes**, not the plugin itself.
Current official loading contracts are:

| Host | Documented package surface |
| --- | --- |
| GitHub Copilot CLI | Agent Plugins root `plugin.json`, skills, optional `mcp.json`; legacy plugin support also exists. [S4] |
| Claude Code | `.claude-plugin/plugin.json`, skills, and optional MCP configuration. [S5] |
| Codex | Agent Plugins root `plugin.json`, skills, optional `mcp.json`; `.codex-plugin/plugin.json` remains a compatibility fallback. [S6] |

The reviewed documentation does not establish automatic OKF discovery or semantic
validation by these hosts. That is a bounded documentation finding, not proof
that no extension supports it. STE would need an explicit interpreter and
host-specific acceptance checks.

## Adoption boundary and security

**Adopt the interchange idea; defer an importer and upstream tooling.**

The upstream reference-agent package brings Google ADK, BigQuery, and other
dependencies and requires Python 3.11+. Its viewer references CDN-hosted
JavaScript. Neither is needed for STE's local deterministic file export; retain
the native PaperBoard-derived renderer and current dependency boundary. [S7, S8]

An STE interoperability profile should:

- Keep imported concept bodies and metadata as data, never as `AGENTS.md`,
  `SKILL.md`, tool permissions, or approval instructions.
- Keep producer-claimed verification distinct from STE-observed review evidence.
  Do not upgrade trust merely because a string names a human.
- Preserve unsupported fields and report unresolved links or conversion losses.
  Distinguish readable-but-incomplete knowledge from a release-ready explanation.
- Avoid automatic URL retrieval or execution of referenced computations,
  executors, attesters, or embedded scripts.
- Bound YAML size/depth, reject executable tags, and constrain file access to the
  selected bundle, including symlink and path-traversal checks.
- Keep private project knowledge out of the distributable plugin by default.
  Export is not consent to publish or upload.

W3C PROV is a useful semantic reference for derivation, attribution, and revision,
but neither provenance records nor graph links prove that a claim is true.
Introducing PROV serialization is not required for this first step. [S9]

## Smallest useful follow-on

After native story integration is working, evaluate an **export-only spike**:
two sources, three qualified claims, and one story, with unchanged native JSON
attached. No new service, database, model call, or SDK.

Proposed acceptance checks, **not executed in this research**:

1. Preserve every ID, value, quotation, qualifier, locator, and attachment hash.
2. Reordering source records must not alter claim attribution.
3. Keep absent, producer-claimed, and locally observed review states distinct.
4. Preserve unknown nested metadata; report unsupported conversions explicitly.
5. Test both document-relative and bundle-root links, missing targets, and
   attempts to escape the bundle.
6. Complete export and local rendering with network disabled.
7. Hostile HTML, YAML, URLs, and embedded instructions must cause no execution
   or disclosure.
8. Test plugin discovery separately from knowledge parsing and factual review.

Proceed to import only after the profile has an explicit loss-reporting contract.
Do not replace native schemas or claim full interoperability from a rendered
Markdown page.

## Primary sources

All retrieved October 3, 2026. Source URLs are recorded for reproducibility.

- **S1 — Google introduction:**
  `https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing`
- **S2 — Pinned OKF v0.2 specification:**
  `https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/ad30107c31c06aec8a7d5636e0d1058118604e6f/SPEC.md`
  Relevant sections: 4-6, 10-11, and non-goals.
- **S3 — Inspected revision:**
  `https://github.com/GoogleCloudPlatform/open-knowledge-format/commit/ad30107c31c06aec8a7d5636e0d1058118604e6f`
- **S4 — Copilot plugin authoring:**
  `https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/plugins-creating`
- **S5 — Claude plugin manifest:**
  `https://code.claude.com/docs/en/plugins/manifest-reference`
- **S6 — OpenAI plugin packaging:**
  `https://developers.openai.com/plugins/build/plugins`
- **S7 — Reference-agent dependencies:**
  `https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/ad30107c31c06aec8a7d5636e0d1058118604e6f/pyproject.toml`
- **S8 — Reference-viewer template:**
  `https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/ad30107c31c06aec8a7d5636e0d1058118604e6f/src/reference_agent/viewer/templates/viz.html`
- **S9 — W3C PROV-DM:**
  `https://www.w3.org/TR/2013/REC-prov-dm-20130430/`

Limitations: no Google Catalog exchange, upstream-tool execution, cross-host
installation, learning-outcome evaluation, or OKF implementation was performed.
Issue-state claims were excluded because independent retrieval was incomplete.
