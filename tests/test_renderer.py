"""Modified for STE-Pro-Max from ATV-PaperBoard's renderer regression contracts.

Copyright (c) 2026 All-The-Vibes / atv-paperboard contributors.
SPDX-License-Identifier: Apache-2.0
Source: atv-paperboard commit 4b068bcab8e4dc105f0ef975ee224564f5d63383,
tests/test_core_render.py, test_md_converter.py, test_core_gallery.py,
and test_cli_schema.py. Unittest adaptation and security coverage added.
"""
from html.parser import HTMLParser
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from ste_promax.render import _default_body_html, _md_to_html, _rows_to_table
from ste_promax.render import _SECTION_EMITTERS, _slugify
from ste_promax.section_schema import SECTION_SCHEMA, list_kinds
from ste_promax.render import _DEFAULT_DESIGN, _design_tokens, render_artifact
from ste_promax.gallery import regenerate_gallery
from ste_promax import render as renderer


class OrdinaryRenderingTests(unittest.TestCase):
    """Pinned ordinary behavior, run against the copied code before adaptation."""

    def test_markdown_heading_levels(self):
        rendered = _md_to_html("\n".join(f"{'#' * n} Level {n}" for n in range(1, 7)))
        for n in range(1, 7):
            self.assertIn(f"<h{n}>Level {n}</h{n}>", rendered)
        self.assertIn("<h6>Level six</h6>", _md_to_html("###### Level six ######"))

    def test_markdown_entities_and_code_spans(self):
        rendered = _md_to_html("**Bold &mdash;** A & B `&mdash;` &#8212; &#x2014;")
        for expected in ("<strong>Bold &mdash;</strong>", "A &amp; B",
                         "<code>&amp;mdash;</code>", "&#8212;", "&#x2014;"):
            self.assertIn(expected, rendered)

    def test_markdown_ordinary_link_and_inline_escape(self):
        rendered = _md_to_html("[link &mdash; arrow](https://example.com).\n"
                               "Prose with <script>alert(1)</script>.")
        self.assertIn('<a href="https://example.com">link &mdash; arrow</a>', rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn("<script>", rendered)

    def test_markdown_blocks(self):
        rendered = _md_to_html("# Report\n\n- One\n- Two\n\n1. First\n\n"
                               "> [!NOTE]\n> Remember\n\n---\n\n"
                               "```python\nprint('<safe>')\n```\n\n"
                               "| Name | Status |\n| --- | --- |\n| Build | PASS |")
        for expected in ('<div class="prose">', "<h1>Report</h1>", "<ul>", "<ol>",
                         'class="callout callout-note"', "<hr />",
                         'data-lang="python"', "&lt;safe&gt;",
                         '<table class="md">', "<td>PASS</td>"):
            self.assertIn(expected, rendered)

    def test_rows_preserve_first_row_column_order_and_escape(self):
        self.assertEqual(
            _rows_to_table([{"B": "<value>", "A": "x"}, {"A": "&"}]),
            "<table><thead><tr><th>B</th><th>A</th></tr></thead>"
            "<tbody><tr><td>&lt;value&gt;</td><td>x</td></tr>"
            "<tr><td></td><td>&amp;</td></tr></tbody></table>",
        )

    def test_body_precedence_and_no_duplicate_markdown_title(self):
        self.assertEqual(_default_body_html({"title": "Title", "subtitle": "Sub",
                                            "body_html": "<p>trusted</p>"}),
                         "<h1>Title</h1>\n<h2>Sub</h2>\n<p>trusted</p>")
        self.assertEqual(_default_body_html({"title": "Title", "body_md": "# Title"}),
                         '<div class="prose">\n<h1>Title</h1>\n</div>')
        self.assertEqual(_default_body_html({"sections": [{"kind": "subhead", "text": "Section"}],
                                            "body_md": "ignored"}),
                         '<div class="subhead">Section</div>')

    def test_slug_is_safe_and_has_fallback(self):
        self.assertEqual(_slugify("Hello World! This is a Test 123"), "hello-world-this-is-a-test-123")
        self.assertEqual(_slugify("!!!"), "artifact")

    def test_schema_matches_all_fifteen_emitters_and_examples_render(self):
        self.assertEqual(set(list_kinds()), set(_SECTION_EMITTERS))
        self.assertEqual(len(_SECTION_EMITTERS), 15)
        for kind, entry in SECTION_SCHEMA.items():
            with self.subTest(kind=kind):
                rendered = _SECTION_EMITTERS[kind](entry["example"])
                self.assertIsInstance(rendered, str)
                self.assertTrue(rendered)

    def test_section_structure(self):
        rendered = _default_body_html({"sections": [
            {"kind": "hero", "title": "Report", "sub": "Status"},
            {"kind": "sec", "title": "Checks", "body": [
                {"kind": "status-table", "rows": [{"check": "build", "status": "PASS"}]},
                {"kind": "code-shell", "code": "<tag>", "lang": "html"},
            ]},
        ]})
        for expected in ('class="hero"', "<h1>Report</h1>", '<section class="sec">',
                         'class="badge pass"', "&lt;tag&gt;", 'class="code-shell"'):
            self.assertIn(expected, rendered)


class Tags(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class NativeArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ste-renderer-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "output"

    def render(self, data=None, **kwargs):
        return render_artifact(data or {"title": "Test Artifact", "body_md": "# Report"},
                               output_dir=self.output, **kwargs)

    def test_real_triple_and_honest_lint_metadata(self):
        triple = self.render({"title": "Test Artifact", "body_html": "<p>Hello from the test suite.</p>"})
        self.assertEqual(set(triple), {"html_path", "design_path", "meta_path", "slug"})
        for key in ("html_path", "design_path", "meta_path"):
            self.assertTrue(triple[key].is_file())
        html = triple["html_path"].read_text(encoding="utf-8")
        self.assertTrue(html.lower().startswith("<!doctype html>"))
        self.assertIn("<p>Hello from the test suite.</p>", html)
        self.assertIn(f'href="{triple["slug"]}.DESIGN.md"', html)
        self.assertEqual(triple["design_path"].read_bytes(), _DEFAULT_DESIGN.read_bytes())
        meta = yaml.safe_load(triple["meta_path"].read_text(encoding="utf-8"))
        self.assertEqual(meta["title"], "Test Artifact")
        self.assertEqual(meta["tier"], "atv")
        self.assertIs(meta["lint_passed"], True)
        self.assertEqual(meta["lint_engine"], "ste-promax.local-design-v1")
        self.assertIn("no Node lint or STE/semantic compliance", meta["lint_scope"])
        self.assertNotIn("harness", meta)

    def test_default_and_gallery_have_no_remote_runtime_dependencies(self):
        triple = self.render()
        gallery = regenerate_gallery(self.output)
        for path in (triple["html_path"], gallery):
            html = path.read_text(encoding="utf-8")
            self.assertNotIn("fonts.googleapis", html)
            self.assertNotIn("fonts.gstatic", html)
            self.assertNotIn("@import", html)
            self.assertNotIn("url(", html)
            for tag, attrs in Tags(html).tags:
                self.assertNotIn(tag, ("script", "iframe", "object"))
                if tag == "link":
                    self.assertFalse(attrs.get("href", "").startswith(("http:", "https:", "//")))

    def test_metadata_is_escaped_but_body_html_is_explicitly_trusted(self):
        payload = '"><img src=x onerror=alert(1)>'
        triple = self.render(dict.fromkeys(("title", "brand", "breadcrumb", "status_tag"), payload) |
                             {"body_html": '<strong id="trusted">trusted body</strong>'})
        html = triple["html_path"].read_text(encoding="utf-8")
        self.assertIn("&lt;img", html)
        self.assertNotIn("<img", html)
        self.assertIn('<strong id="trusted">trusted body</strong>', html)

    def test_custom_design_injects_safe_tokens_and_preserves_exact_sidecar(self):
        design = self.root / "custom.DESIGN.md"
        source = ('---\r\nname: custom\r\ncolors:\r\n  primary: "#ABCDEF"\r\n'
                  'typography:\r\n  body:\r\n    fontFamily: "Segoe UI, sans-serif"\r\n'
                  '    fontSize: 18px\r\n---\r\n# Preserve this prose.\r\n')
        design.write_bytes(source.encode("utf-8"))
        triple = self.render(design_path=design)
        self.assertEqual(triple["design_path"].read_bytes(), design.read_bytes())
        html = triple["html_path"].read_text(encoding="utf-8")
        self.assertIn("--color-primary: #ABCDEF;", html)
        self.assertIn("--font-family-body: Segoe UI, sans-serif;", html)
        self.assertIn("--font-size-body: 18px;", html)

    def test_invalid_designs_fail_without_emitting_artifacts(self):
        invalid = [
            "no frontmatter",
            "---\n[not, a, mapping]\n---",
            "---\ncolors: []\n---",
            "---\ncolors: {primary: red}\n---",
            "---\ncolors: {primary: '#123456; background:url(https://bad)'}\n---",
            "---\ncolors: {primary: '#123456'}\nunknown: true\n---",
            "---\ncolors: {primary: '#123456'}\ntypography: {body: {fontFamily: 'x; color:red'}}\n---",
            "---\ncolors: {primary: '#123456'}\ntypography: {body: {fontSize: 'url(x)'}}\n---",
            "---\ncolors: {primary: '#123456'}\ntypography: {body: {lineHeight: .nan}}\n---",
            "---\ncolors: {primary: '#123456'}\nspacing: {md: '-10px'}\n---",
            "---\ncolors: {primary: '#123456'}\ntypography: {body: {unknown: 1}}\n---",
        ]
        for text in invalid:
            with self.subTest(text=text):
                design = self.root / "bad.DESIGN.md"
                design.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.render(design_path=design)
                self.assertFalse(self.output.exists())

    def test_missing_design_propagates(self):
        with self.assertRaises(FileNotFoundError):
            self.render(design_path=self.root / "missing.DESIGN.md")
        self.assertFalse(self.output.exists())

    def test_all_triple_suffixes_prevent_overwrite(self):
        self.output.mkdir()
        originals = {}
        for base, suffix in zip(("test-artifact", "test-artifact-1", "test-artifact-2"),
                                (".html", ".DESIGN.md", ".meta.yaml")):
            path = self.output / (base + suffix)
            path.write_bytes(b"Preserve user artifact")
            originals[path] = path.read_bytes()
        triple = self.render()
        self.assertEqual(triple["slug"], "test-artifact-3")
        for path, content in originals.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(self.render()["slug"], "test-artifact-4")

    def test_exclusive_creation_preserves_a_racing_sidecar_and_rolls_back(self):
        original_open = Path.open

        def competing_writer(path, mode="r", *args, **kwargs):
            if mode == "x" and path.name.endswith(".DESIGN.md"):
                with original_open(path, "w", encoding="utf-8") as stream:
                    stream.write("other writer")
            return original_open(path, mode, *args, **kwargs)

        with patch.object(Path, "open", competing_writer):
            with self.assertRaises(FileExistsError):
                self.render()
        self.assertEqual((self.output / "test-artifact.DESIGN.md").read_text(), "other writer")
        self.assertFalse((self.output / "test-artifact.html").exists())
        self.assertFalse((self.output / "test-artifact.meta.yaml").exists())

    def test_reserved_and_long_titles_are_safe(self):
        for title in ("CON", "aux", "NUL", "COM1", "LPT9", "gallery", "A" * 500):
            with self.subTest(title=title):
                triple = self.render({"title": title})
                self.assertLess(len(triple["slug"]), 120)
                self.assertNotEqual(triple["html_path"].name.lower(), "gallery.html")
                self.assertTrue(triple["html_path"].is_file())

    def test_gallery_scans_only_direct_files_and_escapes_metadata(self):
        first = self.render({"title": "Alpha"})
        second = self.render({"title": "Beta"})
        nested = self.output / "nested"
        render_artifact({"title": "Hidden Nested"}, output_dir=nested)
        meta = yaml.safe_load(first["meta_path"].read_text(encoding="utf-8"))
        meta.update(title='<img src=x onerror="bad">', slug="../../outside",
                    design='"><script>bad</script>', generator="<b>unknown</b>")
        first["meta_path"].write_text(yaml.safe_dump(meta), encoding="utf-8")
        second["html_path"].unlink()
        (self.output / "invalid.meta.yaml").write_text("[invalid", encoding="utf-8")
        html = regenerate_gallery(self.output).read_text(encoding="utf-8")
        self.assertNotIn("<img", html)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;img", html)
        self.assertNotIn("Hidden Nested", html)
        self.assertIn('href="alpha.html"', html)
        self.assertNotIn('href="../../outside', html)
        self.assertNotIn('href="beta.html"', html)
        self.assertIn("HTML · NOT FOUND", html)
        self.assertFalse((self.output / "gallery.DESIGN.md").exists())

    def test_gallery_regenerates_only_its_owned_index(self):
        self.render({"title": "Alpha"})
        gallery = regenerate_gallery(self.output)
        self.render({"title": "Beta"})
        self.assertEqual(regenerate_gallery(self.output), gallery)
        html = gallery.read_text(encoding="utf-8")
        self.assertIn("Alpha", html)
        self.assertIn("Beta", html)
        gallery.write_bytes(b"user-owned index")
        with self.assertRaises(FileExistsError):
            regenerate_gallery(self.output)
        self.assertEqual(gallery.read_bytes(), b"user-owned index")

    def test_empty_gallery(self):
        html = regenerate_gallery(self.output).read_text(encoding="utf-8")
        self.assertIn("No artifacts found", html)

    def test_local_design_validation_does_not_claim_visual_compliance(self):
        text = _DEFAULT_DESIGN.read_text(encoding="utf-8")
        tokens = _design_tokens(text)
        self.assertIn("--color-primary", tokens)
        self.assertIn("--font-family-body", tokens)
        self.assertIn("--rounded-md", tokens)
        self.assertIn("--spacing-md", tokens)


class InputValidationTests(unittest.TestCase):
    warning = "Do not deploy before approval"

    def assert_rejected_before_output(self, data, location):
        with tempfile.TemporaryDirectory(prefix="ste-invalid-input-") as tmp:
            output = Path(tmp) / "not-created"
            with self.assertRaises(ValueError) as raised:
                render_artifact(data, output_dir=output)
            self.assertIn(location, str(raised.exception))
            self.assertFalse(output.exists(), "Invalid input must not create an output directory")

    def test_unknown_kinds_cannot_drop_approval_warning(self):
        for kind in ("warning", "step", "", None, ["steps"]):
            with self.subTest(kind=kind):
                self.assert_rejected_before_output(
                    {"sections": [{"kind": kind, "title": self.warning}]},
                    "input.sections[0].kind",
                )

    def test_invalid_sections_and_nested_children_have_precise_locations(self):
        cases = [
            ({"sections": "warning"}, "input.sections"),
            ({"sections": {}}, "input.sections"),
            ({"sections": None}, "input.sections"),
            ({"sections": [self.warning]}, "input.sections[0]"),
            ({"sections": [{"title": self.warning}]}, "input.sections[0].kind"),
            ({"sections": [{"kind": "sec", "body": self.warning}]}, "input.sections[0].body"),
            ({"sections": [{"kind": "sec", "body": [None]}]}, "input.sections[0].body[0]"),
            ({"sections": [{"kind": "sec", "body": [{"kind": "sec", "body": [
                {"kind": "warning", "title": self.warning}
            ]}]}]}, "input.sections[0].body[0].body[0].kind"),
        ]
        for data, location in cases:
            with self.subTest(location=location, data=data):
                self.assert_rejected_before_output(data, location)

    def test_step_rows_and_fields_must_match_the_supported_shape(self):
        for rows, suffix in [
            (self.warning, ".rows"),
            ({"desc": self.warning}, ".rows"),
            (None, ".rows"),
            ([self.warning], ".rows[0]"),
            ([None], ".rows[0]"),
            ([[]], ".rows[0]"),
            ([{"desc": [self.warning]}], ".rows[0].desc"),
            ([{"title": {"warning": self.warning}}], ".rows[0].title"),
            ([{"num": True, "desc": self.warning}], ".rows[0].num"),
            ([{"body": self.warning}], ".rows[0].body"),
        ]:
            with self.subTest(rows=rows):
                self.assert_rejected_before_output(
                    {"sections": [{"kind": "sec", "body": [{"kind": "steps", "rows": rows}]}]},
                    "input.sections[0].body[0]" + suffix,
                )

    def test_all_structured_section_collections_are_checked(self):
        cases = [
            ("hero", "meta", [self.warning], ".meta[0]"),
            ("stack-list", "rows", [self.warning], ".rows[0]"),
            ("dep-list", "rows", [self.warning], ".rows[0]"),
            ("q-list", "rows", [self.warning], ".rows[0]"),
            ("props-table", "rows", [self.warning], ".rows[0]"),
            ("status-table", "rows", [self.warning], ".rows[0]"),
            ("color-strip", "colors", [self.warning], ".colors[0]"),
            ("fit-row", "items", [{"unknown": self.warning}], ".items[0].unknown"),
            ("checklist", "items", self.warning, ".items"),
            ("anti", "items", [{"title": self.warning}], ".items[0]"),
            ("callout", "items", [None], ".items[0]"),
            ("props-table", "headers", "Prop", ".headers"),
            ("hero", "unknown", self.warning, ".unknown"),
            ("sec", "zebra", "false", ".zebra"),
        ]
        for kind, field, value, suffix in cases:
            with self.subTest(kind=kind, field=field):
                self.assert_rejected_before_output(
                    {"sections": [{"kind": kind, field: value}]},
                    "input.sections[0]" + suffix,
                )

    def test_top_level_input_types_and_table_rows_are_checked(self):
        cases = [
            ([], "input"),
            ({"body_md": ["warning"]}, "input.body_md"),
            ({"body_html": {"warning": self.warning}}, "input.body_html"),
            ({"rows": self.warning}, "input.rows"),
            ({"rows": [{"check": "build"}, self.warning]}, "input.rows[1]"),
            ({"rows": [{"check": "build"}, {"check": "deploy", "warning": self.warning}]},
             "input.rows[1].warning"),
        ]
        for data, location in cases:
            with self.subTest(data=data):
                self.assert_rejected_before_output(data, location)

    def test_later_table_safety_qualification_is_rejected_not_discarded(self):
        rows = [
            {"Action": "Build", "Status": "Ready"},
            {"Status": "Ready", "Action": "Deploy", "Qualification": self.warning},
        ]
        location = "input.rows[1].Qualification"
        self.assert_rejected_before_output({"rows": rows}, location)
        for operation in (lambda: renderer.validate_input({"rows": rows}),
                          lambda: _rows_to_table(rows)):
            with self.assertRaises(ValueError) as raised:
                operation()
            self.assertIn(location, str(raised.exception))
            self.assertIn("unsupported field", str(raised.exception))

    def test_table_reordered_and_missing_cells_preserve_first_row_order(self):
        rows = [
            {"Action": "Build", "Status": "Ready"},
            {"Status": "Blocked", "Action": "Deploy"},
            {"Action": "Wait for approval"},
        ]
        self.assertIsNone(renderer.validate_input({"rows": rows}))
        html = _rows_to_table(rows)
        self.assertIn("<th>Action</th><th>Status</th>", html)
        self.assertIn("<tr><td>Deploy</td><td>Blocked</td></tr>", html)
        self.assertIn("<tr><td>Wait for approval</td><td></td></tr>", html)

    def test_public_preflight_is_pure_and_renderer_runs_it_before_io(self):
        data = {"sections": [{"kind": "steps", "rows": [self.warning]}]}
        with patch.object(Path, "mkdir", side_effect=AssertionError("No directory creation")), \
                patch.object(Path, "read_bytes", side_effect=AssertionError("No file reads")):
            self.assertIsNone(renderer.validate_input({
                "sections": [{"kind": "steps", "rows": [{"desc": self.warning}]}],
            }))
            for operation in (lambda: renderer.validate_input(data),
                              lambda: render_artifact(data)):
                with self.assertRaises(ValueError) as raised:
                    operation()
                self.assertIn("input.sections[0].rows[0]", str(raised.exception))

    def test_warning_after_valid_sections_and_rows_is_not_partially_rendered(self):
        self.assert_rejected_before_output({"sections": [
            {"kind": "hero", "title": "Release"},
            {"kind": "sec", "body": [{"kind": "steps", "rows": [
                {"title": "Check build", "desc": "Build passed."},
                self.warning,
            ]}]},
        ]}, "input.sections[1].body[0].rows[1]")

    def test_cyclic_native_sections_are_rejected_with_a_location(self):
        section = {"kind": "sec", "body": []}
        section["body"].append(section)
        self.assert_rejected_before_output(
            {"sections": [section]}, "input.sections[0].body[0]",
        )

    def test_supported_examples_and_nested_warning_remain_renderable_without_mutation(self):
        sections = [deepcopy(entry["example"]) for entry in SECTION_SCHEMA.values()]
        sections.append({"kind": "sec", "body": [{"kind": "sec", "body": [
            {"kind": "steps", "rows": [{"num": 1, "title": "Approval", "desc": self.warning}]}
        ]}]})
        data = {"title": "Validated report", "sections": sections}
        original = deepcopy(data)
        self.assertIsNone(renderer.validate_input(data))
        with tempfile.TemporaryDirectory(prefix="ste-valid-input-") as tmp:
            triple = render_artifact(data, output_dir=Path(tmp))
            html = triple["html_path"].read_text(encoding="utf-8")
            self.assertIn(self.warning, html)
            self.assertIn('class="step-row"', html)
            self.assertIn('class="badge pass"', html)
        self.assertEqual(data, original)

    def test_in_memory_body_conversion_cannot_silently_drop_sections(self):
        with self.assertRaises(ValueError) as raised:
            _default_body_html({"sections": [{"kind": "warning", "title": self.warning}]})
        self.assertIn("input.sections[0].kind", str(raised.exception))


class EscapingTests(unittest.TestCase):
    def test_markdown_html_and_comments_are_not_executable(self):
        html = _md_to_html('<script>alert(1)</script>\n<!--\n--><img src=x onerror=alert(1)>')
        self.assertNotIn("<script", html)
        self.assertNotIn("<img", html)
        self.assertNotIn("<!--", html)
        self.assertIn("&lt;script&gt;", html)

    def test_markdown_links_reject_unsafe_schemes_including_entities(self):
        for url in ("javascript:alert", "jav&#x61;script:alert", "javascript&#58;alert",
                    "data:text/html,bad", "file:///secret", "vbscript:bad", "//bad/path"):
            with self.subTest(url=url):
                html = _md_to_html(f"[click]({url})")
                self.assertFalse(any(tag == "a" for tag, _ in Tags(html).tags))

    def test_markdown_only_local_images_and_no_nested_links(self):
        html = _md_to_html("![remote](https://bad/image.png) ![local](images/photo.png)\n"
                           "[https://example.com](https://example.com)")
        tags = Tags(html).tags
        self.assertEqual([attrs["src"] for tag, attrs in tags if tag == "img"], ["images/photo.png"])
        self.assertEqual(sum(tag == "a" for tag, _ in tags), 1)

    def test_section_text_is_escaped_for_every_previously_raw_field(self):
        attack = '"><img src=x onerror=alert(1)>'
        sections = [
            {"kind": "stack-list", "rows": [{"why": attack, "fix": attack}]},
            {"kind": "dep-list", "rows": [{"why": attack}]},
            {"kind": "q-list", "rows": [{"body": attack}]},
            {"kind": "steps", "rows": [{"desc": attack}]},
            {"kind": "anti", "items": [attack]},
            {"kind": "checklist", "items": [attack]},
            {"kind": "callout", "items": [attack], "body": attack},
            {"kind": "props-table", "rows": [{"notes": attack}]},
            {"kind": "status-table", "rows": [{"status": attack}]},
        ]
        for section in sections:
            with self.subTest(kind=section["kind"]):
                html = _default_body_html({"sections": [section]})
                self.assertNotIn("<img", html)
                for _, attrs in Tags(html).tags:
                    self.assertFalse(any(key.startswith("on") for key in attrs))

    def test_swatch_css_injection_is_rejected(self):
        with self.assertRaises(ValueError):
            _default_body_html({"sections": [{"kind": "color-strip", "colors": [
                {"hex": "#fff; background:url(https://bad)"}]}]})

    def test_markdown_placeholder_content_cannot_spoof_internal_tokens(self):
        html = _md_to_html("\x00CODE9999\x00 \x00LINK99\x00 `safe`")
        self.assertIn("<code>safe</code>", html)


if __name__ == "__main__":
    unittest.main()
