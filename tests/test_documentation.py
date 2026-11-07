"""Example-first documentation contracts; no image/Markdown package or network."""
from pathlib import Path
import json
import re
import struct
import unittest
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ("brief-transformation", "retry-storm", "retry-lab", "release-brief", "rate-lab",
            "retry-observatory")


def heading_ids(markdown):
    return {
        re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", heading.lower()))
        for heading in re.findall(r"^#{1,6}\s+(.+)$", markdown, re.M)
    }


class ReadmeTests(unittest.TestCase):
    def assert_local_links_resolve(self, document):
        source = (ROOT / document).read_text(encoding="utf-8")
        links = re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", source)
        self.assertTrue(links)
        for href in links:
            with self.subTest(document=document, href=href):
                parsed = urlsplit(href)
                if parsed.scheme:
                    self.assertEqual(parsed.scheme, "https")
                    continue
                target = ((ROOT / document).parent / unquote(parsed.path)
                          if parsed.path else ROOT / document)
                self.assertTrue(target.resolve().is_relative_to(ROOT))
                self.assertTrue(target.is_file(), href)
                if parsed.fragment and target.suffix == ".md":
                    self.assertIn(parsed.fragment, heading_ids(target.read_text(encoding="utf-8")))

    def test_local_readme_links_and_fragments_resolve(self):
        self.assert_local_links_resolve("README.md")

    def test_moved_reference_material_remains_discoverable_and_linked(self):
        for document in ("docs/README.md", "docs/APPROACH.md", "docs/EXAMPLES.md",
                         "docs/SKILLC_GATE.md", "docs/SKILLC_CREDITS.md", "docs/PROVENANCE.md",
                         "docs/IMPLEMENTATION.md", "docs/VALIDATION.md", "docs/AUTHORING.md",
                         "examples/showcase/README.md", "docs/LINE_STUDIO.md",
                         "skills/ste-line-studio/SKILL.md", "skills/ste-line-studio/references/authoring.md",
                         "skills/ste-line-studio/references/mechanism-figures.md",
                         "skills/ste-promax/SKILL.md", "skills/ste-promax/references/output-modes.md"):
            self.assert_local_links_resolve(document)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/README.md", readme)
        self.assertIn("docs/APPROACH.md", readme)
        self.assertIn("docs/EXAMPLES.md", readme)
        hub = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        for page in ("PLUGINS.md", "EXAMPLES.md", "APPROACH.md", "AUTHORING.md", "VALIDATION.md"):
            self.assertIn(page, hub)

    def test_skillc_scope_impact_and_upstream_credit_are_explicit(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        guide = (ROOT / "docs/SKILLC_GATE.md").read_text(encoding="utf-8")
        credits = (ROOT / "docs/SKILLC_CREDITS.md").read_text(encoding="utf-8")
        notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
        for command in ("render", "narrate", "export"):
            self.assertIn(f"`{command}`", readme)
        self.assertIn("No manual approval", readme)
        self.assertIn("tools check their work before reporting success", readme)
        self.assertIn("not an English tutor or fact-checker", readme)
        self.assertIn("Why it is relevant to STE-Pro Max", guide)
        self.assertIn("For a short conversational rewrite", guide)
        self.assertLess(guide.index("Why it is relevant"), guide.index("Implementation details"))
        self.assertIn("timeouts fail open", guide)
        self.assertIn("not pre-display semantic gates", guide)
        for page in ("docs/SKILLC_GATE.md", "docs/SKILLC_CREDITS.md"):
            self.assertIn(page, readme)
        version = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))["version"]
        self.assertIn(f"## Automatic SkillC checks in v{version}", readme)
        self.assertNotIn("unreleased", readme.lower())
        self.assertIn("Impact: what changes and what does not", guide)
        self.assertIn("Same-user shell or filesystem access", guide)
        self.assertIn("Gina Tcchen and contributors", credits)
        self.assertIn("Anonymous Author(s)", credits)
        self.assertIn("25cc63bf82e968da7d01e204dc6d99879b76c45b", credits)
        self.assertIn("Copyright (c) 2026 Gina Tcchen and contributors", notice)
        self.assertIn("Apache", notice)
        self.assertIn("MIT", notice)

    def test_hero_is_real_wide_png_with_bounded_readme_weight(self):
        image = (ROOT / "docs/assets/hero.png").read_bytes()
        self.assertEqual(image[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", image[16:24])
        self.assertGreaterEqual(width, 1400)
        self.assertGreater(width / height, 2)
        self.assertLess(len(image), 2_000_000)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertRegex(readme, r'<img src="docs/assets/hero\.png" alt="[^"]{30,}"')
        provenance = (ROOT / "docs/assets/README.md").read_text(encoding="utf-8")
        self.assertIn("GPT Image 2.5 Sunburst", provenance)
        self.assertIn("conceptual brand artwork", provenance)

    def test_real_examples_have_local_previews_and_standalone_sources(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        guide = (ROOT / "docs/EXAMPLES.md").read_text(encoding="utf-8")
        for name in EXAMPLES:
            with self.subTest(name=name):
                image = (ROOT / f"docs/assets/{name}.png").read_bytes()
                self.assertEqual(image[:8], b"\x89PNG\r\n\x1a\n")
                self.assertLess(len(image), 1_000_000)
                self.assertIn(f"examples/showcase/{name}.html", guide)
                html = (ROOT / f"examples/showcase/{name}.html").read_text(encoding="utf-8")
                self.assertNotRegex(html, r'(?i)(?:src|href)=["\']https?://')
                self.assertNotRegex(html, r"(?i)\b(?:fetch|XMLHttpRequest|WebSocket|localStorage)\s*[\.(]")
                self.assertIn("<noscript>", html)
        for name in ("retry-lab", "retry-storm"):
            with self.subTest(gif=name):
                gif = (ROOT / f"docs/assets/{name}.gif").read_bytes()
                self.assertIn(gif[:6], (b"GIF87a", b"GIF89a"))
                self.assertLess(len(gif), 3_000_000)
        for name in ("brief-transformation", "retry-storm", "rate-lab"):
            self.assertIn(f"examples/showcase/{name}.html", readme)
        self.assertIn("Working HTML, not UI mockups.", readme)
        self.assertIn("Fictional data and illustrative models.", readme)
        self.assertIn("not retroactively added", guide)

    def test_native_install_not_python_is_the_product_entry(self):
        version = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))["version"]
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        approach = (ROOT / "docs/APPROACH.md").read_text(encoding="utf-8")
        for host, verb in (("copilot", "install"), ("claude", "install"), ("codex", "add")):
            self.assertIn(f"{host} plugin {verb} ste-pro-max@ste-pro-max-plugins", readme)
        self.assertIn(f"v{version}", readme)
        self.assertNotIn("python quickstart.py", readme)
        self.assertNotIn("git clone", readme)
        self.assertNotIn("--plugin-dir", readme)
        self.assertIn("configured runtime", approach)
        self.assertTrue("v0.5.0 does not include it" in readme or "configured runtime" in readme)
        self.assertNotIn("No Python setup", readme)
        self.assertIn("not ASD-STE100 certification", readme)
        self.assertNotIn("pip install ste-pro-max", readme)

    def test_mechanism_figure_guide_is_linked_and_keeps_guardrails(self):
        guide = "mechanism-figures.md"
        for document in ("skills/ste-line-studio/SKILL.md", "skills/ste-promax/SKILL.md",
                         "skills/ste-promax/references/output-modes.md"):
            self.assertIn(guide, (ROOT / document).read_text(encoding="utf-8"), document)
        text = (ROOT / "skills/ste-line-studio/references" / guide).read_text(encoding="utf-8")
        for phrase in ("illustrative", "prefers-reduced-motion", "Self-check", "back to front"):
            self.assertIn(phrase, text)
        self.assertIn("token-bucket-mechanism.html", (ROOT / "examples/showcase/README.md").read_text(encoding="utf-8"))
        self.assertIn("wheresryan22/anatomy", (ROOT / "NOTICE").read_text(encoding="utf-8"))
        for name in ("token-bucket-mechanism.png", "token-bucket-mechanism-dark.png"):
            self.assertEqual((ROOT / "docs/assets" / name).read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        for document in ("README.md", "docs/EXAMPLES.md", "docs/LINE_STUDIO.md"):
            self.assertIn("assets/token-bucket-mechanism.png", (ROOT / document).read_text(encoding="utf-8"))

    def test_line_studio_uses_the_existing_showcase_structure(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        showcase = readme.split("## Show, don't tell", 1)[1].split("## Install the plugin", 1)[0]
        match = re.search(r"^### Line Studio: [^\n]+\n(.*?)(?=^### |\Z)", showcase, re.M | re.S)
        self.assertIsNotNone(match, "Line Studio needs a named showcase subsection.")
        section = match.group(1)
        self.assertRegex(section, r"(?m)^> .+")
        self.assertRegex(
            section,
            r"\[!\[[^\]]+\]\(docs/assets/retry-observatory\.png\)\]"
            r"\(examples/showcase/retry-observatory\.html\)",
        )
        self.assertIn("docs/LINE_STUDIO.md", section)
        self.assertIn("New in v0.5.0", section)
        self.assertNotIn("Development preview", section)
        self.assertNotIn("certified", section.lower())

    def test_release_install_pins_and_feature_availability_match_manifest(self):
        version = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))["version"]
        for document in ("README.md", "docs/PLUGINS.md"):
            source = (ROOT / document).read_text(encoding="utf-8")
            self.assertIn(
                f"copilot plugin marketplace add shyamsridhar123/STE-Pro-Max#v{version}",
                source,
            )
            self.assertIn("legacy v0.5.0 skills", source)
            self.assertIn("claude plugin marketplace add shyamsridhar123/STE-Pro-Max#v0.5.0", source)
            self.assertIn("codex plugin marketplace add shyamsridhar123/STE-Pro-Max --ref v0.5.0", source)
            self.assertNotIn(
                f"claude plugin marketplace add shyamsridhar123/STE-Pro-Max#v{version}",
                source,
            )
            self.assertNotIn(
                f"codex plugin marketplace add shyamsridhar123/STE-Pro-Max --ref v{version}",
                source,
            )
        for document in ("docs/LINE_STUDIO.md", "skills/ste-line-studio/SKILL.md",
                         "examples/showcase/README.md", "docs/EXAMPLES.md"):
            source = (ROOT / document).read_text(encoding="utf-8")
            self.assertIn("v0.5.0", source)
            for stale in ("**in development**", "**In development.", "development preview",
                          "not a published `v0.5.0`", f"not a published `v{version}`",
                          "release/tag has been published"):
                self.assertNotIn(stale, source)
        self.assert_local_links_resolve("docs/releases/v0.5.0.md")
        self.assert_local_links_resolve(f"docs/releases/v{version}.md")

    def test_readme_defines_ste_and_links_actual_karpathy_post_without_claiming_endorsement(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        approach = (ROOT / "docs/APPROACH.md").read_text(encoding="utf-8")
        self.assertIn("STE means Simplified Technical English", readme)
        self.assertIn("https://x.com/karpathy/status/2105819303471976479", readme)
        self.assertIn("style preference, not a score", approach)
        self.assertIn("endorse this", approach)

    def test_readme_highlights_ste_and_karpathy_before_examples_and_stays_short(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        ste = readme.index("## STE: the foundation")
        guidelines = readme.index("## Karpathy's guidelines, put to work")
        showcase = readme.index("## Show, don't tell")
        install = readme.index("## Install the plugin")
        self.assertLess(ste, guidelines)
        self.assertLess(guidelines, showcase)
        self.assertLess(showcase, install)
        self.assertIn("STE means Simplified Technical English", readme[ste:guidelines])
        self.assertIn("**Before:**", readme[ste:guidelines])
        self.assertIn("Check the configuration before you deploy.", readme[ste:guidelines])
        playbook = readme[guidelines:showcase]
        self.assertIn("https://x.com/karpathy/status/2105819303471976479", playbook)
        for idea in ("relaxed STE", "diagrams and images", "interactive HTML",
                     "animation", "Narrate", "available media tool", "purpose-built",
                     "smallest useful medium"):
            self.assertIn(idea, playbook)
        self.assertNotIn("## What stays honest", readme)
        self.assertLessEqual(sum(bool(line.strip()) for line in readme.splitlines()), 100)
        self.assertLess(len(readme.split()), 500)


if __name__ == "__main__":
    unittest.main()
