# Source evidence

Retrieved and checked on October 3, 2026.

## Karpathy's post

- [Complete original post](https://x.com/karpathy/status/2105819303471976479)
- [Attached infographic](https://x.com/karpathy/status/2105819303471976479/photo/1)
- [First-party metadata](https://cdn.syndication.twimg.com/tweet-result?id=2105819303471976479&lang=en&token=0)

Published October 2, 2026, at 00:37 UTC—October 1 at 7:37 PM in Chicago.
The complete long-form text was read on X; its public embed exposes only the
opening. The post contains one image and no attached video. No author-written
follow-up was found in the focused conversation search; that is not proof none exists.

### Paraphrase

Karpathy suggests making model output easier to understand as people spend more
time supervising work done by models. Try controlled, STE-style writing, or a
relaxed approximation when its constraints feel excessive. Use diagrams or images
when they explain a topic better than prose. Ask for HTML when visual design,
interaction, and animation would help. Explore bespoke narrated explainers inspired
by 3Blue1Brown, with ElevenLabs or a free local narration alternative. More broadly,
experiment with useful custom software artifacts whose creation previously cost
too much to justify.

### Implementation boundary

The post proposes richer output options, not a requirement to emit every format
for every answer. It specifies no renderer or hosting service and does not mention
PaperBoard. The repo's native PaperBoard adaptation follows the user's separate
choice and explicit permission. Third-party replies naming other tools are not
treated as Karpathy's requirements.

## The standard is a separate source

[ASD-STE100 Issue 9](https://www.asd-ste100.org/assets/files/ASD-STE100_ISSUE9.pdf),
dated January 15, 2025, was checked directly against relevant rule and dictionary
text. See the [qualified checklist](style-checklist.md) for rule/page references.
The infographic omits exceptions and contains dictionary inaccuracies; it is not a
normative validator specification.

This repo intentionally offers an STE-inspired house style. Its arithmetic,
length checks, renderer validation, and output tests do not establish compliance
with the full standard.

## Technical implementation evidence

- PaperBoard baseline: `All-The-Vibes/ATV-PaperBoard` at
  `4b068bcab8e4dc105f0ef975ee224564f5d63383`; see `docs/PROVENANCE.md` in the repo.
- [HyperFrames WAAPI adapter](https://github.com/heygen-com/hyperframes/blob/main/skills/hyperframes-animation/adapters/waapi.md):
  native finite animations can be paused and deterministically sought without GSAP.
- [HyperFrames HTML schema](https://github.com/heygen-com/hyperframes/blob/main/docs/reference/html-schema.mdx):
  root timing and explicit audio IDs/timing are part of the composition contract.

Record actual installed versions and integration results in `docs/VALIDATION.md`.
Upstream documentation alone is not evidence that a local capability works.
