"""STE-Pro-Max renderer regression contracts.

Copyright (c) 2026 Shyam Sridhar and contributors.
SPDX-License-Identifier: Apache-2.0
Source commit: 4b068bcab8e4dc105f0ef975ee224564f5d63383,
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

    def test_schema_matches_all_seventeen_emitters_and_examples_render(self):
        self.assertEqual(set(list_kinds()), set(_SECTION_EMITTERS))
        self.assertEqual(len(_SECTION_EMITTERS), 17)
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
        self.assertEqual(meta["generator"], "ste-promax/native")
        self.assertEqual(meta["tier"], "ste")
        self.assertIs(meta["lint_passed"], True)
        self.assertEqual(meta["lint_engine"], "ste-promax.local-design-v1")
        self.assertIn("no Node lint or STE/semantic compliance", meta["lint_scope"])
        self.assertNotIn("harness", meta)

    def test_native_resources_and_real_outputs_use_ste_identity_and_license(self):
        self.assertEqual(_DEFAULT_DESIGN.name, "ste.DESIGN.md")
        self.assertTrue((renderer._TEMPLATES_DIR / "document.html.j2").is_file())
        design = _DEFAULT_DESIGN.read_text(encoding="utf-8")
        self.assertEqual(yaml.safe_load(design.split("---", 2)[1])["name"], "ste")
        triple = self.render()
        gallery = regenerate_gallery(self.output)
        for path in (triple["html_path"], triple["design_path"], gallery):
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIn("Copyright (c) 2026 Shyam Sridhar and contributors.", text)
                self.assertIn("SPDX-License-Identifier: Apache-2.0", text)
                if path.suffix == ".html":
                    self.assertIn(("html", {"lang": "en", "data-theme": "ste"}), Tags(text).tags)
                    self.assertIn("Generated by <strong>STE-Pro-Max</strong>.", text)
        gallery_html = gallery.read_text(encoding="utf-8")
        self.assertIn("ste-promax/native", gallery_html)
        self.assertIn('<span class="tier-badge">ste</span>', gallery_html)
        self.assertIn(f'href="{triple["html_path"].name}"', gallery_html)

    def test_schema_examples_describe_the_native_ste_tier(self):
        hero_meta = SECTION_SCHEMA["hero"]["example"]["meta"]
        self.assertIn({"label": "Tier", "value": "ste"}, hero_meta)
        rows = SECTION_SCHEMA["props-table"]["example"]["rows"]
        self.assertEqual(next(row["default"] for row in rows if row["name"] == "tier"), "ste")
        self.assertIn("Default is ste.", _default_body_html({
            "sections": [SECTION_SCHEMA["q-list"]["example"]],
        }))

    def test_gallery_defaults_missing_tier_to_ste_without_mutating_metadata(self):
        triple = self.render()
        meta_path = triple["meta_path"]
        meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
        del meta["tier"]
        meta_path.write_text(yaml.safe_dump(meta), encoding="utf-8")
        original = meta_path.read_bytes()
        html = regenerate_gallery(self.output).read_text(encoding="utf-8")
        self.assertIn('<span class="tier-badge">ste</span>', html)
        self.assertEqual(meta_path.read_bytes(), original)

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
        self.assertEqual(set(SECTION_SCHEMA), set(renderer._SECTION_EMITTERS))
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


class MarkdownRoundTripTests(unittest.TestCase):
    class Parsed(HTMLParser):
        def __init__(self, markup):
            super().__init__(convert_charrefs=True)
            self.tags, self.text = [], []
            self.rows: list[list[str]] = []
            self.row: list[str] | None = None
            self.cell: str | None = None
            self.feed(markup)

        def handle_starttag(self, tag, attrs):
            self.tags.append((tag, dict(attrs)))
            if tag == "tr":
                self.row = []
            if tag in ("th", "td"):
                self.cell = ""

        def handle_data(self, data):
            self.text.append(data)
            if self.cell is not None:
                self.cell += data

        def handle_endtag(self, tag):
            if tag in ("th", "td"):
                assert self.row is not None
                assert self.cell is not None
                self.row.append(self.cell)
                self.cell = None
            if tag == "tr":
                assert self.row is not None
                self.rows.append(self.row)
                self.row = None

    def story_markdown(self):
        from ste_promax.stories import STORY_SCHEMA, story_companions
        source = (
            r'Literal [link](https://example.org/a?x=1&y=2) ![image](images/photo.png) '
            r'**stars** _underscores_ `&mdash;` api_name \ | \| & &lt; &amp; '
            r'<img src=x onerror="bad"> {value} #tag#'
        )
        story = deepcopy(STORY_SCHEMA["example"])
        story["title"] = r"Title [literal] **stars** `code` & <tag> #"
        story["summary"] = source
        story["claims"][0]["uncertainty"] = source
        story["beats"][0]["visual"] = deepcopy(SECTION_SCHEMA["chart"]["example"])
        story["beats"][0]["visual"]["categories"][0] = r"Category [literal] | **stars** `tick` & <tag>"
        before = deepcopy(story)
        prose = story_companions(story)["story.md"]
        self.assertEqual(story, before)
        return story, source, prose

    def test_actual_story_markdown_preserves_literal_text_and_structure(self):
        story, source, prose = self.story_markdown()
        markup = _md_to_html(prose)
        parsed = self.Parsed(markup)
        text = "".join(parsed.text)
        self.assertEqual(text.count(source), 3)  # summary, narrative claim, complete ledger
        self.assertIn(story["title"], text)
        self.assertIn(story["beats"][0]["visual"]["categories"][0], text)
        self.assertFalse({"a", "img", "em", "strong", "code", "script", "table"} &
                         {tag for tag, _ in parsed.tags})
        self.assertFalse(any(key.startswith("on") for _, attrs in parsed.tags for key in attrs))
        self.assertEqual(_default_body_html({"body_md": prose}), markup)

    def test_saved_story_markdown_round_trip_through_root_cli(self):
        import json
        import subprocess
        import sys

        story, source, prose = self.story_markdown()
        with tempfile.TemporaryDirectory(prefix="ste-story-roundtrip-") as temp:
            root = Path(__file__).resolve().parents[1]
            source_path = Path(temp) / "story.md"
            source_path.write_text(prose, encoding="utf-8")
            original = source_path.read_bytes()
            result = subprocess.run(
                [sys.executable, "-X", "utf8", str(root), "render", str(source_path),
                 "--output-dir", str(Path(temp) / "rendered")],
                cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(result.stdout)
            self.assertEqual(manifest["status"], "complete")
            output = Path(manifest["files"]["html"]["path"])
            parsed = self.Parsed(output.read_text(encoding="utf-8"))
            text = "".join(parsed.text)
            self.assertEqual(text.count(source), 3)
            self.assertIn(story["title"], text)
            self.assertNotIn("img", [tag for tag, _ in parsed.tags])
            self.assertTrue(output.with_suffix(".DESIGN.md").is_file())
            self.assertTrue(output.with_suffix(".meta.yaml").is_file())
            self.assertTrue((output.parent / "gallery.html").is_file())
            self.assertEqual(source_path.read_bytes(), original)

    def test_escaped_literals_do_not_disable_intentional_formatting(self):
        parsed = self.Parsed(_md_to_html(
            r"\*literal\* **real** \_literal\_ _real_ \`literal\` `raw \* &amp;` "
            r"\[literal\](https://example.org) [real](https://example.org) \q"
        ))
        self.assertEqual("".join(parsed.text).strip(),
                         "*literal* real _literal_ real `literal` raw \\* &amp; "
                         "[literal](https://example.org) real \\q")
        tags = [tag for tag, _ in parsed.tags]
        for tag in ("strong", "em", "code", "a"):
            self.assertEqual(tags.count(tag), 1)

    def test_story_raw_html_like_text_does_not_autolink_its_attribute_values(self):
        from ste_promax.stories import STORY_SCHEMA, story_companions
        story = deepcopy(STORY_SCHEMA["example"])
        source = '<a href="https://example.org/?a=1&b=2"><img src="images/a.png">**literal**</a>'
        story["summary"] = source
        parsed = self.Parsed(_md_to_html(story_companions(story)["story.md"]))
        self.assertIn(source, "".join(parsed.text))
        self.assertFalse({"a", "img", "strong", "script"} & {tag for tag, _ in parsed.tags})

    def test_literal_tags_inside_intentional_links_and_image_alt_do_not_leak_tokens(self):
        parsed = self.Parsed(_md_to_html(
            '[<label> `code`](https://example.org) ![<alt>](images/local.png)'
        ))
        self.assertIn("<label> code", "".join(parsed.text))
        self.assertEqual(sum(tag == "a" for tag, _ in parsed.tags), 1)
        self.assertEqual(sum(tag == "code" for tag, _ in parsed.tags), 1)
        images = [attrs for tag, attrs in parsed.tags if tag == "img"]
        self.assertEqual(images, [{"alt": "<alt>", "src": "images/local.png", "loading": "lazy"}])
        self.assertNotIn("\x00", "".join(parsed.text))
        self.assertFalse({"label", "alt"} & {tag for tag, _ in parsed.tags})

    def test_even_and_odd_backslashes_before_delimiters(self):
        for count in range(1, 5):
            with self.subTest(count=count):
                slashes = "\\" * count
                parsed = self.Parsed(_md_to_html(slashes + "*word" + slashes + "*"))
                visible_slashes = "\\" * (count // 2)
                expected = (visible_slashes + "*word" + visible_slashes + "*" if count % 2
                            else visible_slashes + "word" + visible_slashes)
                self.assertEqual("".join(parsed.text).strip(), expected)
                self.assertEqual(sum(tag == "em" for tag, _ in parsed.tags), 0 if count % 2 else 1)

    def test_escaped_code_delimiters_keep_prose_entities_but_real_code_stays_literal(self):
        parsed = self.Parsed(_md_to_html(r"\`&mdash;\` `&mdash; \* \[x\]` \&amp;"))
        self.assertEqual("".join(parsed.text).strip(), "`—` &mdash; \\* \\[x\\] &amp;")
        self.assertEqual(sum(tag == "code" for tag, _ in parsed.tags), 1)

    def test_escaped_markers_at_block_boundaries_remain_text(self):
        parsed = self.Parsed(_md_to_html(
            "# Heading \\#\n\n\\# Not a heading\n\n\\* not a list\n\n"
            "\\*\\*\\*\n\n\\`\\`\\`not a fence\\`\\`\\`"
        ))
        text = "".join(parsed.text)
        for expected in ("Heading #", "# Not a heading", "* not a list", "***", "```not a fence```"):
            self.assertIn(expected, text)
        tags = [tag for tag, _ in parsed.tags]
        self.assertEqual(tags.count("h1"), 1)
        self.assertFalse({"ul", "hr", "code", "pre", "em", "strong"} & set(tags))

    def test_table_escaped_pipes_and_backslash_parity_preserve_cells(self):
        parsed = self.Parsed(_md_to_html(
            "| Field \\| name | Meaning |\n| --- | --- |\n"
            "| A\\|B | \\[ref\\] \\*literal\\* |\n"
            "| slash\\\\| next |\n"
            "| odd\\\\\\|pipe | tail\\| |"
        ))
        self.assertEqual(parsed.rows, [
            ["Field | name", "Meaning"], ["A|B", "[ref] *literal*"],
            ["slash\\", "next"], ["odd\\|pipe", "tail|"],
        ])
        self.assertFalse({"em", "strong", "a"} & {tag for tag, _ in parsed.tags})

    def test_table_without_outer_borders_keeps_trailing_literal_pipe(self):
        parsed = self.Parsed(_md_to_html("Head | Last\\|\n--- | ---\nvalue | end\\|"))
        self.assertEqual(parsed.rows, [["Head", "Last|"], ["value", "end|"]])

    def test_table_code_span_escaped_pipe_preserves_other_code_and_entities(self):
        parsed = self.Parsed(_md_to_html(
            "| Code | Literal |\n| --- | --- |\n"
            "| `a\\|b \\* &amp;` | \\`not code\\` &amp; |\n"
            "| | |"
        ))
        self.assertEqual(parsed.rows, [
            ["Code", "Literal"], ["a|b \\* &amp;", "`not code` &"], ["", ""],
        ])
        self.assertEqual(sum(tag == "code" for tag, _ in parsed.tags), 1)

    def test_escaped_pipe_alone_is_not_a_table_delimiter(self):
        parsed = self.Parsed(_md_to_html("Only \\| literal\n| --- | --- |"))
        self.assertEqual(parsed.rows, [])
        self.assertIn("Only | literal", "".join(parsed.text))

    def test_escape_processing_cannot_spoof_opaque_placeholders(self):
        source = ("\x00CODE9999\x00 \x00LINK9999\x00 \x00ESC9999\x00 \x00LITERAL9999\x00 "
                  r"\`CODE0\` `safe &amp;` &#0;CODE9999&#0; \[label\](https://example.org)")
        parsed = self.Parsed(_md_to_html(source))
        text = "".join(parsed.text)
        self.assertIn("\ufffdCODE9999\ufffd", text)
        self.assertIn("\ufffdLINK9999\ufffd", text)
        self.assertIn("\ufffdLITERAL9999\ufffd", text)
        self.assertIn("`CODE0`", text)
        self.assertIn("safe &amp;", text)
        self.assertIn("[label](https://example.org)", text)
        self.assertEqual(sum(tag == "code" for tag, _ in parsed.tags), 1)
        self.assertFalse(any(tag == "a" for tag, _ in parsed.tags))


class OrdinaryTableScrollTests(unittest.TestCase):
    def check_region(self, markup, label):
        parsed = MarkdownRoundTripTests.Parsed(markup)
        regions = [(index, attrs) for index, (tag, attrs) in enumerate(parsed.tags)
                   if tag == "div" and attrs.get("class") == "table-scroll"]
        self.assertEqual(len(regions), 1)
        index, attrs = regions[0]
        self.assertEqual(attrs, {"class": "table-scroll", "role": "region",
                                 "tabindex": "0", "aria-label": label})
        self.assertEqual(parsed.tags[index + 1][0], "table")
        self.assertNotIn("role", parsed.tags[index + 1][1])
        self.assertNotIn("tabindex", parsed.tags[index + 1][1])
        self.assertFalse(any(key.startswith("on") for _, attributes in parsed.tags for key in attributes))
        self.assertNotIn("img", [tag for tag, _ in parsed.tags])
        return parsed

    def test_props_table_scroll_region_uses_default_headers_and_keeps_cells(self):
        parsed = self.check_region(_default_body_html({"sections": [{
            "kind": "props-table", "rows": [
                {"name": "a" * 200, "type": "string", "default": "None supplied", "notes": "Do not infer approval."},
            ],
        }]}), "Table: Prop, Type, Default, Notes")
        self.assertEqual(parsed.rows, [
            ["Prop", "Type", "Default", "Notes"],
            ["a" * 200, "string", "None supplied", "Do not infer approval."],
        ])

    def test_props_custom_headers_are_escaped_in_region_name(self):
        header = 'Notes " onfocus="bad"><img src=x> & scope'
        parsed = self.check_region(_default_body_html({"sections": [{
            "kind": "props-table", "headers": [header, "Type", "Default", "Qualification"],
            "rows": [{"name": "Value", "notes": "<not approved>"}],
        }]}), f"Table: {header}, Type, Default, Qualification")
        self.assertEqual(parsed.rows[0][0], header)
        self.assertEqual(parsed.rows[1][-1], "<not approved>")

    def test_status_table_preserves_headers_order_badges_and_qualifications(self):
        header = 'Locator "><img src=x> & reference'
        rows = [
            {header: "a/long/path/" * 30, "status": "PASS", "claim": "Do not deploy."},
            {"claim": "Still requires review.", "status": "Pending", header: "second"},
        ]
        markup = _default_body_html({"sections": [{"kind": "status-table", "rows": rows}]})
        parsed = self.check_region(markup, f"Table: {header}, status, claim")
        self.assertEqual(parsed.rows, [
            [header, "status", "claim"], [rows[0][header], "PASS", "Do not deploy."],
            ["second", "Pending", "Still requires review."],
        ])
        self.assertIn('class="badge pass"', markup)

    def test_top_level_rows_are_wrapped_but_raw_table_helper_is_unchanged(self):
        header = '" onfocus="bad"> & data'
        rows = [{header: "Source value", "Warning": "<not approved>"}, {"Warning": "Missing locator"}]
        raw = _rows_to_table(rows)
        self.assertTrue(raw.startswith("<table>"))
        self.assertNotIn("table-scroll", raw)
        markup = _default_body_html({"rows": rows})
        self.assertIn(raw, markup)
        parsed = self.check_region(markup, f"Table: {header}, Warning")
        self.assertEqual(parsed.rows, [
            [header, "Warning"], ["Source value", "<not approved>"], ["", "Missing locator"],
        ])

    def test_markdown_table_region_uses_visible_unescaped_headers(self):
        markup = _md_to_html(
            '| **Locator** \\| \\[literal\\] | "<img src=x>" &amp; scope |\n'
            '| --- | --- |\n| long/path | Do not deploy. |\n| other | &lt;not approved&gt; |'
        )
        parsed = self.check_region(markup, 'Table: Locator | [literal], "<img src=x>" & scope')
        self.assertEqual(parsed.rows, [
            ["Locator | [literal]", '"<img src=x>" & scope'],
            ["long/path", "Do not deploy."], ["other", "<not approved>"],
        ])

    def test_caption_documentation_has_wrapped_full_evidence_table(self):
        import json
        root = Path(__file__).resolve().parents[1]
        data = json.loads((root / "examples/suite/caption-documentation.json").read_text(encoding="utf-8"))
        markup = _default_body_html(data)
        parsed = MarkdownRoundTripTests.Parsed(markup)
        regions = [attrs for tag, attrs in parsed.tags if attrs.get("class") == "table-scroll"]
        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0]["aria-label"], "Table: source, locator, claims, status")
        status = next(section for section in data["sections"] if section["kind"] == "status-table")
        for row in status["rows"]:
            self.assertIn(list(row.values()), parsed.rows)

    def test_empty_headers_have_a_name_and_empty_status_has_no_empty_region(self):
        parsed = self.check_region(_md_to_html("| | |\n| --- | --- |\n| A | B |"), "Table data")
        self.assertEqual(parsed.rows, [["", ""], ["A", "B"]])
        self.assertEqual(_default_body_html({"sections": [{"kind": "status-table", "rows": []}]}), "")


if __name__ == "__main__":
    unittest.main()
