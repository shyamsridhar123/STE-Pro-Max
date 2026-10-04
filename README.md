<p align="center">
  <img src="docs/assets/hero.png" alt="STE-Pro Max — Complex ideas. Clear explanations. Write, visualize, explain." width="720">
</p>

# STE-Pro Max

**Stop shipping walls of text. Make complex ideas click.**

Turn dense docs, tangled systems, and raw numbers into **sharp briefs, visual
explanations, and interactive mini-labs**—with the AI agent you already use.

**GitHub Copilot · Claude Code · Codex.** Native plugin. No Python setup.

[See the results](#show-dont-tell) · [Install](#install-the-plugin) · [Get the demos](docs/EXAMPLES.md#get-the-files) · [Docs](docs/README.md)

## Show, don't tell

### One request. 81 backend attempts.

> “Show me why retries multiply. Let me change the rules.”

[![Working retry model: four layers with three attempts each produce 81 backend attempts; one retry owner produces three.](docs/assets/retry-storm.gif)](examples/showcase/retry-storm.html)

Change the layers. Change the attempts. Watch the multiplication—and compare
one retry owner. [Explore the model](examples/showcase/retry-storm.html) · [Still image](docs/assets/retry-storm.png).

### The update nobody reads → the brief everyone gets

> “Turn this pilot write-up into a one-screen briefing. Keep the evidence.”

[![A dense Northstar pilot note becomes a visual brief: 186 of 240 answers accepted, limits visible, shadow pilot proposed.](docs/assets/brief-transformation.png)](examples/showcase/brief-transformation.html)

Buried findings become a clear takeaway. Highlight the numbers, scope, and
next step to trace them back to the source. [Explore the brief](examples/showcase/brief-transformation.html).

### Don't just quote the number. Let people question it.

> “Explain 97.4% → 99.7%. Let me change the baseline.”

[![An interactive rate comparison keeps a zero-based scale and separates 2.3 percentage points from 2.36 percent relative change.](docs/assets/rate-lab.png)](examples/showcase/rate-lab.html)

Move the inputs. See **percentage points vs. relative change** update together.
[Try the rate lab](examples/showcase/rate-lab.html).

**Working HTML, not UI mockups.** Fictional data and illustrative models.
[Get the examples](docs/EXAMPLES.md#get-the-files), open an HTML file, start exploring. No build or server.

## Install the plugin

Choose your agent. Install **v0.4.0**, restart it, and bring your own material.

<details open>
<summary><strong>GitHub Copilot CLI</strong></summary>

```sh
copilot plugin marketplace add shyamsridhar123/STE-Pro-Max#v0.4.0
copilot plugin install ste-pro-max@ste-pro-max-plugins
```

</details>

<details>
<summary><strong>Claude Code</strong></summary>

```sh
claude plugin marketplace add shyamsridhar123/STE-Pro-Max#v0.4.0
claude plugin install ste-pro-max@ste-pro-max-plugins
```

</details>

<details>
<summary><strong>Codex CLI</strong></summary>

```sh
codex plugin marketplace add shyamsridhar123/STE-Pro-Max --ref v0.4.0
codex plugin add ste-pro-max@ste-pro-max-plugins
```

</details>

> Use STE-Pro Max on this material. Make it clear, visual, and interactive where it helps.

[Host versions, updates & uninstall](docs/PLUGINS.md) · [More prompts](docs/EXAMPLES.md#steal-these-prompts)

## Clear writing. Richer explanations.

**STE means Simplified Technical English.** Clear sentences. Consistent terms.
Meaning intact. We combine those principles with
[Karpathy’s ideas for better model output](https://x.com/karpathy/status/2105819303471976479):
show the mechanism, make it explorable, narrate when useful.

STE-inspired, not ASD-STE100 certification. [The approach](docs/APPROACH.md).

[Documentation](docs/README.md) · [All examples](docs/EXAMPLES.md) · [Advanced engine](docs/AUTHORING.md) · [Apache-2.0](LICENSE)
