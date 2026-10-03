"""README delivery contracts; no image/Markdown package or network required."""
from pathlib import Path
import re
import struct
import unittest
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]


def heading_ids(markdown):
    return {
        re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", heading.lower()))
        for heading in re.findall(r"^#{1,6}\s+(.+)$", markdown, re.M)
    }


class ReadmeTests(unittest.TestCase):
    def test_local_readme_links_and_fragments_resolve(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        links = re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", readme)
        self.assertGreater(len(links), 20)
        for href in links:
            with self.subTest(href=href):
                parsed = urlsplit(href)
                if parsed.scheme:
                    self.assertEqual(parsed.scheme, "https")
                    continue
                target = ROOT / unquote(parsed.path) if parsed.path else ROOT / "README.md"
                self.assertTrue(target.resolve().is_relative_to(ROOT))
                self.assertTrue(target.is_file(), href)
                if parsed.fragment and target.suffix == ".md":
                    self.assertIn(parsed.fragment, heading_ids(target.read_text(encoding="utf-8")))

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

    def test_showcase_is_real_webp_and_not_only_referenced_remotely(self):
        image = (ROOT / "docs/assets/showcase.webp").read_bytes()
        self.assertEqual(image[:4], b"RIFF")
        self.assertEqual(image[8:12], b"WEBP")
        self.assertGreater(len(image), 10_000)
        self.assertLess(len(image), 1_000_000)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("](docs/assets/showcase.webp)", readme)
        self.assertIn("Real rendered examples", readme)

    def test_quickstart_and_preview_branch_are_explicit(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("python quickstart.py --open", readme)
        self.assertIn("git clone --branch feat/comprehensive-suite", readme)
        self.assertIn("--no-install", readme)
        self.assertIn("First-time setup may download", readme)
        self.assertIn("not ASD-STE100 certification", readme)
        self.assertNotIn("pip install ste-pro-max", readme)


if __name__ == "__main__":
    unittest.main()
