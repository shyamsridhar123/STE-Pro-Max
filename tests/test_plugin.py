"""Universal source bundle checks, including real extracted native rendering."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_plugin", ROOT / "tools/build_plugin.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source"
        self.source.mkdir()
        files = ("__main__.py", "pyproject.toml", "README.md", "LICENSE", "NOTICE", "plugin.json",
                 ".claude-plugin/plugin.json", ".claude-plugin/marketplace.json",
                 ".github/plugin/marketplace.json", ".agents/plugins/marketplace.json", "STE-ProMAX.zip")
        for relative in files:
            target = self.source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        for name in ("ste_promax", "skills", "examples", "docs", "ste-promax"):
            shutil.copytree(ROOT / name, self.source / name, symlinks=True)
        self.output = self.root / "build"

    def build(self):
        return builder.build_plugin(self.output, source_root=self.source)

    def test_native_manifest_identities_and_fixed_skill_path(self):
        portable = json.loads((self.source / "plugin.json").read_text())
        claude = json.loads((self.source / ".claude-plugin/plugin.json").read_text())
        self.assertEqual(portable["$schema"], "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json")
        self.assertNotIn("$schema", claude)
        for manifest in (portable, claude):
            self.assertEqual(manifest["name"], "ste-pro-max")
            self.assertEqual(manifest["version"], "0.2.0")
            self.assertEqual(manifest["author"]["name"], "Shyam Sridhar")
            self.assertEqual(manifest["repository"], "https://github.com/shyamsridhar123/STE-Pro-Max")
            self.assertEqual(manifest["license"], "Apache-2.0")
            self.assertNotIn("skills", manifest)
            self.assertNotIn("mcpServers", manifest)
            self.assertNotIn("hooks", manifest)
        for skill in ("ste-promax", "ste-visual-docs", "ste-storytelling"):
            self.assertTrue((self.source / "skills" / skill / "SKILL.md").is_file())
        allowed = {"$schema", "name", "version", "description", "author", "homepage",
                   "repository", "license", "keywords", "extensions"}
        self.assertLessEqual(set(portable), allowed)
        for relative in (".claude-plugin/marketplace.json", ".github/plugin/marketplace.json"):
            catalog = json.loads((self.source / relative).read_text())
            self.assertEqual(catalog["name"], "ste-pro-max-plugins")
            self.assertEqual(catalog["owner"]["name"], "Shyam Sridhar")
            self.assertEqual(len(catalog["plugins"]), 1)
            item = catalog["plugins"][0]
            self.assertEqual((item["name"], item["version"], item["source"]), ("ste-pro-max", "0.2.0", "./"))
            self.assertTrue((self.source / item["source"] / "plugin.json").is_file())
        claude_catalog = json.loads((self.source / ".claude-plugin/marketplace.json").read_text())
        self.assertIsInstance(claude_catalog["description"], str)
        self.assertTrue(claude_catalog["description"].strip())
        codex = json.loads((self.source / ".agents/plugins/marketplace.json").read_text())
        self.assertEqual(codex["name"], "ste-pro-max-plugins")
        self.assertEqual(len(codex["plugins"]), 1)
        item = codex["plugins"][0]
        self.assertEqual(item["name"], "ste-pro-max")
        self.assertEqual(item["source"], {"source": "local", "path": "./"})
        self.assertEqual(item["policy"], {"installation": "AVAILABLE", "authentication": "ON_INSTALL"})
        self.assertEqual(item["category"], "Productivity")

    def test_payload_whitelist_and_private_state_exclusion(self):
        forbidden = (
            ".omx/state/private.json", ".git/config", "MEMORY.md", "omx_wiki/private.md",
            "tests/test_private.py", "artifacts/private.html", ".env", "credentials.json",
            "ste_promax/__pycache__/private.pyc", "skills/.env.json",
            "skills/ste-promax/credentials.json", "docs/MEMORY.md", "examples/.git/config",
            "examples/artifacts/private.html", "ste_promax/private.pem",
            "docs/secrets.txt", "examples/api-key.json", "skills/ste-promax/credentials.local.json",
            ".agents/private.md", ".agents/plugins/private.json", ".github/workflows/private.yml",
            ".github/plugin/private.json", ".codex/config.toml",
        )
        for relative in forbidden:
            target = self.source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("PRIVATE SENTINEL")
        manifest = self.build()
        required = {
            "plugin.json", ".claude-plugin/plugin.json", ".claude-plugin/marketplace.json",
            ".github/plugin/marketplace.json", ".agents/plugins/marketplace.json", "ste_promax/render.py",
            "ste_promax/templates/atv-tier.html.j2", "ste_promax/templates/gallery.html.j2",
            "ste_promax/designs/paperboard.DESIGN.md", "skills/ste-promax/SKILL.md",
            "ste_promax/scripts/narrate.ps1", "__main__.py", "pyproject.toml",
            "ste_promax/diagrams.py", "ste_promax/charts.py", "ste_promax/stories.py", "ste_promax/media.py",
            "ste_promax/section_schema.py", "ste_promax/templates/story.html.j2",
            "ste_promax/templates/story-video.html.j2", "skills/ste-visual-docs/SKILL.md",
            "skills/ste-storytelling/SKILL.md", "docs/AUTHORING.md",
            "LICENSE", "NOTICE", "ste-promax/SKILL.md", "STE-ProMAX.zip", "docs/PLUGINS.md",
        }
        self.assertLessEqual(required, set(manifest["files"]))
        self.assertFalse(set(forbidden) & set(manifest["files"]))
        for parent, exact in ((".agents/", ".agents/plugins/marketplace.json"),
                              (".github/", ".github/plugin/marketplace.json")):
            self.assertEqual([path for path in manifest["files"] if path.startswith(parent)], [exact])
        self.assertEqual(sum(path.endswith("/render.py") for path in manifest["files"]), 1)
        for relative in manifest["files"]:
            self.assertEqual((self.output / "ste-pro-max" / relative).read_bytes(),
                             (self.source / relative).read_bytes())
        with zipfile.ZipFile(self.output / "ste-pro-max.zip") as archive:
            for name in archive.namelist():
                self.assertTrue(name.startswith("ste-pro-max/"))
                self.assertNotIn("..", Path(name).parts)
                self.assertNotIn(b"PRIVATE SENTINEL", archive.read(name))

    def test_deterministic_zip_and_hash_manifest(self):
        first = self.build()
        first_zip = (self.output / "ste-pro-max.zip").read_bytes()
        for path in self.source.rglob("*"):
            if path.is_file():
                os.utime(path, (1700000000, 1700000000))
        self.output = self.root / "second"
        second = self.build()
        second_zip = (self.output / "ste-pro-max.zip").read_bytes()
        self.assertEqual(first_zip, second_zip)
        self.assertEqual(first, second)
        self.assertEqual(json.loads((self.output / "hashes.json").read_text()), second)
        self.assertEqual(second["archive"]["sha256"], hashlib.sha256(second_zip).hexdigest())
        self.assertEqual(second["archive"]["size"], len(second_zip))
        with zipfile.ZipFile(self.output / "ste-pro-max.zip") as archive:
            self.assertEqual(archive.namelist(), sorted(archive.namelist()))
            for entry in archive.infolist():
                relative = entry.filename.removeprefix("ste-pro-max/")
                content = archive.read(entry)
                self.assertEqual(entry.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(second["files"][relative]["sha256"], hashlib.sha256(content).hexdigest())
                self.assertEqual(second["files"][relative]["size"], len(content))
                self.assertEqual(content, (self.output / "ste-pro-max" / relative).read_bytes())

    def test_refuses_existing_empty_or_nonempty_output(self):
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError, "must be new"):
            self.build()
        sentinel = self.output / "keep.txt"
        sentinel.write_text("KEEP")
        with self.assertRaisesRegex(ValueError, "must be new"):
            self.build()
        self.assertEqual(list(self.output.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_text(), "KEEP")

    def test_missing_source_fails_before_output_writes(self):
        (self.source / "ste_promax/templates/atv-tier.html.j2").unlink()
        with self.assertRaisesRegex(ValueError, "Missing required"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_missing_output_parent_is_not_created(self):
        self.output = self.root / "missing parent" / "build"
        with self.assertRaisesRegex(ValueError, "parent directory"):
            self.build()
        self.assertFalse(self.output.parent.exists())

    def test_refuses_output_inside_whitelisted_source(self):
        self.output = self.source / "docs" / "build"
        with self.assertRaisesRegex(ValueError, "whitelisted"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_symlink_payload_is_refused(self):
        target = self.source / "ste_promax/linked.py"
        try:
            target.symlink_to(self.source / "__main__.py")
        except OSError as exc:
            self.skipTest(f"Local symlink creation unavailable: {exc}")
        with self.assertRaisesRegex(ValueError, "Symlinks/reparse"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_windows_reparse_attribute_is_refused(self):
        target = self.source / "ste_promax/render.py"
        original_lstat = Path.lstat

        def lstat(path):
            info = original_lstat(path)
            if path == target:
                class Reparse:
                    st_mode = info.st_mode
                    st_file_attributes = stat.FILE_ATTRIBUTE_REPARSE_POINT
                return Reparse()
            return info
        with patch.object(Path, "lstat", lstat):
            with self.assertRaisesRegex(ValueError, "Symlinks/reparse"):
                self.build()
        self.assertFalse(self.output.exists())

    def test_output_through_symlink_is_refused(self):
        target = self.root / "keep"
        target.mkdir()
        link = self.root / "linked-output-parent"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"Local symlink creation unavailable: {exc}")
        self.output = link / "build"
        with self.assertRaisesRegex(ValueError, "Symlinks/reparse"):
            self.build()
        self.assertEqual(list(target.iterdir()), [])

    def test_real_extracted_bundle_launch_and_render_from_arbitrary_cwd(self):
        self.build()
        extracted = self.root / "extracted"
        with zipfile.ZipFile(self.output / "ste-pro-max.zip") as archive:
            archive.extractall(extracted)
        bundle = extracted / "ste-pro-max"
        self.assertFalse((bundle / "tests").exists())
        self.assertFalse((bundle / ".codex").exists())
        for relative in (".agents/plugins/marketplace.json", ".github/plugin/marketplace.json",
                         ".claude-plugin/marketplace.json", "docs/PLUGINS.md"):
            self.assertEqual((bundle / relative).read_bytes(), (self.source / relative).read_bytes())
        workspace = self.root / "unrelated workspace"
        workspace.mkdir()
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["PATH"] = str(workspace)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        self.assertIsNone(shutil.which("paperboard", path=env["PATH"]))
        version = subprocess.run([sys.executable, "-B", str(bundle), "--version"],
                                 cwd=workspace, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertEqual(version.stdout.strip(), "0.2.0")
        source = workspace / "notes.md"
        content = b"# Bundle render\r\n\r\nSource stays unchanged.\r\n"
        source.write_bytes(content)
        rendered = subprocess.run([sys.executable, "-B", str(bundle), "render", str(source),
                                   "--output-dir", str(workspace / "artifact")],
                                  cwd=workspace, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        manifest = json.loads(rendered.stdout)
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["renderer"], "ste_promax.render")
        for name in ("html", "design", "meta", "gallery"):
            self.assertTrue(Path(manifest["files"][name]["path"]).is_file())
        self.assertEqual(source.read_bytes(), content)
        self.assertEqual((workspace / "artifact/source.md").read_bytes(), content)
        self.assertNotIn("fonts.googleapis.com", Path(manifest["files"]["html"]["path"]).read_text())

    def test_extracted_bundle_runs_suite_commands_from_an_unrelated_workspace(self):
        self.build()
        extracted = self.root / "extracted-suite"
        with zipfile.ZipFile(self.output / "ste-pro-max.zip") as archive:
            archive.extractall(extracted)
        bundle = extracted / "ste-pro-max"
        workspace = self.root / "user-workspace"
        workspace.mkdir()
        source = workspace / "story.json"
        shutil.copyfile(ROOT / "examples/suite/retry-explanation.json", source)
        audio = workspace / "audio"
        audio.mkdir()
        for name, seconds in (("trace", 8), ("count", 2)):
            with wave.open(str(audio / (name + ".wav")), "wb") as stream:
                stream.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
                stream.writeframes(b"\xf0\xd8\x10\x27" * (4000 * seconds))

        def run(*args):
            process = subprocess.run([sys.executable, "-B", str(bundle), *map(str, args)],
                                     cwd=workspace, capture_output=True, text=True, timeout=45)
            self.assertEqual(process.returncode, 0, process.stderr)
            return json.loads(process.stdout)

        self.assertIn("beats", run("schema", "story")["fields"])
        artifact = run("render", source, "--output-dir", workspace / "story")
        self.assertEqual(artifact["status"], "complete")
        self.assertEqual(len(artifact["visuals"]), 2)
        self.assertTrue((workspace / "story" / "evidence.json").is_file())
        prepared = run("narrate", source, "--audio-dir", audio, "--output-dir", workspace / "media")
        self.assertEqual(prepared["status"], "prepared_not_rendered")
        self.assertEqual(prepared["narration"], "provided PCM")
        self.assertEqual(prepared["duration_seconds"], 10)
        timeline = json.loads((workspace / "media" / "timeline.json").read_bytes())
        self.assertEqual(len(timeline["beats"][0]["stages"]), 5)
        self.assertTrue((bundle / "ste_promax/scripts/narrate.ps1").is_file())
        self.assertEqual((workspace / "media" / "source.json").read_bytes(), source.read_bytes())
        self.assertFalse(list((workspace / "media").glob("*.mp4")))

    def test_cli_reports_failure_without_side_effects(self):
        self.output.mkdir()
        with contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(builder.main(["--output-dir", str(self.output)]), 2)
        self.assertIn("must be new", error.getvalue())
        self.assertEqual(list(self.output.iterdir()), [])

    def test_real_builder_cli(self):
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "tools/build_plugin.py"), "--output-dir", str(self.output)],
            cwd=self.root, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(result.stdout)
        self.assertEqual(manifest["bundle_type"], "source")
        self.assertEqual(manifest, json.loads((self.output / "hashes.json").read_text()))
        self.assertTrue((self.output / "ste-pro-max/skills/ste-promax/SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
