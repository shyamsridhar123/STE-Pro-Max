# Mechanism figures

Use this pattern when a concept is easier to grasp as a working object than as
boxes and arrows. You invent a small machine whose operation *is* the concept,
build it from simple solid parts, and let one model drive both the parts and the
numbers on screen. The method is credited in `NOTICE`; the wording, code, and
starter here are original to STE-Pro Max.

Starter: [token bucket as a hopper and valve](../../../examples/showcase/token-bucket-mechanism.html),
with its retained model in [token-bucket.json](../../../examples/showcase/sources/token-bucket.json).

## 1. Choose the object

- State the concept, the source numbers, and the one misunderstanding to fix.
- Pick a physical object whose working matches the concept's rule. Example: a
  hopper of tokens, refilled by a spout, empties through a valve, one token per
  request.
- Write the mapping from each part to a concept term. Keep it in the source
  JSON (`metaphor.mapping`) and visible near the figure.
- If no honest mechanism fits, use a normal diagram or prose instead.

## 2. Write the parts list

List every part before you draw: name, kind (box or cylinder), position, size,
and which concept term it represents. Use real counts from the source, for
example ten token discs for a capacity of ten. Mark parts that sit inside a
container (`inside`) so the overlap check can allow them.

## 3. One model drives everything

Keep a pure function from the inputs to the state, such as
`simulate(arrivals, seconds)`. The parts list, the labels, the live readout,
and the still table all read from that state. Do not type numbers twice.
Retain the defaults, formulas, and boundary examples in a source JSON, and test
that the model reproduces them.

## 4. Project and paint back to front

- Use a fixed isometric camera: ground x and y at ±30°, z straight up.
- Draw each solid with three visible faces in distinct tones (top, left, right)
  plus one edge colour. Keep tones as theme variables so light and dark agree.
- Paint back to front. A part is behind another when it ends before the other
  begins on x, y, or z. Contents paint before their container's front glass.
- Check that no two solids intersect, in every reachable state.

## 5. Frame it as a card

Give the figure a numbered title, a one-line model statement, a hint for the
controls, and a live readout in plain sentences. Put a visible badge that says
the mechanism is illustrative. Add a still reading path (a table or text with the
default run) that works without JavaScript or motion.

## 6. Motion and controls

- Every resting state must explain something on its own. Motion only connects
  states.
- Provide equivalent controls: sliders, buttons, pointer drag, and keyboard keys
  on the focused figure. Include Play/Pause and Reset.
- Under `prefers-reduced-motion: reduce`, remove tweens and keep discrete steps.
  Never start playback automatically.

## STE guardrails

- Label the metaphor as illustrative. The hopper is not part of any rate limiter.
- Keep source numbers, units, and tick order exactly as stated. Show assumptions
  such as "refill first, then admit" next to the figure.
- Do not let the machine imply causes, guarantees, or abilities the source does
  not support: no queueing, retries, latency, or fairness unless the source says so.
- State the model's limits in the artifact, not only in this guide.

## Self-check

- [ ] The source JSON holds inputs, formulas, defaults, boundary cases, and limits.
- [ ] Tests reproduce the defaults and boundaries from the model.
- [ ] The overlap check passes for every reachable state.
- [ ] Paint order respects the behind relation; contents sit inside containers.
- [ ] Readout, labels, and still table agree with the model.
- [ ] Keyboard, pointer, reset, and narrow layout work.
- [ ] Light and dark themes and reduced motion were inspected in a browser.
- [ ] The artifact has no external scripts, fonts, or network requests.
