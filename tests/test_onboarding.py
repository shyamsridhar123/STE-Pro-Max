"""First-run UX regression tests, including real rendering and isolated entrypoints."""
import contextlib
import hashlib
from importlib import metadata
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ste_promax import cli, onboarding

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "ste_promax" / "data" / "quickstart.json"


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "notes.md"
        self.original = "# Résumé — 決定\n\nKeep the evidence and uncertainty.\r\n".encode()
        self.source.write_bytes(self.original)

    def run_cli(self, *args, encoding=None):
        with contextlib.ExitStack() as stack:
            streams = [stack.enter_context(io.TextIOWrapper(io.BytesIO(), encoding=encoding, errors="strict")
                                           if encoding else io.StringIO()) for _ in range(2)]
            output, error = streams
            with patch("ste_promax.onboarding.Path.cwd", return_value=self.root), \
                 contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                code = cli.main(list(args))
                self.assertIs(sys.stdout, output)
                self.assertIs(sys.stderr, error)
                for stream in streams:
                    self.assertFalse(stream.closed)
                    self.assertEqual(stream.encoding, encoding)
                    if isinstance(stream, io.TextIOWrapper):
                        self.assertEqual(stream.errors, "strict")
            text = []
            for stream in streams:
                stream.flush()
                if isinstance(stream, io.TextIOWrapper):
                    stream.seek(0)
                    text.append(stream.read())
                else:
                    text.append(stream.getvalue())
            return code, *text

    def display_text(self, text, encoding):
        return text.encode(encoding, "backslashreplace").decode(encoding) if encoding else text

    def test_human_output_does_not_swallow_stream_errors(self):
        for error in (BrokenPipeError("closed pipe"), ValueError("closed stream"), RuntimeError("write failed")):
            with self.subTest(error=error), io.StringIO() as stream, \
                 patch.object(stream, "write", side_effect=error):
                with self.assertRaises(type(error)) as caught:
                    onboarding._print_human("日本語😀", file=stream)
                self.assertIs(caught.exception, error)

    def test_doctor_unicode_human_and_json_on_legacy_and_unencoded_streams(self):
        executable = str(self.root / "日本語😀" / "python.exe")
        for encoding in ("cp1252", "ascii", None):
            for as_json in (False, True):
                with self.subTest(encoding=encoding, json=as_json), \
                     patch("ste_promax.onboarding.util.find_spec", return_value=object()), \
                     patch("ste_promax.onboarding.metadata.version",
                           side_effect={"Jinja2": "3.1.6", "PyYAML": "6.0.3",
                                        "MarkupSafe": "3.0.3"}.__getitem__), \
                     patch("ste_promax.onboarding.sys.executable", executable), \
                     patch("ste_promax.onboarding.shutil.which", return_value=executable), \
                     patch("ste_promax.onboarding.platform.platform", return_value="Windows 日本語😀"):
                    expected = onboarding.doctor_report()
                    code, output, error = self.run_cli("doctor", *(["--json"] if as_json else []),
                                                       encoding=encoding)
                self.assertEqual(code, 0, error)
                self.assertEqual(error, "")
                if as_json:
                    self.assertEqual(output, json.dumps(expected, ensure_ascii=True, indent=2) + "\n")
                    self.assertEqual(json.loads(output), expected)
                else:
                    self.assertIn("Local environment: ready", output)
                    self.assertIn(self.display_text(executable, encoding), output)
                    self.assertIn(self.display_text("Windows 日本語😀", encoding), output)
                    self.assertIn("Required render: Jinja2", output)
                    self.assertIn("Optional: Node.js", output)

    def test_unicode_start_paths_open_and_json_on_legacy_and_unencoded_streams(self):
        for encoding in ("cp1252", None):
            for as_json in (False, True):
                for open_result in ("not requested", True, False, OSError("日本語😀 unavailable")):
                    with self.subTest(encoding=encoding, json=as_json, open_result=open_result):
                        directory = self.root / (
                            f"日本語😀-{encoding}-{as_json}-{type(open_result).__name__}-{open_result}")
                        args = ["start", str(self.source), "--output-dir", str(directory)]
                        if as_json:
                            args.append("--json")
                        if open_result != "not requested":
                            args.append("--open")
                        with patch("webbrowser.open", return_value=open_result,
                                   side_effect=open_result if isinstance(open_result, Exception) else None) as browser:
                            code, output, error = self.run_cli(*args, encoding=encoding)
                        manifest = json.loads((directory / "manifest.json").read_bytes())
                        html = Path(manifest["files"]["html"]["path"])
                        self.assertTrue(html.is_file())
                        self.assertEqual(html.parent, directory)
                        self.assertEqual(manifest["status"], "complete")
                        self.assertEqual((directory / "source.md").read_bytes(), self.original)
                        if open_result == "not requested":
                            browser.assert_not_called()
                        else:
                            browser.assert_called_once_with(html.as_uri())
                        if as_json:
                            self.assertEqual(output, json.dumps(manifest, ensure_ascii=True, indent=2) + "\n")
                            self.assertEqual(json.loads(output), manifest)
                        else:
                            self.assertIn("Local artifact: complete", output)
                            self.assertIn("Open: " + self.display_text(str(html), encoding), output)
                            self.assertIn("Gallery: " + self.display_text(
                                manifest["files"]["gallery"]["path"], encoding), output)
                        if open_result is False or isinstance(open_result, Exception):
                            self.assertEqual(code, 2)
                            self.assertIn("Browser launch failed", error)
                            self.assertIn("Output preserved; open " + self.display_text(str(html), encoding), error)
                            if isinstance(open_result, Exception):
                                self.assertIn(self.display_text(str(open_result), encoding), error)
                        else:
                            self.assertEqual(code, 0, error)
                            self.assertEqual(error, "")

    def test_unicode_failed_start_warning_is_safe_and_never_opens(self):
        failed = {"status": "failed", "files": {}, "warnings": ["Native renderer failed: 日本語😀"]}
        for encoding in ("cp1252", None):
            with self.subTest(encoding=encoding), \
                 patch("ste_promax.onboarding.start", return_value=failed), patch("webbrowser.open") as browser:
                code, output, error = self.run_cli("start", "--open", encoding=encoding)
            self.assertEqual(code, 2, error)
            self.assertIn(self.display_text(f"Warning: {failed['warnings'][0]}", encoding), output)
            browser.assert_not_called()

    def bundle(self, *args, no_site=False):
        command = [sys.executable, "-B"]
        if no_site:
            command.append("-S")
        return subprocess.run([*command, str(ROOT), *args], cwd=self.root, capture_output=True,
                              encoding="utf-8", check=False, timeout=30)

    def manifest(self, *args):
        code, output, error = self.run_cli("start", *args, "--json")
        self.assertEqual(code, 0, error)
        result = json.loads(output)
        self.assertEqual(result["status"], "complete")
        directory = Path(result["files"]["html"]["path"]).parent
        self.assertEqual(json.loads((directory / "manifest.json").read_bytes()), result)
        for item in result["files"].values():
            path = Path(item["path"])
            self.assertTrue(path.is_file())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item["sha256"])
        return result, directory

    def test_no_command_is_helpful_success_and_nonmutating(self):
        before = set(self.root.iterdir())
        with patch("webbrowser.open") as browser:
            code, output, error = self.run_cli()
        self.assertEqual(code, 0, error)
        self.assertIn("start", output)
        self.assertIn("doctor", output)
        self.assertIn("--open", output)
        browser.assert_not_called()
        result = self.bundle(no_site=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("First result", result.stdout)
        self.assertEqual(before, set(self.root.iterdir()))

    def test_doctor_clean_json_read_only(self):
        before = set(self.root.iterdir())
        with patch("ste_promax.onboarding.util.find_spec", return_value=object()), \
             patch("ste_promax.onboarding.metadata.version",
                   side_effect={"Jinja2": "3.1.6", "PyYAML": "6.0.3", "MarkupSafe": "3.0.3"}.__getitem__), \
             patch("ste_promax.onboarding.shutil.which", return_value=None), \
             patch("webbrowser.open") as browser:
            code, output, error = self.run_cli("doctor", "--json")
        self.assertEqual(code, 0, error)
        report = json.loads(output)
        self.assertEqual(report["status"], "ready")
        self.assertEqual(len(report["required_render"]), 3)
        self.assertTrue(all(item["version_compatible"] for item in report["required_render"][:2]))
        self.assertIsNone(report["required_render"][2]["version_compatible"])
        self.assertEqual(len(report["optional"]), 4)
        self.assertIn("Nothing was installed", " ".join(report["hints"]))
        self.assertEqual(before, set(self.root.iterdir()))
        browser.assert_not_called()

    def test_doctor_checks_declared_stable_numeric_version_bounds(self):
        cases = [
            ("Jinja2", "3.1.5", False), ("Jinja2", "3.1.6", True), ("Jinja2", "3.2", True),
            ("Jinja2", "4.0.0", False), ("Jinja2", "5.0", False), ("Jinja2", "3.1.6rc1", False),
            ("PyYAML", "6.0.2", False), ("PyYAML", "6.0.3", True), ("PyYAML", "6.1", True),
            ("PyYAML", "7.0.0", False), ("PyYAML", "8.0", False), ("PyYAML", "6.0.3.dev1", False),
            ("Jinja2", "unrecognized", False), ("PyYAML", "", False),
        ]
        for distribution, version, expected in cases:
            with self.subTest(distribution=distribution, version=version):
                versions = {"Jinja2": "3.1.6", "PyYAML": "6.0.3", "MarkupSafe": "3.0.3"}
                versions[distribution] = version
                with patch("ste_promax.onboarding.util.find_spec", return_value=object()), \
                     patch("ste_promax.onboarding.metadata.version", side_effect=versions.__getitem__):
                    code, output, _ = self.run_cli("doctor", "--json")
                report = json.loads(output)
                dependency = next(item for item in report["required_render"] if item["name"] == distribution)
                self.assertTrue(dependency["available"])
                self.assertEqual(dependency["version_compatible"], expected)
                self.assertEqual(report["status"], "ready" if expected else "missing_requirements")
                self.assertEqual(code, 0 if expected else 2)

    def test_doctor_missing_metadata_fails_closed_for_direct_dependencies(self):
        for distribution in ("Jinja2", "PyYAML", "MarkupSafe"):
            with self.subTest(distribution=distribution):
                def version(name):
                    if name == distribution:
                        raise metadata.PackageNotFoundError(name)
                    return {"Jinja2": "3.1.6", "PyYAML": "6.0.3", "MarkupSafe": "3.0.3"}[name]

                with patch("ste_promax.onboarding.util.find_spec", return_value=object()), \
                     patch("ste_promax.onboarding.metadata.version", side_effect=version):
                    code, output, _ = self.run_cli("doctor", "--json")
                dependency = next(item for item in json.loads(output)["required_render"]
                                  if item["name"] == distribution)
                self.assertFalse(dependency["metadata_available"])
                self.assertIsNone(dependency["version"])
                if distribution == "MarkupSafe":
                    self.assertIsNone(dependency["version_compatible"])
                    self.assertEqual(code, 0)
                else:
                    self.assertFalse(dependency["version_compatible"])
                    self.assertEqual(code, 2)

    def test_doctor_requires_transitive_markupsafe_discovery(self):
        with patch("ste_promax.onboarding.util.find_spec",
                   side_effect=lambda module: None if module == "markupsafe" else object()), \
             patch("ste_promax.onboarding.metadata.version",
                   side_effect={"Jinja2": "3.1.6", "PyYAML": "6.0.3", "MarkupSafe": "3.0.3"}.__getitem__):
            code, output, _ = self.run_cli("doctor", "--json")
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(output)["required_render"][2]["available"])

    def test_doctor_missing_dependencies_without_render_imports(self):
        result = self.bundle("doctor", "--json", no_site=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "missing_requirements")
        self.assertFalse(any(item["available"] for item in report["required_render"]))
        self.assertIn("pip install", " ".join(report["hints"]))
        script = (
            "import sys; from ste_promax.onboarding import doctor_report; doctor_report(); "
            "assert not {'yaml', 'jinja2', 'markupsafe', 'ste_promax.render'} & sys.modules.keys()"
        )
        probe = subprocess.run([sys.executable, "-B", "-S", "-c", script], cwd=ROOT,
                               capture_output=True, text=True, check=False, timeout=30)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertFalse((self.root / "artifacts").exists())

    def test_doctor_human_distinguishes_required_and_optional(self):
        code, output, error = self.run_cli("doctor")
        self.assertEqual(code, 0, error)
        self.assertIn("Required render: Jinja2", output)
        self.assertIn("Optional: Windows System.Speech", output)
        self.assertIn("Discovery only", output)

    def test_doctor_unsupported_python_is_not_ready(self):
        with patch("ste_promax.onboarding.sys.version_info", (3, 9)):
            code, output, _ = self.run_cli("doctor", "--json")
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(output)["python"]["supported"])

    def test_missing_dependencies_fail_before_output(self):
        for source in ([], [str(self.source)]):
            with self.subTest(source=source):
                result = self.bundle("start", *source, no_site=True)
                self.assertEqual(result.returncode, 2)
                self.assertIn("Jinja2 and PyYAML", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse((self.root / "artifacts").exists())

    def test_zero_input_real_demo_has_two_beats_evidence_visual_and_question(self):
        original = SAMPLE.read_bytes()
        with patch("webbrowser.open") as browser:
            result, directory = self.manifest()
        browser.assert_not_called()
        data = json.loads((directory / "input.json").read_bytes())
        self.assertEqual(data["title"], "A check is not an approval")
        self.assertEqual(data["purpose"], "decision-brief")
        self.assertEqual(len(data["beats"]), 2)
        self.assertTrue(data["sources"])
        self.assertTrue(data["beats"][1]["question"])
        self.assertEqual(len(result["visuals"]), 1)
        self.assertTrue((directory / "visual-01.svg").is_file())
        self.assertEqual(directory.parent, self.root / "artifacts")
        self.assertEqual(SAMPLE.read_bytes(), original)
        self.assertEqual((directory / "source.json").read_bytes(), original)
        self.assertFalse(result["trusted_html"])

    def test_supplied_source_json_unicode_and_input_preservation(self):
        result, directory = self.manifest(str(self.source))
        self.assertEqual((directory / "source.md").read_bytes(), self.original)
        self.assertEqual(self.source.read_bytes(), self.original)
        data = json.loads((directory / "input.json").read_bytes())
        self.assertEqual(data["title"], "Résumé — 決定")
        self.assertEqual(result["source_path"], str(self.source))
        self.assertIn("決定", (directory / "input.json").read_text(encoding="utf-8"))

    def test_repeated_runs_use_fresh_directories(self):
        first, first_dir = self.manifest(str(self.source))
        second, second_dir = self.manifest(str(self.source))
        self.assertNotEqual(first_dir, second_dir)
        self.assertEqual(first["source_sha256"], second["source_sha256"])
        self.assertTrue(first_dir.is_dir())

    def test_random_name_collision_does_not_overwrite(self):
        with patch("ste_promax.onboarding.secrets.token_hex", return_value="a" * 16):
            _, directory = self.manifest(str(self.source))
            original = (directory / "manifest.json").read_bytes()
            code, _, error = self.run_cli("start", str(self.source))
        self.assertEqual(code, 2)
        self.assertIn("existing files", error)
        self.assertEqual((directory / "manifest.json").read_bytes(), original)

    def test_relative_source_from_unrelated_cwd(self):
        result = self.bundle("start", "notes.md", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(result.stdout)
        directory = Path(manifest["files"]["html"]["path"]).parent
        self.assertEqual(directory.parent, self.root / "artifacts")
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_explicit_relative_output_and_design(self):
        design = self.root / "my-design.md"
        original = next((ROOT / "ste_promax" / "designs").glob("*.DESIGN.md")).read_bytes()
        design.write_bytes(original)
        result = self.bundle("start", "notes.md", "--output-dir", "custom/result", "--design",
                             "my-design.md", "--title", "Custom title", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(result.stdout)
        self.assertEqual(Path(manifest["files"]["html"]["path"]).parent, self.root / "custom" / "result")
        self.assertEqual(Path(manifest["files"]["input_design"]["path"]).read_bytes(), original)
        self.assertEqual(design.read_bytes(), original)
        self.assertFalse((self.root / "artifacts").exists())

    def test_hostile_titles_cannot_control_auto_output(self):
        for title in ("../../CON", "NUL", "C:\\outside\\x; & calc", "你好", "." * 1000):
            with self.subTest(title=title):
                _, directory = self.manifest(str(self.source), "--title", title)
                self.assertEqual(directory.parent, self.root / "artifacts")
                self.assertRegex(directory.name, r"^brief-[a-z0-9-]+-[a-f0-9]{16}$")
                self.assertLessEqual(len(directory.name), 79)

    def test_bad_inputs_and_design_fail_without_output(self):
        cases = [("bad.json", '{"kind":"story"}'), ("bad.json", '{"title": NaN}'),
                 ("bad.json", "{broken"), ("empty.md", ""), ("bad.txt", "text")]
        for filename, text in cases:
            with self.subTest(text=text):
                path = self.root / filename
                path.write_text(text, encoding="utf-8")
                code, _, _ = self.run_cli("start", str(path))
                self.assertEqual(code, 2)
                self.assertFalse((self.root / "artifacts").exists())
        for flags in (["--title", ""], ["--design", str(self.root / "missing.md")]):
            code, _, _ = self.run_cli("start", str(self.source), *flags)
            self.assertEqual(code, 2)
            self.assertFalse((self.root / "artifacts").exists())
        design = self.root / "bad-design.md"
        design.write_text("# Not a token document", encoding="utf-8")
        code, _, _ = self.run_cli("start", str(self.source), "--design", str(design))
        self.assertEqual(code, 2)
        self.assertFalse((self.root / "artifacts").exists())

    def test_empty_path_arguments_are_not_silently_defaulted(self):
        for arguments in ([""], [str(self.source), "--output-dir", ""],
                          [str(self.source), "--design", " "]):
            with self.subTest(arguments=arguments):
                code, _, error = self.run_cli("start", *arguments)
                self.assertEqual(code, 2)
                self.assertIn("must not be empty", error)
                self.assertFalse((self.root / "artifacts").exists())

    def test_raw_html_refused_unless_explicitly_trusted(self):
        for suffix, original in ((".html", b"<h1>Reviewed HTML</h1>"),
                                 (".json", b'{"body_html":"<b>reviewed</b>","trusted_html":true}')):
            with self.subTest(suffix=suffix):
                source = self.root / ("reviewed" + suffix)
                source.write_bytes(original)
                code, _, error = self.run_cli("start", str(source))
                self.assertEqual(code, 2)
                self.assertIn("--trusted-html", error)
                result, directory = self.manifest(str(source), "--trusted-html")
                self.assertTrue(result["trusted_html"])
                self.assertEqual(source.read_bytes(), original)
                self.assertEqual((directory / ("source" + suffix)).read_bytes(), original)

    def test_existing_output_and_source_collision_are_rejected(self):
        existing = self.root / "existing"
        existing.mkdir()
        for path in (existing, self.source, self.root):
            with self.subTest(path=path):
                code, _, _ = self.run_cli("start", str(self.source), "--output-dir", str(path))
                self.assertEqual(code, 2)
        self.assertEqual(list(existing.iterdir()), [])
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_output_traversal_is_rejected(self):
        code, _, error = self.run_cli("start", str(self.source), "--output-dir",
                                     str(self.root / "new" / ".." / "escape"))
        self.assertEqual(code, 2)
        self.assertIn("must not contain", error)
        self.assertFalse((self.root / "new").exists())

    def test_auto_output_reparse_parent_is_rejected(self):
        artifacts = self.root / "artifacts"
        original_lstat = Path.lstat

        def fake_lstat(path):
            if path == artifacts:
                return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
            return original_lstat(path)

        with patch.object(Path, "lstat", fake_lstat):
            code, _, error = self.run_cli("start", str(self.source))
        self.assertEqual(code, 2)
        self.assertIn("reparse", error)
        self.assertFalse(artifacts.exists())

    def test_symlink_parent_and_dangling_link_are_rejected(self):
        artifacts = self.root / "artifacts"
        original_lstat = Path.lstat

        def fake_lstat(path):
            if path == artifacts:
                return SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0)
            return original_lstat(path)

        with patch.object(Path, "lstat", fake_lstat):
            code, _, error = self.run_cli("start", str(self.source))
        self.assertEqual(code, 2)
        self.assertIn("symbolic", error)
        self.assertFalse(artifacts.exists())

    def test_real_directory_symlink_parent(self):
        target = self.root / "target"
        target.mkdir()
        link = self.root / "artifacts"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"Host cannot create symlinks: {exc}")
        code, _, error = self.run_cli("start", str(self.source))
        self.assertEqual(code, 2)
        self.assertIn("symbolic", error)
        self.assertEqual(list(target.iterdir()), [])

    def test_human_summary_includes_result_path_and_material_warnings(self):
        code, output, error = self.run_cli("start", str(self.source))
        self.assertEqual(code, 0, error)
        self.assertIn("Local artifact: complete", output)
        self.assertIn("Open:", output)
        self.assertIn("Gallery:", output)
        self.assertIn("review remain manual", output)
        self.assertNotIn('"status":', output)

    def test_open_success_uses_file_uri_only_after_success(self):
        with patch("webbrowser.open", return_value=True) as browser:
            _, directory = self.manifest(str(self.source), "--open")
        browser.assert_called_once()
        uri = browser.call_args.args[0]
        self.assertTrue(uri.startswith(directory.as_uri() + "/"))
        self.assertTrue(uri.endswith(".html"))

    def test_open_failure_preserves_outputs_and_json_manifest(self):
        for effect in (False, OSError("browser unavailable")):
            with self.subTest(effect=effect):
                with patch("webbrowser.open", side_effect=effect if isinstance(effect, Exception) else None,
                           return_value=False):
                    code, output, error = self.run_cli("start", str(self.source), "--open", "--json")
                self.assertEqual(code, 2)
                result = json.loads(output)
                self.assertEqual(result["status"], "complete")
                directory = Path(result["files"]["html"]["path"]).parent
                self.assertEqual(json.loads((directory / "manifest.json").read_bytes()), result)
                self.assertIn("Browser launch failed", error)
                self.assertIn("Output preserved", error)
                self.assertTrue(Path(result["files"]["html"]["path"]).is_file())

    def test_failed_render_never_opens_browser(self):
        failed = {"status": "failed", "files": {}, "warnings": ["Native renderer failed."]}
        with patch("ste_promax.cli.render", return_value=failed) as renderer, \
             patch("webbrowser.open") as browser:
            code, output, _ = self.run_cli("start", str(self.source), "--open", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output), failed)
        renderer.assert_called_once()
        browser.assert_not_called()


if __name__ == "__main__":
    unittest.main()
