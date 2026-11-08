// OpenCode V2 Effect plugin entry point for STE-Pro-Max tools and skills.
// Registers the 4 bundled STE skills and 10 top-level guarded STE tools
// (`options: { codemode: false }`) validated through the shared Python dispatcher,
// without intercepting or restricting other host tools, sessions, or commands.

import { Plugin } from "@opencode/plugin/effect";
import { Error as ToolError } from "@opencode/plugin/promise/tool";
import { Effect } from "effect";

import {
  BUNDLE_ROOT,
  DISPATCH_PY_PATH,
  OPENCODE_PLUGIN_ID,
  STE_SKILL_IDS,
  STE_TOOL_NAMES,
  STE_TOOL_SCHEMAS,
  createSteOpenCodePlugin,
} from "./core.js";

const stePlugin = createSteOpenCodePlugin({
  PluginApi: Plugin,
  ToolErrorClass: ToolError,
  EffectApi: Effect,
  bundleRoot: BUNDLE_ROOT,
  dispatchPyPath: DISPATCH_PY_PATH,
});

export {
  BUNDLE_ROOT,
  DISPATCH_PY_PATH,
  OPENCODE_PLUGIN_ID,
  STE_SKILL_IDS,
  STE_TOOL_NAMES,
  STE_TOOL_SCHEMAS,
  createSteOpenCodePlugin,
  stePlugin,
};
export default stePlugin;
