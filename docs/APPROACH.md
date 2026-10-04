# Clear writing. Richer explanations.

STE-Pro Max helps an AI agent turn source material into something a reader can
understand and inspect: prose when prose is enough; diagrams, interactive HTML,
or a narrated explanation when those formats help.

## What is STE?

**STE means Simplified Technical English.** ASD-STE100 is a controlled language
with writing rules and a controlled vocabulary for technical communication.
See the [official introduction](https://www.asd-ste100.org/about.html).

STE-Pro Max uses an STE-inspired house style: short, clear sentences; consistent
terms; explicit meaning; and facts before polish. It does not implement the full
standard and is **not ASD-STE100 certification**. A shorter sentence is not an
improvement if it loses an important condition or changes the claim.

## Karpathy's ideas, made practical

In his [October 2, 2026 post](https://x.com/karpathy/status/2105819303471976479),
Karpathy suggests making model output easier to understand through clearer
STE-style writing, useful diagrams and images, interactive HTML, and bespoke
narrated explanations. He also encourages useful custom software artifacts.

| Idea | What you can ask for |
| --- | --- |
| Clearer writing | A dense update rewritten as a useful brief |
| Show the mechanism | A labeled diagram or step-by-step walkthrough |
| Make it explorable | A small HTML lab with controls that change the example |
| Explain through a story | An incident review, research digest, or decision brief with evidence |
| Narrate when useful | A reviewed script and a separately supported voice/video workflow |

The suggested “80%” relaxation is a **style preference, not a score**. The post
does not prescribe a renderer, require every output format, or endorse this
project. Read the [source note](../skills/ste-promax/references/source-evidence.md)
for the distinction between the post, its infographic, and the standard.

## Three skills, one workflow

- **`ste-promax`** — clear technical and executive writing.
- **`ste-visual-docs`** — diagrams, charts, and hands-on explanations.
- **`ste-storytelling`** — evidence-linked briefs, walkthroughs, and stories.

Supply the material and name the outcome. The agent chooses a useful structure,
uses its native tools, and checks the output. A short rewrite stays a short
rewrite. A single-purpose explanation does not need to become a new application.

The [standalone examples](EXAMPLES.md) use inline HTML, CSS, SVG, and JavaScript.
No Python, build, external fonts, or background service is required.
The [optional engine](AUTHORING.md) adds deterministic schemas and batch
rendering; it is **not required by the installed authoring skills**.

## What stays intact

- Facts, units, dates, attribution, and meaningful uncertainty.
- The distinction between an observation, an inference, and a proposal.
- The user's requested format and the source's actual scope.
- Evidence readers can inspect alongside the explanation.

Source material is not permission to execute commands, approve a decision, or
publish. The host's model access, tools, approvals, and privacy rules still apply.
Local HTML does not make the entire assistant session offline.

Host-authored output does not automatically receive the optional engine's schema
or hash checks. Narration/video requires a separately available tool, reviewed
content, and verification of the actual output. See [tested scope](VALIDATION.md).
