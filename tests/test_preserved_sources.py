import hashlib
from pathlib import Path
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class PreservedSourceTests(unittest.TestCase):
    def test_imported_bytes_are_unchanged(self):
        originals = {
            "STE-ProMAX.zip": "9AEF3BFC674679BE945CF812D32E2233F4683E158661A9C49EE02D31E0CB6F49",
            "ste-promax/SKILL.md": "E7D580281112FD76D7A74150EB029F7F81F90DF726F9623E30199F178091163D",
            "ste-promax/agents/openai.yaml": "DE2184D0787E9BC7880C24A39CBCDAFD1B8882DB1361ED04D442E58D4AD96304",
        }
        for relative, expected in originals.items():
            with self.subTest(file=relative):
                self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest().upper(), expected)

    def test_archive_and_extracted_sources_match(self):
        with zipfile.ZipFile(ROOT / "STE-ProMAX.zip") as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(len(archive.infolist()), 2)
            for entry in archive.infolist():
                self.assertEqual(archive.read(entry), (ROOT / entry.filename).read_bytes())


if __name__ == "__main__":
    unittest.main()
