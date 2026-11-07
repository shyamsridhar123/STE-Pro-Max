"""Offline installer boundary checks; no package installation or network."""
import io
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

from tools.provision_skillc_runtime import extract_source, target_entry


class RuntimeProvisioningTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def test_declared_binary_entry_stays_inside_environment(self):
        environment = self.root / "python"
        site = environment / "Lib" / "site-packages"
        self.assertEqual(target_entry(site, environment, "../../bin/z3.exe"), environment / "bin/z3.exe")

    def test_distribution_escape_is_refused(self):
        environment = self.root / "python"
        site = environment / "Lib" / "site-packages"
        with self.assertRaisesRegex(ValueError, "escapes destination"):
            target_entry(site, environment, "../../../outside.txt")

    def test_source_bytes_preserved_and_existing_file_not_overwritten(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("src/skillc/__init__.py", b"# exact source\n")
        destination = self.root / "source"
        self.assertEqual(extract_source(buffer.getvalue(), destination), 1)
        source = destination / "src/skillc/__init__.py"
        self.assertEqual(source.read_bytes(), b"# exact source\n")
        with self.assertRaises(FileExistsError):
            extract_source(buffer.getvalue(), destination)
        self.assertEqual(source.read_bytes(), b"# exact source\n")

    def test_archive_traversal_and_symlinks_are_refused(self):
        for name, mode in (("../outside.txt", stat.S_IFREG), ("link", stat.S_IFLNK)):
            with self.subTest(name=name):
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w") as archive:
                    entry = zipfile.ZipInfo(name)
                    entry.external_attr = (mode | 0o644) << 16
                    archive.writestr(entry, b"outside")
                with self.assertRaisesRegex(ValueError, "Unsafe source archive"):
                    extract_source(buffer.getvalue(), self.root / "refused-source")
                self.assertFalse((self.root / "outside.txt").exists())


if __name__ == "__main__":
    unittest.main()
