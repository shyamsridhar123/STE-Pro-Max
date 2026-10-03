"""Public native paths for structured visuals and source-grounded stories."""
import contextlib
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

from ste_promax import cli
from ste_promax.charts import CHART_SCHEMA
from ste_promax.diagrams import DIAGRAM_SCHEMA
from ste_promax.render import _default_body_html, render_artifact, validate_input
from ste_promax.section_schema import SECTION_SCHEMA
from ste_promax.stories import STORY_SCHEMA


class SuiteIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source.json"
        self.output = self.root / "rendered"

    def call(self, args):
        with contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            code = cli.main(args)
        return code, out.getvalue(), err.getvalue()

    def render(self, data, *flags):
        self.source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return self.call(["render", str(self.source), "--output-dir", str(self.output), *flags])

    def test_visual_schemas_register_and_render_nested_without_raw_html(self):
        self.assertIn("diagram", SECTION_SCHEMA)
        self.assertIn("chart", SECTION_SCHEMA)
        document = {"title": "Visual reference", "sections": [
            {"kind": "hero", "title": "Visual reference"},
            {"kind": "sec", "title": "Evidence", "body": [
                deepcopy(DIAGRAM_SCHEMA["example"]), deepcopy(CHART_SCHEMA["example"]),
            ]},
        ]}
        before = deepcopy(document)
        code, output, error = self.render(document)
        self.assertEqual(code, 0, error)
        manifest = json.loads(output)
        html = Path(manifest["files"]["html"]["path"]).read_text(encoding="utf-8")
        self.assertEqual(html.count("<svg"), 2)
        self.assertIn("Review feedback", html)
        self.assertIn("Output (items)", html)
        self.assertNotIn('src="https://', html)
        self.assertFalse(manifest["trusted_html"])
        self.assertEqual(document, before)
        self.assertEqual([item["source"] for item in manifest["visuals"]],
                         ["sections[1].body[0]", "sections[1].body[1]"])
        for item in manifest["visuals"]:
            self.assertTrue((self.output / item["file"]).read_text(encoding="utf-8").startswith("<svg"))

    def test_standalone_visual_schema_examples_use_real_emitters(self):
        for schema in (DIAGRAM_SCHEMA, CHART_SCHEMA):
            data = deepcopy(schema["example"])
            with self.subTest(kind=data["kind"]):
                validate_input(data)
                text = _default_body_html(data)
                self.assertIn("<svg", text)
                self.assertIn(data["title"], text)
                self.assertNotIn("&quot;kind&quot;", text)

    def test_standalone_and_story_svg_exports_match_the_native_visual(self):
        from ste_promax.charts import chart_svg
        from ste_promax.diagrams import diagram_svg
        story = deepcopy(STORY_SCHEMA["example"])
        story["beats"][0]["visual"] = deepcopy(DIAGRAM_SCHEMA["example"])
        code, output, error = self.render(story)
        self.assertEqual(code, 0, error)
        manifest = json.loads(output)
        self.assertEqual(manifest["visuals"][0]["source"], "beats[0].visual")
        self.assertEqual((self.output / "visual-01.svg").read_text(encoding="utf-8"),
                         diagram_svg(story["beats"][0]["visual"]))
        self.output = self.root / "standalone-chart"
        code, output, error = self.render(deepcopy(CHART_SCHEMA["example"]))
        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads(output)["visuals"][0]["source"], "input")
        self.assertEqual((self.output / "visual-01.svg").read_text(encoding="utf-8"),
                         chart_svg(CHART_SCHEMA["example"]))

    def test_nested_invalid_visual_is_rejected_before_any_output(self):
        bad = deepcopy(CHART_SCHEMA["example"])
        bad["series"][0]["values"][0] = True
        data = {"sections": [{"kind": "sec", "body": [bad]}]}
        with self.assertRaisesRegex(ValueError, r"input.sections\[0\].body\[0\].series"):
            render_artifact(data, output_dir=self.output)
        self.assertFalse(self.output.exists())
        diagram = deepcopy(DIAGRAM_SCHEMA["example"])
        diagram["edges"][0]["to"] = "not-a-node"
        with self.assertRaisesRegex(ValueError, "edges"):
            render_artifact(diagram, output_dir=self.output)
        self.assertFalse(self.output.exists())

    def test_story_dispatch_and_all_companions_preserve_input_and_hashes(self):
        story = deepcopy(STORY_SCHEMA["example"])
        story["claims"][0]["scope"] += " <script>not executable</script>"
        before = deepcopy(story)
        code, output, error = self.render(story)
        self.assertEqual(code, 0, error)
        self.assertEqual(story, before)
        manifest = json.loads(output)
        self.assertEqual(manifest["status"], "complete")
        self.assertFalse(manifest["trusted_html"])
        for key, name in (("story", "story.md"), ("storyboard", "storyboard.json"),
                          ("narration", "narration.json"), ("evidence", "evidence.json")):
            self.assertEqual(Path(manifest["files"][key]["path"]).name, name)
        for record in manifest["files"].values():
            self.assertEqual(record["sha256"], hashlib.sha256(Path(record["path"]).read_bytes()).hexdigest())
        self.assertEqual((self.output / "source.json").read_bytes(), self.source.read_bytes())
        self.assertEqual(json.loads((self.output / "input.json").read_bytes()), before)
        ledger = json.loads((self.output / "evidence.json").read_bytes())
        self.assertEqual(ledger["source_story"], before)
        self.assertEqual(ledger["review"]["source_verification"], "not_performed")
        text = Path(manifest["files"]["html"]["path"]).read_text(encoding="utf-8")
        self.assertIn("data-ste-story", text)
        self.assertIn("Complete claim ledger", text)
        self.assertIn("&lt;script&gt;not executable&lt;/script&gt;", text)
        self.assertNotIn("<script>not executable</script>", text)

    def test_invalid_story_cannot_fall_back_to_a_successful_json_page(self):
        story = deepcopy(STORY_SCHEMA["example"])
        story["beats"][0]["claim_ids"] = ["missing"]
        code, _, error = self.render(story)
        self.assertEqual(code, 2)
        self.assertIn("unknown reference", error)
        self.assertFalse(self.output.exists())
        with self.assertRaisesRegex(ValueError, "unknown reference"):
            _default_body_html(story)

    def test_story_rejects_conflicting_render_modes_even_with_html_consent(self):
        story = deepcopy(STORY_SCHEMA["example"])
        story["body_html"] = "<p>Hide the pending approval</p>"
        code, _, error = self.render(story, "--trusted-html")
        self.assertEqual(code, 2)
        self.assertIn("unsupported field", error)
        self.assertFalse(self.output.exists())

    def test_title_override_is_explicit_and_original_source_is_kept(self):
        story = deepcopy(STORY_SCHEMA["example"])
        code, output, error = self.render(story, "--title", "Reviewed display title")
        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads((self.output / "source.json").read_bytes()), story)
        normalized = json.loads((self.output / "input.json").read_bytes())
        self.assertEqual(normalized["title"], "Reviewed display title")
        self.assertEqual(json.loads((self.output / "evidence.json").read_bytes())["source_story"], normalized)
        html = Path(json.loads(output)["files"]["html"]["path"]).read_text(encoding="utf-8")
        self.assertIn("Reviewed display title", html)

    def test_render_cannot_mutate_a_story_companion_and_claim_success(self):
        from ste_promax.render import render_artifact as native
        def tamper(data, design_path, output_dir):
            result = native(data, design_path, output_dir)
            (output_dir / "story.md").write_text("Approval granted.", encoding="utf-8")
            return result
        with patch("ste_promax.render.render_artifact", side_effect=tamper):
            code, output, _ = self.render(deepcopy(STORY_SCHEMA["example"]))
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output)["status"], "failed")
        self.assertTrue(any("changed saved story" in warning for warning in json.loads(output)["warnings"]))

    def test_duplicate_json_fields_fail_before_output(self):
        text = json.dumps(STORY_SCHEMA["example"])
        text = text.replace('"summary":', '"summary": "Unsupported different conclusion", "summary":', 1)
        self.source.write_text(text, encoding="utf-8")
        code, _, error = self.call(["render", str(self.source), "--output-dir", str(self.output)])
        self.assertEqual(code, 2)
        self.assertIn("Duplicate JSON field", error)
        self.assertFalse(self.output.exists())

    def test_json_precision_loss_and_invalid_purpose_are_clean_cli_errors(self):
        for token in ("1e-400", "9007199254740993.0"):
            with self.subTest(token=token):
                text = json.dumps(CHART_SCHEMA["example"]).replace("[12, 18]", "[" + token + ", 18]")
                self.source.write_text(text, encoding="utf-8")
                code, _, error = self.call(["render", str(self.source), "--output-dir", str(self.output)])
                self.assertEqual(code, 2)
                self.assertIn("input.series[0].values[0]", error)
                self.assertFalse(self.output.exists())
        for purpose in ([], {}):
            story = deepcopy(STORY_SCHEMA["example"])
            story["purpose"] = purpose
            code, _, error = self.render(story)
            self.assertEqual(code, 2)
            self.assertIn("story.purpose", error)
            self.assertFalse(self.output.exists())

    def test_schema_discovery_is_read_only_and_examples_are_usable(self):
        for name in ("story", "diagram", "chart", "hero"):
            with self.subTest(kind=name):
                code, output, error = self.call(["schema", name])
                self.assertEqual(code, 0, error)
                entry = json.loads(output)
                self.assertIn("fields", entry)
                self.assertIn("example", entry)
                example = entry["example"]
                validate_input(example if name in ("story", "diagram", "chart") else {"sections": [example]})
        code, output, error = self.call(["schema"])
        self.assertEqual(code, 0, error)
        catalog = json.loads(output)
        self.assertIn("story", catalog)
        self.assertEqual(set(catalog["sections"]), set(SECTION_SCHEMA))
        self.assertFalse(self.output.exists())

    def test_narrate_cli_preserves_provided_pcm_and_does_not_export(self):
        story = deepcopy(STORY_SCHEMA["example"])
        self.source.write_text(json.dumps(story), encoding="utf-8")
        audio = self.root / "audio"
        audio.mkdir()
        for beat in story["beats"]:
            with wave.open(str(audio / (beat["id"] + ".wav")), "wb") as out:
                out.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
                out.writeframes(b"\x01\x00\xff\x7f" * 1600)
        with patch("ste_promax.media.synthesize", side_effect=AssertionError("No TTS with provided audio")):
            code, output, error = self.call(["narrate", str(self.source), "--output-dir", str(self.output),
                                            "--audio-dir", str(audio)])
        self.assertEqual(code, 0, error)
        result = json.loads(output)
        self.assertEqual(result["status"], "prepared_not_rendered")
        self.assertEqual(result["narration"], "provided PCM")
        self.assertEqual(result["video_directory"], "video")
        self.assertTrue((self.output / result["composition"]).is_file())
        self.assertFalse(list(self.output.glob("*.mp4")))
        self.assertEqual((self.output / "source.json").read_bytes(), self.source.read_bytes())
        for record in result["audio"]:
            self.assertEqual((self.output / record["file"]).read_bytes(),
                             (audio / (record["id"] + ".wav")).read_bytes())

    def test_narrate_cli_failure_is_not_success_and_preserves_partial_evidence(self):
        self.source.write_text(json.dumps(STORY_SCHEMA["example"]), encoding="utf-8")
        with patch("ste_promax.media.synthesize", side_effect=RuntimeError("Fictional unavailable voice")):
            code, _, error = self.call(["narrate", str(self.source), "--output-dir", str(self.output)])
        self.assertEqual(code, 2)
        self.assertIn("unavailable voice", error)
        result = json.loads((self.output / "manifest.json").read_bytes())
        self.assertEqual(result["status"], "partial_failure_not_rendered")
        self.assertEqual(result["audio"], [])

    def test_unknown_schema_and_invalid_narration_do_not_write(self):
        code, _, error = self.call(["schema", "unknown"])
        self.assertEqual(code, 2)
        self.assertIn("Unknown schema", error)
        self.source.write_text('{"kind":"story","version":99}', encoding="utf-8")
        code, _, error = self.call(["narrate", str(self.source), "--output-dir", str(self.output)])
        self.assertEqual(code, 2)
        self.assertIn("supported story format", error)
        self.assertFalse(self.output.exists())

    def test_machine_json_survives_ascii_only_host_pipes(self):
        source = deepcopy(STORY_SCHEMA["example"])
        source["title"] = "A title with Unicode: \u4e16\u754c"
        self.source.write_text(json.dumps(source), encoding="utf-8")
        output = self.root / "\u8f93\u51fa"
        env = {**os.environ, "PYTHONIOENCODING": "ascii:strict"}
        command = [sys.executable, "-m", "ste_promax", "render", str(self.source),
                   "--output-dir", str(output)]
        run = subprocess.run(command, capture_output=True, env=env, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr.decode("ascii", errors="replace"))
        manifest = json.loads(run.stdout.decode("ascii"))
        self.assertEqual(Path(manifest["files"]["html"]["path"]).parent, output)
        self.assertIn(source["title"], Path(manifest["files"]["html"]["path"]).read_text(encoding="utf-8"))
        run = subprocess.run([sys.executable, "-m", "ste_promax", "schema"],
                             capture_output=True, env=env, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr.decode("ascii", errors="replace"))
        self.assertIn("story", json.loads(run.stdout.decode("ascii")))


if __name__ == "__main__":
    unittest.main()
