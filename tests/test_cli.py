"""Native CLI boundary tests; fake native modules isolate filesystem failures."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType
from typing import Any
import unittest
from unittest.mock import Mock, patch

from ste_promax import __version__
from ste_promax import cli


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "reviewed.md"
        self.original = b"# Reviewed\r\n\r\nPreserve prose.\r\n"
        self.source.write_bytes(self.original)
        self.output = self.root / "new output"
        self.lint = "true"
        self.html = "<html><head></head><body>Reviewed</body></html>"
        self.render_module = Mock(spec=ModuleType("ste_promax.render"))
        self.gallery_module = Mock(spec=ModuleType("ste_promax.gallery"))
        self.renderer = Mock(side_effect=self.fake_render)
        self.gallery = Mock(side_effect=self.fake_gallery)
        self.render_module.render_artifact = self.renderer
        self.render_module.validate_input = Mock()
        self.gallery_module.regenerate_gallery = self.gallery

    def fake_render(self, input_data, design_path: Path | None = None, output_dir: Path | None = None):
        self.input_data = input_data
        self.design_path = design_path
        self.assertEqual(output_dir, self.output)
        assert output_dir is not None
        triple: dict[str, Any] = {
            name + "_path": output_dir / ("example" + suffix) for name, suffix in
            (("html", ".html"), ("design", ".DESIGN.md"), ("meta", ".meta.yaml"))}
        triple["html_path"].write_text(self.html, encoding="utf-8")
        triple["design_path"].write_text("# Design\n", encoding="utf-8")
        triple["meta_path"].write_text(f"lint_passed: {self.lint}\n", encoding="utf-8")
        triple["slug"] = "example"
        return triple

    def fake_gallery(self, artifact_dir):
        self.assertEqual(artifact_dir, self.output)
        path = artifact_dir / "gallery.html"
        path.write_text(self.html, encoding="utf-8")
        return path

    def run_cli(self, *extra):
        with patch.dict(sys.modules, {"ste_promax.render": self.render_module,
                                      "ste_promax.gallery": self.gallery_module}), \
             contextlib.redirect_stdout(io.StringIO()) as output, \
             contextlib.redirect_stderr(io.StringIO()) as error:
            code = cli.main(["render", str(self.source), "--output-dir", str(self.output), *extra])
        return code, output.getvalue(), error.getvalue()

    def test_native_calls_preserve_inputs_and_manifest_hashes(self):
        code, output, _ = self.run_cli("--title", "Reviewed title")
        self.assertEqual(code, 0)
        manifest = json.loads(output)
        self.renderer.assert_called_once()
        self.gallery.assert_called_once_with(self.output)
        normalized = json.loads((self.output / "input.json").read_bytes())
        self.assertEqual(self.input_data, normalized)
        self.assertEqual(normalized["body_md"], self.original.decode())
        self.assertEqual(normalized["title"], "Reviewed title")
        self.assertNotIn("trusted_html", normalized)
        self.assertEqual((self.output / "source.md").read_bytes(), self.original)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(manifest["renderer"], "ste_promax.render")
        self.assertEqual(json.loads((self.output / "manifest.json").read_text()), manifest)
        for item in manifest["files"].values():
            self.assertEqual(item["sha256"], hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest())
        self.assertTrue(manifest["lint_passed"])
        self.assertNotIn("command", manifest)

    def test_raw_html_requires_explicit_consent_then_preserves_exact_body(self):
        self.source = self.root / "reviewed.html"
        content = b"<section>Authored \xe2\x80\x94 HTML.</section>\r\n"
        self.source.write_bytes(content)
        code, _, error = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("--trusted-html", error)
        self.assertFalse(self.output.exists())
        self.renderer.assert_not_called()
        code, output, _ = self.run_cli("--trusted-html")
        self.assertEqual(code, 0)
        self.assertEqual(self.input_data["body_html"], content.decode())
        self.assertTrue(json.loads(output)["trusted_html"])
        self.assertEqual((self.output / "source.html").read_bytes(), content)
        self.assertEqual(self.source.read_bytes(), content)

    def test_json_cannot_grant_raw_html_consent(self):
        self.source = self.root / "reviewed.json"
        for data in (
            {"body_html": "<b>Raw</b>", "trusted_html": True},
            {"body_html": "", "trusted_html": True},
            {"sections": [{"kind": "sec", "body_html": "<script>run()</script>"}]},
            {"sections": [{"html": "<b>Nested raw</b>"}]},
            {"breadcrumb": "<a href='https://example.org'>Raw</a>"},
        ):
            with self.subTest(data=data):
                self.source.write_text(json.dumps(data), encoding="utf-8")
                code, _, error = self.run_cli()
                self.assertEqual(code, 2)
                self.assertIn("--trusted-html", error)
                self.assertFalse(self.output.exists())
        self.renderer.assert_not_called()

    def test_json_raw_html_with_consent_and_safe_structured_input(self):
        self.source = self.root / "reviewed.json"
        for number, (data, flags) in enumerate((
            ({"body_html": "<b>Reviewed</b>"}, ["--trusted-html"]),
            ({"title": "<script>plain title</script>", "rows": [{"Name": "<b>plain text</b>"}],
              "trusted_html": True}, []),
        )):
            with self.subTest(data=data):
                self.source.write_text(json.dumps(data), encoding="utf-8")
                self.output = self.root / str(number)
                self.assertEqual(self.run_cli(*flags)[0], 0)
                self.assertEqual(self.input_data.get("trusted_html"), data.get("trusted_html"))

    def test_invalid_source_and_design_rejected_before_writes(self):
        for suffix, content in ((".json", b"{bad"), (".json", b"[]"), (".json", b'{"body_html":4}'),
                                (".json", b'{"title":null}'), (".json", b'{"value":NaN}'),
                                (".txt", b"unsupported"), (".md", b""), (".md", b"\xff")):
            with self.subTest(suffix=suffix, content=content):
                self.source = self.root / ("invalid" + suffix)
                self.source.write_bytes(content)
                self.assertEqual(self.run_cli()[0], 2)
                self.assertFalse(self.output.exists())
        self.source = self.root / "reviewed.md"
        self.assertEqual(self.run_cli("--design", str(self.root / "missing.md"))[0], 2)
        self.assertFalse(self.output.exists())
        self.renderer.assert_not_called()

    def test_nonempty_output_and_source_directory_refused(self):
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_text("keep")
        code, _, error = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("empty", error)
        self.assertEqual(list(self.output.iterdir()), [sentinel])
        self.output = self.root
        self.assertEqual(self.run_cli()[0], 2)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.renderer.assert_not_called()

    def test_empty_existing_output_is_accepted(self):
        self.output.mkdir()
        self.assertEqual(self.run_cli()[0], 0)

    def test_design_is_copied_exactly(self):
        design = self.root / "my design.md"
        content = b"# Custom\r\n"
        design.write_bytes(content)
        self.assertEqual(self.run_cli("--design", str(design))[0], 0)
        self.assertEqual(self.design_path, self.output / "input-design.md")
        assert self.design_path is not None
        self.assertEqual(self.design_path.read_bytes(), content)
        self.assertEqual(design.read_bytes(), content)

    def test_markdown_frontmatter_and_json_normalization(self):
        for suffix, content, body in (
            (".md", b"---\r\nauthor: A\r\n---\r\n# Hello\r\n\r\nText.\r\n", "# Hello\r\n\r\nText.\r\n"),
            (".json", b'{ "title":"Hello", "body_md":"Text." }\r\n', "Text."),
        ):
            with self.subTest(suffix=suffix):
                self.source = self.root / ("input" + suffix)
                self.source.write_bytes(content)
                self.output = self.root / suffix[1:]
                self.assertEqual(self.run_cli()[0], 0)
                self.assertEqual(self.input_data["title"], "Hello")
                self.assertEqual(self.input_data["body_md"], body)
                self.assertEqual((self.output / ("source" + suffix)).read_bytes(), content)

    def test_each_missing_triple_member_is_failure(self):
        for key in ("html_path", "design_path", "meta_path"):
            with self.subTest(key=key):
                self.output = self.root / key
                def incomplete(*args, **kwargs):
                    triple = self.fake_render(*args, **kwargs)
                    triple[key].unlink()
                    return triple
                self.renderer.side_effect = incomplete
                code, output, _ = self.run_cli()
                self.assertEqual(code, 2)
                self.assertEqual(json.loads(output)["status"], "failed")

    def test_missing_gallery_not_accepted(self):
        self.gallery.side_effect = lambda output: output / "gallery.html"
        code, output, _ = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("gallery.html", " ".join(json.loads(output)["warnings"]))

    def test_native_and_gallery_exceptions_produce_failure_manifests(self):
        for target in ("renderer", "gallery"):
            with self.subTest(target=target):
                self.output = self.root / target
                self.renderer.side_effect = self.fake_render
                self.gallery.side_effect = self.fake_gallery
                getattr(self, target).side_effect = RuntimeError("deliberate failure")
                code, output, _ = self.run_cli()
                self.assertEqual(code, 2)
                self.assertIn("deliberate failure", " ".join(json.loads(output)["warnings"]))
                self.assertTrue((self.output / "input.json").is_file())
                self.assertEqual(self.source.read_bytes(), self.original)

    def test_false_unknown_duplicate_and_malformed_yaml_lint(self):
        for number, (text, expected) in enumerate((
            ("lint_passed: false\n", False), ("lint_passed: 'true'\n", None),
            ("lint_passed: true\nlint_passed: false\n", None), ("not: [yaml\n", None),
            ("- list\n", None), ("lint_passed: true\r\n", True),
        )):
            with self.subTest(text=text):
                self.output = self.root / str(number)
                def metadata(*args, **kwargs):
                    triple = self.fake_render(*args, **kwargs)
                    triple["meta_path"].write_bytes(text.encode())
                    return triple
                self.renderer.side_effect = metadata
                code, output, _ = self.run_cli()
                self.assertEqual(code, 0)
                self.assertIs(json.loads(output)["lint_passed"], expected)

    def test_invalid_utf8_artifact_is_failure(self):
        def invalid(*args, **kwargs):
            triple = self.fake_render(*args, **kwargs)
            triple["html_path"].write_bytes(b"\xff")
            return triple
        self.renderer.side_effect = invalid
        self.assertEqual(self.run_cli()[0], 2)

    def test_saved_input_mutation_or_removal_is_failure(self):
        for removed in (False, True):
            with self.subTest(removed=removed):
                self.output = self.root / str(removed)
                def mutate(*args, **kwargs):
                    triple = self.fake_render(*args, **kwargs)
                    path = self.output / "input.json"
                    if removed:
                        path.unlink()
                    else:
                        path.write_text("{}")
                    return triple
                self.renderer.side_effect = mutate
                code, output, _ = self.run_cli()
                self.assertEqual(code, 2)
                manifest = json.loads(output)
                self.assertTrue(any("saved input" in warning for warning in manifest["warnings"]))
                self.assertEqual(self.source.read_bytes(), self.original)

    def test_artifact_outside_output_or_colliding_is_rejected(self):
        for collision in (False, True):
            with self.subTest(collision=collision):
                self.output = self.root / str(collision)
                def invalid(*args, **kwargs):
                    triple = self.fake_render(*args, **kwargs)
                    triple["html_path"] = self.output / "gallery.html" if collision else self.source
                    return triple
                self.renderer.side_effect = invalid
                self.assertEqual(self.run_cli()[0], 2)
                self.assertEqual(self.source.read_bytes(), self.original)

    def test_external_references_reported_without_rewriting(self):
        self.html = (
            '<html><body><img src="https://cdn.example.org/image.png">'
            '<style>p {background:url(https://cdn.example.org/bg.png)}</style></body></html>'
        )
        code, output, _ = self.run_cli()
        self.assertEqual(code, 0)
        manifest = json.loads(output)
        self.assertFalse(manifest["offline_verified"])
        self.assertIn("https://cdn.example.org/image.png", manifest["external_references"])
        self.assertIn("https://cdn.example.org/bg.png", manifest["external_references"])
        self.assertEqual((self.output / "example.html").read_text(), self.html)

    def test_removed_wrapper_options_are_rejected(self):
        for option in ("--paperboard", "--paperboard-source", "--offline-fonts"):
            with self.subTest(option=option), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    cli.main(["render", str(self.source), "--output-dir", str(self.output), option])
                self.assertEqual(error.exception.code, 2)
        self.assertFalse(self.output.exists())

    def test_version(self):
        self.assertEqual(__version__, "0.2.0")
        with contextlib.redirect_stdout(io.StringIO()) as output, self.assertRaises(SystemExit) as error:
            cli.main(["--version"])
        self.assertEqual(error.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), "0.2.0")


class NativeIntegrationTests(unittest.TestCase):
    def test_real_native_markdown_json_and_trusted_html_without_processes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            cases = (
                (".md", "# Safe title\r\n\r\n<script>alert(1)</script>\r\n", []),
                (".json", json.dumps({"title": "<img src=x onerror=alert(1)>",
                                      "body_md": "<script>alert(1)</script>", "trusted_html": True}), []),
                (".html", "<section><button>Authored control</button></section>\r\n", ["--trusted-html"]),
            )
            for number, (suffix, text, flags) in enumerate(cases):
                with self.subTest(suffix=suffix):
                    source = root / ("source" + suffix)
                    original = text.encode("utf-8")
                    source.write_bytes(original)
                    output_dir = root / str(number)
                    with patch("subprocess.Popen", side_effect=AssertionError("Native rendering must not spawn")), \
                         contextlib.redirect_stdout(io.StringIO()) as stdout, \
                         contextlib.redirect_stderr(io.StringIO()) as stderr:
                        code = cli.main(["render", str(source), "--output-dir", str(output_dir), *flags])
                    self.assertEqual(code, 0, stderr.getvalue() + stdout.getvalue())
                    manifest = json.loads(stdout.getvalue())
                    self.assertEqual(manifest["status"], "complete")
                    self.assertTrue(manifest["lint_passed"])
                    self.assertEqual(source.read_bytes(), original)
                    self.assertEqual((output_dir / ("source" + suffix)).read_bytes(), original)
                    for name in ("html", "design", "meta", "gallery"):
                        self.assertTrue(Path(manifest["files"][name]["path"]).is_file())
                    rendered = Path(manifest["files"]["html"]["path"]).read_text(encoding="utf-8")
                    self.assertNotIn("fonts.googleapis.com", rendered)
                    if suffix == ".html":
                        self.assertIn("<button>Authored control</button>", rendered)
                        with contextlib.redirect_stderr(io.StringIO()) as error:
                            code = cli.main(["render", str(output_dir / "input.json"),
                                             "--output-dir", str(root / "untrusted-rerender")])
                        self.assertEqual(code, 2)
                        self.assertIn("--trusted-html", error.getvalue())
                        self.assertFalse((root / "untrusted-rerender").exists())
                    else:
                        self.assertNotIn("<script>alert(1)</script>", rendered)
                        self.assertIn("&lt;script&gt;", rendered)
                        self.assertNotIn("<img src=x onerror=alert(1)>", rendered)


class InputFidelityTests(unittest.TestCase):
    def test_unsupported_content_is_rejected_before_any_output(self):
        payloads = [
            {"title": "Report", "sections": [{"kind": "unknown", "text": "Do not deploy."}]},
            {"title": "Report", "rows": [{"Task": "Build"},
                                        {"Task": "Ship", "Qualification": "Do not deploy before approval."}]},
        ]
        for payload in payloads:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as temp:
                source = Path(temp) / "source.json"
                output = Path(temp) / "output"
                source.write_text(json.dumps(payload), encoding="utf-8")
                error = io.StringIO()
                with contextlib.redirect_stderr(error):
                    code = cli.main(["render", str(source), "--output-dir", str(output)])
                self.assertNotEqual(code, 0)
                self.assertFalse(output.exists())
                self.assertIn("input.", error.getvalue())


if __name__ == "__main__":
    unittest.main()
