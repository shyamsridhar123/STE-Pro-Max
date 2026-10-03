# Low-friction authoring

The agent handles routine mechanics. The user keeps control of meaning and
consequential actions.

## One request, one useful result

1. Read the supplied material and reuse context already in the conversation.
   A short rewrite needs no file, CLI, dependency installation, or new interview.
2. Honor the requested output. Otherwise choose prose for a finding, a diagram
   for relationships/order, a chart for quantities, or a story for an explanation
   that benefits from ordered evidence. Do not generate every format.
3. Pick the audience, title, and layout from context. State a material assumption
   briefly; ask only when the answer changes the facts, conclusion, or safe scope.
4. Author the minimum valid source in the user's workspace. Keep original facts,
   qualifications, units, and citations. Do not ask the user to hand-write JSON.
5. Run `python "<bundle-root>" start "<absolute-source>" --json` from that workspace.
   The command preserves input bytes and chooses a fresh output directory.
   Use an explicit `--output-dir` only when the user supplies one.
6. Read the result and inspect the actual output. Return an openable artifact and
   a short summary with material limits. Do not make the user browse a build log.

If the host supports local artifact panels, open the resulting file there.
Otherwise return its absolute path. `--open` is an explicit browser-launch option,
not a default action or a substitute for verification.

## Setup without surprises

`doctor --json` reports the current interpreter, dependency readiness, and optional
capabilities without installing anything. Do not re-run it on every request.
If the user requests setup, the repo's `quickstart.py` can prepare an isolated
workspace environment. Explain that the first missing-dependency setup can
download declared Python packages. Never mutate a global environment, a shared
plugin cache, or an existing unrelated environment to make a command pass.

No API key is required by the native renderer. The chosen assistant host may
still process the conversation through its own provider; local rendering is not
a guarantee that the entire assistant session is offline.

## Gates that convenience must not remove

- Missing evidence is not filled with invented claims, numbers, or causal arrows.
- Third-party HTML is not automatically trusted. `--trusted-html` is deliberate.
- A prepared narration is not a movie; final preview approval still precedes export.
- Uploads, publication, paid providers, global installation, and host permissions
  need the applicable user request and host approval.
- Failed preparation remains a failed artifact with evidence, not a silent retry
  that overwrites the source.

Successful defaults remove repetitive choices, not these boundaries.
