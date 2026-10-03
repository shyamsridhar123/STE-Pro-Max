"""Example-first documentation contracts; no image/Markdown package or network."""
from pathlib import Path
import re
import struct
import unittest
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ("brief-transformation", "retry-storm", "retry-lab", "release-brief", "rate-lab")


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
                         "examples/showcase/README.md"):
            self.assert_local_links_resolve(document)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/README.md", readme)
        self.assertIn("docs/APPROACH.md", readme)
        self.assertIn("docs/EXAMPLES.md", readme)
        hub = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        for page in ("PLUGINS.md", "EXAMPLES.md", "APPROACH.md", "AUTHORING.md", "VALIDATION.md"):
            self.assertIn(page, hub)

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
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        approach = (ROOT / "docs/APPROACH.md").read_text(encoding="utf-8")
        for host, verb in (("copilot", "install"), ("claude", "install"), ("codex", "add")):
            self.assertIn(f"{host} plugin {verb} ste-pro-max@ste-pro-max-plugins", readme)
        self.assertIn("v0.4.0", readme)
        self.assertNotIn("python quickstart.py", readme)
        self.assertNotIn("git clone", readme)
        self.assertNotIn("--plugin-dir", readme)
        self.assertIn("not required by the installed authoring skills", approach)
        self.assertIn("No Python setup", readme)
        self.assertIn("not ASD-STE100 certification", readme)
        self.assertNotIn("pip install ste-pro-max", readme)

    def test_readme_defines_ste_and_links_actual_karpathy_post_without_claiming_endorsement(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        approach = (ROOT / "docs/APPROACH.md").read_text(encoding="utf-8")
        self.assertIn("STE means Simplified Technical English", readme)
        self.assertIn("https://x.com/karpathy/status/2105819303471976479", readme)
        self.assertIn("style preference, not a score", approach)
        self.assertIn("endorse this", approach)

    def test_readme_sells_the_result_before_reference_detail_and_stays_short(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        showcase = readme.index("## Show, don't tell")
        install = readme.index("## Install the plugin")
        explanation = readme.index("## Clear writing. Richer explanations.")
        self.assertLess(showcase, install)
        self.assertLess(install, explanation)
        self.assertNotIn("## What stays honest", readme)
        self.assertLessEqual(sum(bool(line.strip()) for line in readme.splitlines()), 100)
        self.assertLess(len(readme.split()), 500)


if __name__ == "__main__":
    unittest.main()
