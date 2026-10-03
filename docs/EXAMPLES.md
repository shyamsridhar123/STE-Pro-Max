# See what you can make

Five self-contained examples. Real HTML, real controls, no build or server.
Every source is fictional or an explicitly stated mathematical model.

## Get the files

[Download the repository ZIP](https://github.com/shyamsridhar123/STE-Pro-Max/archive/refs/heads/main.zip),
unzip, and open an HTML file in `examples/showcase/`.
GitHub's file viewer displays source code; download the file to interact with it.
The source material is embedded, so each example also works on its own.

The [v0.4.0 examples-only ZIP](https://github.com/shyamsridhar123/STE-Pro-Max/releases/download/v0.4.0/ste-examples.zip)
contains the original retry walkthrough, release brief, and rate lab.
The new brief transformation and retry model are repository examples; they are
not retroactively added to the existing v0.4.0 release.

## A dense update becomes a sharp brief

[Open the source](../examples/showcase/brief-transformation.html) ·
[Preview](assets/brief-transformation.png) ·
[Original note](../examples/showcase/sources/launch-note.md)

A fictional Northstar search pilot becomes a readable briefing. The transformation
keeps 240 assessed questions, 186 accepted answers, 38 needing edits, and 16
unanswered questions intact. It also keeps the limited English-language internal
support scope and the proposed—not started—two-week shadow pilot.

Use the evidence controls to connect the outcome, scope, and next step to the
original paragraph. This is a pre-authored example, not a live model call.

## One request. 81 backend attempts.

[Open the source](../examples/showcase/retry-storm.html) ·
[Preview](assets/retry-storm.png) ·
[Model](../examples/showcase/sources/retry-storm.json)

Under persistent backend failure, four independently retrying layers with three
total attempts each can produce `3 × 3 × 3 × 3 = 81` backend attempts.
With one top-level retry owner and no retries in the other layers, the same
model produces three backend attempts.

Change the layer and attempt controls. Compare the two policies. Reset the
example. These are computed worst-case counts, not telemetry, a timing
simulation, or a universal recommendation for retry policy.

## Numbers you can interrogate

[Open the source](../examples/showcase/rate-lab.html) ·
[Preview](assets/rate-lab.png) ·
[Source note](../examples/clarity-lab/source.md)

Compare 97.4% with 99.7%: **+2.3 percentage points**, about **+2.36% relative**.
Change either rate, try a zero baseline, or reset. The chart stays on a 0–100%
scale. Invalid inputs do not produce a misleading result; no cause is invented.

## Follow a mechanism, one step at a time

[Open the source](../examples/showcase/retry-lab.html) ·
[Animated preview](assets/retry-lab.gif) ·
[Static preview](assets/retry-lab.png)

Follow key K7 and receipt R9 through two requests and one stored record.
Step, scrub, play, or reset the sequential trace. This illustrates the mechanism;
it is not evidence of concurrency, crash, or persistence safety.

## Separate evidence from a decision

[Open the source](../examples/showcase/release-brief.html) ·
[Preview](assets/release-brief.png)

See why passing test-environment checks does not supply a release owner's
approval. Open the source record and reveal the reader-check answer.

## Steal these prompts

Replace the example subject with your own material. Attach the source.

**A brief people will read**
> Use STE-Pro Max to turn this update into a one-screen brief. Lead with the
> takeaway, show the supporting numbers, and keep the caveats that affect the decision.

**A system people can see**
> Use STE visual docs to explain this flow. Show what happens at each step and
> let a new engineer move through it. Keep the source and assumptions visible.

**A claim people can test**
> Use STE-Pro Max to make a small interactive explanation of these numbers.
> Let me change the inputs. Keep units, baselines, and percentage points explicit.

**A story people can follow**
> Use STE storytelling to turn these incident notes into an explorable timeline.
> Separate what happened, what we think caused it, and what is still unknown.

**A narrated explainer**
> Use STE storytelling to prepare an explanation of this concept, with a script
> and visuals. Review the story before using an available narration or video tool.

## Adapt, don't just reskin

Read the [template guide](../examples/showcase/README.md). Replace the fictional
source with supplied evidence, then check the rewritten claims, calculations,
controls, narrow layout, keyboard use, print, and no-JavaScript view.
Successful rendering is not proof that an explanation is true or that a reader
has learned it.
