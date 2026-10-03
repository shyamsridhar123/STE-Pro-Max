import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BundleEntrypointTests(unittest.TestCase):
    def test_checker_needs_no_third_party_packages(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "notes.md"
            source.write_text("Validation remains incomplete.", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-S", str(ROOT), "check", str(source), "--json"],
                cwd=temp, capture_output=True, text=True, check=False, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsInstance(json.loads(result.stdout), dict)

    def test_missing_renderer_dependencies_are_explicit_and_nonmutating(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp).resolve()
            source = workspace / "notes.md"
            source.write_text("Validation remains incomplete.", encoding="utf-8")
            output = workspace / "output"
            result = subprocess.run(
                [sys.executable, "-S", str(ROOT), "render", str(source), "--output-dir", str(output)],
                cwd=workspace, capture_output=True, text=True, check=False, timeout=30,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Jinja2 and PyYAML", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(output.exists())

    def test_bundle_runs_from_an_unrelated_workspace(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp).resolve()
            source = workspace / "notes.md"
            source.write_text("# Local result\n\nValidation is incomplete.\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT), "render", str(source),
                 "--output-dir", str(workspace / "artifact")],
                cwd=workspace, capture_output=True, text=True, check=False, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(result.stdout)
            self.assertEqual(manifest["renderer"], "ste_promax.render")
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(Path(manifest["files"]["html"]["path"]).parent, workspace / "artifact")
            self.assertEqual(source.read_text(), "# Local result\n\nValidation is incomplete.\n")


if __name__ == "__main__":
    unittest.main()
